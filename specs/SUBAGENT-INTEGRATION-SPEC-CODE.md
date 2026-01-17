# Subagent Integration - Code Changes

## Overview

This specification details the code modifications required to integrate Auggie CLI subagents
into the SPEC workflow. **We will delete inline prompts** and use subagents exclusively.

---

## 1. AuggieClient Updates

**File**: `spec/integrations/auggie.py`

### 1.1 Add Agent Support to `_build_command()`

Modify the `_build_command` method to accept a required `agent` parameter for workflow calls:

```python
def _build_command(
    self,
    prompt: str,
    agent: str,  # Required for SPEC workflow
    print_mode: bool = False,
    quiet: bool = False,
    dont_save_session: bool = False,
) -> list[str]:
    cmd = ["auggie"]

    # Agent is required - model comes from agent definition file
    cmd.extend(["--agent", agent])

    # ... rest of method unchanged
```

### 1.2 Add Agent Parameter to All Run Methods

Update method signatures for:
- `run()` 
- `run_print_with_output()`
- `run_with_callback()`

Each should accept `agent: Optional[str] = None` and pass it to `_build_command()`.

### 1.3 Add Subagent Constants

```python
# Subagent names used by SPEC workflow
SPEC_AGENT_PLANNER = "spec-planner"
SPEC_AGENT_TASKLIST = "spec-tasklist"
SPEC_AGENT_IMPLEMENTER = "spec-implementer"
SPEC_AGENT_REVIEWER = "spec-reviewer"
```

---

## 2. Step 1 Updates (Plan Creation)

**File**: `spec/workflow/step1_plan.py`

### 2.1 Modify `_create_plan()` - Delete Inline Prompts

```python
from spec.integrations.auggie import SPEC_AGENT_PLANNER

def _create_plan(state: WorkflowState, auggie: AuggieClient) -> bool:
    # Minimal prompt - agent has the instructions
    prompt = f"""Create implementation plan for: {state.ticket.ticket_id}

Ticket: {state.ticket.summary}
Description: {state.ticket.description}

Codebase context will be retrieved automatically."""

    success, output = auggie.run_print_with_output(
        prompt,
        agent=SPEC_AGENT_PLANNER,
        dont_save_session=True,
    )

    return success
```

### 2.2 Delete Legacy Code

**DELETE** the following from step1_plan.py:
- `_build_legacy_plan_prompt()` function or any inline prompt building
- Large prompt template strings
- Any fallback logic

---

## 3. Step 2 Updates (Task List)

**File**: `spec/workflow/step2_tasklist.py`

### 3.1 Modify `_generate_tasklist()` - Delete Inline Prompts

```python
from spec.integrations.auggie import SPEC_AGENT_TASKLIST

def _generate_tasklist(state, plan_path, tasklist_path, auggie):
    plan_content = plan_path.read_text()

    prompt = f"""Generate task list for: {state.ticket.ticket_id}

Implementation Plan:
{plan_content}

Create an executable task list with FUNDAMENTAL and INDEPENDENT categories."""

    success, output = auggie.run_print_with_output(
        prompt,
        agent=SPEC_AGENT_TASKLIST,
        dont_save_session=True,
    )

    # ... rest of parsing logic unchanged
```

### 3.2 Delete Legacy Code

**DELETE** the following from step2_tasklist.py:
- `_build_legacy_tasklist_prompt()` function
- Large inline prompt template strings
- Any fallback logic

---

## 4. Step 3 Updates (Task Execution)

**File**: `spec/workflow/step3_execute.py`

### 4.1 Modify `_execute_task()` - Delete Inline Prompts

```python
from spec.integrations.auggie import SPEC_AGENT_IMPLEMENTER

def _execute_task_with_agent(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    callback: Callable[[str], None],
    is_parallel: bool = False,
) -> bool:
    auggie_client = AuggieClient()  # Model comes from agent file

    plan_content = plan_path.read_text()

    prompt = f"""Execute task: {task.name}

Reference Plan:
{plan_content}

Complete this single task. Do not commit changes."""

    success, output = auggie_client.run_with_callback(
        prompt,
        agent=SPEC_AGENT_IMPLEMENTER,
        output_callback=callback,
        dont_save_session=True,
    )

    return success
```

### 4.2 Delete Legacy Code

**DELETE** the following from step3_execute.py:
- `_build_task_prompt()` function
- Large inline prompt template strings
- Any fallback/conditional logic for non-agent mode

---

## 5. Export Updates

**File**: `spec/integrations/__init__.py`

Add new exports:
```python
from spec.integrations.auggie import (
    # ... existing exports ...
    SPEC_AGENT_PLANNER,
    SPEC_AGENT_TASKLIST,
    SPEC_AGENT_IMPLEMENTER,
    SPEC_AGENT_REVIEWER,
)
```

---

## Validation Checklist

- [ ] `AuggieClient._build_command()` accepts `agent` parameter
- [ ] All run methods pass `agent` through correctly
- [ ] Step 1 uses `spec-planner` agent (no fallback)
- [ ] Step 2 uses `spec-tasklist` agent (no fallback)
- [ ] Step 3 uses `spec-implementer` agent (no fallback)
- [ ] **Inline prompt code DELETED** from all workflow steps
- [ ] Existing tests updated for new behavior
- [ ] New tests added for agent invocation

