"""Caching layer for ticket data.

This module provides efficient caching of ticket data to minimize API calls
and improve responsiveness. Caching is owned by TicketService (AMI-32),
not individual providers.

Concurrency Model:
    - InMemoryTicketCache: Uses threading.Lock for thread-safe access.
      Performs deepcopy outside the lock to minimize contention.
    - FileBasedTicketCache: Uses threading.Lock for thread-safe access within
      a single process. Uses atomic writes (tempfile + os.replace) for
      crash-safety, but is optimistic for multi-process scenarios.
    - Global singleton: Protected by _cache_lock for thread-safe initialization.

See specs/00_Architecture_Refactor_Spec.md Section 8 for design details.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import random
import tempfile
import threading
import urllib.parse
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ingot.integrations.providers.base import GenericTicket

from ingot.integrations.providers.base import Platform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheKey:
    """Unique cache key for ticket data.

    ticket_id is URL-encoded in __str__ to handle special characters
    like colons and slashes that could break parsing logic.
    """

    platform: Platform
    ticket_id: str

    def __str__(self) -> str:
        """Generate string key for storage, URL-encoding ticket_id for safety."""
        encoded_id = urllib.parse.quote(self.ticket_id, safe="")
        return f"{self.platform.name}:{encoded_id}"

    @classmethod
    def from_ticket(cls, ticket: GenericTicket) -> CacheKey:
        """Create cache key from a GenericTicket."""
        return cls(platform=ticket.platform, ticket_id=ticket.id)


@dataclass
class CachedTicket:
    """Cached ticket with expiration metadata. All timestamps use UTC."""

    ticket: GenericTicket
    cached_at: datetime
    expires_at: datetime
    etag: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return datetime.now(UTC) > self.expires_at

    @property
    def ttl_remaining(self) -> timedelta:
        """Get remaining time-to-live for this entry."""
        remaining = self.expires_at - datetime.now(UTC)
        return remaining if remaining.total_seconds() > 0 else timedelta(0)


class TicketCache(ABC):
    """Abstract base class for ticket cache storage.

    Implementations must be thread-safe for concurrent access.
    """

    @abstractmethod
    def get(self, key: CacheKey) -> GenericTicket | None:
        """Retrieve cached ticket if not expired."""
        pass

    @abstractmethod
    def set(
        self,
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
    ) -> None:
        """Store ticket in cache with optional custom TTL."""
        pass

    @abstractmethod
    def invalidate(self, key: CacheKey) -> None:
        """Remove a specific ticket from cache."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all cached tickets."""
        pass

    @abstractmethod
    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a specific platform."""
        pass

    @abstractmethod
    def get_cached_ticket(self, key: CacheKey) -> CachedTicket | None:
        """Retrieve full CachedTicket with metadata."""
        pass

    @abstractmethod
    def get_etag(self, key: CacheKey) -> str | None:
        """Get ETag for conditional requests."""
        pass


class InMemoryTicketCache(TicketCache):
    """In-memory ticket cache with thread-safe access and LRU eviction.

    Uses threading.Lock for thread-safe access. Performs deepcopy outside
    the lock to minimize contention.
    """

    def __init__(
        self,
        default_ttl: timedelta = timedelta(hours=1),
        max_size: int = 0,
    ) -> None:
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
        cached: CachedTicket | None = None
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

            self._cache.move_to_end(key_str)
            logger.debug(f"Cache hit for {key}")

        return copy.deepcopy(cached)

    def set(
        self,
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
    ) -> None:
        """Store ticket in cache.

        Stores a deep copy of the ticket to prevent external mutation
        from corrupting the cache.
        """
        key = CacheKey.from_ticket(ticket)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = datetime.now(UTC)

        # Deep copy to prevent external mutation from corrupting the cache
        cached = CachedTicket(
            ticket=copy.deepcopy(ticket),
            cached_at=now,
            expires_at=now + effective_ttl,
            etag=etag,
        )

        with self._lock:
            key_str = str(key)

            if key_str in self._cache:
                del self._cache[key_str]

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
    """File-based persistent ticket cache (~/.ingot-cache/).

    Uses atomic writes (tempfile + os.replace) for crash-safety and
    probabilistic LRU eviction to avoid O(N) disk scans on every write.

    Not multi-process safe without external locking.
    """

    # Eviction probability and threshold constants
    _EVICTION_THRESHOLD_RATIO: float = 1.1  # Evict when size > max_size * 1.1
    _EVICTION_PROBABILITY: float = 0.1  # 10% chance of checking eviction

    def __init__(
        self,
        cache_dir: Path | None = None,
        default_ttl: timedelta = timedelta(hours=1),
        max_size: int = 0,
        *,
        eviction_rng: random.Random | None = None,
    ) -> None:
        self.cache_dir = cache_dir or Path.home() / ".ingot-cache"
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._approx_size: int | None = None
        self._eviction_rng = eviction_rng

    def _get_path(self, key: CacheKey) -> Path:
        """Get file path for cache key using SHA256 hash of ticket_id."""
        safe_id = hashlib.sha256(key.ticket_id.encode()).hexdigest()[:32]
        return self.cache_dir / f"{key.platform.name}_{safe_id}.json"

    def _serialize_ticket(self, cached: CachedTicket) -> dict[str, Any]:
        """Serialize CachedTicket to JSON-compatible dict."""
        return {
            "ticket": cached.ticket.to_dict(),
            "cached_at": cached.cached_at.isoformat(),
            "expires_at": cached.expires_at.isoformat(),
            "etag": cached.etag,
        }

    def _deserialize_ticket(self, data: dict[str, Any]) -> CachedTicket | None:
        """Deserialize JSON dict to CachedTicket."""
        from ingot.integrations.providers.base import GenericTicket

        try:
            ticket_data = data["ticket"]
            ticket = GenericTicket.from_dict(ticket_data)

            return CachedTicket(
                ticket=ticket,
                cached_at=datetime.fromisoformat(data["cached_at"]),
                expires_at=datetime.fromisoformat(data["expires_at"]),
                etag=data.get("etag"),
            )
        except (KeyError, ValueError, TypeError) as e:
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
                    self._approx_size = None  # Invalidate cache size estimate
                    return None

                if cached.is_expired:
                    path.unlink(missing_ok=True)
                    self._approx_size = None  # Invalidate cache size estimate
                    logger.debug(f"Cache expired for {key}")
                    return None

                # Update mtime on cache hit for true LRU behavior
                try:
                    path.touch()
                except OSError:
                    pass  # Non-critical, continue returning cached data

                logger.debug(f"Cache hit for {key}")
                return cached
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read cache file {path}: {e}")
                try:
                    path.unlink(missing_ok=True)
                    self._approx_size = None
                except OSError:
                    pass
                return None

    def _atomic_write(self, path: Path, data: dict[str, Any]) -> None:
        """Write data to file atomically using temp file + rename.

        This prevents partial/corrupted writes if the process crashes.
        os.replace() is atomic on POSIX systems.

        Uses try...finally to ensure temp file cleanup on any failure.

        Raises:
            TypeError: If data contains non-JSON-serializable objects
            ValueError: If data cannot be serialized
            OSError: If file operations fail
        """
        # Create temp file in same directory to ensure same filesystem
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=".cache_",
            dir=self.cache_dir,
        )
        fd_closed = False
        success = False
        try:
            with os.fdopen(fd, "w") as f:
                fd_closed = True  # os.fdopen takes ownership of fd
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
            success = True
        finally:
            # Close fd if os.fdopen never took ownership (e.g., os.fdopen failed)
            if not fd_closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            # Always clean up temp file on failure
            if not success:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def set(
        self,
        ticket: GenericTicket,
        ttl: timedelta | None = None,
        etag: str | None = None,
    ) -> None:
        """Store ticket in cache with atomic write for crash safety.

        Uses a deep copy of the ticket to prevent external mutation.
        """
        key = CacheKey.from_ticket(ticket)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        now = datetime.now(UTC)

        cached = CachedTicket(
            ticket=copy.deepcopy(ticket),
            cached_at=now,
            expires_at=now + effective_ttl,
            etag=etag,
        )

        path = self._get_path(key)
        with self._lock:
            try:
                is_new_file = not path.exists()
                data = self._serialize_ticket(cached)

                self._atomic_write(path, data)
                logger.debug(f"Cached {key} to {path}")

                # Update approximate size counter
                if is_new_file:
                    if self._approx_size is not None:
                        self._approx_size += 1

                # Lazy eviction: probabilistic check to avoid O(N) on every write
                self._maybe_evict_lru()
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to cache ticket {key} due to serialization error: {e}")
            except OSError as e:
                logger.warning(f"Failed to write cache file {path}: {e}")

    def invalidate(self, key: CacheKey) -> None:
        """Remove a specific ticket from cache."""
        path = self._get_path(key)
        with self._lock:
            if path.exists():
                path.unlink(missing_ok=True)
                self._approx_size = None  # Invalidate cache size estimate
                logger.debug(f"Invalidated cache for {key}")

    def clear(self) -> None:
        """Clear all cached tickets."""
        with self._lock:
            count = 0
            for path in self.cache_dir.glob("*.json"):
                path.unlink(missing_ok=True)
                count += 1
            self._approx_size = 0
            logger.debug(f"Cleared {count} cache files")

    def clear_platform(self, platform: Platform) -> None:
        """Clear all cached tickets for a platform."""
        prefix = f"{platform.name}_"
        with self._lock:
            count = 0
            for path in self.cache_dir.glob(f"{prefix}*.json"):
                path.unlink(missing_ok=True)
                count += 1
            self._approx_size = None  # Invalidate cache size estimate
            logger.debug(f"Cleared {count} cache files for {platform.name}")

    def get_etag(self, key: CacheKey) -> str | None:
        """Get ETag for conditional requests."""
        cached = self.get_cached_ticket(key)
        return cached.etag if cached else None

    def size(self) -> int:
        """Get current number of cached entries."""
        with self._lock:
            count = len(list(self.cache_dir.glob("*.json")))
            self._approx_size = count
            return count

    def stats(self) -> dict[str, int]:
        """Get cache statistics per platform."""
        with self._lock:
            stats: dict[str, int] = {}
            for path in self.cache_dir.glob("*.json"):
                # Filename format: PLATFORM_hash.json
                platform = path.stem.split("_")[0]
                stats[platform] = stats.get(platform, 0) + 1
            return stats

    def _maybe_evict_lru(self) -> None:
        """Probabilistically check and perform LRU eviction.

        Called from set() with the lock already held. Uses injectable RNG
        for deterministic testing.
        """
        if self.max_size <= 0:
            return

        # Quick check using approximate size if available
        if self._approx_size is not None:
            if self._approx_size <= self.max_size:
                return  # Definitely not over threshold

        # Probabilistic check: only scan 10% of the time
        rng_value = (
            self._eviction_rng.random() if self._eviction_rng is not None else random.random()
        )
        if rng_value > self._EVICTION_PROBABILITY:
            return

        # Perform actual eviction check
        self._evict_lru()

    def _evict_lru(self) -> None:
        """Evict least recently used entries if over max_size threshold.

        Uses file modification time as LRU indicator. Called with lock held.
        """
        if self.max_size <= 0:
            return

        files_with_mtime: list[tuple[Path, float]] = []
        try:
            with os.scandir(self.cache_dir) as entries:
                for entry in entries:
                    try:
                        if entry.is_file() and entry.name.endswith(".json"):
                            stat_info = entry.stat()
                            files_with_mtime.append((Path(entry.path), stat_info.st_mtime))
                    except FileNotFoundError:
                        # File was deleted during iteration, skip it
                        continue
                    except OSError:
                        # Other stat errors (permission, etc.), skip file
                        continue
        except OSError as e:
            logger.warning(f"Failed to scan cache directory during eviction: {e}")
            return

        current_size = len(files_with_mtime)
        self._approx_size = current_size

        # Use threshold with math.ceil to ensure buffer headroom for small max_size values
        threshold = math.ceil(self.max_size * self._EVICTION_THRESHOLD_RATIO)
        if current_size <= threshold:
            return

        # Sort by modification time (oldest first)
        files_with_mtime.sort(key=lambda x: x[1])

        # Remove oldest files until at max_size (not threshold)
        to_remove = current_size - self.max_size
        for path, _ in files_with_mtime[:to_remove]:
            try:
                path.unlink(missing_ok=True)
                logger.debug(f"LRU evicted: {path.name}")
            except OSError:
                pass  # File may have been removed by another process

        self._approx_size = self.max_size

    def force_evict(self) -> None:
        """Force LRU eviction check (for testing purposes).

        This bypasses the probabilistic check and forces eviction.
        """
        with self._lock:
            self._evict_lru()


# =============================================================================
# Global Cache Singleton (Internal API - Testing Only)
# =============================================================================
#
# These internal functions (_get_global_cache, _set_global_cache, _clear_global_cache)
# are intentionally kept for testing convenience. They provide a way to manage
# global cache state in tests without requiring full TicketService setup.
#
# IMPORTANT: Production code should NOT use these functions directly.
# Instead, use dependency injection via TicketService (see AMI-32 spec).
#
# Why keep them?
# - Simplifies cache-related unit tests
# - Allows testing cache behavior in isolation
# - Used extensively in tests/test_cache.py
#
# These functions are NOT exported in __all__ and have underscore prefixes
# to indicate their internal status.
# =============================================================================

_global_cache: TicketCache | None = None
_global_cache_type: str | None = None
_global_cache_kwargs: dict[str, Any] = {}
_cache_lock = threading.Lock()


class CacheConfigurationError(ValueError):
    """Raised when _get_global_cache is called with conflicting configuration.

    This indicates that the global cache was already initialized with different
    parameters than the ones being requested. Use _clear_global_cache() first
    to reinitialize with new settings.
    """

    pass


def _get_global_cache(
    cache_type: str = "memory",
    strict: bool = True,
    **kwargs: Any,
) -> TicketCache:
    """Get or create the global cache singleton (internal API).

    Production code should use dependency injection via TicketService instead.

    Raises:
        CacheConfigurationError: If strict=True and the cache was already
            initialized with different parameters.
    """
    global _global_cache, _global_cache_type, _global_cache_kwargs

    with _cache_lock:
        if _global_cache is None:
            _global_cache_type = cache_type
            _global_cache_kwargs = kwargs.copy()
            if cache_type == "file":
                _global_cache = FileBasedTicketCache(**kwargs)
                logger.info("Initialized file-based ticket cache")
            else:
                _global_cache = InMemoryTicketCache(**kwargs)
                logger.info("Initialized in-memory ticket cache")
        else:
            # Check for configuration mismatch
            type_mismatch = cache_type != _global_cache_type
            kwargs_mismatch = kwargs != _global_cache_kwargs

            if type_mismatch or kwargs_mismatch:
                mismatch_details = []
                if type_mismatch:
                    mismatch_details.append(
                        f"cache_type='{cache_type}' vs existing='{_global_cache_type}'"
                    )
                if kwargs_mismatch:
                    mismatch_details.append(f"kwargs={kwargs} vs existing={_global_cache_kwargs}")

                message = (
                    f"_get_global_cache() called with different configuration than "
                    f"existing cache: {', '.join(mismatch_details)}. "
                    f"Use _clear_global_cache() to reinitialize with new settings."
                )

                if strict:
                    raise CacheConfigurationError(message)
                else:
                    logger.warning(message)

        return _global_cache


def _set_global_cache(cache: TicketCache) -> None:
    """Set the global cache instance (internal API for testing)."""
    global _global_cache, _global_cache_type, _global_cache_kwargs

    with _cache_lock:
        _global_cache = cache
        # Set type based on instance type
        if isinstance(cache, FileBasedTicketCache):
            _global_cache_type = "file"
        else:
            _global_cache_type = "memory"
        # Clear kwargs since we don't know what was used to construct this cache
        _global_cache_kwargs = {}


def _clear_global_cache() -> None:
    """Clear and reset the global cache singleton (internal API)."""
    global _global_cache, _global_cache_type, _global_cache_kwargs

    with _cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
            _global_cache = None
        _global_cache_type = None
        _global_cache_kwargs = {}
