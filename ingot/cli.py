"""CLI interface for INGOT.

This module provides the Typer-based command-line interface with all
flags and commands matching the original Bash script.

Supports tickets from all 6 platforms: Jira, Linear, GitHub, Azure DevOps, Monday, Trello.
"""

import asyncio
import re
from collections.abc import Callable, Coroutine
from typing import Annotated, NoReturn

import typer

from ingot.config.manager import ConfigManager
from ingot.integrations.auth import AuthenticationManager
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import BackendNotConfiguredError, BackendNotInstalledError
from ingot.integrations.git import is_git_repo
from ingot.integrations.providers import GenericTicket, Platform
from ingot.integrations.providers.exceptions import (
    AuthenticationError,
    PlatformNotSupportedError,
    TicketNotFoundError,
)
from ingot.integrations.providers.registry import ProviderRegistry
from ingot.integrations.ticket_service import TicketService, create_ticket_service
from ingot.onboarding import is_first_run, run_onboarding
from ingot.ui.menus import MainMenuChoice, show_main_menu
from ingot.utils.console import (
    print_error,
    print_header,
    print_info,
    print_warning,
    show_banner,
    show_version,
)
from ingot.utils.errors import ExitCode, IngotError, UserCancelledError
from ingot.utils.logging import setup_logging

# Platforms that use the PROJECT-123 format and are ambiguous
# (i.e., can't be distinguished from each other without additional context)
AMBIGUOUS_PLATFORMS: tuple[Platform, ...] = (Platform.JIRA, Platform.LINEAR)

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


class AsyncLoopAlreadyRunningError(IngotError):
    """Raised when trying to run async code in an existing event loop.

    This occurs in environments like Jupyter notebooks or when already
    running inside an async context.
    """

    _default_exit_code = ExitCode.GENERAL_ERROR


def run_async[T](coro_factory: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run an async coroutine safely, handling existing event loops.

    This helper detects if an event loop is already running (e.g., in Jupyter
    notebooks or dev environments) and raises a clear error instead of
    crashing with asyncio.run().

    Takes a factory function (callable that returns a coroutine) instead of
    a coroutine object directly. This ensures we check for a running loop
    BEFORE creating the coroutine, avoiding the need to close an uncalled
    coroutine and the subtle footgun of discarding side effects that might
    have occurred before the first await.

    Raises:
        AsyncLoopAlreadyRunningError: If an event loop is already running.
            This provides a clear error message instead of cryptic asyncio errors.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        loop = None

    if loop is not None:
        # Raise BEFORE creating the coroutine - no cleanup needed
        raise AsyncLoopAlreadyRunningError(
            "Cannot run async operation: an event loop is already running. "
            "This can happen in Jupyter notebooks or when running inside an async context. "
            "Consider using 'await' directly or running from a synchronous environment."
        )

    return asyncio.run(coro_factory())


def _validate_platform(platform: str | None) -> Platform | None:
    """Validate and convert platform string to Platform enum.

    Normalizes input by replacing hyphens with underscores to support
    both "azure-devops" and "azure_devops" formats.

    Raises:
        typer.BadParameter: If platform name is invalid
    """
    if platform is None:
        return None

    # Normalize: replace hyphens with underscores for user-friendly input
    normalized = platform.replace("-", "_").upper()

    try:
        return Platform[normalized]
    except KeyError:
        valid = ", ".join(p.name.lower().replace("_", "-") for p in Platform)
        raise typer.BadParameter(f"Invalid platform: {platform}. Valid options: {valid}") from None


def _is_ambiguous_ticket_id(input_str: str) -> bool:
    """Check if input is an ambiguous ticket ID (not a URL).

    Ambiguous formats match multiple platforms:
    - PROJECT-123 could be Jira or Linear
    - MY_PROJ-123 (with underscores in project key) could be Jira or Linear

    Unambiguous formats:
    - URLs (https://...)
    - GitHub format (owner/repo#123)
    """
    # URLs are unambiguous
    if input_str.startswith("http://") or input_str.startswith("https://"):
        return False
    # GitHub format (owner/repo#123) is unambiguous
    if re.match(r"^[^/]+/[^#]+#\d+$", input_str):
        return False
    # PROJECT-123 or MY_PROJECT-123 format is ambiguous (Jira or Linear)
    # Supports: letters, digits, and underscores in project key (Jira allows underscores)
    # Must start with a letter
    if re.match(r"^[A-Za-z][A-Za-z0-9_]*-\d+$", input_str):
        return True
    return False


def _platform_display_name(p: Platform) -> str:
    """Convert Platform enum to user-friendly display name (kebab-case).

    Provides a stable, reversible mapping for user-facing strings.
    E.g., Platform.AZURE_DEVOPS -> "azure-devops"
    """
    return p.name.lower().replace("_", "-")


def _disambiguate_platform(ticket_input: str, config: ConfigManager) -> Platform:
    """Resolve ambiguous ticket ID to a specific platform.

    Resolution order:
    1. Check config default_platform setting
    2. Interactive prompt asking user to choose

    Raises:
        UserCancelledError: If user cancels the prompt
    """
    from ingot.ui.prompts import prompt_select

    # Check config default
    default_platform: Platform | None = config.settings.get_default_platform()
    if default_platform is not None:
        return default_platform

    # Build explicit mapping from display string to Platform enum.
    # This avoids brittle string-to-enum parsing (e.g., .upper()) that would
    # fail for enum names with underscores like AZURE_DEVOPS.
    # Note: AMBIGUOUS_PLATFORMS is a tuple, so iteration order is stable.
    # Do not change it to a set or unordered collection without updating tests.
    options: dict[str, Platform] = {_platform_display_name(p): p for p in AMBIGUOUS_PLATFORMS}

    # Interactive prompt
    print_info(f"Ticket ID '{ticket_input}' could be from multiple platforms.")
    choice: str = prompt_select(
        message="Which platform is this ticket from?",
        choices=list(options.keys()),
    )
    return options[choice]


async def create_ticket_service_from_config(
    config_manager: ConfigManager,
    auth_manager: AuthenticationManager | None = None,
    cli_backend_override: str | None = None,
) -> tuple[TicketService, AIBackend]:
    """Create a TicketService with dependencies wired from configuration.

    This is a dependency injection helper that centralizes the creation of
    the AI backend and AuthenticationManager, making the CLI code cleaner
    and easier to test.

    Raises:
        BackendNotConfiguredError: If no backend is configured
        BackendNotInstalledError: If backend CLI is not installed

    Example:
        service, backend = await create_ticket_service_from_config(config)
        async with service as svc:
            ticket = await svc.get_ticket("PROJ-123")
    """
    from ingot.config.backend_resolver import resolve_backend_platform
    from ingot.integrations.backends.factory import BackendFactory

    platform = resolve_backend_platform(config_manager, cli_backend_override)
    backend = BackendFactory.create(platform, verify_installed=True)

    if auth_manager is None:
        auth_manager = AuthenticationManager(config_manager)

    service = await create_ticket_service(
        backend=backend,
        auth_manager=auth_manager,
        config_manager=config_manager,
    )
    return service, backend


async def _fetch_ticket_async(
    ticket_input: str,
    config: ConfigManager,
    platform_hint: Platform | None = None,
    cli_backend_override: str | None = None,
) -> tuple[GenericTicket, AIBackend]:
    """Fetch ticket using TicketService.

    This async function bridges the sync CLI with the async TicketService.

    Raises:
        TicketNotFoundError: If ticket cannot be found
        AuthenticationError: If authentication fails
        PlatformNotSupportedError: If platform is not supported
        BackendNotConfiguredError: If no backend is configured
        BackendNotInstalledError: If backend CLI is not installed
    """
    # Handle platform hint by constructing a more specific input
    effective_input = ticket_input
    if platform_hint is not None and _is_ambiguous_ticket_id(ticket_input):
        effective_input = _resolve_with_platform_hint(ticket_input, platform_hint)

    service, backend = await create_ticket_service_from_config(
        config_manager=config,
        cli_backend_override=cli_backend_override,
    )
    async with service:
        ticket: GenericTicket = await service.get_ticket(effective_input)
        return ticket, backend


# Linear URL template placeholder for platform hint workaround
_LINEAR_URL_TEMPLATE = "https://linear.app/team/issue/{ticket_id}"


def _resolve_with_platform_hint(
    ticket_id: str,
    platform: Platform,
) -> str:
    """Convert ambiguous ticket ID to platform-specific URL for disambiguation.

    This is a WORKAROUND for the limitation that TicketService/ProviderRegistry
    does not currently support a `platform_override` parameter. Instead of passing
    the intended platform directly, we construct a synthetic URL that will route
    to the correct provider during platform detection.

    TODO(https://github.com/Amiad5298/AI-Platform/issues/36): Refactor TicketService to
    accept platform_override parameter
    directly instead of relying on URL-based platform detection. This would
    eliminate the need for synthetic URL construction and make the intent clearer.

    Assumptions:
    - Linear provider's URL regex extracts the ticket ID from the path and
      ignores the team slug ("team" in the template). The fake team name is
      acceptable because the actual API call uses only the ticket ID.
    - Jira provider handles bare IDs natively (no URL needed).
    - Other platforms in AMBIGUOUS_PLATFORMS (if added) may need their own
      URL templates here.
    """
    if platform == Platform.JIRA:
        # Jira provider handles bare IDs natively - no URL construction needed
        return ticket_id
    elif platform == Platform.LINEAR:
        # Construct synthetic Linear URL with placeholder team name
        return _LINEAR_URL_TEMPLATE.format(ticket_id=ticket_id)
    else:
        # Fallback: return as-is for unsupported platforms
        return ticket_id


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
    print_info("  --config                  Show current configuration")
    print_info("  --version, -v             Show version information")
    print_info("  --help, -h                Show this help message")


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


def _run_main_menu(config: ConfigManager) -> None:
    """Run the main menu loop."""
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


def _configure_settings(config: ConfigManager) -> None:
    """Interactive configuration menu."""
    from ingot.ui.menus import show_model_selection
    from ingot.ui.prompts import prompt_confirm, prompt_input

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


def _handle_fetch_error(exc: Exception) -> NoReturn:
    """Map a ticket-fetch exception to a user-facing message and raise typer.Exit.

    This provides a single source of truth for error-to-message mapping,
    used by both the initial fetch and the retry-after-onboarding paths
    in _fetch_ticket_with_onboarding.

    Re-raises typer.Exit, SystemExit, and KeyboardInterrupt directly.
    """
    if isinstance(exc, typer.Exit | SystemExit | KeyboardInterrupt):
        raise exc
    if isinstance(exc, TicketNotFoundError):
        print_error(f"Ticket not found: {exc}")
    elif isinstance(exc, AuthenticationError):
        print_error(f"Authentication failed: {exc}")
    elif isinstance(exc, PlatformNotSupportedError):
        print_error(f"Platform not supported: {exc}")
    elif isinstance(exc, AsyncLoopAlreadyRunningError | BackendNotInstalledError):
        print_error(str(exc))
    elif isinstance(exc, NotImplementedError):
        print_error(f"Backend not available: {exc}")
    elif isinstance(exc, ValueError):
        print_error(f"Invalid backend configuration: {exc}")
    elif isinstance(exc, IngotError):
        print_error(str(exc))
        raise typer.Exit(exc.exit_code) from exc
    else:
        print_error(f"Failed to fetch ticket: {exc}")
    raise typer.Exit(ExitCode.GENERAL_ERROR) from exc


def _fetch_ticket_with_onboarding(
    ticket: str,
    config: ConfigManager,
    effective_platform: Platform | None,
    backend: str | None,
) -> tuple[GenericTicket, AIBackend]:
    """Fetch ticket, running onboarding if no backend is configured.

    If the initial fetch fails with BackendNotConfiguredError, runs the
    onboarding wizard and retries once.

    Raises:
        typer.Exit: On any unrecoverable error
    """
    try:
        return run_async(
            lambda: _fetch_ticket_async(
                ticket,
                config,
                platform_hint=effective_platform,
                cli_backend_override=backend,
            )
        )
    except BackendNotConfiguredError as e:
        # Reload config in case _check_prerequisites already ran onboarding
        config.load()
        if not is_first_run(config):
            # Backend was saved but resolver failed for another reason
            print_error(str(e))
            raise typer.Exit(ExitCode.GENERAL_ERROR) from e

        result = run_onboarding(config)
        if not result.success:
            print_error(result.error_message or "Backend setup cancelled.")
            raise typer.Exit(ExitCode.GENERAL_ERROR) from e
        # Retry ticket fetch now that backend is configured
        try:
            return run_async(
                lambda: _fetch_ticket_async(
                    ticket,
                    config,
                    platform_hint=effective_platform,
                    cli_backend_override=backend,
                )
            )
        except Exception as retry_exc:
            _handle_fetch_error(retry_exc)
    except Exception as e:
        _handle_fetch_error(e)


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

    # Run workflow
    run_ingot_workflow(
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
    )


if __name__ == "__main__":
    app()
