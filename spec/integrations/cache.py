"""Caching layer for ticket data.

This module provides efficient caching of ticket data to minimize API calls
and improve responsiveness. Caching is owned by TicketService (AMI-32),
not individual providers.

See specs/00_Architecture_Refactor_Spec.md Section 8 for design details.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    def from_ticket(cls, ticket: GenericTicket) -> CacheKey:
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

    ticket: GenericTicket
    cached_at: datetime
    expires_at: datetime
    etag: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return datetime.now() > self.expires_at

    @property
    def ttl_remaining(self) -> timedelta:
        """Get remaining time-to-live for this entry."""
        remaining = self.expires_at - datetime.now()
        return remaining if remaining.total_seconds() > 0 else timedelta(0)


class TicketCache(ABC):
    """Abstract base class for ticket cache storage.

    Implementations must be thread-safe for concurrent access.
    """

    @abstractmethod
    def get(self, key: CacheKey) -> GenericTicket | None:
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
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
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
    def get_cached_ticket(self, key: CacheKey) -> CachedTicket | None:
        """Retrieve full CachedTicket with metadata.

        Args:
            key: Cache key for the ticket

        Returns:
            CachedTicket with full metadata, or None if not found/expired
        """
        pass

    @abstractmethod
    def get_etag(self, key: CacheKey) -> str | None:
        """Get ETag for conditional requests.

        Args:
            key: Cache key to get ETag for

        Returns:
            ETag string if available, None otherwise
        """
        pass


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

    def get(self, key: CacheKey) -> GenericTicket | None:
        """Retrieve cached ticket if not expired."""
        cached = self.get_cached_ticket(key)
        return cached.ticket if cached else None

    def get_cached_ticket(self, key: CacheKey) -> CachedTicket | None:
        """Retrieve full CachedTicket with metadata.

        Returns a deep copy to prevent callers from mutating cached data.
        """
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
            # Return deep copy to prevent mutation of cached data
            return copy.deepcopy(cached)

    def set(
        self,
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
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

    def get_etag(self, key: CacheKey) -> str | None:
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
        """Get file path for cache key.

        Uses SHA256 hash of ticket_id to create safe filenames that avoid
        filesystem issues with special characters while preventing collisions.
        """
        safe_id = hashlib.sha256(key.ticket_id.encode()).hexdigest()[:16]
        return self.cache_dir / f"{key.platform.name}_{safe_id}.json"

    def _serialize_ticket(self, cached: CachedTicket) -> dict:
        """Serialize CachedTicket to JSON-compatible dict."""
        ticket_dict = asdict(cached.ticket)
        # Convert enums to strings for JSON
        # Platform uses auto() so we use .name; Status/Type have string values
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
            ticket_data["platform"] = Platform[ticket_data["platform"]]
            ticket_data["status"] = TicketStatus(ticket_data["status"])
            ticket_data["type"] = TicketType(ticket_data["type"])
            # Convert ISO format back to datetime
            if ticket_data.get("created_at"):
                ticket_data["created_at"] = datetime.fromisoformat(ticket_data["created_at"])
            if ticket_data.get("updated_at"):
                ticket_data["updated_at"] = datetime.fromisoformat(ticket_data["updated_at"])

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

    def get(self, key: CacheKey) -> GenericTicket | None:
        """Retrieve cached ticket if not expired."""
        cached = self.get_cached_ticket(key)
        return cached.ticket if cached else None

    def get_cached_ticket(self, key: CacheKey) -> CachedTicket | None:
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
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
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

    def get_etag(self, key: CacheKey) -> str | None:
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


# Global cache singleton
_global_cache: TicketCache | None = None
_global_cache_type: str | None = None
_cache_lock = threading.Lock()


def get_global_cache(
    cache_type: str = "memory",
    **kwargs: Any,
) -> TicketCache:
    """Get or create the global cache singleton.

    Note: After the first call, subsequent calls return the existing cache
    instance. If different parameters are passed, a warning is logged but
    the existing cache is still returned. Use `clear_global_cache()` first
    if you need to reinitialize with different settings.

    Args:
        cache_type: Type of cache ('memory' or 'file')
        **kwargs: Additional arguments passed to cache constructor

    Returns:
        Global TicketCache instance
    """
    global _global_cache, _global_cache_type

    with _cache_lock:
        if _global_cache is None:
            _global_cache_type = cache_type
            if cache_type == "file":
                _global_cache = FileBasedTicketCache(**kwargs)
                logger.info("Initialized file-based ticket cache")
            else:
                _global_cache = InMemoryTicketCache(**kwargs)
                logger.info("Initialized in-memory ticket cache")
        elif cache_type != _global_cache_type:
            logger.warning(
                f"get_global_cache() called with cache_type='{cache_type}' but "
                f"global cache already initialized as '{_global_cache_type}'. "
                "Returning existing cache. Use clear_global_cache() to reinitialize."
            )

        return _global_cache


def set_global_cache(cache: TicketCache) -> None:
    """Set the global cache instance (primarily for testing).

    Args:
        cache: TicketCache instance to use globally
    """
    global _global_cache, _global_cache_type

    with _cache_lock:
        _global_cache = cache
        # Set type based on instance type
        if isinstance(cache, FileBasedTicketCache):
            _global_cache_type = "file"
        else:
            _global_cache_type = "memory"


def clear_global_cache() -> None:
    """Clear and reset the global cache singleton."""
    global _global_cache, _global_cache_type

    with _cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
            _global_cache = None
        _global_cache_type = None
