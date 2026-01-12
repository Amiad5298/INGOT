# Implementation Specification: User Additional Context After Jira Ticket Fetch

## Overview

Add a user interaction step after fetching the Jira ticket in the workflow runner, allowing users to provide additional context/information about the ticket before proceeding with the AI-driven workflow.

## Goal

After the Jira ticket is fetched and displayed, prompt the user with:
- "Would you like to add any additional context about this ticket?"
- If yes, allow multiline input for additional context
- Store the additional context in workflow state
- Include the additional context in prompts sent to the AI

## Files to Modify

### 1. `ai_workflow/workflow/state.py`
**Change:** Add new field `user_context: str = ""` to `WorkflowState` dataclass

```python
# Add to WorkflowState dataclass attributes (around line 55)
# User-provided additional context
user_context: str = ""
```

### 2. `ai_workflow/workflow/runner.py`
**Change:** Add prompt after ticket fetch, **before** branch creation

**Current flow (lines 92-110):**
1. Fetch ticket information (lines 92-101)
2. Create feature branch (lines 103-106) ← NEW STEP GOES BEFORE THIS
3. Record base commit (lines 108-110)

**New flow:**
1. Fetch ticket information
2. **NEW: Ask user for additional context** ← Insert here (after line 101)
3. Create feature branch
4. Record base commit
5. (rest of workflow unchanged)

```python
# Insert after line 101 (after ticket display), before line 103 (before branch creation):
from ai_workflow.ui.prompts import prompt_input

# ... existing ticket display code (lines 96-101) ...

# NEW: Ask user for additional context
if prompt_confirm("Would you like to add additional context about this ticket?", default=False):
    user_context = prompt_input(
        "Enter additional context (press Enter twice when done):",
        multiline=True,
    )
    state.user_context = user_context.strip()
    if state.user_context:
        print_success("Additional context saved")

# ... existing branch creation code (lines 103+) ...
```

**Import to add:** `prompt_input` (already importing from prompts module)

### 3. `ai_workflow/workflow/step1_plan.py`
**Change:** Include user context in `_build_plan_prompt` function

```python
def _build_plan_prompt(state: WorkflowState) -> str:
    """Build the prompt for plan generation."""
    plan_path = state.get_plan_path()
    
    # Base prompt
    prompt = f"""Create an implementation plan for Jira ticket {state.ticket.ticket_id}.

Ticket title: {state.ticket.title or 'Not available'}
Description: {state.ticket.description or 'Not available'}
"""
    
    # Add user context if provided
    if state.user_context:
        prompt += f"""
## Additional Context from User
{state.user_context}
"""
    
    prompt += f"""
Create a detailed implementation plan and save it to: {plan_path}

The plan should include:
1. Summary of the task
2. Technical approach
3. Implementation steps (numbered)
4. Testing strategy
5. Potential risks or considerations

Format as markdown. Be specific and actionable."""
    
    return prompt
```

## Test Plan

### Tests to Add/Modify in `tests/test_workflow_runner.py` (new file)

```python
class TestUserAdditionalContext:
    """Tests for user additional context feature."""

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input") 
    def test_user_declines_additional_context(self, mock_input, mock_confirm):
        """User declines to add context - no prompt_input called."""
        mock_confirm.return_value = False
        # ... verify prompt_input not called
        # ... verify state.user_context remains empty

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input")
    def test_user_adds_additional_context(self, mock_input, mock_confirm):
        """User provides additional context - stored in state."""
        mock_confirm.return_value = True
        mock_input.return_value = "Additional details about the feature"
        # ... verify state.user_context is set

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input")
    def test_empty_context_handled(self, mock_input, mock_confirm):
        """Empty context input is handled gracefully."""
        mock_confirm.return_value = True
        mock_input.return_value = "   "  # whitespace only
        # ... verify state.user_context is empty string
```

### Tests to Add in `tests/test_workflow_state.py`

```python
def test_user_context_default_empty(self, state):
    """user_context defaults to empty string."""
    assert state.user_context == ""

def test_user_context_can_be_set(self, state):
    """user_context can be set."""
    state.user_context = "Additional details"
    assert state.user_context == "Additional details"
```

### Tests to Add in `tests/test_step1_plan.py` (new or existing)

```python
class TestBuildPlanPrompt:
    """Tests for _build_plan_prompt function."""

    def test_prompt_without_user_context(self):
        """Prompt is built correctly without user context."""
        # ... verify no user context section

    def test_prompt_with_user_context(self):
        """Prompt includes user context when provided."""
        state.user_context = "Focus on performance optimization"
        prompt = _build_plan_prompt(state)
        assert "Additional Context from User" in prompt
        assert "Focus on performance optimization" in prompt
```

## Implementation Order

1. **State modification** (`state.py`) - Add `user_context` field
2. **Runner modification** (`runner.py`) - Add user prompt after ticket fetch, before branch creation
3. **Plan prompt modification** (`step1_plan.py`) - Include context in AI prompt
4. **Tests** - Add tests for each modified component

## Complete Workflow Order (After Implementation)

```
1. Handle dirty git state (if needed)
2. Fetch Jira ticket information
3. Display ticket info (title, description)
4. **NEW: Ask user for additional context** ← INSERTED HERE
5. Create feature branch (or stay on current)
6. Record base commit
7. Step 1: Create Implementation Plan (uses user_context in prompt)
8. Step 2: Create Task List
9. Step 3: Execute Implementation
10. Show completion
```

## Acceptance Criteria

- [ ] After Jira ticket is fetched and displayed, user is asked if they want to add context
- [ ] The prompt happens BEFORE branch creation (preserves original flow order)
- [ ] User can provide multiline context input
- [ ] Context is stored in WorkflowState
- [ ] Context is included in the plan generation prompt
- [ ] Empty/whitespace context is handled gracefully
- [ ] User can decline and workflow continues normally
- [ ] All new and modified code has test coverage

