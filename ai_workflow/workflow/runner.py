"""Workflow orchestration for AI Workflow.

This module provides the main workflow runner that orchestrates
all three steps of the spec-driven development workflow.
"""

from contextlib import contextmanager
from typing import Generator, Optional

from ai_workflow.config.manager import ConfigManager
from ai_workflow.integrations.auggie import AuggieClient
from ai_workflow.integrations.git import (
    DirtyStateAction,
    create_branch,
    get_current_branch,
    get_current_commit,
    handle_dirty_state,
    is_dirty,
    stash_changes,
)
from ai_workflow.integrations.jira import JiraTicket, fetch_ticket_info
from ai_workflow.ui.menus import show_git_dirty_menu
from ai_workflow.ui.prompts import prompt_confirm, prompt_input
from ai_workflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ai_workflow.utils.errors import AIWorkflowError, UserCancelledError
from ai_workflow.utils.logging import log_message
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.step1_plan import step_1_create_plan
from ai_workflow.workflow.step2_tasklist import step_2_create_tasklist
from ai_workflow.workflow.step3_execute import step_3_execute


def run_spec_driven_workflow(
    ticket: JiraTicket,
    config: ConfigManager,
    planning_model: str = "",
    implementation_model: str = "",
    skip_clarification: bool = False,
    squash_at_end: bool = True,
    use_tui: bool | None = None,
    verbose: bool = False,
) -> bool:
    """Run the complete spec-driven development workflow.

    This orchestrates all three steps:
    1. Create implementation plan
    2. Create task list with approval
    3. Execute tasks with clean loop

    Args:
        ticket: Jira ticket information
        config: Configuration manager
        planning_model: Model for planning phases
        implementation_model: Model for implementation phase
        skip_clarification: Skip clarification step
        squash_at_end: Squash commits at end
        use_tui: Override for TUI mode. None = auto-detect.
        verbose: Enable verbose mode in TUI (expanded log panel).

    Returns:
        True if workflow completed successfully
    """
    print_header(f"Starting Workflow: {ticket.ticket_id}")

    # Initialize state
    state = WorkflowState(
        ticket=ticket,
        planning_model=planning_model or config.settings.default_model,
        implementation_model=implementation_model or config.settings.default_model,
        skip_clarification=skip_clarification,
        squash_at_end=squash_at_end,
    )

    # Initialize Auggie client
    auggie = AuggieClient()

    with workflow_cleanup(state):
        # Handle dirty state before starting
        if is_dirty():
            action = show_git_dirty_menu("starting workflow")
            if not handle_dirty_state("starting workflow", action):
                return False

        # Fetch ticket information early (before branch creation)
        print_step("Fetching ticket information...")
        try:
            state.ticket = fetch_ticket_info(state.ticket, auggie)
            print_success(f"Ticket: {state.ticket.title}")
            if state.ticket.description:
                print_info(f"Description: {state.ticket.description[:200]}...")
        except Exception as e:
            log_message(f"Failed to fetch ticket info: {e}")
            print_warning("Could not fetch ticket details. Continuing with ticket ID only.")

        # Ask user for additional context
        if prompt_confirm("Would you like to add additional context about this ticket?", default=False):
            user_context = prompt_input(
                "Enter additional context (press Enter twice when done):",
                multiline=True,
            )
            state.user_context = user_context.strip()
            if state.user_context:
                print_success("Additional context saved")

        # Create feature branch (now with ticket summary available)
        # Use state.ticket which has the updated summary from fetch_ticket_info
        if not _setup_branch(state, state.ticket):
            return False

        # Record base commit
        state.base_commit = get_current_commit()
        log_message(f"Base commit: {state.base_commit}")

        # Step 1: Create implementation plan
        if state.current_step <= 1:
            print_info("Starting Step 1: Create Implementation Plan")
            if not step_1_create_plan(state, auggie):
                return False

        # Step 2: Create task list
        if state.current_step <= 2:
            print_info("Starting Step 2: Create Task List")
            if not step_2_create_tasklist(state, auggie):
                return False

        # Step 3: Execute implementation
        if state.current_step <= 3:
            print_info("Starting Step 3: Execute Implementation")
            if not step_3_execute(state, use_tui=use_tui, verbose=verbose):
                return False

        # Workflow complete
        _show_completion(state)
        return True


def _setup_branch(state: WorkflowState, ticket: JiraTicket) -> bool:
    """Set up the feature branch for the workflow.

    Args:
        state: Workflow state
        ticket: Jira ticket

    Returns:
        True if branch was set up successfully
    """
    current_branch = get_current_branch()

    # Generate branch name using ticket summary if available
    if ticket.summary:
        # Format: RED-180934-add-graphql-query-to-fetch-account
        branch_name = f"{ticket.ticket_id.lower()}-{ticket.summary}"
    else:
        # Fallback to simple format if summary not available
        branch_name = f"feature/{ticket.ticket_id.lower()}"

    state.branch_name = branch_name

    # Check if already on feature branch
    if current_branch == branch_name:
        print_info(f"Already on branch: {branch_name}")
        return True

    # Ask to create branch
    if prompt_confirm(f"Create branch '{branch_name}'?", default=True):
        if create_branch(branch_name):
            print_success(f"Created and switched to branch: {branch_name}")
            return True
        else:
            print_error(f"Failed to create branch: {branch_name}")
            return False
    else:
        # Stay on current branch
        state.branch_name = current_branch
        print_info(f"Staying on branch: {current_branch}")
        return True


def _show_completion(state: WorkflowState) -> None:
    """Show workflow completion message.

    Args:
        state: Workflow state
    """
    console.print()
    print_header("Workflow Complete!")

    console.print(f"[bold green]✓[/bold green] Ticket: {state.ticket.ticket_id}")
    console.print(f"[bold green]✓[/bold green] Branch: {state.branch_name}")
    console.print(f"[bold green]✓[/bold green] Tasks: {len(state.completed_tasks)} completed")

    if state.plan_file:
        console.print(f"[bold green]✓[/bold green] Plan: {state.plan_file}")
    if state.tasklist_file:
        console.print(f"[bold green]✓[/bold green] Tasks: {state.tasklist_file}")

    console.print()
    print_info("Next steps:")
    print_info("  1. Review the changes")
    print_info("  2. Run tests: pytest")
    print_info("  3. Create a pull request")
    console.print()


@contextmanager
def workflow_cleanup(state: WorkflowState) -> Generator[None, None, None]:
    """Context manager for workflow cleanup on error.

    Handles cleanup when workflow is interrupted or fails.

    Args:
        state: Workflow state

    Yields:
        None
    """
    original_branch = get_current_branch()

    try:
        yield
    except UserCancelledError:
        print_info("\nWorkflow cancelled by user")
        _offer_cleanup(state, original_branch)
        raise
    except AIWorkflowError as e:
        print_error(f"\nWorkflow error: {e}")
        _offer_cleanup(state, original_branch)
        raise
    except Exception as e:
        print_error(f"\nUnexpected error: {e}")
        _offer_cleanup(state, original_branch)
        raise


def _offer_cleanup(state: WorkflowState, original_branch: str) -> None:
    """Offer cleanup options after workflow failure.

    Args:
        state: Workflow state
        original_branch: Branch before workflow started
    """
    console.print()
    print_warning("Workflow did not complete successfully.")

    if state.checkpoint_commits:
        print_info(f"Created {len(state.checkpoint_commits)} checkpoint commits")

    if state.branch_name and state.branch_name != original_branch:
        print_info(f"On branch: {state.branch_name}")
        print_info(f"Original branch: {original_branch}")


__all__ = [
    "run_spec_driven_workflow",
    "workflow_cleanup",
]

