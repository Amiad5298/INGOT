# Parallel Execution Unit Tests Specification

## Overview

This document specifies the unit tests needed to cover the parallel task execution feature implemented in the AI-Platform workflow system. The current test coverage for new modules is:

| Module | Current Coverage | Target |
|--------|-----------------|--------|
| `utils/retry.py` | 19% | 90%+ |
| `workflow/step3_execute.py` | 64% | 80%+ |
| `workflow/tasks.py` | 85% | 95%+ |
| `ui/tui.py` | 18% | 50%+ |
| `cli.py` | 36% | 60%+ |

---

## 1. Retry Utility Tests (`tests/test_retry.py`)

### 1.1 RateLimitExceededError Tests
```python
class TestRateLimitExceededError:
    def test_creates_exception_with_message(self):
        """Exception stores message correctly"""
    
    def test_creates_exception_with_retry_after(self):
        """Exception stores retry_after value"""
    
    def test_retry_after_defaults_to_none(self):
        """retry_after is None when not provided"""
```

### 1.2 Backoff Delay Calculation Tests
```python
class TestCalculateBackoffDelay:
    def test_first_attempt_uses_base_delay(self):
        """Attempt 0 returns approximately base_delay"""
    
    def test_delay_increases_exponentially(self):
        """Each attempt roughly doubles the delay"""
    
    def test_delay_respects_max_delay(self):
        """Delay never exceeds max_delay_seconds"""
    
    def test_jitter_adds_randomness(self):
        """Same attempt returns different values (jitter)"""
    
    def test_zero_jitter_returns_exact_delay(self):
        """With jitter_factor=0, returns exact exponential delay"""
    
    def test_custom_config_values(self):
        """Uses values from provided RateLimitConfig"""
```

### 1.3 Retryable Error Detection Tests
```python
class TestIsRetryableError:
    def test_detects_429_status_code(self):
        """HTTP 429 is retryable"""
    
    def test_detects_502_status_code(self):
        """HTTP 502 Bad Gateway is retryable"""
    
    def test_detects_503_status_code(self):
        """HTTP 503 Service Unavailable is retryable"""
    
    def test_detects_504_status_code(self):
        """HTTP 504 Gateway Timeout is retryable"""
    
    def test_detects_rate_limit_text(self):
        """'rate limit' in message is retryable"""
    
    def test_regular_error_not_retryable(self):
        """Normal exceptions are not retryable"""
    
    def test_custom_status_codes(self):
        """Respects custom retryable_status_codes in config"""
```

### 1.4 Retry Decorator Tests
```python
class TestWithRateLimitRetry:
    def test_returns_result_on_success(self):
        """Decorated function returns normally on success"""
    
    def test_retries_on_retryable_error(self):
        """Retries when retryable error occurs"""
    
    def test_raises_after_max_retries(self):
        """Raises RateLimitExceededError after max retries"""
    
    def test_calls_on_retry_callback(self):
        """Calls on_retry callback with attempt info"""
    
    def test_respects_retry_after_header(self):
        """Uses retry_after from exception if available"""
    
    def test_non_retryable_error_raises_immediately(self):
        """Non-retryable errors are not retried"""
```

---

## 2. Task Category Tests (`tests/test_workflow_tasks.py`)

### 2.1 TaskCategory Enum Tests
```python
class TestTaskCategory:
    def test_fundamental_value(self):
        """FUNDAMENTAL has correct string value"""
    
    def test_independent_value(self):
        """INDEPENDENT has correct string value"""
```

### 2.2 Metadata Parsing Tests
```python
class TestParseTaskMetadata:
    def test_parses_fundamental_category(self):
        """Parses 'category: fundamental' correctly"""
    
    def test_parses_independent_category(self):
        """Parses 'category: independent' correctly"""
    
    def test_parses_order_field(self):
        """Parses 'order: N' correctly"""
    
    def test_parses_group_field(self):
        """Parses 'group: name' correctly"""
    
    def test_handles_missing_metadata(self):
        """Returns defaults when no metadata comment"""
    
    def test_handles_partial_metadata(self):
        """Handles metadata with only some fields"""
    
    def test_case_insensitive_parsing(self):
        """Parses 'Category: FUNDAMENTAL' correctly"""
```

### 2.3 Task Filtering Tests
```python
class TestGetFundamentalTasks:
    def test_returns_only_fundamental_tasks(self):
        """Filters to fundamental category only"""
    
    def test_returns_empty_when_none_exist(self):
        """Returns empty list when no fundamental tasks"""
    
    def test_preserves_order(self):
        """Tasks returned in dependency_order"""

class TestGetIndependentTasks:
    def test_returns_only_independent_tasks(self):
        """Filters to independent category only"""
    
    def test_returns_empty_when_none_exist(self):
        """Returns empty list when no independent tasks"""

class TestGetPendingFundamentalTasks:
    def test_excludes_completed_tasks(self):
        """Only returns non-completed fundamental tasks"""
    
    def test_excludes_failed_tasks(self):
        """Only returns non-failed fundamental tasks"""

class TestGetPendingIndependentTasks:
    def test_excludes_completed_tasks(self):
        """Only returns non-completed independent tasks"""
```

---

## 3. Step 3 Execution Tests (`tests/test_step3_execute.py`)

### 3.1 Two-Phase Execution Tests
```python
class TestTwoPhaseExecution:
    def test_executes_fundamental_tasks_first(self):
        """Fundamental tasks run before independent tasks"""

    def test_fundamental_tasks_run_sequentially(self):
        """Fundamental tasks execute one at a time"""

    def test_independent_tasks_run_in_parallel(self):
        """Independent tasks execute concurrently"""

    def test_skips_parallel_phase_when_disabled(self):
        """Respects parallel_execution_enabled=False"""
```

### 3.2 Parallel Execution Tests
```python
class TestExecuteParallelFallback:
    def test_limits_concurrent_tasks(self):
        """Respects max_parallel_tasks limit"""

    def test_executes_all_pending_tasks(self):
        """All pending independent tasks are executed"""

    def test_collects_results_correctly(self):
        """Returns correct success/failure counts"""

    def test_handles_task_failure(self):
        """Continues execution when a task fails"""

    def test_fail_fast_stops_on_first_failure(self):
        """Stops execution when fail_fast=True and task fails"""

class TestExecuteParallelWithTui:
    def test_updates_tui_for_running_tasks(self):
        """TUI shows correct running indicators"""

    def test_respects_max_parallel_limit(self):
        """Never exceeds max_parallel_tasks"""

    def test_handles_keyboard_interrupt(self):
        """Gracefully handles Ctrl+C during execution"""
```

### 3.3 Task Retry Tests
```python
class TestExecuteTaskWithRetry:
    def test_returns_success_on_first_try(self):
        """Returns True when task succeeds immediately"""

    def test_retries_on_rate_limit(self):
        """Retries task when rate limited"""

    def test_returns_false_after_max_retries(self):
        """Returns False after exhausting retries"""

    def test_logs_retry_attempts(self):
        """Logs info about retry attempts"""

    def test_non_rate_limit_error_not_retried(self):
        """Regular errors fail immediately"""
```

---

## 4. TUI Parallel Mode Tests (`tests/test_tui.py`)

### 4.1 Parallel Mode State Tests
```python
class TestTuiParallelMode:
    def test_parallel_mode_defaults_to_false(self):
        """parallel_mode is False initially"""

    def test_set_parallel_mode_enables(self):
        """set_parallel_mode(True) enables parallel mode"""

    def test_set_parallel_mode_disables(self):
        """set_parallel_mode(False) disables parallel mode"""

    def test_running_task_indices_tracked(self):
        """_running_task_indices updates correctly"""

    def test_get_running_count_returns_correct_count(self):
        """_get_running_count() returns number of running tasks"""
```

### 4.2 Render Function Tests
```python
class TestRenderTaskListParallel:
    def test_shows_parallel_indicator_for_running_tasks(self):
        """Running tasks show ⟳ indicator in parallel mode"""

    def test_no_indicator_in_sequential_mode(self):
        """No special indicator when parallel_mode=False"""

    def test_multiple_running_tasks_shown(self):
        """Multiple concurrent tasks displayed correctly"""

class TestRenderStatusBarParallel:
    def test_shows_parallel_task_count(self):
        """Status bar shows 'Running N tasks' in parallel mode"""

    def test_singular_task_count(self):
        """Shows 'Running 1 task' when single task running"""
```

---

## 5. CLI Flag Tests (`tests/test_cli.py`)

### 5.1 Parallel Execution Flags
```python
class TestParallelFlags:
    def test_parallel_flag_enables_parallel(self):
        """--parallel sets parallel_execution_enabled=True"""

    def test_no_parallel_flag_disables(self):
        """--no-parallel sets parallel_execution_enabled=False"""

    def test_max_parallel_sets_value(self):
        """--max-parallel=5 sets max_parallel_tasks=5"""

    def test_max_parallel_validates_range(self):
        """--max-parallel rejects values outside 1-5"""

    def test_fail_fast_flag(self):
        """--fail-fast sets fail_fast=True"""
```

### 5.2 Retry Flags
```python
class TestRetryFlags:
    def test_max_retries_sets_value(self):
        """--max-retries=3 sets config value"""

    def test_max_retries_zero_disables(self):
        """--max-retries=0 disables retries"""

    def test_retry_base_delay_sets_value(self):
        """--retry-base-delay=5.0 sets config value"""
```

---

## 6. Configuration Tests (`tests/test_settings.py`)

### 6.1 Parallel Settings
```python
class TestParallelSettings:
    def test_parallel_execution_enabled_default(self):
        """parallel_execution_enabled defaults to True"""

    def test_max_parallel_tasks_default(self):
        """max_parallel_tasks defaults to 3"""

    def test_fail_fast_default(self):
        """fail_fast defaults to False"""

    def test_loads_from_config_file(self):
        """Settings loaded from .aiworkflowrc file"""
```

---

## 7. State Tests (`tests/test_workflow_state.py`)

### 7.1 RateLimitConfig Tests
```python
class TestRateLimitConfig:
    def test_default_max_retries(self):
        """max_retries defaults to 5"""

    def test_default_base_delay(self):
        """base_delay_seconds defaults to 2.0"""

    def test_default_max_delay(self):
        """max_delay_seconds defaults to 60.0"""

    def test_default_jitter_factor(self):
        """jitter_factor defaults to 0.5"""

    def test_default_retryable_status_codes(self):
        """retryable_status_codes includes 429, 502, 503, 504"""

    def test_custom_values(self):
        """Custom values are stored correctly"""
```

### 7.2 WorkflowState Parallel Fields
```python
class TestWorkflowStateParallelFields:
    def test_max_parallel_tasks_default(self):
        """max_parallel_tasks defaults to 3"""

    def test_parallel_execution_enabled_default(self):
        """parallel_execution_enabled defaults to True"""

    def test_parallel_tasks_completed_default(self):
        """parallel_tasks_completed defaults to 0"""

    def test_parallel_tasks_failed_default(self):
        """parallel_tasks_failed defaults to 0"""

    def test_fail_fast_default(self):
        """fail_fast defaults to False"""

    def test_rate_limit_config_default(self):
        """rate_limit_config is RateLimitConfig instance"""
```

---

## Implementation Priority

### High Priority (Core Functionality)
1. `tests/test_retry.py` - New file, critical for rate limiting
2. `TestParseTaskMetadata` - Task categorization
3. `TestTwoPhaseExecution` - Core execution flow
4. `TestRateLimitConfig` - Configuration validation

### Medium Priority (Integration)
5. `TestExecuteParallelFallback` - Non-TUI parallel execution
6. `TestParallelFlags` - CLI integration
7. `TestGetFundamentalTasks` / `TestGetIndependentTasks` - Task filtering

### Lower Priority (UI/UX)
8. `TestTuiParallelMode` - TUI state management
9. `TestRenderTaskListParallel` - Visual indicators
10. `TestRenderStatusBarParallel` - Status display

---

## Test Data Fixtures

```python
# Suggested fixtures for tests/conftest.py

@pytest.fixture
def sample_tasks_with_categories():
    """Tasks with mixed categories for testing"""
    return [
        Task(name="Schema", status=TaskStatus.PENDING,
             category=TaskCategory.FUNDAMENTAL, dependency_order=1),
        Task(name="Service", status=TaskStatus.PENDING,
             category=TaskCategory.FUNDAMENTAL, dependency_order=2),
        Task(name="UI Component", status=TaskStatus.PENDING,
             category=TaskCategory.INDEPENDENT, group_id="ui"),
        Task(name="Utils", status=TaskStatus.PENDING,
             category=TaskCategory.INDEPENDENT, group_id="utils"),
    ]

@pytest.fixture
def rate_limit_config():
    """Standard rate limit config for testing"""
    return RateLimitConfig(
        max_retries=3,
        base_delay_seconds=0.1,  # Fast for tests
        max_delay_seconds=1.0,
        jitter_factor=0.0,  # Deterministic for tests
    )

@pytest.fixture
def mock_auggie_client():
    """Mocked AuggieClient for task execution tests"""
    client = MagicMock()
    client.run.return_value = True
    return client
```

---

## Estimated Test Count

| Test File | Test Count |
|-----------|------------|
| `test_retry.py` | 18 tests |
| `test_workflow_tasks.py` (additions) | 15 tests |
| `test_step3_execute.py` | 12 tests |
| `test_tui.py` (additions) | 8 tests |
| `test_cli.py` (additions) | 8 tests |
| `test_workflow_state.py` (additions) | 12 tests |
| **Total** | **~73 new tests** |

