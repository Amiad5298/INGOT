"""Azure DevOps REST API handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ingot.integrations.fetchers.exceptions import TicketIdFormatError

from .base import PlatformHandler


class AzureDevOpsHandler(PlatformHandler):
    """Handler for Azure DevOps REST API.

    Credential keys (from AuthenticationManager):
        - organization: Azure DevOps organization name
        - pat: Personal Access Token

    Ticket ID format: "ProjectName/WorkItemID" (e.g., "MyProject/12345")

    API Version:
        Uses Azure DevOps REST API version 7.0 via query parameter.
    """

    # Azure DevOps API version - configured as constant for easy updates
    API_VERSION = "7.0"

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
            timeout_seconds: Request timeout (per-request override for shared client)
            http_client: Shared HTTP client from DirectAPIFetcher

        Returns:
            Raw Azure DevOps work item data

        Raises:
            CredentialValidationError: If required credentials are missing
            TicketIdFormatError: If ticket ID format is invalid
            PlatformNotFoundError: If work item is not found (404)
            httpx.HTTPError: For other HTTP-level failures
        """
        # Validate required credentials are present
        self._validate_credentials(credentials)

        project, work_item_id = self._parse_ticket_id(ticket_id)
        organization = credentials["organization"]
        pat = credentials["pat"]

        # Architecture: api-version moved to params dict for cleaner URL construction
        # and easier version management
        endpoint = (
            f"https://dev.azure.com/{organization}/{project}/_apis/wit/workitems/{work_item_id}"
        )
        headers = {"Accept": "application/json"}
        params = {"api-version": self.API_VERSION}

        # Use base class helper for HTTP request execution
        # Azure DevOps uses Basic auth with empty username and PAT as password
        # ticket_id passed for harmonized 404 handling
        response = await self._execute_request(
            method="GET",
            url=endpoint,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            headers=headers,
            params=params,
            auth=httpx.BasicAuth("", pat),
            ticket_id=ticket_id,
        )

        result: dict[str, Any] = response.json()
        return result
