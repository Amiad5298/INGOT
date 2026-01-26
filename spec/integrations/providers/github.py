"""GitHub issue tracker provider.

This module provides the GitHubProvider class for integrating with GitHub Issues and PRs.
Following the hybrid architecture, this provider handles:
- Input parsing (URLs, owner/repo#123 format, #123 with default)
- Data normalization (raw REST API JSON → GenericTicket)
- Status/type mapping to normalized enums

Data fetching is delegated to TicketFetcher implementations.

Environment Variables:
    GITHUB_DEFAULT_OWNER: Default owner/organization for short ticket references.
        When a user provides just "#123", this is combined with GITHUB_DEFAULT_REPO.
    GITHUB_DEFAULT_REPO: Default repository for short ticket references.
    GITHUB_BASE_URL: Base URL for GitHub Enterprise (e.g., https://github.mycompany.com).
        Defaults to https://github.com for standard GitHub.
"""

from __future__ import annotations

import os
import re
import warnings
from datetime import datetime
from typing import Any

from spec.integrations.providers.base import (
    GenericTicket,
    IssueTrackerProvider,
    Platform,
    PlatformMetadata,
    TicketStatus,
    TicketType,
    sanitize_title_for_branch,
)
from spec.integrations.providers.registry import ProviderRegistry

# Status mapping: GitHub state → TicketStatus
# GitHub issues only have "open" or "closed" states; PRs can be "merged"
STATUS_MAPPING: dict[str, TicketStatus] = {
    "open": TicketStatus.OPEN,
    "closed": TicketStatus.CLOSED,  # Default for closed; may be refined by state_reason
}

# State reason mapping for closed issues (GitHub API v3)
# state_reason indicates why an issue was closed
# Note: "reopened" is NOT included here because:
# - A reopened issue has state="open", not state="closed"
# - This mapping is only consulted when state=="closed"
STATE_REASON_MAPPING: dict[str, TicketStatus] = {
    "completed": TicketStatus.DONE,  # Issue resolved successfully
    "not_planned": TicketStatus.CLOSED,  # Closed without resolution (won't fix)
}

# Label-based status enhancement
# GitHub uses labels to indicate workflow state beyond open/closed
LABEL_STATUS_MAP: dict[str, TicketStatus] = {
    "in progress": TicketStatus.IN_PROGRESS,
    "in-progress": TicketStatus.IN_PROGRESS,
    "wip": TicketStatus.IN_PROGRESS,
    "review": TicketStatus.REVIEW,
    "needs review": TicketStatus.REVIEW,
    "awaiting review": TicketStatus.REVIEW,
    "blocked": TicketStatus.BLOCKED,
    "on hold": TicketStatus.BLOCKED,
}

# Type inference keywords: keyword → TicketType
# GitHub uses labels for categorization, so we infer type from label names
# Note: Removed overly generic keywords like "new" and "issue" to reduce false positives
TYPE_KEYWORDS: dict[TicketType, list[str]] = {
    TicketType.BUG: ["bug", "defect", "fix", "error", "crash", "regression"],
    TicketType.FEATURE: ["feature", "enhancement", "feat", "story", "request"],
    TicketType.TASK: ["task", "chore", "todo", "housekeeping", "spike"],
    TicketType.MAINTENANCE: [
        "maintenance",
        "tech-debt",
        "tech debt",
        "refactor",
        "cleanup",
        "infrastructure",
        "deps",
        "dependencies",
        "devops",
    ],
}


# Structured prompt template for agent-mediated fetching
# Uses GitHub REST API v3 response structure
STRUCTURED_PROMPT_TEMPLATE = """Read GitHub issue {ticket_id} and return the following as JSON.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "number": <issue number>,
  "title": "<title>",
  "body": "<description markdown>",
  "state": "<open|closed>",
  "state_reason": "<completed|not_planned|reopened|null>",
  "labels": [{{"name": "<label1>"}}, {{"name": "<label2>"}}],
  "assignee": {{"login": "<username>"}} or null,
  "assignees": [{{"login": "<username1>"}}, {{"login": "<username2>"}}],
  "user": {{"login": "<author>"}},
  "created_at": "<ISO timestamp>",
  "updated_at": "<ISO timestamp>",
  "closed_at": "<ISO timestamp>" or null,
  "html_url": "<url>",
  "repository": {{"full_name": "<owner/repo>"}},
  "pull_request": null,
  "milestone": {{"title": "<milestone name>"}} or null,
  "merged_at": "<ISO timestamp>" or null
}}"""


@ProviderRegistry.register
class GitHubProvider(IssueTrackerProvider):
    """GitHub issue tracker provider.

    Handles GitHub-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Supports:
    - GitHub.com issues and pull requests
    - GitHub Enterprise Server (via GITHUB_BASE_URL env var)
    - Various URL formats (issue URLs, PR URLs, short references)

    Class Attributes:
        PLATFORM: Platform.GITHUB for registry registration
    """

    PLATFORM = Platform.GITHUB

    # URL pattern for GitHub.com only (strict validation)
    _GITHUB_COM_PATTERN = re.compile(
        r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(issues|pull)/(?P<number>\d+)",
        re.IGNORECASE,
    )

    # Generic URL pattern for extracting components (used with explicit Enterprise host validation)
    _GENERIC_URL_PATTERN = re.compile(
        r"https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(issues|pull)/(?P<number>\d+)",
        re.IGNORECASE,
    )

    # Short reference pattern: owner/repo#123
    _SHORT_REF_PATTERN = re.compile(r"^(?P<owner>[^/]+)/(?P<repo>[^/]+)#(?P<number>\d+)$")

    # Bare issue number pattern: #123 (requires default owner/repo)
    _BARE_NUMBER_PATTERN = re.compile(r"^#(?P<number>\d+)$")

    # Pattern to extract owner/repo from html_url (moved from normalize() for performance)
    _REPO_FROM_URL_PATTERN = re.compile(r"https?://[^/]+/([^/]+)/([^/]+)/")

    def __init__(
        self,
        default_owner: str | None = None,
        default_repo: str | None = None,
    ) -> None:
        """Initialize GitHubProvider.

        Args:
            default_owner: Default owner/org for bare issue references (#123).
                If not provided, uses GITHUB_DEFAULT_OWNER env var.
            default_repo: Default repository for bare issue references (#123).
                If not provided, uses GITHUB_DEFAULT_REPO env var.
        """
        # Track whether defaults were explicitly configured
        env_owner = os.environ.get("GITHUB_DEFAULT_OWNER")
        env_repo = os.environ.get("GITHUB_DEFAULT_REPO")
        self._has_explicit_defaults = (default_owner is not None and default_repo is not None) or (
            env_owner is not None and env_repo is not None
        )

        self._default_owner = default_owner or env_owner or ""
        self._default_repo = default_repo or env_repo or ""

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.GITHUB

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "GitHub Issues"

    def _get_allowed_hosts(self) -> set[str]:
        """Return the set of allowed hosts for URL validation.

        Handles edge cases in GITHUB_BASE_URL:
        - Whitespace: Leading/trailing whitespace is stripped
        - Ports: Port numbers are removed to allow flexible matching
          (e.g., "github.company.com:8443" matches URLs with or without port)

        Returns:
            Set containing 'github.com' and optionally the configured Enterprise host.
        """
        allowed = {"github.com"}
        github_base_url = os.environ.get("GITHUB_BASE_URL")
        if github_base_url:
            # Strip leading/trailing whitespace to handle configuration errors
            github_base_url = github_base_url.strip()

            # Handle URLs with or without scheme (e.g., "https://github.mycompany.com" or "github.mycompany.com")
            # Strip scheme if present
            host = github_base_url
            if host.startswith("https://"):
                host = host[8:]
            elif host.startswith("http://"):
                host = host[7:]

            # Strip trailing slashes and take the host part (before any path)
            host = host.rstrip("/").split("/")[0]

            # Strip port number if present (e.g., "github.company.com:8443" -> "github.company.com")
            # This ensures host matching works regardless of port in config or URL
            if ":" in host:
                host = host.split(":")[0]

            if host:
                allowed.add(host.lower())
        return allowed

    def _is_allowed_url(self, input_str: str) -> tuple[bool, re.Match | None]:
        """Check if a URL matches an allowed host.

        Args:
            input_str: URL to check

        Returns:
            Tuple of (is_allowed, match_object).
            - (True, match) when URL matches and host is allowed
            - (False, match) when URL matches generic pattern but host is not allowed
            - (False, None) when input doesn't look like a valid URL
        """
        # First try github.com pattern (always allowed)
        match = self._GITHUB_COM_PATTERN.match(input_str)
        if match:
            return True, match

        # Try generic pattern and check if host is allowed
        match = self._GENERIC_URL_PATTERN.match(input_str)
        if match:
            host = match.group("host").lower()
            # Strip port from URL host for comparison (e.g., "github.company.com:8443" -> "github.company.com")
            if ":" in host:
                host = host.split(":")[0]
            allowed_hosts = self._get_allowed_hosts()
            if host in allowed_hosts:
                return True, match
            # URL structure matches but host is not allowed - return the match
            # so caller can report which domain was rejected
            return False, match

        return False, None

    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Recognizes:
        - GitHub URLs: https://github.com/owner/repo/issues/123
        - GitHub PR URLs: https://github.com/owner/repo/pull/123
        - GitHub Enterprise URLs: ONLY when GITHUB_BASE_URL env var is set
        - Short references: owner/repo#123
        - Bare issue numbers: #123 (ONLY if default owner/repo are configured)

        GitHub Enterprise Behavior:
            Enterprise URLs are ONLY accepted when GITHUB_BASE_URL is explicitly set.
            The provider is secure by default and does not accept arbitrary domains.

        Args:
            input_str: URL or ticket reference to check

        Returns:
            True if this provider recognizes the input format
        """
        input_str = input_str.strip()

        # Check if URL matches an allowed host (github.com or configured Enterprise)
        is_allowed, _ = self._is_allowed_url(input_str)
        if is_allowed:
            return True

        # Check short reference pattern (owner/repo#123)
        if self._SHORT_REF_PATTERN.match(input_str):
            return True

        # Bare issue number (#123) - only accept if defaults configured
        if self._has_explicit_defaults and self._BARE_NUMBER_PATTERN.match(input_str):
            return True

        return False

    def parse_input(self, input_str: str) -> str:
        """Parse input and extract normalized ticket ID.

        Args:
            input_str: URL or ticket reference

        Returns:
            Normalized ticket ID in format: {owner}/{repo}#{number}
            Examples: "octocat/Hello-World#42", "myorg/backend#1234"

        Raises:
            ValueError: If input cannot be parsed or domain is not allowed
        """
        input_str = input_str.strip()

        # Try URL patterns first - with strict domain validation
        is_allowed, match = self._is_allowed_url(input_str)
        if match:
            if not is_allowed:
                # URL structure matches but domain is not allowed
                host = match.group("host") if "host" in match.groupdict() else "unknown"
                raise ValueError(
                    f"Domain '{host}' is not allowed. Only github.com or explicitly "
                    f"configured GITHUB_BASE_URL hosts are accepted."
                )
            owner = match.group("owner")
            repo = match.group("repo")
            number = match.group("number")
            return f"{owner}/{repo}#{number}"

        # Try short reference pattern (owner/repo#123)
        match = self._SHORT_REF_PATTERN.match(input_str)
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            number = match.group("number")
            return f"{owner}/{repo}#{number}"

        # Try bare issue number (#123)
        match = self._BARE_NUMBER_PATTERN.match(input_str)
        if match and self._default_owner and self._default_repo:
            number = match.group("number")
            return f"{self._default_owner}/{self._default_repo}#{number}"

        raise ValueError(f"Cannot parse GitHub issue from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw GitHub API data to GenericTicket.

        Handles nested API response structure and edge cases.
        Uses defensive field handling for malformed API responses.

        Args:
            raw_data: Raw GitHub REST API response (issue/PR object)
            ticket_id: Optional ticket ID from parse_input (unused, for LSP compliance).

        Returns:
            Populated GenericTicket with normalized fields
        """
        # Extract repository info for ticket ID
        # The repository field may come from different structures depending on source
        # Use `or {}` to protect against API explicitly returning null for repository
        repo_obj = raw_data.get("repository") or {}
        repo_full_name = self.safe_nested_get(repo_obj, "full_name", "")

        # Get html_url for fallback repo detection and PR detection
        html_url = raw_data.get("html_url", "")

        # Fallback: construct from html_url if repository not provided
        if not repo_full_name:
            # Use pre-compiled class constant pattern for performance
            # Use search() instead of match() for resilience to leading whitespace/noise
            url_match = self._REPO_FROM_URL_PATTERN.search(html_url)
            if url_match:
                repo_full_name = f"{url_match.group(1)}/{url_match.group(2)}"

        number = raw_data.get("number", 0)
        ticket_id = f"{repo_full_name}#{number}" if repo_full_name else str(number)

        # Extract state and determine status
        state = raw_data.get("state", "").lower()
        state_reason = raw_data.get("state_reason", "")

        # Check if this is a PR
        # Primary: check pull_request field; Fallback: use strict regex on html_url
        # This handles cases where data source (like an LLM) might omit the pull_request field
        # Using stricter regex to avoid false positives (e.g., "/pull/request" would not match)
        is_pr = raw_data.get("pull_request") is not None
        if not is_pr and re.search(r"/pull/\d+", html_url):
            is_pr = True
        merged_at = raw_data.get("merged_at")

        status = self._map_status(state, state_reason, is_pr, merged_at)

        # Extract labels and enhance status from labels
        labels_raw = raw_data.get("labels") or []
        labels = [
            self.safe_nested_get(label, "name", "").strip()
            for label in labels_raw
            if isinstance(label, dict)
        ]
        labels = [lbl for lbl in labels if lbl]  # Filter empty strings

        # Optionally enhance status from labels (only for open issues)
        if state == "open":
            status = self._enhance_status_from_labels(status, labels)

        # Extract timestamps
        created_at = self._parse_timestamp(raw_data.get("created_at"))
        updated_at = self._parse_timestamp(raw_data.get("updated_at"))

        # Extract assignee (first one if multiple)
        assignee = None
        assignee_obj = raw_data.get("assignee")
        if isinstance(assignee_obj, dict):
            assignee = assignee_obj.get("login")
        elif not assignee and raw_data.get("assignees"):
            assignees = raw_data["assignees"]
            if assignees and isinstance(assignees[0], dict):
                assignee = assignees[0].get("login")

        # Get URL directly from response
        url = raw_data.get("html_url", "")

        # Extract author
        user_obj = raw_data.get("user")
        author = self.safe_nested_get(user_obj, "login", "")

        # Extract milestone
        milestone_obj = raw_data.get("milestone")
        milestone = self.safe_nested_get(milestone_obj, "title", "") or None

        # Build platform-specific metadata
        platform_metadata: PlatformMetadata = {
            "raw_response": raw_data,
            "repository": repo_full_name,
            "issue_number": number,
            "is_pull_request": is_pr,
            "state_reason": state_reason or "",
            "milestone": milestone or "",
            "author": author,
        }

        return GenericTicket(
            id=ticket_id,
            platform=Platform.GITHUB,
            url=url,
            title=raw_data.get("title", ""),
            description=raw_data.get("body", "") or "",
            status=status,
            type=self._map_type(labels),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(raw_data.get("title", "")),
            platform_metadata=platform_metadata,
        )

    def _map_status(
        self,
        state: str,
        state_reason: str | None,
        is_pr: bool,
        merged_at: str | None,
    ) -> TicketStatus:
        """Map GitHub state to TicketStatus enum.

        Args:
            state: GitHub state ("open" or "closed")
            state_reason: Reason for closure (completed, not_planned, reopened)
            is_pr: Whether this is a pull request
            merged_at: Merge timestamp (for PRs only)

        Returns:
            Normalized TicketStatus
        """
        # Merged PRs are DONE
        if is_pr and merged_at:
            return TicketStatus.DONE

        # Check state_reason for closed issues
        if state == "closed" and state_reason:
            reason_status = STATE_REASON_MAPPING.get(state_reason.lower())
            if reason_status:
                return reason_status

        # Fall back to basic state mapping
        return STATUS_MAPPING.get(state, TicketStatus.UNKNOWN)

    def _enhance_status_from_labels(
        self, current_status: TicketStatus, labels: list[str]
    ) -> TicketStatus:
        """Optionally enhance status based on labels.

        GitHub labels can indicate workflow state beyond open/closed.
        Only enhances status for open issues (doesn't override closed).

        Args:
            current_status: Current status from state field
            labels: List of label names

        Returns:
            Enhanced status if matching label found, otherwise current_status
        """
        for label in labels:
            label_lower = label.lower().strip()
            if label_lower in LABEL_STATUS_MAP:
                return LABEL_STATUS_MAP[label_lower]
        return current_status

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map GitHub labels to TicketType enum.

        GitHub uses labels for categorization. Infer type from keywords.

        Args:
            labels: List of label names from the issue

        Returns:
            Matched TicketType or UNKNOWN if no type-specific labels found
        """
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type

        return TicketType.UNKNOWN

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from GitHub API.

        Args:
            timestamp_str: ISO format timestamp (e.g., "2024-01-15T10:30:00Z")

        Returns:
            datetime object or None if parsing fails
        """
        if not timestamp_str:
            return None
        try:
            # GitHub uses ISO format with Z suffix: 2024-01-15T10:30:00Z
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def get_prompt_template(self) -> str:
        """Return structured prompt template for agent-mediated fetch.

        Returns:
            Prompt template string with {ticket_id} placeholder
        """
        return STRUCTURED_PROMPT_TEMPLATE

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket details from GitHub.

        NOTE: This method is required by IssueTrackerProvider ABC but
        in the hybrid architecture, fetching is delegated to TicketService
        which uses TicketFetcher implementations. This method is kept for
        backward compatibility and direct provider usage.

        Args:
            ticket_id: Normalized ticket ID from parse_input()

        Returns:
            Populated GenericTicket

        Raises:
            NotImplementedError: Fetching should use TicketService
        """
        warnings.warn(
            "GitHubProvider.fetch_ticket() is deprecated. "
            "Use TicketService.get_ticket() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            "GitHubProvider.fetch_ticket() is deprecated in hybrid architecture. "
            "Use TicketService.get_ticket() with AuggieMediatedFetcher or "
            "DirectAPIFetcher instead."
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify GitHub integration is properly configured.

        NOTE: Connection checking is delegated to TicketFetcher implementations
        in the hybrid architecture.

        Returns:
            Tuple of (success: bool, message: str)
        """
        # In hybrid architecture, connection check is done by TicketService
        # This method returns True as the provider itself doesn't manage connections
        return (
            True,
            "GitHubProvider ready - use TicketService for connection verification",
        )
