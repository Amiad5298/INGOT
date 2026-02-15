"""Platform detection and disambiguation for the CLI.

Handles validation and resolution of platform-related inputs.
"""

import re

import typer

from ingot.config.manager import ConfigManager
from ingot.integrations.providers import Platform
from ingot.utils.console import print_info

# Platforms that use the PROJECT-123 format and are ambiguous
# (i.e., can't be distinguished from each other without additional context)
AMBIGUOUS_PLATFORMS: tuple[Platform, ...] = (Platform.JIRA, Platform.LINEAR)


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
