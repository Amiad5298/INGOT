"""Step 2: Create Task List.

This module implements the second step of the workflow - creating
a task list from the implementation plan with user approval.
"""

import re
from pathlib import Path

from ingot.integrations.backends.base import AIBackend
from ingot.ui.menus import TaskReviewChoice, show_task_review_menu
from ingot.ui.prompts import prompt_confirm, prompt_enter
from ingot.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ingot.utils.logging import log_message
from ingot.workflow.state import WorkflowState
from ingot.workflow.tasks import parse_task_list


def step_2_create_tasklist(state: WorkflowState, backend: AIBackend) -> bool:
    """Execute Step 2: Create task list.

    This step:
    1. Reads the implementation plan
    2. Generates a task list from the plan
    3. Allows user to review and approve/edit/regenerate
    4. Saves the approved task list

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

            if not _generate_tasklist(state, plan_path, tasklist_path, backend):
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


# Strict regex for add_tasks tool output format:
# UUID:<shortuuid> NAME:[CATEGORY: ]<task_name> DESCRIPTION:<description>
#
# Design decisions:
# 1. UUID field: [A-Za-z0-9]+ (shortuuid format)
# 2. NAME field: Everything between "NAME:" and " DESCRIPTION:"
# 3. DESCRIPTION field: Everything after " DESCRIPTION:" to end of line
# 4. Category prefixes: UPPERCASE only (FUNDAMENTAL:, INDEPENDENT:) to avoid
#    false positives with sentence-case words like "Fundamental analysis"
#
# The regex uses a greedy match for the name field up to the LAST occurrence
# of " DESCRIPTION:" to handle task names containing the word "DESCRIPTION".
ADD_TASKS_TOOL_PATTERN = re.compile(
    r"^UUID:(?P<uuid>[A-Za-z0-9]+)\s+" r"NAME:(?P<name>.+)\s+DESCRIPTION:(?P<desc>.*)$"
)

# Strict category prefixes - UPPERCASE ONLY to avoid false positives
# e.g., "FUNDAMENTAL: Setup DB" matches, but "Fundamental analysis" does NOT
CATEGORY_PREFIX_PATTERN = re.compile(
    r"^(?P<category>FUNDAMENTAL|INDEPENDENT):\s*(?P<task_name>.+)$"
)


def _parse_add_tasks_line(raw_task_text: str) -> tuple[str | None, str]:
    """Parse a line from add_tasks tool output format.

    Strictly parses the format: UUID:<id> NAME:[CATEGORY: ]<name> DESCRIPTION:<desc>

    The regex is designed to handle edge cases:
    - Task names containing "DESCRIPTION" (e.g., "Fix DESCRIPTION field bug")
    - Task names containing "NAME" (e.g., "Update NAME validation")
    """
    match = ADD_TASKS_TOOL_PATTERN.match(raw_task_text.strip())

    if not match:
        # Not add_tasks format - return as-is, no category
        return (None, raw_task_text.strip())

    name_field = match.group("name").strip()

    # Check for UPPERCASE category prefix (strict matching)
    category_match = CATEGORY_PREFIX_PATTERN.match(name_field)

    if category_match:
        category = category_match.group("category").lower()
        task_name = category_match.group("task_name").strip()
        return (f"<!-- category: {category} -->", task_name)

    # No category prefix - return name as-is
    return (None, name_field)


def _extract_tasklist_from_output(output: str, ticket_id: str) -> str | None:
    """Extract markdown checkbox task list from AI output.

    Parses checkbox tasks from AI output, supporting:
    1. Simple checkbox format: `- [ ] Task name`
    2. add_tasks tool output: `[ ] UUID:xxx NAME:CATEGORY: Task DESCRIPTION:...`
    3. Subtask bullet points (e.g., `  - Implementation detail`)
    4. File metadata comments (e.g., `<!-- files: ... -->`)

    Design:
    - Strict parsing: Uses exact regex patterns, no guessing
    - UPPERCASE-only categories: Only "FUNDAMENTAL:" and "INDEPENDENT:" (not lowercase)
    - Edge-case safe: Handles task names containing "DESCRIPTION" or "NAME"
    - Preserves subtasks: Non-checkbox bullets under tasks are kept

    """
    # Pattern for checkbox task lines: optional indent, optional bullet, checkbox, content
    task_pattern = re.compile(r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$")

    # Pattern for existing category/files metadata comments (preserve if present)
    metadata_pattern = re.compile(r"^\s*<!--\s*(category|files):\s*.+-->\s*$")

    # Pattern for subtask bullet points (indented bullets without checkbox)
    # e.g., "  - Implementation detail" or "    - Sub-subtask"
    subtask_pattern = re.compile(r"^(\s+)[-*]\s+(.+)$")

    # Pattern for section headers (e.g., "## Fundamental Tasks")
    header_pattern = re.compile(r"^(#+)\s+(.+)$")

    # Pattern for the main task list header we add ourselves (skip duplicates from AI output)
    # Matches: "# Task List: TICKET-123" or "# Task List: RED-176578"
    main_header_pattern = re.compile(r"^#\s+Task\s+List:\s*", re.IGNORECASE)

    output_lines = output.splitlines()
    result_lines = [f"# Task List: {ticket_id}", ""]

    task_count = 0
    pending_metadata: list[str] = []
    in_task_section = False  # Track if we've seen at least one checkbox task

    for line in output_lines:
        # Skip the main "# Task List:" header if AI included it (we already added our own)
        if main_header_pattern.match(line.strip()):
            continue

        # Preserve existing category/files metadata comments
        if metadata_pattern.match(line):
            pending_metadata.append(line.strip())
            continue

        # Check for section headers (preserve them)
        header_match = header_pattern.match(line)
        if header_match:
            # Flush pending metadata first
            for meta in pending_metadata:
                result_lines.append(meta)
            pending_metadata = []
            result_lines.append(line.rstrip())
            result_lines.append("")  # Add blank line after header
            continue

        # Check for checkbox task lines
        task_match = task_pattern.match(line)
        if task_match:
            indent, checkbox, raw_task_content = task_match.groups()
            in_task_section = True

            # Parse using strict add_tasks format parser
            # Returns (category_metadata, clean_task_name)
            category_metadata, task_name = _parse_add_tasks_line(raw_task_content)

            # Add category metadata if found
            if category_metadata:
                pending_metadata.append(category_metadata)

            # Flush pending metadata before the task
            for meta in pending_metadata:
                result_lines.append(meta)
            pending_metadata = []

            # Normalize indentation (2 spaces per level)
            indent_level = len(indent) // 2
            normalized_indent = "  " * indent_level
            checkbox_char = checkbox.lower()
            result_lines.append(f"{normalized_indent}- [{checkbox_char}] {task_name}")
            task_count += 1
            continue

        # Check for subtask bullet points (only after we've seen a task)
        subtask_match = subtask_pattern.match(line)
        if subtask_match and in_task_section:
            indent, content = subtask_match.groups()
            # Preserve subtask with normalized indentation
            indent_level = len(indent) // 2
            # Subtasks should be at least 1 level indented
            if indent_level < 1:
                indent_level = 1
            normalized_indent = "  " * indent_level
            result_lines.append(f"{normalized_indent}- {content}")
            continue

    if task_count == 0:
        log_message("No checkbox tasks found in AI output")
        return None

    log_message(f"Extracted {task_count} tasks from AI output")
    return "\n".join(result_lines) + "\n"


def _generate_tasklist(
    state: WorkflowState,
    plan_path: Path,
    tasklist_path: Path,
    backend: AIBackend,
) -> bool:
    """Generate task list from implementation plan using subagent.

    Captures AI output and persists the task list to disk, even if the AI
    does not create/write the file itself.
    """
    # Minimal prompt - subagent has detailed instructions
    prompt = f"""Generate task list for: {state.ticket.id}

Implementation plan: {plan_path}
Read the plan file before generating the task list.

Create an executable task list with FUNDAMENTAL and INDEPENDENT categories."""

    if state.user_context and state.user_context.strip():
        prompt += f"\n\nAdditional Context (use for scope and prioritization only — do not generate implementation details or code):\n{state.user_context.strip()}"

    # Use run_with_callback to capture AI output (Phase 2 migration)
    success, output = backend.run_with_callback(
        prompt,
        subagent=state.subagent_names["tasklist"],
        output_callback=lambda _line: None,
        dont_save_session=True,
    )

    if not success:
        log_message("Auggie command failed")
        return False

    # Try to extract and persist the task list from AI output
    tasklist_content = _extract_tasklist_from_output(output, state.ticket.id)

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

    if not tasklist_path.exists():
        return False

    # Post-process: extract test-related work from FUNDAMENTAL to INDEPENDENT
    print_step("Post-processing task list (extracting tests to independent)...")
    if not _post_process_tasklist(state, tasklist_path, backend):
        print_warning("Post-processing failed, using original task list")
        # Continue with original - post-processing is best-effort

    return True


# Test-related keywords for pre-check optimization (case-insensitive)
# Language-agnostic list covering common test terminology
_TEST_KEYWORDS = [
    "test",
    "spec",
    "unit",
    "integration",
    "e2e",
    "assert",
    "verify",
    "check",
    "mock",
    "stub",
]


def _fundamental_section_has_test_keywords(content: str) -> bool:
    """Check if the Fundamental Tasks section contains any test-related keywords.

    This is an optimization to skip the expensive AI call when there are
    no test-related items to extract from FUNDAMENTAL tasks.
    """
    # Extract the Fundamental section
    content_lower = content.lower()

    # Find the start of Fundamental section
    fundamental_start = content_lower.find("## fundamental")
    if fundamental_start == -1:
        # No Fundamental section found
        return False

    # Find the end of Fundamental section (start of Independent or end of file)
    independent_start = content_lower.find("## independent", fundamental_start)
    if independent_start == -1:
        fundamental_section = content_lower[fundamental_start:]
    else:
        fundamental_section = content_lower[fundamental_start:independent_start]

    # Check for any test-related keywords in the Fundamental section
    for keyword in _TEST_KEYWORDS:
        if keyword in fundamental_section:
            return True

    return False


def _post_process_tasklist(state: WorkflowState, tasklist_path: Path, backend: AIBackend) -> bool:
    """Post-process task list to extract test-related work from FUNDAMENTAL tasks.

    Uses the ingot-tasklist-refiner agent to:
    1. Scan FUNDAMENTAL tasks for test-related content
    2. Extract those items to new INDEPENDENT tasks with group: testing
    3. Rewrite the task list with proper separation

    This is a best-effort operation - if it fails, the original task list is preserved.
    """
    tasklist_content = tasklist_path.read_text()
    original_length = len(tasklist_content)

    # Skip if task list is empty or very short
    if len(tasklist_content.strip()) < 50:
        log_message("Task list too short for post-processing, skipping")
        return True

    # Optimization: Skip AI call if no test-related keywords in Fundamental section
    if not _fundamental_section_has_test_keywords(tasklist_content):
        log_message("No test keywords found in Fundamental section, skipping post-processing")
        return True

    # Build prompt referencing task list file path
    prompt = f"""Refine this task list by extracting test-related work from FUNDAMENTAL to INDEPENDENT:

Task list file: {tasklist_path}
Read the current task list file before refining.

Output ONLY the refined task list markdown."""

    success, output = backend.run_with_callback(
        prompt,
        subagent=state.subagent_names["tasklist_refiner"],
        output_callback=lambda _line: None,
        dont_save_session=True,
    )

    if not success:
        log_message("Post-processing agent failed")
        return False

    # Extract the refined task list from output
    refined_content = _extract_tasklist_from_output(output, state.ticket.id)

    if refined_content:
        # Safety check: warn if content is significantly shorter
        refined_length = len(refined_content)
        if refined_length < 0.8 * original_length:
            print_warning(
                "Post-processing resulted in significantly less content. "
                "Please perform a manual double-check to ensure no implementation "
                "tasks were accidentally dropped."
            )

        # Verify we can still parse tasks after refining
        tasks = parse_task_list(refined_content)
        if tasks:
            tasklist_path.write_text(refined_content)
            log_message(f"Post-processed task list: {len(tasks)} tasks")
            return True
        else:
            log_message("Post-processed output has no parseable tasks")
            return False

    # If extraction failed, check if the file was directly modified
    if tasklist_path.exists():
        new_content = tasklist_path.read_text()
        if new_content != tasklist_content:
            # Safety check for directly modified file
            if len(new_content) < 0.8 * original_length:
                print_warning(
                    "Post-processing resulted in significantly less content. "
                    "Please perform a manual double-check to ensure no implementation "
                    "tasks were accidentally dropped."
                )

            # AI modified the file directly
            tasks = parse_task_list(new_content)
            if tasks:
                log_message(f"Post-processing modified file directly: {len(tasks)} tasks")
                return True

    log_message("Post-processing produced no valid output")
    return False


def _create_default_tasklist(tasklist_path: Path, state: WorkflowState) -> None:
    """Create a default task list template."""
    template = f"""# Task List: {state.ticket.id}

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
    """Display the task list."""
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
    """Allow user to edit the task list."""
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
