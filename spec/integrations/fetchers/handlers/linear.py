"""Linear GraphQL API handler.

Linear API Reference:
    https://developers.linear.app/docs/graphql/working-with-the-graphql-api

Authentication:
    Linear uses a simple API key authentication. The key should be passed
    in the Authorization header directly (not as "Bearer <key>").
    See: https://developers.linear.app/docs/graphql/working-with-the-graphql-api#authentication
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import PlatformNotFoundError

from .base import GraphQLPlatformHandler

# Linear GraphQL Query for fetching issues by team-scoped identifier
# Uses issueByIdentifier for team-scoped identifiers (e.g., "AMI-31")
# NOT issue(id:) which requires a UUID
#
# API Reference: https://developers.linear.app/docs/graphql/working-with-the-graphql-api
# Query Reference: https://studio.apollographql.com/public/Linear-API/home
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


class LinearHandler(GraphQLPlatformHandler):
    """Handler for Linear GraphQL API.

    Credential keys (from AuthenticationManager):
        - api_key: Linear API key (personal or OAuth token)

    Ticket ID format: Team-scoped identifier (e.g., "AMI-31", "PROJ-123")

    Authentication:
        Linear accepts the API key directly in the Authorization header,
        without the "Bearer" prefix. This is per Linear's API documentation.
        See: https://developers.linear.app/docs/graphql/working-with-the-graphql-api#authentication
    """

    API_URL = "https://api.linear.app/graphql"

    @property
    def platform_name(self) -> str:
        return "Linear"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"api_key"})

    def _extract_entity(
        self,
        data: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """Extract issue from Linear GraphQL response.

        Args:
            data: The 'data' object from GraphQL response
            ticket_id: Ticket ID for error context

        Returns:
            The issue data

        Raises:
            PlatformNotFoundError: If issue not found
        """
        issue = data.get("issueByIdentifier")
        if issue is None:
            raise PlatformNotFoundError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
            )
        # Type assertion: issue is guaranteed to be a dict at this point
        result: dict[str, Any] = issue
        return result

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
            timeout_seconds: Request timeout (per-request override for shared client)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Linear issue data

        Raises:
            CredentialValidationError: If required credentials are missing
            PlatformNotFoundError: If the issue is not found
            PlatformApiError: If GraphQL returns errors
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        api_key = credentials["api_key"]

        # Linear API Authentication:
        # Linear uses the API key directly in the Authorization header.
        # Per Linear's documentation, the format is just the key itself,
        # NOT "Bearer <key>". This differs from most OAuth2 APIs.
        # Ref: https://developers.linear.app/docs/graphql/working-with-the-graphql-api#authentication
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": ISSUE_QUERY,
            "variables": {"identifier": ticket_id},
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

        # Use base class GraphQL validation and entity extraction
        return self._validate_graphql_response(response_data, ticket_id)
