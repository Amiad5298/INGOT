"""Monday.com item provider.

This module provides the MondayProvider class for integrating with Monday.com.
Following the hybrid architecture, this provider handles:
- Input parsing (monday.com board/pulse URLs)
- Data normalization (raw GraphQL JSON → GenericTicket)
- Status/type mapping via keyword matching

Data fetching is delegated to TicketFetcher implementations.
"""

from __future__ import annotations

import re
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

# Status keywords: TicketStatus → tuple of matching keywords
STATUS_KEYWORDS: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType(
    {
        TicketStatus.OPEN: ("", "not started", "new", "to do", "backlog"),
        TicketStatus.IN_PROGRESS: ("working on it", "in progress", "active", "started"),
        TicketStatus.REVIEW: ("review", "waiting for review", "pending", "awaiting"),
        TicketStatus.BLOCKED: ("stuck", "blocked", "on hold", "waiting"),
        TicketStatus.DONE: ("done", "complete", "completed", "closed", "finished"),
    }
)

# Type keywords: TicketType → tuple of matching keywords
TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType(
    {
        TicketType.BUG: ("bug", "defect", "issue", "fix", "error", "crash"),
        TicketType.FEATURE: ("feature", "enhancement", "story", "user story", "new"),
        TicketType.TASK: ("task", "chore", "todo", "action item"),
        TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
    }
)

# Note: Monday.com does NOT have Auggie MCP support.
# DirectAPIFetcher is the ONLY fetch path for this platform.
# No STRUCTURED_PROMPT_TEMPLATE is defined.


@ProviderRegistry.register
class MondayProvider(IssueTrackerProvider):
    """Monday.com item provider.

    Handles Monday.com-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Supports:
    - monday.com board/pulse URLs (with or without subdomain)
    - monday.com board/views/pulse URLs
    - view.monday.com URLs

    Class Attributes:
        PLATFORM: Platform.MONDAY for registry registration

    Note:
        This provider is registered as a Singleton. To avoid race conditions,
        no request-specific state is stored as instance attributes. The account
        slug is embedded in the composite ticket ID returned by parse_input.
    """

    PLATFORM = Platform.MONDAY

    # Updated regex to handle optional subdomain (including view.monday.com and bare monday.com)
    _URL_PATTERN = re.compile(
        r"https?://(?:(?P<slug>[^.]+)\.)?monday\.com/boards/(?P<board>\d+)(?:/views/\d+)?/pulses/(?P<item>\d+)",
        re.IGNORECASE,
    )

    def __init__(self, user_interaction: UserInteractionInterface | None = None) -> None:
        """Initialize MondayProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
        """
        self._user_interaction = user_interaction or CLIUserInteraction()
        # Note: No request-specific state stored here (Singleton-safe)

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.MONDAY

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "Monday.com"

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a Monday.com item reference."""
        return bool(self._URL_PATTERN.match(input_str.strip()))

    def parse_input(self, input_str: str) -> str:
        """Parse Monday.com item URL.

        Returns a composite ID in the format: slug:board_id:item_id
        The slug may be empty for URLs like view.monday.com or bare monday.com.

        This design avoids storing request-specific state in the Singleton provider.
        """
        match = self._URL_PATTERN.match(input_str.strip())
        if match:
            slug = match.group("slug") or ""
            board_id = match.group("board")
            item_id = match.group("item")
            # Return composite ID: slug:board_id:item_id
            return f"{slug}:{board_id}:{item_id}"
        raise ValueError(f"Cannot parse Monday.com item from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw Monday.com API data to GenericTicket.

        Args:
            raw_data: Raw API response from Monday.com GraphQL API.
            ticket_id: Optional composite ID from parse_input (slug:board_id:item_id).
                       Used to extract account slug for URL construction.
        """
        item_id = str(self.safe_nested_get(raw_data, "id", ""))
        if not item_id:
            raise ValueError("Cannot normalize Monday.com item: 'id' field missing")

        # Extract board info using safe_nested_get
        board = raw_data.get("board") if isinstance(raw_data, dict) else None
        board_id = self.safe_nested_get(board, "id", "")
        board_name = self.safe_nested_get(board, "name", "")

        # Parse account slug from composite ticket_id if provided
        account_slug: str | None = None
        if ticket_id:
            parts = ticket_id.split(":")
            if len(parts) >= 3 and parts[0]:
                account_slug = parts[0]

        # Build normalized ticket ID (board_id:item_id)
        normalized_id = f"{board_id}:{item_id}" if board_id else item_id

        columns = raw_data.get("column_values", []) if isinstance(raw_data, dict) else []
        status_label = self._find_column_text(columns, "status")
        assignee = self._find_column_text(columns, "people")
        tags_text = self._find_column_text(columns, "tag")
        labels = [t.strip() for t in tags_text.split(",") if t.strip()] if tags_text else []

        description = self._extract_description(raw_data, columns)
        created_at = self.parse_timestamp(self.safe_nested_get(raw_data, "created_at", ""))
        updated_at = self.parse_timestamp(self.safe_nested_get(raw_data, "updated_at", ""))

        # Construct URL - use subdomain if available
        if account_slug:
            url = f"https://{account_slug}.monday.com/boards/{board_id}/pulses/{item_id}"
        else:
            url = f"https://monday.com/boards/{board_id}/pulses/{item_id}"

        # Extract group and creator info using safe_nested_get
        group = raw_data.get("group") if isinstance(raw_data, dict) else None
        creator = raw_data.get("creator") if isinstance(raw_data, dict) else None

        platform_metadata: PlatformMetadata = {
            "board_id": board_id,
            "board_name": board_name,
            "group_title": self.safe_nested_get(group, "title", ""),
            "creator_name": self.safe_nested_get(creator, "name", ""),
            "status_label": status_label,
            "account_slug": account_slug,
        }

        # Extract and sanitize title
        title = self.safe_nested_get(raw_data, "name", "")

        return GenericTicket(
            id=normalized_id,
            platform=Platform.MONDAY,
            url=url,
            title=title,
            description=description,
            status=self._map_status(status_label),
            type=self._map_type(labels),
            assignee=assignee or None,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(title),
            platform_metadata=platform_metadata,
        )

    def _find_column_text(self, columns: list[Any], col_type: str) -> str:
        """Find column text by type or id.

        Checks both 'type' AND 'id' fields to handle cases where the column
        id matches common names like 'status', 'person', 'tags', 'date'
        even if the type differs (e.g., type='color' for status columns).
        """
        for col in columns:
            if isinstance(col, dict):
                # Check type OR id (common IDs: "status", "person", "tags", "date")
                if col.get("type") == col_type or col.get("id") == col_type:
                    return str(col.get("text", "") or "")
        return ""

    def _extract_description(self, item: dict[str, Any], columns: list[Any]) -> str:
        """Extract description using cascading fallback strategy."""
        # First try to find a description column
        for col in columns:
            if isinstance(col, dict):
                col_type = str(col.get("type", "") or "")
                col_title = str(col.get("title", "") or "").lower()
                if col_type in ["text", "long_text"] and "desc" in col_title:
                    text = str(col.get("text", "") or "").strip()
                    if text:
                        return text
        # Fallback to updates (oldest first)
        updates = item.get("updates", [])
        if updates and isinstance(updates, list):
            oldest = updates[-1] if updates else {}
            if isinstance(oldest, dict):
                return str(oldest.get("text_body", "") or oldest.get("body", "") or "")
        return ""

    def _map_status(self, label: str) -> TicketStatus:
        """Map Monday.com status label to TicketStatus enum.

        Uses case-insensitive substring matching to handle variations
        like "Working on it" matching "working" keyword.

        Special case: Empty label maps to OPEN (Monday.com default for new items).
        """
        label_lower = label.lower().strip()

        # Special case: empty label maps to OPEN
        if not label_lower:
            return TicketStatus.OPEN

        for status, keywords in STATUS_KEYWORDS.items():
            # Skip empty string keyword - handled above
            if any(kw and kw in label_lower for kw in keywords):
                return status
        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map Monday.com labels to TicketType enum.

        Uses case-insensitive substring matching.
        """
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type
        return TicketType.UNKNOWN

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Monday.com does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""
