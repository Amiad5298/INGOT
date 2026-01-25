"""Base class for platform-specific API handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Literal

import httpx

from spec.integrations.fetchers.exceptions import CredentialValidationError


class PlatformHandler(ABC):
    """Base class for platform-specific API handlers.

    Each handler encapsulates the API-specific logic for fetching
    ticket data from a particular platform.

    HTTP Client Sharing:
        Handlers receive a shared HTTP client from DirectAPIFetcher via
        the fetch() method. This enables connection pooling and proper
        resource management.

        For testing, handlers can still work without an injected client
        by falling back to creating a new client per request.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name."""
        pass

    @property
    @abstractmethod
    def required_credential_keys(self) -> frozenset[str]:
        """Set of required credential keys for this platform.

        Returns:
            Frozenset of credential key names that must be present
        """
        pass

    @abstractmethod
    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch ticket data from platform API.

        Args:
            ticket_id: The ticket identifier
            credentials: Immutable credential mapping from AuthenticationManager
            timeout_seconds: Optional request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw API response as dictionary

        Raises:
            CredentialValidationError: If required credential keys are missing
            TicketIdFormatError: If ticket ID format is invalid
            PlatformApiError: If platform API returns a logical error
            httpx.HTTPError: For HTTP-level failures
            httpx.TimeoutException: For timeout failures
        """
        pass

    def _validate_credentials(self, credentials: Mapping[str, str]) -> None:
        """Validate that all required credential keys are present.

        Args:
            credentials: Credential mapping to validate

        Raises:
            CredentialValidationError: If any required keys are missing
        """
        missing = self.required_credential_keys - set(credentials.keys())
        if missing:
            raise CredentialValidationError(
                platform_name=self.platform_name,
                missing_keys=missing,
            )

    async def _execute_request(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.Response:
        """Execute HTTP request using shared client or create new one.

        This method centralizes the "use injected client vs create new one"
        logic to avoid duplication across all handlers.

        Args:
            method: HTTP method ("GET" or "POST")
            url: Request URL
            http_client: Optional shared HTTP client
            timeout_seconds: Timeout for new client (ignored if http_client provided)
            headers: Optional request headers
            params: Optional query parameters
            json_data: Optional JSON body (for POST requests)
            auth: Optional authentication (e.g., httpx.BasicAuth)

        Returns:
            HTTP response object

        Raises:
            httpx.HTTPError: For HTTP-level failures
            httpx.TimeoutException: For timeout failures
        """
        # Build kwargs dynamically - only include non-None values
        kwargs: dict[str, Any] = {}
        if headers is not None:
            kwargs["headers"] = headers
        if params is not None:
            kwargs["params"] = params
        if auth is not None:
            kwargs["auth"] = auth

        if http_client is not None:
            # Use the shared client from DirectAPIFetcher
            if method == "GET":
                response = await http_client.get(url, **kwargs)
            else:  # POST
                response = await http_client.post(url, json=json_data, **kwargs)
            response.raise_for_status()
            return response
        else:
            # Fallback: create a new client for this request
            timeout = httpx.Timeout(timeout_seconds or 30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "GET":
                    response = await client.get(url, **kwargs)
                else:  # POST
                    response = await client.post(url, json=json_data, **kwargs)
                response.raise_for_status()
                return response
