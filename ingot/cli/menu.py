"""Menu and configuration UI for the CLI.

Provides the main menu loop and interactive configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ingot.config.manager import ConfigManager
from ingot.ui.menus import MainMenuChoice, show_main_menu
from ingot.utils.console import print_error, print_header, print_info

if TYPE_CHECKING:
    from ingot.integrations.backends.base import AIBackend


def show_help() -> None:
    """Display help information."""
    print_header("INGOT Help")
    print_info("INGOT - Spec-driven development workflow using AI backends")
    print_info("")
    print_info("Usage:")
    print_info("  ingot [OPTIONS] [TICKET]")
    print_info("")
    print_info("Arguments:")
    print_info("  TICKET    Ticket ID or URL from any supported platform")
    print_info("            Examples: PROJ-123, https://example.atlassian.net/browse/PROJ-123,")
    print_info("            https://linear.app/team/issue/ENG-456, owner/repo#42")
    print_info("")
    print_info("Options:")
    print_info("  --platform, -p PLATFORM   Override platform detection (jira, linear, github,")
    print_info("                            azure_devops, monday, trello)")
    print_info("  --model, -m MODEL         Override default AI model")
    print_info("  --planning-model MODEL    Model for planning phases")
    print_info("  --impl-model MODEL        Model for implementation phase")
    print_info("  --skip-clarification      Skip clarification step")
    print_info("  --no-squash               Don't squash commits at end")
    print_info("  --force-integration-check Force fresh platform integration check")
    print_info("  --tui/--no-tui            Enable/disable TUI mode (default: auto)")
    print_info("  --verbose, -V             Show verbose output in TUI log panel")
    print_info("  --parallel/--no-parallel  Enable/disable parallel task execution")
    print_info("  --max-parallel N          Max parallel tasks (1-5, default: from config)")
    print_info("  --fail-fast/--no-fail-fast  Stop on first task failure (default: from config)")
    print_info("  --max-retries N           Max retries on rate limit (0 to disable)")
    print_info("  --retry-base-delay SECS   Base delay for retry backoff (seconds)")
    print_info("  --enable-review           Enable phase reviews after task execution")
    print_info("  --auto-update-docs/--no-auto-update-docs  Enable/disable doc updates")
    print_info("  --auto-commit/--no-auto-commit  Enable/disable auto-commit")
    print_info("  --config                  Show current configuration")
    print_info("  --version, -v             Show version information")
    print_info("  --help, -h                Show this help message")


def _run_main_menu(config: ConfigManager) -> None:
    """Run the main menu loop."""
    from ingot.cli.workflow import _run_workflow

    while True:
        choice = show_main_menu()

        if choice == MainMenuChoice.START_WORKFLOW:
            from ingot.ui.prompts import prompt_input

            ticket = prompt_input("Enter ticket ID or URL")
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


def _get_current_backend(config: ConfigManager) -> AIBackend | None:
    """Resolve the current backend instance for model listing.

    Returns None on any error (no backend configured, import failure, etc.).
    """
    try:
        from ingot.config.backend_resolver import resolve_backend_platform
        from ingot.integrations.backends.factory import BackendFactory

        platform = resolve_backend_platform(config)
        return BackendFactory.create(platform)
    except Exception:
        return None


def _configure_settings(config: ConfigManager) -> None:
    """Interactive configuration menu."""
    from ingot.ui.menus import show_model_selection
    from ingot.ui.prompts import prompt_confirm, prompt_input

    print_header("Configure Settings")

    backend = _get_current_backend(config)

    # Planning model
    if prompt_confirm("Configure planning model?", default=False):
        model = show_model_selection(
            current_model=config.settings.planning_model,
            purpose="planning (Steps 1-2)",
            backend=backend,
        )
        if model:
            config.save("PLANNING_MODEL", model)

    # Implementation model
    if prompt_confirm("Configure implementation model?", default=False):
        model = show_model_selection(
            current_model=config.settings.implementation_model,
            purpose="implementation (Step 3)",
            backend=backend,
        )
        if model:
            config.save("IMPLEMENTATION_MODEL", model)

    # Default Jira project (Jira-specific setting for numeric ticket IDs)
    if prompt_confirm("Configure default project key (Jira only)?", default=False):
        project = prompt_input(
            "Enter default Jira project key (used when ticket ID has no project prefix)",
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
