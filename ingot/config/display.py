"""Configuration display functions for INGOT.

Standalone functions extracted from ConfigManager for displaying
configuration status (platform tables, settings summaries).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ingot.config.manager import PLATFORM_DISPLAY_NAMES, _get_known_platforms
from ingot.utils.console import console, print_header, print_info

if TYPE_CHECKING:
    from ingot.config.manager import ConfigManager

# Module-level logger
logger = logging.getLogger(__name__)


def get_agent_integrations(manager: ConfigManager) -> dict[str, bool]:
    """Get agent integration status for all platforms.

    Reads from AgentConfig which is populated from AGENT_INTEGRATION_* config keys.
    Falls back to default Auggie integrations ONLY if:
    1. No explicit config is set (integrations is None, not empty dict), AND
    2. The agent platform is AUGGIE

    For non-Auggie platforms (manual, cursor, etc.) with no explicit integrations,
    returns False for all platforms to avoid falsely reporting agent support.

    Note: An empty dict `{}` means the user explicitly disabled all integrations,
    which is different from None (no config set).
    """
    known_platforms = _get_known_platforms()
    agent_config = manager.get_agent_config()

    # Now that AgentConfig.supports_platform handles defaults, we can simplify
    result = {}
    for platform in known_platforms:
        result[platform] = agent_config.supports_platform(platform)

    return result


def get_fallback_status(manager: ConfigManager) -> dict[str, bool]:
    """Get fallback credential status for all platforms."""
    # Lazy imports to avoid circular dependencies
    from ingot.integrations.auth import AuthenticationManager
    from ingot.integrations.providers import Platform

    known_platforms = _get_known_platforms()
    auth = AuthenticationManager(manager)
    result: dict[str, bool] = {}
    for platform_name in known_platforms:
        try:
            platform_enum = Platform[platform_name.upper()]
            result[platform_name] = auth.has_fallback_configured(platform_enum)
        except KeyError:
            # Platform enum not found - mark as not configured
            logger.debug(f"Platform enum not found for '{platform_name}'")
            result[platform_name] = False
        except Exception as e:
            # Catch all exceptions to prevent one platform from crashing
            # the entire status table. Log to debug and continue.
            logger.debug(f"Error checking fallback for {platform_name}: {e}")
            result[platform_name] = False

    return result


def get_platform_ready_status(
    agent_integrations: dict[str, bool],
    fallback_status: dict[str, bool],
) -> dict[str, bool]:
    """Determine if each platform is ready to use.

    A platform is ready if it has agent integration OR fallback
    credentials configured.
    """
    known_platforms = _get_known_platforms()
    return {
        p: agent_integrations.get(p, False) or fallback_status.get(p, False)
        for p in known_platforms
    }


def show_platform_status(manager: ConfigManager) -> None:
    """Display platform configuration status as a Rich table.

    Handles errors gracefully - if Rich is unavailable or fails,
    falls back to plain-text output to maintain status visibility.

    Error handling strategy:
    1. If status computation fails: show error message and return
    2. If Rich Table creation/printing fails: fall back to plain-text
    3. Uses standard print() for error messages to avoid Rich dependency issues
    """
    # Get status data first (before Rich-specific code)
    # This allows fallback to use the same data
    agent_integrations: dict[str, bool] | None = None
    fallback_status_data: dict[str, bool] | None = None
    ready_status: dict[str, bool] | None = None

    try:
        agent_integrations = get_agent_integrations(manager)
        fallback_status_data = get_fallback_status(manager)
        ready_status = get_platform_ready_status(agent_integrations, fallback_status_data)
    except Exception as e:
        # Status computation failed - use standard print() for robustness
        # (console.print may fail if Rich is not installed or broken)
        try:
            console.print("  [bold]Platform Status:[/bold]")
            console.print(f"  [dim]Unable to determine platform status: {e}[/dim]")
            console.print()
        except Exception:
            # Fall back to standard print if Rich console also fails
            print("  Platform Status:")
            print(f"  Unable to determine platform status: {e}")
            print()
        return

    try:
        from rich.table import Table

        # Create table
        table = Table(title=None, show_header=True, header_style="bold")
        table.add_column("Platform", style="cyan")
        table.add_column("Agent Support")
        table.add_column("Credentials")
        table.add_column("Status")

        # Sort platforms for consistent display order
        known_platforms = _get_known_platforms()
        for platform in sorted(known_platforms):
            display_name = PLATFORM_DISPLAY_NAMES.get(platform, platform.title())
            agent = "✅ Yes" if agent_integrations.get(platform, False) else "❌ No"
            creds = "✅ Configured" if fallback_status_data.get(platform, False) else "❌ None"

            if ready_status.get(platform, False):
                status = "[green]✅ Ready[/green]"
            else:
                status = "[yellow]❌ Needs Config[/yellow]"

            table.add_row(display_name, agent, creds, status)

        console.print("  [bold]Platform Status:[/bold]")
        console.print(table)

        # Show hint for unconfigured platforms
        unconfigured = [p for p, ready in ready_status.items() if not ready]
        if unconfigured:
            console.print()
            console.print(
                "  [dim]Tip: See docs/platform-configuration.md for credential setup[/dim]"
            )
        console.print()

    except Exception:
        # Rich failed - fall back to plain-text output using standard print()
        logger.debug("Rich rendering failed; falling back to plain text", exc_info=True)
        show_platform_status_plain_text(agent_integrations, fallback_status_data, ready_status)


def show_platform_status_plain_text(
    agent_integrations: dict[str, bool],
    fallback_status_data: dict[str, bool],
    ready_status: dict[str, bool],
) -> None:
    """Display platform status as plain text (fallback when Rich fails).

    Uses dynamic column widths to accommodate platform names of any length.
    """
    known_platforms = _get_known_platforms()

    # Build row data first to calculate dynamic column widths
    rows: list[tuple[str, str, str, str]] = []
    for platform in sorted(known_platforms):
        display_name = PLATFORM_DISPLAY_NAMES.get(platform, platform.title())
        agent = "Yes" if agent_integrations.get(platform, False) else "No"
        creds = "Configured" if fallback_status_data.get(platform, False) else "None"
        status = "Ready" if ready_status.get(platform, False) else "Needs Config"
        rows.append((display_name, agent, creds, status))

    # Calculate dynamic column widths (max of header vs content + padding)
    headers = ("Platform", "Agent", "Credentials", "Status")
    col_widths = [
        max(len(headers[i]), max((len(row[i]) for row in rows), default=0)) + 2 for i in range(4)
    ]

    # Total width for separator line
    total_width = sum(col_widths)

    print("  Platform Status:")
    print("  " + "-" * total_width)
    print(
        f"  {headers[0]:<{col_widths[0]}}"
        f"{headers[1]:<{col_widths[1]}}"
        f"{headers[2]:<{col_widths[2]}}"
        f"{headers[3]:<{col_widths[3]}}"
    )
    print("  " + "-" * total_width)

    for row in rows:
        print(
            f"  {row[0]:<{col_widths[0]}}"
            f"{row[1]:<{col_widths[1]}}"
            f"{row[2]:<{col_widths[2]}}"
            f"{row[3]:<{col_widths[3]}}"
        )

    print("  " + "-" * total_width)

    # Show hint for unconfigured platforms
    unconfigured = [p for p, ready in ready_status.items() if not ready]
    if unconfigured:
        print()
        print("  Tip: See docs/platform-configuration.md for credential setup")
    print()


def show_config(manager: ConfigManager) -> None:
    """Display current configuration using Rich formatting."""
    print_header("Current Configuration")

    # Show config file locations
    print_info(f"Global config: {manager.global_config_path}")
    if manager.local_config_path:
        print_info(f"Local config:  {manager.local_config_path}")
    else:
        print_info("Local config:  (not found)")
    console.print()

    s = manager.settings

    # Platform Settings section
    console.print("  [bold]Platform Settings:[/bold]")
    console.print(f"    Default Platform: {s.default_platform or '(not set)'}")
    # Jira-specific: Used when parsing numeric-only ticket IDs (e.g., 123 → PROJ-123)
    console.print(f"    Default Jira Project: {s.default_jira_project or '(not set)'}")
    console.print()

    # Platform Status table (NEW)
    show_platform_status(manager)

    # Model Settings section (reorganized)
    console.print("  [bold]Model Settings:[/bold]")
    console.print(f"    Default Model (Legacy): {s.default_model or '(not set)'}")
    console.print(f"    Planning Model: {s.planning_model or '(not set)'}")
    console.print(f"    Implementation Model: {s.implementation_model or '(not set)'}")
    console.print()

    # General Settings section (reorganized)
    console.print("  [bold]General Settings:[/bold]")
    console.print(f"    Auto-open Files: {s.auto_open_files}")
    console.print(f"    Preferred Editor: {s.preferred_editor or '(auto-detect)'}")
    console.print(f"    Skip Clarification: {s.skip_clarification}")
    console.print(f"    Squash Commits at End: {s.squash_at_end}")
    console.print()

    console.print("  [bold]Parallel Execution:[/bold]")
    console.print(f"    Enabled: {s.parallel_execution_enabled}")
    console.print(f"    Max Parallel Tasks: {s.max_parallel_tasks}")
    console.print(f"    Fail Fast: {s.fail_fast}")
    console.print()
    console.print("  [bold]Subagents:[/bold]")
    console.print(f"    Planner: {s.subagent_planner}")
    console.print(f"    Tasklist: {s.subagent_tasklist}")
    console.print(f"    Implementer: {s.subagent_implementer}")
    console.print(f"    Reviewer: {s.subagent_reviewer}")
    console.print()
