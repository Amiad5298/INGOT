"""Trello REST API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .base import PlatformHandler


class TrelloHandler(PlatformHandler):
    """Handler for Trello REST API.

    Credential keys (from AuthenticationManager):
        - api_key: Trello API key
        - token: Trello token

    Ticket ID: Trello card ID or shortLink
    """

    API_URL = "https://api.trello.com/1"

    @property
    def platform_name(self) -> str:
        return "Trello"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key", "token"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch card from Trello REST API.

        API endpoint: GET /1/cards/{id}

        Args:
            ticket_id: Trello card ID or shortLink
            credentials: Must contain 'api_key', 'token'
            timeout_seconds: Request timeout (per-request override for shared client)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Trello card data

        Raises:
            CredentialValidationError: If required credentials are missing
            PlatformNotFoundError: If card is not found (404)
            httpx.HTTPError: For other HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]
        token = credentials["token"]

        endpoint = f"{self.API_URL}/cards/{ticket_id}"
        params = {"key": api_key, "token": token}

        # Use base class helper for HTTP request execution
        # ticket_id passed for harmonized 404 handling across REST/GraphQL
        response = await self._execute_request(
            method="GET",
            url=endpoint,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            params=params,
            ticket_id=ticket_id,
        )

        result: dict[str, Any] = response.json()
        return result
