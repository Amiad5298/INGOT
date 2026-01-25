"""Live integration tests for DirectAPIFetcher.

These tests require real API credentials and make actual HTTP requests.
Run with: pytest tests/integration/test_direct_fetcher_live.py -v --live

Required environment variables per platform - see test docstrings.

Environment setup:
    # Jira (Auggie-supported platform)
    export FALLBACK_JIRA_URL="https://your-domain.atlassian.net"
    export FALLBACK_JIRA_EMAIL="your-email@example.com"
    export FALLBACK_JIRA_TOKEN="your-api-token"

    # GitHub (Auggie-supported platform)
    export FALLBACK_GITHUB_TOKEN="ghp_your_token_here"

    # Azure DevOps (non-Auggie platform)
    export FALLBACK_AZURE_DEVOPS_ORGANIZATION="your-org"
    export FALLBACK_AZURE_DEVOPS_PAT="your-personal-access-token"

    # Trello (alternative non-Auggie platform)
    export FALLBACK_TRELLO_API_KEY="your-api-key"
    export FALLBACK_TRELLO_TOKEN="your-oauth-token"
"""

from __future__ import annotations

import os

import pytest

from spec.config import ConfigManager
from spec.integrations.auth import AuthenticationManager
from spec.integrations.fetchers import DirectAPIFetcher
from spec.integrations.fetchers.exceptions import AgentIntegrationError
from spec.integrations.providers.base import Platform

from .conftest import (
    has_azure_devops_credentials,
    has_github_credentials,
    has_jira_credentials,
    has_trello_credentials,
)


@pytest.fixture
def fetcher():
    """Create DirectAPIFetcher with real credentials from environment.

    The ConfigManager reads credentials from environment variables
    prefixed with FALLBACK_ (e.g., FALLBACK_JIRA_URL).
    """
    config = ConfigManager()
    config.load()
    auth = AuthenticationManager(config)
    return DirectAPIFetcher(auth, config)


class TestJiraIntegration:
    """Jira live integration tests.

    Requires environment variables:
        - FALLBACK_JIRA_URL: Base URL (e.g., https://company.atlassian.net)
        - FALLBACK_JIRA_EMAIL: Account email
        - FALLBACK_JIRA_TOKEN: API token from Atlassian account settings
    """

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_jira_credentials(),
        reason="Jira credentials not configured (need FALLBACK_JIRA_URL)",
    )
    async def test_fetch_jira_issue(self, fetcher):
        """Fetch a real Jira issue and verify response structure."""
        # Use the test issue ID from environment or default
        issue_key = os.getenv("TEST_JIRA_ISSUE", "TEST-1")

        result = await fetcher.fetch(issue_key, "jira")

        # Verify Jira response structure
        assert "key" in result, "Response should contain 'key'"
        assert "fields" in result, "Response should contain 'fields'"
        assert result["key"] == issue_key

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_jira_credentials(),
        reason="Jira credentials not configured",
    )
    async def test_jira_fetch_returns_required_fields(self, fetcher):
        """Verify Jira response includes fields needed for GenericTicket."""
        issue_key = os.getenv("TEST_JIRA_ISSUE", "TEST-1")

        result = await fetcher.fetch(issue_key, "jira")

        fields = result.get("fields", {})
        # These fields are required for normalization to GenericTicket
        assert "summary" in fields, "Response should contain summary"
        # Status is typically nested: fields.status.name
        assert "status" in fields, "Response should contain status"


class TestGitHubIntegration:
    """GitHub live integration tests.

    Requires environment variables:
        - FALLBACK_GITHUB_TOKEN: Personal access token with repo read scope
    """

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_github_credentials(),
        reason="GitHub credentials not configured (need FALLBACK_GITHUB_TOKEN)",
    )
    async def test_fetch_github_issue(self, fetcher):
        """Fetch a known public GitHub issue."""
        # Use a known public issue that should always exist
        ticket_id = os.getenv("TEST_GITHUB_ISSUE", "octocat/Hello-World#1")

        result = await fetcher.fetch(ticket_id, "github")

        # Verify GitHub response structure
        assert "number" in result, "Response should contain 'number'"
        assert "title" in result, "Response should contain 'title'"
        assert "state" in result, "Response should contain 'state'"

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_github_credentials(),
        reason="GitHub credentials not configured",
    )
    async def test_github_fetch_returns_required_fields(self, fetcher):
        """Verify GitHub response includes fields needed for GenericTicket."""
        ticket_id = os.getenv("TEST_GITHUB_ISSUE", "octocat/Hello-World#1")

        result = await fetcher.fetch(ticket_id, "github")

        # Required for normalization
        assert "html_url" in result, "Response should contain html_url"
        assert "body" in result or result.get("body") is None, "body field expected"
        assert "user" in result, "Response should contain user info"


class TestAzureDevOpsIntegration:
    """Azure DevOps live integration tests (non-Auggie platform).

    Requires environment variables:
        - FALLBACK_AZURE_DEVOPS_ORGANIZATION: Organization name
        - FALLBACK_AZURE_DEVOPS_PAT: Personal access token
    """

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_azure_devops_credentials(),
        reason="Azure DevOps credentials not configured",
    )
    async def test_fetch_azure_devops_work_item(self, fetcher):
        """Fetch a real Azure DevOps work item."""
        # Format: project/work_item_id
        work_item = os.getenv("TEST_AZURE_DEVOPS_ITEM", "TestProject/1")

        result = await fetcher.fetch(work_item, "azure_devops")

        # Verify Azure DevOps response structure
        assert "id" in result, "Response should contain 'id'"
        assert "fields" in result, "Response should contain 'fields'"


class TestTrelloIntegration:
    """Trello live integration tests (alternative non-Auggie platform).

    Requires environment variables:
        - FALLBACK_TRELLO_API_KEY: API key from Trello developer portal
        - FALLBACK_TRELLO_TOKEN: OAuth token
    """

    @pytest.mark.live
    @pytest.mark.skipif(
        not has_trello_credentials(),
        reason="Trello credentials not configured (need FALLBACK_TRELLO_API_KEY)",
    )
    async def test_fetch_trello_card(self, fetcher):
        """Fetch a real Trello card."""
        # Trello card ID (the alphanumeric ID)
        card_id = os.getenv("TEST_TRELLO_CARD", "test-card-id")

        result = await fetcher.fetch(card_id, "trello")

        # Verify Trello response structure
        assert "id" in result, "Response should contain 'id'"
        assert "name" in result, "Response should contain 'name'"
        assert "idBoard" in result, "Response should contain board reference"


class TestCredentialValidation:
    """Tests for credential validation without making API calls."""

    @pytest.mark.live
    async def test_supports_platform_reflects_configuration(self, fetcher):
        """Verify supports_platform matches credential availability."""
        # If Jira credentials exist, should support Jira
        if has_jira_credentials():
            assert fetcher.supports_platform(Platform.JIRA)
        else:
            assert not fetcher.supports_platform(Platform.JIRA)

        # If GitHub credentials exist, should support GitHub
        if has_github_credentials():
            assert fetcher.supports_platform(Platform.GITHUB)
        else:
            assert not fetcher.supports_platform(Platform.GITHUB)

    @pytest.mark.live
    async def test_fetch_without_credentials_raises_error(self, fetcher):
        """Attempting to fetch without credentials should raise error."""
        # Find a platform without credentials configured
        unconfigured_platforms = []
        if not has_jira_credentials():
            unconfigured_platforms.append(("TEST-1", "jira"))
        if not has_github_credentials():
            unconfigured_platforms.append(("octocat/Hello-World#1", "github"))
        if not has_azure_devops_credentials():
            unconfigured_platforms.append(("TestProject/1", "azure_devops"))
        if not has_trello_credentials():
            unconfigured_platforms.append(("abc123", "trello"))

        if not unconfigured_platforms:
            pytest.skip("All platforms have credentials configured")

        ticket_id, platform = unconfigured_platforms[0]
        with pytest.raises(AgentIntegrationError):
            await fetcher.fetch(ticket_id, platform)
