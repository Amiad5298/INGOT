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

Testability:
    The fetcher supports injected sleeper callable for deterministic testing.
    Pass a no-op sleeper to eliminate timing dependencies in tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import weakref
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import httpx

from spec.config.fetch_config import MAX_RETRY_DELAY_SECONDS, FetchPerformanceConfig
from spec.integrations.fetchers.base import TicketFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    CredentialValidationError,
    PlatformApiError,
    PlatformNotFoundError,
    TicketIdFormatError,
)
from spec.integrations.fetchers.handlers import PlatformHandler, create_handler
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auth import AuthenticationManager

logger = logging.getLogger(__name__)

# HTTP status code for rate limiting
HTTP_TOO_MANY_REQUESTS = 429

# Maximum length for error response body in exception messages
# Prevents PII leakage and huge HTML payloads in logs
MAX_ERROR_BODY_LENGTH = 200

# Maximum length for debug log messages (sanitization)
# Applied to all DEBUG-level logs to prevent PII leakage even in debug mode
MAX_DEBUG_LOG_LENGTH = 1000

# Type alias for async sleep functions (for dependency injection in tests)
AsyncSleeper = Callable[[float], Awaitable[None]]


def _default_jitter_generator(max_jitter: float) -> float:
    """Generate random jitter for retry delays.

    Args:
        max_jitter: Maximum jitter value

    Returns:
        Random jitter between 0 and max_jitter
    """
    return random.uniform(0, max_jitter)


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

    Testability:
        For deterministic testing, inject a custom sleeper callable and/or
        jitter generator to eliminate timing dependencies:

            async def no_sleep(seconds: float) -> None:
                pass  # No-op for tests

            fetcher = DirectAPIFetcher(
                auth_manager,
                sleeper=no_sleep,
                jitter_generator=lambda _: 0.0,  # No jitter
            )

    Attributes:
        _auth: AuthenticationManager for credential retrieval
        _config: Optional ConfigManager for performance settings
        _timeout_seconds: Default request timeout
        _performance: FetchPerformanceConfig for retry settings
        _handlers: Lazily-created platform handlers (true lazy loading)
        _http_client: Shared HTTP client for connection pooling
        _sleeper: Async sleep callable (injectable for testing)
        _jitter_generator: Jitter generator callable (injectable for testing)
        _closed: Tracks whether close() has been called
    """

    def __init__(
        self,
        auth_manager: AuthenticationManager,
        config_manager: ConfigManager | None = None,
        timeout_seconds: float | None = None,
        *,
        sleeper: AsyncSleeper | None = None,
        jitter_generator: Callable[[float], float] | None = None,
    ) -> None:
        """Initialize with AuthenticationManager.

        Args:
            auth_manager: AuthenticationManager instance (from AMI-22)
            config_manager: Optional ConfigManager for performance settings
            timeout_seconds: Optional timeout override (uses config default otherwise)
            sleeper: Optional async sleep callable for testing (defaults to asyncio.sleep)
            jitter_generator: Optional jitter generator for testing (defaults to random.uniform)
        """
        self._auth = auth_manager
        self._config = config_manager

        # Handler instances (created lazily per-platform, not all at once)
        self._handlers: dict[Platform, PlatformHandler] = {}

        # Shared HTTP client (created lazily on first request)
        self._http_client: httpx.AsyncClient | None = None

        # Lock for thread-safe client initialization
        self._client_lock = asyncio.Lock()

        # Lock for thread-safe handler creation (concurrency safety)
        # Prevents race conditions when multiple concurrent calls try to create the same handler
        self._handler_lock = asyncio.Lock()

        # Get performance config for defaults
        if config_manager:
            self._performance = config_manager.get_fetch_performance_config()
        else:
            self._performance = FetchPerformanceConfig()

        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else self._performance.timeout_seconds
        )

        # Testability: Injectable sleeper and jitter for deterministic tests
        self._sleeper: AsyncSleeper = sleeper if sleeper is not None else asyncio.sleep
        self._jitter_generator = (
            jitter_generator if jitter_generator is not None else _default_jitter_generator
        )

        # Track resource lifecycle
        self._closed = False

        # Lifecycle Safety: Register weak reference finalizer to warn about resource leaks
        # This logs a warning if the fetcher is garbage collected without being closed
        self._ensure_cleanup_warning()

    def _ensure_cleanup_warning(self) -> None:
        """Set up a weak reference finalizer to warn about unclosed clients.

        Architecture Decision: Lifecycle Safety
            Uses weakref.finalize to detect when the fetcher is garbage collected
            without close() being called. This helps identify resource leaks during
            development without breaking production code.

        Memory Leak Fix (Critical):
            The finalizer callback MUST NOT capture `self` directly, as this would
            create a strong reference that prevents garbage collection. Instead, we:
            1. Capture `id(self)` for the warning message (immutable, no reference)
            2. Use a mutable list `closed_flag` to track closure state (shared with close())

            When close() is called, it sets closed_flag[0] = True. The finalizer
            callback checks this flag without referencing the instance, allowing
            proper garbage collection while still detecting leaks.
        """
        # Capture instance ID for the warning message (does not hold reference to self)
        instance_id = id(self)

        # Mutable flag to track closure state without referencing self
        # This list is shared between close() and the finalizer callback
        # Using a list allows mutation from within the closure
        closed_flag: list[bool] = [False]

        # Store reference to closed_flag so close() can update it
        self._closed_flag = closed_flag

        def _warn_on_gc() -> None:
            """Callback invoked when the object is garbage collected.

            This callback does NOT reference self, avoiding the reference cycle.
            It only reads the mutable closed_flag to determine if close() was called.
            """
            if not closed_flag[0]:
                logger.warning(
                    "DirectAPIFetcher (id=%s) was garbage collected without close() being called. "
                    "This may indicate a resource leak. Use 'async with' context manager "
                    "or call close() explicitly.",
                    instance_id,
                )

        # weakref.finalize registers _warn_on_gc to be called when self is about to be
        # garbage collected. Since _warn_on_gc doesn't capture self, the finalizer
        # won't prevent garbage collection.
        weakref.finalize(self, _warn_on_gc)

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

        Also updates the mutable closed_flag used by the weakref finalizer
        to prevent the "garbage collected without close()" warning.
        """
        self._closed = True
        # Update the mutable flag for the weakref finalizer
        # This prevents the warning when the object is garbage collected after close()
        if hasattr(self, "_closed_flag"):
            self._closed_flag[0] = True
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

        # Get platform-specific handler (async for concurrency-safe lazy loading)
        handler = await self._get_platform_handler(platform)

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

        Backoff Cap:
            Exponential backoff is capped at MAX_RETRY_DELAY_SECONDS (from config)
            to prevent excessively long waits.

        Testability:
            Uses injected sleeper and jitter_generator for deterministic testing.

        Security:
            Truncates error response bodies to prevent PII leakage in logs,
            including DEBUG-level logs.

        Exception Hierarchy Compliance:
            All internal Platform* exceptions are mapped to Agent* exceptions
            to comply with TicketFetcher contract:
            - json.JSONDecodeError -> AgentResponseParseError
            - PlatformApiError -> AgentFetchError
            - PlatformNotFoundError -> AgentFetchError
        """
        last_error: Exception | None = None
        http_client = await self._get_http_client()
        platform = handler.platform_name

        # Contextual logging: Include platform and ticket_id in all log messages
        log_context = {"platform": platform, "ticket_id": ticket_id}

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
                # Exception Hierarchy Compliance: PlatformNotFoundError is a semantic
                # "not found" error. Map to AgentFetchError (not AgentResponseParseError)
                # because the response was valid, the ticket just doesn't exist.
                raise AgentFetchError(
                    message=f"Ticket not found: {e}",
                    agent_name=self.name,
                    original_error=e,
                ) from e
            except PlatformApiError as e:
                # Exception Hierarchy Compliance: PlatformApiError represents logical
                # API errors (e.g., GraphQL errors, validation failures). These are
                # fetch failures - the response was parsed but indicated a platform-level
                # problem. Map to AgentFetchError to prevent Platform* leakage to caller.
                raise AgentFetchError(
                    message=f"Platform API error: {e}",
                    agent_name=self.name,
                    original_error=e,
                ) from e
            except json.JSONDecodeError as e:
                # Exception Hierarchy Compliance: JSONDecodeError indicates the API
                # returned invalid JSON. Map to AgentResponseParseError as specified
                # in the TicketFetcher contract.
                raise AgentResponseParseError(
                    message="Failed to parse API response",
                    agent_name=self.name,
                    raw_response=getattr(e, "doc", None),
                    original_error=e,
                ) from e
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "Timeout fetching ticket (attempt %d/%d): %s",
                    attempt + 1,
                    self._performance.max_retries + 1,
                    e,
                    extra=log_context,
                )
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                # Handle 429 Too Many Requests - retry with Retry-After
                if status_code == HTTP_TOO_MANY_REQUESTS:
                    last_error = e
                    retry_delay = self._get_retry_after_delay(e.response, attempt)
                    logger.warning(
                        "Rate limited (attempt %d/%d), waiting %.1fs",
                        attempt + 1,
                        self._performance.max_retries + 1,
                        retry_delay,
                        extra=log_context,
                    )
                    if attempt < self._performance.max_retries:
                        await self._sleeper(retry_delay)
                    continue

                # Defensive Retry Logic: Explicitly exclude 429 from the 4xx non-retry check.
                # This prevents future regressions if the order of conditions changes,
                # ensuring 429 is always retried regardless of code structure.
                if 400 <= status_code < 500 and status_code != HTTP_TOO_MANY_REQUESTS:
                    # Security: Truncate error body to prevent PII leakage
                    error_body = e.response.text
                    truncated_body = self._truncate_error_body(error_body)

                    # Security Fix: Sanitize DEBUG logs as well to prevent PII leakage
                    # even in debug mode. Use MAX_DEBUG_LOG_LENGTH for debug truncation.
                    sanitized_debug_body = self._sanitize_debug_log(error_body)
                    logger.debug(
                        "API error response for %s/%s: %s",
                        platform,
                        ticket_id,
                        sanitized_debug_body,
                    )

                    raise AgentFetchError(
                        message=f"API request failed: {status_code} {truncated_body}",
                        agent_name=self.name,
                        original_error=e,
                    ) from e

                # Retry server errors (5xx)
                last_error = e
                logger.warning(
                    "HTTP error (attempt %d/%d): status=%d",
                    attempt + 1,
                    self._performance.max_retries + 1,
                    status_code,
                    extra=log_context,
                )
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Network error (attempt %d/%d): %s",
                    attempt + 1,
                    self._performance.max_retries + 1,
                    e,
                    extra=log_context,
                )

            # Calculate delay with jitter for next retry
            # Uses injected sleeper and jitter_generator for testability
            if attempt < self._performance.max_retries:
                # Backoff Cap Fix: Clamp calculated delay to MAX_RETRY_DELAY_SECONDS
                # to prevent excessively long waits with exponential backoff
                calculated_delay = self._performance.retry_delay_seconds * (2**attempt)
                capped_delay = min(calculated_delay, MAX_RETRY_DELAY_SECONDS)
                jitter = self._jitter_generator(capped_delay * 0.1)
                await self._sleeper(capped_delay + jitter)

        # All retries exhausted
        raise AgentFetchError(
            message=f"API request failed after {self._performance.max_retries + 1} attempts",
            agent_name=self.name,
            original_error=last_error,
        )

    def _truncate_error_body(self, body: str) -> str:
        """Truncate error response body to prevent PII leakage.

        Security Decision: Log Sanitization
            Error response bodies may contain sensitive information (PII, auth tokens,
            large HTML pages). Truncating to a reasonable length prevents:
            1. PII leakage in standard logs
            2. Log bloat from huge HTML error pages
            3. Potential security issues from exposing internal details

        Args:
            body: Raw error response body

        Returns:
            Truncated body (max MAX_ERROR_BODY_LENGTH chars) with indicator if truncated
        """
        if len(body) <= MAX_ERROR_BODY_LENGTH:
            return body
        return body[:MAX_ERROR_BODY_LENGTH] + "... [truncated]"

    def _sanitize_debug_log(self, content: str) -> str:
        """Sanitize content for DEBUG-level logging.

        Security Fix: Debug Log Sanitization
            Even DEBUG logs should not contain unbounded PII/tokens. This method
            applies truncation (MAX_DEBUG_LOG_LENGTH chars) to prevent:
            1. PII leakage even when debugging is enabled
            2. Accidental exposure of API tokens in log files
            3. Log file bloat from large error responses

            Note: MAX_DEBUG_LOG_LENGTH (1000) is larger than MAX_ERROR_BODY_LENGTH (200)
            to allow more context for debugging while still providing protection.

        Args:
            content: Raw content to sanitize

        Returns:
            Sanitized content (max MAX_DEBUG_LOG_LENGTH chars) with indicator if truncated
        """
        if len(content) <= MAX_DEBUG_LOG_LENGTH:
            return content
        return content[:MAX_DEBUG_LOG_LENGTH] + "... [truncated for security]"

    def _get_retry_after_delay(self, response: httpx.Response, attempt: int) -> float:
        """Extract Retry-After delay from response, or calculate default.

        Robust Retry-After Handling:
            Supports both formats specified in RFC 7231:
            - delay-seconds: Integer number of seconds (e.g., "120")
            - HTTP-date: RFC 1123 date format (e.g., "Sun, 26 Jan 2026 12:00:00 GMT")

        Backoff Cap:
            All delays (including Retry-After) are capped at MAX_RETRY_DELAY_SECONDS
            to prevent excessively long waits from malicious or misconfigured servers.

        Args:
            response: HTTP response with 429 status
            attempt: Current attempt number (0-based)

        Returns:
            Number of seconds to wait before retrying (capped at MAX_RETRY_DELAY_SECONDS)
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            # Try parsing as integer (delay-seconds format)
            try:
                parsed_delay = float(retry_after)
                # Cap the Retry-After delay to prevent excessively long waits
                return min(parsed_delay, MAX_RETRY_DELAY_SECONDS)
            except ValueError:
                pass

            # Try parsing as HTTP-date (RFC 1123 format)
            try:
                retry_date = parsedate_to_datetime(retry_after)
                now = datetime.now(UTC)
                http_date_delay: float = (retry_date - now).total_seconds()
                # Ensure we don't return a negative delay if the date is in the past
                # Cap the delay to prevent excessively long waits
                return min(max(0.0, http_date_delay), MAX_RETRY_DELAY_SECONDS)
            except (ValueError, TypeError) as e:
                # Log warning on parse failure but continue with default backoff
                logger.warning(
                    "Failed to parse Retry-After header '%s': %s. "
                    "Falling back to exponential backoff.",
                    retry_after,
                    e,
                )

        # Default: exponential backoff (also capped)
        default_delay: float = self._performance.retry_delay_seconds * (2**attempt)
        return min(default_delay, MAX_RETRY_DELAY_SECONDS)

    async def _get_platform_handler(self, platform: Platform) -> PlatformHandler:
        """Get the handler for a specific platform.

        True lazy loading: Only instantiates the requested handler,
        not all handlers at once.

        Concurrency Safety Fix:
            Uses an asyncio.Lock to prevent race conditions when multiple
            concurrent calls try to create the same handler. Without the lock,
            concurrent calls could:
            1. Both check if handler exists (both see it doesn't)
            2. Both create new handler instances
            3. One overwrites the other's handler

            The double-check locking pattern ensures thread-safe lazy initialization
            while minimizing lock contention for the common case (handler exists).
        """
        # Fast path: Check if handler already exists (no lock needed)
        if platform in self._handlers:
            return self._handlers[platform]

        # Slow path: Acquire lock for thread-safe handler creation
        async with self._handler_lock:
            # Double-check locking pattern: Check again inside the lock
            # Another coroutine may have created the handler while we waited
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

        Architecture Decision: Handler Registry Pattern
            Uses the centralized handler registry from handlers/__init__.py
            instead of inline imports. This improves:
            1. Static analysis support (linters can trace imports)
            2. Code maintainability (single source of truth)
            3. Testability (registry can be mocked)

        Args:
            platform: Platform to create handler for

        Returns:
            Handler instance, or None if platform not supported
        """
        # Use the centralized handler registry
        return create_handler(platform)

    def _resolve_platform(self, platform: str) -> Platform:
        """Resolve a platform string to Platform enum.

        Robust Input Normalization:
            Handles common input variations by normalizing the string before lookup:
            - Case-insensitive: "jira" -> "JIRA"
            - Strips whitespace: " jira " -> "JIRA"
            - Normalizes separators: "azure-devops" -> "AZURE_DEVOPS"
            - Handles spaces: "jira cloud" -> "JIRA_CLOUD"

        Args:
            platform: Platform name as string (case-insensitive, flexible format)

        Returns:
            Platform enum value

        Raises:
            AgentIntegrationError: If platform string is invalid
        """
        # Normalize: uppercase, strip whitespace, replace hyphens and spaces with underscores
        normalized = platform.strip().upper().replace("-", "_").replace(" ", "_")

        try:
            return Platform[normalized]
        except KeyError as err:
            raise AgentIntegrationError(
                message=f"Unknown platform: {platform}",
                agent_name=self.name,
            ) from err
