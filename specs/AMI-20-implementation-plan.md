# Implementation Plan: AMI-20 - Implement LinearProvider Concrete Class

**Ticket:** [AMI-20](https://linear.app/amiadspec/issue/AMI-20/implement-linearprovider-concrete-class)
**Status:** ✅ Implemented (PR #28)
**Date:** 2026-01-25

---

## Summary

This ticket implements the `LinearProvider` concrete class that extends `IssueTrackerProvider` for Linear integration. Following the hybrid ticket fetching architecture, this provider focuses on **input parsing and data normalization**, not direct API calls. The actual data fetching is delegated to `TicketFetcher` implementations (`AuggieMediatedFetcher` as primary, `DirectAPIFetcher` as fallback).

The provider is responsible for:
1. **Input parsing** - Recognizing Linear URLs and `TEAM-123` format IDs
2. **Data normalization** - Converting raw Linear GraphQL/agent responses to `GenericTicket`
3. **Status/type mapping** - Mapping Linear-specific workflow states and labels to normalized enums
4. **Structured prompt templates** - Providing Linear-specific prompts for agent-mediated fetching

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TicketFetcher (AMI-29/30/31)      │  Handles HOW to get data               │
│  • AuggieMediatedFetcher (primary) │  • Structured prompt → raw JSON        │
│  • DirectAPIFetcher (fallback)     │  • GraphQL API → raw JSON              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ raw JSON data
┌─────────────────────────────────────────────────────────────────────────────┐
│  LinearProvider (THIS TICKET)      │  Handles WHAT the data means           │
│  • can_handle()                    │  • URL/ID pattern matching             │
│  • parse_input()                   │  • URL/ID → normalized ticket ID       │
│  • normalize()                     │  • raw JSON → GenericTicket            │
│  • get_prompt_template()           │  • Linear-specific prompt for agent    │
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
3. **State Type Mapping** - Uses `state.type` (not `state.name`) for reliable status mapping across teams
4. **Label-Based Type Inference** - Linear uses labels for categorization; type is inferred from keywords
5. **GraphQL Response Structure** - Normalizes nested GraphQL response format (e.g., `labels.nodes[]`)
6. **Optional DI** - Constructor accepts optional `user_interaction` for testing
7. **ID Disambiguation Note** - `TEAM-123` format is ambiguous with Jira; provider handles inputs AFTER platform is determined

---

## Components to Create

### New File: `spec/integrations/providers/linear.py`

| Component | Purpose |
|-----------|---------|
| `LinearProvider` class | Concrete provider for Linear platform |
| `STATUS_MAPPING` dict | Maps Linear state types to `TicketStatus` |
| `TYPE_KEYWORDS` dict | Keywords for inferring `TicketType` from labels |
| `STRUCTURED_PROMPT_TEMPLATE` str | Linear-specific prompt for agent-mediated fetching |

### Modified Files

| File | Changes |
|------|---------|
| `spec/integrations/providers/__init__.py` | Export `LinearProvider` |

### ABC Extension Note

> **Important:** The `normalize()` and `get_prompt_template()` methods are **not** currently part of the `IssueTrackerProvider` ABC. They are provider-specific extensions required by the hybrid architecture's `TicketFetcher` integration pattern:
> - `normalize()` - Called by `DirectAPIFetcher` and `AuggieMediatedFetcher` to convert raw JSON to `GenericTicket`
> - `get_prompt_template()` - Called by `AuggieMediatedFetcher` to get platform-specific structured prompts
>
> These methods are intentionally not part of the ABC to maintain backward compatibility and allow the hybrid architecture to be adopted gradually without breaking existing providers. They may be added to the ABC in a future refactor once all providers have been migrated to the hybrid pattern.

### Defensive Field Handling

> **Pattern:** This implementation uses the `safe_nested_get()` static method from the base class for all nested dictionary access. This protects against malformed API responses where nested objects may be `None` or non-dict types:
>
> ```python
> # Defensive pattern used throughout normalize():
> state_obj = raw_data.get("state")
> state_type = self.safe_nested_get(state_obj, "type", "")
> state_name = self.safe_nested_get(state_obj, "name", "")
> ```
>
> This pattern is consistent with the JiraProvider implementation (PR #26) and uses the base class utility method defined in `spec/integrations/providers/base.py`.

---

## Implementation Steps

### Step 1: Create LinearProvider Module

**File:** `spec/integrations/providers/linear.py`

```python
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
```

### Step 2: Add Type Keywords and Prompt Template

Continue in `spec/integrations/providers/linear.py`:

```python
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
```

### Step 3: Add LinearProvider Class Definition

```python
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

    # Unified URL pattern for Linear (handles with/without title slug)
    # Pattern breakdown:
    # - https?://linear\.app/ - Linear base URL
    # - (?P<org>[^/]+) - organization/workspace slug
    # - /issue/ - literal path
    # - (?P<ticket_id>[A-Z][A-Z0-9]*-\d+) - ticket ID with alphanumeric team key (ENG-123, G2-42, A1-1)
    # - (?:/[^/]*)? - optional title slug
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
        - Ticket IDs: TEAM-123 format (alphanumeric team key, case-insensitive)

        Note: TEAM-123 format is ambiguous with Jira. The PlatformDetector
        handles disambiguation; this method reports if the format is compatible.

        Uses fullmatch() for strict matching to prevent partial matches like
        "ENG-123abc" or "AMI-18-implement-feature" from being accepted.

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
```

### Step 4: Add normalize() Method

```python
    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        """Convert raw Linear GraphQL data to GenericTicket.

        Handles nested GraphQL response structure (e.g., labels.nodes[]).
        Uses safe_nested_get() for defensive field handling of malformed responses.

        Args:
            raw_data: Raw Linear GraphQL response (issue object)

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
        assignee = self.safe_nested_get(assignee_obj, "name", "") or self.safe_nested_get(assignee_obj, "email", "") or None

        # Extract labels from nested GraphQL structure
        # Use safe_nested_get() for defensive handling
        labels_nodes = raw_data.get("labels", {}).get("nodes", [])
        labels = [
            self.safe_nested_get(label, "name", "").strip()
            for label in labels_nodes
            if isinstance(label, dict)
        ]
        labels = [l for l in labels if l]  # Filter empty strings

        # Get URL (directly from response)
        url = raw_data.get("url", "")

        # Build team key for metadata
        # Use safe_nested_get() for defensive handling
        team_obj = raw_data.get("team")
        team_key = self.safe_nested_get(team_obj, "key", "")
        team_name = self.safe_nested_get(team_obj, "name", "")

        # Extract platform-specific metadata
        # Use safe_nested_get() for defensive handling of nested fields
        cycle_obj = raw_data.get("cycle")
        cycle_name = self.safe_nested_get(cycle_obj, "name", "") or None

        parent_obj = raw_data.get("parent")
        parent_id = self.safe_nested_get(parent_obj, "identifier", "") or None

        platform_metadata: PlatformMetadata = {
            "raw_response": raw_data,
            "linear_uuid": raw_data.get("id", ""),
            "team_key": team_key,
            "team_name": team_name,
            "priority": raw_data.get("priorityLabel", ""),
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
            description=raw_data.get("description", "") or "",
            status=self._map_status(state_type, state_name),
            type=self._map_type(labels),
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            branch_summary=sanitize_title_for_branch(raw_data.get("title", "")),
            platform_metadata=platform_metadata,
        )

    def _map_status(self, state_type: str, state_name: str) -> TicketStatus:
        """Map Linear state to TicketStatus enum.

        Prefers state.type (reliable) over state.name (customizable).

        Args:
            state_type: Linear state type (e.g., "started")
            state_name: Linear state name (e.g., "In Progress")

        Returns:
            Normalized TicketStatus, UNKNOWN if not recognized
        """
        # Prefer state.type for reliable mapping
        if state_type:
            status = STATUS_MAPPING.get(state_type.lower())
            if status:
                return status

        # Fall back to state.name for custom workflows
        if state_name:
            status = STATE_NAME_MAPPING.get(state_name.lower())
            if status:
                return status

        return TicketStatus.UNKNOWN

    def _map_type(self, labels: list[str]) -> TicketType:
        """Map Linear labels to TicketType enum.

        Linear uses labels for categorization. Infer type from keywords.

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

        # Return UNKNOWN if no type-specific labels found
        # (Linear uses labels for categorization, so missing labels = unknown type)
        return TicketType.UNKNOWN

    def _parse_timestamp(self, timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from Linear GraphQL API.

        Args:
            timestamp_str: ISO format timestamp string (e.g., "2024-01-15T10:30:00.000Z")

        Returns:
            datetime object or None if parsing fails
        """
        if not timestamp_str:
            return None
        try:
            # Linear uses ISO format with Z suffix: 2024-01-15T10:30:00.000Z
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
```

### Step 5: Add Remaining Methods

```python
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

        NOTE: Connection checking is delegated to TicketFetcher implementations
        in the hybrid architecture.

        Returns:
            Tuple of (success: bool, message: str)
        """
        # In hybrid architecture, connection check is done by TicketService
        # This method returns True as the provider itself doesn't manage connections
        return (True, "LinearProvider ready - use TicketService for connection verification")
```

### Step 6: Update Package Exports

**File:** `spec/integrations/providers/__init__.py`

```python
# Add to existing imports
from spec.integrations.providers.linear import LinearProvider

# Add to __all__
__all__ = [
    # ... existing exports
    "LinearProvider",
]
```

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_linear_provider.py`

```python
"""Tests for LinearProvider."""

import pytest
from datetime import datetime

from spec.integrations.providers.base import (
    GenericTicket,
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.linear import (
    LinearProvider,
    STATUS_MAPPING,
    STATE_NAME_MAPPING,
    TYPE_KEYWORDS,
)
from spec.integrations.providers.registry import ProviderRegistry


class TestLinearProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        ProviderRegistry.clear()
        yield
        ProviderRegistry.clear()

    def test_provider_has_platform_attribute(self):
        """LinearProvider has required PLATFORM class attribute."""
        assert hasattr(LinearProvider, "PLATFORM")
        assert LinearProvider.PLATFORM == Platform.LINEAR

    def test_provider_registers_successfully(self):
        """LinearProvider can be registered with ProviderRegistry."""
        # Import triggers registration due to decorator
        from spec.integrations.providers.linear import LinearProvider

        provider = ProviderRegistry.get_provider(Platform.LINEAR)
        assert provider is not None
        assert isinstance(provider, LinearProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        provider1 = ProviderRegistry.get_provider(Platform.LINEAR)
        provider2 = ProviderRegistry.get_provider(Platform.LINEAR)
        assert provider1 is provider2


class TestLinearProviderCanHandle:
    """Test can_handle() method."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    # Valid URLs
    @pytest.mark.parametrize("url", [
        "https://linear.app/myteam/issue/ENG-123",
        "https://linear.app/company/issue/DESIGN-456",
        "https://linear.app/team/issue/ABC-1",
        "https://linear.app/team/issue/ENG-123/implement-feature",
        "https://linear.app/team/issue/ENG-123/some-title-slug",
        "http://linear.app/team/issue/TEST-99",  # http also works
    ])
    def test_can_handle_valid_urls(self, provider, url):
        assert provider.can_handle(url) is True

    # Valid IDs (TEAM-123 format)
    @pytest.mark.parametrize("ticket_id", [
        "ENG-123",
        "DESIGN-456",
        "ABC-1",
        "XYZ-99999",
        "eng-123",  # lowercase
        "A1-1",     # alphanumeric team
    ])
    def test_can_handle_valid_ids(self, provider, ticket_id):
        assert provider.can_handle(ticket_id) is True

    # Invalid inputs
    @pytest.mark.parametrize("input_str", [
        "https://github.com/owner/repo/issues/123",
        "https://company.atlassian.net/browse/PROJ-123",
        "owner/repo#123",
        "AMI-18-implement-feature",  # Not just ticket ID
        "PROJECT",                   # No number
        "",                          # Empty
        "abc",                       # Letters only, no dash
        "123",                       # Numeric only (not supported for Linear)
    ])
    def test_can_handle_invalid_inputs(self, provider, input_str):
        assert provider.can_handle(input_str) is False


class TestLinearProviderParseInput:
    """Test parse_input() method."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    def test_parse_linear_url(self, provider):
        url = "https://linear.app/myteam/issue/ENG-123"
        assert provider.parse_input(url) == "ENG-123"

    def test_parse_linear_url_with_title(self, provider):
        url = "https://linear.app/team/issue/DESIGN-456/implement-new-feature"
        assert provider.parse_input(url) == "DESIGN-456"

    def test_parse_lowercase_id(self, provider):
        assert provider.parse_input("eng-123") == "ENG-123"

    def test_parse_with_whitespace(self, provider):
        assert provider.parse_input("  ENG-123  ") == "ENG-123"

    def test_parse_invalid_raises_valueerror(self, provider):
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("not-a-ticket")

    def test_parse_numeric_only_raises_valueerror(self, provider):
        """Linear doesn't support numeric-only IDs (unlike Jira)."""
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("123")


class TestLinearProviderNormalize:
    """Test normalize() method."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    @pytest.fixture
    def sample_linear_response(self):
        return {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "identifier": "ENG-123",
            "title": "Implement user authentication",
            "description": "Add OAuth2 login flow with Google and GitHub providers.",
            "url": "https://linear.app/myteam/issue/ENG-123",
            "state": {
                "name": "In Progress",
                "type": "started",
            },
            "assignee": {
                "name": "Jane Developer",
                "email": "jane@company.com",
            },
            "labels": {
                "nodes": [
                    {"name": "feature"},
                    {"name": "backend"},
                ],
            },
            "createdAt": "2024-01-15T10:30:00.000Z",
            "updatedAt": "2024-01-18T14:20:00.000Z",
            "priority": 2,
            "priorityLabel": "High",
            "team": {
                "key": "ENG",
                "name": "Engineering",
            },
            "cycle": {
                "name": "Sprint 42",
            },
            "parent": None,
        }

    def test_normalize_full_response(self, provider, sample_linear_response):
        ticket = provider.normalize(sample_linear_response)

        assert ticket.id == "ENG-123"
        assert ticket.platform == Platform.LINEAR
        assert ticket.url == "https://linear.app/myteam/issue/ENG-123"
        assert ticket.title == "Implement user authentication"
        assert ticket.description == "Add OAuth2 login flow with Google and GitHub providers."
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.type == TicketType.FEATURE
        assert ticket.assignee == "Jane Developer"
        assert ticket.labels == ["feature", "backend"]
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_platform_metadata(self, provider, sample_linear_response):
        ticket = provider.normalize(sample_linear_response)

        assert ticket.platform_metadata["linear_uuid"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert ticket.platform_metadata["team_key"] == "ENG"
        assert ticket.platform_metadata["team_name"] == "Engineering"
        assert ticket.platform_metadata["priority"] == "High"
        assert ticket.platform_metadata["priority_value"] == 2
        assert ticket.platform_metadata["state_type"] == "started"
        assert ticket.platform_metadata["state_name"] == "In Progress"
        assert ticket.platform_metadata["cycle"] == "Sprint 42"
        assert ticket.platform_metadata["parent_id"] is None

    def test_normalize_minimal_response(self, provider):
        minimal = {
            "identifier": "TEST-1",
            "title": "Minimal issue",
            "state": {},
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(minimal)

        assert ticket.id == "TEST-1"
        assert ticket.title == "Minimal issue"
        assert ticket.status == TicketStatus.UNKNOWN
        assert ticket.type == TicketType.UNKNOWN

    def test_normalize_with_parent(self, provider, sample_linear_response):
        sample_linear_response["parent"] = {"identifier": "ENG-100"}
        ticket = provider.normalize(sample_linear_response)

        assert ticket.platform_metadata["parent_id"] == "ENG-100"


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    def test_normalize_with_none_state(self, provider):
        """Handle None state gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.UNKNOWN

    def test_normalize_with_non_dict_state(self, provider):
        """Handle non-dict state gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": "invalid", "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.UNKNOWN

    def test_normalize_with_none_assignee(self, provider):
        """Handle None assignee gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "assignee": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_none_labels(self, provider):
        """Handle None labels gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "labels": None}
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_non_dict_labels(self, provider):
        """Handle non-dict labels gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "labels": "invalid"}
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_malformed_label_nodes(self, provider):
        """Handle malformed label nodes gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "labels": {"nodes": [None, "invalid", {"name": "valid"}, {"name": ""}]},
        }
        ticket = provider.normalize(data)
        assert ticket.labels == ["valid"]

    def test_normalize_with_none_team(self, provider):
        """Handle None team gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "team": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["team_key"] == ""
        assert ticket.platform_metadata["team_name"] == ""

    def test_normalize_with_none_cycle(self, provider):
        """Handle None cycle gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "cycle": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["cycle"] is None

    def test_normalize_with_none_parent(self, provider):
        """Handle None parent gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "parent": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["parent_id"] is None


class TestStatusMapping:
    """Test status mapping coverage."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    @pytest.mark.parametrize("state_type,expected", [
        ("backlog", TicketStatus.OPEN),
        ("unstarted", TicketStatus.OPEN),
        ("started", TicketStatus.IN_PROGRESS),
        ("completed", TicketStatus.DONE),
        ("canceled", TicketStatus.CLOSED),
    ])
    def test_state_type_mapping(self, provider, state_type, expected):
        """Test mapping by state.type (preferred)."""
        assert provider._map_status(state_type, "") == expected

    @pytest.mark.parametrize("state_name,expected", [
        ("Backlog", TicketStatus.OPEN),
        ("Triage", TicketStatus.OPEN),
        ("Todo", TicketStatus.OPEN),
        ("In Progress", TicketStatus.IN_PROGRESS),
        ("In Review", TicketStatus.REVIEW),
        ("Done", TicketStatus.DONE),
        ("Canceled", TicketStatus.CLOSED),
    ])
    def test_state_name_fallback(self, provider, state_name, expected):
        """Test fallback to state.name when state.type is unavailable."""
        assert provider._map_status("", state_name) == expected

    def test_unknown_status(self, provider):
        """Unknown state returns UNKNOWN."""
        assert provider._map_status("custom", "Custom State") == TicketStatus.UNKNOWN


class TestTypeMapping:
    """Test type mapping coverage."""

    @pytest.fixture
    def provider(self):
        return LinearProvider()

    @pytest.mark.parametrize("labels,expected", [
        (["bug"], TicketType.BUG),
        (["Bug Report"], TicketType.BUG),
        (["feature"], TicketType.FEATURE),
        (["enhancement"], TicketType.FEATURE),
        (["task"], TicketType.TASK),
        (["chore"], TicketType.TASK),
        (["tech-debt"], TicketType.MAINTENANCE),
        (["Infrastructure"], TicketType.MAINTENANCE),
        (["priority", "backend"], TicketType.UNKNOWN),  # No type keywords
        ([], TicketType.UNKNOWN),
    ])
    def test_type_mapping_from_labels(self, provider, labels, expected):
        assert provider._map_type(labels) == expected

    def test_first_matching_label_wins(self, provider):
        """If multiple labels match, first one in list wins."""
        # "bug" matches before "feature"
        labels = ["bug", "feature"]
        assert provider._map_type(labels) == TicketType.BUG


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    def test_prompt_template_contains_placeholder(self):
        provider = LinearProvider()
        template = provider.get_prompt_template()

        assert "{ticket_id}" in template
        assert "identifier" in template
        assert "state" in template
        assert "labels" in template


class TestFetchTicketDeprecation:
    """Test fetch_ticket() deprecation warning."""

    def test_fetch_ticket_raises_deprecation_warning(self):
        """fetch_ticket() should emit DeprecationWarning before raising."""
        provider = LinearProvider()

        with pytest.warns(DeprecationWarning, match="deprecated"):
            with pytest.raises(NotImplementedError):
                provider.fetch_ticket("ENG-123")

    def test_fetch_ticket_raises_not_implemented(self):
        """fetch_ticket() should raise NotImplementedError."""
        import warnings
        provider = LinearProvider()

        # Suppress the warning to test the exception
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(NotImplementedError, match="hybrid architecture"):
                provider.fetch_ticket("ENG-123")
```

---

## Integration Points

### TicketService (AMI-32)

The `LinearProvider` integrates with `TicketService` which orchestrates the provider and fetcher:

```python
class TicketService:
    def __init__(self, registry: ProviderRegistry, fetcher: TicketFetcher):
        self._registry = registry
        self._fetcher = fetcher

    async def get_ticket(self, input_str: str) -> GenericTicket:
        # 1. Detect platform and get provider
        provider = self._registry.get_provider_for_input(input_str)

        # 2. Parse input to get normalized ID
        ticket_id = provider.parse_input(input_str)

        # 3. Fetch raw data via TicketFetcher
        raw_data = await self._fetcher.fetch(ticket_id, provider)

        # 4. Normalize using provider
        return provider.normalize(raw_data)
```

### AuggieMediatedFetcher (AMI-30)

Uses `get_prompt_template()` for structured prompts:

```python
class AuggieMediatedFetcher(TicketFetcher):
    async def fetch(self, ticket_id: str, provider: IssueTrackerProvider) -> dict:
        # Get platform-specific prompt
        template = provider.get_prompt_template()
        prompt = template.format(ticket_id=ticket_id)

        # Send to AI agent
        response = await self._agent.send(prompt)

        # Parse JSON from response
        return json.loads(response)
```

### DirectAPIFetcher (AMI-31)

Uses `normalize()` for response conversion:

```python
class DirectAPIFetcher(TicketFetcher):
    async def fetch(self, ticket_id: str, provider: IssueTrackerProvider) -> dict:
        # Make direct GraphQL API call
        raw_data = await self._linear_client.get_issue(ticket_id)

        # Return raw data (normalization done by TicketService)
        return raw_data
```

### ProviderRegistry (AMI-17)

Uses `@ProviderRegistry.register` decorator:

```python
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get Linear provider
provider = ProviderRegistry.get_provider(Platform.LINEAR)

# Or detect from input
provider = ProviderRegistry.get_provider_for_input("https://linear.app/team/issue/ENG-123")
```

---

## Dependencies

### Required (Must Be Complete)

| Dependency | Ticket | Status |
|------------|--------|--------|
| `PlatformDetector` | AMI-16 | ✅ Complete |
| `ProviderRegistry` | AMI-17 | ✅ Complete |
| `IssueTrackerProvider` ABC | AMI-17 | ✅ Complete |
| `Platform` enum | AMI-17 | ✅ Complete |
| `GenericTicket` dataclass | AMI-17 | ✅ Complete |
| `UserInteractionInterface` | AMI-17 | ✅ Complete |

### Future Integration

| Integration Point | Ticket | Relationship |
|-------------------|--------|--------------|
| `TicketService` | AMI-32 | Orchestrates provider + fetcher |
| `AuggieMediatedFetcher` | AMI-30 | Uses `get_prompt_template()` |
| `DirectAPIFetcher` | AMI-31 | Uses `normalize()` for response handling |
| `TicketFetcher` abstraction | AMI-29 | Base class for fetcher implementations |

---

## Migration Considerations

### Backward Compatibility

- `fetch_ticket()` raises `NotImplementedError` with clear migration message
- Existing code using direct Linear integration unchanged
- Provider is opt-in via explicit import

### Gradual Migration Path

1. **Phase 1 (This Ticket):** Implement LinearProvider with parse/normalize capabilities
2. **Phase 2 (AMI-32):** Integrate with TicketService for unified access
3. **Phase 3 (Future):** Deprecate legacy direct GraphQL client usage

### ID Disambiguation

Linear IDs (`TEAM-123`) are ambiguous with Jira IDs (`PROJECT-123`):

| Component | Responsibility |
|-----------|---------------|
| **PlatformDetector** (AMI-16) | Detects POSSIBLE platforms from input pattern |
| **CLI** (AMI-25) | Handles user prompting when multiple platforms match |
| **LinearProvider** (this ticket) | Only handles inputs AFTER platform is determined |

---

## Acceptance Criteria Checklist

From Linear ticket AMI-20:

- [ ] LinearProvider class extends IssueTrackerProvider ABC
- [ ] Registers with ProviderRegistry using @register decorator
- [ ] PLATFORM class attribute set to Platform.LINEAR
- [ ] Implements all required abstract methods:
  - [ ] `platform` property → returns Platform.LINEAR
  - [ ] `name` property → returns "Linear"
  - [ ] `can_handle(input_str)` - recognizes Linear URLs and TEAM-123 format
  - [ ] `parse_input(input_str)` - extracts normalized ticket ID (handles URL slugs)
  - [ ] `fetch_ticket(ticket_id)` - raises NotImplementedError (hybrid architecture)
  - [ ] `check_connection()` - returns ready status
- [ ] Implements additional methods for hybrid architecture:
  - [ ] `normalize(raw_data)` - converts Linear GraphQL JSON to GenericTicket
  - [ ] `get_prompt_template()` - returns structured prompt for agent
- [ ] `platform_metadata` includes: `team_key`, `cycle`, `parent_id`, `linear_uuid`
- [ ] STATUS_MAPPING covers Linear state types (backlog, unstarted, started, completed, canceled)
- [ ] TYPE_KEYWORDS enables type inference from labels
- [ ] No direct HTTP calls in this class
- [ ] Unit tests with >90% coverage
- [ ] Documentation in docstrings

---

## Example Usage

### Basic Provider Usage

```python
from spec.integrations.providers.linear import LinearProvider
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get provider via registry (singleton)
provider = ProviderRegistry.get_provider(Platform.LINEAR)

# Check if input is handled by this provider
if provider.can_handle("https://linear.app/myteam/issue/ENG-123"):
    ticket_id = provider.parse_input("https://linear.app/myteam/issue/ENG-123")
    print(f"Parsed ticket ID: {ticket_id}")  # ENG-123
```

### Normalizing Raw Linear Response

```python
from spec.integrations.providers.linear import LinearProvider

provider = LinearProvider()

# Raw GraphQL response from Linear API
raw_response = {
    "identifier": "ENG-42",
    "title": "Fix login bug",
    "state": {"type": "started", "name": "In Progress"},
    "labels": {"nodes": [{"name": "bug"}]},
    # ... more fields
}

# Normalize to GenericTicket
ticket = provider.normalize(raw_response)
print(f"Title: {ticket.title}")  # Fix login bug
print(f"Status: {ticket.status}")  # TicketStatus.IN_PROGRESS
print(f"Type: {ticket.type}")  # TicketType.BUG
```

### Integration with TicketService (AMI-32)

```python
from spec.integrations.ticket_service import TicketService

# TicketService handles provider lookup and fetching
service = TicketService()
ticket = await service.get_ticket("https://linear.app/team/issue/ENG-123")

# Ticket is already normalized as GenericTicket
print(f"Title: {ticket.title}")
print(f"Status: {ticket.status}")
print(f"Type: {ticket.type}")
print(f"Team: {ticket.platform_metadata['team_key']}")
```

### Test Isolation Pattern

```python
import pytest
from spec.integrations.providers.registry import ProviderRegistry

@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure clean registry state for each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


def test_isolated_provider():
    """Test runs with clean registry state."""
    # Re-import to trigger registration
    from spec.integrations.providers.linear import LinearProvider

    provider = ProviderRegistry.get_provider(Platform.LINEAR)
    assert provider is not None
```

---

## References

- [Linear Integration Spec](specs/02_Integration_Linear_Spec.md) - Linear-specific field mappings
- [Architecture Spec - Section 6: Provider Registry](specs/00_Architecture_Refactor_Spec.md#6-provider-registry--factory-pattern)
- [AMI-17 Implementation Plan](specs/AMI-17-implementation-plan.md) - ProviderRegistry pattern
- [AMI-18 Implementation Plan](specs/AMI-18-implementation-plan.md) - JiraProvider reference implementation
- [AMI-30 Implementation Plan](specs/AMI-30-implementation-plan.md) - Structured prompt templates
- [AMI-31 Implementation Plan](specs/AMI-31-implementation-plan.md) - Direct API handler pattern

---

## Implementation Notes

> **Alignment with Linear Ticket:** This implementation plan has been verified against the AMI-20 Linear ticket to ensure all requirements are addressed. Key alignment points:
>
> 1. **AMI-17 Alignment Verification** - The constructor contract, `PLATFORM` class attribute, and `@ProviderRegistry.register` decorator pattern all follow the AMI-17 provider infrastructure specifications.
>
> 2. **Constructor Contract** - The `LinearProvider.__init__()` accepts optional `user_interaction` parameter for dependency injection during testing, following the same pattern as other providers.
>
> 3. **Test Isolation Pattern** - Tests should use the `reset_registry` fixture (shown in Testing Strategy) to ensure clean registry state. This prevents cross-test pollution when using the `@ProviderRegistry.register` decorator.
>
> 4. **ID Disambiguation** - As noted in AMI-20 comments, the LinearProvider handles inputs AFTER platform is determined. Disambiguation logic belongs in PlatformDetector (AMI-16) and CLI (AMI-25), not in this provider.
>
> 5. **State Type vs Name** - Linear workflow state types are reliable (`backlog`, `unstarted`, `started`, `completed`, `canceled`), while state names are customizable per team. Always prefer `state.type` for mapping, with `state.name` as fallback.
>
> 6. **Label-Based Type Inference** - Unlike Jira which has explicit issue types, Linear uses labels for categorization. Type is inferred from label keywords, with UNKNOWN as default when no type-specific labels are found.
