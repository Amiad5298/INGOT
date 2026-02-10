"""Tests for ingot.integrations.fetchers.handlers module.

Tests cover:
- PlatformHandler ABC contract
- GraphQLPlatformHandler base class
- All 6 platform handlers (Jira, Linear, GitHub, Azure DevOps, Trello, Monday)
- Credential validation
- Ticket ID parsing
- HTTP request construction
- Response handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ingot.integrations.fetchers.exceptions import (
    CredentialValidationError,
    PlatformApiError,
    PlatformNotFoundError,
    TicketIdFormatError,
)
from ingot.integrations.fetchers.handlers import (
    AzureDevOpsHandler,
    GitHubHandler,
    GraphQLPlatformHandler,
    JiraHandler,
    LinearHandler,
    MondayHandler,
    PlatformHandler,
    TrelloHandler,
)


@pytest.fixture
def mock_http_client():
    """Create a mock httpx.AsyncClient.

    Note: The mock response must include status_code attribute for
    the _check_not_found() method in base.py to work correctly.
    """
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = {"id": "test"}
    response.raise_for_status = MagicMock()
    # Required for _check_not_found() in base.py
    response.status_code = 200
    client.get.return_value = response
    client.post.return_value = response
    return client


@pytest.fixture
def jira_credentials():
    """Valid Jira credentials."""
    return {
        "url": "https://company.atlassian.net",
        "email": "user@example.com",
        "token": "jira-api-token",
    }


@pytest.fixture
def linear_credentials():
    """Valid Linear credentials."""
    return {"api_key": "lin_api_key_123"}


@pytest.fixture
def github_credentials():
    """Valid GitHub credentials."""
    return {"token": "ghp_token123"}


@pytest.fixture
def azure_devops_credentials():
    """Valid Azure DevOps credentials."""
    return {"organization": "myorg", "pat": "azure-pat-token"}


@pytest.fixture
def trello_credentials():
    """Valid Trello credentials."""
    return {"api_key": "trello-api-key", "token": "trello-token"}


@pytest.fixture
def monday_credentials():
    """Valid Monday credentials."""
    return {"api_key": "monday-api-key"}


class TestPlatformHandlerABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError, match="abstract"):
            PlatformHandler()

    def test_subclass_must_implement_platform_name(self):
        class IncompleteFetcher(PlatformHandler):
            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"token"})

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()

    def test_subclass_must_implement_required_credential_keys(self):
        class IncompleteFetcher(PlatformHandler):
            @property
            def platform_name(self) -> str:
                return "Test"

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()

    def test_subclass_must_implement_fetch(self):
        class IncompleteFetcher(PlatformHandler):
            @property
            def platform_name(self) -> str:
                return "Test"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"token"})

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()


class TestGraphQLPlatformHandler:
    def test_cannot_instantiate_without_extract_entity(self):
        class IncompleteGraphQLHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        with pytest.raises(TypeError, match="abstract"):
            IncompleteGraphQLHandler()

    def test_check_graphql_errors_raises_on_errors(self):
        class TestHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            def _extract_entity(self, data, ticket_id):
                return data.get("item")

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        handler = TestHandler()
        response_with_errors = {"errors": [{"message": "Some error"}]}

        with pytest.raises(PlatformApiError, match="GraphQL errors"):
            handler._check_graphql_errors(response_with_errors, "TEST-1")

    def test_check_graphql_errors_passes_when_no_errors(self):
        class TestHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            def _extract_entity(self, data, ticket_id):
                return data.get("item")

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        handler = TestHandler()
        response_without_errors = {"data": {"item": {"id": "1"}}}

        # Should not raise
        handler._check_graphql_errors(response_without_errors, "TEST-1")

    def test_check_null_data_raises_on_null(self):
        class TestHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            def _extract_entity(self, data, ticket_id):
                return data.get("item")

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        handler = TestHandler()
        response_with_null_data = {"data": None}

        with pytest.raises(PlatformApiError, match="null data"):
            handler._check_null_data(response_with_null_data, "TEST-1")

    def test_check_null_data_returns_data_when_valid(self):
        class TestHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            def _extract_entity(self, data, ticket_id):
                return data.get("item")

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        handler = TestHandler()
        response_with_valid_data = {"data": {"item": {"id": "1"}}}

        data = handler._check_null_data(response_with_valid_data, "TEST-1")
        assert data == {"item": {"id": "1"}}

    def test_validate_graphql_response_full_flow(self):
        class TestHandler(GraphQLPlatformHandler):
            @property
            def platform_name(self) -> str:
                return "TestGraphQL"

            @property
            def required_credential_keys(self) -> frozenset[str]:
                return frozenset({"api_key"})

            def _extract_entity(self, data, ticket_id):
                item = data.get("item")
                if item is None:
                    raise PlatformNotFoundError(
                        platform_name=self.platform_name,
                        ticket_id=ticket_id,
                    )
                return item

            async def fetch(self, ticket_id, credentials, timeout_seconds=None, http_client=None):
                return {}

        handler = TestHandler()

        # Valid response
        valid_response = {"data": {"item": {"id": "123", "name": "Test"}}}
        result = handler._validate_graphql_response(valid_response, "TEST-1")
        assert result == {"id": "123", "name": "Test"}

        # Response with errors
        error_response = {"errors": [{"message": "Error"}]}
        with pytest.raises(PlatformApiError, match="GraphQL errors"):
            handler._validate_graphql_response(error_response, "TEST-1")

        # Response with null data
        null_data_response = {"data": None}
        with pytest.raises(PlatformApiError, match="null data"):
            handler._validate_graphql_response(null_data_response, "TEST-1")

        # Response with missing entity
        missing_entity_response = {"data": {"item": None}}
        with pytest.raises(PlatformNotFoundError):
            handler._validate_graphql_response(missing_entity_response, "TEST-1")


class TestJiraHandler:
    def test_platform_name(self):
        handler = JiraHandler()
        assert handler.platform_name == "Jira"

    def test_required_credential_keys(self):
        handler = JiraHandler()
        assert handler.required_credential_keys == frozenset({"url", "email", "token"})

    def test_validate_credentials_success(self, jira_credentials):
        handler = JiraHandler()
        # Should not raise
        handler._validate_credentials(jira_credentials)

    def test_validate_credentials_missing_key(self):
        handler = JiraHandler()
        incomplete_creds = {"url": "https://example.com", "email": "user@example.com"}

        with pytest.raises(CredentialValidationError, match="token"):
            handler._validate_credentials(incomplete_creds)

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, jira_credentials):
        mock_http_client.get.return_value.json.return_value = {
            "key": "PROJ-123",
            "fields": {"summary": "Test issue"},
        }
        handler = JiraHandler()

        result = await handler.fetch("PROJ-123", jira_credentials, http_client=mock_http_client)

        assert result["key"] == "PROJ-123"
        mock_http_client.get.assert_called_once()
        call_args = mock_http_client.get.call_args
        assert "PROJ-123" in call_args[0][0]
        assert "rest/api/3/issue" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fetch_uses_basic_auth(self, mock_http_client, jira_credentials):
        handler = JiraHandler()

        await handler.fetch("PROJ-123", jira_credentials, http_client=mock_http_client)

        call_args = mock_http_client.get.call_args
        # Jira uses httpx.BasicAuth for authentication
        assert "auth" in call_args[1]
        auth = call_args[1]["auth"]
        assert isinstance(auth, httpx.BasicAuth)


class TestLinearHandler:
    def test_platform_name(self):
        handler = LinearHandler()
        assert handler.platform_name == "Linear"

    def test_required_credential_keys(self):
        handler = LinearHandler()
        assert handler.required_credential_keys == frozenset({"api_key"})

    def test_validate_credentials_success(self, linear_credentials):
        handler = LinearHandler()
        handler._validate_credentials(linear_credentials)

    def test_validate_credentials_missing_key(self):
        handler = LinearHandler()

        with pytest.raises(CredentialValidationError, match="api_key"):
            handler._validate_credentials({})

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, linear_credentials):
        mock_http_client.post.return_value.json.return_value = {
            "data": {
                "issueByIdentifier": {
                    "id": "uuid-123",
                    "identifier": "TEAM-42",
                    "title": "Test issue",
                }
            }
        }
        handler = LinearHandler()

        result = await handler.fetch("TEAM-42", linear_credentials, http_client=mock_http_client)

        assert result["identifier"] == "TEAM-42"
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_graphql_error(self, mock_http_client, linear_credentials):
        mock_http_client.post.return_value.json.return_value = {
            "errors": [{"message": "Issue not found"}]
        }
        handler = LinearHandler()

        with pytest.raises(PlatformApiError, match="GraphQL errors"):
            await handler.fetch("TEAM-999", linear_credentials, http_client=mock_http_client)


class TestGitHubHandler:
    def test_platform_name(self):
        handler = GitHubHandler()
        assert handler.platform_name == "GitHub"

    def test_required_credential_keys(self):
        handler = GitHubHandler()
        assert handler.required_credential_keys == frozenset({"token"})

    def test_parse_ticket_id_valid(self):
        handler = GitHubHandler()
        owner, repo, number = handler._parse_ticket_id("microsoft/vscode#12345")

        assert owner == "microsoft"
        assert repo == "vscode"
        assert number == 12345

    def test_parse_ticket_id_invalid(self):
        handler = GitHubHandler()

        with pytest.raises(TicketIdFormatError, match="Invalid GitHub ticket format"):
            handler._parse_ticket_id("invalid-format")

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, github_credentials):
        mock_http_client.get.return_value.json.return_value = {
            "number": 123,
            "title": "Test issue",
            "state": "open",
        }
        handler = GitHubHandler()

        result = await handler.fetch(
            "owner/repo#123", github_credentials, http_client=mock_http_client
        )

        assert result["number"] == 123
        call_args = mock_http_client.get.call_args
        assert "/repos/owner/repo/issues/123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fetch_uses_bearer_token(self, mock_http_client, github_credentials):
        handler = GitHubHandler()

        await handler.fetch("owner/repo#1", github_credentials, http_client=mock_http_client)

        call_args = mock_http_client.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer ghp_token123"


class TestAzureDevOpsHandler:
    def test_platform_name(self):
        handler = AzureDevOpsHandler()
        assert handler.platform_name == "Azure DevOps"

    def test_required_credential_keys(self):
        handler = AzureDevOpsHandler()
        assert handler.required_credential_keys == frozenset({"organization", "pat"})

    def test_parse_ticket_id_valid(self):
        handler = AzureDevOpsHandler()
        project, work_item_id = handler._parse_ticket_id("MyProject/12345")

        assert project == "MyProject"
        assert work_item_id == 12345

    def test_parse_ticket_id_invalid(self):
        handler = AzureDevOpsHandler()

        with pytest.raises(TicketIdFormatError, match="Invalid Azure DevOps ticket format"):
            handler._parse_ticket_id("invalid")

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, azure_devops_credentials):
        mock_http_client.get.return_value.json.return_value = {
            "id": 12345,
            "fields": {"System.Title": "Test work item"},
        }
        handler = AzureDevOpsHandler()

        result = await handler.fetch(
            "MyProject/12345", azure_devops_credentials, http_client=mock_http_client
        )

        assert result["id"] == 12345
        call_args = mock_http_client.get.call_args
        assert "dev.azure.com/myorg/MyProject" in call_args[0][0]
        assert "12345" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fetch_uses_basic_auth_with_pat(self, mock_http_client, azure_devops_credentials):
        handler = AzureDevOpsHandler()

        await handler.fetch("Project/1", azure_devops_credentials, http_client=mock_http_client)

        call_args = mock_http_client.get.call_args
        # Azure DevOps uses httpx.BasicAuth for authentication (empty username, PAT as password)
        assert "auth" in call_args[1]
        auth = call_args[1]["auth"]
        assert isinstance(auth, httpx.BasicAuth)


class TestTrelloHandler:
    def test_platform_name(self):
        handler = TrelloHandler()
        assert handler.platform_name == "Trello"

    def test_required_credential_keys(self):
        handler = TrelloHandler()
        assert handler.required_credential_keys == frozenset({"api_key", "token"})

    def test_validate_credentials_success(self, trello_credentials):
        handler = TrelloHandler()
        handler._validate_credentials(trello_credentials)

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, trello_credentials):
        mock_http_client.get.return_value.json.return_value = {
            "id": "card123",
            "name": "Test card",
        }
        handler = TrelloHandler()

        result = await handler.fetch("card123", trello_credentials, http_client=mock_http_client)

        assert result["id"] == "card123"
        call_args = mock_http_client.get.call_args
        assert "/cards/card123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_fetch_uses_query_params_auth(self, mock_http_client, trello_credentials):
        handler = TrelloHandler()

        await handler.fetch("card123", trello_credentials, http_client=mock_http_client)

        call_args = mock_http_client.get.call_args
        params = call_args[1]["params"]
        assert params["key"] == "trello-api-key"
        assert params["token"] == "trello-token"


class TestMondayHandler:
    def test_platform_name(self):
        handler = MondayHandler()
        assert handler.platform_name == "Monday"

    def test_required_credential_keys(self):
        handler = MondayHandler()
        assert handler.required_credential_keys == frozenset({"api_key"})

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_http_client, monday_credentials):
        mock_http_client.post.return_value.json.return_value = {
            "data": {
                "items": [
                    {
                        "id": "12345",
                        "name": "Test item",
                        "state": "active",
                    }
                ]
            }
        }
        handler = MondayHandler()

        result = await handler.fetch("12345", monday_credentials, http_client=mock_http_client)

        assert result["id"] == "12345"
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_graphql_error(self, mock_http_client, monday_credentials):
        mock_http_client.post.return_value.json.return_value = {
            "errors": [{"message": "Item not found"}]
        }
        handler = MondayHandler()

        with pytest.raises(PlatformApiError, match="GraphQL errors"):
            await handler.fetch("99999", monday_credentials, http_client=mock_http_client)

    @pytest.mark.asyncio
    async def test_fetch_item_not_found(self, mock_http_client, monday_credentials):
        mock_http_client.post.return_value.json.return_value = {"data": {"items": []}}
        handler = MondayHandler()

        with pytest.raises(PlatformNotFoundError):
            await handler.fetch("99999", monday_credentials, http_client=mock_http_client)
