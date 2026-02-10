"""Tests for ingot.integrations.fetchers.auggie_fetcher module.

Tests cover:
- AuggieMediatedFetcher instantiation
- Platform support checking (with and without ConfigManager)
- Prompt template retrieval
- Execute fetch prompt via AIBackend
- Full fetch_raw integration with mocked AIBackend
- New fetch() method with string platform parameter
- Timeout functionality
- Response validation
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ingot.config.fetch_config import AgentConfig, AgentPlatform
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.fetchers import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
)
from ingot.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
from ingot.integrations.fetchers.base import DEFAULT_TIMEOUT_SECONDS
from ingot.integrations.fetchers.templates import (
    PLATFORM_PROMPT_TEMPLATES,
    REQUIRED_FIELDS,
    SUPPORTED_PLATFORMS,
)
from ingot.integrations.providers.base import Platform


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend with proper spec for type safety."""
    backend = MagicMock(spec=AIBackend)
    # Default: successful response with JSON
    backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return backend


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
    def test_init_with_backend_only(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher._backend is mock_backend
        assert fetcher._config is None

    def test_init_with_config_manager(self, mock_backend, mock_config_manager):
        fetcher = AuggieMediatedFetcher(mock_backend, mock_config_manager)

        assert fetcher._backend is mock_backend
        assert fetcher._config is mock_config_manager

    def test_name_property(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.name == "Auggie MCP Fetcher"


class TestAuggieMediatedFetcherPlatformSupport:
    def test_supports_platform_jira(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.JIRA) is True

    def test_supports_platform_linear(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.LINEAR) is True

    def test_supports_platform_github(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_azure_devops_unsupported(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.AZURE_DEVOPS) is False

    def test_supports_platform_trello_unsupported(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.TRELLO) is False

    def test_supports_platform_monday_unsupported(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.MONDAY) is False

    def test_supports_platform_with_config_enabled(self, mock_backend, mock_config_manager):
        fetcher = AuggieMediatedFetcher(mock_backend, mock_config_manager)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is True
        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_with_config_disabled(
        self, mock_backend, mock_config_manager_jira_only
    ):
        fetcher = AuggieMediatedFetcher(mock_backend, mock_config_manager_jira_only)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is False
        assert fetcher.supports_platform(Platform.GITHUB) is False

    def test_supports_platform_no_config_defaults_true(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        # All platforms in SUPPORTED_PLATFORMS should return True
        for platform in SUPPORTED_PLATFORMS:
            assert fetcher.supports_platform(platform) is True


class TestAuggieMediatedFetcherPromptTemplates:
    def test_get_prompt_template_jira(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.JIRA)

        assert "{ticket_id}" in template
        assert "Jira" in template
        assert "JSON" in template

    def test_get_prompt_template_linear(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.LINEAR)

        assert "{ticket_id}" in template
        assert "Linear" in template
        assert "JSON" in template

    def test_get_prompt_template_github(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.GITHUB)

        assert "{ticket_id}" in template
        assert "GitHub" in template
        assert "JSON" in template

    def test_get_prompt_template_unsupported_raises(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            fetcher._get_prompt_template(Platform.AZURE_DEVOPS)

        assert "No prompt template" in str(exc_info.value)
        assert "AZURE_DEVOPS" in str(exc_info.value)

    def test_all_supported_platforms_have_templates(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        for platform in SUPPORTED_PLATFORMS:
            template = fetcher._get_prompt_template(platform)
            assert template is not None
            assert "{ticket_id}" in template


class TestAuggieMediatedFetcherExecuteFetchPrompt:
    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_success(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "TEST-1"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert result == '{"key": "TEST-1"}'
        mock_backend.run_print_quiet.assert_called_once_with("test prompt", dont_save_session=True)

    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_empty_response_raises(self, mock_backend):
        mock_backend.run_print_quiet.return_value = ""
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "empty response" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_fetch_prompt_exception_wrapped(self, mock_backend):
        mock_backend.run_print_quiet.side_effect = RuntimeError("CLI failed")
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "Backend invocation failed" in str(exc_info.value)
        assert exc_info.value.original_error is not None


class TestAuggieMediatedFetcherFetchRaw:
    @pytest.mark.asyncio
    async def test_fetch_raw_jira_success(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"key": "PROJ-123", "summary": "Test issue", "status": "Open"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert result == {"key": "PROJ-123", "summary": "Test issue", "status": "Open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_linear_success(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert result == {"identifier": "TEAM-42", "title": "Linear issue"}

    @pytest.mark.asyncio
    async def test_fetch_raw_github_success(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"number": 123, "title": "GitHub issue", "state": "open"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert result == {"number": 123, "title": "GitHub issue", "state": "open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_unsupported_platform_raises(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(PlatformNotSupportedError) as exc_info:
            await fetcher.fetch_raw("TICKET-1", Platform.AZURE_DEVOPS)

        assert exc_info.value.platform == "AZURE_DEVOPS"
        assert exc_info.value.fetcher_name == "Auggie MCP Fetcher"

    @pytest.mark.asyncio
    async def test_fetch_raw_parses_json_from_markdown_block(self, mock_backend):
        mock_backend.run_print_quiet.return_value = """Here is the ticket:

```json
{"key": "PROJ-456", "summary": "Markdown wrapped"}
```

Let me know if you need more info."""
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-456", Platform.JIRA)

        assert result == {"key": "PROJ-456", "summary": "Markdown wrapped"}

    @pytest.mark.asyncio
    async def test_fetch_raw_prompt_contains_ticket_id(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "ABC-999", "summary": "Test issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        await fetcher.fetch_raw("ABC-999", Platform.JIRA)

        call_args = mock_backend.run_print_quiet.call_args[0][0]
        assert "ABC-999" in call_args


class TestPlatformPromptTemplatesConstant:
    def test_templates_exist_for_all_supported_platforms(self):
        for platform in SUPPORTED_PLATFORMS:
            assert platform in PLATFORM_PROMPT_TEMPLATES

    def test_templates_have_ticket_id_placeholder(self):
        for platform, template in PLATFORM_PROMPT_TEMPLATES.items():
            assert "{ticket_id}" in template, f"Template for {platform} missing {{ticket_id}}"

    def test_templates_request_json_only(self):
        for platform, template in PLATFORM_PROMPT_TEMPLATES.items():
            assert "JSON" in template, f"Template for {platform} should mention JSON"
            assert (
                "only" in template.lower() or "ONLY" in template
            ), f"Template for {platform} should request ONLY JSON"


class TestAuggieMediatedFetcherFetchMethod:
    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_jira(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch("PROJ-123", "jira")

        assert result == {"key": "PROJ-123", "summary": "Test issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_linear(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch("TEAM-42", "linear")

        assert result == {"identifier": "TEAM-42", "title": "Linear issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_github(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"number": 123, "title": "GitHub issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch("owner/repo#123", "github")

        assert result == {"number": 123, "title": "GitHub issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_case_insensitive(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        # Test various case combinations
        result_upper = await fetcher.fetch("PROJ-123", "JIRA")
        result_mixed = await fetcher.fetch("PROJ-123", "Jira")

        assert result_upper["key"] == "PROJ-123"
        assert result_mixed["key"] == "PROJ-123"

    @pytest.mark.asyncio
    async def test_fetch_with_invalid_platform_string_raises(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch("TICKET-1", "unknown_platform")

        assert "Unknown platform" in str(exc_info.value)
        assert "unknown_platform" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_with_timeout_override(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test"}'
        fetcher = AuggieMediatedFetcher(mock_backend, timeout_seconds=30.0)

        # Override with shorter timeout
        result = await fetcher.fetch("PROJ-123", "jira", timeout_seconds=10.0)

        assert result == {"key": "PROJ-123", "summary": "Test"}
        # Verify instance timeout was never modified (thread-safe design)
        assert fetcher._timeout_seconds == 30.0

    @pytest.mark.asyncio
    async def test_fetch_with_unsupported_platform_enum_raises(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch("TICKET-1", "azure_devops")

        assert "not supported" in str(exc_info.value)
        assert "AZURE_DEVOPS" in str(exc_info.value)


class TestAuggieMediatedFetcherTimeout:
    def test_timeout_default_value(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert fetcher._timeout_seconds == 60.0

    def test_timeout_custom_value_in_init(self, mock_backend):
        fetcher = AuggieMediatedFetcher(mock_backend, timeout_seconds=120.0)

        assert fetcher._timeout_seconds == 120.0

    @pytest.mark.asyncio
    async def test_timeout_raises_agent_fetch_error(self, mock_backend):
        # Use a short but reliable sleep time to avoid flakiness
        def blocking_call(*args, **kwargs):
            time.sleep(1)  # 1 second sleep
            return '{"key": "PROJ-123"}'

        mock_backend.run_print_quiet.side_effect = blocking_call
        # Use 0.01s timeout - much shorter than 1s sleep
        fetcher = AuggieMediatedFetcher(mock_backend, timeout_seconds=0.01)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "timed out" in str(exc_info.value)
        assert "0.01s" in str(exc_info.value)


class TestAuggieMediatedFetcherValidation:
    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_jira(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"key": "PROJ-123", "summary": "Test", "status": "Open"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert result["key"] == "PROJ-123"
        assert result["summary"] == "Test"

    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_linear(self, mock_backend):
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert result["identifier"] == "TEAM-42"
        assert result["title"] == "Linear issue"

    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_github(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"number": 123, "title": "GitHub issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert result["number"] == 123
        assert result["title"] == "GitHub issue"

    @pytest.mark.asyncio
    async def test_validation_fails_missing_jira_key(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"summary": "Test issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert "missing required fields" in str(exc_info.value)
        assert "key" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_fails_missing_jira_summary(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert "missing required fields" in str(exc_info.value)
        assert "summary" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_fails_missing_linear_identifier(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"title": "Linear issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert "missing required fields" in str(exc_info.value)
        assert "identifier" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_fails_missing_github_number(self, mock_backend):
        mock_backend.run_print_quiet.return_value = '{"title": "GitHub issue"}'
        fetcher = AuggieMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert "missing required fields" in str(exc_info.value)
        assert "number" in str(exc_info.value)

    def test_required_fields_defined_for_all_supported_platforms(self):
        for platform in SUPPORTED_PLATFORMS:
            assert platform in REQUIRED_FIELDS, f"Missing REQUIRED_FIELDS for {platform}"
            assert len(REQUIRED_FIELDS[platform]) > 0, f"Empty REQUIRED_FIELDS for {platform}"
