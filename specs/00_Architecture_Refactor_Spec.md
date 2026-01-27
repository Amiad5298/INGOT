# Architecture Refactor Specification: Platform-Agnostic Issue Tracker Integration

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification outlines the architectural refactoring required to transform SPECFLOW from a Jira-only integration into a **platform-agnostic issue tracker system**. The goal is to support GitHub Issues, Linear, Azure DevOps, Monday.com, and Trello through a unified provider abstraction.

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
9. [File Structure](#9-file-structure)

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
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class TicketType(Enum):
    """Normalized ticket types across platforms.

    Used for downstream automation such as generating semantic branch names
    (e.g., feat/, fix/, chore/) and categorizing work items.
    """
    FEATURE = "feature"      # New functionality, user stories, enhancements
    BUG = "bug"              # Defects, issues, fixes
    TASK = "task"            # General tasks, chores, housekeeping
    MAINTENANCE = "maintenance"  # Tech debt, refactoring, infrastructure
    UNKNOWN = "unknown"      # Unable to determine type

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
        type: Normalized ticket type (feature, bug, task, etc.)
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
    type: TicketType = TicketType.UNKNOWN

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
    def semantic_branch_prefix(self) -> str:
        """Get semantic branch prefix based on ticket type.

        Returns:
            Conventional prefix for git branch naming.
        """
        prefix_map = {
            TicketType.FEATURE: "feat",
            TicketType.BUG: "fix",
            TicketType.TASK: "chore",
            TicketType.MAINTENANCE: "refactor",
            TicketType.UNKNOWN: "feature",
        }
        return prefix_map.get(self.type, "feature")

    @property
    def safe_branch_name(self) -> str:
        """Generate safe git branch name from ticket.

        Uses semantic prefix based on ticket type.
        """
        prefix = self.semantic_branch_prefix
        if self.branch_summary:
            return f"{prefix}/{self.id.lower()}-{self.branch_summary}"
        return f"{prefix}/{self.id.lower()}"
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

        Providers MUST declare a class attribute `PLATFORM: Platform` to be
        registered. This avoids instantiation side-effects during registration.

        Args:
            provider_class: The provider class to register

        Returns:
            The same class (for decorator use)

        Raises:
            TypeError: If provider_class does not declare PLATFORM class attribute
        """
        if not hasattr(provider_class, 'PLATFORM'):
            raise TypeError(
                f"Provider class {provider_class.__name__} must declare a "
                f"PLATFORM class attribute (e.g., PLATFORM = Platform.JIRA)"
            )

        platform = provider_class.PLATFORM
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

### 7.1 Configuration Hierarchy

Configuration follows a **cascading hierarchy** to support developers working on multiple projects with different trackers. The system loads configuration in the following order, with earlier sources taking precedence:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONFIGURATION PRECEDENCE                              │
│                         (Highest to Lowest)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Environment Variables    ─── Highest priority (CI/CD, temporary overrides)│
│  2. Local Config (.specflow) ─── Project-specific settings                    │
│  3. Global Config (~/.specflow-config) ─── User defaults                      │
│  4. Built-in Defaults        ─── Fallback values                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 7.1.1 Local Configuration

A `.specflow` file in the current working directory (or any parent directory up to the repository root) provides project-specific configuration:

```bash
# .specflow (in project root)
DEFAULT_PLATFORM=github
GITHUB_DEFAULT_OWNER=myorg
GITHUB_DEFAULT_REPO=my-project
```

**Resolution Algorithm:**
1. Start from current working directory
2. Look for `.specflow` file
3. If not found, traverse parent directories until repository root (`.git` directory)
4. Stop at repository root or filesystem root

#### 7.1.2 Global Configuration

User-level defaults stored in the home directory:

```bash
# ~/.specflow-config
DEFAULT_PLATFORM=jira
JIRA_BASE_URL=https://company.atlassian.net
JIRA_API_TOKEN=xxxxx
# ... other platform credentials
```

#### 7.1.3 Configuration Manager Implementation

```python
from pathlib import Path
from typing import Optional
import os

class ConfigManager:
    """Manages configuration with cascading hierarchy."""

    LOCAL_CONFIG_NAME = ".specflow"
    GLOBAL_CONFIG_NAME = ".specflow-config"

    def __init__(self):
        self._config: dict[str, str] = {}
        self._local_config_path: Optional[Path] = None
        self._global_config_path: Path = Path.home() / self.GLOBAL_CONFIG_NAME

    def load(self) -> None:
        """Load configuration from all sources in precedence order."""
        # Start with built-in defaults
        self._config = self._get_defaults()

        # Load global config (lowest priority file-based config)
        self._load_file(self._global_config_path)

        # Load local config (higher priority)
        local_path = self._find_local_config()
        if local_path:
            self._local_config_path = local_path
            self._load_file(local_path)

        # Environment variables override everything
        self._load_environment()

    def _find_local_config(self) -> Optional[Path]:
        """Find local .specflow config by traversing up from CWD."""
        current = Path.cwd()
        while True:
            config_path = current / self.LOCAL_CONFIG_NAME
            if config_path.exists():
                return config_path

            # Stop at repository root
            if (current / ".git").exists():
                break

            parent = current.parent
            if parent == current:  # Reached filesystem root
                break
            current = parent

        return None

    def _load_file(self, path: Path) -> None:
        """Load key=value pairs from config file."""
        if not path.exists():
            return

        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    self._config[key.strip()] = value.strip()

    def _load_environment(self) -> None:
        """Override config with environment variables."""
        # Only load known config keys from environment
        known_keys = set(self._config.keys())
        for key in known_keys:
            env_value = os.environ.get(key)
            if env_value is not None:
                self._config[key] = env_value

    def _get_defaults(self) -> dict[str, str]:
        """Return built-in default values."""
        return {
            "DEFAULT_PLATFORM": "",
            "TICKET_CACHE_DURATION": "3600",
        }

    def get(self, key: str, default: str = "") -> str:
        """Get configuration value."""
        return self._config.get(key, default)

    def get_config_source(self, key: str) -> str:
        """Return the source of a config value (for debugging)."""
        if key in os.environ:
            return "environment"
        if self._local_config_path:
            # Check if key exists in local config
            with open(self._local_config_path) as f:
                for line in f:
                    if line.strip().startswith(f"{key}="):
                        return f"local ({self._local_config_path})"
        return f"global ({self._global_config_path})"
```

### 7.2 Environment Variables Structure

```bash
# ~/.specflow-config (global user configuration)

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

## 9. User Interaction Abstraction

### 9.1 Design Principle

Providers must **never** call `print()` or `input()` directly. This restriction:
- Makes providers testable in isolation
- Enables CI/CD usage without interactive prompts
- Allows for different UI implementations (CLI, GUI, web)

### 9.2 UserInteractionInterface

```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from dataclasses import dataclass

T = TypeVar('T')

@dataclass
class SelectOption(Generic[T]):
    """An option for user selection."""
    value: T
    label: str
    description: str = ""


class UserInteractionInterface(ABC):
    """Abstract interface for user interactions.

    All user-facing prompts and confirmations must go through this interface.
    Providers receive an instance via dependency injection.
    """

    @abstractmethod
    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True
    ) -> T | None:
        """Present options to user and get selection.

        Args:
            options: List of options to present
            prompt: Message to display to user
            allow_cancel: If True, user can cancel (returns None)

        Returns:
            Selected option value, or None if cancelled
        """
        pass

    @abstractmethod
    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True
    ) -> str | None:
        """Prompt user for text input.

        Args:
            message: Prompt message to display
            default: Default value if user enters nothing
            required: If True, empty input is not accepted

        Returns:
            User input string, or None if cancelled
        """
        pass

    @abstractmethod
    def confirm(
        self,
        message: str,
        default: bool = False
    ) -> bool:
        """Ask user for yes/no confirmation.

        Args:
            message: Question to ask
            default: Default answer if user presses Enter

        Returns:
            True for yes, False for no
        """
        pass

    @abstractmethod
    def display_message(
        self,
        message: str,
        level: str = "info"
    ) -> None:
        """Display a message to the user.

        Args:
            message: Message to display
            level: One of "info", "warning", "error", "success"
        """
        pass


class CLIUserInteraction(UserInteractionInterface):
    """Command-line implementation of user interaction."""

    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True
    ) -> T | None:
        print(f"\n{prompt}")
        for i, opt in enumerate(options, 1):
            desc = f" - {opt.description}" if opt.description else ""
            print(f"  [{i}] {opt.label}{desc}")

        if allow_cancel:
            print(f"  [0] Cancel")

        while True:
            try:
                choice = input("\nEnter selection: ").strip()
                if not choice:
                    continue

                idx = int(choice)
                if allow_cancel and idx == 0:
                    return None
                if 1 <= idx <= len(options):
                    return options[idx - 1].value

                print(f"Invalid selection. Enter 1-{len(options)}")
            except ValueError:
                print("Please enter a number")
            except KeyboardInterrupt:
                return None

    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True
    ) -> str | None:
        default_hint = f" [{default}]" if default else ""
        try:
            while True:
                result = input(f"{message}{default_hint}: ").strip()
                if not result and default:
                    return default
                if result or not required:
                    return result
                print("This field is required.")
        except KeyboardInterrupt:
            return None

    def confirm(
        self,
        message: str,
        default: bool = False
    ) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        try:
            result = input(f"{message} {hint}: ").strip().lower()
            if not result:
                return default
            return result in ("y", "yes", "true", "1")
        except KeyboardInterrupt:
            return False

    def display_message(
        self,
        message: str,
        level: str = "info"
    ) -> None:
        prefixes = {
            "info": "ℹ️ ",
            "warning": "⚠️ ",
            "error": "❌ ",
            "success": "✅ ",
        }
        print(f"{prefixes.get(level, '')}{message}")


class NonInteractiveUserInteraction(UserInteractionInterface):
    """Non-interactive implementation for CI/CD and testing.

    Returns defaults or raises errors for required interactions.
    """

    def __init__(self, fail_on_interaction: bool = True):
        self.fail_on_interaction = fail_on_interaction

    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True
    ) -> T | None:
        if self.fail_on_interaction:
            raise RuntimeError(
                f"Interactive selection required but running in non-interactive mode. "
                f"Prompt: {prompt}"
            )
        return options[0].value if options else None

    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True
    ) -> str | None:
        if required and not default and self.fail_on_interaction:
            raise RuntimeError(
                f"Required text input but running in non-interactive mode. "
                f"Prompt: {message}"
            )
        return default

    def confirm(
        self,
        message: str,
        default: bool = False
    ) -> bool:
        return default

    def display_message(
        self,
        message: str,
        level: str = "info"
    ) -> None:
        # Optionally log to stderr or logging framework
        pass
```

### 9.3 Provider Integration

Providers that need user interaction receive the interface via constructor injection:

```python
class ProviderRegistry:
    """Registry for issue tracker providers."""

    _user_interaction: UserInteractionInterface = CLIUserInteraction()

    @classmethod
    def set_user_interaction(cls, ui: UserInteractionInterface) -> None:
        """Set the user interaction implementation."""
        cls._user_interaction = ui

    @classmethod
    def get_user_interaction(cls) -> UserInteractionInterface:
        """Get the current user interaction implementation."""
        return cls._user_interaction
```

### 9.4 Usage Example: Platform Disambiguation

```python
def get_provider_for_input(input_str: str) -> IssueTrackerProvider:
    """Get appropriate provider, prompting user if ambiguous."""
    try:
        platform, _ = PlatformDetector.detect(input_str)
        return ProviderRegistry.get_provider(platform)
    except AmbiguousPlatformError as e:
        # Input matches multiple platforms (e.g., "ABC-123" matches Jira and Linear)
        ui = ProviderRegistry.get_user_interaction()

        options = [
            SelectOption(value=p, label=p.name, description=f"Use {p.name} to fetch {input_str}")
            for p in e.possible_platforms
        ]

        selected = ui.select_option(
            options=options,
            prompt=f"The identifier '{input_str}' is ambiguous. Select platform:",
            allow_cancel=True
        )

        if selected is None:
            raise UserCancelledError("Platform selection cancelled")

        return ProviderRegistry.get_provider(selected)
```

---

## 10. File Structure

### 10.1 Directory Layout

```
spec/
├── integrations/
│   ├── __init__.py              # Re-exports
│   ├── auggie.py                # Auggie AI client
│   ├── git.py                   # Git integration
│   └── providers/
│       ├── __init__.py          # Exports base classes + registry
│       ├── base.py              # GenericTicket, IssueTrackerProvider, Platform
│       ├── exceptions.py        # Custom exceptions
│       ├── registry.py          # ProviderRegistry
│       ├── jira.py              # @ProviderRegistry.register
│       ├── github.py            # @ProviderRegistry.register
│       ├── linear.py            # @ProviderRegistry.register
│       ├── azure_devops.py      # @ProviderRegistry.register
│       ├── monday.py            # @ProviderRegistry.register
│       └── trello.py            # @ProviderRegistry.register
│   └── fetchers/
│       ├── __init__.py          # Exports fetcher classes
│       ├── base.py              # TicketFetcher ABC
│       └── auggie.py            # AuggieMediatedFetcher
├── config/
│   ├── settings.py              # Platform settings
│   └── manager.py               # ConfigManager
└── workflow/
    ├── state.py                 # ticket: GenericTicket
    └── runner.py                # Use provider abstraction
```

### 10.2 Import Structure

```python
from spec.integrations.providers import (
    GenericTicket,
    Platform,
    ProviderRegistry,
    IssueTrackerProvider,
)
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
