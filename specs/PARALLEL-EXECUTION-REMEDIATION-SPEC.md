# Parallel Execution Hardening / Remediation Spec (v3)

## Delta / Changes from v2

| Section | Change |
|---------|--------|
| **Fix B** | Resolved API contradiction: introduced `run_with_callback_retryable()` as a NEW method; `run_with_callback` remains backward-compatible. Step 3 parallel/sequential code calls the new method. |
| **Fix C** | Added explicit main-thread pump loop pseudocode inside `_execute_parallel_with_tui`. Uses `concurrent.futures.wait(..., timeout=0.1)` + `tui.refresh()` to drain queue without a separate render thread. |
| **Fix D** | Clarified SKIPPED representation: use tri-state `status` field in `TASK_FINISHED` event data (`"success" | "failed" | "skipped"`). Updated TUI event handler + summary rules. |
| **Fix B+** | Retry now applies to BOTH sequential (Phase 1) and parallel (Phase 2) execution. Documented the retry boundary at `_execute_task_with_retry`. |
| **Fix J** | Simplified: verified `as_completed` loop runs on main thread, so `mark_task_complete` calls are already safe. Removed over-engineered lock/collection proposal. |
| **Test Plan** | Added requirement to mock `time.sleep` and `random.uniform` (or seed) for deterministic, fast retry tests. |

---

## Background & Scope

This spec addresses implementation issues found during review of the parallel execution feature. The issues affect CLI behavior, retry semantics, TUI thread-safety, fail-fast enforcement, task ordering, task memory correctness, and test coverage.

---

## Issue Validation Report

### A) CLI Override Logic Bugs
**STATUS: CONFIRMED**

| Issue | File | Lines | Evidence |
|-------|------|-------|----------|
| max-parallel override bug | `cli.py` | 419 | `effective_max_parallel = max_parallel if max_parallel != 3 else ...` – uses `!= 3` instead of Optional[int] |
| fail-fast cannot disable | `cli.py` | 420 | `effective_fail_fast = fail_fast or config...` – `or` means config True always wins |
| Negative values not validated | `state.py` | 32-35 | `max_retries`, `base_delay_seconds` accept any int/float |

---

### B) Retry Mechanism May Not Retry
**STATUS: CONFIRMED**

- `_execute_task_with_callback` catches all exceptions and returns `False`
- `run_with_callback` returns `(success, output)` without raising
- Retry decorator never sees an exception to retry

---

### C) TUI Thread-Safety Risks
**STATUS: CONFIRMED**

Worker threads call `tui.handle_event()` directly. Rich Live is not thread-safe.

---

### D) fail_fast Not Enforced in Parallel Phase
**STATUS: CONFIRMED**

All futures submitted upfront; no cancellation on first failure.

---

### E) Task Ordering – dependency_order=0 Problem
**STATUS: CONFIRMED**

---

### F) Log Buffer Lifecycle
**STATUS: CONFIRMED**

No try/finally around task execution in parallel TUI path.

---

### G) Task Memory Capture Correctness
**STATUS: CONFIRMED**

---

### H) group_id Unused
**STATUS: CONFIRMED**

---

### I) Missing Tests
**STATUS: CONFIRMED**

---

### J) Thread-Safety of Shared State
**STATUS: ALREADY SATISFIED**

Verified: `as_completed` loop runs on the **main thread**, so `mark_task_complete(tasklist_path, ...)` and `state.mark_task_complete(...)` are called from the main thread, not worker threads. No additional locking required.

---

### K) Concurrent Git/Index Operations
**STATUS: CONFIRMED**

---

## Proposed Fixes

### Fix A: CLI Override Semantics

**Changes to `cli.py`:**

1. Change `max_parallel` from `int` with default 3 to `Optional[int]` default `None`:
```python
max_parallel: Annotated[Optional[int], typer.Option(...)] = None
```

2. Change `fail_fast` to a tri-state flag:
```python
fail_fast: Annotated[Optional[bool], typer.Option("--fail-fast/--no-fail-fast")] = None
```

3. In `_run_workflow`, compute effective values properly:
```python
effective_max_parallel = max_parallel if max_parallel is not None else config.settings.max_parallel_tasks
effective_fail_fast = fail_fast if fail_fast is not None else config.settings.fail_fast
```

4. **Validate effective (post-merge) values**, not just raw CLI args:
```python
# After merging CLI + config:
if effective_max_parallel < 1 or effective_max_parallel > 5:
    print_error(f"Invalid max_parallel={effective_max_parallel} (must be 1-5)")
    raise typer.Exit(ExitCode.GENERAL_ERROR)
```

5. **Validate RateLimitConfig** in `state.py` `__post_init__`:
```python
@dataclass
class RateLimitConfig:
    ...
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

### Fix B: Retry Mechanism (Backward-Compatible Approach)

**Problem:** Errors are returned as `False`, not raised. Retry decorator never sees exceptions.

**Solution:** Add a NEW method `run_with_callback_retryable()` that raises on rate limits. Keep `run_with_callback()` unchanged for backward compatibility.

#### 1. Add `_looks_like_rate_limit()` classifier in `auggie.py`:
```python
def _looks_like_rate_limit(output: str, exit_code: int) -> bool:
    """Heuristic check for rate limit errors."""
    if exit_code == 0:
        return False
    output_lower = output.lower()
    patterns = ["429", "rate limit", "rate_limit", "too many requests",
                "quota exceeded", "capacity", "throttl", "502", "503", "504"]
    return any(p in output_lower for p in patterns)
```

#### 2. Add `AuggieRateLimitError` exception:
```python
class AuggieRateLimitError(Exception):
    """Raised when Auggie CLI output indicates a rate limit error."""
    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output
```

#### 3. Add NEW method `run_with_callback_retryable()` in `AuggieClient`:
```python
def run_with_callback_retryable(self, prompt, *, output_callback, ...) -> tuple[bool, str]:
    """Like run_with_callback, but raises AuggieRateLimitError on rate limits.

    Use this method when you want the caller to handle retries.
    """
    success, output = self.run_with_callback(prompt, output_callback=output_callback, ...)
    if not success and _looks_like_rate_limit(output, -1):  # exit code unavailable here
        raise AuggieRateLimitError("Rate limit detected", output=output)
    return success, output
```

**Note:** To get the actual exit code, we may need to refactor `run_with_callback` to return it or store it. Alternatively, detect rate limit patterns in output only.

#### 4. Update `_execute_task_with_callback` to re-raise rate limit errors:
```python
def _execute_task_with_callback(...) -> bool:
    try:
        success, output = auggie_client.run_with_callback(...)
        if not success and _looks_like_rate_limit(output):
            raise AuggieRateLimitError("Rate limit detected", output)
        return success
    except AuggieRateLimitError:
        raise  # Let retry decorator catch this
    except Exception as e:
        callback(f"[ERROR] Task execution crashed: {e}")
        return False
```

**Backward Compatibility:** `run_with_callback()` is UNCHANGED. Only `_execute_task_with_callback` converts rate limit failures to exceptions.

**Retry Boundary:** The retry logic lives in `_execute_task_with_retry()`, which wraps `_execute_task_with_callback`. Both sequential and parallel execution MUST use `_execute_task_with_retry()` (see Fix B+).

---

### Fix B+: Retry Applies to BOTH Sequential and Parallel Execution

**Problem:** Currently, only `_execute_parallel_fallback` and `_execute_parallel_with_tui` use `_execute_task_with_retry`. Sequential execution (`_execute_with_tui`, `_execute_fallback`) calls `_execute_task_with_callback` directly, bypassing retry logic.

**Solution:** Update sequential execution to also use `_execute_task_with_retry`:

```python
# In _execute_with_tui (around line 347):
# BEFORE:
success = _execute_task_with_callback(state, task, plan_path, callback=...)

# AFTER:
success = _execute_task_with_retry(state, task, plan_path, callback=...)
```

```python
# In _execute_fallback (around line 441):
# BEFORE:
success = _execute_task_with_callback(state, task, plan_path, callback=output_callback)

# AFTER:
success = _execute_task_with_retry(state, task, plan_path, callback=output_callback)
```

**Behavior when `max_retries=0`:** `_execute_task_with_retry` already handles this case by calling the underlying function directly without retry wrapping.

---

### Fix C: TUI Thread-Safety (Queue + Main-Thread Pump Loop)

**Constraints:**
- Workers MUST NOT call `tui.handle_event()` or `tui.refresh()`
- Workers only push events to a thread-safe queue via `tui.post_event()`
- Main thread explicitly drains queue and refreshes display

**Changes to `tui.py`:**

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
        """Apply event (main thread only). Extracted from handle_event, no refresh call."""
        # ... existing handle_event logic, minus self.refresh() at the end ...

    def refresh(self) -> None:
        """Refresh display (main thread only). Drains queue first."""
        self._drain_event_queue()
        if self._live is not None:
            self._live.update(self._render_layout())

    # Keep handle_event for sequential mode backward compatibility:
    def handle_event(self, event: TaskEvent) -> None:
        self._apply_event(event)
        self.refresh()
```

**Main-Thread Pump Loop in `_execute_parallel_with_tui`:**

Rich Live's `refresh_per_second` does NOT automatically call our `refresh()` method. We must explicitly pump the queue. Add an explicit main-thread loop:

```python
def _execute_parallel_with_tui(...) -> list[str]:
    from concurrent.futures import wait, FIRST_COMPLETED

    # ... setup tui, log buffers, etc. ...

    def execute_single_task_tui(task_info):
        idx, task = task_info
        tui.post_event(create_task_started_event(idx, task.name))
        success = _execute_task_with_retry(state, task, plan_path,
            callback=lambda line, i=idx, n=task.name: tui.post_event(
                create_task_output_event(i, n, line)))
        duration = tui.get_record(idx).elapsed_time if tui.get_record(idx) else 0.0
        tui.post_event(create_task_finished_event(idx, task.name, success, duration,
            error=None if success else "Task failed"))
        return idx, task, success

    with tui:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = {executor.submit(execute_single_task_tui, (i, t)): t
                       for i, t in enumerate(tasks)}

            # Main-thread pump loop: drain queue + refresh while futures run
            while pending:
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                tui.refresh()  # Drains queue + updates Live

                for future in done:
                    idx, task, success = future.result()
                    if success:
                        mark_task_complete(tasklist_path, task.name)
                        state.mark_task_complete(task.name)
                    else:
                        failed_tasks.append(task.name)
                        if state.fail_fast:
                            # Cancel remaining (best-effort)
                            for f in pending:
                                f.cancel()

            # Final drain after all complete
            tui.refresh()

    tui.print_summary()
    return failed_tasks
```

**Why this works:** The main thread calls `wait(..., timeout=0.1)` which blocks briefly, then calls `tui.refresh()` to drain the queue and update the display. This avoids a separate render thread while keeping the UI responsive.

---

### Fix D: fail_fast in Parallel Phase + SKIPPED Representation

**Semantics defined:**
1. After first failure, **do not start** any additional tasks (check stop flag before execution)
2. **Best-effort cancel** pending futures (may not interrupt running tasks)
3. Running tasks **may continue** to completion (thread safety)
4. Tasks not started → marked **SKIPPED** (not FAILED)
5. `CancelledError` from `future.result()` → task marked SKIPPED

**SKIPPED Representation in Events:**

Currently, `TASK_FINISHED` has a `success: bool` field. To distinguish SKIPPED from FAILED, change to a tri-state `status` field:

```python
# In events.py:
class TaskFinishedData:
    task_index: int
    task_name: str
    status: Literal["success", "failed", "skipped"]  # Changed from success: bool
    duration: float
    error: Optional[str] = None
```

**Update TUI event handler:**
```python
def _apply_event(self, event: TaskEvent) -> None:
    if event.event_type == TaskEventType.TASK_FINISHED:
        data = event.data
        record = self.records[data.task_index]
        if data.status == "success":
            record.status = TaskRunStatus.COMPLETED
        elif data.status == "skipped":
            record.status = TaskRunStatus.SKIPPED
        else:
            record.status = TaskRunStatus.FAILED
```

**Update summary logic:**
```python
def print_summary(self) -> None:
    completed = sum(1 for r in self.records if r.status == TaskRunStatus.COMPLETED)
    failed = sum(1 for r in self.records if r.status == TaskRunStatus.FAILED)
    skipped = sum(1 for r in self.records if r.status == TaskRunStatus.SKIPPED)
    # ... print summary with all three counts ...
```

**Changes to `step3_execute.py`:**

```python
import threading
from concurrent.futures import CancelledError

def _execute_parallel_fallback(...) -> list[str]:
    failed_tasks: list[str] = []
    skipped_tasks: list[str] = []
    stop_flag = threading.Event()

    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool | None]:
        """Returns (task, success) where success=None means skipped."""
        idx, task = task_info
        if stop_flag.is_set():
            return task, None  # Skipped
        # ... existing execution logic ...
        return task, success

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, task in enumerate(tasks):
            if stop_flag.is_set():
                skipped_tasks.append(task.name)
                continue
            futures[executor.submit(execute_single_task, (i, task))] = task

        for future in as_completed(futures):
            task = futures[future]
            try:
                _, success = future.result()
            except CancelledError:
                skipped_tasks.append(task.name)
                continue

            if success is None:
                skipped_tasks.append(task.name)
            elif success:
                mark_task_complete(tasklist_path, task.name)
                state.mark_task_complete(task.name)
            else:
                failed_tasks.append(task.name)
                if state.fail_fast:
                    stop_flag.set()
                    for f in futures:
                        f.cancel()

    return failed_tasks
```

---

### Fix E: Task Ordering Stability

**Change `get_fundamental_tasks` in `tasks.py`:**
```python
def get_fundamental_tasks(tasks: list[Task]) -> list[Task]:
    fundamental = [t for t in tasks if t.category == TaskCategory.FUNDAMENTAL]
    # Stable sort: (explicit_first, dependency_order, line_number)
    return sorted(fundamental, key=lambda t: (
        0 if t.dependency_order > 0 else 1,  # Explicit order=1-N before order=0
        t.dependency_order,
        t.line_number  # Tie-breaker preserves file order
    ))
```

---

### Fix F: Log Buffer Lifecycle

**Wrap task execution in try/finally in `step3_execute.py`:**
```python
def execute_single_task_tui(task_info):
    idx, task = task_info
    record = tui.get_record(idx)
    success = False

    try:
        start_event = create_task_started_event(idx, task.name)
        tui.post_event(start_event)
        success = _execute_task_with_retry(...)
    finally:
        duration = record.elapsed_time if record else 0.0
        finish_event = create_task_finished_event(
            idx, task.name, success, duration,
            error=None if success else "Task failed or crashed"
        )
        tui.post_event(finish_event)

    return idx, task, success
```

---

### Fix G: Task Memory in Parallel Mode (Revised)

**Problem:** Deferring capture until after all tasks complete still reads a combined `git diff --cached` that mixes all changes. This does NOT prevent contamination.

**MVP Solution (Chosen): Disable memory capture for parallel tasks**
```python
# In _execute_parallel_fallback and _execute_parallel_with_tui:
# DON'T call capture_task_memory() for parallel tasks at all

if success:
    mark_task_complete(tasklist_path, task.name)
    state.mark_task_complete(task.name)
    # Memory capture disabled for parallel tasks (contamination risk)
    # Log this decision:
    print_info(f"[PARALLEL] Completed: {task.name} (memory capture skipped)")
```

**Why this is MVP-safe:** Task memory is used for cross-task learning and analytics. Disabling it for parallel tasks loses some analytics value but prevents incorrect attribution. Sequential/fundamental tasks still capture memory correctly.

**Follow-up (post-MVP):** Implement true isolation via one of:
1. **File-set based capture**: Track which files each task touched (via git diff before/after per task)
2. **Git worktree isolation**: Each parallel task runs in a separate worktree

**Update Acceptance Criteria:**
- Parallel tasks must NOT call `capture_task_memory()`
- Add log message indicating memory capture is skipped for parallel tasks

---

### Fix H: group_id Decision (Explicit)

**Decision: Option A – Keep for UI labeling only**

**Rationale:** The original spec and Step 2 prompt introduce `group:` tags. Removing them would require updating the prompt and breaking existing task lists. Keeping them for UI labeling is low-cost and provides future extensibility.

**Changes:**

1. **Keep** `group_id` in `Task` dataclass and parsing logic
2. **Update documentation** in original spec to clarify: "Group tags are informational labels for UI display only. No scheduler semantics in MVP."
3. **TUI enhancement (optional, low priority):** Display group label in task list if present

**No conflict with original spec:** The original spec says `group:` is for "grouping parallel tasks" – we clarify this means visual grouping, not execution grouping.

---

### Fix J: Thread-Safety of Shared Clients/State (ALREADY SATISFIED)

**Findings after code review:**
- `AuggieClient` is created per call in `_execute_task_with_callback` (line 730) – **OK**
- `WorkflowState.mark_task_complete()` is called from the `as_completed` loop, which runs on the **main thread** – **OK**
- `mark_task_complete(tasklist_path, ...)` is also called from the main thread – **OK**

**Verification:** In both `_execute_parallel_fallback` (lines 521-534) and `_execute_parallel_with_tui` (lines 622-637), the `as_completed` loop runs on the main thread. Worker threads only execute tasks and return results; they do NOT call `mark_task_complete` or mutate `state`.

**No additional fix needed.** The current implementation is already thread-safe for state mutations.

---

### Fix K: Git Contention Policy (NEW)

**Problem:** Parallel tasks may run `git add`, `git commit` which contends on `.git/index`.

**Policy (MVP): Parallel tasks MUST NOT stage/commit**

**Enforcement via agent prompt** – update `_build_task_prompt` in `step3_execute.py`:

```python
def _build_task_prompt(task: Task, plan_path: Path, is_parallel: bool = False) -> str:
    base_prompt = f"""Execute this task.

Task: {task.name}

The implementation plan is at: {plan_path}
Use codebase-retrieval to read the plan and focus on the section relevant to this task."""

    # Add parallel-specific restrictions
    if is_parallel:
        base_prompt += """

IMPORTANT: This task runs in parallel with other tasks.
- Do NOT run `git add`, `git commit`, or `git push`
- Do NOT stage any changes
- Only make file modifications; staging/committing will be done after all tasks complete"""

    base_prompt += "\n\nDo NOT commit or push any changes."
    return base_prompt
```

**Pass `is_parallel=True`** when calling from parallel execution functions.

**Acceptance Criteria:**
- Parallel task prompts include git restriction
- Test that parallel task prompt contains "Do NOT run `git add`"

---

## Test Plan

### Test Determinism Requirements

**Mocking for retry tests:** The retry utilities use `time.sleep()` and `random.uniform()` for exponential backoff with jitter. To ensure tests are fast and deterministic:

1. **Mock `time.sleep`** to avoid actual delays:
   ```python
   @patch('ai_workflow.workflow.retry_utils.time.sleep')
   def test_retry_triggers_on_rate_limit_error(mock_sleep):
       # Test runs instantly, mock_sleep.call_count verifies retry attempts
   ```

2. **Seed or mock `random.uniform`** for deterministic jitter:
   ```python
   @patch('ai_workflow.workflow.retry_utils.random.uniform', return_value=0.5)
   def test_retry_delay_calculation(mock_random):
       # Jitter is now deterministic
   ```

3. **Alternative: Use a test-friendly retry config** with `max_retries=0` for tests that don't need retry behavior.

### Test Matrix

| Test | File | Purpose |
|------|------|---------|
| `test_max_parallel_override_none_uses_config` | `tests/test_cli.py` | `None` → uses config value |
| `test_max_parallel_override_explicit` | `tests/test_cli.py` | `--max-parallel 2` overrides config=5 |
| `test_fail_fast_no_flag_overrides_config` | `tests/test_cli.py` | `--no-fail-fast` overrides config=True |
| `test_rate_limit_config_validation` | `tests/test_state.py` | Invalid values raise ValueError |
| `test_looks_like_rate_limit_patterns` | `tests/test_auggie.py` | Classifier detects 429, 502-504, keywords |
| `test_looks_like_rate_limit_exit_zero_false` | `tests/test_auggie.py` | Exit code 0 → False |
| `test_execute_task_raises_on_rate_limit` | `tests/test_step3_execute.py` | `_execute_task_with_callback` raises `AuggieRateLimitError` |
| `test_retry_triggers_on_rate_limit_error` | `tests/test_retry.py` | Integration: exception triggers retry (mock `time.sleep`) |
| `test_tui_post_event_thread_safe` | `tests/test_tui.py` | Multi-threaded posting works |
| `test_tui_drain_queue_on_refresh` | `tests/test_tui.py` | Events processed on refresh |
| `test_fail_fast_skips_pending_tasks` | `tests/test_step3_execute.py` | Pending tasks → SKIPPED |
| `test_fail_fast_handles_cancelled_error` | `tests/test_step3_execute.py` | CancelledError → SKIPPED |
| `test_task_ordering_stability` | `tests/test_workflow_tasks.py` | Mixed order=0 and order>0 |
| `test_parallel_task_memory_skipped` | `tests/test_step3_execute.py` | No capture_task_memory call |
| `test_parallel_prompt_git_restrictions` | `tests/test_step3_execute.py` | Prompt contains git restrictions |
| `test_sequential_uses_retry` | `tests/test_step3_execute.py` | Sequential mode calls `_execute_task_with_retry` |

---

## Acceptance Criteria

1. **CLI:** `--max-parallel 3` works when config=5; `--no-fail-fast` overrides config `fail_fast: true`; effective values validated
2. **Retry:** Rate limit errors (429, 502-504, keywords) trigger exponential backoff; non-rate-limit errors fail immediately; retry applies to BOTH sequential and parallel execution
3. **TUI:** No race conditions; workers use `post_event()`; main thread drains queue via explicit pump loop
4. **fail_fast:** First failure stops new submissions; pending marked SKIPPED; CancelledError handled; SKIPPED represented as tri-state status in events
5. **Ordering:** Tasks with order=0 appear after explicit orders, preserving file order as tie-breaker
6. **Log buffers:** Always closed via try/finally
7. **Memory:** Parallel tasks skip memory capture; log message indicates skipped
8. **group_id:** Retained for UI labeling; no scheduler semantics in MVP
9. **Thread-safety:** Already satisfied – state mutations happen on main thread in `as_completed` loop
10. **Git contention:** Parallel task prompts include git restrictions
11. **Tests:** All new behaviors have passing tests; retry tests mock `time.sleep` for speed

---

## Implementation Priority

1. **Critical (blocks correctness):** B (retry mechanism), B+ (retry in sequential), D (fail_fast + SKIPPED), K (git contention)
2. **High (user-facing bugs):** A (CLI override), C (TUI thread-safety with pump loop)
3. **Medium (reliability):** E (ordering), F (buffer leaks), G (memory skipping)
4. **Low (cleanup):** H (group_id docs), J (already satisfied - document only)

