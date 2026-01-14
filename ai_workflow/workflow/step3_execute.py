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
"""

import os
import threading
import time
from concurrent.futures import (
    CancelledError,
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ai_workflow.integrations.auggie import (
    AuggieClient,
    AuggieRateLimitError,
    _looks_like_rate_limit,
)
from ai_workflow.integrations.git import get_current_branch, is_dirty
from ai_workflow.ui.log_buffer import TaskLogBuffer
from ai_workflow.ui.prompts import prompt_confirm
from ai_workflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ai_workflow.utils.retry import (
    RateLimitExceededError,
    with_rate_limit_retry,
)
from ai_workflow.workflow.events import (
    TaskRunStatus,
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
    format_log_filename,
    format_run_directory,
)
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.task_memory import capture_task_memory
from ai_workflow.workflow.tasks import (
    Task,
    get_pending_fundamental_tasks,
    get_pending_independent_tasks,
    get_pending_tasks,
    mark_task_complete,
    parse_task_list,
)

if TYPE_CHECKING:
    from ai_workflow.ui.tui import TaskRunnerUI


# =============================================================================
# Log Directory Management
# =============================================================================

# Default log retention count
DEFAULT_LOG_RETENTION = 10


def _get_log_base_dir() -> Path:
    """Get the base directory for run logs.

    Returns:
        Path to the log base directory.
    """
    env_dir = os.environ.get("AI_WORKFLOW_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".ai_workflow/runs")


def _create_run_log_dir(ticket_id: str) -> Path:
    """Create a timestamped log directory for this run.

    Args:
        ticket_id: Ticket identifier for directory naming.

    Returns:
        Path to the created log directory.
    """
    base_dir = _get_log_base_dir()
    ticket_dir = base_dir / ticket_id
    run_dir = ticket_dir / format_run_directory()

    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _cleanup_old_runs(ticket_id: str, keep_count: int = DEFAULT_LOG_RETENTION) -> None:
    """Remove old run directories beyond retention limit.

    Args:
        ticket_id: Ticket identifier.
        keep_count: Number of runs to keep.
    """
    base_dir = _get_log_base_dir()
    ticket_dir = base_dir / ticket_id

    if not ticket_dir.exists():
        return

    # Get all run directories sorted by name (timestamp order)
    run_dirs = sorted(
        [d for d in ticket_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    # Remove directories beyond retention limit
    for old_dir in run_dirs[keep_count:]:
        try:
            import shutil
            shutil.rmtree(old_dir)
        except Exception:
            pass  # Ignore cleanup errors


def step_3_execute(
    state: WorkflowState,
    *,
    use_tui: bool | None = None,
    verbose: bool = False,
) -> bool:
    """Execute Step 3: Two-phase task execution.

    Phase 1: Sequential execution of fundamental tasks
    Phase 2: Parallel execution of independent tasks

    Supports two modes:
    - TUI mode: Rich interactive display with task list and log panels
    - Fallback mode: Simple line-based output for CI/non-TTY environments

    Args:
        state: Current workflow state
        use_tui: Override for TUI mode. None = auto-detect.
        verbose: Enable verbose mode in TUI (expanded log panel).

    Returns:
        True if all tasks completed successfully
    """
    print_header("Step 3: Execute Implementation")

    # Verify task list exists
    tasklist_path = state.get_tasklist_path()
    if not tasklist_path.exists():
        print_error(f"Task list not found: {tasklist_path}")
        return False

    # Parse all tasks
    tasks = parse_task_list(tasklist_path.read_text())

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

    # Setup
    plan_path = state.get_plan_path()
    log_dir = _create_run_log_dir(state.ticket.ticket_id)
    _cleanup_old_runs(state.ticket.ticket_id)

    failed_tasks: list[str] = []

    # Determine execution mode
    from ai_workflow.ui.tui import _should_use_tui

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
                verbose=verbose,
                phase="fundamental",
            )
        else:
            phase1_failed = _execute_fallback(
                state, pending_fundamental, plan_path, tasklist_path, log_dir
            )

        failed_tasks.extend(phase1_failed)

        # If fail_fast and we had failures, stop here
        if failed_tasks and state.fail_fast:
            print_error("Phase 1 failures with fail_fast enabled. Stopping.")
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
                verbose=verbose,
            )
        else:
            phase2_failed = _execute_parallel_fallback(
                state, pending_independent, plan_path, tasklist_path, log_dir
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
                verbose=verbose,
                phase="independent",
            )
        else:
            phase2_failed = _execute_fallback(
                state, pending_independent, plan_path, tasklist_path, log_dir
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
    _run_post_implementation_tests(state)
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
        verbose: Enable verbose mode (expanded log panel).
        phase: Phase identifier for logging ("fundamental", "independent", "sequential").

    Returns:
        List of failed task names
    """
    # Lazy import to avoid circular dependency
    from ai_workflow.ui.tui import TaskRunnerUI

    failed_tasks: list[str] = []
    user_quit: bool = False

    # Initialize TUI
    tui = TaskRunnerUI(ticket_id=state.ticket.ticket_id, verbose_mode=verbose)
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
            if tui.quit_requested:
                # Stop TUI temporarily to show prompt
                tui.stop()
                if prompt_confirm("Quit task execution?", default=False):
                    user_quit = True
                    tui.mark_remaining_skipped(i)
                    break
                else:
                    # User changed their mind, continue
                    tui.quit_requested = False
                    tui.start()

            record = tui.get_record(i)
            if not record:
                continue

            # Emit task started event
            start_event = create_task_started_event(i, task.name)
            tui.handle_event(start_event)

            # Execute task with retry wrapper (sequential mode, not parallel)
            success = _execute_task_with_retry(
                state, task, plan_path,
                callback=lambda line, idx=i, name=task.name: tui.handle_event(
                    create_task_output_event(idx, name, line)
                ),
                is_parallel=False,
            )

            # Check for quit request during task execution
            if tui.quit_requested:
                # Task finished naturally, check if user still wants to quit
                tui.stop()
                if prompt_confirm("Task completed. Quit execution?", default=False):
                    user_quit = True
                    # Emit task finished event first
                    duration = record.elapsed_time
                    status = "success" if success else "failed"
                    finish_event = create_task_finished_event(
                        i, task.name, status, duration,
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
                    tui.quit_requested = False
                    tui.start()

            # Emit task finished event
            duration = record.elapsed_time
            status = "success" if success else "failed"
            finish_event = create_task_finished_event(
                i, task.name, status, duration,
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
) -> list[str]:
    """Execute tasks with fallback (non-TUI) display.

    Args:
        state: Current workflow state
        pending: List of pending tasks
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files

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
                state, task, plan_path,
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
) -> list[str]:
    """Execute independent tasks in parallel (non-TUI mode) with rate limit handling.

    Uses ThreadPoolExecutor for concurrent AI agent execution.
    Each task runs in complete isolation with dont_save_session=True.
    Rate limit errors trigger exponential backoff retry.
    Implements fail_fast semantics with stop_flag for early termination.

    Args:
        state: Current workflow state
        tasks: List of independent tasks to execute
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files

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

        log_filename = format_log_filename(idx, task.name)
        log_path = log_dir / log_filename

        with TaskLogBuffer(log_path) as log_buffer:

            def output_callback(line: str) -> None:
                log_buffer.write(line)

            # Use retry-enabled execution with is_parallel=True
            success = _execute_task_with_retry(
                state,
                task,
                plan_path,
                callback=output_callback,
                is_parallel=True,
            )

        return task, success

    # Execute in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(execute_single_task, (i, task)): task
            for i, task in enumerate(tasks)
        }

        for future in as_completed(futures):
            try:
                task, success = future.result()
            except CancelledError:
                task = futures[future]
                skipped_tasks.append(task.name)
                print_info(f"[PARALLEL] Skipped (cancelled): {task.name}")
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
    verbose: bool = False,
) -> list[str]:
    """Execute independent tasks in parallel with TUI display and rate limit handling.

    Thread-safe design per PARALLEL-EXECUTION-REMEDIATION-SPEC:
    - Worker threads ONLY call tui.post_event() for TASK_STARTED and TASK_OUTPUT
    - Main thread pumps with wait(timeout=0.1) and calls tui.refresh() each loop
    - TASK_FINISHED events are emitted from main thread after future completes

    Args:
        state: Current workflow state
        tasks: List of independent tasks
        plan_path: Path to plan file
        tasklist_path: Path to task list file
        log_dir: Directory for log files
        verbose: Enable verbose mode

    Returns:
        List of failed task names
    """
    from ai_workflow.ui.tui import TaskRunnerUI

    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()
    max_workers = min(state.max_parallel_tasks, len(tasks))

    # Initialize TUI with all parallel tasks
    tui = TaskRunnerUI(ticket_id=state.ticket.ticket_id, verbose_mode=verbose)
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

        Returns:
            Tuple of (idx, task, success) - TASK_FINISHED is emitted by main thread.
        """
        idx, task = task_info

        # Early exit if stop flag set (fail-fast triggered by another task)
        if stop_flag.is_set():
            # Return special marker for skipped (success=None would be ideal but
            # we use a sentinel: raise a specific exception or return a tuple)
            # We'll handle this case in the main loop
            return idx, task, None  # type: ignore[return-value]

        # Post TASK_STARTED event to queue (thread-safe)
        start_event = create_task_started_event(idx, task.name)
        tui.post_event(start_event)

        try:
            # Execute with streaming callback via post_event (thread-safe)
            success = _execute_task_with_retry(
                state,
                task,
                plan_path,
                callback=lambda line, i=idx, n=task.name: tui.post_event(
                    create_task_output_event(i, n, line)
                ),
                is_parallel=True,
            )
            return idx, task, success
        except Exception as e:
            # Unexpected crash - post error output and return failure
            tui.post_event(create_task_output_event(idx, task.name, f"[ERROR] {e}"))
            return idx, task, False

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


def _build_task_prompt(task: Task, plan_path: Path, is_parallel: bool = False) -> str:
    """Build the prompt for task execution.

    Args:
        task: Task to execute
        plan_path: Path to the plan file
        is_parallel: Whether this task runs in parallel with others

    Returns:
        Prompt string for the AI
    """
    if plan_path.exists():
        base_prompt = f"""Execute this task.

Task: {task.name}

The implementation plan is at: {plan_path}
Use codebase-retrieval to read the plan and focus on the section relevant to this task.
Use codebase-retrieval to find existing patterns in the codebase."""
    else:
        base_prompt = f"""Execute this task.

Task: {task.name}

Use codebase-retrieval to find existing patterns in the codebase."""

    if is_parallel:
        base_prompt += """

IMPORTANT: This task runs in parallel with other tasks.
- Do NOT run `git add`, `git commit`, or `git push`
- Do NOT stage any changes
- Only make file modifications; staging/committing will be done after all tasks complete"""

    base_prompt += "\n\nDo NOT commit or push any changes."
    return base_prompt


def _execute_task(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
) -> bool:
    """Execute a single task in clean context (legacy mode).

    Optimistic execution model:
    - Trust AI exit codes
    - No file verification
    - No retry loops
    - Minimal prompt with instructions to retrieve context

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to the plan file (AI will retrieve content as needed)

    Returns:
        True if AI reported success
    """
    prompt = _build_task_prompt(task, plan_path)
    auggie_client = AuggieClient(model=state.implementation_model)

    try:
        success, _ = auggie_client.run_print_with_output(
            prompt,
            dont_save_session=True
        )
        if success:
            print_success(f"Task completed: {task.name}")
        else:
            print_warning(f"Task returned failure: {task.name}")
        return success
    except Exception as e:
        print_error(f"Task execution crashed: {e}")
        return False


def _execute_task_with_callback(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    *,
    callback: Callable[[str], None],
    is_parallel: bool = False,
) -> bool:
    """Execute a single task with streaming output callback.

    Uses AuggieClient.run_with_callback() for streaming output.
    Each output line is passed to the callback function.

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to the plan file
        callback: Function called for each output line
        is_parallel: Whether this task runs in parallel with others

    Returns:
        True if AI reported success

    Raises:
        AuggieRateLimitError: If the output indicates a rate limit error
    """
    prompt = _build_task_prompt(task, plan_path, is_parallel=is_parallel)
    auggie_client = AuggieClient(model=state.implementation_model)

    try:
        success, output = auggie_client.run_with_callback(
            prompt,
            output_callback=callback,
            dont_save_session=True,
        )
        if not success and _looks_like_rate_limit(output):
            raise AuggieRateLimitError("Rate limit detected", output=output)
        return success
    except AuggieRateLimitError:
        raise  # Let retry decorator handle
    except Exception as e:
        callback(f"[ERROR] Task execution crashed: {e}")
        return False


def _execute_task_with_retry(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
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
        callback: Output callback for streaming
        is_parallel: Whether this task runs in parallel with others

    Returns:
        True if task succeeded, False otherwise
    """
    config = state.rate_limit_config

    # Skip retry wrapper if retries disabled
    if config.max_retries <= 0:
        if callback:
            return _execute_task_with_callback(
                state, task, plan_path, callback=callback, is_parallel=is_parallel
            )
        else:
            return _execute_task(state, task, plan_path)

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
                state, task, plan_path, callback=callback, is_parallel=is_parallel
            )
        else:
            return _execute_task(state, task, plan_path)

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

    console.print(f"[bold]Ticket:[/bold] {state.ticket.ticket_id}")
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


def _run_post_implementation_tests(state: WorkflowState) -> None:
    """Run post-implementation verification tests using AI.

    Finds and runs tests that cover the code changed in this Step 3 run.
    This includes both modified test files AND tests that cover modified source files.
    Does NOT run the full project test suite.
    """
    # Prompt user to run tests
    if not prompt_confirm("Run tests for changes made in this run?", default=True):
        print_info("Skipping tests")
        return

    print_step("Running Tests for Changed Code via AI")
    console.print("[dim]AI will identify and run tests that cover the code changed in this run...[/dim]")
    console.print()

    prompt = """Identify and run the tests that are relevant to the code changes made in this run.

## Step 1: Identify Changed Production Code
- Run `git diff --name-only` and `git status --porcelain` to list all files changed in this run.
- Separate the changed files into two categories:
  a) **Test files**: files in directories like `test/`, `tests/`, `__tests__/`, or matching patterns like `*.spec.*`, `*_test.*`, `test_*.*`
  b) **Production/source files**: all other changed files (excluding test paths above)

## Step 2: Determine Relevant Tests to Run
Find the minimal, most targeted set of tests that cover the changes:
- **If test files were modified/added**: include those tests.
- **If production/source files were modified/added**: use codebase-retrieval and repository conventions to find tests that cover those files. Look for:
  - Tests located in the same module/package area as the changed source files
  - Tests named similarly to the changed files (e.g., `foo.py` → `test_foo.py`, `foo_test.py`, `foo.spec.ts`)
  - Tests referenced by existing docs, scripts, or test configuration in the repo
- Prefer the smallest targeted set. If the repo supports running tests by file, class, or package, use that to scope execution.

## Step 3: Transparency Before Execution
Before running any tests:
- Print the exact command(s) you plan to run.
- Briefly explain how these tests were selected (e.g., "These tests correspond to module X which was changed" or "These are the modified test files").

## Step 4: Execute Tests
Run the identified tests and clearly report success or failure.

## Critical Constraints
- Do NOT commit any changes
- Do NOT push any changes
- Do NOT run the entire project test suite by default
- Only expand the test scope if a targeted run is not possible in this repo

## Fallback Behavior
If you cannot reliably map changed source files to specific tests AND cannot run targeted tests in this repo:
1. Explain why targeted test selection is not possible.
2. Propose 1-2 broader-but-still-reasonable commands (e.g., module-level tests, package-level tests).
3. Ask the user for confirmation before running them.
4. Do NOT silently fall back to "run everything".

If NO production files were changed AND NO test files were changed, report "No code changes detected that require testing" and STOP."""

    auggie_client = AuggieClient(model=state.implementation_model)

    try:
        success, _ = auggie_client.run_print_with_output(
            prompt,
            dont_save_session=True
        )
        console.print()
        if success:
            print_success("Test execution completed successfully")
        else:
            print_warning("Test execution reported issues")
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
    commit_msg = f"feat({state.ticket.ticket_id}): implement {task_count} tasks"

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
]

