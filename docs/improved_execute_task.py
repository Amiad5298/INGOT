"""
Improved implementation of _execute_task with session continuity,
verification, and better error handling.

This is a reference implementation showing the recommended improvements
from the code review.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ai_workflow.integrations.auggie import AuggieClient
from ai_workflow.integrations.git import is_dirty
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.tasks import Task


@dataclass
class ErrorAnalysis:
    """Structured error analysis."""
    error_type: str  # "syntax", "import", "runtime", "test_failure", "unknown"
    file_path: Optional[str]
    line_number: Optional[int]
    error_message: str
    stack_trace: list[str]
    root_cause: str
    suggested_fix: str
    
    def to_markdown(self) -> str:
        """Format as markdown for prompt."""
        return f"""
**Type:** {self.error_type}
**File:** {self.file_path or 'Unknown'}
**Line:** {self.line_number or 'Unknown'}

**Error Message:**
{self.error_message}

**Root Cause:**
{self.root_cause}

**Suggested Fix:**
{self.suggested_fix}
"""


@dataclass
class TaskMemory:
    """Captures learnings from completed tasks."""
    task_name: str
    files_modified: list[str]
    patterns_used: list[str]
    key_decisions: list[str]


def _execute_task_improved(
    state: WorkflowState,
    task: Task,
    tasklist_path: Path,
    auggie: AuggieClient,
    session_id: str,
    all_tasks: list[Task],
) -> bool:
    """Execute a single task with improved AI utilization.
    
    Key improvements:
    1. Uses persistent session for learning across tasks
    2. Provides richer context from plan and previous tasks
    3. Includes verification step
    4. Better error analysis and retry logic
    
    Args:
        state: Current workflow state
        task: Task to execute
        tasklist_path: Path to task list file
        auggie: Auggie CLI client (shared across tasks)
        session_id: Session ID for continuity
        all_tasks: All tasks in the workflow (for context)
    
    Returns:
        True if task executed and verified successfully
    """
    plan_path = state.get_plan_path()
    plan_content = plan_path.read_text() if plan_path.exists() else ""
    
    # Build comprehensive initial prompt
    prompt = _build_task_prompt_improved(
        task, plan_content, state, all_tasks
    )
    
    # Execute with retry logic
    retries = 0
    max_retries = state.max_retries
    
    while retries <= max_retries:
        # Execute in persistent session
        success, output = auggie.run_print_with_output(
            prompt, 
            dont_save_session=False,  # KEY CHANGE: Allow learning
            session_id=session_id
        )
        
        if success:
            # Verify task completion
            verified, verification_msg = _verify_task_completion(task, state)
            
            if verified:
                # Capture learnings for future tasks
                _capture_task_memory(task, state)
                return True
            else:
                # Verification failed - treat as execution failure
                output = f"Task executed but verification failed:\n{verification_msg}"
                success = False
        
        # Execution or verification failed
        retries += 1
        
        if retries <= max_retries:
            # Build intelligent retry prompt
            prompt = _build_retry_prompt_improved(
                task, retries, max_retries, output, plan_content, state
            )
        else:
            # Final failure
            return False
    
    return False


def _build_task_prompt_improved(
    task: Task,
    plan_content: str,
    state: WorkflowState,
    all_tasks: list[Task],
) -> str:
    """Build comprehensive task prompt with rich context."""
    
    # Extract semantic context (not just character window)
    task_context = _extract_task_context_semantic(plan_content, task, all_tasks)
    
    # Get relevant file paths from context
    relevant_files = _extract_file_references(task_context)
    
    # Get patterns from completed tasks
    pattern_context = _build_pattern_context(task, state)
    
    # Extract success criteria
    success_criteria = _extract_success_criteria(task, plan_content)
    
    prompt = f"""Execute this task from the implementation plan:

## Task: {task.name}

## Context & Requirements:
{task_context}

## Success Criteria:
{success_criteria}

## Relevant Files:
{chr(10).join(f"- {f}" for f in relevant_files) if relevant_files else "- To be determined"}

{pattern_context}

## Instructions:

### 1. Discovery Phase:
- Use codebase-retrieval to find similar implementations in the codebase
- Identify the exact files that need to be created or modified
- Review existing patterns and conventions

### 2. Implementation Phase:
- Make focused changes to accomplish the task
- Follow patterns from similar code (use codebase-retrieval to find examples)
- Add error handling consistent with the codebase
- Include docstrings/comments for complex logic
- Ensure code is testable

### 3. Verification Phase:
- Run any relevant tests to verify your changes
- Check for syntax/type errors
- Verify all success criteria are met

## Definition of Done:
- [ ] All required files created/modified
- [ ] Code follows project conventions
- [ ] Tests pass (if applicable)
- [ ] No syntax or type errors
- [ ] All success criteria met

Complete this task fully. If you encounter blockers, explain what's preventing completion.
"""
    
    return prompt

