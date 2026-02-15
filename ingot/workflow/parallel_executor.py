"""Parallel task execution for the workflow.

Extracted from step3_execute.py to reduce module size.
Contains parallel execution logic for both TUI and fallback modes.
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
from ingot.integrations.backends.factory import BackendFactory
from ingot.ui.log_buffer import TaskLogBuffer
from ingot.utils.console import (
    print_error,
    print_info,
    print_success,
    print_warning,
)
from ingot.workflow.events import (
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
    format_log_filename,
)
from ingot.workflow.state import WorkflowState
from ingot.workflow.tasks import (
    Task,
    mark_task_complete,
)

# Type alias for task status
TaskStatus = Literal["success", "failed", "skipped"]

# Type alias for the retry-enabled execution callable
ExecuteWithRetryFn = Callable[
    ...,  # WorkflowState, Task, Path, *, backend, callback, is_parallel
    bool,
]


def _execute_parallel_fallback(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    backend: AIBackend,
    execute_task_with_retry: ExecuteWithRetryFn,
) -> list[str]:
    """Execute independent tasks in parallel (non-TUI mode) with rate limit handling.

    Uses ThreadPoolExecutor for concurrent AI agent execution.
    Each task runs in complete isolation with dont_save_session=True.
    Each worker creates a fresh backend instance via BackendFactory.
    Rate limit errors trigger exponential backoff retry.
    Implements fail_fast semantics with stop_flag for early termination.
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
        Returns (task, success) where success is True/False/None (skipped).
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
                success = execute_task_with_retry(
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
    execute_task_with_retry: ExecuteWithRetryFn,
) -> list[str]:
    """Execute independent tasks in parallel with TUI display and rate limit handling.

    Thread-safe design per PARALLEL-EXECUTION-REMEDIATION-SPEC:
    - Worker threads ONLY call tui.post_event() for TASK_STARTED and TASK_OUTPUT
    - Main thread pumps with wait(timeout=0.1) and calls tui.refresh() each loop
    - TASK_FINISHED events are emitted from main thread after future completes
    - Each worker creates a fresh backend instance via BackendFactory
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
        TASK_FINISHED is emitted by the main thread.
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

            success = execute_task_with_retry(
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
