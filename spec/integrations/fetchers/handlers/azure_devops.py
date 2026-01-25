"""Azure DevOps REST API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from spec.integrations.fetchers.exceptions import TicketIdFormatError

from .base import PlatformHandler


class AzureDevOpsHandler(PlatformHandler):
    """Handler for Azure DevOps REST API.

    Credential keys (from AuthenticationManager):
        - organization: Azure DevOps organization name
        - pat: Personal Access Token

    Ticket ID format: "ProjectName/WorkItemID" (e.g., "MyProject/12345")
    """

    @property
    def platform_name(self) -> str:
        return "Azure DevOps"

    @property
    def required_credential_keys(self) -> frozenset[str]:
        return frozenset({"organization", "pat"})

    def _parse_ticket_id(self, ticket_id: str) -> tuple[str, int]:
        """Parse 'Project/ID' format.

        Returns:
            Tuple of (project, work_item_id)

        Raises:
            TicketIdFormatError: If ticket ID format is invalid
        """
        parts = ticket_id.split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            raise TicketIdFormatError(
                platform_name=self.platform_name,
                ticket_id=ticket_id,
                expected_format="Project/WorkItemID",
            )
        return parts[0], int(parts[1])

    async def fetch(
        self,
        ticket_id: str,
        credentials: Mapping[str, str],
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Fetch work item from Azure DevOps REST API.

        API endpoint: GET /{organization}/{project}/_apis/wit/workitems/{id}

        Args:
            ticket_id: Azure DevOps work item in "Project/ID" format
            credentials: Must contain 'organization', 'pat'
            timeout_seconds: Request timeout (ignored if http_client provided)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Azure DevOps work item data

        Raises:
            CredentialValidationError: If required credentials are missing
            TicketIdFormatError: If ticket ID format is invalid
            httpx.HTTPError: For HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        project, work_item_id = self._parse_ticket_id(ticket_id)
        organization = credentials["organization"]
        pat = credentials["pat"]

        endpoint = (
            f"https://dev.azure.com/{organization}/{project}/"
            f"_apis/wit/workitems/{work_item_id}?api-version=7.0"
        )
        headers = {"Accept": "application/json"}

        # Use base class helper for HTTP request execution
        # Azure DevOps uses Basic auth with empty username and PAT as password
        response = await self._execute_request(
            method="GET",
            url=endpoint,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
            auth=httpx.BasicAuth("", pat),
        )

        result: dict[str, Any] = response.json()
        return result
