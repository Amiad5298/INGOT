"""Step 1: Create Implementation Plan.

This module implements the first step of the workflow - creating
an implementation plan based on the Jira ticket.
"""

import os
from pathlib import Path

from specflow.integrations.auggie import AuggieClient
from specflow.ui.prompts import prompt_confirm, prompt_enter
from specflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from specflow.utils.logging import log_message
from specflow.workflow.events import format_run_directory
from specflow.workflow.state import WorkflowState


# =============================================================================
# Log Directory Management
# =============================================================================


def _get_log_base_dir() -> Path:
    """Get the base directory for run logs.

    Returns:
        Path to the log base directory.
    """
    env_dir = os.environ.get("SPECFLOW_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".specflow/runs")


def _create_plan_log_dir(ticket_id: str) -> Path:
    """Create a timestamped log directory for plan generation.

    Args:
        ticket_id: Ticket identifier for directory naming.

    Returns:
        Path to the created log directory.
    """
    base_dir = _get_log_base_dir()
    plan_dir = base_dir / ticket_id / "plan_generation"
    plan_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir


# =============================================================================
# Plan Generation Functions
# =============================================================================


def _generate_plan_with_tui(
    state: WorkflowState,
    plan_path: Path,
) -> bool:
    """Generate plan with TUI progress display using subagent.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan will be saved.

    Returns:
        True if plan generation succeeded.
    """
    from specflow.ui.plan_tui import StreamingOperationUI

    # Create log directory and log path
    log_dir = _create_plan_log_dir(state.ticket.ticket_id)
    log_path = log_dir / f"{format_run_directory()}.log"

    ui = StreamingOperationUI(
        status_message="Generating implementation plan...",
        ticket_id=state.ticket.ticket_id,
    )
    ui.set_log_path(log_path)

    # Build minimal prompt - agent has the instructions
    prompt = _build_minimal_prompt(state, plan_path)

    auggie_client = AuggieClient()

    with ui:
        success, _output = auggie_client.run_with_callback(
            prompt,
            agent=state.subagent_names["planner"],
            output_callback=ui.handle_output_line,
            dont_save_session=True,
        )

        # Check if user requested quit
        if ui.quit_requested:
            print_warning("Plan generation cancelled by user.")
            return False

    ui.print_summary(success)
    return success


def _build_minimal_prompt(state: WorkflowState, plan_path: Path) -> str:
    """Build minimal prompt for plan generation.

    The subagent has detailed instructions - we just pass context.

    Args:
        state: Current workflow state.
        plan_path: Path where plan should be saved.

    Returns:
        Minimal prompt string with ticket context.
    """
    prompt = f"""Create implementation plan for: {state.ticket.ticket_id}

Ticket: {state.ticket.title or state.ticket.summary or 'Not available'}
Description: {state.ticket.description or 'Not available'}"""

    # Add user context if provided
    if state.user_context:
        prompt += f"""

Additional Context:
{state.user_context}"""

    prompt += f"""

Save the plan to: {plan_path}

Codebase context will be retrieved automatically."""

    return prompt


def step_1_create_plan(state: WorkflowState, auggie: AuggieClient) -> bool:
    """Execute Step 1: Create implementation plan.

    This step:
    1. Optionally runs clarification with the user
    2. Generates an implementation plan
    3. Saves the plan to specs/{ticket}-plan.md

    Note: Ticket information is already fetched in the workflow runner
    before this step is called.

    Args:
        state: Current workflow state
        auggie: Auggie CLI client

    Returns:
        True if plan was created successfully
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

    success = _generate_plan_with_tui(state, plan_path)

    if not success:
        print_error("Failed to generate implementation plan")
        return False

    # Check if plan file was created
    if not plan_path.exists():
        # Plan might be in output, save it
        print_info("Saving plan to file...")
        _save_plan_from_output(plan_path, state)

    if plan_path.exists():
        print_success(f"Implementation plan saved to: {plan_path}")
        state.plan_file = plan_path

        # Display plan summary
        _display_plan_summary(plan_path)

        # Clarification step (optional) - happens AFTER plan creation
        if not state.skip_clarification:
            if not _run_clarification(state, auggie, plan_path):
                return False
            # Display updated plan after clarification
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


def _run_clarification(state: WorkflowState, auggie: AuggieClient, plan_path: Path) -> bool:
    """Run clarification step with user.

    This happens AFTER the plan is created. The AI reviews the plan and asks
    clarifying questions, then updates the plan with a Q&A section.

    Args:
        state: Current workflow state
        auggie: Auggie CLI client (unused, kept for signature compatibility)
        plan_path: Path to the created plan file

    Returns:
        True to continue, False to abort
    """
    print_header("Step 1.5: Clarification Phase (Optional)")
    print_info("The AI can review the plan and ask clarification questions about:")
    print_info("  - Ambiguous requirements")
    print_info("  - Missing technical details")
    print_info("  - Unclear dependencies or integration points")
    print_info("  - Edge cases not covered")
    console.print()

    if not prompt_confirm("Would you like the AI to review the plan and ask clarification questions?", default=True):
        print_info("Skipping clarification phase")
        return True

    print_step("Starting interactive clarification phase...")
    console.print()
    print_info("INSTRUCTIONS:")
    print_info("  1. The AI will review the plan and ask clarification questions")
    print_info("  2. Answer each question in the chat")
    print_info("  3. The AI will update the plan file with a '## Clarification Q&A' section")
    print_info("  4. Type 'done' or press Ctrl+D when you're finished with clarifications")
    console.print()

    prompt = f"""Review the implementation plan at @{plan_path}.

Ask 2-4 clarifying questions about any ambiguous or unclear aspects:
- Requirements that could be interpreted multiple ways
- Missing technical details needed for implementation
- Unclear dependencies or integration points
- Edge cases or error scenarios not covered
- Performance, security, or scalability considerations

After I answer your questions, update the plan file by adding a new section at the end:

## Clarification Q&A

Q1: [Your question]
A1: [My answer]

Q2: [Your question]
A2: [My answer]

If the plan is complete and clear, simply respond with 'No clarifications needed - plan is comprehensive.' and do not modify the file."""

    # Use spec-planner subagent for clarification (same agent that created the plan)
    auggie_client = AuggieClient()

    print_step("Running: auggie (interactive mode)")
    print_info(f"Using agent: {state.subagent_names['planner']}")
    console.print()

    success = auggie_client.run_print(prompt, agent=state.subagent_names["planner"])

    console.print()
    if success:
        print_success("Clarification phase completed!")
        console.print()
        print_info("The plan file has been updated with clarification Q&A (if any questions were asked)")
    else:
        print_warning("Clarification phase encountered an issue, but continuing...")

    return True


def _save_plan_from_output(plan_path: Path, state: WorkflowState) -> None:
    """Save plan from Auggie output if file wasn't created.

    Args:
        plan_path: Path to save plan
        state: Current workflow state
    """
    # Create a basic plan template if Auggie didn't create the file
    template = f"""# Implementation Plan: {state.ticket.ticket_id}

## Summary
{state.ticket.title or 'Implementation task'}

## Description
{state.ticket.description or 'See Jira ticket for details.'}

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
    """Display summary of the plan.

    Args:
        plan_path: Path to plan file
    """
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

