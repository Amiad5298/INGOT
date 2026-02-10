"""Step 3: Execute Implementation - Two-Phase Execution Model.

This module implements the third step of the workflow - executing
the task list with a two-phase execution model:

Phase 1: Sequential execution of fundamental tasks (dependencies, order matters)
Phase 2: Parallel execution of independent tasks (can run concurrently)

Philosophy: Trust the AI. If it returns success, it succeeded.
Don't nanny it with file checks and retry loops.

Each task runs in its own clean context (using dont_save_session=True)
to maintain focus and avoid context pollution.

Supports two display modes:
- TUI mode: Rich interactive display with task list and log panels
- Fallback mode: Simple line-based output for CI/non-TTY environments

Helper modules:
- git_utils: Git diff collection and parsing
- review: Code review prompting and status parsing
- autofix: Auto-fix logic for review feedback
- log_management: Run log directory management
- prompts: Task execution prompt templates
"""

import threading
from collections.abc import Callable
from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from pathlib import Path
from typing import Literal

from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import BackendRateLimitError
from ingot.integrations.backends.factory import BackendFactory
from ingot.integrations.git import get_current_branch, is_dirty
from ingot.ui.log_buffer import TaskLogBuffer
from ingot.ui.prompts import prompt_confirm
from ingot.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ingot.utils.retry import (
    RateLimitExceededError,
    with_rate_limit_retry,
)
from ingot.workflow.events import (
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
    format_log_filename,
)
from ingot.workflow.git_utils import (
    DirtyWorkingTreeError,
    capture_baseline,
    check_dirty_working_tree,
)
from ingot.workflow.log_management import (
    cleanup_old_runs as _cleanup_old_runs,
)
from ingot.workflow.log_management import (
    create_run_log_dir as _create_run_log_dir,
)
from ingot.workflow.log_management import (
    get_log_base_dir as _get_log_base_dir,
)
from ingot.workflow.prompts import (
    POST_IMPLEMENTATION_TEST_PROMPT,
)
from ingot.workflow.prompts import (
    build_task_prompt as _build_task_prompt,
)
from ingot.workflow.review import run_phase_review as _run_phase_review
from ingot.workflow.state import WorkflowState
from ingot.workflow.task_memory import capture_task_memory
from ingot.workflow.tasks import (
    Task,
    get_pending_fundamental_tasks,
    get_pending_independent_tasks,
    get_pending_tasks,
    mark_task_complete,
    parse_task_list,
)

# Type alias for task status
TaskStatus = Literal["success", "failed", "skipped"]

# Log directory names for workflow steps
LOG_DIR_TEST_EXECUTION = "test_execution"


def _capture_baseline_for_diffs(state: WorkflowState) -> bool:
    """Capture baseline ref and check for dirty working tree.

    This must be called at the start of Step 3 before any modifications.
    It captures the current HEAD as the baseline for all subsequent diff
    operations, ensuring diffs are scoped to changes introduced by this
    workflow run.

    The dirty tree policy is read from state.dirty_tree_policy:
    - FAIL_FAST: Abort if working tree is dirty (default, recommended)
    - WARN_AND_CONTINUE: Warn but continue (diffs may include unrelated changes)

    Args:
        state: Current workflow state (will be updated with baseline ref)

    Returns:
        True if baseline was captured successfully, False if there was
        a dirty working tree that prevents safe operation (only with FAIL_FAST).
    """
    # Check for dirty working tree before capturing baseline
    try:
        is_clean = check_dirty_working_tree(policy=state.dirty_tree_policy)
        if not is_clean:
            # WARN_AND_CONTINUE policy - tree is dirty but we continue
            print_warning(
                "Continuing with dirty working tree. "
                "Review diffs may include pre-existing changes."
            )
    except DirtyWorkingTreeError as e:
        # FAIL_FAST policy - abort on dirty tree
        print_error(str(e))
        return False

    # Capture baseline ref
    try:
        baseline_ref = capture_baseline()
        state.diff_baseline_ref = baseline_ref
        print_info(f"Captured baseline for diff operations: {baseline_ref[:8]}")
        return True
    except Exception as e:
        print_error(f"Failed to capture git baseline: {e}")
        return False


def step_3_execute(
    state: WorkflowState,
    *,
    backend: AIBackend,
    use_tui: bool | None = None,
    verbose: bool = False,
) -> bool:
    """Execute Step 3: Two-phase task execution.

    Phase 1: Sequential execution of fundamental tasks
    Phase 2: Parallel execution of independent tasks

    Supports two modes:
    - TUI mode: Rich interactive display with task list and log panels
    - Fallback mode: Simple line-based output for CI/non-TTY environments

    Before execution begins, captures a baseline git ref to ensure all
    subsequent diff operations are scoped to changes introduced by this
    workflow run. Fails fast if the working tree has uncommitted changes.

    Args:
        state: Current workflow state
        backend: AI backend instance for agent interactions
        use_tui: Override for TUI mode. None = auto-detect.
        verbose: Enable verbose mode in TUI (expanded log panel).

    Returns:
        True if all tasks completed successfully
    """
    print_header("Step 3: Execute Implementation")

    # Capture baseline and check for dirty working tree
    # This MUST happen before any modifications begin
    if not _capture_baseline_for_diffs(state):
        print_error("Cannot proceed with dirty working tree.")
        print_info("Please commit or stash uncommitted changes first.")
        return False

    # Verify task list exists
    tasklist_path = state.get_tasklist_path()
    if not tasklist_path.exists():
        print_error(f"Task list not found: {tasklist_path}")
        return False

    # Parse all tasks
    tasks = parse_task_list(tasklist_path.read_text())

    # Disable parallel execution if backend doesn't support it
    if not backend.supports_parallel:
        state.parallel_execution_enabled = False

    # Separate into phases
    pending_fundamental = get_pending_fundamental_tasks(tasks)
    pending_independent = get_pending_independent_tasks(tasks)

    # Handle legacy task lists (no categorization = all fundamental)
    if not pending_fundamental and not pending_independent:
        # Legacy mode: treat all as fundamental
        pending_fundamental = get_pending_tasks(tasks)
        pending_independent = []

    total_pending = len(pending_fundamental) + len(pending_independent)
    if total_pending == 0:
        print_success("All tasks already completed!")
        return True

    print_info(
        f"Found {len(pending_fundamental)} fundamental + "
        f"{len(pending_independent)} independent tasks"
    )

    # Setup (use safe_filename_stem for filesystem operations)
    plan_path = state.get_plan_path()
    log_dir = _create_run_log_dir(state.ticket.safe_filename_stem)
    _cleanup_old_runs(state.ticket.safe_filename_stem)

    failed_tasks: list[str] = []

    # Determine execution mode
    from ingot.ui.tui import _should_use_tui

    use_tui_mode = _should_use_tui(use_tui)

    # PHASE 1: Execute fundamental tasks sequentially
    if pending_fundamental:
        print_header("Phase 1: Fundamental Tasks (Sequential)")

        if use_tui_mode:
            phase1_failed = _execute_with_tui(
                state,
                pending_fundamental,
                plan_path,
                tasklist_path,
                log_dir,
                backend=backend,
                verbose=verbose,
                phase="fundamental",
            )
        else:
            phase1_failed = _execute_fallback(
                state, pending_fundamental, plan_path, tasklist_path, log_dir, backend=backend
            )

        failed_tasks.extend(phase1_failed)

        # If fail_fast and we had failures, stop here
        if failed_tasks and state.fail_fast:
            print_error("Phase 1 failures with fail_fast enabled. Stopping.")
            return False

    # PHASE 1 REVIEW CHECKPOINT
    # Run after TUI context manager has exited to avoid display corruption
    if pending_fundamental and state.enable_phase_review and not failed_tasks:
        review_passed = _run_phase_review(state, log_dir, phase="fundamental", backend=backend)
        if not review_passed:
            # User explicitly chose to stop
            print_info("Stopping after Phase 1 review.")
            return False

    # PHASE 2: Execute independent tasks in parallel
    if pending_independent and state.parallel_execution_enabled:
        print_header("Phase 2: Independent Tasks (Parallel)")

        if use_tui_mode:
            phase2_failed = _execute_parallel_with_tui(
                state,
                pending_independent,
                plan_path,
                tasklist_path,
                log_dir,
                backend=backend,
                verbose=verbose,
            )
        else:
            phase2_failed = _execute_parallel_fallback(
                state, pending_independent, plan_path, tasklist_path, log_dir, backend=backend
            )

        failed_tasks.extend(phase2_failed)
    elif pending_independent:
        # Parallel disabled, run sequentially
        print_info("Parallel execution disabled. Running independent tasks sequentially.")
        if use_tui_mode:
            phase2_failed = _execute_with_tui(
                state,
                pending_independent,
                plan_path,
                tasklist_path,
                log_dir,
                backend=backend,
                verbose=verbose,
                phase="independent",
            )
        else:
            phase2_failed = _execute_fallback(
                state, pending_independent, plan_path, tasklist_path, log_dir, backend=backend
            )
        failed_tasks.extend(phase2_failed)

    # Handle failures
    if failed_tasks:
        if not prompt_confirm(
            "Some tasks failed. Proceed to post-implementation steps?",
            default=True,
        ):
            print_info("Exiting Step 3 early due to task failures.")
            return False

    # Post-execution steps
    _show_summary(state, failed_tasks)
    _run_post_implementation_tests(state, backend)

    # FINAL REVIEW CHECKPOINT
    # Run after tests but before commit instructions
    if state.enable_phase_review:
        review_passed = _run_phase_review(state, log_dir, phase="final", backend=backend)
        if not review_passed:
            # User explicitly chose to stop
            print_warning(
                "Workflow stopped after final review. Please address issues before committing."
            )
            return False

    _offer_commit_instructions(state)
    print_info(f"Task logs saved to: {log_dir}")

    return len(failed_tasks) == 0


def _execute_with_tui(
    state: WorkflowState,
    pending: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    backend: AIBackend,
    verbose: bool = False,
    phase: str = "sequential",
) -> list[str]:
    """Execute tasks with TUI display (sequential mode).

    Args:
        state: Current workflow state
        pending: List of pending tasks
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files
        backend: AI backend instance for agent interactions
        verbose: Enable verbose mode (expanded log panel).
        phase: Phase identifier for logging ("fundamental", "independent", "sequential").

    Returns:
        List of failed task names
    """
    # Lazy import to avoid circular dependency
    from ingot.ui.tui import TaskRunnerUI

    failed_tasks: list[str] = []
    user_quit: bool = False

    # Initialize TUI
    tui = TaskRunnerUI(ticket_id=state.ticket.id, verbose_mode=verbose)
    tui.initialize_records([t.name for t in pending])
    tui.set_log_dir(log_dir)

    # Create log buffers for each task
    for i, task in enumerate(pending):
        log_filename = format_log_filename(i, task.name)
        log_path = log_dir / log_filename
        record = tui.get_record(i)
        if record:
            record.log_buffer = TaskLogBuffer(log_path)

    with tui:
        for i, task in enumerate(pending):
            # Check for quit request before starting next task
            if tui.check_quit_requested():
                # Stop TUI temporarily to show prompt
                tui.stop()
                if prompt_confirm("Quit task execution?", default=False):
                    user_quit = True
                    tui.mark_remaining_skipped(i)
                    break
                else:
                    # User changed their mind, continue
                    tui.clear_quit_request()
                    tui.start()

            record = tui.get_record(i)
            if not record:
                continue

            # Emit task started event
            start_event = create_task_started_event(i, task.name)
            tui.handle_event(start_event)

            # Execute task with retry wrapper (sequential mode, not parallel)
            def make_callback(idx: int, name: str) -> Callable[[str], None]:
                def cb(line: str) -> None:
                    tui.handle_event(create_task_output_event(idx, name, line))

                return cb

            success = _execute_task_with_retry(
                state,
                task,
                plan_path,
                backend=backend,
                callback=make_callback(i, task.name),
                is_parallel=False,
            )

            # Check for quit request during task execution
            if tui.check_quit_requested():
                # Task finished naturally, check if user still wants to quit
                tui.stop()
                if prompt_confirm("Task completed. Quit execution?", default=False):
                    user_quit = True
                    # Emit task finished event first
                    duration = record.elapsed_time
                    status: TaskStatus = "success" if success else "failed"
                    finish_event = create_task_finished_event(
                        i,
                        task.name,
                        status,
                        duration,
                        error=None if success else "Task returned failure",
                    )
                    tui.handle_event(finish_event)
                    if success:
                        mark_task_complete(tasklist_path, task.name)
                        state.mark_task_complete(task.name)
                    else:
                        failed_tasks.append(task.name)
                    tui.mark_remaining_skipped(i + 1)
                    break
                else:
                    tui.clear_quit_request()
                    tui.start()

            # Emit task finished event
            duration = record.elapsed_time
            task_status: TaskStatus = "success" if success else "failed"
            finish_event = create_task_finished_event(
                i,
                task.name,
                task_status,
                duration,
                error=None if success else "Task returned failure",
            )
            tui.handle_event(finish_event)

            if success:
                mark_task_complete(tasklist_path, task.name)
                state.mark_task_complete(task.name)
                try:
                    capture_task_memory(task, state)
                except Exception as e:
                    # Log to buffer, don't print
                    if record.log_buffer:
                        record.log_buffer.write(f"[WARNING] Failed to capture task memory: {e}")
            else:
                failed_tasks.append(task.name)
                if state.fail_fast:
                    tui.mark_remaining_skipped(i + 1)
                    break

    tui.print_summary()
    if user_quit:
        print_info("Execution stopped by user request.")
    return failed_tasks


def _execute_fallback(
    state: WorkflowState,
    pending: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    backend: AIBackend,
) -> list[str]:
    """Execute tasks with fallback (non-TUI) display.

    Args:
        state: Current workflow state
        pending: List of pending tasks
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files
        backend: AI backend instance for agent interactions

    Returns:
        List of failed task names
    """
    failed_tasks: list[str] = []

    for i, task in enumerate(pending):
        print_step(f"[{i + 1}/{len(pending)}] {task.name}")

        # Create log buffer for this task
        log_filename = format_log_filename(i, task.name)
        log_path = log_dir / log_filename

        with TaskLogBuffer(log_path) as log_buffer:
            # Callback that writes to log and prints to stdout
            def output_callback(line: str) -> None:
                log_buffer.write(line)
                console.print(line)

            # Execute with retry wrapper (sequential mode, not parallel)
            success = _execute_task_with_retry(
                state,
                task,
                plan_path,
                backend=backend,
                callback=output_callback,
                is_parallel=False,
            )

        if success:
            mark_task_complete(tasklist_path, task.name)
            state.mark_task_complete(task.name)
            print_success(f"Task completed: {task.name}")
            try:
                capture_task_memory(task, state)
            except Exception as e:
                print_warning(f"Failed to capture task memory (analytics): {e}")
        else:
            failed_tasks.append(task.name)
            print_warning(f"Task returned failure: {task.name}")
            if state.fail_fast:
                print_error("Stopping: fail_fast enabled")
                break

    return failed_tasks


def _execute_parallel_fallback(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    backend: AIBackend,
) -> list[str]:
    """Execute independent tasks in parallel (non-TUI mode) with rate limit handling.

    Uses ThreadPoolExecutor for concurrent AI agent execution.
    Each task runs in complete isolation with dont_save_session=True.
    Each worker creates a fresh backend instance via BackendFactory.
    Rate limit errors trigger exponential backoff retry.
    Implements fail_fast semantics with stop_flag for early termination.

    Args:
        state: Current workflow state
        tasks: List of independent tasks to execute
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files
        backend: AI backend instance (platform used to create per-worker backends)

    Returns:
        List of failed task names
    """
    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()
    max_workers = min(state.max_parallel_tasks, len(tasks))

    print_info(f"Executing {len(tasks)} tasks with {max_workers} parallel workers")
    print_info(f"Rate limit retry: max {state.rate_limit_config.max_retries} retries")

    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool | None]:
        """Execute a single task with retry handling (runs in thread).

        Each worker creates its own fresh backend instance for thread safety.

        Returns:
            Tuple of (task, success) where success is:
            - True if task succeeded
            - False if task failed
            - None if task was skipped (due to stop_flag)
        """
        idx, task = task_info

        # Check stop flag before starting
        if stop_flag.is_set():
            return task, None  # Skipped

        # Create a fresh backend for this worker thread, forwarding the model
        worker_backend = BackendFactory.create(backend.platform, model=backend.model)

        log_filename = format_log_filename(idx, task.name)
        log_path = log_dir / log_filename

        try:
            with TaskLogBuffer(log_path) as log_buffer:

                def output_callback(line: str) -> None:
                    log_buffer.write(line)

                # Use retry-enabled execution with is_parallel=True
                success = _execute_task_with_retry(
                    state,
                    task,
                    plan_path,
                    backend=worker_backend,
                    callback=output_callback,
                    is_parallel=True,
                )

            return task, success
        finally:
            worker_backend.close()

    # Execute in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(execute_single_task, (i, task)): task for i, task in enumerate(tasks)
        }

        for future in as_completed(futures):
            try:
                task, success = future.result()
            except CancelledError:
                task = futures[future]
                skipped_tasks.append(task.name)
                print_info(f"[PARALLEL] Skipped (cancelled): {task.name}")
                continue
            except Exception as e:
                task = futures[future]
                failed_tasks.append(task.name)
                print_error(f"[PARALLEL] Crashed: {task.name}: {e}")
                if state.fail_fast:
                    stop_flag.set()
                    for f in futures:
                        f.cancel()
                continue

            if success is None:
                # Task was skipped due to stop_flag
                skipped_tasks.append(task.name)
                print_info(f"[PARALLEL] Skipped: {task.name}")
            elif success:
                mark_task_complete(tasklist_path, task.name)
                state.mark_task_complete(task.name)
                print_success(f"[PARALLEL] Completed: {task.name}")
                # Memory capture disabled for parallel tasks (contamination risk)
            else:
                failed_tasks.append(task.name)
                print_warning(f"[PARALLEL] Failed: {task.name}")
                # Trigger fail-fast if enabled
                if state.fail_fast:
                    stop_flag.set()
                    # Cancel pending futures
                    for f in futures:
                        f.cancel()

    return failed_tasks


def _execute_parallel_with_tui(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    backend: AIBackend,
    verbose: bool = False,
) -> list[str]:
    """Execute independent tasks in parallel with TUI display and rate limit handling.

    Thread-safe design per PARALLEL-EXECUTION-REMEDIATION-SPEC:
    - Worker threads ONLY call tui.post_event() for TASK_STARTED and TASK_OUTPUT
    - Main thread pumps with wait(timeout=0.1) and calls tui.refresh() each loop
    - TASK_FINISHED events are emitted from main thread after future completes
    - Each worker creates a fresh backend instance via BackendFactory

    Args:
        state: Current workflow state
        tasks: List of independent tasks
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files
        backend: AI backend instance (platform used to create per-worker backends)
        verbose: Enable verbose mode

    Returns:
        List of failed task names
    """
    from ingot.ui.tui import TaskRunnerUI

    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()
    max_workers = min(state.max_parallel_tasks, len(tasks))

    # Initialize TUI with all parallel tasks
    tui = TaskRunnerUI(ticket_id=state.ticket.id, verbose_mode=verbose)
    tui.initialize_records([t.name for t in tasks])
    tui.set_log_dir(log_dir)
    tui.set_parallel_mode(True)  # Enable parallel mode display

    # Create log buffers for each task
    for i, task in enumerate(tasks):
        log_filename = format_log_filename(i, task.name)
        log_path = log_dir / log_filename
        record = tui.get_record(i)
        if record:
            record.log_buffer = TaskLogBuffer(log_path)

    def execute_single_task_worker(task_info: tuple[int, Task]) -> tuple[int, Task, bool]:
        """Worker thread: execute task, post TASK_STARTED/TASK_OUTPUT via post_event.

        Each worker creates its own fresh backend instance for thread safety.

        Returns:
            Tuple of (idx, task, success) - TASK_FINISHED is emitted by main thread.
        """
        idx, task = task_info

        # Early exit if stop flag set (fail-fast triggered by another task)
        if stop_flag.is_set():
            return idx, task, None  # type: ignore[return-value]

        # Create a fresh backend for this worker thread, forwarding the model
        worker_backend = BackendFactory.create(backend.platform, model=backend.model)

        # Post TASK_STARTED event to queue (thread-safe)
        start_event = create_task_started_event(idx, task.name)
        tui.post_event(start_event)

        try:
            # Execute with streaming callback via post_event (thread-safe)
            def make_parallel_callback(i: int, n: str) -> Callable[[str], None]:
                def cb(line: str) -> None:
                    tui.post_event(create_task_output_event(i, n, line))

                return cb

            success = _execute_task_with_retry(
                state,
                task,
                plan_path,
                backend=worker_backend,
                callback=make_parallel_callback(idx, task.name),
                is_parallel=True,
            )
            return idx, task, success
        except Exception as e:
            # Unexpected crash - post error output and return failure
            tui.post_event(create_task_output_event(idx, task.name, f"[ERROR] {e}"))
            return idx, task, False
        finally:
            worker_backend.close()

    with tui:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(execute_single_task_worker, (i, task)): (i, task)
                for i, task in enumerate(tasks)
            }
            pending = set(futures.keys())

            # Main thread: pump events while waiting for futures
            while pending:
                # Wait with timeout so we can refresh TUI periodically
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)

                # Drain event queue and refresh TUI display
                tui.refresh()

                # Process completed futures
                for future in done:
                    idx, task = futures[future]
                    record = tui.get_record(idx)
                    duration = record.elapsed_time if record else 0.0

                    status: TaskStatus
                    error: str | None
                    try:
                        result_idx, result_task, success = future.result()

                        # Handle skipped tasks (stop_flag was set before execution)
                        if success is None:
                            status = "skipped"
                            error = None
                        elif success:
                            status = "success"
                            error = None
                        else:
                            status = "failed"
                            error = "Task returned failure"

                    except CancelledError:
                        status = "skipped"
                        error = None

                    # Emit TASK_FINISHED from main thread (thread-safe log buffer close)
                    finish_event = create_task_finished_event(
                        idx, task.name, status, duration, error=error
                    )
                    tui.handle_event(finish_event)

                    # Update state based on status
                    if status == "success":
                        mark_task_complete(tasklist_path, task.name)
                        state.mark_task_complete(task.name)
                        # Memory capture disabled for parallel tasks (contamination risk)
                    elif status == "skipped":
                        skipped_tasks.append(task.name)
                    else:  # failed
                        failed_tasks.append(task.name)
                        # Trigger fail-fast if enabled
                        if state.fail_fast:
                            stop_flag.set()
                            # Cancel pending futures
                            for f in pending:
                                f.cancel()

            # Final refresh to ensure all events are processed
            tui.refresh()

    tui.print_summary()
    return failed_tasks


def _execute_task(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    backend: AIBackend,
) -> bool:
    """Execute a single task using the ingot-implementer agent.

    Optimistic execution model:
    - Trust AI exit codes
    - No file verification
    - No retry loops
    - Minimal prompt - agent has full instructions

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to the plan file
        backend: AI backend instance for agent interactions

    Returns:
        True if AI reported success
    """
    # Build minimal prompt - pass plan path reference, not full content
    # The agent uses codebase-retrieval to read relevant sections
    prompt = _build_task_prompt(task, plan_path, is_parallel=False, user_context=state.user_context)

    try:
        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["implementer"],
            output_callback=lambda _line: None,
            dont_save_session=True,
        )
        if not success and backend.detect_rate_limit(output):
            raise BackendRateLimitError(
                "Rate limit detected", output=output, backend_name=backend.name
            )
        if success:
            print_success(f"Task completed: {task.name}")
        else:
            print_warning(f"Task returned failure: {task.name}")
        return success
    except BackendRateLimitError:
        raise  # Let retry decorator handle
    except Exception as e:
        print_error(f"Task execution crashed: {e}")
        return False


def _execute_task_with_callback(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    *,
    backend: AIBackend,
    callback: Callable[[str], None],
    is_parallel: bool = False,
) -> bool:
    """Execute a single task with streaming output callback using ingot-implementer agent.

    Uses backend.run_with_callback() for streaming output.
    Each output line is passed to the callback function.

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to the plan file
        backend: AI backend instance for agent interactions
        callback: Function called for each output line
        is_parallel: Whether this task runs in parallel with others

    Returns:
        True if AI reported success

    Raises:
        BackendRateLimitError: If the output indicates a rate limit error
    """
    # Build minimal prompt - pass plan path reference, not full content
    # The agent uses codebase-retrieval to read relevant sections
    prompt = _build_task_prompt(
        task, plan_path, is_parallel=is_parallel, user_context=state.user_context
    )

    try:
        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["implementer"],
            output_callback=callback,
            dont_save_session=True,
        )
        if not success and backend.detect_rate_limit(output):
            raise BackendRateLimitError(
                "Rate limit detected", output=output, backend_name=backend.name
            )
        return success
    except BackendRateLimitError:
        raise  # Let retry decorator handle
    except Exception as e:
        callback(f"[ERROR] Task execution crashed: {e}")
        return False


def _execute_task_with_retry(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    *,
    backend: AIBackend,
    callback: Callable[[str], None] | None = None,
    is_parallel: bool = False,
) -> bool:
    """Execute a task with rate limit retry handling.

    Wraps the core execution with exponential backoff retry logic
    to handle API rate limits during parallel execution.

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to plan file
        backend: AI backend instance for agent interactions
        callback: Output callback for streaming
        is_parallel: Whether this task runs in parallel with others

    Returns:
        True if task succeeded, False otherwise
    """
    config = state.rate_limit_config

    # Skip retry wrapper if retries disabled
    if config.max_retries <= 0:
        try:
            if callback:
                return _execute_task_with_callback(
                    state,
                    task,
                    plan_path,
                    backend=backend,
                    callback=callback,
                    is_parallel=is_parallel,
                )
            else:
                return _execute_task(state, task, plan_path, backend)
        except BackendRateLimitError:
            # No retries available — treat as failure
            error_msg = "[FAILED] Rate limit detected but retries are disabled"
            if callback:
                callback(error_msg)
            print_warning(error_msg)
            return False

    def log_retry(attempt: int, delay: float, error: Exception) -> None:
        """Log retry attempts."""
        message = f"[RETRY {attempt}/{config.max_retries}] Rate limited. Waiting {delay:.1f}s..."
        if callback:
            callback(message)
        print_warning(message)

    @with_rate_limit_retry(config, on_retry=log_retry)
    def execute_with_retry() -> bool:
        if callback:
            return _execute_task_with_callback(
                state, task, plan_path, backend=backend, callback=callback, is_parallel=is_parallel
            )
        else:
            return _execute_task(state, task, plan_path, backend)

    try:
        return execute_with_retry()
    except RateLimitExceededError as e:
        error_msg = f"[FAILED] Task exhausted all retries: {e}"
        if callback:
            callback(error_msg)
        print_error(error_msg)
        return False


def _show_summary(state: WorkflowState, failed_tasks: list[str] | None = None) -> None:
    """Show execution summary.

    Args:
        state: Current workflow state
        failed_tasks: Optional list of task names that failed
    """
    console.print()
    print_header("Execution Summary")

    console.print(f"[bold]Ticket:[/bold] {state.ticket.id}")
    console.print(f"[bold]Branch:[/bold] {state.branch_name or get_current_branch()}")
    console.print(f"[bold]Tasks completed:[/bold] {len(state.completed_tasks)}")
    console.print(f"[bold]Checkpoints:[/bold] {len(state.checkpoint_commits)}")

    if failed_tasks:
        console.print(f"[bold]Tasks with issues:[/bold] {len(failed_tasks)}")

    if state.completed_tasks:
        console.print()
        console.print("[bold]Completed tasks:[/bold]")
        for task in state.completed_tasks:
            console.print(f"  [green]✓[/green] {task}")

    if failed_tasks:
        console.print()
        console.print("[bold]Tasks with issues:[/bold]")
        for task in failed_tasks:
            console.print(f"  [yellow]![/yellow] {task}")

    console.print()

    # Add helpful note about git staging
    console.print(
        "[dim]Note: Generated files may appear as 'Unversioned' (if new) or "
        "'Modified' (if existing).[/dim]"
    )
    console.print(
        "[dim]      You need to manually review and [bold]git add[/bold] them "
        "before committing.[/dim]"
    )
    console.print()


def _run_post_implementation_tests(state: WorkflowState, backend: AIBackend) -> None:
    """Run post-implementation verification tests using AI.

    Finds and runs tests that cover the code changed in this Step 3 run.
    This includes both modified test files AND tests that cover modified source files.
    Does NOT run the full project test suite.

    Uses TaskRunnerUI in single-operation mode to provide a consistent
    collapsible UI with verbose toggle, matching the UX of Steps 1 and 3.

    Args:
        state: Current workflow state
        backend: AI backend instance for agent interactions
    """
    from ingot.ui.tui import TaskRunnerUI
    from ingot.workflow.events import format_run_directory

    # Prompt user to run tests
    if not prompt_confirm("Run tests for changes made in this run?", default=True):
        print_info("Skipping tests")
        return

    print_step("Running Tests for Changed Code via AI")

    # Create log directory for test execution (use safe_filename_stem for paths)
    log_dir = _get_log_base_dir() / state.ticket.safe_filename_stem / LOG_DIR_TEST_EXECUTION
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{format_run_directory()}.log"

    # Create UI with collapsible panel and verbose toggle (single-operation mode)
    ui = TaskRunnerUI(
        status_message="Running tests for changed code...",
        ticket_id=state.ticket.id,  # Keep original ID for display
        single_operation_mode=True,
    )
    ui.set_log_path(log_path)

    try:
        with ui:
            success, _ = backend.run_with_callback(
                POST_IMPLEMENTATION_TEST_PROMPT,
                subagent=state.subagent_names["implementer"],
                output_callback=ui.handle_output_line,
                dont_save_session=True,
            )

            # Check if user requested quit
            if ui.check_quit_requested():
                print_warning("Test execution cancelled by user.")
                return

        ui.print_summary(success)

        if not success:
            print_info("Review test output above to identify issues")
    except Exception as e:
        print_error(f"Failed to run tests: {e}")


def _offer_commit_instructions(state: WorkflowState) -> None:
    """Offer commit instructions to the user if there are uncommitted changes.

    Does NOT execute any git commands. Only prints suggested commands
    for the user to run manually.

    Args:
        state: Current workflow state
    """
    if not is_dirty():
        return

    console.print()
    if not prompt_confirm("Would you like instructions to commit these changes?", default=True):
        return

    # Generate suggested commit message
    task_count = len(state.completed_tasks)
    commit_msg = f"feat({state.ticket.id}): implement {task_count} tasks"

    console.print()
    print_header("Suggested Commit Steps")
    console.print()
    console.print("Run the following commands to commit your changes:")
    console.print()
    console.print("[bold cyan]  git status[/bold cyan]")
    console.print("[bold cyan]  git add -A[/bold cyan]")
    console.print(f'[bold cyan]  git commit -m "{commit_msg}"[/bold cyan]')
    console.print()
    print_info("Review 'git status' output before adding files.")
    console.print()


__all__ = [
    "step_3_execute",
    "LOG_DIR_TEST_EXECUTION",
]
