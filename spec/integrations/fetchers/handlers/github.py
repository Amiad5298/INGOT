"""GitHub REST API handler."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import TicketIdFormatError

from .base import PlatformHandler


class GitHubHandler(PlatformHandler):
    """Handler for GitHub REST API v3.

    Credential keys (from AuthenticationManager):
        - token: GitHub personal access token

    Ticket ID format: "owner/repo#number" (e.g., "microsoft/vscode#12345")
    """

    API_URL = "https://api.github.com"

    @property
    def platform_name(self) -> str:
        return "GitHub"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"token"})

    def _parse_ticket_id(self, ticket_id: str) -> tuple[str, str, int]:
        """Parse 'owner/repo#number' format.

        Returns:
            Tuple of (owner, repo, issue_number)

        Raises:
            TicketIdFormatError: If ticket ID format is invalid
        """
        match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", ticket_id)
        if not match:
            raise TicketIdFormatError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
                expected_format="owner/repo#number",
            )
        return match.group(1), match.group(2), int(match.group(3))

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch issue/PR from GitHub REST API.

        API endpoint: GET /repos/{owner}/{repo}/issues/{issue_number}

        Args:
            ticket_id: GitHub issue ID in "owner/repo#number" format
            credentials: Must contain 'token'
            timeout_seconds: Request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw GitHub issue data

        Raises:
            CredentialValidationError: If required credentials are missing
            TicketIdFormatError: If ticket ID format is invalid
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        owner, repo, number = self._parse_ticket_id(ticket_id)
        token = credentials["token"]

        endpoint = f"{self.API_URL}/repos/{owner}/{repo}/issues/{number}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Use base class helper for HTTP request execution
        response = await self._execute_request(
            method="GET",
            url=endpoint,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )

        result: dict[str, Any] = response.json()
        return result
