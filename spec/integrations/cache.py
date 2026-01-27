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
    from spec.integrations.providers.base import GenericTicket

from spec.integrations.providers.base import Platform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheKey:
    """Unique cache key for ticket data.

    P2 Fix: ticket_id is URL-encoded in __str__ to handle special characters
    like colons (:) which could otherwise break parsing logic. The encoding
    uses 'safe=""' to ensure all special chars are encoded.

    Attributes:
        platform: The platform this ticket belongs to
        ticket_id: Normalized ticket identifier (e.g., 'PROJ-123', 'owner/repo#42')
    """

    platform: Platform
    ticket_id: str

    def __str__(self) -> str:
        """Generate string key for storage.

        P2 Fix: URL-encodes ticket_id to safely handle special characters
        (colons, slashes, etc.) that could break parsing. Uses safe="" to
        encode all special characters for maximum safety.
        """
        encoded_id = urllib.parse.quote(self.ticket_id, safe="")
        return f"{self.platform.name}:{encoded_id}"

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
        cached_at: Timestamp when the ticket was cached (UTC)
        expires_at: Timestamp when the cache entry expires (UTC)
        etag: Optional ETag for conditional requests (e.g., GitHub)

    Note:
        All timestamps use UTC to avoid DST and system clock ambiguity.
    """

    ticket: GenericTicket
    cached_at: datetime
    expires_at: datetime
    etag: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if this cache entry has expired.

        Uses UTC time for consistent behavior across timezones.
        """
        return datetime.now(UTC) > self.expires_at

    @property
    def ttl_remaining(self) -> timedelta:
        """Get remaining time-to-live for this entry.

        Uses UTC time for consistent behavior across timezones.
        """
        remaining = self.expires_at - datetime.now(UTC)
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

    Concurrency Model:
        - Uses threading.Lock for thread-safe access to the internal OrderedDict.
        - Performs deepcopy OUTSIDE the lock to minimize contention.
        - Stores a deepcopy on set() to prevent external mutation from
          corrupting the cache.

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
        Lock is held only during dict access; deepcopy happens outside lock
        to minimize contention.
        """
        # Step 1: Lock -> Get item -> Validate expiry -> Move to end -> Unlock
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

            # Move to end for LRU tracking
            self._cache.move_to_end(key_str)
            logger.debug(f"Cache hit for {key}")

        # Step 2: Deepcopy OUTSIDE the lock to reduce contention
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

        # Create CachedTicket with a deep copy of the ticket (P0 fix)
        cached = CachedTicket(
            ticket=copy.deepcopy(ticket),
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

    Concurrency Model:
        - Uses threading.Lock for thread-safe access within a single process.
        - Uses atomic writes (tempfile + os.replace) for crash-safety.
        - Optimistic concurrency (Last-writer-wins) for multi-process scenarios.
          Partial/corrupted writes are prevented by atomic rename.
        - LRU eviction uses file modification time; get() updates mtime to ensure
          recently accessed items are retained.

    Warning:
        **NOT MULTI-PROCESS SAFE** without external locking (e.g., file locks,
        Redis, or a dedicated cache service). Concurrent access from multiple
        processes may result in:
        - Lost updates (last writer wins)
        - Inconsistent reads during concurrent writes
        - Race conditions during eviction

        For multi-process deployments, consider using Redis or a database-backed
        cache, or implement external file locking.

    Lazy Eviction Strategy:
        - Eviction only runs probabilistically (10% chance per write) when cache
          size exceeds max_size * 1.1 (110% threshold).
        - This avoids O(N) disk scan on every set() operation.

    Attributes:
        cache_dir: Directory for cache files
        default_ttl: Default TTL for cache entries
        max_size: Maximum number of entries (0 = unlimited)
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
        """Initialize file-based cache.

        Args:
            cache_dir: Directory for cache files (default: ~/.specflow-cache)
            default_ttl: Default TTL for entries (default: 1 hour)
            max_size: Maximum entries before LRU eviction (0 = unlimited)
            eviction_rng: Optional Random instance for deterministic eviction
                behavior in tests. If None (default), uses global random.random().
                Pass random.Random(seed) for reproducible eviction behavior.
        """
        self.cache_dir = cache_dir or Path.home() / ".specflow-cache"
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Approximate cache size to avoid frequent disk scans
        self._approx_size: int | None = None
        # P2 FIX: Injectable RNG for deterministic testing
        self._eviction_rng = eviction_rng

    def _get_path(self, key: CacheKey) -> Path:
        """Get file path for cache key.

        Uses SHA256 hash (32 chars) of ticket_id to create safe filenames
        that avoid filesystem issues with special characters while minimizing
        collision risk.
        """
        # Increased from 16 to 32 characters for reduced collision risk
        safe_id = hashlib.sha256(key.ticket_id.encode()).hexdigest()[:32]
        return self.cache_dir / f"{key.platform.name}_{safe_id}.json"

    def _serialize_ticket(self, cached: CachedTicket) -> dict[str, Any]:
        """Serialize CachedTicket to JSON-compatible dict.

        Uses GenericTicket.to_dict() for clean encapsulation.
        """
        return {
            "ticket": cached.ticket.to_dict(),
            "cached_at": cached.cached_at.isoformat(),
            "expires_at": cached.expires_at.isoformat(),
            "etag": cached.etag,
        }

    def _deserialize_ticket(self, data: dict[str, Any]) -> CachedTicket | None:
        """Deserialize JSON dict to CachedTicket.

        Uses GenericTicket.from_dict() for resilient deserialization.
        """
        from spec.integrations.providers.base import GenericTicket

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
        """Retrieve full CachedTicket with metadata.

        Updates file modification time on cache hit to ensure LRU eviction
        removes least recently used items (not just least recently written).
        """
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

                # P1 FIX: Update mtime on cache hit for true LRU behavior
                # This ensures recently accessed items are retained, not just
                # recently written ones.
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

        P0 Fix: Uses try...finally to ensure temp file cleanup for ANY
        failure (TypeError from json.dump, OSError, etc.), preventing resource leaks.
        Also ensures fd is closed even if os.fdopen fails to take ownership.

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

                # P0 FIX: Atomic write using temp file + rename
                self._atomic_write(path, data)
                logger.debug(f"Cached {key} to {path}")

                # Update approximate size counter
                if is_new_file:
                    if self._approx_size is not None:
                        self._approx_size += 1

                # Lazy eviction: probabilistic check to avoid O(N) on every write
                self._maybe_evict_lru()
            except (TypeError, ValueError) as e:
                # P0 FIX: Handle non-JSON-serializable objects in platform_metadata
                # (e.g., datetime objects, sets, custom objects). Log warning and skip caching.
                # No temp file leak: _atomic_write uses try...finally for cleanup.
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
        """Get current number of cached entries.

        Updates the approximate size cache for lazy eviction.
        """
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

        Lazy eviction strategy to avoid O(N) disk scan on every set():
        - Only runs with _EVICTION_PROBABILITY (10%) chance
        - Only evicts if size > max_size * _EVICTION_THRESHOLD_RATIO (110%)

        P2 Fix: Uses injectable RNG (self._eviction_rng) for deterministic
        testing. If None, falls back to global random.random().

        This is called from set() with the lock already held.
        """
        if self.max_size <= 0:
            return

        # Quick check using approximate size if available
        if self._approx_size is not None:
            if self._approx_size <= self.max_size:
                return  # Definitely not over threshold

        # Probabilistic check: only scan 10% of the time
        # P2 FIX: Use injectable RNG for deterministic testing
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
        Eviction threshold is math.ceil(max_size * 1.1) to ensure buffer headroom.

        P1 FIX: Uses os.scandir() instead of glob() + stat() to:
        - Avoid race conditions where files are deleted between listing and stat
        - Improve I/O performance (scandir caches stat info on most platforms)
        """
        if self.max_size <= 0:
            return

        # P1 FIX: Use os.scandir for atomic stat + listing in one syscall
        # This avoids the race condition in glob() + stat() pattern
        files_with_mtime: list[tuple[Path, float]] = []
        try:
            with os.scandir(self.cache_dir) as entries:
                for entry in entries:
                    try:
                        # Only process .json files
                        if entry.is_file() and entry.name.endswith(".json"):
                            # entry.stat() uses cached info from scandir on most platforms
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


# Global cache singleton (internal - use dependency injection via TicketService)
# These globals are maintained for testing convenience only.
_global_cache: TicketCache | None = None
_global_cache_type: str | None = None
# P1 Fix: Use empty dict instead of None for consistent mismatch comparison logic.
# This ensures kwargs comparison always works correctly after clear_global_cache().
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

    Warning:
        This is an internal API for testing convenience. Production code should
        use dependency injection via TicketService (AMI-32) instead of relying
        on global state.

    Args:
        cache_type: Type of cache ('memory' or 'file')
        strict: If True (default), raise CacheConfigurationError when called
            with different parameters than the existing cache. If False,
            log a warning and return the existing cache.
        **kwargs: Additional arguments passed to cache constructor

    Returns:
        Global TicketCache instance

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
    """Set the global cache instance (internal API for testing).

    Warning:
        This is an internal API for testing convenience. Production code should
        use dependency injection via TicketService (AMI-32) instead.

    Args:
        cache: TicketCache instance to use globally
    """
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
    """Clear and reset the global cache singleton (internal API).

    Warning:
        This is an internal API for testing convenience.

    P1 Fix: Reset _global_cache_kwargs to {} instead of None for consistent
    comparison logic in _get_global_cache(). This ensures that after clearing,
    subsequent calls with no kwargs will correctly match the empty state.
    """
    global _global_cache, _global_cache_type, _global_cache_kwargs

    with _cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
            _global_cache = None
        _global_cache_type = None
        # P1 Fix: Use empty dict instead of None for consistent mismatch checks
        _global_cache_kwargs = {}


# Backward compatibility aliases (deprecated - will be removed)
# These are kept temporarily for existing tests but should not be used in production.
def get_global_cache(
    cache_type: str = "memory",
    strict: bool = True,
    **kwargs: Any,
) -> TicketCache:
    """DEPRECATED: Use dependency injection via TicketService instead.

    This function is maintained for backward compatibility with existing tests.
    New code should instantiate cache directly and pass to TicketService.

    See specs/AMI-32-implementation-plan.md for the recommended pattern.
    """
    import warnings

    warnings.warn(
        "get_global_cache() is deprecated. Use dependency injection via TicketService instead. "
        "See AMI-32 for the recommended caching pattern.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_global_cache(cache_type=cache_type, strict=strict, **kwargs)


def set_global_cache(cache: TicketCache) -> None:
    """DEPRECATED: Use dependency injection via TicketService instead."""
    import warnings

    warnings.warn(
        "set_global_cache() is deprecated. Use dependency injection via TicketService instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _set_global_cache(cache)


def clear_global_cache() -> None:
    """DEPRECATED: Use dependency injection via TicketService instead."""
    import warnings

    warnings.warn(
        "clear_global_cache() is deprecated. Use dependency injection via TicketService instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _clear_global_cache()
