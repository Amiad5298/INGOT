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
            re.compile(r"https?://[^/]+\.atlassian\.net/browse/([A-Z]+-\d+)", re.IGNORECASE),
            # Self-hosted Jira: https://jira.company.com/browse/PROJECT-123
            re.compile(r"https?://jira\.[^/]+/browse/([A-Z]+-\d+)", re.IGNORECASE),
            # Generic Jira: https://company.com/browse/PROJECT-123
            re.compile(r"https?://[^/]+/browse/([A-Z]+-\d+)", re.IGNORECASE),
        ],
        id_patterns=[
            # PROJECT-123 format (e.g., PROJ-123, ABC-1, XYZ-99999)
            re.compile(r"^([A-Z][A-Z0-9]*-\d+)$", re.IGNORECASE),
        ],
    ),
    PlatformPattern(
        platform=Platform.GITHUB,
        url_patterns=[
            # GitHub issue: https://github.com/owner/repo/issues/123
            re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)"),
            # GitHub PR: https://github.com/owner/repo/pull/123
            re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)"),
        ],
        id_patterns=[
            # Short reference: owner/repo#123
            re.compile(r"^([^/]+/[^/]+)#(\d+)$"),
        ],
    ),
    PlatformPattern(
        platform=Platform.LINEAR,
        url_patterns=[
            # Linear issue: https://linear.app/team/issue/TEAM-123
            re.compile(r"https?://linear\.app/([^/]+)/issue/([A-Z]+-\d+)", re.IGNORECASE),
        ],
        id_patterns=[
            # Note: TEAM-123 format is same as Jira - ambiguous by ID alone
            # URL detection is preferred for Linear; ID detection falls back to Jira
            # Kept empty to avoid false positives - use URL for Linear
        ],
    ),
    PlatformPattern(
        platform=Platform.AZURE_DEVOPS,
        url_patterns=[
            # Azure DevOps: https://dev.azure.com/org/project/_workitems/edit/123
            re.compile(r"https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)"),
            # Visual Studio: https://org.visualstudio.com/project/_workitems/edit/123
            re.compile(r"https?://([^/]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)"),
        ],
        id_patterns=[
            # Azure Boards: AB#12345
            re.compile(r"^AB#(\d+)$", re.IGNORECASE),
        ],
    ),
    PlatformPattern(
        platform=Platform.MONDAY,
        url_patterns=[
            # Monday.com: https://view.monday.com/boards/123/pulses/456
            re.compile(r"https?://[^/]*\.?monday\.com/boards/(\d+)/pulses/(\d+)"),
            # Monday.com alternate: https://company.monday.com/boards/123/pulses/456
            re.compile(r"https?://[^/]+\.monday\.com/boards/(\d+)(?:/[^/]+)?/pulses/(\d+)"),
        ],
        id_patterns=[
            # Monday requires URL or board context - no standalone ID pattern
        ],
    ),
    PlatformPattern(
        platform=Platform.TRELLO,
        url_patterns=[
            # Trello card: https://trello.com/c/cardId or https://trello.com/c/cardId/name
            re.compile(r"https?://trello\.com/c/([a-zA-Z0-9]+)(?:/[^/]*)?"),
        ],
        id_patterns=[
            # Trello short ID: 8 alphanumeric characters
            re.compile(r"^([a-zA-Z0-9]{8})$"),
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
        # Returns: (Platform.GITHUB, {0: 'owner', 1: 'repo', 2: '42'})

        platform, groups = PlatformDetector.detect("PROJ-123")
        # Returns: (Platform.JIRA, {0: 'PROJ-123'})
    """

    @staticmethod
    def _extract_groups(match: re.Match[str]) -> dict[int | str, str]:
        """Extract groups from a regex match as a dictionary.

        Args:
            match: The regex match object

        Returns:
            Dictionary with named groups (str keys) or indexed groups (int keys)
        """
        named_groups = match.groupdict()
        if named_groups:
            return named_groups  # type: ignore[return-value]
        # Use indexed groups when no named groups exist
        return dict(enumerate(match.groups()))

    @staticmethod
    def detect(input_str: str) -> tuple[Platform, dict[int | str, str]]:
        """Detect platform from input URL or ID.

        Args:
            input_str: URL or ticket ID to analyze

        Returns:
            Tuple of (Platform, extracted_groups_dict) where groups_dict
            contains captured regex groups as {index: value} or {name: value}

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
