"""Linear GraphQL API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import PlatformApiError, PlatformNotFoundError

from .base import PlatformHandler

# Use issueByIdentifier for team-scoped identifiers (e.g., "AMI-31")
# NOT issue(id:) which requires a UUID
ISSUE_QUERY = """
query GetIssue($identifier: String!) {
  issueByIdentifier(identifier: $identifier) {
    id
    identifier
    title
    description
    state { name }
    assignee { name email }
    labels { nodes { name } }
    createdAt
    updatedAt
    priority
    team { key name }
    url
  }
}
"""


class LinearHandler(PlatformHandler):
    """Handler for Linear GraphQL API.

    Credential keys (from AuthenticationManager):
        - api_key: Linear API key

    Ticket ID format: Team-scoped identifier (e.g., "AMI-31", "PROJ-123")
    """

    API_URL = "https://api.linear.app/graphql"

    @property
    def platform_name(self) -> str:
        return "Linear"

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
        """Fetch issue from Linear GraphQL API.

        Uses issueByIdentifier query for team-scoped identifiers.

        Args:
            ticket_id: Linear issue identifier (e.g., "AMI-31")
            credentials: Must contain 'api_key'
            timeout_seconds: Request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Linear issue data

        Raises:
            CredentialValidationError: If required credentials are missing
            PlatformApiError: If GraphQL returns errors or issue not found
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
            "query": ISSUE_QUERY,
            "variables": {"identifier": ticket_id},
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

        issue = data.get("data", {}).get("issueByIdentifier")
        if issue is None:
            raise PlatformNotFoundError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
            )

        result: dict[str, Any] = issue
        return result
