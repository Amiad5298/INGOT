"""Direct API ticket fetcher using REST/GraphQL clients.

This module provides DirectAPIFetcher for fetching ticket data directly
from platform APIs. This is the FALLBACK path when agent-mediated
fetching is unavailable.

The fetcher uses:
- AuthenticationManager (AMI-22) for credential retrieval
- FetchPerformanceConfig (AMI-33) for timeout/retry settings
- Platform-specific handlers for API implementation

Resource Management:
    DirectAPIFetcher manages a shared HTTP client for connection pooling.
    Use as an async context manager for proper cleanup:

        async with DirectAPIFetcher(auth_manager) as fetcher:
            data = await fetcher.fetch(ticket_id, platform)
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import httpx

from spec.config.fetch_config import FetchPerformanceConfig
from spec.integrations.fetchers.base import TicketFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    CredentialValidationError,
    PlatformApiError,
    PlatformNotFoundError,
    TicketIdFormatError,
)
from spec.integrations.fetchers.handlers import PlatformHandler
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auth import AuthenticationManager

logger = logging.getLogger(__name__)

# HTTP status code for rate limiting
HTTP_TOO_MANY_REQUESTS = 429


class DirectAPIFetcher(TicketFetcher):
    """Fetches tickets directly from platform APIs.

    Uses AuthenticationManager for fallback credentials when agent-mediated
    fetching fails or is unavailable. Supports all 6 platforms with
    platform-specific handlers.

    Resource Management:
        This class manages a shared HTTP client for connection pooling.
        Use as an async context manager for proper cleanup:

            async with DirectAPIFetcher(auth_manager) as fetcher:
                data = await fetcher.fetch(ticket_id, platform)

        Alternatively, call close() explicitly when done:

            fetcher = DirectAPIFetcher(auth_manager)
            try:
                data = await fetcher.fetch(ticket_id, platform)
            finally:
                await fetcher.close()

    Attributes:
        _auth: AuthenticationManager for credential retrieval
        _config: Optional ConfigManager for performance settings
        _timeout_seconds: Default request timeout
        _performance: FetchPerformanceConfig for retry settings
        _handlers: Lazily-created platform handlers (true lazy loading)
        _http_client: Shared HTTP client for connection pooling
    """

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

        # Handler instances (created lazily per-platform, not all at once)
        self._handlers: dict[Platform, PlatformHandler] = {}

        # Shared HTTP client (created lazily on first request)
        self._http_client: httpx.AsyncClient | None = None

        # Lock for thread-safe client initialization
        self._client_lock = asyncio.Lock()

        # Get performance config for defaults
        if config_manager:
            self._performance = config_manager.get_fetch_performance_config()
        else:
            self._performance = FetchPerformanceConfig()

        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else self._performance.timeout_seconds
        )

    async def __aenter__(self) -> DirectAPIFetcher:
        """Enter async context manager, ensuring HTTP client is initialized."""
        await self._get_http_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager, closing HTTP client."""
        await self.close()

    async def close(self) -> None:
        """Close the shared HTTP client.

        Call this when done using the fetcher to release resources.
        Safe to call multiple times.
        """
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client.

        Uses double-check locking pattern for thread/concurrency safety.
        Creates a new client on first call with configured timeout.
        """
        if self._http_client is None:
            async with self._client_lock:
                # Double-check locking pattern
                if self._http_client is None:
                    timeout = httpx.Timeout(self._timeout_seconds)
                    self._http_client = httpx.AsyncClient(timeout=timeout)
        return self._http_client

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Direct API Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        """Check if fallback credentials are configured for this platform.

        Uses a lightweight check to avoid expensive credential decryption.
        Full validation happens during fetch_raw when credentials are used.

        Args:
            platform: Platform enum value

        Returns:
            True if fallback credentials are configured for the platform
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
            AgentIntegrationError: If no credentials configured for platform,
                or credential/ticket format validation fails
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
            timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        )

        # Execute with retry logic
        # Keep credentials as Mapping[str, str] to respect immutability
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
        credentials: Mapping[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Execute fetch with exponential backoff retry.

        Uses FetchPerformanceConfig settings for max_retries and retry_delay.

        Retry Policy:
            - Retries on timeouts and server errors (5xx)
            - Retries on 429 Too Many Requests (respects Retry-After header)
            - Does NOT retry on other client errors (4xx except 429)
        """
        last_error: Exception | None = None
        http_client = await self._get_http_client()

        for attempt in range(self._performance.max_retries + 1):
            try:
                return await handler.fetch(
                    ticket_id,
                    credentials,
                    timeout_seconds,
                    http_client=http_client,
                )
            except (CredentialValidationError, TicketIdFormatError) as e:
                # Configuration/input errors - don't retry, map to integration error
                raise AgentIntegrationError(
                    message=str(e),
                    agent_name=self.name,
                    original_error=e,
                ) from e
            except PlatformNotFoundError as e:
                # Ticket not found - semantic "not found" error, don't retry
                raise AgentFetchError(
                    message=str(e),
                    agent_name=self.name,
                    original_error=e,
                ) from e
            except PlatformApiError as e:
                # Semantic Exception Mapping: PlatformApiError represents logical API errors
                # (e.g., GraphQL errors, validation failures). These are fetch failures,
                # not parse errors - the response was successfully parsed but indicated a
                # platform-level problem. Map to AgentFetchError for correct semantics.
                raise AgentFetchError(
                    message=f"Platform API error: {e}",
                    agent_name=self.name,
                    original_error=e,
                ) from e
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "Timeout fetching %s (attempt %d/%d): %s",
                    ticket_id,
                    attempt + 1,
                    self._performance.max_retries + 1,
                    e,
                )
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                # Handle 429 Too Many Requests - retry with Retry-After
                if status_code == HTTP_TOO_MANY_REQUESTS:
                    last_error = e
                    retry_delay = self._get_retry_after_delay(e.response, attempt)
                    logger.warning(
                        "Rate limited fetching %s (attempt %d/%d), waiting %.1fs",
                        ticket_id,
                        attempt + 1,
                        self._performance.max_retries + 1,
                        retry_delay,
                    )
                    if attempt < self._performance.max_retries:
                        await asyncio.sleep(retry_delay)
                    continue

                # Defensive Retry Logic: Explicitly exclude 429 from the 4xx non-retry check.
                # This prevents future regressions if the order of conditions changes,
                # ensuring 429 is always retried regardless of code structure.
                if 400 <= status_code < 500 and status_code != HTTP_TOO_MANY_REQUESTS:
                    raise AgentFetchError(
                        message=f"API request failed: {status_code} {e.response.text}",
                        agent_name=self.name,
                        original_error=e,
                    ) from e

                # Retry server errors (5xx)
                last_error = e
                logger.warning(
                    "HTTP error fetching %s (attempt %d/%d): %s",
                    ticket_id,
                    attempt + 1,
                    self._performance.max_retries + 1,
                    e,
                )
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Network error fetching %s (attempt %d/%d): %s",
                    ticket_id,
                    attempt + 1,
                    self._performance.max_retries + 1,
                    e,
                )

            # Calculate delay with jitter for next retry
            if attempt < self._performance.max_retries:
                delay = self._performance.retry_delay_seconds * (2**attempt)
                jitter = random.uniform(0, delay * 0.1)
                await asyncio.sleep(delay + jitter)

        # All retries exhausted
        raise AgentFetchError(
            message=f"API request failed after {self._performance.max_retries + 1} attempts",
            agent_name=self.name,
            original_error=last_error,
        )

    def _get_retry_after_delay(self, response: httpx.Response, attempt: int) -> float:
        """Extract Retry-After delay from response, or calculate default.

        Robust Retry-After Handling:
            Supports both formats specified in RFC 7231:
            - delay-seconds: Integer number of seconds (e.g., "120")
            - HTTP-date: RFC 1123 date format (e.g., "Sun, 26 Jan 2026 12:00:00 GMT")

        Args:
            response: HTTP response with 429 status
            attempt: Current attempt number (0-based)

        Returns:
            Number of seconds to wait before retrying
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            # Try parsing as integer (delay-seconds format)
            try:
                return float(retry_after)
            except ValueError:
                pass

            # Try parsing as HTTP-date (RFC 1123 format)
            try:
                retry_date = parsedate_to_datetime(retry_after)
                now = datetime.now(UTC)
                http_date_delay: float = (retry_date - now).total_seconds()
                # Ensure we don't return a negative delay if the date is in the past
                return max(0.0, http_date_delay)
            except (ValueError, TypeError) as e:
                # Log warning on parse failure but continue with default backoff
                logger.warning(
                    "Failed to parse Retry-After header '%s': %s. "
                    "Falling back to exponential backoff.",
                    retry_after,
                    e,
                )

        # Default: exponential backoff
        default_delay: float = self._performance.retry_delay_seconds * (2**attempt)
        return default_delay

    def _get_platform_handler(self, platform: Platform) -> PlatformHandler:
        """Get the handler for a specific platform.

        True lazy loading: Only instantiates the requested handler,
        not all handlers at once.
        """
        # Check if handler already exists
        if platform in self._handlers:
            return self._handlers[platform]

        # Create handler on demand (true lazy loading)
        handler = self._create_handler(platform)
        if handler is None:
            raise AgentIntegrationError(
                message=f"No handler for platform: {platform.name}",
                agent_name=self.name,
            )

        self._handlers[platform] = handler
        return handler

    def _create_handler(self, platform: Platform) -> PlatformHandler | None:
        """Create a handler instance for the given platform.

        Args:
            platform: Platform to create handler for

        Returns:
            Handler instance, or None if platform not supported
        """
        # Import handlers here to avoid circular imports and enable lazy loading
        from spec.integrations.fetchers.handlers import (
            AzureDevOpsHandler,
            GitHubHandler,
            JiraHandler,
            LinearHandler,
            MondayHandler,
            TrelloHandler,
        )

        handler_classes: dict[Platform, type[PlatformHandler]] = {
            Platform.JIRA: JiraHandler,
            Platform.LINEAR: LinearHandler,
            Platform.GITHUB: GitHubHandler,
            Platform.AZURE_DEVOPS: AzureDevOpsHandler,
            Platform.TRELLO: TrelloHandler,
            Platform.MONDAY: MondayHandler,
        }

        handler_class = handler_classes.get(platform)
        if handler_class is None:
            return None
        return handler_class()

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
        except KeyError as err:
            raise AgentIntegrationError(
                message=f"Unknown platform: {platform}",
                agent_name=self.name,
            ) from err
