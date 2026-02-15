"""Step 1: Create Implementation Plan.

This module implements the first step of the workflow - creating
an implementation plan based on the Jira ticket.
"""

import os
import re
from pathlib import Path

from ingot.integrations.backends.base import AIBackend
from ingot.ui.prompts import prompt_confirm
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
from ingot.workflow.events import format_run_directory
from ingot.workflow.state import WorkflowState

# Robust ANSI/terminal escape sequence patterns (ECMA-48 compliant).
# Matches:
# - CSI sequences: \x1b[ followed by parameter bytes (0x30-0x3f, including ?),
#   intermediate bytes (0x20-0x2f), and a final byte (0x40-0x7e).
#   Examples: \x1b[32m (color), \x1b[?25l (hide cursor), \x1b[38;2;255;0;0m (24-bit color)
# - OSC sequences: \x1b] ... ST (terminated by \x1b\\ or \x07).
#   Examples: \x1b]0;title\x07 (set window title)
# - Character set designation: \x1b( or \x1b) followed by a charset ID.
#
# Known limitation: Does not match bare two-byte ESC sequences like \x1bM
# (reverse index) or \x1bc (terminal reset). These are rare in AI CLI output.
_ANSI_RE = re.compile(
    r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # CSI sequences
    r"|\x1b\].*?(?:\x1b\\|\x07)"  # OSC sequences
    r"|\x1b[()][A-Z0-9]"  # Character set designation
)

# Matches <thinking>...</thinking> blocks (case-insensitive, multi-line).
_THINKING_BLOCK_RE = re.compile(
    r"<thinking>.*?</thinking>",
    re.DOTALL | re.IGNORECASE,
)

# =============================================================================
# Log Directory Management
# =============================================================================


def _get_log_base_dir() -> Path:
    """Get the base directory for run logs."""
    env_dir = os.environ.get("INGOT_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".ingot/runs")


def _create_plan_log_dir(safe_ticket_id: str) -> Path:
    """Create a timestamped log directory for plan generation.

    safe_ticket_id MUST be sanitized (use ticket.safe_filename_stem) -
    raw ticket IDs may contain unsafe chars like '/'.
    """
    base_dir = _get_log_base_dir()
    plan_dir = base_dir / safe_ticket_id / "plan_generation"
    plan_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir


# =============================================================================
# Plan Generation Functions
# =============================================================================


def _generate_plan_with_tui(
    state: WorkflowState,
    plan_path: Path,
    backend: AIBackend,
) -> tuple[bool, str]:
    """Generate plan with TUI progress display using subagent.

    Returns:
        Tuple of (success, captured_output).
    """
    from ingot.ui.tui import TaskRunnerUI

    # Create log directory and log path (use safe_filename_stem for paths)
    log_dir = _create_plan_log_dir(state.ticket.safe_filename_stem)
    log_path = log_dir / f"{format_run_directory()}.log"

    ui = TaskRunnerUI(
        status_message="Generating implementation plan...",
        ticket_id=state.ticket.id,  # Keep original ID for display
        single_operation_mode=True,
    )
    ui.set_log_path(log_path)

    # Use plan_mode only for backends that map it to a CLI flag;
    # others (Auggie, Codex) can write the plan file directly.
    use_plan_mode = backend.supports_plan_mode

    # Build minimal prompt - agent has the instructions
    prompt = _build_minimal_prompt(state, plan_path, plan_mode=use_plan_mode)

    with ui:
        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["planner"],
            output_callback=ui.handle_output_line,
            dont_save_session=True,
            plan_mode=use_plan_mode,
        )

        # Check if user requested quit
        if ui.check_quit_requested():
            print_warning("Plan generation cancelled by user.")
            return False, ""

    ui.print_summary(success)
    return success, output


def _build_minimal_prompt(state: WorkflowState, plan_path: Path, *, plan_mode: bool = False) -> str:
    """Build minimal prompt for plan generation.

    The subagent has detailed instructions - we just pass context.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan should be saved.
        plan_mode: If True, instruct the AI to output the plan to stdout
            instead of writing a file (for read-only backends).
    """
    prompt = f"""Create implementation plan for: {state.ticket.id}

Ticket: {state.ticket.title or state.ticket.branch_summary or "Not available"}
Description: {state.ticket.description or "Not available"}"""

    # Add user context if provided
    if state.user_context:
        prompt += f"""

Additional Context:
{state.user_context}"""

    if plan_mode:
        prompt += """

Output the complete implementation plan in Markdown format to stdout.
Do not attempt to create or write any files.

Codebase context will be retrieved automatically."""
    else:
        prompt += f"""

Save the plan to: {plan_path}

Codebase context will be retrieved automatically."""

    return prompt


def _extract_plan_markdown(output: str) -> str:
    """Extract clean markdown plan from CLI output.

    Strips ANSI escape codes, ``<thinking>`` blocks, tool-call logs,
    and other noise. Looks for the first markdown heading (any level)
    and returns everything from there. Falls back to full output if no
    headings found.

    Known limitation: Heading detection does not account for fenced code
    blocks — a ``# comment`` inside a code fence would be matched as a
    heading. This is low risk for typical plan output.
    """
    output = _ANSI_RE.sub("", output)
    output = _THINKING_BLOCK_RE.sub("", output)
    lines = output.splitlines()

    # Find first markdown heading (any level: #, ##, ###, etc.)
    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") and stripped.lstrip("#").startswith(" "):
            start_idx = i
            break

    # Strip trailing empty lines
    content = "\n".join(lines[start_idx:]).rstrip()
    return content if content else output.strip()


def step_1_create_plan(state: WorkflowState, backend: AIBackend) -> bool:
    """Execute Step 1: Create implementation plan.

    This step:
    1. Generates an implementation plan
    2. Saves the plan to specs/{ticket}-plan.md

    Note: Ticket information is already fetched in the workflow runner
    before this step is called. Clarification is handled separately
    in step 1.5 (step1_5_clarification.py).
    """
    print_header("Step 1: Create Implementation Plan")

    # Ensure specs directory exists
    state.specs_dir.mkdir(parents=True, exist_ok=True)

    # Display ticket information (already fetched earlier)
    if state.ticket.title:
        print_info(f"Ticket: {state.ticket.title}")
    if state.ticket.description:
        print_info(f"Description: {state.ticket.description[:200]}...")

    # Generate implementation plan using subagent
    print_step("Generating implementation plan...")
    plan_path = state.get_plan_path()

    success, output = _generate_plan_with_tui(state, plan_path, backend)

    if not success:
        print_error("Failed to generate implementation plan")
        return False

    # Check if plan file was created
    if not plan_path.exists():
        # Plan might be in output, save it
        print_info("Saving plan to file...")
        _save_plan_from_output(plan_path, state, output=output)

    if plan_path.exists():
        print_success(f"Implementation plan saved to: {plan_path}")
        state.plan_file = plan_path

        # Display plan summary
        _display_plan_summary(plan_path)

        # Confirm plan
        if prompt_confirm("Does this plan look good?", default=True):
            state.current_step = 2
            return True
        else:
            print_info("You can edit the plan manually and re-run.")
            return False
    else:
        print_error("Plan file was not created")
        return False


def _save_plan_from_output(plan_path: Path, state: WorkflowState, *, output: str = "") -> None:
    """Save plan from backend output if file wasn't created.

    When output is non-empty (plan mode backends output to stdout),
    sanitize and save the captured output. Falls back to a template
    when output is empty.
    """
    if output.strip():
        plan_content = _extract_plan_markdown(output)
        plan_path.write_text(plan_content)
        log_message(f"Saved plan from output at {plan_path}")
        return

    # Create a basic plan template if backend didn't create the file
    template = f"""# Implementation Plan: {state.ticket.id}

## Summary
{state.ticket.title or "Implementation task"}

## Description
{state.ticket.description or "See Jira ticket for details."}

## Implementation Steps
1. Review requirements
2. Implement changes
3. Write tests
4. Review and refactor

## Testing Strategy
- Unit tests for new functionality
- Integration tests as needed
- Manual verification

## Notes
Plan generated automatically. Please review and update as needed.
"""
    plan_path.write_text(template)
    log_message(f"Created template plan at {plan_path}")


def _display_plan_summary(plan_path: Path) -> None:
    """Display summary of the plan."""
    content = plan_path.read_text()
    lines = content.splitlines()

    # Show first 20 lines or until first major section
    preview_lines = []
    for line in lines[:30]:
        preview_lines.append(line)
        if len(preview_lines) >= 20:
            break

    console.print()
    console.print("[bold]Plan Preview:[/bold]")
    console.print("-" * 40)
    for line in preview_lines:
        console.print(line)
    if len(lines) > len(preview_lines):
        console.print("...")
    console.print("-" * 40)
    console.print()


__all__ = [
    "step_1_create_plan",
]
