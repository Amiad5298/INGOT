# Implementation Plan: AMI-23 - Implement Caching Layer for Ticket Data

**Ticket:** [AMI-23](https://linear.app/amiadspec/issue/AMI-23/implement-caching-layer-for-ticket-data)
**Status:** Draft
**Date:** 2026-01-26

---

## Summary

This ticket implements the caching layer for ticket data as defined in **Section 8: Caching Strategy** of `specs/00_Architecture_Refactor_Spec.md`. The caching layer provides efficient caching of ticket data to minimize API calls and improve responsiveness, while ensuring data freshness through TTL-based expiration.

**Key Architecture Decision (per AMI-23 comments):**
- **File location changed** from `specflow/integrations/providers/cache.py` to `spec/integrations/cache.py`
- **Caching is an orchestration concern** owned by `TicketService` (AMI-32), not individual providers
- The `@cached_fetch` decorator is **removed from scope** - caching is handled by `TicketService`

The caching layer provides:
1. **CacheKey** dataclass for unique cache key generation per platform+ticket
2. **CachedTicket** dataclass for tracking expiration metadata and ETag support
3. **TicketCache** abstract base class defining the cache storage interface
4. **InMemoryTicketCache** implementation for process-local caching (MVP)
5. **FileBasedTicketCache** implementation for persistence across sessions (future enhancement)
6. Thread-safe, memory-efficient caching with optional LRU eviction

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TicketService (AMI-32)                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  get_ticket(input_str)                                                │  │
│  │    │                                                                   │  │
│  │    ├─ Step 1: Detect platform (ProviderRegistry)                      │  │
│  │    ├─ Step 2: Parse input (Provider.parse_input)                      │  │
│  │    ├─ Step 3: Check cache ◄── TicketCache.get() ── THIS TICKET       │  │
│  │    │     └─ if cached AND not expired: return cached ticket           │  │
│  │    ├─ Step 4: Fetch raw data (AuggieMediatedFetcher / DirectAPIFetcher)│
│  │    ├─ Step 5: Normalize (Provider.normalize)                          │  │
│  │    ├─ Step 6: Cache result ◄── TicketCache.set() ── THIS TICKET      │  │
│  │    └─ Step 7: Return GenericTicket                                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ uses
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  TicketCache (THIS TICKET)          │  Caching Layer                       │
│  • CacheKey (Platform + ticket_id)  │  • Unique key per platform+ticket    │
│  • CachedTicket (ticket + metadata) │  • TTL-based expiration              │
│  • TicketCache ABC                  │  • ETag support for conditional reqs │
│  • InMemoryTicketCache              │  • Thread-safe, memory-efficient     │
│  • FileBasedTicketCache             │  • Persistence (future enhancement)  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **TicketService Owns Caching** - Per architecture review, caching is an orchestration concern, not a provider concern
2. **No `@cached_fetch` Decorator** - Removed from scope; providers don't handle caching directly
3. **Abstract Cache Interface** - `TicketCache` ABC allows swapping implementations (in-memory, file-based, Redis future)
4. **TTL-Based Expiration** - Configurable per-platform or global (default: 1 hour from `TICKET_CACHE_DURATION`)
5. **ETag Support** - Enables conditional requests for platforms supporting it (GitHub)
6. **Thread-Safe** - Uses threading.Lock for concurrent access safety
7. **Memory-Efficient** - Optional LRU eviction for large caches (configurable max size)

---

## Components to Create

### New File: `spec/integrations/cache.py`

| Component | Purpose |
|-----------|---------|
| `CacheKey` dataclass | Unique cache key per platform+ticket |
| `CachedTicket` dataclass | Cached ticket with expiration metadata and ETag |
| `TicketCache` ABC | Abstract cache storage interface |
| `InMemoryTicketCache` | In-memory implementation (default) |
| `FileBasedTicketCache` | File-based persistent implementation |
| `get_global_cache()` | Factory function for singleton cache instance |

### Modified Files

| File | Changes |
|------|---------|
| `spec/integrations/__init__.py` | Export cache classes |

---

## Implementation Steps

### Step 1: Create Cache Module with CacheKey and CachedTicket

**File:** `spec/integrations/cache.py`

```python
"""Caching layer for ticket data.

This module provides efficient caching of ticket data to minimize API calls
and improve responsiveness. Caching is owned by TicketService (AMI-32),
not individual providers.

See specs/00_Architecture_Refactor_Spec.md Section 8 for design details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from spec.integrations.providers.base import GenericTicket

from spec.integrations.providers.base import Platform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheKey:
    """Unique cache key for ticket data.

    Attributes:
        platform: The platform this ticket belongs to
        ticket_id: Normalized ticket identifier (e.g., 'PROJ-123', 'owner/repo#42')
    """

    platform: Platform
    ticket_id: str

    def __str__(self) -> str:
        """Generate string key for storage."""
        return f"{self.platform.name}:{self.ticket_id}"

    def __hash__(self) -> int:
        """Hash for dict key usage."""
        return hash((self.platform, self.ticket_id))

    @classmethod
    def from_ticket(cls, ticket: "GenericTicket") -> "CacheKey":
        """Create cache key from a GenericTicket.

        Args:
            ticket: GenericTicket to create key from

        Returns:
            CacheKey for the ticket
        """
        return cls(platform=ticket.platform, ticket_id=ticket.id)


@dataclass
class CachedTicket:
    """Cached ticket with expiration metadata.

    Attributes:
        ticket: The cached GenericTicket
        cached_at: Timestamp when the ticket was cached
        expires_at: Timestamp when the cache entry expires
        etag: Optional ETag for conditional requests (e.g., GitHub)
    """

    ticket: "GenericTicket"
    cached_at: datetime
    expires_at: datetime
    etag: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return datetime.now() > self.expires_at

    @property
    def ttl_remaining(self) -> timedelta:
        """Get remaining time-to-live for this entry."""
        remaining = self.expires_at - datetime.now()
        return remaining if remaining.total_seconds() > 0 else timedelta(0)
```

### Step 2: Add TicketCache Abstract Base Class

```python
class TicketCache(ABC):
    """Abstract base class for ticket cache storage.

    Implementations must be thread-safe for concurrent access.
    """

    @abstractmethod
    def get(self, key: CacheKey) -> Optional["GenericTicket"]:
        """Retrieve cached ticket if not expired.

        Args:
            key: Cache key for the ticket

        Returns:
            Cached GenericTicket if valid, None if expired or not found
        """
        pass

    @abstractmethod
    def set(
        self,
        ticket: "GenericTicket",
        ttl: Optional[timedelta] = None,
        etag: Optional[str] = None,
    ) -> None:
        """Store ticket in cache with optional custom TTL.

        Args:
            ticket: GenericTicket to cache
            ttl: Optional TTL override (uses default if None)
            etag: Optional ETag for conditional requests
        """
        pass

    @abstractmethod
    def invalidate(self, key: CacheKey) -> None:
        """Remove a specific ticket from cache.

        Args:
            key: Cache key to invalidate
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cached tickets."""
        pass

    @abstractmethod
    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a specific platform.

        Args:
            platform: Platform to clear cache for
        """
        pass

    @abstractmethod
    def get_cached_ticket(self, key: CacheKey) -> Optional[CachedTicket]:
        """Retrieve full CachedTicket with metadata.

        Args:
            key: Cache key for the ticket

        Returns:
            CachedTicket with full metadata, or None if not found/expired
        """
        pass

    @abstractmethod
    def get_etag(self, key: CacheKey) -> Optional[str]:
        """Get ETag for conditional requests.

        Args:
            key: Cache key to get ETag for

        Returns:
            ETag string if available, None otherwise
        """
        pass
```

### Step 3: Implement InMemoryTicketCache

```python
class InMemoryTicketCache(TicketCache):
    """In-memory ticket cache with thread-safe access and LRU eviction.

    This is the default implementation for process-local caching.

    Attributes:
        default_ttl: Default TTL for cache entries
        max_size: Maximum number of entries (0 = unlimited)
    """

    def __init__(
        self,
        default_ttl: timedelta = timedelta(hours=1),
        max_size: int = 0,
    ) -> None:
        """Initialize in-memory cache.

        Args:
            default_ttl: Default TTL for entries (default: 1 hour)
            max_size: Maximum entries before LRU eviction (0 = unlimited)
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache: OrderedDict[str, CachedTicket] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> Optional["GenericTicket"]:
        """Retrieve cached ticket if not expired."""
        cached = self.get_cached_ticket(key)
        return cached.ticket if cached else None

    def get_cached_ticket(self, key: CacheKey) -> Optional[CachedTicket]:
        """Retrieve full CachedTicket with metadata."""
        with self._lock:
            key_str = str(key)
            cached = self._cache.get(key_str)

            if cached is None:
                return None

            if cached.is_expired:
                # Remove expired entry
                del self._cache[key_str]
                logger.debug(f"Cache expired for {key}")
                return None

            # Move to end for LRU tracking
            self._cache.move_to_end(key_str)
            logger.debug(f"Cache hit for {key}")
            return cached

    def set(
        self,
        ticket: "GenericTicket",
        ttl: Optional[timedelta] = None,
        etag: Optional[str] = None,
    ) -> None:
        """Store ticket in cache."""
        key = CacheKey.from_ticket(ticket)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = datetime.now()

        cached = CachedTicket(
            ticket=ticket,
            cached_at=now,
            expires_at=now + effective_ttl,
            etag=etag,
        )

        with self._lock:
            key_str = str(key)

            # Remove if already exists (to update position)
            if key_str in self._cache:
                del self._cache[key_str]

            # Evict oldest entries if at max capacity
            while self.max_size > 0 and len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"LRU evicted: {oldest_key}")

            self._cache[key_str] = cached
            logger.debug(f"Cached {key} with TTL {effective_ttl}")

    def invalidate(self, key: CacheKey) -> None:
        """Remove a specific ticket from cache."""
        with self._lock:
            key_str = str(key)
            if key_str in self._cache:
                del self._cache[key_str]
                logger.debug(f"Invalidated cache for {key}")

    def clear(self) -> None:
        """Clear all cached tickets."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"Cleared {count} cache entries")

    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a platform."""
        prefix = f"{platform.name}:"
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._cache[key]
            logger.debug(f"Cleared {len(keys_to_delete)} entries for {platform.name}")

    def get_etag(self, key: CacheKey) -> Optional[str]:
        """Get ETag for conditional requests."""
        cached = self.get_cached_ticket(key)
        return cached.etag if cached else None

    def size(self) -> int:
        """Get current number of cached entries."""
        with self._lock:
            return len(self._cache)

    def stats(self) -> dict[str, int]:
        """Get cache statistics per platform."""
        with self._lock:
            stats: dict[str, int] = {}
            for key_str in self._cache:
                platform = key_str.split(":")[0]
                stats[platform] = stats.get(platform, 0) + 1
            return stats
```

### Step 4: Implement FileBasedTicketCache

```python
class FileBasedTicketCache(TicketCache):
    """File-based persistent ticket cache.

    Stores cache in ~/.specflow-cache/ directory for persistence across sessions.
    Each ticket is stored as a separate JSON file with platform_ticketId hash.

    Attributes:
        cache_dir: Directory for cache files
        default_ttl: Default TTL for cache entries
        max_size: Maximum number of entries (0 = unlimited)
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        default_ttl: timedelta = timedelta(hours=1),
        max_size: int = 0,
    ) -> None:
        """Initialize file-based cache.

        Args:
            cache_dir: Directory for cache files (default: ~/.specflow-cache)
            default_ttl: Default TTL for entries (default: 1 hour)
            max_size: Maximum entries before LRU eviction (0 = unlimited)
        """
        self.cache_dir = cache_dir or Path.home() / ".specflow-cache"
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _get_path(self, key: CacheKey) -> Path:
        """Get file path for cache key."""
        safe_id = hashlib.md5(key.ticket_id.encode()).hexdigest()
        return self.cache_dir / f"{key.platform.name}_{safe_id}.json"

    def _serialize_ticket(self, cached: CachedTicket) -> dict:
        """Serialize CachedTicket to JSON-compatible dict."""
        from dataclasses import asdict
        ticket_dict = asdict(cached.ticket)
        # Convert enums to strings for JSON
        # Platform uses auto() so we use .name; Status/Type have string values so we use .value
        ticket_dict["platform"] = cached.ticket.platform.name
        ticket_dict["status"] = cached.ticket.status.value
        ticket_dict["type"] = cached.ticket.type.value
        # Convert datetime to ISO format
        if cached.ticket.created_at:
            ticket_dict["created_at"] = cached.ticket.created_at.isoformat()
        if cached.ticket.updated_at:
            ticket_dict["updated_at"] = cached.ticket.updated_at.isoformat()

        return {
            "ticket": ticket_dict,
            "cached_at": cached.cached_at.isoformat(),
            "expires_at": cached.expires_at.isoformat(),
            "etag": cached.etag,
        }

    def _deserialize_ticket(self, data: dict) -> CachedTicket | None:
        """Deserialize JSON dict to CachedTicket."""
        from spec.integrations.providers.base import (
            GenericTicket,
            Platform,
            TicketStatus,
            TicketType,
        )

        try:
            ticket_data = data["ticket"]
            # Convert string values back to enums
            # Platform uses auto() so we lookup by name; Status/Type have string values
            ticket_data["platform"] = Platform[ticket_data["platform"]]
            ticket_data["status"] = TicketStatus(ticket_data["status"])
            ticket_data["type"] = TicketType(ticket_data["type"])
            # Convert ISO format back to datetime
            if ticket_data.get("created_at"):
                ticket_data["created_at"] = datetime.fromisoformat(
                    ticket_data["created_at"]
                )
            if ticket_data.get("updated_at"):
                ticket_data["updated_at"] = datetime.fromisoformat(
                    ticket_data["updated_at"]
                )

            ticket = GenericTicket(**ticket_data)

            return CachedTicket(
                ticket=ticket,
                cached_at=datetime.fromisoformat(data["cached_at"]),
                expires_at=datetime.fromisoformat(data["expires_at"]),
                etag=data.get("etag"),
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to deserialize cached ticket: {e}")
            return None

    def get(self, key: CacheKey) -> Optional["GenericTicket"]:
        """Retrieve cached ticket if not expired."""
        cached = self.get_cached_ticket(key)
        return cached.ticket if cached else None

    def get_cached_ticket(self, key: CacheKey) -> Optional[CachedTicket]:
        """Retrieve full CachedTicket with metadata."""
        path = self._get_path(key)
        with self._lock:
            if not path.exists():
                return None

            try:
                data = json.loads(path.read_text())
                cached = self._deserialize_ticket(data)

                if cached is None:
                    path.unlink(missing_ok=True)
                    return None

                if cached.is_expired:
                    path.unlink(missing_ok=True)
                    logger.debug(f"Cache expired for {key}")
                    return None

                logger.debug(f"Cache hit for {key}")
                return cached
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read cache file {path}: {e}")
                path.unlink(missing_ok=True)
                return None

    def set(
        self,
        ticket: "GenericTicket",
        ttl: Optional[timedelta] = None,
        etag: Optional[str] = None,
    ) -> None:
        """Store ticket in cache."""
        key = CacheKey.from_ticket(ticket)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = datetime.now()

        cached = CachedTicket(
            ticket=ticket,
            cached_at=now,
            expires_at=now + effective_ttl,
            etag=etag,
        )

        path = self._get_path(key)
        with self._lock:
            try:
                data = self._serialize_ticket(cached)
                path.write_text(json.dumps(data, indent=2))
                logger.debug(f"Cached {key} to {path}")

                # Evict oldest entries if over max_size
                self._evict_lru()
            except OSError as e:
                logger.warning(f"Failed to write cache file {path}: {e}")

    def invalidate(self, key: CacheKey) -> None:
        """Remove a specific ticket from cache."""
        path = self._get_path(key)
        with self._lock:
            if path.exists():
                path.unlink(missing_ok=True)
                logger.debug(f"Invalidated cache for {key}")

    def clear(self) -> None:
        """Clear all cached tickets."""
        with self._lock:
            count = 0
            for path in self.cache_dir.glob("*.json"):
                path.unlink(missing_ok=True)
                count += 1
            logger.debug(f"Cleared {count} cache files")

    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a platform."""
        prefix = f"{platform.name}_"
        with self._lock:
            count = 0
            for path in self.cache_dir.glob(f"{prefix}*.json"):
                path.unlink(missing_ok=True)
                count += 1
            logger.debug(f"Cleared {count} cache files for {platform.name}")

    def get_etag(self, key: CacheKey) -> Optional[str]:
        """Get ETag for conditional requests."""
        cached = self.get_cached_ticket(key)
        return cached.etag if cached else None

    def size(self) -> int:
        """Get current number of cached entries."""
        with self._lock:
            return len(list(self.cache_dir.glob("*.json")))

    def stats(self) -> dict[str, int]:
        """Get cache statistics per platform."""
        with self._lock:
            stats: dict[str, int] = {}
            for path in self.cache_dir.glob("*.json"):
                # Filename format: PLATFORM_hash.json
                platform = path.stem.split("_")[0]
                stats[platform] = stats.get(platform, 0) + 1
            return stats

    def _evict_lru(self) -> None:
        """Evict least recently used entries if over max_size.

        Uses file modification time as LRU indicator.
        """
        if self.max_size <= 0:
            return

        files = list(self.cache_dir.glob("*.json"))
        if len(files) <= self.max_size:
            return

        # Sort by modification time (oldest first)
        files.sort(key=lambda p: p.stat().st_mtime)

        # Remove oldest files until under max_size
        to_remove = len(files) - self.max_size
        for path in files[:to_remove]:
            path.unlink(missing_ok=True)
            logger.debug(f"LRU evicted: {path.name}")
```

### Step 5: Add Global Cache Factory Function

```python
# Global cache singleton
_global_cache: Optional[TicketCache] = None
_cache_lock = threading.Lock()


def get_global_cache(
    cache_type: str = "memory",
    **kwargs,
) -> TicketCache:
    """Get or create the global cache singleton.

    Args:
        cache_type: Type of cache ('memory' or 'file')
        **kwargs: Additional arguments passed to cache constructor

    Returns:
        Global TicketCache instance
    """
    global _global_cache

    with _cache_lock:
        if _global_cache is None:
            if cache_type == "file":
                _global_cache = FileBasedTicketCache(**kwargs)
                logger.info("Initialized file-based ticket cache")
            else:
                _global_cache = InMemoryTicketCache(**kwargs)
                logger.info("Initialized in-memory ticket cache")

        return _global_cache


def set_global_cache(cache: TicketCache) -> None:
    """Set the global cache instance (primarily for testing).

    Args:
        cache: TicketCache instance to use globally
    """
    global _global_cache

    with _cache_lock:
        _global_cache = cache


def clear_global_cache() -> None:
    """Clear and reset the global cache singleton."""
    global _global_cache

    with _cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
            _global_cache = None
```

### Step 6: Update Package Exports

**File:** `spec/integrations/__init__.py`

```python
# Add to existing exports
from spec.integrations.cache import (
    CacheKey,
    CachedTicket,
    TicketCache,
    InMemoryTicketCache,
    FileBasedTicketCache,
    get_global_cache,
    set_global_cache,
    clear_global_cache,
)

__all__ = [
    # ... existing exports
    "CacheKey",
    "CachedTicket",
    "TicketCache",
    "InMemoryTicketCache",
    "FileBasedTicketCache",
    "get_global_cache",
    "set_global_cache",
    "clear_global_cache",
]
```

---

## Integration Points

### TicketService (AMI-32)

The `TicketCache` integrates with `TicketService` which owns the caching logic:

```python
from spec.integrations.cache import (
    CacheKey,
    TicketCache,
    InMemoryTicketCache,
)

class TicketService:
    """Orchestrates ticket fetching with caching support."""

    def __init__(
        self,
        primary_fetcher: TicketFetcher,
        fallback_fetcher: TicketFetcher | None = None,
        cache: TicketCache | None = None,
        default_ttl: timedelta = timedelta(hours=1),
    ) -> None:
        self._primary = primary_fetcher
        self._fallback = fallback_fetcher
        self._cache = cache
        self._default_ttl = default_ttl

    async def get_ticket(self, input_str: str) -> GenericTicket:
        """Fetch ticket with caching.

        Flow:
        1. Detect platform and get provider
        2. Parse input to get normalized ID
        3. Check cache
        4. Fetch raw data (primary or fallback)
        5. Normalize to GenericTicket
        6. Cache result
        7. Return ticket
        """
        # Step 1: Detect platform
        provider = ProviderRegistry.get_provider_for_input(input_str)
        platform = provider.platform

        # Step 2: Parse input
        ticket_id = provider.parse_input(input_str)

        # Step 3: Check cache
        if self._cache:
            key = CacheKey(platform, ticket_id)
            cached = self._cache.get(key)
            if cached:
                logger.debug(f"Cache hit for {key}")
                return cached

        # Step 4: Fetch raw data
        try:
            raw_data = await self._primary.fetch_raw(ticket_id, platform)
        except (AgentIntegrationError, AgentFetchError) as e:
            if self._fallback:
                logger.warning(f"Primary fetch failed: {e}, trying fallback")
                raw_data = await self._fallback.fetch_raw(ticket_id, platform)
            else:
                raise

        # Step 5: Normalize
        ticket = provider.normalize(raw_data)

        # Step 6: Cache result
        if self._cache:
            self._cache.set(ticket, ttl=self._default_ttl)

        # Step 7: Return
        return ticket

    def invalidate_cache(self, input_str: str) -> None:
        """Invalidate cache for a specific ticket."""
        if not self._cache:
            return

        provider = ProviderRegistry.get_provider_for_input(input_str)
        ticket_id = provider.parse_input(input_str)
        key = CacheKey(provider.platform, ticket_id)
        self._cache.invalidate(key)

    def clear_cache(self, platform: Platform | None = None) -> None:
        """Clear cache for all or specific platform."""
        if not self._cache:
            return

        if platform:
            self._cache.clear_platform(platform)
        else:
            self._cache.clear()
```

### AuggieMediatedFetcher (AMI-30) & DirectAPIFetcher (AMI-31)

Fetchers are **cache-unaware** - they don't interact with the cache directly. Caching is handled by `TicketService`:

```
TicketService
    ├── Cache check (CacheKey)
    ├── If miss: call fetcher
    │   ├── AuggieMediatedFetcher.fetch() → raw_data
    │   └── DirectAPIFetcher.fetch() → raw_data (fallback)
    ├── provider.normalize(raw_data) → GenericTicket
    └── Cache set (GenericTicket)
```

### Providers (JiraProvider, LinearProvider, GitHubProvider, etc.)

Providers are **cache-unaware** - they only handle normalization. The `@cached_fetch` decorator pattern from Section 8.3 of the architecture spec is **not used** per the architecture review.

---

## Configuration

### Cache Settings

The cache respects the following configuration from `spec/config/fetch_config.py`:

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| Cache TTL | `TICKET_CACHE_DURATION` | `3600` (1 hour) | Cache entry TTL in seconds |
| Cache Type | `TICKET_CACHE_TYPE` | `memory` | `memory` or `file` |
| Max Size | `TICKET_CACHE_MAX_SIZE` | `0` (unlimited) | Max entries for LRU eviction |
| Cache Dir | `TICKET_CACHE_DIR` | `~/.specflow-cache` | Directory for file cache |

### Example Configuration

```bash
# ~/.spec-config

# === Cache Settings ===
TICKET_CACHE_DURATION=3600    # 1 hour TTL
TICKET_CACHE_TYPE=memory      # 'memory' or 'file'
TICKET_CACHE_MAX_SIZE=1000    # LRU eviction threshold

# For file-based cache (cross-session persistence)
# TICKET_CACHE_TYPE=file
# TICKET_CACHE_DIR=/tmp/specflow-cache
```

---

## Dependencies

### Required (Must Be Complete)

| Dependency | Ticket | Status | Description |
|------------|--------|--------|-------------|
| `GenericTicket` dataclass | AMI-17 | ✅ Complete | Cached data structure |
| `Platform` enum | AMI-17 | ✅ Complete | Part of cache key |
| `TicketStatus` enum | AMI-17 | ✅ Complete | For serialization |
| `TicketType` enum | AMI-17 | ✅ Complete | For serialization |

### Downstream Dependents

| Dependent | Ticket | Relationship |
|-----------|--------|--------------|
| `TicketService` | AMI-32 | Primary consumer; owns caching logic |

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_cache.py`

```python
"""Tests for ticket caching layer."""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from spec.integrations.cache import (
    CacheKey,
    CachedTicket,
    InMemoryTicketCache,
    FileBasedTicketCache,
    get_global_cache,
    set_global_cache,
    clear_global_cache,
)
from spec.integrations.providers.base import (
    GenericTicket,
    Platform,
    TicketStatus,
    TicketType,
)


@pytest.fixture
def sample_ticket():
    """Create a sample GenericTicket for testing."""
    return GenericTicket(
        id="PROJ-123",
        platform=Platform.JIRA,
        url="https://company.atlassian.net/browse/PROJ-123",
        title="Test Ticket",
        description="Test description",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.FEATURE,
        assignee="Test User",
        labels=["test", "feature"],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        branch_summary="test-ticket",
        platform_metadata={},
    )


class TestCacheKey:
    """Test CacheKey dataclass."""

    def test_string_representation(self):
        key = CacheKey(Platform.JIRA, "PROJ-123")
        assert str(key) == "jira:PROJ-123"

    def test_from_ticket(self, sample_ticket):
        key = CacheKey.from_ticket(sample_ticket)
        assert key.platform == Platform.JIRA
        assert key.ticket_id == "PROJ-123"

    def test_hash_equality(self):
        key1 = CacheKey(Platform.JIRA, "PROJ-123")
        key2 = CacheKey(Platform.JIRA, "PROJ-123")
        assert key1 == key2
        assert hash(key1) == hash(key2)

    def test_different_platform_keys(self):
        key1 = CacheKey(Platform.JIRA, "PROJ-123")
        key2 = CacheKey(Platform.LINEAR, "PROJ-123")
        assert key1 != key2


class TestCachedTicket:
    """Test CachedTicket dataclass."""

    def test_is_expired_false(self, sample_ticket):
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert cached.is_expired is False

    def test_is_expired_true(self, sample_ticket):
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=datetime.now() - timedelta(hours=2),
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert cached.is_expired is True

    def test_ttl_remaining(self, sample_ticket):
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=30),
        )
        assert cached.ttl_remaining.total_seconds() > 0
        assert cached.ttl_remaining.total_seconds() <= 30 * 60


class TestInMemoryTicketCache:
    """Test InMemoryTicketCache implementation."""

    @pytest.fixture
    def cache(self):
        return InMemoryTicketCache(default_ttl=timedelta(hours=1))

    def test_set_and_get(self, cache, sample_ticket):
        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)
        result = cache.get(key)
        assert result is not None
        assert result.id == sample_ticket.id

    def test_get_nonexistent_returns_none(self, cache):
        key = CacheKey(Platform.JIRA, "NONEXISTENT-123")
        assert cache.get(key) is None

    def test_expired_entry_returns_none(self, cache, sample_ticket):
        cache.set(sample_ticket, ttl=timedelta(seconds=-1))
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get(key) is None

    def test_invalidate(self, cache, sample_ticket):
        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get(key) is not None
        cache.invalidate(key)
        assert cache.get(key) is None

    def test_clear(self, cache, sample_ticket):
        cache.set(sample_ticket)
        assert cache.size() == 1
        cache.clear()
        assert cache.size() == 0

    def test_clear_platform(self, cache, sample_ticket):
        cache.set(sample_ticket)
        # Add another ticket from different platform
        linear_ticket = GenericTicket(
            id="ENG-456",
            platform=Platform.LINEAR,
            url="https://linear.app/team/issue/ENG-456",
            title="Linear Ticket",
            description="",
            status=TicketStatus.OPEN,
            type=TicketType.TASK,
            assignee=None,
            labels=[],
            created_at=None,
            updated_at=None,
            branch_summary="linear-ticket",
            platform_metadata={},
        )
        cache.set(linear_ticket)
        assert cache.size() == 2

        cache.clear_platform(Platform.JIRA)
        assert cache.size() == 1
        assert cache.get(CacheKey(Platform.LINEAR, "ENG-456")) is not None

    def test_lru_eviction(self, sample_ticket):
        cache = InMemoryTicketCache(default_ttl=timedelta(hours=1), max_size=2)
        # Add 3 tickets to trigger eviction
        for i in range(3):
            ticket = GenericTicket(
                id=f"PROJ-{i}",
                platform=Platform.JIRA,
                url=f"https://example.com/PROJ-{i}",
                title=f"Ticket {i}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"ticket-{i}",
                platform_metadata={},
            )
            cache.set(ticket)

        assert cache.size() == 2
        # First ticket should be evicted
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-0")) is None
        # Last two should still exist
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-1")) is not None
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-2")) is not None

    def test_etag_support(self, cache, sample_ticket):
        cache.set(sample_ticket, etag="abc123")
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get_etag(key) == "abc123"

    def test_thread_safety_no_exceptions(self, cache, sample_ticket):
        """Test concurrent access doesn't raise exceptions."""
        import threading

        errors = []

        def cache_operations():
            try:
                for _ in range(100):
                    cache.set(sample_ticket)
                    key = CacheKey.from_ticket(sample_ticket)
                    cache.get(key)
                    cache.invalidate(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=cache_operations) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_thread_safety_data_integrity(self):
        """Test concurrent writes maintain data integrity."""
        import threading

        cache = InMemoryTicketCache(default_ttl=timedelta(hours=1))
        results = []
        num_threads = 10
        iterations = 50

        def write_unique_ticket(thread_id: int):
            """Each thread writes tickets with unique IDs."""
            for i in range(iterations):
                ticket = GenericTicket(
                    id=f"THREAD{thread_id}-{i}",
                    platform=Platform.JIRA,
                    url=f"https://example.com/THREAD{thread_id}-{i}",
                    title=f"Thread {thread_id} Ticket {i}",
                    description="",
                    status=TicketStatus.OPEN,
                    type=TicketType.TASK,
                    assignee=None,
                    labels=[],
                    created_at=None,
                    updated_at=None,
                    branch_summary=f"thread-{thread_id}-ticket-{i}",
                    platform_metadata={},
                )
                cache.set(ticket)

        def verify_tickets(thread_id: int):
            """Verify all tickets from a thread are retrievable."""
            found = 0
            for i in range(iterations):
                key = CacheKey(Platform.JIRA, f"THREAD{thread_id}-{i}")
                if cache.get(key) is not None:
                    found += 1
            results.append((thread_id, found))

        # Write phase
        write_threads = [
            threading.Thread(target=write_unique_ticket, args=(i,))
            for i in range(num_threads)
        ]
        for t in write_threads:
            t.start()
        for t in write_threads:
            t.join()

        # Verify phase
        verify_threads = [
            threading.Thread(target=verify_tickets, args=(i,))
            for i in range(num_threads)
        ]
        for t in verify_threads:
            t.start()
        for t in verify_threads:
            t.join()

        # All tickets should be found
        total_found = sum(count for _, count in results)
        assert total_found == num_threads * iterations
        assert cache.size() == num_threads * iterations


class TestFileBasedTicketCache:
    """Test FileBasedTicketCache implementation."""

    @pytest.fixture
    def cache(self, tmp_path):
        return FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
        )

    def test_set_and_get(self, cache, sample_ticket):
        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)
        result = cache.get(key)
        assert result is not None
        assert result.id == sample_ticket.id

    def test_persistence(self, sample_ticket, tmp_path):
        # Create cache, add ticket, then create new cache instance
        cache1 = FileBasedTicketCache(cache_dir=tmp_path)
        cache1.set(sample_ticket)

        # New cache instance should find the ticket
        cache2 = FileBasedTicketCache(cache_dir=tmp_path)
        key = CacheKey.from_ticket(sample_ticket)
        result = cache2.get(key)
        assert result is not None
        assert result.id == sample_ticket.id

    def test_expired_entry_deleted(self, cache, sample_ticket):
        cache.set(sample_ticket, ttl=timedelta(seconds=-1))
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get(key) is None
        # File should be deleted
        path = cache._get_path(key)
        assert not path.exists()

    def test_size(self, cache, sample_ticket):
        assert cache.size() == 0
        cache.set(sample_ticket)
        assert cache.size() == 1

    def test_stats(self, sample_ticket, tmp_path):
        cache = FileBasedTicketCache(cache_dir=tmp_path)
        cache.set(sample_ticket)
        # Add another ticket from different platform
        linear_ticket = GenericTicket(
            id="ENG-456",
            platform=Platform.LINEAR,
            url="https://linear.app/team/issue/ENG-456",
            title="Linear Ticket",
            description="",
            status=TicketStatus.OPEN,
            type=TicketType.TASK,
            assignee=None,
            labels=[],
            created_at=None,
            updated_at=None,
            branch_summary="linear-ticket",
            platform_metadata={},
        )
        cache.set(linear_ticket)

        stats = cache.stats()
        assert stats["JIRA"] == 1
        assert stats["LINEAR"] == 1

    def test_lru_eviction(self, sample_ticket, tmp_path):
        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=2,
        )
        # Add 3 tickets to trigger eviction
        import time
        for i in range(3):
            ticket = GenericTicket(
                id=f"PROJ-{i}",
                platform=Platform.JIRA,
                url=f"https://example.com/PROJ-{i}",
                title=f"Ticket {i}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"ticket-{i}",
                platform_metadata={},
            )
            cache.set(ticket)
            time.sleep(0.01)  # Ensure different mtime for LRU ordering

        assert cache.size() == 2
        # First ticket should be evicted (oldest mtime)
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-0")) is None
        # Last two should still exist
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-1")) is not None
        assert cache.get(CacheKey(Platform.JIRA, "PROJ-2")) is not None


class TestGlobalCache:
    """Test global cache singleton functions."""

    def test_get_global_cache_singleton(self):
        clear_global_cache()
        cache1 = get_global_cache()
        cache2 = get_global_cache()
        assert cache1 is cache2

    def test_set_global_cache(self):
        clear_global_cache()
        custom_cache = InMemoryTicketCache(max_size=100)
        set_global_cache(custom_cache)
        assert get_global_cache() is custom_cache
        clear_global_cache()
```

### Test Coverage Requirements

| Component | Coverage Target |
|-----------|----------------|
| `CacheKey` | 100% |
| `CachedTicket` | 100% |
| `InMemoryTicketCache` | >95% |
| `FileBasedTicketCache` | >90% |
| Global cache functions | 100% |

---

## Migration Considerations

### Backward Compatibility

- **No breaking changes** - This is a new module with no existing dependents
- Existing code is unaffected until explicitly using the cache
- Cache is optional in `TicketService` constructor

### Gradual Adoption Path

1. **Phase 1 (This Ticket):** Implement caching layer with in-memory and file-based implementations
2. **Phase 2 (AMI-32):** Integrate with TicketService for transparent caching
3. **Phase 3 (Future):** Add cache statistics/metrics, consider Redis for distributed caching

---

## Acceptance Criteria Checklist

From Linear ticket AMI-23:

- [ ] `CacheKey` generates unique keys per platform+ticket
- [ ] `CachedTicket` tracks expiration correctly
- [ ] `TicketCache.get()` returns None for expired entries
- [ ] `TicketCache.set()` respects custom TTL
- [ ] Thread-safe for concurrent access
- [ ] Memory-efficient (LRU eviction for large caches)
- [ ] Exports added to `integrations/__init__.py`
- [ ] Unit tests for cache hit/miss/expiration scenarios

### Updated Scope (per architecture review):

- [ ] **REMOVED:** `@cached_fetch` decorator (caching owned by TicketService)
- [ ] **ADDED:** File location changed to `spec/integrations/cache.py`
- [ ] **ADDED:** `FileBasedTicketCache` implementation with LRU eviction support
- [ ] **ADDED:** Global cache singleton pattern
- [ ] **ADDED:** `get_etag()` method for conditional requests
- [ ] **ADDED:** `clear_platform()` method for selective invalidation
- [ ] **ADDED:** Cache statistics methods (`size()`, `stats()`) for both implementations
- [ ] **ADDED:** `get_cached_ticket()` method for accessing full metadata (expiration, ETag)
- [ ] **ADDED:** `max_size` parameter for LRU eviction in both cache implementations

---

## Usage Examples

### Basic Cache Usage

```python
from datetime import timedelta
from spec.integrations.cache import (
    CacheKey,
    InMemoryTicketCache,
)
from spec.integrations.providers.base import Platform

# Create cache with 30-minute TTL
cache = InMemoryTicketCache(default_ttl=timedelta(minutes=30))

# Cache a ticket
cache.set(ticket)

# Retrieve from cache
key = CacheKey(Platform.JIRA, "PROJ-123")
cached_ticket = cache.get(key)
if cached_ticket:
    print(f"Cache hit: {cached_ticket.title}")
else:
    print("Cache miss - fetch from API")
```

### Using Global Cache Singleton

```python
from spec.integrations.cache import get_global_cache

# Get or create the global cache
cache = get_global_cache(cache_type="memory", max_size=500)

# Use throughout application
cache.set(ticket)
```

### Integration with TicketService (AMI-32)

```python
from spec.integrations.cache import InMemoryTicketCache
from spec.integrations.fetchers import AuggieMediatedFetcher, DirectAPIFetcher

# Create service with caching
cache = InMemoryTicketCache(default_ttl=timedelta(hours=1), max_size=1000)

service = TicketService(
    primary_fetcher=auggie_fetcher,
    fallback_fetcher=direct_fetcher,
    cache=cache,
)

# Cache is used transparently
ticket = await service.get_ticket("PROJ-123")  # Fetches and caches
ticket = await service.get_ticket("PROJ-123")  # Returns from cache

# Manual invalidation
service.invalidate_cache("PROJ-123")
```

### File-Based Cache for Persistence

```python
from pathlib import Path
from spec.integrations.cache import FileBasedTicketCache

# Use file-based cache for cross-session persistence
cache = FileBasedTicketCache(
    cache_dir=Path.home() / ".specflow-cache",
    default_ttl=timedelta(hours=24),  # Longer TTL for file cache
)

# Tickets persist across restarts
```

---

## References

- [Architecture Spec - Section 8: Caching Strategy](specs/00_Architecture_Refactor_Spec.md#8-caching-strategy)
- [AMI-32 Linear Ticket](https://linear.app/amiadspec/issue/AMI-32) - TicketService integration
- [AMI-30 Implementation Plan](specs/AMI-30-implementation-plan.md) - AuggieMediatedFetcher
- [AMI-31 Implementation Plan](specs/AMI-31-implementation-plan.md) - DirectAPIFetcher

---

## Implementation Notes

> **Architecture Review Updates (2026-01-25):**
>
> 1. **File Location Changed**: From `specflow/integrations/providers/cache.py` to `spec/integrations/cache.py` - caching is an orchestration concern, not a provider concern.
>
> 2. **Decorator Removed**: The `@cached_fetch` decorator pattern from Section 8.3 is NOT implemented. Per architecture review, caching is handled by `TicketService`, not by individual providers.
>
> 3. **Dependency on AMI-32**: `TicketService` is the primary consumer of `TicketCache`. The integration pattern is documented in the Integration Points section.
>
> 4. **Thread Safety**: All cache implementations use `threading.Lock` for concurrent access safety. This is critical for CLI usage where multiple threads may access the cache.
>
> 5. **ETag Support**: Enables conditional requests for platforms like GitHub that support `If-None-Match` headers. This can reduce API quota usage significantly.
