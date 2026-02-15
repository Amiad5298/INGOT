"""CLI interface for INGOT.

This package provides the Typer-based command-line interface with all
flags and commands matching the original Bash script.

Supports tickets from all 6 platforms: Jira, Linear, GitHub, Azure DevOps, Monday, Trello.
"""

# Re-export everything for backward compatibility.
# Existing imports like `from ingot.cli import app` continue to work.
from ingot.cli.app import app, main, version_callback
from ingot.cli.async_helpers import AsyncLoopAlreadyRunningError, run_async
from ingot.cli.menu import _configure_settings, _run_main_menu, show_help
from ingot.cli.platform import (
    AMBIGUOUS_PLATFORMS,
    _disambiguate_platform,
    _is_ambiguous_ticket_id,
    _platform_display_name,
    _validate_platform,
)
from ingot.cli.ticket import (
    _LINEAR_URL_TEMPLATE,
    _fetch_ticket_async,
    _fetch_ticket_with_onboarding,
    _handle_fetch_error,
    _resolve_with_platform_hint,
    create_ticket_service_from_config,
)
from ingot.cli.workflow import _check_prerequisites, _run_workflow

__all__ = [
    # app.py
    "app",
    "main",
    "version_callback",
    # async_helpers.py
    "AsyncLoopAlreadyRunningError",
    "run_async",
    # menu.py
    "show_help",
    "_run_main_menu",
    "_configure_settings",
    # platform.py
    "AMBIGUOUS_PLATFORMS",
    "_validate_platform",
    "_is_ambiguous_ticket_id",
    "_platform_display_name",
    "_disambiguate_platform",
    # ticket.py
    "create_ticket_service_from_config",
    "_fetch_ticket_async",
    "_resolve_with_platform_hint",
    "_LINEAR_URL_TEMPLATE",
    "_handle_fetch_error",
    "_fetch_ticket_with_onboarding",
    # workflow.py
    "_check_prerequisites",
    "_run_workflow",
]
