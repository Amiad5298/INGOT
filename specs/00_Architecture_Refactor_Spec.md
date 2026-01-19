# Architecture Refactor Specification: Platform-Agnostic Issue Tracker Integration

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification outlines the architectural refactoring required to transform SPECFLOW from a Jira-only integration into a **platform-agnostic issue tracker system**. The goal is to support GitHub Issues, Linear, Azure DevOps, Monday.com, and Trello while maintaining backward compatibility with existing Jira functionality.

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Proposed Architecture](#2-proposed-architecture)
3. [GenericTicket Data Model](#3-genericticket-data-model)
4. [IssueTrackerProvider Interface](#4-issuetrackerrovider-interface)
5. [URL Detection & Platform Resolution](#5-url-detection--platform-resolution)
6. [Provider Registry & Factory Pattern](#6-provider-registry--factory-pattern)
7. [Configuration & Authentication](#7-configuration--authentication)
8. [Caching Strategy](#8-caching-strategy)
9. [Migration Path](#9-migration-path)
10. [File Structure](#10-file-structure)

---

## 1. Current State Analysis

### 1.1 Current Jira Integration Flow

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌──────────────┐
│ User Input  │───▶│ parse_jira_     │───▶│ fetch_ticket_   │───▶│ WorkflowState│
│ (URL/ID)    │    │ ticket()        │    │ info()          │    │ .ticket      │
└─────────────┘    └─────────────────┘    └─────────────────┘    └──────────────┘
                         │                       │
                         ▼                       ▼
                   JiraTicket             Auggie CLI Call
                   Dataclass              (No direct API)
```

### 1.2 Current Coupling Points

| Component | File | Jira Dependency |
|-----------|------|-----------------|
| CLI Entry | `specflow/cli.py` | `parse_jira_ticket()`, Jira-specific prompts |
| Workflow Runner | `specflow/workflow/runner.py` | `JiraTicket` type annotation |
| Workflow State | `specflow/workflow/state.py` | `JiraTicket` import and field |
| Config Settings | `specflow/config/settings.py` | `default_jira_project` setting |
| Integration Module | `specflow/integrations/jira.py` | All Jira logic |

### 1.3 Current Caching Mechanism

The current caching is for **integration status verification** (24-hour TTL), NOT ticket data:

```python
# From jira.py
JIRA_CACHE_DURATION = timedelta(hours=24)
# Cache keys: JIRA_CHECK_TIMESTAMP, JIRA_INTEGRATION_STATUS
```

**Important Note:** The current implementation uses Auggie CLI to fetch ticket info, not direct API calls. The refactoring must decide whether to:
- A) Continue using Auggie CLI for all platforms (simpler, depends on Auggie MCP support)
- B) Implement direct API calls per platform (more control, more code)

**Recommendation:** Implement **Option B (Direct API calls)** for maximum flexibility and independence.

---

## 2. Proposed Architecture

### 2.1 High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              SPECFLOW CLI                                     │
│  spec <ticket_url_or_id>                                                     │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         URL DETECTOR / RESOLVER                               │
│  PlatformDetector.detect(input) → Platform Enum                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         PROVIDER REGISTRY (Factory)                           │
│  ProviderRegistry.get_provider(platform) → IssueTrackerProvider              │
└──────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
          ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
          │ JiraProvider│   │GitHubProvider│  │LinearProvider│  ...
          └─────────────┘   └─────────────┘   └─────────────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     ▼
                      ┌───────────────────────────┐
                      │     GenericTicket         │
                      │  (Normalized Data Model)  │
                      └───────────────────────────┘
                                     │
                                     ▼
                      ┌───────────────────────────┐
                      │      Caching Layer        │
                      │   (Platform + ID → Data)  │
                      └───────────────────────────┘
                                     │
                                     ▼
                      ┌───────────────────────────┐
                      │     WorkflowState         │
                      │  ticket: GenericTicket    │
                      └───────────────────────────┘
```

### 2.2 SOLID Principles Application

| Principle | Application |
|-----------|-------------|
| **S** - Single Responsibility | Each provider handles ONE platform only |
| **O** - Open/Closed | New platforms added by creating new providers, no core modification |
| **L** - Liskov Substitution | All providers implement same interface, fully interchangeable |
| **I** - Interface Segregation | `IssueTrackerProvider` has minimal, focused methods |
| **D** - Dependency Inversion | Core workflow depends on abstractions, not concrete providers |

---

## 3. GenericTicket Data Model

### 3.1 Definition

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional

class Platform(Enum):
    """Supported issue tracking platforms."""
    JIRA = auto()
    GITHUB = auto()
    LINEAR = auto()
    AZURE_DEVOPS = auto()
    MONDAY = auto()
    TRELLO = auto()

class TicketStatus(Enum):
    """Normalized ticket statuses across platforms."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CLOSED = "closed"
    UNKNOWN = "unknown"

@dataclass
class GenericTicket:
    """Platform-agnostic ticket representation.

    This is the normalized data model that all platform providers
    must populate. The workflow engine only interacts with this model.

    Attributes:
        id: Unique ticket identifier (platform-specific format preserved)
        platform: Source platform
        url: Original full URL to the ticket
        title: Ticket title/summary
        description: Full description/body text
        status: Normalized status
        assignee: Assigned user (display name or username)
        labels: List of labels/tags
        created_at: Creation timestamp
        updated_at: Last update timestamp

        # Workflow-specific fields (computed)
        branch_summary: Short summary suitable for git branch name
        full_info: Complete raw ticket information for context

        # Platform-specific metadata (preserved for edge cases)
        platform_metadata: dict with platform-specific fields
    """

    # Core identifiers
    id: str
    platform: Platform
    url: str

    # Primary fields
    title: str = ""
    description: str = ""
    status: TicketStatus = TicketStatus.UNKNOWN

    # Assignment
    assignee: Optional[str] = None

    # Categorization
    labels: list[str] = field(default_factory=list)

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Workflow fields
    branch_summary: str = ""
    full_info: str = ""

    # Platform-specific raw data
    platform_metadata: dict = field(default_factory=dict)

    @property
    def display_id(self) -> str:
        """Human-readable ticket ID for display."""
        return self.id

    @property
    def safe_branch_name(self) -> str:
        """Generate safe git branch name from ticket."""
        if self.branch_summary:
            return f"{self.id.lower()}-{self.branch_summary}"
        return f"feature/{self.id.lower()}"
```

### 3.2 Backward Compatibility Bridge

To maintain backward compatibility during migration, provide a bridge:

```python
def from_jira_ticket(jira_ticket: JiraTicket) -> GenericTicket:
    """Convert legacy JiraTicket to GenericTicket."""
    return GenericTicket(
        id=jira_ticket.ticket_id,
        platform=Platform.JIRA,
        url=jira_ticket.ticket_url,
        title=jira_ticket.title,
        description=jira_ticket.description,
        branch_summary=jira_ticket.summary,
        full_info=jira_ticket.full_info,
    )

def to_jira_ticket(ticket: GenericTicket) -> JiraTicket:
    """Convert GenericTicket to legacy JiraTicket for compatibility."""
    return JiraTicket(
        ticket_id=ticket.id,
        ticket_url=ticket.url,
        summary=ticket.branch_summary,
        title=ticket.title,
        description=ticket.description,
        full_info=ticket.full_info,
    )
```


---

## 4. IssueTrackerProvider Interface

### 4.1 Abstract Base Class Definition

```python
from abc import ABC, abstractmethod
from typing import Optional

class IssueTrackerProvider(ABC):
    """Abstract base class for issue tracker integrations.

    All platform-specific providers must implement this interface.
    This ensures consistent behavior and enables the Open/Closed principle.
    """

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform this provider handles."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        pass

    @abstractmethod
    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Args:
            input_str: URL or ticket ID to check

        Returns:
            True if this provider recognizes the input format
        """
        pass

    @abstractmethod
    def parse_input(self, input_str: str) -> str:
        """Parse input and extract normalized ticket ID.

        Args:
            input_str: URL or ticket ID

        Returns:
            Normalized ticket ID (e.g., "PROJECT-123", "owner/repo#42")

        Raises:
            ValueError: If input cannot be parsed
        """
        pass

    @abstractmethod
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch ticket details from the platform.

        Args:
            ticket_id: Normalized ticket ID from parse_input()

        Returns:
            Populated GenericTicket with all available fields

        Raises:
            ConnectionError: If API is unreachable
            AuthenticationError: If credentials are invalid
            TicketNotFoundError: If ticket doesn't exist
        """
        pass

    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """Verify the integration is properly configured.

        Returns:
            Tuple of (success: bool, message: str)
        """
        pass

    def generate_branch_summary(self, ticket: GenericTicket) -> str:
        """Generate a git-friendly branch summary.

        Default implementation - can be overridden by providers.

        Args:
            ticket: The ticket to generate summary for

        Returns:
            Short lowercase hyphenated summary (max 50 chars)
        """
        import re
        summary = ticket.title.lower()[:50]
        summary = re.sub(r"[^a-z0-9-]", "-", summary)
        summary = re.sub(r"-+", "-", summary).strip("-")
        return summary
```

### 4.2 Custom Exceptions

```python
class IssueTrackerError(Exception):
    """Base exception for issue tracker operations."""
    pass

class AuthenticationError(IssueTrackerError):
    """Raised when authentication fails."""
    pass

class TicketNotFoundError(IssueTrackerError):
    """Raised when a ticket cannot be found."""
    pass

class RateLimitError(IssueTrackerError):
    """Raised when API rate limit is exceeded."""
    def __init__(self, retry_after: Optional[int] = None):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s" if retry_after else "Rate limited")

class PlatformNotSupportedError(IssueTrackerError):
    """Raised when a platform is not recognized or supported."""
    pass
```

---

## 5. URL Detection & Platform Resolution

### 5.1 URL Pattern Registry

```python
import re
from dataclasses import dataclass
from typing import Pattern

@dataclass
class PlatformPattern:
    """Defines URL patterns for a platform."""
    platform: Platform
    url_patterns: list[Pattern]
    id_patterns: list[Pattern]  # For non-URL input like "PROJECT-123"

# Platform detection patterns
PLATFORM_PATTERNS: list[PlatformPattern] = [
    PlatformPattern(
        platform=Platform.JIRA,
        url_patterns=[
            re.compile(r"https?://[^/]+\.atlassian\.net/browse/([A-Z]+-\d+)"),
            re.compile(r"https?://[^/]+/browse/([A-Z]+-\d+)"),
            re.compile(r"https?://jira\.[^/]+/browse/([A-Z]+-\d+)"),
        ],
        id_patterns=[
            re.compile(r"^([A-Z][A-Z0-9]*-\d+)$", re.IGNORECASE),
        ],
    ),
    PlatformPattern(
        platform=Platform.GITHUB,
        url_patterns=[
            re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)"),
            re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)"),
        ],
        id_patterns=[
            re.compile(r"^([^/]+/[^/]+)#(\d+)$"),  # owner/repo#123
        ],
    ),
    PlatformPattern(
        platform=Platform.LINEAR,
        url_patterns=[
            re.compile(r"https?://linear\.app/([^/]+)/issue/([A-Z]+-\d+)"),
        ],
        id_patterns=[
            re.compile(r"^([A-Z]+-\d+)$"),  # ABC-123 (same as Jira, needs disambiguation)
        ],
    ),
    PlatformPattern(
        platform=Platform.AZURE_DEVOPS,
        url_patterns=[
            re.compile(r"https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)"),
            re.compile(r"https?://([^/]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)"),
        ],
        id_patterns=[
            re.compile(r"^AB#(\d+)$"),  # AB#12345
        ],
    ),
    PlatformPattern(
        platform=Platform.MONDAY,
        url_patterns=[
            re.compile(r"https?://[^/]+\.monday\.com/boards/(\d+)/pulses/(\d+)"),
        ],
        id_patterns=[],  # Monday requires URL or board context
    ),
    PlatformPattern(
        platform=Platform.TRELLO,
        url_patterns=[
            re.compile(r"https?://trello\.com/c/([a-zA-Z0-9]+)"),
        ],
        id_patterns=[
            re.compile(r"^([a-zA-Z0-9]{8})$"),  # Trello short ID
        ],
    ),
]
```

### 5.2 Platform Detector Implementation

```python
class PlatformDetector:
    """Detects the platform from user input."""

    @staticmethod
    def detect(input_str: str) -> tuple[Platform, dict]:
        """Detect platform from input URL or ID.

        Args:
            input_str: URL or ticket ID

        Returns:
            Tuple of (Platform, extracted_groups_dict)

        Raises:
            PlatformNotSupportedError: If platform cannot be determined
        """
        input_str = input_str.strip()

        for pattern_def in PLATFORM_PATTERNS:
            # Check URL patterns first
            for pattern in pattern_def.url_patterns:
                match = pattern.match(input_str)
                if match:
                    return pattern_def.platform, match.groupdict() or dict(enumerate(match.groups()))

            # Check ID patterns
            for pattern in pattern_def.id_patterns:
                match = pattern.match(input_str)
                if match:
                    return pattern_def.platform, match.groupdict() or dict(enumerate(match.groups()))

        raise PlatformNotSupportedError(
            f"Could not detect platform from input: {input_str}\n"
            f"Supported platforms: {[p.name for p in Platform]}"
        )

    @staticmethod
    def is_url(input_str: str) -> bool:
        """Check if input is a URL."""
        return input_str.strip().startswith(("http://", "https://"))
```


---

## 6. Provider Registry & Factory Pattern

### 6.1 Registry Implementation

```python
from typing import Type

class ProviderRegistry:
    """Registry for issue tracker providers.

    Implements the Factory pattern for provider instantiation.
    New providers register themselves; core code never changes.
    """

    _providers: dict[Platform, Type[IssueTrackerProvider]] = {}
    _instances: dict[Platform, IssueTrackerProvider] = {}

    @classmethod
    def register(cls, provider_class: Type[IssueTrackerProvider]) -> Type[IssueTrackerProvider]:
        """Register a provider class (can be used as decorator).

        Args:
            provider_class: The provider class to register

        Returns:
            The same class (for decorator use)
        """
        # Create temporary instance to get platform
        temp = provider_class.__new__(provider_class)
        if hasattr(provider_class, 'PLATFORM'):
            platform = provider_class.PLATFORM
        else:
            # Fallback: instantiate to get platform property
            temp.__init__()
            platform = temp.platform

        cls._providers[platform] = provider_class
        return provider_class

    @classmethod
    def get_provider(cls, platform: Platform) -> IssueTrackerProvider:
        """Get provider instance for a platform.

        Uses singleton pattern - one instance per platform.

        Args:
            platform: The platform to get provider for

        Returns:
            Configured provider instance

        Raises:
            PlatformNotSupportedError: If no provider registered
        """
        if platform not in cls._providers:
            raise PlatformNotSupportedError(f"No provider registered for {platform.name}")

        if platform not in cls._instances:
            cls._instances[platform] = cls._providers[platform]()

        return cls._instances[platform]

    @classmethod
    def get_provider_for_input(cls, input_str: str) -> IssueTrackerProvider:
        """Get appropriate provider based on input.

        Convenience method combining detection and lookup.

        Args:
            input_str: URL or ticket ID

        Returns:
            Appropriate provider instance
        """
        platform, _ = PlatformDetector.detect(input_str)
        return cls.get_provider(platform)

    @classmethod
    def list_platforms(cls) -> list[Platform]:
        """List all registered platforms."""
        return list(cls._providers.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._providers.clear()
        cls._instances.clear()
```

### 6.2 Provider Registration Example

```python
@ProviderRegistry.register
class JiraProvider(IssueTrackerProvider):
    """Jira issue tracker provider."""

    PLATFORM = Platform.JIRA

    @property
    def platform(self) -> Platform:
        return Platform.JIRA

    @property
    def name(self) -> str:
        return "Jira"

    # ... implementation
```

---

## 7. Configuration & Authentication

### 7.1 Environment Variables Structure

```bash
# ~/.specflow-config (updated structure)

# === Global Settings ===
DEFAULT_PLATFORM=jira              # Default platform when ID is ambiguous
TICKET_CACHE_DURATION=3600         # Cache TTL in seconds (default: 1 hour)

# === Jira Configuration ===
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_API_TOKEN=your-api-token
JIRA_USER_EMAIL=your-email@company.com
JIRA_DEFAULT_PROJECT=PROJ
JIRA_INTEGRATION_STATUS=working
JIRA_CHECK_TIMESTAMP=1705680000

# === GitHub Configuration ===
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_DEFAULT_OWNER=myorg
GITHUB_DEFAULT_REPO=myrepo

# === Linear Configuration ===
LINEAR_API_KEY=lin_api_xxxxxxxxxxxx
LINEAR_DEFAULT_TEAM=ENG

# === Azure DevOps Configuration ===
AZURE_DEVOPS_ORG=myorg
AZURE_DEVOPS_PROJECT=myproject
AZURE_DEVOPS_PAT=xxxxxxxxxxxx

# === Monday.com Configuration ===
MONDAY_API_TOKEN=xxxxxxxxxxxx
MONDAY_DEFAULT_BOARD_ID=123456789

# === Trello Configuration ===
TRELLO_API_KEY=xxxxxxxxxxxx
TRELLO_API_TOKEN=xxxxxxxxxxxx
TRELLO_DEFAULT_BOARD_ID=xxxxxxxx
```

### 7.2 Authentication Manager

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class PlatformCredentials:
    """Credentials for a specific platform."""
    platform: Platform
    is_configured: bool
    credentials: dict[str, str]
    error_message: Optional[str] = None

class AuthenticationManager:
    """Manages authentication for all platforms."""

    REQUIRED_CREDENTIALS = {
        Platform.JIRA: ["JIRA_BASE_URL", "JIRA_API_TOKEN", "JIRA_USER_EMAIL"],
        Platform.GITHUB: ["GITHUB_TOKEN"],
        Platform.LINEAR: ["LINEAR_API_KEY"],
        Platform.AZURE_DEVOPS: ["AZURE_DEVOPS_ORG", "AZURE_DEVOPS_PROJECT", "AZURE_DEVOPS_PAT"],
        Platform.MONDAY: ["MONDAY_API_TOKEN"],
        Platform.TRELLO: ["TRELLO_API_KEY", "TRELLO_API_TOKEN"],
    }

    def __init__(self, config: ConfigManager):
        self.config = config

    def get_credentials(self, platform: Platform) -> PlatformCredentials:
        """Get credentials for a platform."""
        required = self.REQUIRED_CREDENTIALS.get(platform, [])
        credentials = {}
        missing = []

        for key in required:
            value = self.config.get(key, "")
            if value:
                credentials[key] = value
            else:
                missing.append(key)

        if missing:
            return PlatformCredentials(
                platform=platform,
                is_configured=False,
                credentials=credentials,
                error_message=f"Missing credentials: {', '.join(missing)}"
            )

        return PlatformCredentials(
            platform=platform,
            is_configured=True,
            credentials=credentials
        )

    def list_configured_platforms(self) -> list[Platform]:
        """List platforms with valid credentials."""
        return [p for p in Platform if self.get_credentials(p).is_configured]
```


---

## 8. Caching Strategy

### 8.1 Cache Key Design

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import json

@dataclass
class CacheKey:
    """Unique cache key for ticket data."""
    platform: Platform
    ticket_id: str

    def __str__(self) -> str:
        """Generate string key for storage."""
        return f"{self.platform.name}:{self.ticket_id}"

    @classmethod
    def from_ticket(cls, ticket: GenericTicket) -> "CacheKey":
        """Create cache key from ticket."""
        return cls(platform=ticket.platform, ticket_id=ticket.id)

@dataclass
class CachedTicket:
    """Cached ticket with metadata."""
    ticket: GenericTicket
    cached_at: datetime
    expires_at: datetime
    etag: Optional[str] = None  # For conditional requests

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at
```

### 8.2 Cache Storage Interface

```python
from abc import ABC, abstractmethod

class TicketCache(ABC):
    """Abstract cache storage for tickets."""

    @abstractmethod
    def get(self, key: CacheKey) -> Optional[CachedTicket]:
        """Retrieve cached ticket."""
        pass

    @abstractmethod
    def set(self, key: CacheKey, ticket: GenericTicket, ttl: timedelta) -> None:
        """Store ticket in cache."""
        pass

    @abstractmethod
    def delete(self, key: CacheKey) -> None:
        """Remove ticket from cache."""
        pass

    @abstractmethod
    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a platform."""
        pass

class InMemoryTicketCache(TicketCache):
    """In-memory ticket cache (default implementation)."""

    def __init__(self):
        self._cache: dict[str, CachedTicket] = {}

    def get(self, key: CacheKey) -> Optional[CachedTicket]:
        cached = self._cache.get(str(key))
        if cached and not cached.is_expired:
            return cached
        elif cached:
            del self._cache[str(key)]
        return None

    def set(self, key: CacheKey, ticket: GenericTicket, ttl: timedelta) -> None:
        now = datetime.now()
        self._cache[str(key)] = CachedTicket(
            ticket=ticket,
            cached_at=now,
            expires_at=now + ttl
        )

    def delete(self, key: CacheKey) -> None:
        self._cache.pop(str(key), None)

    def clear_platform(self, platform: Platform) -> None:
        prefix = f"{platform.name}:"
        keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_delete:
            del self._cache[key]

class FileBasedTicketCache(TicketCache):
    """File-based persistent ticket cache.

    Stores cache in ~/.specflow-cache/ directory.
    """

    def __init__(self, cache_dir: Path = Path.home() / ".specflow-cache"):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)

    def _get_path(self, key: CacheKey) -> Path:
        """Get file path for cache key."""
        safe_id = hashlib.md5(key.ticket_id.encode()).hexdigest()
        return self.cache_dir / f"{key.platform.name}_{safe_id}.json"

    # ... implementation details
```

### 8.3 Caching Decorator for Providers

```python
from functools import wraps

def cached_fetch(ttl: timedelta = timedelta(hours=1)):
    """Decorator to add caching to fetch_ticket method."""

    def decorator(fetch_method):
        @wraps(fetch_method)
        def wrapper(self: IssueTrackerProvider, ticket_id: str) -> GenericTicket:
            cache = get_global_cache()  # Singleton cache instance
            key = CacheKey(platform=self.platform, ticket_id=ticket_id)

            # Check cache
            cached = cache.get(key)
            if cached:
                return cached.ticket

            # Fetch fresh
            ticket = fetch_method(self, ticket_id)

            # Store in cache
            cache.set(key, ticket, ttl)

            return ticket
        return wrapper
    return decorator
```

---

## 9. Migration Path

### 9.1 Phase 1: Create Abstractions (Non-Breaking)

1. Create `specflow/integrations/providers/` package
2. Define `GenericTicket`, `Platform`, `IssueTrackerProvider` in base module
3. Create `JiraProvider` that wraps existing `jira.py` logic
4. Add backward-compatible type aliases

### 9.2 Phase 2: Parallel Support

1. Update `WorkflowState.ticket` to accept `GenericTicket | JiraTicket`
2. Add bridge functions for conversion
3. Update `cli.py` to use `ProviderRegistry.get_provider_for_input()`
4. Keep `parse_jira_ticket()` working for explicit Jira usage

### 9.3 Phase 3: Full Migration

1. Replace `JiraTicket` usage with `GenericTicket` throughout
2. Remove direct Jira dependencies from workflow modules
3. Deprecate legacy Jira functions (keep for 1 major version)
4. Update all tests

### 9.4 Phase 4: Add New Providers

1. Implement GitHub provider
2. Implement Linear provider
3. Implement Azure DevOps provider
4. Implement Monday provider
5. Implement Trello provider

---

## 10. File Structure

### 10.1 Proposed Directory Layout

```
specflow/
├── integrations/
│   ├── __init__.py              # Re-exports, backward compat
│   ├── auggie.py                # Unchanged
│   ├── git.py                   # Unchanged
│   ├── jira.py                  # Deprecated, calls JiraProvider
│   └── providers/
│       ├── __init__.py          # Exports base classes + registry
│       ├── base.py              # GenericTicket, IssueTrackerProvider, Platform
│       ├── exceptions.py        # Custom exceptions
│       ├── registry.py          # ProviderRegistry, PlatformDetector
│       ├── cache.py             # Caching layer
│       ├── auth.py              # AuthenticationManager
│       ├── jira_provider.py     # @ProviderRegistry.register
│       ├── github_provider.py   # @ProviderRegistry.register
│       ├── linear_provider.py   # @ProviderRegistry.register
│       ├── azure_provider.py    # @ProviderRegistry.register
│       ├── monday_provider.py   # @ProviderRegistry.register
│       └── trello_provider.py   # @ProviderRegistry.register
├── config/
│   ├── settings.py              # Add new platform settings
│   └── manager.py               # Handle new config keys
└── workflow/
    ├── state.py                 # ticket: GenericTicket
    └── runner.py                # Use provider abstraction
```

### 10.2 Import Structure

```python
# After migration, imports look like:
from specflow.integrations.providers import (
    GenericTicket,
    Platform,
    ProviderRegistry,
    IssueTrackerProvider,
)

# Backward compatible:
from specflow.integrations import JiraTicket, parse_jira_ticket  # Still works
```

---

## Appendix A: Decision Log

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| Direct API calls | Full control, no Auggie dependency for fetching | Auggie CLI proxy (simpler but limiting) |
| Singleton providers | Memory efficiency, connection reuse | Instance per request (wasteful) |
| File-based cache | Persistence across sessions | Redis (overkill), Memory only (lost on restart) |
| Decorator pattern | Provider class stays focused on API logic | Cache logic mixed in fetch (violates SRP) |
| Strategy pattern for URL detection | Extensible, testable, ordered | Giant if/else chain (unmaintainable) |

---

## Appendix B: Testing Strategy

```python
# Each provider should have:
# 1. Unit tests with mocked API responses
# 2. Integration tests with real API (skipped in CI without credentials)
# 3. URL parsing tests
# 4. Cache behavior tests

class TestJiraProvider:
    def test_can_handle_jira_url(self): ...
    def test_can_handle_ticket_id(self): ...
    def test_fetch_ticket_returns_generic_ticket(self): ...
    def test_fetch_ticket_maps_status_correctly(self): ...
    def test_fetch_ticket_handles_not_found(self): ...
    def test_fetch_ticket_uses_cache(self): ...
```

---

*End of Architecture Refactor Specification*