"""Monday.com GraphQL API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import PlatformApiError, PlatformNotFoundError

from .base import PlatformHandler

ITEM_QUERY = """
query GetItem($itemId: ID!) {
  items(ids: [$itemId]) {
    id
    name
    state
    column_values {
      id
      title
      text
    }
    created_at
    updated_at
    board { id name }
    group { id title }
  }
}
"""


class MondayHandler(PlatformHandler):
    """Handler for Monday.com GraphQL API.

    Credential keys (from AuthenticationManager):
        - api_key: Monday API key

    Ticket ID: Monday item ID (numeric)
    """

    API_URL = "https://api.monday.com/v2"

    @property
    def platform_name(self) -> str:
        return "Monday"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch item from Monday GraphQL API.

        Args:
            ticket_id: Monday item ID (numeric string)
            credentials: Must contain 'api_key'
            timeout_seconds: Request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Monday item data

        Raises:
            CredentialValidationError: If required credentials are missing
            PlatformApiError: If GraphQL returns errors or item not found
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": ITEM_QUERY,
            "variables": {"itemId": ticket_id},
        }

        # Use base class helper for HTTP request execution
        response = await self._execute_request(
            method="POST",
            url=self.API_URL,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
            json_data=payload,
        )

        data: dict[str, Any] = response.json()

        # Check for GraphQL errors
        if "errors" in data:
            raise PlatformApiError(
                platform_name=self.platform_name,
                error_details=f"GraphQL errors: {data['errors']}",
                ticket_id=ticket_id,
            )

        items = data.get("data", {}).get("items", [])
        if not items:
            raise PlatformNotFoundError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
            )

        result: dict[str, Any] = items[0]
        return result
