# Parallel Execution Hardening / Remediation Spec

## Scope

This spec remediates implementation issues in the parallel execution feature affecting:
- CLI flag override logic
- Retry mechanism for rate-limit errors
- TUI thread-safety
- fail-fast enforcement and SKIPPED task representation
- Task ordering stability
- Log buffer lifecycle
- Task memory capture in parallel mode
- Git contention policy

## Non-Goals

- New features beyond what PARALLEL-EXECUTION-SPEC.md defines
- Scheduler semantics for `group_id` (kept for UI labeling only)
- Full task memory isolation (deferred to post-MVP)

---

## MVP Decisions

| Decision | Rationale |
|----------|-----------|
| **Memory capture disabled for parallel tasks** | `git diff --cached` mixes all concurrent changes; disabling prevents attribution contamination. Sequential tasks still capture. |
| **`group_id` is UI-only** | Original spec introduced `group:` tags; removing would break existing task lists. No scheduler semantics in MVP. |
| **Git operations forbidden in parallel tasks** | Parallel `git add`/`commit` contends on `.git/index`. Enforcement via prompt instructions. |
| **Retry boundary is `_execute_task_with_callback`** | This function raises `AuggieRateLimitError` on rate-limit failures; `_execute_task_with_retry` wraps it with exponential backoff. |
| **Thread-safety of state mutations: already satisfied** | `as_completed` loop runs on main thread; no additional locking required. |

---

## Required Code Changes

### File: `spec/cli.py`

#### Change 1: `max_parallel` CLI parameter
```python
# BEFORE:
max_parallel: Annotated[int, typer.Option(...)] = 3

# AFTER:
max_parallel: Annotated[Optional[int], typer.Option(...)] = None
```

#### Change 2: `fail_fast` CLI parameter
```python
# BEFORE:
fail_fast: Annotated[bool, typer.Option("--fail-fast")] = False

# AFTER:
fail_fast: Annotated[Optional[bool], typer.Option("--fail-fast/--no-fail-fast")] = None
```

#### Change 3: Compute effective values in `_run_workflow`
```python
effective_max_parallel = max_parallel if max_parallel is not None else config.settings.max_parallel_tasks
effective_fail_fast = fail_fast if fail_fast is not None else config.settings.fail_fast
```

#### Change 4: Validate effective values
```python
if effective_max_parallel < 1 or effective_max_parallel > 5:
    print_error(f"Invalid max_parallel={effective_max_parallel} (must be 1-5)")
    raise typer.Exit(ExitCode.GENERAL_ERROR)
```

---

### File: `spec/workflow/state.py`

#### Change 1: Add `__post_init__` validation to `RateLimitConfig`
```python
@dataclass
class RateLimitConfig:
    max_retries: int = 5
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    jitter_factor: float = 0.5
    retryable_status_codes: tuple[int, ...] = (429, 502, 503, 504)

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.max_retries > 0 and self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be > 0 when max_retries > 0")
        if self.jitter_factor < 0 or self.jitter_factor > 1:
            raise ValueError("jitter_factor must be in [0, 1]")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
```

---

### File: `spec/integrations/auggie.py`

#### Change 1: Add `AuggieRateLimitError` exception
```python
class AuggieRateLimitError(Exception):
    """Raised when Auggie CLI output indicates a rate limit error."""
    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output
```

#### Change 2: Add `_looks_like_rate_limit()` classifier (module-level)
```python
def _looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in output."""
    output_lower = output.lower()
    patterns = ["429", "rate limit", "rate_limit", "too many requests",
                "quota exceeded", "capacity", "throttl", "502", "503", "504"]
    return any(p in output_lower for p in patterns)
```

---

### File: `spec/workflow/step3_execute.py`

#### Change 1: Update `_execute_task_with_callback` to raise on rate limit
```python
from spec.integrations.auggie import AuggieRateLimitError, _looks_like_rate_limit

def _execute_task_with_callback(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    *,
    callback: callable,
) -> bool:
    prompt = _build_task_prompt(task, plan_path)
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
```

#### Change 2: Update `_execute_with_tui` to use retry wrapper
```python
# Around line 347:
# BEFORE:
success = _execute_task_with_callback(state, task, plan_path, callback=...)

# AFTER:
success = _execute_task_with_retry(state, task, plan_path, callback=...)
```

#### Change 3: Update `_execute_fallback` to use retry wrapper
```python
# Around line 441:
# BEFORE:
success = _execute_task_with_callback(state, task, plan_path, callback=output_callback)

# AFTER:
success = _execute_task_with_retry(state, task, plan_path, callback=output_callback)
```

#### Change 4: Add `is_parallel` parameter to `_build_task_prompt`
```python
def _build_task_prompt(task: Task, plan_path: Path, is_parallel: bool = False) -> str:
    base_prompt = f"""Execute this task.

Task: {task.name}

The implementation plan is at: {plan_path}
Use codebase-retrieval to read the plan and focus on the section relevant to this task."""

    if is_parallel:
        base_prompt += """

IMPORTANT: This task runs in parallel with other tasks.
- Do NOT run `git add`, `git commit`, or `git push`
- Do NOT stage any changes
- Only make file modifications; staging/committing will be done after all tasks complete"""

    base_prompt += "\n\nDo NOT commit or push any changes."
    return base_prompt
```

#### Change 5: Pass `is_parallel=True` in parallel execution functions
Update calls to `_build_task_prompt` in `_execute_parallel_fallback` and `_execute_parallel_with_tui`.

#### Change 6: Disable memory capture for parallel tasks
```python
# In parallel execution completion handling:
if success:
    mark_task_complete(tasklist_path, task.name)
    state.mark_task_complete(task.name)
    # Memory capture disabled for parallel tasks (contamination risk)
```

#### Change 7: Add `threading.Event` stop flag for fail-fast in `_execute_parallel_fallback`
```python
import threading
from concurrent.futures import CancelledError

def _execute_parallel_fallback(...) -> list[str]:
    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()

    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool | None]:
        idx, task = task_info
        if stop_flag.is_set():
            return task, None  # Skipped
        # ... existing execution logic ...
        return task, success

    # ... in as_completed loop:
    try:
        _, success = future.result()
    except CancelledError:
        skipped_tasks.append(task.name)
        continue

    if success is None:
        skipped_tasks.append(task.name)
    elif success:
        mark_task_complete(...)
    else:
        failed_tasks.append(task.name)
        if state.fail_fast:
            stop_flag.set()
            for f in futures:
                f.cancel()
```

#### Change 8: Add fail-fast with stop flag in `_execute_parallel_with_tui`

The TUI path must implement the same fail-fast behavior as the fallback path:
- Use a shared `threading.Event` stop flag
- Worker threads check `stop_flag.is_set()` before executing
- On first failure with `fail_fast=True`, set `stop_flag` and cancel pending futures
- Handle `CancelledError` and mark as SKIPPED
- Emit `TASK_FINISHED` with `status="skipped"` for cancelled/not-started tasks

```python
import threading
from concurrent.futures import wait, FIRST_COMPLETED, CancelledError

def _execute_parallel_with_tui(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    tui: TaskRunnerUI,
    max_workers: int,
) -> list[str]:
    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()
    future_to_task: dict[Future, tuple[int, Task]] = {}

    def execute_single_task_tui(task_info: tuple[int, Task]) -> tuple[int, Task, str]:
        """Worker function. Returns (idx, task, status) where status is 'success'|'failed'|'skipped'."""
        idx, task = task_info

        # Early exit if stop flag set (fail-fast triggered by another task)
        if stop_flag.is_set():
            return idx, task, "skipped"

        tui.post_event(create_task_started_event(idx, task.name))

        try:
            success = _execute_task_with_retry(
                state, task, plan_path,
                callback=lambda msg: tui.post_event(create_task_output_event(idx, task.name, msg)),
                is_parallel=True,
            )
            status = "success" if success else "failed"
        except Exception as e:
            # Unexpected crash - treat as failure
            tui.post_event(create_task_output_event(idx, task.name, f"[ERROR] {e}"))
            status = "failed"

        return idx, task, status

    with tui:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            for i, task in enumerate(tasks):
                future = executor.submit(execute_single_task_tui, (i, task))
                future_to_task[future] = (i, task)

            pending = set(future_to_task.keys())

            while pending:
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                tui.refresh()  # Drains event queue + updates Live display

                for future in done:
                    idx, task = future_to_task[future]

                    try:
                        _, _, status = future.result()
                    except CancelledError:
                        status = "skipped"

                    # Emit TASK_FINISHED event for this task
                    record = tui.get_record(idx)
                    duration = record.elapsed_time if record else 0.0
                    tui.post_event(create_task_finished_event(
                        idx, task.name, status, duration,
                        error="Task failed" if status == "failed" else None
                    ))

                    # Update tracking lists
                    if status == "success":
                        mark_task_complete(tasklist_path, task.name)
                        state.mark_task_complete(task.name)
                        # Memory capture disabled for parallel tasks (contamination risk)
                    elif status == "skipped":
                        skipped_tasks.append(task.name)
                    else:  # failed
                        failed_tasks.append(task.name)

                        # Trigger fail-fast: stop accepting new work
                        if state.fail_fast:
                            stop_flag.set()
                            # Cancel all pending futures
                            for f in pending:
                                f.cancel()

            tui.refresh()  # Final drain

    return failed_tasks  # Caller may also want skipped_tasks
```

---

### File: `spec/ui/tui.py`

#### Change 1: Add event queue for thread-safe event posting
```python
import queue

@dataclass
class TaskRunnerUI:
    _event_queue: queue.Queue = field(default_factory=queue.Queue, init=False)

    def post_event(self, event: TaskEvent) -> None:
        """Thread-safe: push event to queue (called from worker threads)."""
        self._event_queue.put(event)

    def _drain_event_queue(self) -> None:
        """Main thread: process all pending events."""
        while True:
            try:
                event = self._event_queue.get_nowait()
                self._apply_event(event)
            except queue.Empty:
                break

    def _apply_event(self, event: TaskEvent) -> None:
        """Apply event (main thread only). Extracted from handle_event."""
        # ... existing handle_event logic, minus self.refresh() ...

    def refresh(self) -> None:
        """Refresh display (main thread only). Drains queue first."""
        self._drain_event_queue()
        if self._live is not None:
            self._live.update(self._render_layout())

    # Keep handle_event for sequential mode:
    def handle_event(self, event: TaskEvent) -> None:
        self._apply_event(event)
        self.refresh()
```

#### Change 2: Log buffer lifecycle in `_apply_event`

Log buffers must be closed for ALL task completion statuses (success, failed, skipped). The existing logic closes log buffers on TASK_FINISHED; this must be preserved after refactoring `handle_event` → `_apply_event`.

```python
def _apply_event(self, event: TaskEvent) -> None:
    """Apply event to TUI state (main thread only)."""
    if event.event_type == TaskEventType.TASK_FINISHED:
        data = event.data
        idx = data.get("task_index", event.task_index)
        record = self.records[idx]

        status_str = data["status"]
        if status_str == "success":
            record.status = TaskRunStatus.SUCCESS
        elif status_str == "skipped":
            record.status = TaskRunStatus.SKIPPED
        else:
            record.status = TaskRunStatus.FAILED
            record.error = data.get("error")

        record.end_time = event.timestamp
        record.duration = data.get("duration", 0.0)

        # CRITICAL: Close log buffer for ALL statuses (success, failed, skipped)
        if record.log_buffer is not None:
            try:
                record.log_buffer.close()
            except Exception:
                pass  # Best-effort cleanup
            record.log_buffer = None

    elif event.event_type == TaskEventType.TASK_STARTED:
        # ... existing logic ...
        pass

    elif event.event_type == TaskEventType.TASK_OUTPUT:
        # ... existing logic ...
        pass
```

**Requirement**: Log buffer cleanup MUST happen in `_apply_event` on the main thread (not in worker threads) because:
1. Workers only call `post_event()` (thread-safe queue push)
2. Main thread drains queue via `refresh()` → `_drain_event_queue()` → `_apply_event()`
3. Log buffers may have thread affinity; closing on main thread is safest

---

### File: `spec/workflow/events.py`

#### Change 1: Update `create_task_finished_event` to use tri-state status
```python
def create_task_finished_event(
    task_index: int,
    task_name: str,
    status: Literal["success", "failed", "skipped"],  # Changed from success: bool
    duration: float,
    error: str | None = None,
) -> TaskEvent:
    return TaskEvent(
        event_type=TaskEventType.TASK_FINISHED,
        task_index=task_index,
        task_name=task_name,
        timestamp=time.time(),
        data={"status": status, "duration": duration, "error": error},
    )
```

#### Change 2: Update all callers to pass status string
```python
# Success case:
create_task_finished_event(idx, task.name, "success", duration)

# Failure case:
create_task_finished_event(idx, task.name, "failed", duration, error="...")

# Skipped case:
create_task_finished_event(idx, task.name, "skipped", 0.0)
```

#### Note on TUI handler update:
```python
def _apply_event(self, event: TaskEvent) -> None:
    if event.event_type == TaskEventType.TASK_FINISHED:
        data = event.data
        record = self.records[data["task_index"]]
        status_str = data["status"]
        if status_str == "success":
            record.status = TaskRunStatus.SUCCESS
        elif status_str == "skipped":
            record.status = TaskRunStatus.SKIPPED
        else:
            record.status = TaskRunStatus.FAILED
```

---

### File: `spec/workflow/tasks.py`

#### Change 1: Stable sort for `get_fundamental_tasks`
```python
def get_fundamental_tasks(tasks: list[Task]) -> list[Task]:
    fundamental = [t for t in tasks if t.category == TaskCategory.FUNDAMENTAL]
    return sorted(fundamental, key=lambda t: (
        0 if t.dependency_order > 0 else 1,  # Explicit order before order=0
        t.dependency_order,
        t.line_number  # Tie-breaker preserves file order
    ))
```

---

## Acceptance Criteria

1. **CLI:** `--max-parallel 3` overrides config value of 5; `--no-fail-fast` overrides config `fail_fast: true`; effective values validated (1-5 range)
2. **Retry:** Rate limit errors (429, 502-504, keywords) trigger exponential backoff via `_execute_task_with_retry`; non-rate-limit errors fail immediately; retry applies to BOTH sequential and parallel execution
3. **TUI:** No race conditions; workers use `post_event()`; main thread drains queue via explicit `wait()` pump loop
4. **fail_fast (both paths):** First failure stops new submissions in BOTH `_execute_parallel_fallback` AND `_execute_parallel_with_tui`; uses shared `threading.Event` stop_flag; workers check `stop_flag.is_set()` before executing; pending tasks marked SKIPPED; `CancelledError` handled in both paths; SKIPPED represented as tri-state `status` field in `TASK_FINISHED` events
5. **Ordering:** Tasks with `dependency_order=0` appear after tasks with explicit orders; `line_number` used as tie-breaker
6. **Log buffers:** Closed in `_apply_event()` for ALL statuses (success, failed, skipped); cleanup is best-effort (catches exceptions)
7. **TASK_FINISHED guarantee:** Every task that starts MUST emit a TASK_FINISHED event, even on unexpected exceptions; workers use try/except to catch crashes and emit "failed" status
8. **Memory:** Parallel tasks do NOT call `capture_task_memory()`
9. **group_id:** Retained for UI labeling only; no scheduler semantics
10. **Thread-safety:** State mutations happen on main thread; workers only call `post_event()` (queue push)
11. **Git contention:** Parallel task prompts include git operation restrictions
12. **Tests:** All behaviors have passing tests; retry tests mock `time.sleep` and `random.uniform`

---

## Test Plan

### Test Determinism

Mock `time.sleep` and `random.uniform` for fast, deterministic retry tests:
```python
@patch('spec.utils.retry.time.sleep')
@patch('spec.utils.retry.random.uniform', return_value=0.5)
def test_retry_triggers_on_rate_limit_error(mock_random, mock_sleep):
    # Test runs instantly, mock_sleep.call_count verifies attempts
```

### Test Matrix

| Test | File | Purpose |
|------|------|---------|
| `test_max_parallel_override_none_uses_config` | `tests/test_cli.py` | `None` → uses config value |
| `test_max_parallel_override_explicit` | `tests/test_cli.py` | `--max-parallel 2` overrides config=5 |
| `test_fail_fast_no_flag_overrides_config` | `tests/test_cli.py` | `--no-fail-fast` overrides config=True |
| `test_rate_limit_config_validation` | `tests/test_workflow_state.py` | Invalid values raise ValueError |
| `test_looks_like_rate_limit_patterns` | `tests/test_auggie.py` | Classifier detects 429, 502-504, keywords |
| `test_execute_task_raises_on_rate_limit` | `tests/test_step3_execute.py` | `_execute_task_with_callback` raises `AuggieRateLimitError` |
| `test_retry_triggers_on_rate_limit_error` | `tests/test_retry.py` | Exception triggers retry with mocked sleep |
| `test_tui_post_event_thread_safe` | `tests/test_tui.py` | Multi-threaded posting to queue works |
| `test_tui_drain_queue_on_refresh` | `tests/test_tui.py` | Events processed on refresh() |
| `test_fail_fast_skips_pending_tasks_fallback` | `tests/test_step3_execute.py` | Fallback path: pending tasks → SKIPPED status |
| `test_fail_fast_skips_pending_tasks_tui` | `tests/test_step3_execute.py` | TUI path: pending tasks → SKIPPED status |
| `test_fail_fast_handles_cancelled_error_fallback` | `tests/test_step3_execute.py` | Fallback path: CancelledError → SKIPPED |
| `test_fail_fast_handles_cancelled_error_tui` | `tests/test_step3_execute.py` | TUI path: CancelledError → SKIPPED |
| `test_task_ordering_stability` | `tests/test_workflow_tasks.py` | Mixed order=0 and order>0 sorted correctly |
| `test_parallel_task_memory_skipped` | `tests/test_step3_execute.py` | No capture_task_memory call |
| `test_parallel_prompt_git_restrictions` | `tests/test_step3_execute.py` | Prompt contains "Do NOT run `git add`" |
| `test_sequential_uses_retry` | `tests/test_step3_execute.py` | Sequential mode calls `_execute_task_with_retry` |
| `test_task_finished_event_tri_state` | `tests/test_events.py` | `create_task_finished_event` accepts status string |
| `test_task_finished_always_emitted_on_exception` | `tests/test_step3_execute.py` | Worker crash still emits TASK_FINISHED (failed) |
| `test_log_buffer_closed_on_success` | `tests/test_tui.py` | Log buffer closed in `_apply_event` for success |
| `test_log_buffer_closed_on_failure` | `tests/test_tui.py` | Log buffer closed in `_apply_event` for failure |
| `test_log_buffer_closed_on_skipped` | `tests/test_tui.py` | Log buffer closed in `_apply_event` for skipped |
| `test_stop_flag_prevents_new_task_execution` | `tests/test_step3_execute.py` | Worker early-exits if stop_flag set |

---

## Repo Hygiene Note

This is the **single source-of-truth** remediation spec. If older versions exist in this directory, archive or remove them. Git preserves history.

---

## Changelog

Version history: see Git.
