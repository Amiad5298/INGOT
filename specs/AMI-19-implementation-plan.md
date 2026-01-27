# Implementation Plan: AMI-19 - Implement GitHubProvider Concrete Class

**Ticket:** [AMI-19](https://linear.app/amiadspec/issue/AMI-19/implement-githubprovider-concrete-class)
**Status:** Draft
**Date:** 2026-01-25

---

## Summary

This ticket implements the `GitHubProvider` concrete class that extends `IssueTrackerProvider` for GitHub Issues and Pull Requests integration. Following the hybrid ticket fetching architecture, this provider focuses on **input parsing and data normalization**, not direct API calls. The actual data fetching is delegated to `TicketFetcher` implementations (`AuggieMediatedFetcher` as primary, `DirectAPIFetcher` as fallback).

The provider is responsible for:
1. **Input parsing** - Recognizing GitHub URLs (issues, PRs), short references (`owner/repo#123`), and `#123` format with default owner/repo
2. **Data normalization** - Converting raw GitHub REST API/agent responses to `GenericTicket`
3. **Status/type mapping** - Mapping GitHub states and labels to normalized enums
4. **Structured prompt templates** - Providing GitHub-specific prompts for agent-mediated fetching

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TicketFetcher (AMI-29/30/31)      │  Handles HOW to get data               │
│  • AuggieMediatedFetcher (primary) │  • Structured prompt → raw JSON        │
│  • DirectAPIFetcher (fallback)     │  • REST API → raw JSON                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ raw JSON data
┌─────────────────────────────────────────────────────────────────────────────┐
│  GitHubProvider (THIS TICKET)      │  Handles WHAT the data means           │
│  • can_handle()                    │  • URL/ID pattern matching             │
│  • parse_input()                   │  • URL/ID → normalized ticket ID       │
│  • normalize()                     │  • raw JSON → GenericTicket            │
│  • get_prompt_template()           │  • GitHub-specific prompt for agent    │
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
3. **Unified Issue/PR Handling** - Both issues and PRs use same endpoints; distinguished via `pull_request` field
4. **Label-Based Type Inference** - GitHub uses labels for categorization; type is inferred from keywords
5. **State-Based Status + Label Enhancement** - Base status from `state` field, optionally enhanced by labels
6. **Optional DI** - Constructor accepts optional `user_interaction` for testing
7. **GitHub Enterprise Support** - URL patterns support custom domains

---

## Components to Create

### New File: `spec/integrations/providers/github.py`

| Component | Purpose |
|-----------|---------|
| `GitHubProvider` class | Concrete provider for GitHub platform |
| `STATUS_MAPPING` dict | Maps GitHub states/state_reason to `TicketStatus` |
| `LABEL_STATUS_MAP` dict | Optional status enhancement from labels |
| `TYPE_KEYWORDS` dict | Keywords for inferring `TicketType` from labels |
| `STRUCTURED_PROMPT_TEMPLATE` str | GitHub-specific prompt for agent-mediated fetching |

### Modified Files

| File | Changes |
|------|---------|
| `spec/integrations/providers/__init__.py` | Export `GitHubProvider` |

### ABC Extension Note

> **Important:** The `normalize()` and `get_prompt_template()` methods are **not** currently part of the `IssueTrackerProvider` ABC. They are provider-specific extensions required by the hybrid architecture's `TicketFetcher` integration pattern:
> - `normalize()` - Called by `DirectAPIFetcher` and `AuggieMediatedFetcher` to convert raw JSON to `GenericTicket`
> - `get_prompt_template()` - Called by `AuggieMediatedFetcher` to get platform-specific structured prompts
>
> These methods may be added to the ABC in a future refactor once the hybrid pattern stabilizes.

### Defensive Field Handling

> **Pattern:** This implementation uses the `safe_nested_get()` static method from the base class for all nested dictionary access. This protects against malformed API responses where nested objects may be `None` or non-dict types:
>
> ```python
> # Defensive pattern used throughout normalize():
> user_obj = raw_data.get("user")
> author_login = self.safe_nested_get(user_obj, "login", "")
> ```
>
> This pattern is consistent with the JiraProvider implementation (PR #26) and uses the base class utility method defined in `spec/integrations/providers/base.py`.

---

## Implementation Steps

### Step 1: Create GitHubProvider Module

**File:** `spec/integrations/providers/github.py`

```python
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
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    UserInteractionInterface,
)


# Status mapping: GitHub state + state_reason → TicketStatus
# GitHub issues only have "open" or "closed" states; PRs can be "merged"
STATUS_MAPPING: dict[str, TicketStatus] = {
    "open": TicketStatus.OPEN,
    "closed": TicketStatus.CLOSED,  # Default for closed; may be refined by state_reason
}

# State reason mapping for closed issues (GitHub API v3)
# state_reason indicates why an issue was closed
STATE_REASON_MAPPING: dict[str, TicketStatus] = {
    "completed": TicketStatus.DONE,      # Issue resolved successfully
    "not_planned": TicketStatus.CLOSED,  # Closed without resolution (won't fix)
    "reopened": TicketStatus.OPEN,       # Issue was reopened
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
```

### Step 2: Add Type Keywords and Prompt Template

Continue in `spec/integrations/providers/github.py`:

```python
# Type inference keywords: keyword → TicketType
# GitHub uses labels for categorization, so we infer type from label names
TYPE_KEYWORDS: dict[TicketType, list[str]] = {
    TicketType.BUG: ["bug", "defect", "fix", "error", "crash", "regression", "issue"],
    TicketType.FEATURE: ["feature", "enhancement", "feat", "story", "request", "new"],
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
```

### Step 3: Add GitHubProvider Class Definition

```python
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

    # URL patterns for GitHub (supports both github.com and GitHub Enterprise)
    _URL_PATTERNS = [
        # Standard GitHub.com issue/PR URL
        re.compile(
            r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(issues|pull)/(?P<number>\d+)",
            re.IGNORECASE,
        ),
        # GitHub Enterprise URL pattern (any domain with /issues/ or /pull/)
        re.compile(
            r"https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(issues|pull)/(?P<number>\d+)",
            re.IGNORECASE,
        ),
    ]

    # Short reference pattern: owner/repo#123
    _SHORT_REF_PATTERN = re.compile(
        r"^(?P<owner>[^/]+)/(?P<repo>[^/]+)#(?P<number>\d+)$"
    )

    # Bare issue number pattern: #123 (requires default owner/repo)
    _BARE_NUMBER_PATTERN = re.compile(r"^#(?P<number>\d+)$")

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
        self._has_explicit_defaults = (
            (default_owner is not None and default_repo is not None)
            or (env_owner is not None and env_repo is not None)
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

    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Recognizes:
        - GitHub URLs: https://github.com/owner/repo/issues/123
        - GitHub PR URLs: https://github.com/owner/repo/pull/123
        - GitHub Enterprise URLs: https://github.company.com/owner/repo/issues/123
        - Short references: owner/repo#123
        - Bare issue numbers: #123 (ONLY if default owner/repo are configured)

        Args:
            input_str: URL or ticket reference to check

        Returns:
            True if this provider recognizes the input format
        """
        input_str = input_str.strip()

        # Check URL patterns (unambiguous GitHub detection)
        for pattern in self._URL_PATTERNS:
            if pattern.match(input_str):
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
            ValueError: If input cannot be parsed
        """
        input_str = input_str.strip()

        # Try URL patterns first
        for pattern in self._URL_PATTERNS:
            match = pattern.match(input_str)
            if match:
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
```

### Step 4: Add normalize() Method

```python
    def normalize(self, raw_data: dict[str, Any]) -> GenericTicket:
        """Convert raw GitHub API data to GenericTicket.

        Handles nested API response structure and edge cases.
        Uses defensive field handling for malformed API responses.

        Args:
            raw_data: Raw GitHub REST API response (issue/PR object)

        Returns:
            Populated GenericTicket with normalized fields
        """
        # Extract repository info for ticket ID
        # The repository field may come from different structures depending on source
        repo_obj = raw_data.get("repository", {})
        repo_full_name = self.safe_nested_get(repo_obj, "full_name", "")

        # Fallback: construct from html_url if repository not provided
        if not repo_full_name:
            html_url = raw_data.get("html_url", "")
            # Parse owner/repo from URL: https://github.com/owner/repo/issues/123
            url_match = re.match(r"https?://[^/]+/([^/]+)/([^/]+)/", html_url)
            if url_match:
                repo_full_name = f"{url_match.group(1)}/{url_match.group(2)}"

        number = raw_data.get("number", 0)
        ticket_id = f"{repo_full_name}#{number}" if repo_full_name else str(number)

        # Extract state and determine status
        state = raw_data.get("state", "").lower()
        state_reason = raw_data.get("state_reason", "")

        # Check if PR was merged (for merged PRs, state is "closed" but merged_at is set)
        is_pr = raw_data.get("pull_request") is not None
        merged_at = raw_data.get("merged_at")

        status = self._map_status(state, state_reason, is_pr, merged_at)

        # Extract labels and enhance status from labels
        labels_raw = raw_data.get("labels", [])
        labels = [
            self.safe_nested_get(label, "name", "").strip()
            for label in labels_raw
            if isinstance(label, dict)
        ]
        labels = [l for l in labels if l]  # Filter empty strings

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
```

### Step 5: Add Prompt Template Method

```python
    def get_prompt_template(self) -> str:
        """Return structured prompt template for agent-mediated fetch.

        Returns:
            Prompt template string with {ticket_id} placeholder
        """
        return STRUCTURED_PROMPT_TEMPLATE
```

### Step 6: Update Package Exports

**File:** `spec/integrations/providers/__init__.py`

```python
# Add to existing imports
from spec.integrations.providers.github import GitHubProvider

# Add to __all__
__all__ = [
    # ... existing exports
    "GitHubProvider",
]
```

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_github_provider.py`

```python
"""Tests for GitHubProvider."""

import pytest
from datetime import datetime

from spec.integrations.providers.base import (
    GenericTicket,
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.github import (
    GitHubProvider,
    STATUS_MAPPING,
    STATE_REASON_MAPPING,
    LABEL_STATUS_MAP,
    TYPE_KEYWORDS,
)
from spec.integrations.providers.registry import ProviderRegistry


class TestGitHubProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        ProviderRegistry.clear()
        yield
        ProviderRegistry.clear()

    def test_provider_has_platform_attribute(self):
        """GitHubProvider has required PLATFORM class attribute."""
        assert hasattr(GitHubProvider, "PLATFORM")
        assert GitHubProvider.PLATFORM == Platform.GITHUB

    def test_provider_registers_successfully(self):
        """GitHubProvider can be registered with ProviderRegistry."""
        from spec.integrations.providers.github import GitHubProvider

        provider = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider is not None
        assert isinstance(provider, GitHubProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        provider1 = ProviderRegistry.get_provider(Platform.GITHUB)
        provider2 = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider1 is provider2


class TestGitHubProviderCanHandle:
    """Test can_handle() method."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    # Valid URLs
    @pytest.mark.parametrize("url", [
        "https://github.com/owner/repo/issues/123",
        "https://github.com/owner/repo/pull/456",
        "https://github.com/octocat/Hello-World/issues/42",
        "https://github.com/myorg/backend/pull/1234",
        "http://github.com/owner/repo/issues/1",
        "https://github.mycompany.com/owner/repo/issues/99",  # GHE
    ])
    def test_can_handle_valid_urls(self, provider, url):
        assert provider.can_handle(url) is True

    # Valid short references
    @pytest.mark.parametrize("ref", [
        "owner/repo#123",
        "octocat/Hello-World#42",
        "myorg/backend#1",
        "OWNER/REPO#999",  # Case doesn't matter for matching
    ])
    def test_can_handle_valid_short_refs(self, provider, ref):
        assert provider.can_handle(ref) is True

    # Invalid inputs
    @pytest.mark.parametrize("input_str", [
        "https://company.atlassian.net/browse/PROJ-123",  # Jira
        "https://linear.app/team/issue/ENG-123",  # Linear
        "PROJ-123",  # Jira ID
        "ENG-123",   # Linear ID
        "#123",      # Bare number (no defaults configured)
        "123",       # Numeric only
        "",          # Empty
    ])
    def test_can_handle_invalid_inputs(self, provider, input_str):
        assert provider.can_handle(input_str) is False

    def test_can_handle_bare_number_with_defaults(self):
        """#123 is accepted when default owner/repo configured."""
        provider = GitHubProvider(default_owner="myorg", default_repo="myrepo")
        assert provider.can_handle("#123") is True
        assert provider.can_handle("#1") is True


class TestGitHubProviderParseInput:
    """Test parse_input() method."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_parse_issue_url(self, provider):
        url = "https://github.com/octocat/Hello-World/issues/42"
        assert provider.parse_input(url) == "octocat/Hello-World#42"

    def test_parse_pr_url(self, provider):
        url = "https://github.com/owner/repo/pull/123"
        assert provider.parse_input(url) == "owner/repo#123"

    def test_parse_ghe_url(self, provider):
        url = "https://github.company.com/org/project/issues/99"
        assert provider.parse_input(url) == "org/project#99"

    def test_parse_short_ref(self, provider):
        assert provider.parse_input("owner/repo#123") == "owner/repo#123"

    def test_parse_with_whitespace(self, provider):
        assert provider.parse_input("  owner/repo#123  ") == "owner/repo#123"

    def test_parse_bare_number_with_defaults(self):
        provider = GitHubProvider(default_owner="myorg", default_repo="myrepo")
        assert provider.parse_input("#123") == "myorg/myrepo#123"

    def test_parse_invalid_raises_valueerror(self, provider):
        with pytest.raises(ValueError, match="Cannot parse GitHub issue"):
            provider.parse_input("PROJ-123")  # Jira format


class TestGitHubProviderNormalize:
    """Test normalize() method."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    @pytest.fixture
    def sample_github_response(self):
        return {
            "number": 42,
            "title": "Found a bug in login",
            "body": "When clicking login, nothing happens.",
            "state": "open",
            "state_reason": None,
            "html_url": "https://github.com/octocat/Hello-World/issues/42",
            "labels": [{"name": "bug"}, {"name": "priority: high"}],
            "assignee": {"login": "developer"},
            "assignees": [{"login": "developer"}, {"login": "reviewer"}],
            "user": {"login": "reporter"},
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-18T14:20:00Z",
            "closed_at": None,
            "repository": {"full_name": "octocat/Hello-World"},
            "pull_request": None,
            "milestone": {"title": "v1.0"},
            "merged_at": None,
        }

    def test_normalize_full_response(self, provider, sample_github_response):
        ticket = provider.normalize(sample_github_response)

        assert ticket.id == "octocat/Hello-World#42"
        assert ticket.platform == Platform.GITHUB
        assert ticket.url == "https://github.com/octocat/Hello-World/issues/42"
        assert ticket.title == "Found a bug in login"
        assert ticket.description == "When clicking login, nothing happens."
        assert ticket.status == TicketStatus.OPEN
        assert ticket.type == TicketType.BUG
        assert ticket.assignee == "developer"
        assert "bug" in ticket.labels
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_platform_metadata(self, provider, sample_github_response):
        ticket = provider.normalize(sample_github_response)

        assert ticket.platform_metadata["repository"] == "octocat/Hello-World"
        assert ticket.platform_metadata["issue_number"] == 42
        assert ticket.platform_metadata["is_pull_request"] is False
        assert ticket.platform_metadata["milestone"] == "v1.0"
        assert ticket.platform_metadata["author"] == "reporter"

    def test_normalize_minimal_response(self, provider):
        minimal = {
            "number": 1,
            "title": "Minimal issue",
            "html_url": "https://github.com/owner/repo/issues/1",
            "state": "open",
            "labels": [],
        }
        ticket = provider.normalize(minimal)

        assert ticket.id == "owner/repo#1"
        assert ticket.title == "Minimal issue"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.type == TicketType.UNKNOWN

    def test_normalize_closed_completed(self, provider, sample_github_response):
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "completed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE

    def test_normalize_closed_not_planned(self, provider, sample_github_response):
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "not_planned"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.CLOSED

    def test_normalize_merged_pr(self, provider, sample_github_response):
        sample_github_response["pull_request"] = {"url": "..."}
        sample_github_response["merged_at"] = "2024-01-20T12:00:00Z"
        sample_github_response["state"] = "closed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE
        assert ticket.platform_metadata["is_pull_request"] is True


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_normalize_with_none_labels(self, provider):
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": None,
        }
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_none_assignee(self, provider):
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [],
            "assignee": None,
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_malformed_labels(self, provider):
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [None, "invalid", {"name": "valid"}, {"name": ""}],
        }
        ticket = provider.normalize(data)
        assert ticket.labels == ["valid"]

    def test_normalize_without_repository_field(self, provider):
        """Falls back to parsing html_url for repo info."""
        data = {
            "number": 42,
            "title": "Test",
            "html_url": "https://github.com/owner/repo/issues/42",
            "state": "open",
            "labels": [],
        }
        ticket = provider.normalize(data)
        assert ticket.id == "owner/repo#42"
        assert ticket.platform_metadata["repository"] == "owner/repo"


class TestStatusMapping:
    """Test status mapping coverage."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    @pytest.mark.parametrize("state,state_reason,expected", [
        ("open", None, TicketStatus.OPEN),
        ("closed", None, TicketStatus.CLOSED),
        ("closed", "completed", TicketStatus.DONE),
        ("closed", "not_planned", TicketStatus.CLOSED),
    ])
    def test_status_mapping(self, provider, state, state_reason, expected):
        assert provider._map_status(state, state_reason, False, None) == expected

    def test_merged_pr_is_done(self, provider):
        assert provider._map_status("closed", None, True, "2024-01-20T12:00:00Z") == TicketStatus.DONE

    @pytest.mark.parametrize("label,expected", [
        ("in progress", TicketStatus.IN_PROGRESS),
        ("in-progress", TicketStatus.IN_PROGRESS),
        ("wip", TicketStatus.IN_PROGRESS),
        ("review", TicketStatus.REVIEW),
        ("blocked", TicketStatus.BLOCKED),
    ])
    def test_label_status_enhancement(self, provider, label, expected):
        result = provider._enhance_status_from_labels(TicketStatus.OPEN, [label])
        assert result == expected


class TestTypeMapping:
    """Test type mapping coverage."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    @pytest.mark.parametrize("labels,expected", [
        (["bug"], TicketType.BUG),
        (["type: bug"], TicketType.BUG),
        (["feature"], TicketType.FEATURE),
        (["enhancement"], TicketType.FEATURE),
        (["chore"], TicketType.TASK),
        (["tech-debt"], TicketType.MAINTENANCE),
        (["dependencies"], TicketType.MAINTENANCE),
        (["priority: high"], TicketType.UNKNOWN),  # No type keyword
        ([], TicketType.UNKNOWN),
    ])
    def test_type_mapping_from_labels(self, provider, labels, expected):
        assert provider._map_type(labels) == expected


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    def test_prompt_template_contains_placeholder(self):
        provider = GitHubProvider()
        template = provider.get_prompt_template()

        assert "{ticket_id}" in template
        assert "number" in template
        assert "state" in template
        assert "labels" in template


class TestFetchTicketDeprecation:
    """Test fetch_ticket() deprecation warning."""

    def test_fetch_ticket_raises_deprecation_warning(self):
        provider = GitHubProvider()

        with pytest.warns(DeprecationWarning, match="deprecated"):
            with pytest.raises(NotImplementedError):
                provider.fetch_ticket("owner/repo#123")

    def test_fetch_ticket_raises_not_implemented(self):
        import warnings
        provider = GitHubProvider()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(NotImplementedError, match="hybrid architecture"):
                provider.fetch_ticket("owner/repo#123")
```

---

## Integration Points

### TicketService (AMI-32)

The `GitHubProvider` integrates with `TicketService` which orchestrates the provider and fetcher:

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
        # Parse ticket_id: "owner/repo#123"
        match = re.match(r"^([^/]+)/([^/]+)#(\d+)$", ticket_id)
        owner, repo, number = match.groups()

        # Make direct REST API call
        raw_data = await self._github_client.get_issue(owner, repo, int(number))

        # Return raw data (normalization done by TicketService)
        return raw_data
```

### ProviderRegistry (AMI-17)

Uses `@ProviderRegistry.register` decorator:

```python
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get GitHub provider
provider = ProviderRegistry.get_provider(Platform.GITHUB)

# Or detect from input
provider = ProviderRegistry.get_provider_for_input("https://github.com/owner/repo/issues/123")
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

## URL Pattern Disambiguation

GitHub URLs are unambiguous due to distinct patterns:

| Input Pattern | Provider | Notes |
|---------------|----------|-------|
| `https://github.com/.../issues/...` | GitHub | Unambiguous |
| `https://github.com/.../pull/...` | GitHub | Unambiguous |
| `owner/repo#123` | GitHub | Unique to GitHub |
| `#123` | GitHub | Only with explicit defaults |
| `PROJECT-123` | Jira/Linear | Ambiguous, not handled by GitHub |

---

## Acceptance Criteria Checklist

From Linear ticket AMI-19:

- [ ] GitHubProvider class extends IssueTrackerProvider ABC
- [ ] Registers with ProviderRegistry using @register decorator
- [ ] PLATFORM class attribute set to Platform.GITHUB
- [ ] Implements all required abstract methods:
  - [ ] `platform` property → returns Platform.GITHUB
  - [ ] `name` property → returns "GitHub Issues"
  - [ ] `can_handle(input_str)` - recognizes GitHub URLs and owner/repo#123 format
  - [ ] `parse_input(input_str)` - extracts normalized ticket ID ({owner}/{repo}#{number})
  - [ ] `fetch_ticket(ticket_id)` - raises NotImplementedError (hybrid architecture)
  - [ ] `check_connection()` - returns ready status
- [ ] Implements additional methods for hybrid architecture:
  - [ ] `normalize(raw_data)` - converts GitHub REST JSON to GenericTicket
  - [ ] `get_prompt_template()` - returns structured prompt for agent
- [ ] `platform_metadata` includes: `repository`, `issue_number`, `is_pull_request`, `state_reason`
- [ ] Handles both issues and pull requests
- [ ] STATUS_MAPPING covers GitHub states (open, closed)
- [ ] STATE_REASON_MAPPING handles closure reasons (completed, not_planned)
- [ ] LABEL_STATUS_MAP enhances status from workflow labels
- [ ] TYPE_KEYWORDS enables type inference from labels
- [ ] No direct HTTP calls in this class
- [ ] Unit tests with >90% coverage
- [ ] Documentation in docstrings

---

## Example Usage

### Basic Provider Usage

```python
from spec.integrations.providers.github import GitHubProvider
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.base import Platform

# Get provider via registry (singleton)
provider = ProviderRegistry.get_provider(Platform.GITHUB)

# Check if input is handled by this provider
if provider.can_handle("https://github.com/octocat/Hello-World/issues/42"):
    ticket_id = provider.parse_input("https://github.com/octocat/Hello-World/issues/42")
    print(f"Parsed ticket ID: {ticket_id}")  # octocat/Hello-World#42
```

### Normalizing Raw GitHub Response

```python
from spec.integrations.providers.github import GitHubProvider

provider = GitHubProvider()

# Raw REST API response from GitHub
raw_response = {
    "number": 42,
    "title": "Fix login bug",
    "state": "open",
    "labels": [{"name": "bug"}],
    "html_url": "https://github.com/owner/repo/issues/42",
    "repository": {"full_name": "owner/repo"},
    # ... more fields
}

# Normalize to GenericTicket
ticket = provider.normalize(raw_response)
print(f"Title: {ticket.title}")  # Fix login bug
print(f"Status: {ticket.status}")  # TicketStatus.OPEN
print(f"Type: {ticket.type}")  # TicketType.BUG
```

### Using Default Owner/Repo

```python
from spec.integrations.providers.github import GitHubProvider

# Configure provider with defaults for bare issue references
provider = GitHubProvider(default_owner="myorg", default_repo="myrepo")

# Now can parse bare issue numbers
if provider.can_handle("#123"):
    ticket_id = provider.parse_input("#123")
    print(f"Parsed: {ticket_id}")  # myorg/myrepo#123
```

### Integration with TicketService (AMI-32)

```python
from spec.integrations.ticket_service import TicketService

# TicketService handles provider lookup and fetching
service = TicketService()
ticket = await service.get_ticket("https://github.com/owner/repo/issues/42")

# Ticket is already normalized as GenericTicket
print(f"Title: {ticket.title}")
print(f"Status: {ticket.status}")
print(f"Type: {ticket.type}")
print(f"Is PR: {ticket.platform_metadata['is_pull_request']}")
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
    from spec.integrations.providers.github import GitHubProvider

    provider = ProviderRegistry.get_provider(Platform.GITHUB)
    assert provider is not None
```

---

## References

- [GitHub Integration Spec](specs/01_Integration_GitHub_Spec.md) - GitHub-specific field mappings
- [Architecture Spec - Section 6: Provider Registry](specs/00_Architecture_Refactor_Spec.md#6-provider-registry--factory-pattern)
- [AMI-17 Implementation Plan](specs/AMI-17-implementation-plan.md) - ProviderRegistry pattern
- [AMI-18 Implementation Plan](specs/AMI-18-implementation-plan.md) - JiraProvider reference implementation
- [AMI-20 Implementation Plan](specs/AMI-20-implementation-plan.md) - LinearProvider reference implementation
- [AMI-30 Implementation Plan](specs/AMI-30-implementation-plan.md) - Structured prompt templates
- [AMI-31 Implementation Plan](specs/AMI-31-implementation-plan.md) - Direct API handler pattern

---

## Implementation Notes

> **Alignment with Linear Ticket:** This implementation plan has been verified against the AMI-19 Linear ticket to ensure all requirements are addressed. Key alignment points:
>
> 1. **AMI-17 Alignment Verification** - The constructor contract, `PLATFORM` class attribute, and `@ProviderRegistry.register` decorator pattern all follow the AMI-17 provider infrastructure specifications.
>
> 2. **Constructor Contract** - The `GitHubProvider.__init__()` accepts optional `default_owner` and `default_repo` parameters for bare issue number support. The `user_interaction` parameter is intentionally omitted since GitHubProvider doesn't require interactive user prompts - all fetching is delegated to the hybrid architecture.
>
> 3. **Test Isolation Pattern** - Tests should use the `reset_registry` fixture (shown in Testing Strategy) to ensure clean registry state. This prevents cross-test pollution when using the `@ProviderRegistry.register` decorator.
>
> 4. **Conservative Bare Number Support** - Bare issue numbers (`#123`) are only accepted when both `default_owner` and `default_repo` are **explicitly configured** via constructor or environment variables. The `_has_explicit_defaults` flag tracks this. This prevents ambiguous input from being claimed when no repository context exists.
>
> 5. **Defensive Normalization Pattern** - The `safe_nested_get()` helper method (inherited from `IssueTrackerProvider` base class) is used for all nested field access in `normalize()`. This handles malformed API responses where nested objects may be None or non-dict types.
>
> 6. **Dual Status Mapping Strategy** - Base status comes from `state` field, but is enhanced by:
>    - `state_reason` for closed issues (completed → DONE, not_planned → CLOSED)
>    - `merged_at` for merged PRs (→ DONE)
>    - Workflow labels for open issues (in-progress, review, blocked)
>
> 7. **Label-Based Type Inference** - GitHub doesn't have native issue types; type is inferred from label keywords. This is consistent with the Linear provider approach.
>
> 8. **ID Format** - Normalized ticket ID uses format `{owner}/{repo}#{number}` as specified in the GitHub Integration Spec (section 5.2).
>
> 9. **GitHub Enterprise Support** - URL patterns support custom domains via flexible regex. Base URL can be configured via `GITHUB_BASE_URL` environment variable.
>
> 10. **Pull Request Handling** - PRs are fetched through the same issues endpoint. The `pull_request` field presence indicates a PR, and `merged_at` indicates merge status.

---

*End of Implementation Plan*
