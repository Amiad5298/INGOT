"""Linear issue tracker provider.

This module provides the LinearProvider class for integrating with Linear.
Following the hybrid architecture, this provider handles:
- Input parsing (URLs, TEAM-123 format)
- Data normalization (raw GraphQL JSON → GenericTicket)
- Status/type mapping to normalized enums

Data fetching is delegated to TicketFetcher implementations.
"""

from __future__ import annotations

import re
import warnings
from datetime import datetime
from types import MappingProxyType
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
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    UserInteractionInterface,
)

# Status mapping: Linear state.type → TicketStatus
# Linear has 5 workflow state types
# NOTE: state.name takes PRIORITY for specific statuses like "In Review"
# because "In Review" often has type="started" but should map to REVIEW
# Using MappingProxyType to prevent accidental mutation
STATUS_TYPE_MAPPING: MappingProxyType[str, TicketStatus] = MappingProxyType(
    {
        # Backlog state - not started, low priority
        "backlog": TicketStatus.OPEN,
        # Unstarted state - ready to work on
        "unstarted": TicketStatus.OPEN,
        # Started state - actively being worked on
        "started": TicketStatus.IN_PROGRESS,
        # Completed state - work is finished
        "completed": TicketStatus.DONE,
        # Canceled state - will not be done
        "canceled": TicketStatus.CLOSED,
    }
)

# State name mappings for specific state names that OVERRIDE state.type
# IMPORTANT: These are checked BEFORE state.type to handle cases like
# "In Review" which has type="started" but should map to REVIEW
# Using MappingProxyType to prevent accidental mutation
STATE_NAME_MAPPING: MappingProxyType[str, TicketStatus] = MappingProxyType(
    {
        # Review states - MUST be checked before state.type
        # because "In Review" often has type="started"
        "in review": TicketStatus.REVIEW,
        "review": TicketStatus.REVIEW,
        "code review": TicketStatus.REVIEW,
        "pending review": TicketStatus.REVIEW,
        # Backlog states
        "backlog": TicketStatus.OPEN,
        "triage": TicketStatus.OPEN,
        # Ready states
        "todo": TicketStatus.OPEN,
        "to do": TicketStatus.OPEN,
        "ready": TicketStatus.OPEN,
        # In progress states
        "in progress": TicketStatus.IN_PROGRESS,
        "in development": TicketStatus.IN_PROGRESS,
        # Done states
        "done": TicketStatus.DONE,
        "complete": TicketStatus.DONE,
        "completed": TicketStatus.DONE,
        # Closed states
        "canceled": TicketStatus.CLOSED,
        "cancelled": TicketStatus.CLOSED,
    }
)

# Type inference keywords: keyword → TicketType
# Linear uses labels for categorization, so we infer type from label names
# NOTE: If no type-specific keywords are found, defaults to FEATURE (not UNKNOWN)
# Using MappingProxyType to prevent accidental mutation
TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType(
    {
        TicketType.BUG: ("bug", "defect", "fix", "error", "crash", "regression", "issue"),
        TicketType.FEATURE: ("feature", "enhancement", "story", "improvement", "new"),
        TicketType.TASK: ("task", "chore", "todo", "spike", "research"),
        TicketType.MAINTENANCE: (
            "maintenance",
            "tech-debt",
            "tech debt",
            "refactor",
            "cleanup",
            "infrastructure",
            "devops",
        ),
    }
)


# Structured prompt template for agent-mediated fetching
# Uses Linear's GraphQL response structure
STRUCTURED_PROMPT_TEMPLATE = """Read Linear issue {ticket_id} and return the following as JSON.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "id": "<Linear internal UUID>",
  "identifier": "<TEAM-123>",
  "title": "<issue title>",
  "description": "<description markdown or null>",
  "url": "<Linear URL>",
  "state": {{
    "name": "<status name>",
    "type": "<backlog|unstarted|started|completed|canceled>"
  }},
  "assignee": {{"name": "<assignee name>", "email": "<email>"}} or null,
  "labels": {{
    "nodes": [
      {{"name": "<label1>"}},
      {{"name": "<label2>"}}
    ]
  }},
  "priority": <0-4 number>,
  "priorityLabel": "<No priority|Urgent|High|Medium|Low>",
  "team": {{"key": "<TEAM>", "name": "<Team Name>"}},
  "cycle": {{"name": "<cycle name>"}} or null,
  "parent": {{"identifier": "<parent TEAM-123>"}} or null,
  "createdAt": "<ISO timestamp>",
  "updatedAt": "<ISO timestamp>"
}}"""


@ProviderRegistry.register
class LinearProvider(IssueTrackerProvider):
    """Linear issue tracker provider.

    Handles Linear-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Linear uses GraphQL API and has:
    - Workflow state types (backlog, unstarted, started, completed, canceled)
    - Labels for categorization (used for type inference)
    - Team-based issue identifiers (TEAM-123)

    Class Attributes:
        PLATFORM: Platform.LINEAR for registry registration
    """

    PLATFORM = Platform.LINEAR

    # Unified URL pattern for Linear - handles both with and without title slug
    # Pattern breakdown:
    # - https?://linear\.app/ - protocol and domain
    # - (?P<org>[^/]+)/ - organization/workspace slug
    # - issue/ - literal path segment
    # - (?P<ticket_id>[A-Z][A-Z0-9]*-\d+) - team key (alphanumeric like ENG, G2, A1) + number
    # - (?:/[^/]*)? - optional title slug (non-capturing group)
    # - $ - end of string (strict matching)
    # Using fullmatch equivalent via $ anchor to prevent partial matches
    _URL_PATTERN = re.compile(
        r"https?://linear\.app/(?P<org>[^/]+)/issue/"
        r"(?P<ticket_id>[A-Z][A-Z0-9]*-\d+)(?:/[^/]*)?$",
        re.IGNORECASE,
    )

    # ID pattern: TEAM-123 format (alphanumeric team key like ENG, G2, A1)
    # Uses fullmatch-equivalent $ anchor to prevent partial matches like "ENG-123abc"
    _ID_PATTERN = re.compile(r"^(?P<ticket_id>[A-Z][A-Z0-9]*-\d+)$", re.IGNORECASE)

    def __init__(
        self,
        user_interaction: UserInteractionInterface | None = None,
    ) -> None:
        """Initialize LinearProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
                If not provided, uses CLIUserInteraction.
        """
        self._user_interaction = user_interaction or CLIUserInteraction()

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.LINEAR

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "Linear"

    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Recognizes:
        - Linear URLs: https://linear.app/org/issue/TEAM-123
        - Linear URLs with title: https://linear.app/org/issue/TEAM-123/title-slug
        - Ticket IDs: TEAM-123 format with alphanumeric team (ENG, G2, A1)

        Note: TEAM-123 format is ambiguous with Jira. The PlatformDetector
        handles disambiguation; this method reports if the format is compatible.

        Uses fullmatch-equivalent patterns ($ anchor) to prevent partial matches
        on invalid strings like "ENG-123abc".

        Args:
            input_str: URL or ticket ID to check

        Returns:
            True if this provider recognizes the input format
        """
        input_str = input_str.strip()

        # Check URL pattern (unambiguous Linear detection)
        # Uses unified pattern with $ anchor for strict matching
        if self._URL_PATTERN.fullmatch(input_str):
            return True

        # Check ID pattern (TEAM-123) - ambiguous with Jira
        # Uses fullmatch() for strict matching (rejects "ENG-123abc")
        if self._ID_PATTERN.fullmatch(input_str):
            return True

        return False

    def parse_input(self, input_str: str) -> str:
        """Parse input and extract normalized ticket ID.

        Uses fullmatch() for strict pattern matching to reject invalid
        inputs like "ENG-123abc" that only partially match.

        Args:
            input_str: URL or ticket ID

        Returns:
            Normalized ticket ID in uppercase (e.g., "TEAM-123", "G2-42")

        Raises:
            ValueError: If input cannot be parsed
        """
        input_str = input_str.strip()

        # Try URL pattern first (unified pattern handles with/without slug)
        match = self._URL_PATTERN.fullmatch(input_str)
        if match:
            return match.group("ticket_id").upper()

        # Try ID pattern (TEAM-123, G2-42, etc.)
        match = self._ID_PATTERN.fullmatch(input_str)
        if match:
            return match.group("ticket_id").upper()

        raise ValueError(f"Cannot parse Linear ticket from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw Linear GraphQL data to GenericTicket.

        Handles nested GraphQL response structure (e.g., labels.nodes[]).
        Uses safe_nested_get() for defensive field handling of malformed responses.

        Args:
            raw_data: Raw Linear GraphQL response (issue object)
            ticket_id: Optional ticket ID from parse_input (unused, for LSP compliance).

        Returns:
            Populated GenericTicket with normalized fields

        Raises:
            ValueError: If ticket ID (identifier) is empty or missing.
                Do not create "ghost" tickets without valid IDs.
        """
        # Extract and validate identifier (TEAM-123)
        ticket_id = raw_data.get("identifier", "")
        if not ticket_id or not isinstance(ticket_id, str) or not ticket_id.strip():
            raise ValueError(
                "Cannot normalize Linear ticket: 'identifier' field is missing or empty. "
                "A valid ticket ID is required."
            )
        ticket_id = ticket_id.strip()

        # Extract state - check state.name FIRST for specific statuses like "In Review"
        # because "In Review" often has type="started" but should map to REVIEW
        # Use safe_nested_get() for defensive handling of malformed responses
        state_obj = raw_data.get("state")
        state_type = self.safe_nested_get(state_obj, "type", "")
        state_name = self.safe_nested_get(state_obj, "name", "")

        # Extract timestamps
        created_at = self._parse_timestamp(raw_data.get("createdAt"))
        updated_at = self._parse_timestamp(raw_data.get("updatedAt"))

        # Extract assignee (prefer name over email)
        # Use safe_nested_get() for defensive handling
        assignee_obj = raw_data.get("assignee")
        assignee = (
            self.safe_nested_get(assignee_obj, "name", "")
            or self.safe_nested_get(assignee_obj, "email", "")
            or None
        )

        # Extract labels from nested GraphQL structure
        # Use safe_nested_get() consistently to avoid AttributeError
        # if labels is None or a non-dict type
        labels = self._extract_labels(raw_data.get("labels"))

        # Get URL (directly from response)
        url = raw_data.get("url", "")

        # Build team key for metadata
        # Use safe_nested_get() for defensive handling
        team_obj = raw_data.get("team")
        team_key = self.safe_nested_get(team_obj, "key", "")
        team_name = self.safe_nested_get(team_obj, "name", "")

        # Extract platform-specific metadata
        # Use safe_nested_get() for defensive handling of nested fields
        # NOTE: raw_response is intentionally omitted to avoid log/cache bloat
        cycle_obj = raw_data.get("cycle")
        cycle_name = self.safe_nested_get(cycle_obj, "name", "") or None

        parent_obj = raw_data.get("parent")
        parent_id = self.safe_nested_get(parent_obj, "identifier", "") or None

        platform_metadata: PlatformMetadata = {
            # Intentionally omit raw_response to avoid polluting logs/cache
            "linear_uuid": raw_data.get("id", ""),
            "team_key": team_key,
            "team_name": team_name,
            "priority_label": raw_data.get("priorityLabel", ""),
            "priority_value": raw_data.get("priority"),
            "state_name": state_name,
            "state_type": state_type,
            "cycle": cycle_name,
            "parent_id": parent_id,
        }

        return GenericTicket(
            id=ticket_id,
            platform=Platform.LINEAR,
            url=url,
            title=raw_data.get("title", ""),
            description=raw_data.get("description") or "",
            status=self._map_status(state_type, state_name),
            type=self._map_type(labels),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(raw_data.get("title", "")),
            platform_metadata=platform_metadata,
        )

    def _extract_labels(self, labels_obj: Any) -> list[str]:
        """Extract label names from nested GraphQL labels structure.

        Safely handles malformed data where labels_obj might be None,
        a string, or have missing/malformed nodes.

        Args:
            labels_obj: The 'labels' field from raw_data, expected to be
                {"nodes": [{"name": "..."}, ...]} or None/invalid

        Returns:
            List of label name strings, empty list if extraction fails
        """
        # Handle None or non-dict labels_obj
        if not isinstance(labels_obj, dict):
            return []

        # Use safe_nested_get pattern for consistent defensive access
        # Note: safe_nested_get returns str, so we get the raw value and validate
        nodes_raw = labels_obj.get("nodes") if isinstance(labels_obj, dict) else None
        # Convert via safe_nested_get pattern: if not a list, treat as empty
        nodes = nodes_raw if isinstance(nodes_raw, list) else []

        # Extract name from each node, filtering invalid entries
        labels: list[str] = []
        for node in nodes:
            if isinstance(node, dict):
                name = self.safe_nested_get(node, "name", "").strip()
                if name:
                    labels.append(name)

        return labels

    def _map_status(self, state_type: str, state_name: str) -> TicketStatus:
        """Map Linear state to TicketStatus enum.

        IMPORTANT: Checks state.name FIRST for specific statuses like "In Review".
        This is because Linear's "In Review" status typically has type="started",
        but should map to TicketStatus.REVIEW, not IN_PROGRESS.

        Priority order:
        1. Check state.name for specific mappings (e.g., "In Review" → REVIEW)
        2. Fall back to state.type for standard mappings (e.g., "started" → IN_PROGRESS)
        3. Return UNKNOWN if neither matches

        Args:
            state_type: Linear state type (e.g., "started", "completed")
            state_name: Linear state name (e.g., "In Review", "In Progress")

        Returns:
            Normalized TicketStatus, UNKNOWN if not recognized
        """
        # FIRST: Check state.name for specific mappings
        # This handles cases like "In Review" which has type="started"
        # but should map to REVIEW, not IN_PROGRESS
        if state_name:
            status = STATE_NAME_MAPPING.get(state_name.lower())
            if status:
                return status

        # SECOND: Fall back to state.type for standard workflow states
        if state_type:
            status = STATUS_TYPE_MAPPING.get(state_type.lower())
            if status:
                return status

        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map Linear labels to TicketType enum.

        Linear uses labels for categorization. Infer type from keywords
        in the label names.

        Args:
            labels: List of label names from the issue

        Returns:
            Matched TicketType, or FEATURE if no type-specific labels found.
            According to requirements, default type is FEATURE (not UNKNOWN).
        """
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type

        # Return FEATURE as default if no type-specific labels found
        # Per requirements: default ticket type must be FEATURE, not UNKNOWN
        return TicketType.FEATURE

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from Linear GraphQL API.

        Args:
            timestamp_str: ISO format timestamp string (e.g., "2024-01-15T10:30:00.000Z")

        Returns:
            datetime object or None if parsing fails
        """
        if not timestamp_str:
            return None
        # Ensure we have a string before calling .replace()
        if not isinstance(timestamp_str, str):
            return None
        try:
            # Linear uses ISO format with Z suffix: 2024-01-15T10:30:00.000Z
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    def get_prompt_template(self) -> str:
        """Return structured prompt template for agent-mediated fetch.

        Returns:
            Prompt template string with {ticket_id} placeholder
        """
        return STRUCTURED_PROMPT_TEMPLATE

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket details from Linear.

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
            "LinearProvider.fetch_ticket() is deprecated. "
            "Use TicketService.get_ticket() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            "LinearProvider.fetch_ticket() is deprecated in hybrid architecture. "
            "Use TicketService.get_ticket() with AuggieMediatedFetcher or "
            "DirectAPIFetcher instead."
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Linear integration is properly configured.

        .. deprecated::
            This method returns a hardcoded True and should not be relied upon
            in the hybrid architecture. Use TicketService for actual connection
            verification via TicketFetcher implementations.

        Returns:
            Tuple of (success: bool, message: str)
        """
        warnings.warn(
            "LinearProvider.check_connection() is deprecated. "
            "This method returns a hardcoded True and should not be relied upon. "
            "Use TicketService for connection verification.",
            DeprecationWarning,
            stacklevel=2,
        )
        # In hybrid architecture, connection check is done by TicketService
        # This method returns True as the provider itself doesn't manage connections
        return (True, "LinearProvider ready - use TicketService for connection verification")
