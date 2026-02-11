"""Workflow orchestration for INGOT.

This module provides the main workflow runner that orchestrates
all five steps of the spec-driven development workflow.
"""

from collections.abc import Generator
from contextlib import contextmanager

from ingot.config.manager import ConfigManager
from ingot.integrations.agents import ensure_agents_installed
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.git import (
    create_branch,
    get_current_branch,
    get_current_commit,
    handle_dirty_state,
    is_dirty,
)
from ingot.integrations.providers import GenericTicket
from ingot.ui.menus import show_git_dirty_menu
from ingot.ui.prompts import prompt_confirm, prompt_input
from ingot.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ingot.utils.errors import IngotError, UserCancelledError
from ingot.utils.logging import log_message
from ingot.workflow.conflict_detection import (
    _detect_context_conflict,
    detect_context_conflict,
)
from ingot.workflow.git_utils import DirtyTreePolicy
from ingot.workflow.state import RateLimitConfig, WorkflowState
from ingot.workflow.step1_5_clarification import step_1_5_clarification
from ingot.workflow.step1_plan import step_1_create_plan
from ingot.workflow.step2_tasklist import step_2_create_tasklist
from ingot.workflow.step3_execute import step_3_execute
from ingot.workflow.step4_update_docs import Step4Result, step_4_update_docs
from ingot.workflow.step5_commit import Step5Result, step_5_commit


def run_ingot_workflow(
    ticket: GenericTicket,
    config: ConfigManager,
    backend: AIBackend,
    planning_model: str = "",
    implementation_model: str = "",
    skip_clarification: bool = False,
    squash_at_end: bool = True,
    use_tui: bool | None = None,
    verbose: bool = False,
    parallel_execution_enabled: bool = True,
    max_parallel_tasks: int = 3,
    fail_fast: bool = False,
    rate_limit_config: RateLimitConfig | None = None,
    enable_phase_review: bool = False,
    dirty_tree_policy: DirtyTreePolicy = DirtyTreePolicy.FAIL_FAST,
    auto_update_docs: bool = True,
    auto_commit: bool = True,
) -> bool:
    """Run the complete spec-driven development workflow.

    This orchestrates all five steps:
    1. Create implementation plan
    2. Create task list with approval
    3. Execute tasks with clean loop
    4. Update documentation based on code changes
    5. Commit changes
    """
    # Guardrails: Handle potentially incomplete ticket data
    # Tickets may lack title if fetched without enrichment
    display_name = ticket.title or ticket.branch_summary or ticket.id
    if not ticket.title:
        print_warning(
            f"Ticket '{ticket.id}' is missing title. Using '{display_name}' for display purposes."
        )

    print_header(f"Starting Workflow: {ticket.id}")

    # Initialize state with subagent names from config
    state = WorkflowState(
        ticket=ticket,
        planning_model=planning_model or config.settings.default_model,
        implementation_model=implementation_model or config.settings.default_model,
        skip_clarification=skip_clarification,
        squash_at_end=squash_at_end,
        parallel_execution_enabled=parallel_execution_enabled,
        max_parallel_tasks=max_parallel_tasks,
        fail_fast=fail_fast,
        rate_limit_config=rate_limit_config or RateLimitConfig(),
        enable_phase_review=enable_phase_review,
        dirty_tree_policy=dirty_tree_policy,
        backend_platform=backend.platform,
        backend_model=backend.model or "",
        backend_name=backend.name,
        subagent_names={
            "planner": config.settings.subagent_planner,
            "tasklist": config.settings.subagent_tasklist,
            "tasklist_refiner": config.settings.subagent_tasklist_refiner,
            "implementer": config.settings.subagent_implementer,
            "reviewer": config.settings.subagent_reviewer,
            "fixer": config.settings.subagent_fixer,
            "doc_updater": config.settings.subagent_doc_updater,
        },
    )

    with workflow_cleanup(state, backend):
        # Handle dirty state before starting
        # This must happen BEFORE ensure_agents_installed() to avoid discarding
        # the .gitignore updates that ensure_agents_installed() makes
        if is_dirty():
            action = show_git_dirty_menu("starting workflow")
            if not handle_dirty_state("starting workflow", action):
                return False

        # Ensure INGOT subagent files are installed (includes .gitignore configuration)
        # This is done AFTER dirty state handling so the .gitignore updates aren't discarded
        if not ensure_agents_installed():
            print_error("Failed to install INGOT subagent files")
            return False

        # Display ticket information (already fetched via TicketService before workflow)
        print_success(f"Ticket: {state.ticket.title}")
        if state.ticket.description:
            print_info(f"Description: {state.ticket.description[:200]}...")

        # Ask user for additional context
        if prompt_confirm(
            "Would you like to add additional context about this ticket?", default=False
        ):
            user_context = prompt_input(
                "Enter additional context (press Enter twice when done):",
                multiline=True,
            )
            state.user_context = user_context.strip()
            if state.user_context:
                print_success("Additional context saved")

                # Fail-Fast Semantic Check: Detect conflicts between ticket and user context
                print_step("Checking for conflicts between ticket and your context...")
                conflict_detected, conflict_summary = _detect_context_conflict(
                    state.ticket, state.user_context, backend, state
                )
                state.conflict_detected = conflict_detected
                state.conflict_summary = conflict_summary

                if conflict_detected:
                    console.print()
                    print_warning(
                        "⚠️  Potential conflict detected between ticket description and your additional context"
                    )
                    console.print(f"[yellow]   {conflict_summary}[/yellow]")
                    console.print()
                    print_info(
                        "💡 Running the clarification step is strongly recommended to resolve this conflict."
                    )
                    print_info(
                        "   You'll be prompted about clarification after the initial plan is generated."
                    )
                    console.print()

        # Create feature branch using ticket's branch_slug with feature/ prefix
        if not _setup_branch(state, state.ticket):
            return False

        # Record base commit
        state.base_commit = get_current_commit()
        log_message(f"Base commit: {state.base_commit}")

        # Step 1: Create implementation plan
        if state.current_step <= 1:
            print_info("Starting Step 1: Create Implementation Plan")
            if not step_1_create_plan(state, backend):
                return False

        # Step 1.5: Interactive clarification (optional)
        if state.current_step == 2 and not state.skip_clarification:
            if not step_1_5_clarification(state, backend):
                return False

        # Step 2: Create task list
        if state.current_step <= 2:
            print_info("Starting Step 2: Create Task List")
            if not step_2_create_tasklist(state, backend):
                return False

        # Step 3: Execute implementation
        if state.current_step <= 3:
            print_info("Starting Step 3: Execute Implementation")
            if not step_3_execute(state, backend=backend, use_tui=use_tui, verbose=verbose):
                return False

        # Step 4: Update documentation (optional, non-blocking)
        if auto_update_docs:
            print_info("Starting Step 4: Update Documentation")
            # Note: This step is non-blocking - failures don't stop the workflow
            step4_result: Step4Result = step_4_update_docs(state, backend=backend)
            if step4_result.non_doc_reverted:
                log_message(
                    f"Step 4 enforcement: reverted {len(step4_result.non_doc_reverted)} non-doc file(s)"
                )
            if step4_result.error_message:
                log_message(f"Step 4 warning: {step4_result.error_message}")

        # Step 5: Commit changes (optional, non-blocking)
        if auto_commit:
            print_info("Starting Step 5: Commit Changes")
            step5_result: Step5Result = step_5_commit(state, backend=backend)
            if step5_result.error_message:
                log_message(f"Step 5 warning: {step5_result.error_message}")

        # Workflow complete
        _show_completion(state)
        return True


def _setup_branch(
    state: WorkflowState, ticket: GenericTicket, branch_prefix: str = "feature"
) -> bool:
    """Set up the feature branch for the workflow."""
    current_branch = get_current_branch()

    # Use GenericTicket's branch_slug and prepend the prefix
    # Policy: The prefix (e.g., "feature/") is a workflow concern, not model concern
    branch_name = f"{branch_prefix}/{ticket.branch_slug}"

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
    """Show workflow completion message."""
    console.print()
    print_header("Workflow Complete!")

    console.print(f"[bold green]✓[/bold green] Ticket: {state.ticket.id}")
    console.print(f"[bold green]✓[/bold green] Branch: {state.branch_name}")
    console.print(f"[bold green]✓[/bold green] Tasks: {len(state.completed_tasks)} completed")

    if state.plan_file:
        console.print(f"[bold green]✓[/bold green] Plan: {state.plan_file}")
    if state.tasklist_file:
        console.print(f"[bold green]✓[/bold green] Tasks: {state.tasklist_file}")

    console.print()
    print_info("Next steps:")
    print_info("  1. Review the changes")
    print_info("  2. Run tests")
    print_info("  3. Create a pull request")
    console.print()


@contextmanager
def workflow_cleanup(
    state: WorkflowState, backend: AIBackend | None = None
) -> Generator[None, None, None]:
    """Context manager for workflow cleanup on error.

    Handles cleanup when workflow is interrupted or fails.
    Ensures backend resources are released.
    """
    original_branch = get_current_branch()

    try:
        yield
    except UserCancelledError:
        print_info("\nWorkflow cancelled by user")
        _offer_cleanup(state, original_branch)
        raise
    except IngotError as e:
        print_error(f"\nWorkflow error: {e}")
        _offer_cleanup(state, original_branch)
        raise
    except Exception as e:
        print_error(f"\nUnexpected error: {e}")
        _offer_cleanup(state, original_branch)
        raise
    finally:
        if backend is not None:
            backend.close()


def _offer_cleanup(state: WorkflowState, original_branch: str) -> None:
    """Offer cleanup options after workflow failure."""
    console.print()
    print_warning("Workflow did not complete successfully.")

    if state.checkpoint_commits:
        print_info(f"Created {len(state.checkpoint_commits)} checkpoint commits")

    if state.branch_name and state.branch_name != original_branch:
        print_info(f"On branch: {state.branch_name}")
        print_info(f"Original branch: {original_branch}")


__all__ = [
    "run_ingot_workflow",
    "workflow_cleanup",
    # Re-exported from conflict_detection module for backward compatibility
    "_detect_context_conflict",
    "detect_context_conflict",
]
