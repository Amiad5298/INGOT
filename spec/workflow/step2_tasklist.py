"""Step 2: Create Task List.

This module implements the second step of the workflow - creating
a task list from the implementation plan with user approval.
"""

import re
from pathlib import Path

from spec.integrations.auggie import AuggieClient
from spec.ui.menus import TaskReviewChoice, show_task_review_menu
from spec.ui.prompts import prompt_confirm, prompt_enter
from spec.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from spec.utils.logging import log_message
from spec.workflow.state import WorkflowState
from spec.workflow.tasks import (
    parse_task_list,
    format_task_list,
    Task,
    TaskCategory,
    normalize_path,
    deduplicate_paths,
    PathSecurityError,
)


class StrictFileScopingError(ValueError):
    """Raised when an INDEPENDENT task lacks required target_files metadata.

    Strict file scoping is required for parallel execution to prevent race
    conditions. INDEPENDENT tasks MUST declare their target files explicitly.
    """

    def __init__(self, task_name: str):
        self.task_name = task_name
        super().__init__(
            f"Strict file scoping required: INDEPENDENT task '{task_name}' "
            f"has no target_files. Parallel execution requires explicit file "
            f"declarations to prevent race conditions."
        )


def _validate_file_disjointness(
    tasks: list[Task],
    repo_root: Path,
) -> list[str]:
    """Validate that independent tasks have disjoint file sets.

    Independent tasks running in parallel must not target the same files
    to prevent race conditions and data loss.

    Uses normalized paths for comparison to ensure equivalent paths
    (e.g., ./src/file.py and src/file.py) are treated as the same file.

    SECURITY: repo_root is REQUIRED for path normalization and jail check.
    All paths are validated to ensure they do not escape the repository.

    STRICT MODE: Independent tasks with empty target_files will raise an
    exception. This enforces strict file scoping for parallel execution.

    Args:
        tasks: List of all tasks
        repo_root: Repository root for path normalization and security.
                   REQUIRED - all paths must resolve within this directory.

    Returns:
        List of warning messages for overlapping files

    Raises:
        StrictFileScopingError: If an INDEPENDENT task has no target_files
        PathSecurityError: If any path escapes the repository root
    """
    independent = [t for t in tasks if t.category == TaskCategory.INDEPENDENT]
    warnings: list[str] = []

    # Build normalized file -> tasks mapping
    file_to_tasks: dict[str, list[str]] = {}

    for task in independent:
        # STRICT: Raise exception if independent task has no target_files
        if not task.target_files:
            raise StrictFileScopingError(task.name)

        # Normalize and deduplicate paths within the task
        # PathSecurityError will propagate if path escapes repo
        normalized_files = deduplicate_paths(task.target_files, repo_root)

        for file_path in normalized_files:
            if file_path not in file_to_tasks:
                file_to_tasks[file_path] = []
            file_to_tasks[file_path].append(task.name)

    # Check for conflicts
    for file_path, task_names in file_to_tasks.items():
        if len(task_names) > 1:
            warnings.append(
                f"File collision detected: '{file_path}' is targeted by multiple "
                f"independent tasks: {', '.join(task_names)}"
            )

    return warnings


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

            if not _generate_tasklist(state, plan_path, tasklist_path):
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

    Finds all lines matching checkbox format, preserving category metadata comments,
    files metadata comments, and section headers for parallel execution support.

    Args:
        output: AI output text that may contain task list
        ticket_id: Ticket ID for the header

    Returns:
        Formatted task list content, or None if no tasks found
    """
    # Pattern for task items: optional indent, optional bullet, checkbox, task name
    task_pattern = re.compile(r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$")
    # Pattern for category metadata comments
    category_pattern = re.compile(r"^\s*<!--\s*category:\s*.+-->\s*$")
    # Pattern for files metadata comments (predictive context)
    files_pattern = re.compile(r"^\s*<!--\s*files:\s*.+-->\s*$")
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
        if category_pattern.match(line):
            pending_metadata.append(line.strip())
            continue

        # Check for files metadata comments (predictive context)
        if files_pattern.match(line):
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
) -> bool:
    """Generate task list from implementation plan using subagent.

    Captures AI output and persists the task list to disk, even if the AI
    does not create/write the file itself.

    Args:
        state: Current workflow state
        plan_path: Path to implementation plan
        tasklist_path: Path to save task list

    Returns:
        True if task list was generated and contains valid tasks
    """
    plan_content = plan_path.read_text()

    # Minimal prompt - subagent has detailed instructions
    prompt = f"""Generate task list for: {state.ticket.ticket_id}

Implementation Plan:
{plan_content}

Create an executable task list with FUNDAMENTAL and INDEPENDENT categories."""

    # Use subagent - model comes from agent definition
    auggie_client = AuggieClient()

    # Use run_print_with_output to capture AI output
    success, output = auggie_client.run_print_with_output(
        prompt,
        agent=state.subagent_names["tasklist"],
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
            # Validate file disjointness for independent tasks
            # Uses state.repo_root for security validation
            try:
                warnings = _validate_file_disjointness(tasks, state.repo_root)
                for warning in warnings:
                    print_warning(warning)
                if warnings:
                    print_warning(
                        "File collisions detected! Consider extracting shared files to a "
                        "FUNDAMENTAL setup task or merging the conflicting tasks."
                    )
            except StrictFileScopingError as e:
                print_error(str(e))
                print_info(
                    "INDEPENDENT tasks require explicit target_files for parallel execution. "
                    "Add <!-- files: path/to/file.py --> metadata or change category to FUNDAMENTAL."
                )
                return False
            except PathSecurityError as e:
                print_error(f"Security violation: {e}")
                return False
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
                # Validate file disjointness for independent tasks
                # Uses state.repo_root for security validation
                try:
                    warnings = _validate_file_disjointness(tasks, state.repo_root)
                    for warning in warnings:
                        print_warning(warning)
                    if warnings:
                        print_warning(
                            "File collisions detected! Consider extracting shared files to a "
                            "FUNDAMENTAL setup task or merging the conflicting tasks."
                        )
                except StrictFileScopingError as e:
                    print_error(str(e))
                    print_info(
                        "INDEPENDENT tasks require explicit target_files for parallel execution. "
                        "Add <!-- files: path/to/file.py --> metadata or change category to FUNDAMENTAL."
                    )
                    return False
                except PathSecurityError as e:
                    print_error(f"Security violation: {e}")
                    return False
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
    "_validate_file_disjointness",
    "StrictFileScopingError",
]

