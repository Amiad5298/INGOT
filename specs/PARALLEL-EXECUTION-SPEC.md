# Parallel Task Execution Enhancement Specification

## Overview

This specification describes enhancements to the AI Platform's task execution workflow to support parallel execution of independent tasks while maintaining sequential execution for foundational/dependent tasks.

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Proposed Changes](#proposed-changes)
3. [Data Model Changes](#data-model-changes)
4. [Step 2 Enhancements](#step-2-enhancements)
5. [Step 3 Enhancements](#step-3-enhancements)
6. [Resilience & Rate Limit Handling](#resilience--rate-limit-handling)
7. [TUI Changes](#tui-changes)
8. [CLI Changes](#cli-changes)
9. [Configuration](#configuration)
10. [Testing Requirements](#testing-requirements)
11. [Migration Notes](#migration-notes)
12. [Performance Considerations](#performance-considerations)

---

## Current Architecture

### Task Execution Flow

```
Step 2: Task Generation → Step 3: Sequential Execution
                                 ↓
                          Task 1 → Task 2 → Task 3 → ... → Task N
```

### Key Components

| File | Purpose |
|------|---------|
| `spec/workflow/tasks.py` | Task dataclass, parsing, status management |
| `spec/workflow/step2_tasklist.py` | Task list generation from plan |
| `spec/workflow/step3_execute.py` | Sequential task execution |
| `spec/workflow/state.py` | WorkflowState dataclass |
| `spec/workflow/events.py` | Task events and run records |
| `spec/ui/tui.py` | Terminal UI for execution display |

### Current Task Structure

```python
@dataclass
class Task:
    name: str
    status: TaskStatus = TaskStatus.PENDING
    line_number: int = 0
    indent_level: int = 0
    parent: Optional[str] = None
```

### Current Execution Model

- All tasks execute sequentially
- Each task runs with `dont_save_session=True` for isolation
- Task memory captured after each completion
- TUI shows one active task at a time

---

## Proposed Changes

### Two-Phase Execution Model

```
Phase 1: Sequential Execution (Fundamental Tasks)
    Task 1 → Task 2 → Task 3
           ↓
Phase 2: Parallel Execution (Independent Tasks)
    Task 4 ─┬─ Task 5 ─┬─ Task 6
            └──────────┴──────────→ All complete
```

### Design Principles

1. **Backward Compatibility**: Existing task lists without categorization work as before
2. **Explicit Categorization**: AI categorizes tasks during generation
3. **Isolated Execution**: Parallel tasks use `dont_save_session=True`
4. **Graceful Degradation**: Fallback to sequential if parallel fails
5. **Resource Limits**: Configurable concurrency level

---

## Data Model Changes

### 1. Enhanced Task Dataclass (`tasks.py`)

```python
from enum import Enum

class TaskCategory(Enum):
    """Task execution category."""
    FUNDAMENTAL = "fundamental"  # Must run sequentially
    INDEPENDENT = "independent"  # Can run in parallel

@dataclass
class Task:
    name: str
    status: TaskStatus = TaskStatus.PENDING
    line_number: int = 0
    indent_level: int = 0
    parent: Optional[str] = None
    # New fields for parallel execution
    category: TaskCategory = TaskCategory.FUNDAMENTAL
    dependency_order: int = 0  # For fundamental tasks ordering
    group_id: Optional[str] = None  # For grouping parallel tasks
```

### 2. Task List Format

New format includes categorization metadata in comments:

```markdown
# Task List: TICKET-123

## Fundamental Tasks (Sequential)
<!-- category: fundamental, order: 1 -->
- [ ] Create core data models and database schema

<!-- category: fundamental, order: 2 -->
- [ ] Implement service layer with business logic

## Independent Tasks (Parallel)
<!-- category: independent, group: ui -->
- [ ] Build user dashboard component

<!-- category: independent, group: utils -->
- [ ] Create utility functions and helpers

<!-- category: independent, group: docs -->
- [ ] Update API documentation
```

### 3. WorkflowState Additions (`state.py`)

```python
@dataclass
class WorkflowState:
    # ... existing fields ...
    
    # Parallel execution configuration
    max_parallel_tasks: int = 3  # Default concurrency limit
    parallel_execution_enabled: bool = True
    
    # Execution tracking
    parallel_tasks_completed: list[str] = field(default_factory=list)
    parallel_tasks_failed: list[str] = field(default_factory=list)
```

---

## Step 2 Enhancements

### Modified Prompt Template (`step2_tasklist.py`)

Replace the existing prompt in `_generate_tasklist()`:

```python
prompt = f"""Based on this implementation plan, create a task list optimized for AI agent execution.

Plan:
{plan_content}

## Task Generation Guidelines:

### Size & Scope
- Each task should represent a **complete, coherent unit of work**
- Target 3-8 tasks for a typical feature
- Include tests WITH implementation, not as separate tasks

### Task Categorization

Categorize each task into one of two categories:

#### FUNDAMENTAL Tasks (Sequential Execution)
Tasks that establish foundational infrastructure and MUST run in order:
- Core data models, schemas, database migrations
- Base classes, interfaces, or abstract implementations
- Service layers that other components depend on
- Configuration or setup that other tasks require
- Any task where Task N+1 depends on Task N's output

Mark fundamental tasks with: `<!-- category: fundamental, order: N -->`

#### INDEPENDENT Tasks (Parallel Execution)
Tasks that can run concurrently with no dependencies on each other:
- UI components (after models/services exist)
- Utility functions and helpers
- Documentation updates
- Separate API endpoints that don't share state
- Test suites that don't modify shared resources

**CRITICAL: File Disjointness Requirement**
Independent tasks running in parallel MUST touch disjoint sets of files. Two parallel agents editing the same file simultaneously will cause race conditions and data loss.

If two tasks need to edit the same file:
1. **Preferred**: Mark BOTH tasks as FUNDAMENTAL (sequential) to avoid conflicts
2. **Alternative**: Merge them into a single task
3. **Alternative**: Restructure the tasks so each touches different files

Examples of file conflicts to avoid:
- Two tasks both adding functions to `utils.py` → Make FUNDAMENTAL or merge
- Two tasks both updating `config.yaml` → Make FUNDAMENTAL or merge
- Two tasks both modifying `__init__.py` exports → Make FUNDAMENTAL or merge

Mark independent tasks with: `<!-- category: independent, group: GROUP_NAME -->`

### Output Format

```markdown
# Task List: {ticket_id}

## Fundamental Tasks (Sequential)
<!-- category: fundamental, order: 1 -->
- [ ] [First foundational task]

<!-- category: fundamental, order: 2 -->
- [ ] [Second foundational task that depends on first]

## Independent Tasks (Parallel)
<!-- category: independent, group: ui -->
- [ ] [UI component task]

<!-- category: independent, group: utils -->
- [ ] [Utility task]
```

### Categorization Heuristics

1. **If unsure, mark as FUNDAMENTAL** - Sequential is always safe
2. **Data/Schema tasks are ALWAYS FUNDAMENTAL** - Order 1
3. **Service/Logic tasks are USUALLY FUNDAMENTAL** - Order 2+
4. **UI/Docs/Utils are USUALLY INDEPENDENT** - Can parallelize
5. **Tests with their implementation are FUNDAMENTAL** - Part of that task
6. **Shared file edits require FUNDAMENTAL** - If two tasks edit the same file, both must be FUNDAMENTAL to prevent race conditions

Order tasks by dependency (prerequisites first). Keep descriptions concise but specific.
"""
```

### Enhanced Task Extraction (`step2_tasklist.py`)

Add new function to parse categorization metadata:

```python
def _parse_task_metadata(lines: list[str], task_line_num: int) -> tuple[TaskCategory, int, Optional[str]]:
    """Parse task metadata from comment line above task.

    Searches backwards from the task line, skipping empty lines,
    to find the metadata comment. This handles cases where LLMs
    insert blank lines between the comment and task for readability.

    Args:
        lines: All lines from task list
        task_line_num: Line number of the task (0-indexed)

    Returns:
        Tuple of (category, order, group_id)
    """
    # Default values
    category = TaskCategory.FUNDAMENTAL
    order = 0
    group_id = None

    # Look backwards from task line, skipping empty lines
    search_line = task_line_num - 1
    while search_line >= 0:
        line_content = lines[search_line].strip()

        # Skip empty lines
        if not line_content:
            search_line -= 1
            continue

        # Found non-empty line - check if it's metadata
        if line_content.startswith("<!-- category:"):
            # Parse: <!-- category: fundamental, order: 1 -->
            # or: <!-- category: independent, group: ui -->
            if "fundamental" in line_content.lower():
                category = TaskCategory.FUNDAMENTAL
                order_match = re.search(r'order:\s*(\d+)', line_content)
                if order_match:
                    order = int(order_match.group(1))
            elif "independent" in line_content.lower():
                category = TaskCategory.INDEPENDENT
                group_match = re.search(r'group:\s*(\w+)', line_content)
                if group_match:
                    group_id = group_match.group(1)

        # Stop searching after first non-empty line (whether metadata or not)
        break

    return category, order, group_id
```

### Update `parse_task_list()` (`tasks.py`)

Modify to include category parsing:

```python
def parse_task_list(content: str) -> list[Task]:
    """Parse task list from markdown content with category metadata."""
    tasks: list[Task] = []
    lines = content.splitlines()

    # Pattern for task items
    pattern = re.compile(r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$", re.MULTILINE)

    for line_num, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            indent, checkbox, name = match.groups()
            indent_level = len(indent) // 2
            status = TaskStatus.COMPLETE if checkbox.lower() == "x" else TaskStatus.PENDING

            # Parse metadata from previous line
            category, order, group_id = _parse_task_metadata(lines, line_num)

            task = Task(
                name=name.strip(),
                status=status,
                line_number=line_num + 1,
                indent_level=indent_level,
                category=category,
                dependency_order=order,
                group_id=group_id,
            )

            # Set parent for nested tasks
            if indent_level > 0 and tasks:
                for prev_task in reversed(tasks):
                    if prev_task.indent_level < indent_level:
                        task.parent = prev_task.name
                        break

            tasks.append(task)

    return tasks
```

### Helper Functions for Task Filtering (`tasks.py`)

```python
def get_fundamental_tasks(tasks: list[Task]) -> list[Task]:
    """Get fundamental tasks sorted by dependency order."""
    fundamental = [t for t in tasks if t.category == TaskCategory.FUNDAMENTAL]
    return sorted(fundamental, key=lambda t: t.dependency_order)

def get_independent_tasks(tasks: list[Task]) -> list[Task]:
    """Get independent tasks (parallelizable)."""
    return [t for t in tasks if t.category == TaskCategory.INDEPENDENT]

def get_pending_fundamental_tasks(tasks: list[Task]) -> list[Task]:
    """Get pending fundamental tasks sorted by order."""
    return [t for t in get_fundamental_tasks(tasks) if t.status == TaskStatus.PENDING]

def get_pending_independent_tasks(tasks: list[Task]) -> list[Task]:
    """Get pending independent tasks."""
    return [t for t in get_independent_tasks(tasks) if t.status == TaskStatus.PENDING]
```

---

## Step 3 Enhancements

### Core Architecture Changes (`step3_execute.py`)

#### 1. New Import Requirements

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable

from spec.workflow.tasks import (
    Task,
    TaskCategory,
    get_pending_tasks,
    get_pending_fundamental_tasks,
    get_pending_independent_tasks,
    mark_task_complete,
    parse_task_list,
)
```

#### 2. Main Execution Flow Modification

Replace the execution section in `step_3_execute()`:

```python
def step_3_execute(
    state: WorkflowState,
    *,
    use_tui: bool | None = None,
    verbose: bool = False,
) -> bool:
    """Execute Step 3: Two-phase task execution.

    Phase 1: Sequential execution of fundamental tasks
    Phase 2: Parallel execution of independent tasks
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

    print_info(f"Found {len(pending_fundamental)} fundamental + {len(pending_independent)} independent tasks")

    # Setup
    plan_path = state.get_plan_path()
    log_dir = _create_run_log_dir(state.ticket.ticket_id)
    _cleanup_old_runs(state.ticket.ticket_id)

    failed_tasks: list[str] = []

    # Determine execution mode
    from spec.ui.tui import _should_use_tui
    use_tui_mode = _should_use_tui(use_tui)

    # PHASE 1: Execute fundamental tasks sequentially
    if pending_fundamental:
        print_header("Phase 1: Fundamental Tasks (Sequential)")

        if use_tui_mode:
            phase1_failed = _execute_with_tui(
                state, pending_fundamental, plan_path, tasklist_path, log_dir,
                verbose=verbose, phase="fundamental"
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
                state, pending_independent, plan_path, tasklist_path, log_dir,
                verbose=verbose
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
                state, pending_independent, plan_path, tasklist_path, log_dir,
                verbose=verbose, phase="independent"
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
            default=True
        ):
            print_info("Exiting Step 3 early due to task failures.")
            return False

    # Post-execution steps
    _show_summary(state, failed_tasks)
    _run_post_implementation_tests(state)
    _offer_commit_instructions(state)
    print_info(f"Task logs saved to: {log_dir}")

    return len(failed_tasks) == 0
```

#### 3. Parallel Execution Function (Fallback Mode)

```python
def _execute_parallel_fallback(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
) -> list[str]:
    """Execute independent tasks in parallel (non-TUI mode).

    Uses ThreadPoolExecutor for concurrent AI agent execution.
    Each task runs in complete isolation with dont_save_session=True.

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
    max_workers = min(state.max_parallel_tasks, len(tasks))

    print_info(f"Executing {len(tasks)} tasks with {max_workers} parallel workers")

    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool]:
        """Execute a single task (runs in thread)."""
        idx, task = task_info
        log_filename = format_log_filename(idx, task.name)
        log_path = log_dir / log_filename

        with TaskLogBuffer(log_path) as log_buffer:
            def output_callback(line: str) -> None:
                log_buffer.write(line)

            success = _execute_task_with_callback(
                state, task, plan_path,
                callback=output_callback,
            )

        return task, success

    # Execute in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(execute_single_task, (i, task)): task
            for i, task in enumerate(tasks)
        }

        for future in as_completed(futures):
            task, success = future.result()

            if success:
                mark_task_complete(tasklist_path, task.name)
                state.mark_task_complete(task.name)
                print_success(f"[PARALLEL] Completed: {task.name}")
                try:
                    capture_task_memory(task, state)
                except Exception as e:
                    print_warning(f"Failed to capture task memory: {e}")
            else:
                failed_tasks.append(task.name)
                print_warning(f"[PARALLEL] Failed: {task.name}")

    return failed_tasks
```

#### 4. Parallel Execution with TUI

```python
def _execute_parallel_with_tui(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    *,
    verbose: bool = False,
) -> list[str]:
    """Execute independent tasks in parallel with TUI display.

    Shows multiple tasks running concurrently in the TUI.

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
    from spec.ui.tui import TaskRunnerUI

    failed_tasks: list[str] = []
    max_workers = min(state.max_parallel_tasks, len(tasks))

    # Initialize TUI with all parallel tasks
    tui = TaskRunnerUI(ticket_id=state.ticket.ticket_id, verbose_mode=verbose)
    tui.initialize_records([t.name for t in tasks])
    tui.set_log_dir(log_dir)
    tui.set_parallel_mode(True)  # New: Enable parallel display mode

    # Create log buffers for each task
    for i, task in enumerate(tasks):
        log_filename = format_log_filename(i, task.name)
        log_path = log_dir / log_filename
        record = tui.get_record(i)
        if record:
            record.log_buffer = TaskLogBuffer(log_path)

    def execute_single_task_tui(task_info: tuple[int, Task]) -> tuple[int, Task, bool]:
        """Execute a single task with TUI callbacks."""
        idx, task = task_info
        record = tui.get_record(idx)

        # Emit task started
        start_event = create_task_started_event(idx, task.name)
        tui.handle_event(start_event)

        # Execute with streaming callback
        success = _execute_task_with_callback(
            state, task, plan_path,
            callback=lambda line: tui.handle_event(
                create_task_output_event(idx, task.name, line)
            ),
        )

        # Emit task finished
        duration = record.elapsed_time if record else 0.0
        finish_event = create_task_finished_event(
            idx, task.name, success, duration,
            error=None if success else "Task returned failure"
        )
        tui.handle_event(finish_event)

        return idx, task, success

    with tui:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(execute_single_task_tui, (i, task)): task
                for i, task in enumerate(tasks)
            }

            for future in as_completed(futures):
                idx, task, success = future.result()

                if success:
                    mark_task_complete(tasklist_path, task.name)
                    state.mark_task_complete(task.name)
                    try:
                        capture_task_memory(task, state)
                    except Exception as e:
                        record = tui.get_record(idx)
                        if record and record.log_buffer:
                            record.log_buffer.write(f"[WARNING] Memory capture failed: {e}")
                else:
                    failed_tasks.append(task.name)

    tui.print_summary()
    return failed_tasks
```

---

## Resilience & Rate Limit Handling

### Problem Statement

With `max_parallel_tasks` set to 3-5, concurrent API calls are highly likely to hit provider rate limits (TPM - Tokens Per Minute, RPM - Requests Per Minute), causing HTTP 429 (Too Many Requests) errors. Without proper handling, tasks will fail falsely even though the underlying work is valid.

### Solution: Exponential Backoff with Jitter

Implement a retry mechanism that progressively increases wait times while adding randomness to prevent thundering herd problems.

#### 1. Rate Limit Configuration (`state.py`)

```python
@dataclass
class RateLimitConfig:
    """Configuration for API rate limit handling."""

    max_retries: int = 5  # Maximum retry attempts
    base_delay_seconds: float = 2.0  # Initial delay
    max_delay_seconds: float = 60.0  # Cap on delay
    jitter_factor: float = 0.5  # Random jitter (0-50% of delay)

    # HTTP status codes that trigger retry
    retryable_status_codes: tuple[int, ...] = (429, 502, 503, 504)


@dataclass
class WorkflowState:
    # ... existing fields ...

    # Rate limit configuration
    rate_limit_config: RateLimitConfig = field(default_factory=RateLimitConfig)
```

#### 2. Retry Decorator (`utils/retry.py`)

```python
import random
import time
from functools import wraps
from typing import Callable, TypeVar

from spec.workflow.state import RateLimitConfig

T = TypeVar("T")


class RateLimitExceededError(Exception):
    """Raised when rate limit is hit and retries are exhausted."""

    def __init__(self, message: str, attempts: int, total_wait_time: float):
        super().__init__(message)
        self.attempts = attempts
        self.total_wait_time = total_wait_time


def calculate_backoff_delay(
    attempt: int,
    config: RateLimitConfig,
) -> float:
    """Calculate delay with exponential backoff and jitter.

    Formula: min(base * 2^attempt + jitter, max_delay)

    Args:
        attempt: Current attempt number (0-indexed)
        config: Rate limit configuration

    Returns:
        Delay in seconds
    """
    # Exponential backoff: 2s, 4s, 8s, 16s, 32s...
    exponential_delay = config.base_delay_seconds * (2 ** attempt)

    # Add jitter: random value between 0 and jitter_factor * delay
    jitter = random.uniform(0, config.jitter_factor * exponential_delay)

    # Apply delay with jitter, capped at max
    delay = min(exponential_delay + jitter, config.max_delay_seconds)

    return delay


def with_rate_limit_retry(
    config: RateLimitConfig,
    on_retry: Callable[[int, float, Exception], None] | None = None,
):
    """Decorator for retrying functions on rate limit errors.

    Args:
        config: Rate limit configuration
        on_retry: Optional callback called before each retry
                  (attempt_number, delay_seconds, exception)

    Usage:
        @with_rate_limit_retry(config, on_retry=log_retry)
        def call_api():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            total_wait_time = 0.0
            last_exception: Exception | None = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check if this is a retryable error
                    if not _is_retryable_error(e, config):
                        raise

                    last_exception = e

                    # Check if we have retries left
                    if attempt >= config.max_retries:
                        break

                    # Calculate delay
                    delay = calculate_backoff_delay(attempt, config)
                    total_wait_time += delay

                    # Notify callback if provided
                    if on_retry:
                        on_retry(attempt + 1, delay, e)

                    # Wait before retry
                    time.sleep(delay)

            # All retries exhausted
            raise RateLimitExceededError(
                f"Rate limit exceeded after {config.max_retries} retries "
                f"(total wait: {total_wait_time:.1f}s): {last_exception}",
                attempts=config.max_retries,
                total_wait_time=total_wait_time,
            )

        return wrapper
    return decorator


def _is_retryable_error(error: Exception, config: RateLimitConfig) -> bool:
    """Check if an error should trigger a retry.

    Handles various error types from different API clients.
    """
    error_str = str(error).lower()

    # Check for HTTP status codes in error message
    for status_code in config.retryable_status_codes:
        if str(status_code) in error_str:
            return True

    # Check for common rate limit keywords
    rate_limit_keywords = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "throttl",
        "quota exceeded",
        "capacity",
    ]

    return any(keyword in error_str for keyword in rate_limit_keywords)
```

#### 3. Integration with Task Execution (`step3_execute.py`)

Update the task execution function to use the retry mechanism:

```python
from spec.utils.retry import (
    RateLimitExceededError,
    with_rate_limit_retry,
)


def _execute_task_with_retry(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    callback: Callable[[str], None] | None = None,
) -> bool:
    """Execute a task with rate limit retry handling.

    Wraps the core execution with exponential backoff retry logic.

    Args:
        state: Current workflow state
        task: Task to execute
        plan_path: Path to plan file
        callback: Output callback for streaming

    Returns:
        True if task succeeded, False otherwise
    """
    config = state.rate_limit_config

    def log_retry(attempt: int, delay: float, error: Exception) -> None:
        """Log retry attempts."""
        message = f"[RETRY {attempt}/{config.max_retries}] Rate limited. Waiting {delay:.1f}s..."
        if callback:
            callback(message)
        print_warning(message)

    @with_rate_limit_retry(config, on_retry=log_retry)
    def execute_with_retry() -> bool:
        return _execute_task_with_callback(
            state, task, plan_path, callback=callback
        )

    try:
        return execute_with_retry()
    except RateLimitExceededError as e:
        error_msg = f"[FAILED] Task exhausted all retries: {e}"
        if callback:
            callback(error_msg)
        print_error(error_msg)
        return False
```

#### 4. Updated Parallel Execution with Retry

Modify `_execute_parallel_fallback()` to use the retry-enabled execution:

```python
def _execute_parallel_fallback(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
) -> list[str]:
    """Execute independent tasks in parallel with rate limit handling."""
    failed_tasks: list[str] = []
    max_workers = min(state.max_parallel_tasks, len(tasks))

    print_info(f"Executing {len(tasks)} tasks with {max_workers} parallel workers")
    print_info(f"Rate limit retry: max {state.rate_limit_config.max_retries} retries")

    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool]:
        """Execute a single task with retry handling (runs in thread)."""
        idx, task = task_info
        log_filename = format_log_filename(idx, task.name)
        log_path = log_dir / log_filename

        with TaskLogBuffer(log_path) as log_buffer:
            def output_callback(line: str) -> None:
                log_buffer.write(line)

            # Use retry-enabled execution
            success = _execute_task_with_retry(
                state, task, plan_path,
                callback=output_callback,
            )

        return task, success

    # ... rest of parallel execution logic ...
```

### Retry Behavior Summary

| Attempt | Base Delay | With Jitter (example) | Cumulative Wait |
|---------|------------|----------------------|-----------------|
| 1       | 2s         | 2.0 - 3.0s          | ~2.5s           |
| 2       | 4s         | 4.0 - 6.0s          | ~7.5s           |
| 3       | 8s         | 8.0 - 12.0s         | ~17.5s          |
| 4       | 16s        | 16.0 - 24.0s        | ~37.5s          |
| 5       | 32s        | 32.0 - 48.0s        | ~77.5s          |

After 5 retries (~77 seconds of waiting), the task fails permanently.

### CLI Configuration Options

Add rate limit options to CLI:

```python
@click.option("--max-retries", default=5, type=int, help="Max retries on rate limit (0 to disable)")
@click.option("--retry-base-delay", default=2.0, type=float, help="Base delay for retry backoff (seconds)")
def run(
    # ... existing options ...
    max_retries: int,
    retry_base_delay: float,
) -> None:
    """Run the AI workflow for a ticket."""
    state = WorkflowState(
        # ... existing config ...
        rate_limit_config=RateLimitConfig(
            max_retries=max_retries,
            base_delay_seconds=retry_base_delay,
        ),
    )
```

### Logging & Observability

Rate limit events should be logged for monitoring:

```python
# Example log output during retry
[2024-01-15 10:30:15] [TASK: Build UI component] Starting execution...
[2024-01-15 10:30:18] [TASK: Build UI component] HTTP 429 received
[2024-01-15 10:30:18] [RETRY 1/5] Rate limited. Waiting 2.3s...
[2024-01-15 10:30:20] [TASK: Build UI component] Retrying...
[2024-01-15 10:30:45] [TASK: Build UI component] ✓ Completed successfully
```

---

## TUI Changes

### 1. Enhanced TaskRunnerUI (`tui.py`)

Add parallel mode support to display multiple running tasks:

```python
@dataclass
class TaskRunnerUI:
    """TUI manager for Step 3 task execution."""

    ticket_id: str = ""
    records: list[TaskRunRecord] = field(default_factory=list)
    selected_index: int = -1
    follow_mode: bool = True
    verbose_mode: bool = False
    parallel_mode: bool = False  # NEW: Multiple tasks can run simultaneously
    _current_task_index: int = -1
    _running_task_indices: set[int] = field(default_factory=set)  # NEW: Track parallel tasks
    # ... rest of existing fields ...

    def set_parallel_mode(self, enabled: bool) -> None:
        """Enable or disable parallel execution display mode."""
        self.parallel_mode = enabled

    def _handle_task_started(self, event: TaskEvent) -> None:
        """Handle TASK_STARTED event with parallel support."""
        record = self.get_record(event.task_index)
        if record:
            record.status = TaskRunStatus.RUNNING
            record.start_time = event.timestamp

            if self.parallel_mode:
                self._running_task_indices.add(event.task_index)
            else:
                self._current_task_index = event.task_index

    def _handle_task_finished(self, event: TaskEvent) -> None:
        """Handle TASK_FINISHED event with parallel support."""
        record = self.get_record(event.task_index)
        if record:
            record.end_time = event.timestamp
            if event.data:
                if event.data.get("success", False):
                    record.status = TaskRunStatus.SUCCESS
                else:
                    record.status = TaskRunStatus.FAILED
                    record.error = event.data.get("error")

            if record.log_buffer:
                record.log_buffer.close()

            if self.parallel_mode:
                self._running_task_indices.discard(event.task_index)
```

### 2. Updated Task List Panel

Modify `render_task_list()` to show multiple running tasks:

```python
def render_task_list(
    records: list[TaskRunRecord],
    selected_index: int = -1,
    ticket_id: str = "",
    parallel_mode: bool = False,
) -> Panel:
    """Render the task list panel with parallel execution support."""
    table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
    table.add_column("Status", width=3)
    table.add_column("Task", ratio=1)
    table.add_column("Duration", width=10, justify="right")

    running_count = sum(1 for r in records if r.status == TaskRunStatus.RUNNING)

    for i, record in enumerate(records):
        icon = record.get_status_icon()
        color = record.get_status_color()

        # Use spinner for running tasks
        if record.status == TaskRunStatus.RUNNING:
            status_cell = Spinner("dots", style=color)
        else:
            status_cell = Text(icon, style=color)

        # Task name with running indicator
        name_style = ""
        if i == selected_index:
            name_style = "reverse"
        elif record.status == TaskRunStatus.RUNNING:
            name_style = "bold"

        name_text = record.task_name
        if record.status == TaskRunStatus.RUNNING and parallel_mode:
            name_text = f"{name_text} ⚡"  # Parallel indicator
        elif record.status == TaskRunStatus.RUNNING:
            name_text = f"{name_text} ← Running"

        # Duration
        duration_text = ""
        if record.status in (TaskRunStatus.RUNNING, TaskRunStatus.SUCCESS, TaskRunStatus.FAILED):
            duration_text = f"[dim]{record.format_duration()}[/dim]"

        table.add_row(status_cell, Text(name_text, style=name_style), Text.from_markup(duration_text))

    # Build header with parallel mode indicator
    total = len(records)
    completed = sum(1 for r in records if r.status == TaskRunStatus.SUCCESS)

    if parallel_mode and running_count > 0:
        header = f"TASKS [{ticket_id}] [{completed}/{total}] [⚡ {running_count} parallel]"
    else:
        header = f"TASKS [{ticket_id}] [{completed}/{total} tasks]"

    return Panel(table, title=header, border_style="blue")
```

### 3. Status Bar Update

Add parallel execution indicator:

```python
def render_status_bar(
    running: bool = False,
    verbose_mode: bool = False,
    parallel_mode: bool = False,
    running_count: int = 0,
) -> Text:
    """Render the keyboard shortcuts status bar."""
    shortcuts = [
        ("[↑↓]", "Navigate"),
        ("[Enter]", "View logs"),
        ("[f]", "Follow"),
        ("[v]", "Verbose"),
        ("[q]", "Quit"),
    ]

    text = Text()
    for key, action in shortcuts:
        text.append(key, style="bold cyan")
        text.append(f" {action}  ", style="dim")

    if parallel_mode and running_count > 0:
        text.append(f" | ⚡ {running_count} tasks running", style="bold yellow")

    return text
```

---

## CLI Changes

### 1. New CLI Options (`cli.py`)

Add parallel execution flags to the `run` command:

```python
@click.command()
@click.argument("ticket_id")
@click.option("--parallel/--no-parallel", default=True, help="Enable parallel execution of independent tasks")
@click.option("--max-parallel", default=3, type=int, help="Maximum number of parallel tasks (1-5)")
@click.option("--fail-fast", is_flag=True, help="Stop on first task failure")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option("--tui/--no-tui", default=None, help="Force TUI mode on/off")
def run(
    ticket_id: str,
    parallel: bool,
    max_parallel: int,
    fail_fast: bool,
    verbose: bool,
    tui: bool | None,
) -> None:
    """Run the AI workflow for a ticket."""
    # Validate max_parallel
    if max_parallel < 1 or max_parallel > 5:
        click.echo("Error: --max-parallel must be between 1 and 5", err=True)
        raise SystemExit(1)

    # Initialize state with parallel settings
    state = WorkflowState(
        ticket=Ticket(ticket_id=ticket_id),
        parallel_execution_enabled=parallel,
        max_parallel_tasks=max_parallel,
        fail_fast=fail_fast,
    )

    # ... rest of run command ...
```

### 2. Step 3 Specific Options

```python
@click.command()
@click.argument("ticket_id")
@click.option("--parallel/--no-parallel", default=True, help="Enable parallel execution")
@click.option("--max-parallel", default=3, type=int, help="Max parallel tasks")
@click.option("--fail-fast", is_flag=True, help="Stop on first failure")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--tui/--no-tui", default=None, help="Force TUI mode")
def step3(
    ticket_id: str,
    parallel: bool,
    max_parallel: int,
    fail_fast: bool,
    verbose: bool,
    tui: bool | None,
) -> None:
    """Execute Step 3 only for a ticket."""
    state = load_workflow_state(ticket_id)

    # Apply parallel settings
    state.parallel_execution_enabled = parallel
    state.max_parallel_tasks = max_parallel
    state.fail_fast = fail_fast

    success = step_3_execute(state, use_tui=tui, verbose=verbose)

    if not success:
        raise SystemExit(1)
```

---

## Configuration

### 1. Config File Support (`config.py`)

Add parallel execution defaults to config:

```python
@dataclass
class WorkflowConfig:
    """Configuration for AI workflow."""

    # Existing fields...

    # Parallel execution settings
    parallel_execution_enabled: bool = True
    max_parallel_tasks: int = 3
    fail_fast: bool = False

    @classmethod
    def from_file(cls, path: Path) -> "WorkflowConfig":
        """Load config from YAML file."""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls(
            # ... existing fields ...
            parallel_execution_enabled=data.get("parallel_execution_enabled", True),
            max_parallel_tasks=data.get("max_parallel_tasks", 3),
            fail_fast=data.get("fail_fast", False),
        )
```

### 2. Example Config File

```yaml
# .spec.yaml

# Parallel execution settings
parallel_execution_enabled: true
max_parallel_tasks: 3
fail_fast: false

# Other settings...
```

---

## Testing Requirements

### 1. Unit Tests

```python
# tests/test_parallel_execution.py

import pytest
from spec.workflow.tasks import (
    Task,
    TaskCategory,
    TaskStatus,
    get_fundamental_tasks,
    get_independent_tasks,
    get_pending_fundamental_tasks,
    get_pending_independent_tasks,
    parse_task_list,
)


class TestTaskCategorization:
    """Tests for task categorization parsing."""

    def test_parse_fundamental_task(self):
        """Test parsing fundamental task with order."""
        content = """
<!-- category: fundamental, order: 1 -->
- [ ] Create database schema
"""
        tasks = parse_task_list(content)
        assert len(tasks) == 1
        assert tasks[0].category == TaskCategory.FUNDAMENTAL
        assert tasks[0].dependency_order == 1

    def test_parse_independent_task(self):
        """Test parsing independent task with group."""
        content = """
<!-- category: independent, group: ui -->
- [ ] Build user profile component
"""
        tasks = parse_task_list(content)
        assert len(tasks) == 1
        assert tasks[0].category == TaskCategory.INDEPENDENT
        assert tasks[0].group_id == "ui"

    def test_parse_mixed_tasks(self):
        """Test parsing mixed fundamental and independent tasks."""
        content = """
## Fundamental Tasks
<!-- category: fundamental, order: 1 -->
- [ ] Create models

<!-- category: fundamental, order: 2 -->
- [ ] Create services

## Independent Tasks
<!-- category: independent, group: ui -->
- [ ] Build UI component

<!-- category: independent, group: utils -->
- [ ] Add utility functions
"""
        tasks = parse_task_list(content)
        assert len(tasks) == 4

        fundamental = get_fundamental_tasks(tasks)
        assert len(fundamental) == 2
        assert fundamental[0].dependency_order == 1
        assert fundamental[1].dependency_order == 2

        independent = get_independent_tasks(tasks)
        assert len(independent) == 2

    def test_legacy_task_list_defaults_to_fundamental(self):
        """Test that tasks without metadata default to fundamental."""
        content = """
- [ ] Task without metadata
- [ ] Another task
"""
        tasks = parse_task_list(content)
        assert len(tasks) == 2
        assert all(t.category == TaskCategory.FUNDAMENTAL for t in tasks)


class TestParallelExecution:
    """Tests for parallel execution logic."""

    def test_max_parallel_tasks_limit(self):
        """Test that max_parallel_tasks is respected."""
        # This would be an integration test
        pass

    def test_fundamental_tasks_run_sequentially(self):
        """Test that fundamental tasks run in order."""
        pass

    def test_independent_tasks_run_in_parallel(self):
        """Test that independent tasks can run concurrently."""
        pass

    def test_fail_fast_stops_execution(self):
        """Test that fail_fast stops on first failure."""
        pass
```

### 2. Integration Tests

```python
# tests/integration/test_parallel_workflow.py

import pytest
from pathlib import Path
from spec.workflow.state import WorkflowState
from spec.workflow.step3_execute import step_3_execute


class TestParallelWorkflow:
    """Integration tests for parallel execution."""

    @pytest.fixture
    def sample_state(self, tmp_path):
        """Create a sample workflow state with categorized tasks."""
        state = WorkflowState(
            ticket=Ticket(ticket_id="TEST-123"),
            parallel_execution_enabled=True,
            max_parallel_tasks=2,
        )

        # Create task list with categories
        tasklist = tmp_path / "tasklist.md"
        tasklist.write_text("""
## Fundamental Tasks
<!-- category: fundamental, order: 1 -->
- [ ] Setup database

## Independent Tasks
<!-- category: independent, group: ui -->
- [ ] Build component A

<!-- category: independent, group: ui -->
- [ ] Build component B
""")

        return state

    def test_two_phase_execution(self, sample_state):
        """Test that execution follows two-phase pattern."""
        # Would need mocking of AI agent calls
        pass
```

---

## Migration Notes

### Backward Compatibility

1. **Legacy Task Lists**: Task lists without category metadata will be treated as all-fundamental (sequential execution)
2. **CLI Defaults**: Parallel execution is enabled by default but can be disabled with `--no-parallel`
3. **Config Override**: CLI flags override config file settings

### Rollout Strategy

1. **Phase 1**: Deploy with parallel execution disabled by default
2. **Phase 2**: Enable parallel execution for new tickets only
3. **Phase 3**: Full rollout with parallel execution enabled by default

---

## Performance Considerations

### Resource Management

1. **Thread Pool Size**: Limited to `max_parallel_tasks` (default: 3, max: 5)
2. **Memory**: Each parallel task maintains its own log buffer
3. **API Rate Limits**: Handled via exponential backoff retry (see [Resilience & Rate Limit Handling](#resilience--rate-limit-handling))

### Monitoring

Track these metrics:
- Total execution time (sequential vs parallel)
- Per-task execution time
- Parallel task success rate
- Resource utilization during parallel execution
- **Rate limit retries**: Count of 429 errors and retry attempts
- **Retry wait time**: Total time spent waiting on rate limits

