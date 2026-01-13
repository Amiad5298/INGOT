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

    Finds all lines matching checkbox format, preserving category metadata comments
    and section headers for parallel execution support.

    Args:
        output: AI output text that may contain task list
        ticket_id: Ticket ID for the header

    Returns:
        Formatted task list content, or None if no tasks found
    """
    # Pattern for task items: optional indent, optional bullet, checkbox, task name
    task_pattern = re.compile(r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$")
    # Pattern for category metadata comments
    metadata_pattern = re.compile(r"^\s*<!--\s*category:\s*.+-->\s*$")
    # Pattern for section headers (## Fundamental Tasks, ## Independent Tasks, etc.)
    section_pattern = re.compile(r"^##\s+(Fundamental|Independent)\s+Tasks.*$", re.IGNORECASE)

    output_lines = output.splitlines()
    result_lines = [f"# Task List: {ticket_id}", ""]

    task_count = 0
    pending_metadata: list[str] = []  # Buffer for metadata before a task

    for line in output_lines:
        # Check for section headers
        if section_pattern.match(line):
            # Add blank line before section (if we have content)
            if len(result_lines) > 2:
                result_lines.append("")
            result_lines.append(line)
            pending_metadata = []  # Reset metadata buffer
            continue

        # Check for category metadata comments
        if metadata_pattern.match(line):
            pending_metadata.append(line.strip())
            continue

        # Check for task items
        task_match = task_pattern.match(line)
        if task_match:
            indent, checkbox, task_name = task_match.groups()

            # Add any pending metadata before this task
            for meta in pending_metadata:
                result_lines.append(meta)
            pending_metadata = []

            # Normalize indentation (2 spaces per level)
            indent_level = len(indent) // 2
            normalized_indent = "  " * indent_level
            checkbox_char = checkbox.lower()  # Normalize to lowercase
            result_lines.append(f"{normalized_indent}- [{checkbox_char}] {task_name.strip()}")
            task_count += 1

    if task_count == 0:
        log_message("No checkbox tasks found in AI output")
        return None

    log_message(f"Extracted {task_count} tasks from AI output")
    return "\n".join(result_lines) + "\n"


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

    ticket_id = state.ticket.ticket_id
    prompt = f"""Based on this implementation plan, create a task list optimized for AI agent execution.

Plan:
{plan_content}

## Task Generation Guidelines:

### Size & Scope
- Each task should represent a **complete, coherent unit of work**
- Target 3-8 tasks for a typical feature
- Include tests WITH implementation, not as separate tasks

### Task Categorization

Categorize each task into one of two categories:

#### FUNDAMENTAL Tasks (Sequential Execution)
Tasks that establish foundational infrastructure and MUST run in order:
- Core data models, schemas, database migrations
- Base classes, interfaces, or abstract implementations
- Service layers that other components depend on
- Configuration or setup that other tasks require
- Any task where Task N+1 depends on Task N's output

Mark fundamental tasks with: `<!-- category: fundamental, order: N -->`

#### INDEPENDENT Tasks (Parallel Execution)
Tasks that can run concurrently with no dependencies on each other:
- UI components (after models/services exist)
- Utility functions and helpers
- Documentation updates
- Separate API endpoints that don't share state
- Test suites that don't modify shared resources

**CRITICAL: File Disjointness Requirement & Resolution Strategy**
Independent tasks running in parallel MUST touch disjoint sets of files.

If you detect that multiple logical tasks need to edit the same shared file (e.g., `TestData.java`, `pom.xml`, `Enums.java`, configuration files), use the **"Setup Task Pattern"**:

1.  **Extract Shared Changes**: Take the edits for the shared files from all features.
2.  **Create Setup Task**: Create a single `FUNDAMENTAL` task (Order 1) named "Update Shared Resources" containing ONLY these shared file edits.
3.  **Parallelize the Rest**: Now that the shared conflicts are resolved in the setup task, create the remaining feature-specific tasks as `INDEPENDENT`.

**Example of Resolving Conflict in `TestData.java`:**
Instead of:
- Task A (Fundamental): Implement Feature A + Update TestData
- Task B (Fundamental): Implement Feature B + Update TestData (Blocked by A)

DO THIS:
- Task 1 (Fundamental): **Prepare Shared Test Data** (Update `TestData.java` with mocks for BOTH A and B)
- Task 2 (Independent): **Implement Feature A** (Logic + Unit Tests, no longer touching TestData)
- Task 3 (Independent): **Implement Feature B** (Logic + Unit Tests, no longer touching TestData)

### Output Format

**IMPORTANT:** Output ONLY the task list as plain markdown text. Do NOT use any task management tools.

```markdown
# Task List: {ticket_id}

## Fundamental Tasks (Sequential)
<!-- category: fundamental, order: 1 -->
- [ ] [First foundational task]

<!-- category: fundamental, order: 2 -->
- [ ] [Second foundational task that depends on first]

## Independent Tasks (Parallel)
<!-- category: independent, group: ui -->
- [ ] [UI component task]

<!-- category: independent, group: utils -->
- [ ] [Utility task]
```

### Categorization Heuristics

1. **If unsure, mark as FUNDAMENTAL** - Sequential is always safe
2. **Data/Schema tasks are ALWAYS FUNDAMENTAL** - Order 1
3. **Service/Logic tasks are USUALLY FUNDAMENTAL** - Order 2+
4. **UI/Docs/Utils are USUALLY INDEPENDENT** - Can parallelize
5. **Tests with their implementation are FUNDAMENTAL** - Part of that task
6. **Shared file edits require EXTRACTION** - If two tasks edit the same file, extract the shared edits to a new FUNDAMENTAL setup task, then keep the original tasks INDEPENDENT.

Order tasks by dependency (prerequisites first). Keep descriptions concise but specific."""

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

