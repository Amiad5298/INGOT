# Implementation Plan: AMI-21 - Implement Additional Platform Providers (Azure DevOps, Monday, Trello)

**Ticket:** [AMI-21](https://linear.app/amiadspec/issue/AMI-21/implement-additional-platform-providers-azure-devops-monday-trello)
**Status:** ✅ Implemented
**Date:** 2026-01-25
**Implemented:** 2026-01-26
**PR:** [#30](https://github.com/Amiad5298/Spec/pull/30)

---

## Summary

This ticket implements three additional provider concrete classes that extend `IssueTrackerProvider`:
- `AzureDevOpsProvider` (Platform.AZURE_DEVOPS)
- `MondayProvider` (Platform.MONDAY)
- `TrelloProvider` (Platform.TRELLO)

Following the hybrid ticket fetching architecture established in AMI-18, AMI-19, and AMI-20, each provider focuses on **input parsing and data normalization**, not direct API calls. The actual data fetching is delegated to `TicketFetcher` implementations (`DirectAPIFetcher` as the primary path for these platforms, since they are NOT supported by Auggie MCP).

Each provider is responsible for:
1. **Input parsing** - Recognizing platform-specific URLs and ticket ID formats
2. **Data normalization** - Converting raw API/agent responses to `GenericTicket`
3. **Status/type mapping** - Mapping platform-specific values to normalized enums
4. **No agent-mediated fetch** - DirectAPIFetcher is the only fetch path (no Auggie MCP support)

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TicketFetcher (AMI-29/30/31)      │  Handles HOW to get data               │
│  • DirectAPIFetcher (primary)     │  • REST/GraphQL API → raw JSON         │
│  • AuggieMediatedFetcher (N/A)    │  • NOT supported for these platforms   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ raw JSON data
┌─────────────────────────────────────────────────────────────────────────────┐
│  Provider (THIS TICKET)            │  Handles WHAT the data means           │
│  • AzureDevOpsProvider            │  • can_handle() + parse_input()        │
│  • MondayProvider                 │  • normalize() → GenericTicket         │
│  • TrelloProvider                 │  • No Auggie MCP (DirectAPI only)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ProviderRegistry (AMI-17)                            │
│  @ProviderRegistry.register                                                  │
│  → Singleton provider instance per platform                                  │
│  → Auto-detection via get_provider_for_input()                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **PLATFORM Class Attribute** - Required for `@ProviderRegistry.register` decorator validation
2. **No Direct API Calls** - All fetching delegated to `TicketFetcher` via `TicketService` (AMI-32)
3. **DirectAPIFetcher Primary** - These platforms lack Auggie MCP support; handlers already in AMI-31
4. **Status Mapping via Keywords** - Flexible keyword matching for customizable platforms
5. **Type Inference from Labels** - Monday/Trello use labels; Azure DevOps uses `WorkItemType`
6. **Optional DI** - Constructor accepts optional `user_interaction` for testing
7. **Defensive Field Handling** - Uses `safe_nested_get()` from base class

### Important Scope Note

Per AMI-21 Linear ticket comments, the API handlers for these platforms are **already implemented in AMI-31**:
- `spec/integrations/fetchers/handlers/azure_devops.py`
- `spec/integrations/fetchers/handlers/monday.py`
- `spec/integrations/fetchers/handlers/trello.py`

This ticket focuses **only** on the `IssueTrackerProvider` implementations (parsing, normalization, registry integration).

---

## Files to Create

| File | Purpose |
|------|---------|
| `spec/integrations/providers/azure_devops.py` | AzureDevOpsProvider implementation |
| `spec/integrations/providers/monday.py` | MondayProvider implementation |
| `spec/integrations/providers/trello.py` | TrelloProvider implementation |

## Files to Modify

| File | Changes |
|------|---------|
| `spec/integrations/providers/__init__.py` | Export new providers in `__all__` |

---

## Provider 1: AzureDevOpsProvider

### File: `spec/integrations/providers/azure_devops.py`

#### Input Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| Cloud URL (dev.azure.com) | `https://dev.azure.com/myorg/MyProject/_workitems/edit/42` | `https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)` |
| Cloud URL (visualstudio.com) | `https://myorg.visualstudio.com/MyProject/_workitems/edit/42` | `https?://([^.]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)` |
| ID with context | `AB#42` | `^AB#(\d+)$` (requires default org/project) |

**Normalized Ticket ID Format:** `{organization}/{project}#{work_item_id}` (e.g., `contoso/Backend#42`)

#### Status Mapping

Azure DevOps states vary by process template (Agile, Scrum, CMMI). Using keyword matching:

```python
STATUS_MAPPING: MappingProxyType[str, TicketStatus] = MappingProxyType({
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
})
```

#### Type Mapping

Azure DevOps has explicit `System.WorkItemType` field:

```python
TYPE_MAPPING: MappingProxyType[str, TicketType] = MappingProxyType({
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
    "review": TicketType.TASK,
    # Maintenance types
    "tech debt": TicketType.MAINTENANCE,
    "change request": TicketType.MAINTENANCE,
    "risk": TicketType.MAINTENANCE,
})
```

#### Platform Metadata

| Metadata Field | API Field | Notes |
|----------------|-----------|-------|
| `organization` | Extracted from URL | Azure DevOps org name |
| `project` | Extracted from URL | Project name |
| `work_item_type` | `System.WorkItemType` | Bug, Task, User Story, etc. |
| `state_name` | `System.State` | Original state name |
| `area_path` | `System.AreaPath` | Area classification |
| `iteration_path` | `System.IterationPath` | Sprint/iteration path |
| `assigned_to_email` | `System.AssignedTo.uniqueName` | Assignee email |
| `revision` | `rev` | Work item revision number |

#### No Agent-Mediated Fetch

Azure DevOps does **NOT** have Auggie MCP integration. `DirectAPIFetcher` is the only fetch path.

The `get_prompt_template()` method returns an empty string:

```python
def get_prompt_template(self) -> str:
    """Return empty string - agent-mediated fetch not supported.

    Azure DevOps does NOT have Auggie MCP integration.
    DirectAPIFetcher is the only fetch path.
    """
    return ""
```

---

## Provider 2: MondayProvider

### File: `spec/integrations/providers/monday.py`

#### Input Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| Item URL | `https://mycompany.monday.com/boards/123/pulses/456` | `https?://([^.]+)\.monday\.com/boards/(\d+)/pulses/(\d+)` |
| Item URL with view | `https://mycompany.monday.com/boards/123/views/789/pulses/456` | `https?://([^.]+)\.monday\.com/boards/(\d+)/views/\d+/pulses/(\d+)` |

**Note:** Monday.com item IDs are numeric and require URL context (no standalone ID pattern).

**Normalized Ticket ID Format:** `{board_id}:{item_id}` (e.g., `123456:789012`)

#### Status Mapping

Monday.com status columns have customizable labels. Using keyword matching:

```python
STATUS_KEYWORDS: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType({
    TicketStatus.OPEN: ("", "not started", "new", "to do", "backlog"),
    TicketStatus.IN_PROGRESS: ("working on it", "in progress", "active", "started"),
    TicketStatus.REVIEW: ("review", "waiting for review", "pending", "awaiting"),
    TicketStatus.BLOCKED: ("stuck", "blocked", "on hold", "waiting"),
    TicketStatus.DONE: ("done", "complete", "completed", "closed", "finished"),
})
```

#### Type Mapping

Monday.com doesn't have native issue types. Type is inferred from labels/tags:

```python
TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType({
    TicketType.BUG: ("bug", "defect", "issue", "fix", "error", "crash"),
    TicketType.FEATURE: ("feature", "enhancement", "story", "user story", "new"),
    TicketType.TASK: ("task", "chore", "todo", "action item"),
    TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
})
```

#### Platform Metadata

| Metadata Field | API Field | Notes |
|----------------|-----------|-------|
| `board_id` | `board.id` | Board ID |
| `board_name` | `board.name` | Board name |
| `group_title` | `group.title` | Group (column) title |
| `creator_name` | `creator.name` | Item creator |
| `status_label` | Status column `text` | Original status text |
| `account_slug` | Extracted from URL | Monday.com subdomain |

#### No Agent-Mediated Fetch

Monday.com does **NOT** have Auggie MCP integration. `DirectAPIFetcher` is the only fetch path.

The `get_prompt_template()` method returns an empty string:

```python
def get_prompt_template(self) -> str:
    """Return empty string - agent-mediated fetch not supported.

    Monday.com does NOT have Auggie MCP integration.
    DirectAPIFetcher is the only fetch path.
    """
    return ""
```

---

## Provider 3: TrelloProvider

### File: `spec/integrations/providers/trello.py`

#### Input Patterns

| Pattern | Example | Regex |
|---------|---------|-------|
| Card URL (full) | `https://trello.com/c/abc123de/42-card-name` | `https?://trello\.com/c/([a-zA-Z0-9]+)` |
| Card URL (short) | `https://trello.com/c/abc123de` | Same regex |
| Short link only | `abc123de` | `^[a-zA-Z0-9]{8}$` |

**Note:** Trello short links are 8-character alphanumeric and globally unique.

**Normalized Ticket ID Format:** `{shortLink}` (e.g., `abc123de`)

#### Status Mapping

Trello uses list names as status indicators:

```python
LIST_STATUS_MAPPING: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType({
    TicketStatus.OPEN: ("to do", "backlog", "todo", "new", "inbox"),
    TicketStatus.IN_PROGRESS: ("in progress", "doing", "active", "working"),
    TicketStatus.REVIEW: ("review", "in review", "testing", "qa"),
    TicketStatus.BLOCKED: ("blocked", "on hold", "waiting"),
    TicketStatus.DONE: ("done", "complete", "completed", "closed", "archived"),
})
```

**Note:** Closed cards (`closed: true`) are mapped to `TicketStatus.CLOSED` regardless of list.

#### Type Mapping

Trello uses labels for categorization:

```python
TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType({
    TicketType.BUG: ("bug", "defect", "fix", "error", "issue"),
    TicketType.FEATURE: ("feature", "enhancement", "story", "new"),
    TicketType.TASK: ("task", "chore", "todo", "action"),
    TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
})
```

#### Platform Metadata

| Metadata Field | API Field | Notes |
|----------------|-----------|-------|
| `board_id` | `idBoard` | Board ID |
| `board_name` | `board.name` | Board name (if expanded) |
| `list_id` | `idList` | List ID |
| `list_name` | `list.name` | List name (status source) |
| `due_date` | `due` | Due date if set |
| `due_complete` | `dueComplete` | Due date completion status |
| `is_closed` | `closed` | Archived status |
| `short_link` | `shortLink` | 8-char short link |

#### Created Date Extraction

Trello card IDs are MongoDB ObjectIds. Creation timestamp is extracted:

```python
def _get_created_at(self, card_id: str) -> datetime:
    """Extract creation timestamp from card ID (ObjectId)."""
    try:
        timestamp_hex = card_id[:8]
        timestamp = int(timestamp_hex, 16)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (ValueError, IndexError):
        return datetime.now(tz=timezone.utc)
```

#### No Agent-Mediated Fetch

Trello does **NOT** have Auggie MCP integration. `DirectAPIFetcher` is the only fetch path.

The `get_prompt_template()` method returns an empty string:

```python
def get_prompt_template(self) -> str:
    """Return empty string - agent-mediated fetch not supported.

    Trello does NOT have Auggie MCP integration.
    DirectAPIFetcher is the only fetch path.
    """
    return ""
```

---

## Implementation Steps

### Step 1: Create AzureDevOpsProvider

**File:** `spec/integrations/providers/azure_devops.py`

```python
"""Azure DevOps work item provider.

This module provides the AzureDevOpsProvider class for integrating with Azure DevOps.
Following the hybrid architecture, this provider handles:
- Input parsing (dev.azure.com URLs, visualstudio.com URLs, AB#123 format)
- Data normalization (raw REST API JSON → GenericTicket)
- Status/type mapping to normalized enums

Data fetching is delegated to TicketFetcher implementations.
"""

from __future__ import annotations

import re
import warnings
from datetime import datetime
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
STATUS_MAPPING: MappingProxyType[str, TicketStatus] = MappingProxyType({
    "new": TicketStatus.OPEN,
    "to do": TicketStatus.OPEN,
    "active": TicketStatus.IN_PROGRESS,
    "in progress": TicketStatus.IN_PROGRESS,
    "committed": TicketStatus.IN_PROGRESS,
    "resolved": TicketStatus.REVIEW,
    "closed": TicketStatus.DONE,
    "done": TicketStatus.DONE,
    "removed": TicketStatus.CLOSED,
})

# Type mapping: Azure DevOps work item type → TicketType
TYPE_MAPPING: MappingProxyType[str, TicketType] = MappingProxyType({
    "bug": TicketType.BUG,
    "defect": TicketType.BUG,
    "impediment": TicketType.BUG,
    "issue": TicketType.BUG,
    "user story": TicketType.FEATURE,
    "feature": TicketType.FEATURE,
    "product backlog item": TicketType.FEATURE,
    "epic": TicketType.FEATURE,
    "requirement": TicketType.FEATURE,
    "task": TicketType.TASK,
    "spike": TicketType.TASK,
    "tech debt": TicketType.MAINTENANCE,
    "change request": TicketType.MAINTENANCE,
})


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper for Azure DevOps descriptions."""

    def __init__(self):
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
        import os
        self._default_org = default_org or os.environ.get("AZURE_DEVOPS_ORG", "")
        self._default_project = default_project or os.environ.get("AZURE_DEVOPS_PROJECT", "")

    @property
    def platform(self) -> Platform:
        return Platform.AZURE_DEVOPS

    @property
    def name(self) -> str:
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

    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        """Convert raw Azure DevOps API data to GenericTicket."""
        fields = raw_data.get("fields", {})

        # Extract work item ID
        work_item_id = str(raw_data.get("id", ""))
        if not work_item_id:
            raise ValueError("Cannot normalize Azure DevOps work item: 'id' field missing")

        # Extract org/project from URL if available
        url = raw_data.get("url", "")
        org, project = "", ""
        if url:
            match = self._DEV_AZURE_PATTERN.match(url)
            if match:
                org, project = match.group("org"), match.group("project")

        ticket_id = f"{org}/{project}#{work_item_id}" if org and project else work_item_id

        # Extract fields with defensive handling
        title = fields.get("System.Title", "")
        description_html = fields.get("System.Description", "") or ""
        description = strip_html(description_html)
        state = fields.get("System.State", "")
        work_item_type = fields.get("System.WorkItemType", "")

        # Assignee
        assigned_to = fields.get("System.AssignedTo", {})
        assignee = self.safe_nested_get(assigned_to, "displayName", "") or None

        # Tags (semicolon-separated)
        tags_str = fields.get("System.Tags", "") or ""
        labels = [t.strip() for t in tags_str.split(";") if t.strip()]

        # Timestamps
        created_at = self._parse_timestamp(fields.get("System.CreatedDate"))
        updated_at = self._parse_timestamp(fields.get("System.ChangedDate"))

        platform_metadata: PlatformMetadata = {
            "organization": org,
            "project": project,
            "work_item_type": work_item_type,
            "state_name": state,
            "area_path": fields.get("System.AreaPath", ""),
            "iteration_path": fields.get("System.IterationPath", ""),
            "assigned_to_email": self.safe_nested_get(assigned_to, "uniqueName", ""),
            "revision": raw_data.get("rev"),
        }

        # Construct browse URL
        browse_url = url
        if not browse_url and org and project:
            browse_url = f"https://dev.azure.com/{org}/{project}/_workitems/edit/{work_item_id}"

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

    def _map_status(self, state: str) -> TicketStatus:
        return STATUS_MAPPING.get(state.lower(), TicketStatus.UNKNOWN)

    def _map_type(self, work_item_type: str) -> TicketType:
        return TYPE_MAPPING.get(work_item_type.lower(), TicketType.UNKNOWN)

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        if not timestamp_str:
            return None
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Azure DevOps does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""
```

### Step 2: Create MondayProvider

**File:** `spec/integrations/providers/monday.py`

```python
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


STATUS_KEYWORDS: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType({
    TicketStatus.OPEN: ("", "not started", "new", "to do", "backlog"),
    TicketStatus.IN_PROGRESS: ("working on it", "in progress", "active", "started"),
    TicketStatus.REVIEW: ("review", "waiting for review", "pending", "awaiting"),
    TicketStatus.BLOCKED: ("stuck", "blocked", "on hold", "waiting"),
    TicketStatus.DONE: ("done", "complete", "completed", "closed", "finished"),
})

TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType({
    TicketType.BUG: ("bug", "defect", "issue", "fix", "error", "crash"),
    TicketType.FEATURE: ("feature", "enhancement", "story", "user story", "new"),
    TicketType.TASK: ("task", "chore", "todo", "action item"),
    TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
})

# Note: Monday.com does NOT have Auggie MCP support.
# DirectAPIFetcher is the ONLY fetch path for this platform.
# No STRUCTURED_PROMPT_TEMPLATE is defined.


@ProviderRegistry.register
class MondayProvider(IssueTrackerProvider):
    """Monday.com item provider."""

    PLATFORM = Platform.MONDAY

    _URL_PATTERN = re.compile(
        r"https?://(?P<slug>[^.]+)\.monday\.com/boards/(?P<board>\d+)(?:/views/\d+)?/pulses/(?P<item>\d+)",
        re.IGNORECASE,
    )

    def __init__(self, user_interaction: UserInteractionInterface | None = None) -> None:
        self._user_interaction = user_interaction or CLIUserInteraction()
        self._account_slug: str | None = None

    @property
    def platform(self) -> Platform:
        return Platform.MONDAY

    @property
    def name(self) -> str:
        return "Monday.com"

    def can_handle(self, input_str: str) -> bool:
        return bool(self._URL_PATTERN.match(input_str.strip()))

    def parse_input(self, input_str: str) -> str:
        match = self._URL_PATTERN.match(input_str.strip())
        if match:
            self._account_slug = match.group("slug")
            return f"{match.group('board')}:{match.group('item')}"
        raise ValueError(f"Cannot parse Monday.com item from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
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

    def _find_column_text(self, columns: list, col_type: str) -> str:
        for col in columns:
            if isinstance(col, dict) and col.get("type") == col_type:
                return col.get("text", "")
        return ""

    def _extract_description(self, item: dict, columns: list) -> str:
        """Extract description using cascading fallback strategy."""
        for col in columns:
            if isinstance(col, dict):
                col_type = col.get("type", "")
                col_title = col.get("title", "").lower()
                if col_type in ["text", "long_text"] and "desc" in col_title:
                    text = col.get("text", "").strip()
                    if text:
                        return text
        updates = item.get("updates", [])
        if updates and isinstance(updates, list):
            oldest = updates[-1] if updates else {}
            return oldest.get("text_body", "") or oldest.get("body", "")
        return ""

    def _map_status(self, label: str) -> TicketStatus:
        label_lower = label.lower().strip()
        for status, keywords in STATUS_KEYWORDS.items():
            if label_lower in keywords:
                return status
        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type
        return TicketType.UNKNOWN

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
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
```

### Step 3: Create TrelloProvider

**File:** `spec/integrations/providers/trello.py`

```python
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


LIST_STATUS_MAPPING: MappingProxyType[TicketStatus, tuple[str, ...]] = MappingProxyType({
    TicketStatus.OPEN: ("to do", "backlog", "todo", "new", "inbox"),
    TicketStatus.IN_PROGRESS: ("in progress", "doing", "active", "working"),
    TicketStatus.REVIEW: ("review", "in review", "testing", "qa"),
    TicketStatus.BLOCKED: ("blocked", "on hold", "waiting"),
    TicketStatus.DONE: ("done", "complete", "completed", "closed", "archived"),
})

TYPE_KEYWORDS: MappingProxyType[TicketType, tuple[str, ...]] = MappingProxyType({
    TicketType.BUG: ("bug", "defect", "fix", "error", "issue"),
    TicketType.FEATURE: ("feature", "enhancement", "story", "new"),
    TicketType.TASK: ("task", "chore", "todo", "action"),
    TicketType.MAINTENANCE: ("maintenance", "tech debt", "refactor", "cleanup", "infra"),
})

# Note: Trello does NOT have Auggie MCP support.
# DirectAPIFetcher is the ONLY fetch path for this platform.
# No STRUCTURED_PROMPT_TEMPLATE is defined.


@ProviderRegistry.register
class TrelloProvider(IssueTrackerProvider):
    """Trello card provider."""

    PLATFORM = Platform.TRELLO

    _URL_PATTERN = re.compile(
        r"https?://trello\.com/c/(?P<short_link>[a-zA-Z0-9]+)",
        re.IGNORECASE,
    )
    _SHORT_LINK_PATTERN = re.compile(r"^[a-zA-Z0-9]{8}$")

    def __init__(self, user_interaction: UserInteractionInterface | None = None) -> None:
        self._user_interaction = user_interaction or CLIUserInteraction()

    @property
    def platform(self) -> Platform:
        return Platform.TRELLO

    @property
    def name(self) -> str:
        return "Trello"

    def can_handle(self, input_str: str) -> bool:
        input_str = input_str.strip()
        if self._URL_PATTERN.match(input_str):
            return True
        if self._SHORT_LINK_PATTERN.match(input_str):
            return True
        return False

    def parse_input(self, input_str: str) -> str:
        input_str = input_str.strip()
        match = self._URL_PATTERN.match(input_str)
        if match:
            return match.group("short_link")
        if self._SHORT_LINK_PATTERN.match(input_str):
            return input_str
        raise ValueError(f"Cannot parse Trello card from input: {input_str}")

    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        short_link = raw_data.get("shortLink", "")
        card_id = raw_data.get("id", "")
        ticket_id = short_link or card_id
        if not ticket_id:
            raise ValueError("Cannot normalize Trello card: 'id' and 'shortLink' missing")

        list_info = raw_data.get("list", {})
        list_name = self.safe_nested_get(list_info, "name", "")
        status = self._map_list_to_status(list_name)

        if raw_data.get("closed"):
            status = TicketStatus.CLOSED

        members = raw_data.get("members", [])
        assignee = members[0].get("fullName") if members else None

        labels_raw = raw_data.get("labels", [])
        labels = [l.get("name") for l in labels_raw if isinstance(l, dict) and l.get("name")]

        board = raw_data.get("board", {})
        created_at = self._get_created_at(card_id)
        updated_at = self._parse_timestamp(raw_data.get("dateLastActivity"))

        platform_metadata: PlatformMetadata = {
            "board_id": raw_data.get("idBoard"),
            "board_name": self.safe_nested_get(board, "name", ""),
            "list_id": raw_data.get("idList"),
            "list_name": list_name,
            "due_date": raw_data.get("due"),
            "due_complete": raw_data.get("dueComplete"),
            "is_closed": raw_data.get("closed", False),
            "short_link": short_link,
        }

        return GenericTicket(
            id=ticket_id,
            platform=Platform.TRELLO,
            url=raw_data.get("url") or raw_data.get("shortUrl", ""),
            title=raw_data.get("name", ""),
            description=raw_data.get("desc", ""),
            status=status,
            type=self._map_type(labels),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(raw_data.get("name", "")),
            platform_metadata=platform_metadata,
        )

    def _map_list_to_status(self, list_name: str) -> TicketStatus:
        name_lower = list_name.lower().strip()
        for status, keywords in LIST_STATUS_MAPPING.items():
            if name_lower in keywords:
                return status
        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        for label in labels:
            label_lower = label.lower().strip()
            for ticket_type, keywords in TYPE_KEYWORDS.items():
                if any(kw in label_lower for kw in keywords):
                    return ticket_type
        return TicketType.UNKNOWN

    def _get_created_at(self, card_id: str) -> datetime:
        """Extract creation timestamp from card ID (MongoDB ObjectId)."""
        try:
            timestamp_hex = card_id[:8]
            timestamp = int(timestamp_hex, 16)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, IndexError):
            return datetime.now(tz=timezone.utc)

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        if not timestamp_str:
            return None
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def get_prompt_template(self) -> str:
        """Return empty string - agent-mediated fetch not supported.

        Trello does NOT have Auggie MCP integration.
        DirectAPIFetcher is the only fetch path.
        """
        return ""
```

### Step 4: Update Package Exports

**File:** `spec/integrations/providers/__init__.py`

```python
# Add to existing imports
from spec.integrations.providers.azure_devops import AzureDevOpsProvider
from spec.integrations.providers.monday import MondayProvider
from spec.integrations.providers.trello import TrelloProvider

# Add to __all__
__all__ = [
    # ... existing exports
    "AzureDevOpsProvider",
    "MondayProvider",
    "TrelloProvider",
]
```

---

## Testing Strategy

### Unit Tests Structure

Each provider follows the same test structure as JiraProvider (AMI-18) and LinearProvider (AMI-20):

| Test Class | Coverage |
|------------|----------|
| `TestProviderRegistration` | PLATFORM attribute, decorator registration, singleton |
| `TestProviderCanHandle` | Valid/invalid URL patterns |
| `TestProviderParseInput` | URL parsing, ID normalization |
| `TestProviderNormalize` | Full response, minimal response, platform metadata |
| `TestDefensiveFieldHandling` | None values, malformed responses |
| `TestStatusMapping` | All status mappings |
| `TestTypeMapping` | All type mappings |
| `TestPromptTemplate` | Returns empty string (no Auggie MCP support) |
| `TestFetchTicketDeprecation` | DeprecationWarning + NotImplementedError |

### Test Isolation Pattern

```python
import pytest
from spec.integrations.providers.registry import ProviderRegistry

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()
```

### Example Test: AzureDevOpsProvider

```python
"""Tests for AzureDevOpsProvider."""

import pytest
from spec.integrations.providers.base import Platform, TicketStatus, TicketType
from spec.integrations.providers.azure_devops import AzureDevOpsProvider


class TestAzureDevOpsCanHandle:
    @pytest.fixture
    def provider(self):
        return AzureDevOpsProvider()

    @pytest.mark.parametrize("url", [
        "https://dev.azure.com/myorg/MyProject/_workitems/edit/42",
        "https://contoso.visualstudio.com/Backend/_workitems/edit/123",
    ])
    def test_can_handle_valid_urls(self, provider, url):
        assert provider.can_handle(url) is True

    def test_can_handle_ab_format(self, provider):
        assert provider.can_handle("AB#42") is True

    def test_cannot_handle_github(self, provider):
        assert provider.can_handle("https://github.com/owner/repo/issues/1") is False


class TestAzureDevOpsNormalize:
    @pytest.fixture
    def provider(self):
        return AzureDevOpsProvider()

    @pytest.fixture
    def sample_response(self):
        return {
            "id": 42,
            "rev": 5,
            "url": "https://dev.azure.com/contoso/Backend/_workitems/edit/42",
            "fields": {
                "System.Title": "Fix login bug",
                "System.Description": "<p>Description here</p>",
                "System.State": "Active",
                "System.WorkItemType": "Bug",
                "System.AssignedTo": {
                    "displayName": "Jane Developer",
                    "uniqueName": "jane@contoso.com"
                },
                "System.Tags": "backend; security",
                "System.AreaPath": "Backend\\Auth",
                "System.IterationPath": "Sprint 5",
                "System.CreatedDate": "2024-01-15T10:30:00Z",
                "System.ChangedDate": "2024-01-18T14:20:00Z"
            }
        }

    def test_normalize_full_response(self, provider, sample_response):
        ticket = provider.normalize(sample_response)
        assert ticket.id == "contoso/Backend#42"
        assert ticket.platform == Platform.AZURE_DEVOPS
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.type == TicketType.BUG
        assert ticket.assignee == "Jane Developer"
        assert "backend" in ticket.labels
```

### Coverage Target

- **Unit tests:** >90% line coverage for each provider
- **Test files:**
  - `tests/test_azure_devops_provider.py`
  - `tests/test_monday_provider.py`
  - `tests/test_trello_provider.py`

---

## Integration Points

### TicketService (AMI-32)

```python
class TicketService:
    async def get_ticket(self, input_str: str) -> GenericTicket:
        # 1. Detect platform and get provider
        provider = self._registry.get_provider_for_input(input_str)

        # 2. Parse input to get normalized ID
        ticket_id = provider.parse_input(input_str)

        # 3. Fetch raw data via DirectAPIFetcher (primary for these platforms)
        raw_data = await self._fetcher.fetch(ticket_id, provider)

        # 4. Normalize using provider
        return provider.normalize(raw_data)
```

### DirectAPIFetcher (AMI-31)

Primary fetch path for Azure DevOps, Monday, and Trello:

```python
class DirectAPIFetcher(TicketFetcher):
    async def fetch(self, ticket_id: str, provider: IssueTrackerProvider) -> dict:
        # Dispatch to platform-specific handler (already implemented in AMI-31)
        handler = self._handlers.get(provider.platform)
        return await handler.fetch(ticket_id)
```

### ProviderRegistry (AMI-17)

```python
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get providers via registry
azure_provider = ProviderRegistry.get_provider(Platform.AZURE_DEVOPS)
monday_provider = ProviderRegistry.get_provider(Platform.MONDAY)
trello_provider = ProviderRegistry.get_provider(Platform.TRELLO)

# Or detect from input
provider = ProviderRegistry.get_provider_for_input(
    "https://dev.azure.com/myorg/MyProject/_workitems/edit/42"
)
```

---

## Dependencies

### Required (Must Be Complete)

| Dependency | Ticket | Status |
|------------|--------|--------|
| `PlatformDetector` | AMI-16 | ✅ Complete |
| `ProviderRegistry` | AMI-17 | ✅ Complete |
| `IssueTrackerProvider` ABC | AMI-17 | ✅ Complete |
| `Platform` enum (AZURE_DEVOPS, MONDAY, TRELLO) | AMI-17 | ✅ Complete |
| `GenericTicket` dataclass | AMI-17 | ✅ Complete |
| `UserInteractionInterface` | AMI-17 | ✅ Complete |
| `DirectAPIFetcher` handlers | AMI-31 | ✅ Complete |

### Future Integration

| Integration Point | Ticket | Relationship |
|-------------------|--------|--------------|
| `TicketService` | AMI-32 | Orchestrates provider + fetcher |
| `TicketFetcher` abstraction | AMI-29 | Base class for fetcher implementations |

---

## No Auggie MCP Support

These three platforms do NOT have Auggie MCP integration:
- `AuggieMediatedFetcher` is NOT available for these platforms
- `DirectAPIFetcher` is the **ONLY** fetch path
- `get_prompt_template()` returns empty string for all three providers

---

## Acceptance Criteria Checklist

From Linear ticket AMI-21:

### AzureDevOpsProvider
- [ ] Extends IssueTrackerProvider ABC
- [ ] Registers with ProviderRegistry using @register decorator
- [ ] PLATFORM class attribute set to Platform.AZURE_DEVOPS
- [ ] `can_handle()` - recognizes dev.azure.com, visualstudio.com URLs, AB# format
- [ ] `parse_input()` - extracts normalized ticket ID (org/project#id)
- [ ] `normalize()` - converts Azure DevOps REST JSON to GenericTicket
- [ ] `get_prompt_template()` - returns empty string (no Auggie MCP support)
- [ ] STATUS_MAPPING covers common Azure DevOps states
- [ ] TYPE_MAPPING covers common work item types
- [ ] HTML description stripping implemented
- [ ] Unit tests with >90% coverage

### MondayProvider
- [ ] Extends IssueTrackerProvider ABC
- [ ] Registers with ProviderRegistry using @register decorator
- [ ] PLATFORM class attribute set to Platform.MONDAY
- [ ] `can_handle()` - recognizes monday.com board/pulse URLs
- [ ] `parse_input()` - extracts board_id:item_id format
- [ ] `normalize()` - converts Monday.com GraphQL JSON to GenericTicket
- [ ] `get_prompt_template()` - returns empty string (no Auggie MCP support)
- [ ] STATUS_KEYWORDS maps customizable status labels
- [ ] TYPE_KEYWORDS infers type from labels
- [ ] Description extraction with cascading fallback
- [ ] Unit tests with >90% coverage

### TrelloProvider
- [ ] Extends IssueTrackerProvider ABC
- [ ] Registers with ProviderRegistry using @register decorator
- [ ] PLATFORM class attribute set to Platform.TRELLO
- [ ] `can_handle()` - recognizes trello.com card URLs, short links
- [ ] `parse_input()` - extracts short link
- [ ] `normalize()` - converts Trello REST JSON to GenericTicket
- [ ] `get_prompt_template()` - returns empty string (no Auggie MCP support)
- [ ] LIST_STATUS_MAPPING maps list names to statuses
- [ ] TYPE_KEYWORDS infers type from labels
- [ ] Created date extraction from ObjectId
- [ ] Closed cards map to CLOSED status
- [ ] Unit tests with >90% coverage

### General
- [ ] All three providers exported from `spec/integrations/providers/__init__.py`
- [ ] No direct HTTP calls in provider classes
- [ ] Documentation in docstrings
- [ ] Defensive field handling with `safe_nested_get()`

---

## Example Usage

### AzureDevOpsProvider

```python
from spec.integrations.providers.azure_devops import AzureDevOpsProvider
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get provider via registry
provider = ProviderRegistry.get_provider(Platform.AZURE_DEVOPS)

# Check if input is handled
if provider.can_handle("https://dev.azure.com/contoso/Backend/_workitems/edit/42"):
    ticket_id = provider.parse_input("https://dev.azure.com/contoso/Backend/_workitems/edit/42")
    print(f"Parsed: {ticket_id}")  # contoso/Backend#42
```

### MondayProvider

```python
from spec.integrations.providers.monday import MondayProvider

provider = MondayProvider()

# Parse Monday.com URL
ticket_id = provider.parse_input(
    "https://mycompany.monday.com/boards/123456/pulses/789012"
)
print(f"Parsed: {ticket_id}")  # 123456:789012
```

### TrelloProvider

```python
from spec.integrations.providers.trello import TrelloProvider

provider = TrelloProvider()

# Parse Trello URL
ticket_id = provider.parse_input("https://trello.com/c/abc123de/42-my-card")
print(f"Parsed: {ticket_id}")  # abc123de

# Normalize raw API response
raw_data = {
    "id": "507f1f77bcf86cd799439011",
    "shortLink": "abc123de",
    "name": "Fix login bug",
    "list": {"name": "In Progress"},
    "labels": [{"name": "bug"}],
    # ...
}
ticket = provider.normalize(raw_data)
print(f"Status: {ticket.status}")  # TicketStatus.IN_PROGRESS
print(f"Type: {ticket.type}")  # TicketType.BUG
```

---

## References

- [Azure DevOps Integration Spec](specs/03_Integration_AzureDevOps_Spec.md)
- [Monday.com Integration Spec](specs/04_Integration_Monday_Spec.md)
- [Trello Integration Spec](specs/05_Integration_Trello_Spec.md)
- [Architecture Spec - Section 6: Provider Registry](specs/00_Architecture_Refactor_Spec.md#6-provider-registry--factory-pattern)
- [AMI-17 Implementation Plan](specs/AMI-17-implementation-plan.md) - ProviderRegistry pattern
- [AMI-18 Implementation Plan](specs/AMI-18-implementation-plan.md) - JiraProvider reference
- [AMI-19 Implementation Plan](specs/AMI-19-implementation-plan.md) - GitHubProvider reference
- [AMI-20 Implementation Plan](specs/AMI-20-implementation-plan.md) - LinearProvider reference
- [AMI-31 Implementation Plan](specs/AMI-31-implementation-plan.md) - DirectAPIFetcher handlers

---

## Implementation Notes

> **Alignment with Linear Ticket:** This implementation plan addresses all requirements from AMI-21:
>
> 1. **Reference Patterns from JiraProvider (PR #26):**
>    - Defensive field handling with `safe_nested_get()` used throughout
>    - Test structure with `reset_registry` fixture
>    - Labels/tags normalization to list of strings
>
> 2. **AMI-31 Scope Clarification:**
>    - API handlers are already implemented in AMI-31
>    - This ticket focuses only on `IssueTrackerProvider` implementations
>    - DirectAPIFetcher is the primary fetch path (no Auggie MCP)
>
> 3. **AMI-17 Alignment Verification:**
>    - `@ProviderRegistry.register` decorator pattern used
>    - `PLATFORM` class attribute defined for each provider
>    - Constructor accepts optional `user_interaction` for DI
>
> 4. **Platform-Specific Considerations:**
>    - **Azure DevOps:** HTML description stripping, process-agnostic status mapping
>    - **Monday.com:** Column-based data extraction, description cascading fallback
>    - **Trello:** List-based status, ObjectId timestamp extraction, closed card handling
>
> 5. **No Agent-Mediated Fetch:**
>    - These platforms do NOT have Auggie MCP support
>    - DirectAPIFetcher is the ONLY fetch path
>    - `get_prompt_template()` returns empty string



---

## ✅ Implementation Summary (PR #30)

**PR:** [#30 - feat(AMI-21): Add AzureDevOps, Monday, and Trello providers](https://github.com/Amiad5298/Spec/pull/30)
**State:** Open (ready for merge)
**Commits:** 7
**Lines Changed:** +2,130 / -3

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `spec/integrations/providers/azure_devops.py` | 349 | AzureDevOpsProvider implementation |
| `spec/integrations/providers/monday.py` | 289 | MondayProvider implementation |
| `spec/integrations/providers/trello.py` | 260 | TrelloProvider implementation |
| `tests/test_azure_devops_provider.py` | 400 | 50+ tests for AzureDevOpsProvider |
| `tests/test_monday_provider.py` | 333 | 40+ tests for MondayProvider |
| `tests/test_trello_provider.py` | 404 | 50+ tests for TrelloProvider |

### Files Modified

| File | Changes | Purpose |
|------|---------|---------|
| `spec/integrations/providers/__init__.py` | +6 | Export new providers |
| `spec/integrations/providers/base.py` | +83 | Add `normalize()` ABC, `parse_timestamp()`, PlatformMetadata fields |
| `spec/integrations/providers/github.py` | +2/-1 | Add `ticket_id` param to `normalize()` |
| `spec/integrations/providers/jira.py` | +2/-1 | Add `ticket_id` param to `normalize()` |
| `spec/integrations/providers/linear.py` | +2/-1 | Add `ticket_id` param to `normalize()` |

### Key Implementation Details

1. **All providers use `@ProviderRegistry.register` decorator** - Consistent with AMI-17 pattern
2. **`normalize()` is now an ABC method** - Added to `IssueTrackerProvider` base class
3. **`ticket_id` optional param** - Added to all `normalize()` methods for Singleton-safe context passing
4. **`parse_timestamp()` utility** - Added to base class as shared utility
5. **126 total tests passing** - 92-98% coverage per provider
6. **No direct HTTP calls** - Fetching delegated to DirectAPIFetcher (AMI-31)

### Deviations from Plan

1. **`normalize()` signature enhanced**: Added optional `ticket_id: str | None = None` param to avoid storing request-specific state in Singleton providers (affects MondayProvider URL construction)
2. **`_safe_get_dict()` helper added**: AzureDevOpsProvider adds a helper for safely extracting nested dict values
3. **`_get_created_at()` returns None on error**: TrelloProvider returns `None` instead of `datetime.now()` for invalid ObjectIds (more accurate)
4. **PlatformMetadata expanded**: Added 20+ new fields across all three platforms

### Test Coverage

- **AzureDevOpsProvider:** 50+ tests, 98% coverage
- **MondayProvider:** 40+ tests, 92% coverage
- **TrelloProvider:** 50+ tests, 96% coverage

### Acceptance Criteria Status

- [x] All three providers implement updated `IssueTrackerProvider` interface
- [x] All registered with `@ProviderRegistry.register` decorator
- [x] Each provider has comprehensive URL/ID pattern matching in `can_handle()`
- [x] Each provider has `normalize()` method for JSON → GenericTicket
- [x] Each provider maps platform statuses to `TicketStatus` enum
- [x] Each provider maps work item types to `TicketType` enum
- [x] Each provider populates relevant `platform_metadata` fields
- [x] Each provider has `get_prompt_template()` returning empty string (no Auggie MCP)
- [x] Unit tests for each provider with sample JSON responses
- [x] No direct HTTP calls in any provider class
