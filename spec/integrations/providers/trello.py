"""Trello card provider.

This module provides the TrelloProvider class for integrating with Trello.
Following the hybrid architecture, this provider handles:
- Input parsing (trello.com card URLs, short links)
- Data normalization (raw REST API JSON → GenericTicket)
- Status/type mapping (list-based status, label-based type)

Data fetching is delegated to TicketFetcher implementations.
"""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone
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

# List status mapping: TicketStatus → tuple of matching list names
LIST_STATUS_MAPPING: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType(
    {
        TicketStatus.OPEN: ("to do", "backlog", "todo", "new", "inbox"),
        TicketStatus.IN_PROGRESS: ("in progress", "doing", "active", "working"),
        TicketStatus.REVIEW: ("review", "in review", "testing", "qa"),
        TicketStatus.BLOCKED: ("blocked", "on hold", "waiting"),
        TicketStatus.DONE: ("done", "complete", "completed", "closed", "archived"),
    }
)

# Type keywords: TicketType → tuple of matching keywords
TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType(
    {
        TicketType.BUG: ("bug", "defect", "fix", "error", "issue"),
        TicketType.FEATURE: ("feature", "enhancement", "story", "new"),
        TicketType.TASK: ("task", "chore", "todo", "action"),
        TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
    }
)

# Note: Trello does NOT have Auggie MCP support.
# DirectAPIFetcher is the ONLY fetch path for this platform.
# No STRUCTURED_PROMPT_TEMPLATE is defined.


@ProviderRegistry.register
class TrelloProvider(IssueTrackerProvider):
    """Trello card provider.

    Handles Trello-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Supports:
    - trello.com card URLs (full and short)
    - 8-character short links

    Class Attributes:
        PLATFORM: Platform.TRELLO for registry registration
    """

    PLATFORM = Platform.TRELLO

    _URL_PATTERN = re.compile(
        r"https?://trello\.com/c/(?P<short_link>[a-zA-Z0-9]+)",
        re.IGNORECASE,
    )
    _SHORT_LINK_PATTERN = re.compile(r"^[a-zA-Z0-9]{8}$")

    def __init__(self, user_interaction: UserInteractionInterface | None = None) -> None:
        """Initialize TrelloProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
        """
        self._user_interaction = user_interaction or CLIUserInteraction()

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.TRELLO

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "Trello"

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a Trello card reference."""
        input_str = input_str.strip()
        if self._URL_PATTERN.match(input_str):
            return True
        if self._SHORT_LINK_PATTERN.match(input_str):
            return True
        return False

    def parse_input(self, input_str: str) -> str:
        """Parse Trello card URL or short link."""
        input_str = input_str.strip()
        match = self._URL_PATTERN.match(input_str)
        if match:
            return match.group("short_link")
        if self._SHORT_LINK_PATTERN.match(input_str):
            return input_str
        raise ValueError(f"Cannot parse Trello card from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw Trello API data to GenericTicket.

        Uses safe_nested_get for all nested field access to handle
        malformed API responses gracefully.

        Args:
            raw_data: Raw API response from Trello REST API.
            ticket_id: Optional ticket ID from parse_input (unused, for LSP compliance).
        """
        # Use safe_nested_get for all direct field access
        short_link = self.safe_nested_get(raw_data, "shortLink", "")
        card_id = self.safe_nested_get(raw_data, "id", "")
        ticket_id = short_link or card_id
        if not ticket_id:
            raise ValueError("Cannot normalize Trello card: 'id' and 'shortLink' missing")

        # Extract list info using safe_nested_get
        list_info = raw_data.get("list") if isinstance(raw_data, dict) else None
        list_name = self.safe_nested_get(list_info, "name", "")
        status = self._map_list_to_status(list_name)

        # Closed cards override list-based status
        if raw_data.get("closed") if isinstance(raw_data, dict) else False:
            status = TicketStatus.CLOSED

        # Defensive handling for members list - may contain non-dict elements
        members = raw_data.get("members", []) if isinstance(raw_data, dict) else []
        assignee = None
        if members and isinstance(members, list) and len(members) > 0:
            first_member = members[0]
            assignee = self.safe_nested_get(first_member, "fullName", "") or None

        labels_raw = raw_data.get("labels", []) if isinstance(raw_data, dict) else []
        labels: list[str] = [
            str(lbl.get("name")) for lbl in labels_raw if isinstance(lbl, dict) and lbl.get("name")
        ]

        # Extract board info using safe_nested_get
        board = raw_data.get("board") if isinstance(raw_data, dict) else None
        created_at = self._get_created_at(card_id)
        updated_at = self.parse_timestamp(self.safe_nested_get(raw_data, "dateLastActivity", ""))

        # Use safe_nested_get for platform metadata fields
        platform_metadata: PlatformMetadata = {
            "board_id": self.safe_nested_get(raw_data, "idBoard", ""),
            "board_name": self.safe_nested_get(board, "name", ""),
            "list_id": self.safe_nested_get(raw_data, "idList", ""),
            "list_name": list_name,
            "due_date": raw_data.get("due") if isinstance(raw_data, dict) else None,
            "due_complete": bool(raw_data.get("dueComplete", False))
            if isinstance(raw_data, dict)
            else False,
            "is_closed": bool(raw_data.get("closed", False))
            if isinstance(raw_data, dict)
            else False,
            "short_link": short_link,
        }

        # Extract and sanitize title
        title = self.safe_nested_get(raw_data, "name", "")
        url = self.safe_nested_get(raw_data, "url", "") or self.safe_nested_get(
            raw_data, "shortUrl", ""
        )

        return GenericTicket(
            id=ticket_id,
            platform=Platform.TRELLO,
            url=url,
            title=title,
            description=self.safe_nested_get(raw_data, "desc", ""),
            status=status,
            type=self._map_type(labels),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(title),
            platform_metadata=platform_metadata,
        )

    def _map_list_to_status(self, list_name: str) -> TicketStatus:
        """Map Trello list name to TicketStatus enum.

        Uses case-insensitive substring matching to handle variations
        like "In Progress (Dev)" matching "in progress" keyword.
        """
        name_lower = list_name.lower().strip()
        for status, keywords in LIST_STATUS_MAPPING.items():
            if any(kw in name_lower for kw in keywords):
                return status
        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map Trello labels to TicketType enum.

        Uses case-insensitive substring matching.
        """
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type
        return TicketType.UNKNOWN

    def _get_created_at(self, card_id: str) -> datetime | None:
        """Extract creation timestamp from card ID (MongoDB ObjectId).

        Returns None if parsing fails (instead of misleading datetime.now()).
        """
        if not card_id or len(card_id) < 8:
            return None
        try:
            timestamp_hex = card_id[:8]
            timestamp = int(timestamp_hex, 16)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, IndexError, OSError):
            return None

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Trello does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket - deprecated in hybrid architecture."""
        warnings.warn(
            "TrelloProvider.fetch_ticket() is deprecated. "
            "Use TicketService.get_ticket() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError("TrelloProvider.fetch_ticket() is deprecated.")

    def check_connection(self) -> tuple[bool, str]:
        """Verify integration is properly configured."""
        return (True, "TrelloProvider ready - use TicketService for connection verification")
