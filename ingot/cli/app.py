"""Typer application and main entry point for the CLI.

Contains the Typer app, main command, and version callback.
"""

from typing import Annotated

import typer

from ingot.cli.menu import _run_main_menu
from ingot.cli.platform import _validate_platform
from ingot.cli.workflow import _check_prerequisites, _run_workflow
from ingot.config.manager import ConfigManager
from ingot.integrations.providers.registry import ProviderRegistry
from ingot.utils.console import (
    print_error,
    print_info,
    show_banner,
    show_version,
)
from ingot.utils.errors import ExitCode, IngotError, UserCancelledError
from ingot.utils.logging import setup_logging

# Create Typer app
app = typer.Typer(
    name="ingot",
    help="INGOT - Spec-driven development workflow using AI backends",
    add_completion=False,
    no_args_is_help=False,
)


def version_callback(value: bool) -> None:
    """Display version and exit."""
    if value:
        show_version()
        raise typer.Exit()


@app.command()
def main(
    ticket: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Ticket ID or URL. Examples: PROJ-123, "
                "https://example.atlassian.net/browse/PROJ-123, "
                "https://linear.app/team/issue/ENG-456, owner/repo#42"
            ),
        ),
    ] = None,
    platform: Annotated[
        str | None,
        typer.Option(
            "--platform",
            "-p",
            help="Override platform detection (jira, linear, github, azure_devops, monday, trello)",
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
    force_integration_check: Annotated[
        bool,
        typer.Option(
            "--force-integration-check",
            help="Force fresh platform integration check",
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
    auto_commit: Annotated[
        bool | None,
        typer.Option(
            "--auto-commit/--no-auto-commit",
            help="Enable automatic commit after workflow (default: from config)",
        ),
    ] = None,
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend",
            "-b",
            help="Override AI backend for this run (auggie, claude, cursor, aider, gemini, codex)",
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
    """INGOT - Spec-driven development workflow using AI backends.

    Start a spec-driven development workflow for a ticket from any
    supported platform (Jira, Linear, GitHub, Azure DevOps, Monday, Trello).
    If no ticket is provided, shows the interactive main menu.
    """
    setup_logging()

    # Validate --platform flag if provided
    platform_enum = _validate_platform(platform)

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

        # Reset and reconfigure ProviderRegistry at startup to ensure deterministic state
        # This prevents stale config from previous runs (e.g., in tests or daemon mode)
        ProviderRegistry.reset_instances()
        ProviderRegistry.set_config(
            {
                "default_jira_project": config.settings.default_jira_project or "",
            }
        )

        # Handle --config flag
        if show_config:
            config.show()
            raise typer.Exit()

        # Check prerequisites
        if not _check_prerequisites(config, force_integration_check):
            raise typer.Exit(ExitCode.GENERAL_ERROR)

        # If ticket provided, start workflow directly
        if ticket:
            _run_workflow(
                ticket=ticket,
                config=config,
                platform=platform_enum,
                backend=backend,
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
                auto_commit=auto_commit,
            )
        else:
            # Show main menu
            _run_main_menu(config)

    except UserCancelledError as e:
        print_info(f"\n{e}")
        raise typer.Exit(ExitCode.USER_CANCELLED) from e

    except IngotError as e:
        print_error(str(e))
        raise typer.Exit(e.exit_code) from e

    except KeyboardInterrupt as e:
        print_info("\nOperation cancelled by user")
        raise typer.Exit(ExitCode.USER_CANCELLED) from e
