# Test Coverage Improvement Specification

## Overview

This document outlines the missing tests for the `spec/workflow` module. The analysis compares each source file against existing test files to identify gaps in test coverage.

---

## Summary of Current Coverage

| Module | Source File | Test File | Coverage Status |
|--------|-------------|-----------|-----------------|
| state | `state.py` | `test_workflow_state.py` | ✅ Good coverage |
| tasks | `tasks.py` | `test_workflow_tasks.py` | ✅ Good coverage |
| events | `events.py` | `test_workflow_events.py` | ✅ Good coverage |
| task_memory | `task_memory.py` | `test_task_memory.py` | ✅ Good coverage |
| step2_tasklist | `step2_tasklist.py` | `test_step2_tasklist.py` | ⚠️ Partial coverage |
| step1_plan | `step1_plan.py` | ❌ Missing | ❌ No dedicated tests |
| step3_execute | `step3_execute.py` | ❌ Missing | ❌ No dedicated tests |
| runner | `runner.py` | ❌ Missing | ❌ No dedicated tests |

---

## Priority 1: Missing Test Files (Critical)

### 1.1 `tests/test_step1_plan.py` - NEW FILE NEEDED

The `step1_plan.py` module has **0 dedicated tests**. Only `_build_plan_prompt` is tested indirectly in integration tests.

#### Functions to Test:

**`_get_log_base_dir()`**
- Test default returns `Path(".spec/runs")`
- Test respects `SPEC_LOG_DIR` environment variable

**`_create_plan_log_dir(ticket_id: str)`**
- Test creates directory with correct structure (`{base}/ticket_id/plan_generation`)
- Test directory is created with `parents=True`
- Test returns correct `Path` object

**`_generate_plan_with_tui(state, prompt, plan_path)`**
- Test returns `True` on successful generation
- Test returns `False` when user requests quit (via `ui.quit_requested`)
- Test log path is set on UI
- Test Auggie client is called with correct model

**`_generate_plan_fallback(state, prompt)`**
- Test returns `True` on success
- Test returns `False` on failure
- Test uses correct planning model

**`step_1_create_plan(state, auggie)`**
- Test creates specs directory if not exists
- Test calls `_generate_plan_with_tui` in TUI mode
- Test calls `_generate_plan_fallback` in non-TUI mode
- Test returns `False` when plan generation fails
- Test saves plan file on success
- Test calls `_save_plan_from_output` when plan file not created
- Test calls `_run_clarification` when `skip_clarification=False`
- Test skips clarification when `skip_clarification=True`
- Test returns `True` when plan confirmed
- Test returns `False` when plan rejected
- Test updates `state.current_step` to 2 on success

**`_run_clarification(state, auggie, plan_path)`**
- Test returns `True` when user declines clarification prompt
- Test runs Auggie with correct clarification prompt
- Test always returns `True` (even on Auggie failure)

**`_build_plan_prompt(state)`**
- ✅ Already tested in `test_integration_workflow.py`
- Add edge cases: empty title, empty description

**`_save_plan_from_output(plan_path, state)`**
- Test creates template with ticket ID
- Test writes to correct path
- Test includes all template sections

**`_display_plan_summary(plan_path)`**
- Test reads file correctly
- Test limits preview to 20 lines
- Test handles short files

---

### 1.2 `tests/test_step3_execute.py` - NEW FILE NEEDED

The `step3_execute.py` module has **0 dedicated tests**.

#### Functions to Test:

**`_get_log_base_dir()`**
- Test default returns `Path(".spec/runs")`
- Test respects `SPEC_LOG_DIR` environment variable

**`_create_run_log_dir(ticket_id: str)`**
- Test creates timestamped directory
- Test creates parent directories
- Test returns correct `Path`

**`_cleanup_old_runs(ticket_id, keep_count)`**
- Test removes directories beyond `keep_count`
- Test keeps newest directories
- Test handles non-existent ticket directory
- Test ignores cleanup errors gracefully

**`step_3_execute(state, use_tui, verbose)`**
- Test returns `False` when tasklist not found
- Test returns `True` when all tasks already complete
- Test calls `_execute_with_tui` when TUI mode
- Test calls `_execute_fallback` when non-TUI mode
- Test prompts user on task failures
- Test returns `True` when all tasks succeed
- Test returns `False` when any task fails
- Test calls `_show_summary`
- Test calls `_run_post_implementation_tests`
- Test calls `_offer_commit_instructions`

**`_execute_with_tui(state, pending, plan_path, tasklist_path, log_dir, verbose)`**
- Test initializes TUI correctly
- Test creates log buffers for each task
- Test handles quit request before task starts
- Test handles quit request during task execution
- Test marks tasks complete on success
- Test tracks failed tasks
- Test calls `capture_task_memory` on success
- Test handles `capture_task_memory` exceptions gracefully
- Test respects `fail_fast` option
- Test returns list of failed task names

**`_execute_fallback(state, pending, plan_path, tasklist_path, log_dir)`**
- Test executes tasks sequentially
- Test creates log buffer for each task
- Test marks tasks complete on success
- Test tracks failed tasks
- Test calls `capture_task_memory` on success
- Test handles `capture_task_memory` exceptions gracefully
- Test respects `fail_fast` option
- Test returns list of failed task names

**`_build_task_prompt(task, plan_path)`**
- Test prompt includes task name
- Test prompt includes plan path when exists
- Test prompt excludes plan path when not exists
- Test prompt includes retrieval instructions

**`_execute_task(state, task, plan_path)`**
- Test returns `True` on Auggie success
- Test returns `False` on Auggie failure
- Test returns `False` on exception
- Test uses correct implementation model

**`_execute_task_with_callback(state, task, plan_path, callback)`**
- Test returns `True` on success
- Test returns `False` on failure
- Test callback is called with output lines
- Test callback receives error message on exception

**`_show_summary(state, failed_tasks)`**
- Test displays ticket ID
- Test displays branch name
- Test displays completed task count
- Test displays checkpoint count
- Test displays failed task names when present

**`_run_post_implementation_tests(state)`**
- Test prompts user to run tests
- Test skips when user declines
- Test runs Auggie with test prompt
- Test handles Auggie exceptions

**`_offer_commit_instructions(state)`**
- Test does nothing when no dirty files
- Test prompts user for instructions
- Test does nothing when user declines
- Test prints commit commands when accepted

---

### 1.3 `tests/test_workflow_runner.py` - NEW FILE NEEDED

The `runner.py` module has **0 dedicated tests**.

#### Functions to Test:

**`run_spec_driven_workflow(ticket, config, ...)`**
- Test initializes WorkflowState correctly
- Test handles dirty state at start
- Test fetches ticket info
- Test handles fetch_ticket_info failure gracefully
- Test prompts for additional user context
- Test stores user context in state
- Test sets up branch correctly
- Test records base commit
- Test calls step_1_create_plan
- Test calls step_2_create_tasklist
- Test calls step_3_execute
- Test returns `False` when any step fails
- Test returns `True` when all steps succeed
- Test shows completion on success

**`_setup_branch(state, ticket)`**
- Test generates branch name with summary
- Test generates branch name without summary (fallback)
- Test stays on current branch if already on feature branch
- Test creates new branch when confirmed
- Test returns `False` on branch creation failure
- Test stays on current branch when user declines
- Test updates `state.branch_name`

**`_show_completion(state)`**
- Test displays all completion information
- Test displays plan file if exists
- Test displays tasklist file if exists
- Test prints next steps

**`workflow_cleanup(state)` context manager**
- Test yields normally on success
- Test catches `UserCancelledError` and offers cleanup
- Test catches `SpecError` and offers cleanup
- Test catches generic exceptions and offers cleanup
- Test stores original branch

**`_offer_cleanup(state, original_branch)`**
- Test prints checkpoint commit count
- Test prints branch information when different from original

---

## Priority 2: Existing Test File Gaps

### 2.1 `tests/test_step2_tasklist.py` - ADD MORE TESTS

**Missing tests for `_display_tasklist(tasklist_path)`**
- Test reads file content
- Test parses tasks correctly
- Test prints task count

**Missing tests for `_edit_tasklist(tasklist_path)`**
- Test opens editor with correct path
- Test handles editor success
- Test handles editor failure (CalledProcessError)
- Test handles missing editor (FileNotFoundError)
- Test uses EDITOR environment variable

**Missing tests for `_create_default_tasklist(tasklist_path, state)`**
- Test creates file with correct template
- Test includes ticket ID in header
- Test writes placeholder tasks

**Missing edge cases for `step_2_create_tasklist`**
- Test returns `False` when plan file not found
- Test retries on generation failure

---

### 2.2 `tests/test_workflow_state.py` - ADD MORE TESTS

**Missing tests:**
- Test `fail_fast` default value (False)
- Test `planning_model` and `implementation_model` defaults
- Test `task_memories` list initialization
- Test `get_tasklist_path` with override

---

### 2.3 `tests/test_workflow_tasks.py` - ADD MORE TESTS

**Missing edge cases for `parse_task_list`**
- Test deeply nested tasks (3+ levels)
- Test mixed indentation styles
- Test empty content
- Test content with only headers

**Missing edge cases for `mark_task_complete`**
- Test returns `False` when task not found
- Test handles task with special characters in name

---

## Priority 3: Integration Test Improvements

### 3.1 `tests/test_integration_workflow.py` - ADD MORE TESTS

**Missing end-to-end scenarios:**
- Test complete workflow from step 1 to step 3
- Test workflow resumption from step 2
- Test workflow resumption from step 3
- Test workflow with fail_fast enabled
- Test workflow with squash_at_end enabled

**Missing error handling scenarios:**
- Test workflow handles Auggie client failures
- Test workflow handles git command failures
- Test workflow handles file system errors

---

## Implementation Recommendations

### Test File Structure

For each new test file, use the following structure:

```python
"""Tests for spec.workflow.{module} module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import module under test
from spec.workflow.{module} import (
    function1,
    function2,
)


@pytest.fixture
def mock_workflow_state(tmp_path):
    """Create a mock workflow state for testing."""
    # Setup fixtures here
    pass


class TestFunction1:
    """Tests for function1."""

    def test_basic_functionality(self):
        """Basic case works correctly."""
        pass

    def test_edge_case(self):
        """Edge case is handled."""
        pass

    def test_error_handling(self):
        """Errors are handled gracefully."""
        pass
```

### Mocking Strategy

1. **External dependencies** (git, Auggie CLI): Always mock
2. **File system**: Use `tmp_path` fixture
3. **User prompts**: Mock with `patch`
4. **TUI components**: Mock entire TUI classes
5. **Environment variables**: Use `monkeypatch.setenv()`

### Test Categories

Each function should have tests for:

1. **Happy path**: Normal successful execution
2. **Edge cases**: Boundary conditions, empty inputs
3. **Error handling**: Exceptions, failures, invalid inputs
4. **Integration points**: Mock external dependencies

---

## Estimated Test Count

| Test File | Estimated Test Cases |
|-----------|---------------------|
| `test_step1_plan.py` (NEW) | ~25 tests |
| `test_step3_execute.py` (NEW) | ~40 tests |
| `test_workflow_runner.py` (NEW) | ~20 tests |
| `test_step2_tasklist.py` (ADD) | ~8 tests |
| `test_workflow_state.py` (ADD) | ~4 tests |
| `test_workflow_tasks.py` (ADD) | ~5 tests |
| `test_integration_workflow.py` (ADD) | ~8 tests |
| **TOTAL** | **~110 new tests** |

---

## Execution Order

1. **Phase 1**: Create `test_step3_execute.py` (highest complexity, most critical)
2. **Phase 2**: Create `test_step1_plan.py`
3. **Phase 3**: Create `test_workflow_runner.py`
4. **Phase 4**: Add missing tests to existing files
5. **Phase 5**: Add integration test scenarios

---

## Notes

- All tests should use `pytest` conventions
- Use `unittest.mock` for mocking dependencies
- Use `tmp_path` fixture for file system operations
- Keep tests isolated - no shared state between tests
- Mock external CLI tools (git, auggie) to ensure tests run in CI
- Consider adding test fixtures to `conftest.py` for reuse

