"""Tests for ticket caching layer."""

import os
import queue
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from spec.integrations.cache import (
    CacheConfigurationError,
    CachedTicket,
    CacheKey,
    FileBasedTicketCache,
    InMemoryTicketCache,
    # Use internal APIs directly to avoid deprecation warnings in tests
    _clear_global_cache,
    _get_global_cache,
    _set_global_cache,
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


@pytest.fixture
def linear_ticket():
    """Create a sample Linear ticket for testing."""
    return GenericTicket(
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


class TestCacheKey:
    """Test CacheKey dataclass."""

    def test_string_representation(self):
        key = CacheKey(Platform.JIRA, "PROJ-123")
        assert str(key) == "JIRA:PROJ-123"

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
        now = datetime.now(UTC)
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert cached.is_expired is False

    def test_is_expired_true(self, sample_ticket):
        now = datetime.now(UTC)
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert cached.is_expired is True

    def test_ttl_remaining(self, sample_ticket):
        now = datetime.now(UTC)
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        assert cached.ttl_remaining.total_seconds() > 0
        assert cached.ttl_remaining.total_seconds() <= 30 * 60

    def test_ttl_remaining_expired(self, sample_ticket):
        now = datetime.now(UTC)
        cached = CachedTicket(
            ticket=sample_ticket,
            cached_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert cached.ttl_remaining.total_seconds() == 0


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

    def test_clear_platform(self, cache, sample_ticket, linear_ticket):
        cache.set(sample_ticket)
        cache.set(linear_ticket)
        assert cache.size() == 2

        cache.clear_platform(Platform.JIRA)
        assert cache.size() == 1
        assert cache.get(CacheKey(Platform.LINEAR, "ENG-456")) is not None

    def test_lru_eviction(self):
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

    def test_get_cached_ticket_returns_metadata(self, cache, sample_ticket):
        cache.set(sample_ticket, etag="test-etag")
        key = CacheKey.from_ticket(sample_ticket)
        cached = cache.get_cached_ticket(key)
        assert cached is not None
        assert cached.ticket.id == sample_ticket.id
        assert cached.etag == "test-etag"
        assert cached.cached_at is not None
        assert cached.expires_at is not None

    def test_stats(self, cache, sample_ticket, linear_ticket):
        cache.set(sample_ticket)
        cache.set(linear_ticket)
        stats = cache.stats()
        assert stats["JIRA"] == 1
        assert stats["LINEAR"] == 1

    def test_get_returns_copy_not_reference(self, cache, sample_ticket):
        """Test that get() returns a copy, preventing mutation of cached data."""
        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)

        # Get the ticket and mutate it
        retrieved = cache.get(key)
        assert retrieved is not None
        original_title = retrieved.title
        # Note: GenericTicket is a dataclass, not frozen, so we can mutate
        # But the cache should return a copy, so mutation shouldn't affect cache
        object.__setattr__(retrieved, "title", "MUTATED TITLE")

        # Get again - should have original title
        retrieved2 = cache.get(key)
        assert retrieved2 is not None
        assert retrieved2.title == original_title

    def test_thread_safety_no_exceptions(self, cache, sample_ticket):
        """Test concurrent access doesn't raise exceptions.

        Uses queue.Queue for thread-safe error collection.
        """
        error_queue: queue.Queue[Exception] = queue.Queue()

        def cache_operations() -> None:
            try:
                for _ in range(100):
                    cache.set(sample_ticket)
                    key = CacheKey.from_ticket(sample_ticket)
                    cache.get(key)
                    cache.invalidate(key)
            except Exception as e:
                error_queue.put(e)

        threads = [threading.Thread(target=cache_operations) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert error_queue.empty(), f"Errors occurred: {list(error_queue.queue)}"

    def test_thread_safety_data_integrity(self):
        """Test concurrent writes maintain data integrity.

        Uses queue.Queue for thread-safe result collection.
        """
        cache = InMemoryTicketCache(default_ttl=timedelta(hours=1))
        result_queue: queue.Queue[tuple[int, int]] = queue.Queue()
        num_threads = 10
        iterations = 50

        def write_unique_ticket(thread_id: int) -> None:
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

        def verify_tickets(thread_id: int) -> None:
            """Verify all tickets from a thread are retrievable."""
            found = 0
            for i in range(iterations):
                key = CacheKey(Platform.JIRA, f"THREAD{thread_id}-{i}")
                if cache.get(key) is not None:
                    found += 1
            result_queue.put((thread_id, found))

        # Write phase
        write_threads = [
            threading.Thread(target=write_unique_ticket, args=(i,)) for i in range(num_threads)
        ]
        for t in write_threads:
            t.start()
        for t in write_threads:
            t.join()

        # Verify phase
        verify_threads = [
            threading.Thread(target=verify_tickets, args=(i,)) for i in range(num_threads)
        ]
        for t in verify_threads:
            t.start()
        for t in verify_threads:
            t.join()

        # Collect results from queue
        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

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

    def test_stats(self, sample_ticket, linear_ticket, tmp_path):
        cache = FileBasedTicketCache(cache_dir=tmp_path)
        cache.set(sample_ticket)
        cache.set(linear_ticket)

        stats = cache.stats()
        assert stats["JIRA"] == 1
        assert stats["LINEAR"] == 1

    def test_invalidate(self, cache, sample_ticket):
        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get(key) is not None
        cache.invalidate(key)
        assert cache.get(key) is None

    def test_clear(self, cache, sample_ticket, linear_ticket):
        cache.set(sample_ticket)
        cache.set(linear_ticket)
        assert cache.size() == 2
        cache.clear()
        assert cache.size() == 0

    def test_clear_platform(self, cache, sample_ticket, linear_ticket):
        cache.set(sample_ticket)
        cache.set(linear_ticket)
        assert cache.size() == 2

        cache.clear_platform(Platform.JIRA)
        assert cache.size() == 1
        assert cache.get(CacheKey(Platform.LINEAR, "ENG-456")) is not None

    def test_etag_support(self, cache, sample_ticket):
        cache.set(sample_ticket, etag="file-etag-123")
        key = CacheKey.from_ticket(sample_ticket)
        assert cache.get_etag(key) == "file-etag-123"

    def test_lru_eviction(self, sample_ticket, tmp_path):
        """Test LRU eviction using deterministic file timestamps.

        Uses os.utime() for explicit timestamp control instead of time.sleep()
        to avoid flaky tests.

        Note: With max_size=2 and threshold=math.ceil(2*1.1)=3, we need 4 items
        to exceed the threshold and trigger eviction.
        """
        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=2,
        )
        base_time = time.time()

        # Add 4 tickets to exceed threshold (ceil(2*1.1)=3)
        tickets = []
        for i in range(4):
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
            tickets.append(ticket)

        # Set explicit timestamps using os.utime for deterministic ordering
        # PROJ-0 is oldest, PROJ-3 is newest
        # Note: Some files may have been evicted by lazy eviction during set()
        for i, ticket in enumerate(tickets):
            key = CacheKey.from_ticket(ticket)
            path = cache._get_path(key)
            if path.exists():  # File may have been evicted already
                file_time = base_time + i
                os.utime(path, (file_time, file_time))

        # Force eviction (bypasses probabilistic check)
        cache.force_evict()

        assert cache.size() == 2
        # Verify only 2 tickets remain (the newest ones based on mtime)
        remaining = [cache.get(CacheKey(Platform.JIRA, f"PROJ-{i}")) for i in range(4)]
        remaining_count = sum(1 for r in remaining if r is not None)
        assert remaining_count == 2, f"Expected 2 remaining tickets, got {remaining_count}"

    def test_corrupted_json_file_returns_none(self, cache, sample_ticket):
        """Test that corrupted JSON files are handled gracefully."""
        from spec.integrations.cache import CacheKey

        cache.set(sample_ticket)
        key = CacheKey.from_ticket(sample_ticket)
        path = cache._get_path(key)

        # Corrupt the JSON file
        path.write_text("{ invalid json content")

        # Should return None and delete the corrupted file
        result = cache.get(key)
        assert result is None
        assert not path.exists()

    def test_thread_safety_file_cache(self, tmp_path, sample_ticket):
        """Test concurrent access to file-based cache.

        Uses queue.Queue for thread-safe error collection.
        """
        cache = FileBasedTicketCache(cache_dir=tmp_path, default_ttl=timedelta(hours=1))
        error_queue: queue.Queue[Exception] = queue.Queue()

        def cache_operations(thread_id: int) -> None:
            try:
                for i in range(20):
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
                    key = CacheKey.from_ticket(ticket)
                    cache.get(key)
            except Exception as e:
                error_queue.put(e)

        threads = [threading.Thread(target=cache_operations, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert error_queue.empty(), f"Errors occurred: {list(error_queue.queue)}"

    def test_no_temp_file_leak_on_serialization_error(self, tmp_path):
        """Test that non-serializable data doesn't leave orphaned .tmp files.

        P0 Fix: Ensures _atomic_write cleans up temp files even when json.dump
        fails with TypeError (e.g., for non-serializable platform_metadata).
        """
        cache = FileBasedTicketCache(cache_dir=tmp_path, default_ttl=timedelta(hours=1))

        # Create a ticket with non-serializable platform_metadata
        ticket_with_bad_metadata = GenericTicket(
            id="BAD-123",
            platform=Platform.JIRA,
            url="https://example.com/BAD-123",
            title="Ticket with non-serializable metadata",
            description="",
            status=TicketStatus.OPEN,
            type=TicketType.TASK,
            assignee=None,
            labels=[],
            created_at=None,
            updated_at=None,
            branch_summary="bad-ticket",
            # Non-serializable objects: set and object()
            platform_metadata={
                "bad_set": {1, 2, 3},  # Sets are not JSON serializable
                "bad_object": object(),  # Custom objects are not JSON serializable
            },
        )

        # This should fail gracefully without raising an exception
        # (the cache logs a warning instead)
        cache.set(ticket_with_bad_metadata)

        # Check that no .tmp files were left behind
        tmp_files = list(tmp_path.glob(".cache_*.tmp"))
        assert len(tmp_files) == 0, f"Orphaned temp files found: {tmp_files}"

        # Also verify no cache file was created for this ticket
        key = CacheKey.from_ticket(ticket_with_bad_metadata)
        assert cache.get(key) is None

    def test_atomic_write_cleans_up_on_json_dump_type_error(self, tmp_path, sample_ticket):
        """Test that _atomic_write cleans up temp files when json.dump raises TypeError.

        P0 Fix: Uses unittest.mock to directly mock json.dump to raise TypeError,
        ensuring the cleanup path in _atomic_write's finally block is exercised.
        """
        from unittest.mock import patch

        cache = FileBasedTicketCache(cache_dir=tmp_path, default_ttl=timedelta(hours=1))

        # Mock json.dump to raise TypeError
        with patch(
            "spec.integrations.cache.json.dump", side_effect=TypeError("Test serialization error")
        ):
            # This should raise TypeError (not caught by set())
            # Actually, set() catches TypeError and logs a warning
            cache.set(sample_ticket)

        # Check that no .tmp files were left behind
        tmp_files = list(tmp_path.glob(".cache_*.tmp"))
        assert len(tmp_files) == 0, f"Orphaned temp files found: {tmp_files}"

        # Verify the cache directory is empty (no successful writes)
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 0, f"Unexpected cache files found: {json_files}"

    def test_atomic_write_raises_and_cleans_up_on_type_error(self, tmp_path):
        """Test that _atomic_write raises TypeError but still cleans up temp files.

        This test directly calls _atomic_write to verify the exception bubbles up
        while temp files are still cleaned.
        """
        from unittest.mock import patch

        cache = FileBasedTicketCache(cache_dir=tmp_path, default_ttl=timedelta(hours=1))

        test_path = tmp_path / "test_write.json"
        test_data = {"key": "value"}

        # Mock json.dump to raise TypeError
        with patch("spec.integrations.cache.json.dump", side_effect=TypeError("Test error")):
            with pytest.raises(TypeError, match="Test error"):
                cache._atomic_write(test_path, test_data)

        # Check that no .tmp files were left behind
        tmp_files = list(tmp_path.glob(".cache_*.tmp"))
        assert len(tmp_files) == 0, f"Orphaned temp files found: {tmp_files}"

        # Test file should not exist either
        assert not test_path.exists()

    def test_eviction_threshold_with_small_max_size(self, tmp_path):
        """Test that math.ceil correctly provides buffer for small max_size values.

        P2 Fix: Ensures int(max_size * 1.1) doesn't round down to max_size
        for small values like max_size=2 (int(2.2) == 2, no buffer).
        Using math.ceil(2 * 1.1) = 3 ensures proper headroom.
        """
        # With max_size=2 and math.ceil(2 * 1.1) = 3 as threshold
        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=2,
        )
        base_time = time.time()

        # Add 4 tickets to exceed threshold (ceil(2*1.1)=3)
        tickets = []
        for i in range(4):
            ticket = GenericTicket(
                id=f"THRESH-{i}",
                platform=Platform.JIRA,
                url=f"https://example.com/THRESH-{i}",
                title=f"Threshold Ticket {i}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"thresh-ticket-{i}",
                platform_metadata={},
            )
            cache.set(ticket)
            tickets.append(ticket)

        # Set explicit timestamps: THRESH-0 oldest, THRESH-3 newest
        for i, ticket in enumerate(tickets):
            key = CacheKey.from_ticket(ticket)
            path = cache._get_path(key)
            if path.exists():  # File may have been evicted already
                file_time = base_time + i
                os.utime(path, (file_time, file_time))

        # Force eviction to trigger (in case lazy eviction didn't run)
        cache.force_evict()

        # Should now be at max_size=2
        assert cache.size() == 2

        # The two newest tickets should remain (THRESH-2 and THRESH-3)
        assert cache.get(CacheKey(Platform.JIRA, "THRESH-2")) is not None
        assert cache.get(CacheKey(Platform.JIRA, "THRESH-3")) is not None

    def test_eviction_threshold_boundary_max_size_5(self, tmp_path):
        """Test eviction threshold boundary: max_size=5, threshold=ceil(5*1.1)=6.

        Verifies:
        - Eviction does NOT trigger when count is 5 (at max_size)
        - Eviction does NOT trigger when count is 6 (at threshold)
        - Eviction DOES trigger when count exceeds 6 (> threshold)
        """
        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=5,
        )
        base_time = time.time()

        def create_and_set_ticket(idx: int) -> GenericTicket:
            ticket = GenericTicket(
                id=f"BOUND-{idx}",
                platform=Platform.JIRA,
                url=f"https://example.com/BOUND-{idx}",
                title=f"Boundary Ticket {idx}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"bound-ticket-{idx}",
                platform_metadata={},
            )
            cache.set(ticket)
            # Set explicit timestamp for deterministic ordering
            key = CacheKey.from_ticket(ticket)
            path = cache._get_path(key)
            if path.exists():
                file_time = base_time + idx
                os.utime(path, (file_time, file_time))
            return ticket

        # Add exactly 5 tickets (at max_size)
        for i in range(5):
            create_and_set_ticket(i)

        # Force eviction - should NOT evict (5 <= 6 threshold)
        cache.force_evict()
        assert cache.size() == 5, "No eviction should occur when count equals max_size"

        # Add 1 more ticket (now at 6, which equals threshold)
        create_and_set_ticket(5)
        cache.force_evict()
        assert cache.size() == 6, "No eviction should occur when count equals threshold (6)"

        # Add 1 more ticket (now at 7, exceeds threshold)
        create_and_set_ticket(6)
        cache.force_evict()
        # After eviction, should be back to max_size=5
        assert cache.size() == 5, "Eviction should occur when count exceeds threshold"

        # The 5 newest tickets should remain (BOUND-2 through BOUND-6)
        assert cache.get(CacheKey(Platform.JIRA, "BOUND-0")) is None
        assert cache.get(CacheKey(Platform.JIRA, "BOUND-1")) is None
        for i in range(2, 7):
            assert (
                cache.get(CacheKey(Platform.JIRA, f"BOUND-{i}")) is not None
            ), f"BOUND-{i} should remain"

    def test_eviction_handles_file_deletion_race(self, tmp_path):
        """Test that eviction handles files being deleted during scan.

        P1 Fix: Uses os.scandir with proper exception handling to avoid
        FileNotFoundError when a file is deleted between listing and stat.

        The main goal is to verify eviction doesn't crash when files disappear.
        """
        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=5,
        )

        # Add 10 tickets (lazy eviction may run during set() calls)
        for i in range(10):
            ticket = GenericTicket(
                id=f"RACE-{i}",
                platform=Platform.JIRA,
                url=f"https://example.com/RACE-{i}",
                title=f"Race Ticket {i}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"race-ticket-{i}",
                platform_metadata={},
            )
            cache.set(ticket)

        # Get current file count and delete one file to simulate race condition
        json_files = list(tmp_path.glob("*.json"))
        initial_count = len(json_files)

        if json_files:
            # Delete one file to simulate race condition
            json_files[0].unlink()

        # This should NOT crash even though a file was deleted
        # This is the main assertion - no exception should be raised
        cache.force_evict()

        # Cache should still be functional
        final_size = cache.size()
        # After eviction, size should be at most max_size (5)
        # But we're mainly testing that it doesn't crash
        assert final_size <= max(
            5, initial_count - 1
        ), f"Cache size {final_size} should be reasonable after eviction"

    def test_eviction_handles_stat_race_with_mock(self, tmp_path):
        """Test that eviction handles FileNotFoundError during stat() with mock.

        P1 Fix: Uses unittest.mock to simulate a FileNotFoundError occurring
        when stat() is called on an entry during the scandir iteration.
        This tests the try/except FileNotFoundError block in _evict_lru.
        """
        from unittest.mock import MagicMock, patch

        cache = FileBasedTicketCache(
            cache_dir=tmp_path,
            default_ttl=timedelta(hours=1),
            max_size=2,
        )

        # Add tickets to populate the cache
        for i in range(5):
            ticket = GenericTicket(
                id=f"MOCK-{i}",
                platform=Platform.JIRA,
                url=f"https://example.com/MOCK-{i}",
                title=f"Mock Ticket {i}",
                description="",
                status=TicketStatus.OPEN,
                type=TicketType.TASK,
                assignee=None,
                labels=[],
                created_at=None,
                updated_at=None,
                branch_summary=f"mock-ticket-{i}",
                platform_metadata={},
            )
            cache.set(ticket)

        # Create a mock DirEntry that raises FileNotFoundError on stat()
        def create_mock_entries():
            """Create a mix of normal and failing mock DirEntry objects."""
            entries = []

            # Create normal entries for existing files
            for path in tmp_path.glob("*.json"):
                mock_entry = MagicMock()
                mock_entry.name = path.name
                mock_entry.path = str(path)
                mock_entry.is_file.return_value = True
                mock_entry.stat.return_value = path.stat()
                entries.append(mock_entry)

            # Insert a "ghost" entry that raises FileNotFoundError on stat()
            ghost_entry = MagicMock()
            ghost_entry.name = "ghost_file.json"
            ghost_entry.path = str(tmp_path / "ghost_file.json")
            ghost_entry.is_file.return_value = True
            ghost_entry.stat.side_effect = FileNotFoundError("File vanished")
            entries.insert(0, ghost_entry)  # Insert at beginning

            return iter(entries)

        # Patch os.scandir to return our mock entries
        with patch("os.scandir") as mock_scandir:
            # Create a context manager mock
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=create_mock_entries())
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_scandir.return_value = mock_context

            # This should NOT raise an exception - the FileNotFoundError
            # should be caught and the ghost entry should be skipped
            cache.force_evict()

        # Cache should still be functional after eviction
        # The exact size may vary based on eviction, but it shouldn't crash
        assert cache.size() >= 0


class TestGlobalCache:
    """Test global cache singleton functions (internal APIs)."""

    def test_get_global_cache_singleton(self):
        _clear_global_cache()
        cache1 = _get_global_cache()
        cache2 = _get_global_cache()
        assert cache1 is cache2
        _clear_global_cache()

    def test_set_global_cache(self):
        _clear_global_cache()
        custom_cache = InMemoryTicketCache(max_size=100)
        _set_global_cache(custom_cache)
        assert _get_global_cache() is custom_cache
        _clear_global_cache()

    def test_get_global_cache_memory_type(self):
        _clear_global_cache()
        cache = _get_global_cache(cache_type="memory")
        assert isinstance(cache, InMemoryTicketCache)
        _clear_global_cache()

    def test_get_global_cache_file_type(self, tmp_path):
        _clear_global_cache()
        cache = _get_global_cache(cache_type="file", cache_dir=tmp_path)
        assert isinstance(cache, FileBasedTicketCache)
        _clear_global_cache()

    def test_clear_global_cache_clears_entries(self, sample_ticket):
        _clear_global_cache()
        cache = _get_global_cache()
        cache.set(sample_ticket)
        assert cache.size() == 1
        _clear_global_cache()
        # After clear, getting global cache should return a new empty cache
        new_cache = _get_global_cache()
        assert new_cache.size() == 0
        _clear_global_cache()

    def test_get_global_cache_type_mismatch_strict_raises(self, tmp_path):
        """Test that strict mode raises CacheConfigurationError on type mismatch."""
        _clear_global_cache()
        # Initialize as memory cache
        cache1 = _get_global_cache(cache_type="memory")
        assert isinstance(cache1, InMemoryTicketCache)

        # Try to get as file cache with strict=True (default) - should raise
        with pytest.raises(CacheConfigurationError) as exc_info:
            _get_global_cache(cache_type="file", cache_dir=tmp_path)

        assert "cache_type='file' vs existing='memory'" in str(exc_info.value)
        _clear_global_cache()

    def test_get_global_cache_type_mismatch_non_strict_warning(self, tmp_path, caplog):
        """Test that non-strict mode logs warning on type mismatch."""
        import logging

        _clear_global_cache()
        # Initialize as memory cache
        cache1 = _get_global_cache(cache_type="memory")
        assert isinstance(cache1, InMemoryTicketCache)

        # Try to get as file cache with strict=False - should warn and return existing
        with caplog.at_level(logging.WARNING):
            cache2 = _get_global_cache(cache_type="file", cache_dir=tmp_path, strict=False)

        assert cache2 is cache1  # Should return the same cache
        assert isinstance(cache2, InMemoryTicketCache)  # Still memory cache
        assert "different configuration" in caplog.text
        _clear_global_cache()

    def test_get_global_cache_kwargs_mismatch_strict_raises(self):
        """Test that strict mode raises CacheConfigurationError on kwargs mismatch."""
        _clear_global_cache()
        # Initialize with max_size=100
        cache1 = _get_global_cache(cache_type="memory", max_size=100)
        assert isinstance(cache1, InMemoryTicketCache)

        # Try to get with different max_size - should raise
        with pytest.raises(CacheConfigurationError) as exc_info:
            _get_global_cache(cache_type="memory", max_size=200)

        assert "kwargs=" in str(exc_info.value)
        _clear_global_cache()

    def test_set_global_cache_updates_type(self, tmp_path, caplog):
        """Test that _set_global_cache correctly updates the cache type."""
        import logging

        _clear_global_cache()

        # Set a file-based cache
        file_cache = FileBasedTicketCache(cache_dir=tmp_path)
        _set_global_cache(file_cache)

        # Verify the cache is the file cache we set (use file type to match)
        assert _get_global_cache(cache_type="file") is file_cache

        # Getting with memory type should raise (cache is file type)
        with pytest.raises(CacheConfigurationError):
            _get_global_cache(cache_type="memory")

        # With strict=False, should warn and return existing
        with caplog.at_level(logging.WARNING):
            cache = _get_global_cache(cache_type="memory", strict=False)

        assert cache is file_cache  # Should return existing cache
        assert "different configuration" in caplog.text
        _clear_global_cache()
