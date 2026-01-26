"""Azure DevOps work item provider.

This module provides the AzureDevOpsProvider class for integrating with Azure DevOps.
Following the hybrid architecture, this provider handles:
- Input parsing (dev.azure.com URLs, visualstudio.com URLs, AB#123 format)
- Data normalization (raw REST API JSON → GenericTicket)
- Status/type mapping to normalized enums

Data fetching is delegated to TicketFetcher implementations.
"""

from __future__ import annotations

import os
import re
import warnings
from html.parser import HTMLParser
from io import StringIO
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

# Status mapping: Azure DevOps state → TicketStatus
STATUS_MAPPING: MappingProxyType[str, TicketStatus] = MappingProxyType(
    {
        # Open states
        "new": TicketStatus.OPEN,
        "to do": TicketStatus.OPEN,
        # In Progress states
        "active": TicketStatus.IN_PROGRESS,
        "in progress": TicketStatus.IN_PROGRESS,
        "committed": TicketStatus.IN_PROGRESS,
        # Review states
        "resolved": TicketStatus.REVIEW,
        # Done states
        "closed": TicketStatus.DONE,
        "done": TicketStatus.DONE,
        # Closed/Cancelled states
        "removed": TicketStatus.CLOSED,
    }
)

# Type mapping: Azure DevOps work item type → TicketType
TYPE_MAPPING: MappingProxyType[str, TicketType] = MappingProxyType(
    {
        # Bug types
        "bug": TicketType.BUG,
        "defect": TicketType.BUG,
        "impediment": TicketType.BUG,
        "issue": TicketType.BUG,
        # Feature types
        "user story": TicketType.FEATURE,
        "feature": TicketType.FEATURE,
        "product backlog item": TicketType.FEATURE,
        "epic": TicketType.FEATURE,
        "requirement": TicketType.FEATURE,
        # Task types
        "task": TicketType.TASK,
        "spike": TicketType.TASK,
        # Maintenance types
        "tech debt": TicketType.MAINTENANCE,
        "change request": TicketType.MAINTENANCE,
    }
)


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper for Azure DevOps descriptions."""

    def __init__(self) -> None:
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, data: str) -> None:
        self.text.write(data)

    def get_data(self) -> str:
        return self.text.getvalue()


def strip_html(html: str) -> str:
    """Strip HTML tags from Azure DevOps description."""
    if not html:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_data().strip()


# Note: Azure DevOps does NOT have Auggie MCP support.
# DirectAPIFetcher is the ONLY fetch path for this platform.
# No STRUCTURED_PROMPT_TEMPLATE is defined.


@ProviderRegistry.register
class AzureDevOpsProvider(IssueTrackerProvider):
    """Azure DevOps work item provider.

    Handles Azure DevOps-specific input parsing and data normalization.
    Data fetching is delegated to TicketFetcher implementations.

    Supports:
    - dev.azure.com URLs
    - visualstudio.com URLs (legacy)
    - AB#123 format (requires default org/project config)

    Class Attributes:
        PLATFORM: Platform.AZURE_DEVOPS for registry registration
    """

    PLATFORM = Platform.AZURE_DEVOPS

    # URL patterns for Azure DevOps
    _DEV_AZURE_PATTERN = re.compile(
        r"https?://dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_workitems/edit/(?P<id>\d+)",
        re.IGNORECASE,
    )
    _VISUALSTUDIO_PATTERN = re.compile(
        r"https?://(?P<org>[^.]+)\.visualstudio\.com/(?P<project>[^/]+)/_workitems/edit/(?P<id>\d+)",
        re.IGNORECASE,
    )
    # AB#123 format (Azure Boards shorthand)
    _AB_PATTERN = re.compile(r"^AB#(?P<id>\d+)$", re.IGNORECASE)

    def __init__(
        self,
        user_interaction: UserInteractionInterface | None = None,
        default_org: str | None = None,
        default_project: str | None = None,
    ) -> None:
        """Initialize AzureDevOpsProvider.

        Args:
            user_interaction: Optional user interaction interface for DI.
            default_org: Default organization for AB# format.
            default_project: Default project for AB# format.
        """
        self._user_interaction = user_interaction or CLIUserInteraction()
        self._default_org = default_org or os.environ.get("AZURE_DEVOPS_ORG", "")
        self._default_project = default_project or os.environ.get("AZURE_DEVOPS_PROJECT", "")

    @property
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        return Platform.AZURE_DEVOPS

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return "Azure DevOps"

    def can_handle(self, input_str: str) -> bool:
        """Check if input is an Azure DevOps work item reference."""
        input_str = input_str.strip()
        if self._DEV_AZURE_PATTERN.match(input_str):
            return True
        if self._VISUALSTUDIO_PATTERN.match(input_str):
            return True
        if self._AB_PATTERN.match(input_str):
            return True
        return False

    def parse_input(self, input_str: str) -> str:
        """Parse Azure DevOps work item URL or ID."""
        input_str = input_str.strip()

        # dev.azure.com URL
        match = self._DEV_AZURE_PATTERN.match(input_str)
        if match:
            return f"{match.group('org')}/{match.group('project')}#{match.group('id')}"

        # visualstudio.com URL
        match = self._VISUALSTUDIO_PATTERN.match(input_str)
        if match:
            return f"{match.group('org')}/{match.group('project')}#{match.group('id')}"

        # AB#123 format
        match = self._AB_PATTERN.match(input_str)
        if match:
            if not self._default_org or not self._default_project:
                raise ValueError(
                    "AB#123 format requires AZURE_DEVOPS_ORG and AZURE_DEVOPS_PROJECT "
                    "environment variables or default_org/default_project parameters"
                )
            return f"{self._default_org}/{self._default_project}#{match.group('id')}"

        raise ValueError(f"Cannot parse Azure DevOps work item from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw Azure DevOps API data to GenericTicket.

        Uses safe_nested_get for all nested field access to handle
        malformed API responses gracefully.

        Args:
            raw_data: Raw API response from Azure DevOps REST API.
            ticket_id: Optional ticket ID from parse_input (unused, for LSP compliance).
        """
        # Safely extract fields dict using _safe_get_dict
        fields = self._safe_get_dict(raw_data, "fields")

        # Extract work item ID using safe_nested_get
        work_item_id = self.safe_nested_get(raw_data, "id", "")
        if not work_item_id:
            raise ValueError("Cannot normalize Azure DevOps work item: 'id' field missing")

        # Extract org/project from URL if available
        raw_url = self.safe_nested_get(raw_data, "url", "")
        org, project = "", ""
        if raw_url:
            match = self._DEV_AZURE_PATTERN.match(raw_url)
            if match:
                org, project = match.group("org"), match.group("project")

        ticket_id = f"{org}/{project}#{work_item_id}" if org and project else work_item_id

        # Extract fields with defensive handling using safe_nested_get pattern
        title = self.safe_nested_get(fields, "System.Title", "")
        description_html = self.safe_nested_get(fields, "System.Description", "")
        description = strip_html(description_html)
        state = self.safe_nested_get(fields, "System.State", "")
        work_item_type = self.safe_nested_get(fields, "System.WorkItemType", "")

        # Assignee - safely extract nested object using _safe_get_dict
        assigned_to = self._safe_get_dict(fields, "System.AssignedTo")
        assignee = self.safe_nested_get(assigned_to, "displayName", "") or None

        # Tags (semicolon-separated)
        tags_str = self.safe_nested_get(fields, "System.Tags", "")
        labels = [t.strip() for t in tags_str.split(";") if t.strip()]

        # Timestamps using inherited parse_timestamp
        created_at = self.parse_timestamp(self.safe_nested_get(fields, "System.CreatedDate", ""))
        updated_at = self.parse_timestamp(self.safe_nested_get(fields, "System.ChangedDate", ""))

        platform_metadata: PlatformMetadata = {
            "organization": org,
            "project": project,
            "work_item_type": work_item_type,
            "state_name": state,
            "area_path": self.safe_nested_get(fields, "System.AreaPath", ""),
            "iteration_path": self.safe_nested_get(fields, "System.IterationPath", ""),
            "assigned_to_email": self.safe_nested_get(assigned_to, "uniqueName", ""),
            "revision": raw_data.get("rev"),
        }

        # Construct browse URL - prefer _links.html.href (human-friendly browse URL)
        links = self._safe_get_dict(raw_data, "_links")
        html_link = self._safe_get_dict(links, "html")
        browse_url = self.safe_nested_get(html_link, "href", "")

        # Fallback logic: only use raw_url if it doesn't look like an API endpoint
        if not browse_url:
            # Check if raw_url looks like an API endpoint (contains _apis)
            if raw_url and "_apis" not in raw_url:
                browse_url = raw_url
            elif org and project:
                # Construct browser URL from org/project if available
                browse_url = f"https://dev.azure.com/{org}/{project}/_workitems/edit/{work_item_id}"
            else:
                # No valid URL available
                browse_url = ""

        return GenericTicket(
            id=ticket_id,
            platform=Platform.AZURE_DEVOPS,
            url=browse_url,
            title=title,
            description=description,
            status=self._map_status(state),
            type=self._map_type(work_item_type),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(title),
            platform_metadata=platform_metadata,
        )

    @staticmethod
    def _safe_get_dict(obj: Any, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        """Safely get a dict value from an object that might not be a dict.

        Args:
            obj: The object to get the key from (may be None, dict, or other type)
            key: The key to retrieve
            default: Default value if key not found or result is not a dict

        Returns:
            The dict value at key if obj is a dict and key exists and value is dict,
            otherwise the default value (empty dict if not provided).
        """
        if default is None:
            default = {}
        if not isinstance(obj, dict):
            return default
        value = obj.get(key)
        if not isinstance(value, dict):
            return default
        return value

    def _map_status(self, state: str) -> TicketStatus:
        """Map Azure DevOps state to TicketStatus enum."""
        return STATUS_MAPPING.get(state.lower(), TicketStatus.UNKNOWN)

    def _map_type(self, work_item_type: str) -> TicketType:
        """Map Azure DevOps work item type to TicketType enum."""
        return TYPE_MAPPING.get(work_item_type.lower(), TicketType.UNKNOWN)

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Azure DevOps does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""

    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket - deprecated in hybrid architecture."""
        warnings.warn(
            "AzureDevOpsProvider.fetch_ticket() is deprecated. "
            "Use TicketService.get_ticket() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            "AzureDevOpsProvider.fetch_ticket() is deprecated in hybrid architecture."
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify integration is properly configured."""
        return (True, "AzureDevOpsProvider ready - use TicketService for connection verification")
