"""Monday.com GraphQL API handler.

Monday.com API Reference:
    https://developer.monday.com/api-reference/reference/items

API Version:
    Uses Monday.com API v2 (2023-10 stable release).
    The API is GraphQL-based with a stable schema.

Authentication:
    Monday uses API key authentication. The key should be passed
    in the Authorization header directly (not as "Bearer <key>").
    See: https://developer.monday.com/api-reference/reference/authentication

Field Stability Notes:
    The fields used in ITEM_QUERY are standard Monday.com item fields
    that are part of the stable API. These are unlikely to change between
    API versions:
    - id, name, state: Core item properties
    - column_values: Standard way to access custom columns
    - created_at, updated_at: Timestamp fields
    - board, group: Relationship fields
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import PlatformApiError, PlatformNotFoundError

from .base import PlatformHandler

# Monday.com GraphQL Query for fetching items by ID
# API Reference: https://developer.monday.com/api-reference/reference/items
#
# Field Stability Notes (2024-01 API version):
# - id, name: Core item identifiers (stable)
# - state: Item state (active/archived/deleted) - stable field
# - column_values: Access to custom columns via flexible schema (stable pattern)
# - created_at, updated_at: Standard timestamps (stable)
# - board: Parent board reference (stable relationship)
# - group: Parent group reference (stable relationship)
#
# Note: 'state' returns "active", "archived", or "deleted" per API docs
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

    Ticket ID: Monday item ID (numeric string)

    Authentication:
        Monday accepts the API key directly in the Authorization header,
        without the "Bearer" prefix. This is per Monday's API documentation.
        See: https://developer.monday.com/api-reference/reference/authentication
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
        """Fetch item from Monday.com GraphQL API.

        Args:
            ticket_id: Monday item ID (numeric string)
            credentials: Must contain 'api_key'
            timeout_seconds: Request timeout (per-request override for shared client)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Monday item data

        Raises:
            CredentialValidationError: If required credentials are missing
            PlatformNotFoundError: If the item is not found
            PlatformApiError: If GraphQL returns errors
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]

        # Monday API Authentication:
        # Monday uses the API key directly in the Authorization header.
        # Per Monday's documentation, the format is just the key itself.
        # Ref: https://developer.monday.com/api-reference/reference/authentication
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": ITEM_QUERY,
            "variables": {"itemId": ticket_id},
        }

        # Use base class helper for HTTP request execution
        # ticket_id passed for harmonized 404 context in error messages
        response = await self._execute_request(
            method="POST",
            url=self.API_URL,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
            json_data=payload,
            ticket_id=ticket_id,
        )

        response_data: dict[str, Any] = response.json()

        # GraphQL Safety: Check for GraphQL-level errors
        if "errors" in response_data:
            raise PlatformApiError(
                platform_name=self.platform_name,
                error_details=f"GraphQL errors: {response_data['errors']}",
                ticket_id=ticket_id,
            )

        # GraphQL Safety: Check for None data before accessing nested keys
        # This prevents TypeError if the API returns {"data": null}
        data = response_data.get("data")
        if data is None:
            raise PlatformApiError(
                platform_name=self.platform_name,
                error_details="GraphQL response contains null data",
                ticket_id=ticket_id,
            )

        items = data.get("items")
        if items is None or len(items) == 0:
            raise PlatformNotFoundError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
            )

        result: dict[str, Any] = items[0]
        return result
