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
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from spec.integrations.cache import CacheKey, InMemoryTicketCache, TicketCache
from spec.integrations.fetchers import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    AuggieMediatedFetcher,
    DirectAPIFetcher,
)
from spec.integrations.fetchers.exceptions import PlatformNotSupportedError
from spec.integrations.providers import Platform, ProviderRegistry
from spec.integrations.providers.base import GenericTicket

if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auth import AuthenticationManager
    from spec.integrations.backends.base import AIBackend


@runtime_checkable
class TicketFetcherProtocol(Protocol):
    """Protocol for ticket fetchers with string-based fetch method.

    Both AuggieMediatedFetcher and DirectAPIFetcher implement this interface.
    """

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        ...

    def supports_platform(self, platform: Platform) -> bool:
        """Check if this fetcher supports the given platform."""
        ...

    async def fetch(
        self,
        ticket_id: str,
        platform: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch raw ticket data using string platform identifier."""
        ...


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
        primary_fetcher: TicketFetcherProtocol,
        fallback_fetcher: TicketFetcherProtocol | None = None,
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
        self._primary: TicketFetcherProtocol = primary_fetcher
        self._fallback: TicketFetcherProtocol | None = fallback_fetcher
        self._cache = cache
        self._default_ttl = default_ttl
        self._closed = False

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
        platform = provider.platform

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
    ) -> dict[str, Any]:
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
                platform=platform.name,
                fetcher_name=self._primary.name,
                message=f"No fetcher supports platform {platform.name}",
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

    async def close(self) -> None:
        """Close the service and release resources.

        This should be called when done using the service to ensure
        proper cleanup of HTTP clients and other resources.
        """
        if self._closed:
            return

        self._closed = True

        # Close fallback fetcher if it has a close method (DirectAPIFetcher)
        if self._fallback and hasattr(self._fallback, "close"):
            await self._fallback.close()
            logger.debug(f"Closed fallback fetcher: {self._fallback.name}")

    async def __aenter__(self) -> TicketService:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager and close resources."""
        await self.close()


async def create_ticket_service(
    backend: AIBackend | None = None,
    auth_manager: AuthenticationManager | None = None,
    config_manager: ConfigManager | None = None,
    cache: TicketCache | None = None,
    cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    enable_fallback: bool = True,
) -> TicketService:
    """Create a TicketService with standard configuration.

    Factory function that creates a TicketService with:
    - AuggieMediatedFetcher as primary (if backend provided)
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
        backend: AIBackend instance for agent-mediated fetching.
            If None, DirectAPIFetcher becomes the only fetcher.
        auth_manager: AuthenticationManager for DirectAPIFetcher.
            Required if enable_fallback=True or backend is None.
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
        from spec.integrations.backends import AuggieBackend
        from spec.integrations.auth import get_auth_manager

        backend = AuggieBackend()
        auth_manager = await get_auth_manager()

        async with await create_ticket_service(
            backend=backend,
            auth_manager=auth_manager,
        ) as service:
            ticket = await service.get_ticket("PROJ-123")
    """
    primary: TicketFetcherProtocol | None = None
    fallback: TicketFetcherProtocol | None = None

    # Configure primary fetcher
    if backend:
        primary = AuggieMediatedFetcher(
            backend=backend,
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
            "Provide backend or auth_manager."
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
