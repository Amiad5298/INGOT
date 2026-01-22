"""CLI interface for SPEC.

This module provides the Typer-based command-line interface with all
flags and commands matching the original Bash script.
"""

from typing import Annotated

import typer

from spec.config.manager import ConfigManager
from spec.integrations.auggie import check_auggie_installed, install_auggie
from spec.integrations.git import is_git_repo
from spec.integrations.jira import check_jira_integration
from spec.ui.menus import MainMenuChoice, show_main_menu
from spec.utils.console import (
    print_error,
    print_header,
    print_info,
    show_banner,
    show_version,
)
from spec.utils.errors import ExitCode, SpecError, UserCancelledError
from spec.utils.logging import setup_logging

# Create Typer app
app = typer.Typer(
    name="spec",
    help="SPEC - Spec-driven development workflow using Auggie CLI",
    add_completion=False,
    no_args_is_help=False,
)


def version_callback(value: bool) -> None:
    """Display version and exit."""
    if value:
        show_version()
        raise typer.Exit()


def show_help() -> None:
    """Display help information."""
    print_header("SPEC Help")
    print_info("SPEC - Spec-driven development workflow using Auggie CLI")
    print_info("")
    print_info("Usage:")
    print_info("  spec [OPTIONS] [TICKET]")
    print_info("")
    print_info("Arguments:")
    print_info("  TICKET    Jira ticket ID or URL (e.g., PROJECT-123)")
    print_info("")
    print_info("Options:")
    print_info("  --model, -m MODEL         Override default AI model")
    print_info("  --planning-model MODEL    Model for planning phases")
    print_info("  --impl-model MODEL        Model for implementation phase")
    print_info("  --skip-clarification      Skip clarification step")
    print_info("  --no-squash               Don't squash commits at end")
    print_info("  --force-jira-check        Force fresh Jira integration check")
    print_info("  --tui/--no-tui            Enable/disable TUI mode (default: auto)")
    print_info("  --verbose, -V             Show verbose output in TUI log panel")
    print_info("  --parallel/--no-parallel  Enable/disable parallel task execution")
    print_info("  --max-parallel N          Max parallel tasks (1-5, default: from config)")
    print_info("  --fail-fast/--no-fail-fast  Stop on first task failure (default: from config)")
    print_info("  --max-retries N           Max retries on rate limit (0 to disable)")
    print_info("  --retry-base-delay SECS   Base delay for retry backoff (seconds)")
    print_info("  --enable-review           Enable phase reviews after task execution")
    print_info("  --auto-update-docs/--no-auto-update-docs  Enable/disable doc updates")
    print_info("  --config                  Show current configuration")
    print_info("  --version, -v             Show version information")
    print_info("  --help, -h                Show this help message")


@app.command()
def main(
    ticket: Annotated[
        str | None,
        typer.Argument(
            help="Jira ticket ID or URL (e.g., PROJECT-123)",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Override default AI model for all phases",
        ),
    ] = None,
    planning_model: Annotated[
        str | None,
        typer.Option(
            "--planning-model",
            help="AI model for planning phases (Steps 1-2)",
        ),
    ] = None,
    impl_model: Annotated[
        str | None,
        typer.Option(
            "--impl-model",
            help="AI model for implementation phase (Step 3)",
        ),
    ] = None,
    skip_clarification: Annotated[
        bool,
        typer.Option(
            "--skip-clarification",
            help="Skip the clarification step",
        ),
    ] = False,
    no_squash: Annotated[
        bool,
        typer.Option(
            "--no-squash",
            help="Don't squash checkpoint commits at end",
        ),
    ] = False,
    force_jira_check: Annotated[
        bool,
        typer.Option(
            "--force-jira-check",
            help="Force fresh Jira integration check",
        ),
    ] = False,
    tui: Annotated[
        bool | None,
        typer.Option(
            "--tui/--no-tui",
            help="Enable/disable TUI mode (default: auto-detect TTY)",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-V",
            help="Show verbose output in TUI log panel",
        ),
    ] = False,
    parallel: Annotated[
        bool | None,
        typer.Option(
            "--parallel/--no-parallel",
            help="Enable parallel execution of independent tasks (default: enabled)",
        ),
    ] = None,
    max_parallel: Annotated[
        int | None,
        typer.Option(
            "--max-parallel",
            help="Maximum number of parallel tasks (1-5, default: from config)",
        ),
    ] = None,
    fail_fast: Annotated[
        bool | None,
        typer.Option(
            "--fail-fast/--no-fail-fast",
            help="Stop on first task failure (default: from config)",
        ),
    ] = None,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="Max retries on rate limit (0 to disable)",
        ),
    ] = 5,
    retry_base_delay: Annotated[
        float,
        typer.Option(
            "--retry-base-delay",
            help="Base delay for retry backoff (seconds)",
        ),
    ] = 2.0,
    enable_review: Annotated[
        bool,
        typer.Option(
            "--enable-review",
            help="Enable phase reviews after task execution",
        ),
    ] = False,
    dirty_tree_policy: Annotated[
        str | None,
        typer.Option(
            "--dirty-tree-policy",
            help="Policy for dirty working tree: 'fail-fast' (default) or 'warn'",
        ),
    ] = None,
    auto_update_docs: Annotated[
        bool | None,
        typer.Option(
            "--auto-update-docs/--no-auto-update-docs",
            help="Enable automatic documentation updates (default: from config)",
        ),
    ] = None,
    show_config: Annotated[
        bool,
        typer.Option(
            "--config",
            help="Show current configuration and exit",
        ),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            callback=version_callback,
            is_eager=True,
            help="Show version information",
        ),
    ] = None,
) -> None:
    """SPEC - Spec-driven development workflow using Auggie CLI.

    Start a spec-driven development workflow for a Jira ticket.
    If no ticket is provided, shows the interactive main menu.
    """
    setup_logging()

    # Validate max_parallel if provided via CLI
    if max_parallel is not None and (max_parallel < 1 or max_parallel > 5):
        print_error("Error: --max-parallel must be between 1 and 5")
        raise typer.Exit(ExitCode.GENERAL_ERROR)

    try:
        # Show banner
        show_banner()

        # Load configuration
        config = ConfigManager()
        config.load()

        # Handle --config flag
        if show_config:
            config.show()
            raise typer.Exit()

        # Check prerequisites
        if not _check_prerequisites(config, force_jira_check):
            raise typer.Exit(ExitCode.GENERAL_ERROR)

        # If ticket provided, start workflow directly
        if ticket:
            _run_workflow(
                ticket=ticket,
                config=config,
                model=model,
                planning_model=planning_model,
                impl_model=impl_model,
                skip_clarification=skip_clarification,
                squash_at_end=not no_squash,
                use_tui=tui,
                verbose=verbose,
                parallel=parallel,
                max_parallel=max_parallel,
                fail_fast=fail_fast,
                max_retries=max_retries,
                retry_base_delay=retry_base_delay,
                enable_review=enable_review,
                dirty_tree_policy=dirty_tree_policy,
                auto_update_docs=auto_update_docs,
            )
        else:
            # Show main menu
            _run_main_menu(config)

    except UserCancelledError as e:
        print_info(f"\n{e}")
        raise typer.Exit(ExitCode.USER_CANCELLED) from e

    except SpecError as e:
        print_error(str(e))
        raise typer.Exit(e.exit_code) from e

    except KeyboardInterrupt as e:
        print_info("\nOperation cancelled by user")
        raise typer.Exit(ExitCode.USER_CANCELLED) from e


def _check_prerequisites(config: ConfigManager, force_jira_check: bool) -> bool:
    """Check all prerequisites for running the workflow.

    Args:
        config: Configuration manager
        force_jira_check: Force fresh Jira check

    Returns:
        True if all prerequisites are met
    """
    from spec.integrations.auggie import AuggieClient

    # Check git repository
    if not is_git_repo():
        print_error("Not in a git repository. Please run from a git repository.")
        return False

    # Check Auggie installation
    is_valid, message = check_auggie_installed()
    if not is_valid:
        print_error(message)
        from spec.ui.prompts import prompt_confirm

        if prompt_confirm("Would you like to install Auggie CLI now?"):
            if not install_auggie():
                return False
        else:
            return False

    # Check Jira integration (optional but recommended)
    auggie = AuggieClient()
    check_jira_integration(config, auggie, force=force_jira_check)

    return True


def _run_main_menu(config: ConfigManager) -> None:
    """Run the main menu loop.

    Args:
        config: Configuration manager
    """
    while True:
        choice = show_main_menu()

        if choice == MainMenuChoice.START_WORKFLOW:
            from spec.ui.prompts import prompt_input

            ticket = prompt_input("Enter Jira ticket ID or URL")
            if ticket:
                _run_workflow(ticket=ticket, config=config)
            break

        elif choice == MainMenuChoice.CONFIGURE:
            _configure_settings(config)

        elif choice == MainMenuChoice.SHOW_CONFIG:
            config.show()

        elif choice == MainMenuChoice.HELP:
            show_help()

        elif choice == MainMenuChoice.QUIT:
            print_info("Goodbye!")
            break


def _configure_settings(config: ConfigManager) -> None:
    """Interactive configuration menu.

    Args:
        config: Configuration manager
    """
    from spec.ui.menus import show_model_selection
    from spec.ui.prompts import prompt_confirm, prompt_input

    print_header("Configure Settings")

    # Planning model
    if prompt_confirm("Configure planning model?", default=False):
        model = show_model_selection(
            current_model=config.settings.planning_model,
            purpose="planning (Steps 1-2)",
        )
        if model:
            config.save("PLANNING_MODEL", model)

    # Implementation model
    if prompt_confirm("Configure implementation model?", default=False):
        model = show_model_selection(
            current_model=config.settings.implementation_model,
            purpose="implementation (Step 3)",
        )
        if model:
            config.save("IMPLEMENTATION_MODEL", model)

    # Default Jira project
    if prompt_confirm("Configure default Jira project?", default=False):
        project = prompt_input(
            "Enter default Jira project key",
            default=config.settings.default_jira_project,
        )
        if project:
            config.save("DEFAULT_JIRA_PROJECT", project.upper())

    # Parallel execution settings
    if prompt_confirm("Configure parallel execution settings?", default=False):
        # Enable/disable parallel execution
        parallel_enabled = prompt_confirm(
            "Enable parallel execution of independent tasks?",
            default=config.settings.parallel_execution_enabled,
        )
        config.save("PARALLEL_EXECUTION_ENABLED", str(parallel_enabled).lower())

        # Max parallel tasks
        max_parallel_str = prompt_input(
            "Maximum parallel tasks (1-5)",
            default=str(config.settings.max_parallel_tasks),
        )
        try:
            max_parallel = int(max_parallel_str)
            if 1 <= max_parallel <= 5:
                config.save("MAX_PARALLEL_TASKS", str(max_parallel))
            else:
                print_error("Invalid value. Must be between 1 and 5. Keeping current value.")
        except ValueError:
            print_error("Invalid number. Keeping current value.")

        # Fail fast
        fail_fast = prompt_confirm(
            "Stop on first task failure (fail-fast)?",
            default=config.settings.fail_fast,
        )
        config.save("FAIL_FAST", str(fail_fast).lower())

    print_info("Configuration saved!")


def _run_workflow(
    ticket: str,
    config: ConfigManager,
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
) -> None:
    """Run the AI-assisted workflow.

    Args:
        ticket: Jira ticket ID or URL
        config: Configuration manager
        model: Override model for all phases
        planning_model: Model for planning phases
        impl_model: Model for implementation phase
        skip_clarification: Skip clarification step
        squash_at_end: Squash commits at end
        use_tui: Override for TUI mode. None = auto-detect.
        verbose: Enable verbose mode in TUI (expanded log panel).
        parallel: Override for parallel execution. None = use config.
        max_parallel: Maximum number of parallel tasks (1-5). None = use config.
        fail_fast: Stop on first task failure. None = use config.
        max_retries: Max retries on rate limit (0 to disable).
        retry_base_delay: Base delay for retry backoff (seconds).
        enable_review: Enable phase reviews after task execution.
        dirty_tree_policy: Policy for dirty working tree: 'fail-fast' or 'warn'.
        auto_update_docs: Enable documentation updates. None = use config.
    """
    from spec.integrations.jira import parse_jira_ticket
    from spec.workflow.runner import run_spec_driven_workflow
    from spec.workflow.state import DirtyTreePolicy, RateLimitConfig

    # Parse ticket
    jira_ticket = parse_jira_ticket(
        ticket,
        default_project=config.settings.default_jira_project,
    )

    # Determine models
    effective_planning_model = (
        planning_model or model or config.settings.planning_model or config.settings.default_model
    )
    effective_impl_model = (
        impl_model or model or config.settings.implementation_model or config.settings.default_model
    )

    # Determine parallel execution settings
    effective_parallel = parallel if parallel is not None else config.settings.parallel_execution_enabled
    effective_max_parallel = max_parallel if max_parallel is not None else config.settings.max_parallel_tasks
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
                f"Invalid --dirty-tree-policy '{dirty_tree_policy}'. "
                "Use 'fail-fast' or 'warn'."
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

    # Run workflow
    run_spec_driven_workflow(
        ticket=jira_ticket,
        config=config,
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
    )


if __name__ == "__main__":
    app()

