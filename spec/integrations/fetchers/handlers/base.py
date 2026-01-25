"""Base class for platform-specific API handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Literal

import httpx

from spec.integrations.fetchers.exceptions import (
    CredentialValidationError,
    PlatformApiError,
    PlatformNotFoundError,
)

# HTTP status code for Not Found
HTTP_NOT_FOUND = 404


class PlatformHandler(ABC):
    """Base class for platform-specific API handlers.

    Each handler encapsulates the API-specific logic for fetching
    ticket data from a particular platform.

    HTTP Client Sharing:
        Handlers receive a shared HTTP client from DirectAPIFetcher via
        the fetch() method. This enables connection pooling and proper
        resource management.

        Per-Request Timeout Override:
            When a shared client is provided, the timeout_seconds parameter
            is passed as a per-request override via httpx's timeout parameter.
            This allows different operations to have different timeout requirements
            even when using connection pooling.

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
            timeout_seconds: Request timeout (applied per-request even with shared client)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw API response as dictionary

        Raises:
            CredentialValidationError: If required credential keys are missing
            TicketIdFormatError: If ticket ID format is invalid
            PlatformNotFoundError: If the ticket is not found (404)
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
        ticket_id: str | None = None,
    ) -> httpx.Response:
        """Execute HTTP request using shared client or create new one.

        This method centralizes the "use injected client vs create new one"
        logic to avoid duplication across all handlers.

        Architecture Decision: Per-Request Timeout Override
            Even when using a shared HTTP client, the timeout_seconds parameter
            is applied as a per-request override. This ensures that different
            API calls can have different timeout requirements while still
            benefiting from connection pooling.

        Args:
            method: HTTP method ("GET" or "POST")
            url: Request URL
            http_client: Optional shared HTTP client
            timeout_seconds: Per-request timeout (applied even with shared client)
            headers: Optional request headers
            params: Optional query parameters
            json_data: Optional JSON body (for POST requests)
            auth: Optional authentication (e.g., httpx.BasicAuth)
            ticket_id: Optional ticket ID for error context (used in 404 handling)

        Returns:
            HTTP response object

        Raises:
            PlatformNotFoundError: If HTTP 404 is returned
            httpx.HTTPError: For other HTTP-level failures
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
            # Architecture Fix: Apply per-request timeout override to shared client.
            # This allows different operations to have different timeout requirements
            # while still benefiting from connection pooling.
            if timeout_seconds is not None:
                kwargs["timeout"] = httpx.Timeout(timeout_seconds)

            # Use the shared client from DirectAPIFetcher
            if method == "GET":
                response = await http_client.get(url, **kwargs)
            else:  # POST
                response = await http_client.post(url, json=json_data, **kwargs)

            # Harmonized 404 handling: Convert HTTP 404 to semantic PlatformNotFoundError
            # This ensures consistent "Not Found" handling across REST and GraphQL handlers
            self._check_not_found(response, ticket_id)
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

                # Harmonized 404 handling for fallback client as well
                self._check_not_found(response, ticket_id)
                response.raise_for_status()
                return response

    def _check_not_found(self, response: httpx.Response, ticket_id: str | None) -> None:
        """Check for 404 response and raise PlatformNotFoundError.

        Architecture Decision: Harmonized 404 Handling
            GraphQL handlers raise PlatformNotFoundError for missing resources.
            This method provides the same behavior for REST handlers, ensuring
            consistent "Not Found" semantics across the entire system.

        Args:
            response: HTTP response to check
            ticket_id: Ticket ID for error context (if available)

        Raises:
            PlatformNotFoundError: If response status is 404
        """
        if response.status_code == HTTP_NOT_FOUND:
            raise PlatformNotFoundError(
                platform_name=self.platform_name,
                ticket_id=ticket_id or "unknown",
            )


class GraphQLPlatformHandler(PlatformHandler):
    """Base class for platform handlers using GraphQL APIs.

    This class provides common functionality for GraphQL-based platforms:
    - GraphQL error checking (errors array in response)
    - Null data checking
    - Common request execution pattern

    Subclasses must implement:
    - platform_name: Human-readable platform name
    - required_credential_keys: Set of required credential keys
    - fetch(): Main fetch method (can use helper methods from this class)
    - _extract_entity(): Extract the entity from GraphQL data response
    """

    @abstractmethod
    def _extract_entity(
        self,
        data: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """Extract the entity from GraphQL data response.

        Subclasses implement this to extract the platform-specific entity
        from the GraphQL data object (e.g., issueByIdentifier for Linear,
        items[0] for Monday).

        Args:
            data: The 'data' object from GraphQL response (guaranteed non-null)
            ticket_id: Ticket ID for error context

        Returns:
            The extracted entity data

        Raises:
            PlatformNotFoundError: If the entity is not found in the data
        """
        pass

    def _check_graphql_errors(
        self,
        response_data: dict[str, Any],
        ticket_id: str,
    ) -> None:
        """Check for GraphQL-level errors in the response.

        Args:
            response_data: Full GraphQL response
            ticket_id: Ticket ID for error context

        Raises:
            PlatformApiError: If GraphQL errors are present
        """
        if "errors" in response_data:
            raise PlatformApiError(
                platform_name=self.platform_name,
                error_details=f"GraphQL errors: {response_data['errors']}",
                ticket_id=ticket_id,
            )

    def _check_null_data(
        self,
        response_data: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """Check for null data in GraphQL response and return data if valid.

        Args:
            response_data: Full GraphQL response
            ticket_id: Ticket ID for error context

        Returns:
            The 'data' object from the response

        Raises:
            PlatformApiError: If data is null or missing
        """
        data = response_data.get("data")
        if data is None:
            raise PlatformApiError(
                platform_name=self.platform_name,
                error_details="GraphQL response contains null data",
                ticket_id=ticket_id,
            )
        # Type assertion: data is guaranteed to be a dict at this point
        result: dict[str, Any] = data
        return result

    def _validate_graphql_response(
        self,
        response_data: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """Validate GraphQL response and extract entity.

        Performs all GraphQL safety checks and extracts the entity:
        1. Checks for GraphQL errors
        2. Checks for null data
        3. Extracts entity using subclass implementation

        Args:
            response_data: Full GraphQL response
            ticket_id: Ticket ID for error context

        Returns:
            The extracted entity data

        Raises:
            PlatformApiError: If GraphQL errors or null data
            PlatformNotFoundError: If entity not found
        """
        self._check_graphql_errors(response_data, ticket_id)
        data = self._check_null_data(response_data, ticket_id)
        return self._extract_entity(data, ticket_id)
