"""Jira integration for SPEC.

This module provides Jira ticket parsing, validation, and integration
checking through the Auggie CLI.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from spec.utils.console import (
    print_info,
    print_step,
    print_success,
    print_warning,
)
from spec.utils.logging import log_message

if TYPE_CHECKING:
    from spec.config.manager import ConfigManager
    from spec.integrations.auggie import AuggieClient

# Cache duration for Jira integration check
JIRA_CACHE_DURATION = timedelta(hours=24)


@dataclass
class JiraTicket:
    """Parsed Jira ticket information.

    Attributes:
        ticket_id: Normalized ticket ID (e.g., "PROJECT-123")
        ticket_url: Original URL or ticket ID
        summary: Short summary for branch name
        title: Full ticket title
        description: Brief description
        full_info: Complete ticket information
    """

    ticket_id: str
    ticket_url: str
    summary: str = ""
    title: str = ""
    description: str = ""
    full_info: str = ""


def parse_jira_ticket(input_str: str, default_project: str = "") -> JiraTicket:
    """Parse Jira ticket from various input formats.

    Supports:
    - Full URLs: https://jira.example.com/browse/PROJECT-123
    - Ticket IDs: PROJECT-123, project-123, Project2-456
    - Numeric only: 123 (requires default_project)

    Args:
        input_str: URL, ticket ID, or numeric ID
        default_project: Default project key for numeric-only input

    Returns:
        JiraTicket with parsed ticket_id and ticket_url

    Raises:
        ValueError: If input format is invalid
    """
    input_str = input_str.strip()

    # URL pattern: https://jira.example.com/browse/PROJECT-123
    url_pattern = r"^https?://"
    ticket_pattern = r"([a-zA-Z][a-zA-Z0-9]*-[0-9]+)"
    numeric_pattern = r"^[0-9]+$"

    if re.match(url_pattern, input_str):
        # Extract ticket ID from URL
        match = re.search(ticket_pattern, input_str)
        if not match:
            raise ValueError("Could not extract ticket ID from URL")
        ticket_id = match.group(1).upper()
        log_message(f"Parsed ticket from URL: {ticket_id}")
        return JiraTicket(ticket_id=ticket_id, ticket_url=input_str)

    elif re.match(numeric_pattern, input_str):
        # Numeric only - requires default project
        if not default_project:
            raise ValueError(
                "Numeric ticket ID requires DEFAULT_JIRA_PROJECT to be configured. "
                "Use full ticket ID (e.g., PROJECT-123) or configure default project."
            )
        ticket_id = f"{default_project.upper()}-{input_str}"
        log_message(f"Parsed numeric ticket with default project: {ticket_id}")
        return JiraTicket(ticket_id=ticket_id, ticket_url=ticket_id)

    elif re.match(r"^[a-zA-Z][a-zA-Z0-9]*-[0-9]+$", input_str):
        # Standard ticket ID format
        ticket_id = input_str.upper()
        log_message(f"Parsed standard ticket ID: {ticket_id}")
        return JiraTicket(ticket_id=ticket_id, ticket_url=ticket_id)

    else:
        raise ValueError(
            "Invalid ticket format. Expected: PROJECT-123, 123, or full Jira URL"
        )


def check_jira_integration(
    config: "ConfigManager",
    auggie: "AuggieClient",
    force: bool = False,
) -> bool:
    """Check if Jira integration is configured in Auggie.

    Uses 24-hour cache unless force=True.

    Args:
        config: Configuration manager
        auggie: Auggie CLI client
        force: Force fresh check, ignore cache

    Returns:
        True if Jira is configured and working
    """
    print_step("Checking Jira integration...")
    log_message("Jira integration check started")

    current_time = int(datetime.now().timestamp())

    # Check cache (unless forced)
    if not force:
        cached_timestamp = config.get("JIRA_CHECK_TIMESTAMP", "0")
        cached_status = config.get("JIRA_INTEGRATION_STATUS", "")

        if cached_timestamp:
            try:
                cache_age = current_time - int(cached_timestamp)
                if cache_age < JIRA_CACHE_DURATION.total_seconds():
                    if cached_status == "working":
                        hours_ago = cache_age // 3600
                        print_success(
                            f"Jira integration is configured "
                            f"(cached - checked {hours_ago} hours ago)"
                        )
                        log_message("Jira integration: using cached result (working)")
                        return True
            except ValueError:
                pass  # Invalid timestamp, proceed with fresh check
    else:
        print_info("Forcing fresh Jira integration check...")
        log_message("Jira integration: forcing fresh check")

    # Perform actual check
    print_info("Verifying Jira integration (this may take a moment)...")

    prompt = (
        "Check if Jira integration is available. "
        "Respond with 'YES' if you can access Jira, 'NO' otherwise."
    )

    try:
        output = auggie.run_print_quiet(prompt)

        # Check for error indicators
        error_patterns = [
            r"jira.*not.*configured",
            r"jira.*not.*available",
            r"cannot.*access.*jira",
            r"jira.*integration.*failed",
        ]

        for pattern in error_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                config.save("JIRA_INTEGRATION_STATUS", "not_configured")
                config.save("JIRA_CHECK_TIMESTAMP", str(current_time))
                print_warning("Jira integration is not configured")
                log_message("Jira integration: not configured")
                return False

        # Check for positive response
        if re.search(r"yes|available|configured|working", output, re.IGNORECASE):
            config.save("JIRA_INTEGRATION_STATUS", "working")
            config.save("JIRA_CHECK_TIMESTAMP", str(current_time))
            print_success("Jira integration is configured and working")
            log_message("Jira integration: working")
            return True

    except Exception as e:
        log_message(f"Jira integration check failed: {e}")

    config.save("JIRA_INTEGRATION_STATUS", "unknown")
    config.save("JIRA_CHECK_TIMESTAMP", str(current_time))
    print_warning("Unable to verify Jira integration")
    log_message("Jira integration: unknown/failed")
    return False


def fetch_ticket_info(ticket: JiraTicket, auggie: "AuggieClient") -> JiraTicket:
    """Fetch ticket information from Jira via Auggie.

    Args:
        ticket: JiraTicket with ticket_id set
        auggie: Auggie CLI client

    Returns:
        JiraTicket with summary, title, description populated
    """
    prompt = f"""Read Jira ticket {ticket.ticket_url} and provide:
1. A short 3-5 word summary suitable for a git branch name (lowercase with hyphens)
2. The full ticket title
3. A brief description (2-3 sentences)

Format your response as:
BRANCH_SUMMARY: <summary>
TITLE: <title>
DESCRIPTION: <description>"""

    output = auggie.run_print_quiet(prompt)

    # Parse response
    summary_match = re.search(r"^BRANCH_SUMMARY:\s*(.+)$", output, re.MULTILINE)
    if summary_match:
        summary = summary_match.group(1).strip().lower()
        # Sanitize for branch name
        summary = re.sub(r"[^a-z0-9-]", "-", summary)
        summary = re.sub(r"-+", "-", summary).strip("-")
        ticket.summary = summary[:50]  # Max 50 chars

    title_match = re.search(r"^TITLE:\s*(.+)$", output, re.MULTILINE)
    if title_match:
        ticket.title = title_match.group(1).strip()

    desc_match = re.search(r"^DESCRIPTION:\s*(.+)$", output, re.MULTILINE | re.DOTALL)
    if desc_match:
        ticket.description = desc_match.group(1).strip()

    ticket.full_info = output
    return ticket


__all__ = [
    "JiraTicket",
    "JIRA_CACHE_DURATION",
    "parse_jira_ticket",
    "check_jira_integration",
    "fetch_ticket_info",
]

