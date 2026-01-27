# Implementation Plan: AMI-32 - Implement TicketService Orchestration Layer

**Ticket:** [AMI-32](https://linear.app/amiadspec/issue/AMI-32/implement-ticketservice-orchestration-layer)
**Status:** Draft
**Date:** 2026-01-27

---

## Summary

This ticket implements the `TicketService` class, the central orchestration layer that coordinates between `ProviderRegistry`, `TicketFetcher` implementations (AuggieMediatedFetcher/DirectAPIFetcher), and the `TicketCache`. TicketService is the single entry point for all ticket fetching operations in the spec system.

The orchestration flow:
1. **Detect platform** → Use `ProviderRegistry.get_provider_for_input()` to identify the platform
2. **Parse input** → Use `provider.parse_input()` to extract normalized ticket ID
3. **Check cache** → If caching enabled, check for unexpired cached result
4. **Fetch raw data** → Use primary fetcher (AuggieMediatedFetcher), fallback to secondary (DirectAPIFetcher)
5. **Normalize** → Use `provider.normalize(raw_data, ticket_id)` to convert to GenericTicket
6. **Cache result** → Store normalized ticket in cache with TTL
7. **Return** → Return the GenericTicket to caller

**Key Architecture Points:**
- **Caching is owned by TicketService** - not by providers or fetchers
- **Primary/Fallback pattern** - AuggieMediatedFetcher is primary; DirectAPIFetcher is fallback
- **6 Platform Support** - Jira, Linear, GitHub, Azure DevOps, Monday, Trello
- **DirectAPIFetcher-only platforms** - Azure DevOps, Monday, Trello have no Auggie MCP support

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SPECFLOW CLI                                        │
│  spec <ticket_url_or_id>                                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          TicketService (THIS TICKET)                             │
│                                                                                  │
│   async def get_ticket(input_str: str) -> GenericTicket                         │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  1. Detect platform     → ProviderRegistry.get_provider_for_input()    │   │
│   │  2. Parse input         → provider.parse_input(input_str)               │   │
│   │  3. Check cache         → cache.get(CacheKey(platform, ticket_id))     │   │
│   │     └─ if cached: return cached ticket                                  │   │
│   │  4. Fetch raw data      → primary_fetcher.fetch() or fallback          │   │
│   │  5. Normalize           → provider.normalize(raw_data, ticket_id)       │   │
│   │  6. Cache result        → cache.set(ticket, ttl)                        │   │
│   │  7. Return GenericTicket                                                 │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                │                              │                        │
       ┌────────┴────────┐           ┌─────────┴─────────┐      ┌──────┴──────┐
       ▼                 ▼           ▼                   ▼      ▼             ▼
┌─────────────┐   ┌─────────────┐  ┌───────────────┐  ┌──────────────┐ ┌────────────┐
│ProviderReg- │   │TicketCache │  │AuggieMedi-   │  │DirectAPI-   │ │ Providers │
│istry        │   │(AMI-23)    │  │atedFetcher   │  │Fetcher      │ │(AMI-18-21)│
│(AMI-17)     │   │            │  │(AMI-30)      │  │(AMI-31)     │ │           │
│             │   │ In-memory/ │  │              │  │             │ │Jira,Linear│
│detect+get   │   │ File-based │  │PRIMARY PATH  │  │FALLBACK PATH│ │GitHub,ADO,│
│provider     │   │ w/ TTL     │  │Jira,Linear,GH│  │ALL 6 plats  │ │Monday,    │
│             │   │            │  │              │  │             │ │Trello     │
└─────────────┘   └─────────────┘  └───────────────┘  └──────────────┘ └────────────┘
```

### Orchestration Flow Detail

```
get_ticket("PROJ-123" or "https://jira.example.com/browse/PROJ-123")
    │
    ├─→ Step 1: ProviderRegistry.get_provider_for_input(input_str)
    │           └── returns JiraProvider (or raises PlatformNotSupportedError)
    │
    ├─→ Step 2: provider.parse_input(input_str)
    │           └── returns "PROJ-123" (normalized ticket ID)
    │
    ├─→ Step 3: cache.get(CacheKey(Platform.JIRA, "PROJ-123"))
    │           └── returns GenericTicket if cached and not expired
    │           └── returns None if cache miss or expired
    │
    ├─→ Step 4: Fetch (if cache miss)
    │   ├─→ Try: primary_fetcher.fetch("PROJ-123", "jira")
    │   │        └── AuggieMediatedFetcher for Jira/Linear/GitHub
    │   │
    │   └─→ On AgentIntegrationError/AgentFetchError/AgentResponseParseError:
    │        └── fallback_fetcher.fetch("PROJ-123", "jira")
    │            └── DirectAPIFetcher for all 6 platforms
    │
    ├─→ Step 5: provider.normalize(raw_data, ticket_id="PROJ-123")
    │           └── returns GenericTicket
    │
    ├─→ Step 6: cache.set(ticket, ttl=default_ttl)
    │
    └─→ Step 7: return GenericTicket
```

### Key Design Decisions

1. **TicketService Owns Caching** - Caching is an orchestration concern, not a provider/fetcher concern
2. **String-Based Fetcher Interface** - Uses `fetch(ticket_id, platform_string)` for simplicity (per AMI-30)
3. **Primary/Fallback Pattern** - AuggieMediatedFetcher → DirectAPIFetcher with automatic fallback
4. **Graceful Degradation** - DirectAPIFetcher can function without agent availability
5. **Resource Management** - TicketService owns DirectAPIFetcher lifecycle (async context manager or explicit close)
6. **Pass ticket_id to normalize()** - Some providers (e.g., MondayProvider) need context for URL construction
7. **No Direct AuthenticationManager Usage** - TicketService doesn't use AuthenticationManager; it's passed to DirectAPIFetcher

### Exception Mapping (from AMI-31)

DirectAPIFetcher maps handler-specific exceptions to public API exceptions. TicketService only handles public exceptions:

| Handler Exception | Mapped To | Description |
|------------------|-----------|-------------|
| `CredentialValidationError` | `AgentIntegrationError` | Missing credential keys |
| `TicketIdFormatError` | `AgentIntegrationError` | Invalid ticket ID format |
| `PlatformApiError` | `AgentFetchError` | Platform API logical error |
| `PlatformNotFoundError` | `AgentFetchError` | Ticket not found |

TicketService triggers fallback on these public exceptions:
- `AgentIntegrationError` - Platform not configured/available
- `AgentFetchError` - Tool execution failed (timeout, CLI error, API error)
- `AgentResponseParseError` - Invalid JSON or missing required fields

---

## Components to Create

### New File: `spec/integrations/ticket_service.py`

| Component | Purpose |
|-----------|---------|
| `TicketService` class | Main orchestration service |
| `create_ticket_service()` factory | Convenience function for default setup |

### File to Modify: `spec/integrations/__init__.py`

Add export for `TicketService` and `create_ticket_service` in `__all__`.

---

## Implementation Steps

### Step 1: Create TicketService Class with Constructor

```python
"""TicketService orchestration layer for ticket fetching.

This module provides the central orchestration service that coordinates:
- ProviderRegistry for platform detection and normalization
- TicketFetcher implementations for data retrieval
- TicketCache for result caching

Example usage:
    service = await create_ticket_service()
    ticket = await service.get_ticket("PROJ-123")
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from spec.integrations.providers import Platform, ProviderRegistry
from spec.integrations.providers.base import GenericTicket
from spec.integrations.fetchers import (
    TicketFetcher,
    AuggieMediatedFetcher,
    DirectAPIFetcher,
    AgentIntegrationError,
    AgentFetchError,
    AgentResponseParseError,
)
from spec.integrations.cache import TicketCache, InMemoryTicketCache, CacheKey

if TYPE_CHECKING:
    from spec.integrations.auth import AuthenticationManager
    from spec.auggie.client import AuggieClient
    from spec.config import ConfigManager

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL = timedelta(hours=1)


class TicketService:
    """Orchestrates ticket fetching with caching and fallback.

    This is the primary entry point for fetching tickets. It coordinates:
    1. Platform detection via ProviderRegistry
    2. Input parsing via provider.parse_input()
    3. Cache lookup before fetching
    4. Primary/fallback fetcher execution
    5. Normalization via provider.normalize()
    6. Cache storage after successful fetch

    Resource Management:
        If using DirectAPIFetcher as fallback, the caller is responsible
        for proper cleanup. Use the async context manager pattern or
        call close() explicitly when done.

    Example:
        async with await create_ticket_service() as service:
            ticket = await service.get_ticket("PROJ-123")
    """

    def __init__(
        self,
        primary_fetcher: TicketFetcher,
        fallback_fetcher: TicketFetcher | None = None,
        cache: TicketCache | None = None,
        default_ttl: timedelta = DEFAULT_CACHE_TTL,
    ) -> None:
        """Initialize TicketService with fetchers and optional cache.

        Args:
            primary_fetcher: Primary fetcher (typically AuggieMediatedFetcher)
            fallback_fetcher: Optional fallback (typically DirectAPIFetcher)
            cache: Optional cache implementation (defaults to InMemoryTicketCache)
            default_ttl: Default cache TTL (default: 1 hour)
        """
        self._primary = primary_fetcher
        self._fallback = fallback_fetcher
        self._cache = cache
        self._default_ttl = default_ttl
        self._closed = False
```

### Step 2: Implement get_ticket() Orchestration Method

```python
    async def get_ticket(
        self,
        input_str: str,
        *,
        skip_cache: bool = False,
        ttl: timedelta | None = None,
    ) -> GenericTicket:
        """Fetch and normalize a ticket from any supported platform.

        This is the main entry point for ticket retrieval. It:
        1. Detects the platform from the input
        2. Parses the input to extract ticket ID
        3. Checks cache (unless skip_cache=True)
        4. Fetches via primary fetcher with fallback
        5. Normalizes to GenericTicket
        6. Caches the result

        Args:
            input_str: Ticket URL or ID (e.g., "PROJ-123", "https://...")
            skip_cache: If True, bypass cache lookup (still caches result)
            ttl: Custom TTL for this ticket (defaults to self._default_ttl)

        Returns:
            Normalized GenericTicket

        Raises:
            PlatformNotSupportedError: If platform cannot be detected
            ValueError: If input cannot be parsed
            TicketFetchError: If both fetchers fail
        """
        if self._closed:
            raise RuntimeError("TicketService has been closed")

        # Step 1: Detect platform and get provider
        provider = ProviderRegistry.get_provider_for_input(input_str)
        platform = provider.PLATFORM

        # Step 2: Parse input to get normalized ticket ID
        ticket_id = provider.parse_input(input_str)
        logger.debug(f"Parsed {input_str} -> platform={platform.name}, id={ticket_id}")

        # Step 3: Check cache (if enabled and not skipped)
        if self._cache and not skip_cache:
            cache_key = CacheKey(platform, ticket_id)
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached
            logger.debug(f"Cache miss for {cache_key}")

        # Step 4: Fetch raw data with primary/fallback pattern
        raw_data = await self._fetch_with_fallback(ticket_id, platform)

        # Step 5: Normalize using provider
        ticket = provider.normalize(raw_data, ticket_id)

        # Step 6: Cache the result
        if self._cache:
            effective_ttl = ttl or self._default_ttl
            self._cache.set(ticket, ttl=effective_ttl)
            logger.debug(f"Cached ticket {ticket.id} with TTL {effective_ttl}")

        return ticket

    async def _fetch_with_fallback(
        self,
        ticket_id: str,
        platform: Platform,
    ) -> dict:
        """Fetch raw ticket data with automatic fallback.

        Tries primary fetcher first. If it fails with agent-related errors
        AND a fallback is configured, retries with the fallback fetcher.

        Args:
            ticket_id: Normalized ticket ID
            platform: Target platform

        Returns:
            Raw ticket data dict

        Raises:
            TicketFetchError: If all fetchers fail
            PlatformNotSupportedError: If no fetcher supports the platform
        """
        platform_str = platform.name.lower()

        # For platforms not supported by primary, go directly to fallback
        if not self._primary.supports_platform(platform):
            if self._fallback and self._fallback.supports_platform(platform):
                logger.info(f"Primary fetcher doesn't support {platform.name}, using fallback")
                return await self._fallback.fetch(ticket_id, platform_str)
            raise PlatformNotSupportedError(
                f"No fetcher supports platform {platform.name}"
            )

        # Try primary fetcher
        try:
            return await self._primary.fetch(ticket_id, platform_str)
        except (AgentIntegrationError, AgentFetchError, AgentResponseParseError) as e:
            # Only fallback on agent-specific errors
            if self._fallback and self._fallback.supports_platform(platform):
                logger.warning(
                    f"Primary fetch failed for {ticket_id} on {platform.name}: {e}. "
                    f"Falling back to {self._fallback.name}"
                )
                return await self._fallback.fetch(ticket_id, platform_str)
            # No fallback available, re-raise
            raise
```

### Step 3: Implement Helper Methods

```python
    def invalidate_cache(self, platform: Platform, ticket_id: str) -> None:
        """Invalidate a specific cached ticket.

        Args:
            platform: Ticket platform
            ticket_id: Ticket ID to invalidate
        """
        if not self._cache:
            return
        cache_key = CacheKey(platform, ticket_id)
        self._cache.invalidate(cache_key)

    def clear_cache(self, platform: Platform | None = None) -> None:
        """Clear cached tickets.

        Args:
            platform: If specified, only clear tickets for this platform.
                     If None, clear all cached tickets.
        """
        if not self._cache:
            return
        if platform:
            self._cache.clear_platform(platform)
        else:
            self._cache.clear()

    @property
    def has_cache(self) -> bool:
        """Whether caching is enabled."""
        return self._cache is not None

    @property
    def primary_fetcher_name(self) -> str:
        """Name of the primary fetcher."""
        return self._primary.name

    @property
    def fallback_fetcher_name(self) -> str | None:
        """Name of the fallback fetcher, or None if not configured."""
        return self._fallback.name if self._fallback else None
```

### Step 4: Implement Resource Management (Async Context Manager)

```python
    async def close(self) -> None:
        """Close the service and release resources.

        This should be called when done using the service to ensure
        proper cleanup of HTTP clients and other resources.
        """
        if self._closed:
            return

        self._closed = True

        # Close fallback fetcher if it has a close method (DirectAPIFetcher)
        if self._fallback and hasattr(self._fallback, 'close'):
            await self._fallback.close()
            logger.debug(f"Closed fallback fetcher: {self._fallback.name}")

    async def __aenter__(self) -> "TicketService":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and close resources."""
        await self.close()
```

### Step 5: Create Factory Function

```python
async def create_ticket_service(
    auggie_client: AuggieClient | None = None,
    auth_manager: AuthenticationManager | None = None,
    config_manager: ConfigManager | None = None,
    cache: TicketCache | None = None,
    cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    enable_fallback: bool = True,
) -> TicketService:
    """Create a TicketService with standard configuration.

    Factory function that creates a TicketService with:
    - AuggieMediatedFetcher as primary (if auggie_client provided)
    - DirectAPIFetcher as fallback (if enable_fallback=True and auth_manager provided)
    - InMemoryTicketCache (if no cache provided)

    Resource Management:
        The returned TicketService owns the lifecycle of the DirectAPIFetcher.
        Use as an async context manager or call close() explicitly:

            async with await create_ticket_service(...) as service:
                ticket = await service.get_ticket("PROJ-123")

    Credential Flow:
        TicketService does NOT use AuthenticationManager directly.
        AuthenticationManager is passed to DirectAPIFetcher:

            TicketService → DirectAPIFetcher → AuthenticationManager → ConfigManager

    Args:
        auggie_client: AuggieClient for agent-mediated fetching.
            If None, DirectAPIFetcher becomes the only fetcher.
        auth_manager: AuthenticationManager for DirectAPIFetcher.
            Required if enable_fallback=True or auggie_client is None.
        config_manager: Optional ConfigManager for AuggieMediatedFetcher.
        cache: Optional custom cache implementation.
            Defaults to InMemoryTicketCache with max_size=1000.
        cache_ttl: Default cache TTL (default: 1 hour).
        enable_fallback: Whether to enable DirectAPIFetcher fallback.

    Returns:
        Configured TicketService ready for use

    Raises:
        ValueError: If configuration is invalid (no fetchers configured)

    Example:
        from spec.auggie.client import AuggieClient
        from spec.integrations.auth import get_auth_manager

        auggie = AuggieClient()
        auth_manager = await get_auth_manager()

        async with await create_ticket_service(
            auggie_client=auggie,
            auth_manager=auth_manager,
        ) as service:
            ticket = await service.get_ticket("PROJ-123")
    """
    primary: TicketFetcher | None = None
    fallback: TicketFetcher | None = None

    # Configure primary fetcher
    if auggie_client:
        primary = AuggieMediatedFetcher(
            auggie_client=auggie_client,
            config_manager=config_manager,
        )

    # Configure fallback fetcher (TicketService owns its lifecycle)
    if enable_fallback and auth_manager:
        fallback = DirectAPIFetcher(auth_manager=auth_manager)

    # If no primary, use fallback as primary
    if not primary and fallback:
        primary = fallback
        fallback = None

    if not primary:
        raise ValueError(
            "Cannot create TicketService: no fetchers configured. "
            "Provide auggie_client or auth_manager."
        )

    # Configure cache
    if cache is None:
        cache = InMemoryTicketCache(
            default_ttl=cache_ttl,
            max_size=1000,
        )

    return TicketService(
        primary_fetcher=primary,
        fallback_fetcher=fallback,
        cache=cache,
        default_ttl=cache_ttl,
    )
```

### Step 6: Update Package Exports

Update `spec/integrations/__init__.py`:

```python
from spec.integrations.ticket_service import TicketService, create_ticket_service

__all__ = [
    # ... existing exports ...
    "TicketService",
    "create_ticket_service",
]
```

---

## Integration Points

### AMI-17: ProviderRegistry

TicketService uses ProviderRegistry for platform detection and provider access:

```python
# Platform detection
provider = ProviderRegistry.get_provider_for_input(input_str)

# Parse input
ticket_id = provider.parse_input(input_str)

# Normalize raw data
ticket = provider.normalize(raw_data, ticket_id)
```

### AMI-29: TicketFetcher Abstraction

TicketService depends on the TicketFetcher interface for fetcher polymorphism:

```python
class TicketFetcher(ABC):
    @property
    def name(self) -> str: ...
    def supports_platform(self, platform: Platform) -> bool: ...
    async def fetch(self, ticket_id: str, platform: str) -> dict: ...
```

### AMI-30: AuggieMediatedFetcher

Primary fetcher for Jira, Linear, and GitHub:

```python
# Supported platforms
Platform.JIRA, Platform.LINEAR, Platform.GITHUB

# Exception types that trigger fallback
AgentIntegrationError  # Agent not available/configured
AgentFetchError        # Tool execution failed
AgentResponseParseError  # Malformed JSON response
```

### AMI-31: DirectAPIFetcher

Fallback fetcher supporting all 6 platforms:

```python
# Supports ALL platforms
Platform.JIRA, Platform.LINEAR, Platform.GITHUB,
Platform.AZURE_DEVOPS, Platform.MONDAY, Platform.TRELLO

# Resource management required
async with DirectAPIFetcher(auth_manager) as fetcher:
    data = await fetcher.fetch(ticket_id, platform)
```

### AMI-23: TicketCache

Caching layer integration:

```python
from spec.integrations.cache import TicketCache, CacheKey, InMemoryTicketCache

# Cache lookup (returns GenericTicket | None)
cache_key = CacheKey(platform, ticket_id)
cached = cache.get(cache_key)

# Cache storage (ticket contains platform+id for key generation)
cache.set(ticket, ttl=timedelta(hours=1))

# Cache management (all return None)
cache.invalidate(cache_key)
cache.clear_platform(platform)
cache.clear()

# ETag support for conditional requests
etag = cache.get_etag(cache_key)
cache.set(ticket, ttl=timedelta(hours=1), etag="W/\"abc123\"")
```

---

## Acceptance Criteria Checklist

### Core Functionality

- [ ] `TicketService` class created with constructor accepting primary/fallback fetchers and cache
- [ ] `get_ticket(input_str)` method orchestrates the full flow
- [ ] Platform detection via `ProviderRegistry.get_provider_for_input()`
- [ ] Input parsing via `provider.parse_input()`
- [ ] Cache check before fetch when cache is enabled
- [ ] Cache bypass with `skip_cache=True` parameter
- [ ] Primary/fallback pattern with automatic fallback on agent errors
- [ ] Normalization via `provider.normalize(raw_data, ticket_id)`
- [ ] Cache storage after successful fetch with configurable TTL
- [ ] Custom TTL per-request via `ttl` parameter

### Error Handling

- [ ] `AgentIntegrationError` triggers fallback (includes mapped `CredentialValidationError`, `TicketIdFormatError`)
- [ ] `AgentFetchError` triggers fallback (includes mapped `PlatformApiError`, `PlatformNotFoundError`)
- [ ] `AgentResponseParseError` triggers fallback
- [ ] `PlatformNotSupportedError` raised when no fetcher supports platform
- [ ] Handler-specific exceptions never leak to caller (mapped by DirectAPIFetcher per AMI-31)

### Platform Support

- [ ] Jira: AuggieMediatedFetcher (primary) → DirectAPIFetcher (fallback)
- [ ] Linear: AuggieMediatedFetcher (primary) → DirectAPIFetcher (fallback)
- [ ] GitHub: AuggieMediatedFetcher (primary) → DirectAPIFetcher (fallback)
- [ ] Azure DevOps: DirectAPIFetcher only (no Auggie MCP support)
- [ ] Monday: DirectAPIFetcher only (no Auggie MCP support)
- [ ] Trello: DirectAPIFetcher only (no Auggie MCP support)

### Resource & Lifecycle Management (per AMI-31 comments)

- [ ] TicketService owns DirectAPIFetcher lifecycle (not caller)
- [ ] Async context manager support (`async with service: ...`)
- [ ] Explicit `close()` method for cleanup
- [ ] `close()` method closes fallback fetcher if it has `close()` method
- [ ] Service raises `RuntimeError` if used after `close()`

### Cache Management

- [ ] `invalidate_cache(platform, ticket_id)` removes specific ticket (returns None)
- [ ] `clear_cache()` removes all cached tickets (returns None)
- [ ] `clear_cache(platform)` removes tickets for specific platform (returns None)
- [ ] `has_cache` property indicates if caching enabled

### Factory Function

- [ ] `create_ticket_service()` creates configured service
- [ ] Accepts optional `auggie_client` for agent-mediated fetching
- [ ] Accepts optional `auth_manager` for direct API fetching
- [ ] Falls back to DirectAPIFetcher-only if no `auggie_client`
- [ ] Creates InMemoryTicketCache by default
- [ ] Raises `ValueError` if no fetchers can be configured

---

## Example Usage

### Basic Usage with Default Setup

```python
from spec.auggie.client import AuggieClient
from spec.integrations.auth import get_auth_manager
from spec.integrations import create_ticket_service

async def main():
    auggie = AuggieClient()
    auth_manager = await get_auth_manager()

    async with await create_ticket_service(
        auggie_client=auggie,
        auth_manager=auth_manager,
    ) as service:
        # Fetch from Jira (uses Auggie with DirectAPI fallback)
        jira_ticket = await service.get_ticket("PROJ-123")

        # Fetch from Linear URL
        linear_ticket = await service.get_ticket(
            "https://linear.app/team/issue/ENG-456"
        )

        # Fetch from Azure DevOps (DirectAPI only)
        ado_ticket = await service.get_ticket(
            "https://dev.azure.com/org/project/_workitems/edit/789"
        )

        print(f"Jira: {jira_ticket.title}")
        print(f"Linear: {linear_ticket.title}")
        print(f"ADO: {ado_ticket.title}")
```

### DirectAPI-Only Mode (No Agent)

```python
from spec.integrations.auth import get_auth_manager
from spec.integrations.fetchers import DirectAPIFetcher
from spec.integrations.cache import InMemoryTicketCache
from spec.integrations import TicketService

async def main():
    auth_manager = await get_auth_manager()

    async with DirectAPIFetcher(auth_manager) as fetcher:
        service = TicketService(
            primary_fetcher=fetcher,
            cache=InMemoryTicketCache(),
        )

        ticket = await service.get_ticket("PROJ-123")
```

### Cache Bypass and Custom TTL

```python
async with await create_ticket_service(...) as service:
    # Force fresh fetch (bypasses cache, but still caches result)
    fresh_ticket = await service.get_ticket("PROJ-123", skip_cache=True)

    # Custom TTL for volatile tickets
    volatile_ticket = await service.get_ticket(
        "PROJ-456",
        ttl=timedelta(minutes=5),
    )
```

### Cache Management

```python
from spec.integrations.providers import Platform

async with await create_ticket_service(...) as service:
    # Fetch and cache
    ticket = await service.get_ticket("PROJ-123")

    # Invalidate specific ticket
    service.invalidate_cache(Platform.JIRA, "PROJ-123")

    # Clear all Jira tickets
    service.clear_cache(Platform.JIRA)

    # Clear entire cache
    service.clear_cache()
```

### Error Handling

```python
from spec.integrations.fetchers import (
    TicketFetchError,
    PlatformNotSupportedError,
)

async with await create_ticket_service(...) as service:
    try:
        ticket = await service.get_ticket("PROJ-123")
    except PlatformNotSupportedError:
        print("Unknown platform or unsupported input format")
    except TicketFetchError as e:
        print(f"Failed to fetch ticket: {e}")
    except ValueError as e:
        print(f"Invalid input format: {e}")
```

---

## Testing Strategy

### Unit Tests: `tests/integrations/test_ticket_service.py`

#### Test Categories

1. **Constructor Tests**
   - Test initialization with primary fetcher only
   - Test initialization with primary and fallback fetchers
   - Test initialization with cache
   - Test initialization without cache

2. **get_ticket() Tests**
   - Test successful fetch from primary fetcher
   - Test cache hit returns cached ticket
   - Test cache miss fetches from fetcher
   - Test skip_cache bypasses cache lookup
   - Test custom TTL is used for caching
   - Test fallback on AgentIntegrationError
   - Test fallback on AgentFetchError
   - Test fallback on AgentResponseParseError
   - Test error propagation when no fallback configured
   - Test DirectAPI-only platforms skip primary fetcher
   - Test error when service is closed

3. **Cache Management Tests**
   - Test invalidate_cache removes specific ticket
   - Test clear_cache removes all tickets
   - Test clear_cache with platform removes only that platform
   - Test has_cache property

4. **Resource Management Tests**
   - Test async context manager closes resources
   - Test explicit close() method
   - Test service raises error after close

5. **Factory Function Tests**
   - Test create_ticket_service with auggie_client
   - Test create_ticket_service with auth_manager only
   - Test create_ticket_service raises ValueError with no clients
   - Test default cache creation

#### Mock Strategy

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from spec.integrations.ticket_service import TicketService, create_ticket_service
from spec.integrations.providers.base import GenericTicket, Platform, TicketStatus
from spec.integrations.fetchers import (
    AgentIntegrationError,
    AgentFetchError,
    AgentResponseParseError,
)
from spec.integrations.cache import CacheKey

@pytest.fixture
def mock_primary_fetcher():
    fetcher = MagicMock()
    fetcher.name = "Mock Primary"
    fetcher.supports_platform.return_value = True
    fetcher.fetch = AsyncMock(return_value={"key": "PROJ-123", "summary": "Test"})
    return fetcher

@pytest.fixture
def mock_fallback_fetcher():
    fetcher = MagicMock()
    fetcher.name = "Mock Fallback"
    fetcher.supports_platform.return_value = True
    fetcher.fetch = AsyncMock(return_value={"key": "PROJ-123", "summary": "Test"})
    fetcher.close = AsyncMock()
    return fetcher

@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get.return_value = None
    cache.set = MagicMock()
    cache.invalidate.return_value = True
    cache.clear.return_value = 5
    cache.clear_platform.return_value = 3
    return cache

@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.PLATFORM = Platform.JIRA
    provider.parse_input.return_value = "PROJ-123"
    provider.normalize.return_value = GenericTicket(
        id="PROJ-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/browse/PROJ-123",
        title="Test Ticket",
        status=TicketStatus.OPEN,
    )
    return provider
```

#### Example Test Cases

```python
@pytest.mark.asyncio
async def test_get_ticket_cache_hit(mock_primary_fetcher, mock_cache, mock_provider):
    """Test that cache hit returns cached ticket without fetching."""
    cached_ticket = GenericTicket(
        id="PROJ-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/browse/PROJ-123",
        title="Cached Ticket",
    )
    mock_cache.get.return_value = cached_ticket

    with patch.object(ProviderRegistry, "get_provider_for_input", return_value=mock_provider):
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )

        result = await service.get_ticket("PROJ-123")

        assert result == cached_ticket
        mock_primary_fetcher.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_get_ticket_fallback_on_agent_error(
    mock_primary_fetcher, mock_fallback_fetcher, mock_cache, mock_provider
):
    """Test fallback is used when primary fails with agent error."""
    mock_primary_fetcher.fetch.side_effect = AgentIntegrationError("Agent unavailable")

    with patch.object(ProviderRegistry, "get_provider_for_input", return_value=mock_provider):
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            fallback_fetcher=mock_fallback_fetcher,
            cache=mock_cache,
        )

        result = await service.get_ticket("PROJ-123")

        mock_primary_fetcher.fetch.assert_called_once()
        mock_fallback_fetcher.fetch.assert_called_once()
        assert result.id == "PROJ-123"


@pytest.mark.asyncio
async def test_context_manager_closes_fallback(mock_primary_fetcher, mock_fallback_fetcher):
    """Test async context manager closes fallback fetcher."""
    async with TicketService(
        primary_fetcher=mock_primary_fetcher,
        fallback_fetcher=mock_fallback_fetcher,
    ):
        pass

    mock_fallback_fetcher.close.assert_called_once()
```

---

## Dependencies

### Upstream (Required Before Implementation)

| Ticket | Component | Status |
|--------|-----------|--------|
| AMI-17 | ProviderRegistry | ✅ Implemented |
| AMI-18 | JiraProvider | ✅ Implemented |
| AMI-19 | GitHubProvider | ✅ Implemented |
| AMI-20 | LinearProvider | ✅ Implemented |
| AMI-21 | Azure/Monday/Trello Providers | ✅ Implemented |
| AMI-23 | TicketCache | ✅ Implemented |
| AMI-29 | TicketFetcher abstraction | ✅ Implemented |
| AMI-30 | AuggieMediatedFetcher | ✅ Implemented |
| AMI-31 | DirectAPIFetcher | ✅ Implemented |

### Downstream (Depends on This Ticket)

| Ticket | Component | Description |
|--------|-----------|-------------|
| AMI-6 | spec CLI | Will use TicketService as entry point |
| Future | Workflow Engine | Will consume GenericTicket from TicketService |

---

## Additional Changes (Bug Fixes & Improvements)

During implementation, several improvements were made to support TicketService reliability and proper architecture. These changes are documented here for completeness.

### Cache Module Improvements

These changes improve cache reliability, testing, and correctness:

| Priority | Change | Description | Rationale |
|----------|--------|-------------|-----------|
| **P0** | Atomic write cleanup | Refactored `_atomic_write()` with proper `try...finally` for temp file cleanup | Prevents resource leaks on serialization errors (TypeError, ValueError) |
| **P1** | LRU eviction race fix | Replaced `glob() + stat()` with `os.scandir()` | Avoids race condition where files are deleted between listing and stat |
| **P1** | Injected RNG for testing | Added `eviction_rng` parameter to `FileBasedTicketCache` | Enables deterministic eviction behavior in tests |
| **P1** | Global cache kwargs reset | Changed `_global_cache_kwargs` from `None` to `{}` after clear | Ensures consistent comparison logic in `_get_global_cache()` |
| **P2** | URL-encoded cache keys | Added `urllib.parse.quote()` to `CacheKey.__str__()` | Fixes parsing of ticket IDs with special characters (e.g., GitHub `owner/repo#123`) |

#### Breaking Change: URL-Encoded Cache Keys

The `CacheKey.__str__()` method now URL-encodes the `ticket_id` to safely handle special characters:

**Before:** `JIRA:owner/repo#42`
**After:** `JIRA:owner%2Frepo%2342`

**Impact:**
- Existing cached files will NOT be found (cache miss on first access)
- Tickets will be re-fetched and cached with the new key format
- This is a one-time cache invalidation, not data loss
- Required for correctness with GitHub ticket IDs containing `/` and `#`

### Global Cache Deprecation

The global cache singleton functions are deprecated in favor of dependency injection via TicketService:

| Deprecated Function | Replacement |
|---------------------|-------------|
| `get_global_cache()` | Pass `InMemoryTicketCache()` or `FileBasedTicketCache()` to `TicketService` constructor |
| `set_global_cache()` | Pass cache instance to `TicketService` constructor |
| `clear_global_cache()` | Use `service.clear_cache()` method |

**Migration Example:**

```python
# OLD (deprecated - emits DeprecationWarning)
from spec.integrations import get_global_cache
cache = get_global_cache()

# NEW (recommended)
from spec.integrations import TicketService, InMemoryTicketCache, create_ticket_service

# Option 1: Use factory function (creates cache automatically)
async with await create_ticket_service(auggie_client=client) as service:
    ticket = await service.get_ticket("PROJ-123")

# Option 2: Explicit cache injection
cache = InMemoryTicketCache(default_ttl=timedelta(hours=2))
service = TicketService(primary_fetcher=fetcher, cache=cache)
```

**Rationale:**
- Global state makes testing difficult and creates hidden dependencies
- Dependency injection provides explicit control over cache lifecycle
- TicketService owns caching as an orchestration concern (per architecture spec)

### GenericTicket Serialization Improvements

Added `_normalize_for_json()` helper function to handle non-serializable objects in `platform_metadata`:

| Input Type | Output |
|------------|--------|
| `None`, `bool`, `int`, `float`, `str` | Passed through unchanged |
| `datetime` | ISO format string |
| `set`, `frozenset` | Sorted list |
| `Enum` | `.value` (or `.name` if value not JSON-safe) |
| `dict` | Recursively normalized |
| `list`, `tuple` | Recursively normalized list |
| Other objects | `{"__non_serializable__": True, "type": "...", "repr": "..."}` |

**Impact:**
- `GenericTicket.to_dict()` now normalizes `platform_metadata` before returning
- Prevents `TypeError` when caching tickets with complex metadata
- The `__non_serializable__` marker preserves visibility into unconverted data

**Additional Fix:**
- `GenericTicket.from_dict()` now accepts case-insensitive platform names ("jira", "JIRA", "Jira" all map to `Platform.JIRA`)

---

## References

### Related Tickets

- [AMI-17](https://linear.app/amiadspec/issue/AMI-17): ProviderRegistry implementation
- [AMI-18](https://linear.app/amiadspec/issue/AMI-18): JiraProvider implementation
- [AMI-19](https://linear.app/amiadspec/issue/AMI-19): GitHubProvider implementation
- [AMI-20](https://linear.app/amiadspec/issue/AMI-20): LinearProvider implementation
- [AMI-21](https://linear.app/amiadspec/issue/AMI-21): Additional platform providers
- [AMI-22](https://linear.app/amiadspec/issue/AMI-22): AuthenticationManager (used by DirectAPIFetcher)
- [AMI-23](https://linear.app/amiadspec/issue/AMI-23): Caching layer implementation
- [AMI-29](https://linear.app/amiadspec/issue/AMI-29): TicketFetcher abstraction layer
- [AMI-30](https://linear.app/amiadspec/issue/AMI-30): AuggieMediatedFetcher implementation
- [AMI-31](https://linear.app/amiadspec/issue/AMI-31): DirectAPIFetcher implementation

### Architecture Documents

- [Hybrid Ticket Fetching Architecture](./hybrid-ticket-fetching.md)
- [Provider Registry Design](./AMI-17-implementation-plan.md)
- [Caching Strategy](./AMI-23-implementation-plan.md)

### Codebase References

- `spec/integrations/providers/registry.py` - ProviderRegistry
- `spec/integrations/providers/base.py` - GenericTicket, Platform, IssueTrackerProvider
- `spec/integrations/fetchers/base.py` - TicketFetcher
- `spec/integrations/fetchers/auggie_fetcher.py` - AuggieMediatedFetcher
- `spec/integrations/fetchers/direct_api_fetcher.py` - DirectAPIFetcher
- `spec/integrations/fetchers/exceptions.py` - Exception hierarchy
- `spec/integrations/cache/` - Cache implementations
