"""CLI interface for AI Workflow.

This module provides the Typer-based command-line interface with all
flags and commands matching the original Bash script.
"""

import sys
from typing import Annotated, Optional

import typer

from ai_workflow import __version__
from ai_workflow.config.manager import ConfigManager
from ai_workflow.integrations.auggie import check_auggie_installed, install_auggie
from ai_workflow.integrations.git import is_git_repo
from ai_workflow.integrations.jira import check_jira_integration
from ai_workflow.ui.menus import MainMenuChoice, show_main_menu
from ai_workflow.utils.console import (
    print_error,
    print_header,
    print_info,
    show_banner,
    show_version,
)
from ai_workflow.utils.errors import AIWorkflowError, ExitCode, UserCancelledError
from ai_workflow.utils.logging import setup_logging

# Create Typer app
app = typer.Typer(
    name="ai-workflow",
    help="AI-Assisted Development Workflow using Auggie CLI",
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
    print_header("AI Workflow Help")
    print_info("AI-Assisted Development Workflow using Auggie CLI")
    print_info("")
    print_info("Usage:")
    print_info("  ai-workflow [OPTIONS] [TICKET]")
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
    print_info("  --config                  Show current configuration")
    print_info("  --version, -v             Show version information")
    print_info("  --help, -h                Show this help message")


@app.command()
def main(
    ticket: Annotated[
        Optional[str],
        typer.Argument(
            help="Jira ticket ID or URL (e.g., PROJECT-123)",
        ),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Override default AI model for all phases",
        ),
    ] = None,
    planning_model: Annotated[
        Optional[str],
        typer.Option(
            "--planning-model",
            help="AI model for planning phases (Steps 1-2)",
        ),
    ] = None,
    impl_model: Annotated[
        Optional[str],
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
        Optional[bool],
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
    show_config: Annotated[
        bool,
        typer.Option(
            "--config",
            help="Show current configuration and exit",
        ),
    ] = False,
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            callback=version_callback,
            is_eager=True,
            help="Show version information",
        ),
    ] = None,
) -> None:
    """AI-Assisted Development Workflow using Auggie CLI.

    Start an AI-assisted development workflow for a Jira ticket.
    If no ticket is provided, shows the interactive main menu.
    """
    setup_logging()

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
            )
        else:
            # Show main menu
            _run_main_menu(config)

    except UserCancelledError as e:
        print_info(f"\n{e}")
        raise typer.Exit(ExitCode.USER_CANCELLED)

    except AIWorkflowError as e:
        print_error(str(e))
        raise typer.Exit(e.exit_code)

    except KeyboardInterrupt:
        print_info("\nOperation cancelled by user")
        raise typer.Exit(ExitCode.USER_CANCELLED)


def _check_prerequisites(config: ConfigManager, force_jira_check: bool) -> bool:
    """Check all prerequisites for running the workflow.

    Args:
        config: Configuration manager
        force_jira_check: Force fresh Jira check

    Returns:
        True if all prerequisites are met
    """
    from ai_workflow.integrations.auggie import AuggieClient

    # Check git repository
    if not is_git_repo():
        print_error("Not in a git repository. Please run from a git repository.")
        return False

    # Check Auggie installation
    is_valid, message = check_auggie_installed()
    if not is_valid:
        print_error(message)
        from ai_workflow.ui.prompts import prompt_confirm

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
            from ai_workflow.ui.prompts import prompt_input

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
    from ai_workflow.ui.menus import show_model_selection
    from ai_workflow.ui.prompts import prompt_confirm, prompt_input

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

    print_info("Configuration saved!")


def _run_workflow(
    ticket: str,
    config: ConfigManager,
    model: Optional[str] = None,
    planning_model: Optional[str] = None,
    impl_model: Optional[str] = None,
    skip_clarification: bool = False,
    squash_at_end: bool = True,
    use_tui: Optional[bool] = None,
    verbose: bool = False,
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
    """
    from ai_workflow.integrations.jira import parse_jira_ticket
    from ai_workflow.workflow.runner import run_spec_driven_workflow

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
    )


if __name__ == "__main__":
    app()

