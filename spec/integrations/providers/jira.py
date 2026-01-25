"""Jira issue tracker provider.

This module provides the JiraProvider class for integrating with Jira.
Following the hybrid architecture, this provider handles:
- Input parsing (URLs, PROJECT-123 format)
- Data normalization (raw JSON → GenericTicket)
- Status/type mapping to normalized enums

Data fetching is delegated to TicketFetcher implementations.

Environment Variables:
    JIRA_DEFAULT_PROJECT: Default project key for numeric-only ticket IDs.
        When a user provides just a number (e.g., "123"), it will be prefixed
        with this project key to form "PROJECT-123". If not set, defaults to
        the DEFAULT_PROJECT constant ("PROJ"). This can also be overridden
        per-instance via the JiraProvider constructor's `default_project` parameter.
"""

from __future__ import annotations

import os
import re
import warnings
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

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
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    UserInteractionInterface,
)

# Status mapping: Jira status name → TicketStatus
STATUS_MAPPING: dict[str, TicketStatus] = {
    # Open states
    "to do": TicketStatus.OPEN,
    "open": TicketStatus.OPEN,
    "backlog": TicketStatus.OPEN,
    "new": TicketStatus.OPEN,
    "reopened": TicketStatus.OPEN,
    # In Progress states
    "in progress": TicketStatus.IN_PROGRESS,
    "in development": TicketStatus.IN_PROGRESS,
    "in review": TicketStatus.REVIEW,
    "code review": TicketStatus.REVIEW,
    "review": TicketStatus.REVIEW,
    "testing": TicketStatus.REVIEW,
    "qa": TicketStatus.REVIEW,
    # Done states
    "done": TicketStatus.DONE,
    "resolved": TicketStatus.DONE,
    "completed": TicketStatus.DONE,
    # Closed states
    "closed": TicketStatus.CLOSED,
    # Blocked states
    "blocked": TicketStatus.BLOCKED,
    "on hold": TicketStatus.BLOCKED,
    "waiting": TicketStatus.BLOCKED,
}

# Type mapping: Jira issue type → TicketType
TYPE_MAPPING: dict[str, TicketType] = {
    # Feature types
    "story": TicketType.FEATURE,
    "feature": TicketType.FEATURE,
    "epic": TicketType.FEATURE,
    "user story": TicketType.FEATURE,
    "enhancement": TicketType.FEATURE,
    "new feature": TicketType.FEATURE,
    # Bug types
    "bug": TicketType.BUG,
    "defect": TicketType.BUG,
    "incident": TicketType.BUG,
    "problem": TicketType.BUG,
    # Task types
    "task": TicketType.TASK,
    "sub-task": TicketType.TASK,
    "subtask": TicketType.TASK,
    "spike": TicketType.TASK,
    # Maintenance types
    "technical debt": TicketType.MAINTENANCE,
    "improvement": TicketType.MAINTENANCE,
    "refactor": TicketType.MAINTENANCE,
    "maintenance": TicketType.MAINTENANCE,
    "chore": TicketType.MAINTENANCE,
}

# Default project key for numeric-only ticket IDs
# Can be overridden via environment variable JIRA_DEFAULT_PROJECT
DEFAULT_PROJECT: str = "PROJ"

# Structured prompt template for agent-mediated fetching
STRUCTURED_PROMPT_TEMPLATE = """Use your Jira tool to fetch issue {ticket_id}.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "key": "<ticket key>",
  "fields": {{
    "summary": "<title>",
    "description": "<description text>",
    "status": {{"name": "<status name>"}},
    "issuetype": {{"name": "<issue type>"}},
    "priority": {{"name": "<priority>"}},
    "assignee": {{"displayName": "<name>", "emailAddress": "<email>"}} or null,
    "labels": ["<label1>", "<label2>"],
    "created": "<ISO timestamp>",
    "updated": "<ISO timestamp>",
    "project": {{"key": "<PROJECT>", "name": "<Project Name>"}},
    "components": [{{"name": "<component>"}}],
    "fixVersions": [{{"name": "<version>"}}],
    "customfield_10014": "<epic link>" or null,
    "customfield_10016": <story points number> or null
  }}
}}"""


@ProviderRegistry.register
class JiraProvider(IssueTrackerProvider):
    """Jira issue tracker provider.

    Handles Jira-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Class Attributes:
        PLATFORM: Platform.JIRA for registry registration
    """

    PLATFORM = Platform.JIRA

    # Ticket ID pattern: Supports alphanumeric project keys (e.g., A1-123, PROJ-123)
    # Pattern: [A-Z][A-Z0-9]*-\d+ (project must start with letter, can contain digits)
    _TICKET_ID_REGEX = r"[A-Z][A-Z0-9]*-\d+"

    # URL patterns for Jira - consolidated to use generic /browse/ pattern
    # This handles Atlassian Cloud, self-hosted, and any other Jira instances
    _URL_PATTERNS = [
        # Generic /browse/ URL - handles all Jira instances
        re.compile(
            rf"https?://[^/]+/browse/(?P<ticket_id>{_TICKET_ID_REGEX})",
            re.IGNORECASE,
        ),
    ]

    # ID pattern: PROJECT-123 format
    _ID_PATTERN = re.compile(r"^(?P<ticket_id>[A-Z][A-Z0-9]*-\d+)$", re.IGNORECASE)

    # Numeric-only pattern: 123 → DEFAULT_PROJECT-123
    _NUMERIC_ID_PATTERN = re.compile(r"^(?P<number>\d+)$")

    def __init__(
        self,
        user_interaction: UserInteractionInterface | None = None,
        default_project: str | None = None,
    ) -> None:
        """Initialize JiraProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
                If not provided, uses CLIUserInteraction.
            default_project: Default project key for numeric-only ticket IDs.
                If not provided, uses JIRA_DEFAULT_PROJECT env var or DEFAULT_PROJECT constant.
        """
        # Note: _user_interaction is stored for potential future use and to maintain
        # constructor contract parity with other providers. The hybrid architecture
        # currently doesn't require user interaction in the provider layer - all
        # interactive operations are handled by TicketService and TicketFetcher.
        self._user_interaction = user_interaction or CLIUserInteraction()

        # Track if default project was explicitly configured (for can_handle behavior)
        env_project = os.environ.get("JIRA_DEFAULT_PROJECT")
        self._has_explicit_default_project = default_project is not None or env_project is not None
        self._default_project = default_project or env_project or DEFAULT_PROJECT

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.JIRA

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "Jira"

    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Recognizes:
        - Jira URLs: any /browse/PROJECT-123 format (Cloud or self-hosted)
        - Ticket IDs: PROJ-123, A1-123, XYZ-99999 (case-insensitive, alphanumeric project)
        - Numeric IDs: 123 (only if default_project is explicitly configured)

        Args:
            input_str: URL or ticket ID to check

        Returns:
            True if this provider recognizes the input format
        """
        input_str = input_str.strip()

        # Check URL patterns
        for pattern in self._URL_PATTERNS:
            if pattern.match(input_str):
                return True

        # Check ID pattern (PROJECT-123 with alphanumeric project key)
        if self._ID_PATTERN.match(input_str):
            return True

        # Numeric-only pattern (123) - only accept if default project is explicitly configured
        # This prevents ambiguous input from being claimed when no project context exists
        if self._has_explicit_default_project and self._NUMERIC_ID_PATTERN.match(input_str):
            return True

        return False

    def parse_input(self, input_str: str) -> str:
        """Parse input and extract normalized ticket ID.

        Args:
            input_str: URL or ticket ID

        Returns:
            Normalized ticket ID in uppercase (e.g., "PROJECT-123")
            For numeric-only input, prepends default project: 123 → "PROJ-123"

        Raises:
            ValueError: If input cannot be parsed
        """
        input_str = input_str.strip()

        # Try URL patterns first
        for pattern in self._URL_PATTERNS:
            match = pattern.match(input_str)
            if match:
                return match.group("ticket_id").upper()

        # Try ID pattern (PROJECT-123)
        match = self._ID_PATTERN.match(input_str)
        if match:
            return match.group("ticket_id").upper()

        # Try numeric-only pattern (123 → DEFAULT_PROJECT-123)
        match = self._NUMERIC_ID_PATTERN.match(input_str)
        if match:
            number = match.group("number")
            return f"{self._default_project.upper()}-{number}"

        raise ValueError(f"Cannot parse Jira ticket from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        """Convert raw Jira data to GenericTicket.

        Handles edge cases gracefully:
        - Empty raw_data dict
        - Missing fields
        - Non-dict values where dicts are expected (e.g., status: null)

        Args:
            raw_data: Raw Jira API response (issue object)

        Returns:
            Populated GenericTicket with normalized fields
        """
        raw_fields = raw_data.get("fields")
        fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}
        ticket_id = str(raw_data.get("key", ""))

        # Extract status and type with defensive handling for non-dict values
        status_obj = fields.get("status")
        status_name = self.safe_nested_get(status_obj, "name", "")

        issuetype_obj = fields.get("issuetype")
        type_name = self.safe_nested_get(issuetype_obj, "name", "")

        # Extract timestamps
        created_at = self._parse_timestamp(fields.get("created"))
        updated_at = self._parse_timestamp(fields.get("updated"))

        # Extract assignee with defensive handling
        assignee = None
        assignee_obj = fields.get("assignee")
        if isinstance(assignee_obj, dict):
            assignee = assignee_obj.get("displayName") or assignee_obj.get("name")

        # Extract labels - ensure every element is a stripped string
        # Filter after stripping to remove whitespace-only entries
        labels_raw = fields.get("labels")
        labels = (
            [s for s in (str(x).strip() for x in labels_raw) if s]
            if isinstance(labels_raw, list)
            else []
        )

        # Build project key for URL with defensive handling
        project_obj = fields.get("project")
        project_key = self.safe_nested_get(project_obj, "key", "")

        # Smart URL construction: parse scheme/netloc from 'self' API URL if available
        api_url = raw_data.get("self", "")
        browse_url = ""
        if api_url and ticket_id:
            try:
                parsed = urlparse(api_url)
                if parsed.scheme and parsed.netloc:
                    browse_url = f"{parsed.scheme}://{parsed.netloc}/browse/{ticket_id}"
            except Exception:
                pass  # Fall back to empty string

        # Fallback if we couldn't construct from 'self'
        # Use JIRA_BASE_URL env var if available, otherwise leave URL empty
        # (empty is better than a wrong hardcoded URL for self-hosted instances)
        if not browse_url and ticket_id:
            base_url = os.environ.get("JIRA_BASE_URL", "")
            if base_url:
                # Strip trailing slash for consistency
                base_url = base_url.rstrip("/")
                browse_url = f"{base_url}/browse/{ticket_id}"
            # If no base URL configured, leave browse_url as empty string

        # Extract priority with defensive handling
        priority_obj = fields.get("priority")
        priority_name = self.safe_nested_get(priority_obj, "name", "")

        # Extract resolution with defensive handling
        resolution_obj = fields.get("resolution")
        resolution_name = self.safe_nested_get(resolution_obj, "name", "")

        # Extract components (ensure it's a list of dicts)
        components_raw = fields.get("components")
        components = (
            [self.safe_nested_get(c, "name", "") for c in components_raw]
            if isinstance(components_raw, list)
            else []
        )

        # Extract fix versions (ensure it's a list of dicts)
        fix_versions_raw = fields.get("fixVersions")
        fix_versions = (
            [self.safe_nested_get(v, "name", "") for v in fix_versions_raw]
            if isinstance(fix_versions_raw, list)
            else []
        )

        # Extract story points with robust type coercion (handles string values like "5")
        story_points_raw = fields.get("customfield_10016")
        story_points: float = 0.0
        if story_points_raw is not None:
            try:
                story_points = float(story_points_raw)
            except (ValueError, TypeError):
                story_points = 0.0

        # Extract epic link with type safety
        epic_link_raw = fields.get("customfield_10014")
        epic_link: str = str(epic_link_raw) if epic_link_raw else ""

        # Extract summary with type safety
        summary_raw = fields.get("summary")
        summary: str = str(summary_raw) if summary_raw else ""

        # Extract description with ADF (Atlassian Document Format) handling
        description_raw = fields.get("description")
        adf_description: dict[str, Any] | None = None
        if isinstance(description_raw, dict):
            # Description is in ADF format - store raw and provide placeholder
            adf_description = description_raw
            description = "[Rich content - see platform_metadata.adf_description]"
        elif description_raw:
            description = str(description_raw)
        else:
            description = ""

        # Extract platform-specific metadata
        platform_metadata: PlatformMetadata = {
            "raw_response": raw_data,
            "project_key": project_key,
            "priority": priority_name,
            "epic_link": epic_link,
            "story_points": story_points,
            "components": components,
            "issue_type_id": self.safe_nested_get(issuetype_obj, "id", ""),
            "resolution": resolution_name,
            "fix_versions": fix_versions,
            "api_url": api_url,  # Store original API URL for debugging
        }

        # Add ADF description to metadata if present
        if adf_description is not None:
            platform_metadata["adf_description"] = adf_description

        return GenericTicket(
            id=ticket_id,
            platform=Platform.JIRA,
            url=browse_url,
            title=summary,
            description=description,
            status=self._map_status(status_name),
            type=self._map_type(type_name),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(summary),
            platform_metadata=platform_metadata,
        )

    def _map_status(self, status_name: str) -> TicketStatus:
        """Map Jira status to TicketStatus enum.

        Args:
            status_name: Jira status name (e.g., "In Progress")

        Returns:
            Normalized TicketStatus, UNKNOWN if not recognized
        """
        return STATUS_MAPPING.get(status_name.lower(), TicketStatus.UNKNOWN)

    def _map_type(self, type_name: str) -> TicketType:
        """Map Jira issue type to TicketType enum.

        Args:
            type_name: Jira issue type name (e.g., "Story")

        Returns:
            Normalized TicketType, UNKNOWN if not recognized
        """
        return TYPE_MAPPING.get(type_name.lower(), TicketType.UNKNOWN)

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from Jira API.

        Handles various timezone formats for broader Python version compatibility:
        - Z suffix at end of string (converted to +00:00)
        - +0000 format without colon (converted to +00:00)
        - +00:00 format with colon (native support)

        Args:
            timestamp_str: ISO format timestamp string

        Returns:
            datetime object or None if parsing fails
        """
        if not timestamp_str:
            return None
        try:
            # Jira uses ISO format: 2024-01-15T10:30:00.000+0000
            normalized = timestamp_str

            # Normalize Z suffix to +00:00 (only at end of string for precision)
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"

            # Normalize +0000 to +00:00 format (for broader Python compatibility)
            # This handles timezone offsets without colon like +0000, -0500, +0530
            # Only match at end of string to avoid false positives
            if re.search(r"[+-]\d{4}$", normalized):
                normalized = normalized[:-2] + ":" + normalized[-2:]

            return datetime.fromisoformat(normalized)
        except (ValueError, TypeError):
            return None

    def get_prompt_template(self) -> str:
        """Return structured prompt template for agent-mediated fetch.

        Returns:
            Prompt template string with {ticket_id} placeholder
        """
        return STRUCTURED_PROMPT_TEMPLATE

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket details from Jira.

        .. deprecated::
            This method is required by IssueTrackerProvider ABC but
            in the hybrid architecture, fetching is delegated to TicketService
            which uses TicketFetcher implementations. Use TicketService.get_ticket()
            with AuggieMediatedFetcher or DirectAPIFetcher instead.

        Args:
            ticket_id: Normalized ticket ID from parse_input()

        Returns:
            Populated GenericTicket

        Raises:
            NotImplementedError: Fetching should use TicketService
        """
        warnings.warn(
            "JiraProvider.fetch_ticket() is deprecated in hybrid architecture. "
            "Use TicketService.get_ticket() with AuggieMediatedFetcher or "
            "DirectAPIFetcher instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            "JiraProvider.fetch_ticket() is deprecated in hybrid architecture. "
            "Use TicketService.get_ticket() with AuggieMediatedFetcher or "
            "DirectAPIFetcher instead."
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Jira integration is properly configured.

        NOTE: Connection checking is delegated to TicketFetcher implementations
        in the hybrid architecture.

        Returns:
            Tuple of (success: bool, message: str)
        """
        # In hybrid architecture, connection check is done by TicketService
        # This method returns True as the provider itself doesn't manage connections
        return (
            True,
            "JiraProvider ready - use TicketService for connection verification",
        )
