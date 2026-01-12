"""Step 2: Create Task List.

This module implements the second step of the workflow - creating
a task list from the implementation plan with user approval.
"""

import re
from pathlib import Path
from typing import Optional

from ai_workflow.integrations.auggie import AuggieClient
from ai_workflow.ui.menus import TaskReviewChoice, show_task_review_menu
from ai_workflow.ui.prompts import prompt_confirm, prompt_enter
from ai_workflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ai_workflow.utils.logging import log_message
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.tasks import parse_task_list, format_task_list


def step_2_create_tasklist(state: WorkflowState, auggie: AuggieClient) -> bool:
    """Execute Step 2: Create task list.

    This step:
    1. Reads the implementation plan
    2. Generates a task list from the plan
    3. Allows user to review and approve/edit/regenerate
    4. Saves the approved task list

    Args:
        state: Current workflow state
        auggie: Auggie CLI client

    Returns:
        True if task list was created and approved
    """
    print_header("Step 2: Create Task List")

    # Verify plan exists
    plan_path = state.get_plan_path()
    if not plan_path.exists():
        print_error(f"Implementation plan not found: {plan_path}")
        print_info("Please run Step 1 first to create the plan.")
        return False

    tasklist_path = state.get_tasklist_path()

    # Flag to control when generation happens
    # Only generate on first entry or after REGENERATE
    needs_generation = True

    # Task list approval loop
    while True:
        if needs_generation:
            # Generate task list
            print_step("Generating task list from plan...")

            if not _generate_tasklist(state, plan_path, tasklist_path, auggie):
                print_error("Failed to generate task list")
                if not prompt_confirm("Retry?", default=True):
                    return False
                continue

            # Successfully generated, don't regenerate unless explicitly requested
            needs_generation = False

        # Display task list
        _display_tasklist(tasklist_path)

        # Get user decision
        choice = show_task_review_menu()

        if choice == TaskReviewChoice.APPROVE:
            state.tasklist_file = tasklist_path
            state.current_step = 3
            print_success("Task list approved!")
            return True

        elif choice == TaskReviewChoice.REGENERATE:
            print_info("Regenerating task list...")
            needs_generation = True
            continue

        elif choice == TaskReviewChoice.EDIT:
            _edit_tasklist(tasklist_path)
            # Re-display after edit, but do NOT regenerate
            # needs_generation stays False
            continue

        elif choice == TaskReviewChoice.ABORT:
            print_warning("Workflow aborted by user")
            return False


def _extract_tasklist_from_output(output: str, ticket_id: str) -> Optional[str]:
    """Extract markdown checkbox task list from AI output.

    Finds all lines matching checkbox format and returns them as a task list.

    Args:
        output: AI output text that may contain task list
        ticket_id: Ticket ID for the header

    Returns:
        Formatted task list content, or None if no tasks found
    """
    # Pattern for task items: optional indent, optional bullet, checkbox, task name
    pattern = re.compile(r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$", re.MULTILINE)

    matches = pattern.findall(output)
    if not matches:
        log_message("No checkbox tasks found in AI output")
        return None

    # Build the task list content
    lines = [f"# Task List: {ticket_id}", "", "## Implementation Tasks", ""]

    for indent, checkbox, task_name in matches:
        # Preserve indentation (normalize to 2 spaces per level)
        indent_level = len(indent) // 2
        normalized_indent = "  " * indent_level
        checkbox_char = checkbox.lower()  # Normalize to lowercase
        lines.append(f"{normalized_indent}- [{checkbox_char}] {task_name.strip()}")

    log_message(f"Extracted {len(matches)} tasks from AI output")
    return "\n".join(lines) + "\n"


def _generate_tasklist(
    state: WorkflowState,
    plan_path: Path,
    tasklist_path: Path,
    auggie: AuggieClient,
) -> bool:
    """Generate task list from implementation plan.

    Captures AI output and persists the task list to disk, even if the AI
    does not create/write the file itself.

    Args:
        state: Current workflow state
        plan_path: Path to implementation plan
        tasklist_path: Path to save task list
        auggie: Auggie CLI client

    Returns:
        True if task list was generated and contains valid tasks
    """
    plan_content = plan_path.read_text()

    prompt = f"""Based on this implementation plan, create a task list optimized for AI agent execution.

Plan:
{plan_content}

## Task Generation Guidelines:

### Size & Scope
- Each task should represent a **complete, coherent unit of work**
- Target 3-8 tasks for a typical feature (not 15-25 micro-tasks)
- A task should implement a full capability, not fragments
- Include tests WITH implementation, not as separate tasks

### Good Task Examples:
- "Implement UserService with CRUD operations and unit tests"
- "Add authentication middleware with JWT validation and integration tests"
- "Create database migration for users table and seed data"
- "Refactor payment module to use new pricing engine"

### Bad Task Examples (avoid these):
- "Create new file" (too granular)
- "Add import statements" (not a real unit of work)
- "Write test for function X" (tests should be with implementation)
- "Add type hints" (should be part of implementation task)

### Task Boundaries
- Align tasks with **natural code boundaries**: modules, features, layers
- A task should leave the codebase in a **working state**
- If tasks depend on each other, note the dependency

### Output Format
**IMPORTANT:** Output ONLY the task list as plain markdown text. Do NOT use any task management tools.

Format each task as a markdown checkbox:
- [ ] Task description here

Example output:
- [ ] Implement UserService with CRUD operations and unit tests
- [ ] Add authentication middleware with JWT validation
- [ ] Create database migration for users table

Order tasks by dependency (prerequisites first). Keep descriptions concise but specific.

Be outcome-focused: describe WHAT to achieve, not HOW to do it step-by-step.
The AI agent will determine the implementation approach."""

    # Use a planning-specific client if a planning model is configured
    if state.planning_model:
        auggie_client = AuggieClient(model=state.planning_model)
    else:
        auggie_client = auggie

    # Use run_print_with_output to capture AI output
    success, output = auggie_client.run_print_with_output(
        prompt,
        dont_save_session=True,
    )

    if not success:
        log_message("Auggie command failed")
        return False

    # Try to extract and persist the task list from AI output
    tasklist_content = _extract_tasklist_from_output(output, state.ticket.ticket_id)

    if tasklist_content:
        # Ensure parent directory exists
        tasklist_path.parent.mkdir(parents=True, exist_ok=True)
        tasklist_path.write_text(tasklist_content)
        log_message(f"Wrote task list to {tasklist_path}")

        # Verify we can parse the tasks
        tasks = parse_task_list(tasklist_content)
        if not tasks:
            log_message("Warning: Written task list has no parseable tasks")
            _create_default_tasklist(tasklist_path, state)
    else:
        # No tasks extracted from output, check if AI wrote the file
        if tasklist_path.exists():
            # AI wrote file - verify it has tasks
            content = tasklist_path.read_text()
            tasks = parse_task_list(content)
            if not tasks:
                log_message("AI-created file has no parseable tasks, using default")
                _create_default_tasklist(tasklist_path, state)
        else:
            # Fall back to default template
            log_message("No tasks extracted and no file created, using default")
            _create_default_tasklist(tasklist_path, state)

    return tasklist_path.exists()


def _create_default_tasklist(tasklist_path: Path, state: WorkflowState) -> None:
    """Create a default task list template.

    Args:
        tasklist_path: Path to save task list
        state: Current workflow state
    """
    template = f"""# Task List: {state.ticket.ticket_id}

## Implementation Tasks

- [ ] [Core functionality implementation with tests]
- [ ] [Integration/API layer with tests]
- [ ] [Documentation updates]

## Notes
Tasks represent complete units of work, not micro-steps.
Each task should leave the codebase in a working state.
"""
    tasklist_path.write_text(template)
    log_message(f"Created default task list at {tasklist_path}")


def _display_tasklist(tasklist_path: Path) -> None:
    """Display the task list.

    Args:
        tasklist_path: Path to task list file
    """
    content = tasklist_path.read_text()
    tasks = parse_task_list(content)

    console.print()
    console.print("[bold]Task List:[/bold]")
    console.print("-" * 50)
    console.print(content)
    console.print("-" * 50)
    console.print(f"[dim]Total tasks: {len(tasks)}[/dim]")
    console.print()


def _edit_tasklist(tasklist_path: Path) -> None:
    """Allow user to edit the task list.

    Args:
        tasklist_path: Path to task list file
    """
    import os
    import subprocess

    editor = os.environ.get("EDITOR", "vim")

    print_info(f"Opening task list in {editor}...")
    print_info("Save and close the editor when done.")

    try:
        subprocess.run([editor, str(tasklist_path)], check=True)
        print_success("Task list updated")
    except subprocess.CalledProcessError:
        print_warning("Editor closed without saving")
    except FileNotFoundError:
        print_error(f"Editor not found: {editor}")
        print_info(f"Edit the file manually: {tasklist_path}")
        prompt_enter("Press Enter when done editing...")


__all__ = [
    "step_2_create_tasklist",
    "_generate_tasklist",
    "_extract_tasklist_from_output",
]

