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
    - monday.com board/pulse URLs
    - monday.com board/views/pulse URLs

    Class Attributes:
        PLATFORM: Platform.MONDAY for registry registration
    """

    PLATFORM = Platform.MONDAY

    _URL_PATTERN = re.compile(
        r"https?://(?P<slug>[^.]+)\.monday\.com/boards/(?P<board>\d+)(?:/views/\d+)?/pulses/(?P<item>\d+)",
        re.IGNORECASE,
    )

    def __init__(self, user_interaction: UserInteractionInterface | None = None) -> None:
        """Initialize MondayProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
        """
        self._user_interaction = user_interaction or CLIUserInteraction()
        self._account_slug: str | None = None

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
        """Parse Monday.com item URL."""
        match = self._URL_PATTERN.match(input_str.strip())
        if match:
            self._account_slug = match.group("slug")
            return f"{match.group('board')}:{match.group('item')}"
        raise ValueError(f"Cannot parse Monday.com item from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        """Convert raw Monday.com API data to GenericTicket."""
        item_id = str(raw_data.get("id", ""))
        if not item_id:
            raise ValueError("Cannot normalize Monday.com item: 'id' field missing")

        board = raw_data.get("board", {})
        board_id = self.safe_nested_get(board, "id", "")
        ticket_id = f"{board_id}:{item_id}" if board_id else item_id

        columns = raw_data.get("column_values", [])
        status_label = self._find_column_text(columns, "status")
        assignee = self._find_column_text(columns, "people")
        tags_text = self._find_column_text(columns, "tag")
        labels = [t.strip() for t in tags_text.split(",") if t.strip()] if tags_text else []

        description = self._extract_description(raw_data, columns)
        created_at = self._parse_timestamp(raw_data.get("created_at"))
        updated_at = self._parse_timestamp(raw_data.get("updated_at"))

        url = f"https://monday.com/boards/{board_id}/pulses/{item_id}"
        if self._account_slug:
            url = f"https://{self._account_slug}.monday.com/boards/{board_id}/pulses/{item_id}"

        platform_metadata: PlatformMetadata = {
            "board_id": board_id,
            "board_name": self.safe_nested_get(board, "name", ""),
            "group_title": self.safe_nested_get(raw_data.get("group", {}), "title", ""),
            "creator_name": self.safe_nested_get(raw_data.get("creator", {}), "name", ""),
            "status_label": status_label,
            "account_slug": self._account_slug,
        }

        return GenericTicket(
            id=ticket_id,
            platform=Platform.MONDAY,
            url=url,
            title=raw_data.get("name", ""),
            description=description,
            status=self._map_status(status_label),
            type=self._map_type(labels),
            assignee=assignee or None,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(raw_data.get("name", "")),
            platform_metadata=platform_metadata,
        )

    def _find_column_text(self, columns: list[Any], col_type: str) -> str:
        """Find column text by type."""
        for col in columns:
            if isinstance(col, dict) and col.get("type") == col_type:
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
        """Map Monday.com status label to TicketStatus enum."""
        label_lower = label.lower().strip()
        for status, keywords in STATUS_KEYWORDS.items():
            if label_lower in keywords:
                return status
        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map Monday.com labels to TicketType enum."""
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type
        return TicketType.UNKNOWN

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from Monday.com API."""
        if not timestamp_str:
            return None
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Monday.com does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket - deprecated in hybrid architecture."""
        warnings.warn(
            "MondayProvider.fetch_ticket() is deprecated. "
            "Use TicketService.get_ticket() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError("MondayProvider.fetch_ticket() is deprecated.")

    def check_connection(self) -> tuple[bool, str]:
        """Verify integration is properly configured."""
        return (True, "MondayProvider ready - use TicketService for connection verification")
