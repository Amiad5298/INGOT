# Technical Specification: Performance Optimization of `step3_execute.py`

**Target File:** `ai_workflow/workflow/step3_execute.py`  
**Goal:** Reduce latency by eliminating redundant AI calls, optimizing I/O operations, and making test execution user-opt-in.

---

## 1. Remove "Double Verification" (AI-based Check)

### Problem
The current implementation performs a secondary AI roundtrip in `_verify_task_completion()` to ask the LLM to verify that a task was completed. This adds significant latency without proportional value, since the execution itself is already done by an LLM.

### Changes Required

#### 1.1 Modify `_verify_task_completion()` (Lines 259-338)

**Current Behavior:**  
- Checks for modified files via `_get_modified_files_list()`
- Runs tests via `_run_relevant_tests()` (automatically)
- Calls `auggie.run_print_with_output()` with a verification prompt to ask the AI to verify completion
- Parses the AI response for "✅ VERIFIED" or "❌ INCOMPLETE"

**New Behavior:**  
- Check for modified files via `_get_modified_files_list()`
- Check for relevant source files via `_filter_relevant_files()`
- **Remove:** The entire AI verification block (lines 301-337)
- **Remove:** The `auggie: AuggieClient` parameter (no longer needed)
- Return success if relevant files were modified

**New Signature:**
```python
def _verify_task_completion(
    state: WorkflowState,
    task: Task,
) -> tuple[bool, str]:
```

**New Logic:**
```python
def _verify_task_completion(
    state: WorkflowState,
    task: Task,
) -> tuple[bool, str]:
    log_message(f"Verifying task completion: {task.name}")
    
    modified_files = _get_modified_files_list()
    if not modified_files:
        return False, "No files were modified - task appears incomplete"
    
    relevant_files = _filter_relevant_files(modified_files)
    if not relevant_files:
        return False, "No relevant source files were modified"
    
    log_message(f"Modified files: {', '.join(relevant_files)}")
    return True, f"Task completed - {len(relevant_files)} file(s) modified"
```

#### 1.2 Modify `_execute_task()` (Lines 564-735)

**Current Behavior:**  
- Calls `_verify_task_completion(state, task, auggie_impl)` after successful execution
- If verification fails, regenerates prompt with verification feedback and retries
- Has a nested retry loop for verification failures

**New Behavior:**  
- Call `_verify_task_completion(state, task)` (without auggie parameter)
- If files were modified, consider the task done
- **Remove:** The verification-failure retry loop (lines 658-692)
- **Remove:** The prompt regeneration logic for verification failure

**Simplified Success Block (inside the `while retries <= max_retries` loop):**
```python
if success:
    print_success(f"Task '{task.name}' executed successfully")
    
    verified, verify_message = _verify_task_completion(state, task)
    
    if verified:
        print_success(f"Task verified: {verify_message}")
        return True
    else:
        # Files not modified - consider this a failure, continue retry loop
        print_warning(f"Task incomplete: {verify_message}")
        retries += 1
        if retries > max_retries:
            print_error(f"Task '{task.name}' failed after {max_retries} retries")
            return False
        # Continue with existing error-retry logic (build error context, etc.)
        last_error_info = verify_message
        prompt = f"""Continue working on this task (retry attempt {retries}/{max_retries}):
...existing retry prompt structure...
PREVIOUS ISSUE: {last_error_info}
..."""
        continue
```

---

## 2. Change Test Execution to "User-Opt-In"

### Problem
The current implementation runs `_run_relevant_tests()` automatically within `_verify_task_completion()`, blocking the workflow for every test-related task.

### Changes Required

#### 2.1 Remove automatic test execution from `_verify_task_completion()`

**Current Behavior (Lines 295-298):**
```python
test_result = _run_relevant_tests(task, state)
if test_result is not None and not test_result:
    return False, "Tests failed - task verification failed"
```

**New Behavior:**  
- **Remove** these lines entirely from `_verify_task_completion()`

#### 2.2 Add user opt-in test execution in `step_3_execute()` or after each task

**Location:** After successful task execution in `step_3_execute()` (around line 530)

**New Logic (add after task completion, before checkpoint commit):**
```python
# Offer user opt-in test execution
if prompt_confirm(f"Run tests for task '{task.name}'?", default=False):
    test_result = _run_relevant_tests(task, state)
    if test_result is False:
        print_warning("Tests failed - you may want to review before continuing")
    elif test_result is True:
        print_success("Tests passed")
    # Note: test_result=None means no tests to run
```

---

## 3. I/O Optimization (Hoisting Operations)

### Problem
Currently, `_generate_file_tree(state)` and `plan_path.read_text()` are called inside `_execute_task()` for every task iteration. These operations are redundant because the plan and project structure don't change between tasks.

### Changes Required

#### 3.1 Modify `step_3_execute()` (Lines 461-561)

**Add at the beginning of the function (after line 498):**
```python
# Hoist I/O operations - read once, reuse for all tasks
plan_path = state.get_plan_path()
plan_content = plan_path.read_text() if plan_path.exists() else ""
file_tree = _generate_file_tree(state)
```

**Modify the `_execute_task()` call (line 513):**
```python
# Before:
success = _execute_task(state, task, tasklist_path, auggie)

# After:
success = _execute_task(state, task, tasklist_path, auggie, file_tree, plan_content)
```

#### 3.2 Modify `_execute_task()` signature and body (Lines 564-735)

**New Signature:**
```python
def _execute_task(
    state: WorkflowState,
    task: Task,
    tasklist_path: Path,
    auggie: AuggieClient,
    file_tree: str,
    plan_content: str,
) -> bool:
```

**Remove from function body (Lines 589-596):**
```python
# Remove these lines:
plan_path = state.get_plan_path()
plan_content = plan_path.read_text() if plan_path.exists() else ""
...
file_tree = _generate_file_tree(state)
```

**Keep the task_context extraction (it uses plan_content):**
```python
task_context = _extract_task_context(plan_content, task)
```

---

## Constraint

**DO NOT** change the `dont_save_session=True` setting. Each task must continue to run in a clean context to avoid context pollution.

---

## Summary of Changes

| Function | Change Type | Description |
|----------|-------------|-------------|
| `_verify_task_completion()` | Simplify | Remove AI verification call, remove `auggie` param, keep only file-based checks |
| `_verify_task_completion()` | Remove | Remove automatic `_run_relevant_tests()` call |
| `_execute_task()` | Simplify | Remove verification-failure retry loop, remove prompt regeneration for verification |
| `_execute_task()` | Signature | Add `file_tree: str` and `plan_content: str` parameters |
| `_execute_task()` | Remove | Remove internal plan reading and file tree generation |
| `step_3_execute()` | Add | Hoist `plan_content` and `file_tree` computation before task loop |
| `step_3_execute()` | Add | User opt-in test execution with `prompt_confirm()` after each task |
| `step_3_execute()` | Update | Pass hoisted values to `_execute_task()` |

---

## Expected Impact

- **Latency Reduction:** Eliminates 1 AI roundtrip per task (verification), saving ~5-15 seconds per task
- **I/O Reduction:** Plan file and file tree read once instead of N times (where N = number of tasks)
- **User Control:** Tests only run when explicitly requested, avoiding unexpected blocking
- **Maintained Isolation:** `dont_save_session=True` preserved for clean context per task

