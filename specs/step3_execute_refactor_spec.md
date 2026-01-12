# Technical Specification: Step 3 Execute Refactor

## Overview

**Goal:** Transform `step3_execute.py` from a "Defensive Execution" model to an "Optimistic Execution" model.

**Philosophy:** Trust the AI. If it returns success, it succeeded. Don't nanny it with file checks and retry loops.

**Constraint:** Maintain isolation (`dont_save_session=True`) - this is correct for quality.

---

## Current Bottlenecks (Confirmed)

| Bottleneck | Location | Impact |
|------------|----------|--------|
| False Negative Retries | `_verify_task_completion` (lines 259-290) | Forces retries even when AI succeeds but no files change |
| Context Bloat | `_generate_file_tree` (lines 344-411) | 200+ lines of file tree injected into every prompt |
| I/O Overhead | Main loop (lines 504-509) | Git commit after EVERY task |

---

## Changes Required

### 1. DELETE: Functions to Remove Entirely

These functions are part of the "nanny" logic and must be **deleted**:

| Function | Lines | Reason for Deletion |
|----------|-------|---------------------|
| `_verify_task_completion` | 259-290 | Distrusts AI exit code, forces useless retries |
| `_get_modified_files_list` | 201-221 | Only used by `_verify_task_completion` |
| `_filter_relevant_files` | 224-256 | Only used by `_verify_task_completion` |
| `_generate_file_tree` | 344-411 | Heavy context injection, AI has codebase-retrieval |
| `_build_error_context` | 177-198 | Complex error formatting for retry loops we're removing |

### 2. SIMPLIFY: `_execute_task` Function

**Current:** Complex retry loop with verification after each attempt.

**New:** Single execution, trust exit code, only retry on crashes/exceptions.

```python
def _execute_task(
    state: WorkflowState,
    task: Task,
    auggie: AuggieClient,
    plan_content: str,
) -> bool:
    """Execute a single task in clean context. Optimistic execution.
    
    Trust the AI: if it returns success, the task is done.
    Only retry on actual exceptions/crashes, not "no files modified".
    """
    task_context = _extract_task_context(plan_content, task)
    
    prompt = f"""Execute this task:

Task: {task.name}

Context from plan:
{task_context}

Implement completely. You have access to codebase-retrieval for finding patterns."""

    auggie_client = AuggieClient(model=state.implementation_model)
    
    try:
        success, output = auggie_client.run_print_with_output(
            prompt, 
            dont_save_session=True
        )
        return success
    except Exception as e:
        print_error(f"Task crashed: {e}")
        return False
```

**Key Changes:**
- No retry loop
- No file verification
- No `_build_error_context`
- No `pattern_context` injection (keep task memory capture, but don't inject as prompt bloat)
- Minimal prompt (no file tree, no DEFINITION OF DONE paragraph)

### 3. 3. OPTIMIZE: Prompt Context

Current: Heavy ASCII file tree + Pattern Context. New: Inject a minimal flat list of source file paths to guide file placement.

Do not read file content.

Do not use ASCII tree characters.

Filter: Only show source files (e.g., .py, .ts, .java), exclude configs/tests if irrelevant.
Example Python Implementation:
'''python
def _get_file_paths(root: Path) -> str:
    # Quick, cheap list of relative paths
    # e.g., "src/main.py\nsrc/utils/helpers.py"
    paths = [
        str(p.relative_to(root)) 
        for p in root.rglob("*") 
        if p.is_file() and not p.name.startswith(".") and "__" not in p.parts
    ]
    return "\n".join(sorted(paths)[:100]) # Limit to 100 files to stay light
    '''
Prompt update:
Project Files:
{file_paths}

Use codebase-retrieval to read specific file contents.

### 4. CHANGE: Commit Strategy

**Current:** Commit after every task (N commits for N tasks).

**New:** Single commit at the end of all tasks.

```python
# In step_3_execute main loop:
for task in pending:
    success = _execute_task(state, task, auggie, plan_content)
    if success:
        mark_task_complete(tasklist_path, task.name)
        state.mark_task_complete(task.name)
    elif state.fail_fast:
        return False
    # NO commit here

# After all tasks:
if is_dirty():
    commit_msg = f"feat({state.ticket.ticket_id}): implement {len(state.completed_tasks)} tasks"
    commit_changes(commit_msg)
```

### 5. REMOVE: Test Prompts During Execution

**Current:** After each task, prompts user to run tests.

**New:** Remove the `prompt_confirm()` call for tests. Tests run at the very end or not at all during execution phase.

### 6. KEEP: Task Memory Capture

Keep `capture_task_memory()` but DON'T inject its output as prompt context. This is for analytics/debugging, not for bloating prompts.

---

## Deleted Imports

After removing functions, clean up unused imports:
- `from difflib import SequenceMatcher` - only used by `_extract_task_context` fuzzy matching (KEEP if we keep the function)
- Remove any imports only used by deleted functions

---

## New File Structure

```python
"""Step 3: Execute Implementation - Optimistic Execution Model."""

# Minimal imports
from pathlib import Path
from ai_workflow.integrations.auggie import AuggieClient
from ai_workflow.integrations.git import commit_changes, is_dirty
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.task_memory import capture_task_memory
from ai_workflow.workflow.tasks import Task, get_pending_tasks, mark_task_complete, parse_task_list

# KEEP
def _extract_task_context(plan_content: str, task: Task) -> str: ...
def _detect_test_command() -> str | None: ...  # Keep for final test run
def _show_summary(state, failed_tasks): ...
def _squash_checkpoints(state): ...

# SIMPLIFIED
def _execute_task(state, task, auggie, plan_content) -> bool: ...  # Rewrite

# MAIN
def step_3_execute(state, auggie) -> bool: ...  # Rewrite main loop

# DELETE these entirely:
# - _verify_task_completion
# - _get_modified_files_list  
# - _filter_relevant_files
# - _generate_file_tree
# - _build_error_context
# - _run_relevant_tests (move test running to end or remove)
```

---

## Success Metrics

After refactoring, measure:
1. **Time to complete N tasks** - Should be significantly faster
2. **Token usage per task** - Should be ~60-70% lower due to smaller prompts
3. **Git operations count** - Should be 1 instead of N

---

## Migration Notes

- **No backward compatibility required** - This is a greenfield system
- **Delete commented code** - Don't leave `# TODO: old verification logic`
- **Update tests** - Remove tests for deleted functions

---

## Detailed Implementation

### New `_execute_task` Implementation

```python
def _execute_task(
    state: WorkflowState,
    task: Task,
    plan_content: str,
) -> bool:
    """Execute a single task in clean context.

    Optimistic execution model:
    - Trust AI exit codes
    - No file verification
    - No retry loops
    - Minimal prompt

    Args:
        state: Current workflow state
        task: Task to execute
        plan_content: Pre-read plan content

    Returns:
        True if AI reported success
    """
    task_context = _extract_task_context(plan_content, task)

    prompt = f"""Execute this task:

Task: {task.name}

{task_context}

Use codebase-retrieval to find existing patterns."""

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
```

### New `step_3_execute` Main Loop

```python
def step_3_execute(state: WorkflowState, auggie: AuggieClient) -> bool:
    """Execute Step 3: Optimistic automated implementation.

    Fast execution model:
    - Minimal prompts
    - Trust AI success signals
    - Single commit at end
    - No per-task verification
    """
    print_header("Step 3: Execute Implementation")

    # Verify task list exists
    tasklist_path = state.get_tasklist_path()
    if not tasklist_path.exists():
        print_error(f"Task list not found: {tasklist_path}")
        return False

    # Parse and get pending tasks
    tasks = parse_task_list(tasklist_path.read_text())
    pending = get_pending_tasks(tasks)

    if not pending:
        print_success("All tasks already completed!")
        return True

    print_info(f"Executing {len(pending)} tasks...")

    # Read plan once
    plan_path = state.get_plan_path()
    plan_content = plan_path.read_text() if plan_path.exists() else ""

    failed_tasks: list[str] = []

    # Execute each task
    for i, task in enumerate(pending, 1):
        print_step(f"[{i}/{len(pending)}] {task.name}")

        success = _execute_task(state, task, plan_content)

        if success:
            mark_task_complete(tasklist_path, task.name)
            state.mark_task_complete(task.name)
            capture_task_memory(task, state)  # For analytics only
        else:
            failed_tasks.append(task.name)
            if state.fail_fast:
                print_error(f"Stopping: fail_fast enabled")
                return False

    # Single commit at end
    if is_dirty():
        task_count = len(state.completed_tasks)
        commit_msg = f"feat({state.ticket.ticket_id}): implement {task_count} tasks"
        commit_hash = commit_changes(commit_msg)
        if commit_hash:
            state.add_checkpoint(commit_hash)
            print_success(f"Committed: {commit_hash}")

    # Summary
    _show_summary(state, failed_tasks)

    # Squash if requested (already has single commit, but keep for consistency)
    if state.squash_at_end and len(state.checkpoint_commits) > 1:
        if prompt_confirm("Squash commits?", default=True):
            _squash_checkpoints(state)

    return len(failed_tasks) == 0 or prompt_confirm("Continue despite failures?", default=True)
```

---

## Functions Comparison

| Function | Current | New |
|----------|---------|-----|
| `step_3_execute` | 95 lines | ~50 lines |
| `_execute_task` | 168 lines | ~30 lines |
| `_verify_task_completion` | 32 lines | **DELETED** |
| `_get_modified_files_list` | 21 lines | **DELETED** |
| `_filter_relevant_files` | 33 lines | **DELETED** |
| `_generate_file_tree` | 68 lines | **DELETED** |
| `_build_error_context` | 22 lines | **DELETED** |
| `_run_relevant_tests` | 50 lines | **DELETED** (move to final step) |

**Total reduction:** ~300+ lines deleted

---

## Prompt Token Comparison

| Component | Current | New |
|-----------|---------|-----|
| Task name | ~20 tokens | ~20 tokens |
| Task context | ~1000 tokens | ~1000 tokens |
| File tree | ~500-1000 tokens | **0** |
| Pattern context | ~200 tokens | **0** |
| Instructions | ~150 tokens | ~20 tokens |
| DEFINITION OF DONE | ~100 tokens | **0** |
| **Total** | **~2000 tokens** | **~1040 tokens** |

**Token reduction:** ~50% per task

---

## Configuration Changes

### Keep These State Fields
- `implementation_model` - Still needed
- `fail_fast` - Still useful
- `squash_at_end` - Still useful

### Remove/Ignore These State Fields
- `max_retries` - No longer used (no retry loop)
- `retry_count` - No longer used

Consider removing from `WorkflowState` or leaving as dead fields for now.

---

## Test Updates Required

### Delete These Test Cases
- Tests for `_verify_task_completion`
- Tests for `_get_modified_files_list`
- Tests for `_filter_relevant_files`
- Tests for `_generate_file_tree`
- Tests for `_build_error_context`
- Tests for retry logic in `_execute_task`

### Update These Test Cases
- `test_step_3_execute` - Update to expect single commit
- `test_execute_task` - Update to expect no verification

---

## Rollout Checklist

- [ ] Delete `_verify_task_completion` function
- [ ] Delete `_get_modified_files_list` function
- [ ] Delete `_filter_relevant_files` function
- [ ] Delete `_generate_file_tree` function
- [ ] Delete `_build_error_context` function
- [ ] Delete `_run_relevant_tests` function (or move to final step)
- [ ] Rewrite `_execute_task` with minimal prompt
- [ ] Rewrite `step_3_execute` main loop with single commit
- [ ] Remove retry loop logic
- [ ] Remove file tree from prompt
- [ ] Remove pattern context from prompt
- [ ] Clean up unused imports
- [ ] Update/delete tests
- [ ] Verify execution speed improvement


