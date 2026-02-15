"""Ticket fetching and onboarding for the CLI.

Handles ticket resolution, platform hints, and onboarding retry logic.
"""

from typing import NoReturn

import typer

from ingot.cli.async_helpers import AsyncLoopAlreadyRunningError, run_async
from ingot.cli.platform import _is_ambiguous_ticket_id
from ingot.config.manager import ConfigManager
from ingot.integrations.auth import AuthenticationManager
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import BackendNotConfiguredError, BackendNotInstalledError
from ingot.integrations.providers import GenericTicket, Platform
from ingot.integrations.providers.exceptions import (
    AuthenticationError,
    PlatformNotSupportedError,
    TicketNotFoundError,
)
from ingot.integrations.ticket_service import TicketService, create_ticket_service
from ingot.onboarding import is_first_run, run_onboarding
from ingot.utils.console import print_error
from ingot.utils.errors import ExitCode, IngotError


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
