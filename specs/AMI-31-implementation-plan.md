# Implementation Plan: AMI-31 - Implement DirectAPIFetcher as Fallback with REST/GraphQL Clients

**Ticket:** [AMI-31](https://linear.app/amiadspec/issue/AMI-31/implement-directapifetcher-as-fallback-with-restgraphql-clients)
**Status:** Implemented
**PR:** [#24](https://github.com/Amiad5298/Spec/pull/24)
**Date:** 2026-01-25
**Last Updated:** 2026-01-25

---

## Summary

This ticket implements the `DirectAPIFetcher` class that fetches ticket data directly from platform APIs using credentials from `AuthenticationManager`. This serves as the **fallback path** when agent-mediated fetching (AMI-30) is unavailable or fails.

Unlike `AuggieMediatedFetcher` which delegates to an AI agent's MCP tools, `DirectAPIFetcher` makes direct HTTP requests to platform APIs:
- **REST APIs**: Jira, GitHub, Azure DevOps, Trello
- **GraphQL APIs**: Linear, Monday, GitHub (alternative)

The fetcher extends `TicketFetcher` ABC (AMI-29) and uses `AuthenticationManager` (AMI-22) for credential retrieval and `FetchPerformanceConfig` (AMI-33) for timeout/retry settings.

---

## Implementation Notes (Post-PR #24)

> **This section documents features implemented in PR #24 that were not in the original plan.**

### Additional Features Implemented

| Feature | Description |
|---------|-------------|
| **Resource Management** | Async context manager (`__aenter__`/`__aexit__`) and `close()` method for HTTP client lifecycle |
| **Lifecycle Safety** | `weakref.finalize` warns about unclosed clients to prevent resource leaks |
| **Concurrency Safety** | `asyncio.Lock` for thread-safe handler creation and HTTP client initialization |
| **Handler Registry** | Centralized registry pattern in `handlers/__init__.py` with `create_handler()` function |
| **Extended Exceptions** | New handler-specific exceptions: `CredentialValidationError`, `TicketIdFormatError`, `PlatformApiError`, `PlatformNotFoundError` |
| **Rate Limiting** | 429 handling with Retry-After header support (RFC 7231 compliant) |
| **Backoff Cap** | Exponential backoff capped at `MAX_RETRY_DELAY_SECONDS` |
| **Testability** | Injectable `sleeper` and `jitter_generator` for deterministic retry testing |
| **Security** | Log sanitization (`_truncate_error_body`, `_sanitize_debug_log`) to prevent PII leakage |
| **True Lazy Loading** | Only instantiate requested platform handler, not all handlers at once |

### Exception Hierarchy (Implemented)

The implementation added handler-specific exceptions that are mapped to `Agent*` exceptions:

```
TicketFetchError (base)
├── CredentialValidationError  → mapped to AgentIntegrationError
├── TicketIdFormatError        → mapped to AgentIntegrationError
├── PlatformApiError           → mapped to AgentFetchError
│   └── PlatformNotFoundError  → mapped to AgentFetchError
├── PlatformNotSupportedError
├── AgentIntegrationError      (public API)
├── AgentFetchError            (public API)
└── AgentResponseParseError    (public API)
```

### Resource Management Pattern (Required)

```python
# Recommended: Use async context manager
async with DirectAPIFetcher(auth_manager) as fetcher:
    data = await fetcher.fetch(ticket_id, platform)

# Alternative: Explicit close
fetcher = DirectAPIFetcher(auth_manager)
try:
    data = await fetcher.fetch(ticket_id, platform)
finally:
    await fetcher.close()
```

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TicketFetcher (ABC)                                │
│                      (spec/integrations/fetchers/base.py)                    │
│                                                                             │
│  async def fetch_raw(ticket_id, platform) → dict                            │
│  def supports_platform(platform) → bool                                     │
│  @property name → str                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                     ▲
                    ┌────────────────┴────────────────┐
                    │                                 │
┌───────────────────────────────────┐   ┌───────────────────────────────────┐
│   AuggieMediatedFetcher           │   │   DirectAPIFetcher ← THIS TICKET  │
│   (AMI-30)                        │   │                                   │
│                                   │   │   Uses AuthenticationManager      │
│   PRIMARY: Uses Auggie MCP tools  │   │   for fallback credentials        │
│   Platforms: Jira, Linear, GitHub │   │                                   │
│                                   │   │   FALLBACK: Direct REST/GraphQL   │
└───────────────────────────────────┘   │   Platforms: ALL 6 platforms      │
                                        └───────────────────────────────────┘
                                                         │
                                                         ▼
                                        ┌───────────────────────────────────┐
                                        │      PlatformHandler (ABC)        │
                                        │                                   │
                                        │  async def fetch(ticket_id,       │
                                        │                  credentials,     │
                                        │                  timeout) → dict  │
                                        └───────────────────────────────────┘
                                                         ▲
                    ┌────────────────┬────────────────┬──┴───┬─────────────┐
                    │                │                │      │             │
              ┌──────────┐   ┌───────────┐   ┌────────────┐ ┌──────────┐ ┌─────────┐
              │JiraHandler│   │LinearHandler│ │GitHubHandler│ │AzureDevOps│ │Trello/  │
              │  (REST)  │   │ (GraphQL)  │   │(REST)      │ │ Handler   │ │Monday   │
              └──────────┘   └───────────┘   └────────────┘ └──────────┘ └─────────┘
```

### Integration Points

| Component | Source | Usage |
|-----------|--------|-------|
| `TicketFetcher` ABC | AMI-29 | Base class to extend |
| `AuthenticationManager` | AMI-22 | `get_credentials(platform)` for auth |
| `FetchPerformanceConfig` | AMI-33 | Timeout, retry, and delay settings |
| `Platform` enum | `providers/base.py` | Platform identification |
| Exception hierarchy | `fetchers/exceptions.py` | Error handling |

### Key Design Decisions

1. **HTTP Client: `httpx`** - Async-native, modern Python HTTP library with excellent timeout support
2. **GraphQL Client: Native `httpx`** - Use `httpx` directly for GraphQL (simpler than `gql` for our use case)
3. **Handler Pattern** - Platform-specific handlers encapsulate API-specific logic
4. **Retry Strategy** - Exponential backoff with jitter using `FetchPerformanceConfig` settings
5. **Timeout Hierarchy** - Per-request timeout override > Instance timeout > `FetchPerformanceConfig` default
6. **Credential Immutability** - Uses `Mapping[str, str]` from `AuthenticationManager` (no modification)

---

## Components to Create

### New Files

| File | Purpose |
|------|---------|
| `spec/integrations/fetchers/direct_api_fetcher.py` | `DirectAPIFetcher` class |
| `spec/integrations/fetchers/handlers/__init__.py` | Handler package exports |
| `spec/integrations/fetchers/handlers/base.py` | `PlatformHandler` ABC |
| `spec/integrations/fetchers/handlers/jira.py` | `JiraHandler` - REST API |
| `spec/integrations/fetchers/handlers/linear.py` | `LinearHandler` - GraphQL API |
| `spec/integrations/fetchers/handlers/github.py` | `GitHubHandler` - REST API |
| `spec/integrations/fetchers/handlers/azure_devops.py` | `AzureDevOpsHandler` - REST API |
| `spec/integrations/fetchers/handlers/trello.py` | `TrelloHandler` - REST API |
| `spec/integrations/fetchers/handlers/monday.py` | `MondayHandler` - GraphQL API |

### Modified Files

| File | Changes |
|------|---------|
| `spec/integrations/fetchers/__init__.py` | Export `DirectAPIFetcher` |
| `pyproject.toml` | Add `httpx` dependency |

---

## Implementation Steps

### Step 1: Add httpx Dependency
**Command:** `poetry add httpx`

Add `httpx` as a project dependency for async HTTP requests.

### Step 2: Create Platform Handler Base Class
**File:** `spec/integrations/fetchers/handlers/base.py`

```python
"""Base class for platform-specific API handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import httpx


class PlatformHandler(ABC):
    """Base class for platform-specific API handlers.

    Each handler encapsulates the API-specific logic for fetching
    ticket data from a particular platform.

    HTTP Client Injection:
        Handlers accept an optional `http_client` parameter for testability.
        When provided, the handler uses the injected client instead of
        creating a new one. This enables easy mocking in unit tests.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name."""
        pass

    @property
    @abstractmethod
    def required_credential_keys(self) -> frozenset[str]:
        """Set of required credential keys for this platform.

        Returns:
            Frozenset of credential key names that must be present
        """
        pass

    @abstractmethod
    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch ticket data from platform API.

        Args:
            ticket_id: The ticket identifier
            credentials: Immutable credential mapping from AuthenticationManager
            timeout_seconds: Optional request timeout
            http_client: Optional injected HTTP client for testing

        Returns:
            Raw API response as dictionary

        Raises:
            ValueError: If required credential keys are missing
            httpx.HTTPError: For HTTP-level failures
            httpx.TimeoutException: For timeout failures
        """
        pass

    def _validate_credentials(self, credentials: Mapping[str, str]) -> None:
        """Validate that all required credential keys are present.

        Args:
            credentials: Credential mapping to validate

        Raises:
            ValueError: If any required keys are missing
        """
        missing = self.required_credential_keys - set(credentials.keys())
        if missing:
            raise ValueError(
                f"{self.platform_name} handler missing required credentials: {sorted(missing)}"
            )

    def _get_http_client(self, timeout_seconds: float | None = None) -> httpx.AsyncClient:
        """Create configured HTTP client with timeout."""
        timeout = httpx.Timeout(timeout_seconds or 30.0)
        return httpx.AsyncClient(timeout=timeout)
```

### Step 3: Implement Jira Handler (REST)
**File:** `spec/integrations/fetchers/handlers/jira.py`

```python
"""Jira REST API handler."""

from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


class JiraHandler(PlatformHandler):
    """Handler for Jira REST API v3.

    Credential keys (from AuthenticationManager):
        - url: Jira instance URL (e.g., https://company.atlassian.net)
        - email: User email for authentication
        - token: API token
    """

    @property
    def platform_name(self) -> str:
        return "Jira"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"url", "email", "token"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch issue from Jira REST API.

        API endpoint: GET /rest/api/3/issue/{issueIdOrKey}
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        url = credentials["url"].rstrip("/")
        email = credentials["email"]
        token = credentials["token"]

        endpoint = f"{url}/rest/api/3/issue/{ticket_id}"

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.get(
                endpoint,
                auth=(email, token),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.get(
                    endpoint,
                    auth=(email, token),
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                return response.json()
```

### Step 4: Implement Linear Handler (GraphQL)
**File:** `spec/integrations/fetchers/handlers/linear.py`

> **Note:** Linear's GraphQL API uses `issueByIdentifier` for team-scoped identifiers
> like "AMI-31". The `issue(id:)` query requires a UUID, which is not user-friendly.

```python
"""Linear GraphQL API handler."""

from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


# Use issueByIdentifier for team-scoped identifiers (e.g., "AMI-31")
# NOT issue(id:) which requires a UUID
ISSUE_QUERY = """
query GetIssue($identifier: String!) {
  issueByIdentifier(identifier: $identifier) {
    id
    identifier
    title
    description
    state { name }
    assignee { name email }
    labels { nodes { name } }
    createdAt
    updatedAt
    priority
    team { key name }
    url
  }
}
"""


class LinearHandler(PlatformHandler):
    """Handler for Linear GraphQL API.

    Credential keys (from AuthenticationManager):
        - api_key: Linear API key

    Ticket ID format: Team-scoped identifier (e.g., "AMI-31", "PROJ-123")
    """

    API_URL = "https://api.linear.app/graphql"

    @property
    def platform_name(self) -> str:
        return "Linear"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch issue from Linear GraphQL API.

        Uses issueByIdentifier query for team-scoped identifiers.
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": ISSUE_QUERY,
            "variables": {"identifier": ticket_id},
        }

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.post(
                self.API_URL,
                headers=headers,
                json=payload,
            )
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                )

        response.raise_for_status()
        data = response.json()

        # Extract issue from GraphQL response
        if "errors" in data:
            raise ValueError(f"GraphQL errors: {data['errors']}")

        issue = data.get("data", {}).get("issueByIdentifier")
        if issue is None:
            raise ValueError(f"Issue not found: {ticket_id}")
        return issue
```

### Step 5: Implement GitHub Handler (REST)
**File:** `spec/integrations/fetchers/handlers/github.py`

```python
"""GitHub REST API handler."""

import re
from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


class GitHubHandler(PlatformHandler):
    """Handler for GitHub REST API v3.

    Credential keys (from AuthenticationManager):
        - token: GitHub personal access token

    Ticket ID format: "owner/repo#number" (e.g., "microsoft/vscode#12345")
    """

    API_URL = "https://api.github.com"

    @property
    def platform_name(self) -> str:
        return "GitHub"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"token"})

    def _parse_ticket_id(self, ticket_id: str) -> tuple[str, str, int]:
        """Parse 'owner/repo#number' format.

        Returns:
            Tuple of (owner, repo, issue_number)
        """
        match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", ticket_id)
        if not match:
            raise ValueError(f"Invalid GitHub ticket format: {ticket_id}")
        return match.group(1), match.group(2), int(match.group(3))

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch issue/PR from GitHub REST API.

        API endpoint: GET /repos/{owner}/{repo}/issues/{issue_number}
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        owner, repo, number = self._parse_ticket_id(ticket_id)
        token = credentials["token"]

        endpoint = f"{self.API_URL}/repos/{owner}/{repo}/issues/{number}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.get(endpoint, headers=headers)
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.get(endpoint, headers=headers)

        response.raise_for_status()
        return response.json()
```

### Step 6: Implement Azure DevOps Handler (REST)
**File:** `spec/integrations/fetchers/handlers/azure_devops.py`

```python
"""Azure DevOps REST API handler."""

import base64
from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


class AzureDevOpsHandler(PlatformHandler):
    """Handler for Azure DevOps REST API.

    Credential keys (from AuthenticationManager):
        - organization: Azure DevOps organization name
        - pat: Personal Access Token

    Ticket ID format: "ProjectName/WorkItemID" (e.g., "MyProject/12345")
    """

    @property
    def platform_name(self) -> str:
        return "Azure DevOps"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"organization", "pat"})

    def _parse_ticket_id(self, ticket_id: str) -> tuple[str, int]:
        """Parse 'Project/ID' format.

        Returns:
            Tuple of (project, work_item_id)
        """
        parts = ticket_id.split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError(f"Invalid Azure DevOps ticket format: {ticket_id}")
        return parts[0], int(parts[1])

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch work item from Azure DevOps REST API.

        API endpoint: GET /{organization}/{project}/_apis/wit/workitems/{id}
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        project, work_item_id = self._parse_ticket_id(ticket_id)
        organization = credentials["organization"]
        pat = credentials["pat"]

        # Azure DevOps uses Basic auth with PAT as password
        auth_bytes = base64.b64encode(f":{pat}".encode()).decode()

        endpoint = (
            f"https://dev.azure.com/{organization}/{project}/"
            f"_apis/wit/workitems/{work_item_id}?api-version=7.0"
        )
        headers = {
            "Authorization": f"Basic {auth_bytes}",
            "Accept": "application/json",
        }

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.get(endpoint, headers=headers)
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.get(endpoint, headers=headers)

        response.raise_for_status()
        return response.json()
```

### Step 7: Implement Trello Handler (REST)
**File:** `spec/integrations/fetchers/handlers/trello.py`

```python
"""Trello REST API handler."""

from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


class TrelloHandler(PlatformHandler):
    """Handler for Trello REST API.

    Credential keys (from AuthenticationManager):
        - api_key: Trello API key
        - token: Trello token

    Ticket ID: Trello card ID or shortLink
    """

    API_URL = "https://api.trello.com/1"

    @property
    def platform_name(self) -> str:
        return "Trello"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key", "token"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch card from Trello REST API.

        API endpoint: GET /1/cards/{id}
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]
        token = credentials["token"]

        endpoint = f"{self.API_URL}/cards/{ticket_id}"
        params = {"key": api_key, "token": token}

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.get(endpoint, params=params)
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.get(endpoint, params=params)

        response.raise_for_status()
        return response.json()
```

### Step 8: Implement Monday Handler (GraphQL)
**File:** `spec/integrations/fetchers/handlers/monday.py`

```python
"""Monday.com GraphQL API handler."""

from collections.abc import Mapping
from typing import Any
import httpx
from .base import PlatformHandler


ITEM_QUERY = """
query GetItem($itemId: ID!) {
  items(ids: [$itemId]) {
    id
    name
    state
    column_values {
      id
      title
      text
    }
    created_at
    updated_at
    board { id name }
    group { id title }
  }
}
"""


class MondayHandler(PlatformHandler):
    """Handler for Monday.com GraphQL API.

    Credential keys (from AuthenticationManager):
        - api_key: Monday API key

    Ticket ID: Monday item ID (numeric)
    """

    API_URL = "https://api.monday.com/v2"

    @property
    def platform_name(self) -> str:
        return "Monday"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch item from Monday GraphQL API."""
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": ITEM_QUERY,
            "variables": {"itemId": ticket_id},
        }

        # Use injected client or create new one
        if http_client is not None:
            response = await http_client.post(
                self.API_URL,
                headers=headers,
                json=payload,
            )
        else:
            async with self._get_http_client(timeout_seconds) as client:
                response = await client.post(
                    self.API_URL,
                    headers=headers,
                    json=payload,
                )

        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise ValueError(f"GraphQL errors: {data['errors']}")

        items = data.get("data", {}).get("items", [])
        if not items:
            raise ValueError(f"Item not found: {ticket_id}")
        return items[0]
```

### Step 9: Create Handler Package Init
**File:** `spec/integrations/fetchers/handlers/__init__.py`

```python
"""Platform-specific API handlers for DirectAPIFetcher."""

from spec.integrations.fetchers.handlers.azure_devops import AzureDevOpsHandler
from spec.integrations.fetchers.handlers.base import PlatformHandler
from spec.integrations.fetchers.handlers.github import GitHubHandler
from spec.integrations.fetchers.handlers.jira import JiraHandler
from spec.integrations.fetchers.handlers.linear import LinearHandler
from spec.integrations.fetchers.handlers.monday import MondayHandler
from spec.integrations.fetchers.handlers.trello import TrelloHandler

__all__ = [
    "PlatformHandler",
    "JiraHandler",
    "LinearHandler",
    "GitHubHandler",
    "AzureDevOpsHandler",
    "TrelloHandler",
    "MondayHandler",
]
```

### Step 10: Implement DirectAPIFetcher Class
**File:** `spec/integrations/fetchers/direct_api_fetcher.py`

```python
"""Direct API ticket fetcher using REST/GraphQL clients.

This module provides DirectAPIFetcher for fetching ticket data directly
from platform APIs. This is the FALLBACK path when agent-mediated
fetching is unavailable.

The fetcher uses:
- AuthenticationManager (AMI-22) for credential retrieval
- FetchPerformanceConfig (AMI-33) for timeout/retry settings
- Platform-specific handlers for API implementation
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any

import httpx

from spec.config.fetch_config import FetchPerformanceConfig
from spec.integrations.fetchers.base import TicketFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
)
from spec.integrations.fetchers.handlers import (
    AzureDevOpsHandler,
    GitHubHandler,
    JiraHandler,
    LinearHandler,
    MondayHandler,
    PlatformHandler,
    TrelloHandler,
)
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auth import AuthenticationManager

logger = logging.getLogger(__name__)


class DirectAPIFetcher(TicketFetcher):
    """Fetches tickets directly from platform APIs.

    Uses AuthenticationManager for fallback credentials when agent-mediated
    fetching fails or is unavailable. Supports all 6 platforms with
    platform-specific handlers.

    Attributes:
        _auth: AuthenticationManager for credential retrieval
        _config: Optional ConfigManager for performance settings
        _timeout_seconds: Default request timeout
        _performance: FetchPerformanceConfig for retry settings
    """

    # Handler instances (created lazily)
    _handlers: dict[Platform, PlatformHandler] | None = None

    def __init__(
        self,
        auth_manager: AuthenticationManager,
        config_manager: ConfigManager | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Initialize with AuthenticationManager.

        Args:
            auth_manager: AuthenticationManager instance (from AMI-22)
            config_manager: Optional ConfigManager for performance settings
            timeout_seconds: Optional timeout override (uses config default otherwise)
        """
        self._auth = auth_manager
        self._config = config_manager

        # Get performance config for defaults
        if config_manager:
            self._performance = config_manager.get_fetch_performance_config()
        else:
            self._performance = FetchPerformanceConfig()

        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else self._performance.timeout_seconds
        )

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Direct API Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        """Check if fallback credentials exist for this platform.

        Uses AuthenticationManager.has_fallback_configured() from AMI-22.

        Args:
            platform: Platform enum value

        Returns:
            True if fallback credentials are configured
        """
        return self._auth.has_fallback_configured(platform)

    async def fetch(
        self,
        ticket_id: str,
        platform: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch ticket data from platform API (string-based interface).

        This is the primary public interface for TicketService integration.
        Accepts platform as a string and handles internal enum conversion.

        Args:
            ticket_id: Normalized ticket ID
            platform: Platform name string (e.g., 'jira', 'linear')
            timeout_seconds: Optional timeout override

        Returns:
            Raw API response data

        Raises:
            AgentIntegrationError: If platform string is invalid or not supported
            AgentFetchError: If API request fails
            AgentResponseParseError: If response parsing fails
        """
        platform_enum = self._resolve_platform(platform)
        return await self.fetch_raw(ticket_id, platform_enum, timeout_seconds)

    async def fetch_raw(
        self,
        ticket_id: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch ticket data from platform API.

        Args:
            ticket_id: Normalized ticket ID
            platform: Platform enum value
            timeout_seconds: Optional timeout override

        Returns:
            Raw API response data

        Raises:
            AgentIntegrationError: If no credentials configured for platform
            AgentFetchError: If API request fails (with retry exhaustion)
            AgentResponseParseError: If response parsing fails
        """
        # Get credentials from AuthenticationManager
        creds = self._auth.get_credentials(platform)
        if not creds.is_configured:
            raise AgentIntegrationError(
                message=creds.error_message or f"No credentials configured for {platform.name}",
                agent_name=self.name,
            )

        # Get platform-specific handler
        handler = self._get_platform_handler(platform)

        # Determine effective timeout
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._timeout_seconds
        )

        # Execute with retry logic
        return await self._fetch_with_retry(
            handler=handler,
            ticket_id=ticket_id,
            credentials=creds.credentials,
            timeout_seconds=effective_timeout,
        )

    async def _fetch_with_retry(
        self,
        handler: PlatformHandler,
        ticket_id: str,
        credentials: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Execute fetch with exponential backoff retry.

        Uses FetchPerformanceConfig settings for max_retries and retry_delay.
        """
        last_error: Exception | None = None

        for attempt in range(self._performance.max_retries + 1):
            try:
                return await handler.fetch(ticket_id, credentials, timeout_seconds)
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "Timeout fetching %s (attempt %d/%d): %s",
                    ticket_id, attempt + 1, self._performance.max_retries + 1, e,
                )
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise AgentFetchError(
                        message=f"API request failed: {e.response.status_code} {e.response.text}",
                        agent_name=self.name,
                        original_error=e,
                    ) from e
                last_error = e
                logger.warning(
                    "HTTP error fetching %s (attempt %d/%d): %s",
                    ticket_id, attempt + 1, self._performance.max_retries + 1, e,
                )
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Network error fetching %s (attempt %d/%d): %s",
                    ticket_id, attempt + 1, self._performance.max_retries + 1, e,
                )
            except ValueError as e:
                # GraphQL errors or parse errors
                raise AgentResponseParseError(
                    message=str(e),
                    agent_name=self.name,
                    original_error=e,
                ) from e

            # Calculate delay with jitter for next retry
            if attempt < self._performance.max_retries:
                delay = self._performance.retry_delay_seconds * (2 ** attempt)
                jitter = random.uniform(0, delay * 0.1)
                await asyncio.sleep(delay + jitter)

        # All retries exhausted
        raise AgentFetchError(
            message=f"API request failed after {self._performance.max_retries + 1} attempts",
            agent_name=self.name,
            original_error=last_error,
        )

    def _get_platform_handler(self, platform: Platform) -> PlatformHandler:
        """Get the handler for a specific platform.

        Lazily creates handlers on first access.
        """
        if self._handlers is None:
            self._handlers = {
                Platform.JIRA: JiraHandler(),
                Platform.LINEAR: LinearHandler(),
                Platform.GITHUB: GitHubHandler(),
                Platform.AZURE_DEVOPS: AzureDevOpsHandler(),
                Platform.TRELLO: TrelloHandler(),
                Platform.MONDAY: MondayHandler(),
            }

        handler = self._handlers.get(platform)
        if not handler:
            raise AgentIntegrationError(
                message=f"No handler for platform: {platform.name}",
                agent_name=self.name,
            )
        return handler

    def _resolve_platform(self, platform: str) -> Platform:
        """Resolve a platform string to Platform enum.

        Args:
            platform: Platform name as string (case-insensitive)

        Returns:
            Platform enum value

        Raises:
            AgentIntegrationError: If platform string is invalid
        """
        try:
            return Platform[platform.upper()]
        except KeyError:
            raise AgentIntegrationError(
                message=f"Unknown platform: {platform}",
                agent_name=self.name,
            )
```

### Step 11: Update Package Exports
**File:** `spec/integrations/fetchers/__init__.py`

Add export for `DirectAPIFetcher`:

```python
from spec.integrations.fetchers.direct_api_fetcher import DirectAPIFetcher

__all__ = [
    # ... existing exports ...
    "DirectAPIFetcher",
]
```

---

## Dependencies

### Upstream Dependencies (Must Exist Before Implementation)

| Component | Status | Location |
|-----------|--------|----------|
| `TicketFetcher` ABC | ✅ Implemented (AMI-29) | `spec/integrations/fetchers/base.py` |
| `AuthenticationManager` | ✅ Implemented (AMI-22) | `spec/integrations/auth.py` |
| `PlatformCredentials` | ✅ Implemented (AMI-22) | `spec/integrations/auth.py` |
| `FetchPerformanceConfig` | ✅ Implemented (AMI-33) | `spec/config/fetch_config.py` |
| `Platform` enum | ✅ Implemented (AMI-16) | `spec/integrations/providers/base.py` |
| Exception hierarchy | ✅ Implemented (AMI-30) | `spec/integrations/fetchers/exceptions.py` |

### External Dependencies (New)

| Package | Version | Purpose |
|---------|---------|---------|
| `httpx` | `^0.27.0` | Async HTTP client for REST/GraphQL |

### Downstream Dependents (Will Use This After Implementation)

| Component | Ticket | Usage |
|-----------|--------|-------|
| `TicketService` | AMI-32 | Uses `DirectAPIFetcher` as fallback when `AuggieMediatedFetcher` fails |

---

## Testing Strategy

### Unit Tests (`tests/test_direct_fetcher.py`)

1. **Initialization Tests**
   - `test_init_with_auth_manager_only` - Minimal initialization
   - `test_init_with_config_manager` - With ConfigManager for performance settings
   - `test_init_with_custom_timeout` - Custom timeout override
   - `test_name_property` - Returns "Direct API Fetcher"

2. **Platform Support Tests**
   - `test_supports_platform_with_credentials` - Returns True when credentials exist
   - `test_supports_platform_without_credentials` - Returns False when no credentials
   - `test_supports_platform_all_six` - Test each platform enum value

3. **Platform Resolution Tests**
   - `test_resolve_platform_valid_lowercase` - "jira" → Platform.JIRA
   - `test_resolve_platform_valid_uppercase` - "JIRA" → Platform.JIRA
   - `test_resolve_platform_invalid` - Raises AgentIntegrationError

4. **Handler Tests**
   - `test_get_platform_handler_jira` - Returns JiraHandler
   - `test_get_platform_handler_linear` - Returns LinearHandler
   - `test_get_platform_handler_github` - Returns GitHubHandler
   - `test_get_platform_handler_azure_devops` - Returns AzureDevOpsHandler
   - `test_get_platform_handler_trello` - Returns TrelloHandler
   - `test_get_platform_handler_monday` - Returns MondayHandler
   - `test_get_platform_handler_lazy_creation` - Handlers created lazily

5. **Fetch Tests (Mocked HTTP)**
   - `test_fetch_raw_jira_success` - Full flow with mocked response
   - `test_fetch_raw_linear_success` - GraphQL response handling
   - `test_fetch_raw_github_success` - GitHub issue fetch
   - `test_fetch_raw_no_credentials` - Raises AgentIntegrationError
   - `test_fetch_string_interface` - `fetch()` method works

6. **Retry Logic Tests**
   - `test_retry_on_timeout` - Retries on timeout, succeeds
   - `test_retry_exhausted` - Raises AgentFetchError after max retries
   - `test_no_retry_on_4xx` - Client errors not retried
   - `test_retry_on_5xx` - Server errors are retried
   - `test_exponential_backoff` - Delay increases exponentially

7. **Error Handling Tests**
   - `test_http_error_raises_agent_fetch_error` - HTTP failures wrapped
   - `test_graphql_error_raises_parse_error` - GraphQL errors wrapped
   - `test_invalid_ticket_format_raises` - Handler validation errors

### Handler Unit Tests (`tests/test_handlers/`)

Separate test files for each handler:

1. **`test_jira_handler.py`**
   - `test_fetch_success` - Valid response
   - `test_auth_header` - Basic auth format
   - `test_endpoint_url` - Correct API endpoint

2. **`test_linear_handler.py`**
   - `test_fetch_success` - GraphQL response extraction
   - `test_graphql_error_handling` - Error in response
   - `test_auth_header` - Authorization header format

3. **`test_github_handler.py`**
   - `test_parse_ticket_id_valid` - "owner/repo#123" parsing
   - `test_parse_ticket_id_invalid` - ValueError on bad format
   - `test_fetch_success` - Valid response

4. **`test_azure_devops_handler.py`**
   - `test_parse_ticket_id_valid` - "Project/123" parsing
   - `test_basic_auth_encoding` - PAT encoded correctly
   - `test_fetch_success` - Valid response

5. **`test_trello_handler.py`**
   - `test_fetch_success` - API key in query params
   - `test_endpoint_url` - Correct API endpoint

6. **`test_monday_handler.py`**
   - `test_fetch_success` - Item extraction from response
   - `test_item_not_found` - ValueError when empty

### Mock Strategy

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import httpx

from spec.integrations.auth import AuthenticationManager, PlatformCredentials
from spec.integrations.fetchers import DirectAPIFetcher
from spec.integrations.providers.base import Platform


@pytest.fixture
def mock_auth_manager():
    """Create a mock AuthenticationManager."""
    auth = MagicMock(spec=AuthenticationManager)
    # Default: no credentials configured
    auth.has_fallback_configured.return_value = False
    auth.get_credentials.return_value = PlatformCredentials(
        platform=Platform.JIRA,
        is_configured=False,
        credentials={},
        error_message="No credentials",
    )
    return auth


@pytest.fixture
def auth_with_jira_creds(mock_auth_manager):
    """AuthenticationManager with Jira credentials configured."""
    mock_auth_manager.has_fallback_configured.side_effect = (
        lambda p: p == Platform.JIRA
    )
    mock_auth_manager.get_credentials.return_value = PlatformCredentials(
        platform=Platform.JIRA,
        is_configured=True,
        credentials={
            "url": "https://company.atlassian.net",
            "email": "user@example.com",
            "token": "abc123",
        },
    )
    return mock_auth_manager


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"key": "PROJ-123", "summary": "Test"}
    return response
```

### Integration Tests (Required)

> **Architecture Review Requirement (2026-01-25):** Integration tests must cover at least
> **Jira, GitHub, and one non-Auggie platform** (Azure DevOps, Trello, or Monday).

For live API testing with real credentials:

```bash
# Run all integration tests (requires env vars for each platform)
pytest tests/integration/test_direct_fetcher_live.py -v --live

# Required platform coverage:
# 1. Jira (Auggie-supported platform)
FALLBACK_JIRA_URL=... FALLBACK_JIRA_EMAIL=... FALLBACK_JIRA_TOKEN=...

# 2. GitHub (Auggie-supported platform)
FALLBACK_GITHUB_TOKEN=...

# 3. At least ONE non-Auggie platform (choose one):
# Option A: Azure DevOps
FALLBACK_AZURE_DEVOPS_ORGANIZATION=... FALLBACK_AZURE_DEVOPS_PAT=...

# Option B: Trello
FALLBACK_TRELLO_API_KEY=... FALLBACK_TRELLO_TOKEN=...

# Option C: Monday
FALLBACK_MONDAY_API_KEY=...
```

**Integration Test File:** `tests/integration/test_direct_fetcher_live.py`

```python
"""Live integration tests for DirectAPIFetcher.

These tests require real API credentials and make actual HTTP requests.
Run with: pytest tests/integration/test_direct_fetcher_live.py -v --live

Required environment variables per platform - see test docstrings.
"""

import os
import pytest

from spec.config import ConfigManager
from spec.integrations.auth import AuthenticationManager
from spec.integrations.fetchers import DirectAPIFetcher
from spec.integrations.providers.base import Platform


# Skip all tests if --live flag not provided
pytestmark = pytest.mark.skipif(
    not pytest.config.getoption("--live", default=False),
    reason="Live tests require --live flag",
)


@pytest.fixture
def fetcher():
    """Create DirectAPIFetcher with real credentials."""
    config = ConfigManager()
    config.load()
    auth = AuthenticationManager(config)
    return DirectAPIFetcher(auth, config)


class TestJiraIntegration:
    """Jira live integration tests.

    Requires: FALLBACK_JIRA_URL, FALLBACK_JIRA_EMAIL, FALLBACK_JIRA_TOKEN
    """

    @pytest.mark.skipif(
        not os.getenv("FALLBACK_JIRA_URL"),
        reason="Jira credentials not configured",
    )
    async def test_fetch_jira_issue(self, fetcher):
        """Fetch a real Jira issue."""
        # Use a known test issue ID
        result = await fetcher.fetch("TEST-1", "jira")
        assert "key" in result
        assert "fields" in result


class TestGitHubIntegration:
    """GitHub live integration tests.

    Requires: FALLBACK_GITHUB_TOKEN
    """

    @pytest.mark.skipif(
        not os.getenv("FALLBACK_GITHUB_TOKEN"),
        reason="GitHub credentials not configured",
    )
    async def test_fetch_github_issue(self, fetcher):
        """Fetch a real GitHub issue."""
        # Use a known public issue
        result = await fetcher.fetch("octocat/Hello-World#1", "github")
        assert "number" in result
        assert "title" in result


class TestAzureDevOpsIntegration:
    """Azure DevOps live integration tests (non-Auggie platform).

    Requires: FALLBACK_AZURE_DEVOPS_ORGANIZATION, FALLBACK_AZURE_DEVOPS_PAT
    """

    @pytest.mark.skipif(
        not os.getenv("FALLBACK_AZURE_DEVOPS_ORGANIZATION"),
        reason="Azure DevOps credentials not configured",
    )
    async def test_fetch_azure_devops_work_item(self, fetcher):
        """Fetch a real Azure DevOps work item."""
        # Use a known test work item
        result = await fetcher.fetch("TestProject/1", "azure_devops")
        assert "id" in result
        assert "fields" in result
```

---

## Acceptance Criteria Checklist (Updated Post-Implementation)

From the Linear ticket:

- [x] `DirectAPIFetcher` class implementing `TicketFetcher` ABC
- [x] Constructor accepts `AuthenticationManager` (primary) and optional `ConfigManager`
- [x] `supports_platform()` uses `AuthenticationManager.has_fallback_configured(Platform)`
- [x] `fetch()` provides string-based interface for consistency with AuggieMediatedFetcher
- [x] `fetch_raw()` uses `AuthenticationManager.get_credentials(Platform)` returning `PlatformCredentials`
- [x] Handles `PlatformCredentials.credentials` as `Mapping[str, str]` (immutable)
- [x] Raises `AgentIntegrationError` when credentials not configured
- [x] Raises `AgentFetchError` for HTTP/API failures
- [x] Raises `AgentResponseParseError` for JSON/GraphQL parse failures
- [x] HTTP client injection for testing (optional `http_client` parameter in handlers)
- [x] Unit tests with mocked AuthenticationManager
- [ ] Integration tests for Jira, GitHub, and one non-Auggie platform *(test file exists, verify coverage)*

### Additional Criteria (From Architecture Review Comment 2026-01-25)

- [x] **All 6 platform handlers implemented**: JiraHandler, LinearHandler, GitHubHandler, AzureDevOpsHandler, TrelloHandler, MondayHandler
- [x] Each handler correctly uses the credential keys from AuthenticationManager (per AMI-22)
- [x] Each handler validates required credential keys before making API calls
- [ ] Integration tests for at least Jira, GitHub, and one non-Auggie platform (Azure DevOps, Trello, or Monday) *(verify coverage)*

### Additional Features Implemented (Beyond Original Plan)

- [x] Retry logic with exponential backoff using `FetchPerformanceConfig` settings
- [x] Timeout hierarchy: per-request > instance > config default
- [x] Handler package structure for maintainability
- [x] Package exports in `fetchers/__init__.py`
- [x] Type hints and docstrings for all public methods
- [x] Credential key validation in each handler (`_validate_credentials()` method)
- [x] Async context manager for resource lifecycle management (`__aenter__`/`__aexit__`/`close()`)
- [x] Concurrency-safe handler/client initialization with `asyncio.Lock`
- [x] Rate limiting (429) handling with Retry-After header support (RFC 7231)
- [x] Backoff cap at `MAX_RETRY_DELAY_SECONDS` to prevent excessively long waits
- [x] Log sanitization to prevent PII leakage (`_truncate_error_body`, `_sanitize_debug_log`)
- [x] Injectable `sleeper` and `jitter_generator` for deterministic testing
- [x] Handler registry pattern in `handlers/__init__.py` for clean instantiation
- [x] New exception types: `CredentialValidationError`, `TicketIdFormatError`, `PlatformApiError`, `PlatformNotFoundError`
- [x] `weakref.finalize` lifecycle safety warning for unclosed clients
- [x] `GraphQLPlatformHandler` base class for GraphQL-specific handlers

---

## Example Usage

### Basic Usage with String-Based Interface (Recommended)

```python
from spec.config import ConfigManager
from spec.integrations.auth import AuthenticationManager
from spec.integrations.fetchers import (
    DirectAPIFetcher,
    AgentIntegrationError,
    AgentFetchError,
    AgentResponseParseError,
)

# Initialize dependencies
config = ConfigManager()
config.load()
auth_manager = AuthenticationManager(config)

# Create fetcher with dependencies
fetcher = DirectAPIFetcher(
    auth_manager,
    config,
    timeout_seconds=45.0,  # Optional: custom default timeout
)

# Use the string-based fetch() interface
try:
    raw_data = await fetcher.fetch("PROJ-123", "jira")
    print(f"Fetched: {raw_data['summary']}")
except AgentIntegrationError as e:
    # Platform not supported or credentials not configured
    print(f"Configuration error: {e}")
except AgentFetchError as e:
    # HTTP/network failure (after retries)
    print(f"Fetch failed: {e}")
except AgentResponseParseError as e:
    # Response was invalid JSON or GraphQL error
    print(f"Parse error: {e}")
```

### Using Platform Enum Interface

```python
from spec.integrations.providers.base import Platform

# Check platform support before fetching
if fetcher.supports_platform(Platform.AZURE_DEVOPS):
    raw_data = await fetcher.fetch_raw("MyProject/12345", Platform.AZURE_DEVOPS)
    print(f"Work item: {raw_data['fields']['System.Title']}")
```

### With TicketService (AMI-32) - Fallback Pattern

```python
from spec.integrations.fetchers import (
    AuggieMediatedFetcher,
    DirectAPIFetcher,
    AgentIntegrationError,
    AgentFetchError,
)

class TicketService:
    def __init__(
        self,
        primary_fetcher: TicketFetcher,
        fallback_fetcher: TicketFetcher | None = None,
    ):
        self._primary = primary_fetcher
        self._fallback = fallback_fetcher

    async def fetch_ticket(self, ticket_id: str, platform: str) -> dict:
        """Fetch with automatic fallback."""
        try:
            return await self._primary.fetch(ticket_id, platform)
        except (AgentIntegrationError, AgentFetchError) as e:
            if self._fallback and self._fallback.supports_platform(
                Platform[platform.upper()]
            ):
                logger.warning(f"Primary fetch failed, using fallback: {e}")
                return await self._fallback.fetch(ticket_id, platform)
            raise


# Usage
auggie_fetcher = AuggieMediatedFetcher(auggie_client, config)
direct_fetcher = DirectAPIFetcher(auth_manager, config)

service = TicketService(
    primary_fetcher=auggie_fetcher,
    fallback_fetcher=direct_fetcher,
)

# Automatically falls back to DirectAPIFetcher if Auggie fails
raw_data = await service.fetch_ticket("PROJ-123", "jira")
```

### Fetching from Non-Auggie Platforms

For platforms not supported by Auggie MCP (Azure DevOps, Trello, Monday), `DirectAPIFetcher` is the **only** fetch path:

```python
# Azure DevOps - requires FALLBACK_AZURE_DEVOPS_* credentials
raw_data = await fetcher.fetch("MyProject/12345", "azure_devops")

# Trello - requires FALLBACK_TRELLO_* credentials
raw_data = await fetcher.fetch("abc123cardid", "trello")

# Monday - requires FALLBACK_MONDAY_* credentials
raw_data = await fetcher.fetch("1234567890", "monday")
```

---

## Configuration Reference

### Credential Keys per Platform (from AMI-22)

| Platform | Canonical Keys | Notes |
|----------|----------------|-------|
| Jira | `url`, `email`, `token` | Basic auth with API token |
| GitHub | `token` | Bearer token |
| Linear | `api_key` | Authorization header |
| Azure DevOps | `organization`, `pat` | Basic auth with PAT |
| Trello | `api_key`, `token` | Query parameters |
| Monday | `api_key` | Authorization header |

### Example Configuration

```bash
# ~/.spec-config or .spec

# Fallback credentials for platforms without Auggie MCP support
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}

FALLBACK_TRELLO_API_KEY=${TRELLO_API_KEY}
FALLBACK_TRELLO_TOKEN=${TRELLO_API_TOKEN}

FALLBACK_MONDAY_API_KEY=${MONDAY_API_KEY}

# Optional: Jira/GitHub/Linear fallback (usually via Auggie)
FALLBACK_JIRA_URL=https://company.atlassian.net
FALLBACK_JIRA_EMAIL=user@company.com
FALLBACK_JIRA_TOKEN=${JIRA_API_TOKEN}
```

---

## Architecture Notes

### Relationship with AuggieMediatedFetcher

| Aspect | AuggieMediatedFetcher | DirectAPIFetcher |
|--------|----------------------|------------------|
| Role | Primary fetcher | Fallback fetcher |
| Method | Auggie MCP tool invocation | Direct HTTP requests |
| Platforms | Jira, Linear, GitHub | All 6 platforms |
| Auth | Agent's MCP config | AuthenticationManager |
| Timeout | Via AuggieClient | Via httpx/FetchPerformanceConfig |

### Data Flow

```
1. TicketService receives fetch request
2. Tries AuggieMediatedFetcher (primary)
   └── If fails (AgentIntegrationError, AgentFetchError)
3. Falls back to DirectAPIFetcher
   ├── Gets credentials from AuthenticationManager
   ├── Selects platform-specific handler
   ├── Makes HTTP request with retry logic
   └── Returns raw API response
4. Provider normalizes raw data to GenericTicket
```

### Why Both Fetchers?

- **AuggieMediatedFetcher**: Uses existing agent MCP integrations (no credential duplication)
- **DirectAPIFetcher**: Required for non-Auggie platforms AND as fallback when agent fails

For Azure DevOps, Trello, and Monday, `DirectAPIFetcher` is the **only** fetch path since Auggie has no MCP integration for these platforms.
