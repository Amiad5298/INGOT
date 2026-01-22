"""Platform detection for URL and ticket ID pattern matching.

This module provides:
- PlatformPattern dataclass for defining URL and ID patterns per platform
- PLATFORM_PATTERNS list with regex patterns for all supported platforms
- PlatformDetector class for detecting platform from user input

The detector supports:
- Jira: *.atlassian.net URLs, custom Jira URLs, PROJECT-123 format
- GitHub: github.com URLs for issues/PRs, owner/repo#123 format
- Linear: linear.app URLs, TEAM-123 format
- Azure DevOps: dev.azure.com and visualstudio.com URLs, AB#123 format
- Monday: monday.com board/pulse URLs
- Trello: trello.com card URLs, 8-char short IDs
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Pattern

from spec.integrations.providers.base import Platform
from spec.integrations.providers.exceptions import PlatformNotSupportedError


@dataclass
class PlatformPattern:
    """Defines URL and ID patterns for a platform.

    Attributes:
        platform: The platform these patterns match
        url_patterns: List of compiled regex patterns for URLs
        id_patterns: List of compiled regex patterns for ticket IDs
    """

    platform: Platform
    url_patterns: list[Pattern[str]] = field(default_factory=list)
    id_patterns: list[Pattern[str]] = field(default_factory=list)


# Platform detection patterns for all supported platforms
# Order matters: more specific patterns should come first
# Note: Jira and Linear share the same ID pattern (PROJECT-123)
# which may cause ambiguity - detect() returns the first match (Jira)
PLATFORM_PATTERNS: list[PlatformPattern] = [
    PlatformPattern(
        platform=Platform.JIRA,
        url_patterns=[
            # Atlassian Cloud: https://company.atlassian.net/browse/PROJECT-123
            re.compile(
                r"https?://[^/]+\.atlassian\.net/browse/(?P<ticket_id>[A-Z]+-\d+)",
                re.IGNORECASE,
            ),
            # Self-hosted Jira: https://jira.company.com/browse/PROJECT-123
            re.compile(
                r"https?://jira\.[^/]+/browse/(?P<ticket_id>[A-Z]+-\d+)",
                re.IGNORECASE,
            ),
            # Generic Jira: https://company.com/browse/PROJECT-123
            re.compile(
                r"https?://[^/]+/browse/(?P<ticket_id>[A-Z]+-\d+)",
                re.IGNORECASE,
            ),
        ],
        id_patterns=[
            # PROJECT-123 format (e.g., PROJ-123, ABC-1, XYZ-99999)
            re.compile(r"^(?P<ticket_id>[A-Z][A-Z0-9]*-\d+)$", re.IGNORECASE),
        ],
    ),
    PlatformPattern(
        platform=Platform.GITHUB,
        url_patterns=[
            # GitHub issue: https://github.com/owner/repo/issues/123
            re.compile(
                r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)"
            ),
            # GitHub PR: https://github.com/owner/repo/pull/123
            re.compile(
                r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
            ),
        ],
        id_patterns=[
            # Short reference: owner/repo#123
            re.compile(r"^(?P<repo_ref>[^/]+/[^/]+)#(?P<number>\d+)$"),
        ],
    ),
    PlatformPattern(
        platform=Platform.LINEAR,
        url_patterns=[
            # Linear issue: https://linear.app/team/issue/TEAM-123
            re.compile(
                r"https?://linear\.app/(?P<team>[^/]+)/issue/(?P<ticket_id>[A-Z]+-\d+)",
                re.IGNORECASE,
            ),
        ],
        id_patterns=[
            # INTENTIONALLY EMPTY - Linear vs Jira Ambiguity:
            # ---------------------------------------------------
            # The original spec requested support for Linear ticket IDs in the
            # format TEAM-123 (e.g., "ENG-456", "DESIGN-789"). However, this format
            # is identical to Jira's PROJECT-123 pattern, making it impossible to
            # distinguish between the two platforms based solely on the ID.
            #
            # Design Decision:
            # - Linear ID detection is intentionally omitted to prevent false positives.
            # - Jira (being more widely adopted) takes precedence for ambiguous IDs.
            # - Users must provide the full Linear URL for unambiguous Linear detection.
            #
            # Example:
            #   "ABC-123" -> Detected as Jira (ambiguous, could be Linear)
            #   "https://linear.app/team/issue/ABC-123" -> Detected as Linear (unambiguous)
            #
            # See: Original ticket discussion on Linear vs Jira pattern collision.
        ],
    ),
    PlatformPattern(
        platform=Platform.AZURE_DEVOPS,
        url_patterns=[
            # Azure DevOps: https://dev.azure.com/org/project/_workitems/edit/123
            re.compile(
                r"https?://dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_workitems/edit/(?P<work_item_id>\d+)"
            ),
            # Visual Studio: https://org.visualstudio.com/project/_workitems/edit/123
            re.compile(
                r"https?://(?P<org>[^/]+)\.visualstudio\.com/(?P<project>[^/]+)/_workitems/edit/(?P<work_item_id>\d+)"
            ),
        ],
        id_patterns=[
            # Azure Boards: AB#12345
            re.compile(r"^AB#(?P<work_item_id>\d+)$", re.IGNORECASE),
        ],
    ),
    PlatformPattern(
        platform=Platform.MONDAY,
        url_patterns=[
            # Monday.com: https://view.monday.com/boards/123/pulses/456
            re.compile(
                r"https?://[^/]*\.?monday\.com/boards/(?P<board_id>\d+)/pulses/(?P<pulse_id>\d+)"
            ),
            # Monday.com alternate: https://company.monday.com/boards/123/pulses/456
            re.compile(
                r"https?://[^/]+\.monday\.com/boards/(?P<board_id>\d+)(?:/[^/]+)?/pulses/(?P<pulse_id>\d+)"
            ),
        ],
        id_patterns=[
            # Monday requires URL or board context - no standalone ID pattern
        ],
    ),
    PlatformPattern(
        platform=Platform.TRELLO,
        url_patterns=[
            # Trello card: https://trello.com/c/cardId or https://trello.com/c/cardId/name
            re.compile(r"https?://trello\.com/c/(?P<card_id>[a-zA-Z0-9]+)(?:/[^/]*)?"),
        ],
        id_patterns=[
            # Trello short ID: 8 alphanumeric characters
            re.compile(r"^(?P<card_id>[a-zA-Z0-9]{8})$"),
        ],
    ),
]


class PlatformDetector:
    """Detects the platform from user input (URL or ticket ID).

    This class provides static methods to identify which issue tracking
    platform a given input belongs to, based on URL patterns or ticket
    ID formats.

    Example usage:
        platform, groups = PlatformDetector.detect("https://github.com/owner/repo/issues/42")
        # Returns: (Platform.GITHUB, {'owner': 'owner', 'repo': 'repo', 'number': '42'})

        platform, groups = PlatformDetector.detect("PROJ-123")
        # Returns: (Platform.JIRA, {'ticket_id': 'PROJ-123'})
    """

    @staticmethod
    def _extract_groups(match: re.Match[str]) -> dict[str, str]:
        """Extract named groups from a regex match as a dictionary.

        Named groups are prioritized via .groupdict(). Any groups that did not
        participate in the match (i.e., have None values) are filtered out.

        Args:
            match: The regex match object

        Returns:
            Dictionary with named groups as {group_name: matched_value}.
            Only groups with non-None values are included.
        """
        named_groups = match.groupdict()
        # Filter out None values (from optional groups that didn't match)
        return {key: value for key, value in named_groups.items() if value is not None}

    @staticmethod
    def detect(input_str: str) -> tuple[Platform, dict[str, str]]:
        """Detect platform from input URL or ID.

        Args:
            input_str: URL or ticket ID to analyze

        Returns:
            Tuple of (Platform, extracted_groups_dict) where groups_dict
            contains captured regex named groups as {group_name: matched_value}

        Raises:
            PlatformNotSupportedError: If platform cannot be determined
        """
        input_str = input_str.strip()

        for pattern_def in PLATFORM_PATTERNS:
            # Check URL patterns first (more specific)
            for pattern in pattern_def.url_patterns:
                match = pattern.match(input_str)
                if match:
                    return pattern_def.platform, PlatformDetector._extract_groups(match)

            # Check ID patterns
            for pattern in pattern_def.id_patterns:
                match = pattern.match(input_str)
                if match:
                    return pattern_def.platform, PlatformDetector._extract_groups(match)

        # No pattern matched - raise error with helpful message
        supported = [p.name for p in Platform]
        raise PlatformNotSupportedError(
            input_str=input_str,
            supported_platforms=supported,
        )

    @staticmethod
    def is_url(input_str: str) -> bool:
        """Check if input is a URL.

        Args:
            input_str: String to check

        Returns:
            True if input starts with http:// or https://
        """
        return input_str.strip().startswith(("http://", "https://"))
