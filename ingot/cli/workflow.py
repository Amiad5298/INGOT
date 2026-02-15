"""Workflow orchestration for the CLI.

Handles prerequisites checking and workflow execution from CLI context.
"""

import typer

from ingot.cli.platform import _disambiguate_platform, _is_ambiguous_ticket_id
from ingot.cli.ticket import _fetch_ticket_with_onboarding
from ingot.config.manager import ConfigManager
from ingot.integrations.git import is_git_repo
from ingot.integrations.providers import Platform
from ingot.onboarding import is_first_run, run_onboarding
from ingot.utils.console import print_error, print_warning
from ingot.utils.errors import ExitCode


def _check_prerequisites(config: ConfigManager, force_integration_check: bool) -> bool:
    """Check all prerequisites for running the workflow."""
    # Check git repository
    if not is_git_repo():
        print_error("Not in a git repository. Please run from a git repository.")
        return False

    # Run onboarding if no backend is configured
    if is_first_run(config):
        result = run_onboarding(config)
        if not result.success:
            print_error(result.error_message or "Backend setup cancelled.")
            return False

    # Warn user if they provided --force-integration-check flag
    # This flag currently has no effect but is reserved for future use
    if force_integration_check:
        print_warning(
            "--force-integration-check flag currently has no effect. "
            "Platform integration checks are handled at ticket fetch time."
        )

    return True


def _run_workflow(
    ticket: str,
    config: ConfigManager,
    platform: Platform | None = None,
    backend: str | None = None,
    model: str | None = None,
    planning_model: str | None = None,
    impl_model: str | None = None,
    skip_clarification: bool = False,
    squash_at_end: bool = True,
    use_tui: bool | None = None,
    verbose: bool = False,
    parallel: bool | None = None,
    max_parallel: int | None = None,
    fail_fast: bool | None = None,
    max_retries: int = 5,
    retry_base_delay: float = 2.0,
    enable_review: bool = False,
    dirty_tree_policy: str | None = None,
    auto_update_docs: bool | None = None,
    auto_commit: bool | None = None,
) -> None:
    """Run the AI-assisted workflow."""
    from ingot.workflow.runner import run_ingot_workflow
    from ingot.workflow.state import DirtyTreePolicy, RateLimitConfig

    # Resolve platform for ambiguous ticket IDs
    effective_platform = platform
    if effective_platform is None and _is_ambiguous_ticket_id(ticket):
        effective_platform = _disambiguate_platform(ticket, config)

    # Fetch ticket using TicketService (async)
    # Use run_async helper to safely handle existing event loops
    generic_ticket, ai_backend = _fetch_ticket_with_onboarding(
        ticket, config, effective_platform, backend
    )

    # Determine models
    effective_planning_model = (
        planning_model or model or config.settings.planning_model or config.settings.default_model
    )
    effective_impl_model = (
        impl_model or model or config.settings.implementation_model or config.settings.default_model
    )

    # Determine parallel execution settings
    effective_parallel = (
        parallel if parallel is not None else config.settings.parallel_execution_enabled
    )
    effective_max_parallel = (
        max_parallel if max_parallel is not None else config.settings.max_parallel_tasks
    )
    effective_fail_fast = fail_fast if fail_fast is not None else config.settings.fail_fast

    # Validate effective_max_parallel (catches invalid config values too)
    if effective_max_parallel < 1 or effective_max_parallel > 5:
        print_error(f"Invalid max_parallel={effective_max_parallel} (must be 1-5)")
        raise typer.Exit(ExitCode.GENERAL_ERROR)

    # Parse dirty tree policy
    effective_dirty_tree_policy = DirtyTreePolicy.FAIL_FAST  # default
    if dirty_tree_policy:
        policy_lower = dirty_tree_policy.lower().replace("-", "_")
        if policy_lower in ("fail_fast", "fail"):
            effective_dirty_tree_policy = DirtyTreePolicy.FAIL_FAST
        elif policy_lower in ("warn_and_continue", "warn"):
            effective_dirty_tree_policy = DirtyTreePolicy.WARN_AND_CONTINUE
        else:
            print_error(
                f"Invalid --dirty-tree-policy '{dirty_tree_policy}'. Use 'fail-fast' or 'warn'."
            )
            raise typer.Exit(ExitCode.GENERAL_ERROR)

    # Build rate limit config
    rate_limit_config = RateLimitConfig(
        max_retries=max_retries,
        base_delay_seconds=retry_base_delay,
    )

    # Determine auto_update_docs setting
    effective_auto_update_docs = (
        auto_update_docs if auto_update_docs is not None else config.settings.auto_update_docs
    )

    # Determine auto_commit setting
    effective_auto_commit = auto_commit if auto_commit is not None else config.settings.auto_commit

    # Run workflow
    result = run_ingot_workflow(
        ticket=generic_ticket,
        config=config,
        backend=ai_backend,
        planning_model=effective_planning_model,
        implementation_model=effective_impl_model,
        skip_clarification=skip_clarification or config.settings.skip_clarification,
        squash_at_end=squash_at_end and config.settings.squash_at_end,
        use_tui=use_tui,
        verbose=verbose,
        parallel_execution_enabled=effective_parallel,
        max_parallel_tasks=effective_max_parallel,
        fail_fast=effective_fail_fast,
        rate_limit_config=rate_limit_config,
        enable_phase_review=enable_review,
        dirty_tree_policy=effective_dirty_tree_policy,
        auto_update_docs=effective_auto_update_docs,
        auto_commit=effective_auto_commit,
    )
    if not result:
        raise typer.Exit(code=ExitCode.GENERAL_ERROR)
