"""Tests for spec.integrations.fetchers.auggie_fetcher module.

Tests cover:
- AuggieMediatedFetcher instantiation
- Platform support checking (with and without ConfigManager)
- Prompt template retrieval
- Execute fetch prompt via AuggieClient
- Full fetch_raw integration with mocked AuggieClient
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spec.config.fetch_config import AgentConfig, AgentPlatform
from spec.integrations.fetchers import (
    AgentIntegrationError,
    AuggieMediatedFetcher,
    PlatformNotSupportedError,
)
from spec.integrations.fetchers.auggie_fetcher import (
    PLATFORM_PROMPT_TEMPLATES,
    SUPPORTED_PLATFORMS,
)
from spec.integrations.providers.base import Platform


@pytest.fixture
def mock_auggie_client():
    """Create a mock AuggieClient."""
    client = MagicMock()
    # Default: successful response with JSON
    client.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return client


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager with Jira/Linear/GitHub enabled."""
    config = MagicMock()
    agent_config = AgentConfig(
        platform=AgentPlatform.AUGGIE,
        integrations={"jira": True, "linear": True, "github": True},
    )
    config.get_agent_config.return_value = agent_config
    return config


@pytest.fixture
def mock_config_manager_jira_only():
    """Create a mock ConfigManager with only Jira enabled."""
    config = MagicMock()
    agent_config = AgentConfig(
        platform=AgentPlatform.AUGGIE,
        integrations={"jira": True, "linear": False, "github": False},
    )
    config.get_agent_config.return_value = agent_config
    return config


class TestAuggieMediatedFetcherInstantiation:
    """Tests for AuggieMediatedFetcher initialization."""

    def test_init_with_auggie_client_only(self, mock_auggie_client):
        """Can initialize with just AuggieClient."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher._auggie is mock_auggie_client
        assert fetcher._config is None

    def test_init_with_config_manager(self, mock_auggie_client, mock_config_manager):
        """Can initialize with AuggieClient and ConfigManager."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client, mock_config_manager)

        assert fetcher._auggie is mock_auggie_client
        assert fetcher._config is mock_config_manager

    def test_name_property(self, mock_auggie_client):
        """Name property returns 'Auggie MCP Fetcher'."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.name == "Auggie MCP Fetcher"


class TestAuggieMediatedFetcherPlatformSupport:
    """Tests for supports_platform method."""

    def test_supports_platform_jira(self, mock_auggie_client):
        """Jira is supported without config."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.JIRA) is True

    def test_supports_platform_linear(self, mock_auggie_client):
        """Linear is supported without config."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.LINEAR) is True

    def test_supports_platform_github(self, mock_auggie_client):
        """GitHub is supported without config."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_azure_devops_unsupported(self, mock_auggie_client):
        """Azure DevOps is not supported."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.AZURE_DEVOPS) is False

    def test_supports_platform_trello_unsupported(self, mock_auggie_client):
        """Trello is not supported."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.TRELLO) is False

    def test_supports_platform_monday_unsupported(self, mock_auggie_client):
        """Monday is not supported."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher.supports_platform(Platform.MONDAY) is False

    def test_supports_platform_with_config_enabled(self, mock_auggie_client, mock_config_manager):
        """Respects AgentConfig when platform is enabled."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client, mock_config_manager)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is True
        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_with_config_disabled(
        self, mock_auggie_client, mock_config_manager_jira_only
    ):
        """Respects AgentConfig when platform is disabled."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client, mock_config_manager_jira_only)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is False
        assert fetcher.supports_platform(Platform.GITHUB) is False

    def test_supports_platform_no_config_defaults_true(self, mock_auggie_client):
        """Without config, supported platforms default to True."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        # All platforms in SUPPORTED_PLATFORMS should return True
        for platform in SUPPORTED_PLATFORMS:
            assert fetcher.supports_platform(platform) is True


class TestAuggieMediatedFetcherPromptTemplates:
    """Tests for _get_prompt_template method."""

    def test_get_prompt_template_jira(self, mock_auggie_client):
        """Returns Jira template with {ticket_id} placeholder."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        template = fetcher._get_prompt_template(Platform.JIRA)

        assert "{ticket_id}" in template
        assert "Jira" in template
        assert "JSON" in template

    def test_get_prompt_template_linear(self, mock_auggie_client):
        """Returns Linear template with {ticket_id} placeholder."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        template = fetcher._get_prompt_template(Platform.LINEAR)

        assert "{ticket_id}" in template
        assert "Linear" in template
        assert "JSON" in template

    def test_get_prompt_template_github(self, mock_auggie_client):
        """Returns GitHub template with {ticket_id} placeholder."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        template = fetcher._get_prompt_template(Platform.GITHUB)

        assert "{ticket_id}" in template
        assert "GitHub" in template
        assert "JSON" in template

    def test_get_prompt_template_unsupported_raises(self, mock_auggie_client):
        """Raises AgentIntegrationError for unsupported platform."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        with pytest.raises(AgentIntegrationError) as exc_info:
            fetcher._get_prompt_template(Platform.AZURE_DEVOPS)

        assert "No prompt template" in str(exc_info.value)
        assert "AZURE_DEVOPS" in str(exc_info.value)

    def test_all_supported_platforms_have_templates(self, mock_auggie_client):
        """All platforms in SUPPORTED_PLATFORMS have templates."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        for platform in SUPPORTED_PLATFORMS:
            template = fetcher._get_prompt_template(platform)
            assert template is not None
            assert "{ticket_id}" in template


class TestAuggieMediatedFetcherExecuteFetchPrompt:
    """Tests for _execute_fetch_prompt method."""

    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_success(self, mock_auggie_client):
        """Returns stdout on successful execution."""
        mock_auggie_client.run_print_quiet.return_value = '{"key": "TEST-1"}'
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        result = await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert result == '{"key": "TEST-1"}'
        mock_auggie_client.run_print_quiet.assert_called_once_with(
            "test prompt", dont_save_session=True
        )

    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_empty_response_raises(self, mock_auggie_client):
        """Raises AgentIntegrationError on empty response."""
        mock_auggie_client.run_print_quiet.return_value = ""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "empty response" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_exception_wrapped(self, mock_auggie_client):
        """Wraps exceptions in AgentIntegrationError."""
        mock_auggie_client.run_print_quiet.side_effect = RuntimeError("CLI failed")
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "CLI invocation failed" in str(exc_info.value)
        assert exc_info.value.original_error is not None


class TestAuggieMediatedFetcherFetchRaw:
    """Integration tests for fetch_raw method."""

    @pytest.mark.asyncio
    async def test_fetch_raw_jira_success(self, mock_auggie_client):
        """Full flow with mocked Auggie returning JSON for Jira."""
        mock_auggie_client.run_print_quiet.return_value = (
            '{"key": "PROJ-123", "summary": "Test issue", "status": "Open"}'
        )
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert result == {"key": "PROJ-123", "summary": "Test issue", "status": "Open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_linear_success(self, mock_auggie_client):
        """Full flow with mocked Auggie returning JSON for Linear."""
        mock_auggie_client.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        result = await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert result == {"identifier": "TEAM-42", "title": "Linear issue"}

    @pytest.mark.asyncio
    async def test_fetch_raw_github_success(self, mock_auggie_client):
        """Full flow with mocked Auggie returning JSON for GitHub."""
        mock_auggie_client.run_print_quiet.return_value = (
            '{"number": 123, "title": "GitHub issue", "state": "open"}'
        )
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        result = await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert result == {"number": 123, "title": "GitHub issue", "state": "open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_unsupported_platform_raises(self, mock_auggie_client):
        """Raises PlatformNotSupportedError for unsupported platform."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        with pytest.raises(PlatformNotSupportedError) as exc_info:
            await fetcher.fetch_raw("TICKET-1", Platform.AZURE_DEVOPS)

        assert exc_info.value.platform == "AZURE_DEVOPS"
        assert exc_info.value.fetcher_name == "Auggie MCP Fetcher"

    @pytest.mark.asyncio
    async def test_fetch_raw_parses_json_from_markdown_block(self, mock_auggie_client):
        """Parses JSON from markdown code block in response."""
        mock_auggie_client.run_print_quiet.return_value = """Here is the ticket:

```json
{"key": "PROJ-456", "summary": "Markdown wrapped"}
```

Let me know if you need more info."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        result = await fetcher.fetch_raw("PROJ-456", Platform.JIRA)

        assert result == {"key": "PROJ-456", "summary": "Markdown wrapped"}

    @pytest.mark.asyncio
    async def test_fetch_raw_prompt_contains_ticket_id(self, mock_auggie_client):
        """Prompt sent to Auggie contains the ticket ID."""
        mock_auggie_client.run_print_quiet.return_value = '{"key": "ABC-999"}'
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        await fetcher.fetch_raw("ABC-999", Platform.JIRA)

        call_args = mock_auggie_client.run_print_quiet.call_args[0][0]
        assert "ABC-999" in call_args


class TestPlatformPromptTemplatesConstant:
    """Tests for PLATFORM_PROMPT_TEMPLATES constant."""

    def test_templates_exist_for_all_supported_platforms(self):
        """All SUPPORTED_PLATFORMS have corresponding templates."""
        for platform in SUPPORTED_PLATFORMS:
            assert platform in PLATFORM_PROMPT_TEMPLATES

    def test_templates_have_ticket_id_placeholder(self):
        """All templates have {ticket_id} placeholder."""
        for platform, template in PLATFORM_PROMPT_TEMPLATES.items():
            assert "{ticket_id}" in template, f"Template for {platform} missing {{ticket_id}}"

    def test_templates_request_json_only(self):
        """All templates instruct to return only JSON."""
        for platform, template in PLATFORM_PROMPT_TEMPLATES.items():
            assert "JSON" in template, f"Template for {platform} should mention JSON"
            assert (
                "only" in template.lower() or "ONLY" in template
            ), f"Template for {platform} should request ONLY JSON"
