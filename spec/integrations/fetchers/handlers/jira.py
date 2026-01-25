"""Jira REST API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .base import PlatformHandler


class JiraHandler(PlatformHandler):
    """Handler for Jira REST API v3.

    Credential keys (from AuthenticationManager):
        - url: Jira instance URL (e.g., https://company.atlassian.net)
        - email: User email for authentication
        - token: API token

    URL Handling:
        The handler normalizes the base URL by stripping trailing slashes
        to ensure consistent endpoint construction regardless of whether
        the user provides "https://company.atlassian.net" or
        "https://company.atlassian.net/".
    """

    @property
    def platform_name(self) -> str:
        return "Jira"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"url", "email", "token"})

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch issue from Jira REST API.

        API endpoint: GET /rest/api/3/issue/{issueIdOrKey}

        Args:
            ticket_id: Jira issue key (e.g., "PROJ-123")
            credentials: Must contain 'url', 'email', 'token'
            timeout_seconds: Request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Jira issue data

        Raises:
            CredentialValidationError: If required credentials are missing
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        # Normalize base URL (strip trailing slashes for consistent endpoint building)
        base_url = credentials["url"].rstrip("/")
        email = credentials["email"]
        token = credentials["token"]

        endpoint = f"{base_url}/rest/api/3/issue/{ticket_id}"
        headers = {"Accept": "application/json"}

        # Use base class helper for HTTP request execution
        response = await self._execute_request(
            method="GET",
            url=endpoint,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
            auth=httpx.BasicAuth(email, token),
        )

        result: dict[str, Any] = response.json()
        return result
