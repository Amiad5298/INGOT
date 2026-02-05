"""CLI interface for SPEC.

This module provides the Typer-based command-line interface with all
flags and commands matching the original Bash script.

Supports tickets from all 6 platforms: Jira, Linear, GitHub, Azure DevOps, Monday, Trello.
"""

import asyncio
import re
from collections.abc import Callable, Coroutine
from typing import Annotated, TypeVar

import typer

from spec.config.manager import ConfigManager
from spec.integrations.auggie import check_auggie_installed, install_auggie
from spec.integrations.auth import AuthenticationManager
from spec.integrations.git import is_git_repo
from spec.integrations.providers import GenericTicket, Platform
from spec.integrations.providers.exceptions import (
    AuthenticationError,
    PlatformNotSupportedError,
    TicketNotFoundError,
)
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.ticket_service import TicketService, create_ticket_service
from spec.ui.menus import MainMenuChoice, show_main_menu
from spec.utils.console import (
    print_error,
    print_header,
    print_info,
    print_warning,
    show_banner,
    show_version,
)
from spec.utils.errors import ExitCode, SpecError, UserCancelledError
from spec.utils.logging import setup_logging

# Type variable for async helper
T = TypeVar("T")

# Platforms that use the PROJECT-123 format and are ambiguous
# (i.e., can't be distinguished from each other without additional context)
AMBIGUOUS_PLATFORMS: tuple[Platform, ...] = (Platform.JIRA, Platform.LINEAR)

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


class AsyncLoopAlreadyRunningError(SpecError):
    """Raised when trying to run async code in an existing event loop.

    This occurs in environments like Jupyter notebooks or when already
    running inside an async context.
    """

    _default_exit_code = ExitCode.GENERAL_ERROR


def run_async(coro_factory: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run an async coroutine safely, handling existing event loops.

    This helper detects if an event loop is already running (e.g., in Jupyter
    notebooks or dev environments) and raises a clear error instead of
    crashing with asyncio.run().

    Takes a factory function (callable that returns a coroutine) instead of
    a coroutine object directly. This ensures we check for a running loop
    BEFORE creating the coroutine, avoiding the need to close an uncalled
    coroutine and the subtle footgun of discarding side effects that might
    have occurred before the first await.

    Args:
        coro_factory: A callable that returns the coroutine to run.
            Example: lambda: my_async_fn(arg1, arg2)

    Returns:
        The result of the coroutine

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

    Args:
        platform: Platform name string (e.g., "jira", "linear", "azure-devops")

    Returns:
        Platform enum if valid, None if not provided

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

    Args:
        input_str: Ticket input string

    Returns:
        True if the input is ambiguous
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

    Args:
        ticket_input: The ambiguous ticket ID
        config: Configuration manager

    Returns:
        Resolved Platform enum

    Raises:
        UserCancelledError: If user cancels the prompt
    """
    from spec.ui.prompts import prompt_select

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


async def create_ticket_service_from_config(config: ConfigManager) -> TicketService:
    """Create a TicketService with dependencies wired from configuration.

    This is a dependency injection helper that centralizes the creation of
    the AI backend and AuthenticationManager, making the CLI code cleaner
    and easier to test.

    Args:
        config: Configuration manager

    Returns:
        Configured TicketService ready for use as an async context manager

    Example:
        service = await create_ticket_service_from_config(config)
        async with service as svc:
            ticket = await svc.get_ticket("PROJ-123")
    """
    from spec.integrations.backends.auggie import AuggieBackend

    backend = AuggieBackend()
    auth_manager = AuthenticationManager(config)

    return await create_ticket_service(
        backend=backend,
        auth_manager=auth_manager,
        config_manager=config,
    )


async def _fetch_ticket_async(
    ticket_input: str,
    config: ConfigManager,
    platform_hint: Platform | None = None,
) -> GenericTicket:
    """Fetch ticket using TicketService.

    This async function bridges the sync CLI with the async TicketService.

    Args:
        ticket_input: Ticket ID or URL
        config: Configuration manager
        platform_hint: Optional platform override for ambiguous ticket IDs

    Returns:
        GenericTicket from TicketService

    Raises:
        TicketNotFoundError: If ticket cannot be found
        AuthenticationError: If authentication fails
        PlatformNotSupportedError: If platform is not supported
    """
    # Handle platform hint by constructing a more specific input
    effective_input = ticket_input
    if platform_hint is not None and _is_ambiguous_ticket_id(ticket_input):
        effective_input = _resolve_with_platform_hint(ticket_input, platform_hint)

    # Use the dependency injection helper for cleaner code
    service: TicketService = await create_ticket_service_from_config(config)
    async with service:
        ticket: GenericTicket = await service.get_ticket(effective_input)
        return ticket


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

    TODO(https://github.com/Amiad5298/Spec/issues/36): Refactor TicketService to
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

    Args:
        ticket_id: Ambiguous ticket ID (e.g., "PROJ-123")
        platform: Target platform to route to

    Returns:
        Platform-specific URL for routing, or the original ID if no conversion needed
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
    print_header("SPEC Help")
    print_info("SPEC - Spec-driven development workflow using Auggie CLI")
    print_info("")
    print_info("Usage:")
    print_info("  spec [OPTIONS] [TICKET]")
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


def _check_prerequisites(config: ConfigManager, force_integration_check: bool) -> bool:
    """Check all prerequisites for running the workflow.

    Args:
        config: Configuration manager
        force_integration_check: Force fresh platform integration check

    Returns:
        True if all prerequisites are met
    """
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

    # Warn user if they provided --force-integration-check flag
    # This flag currently has no effect but is reserved for future use
    if force_integration_check:
        print_warning(
            "--force-integration-check flag currently has no effect. "
            "Platform integration checks are handled at ticket fetch time."
        )

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


def _run_workflow(
    ticket: str,
    config: ConfigManager,
    platform: Platform | None = None,
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
        ticket: Ticket ID or URL from any supported platform
        config: Configuration manager
        platform: Explicit platform override (from --platform flag)
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
    from spec.workflow.runner import run_spec_driven_workflow
    from spec.workflow.state import DirtyTreePolicy, RateLimitConfig

    # Resolve platform for ambiguous ticket IDs
    effective_platform = platform
    if effective_platform is None and _is_ambiguous_ticket_id(ticket):
        effective_platform = _disambiguate_platform(ticket, config)

    # Fetch ticket using TicketService (async)
    # Use run_async helper to safely handle existing event loops
    try:
        generic_ticket = run_async(
            lambda: _fetch_ticket_async(ticket, config, platform_hint=effective_platform)
        )
    except TicketNotFoundError as e:
        print_error(f"Ticket not found: {e}")
        raise typer.Exit(ExitCode.GENERAL_ERROR) from e
    except AuthenticationError as e:
        print_error(f"Authentication failed: {e}")
        raise typer.Exit(ExitCode.GENERAL_ERROR) from e
    except PlatformNotSupportedError as e:
        print_error(f"Platform not supported: {e}")
        raise typer.Exit(ExitCode.GENERAL_ERROR) from e
    except AsyncLoopAlreadyRunningError as e:
        print_error(str(e))
        raise typer.Exit(ExitCode.GENERAL_ERROR) from e
    except (typer.Exit, SystemExit, KeyboardInterrupt):
        # Allow typer.Exit, SystemExit, and KeyboardInterrupt to propagate
        raise
    except SpecError as e:
        # Handle any other SpecError subclasses
        print_error(str(e))
        raise typer.Exit(e.exit_code) from e
    except Exception as e:
        # Final catch-all for unexpected errors
        print_error(f"Failed to fetch ticket: {e}")
        raise typer.Exit(ExitCode.GENERAL_ERROR) from e

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
                f"Invalid --dirty-tree-policy '{dirty_tree_policy}'. " "Use 'fail-fast' or 'warn'."
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
        ticket=generic_ticket,
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
