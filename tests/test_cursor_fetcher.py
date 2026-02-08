"""Tests for spec.integrations.fetchers.cursor_fetcher module.

Tests cover:
- CursorMediatedFetcher instantiation
- Platform support checking (with and without ConfigManager)
- Prompt template retrieval
- Execute fetch prompt via AIBackend
- Full fetch_raw integration with mocked AIBackend
- New fetch() method with string platform parameter
- Timeout functionality
- Response validation
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from spec.config.fetch_config import AgentConfig, AgentPlatform
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendTimeoutError
from spec.integrations.fetchers import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
)
from spec.integrations.fetchers.cursor_fetcher import (
    DEFAULT_TIMEOUT_SECONDS,
    CursorMediatedFetcher,
)
from spec.integrations.fetchers.templates import (
    PLATFORM_PROMPT_TEMPLATES,
    REQUIRED_FIELDS,
    SUPPORTED_PLATFORMS,
)
from spec.integrations.providers.base import Platform


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend with proper spec for type safety."""
    backend = MagicMock(spec=AIBackend)
    backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return backend


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager with Jira/Linear/GitHub enabled."""
    config = MagicMock()
    agent_config = AgentConfig(
        platform=AgentPlatform.CURSOR,
        integrations={"jira": True, "linear": True, "github": True},
    )
    config.get_agent_config.return_value = agent_config
    return config


@pytest.fixture
def mock_config_manager_jira_only():
    """Create a mock ConfigManager with only Jira enabled."""
    config = MagicMock()
    agent_config = AgentConfig(
        platform=AgentPlatform.CURSOR,
        integrations={"jira": True, "linear": False, "github": False},
    )
    config.get_agent_config.return_value = agent_config
    return config


class TestCursorMediatedFetcherInstantiation:
    """Tests for CursorMediatedFetcher initialization."""

    def test_init_with_backend_only(self, mock_backend):
        """Can initialize with just AIBackend."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher._backend is mock_backend
        assert fetcher._config is None

    def test_init_with_config_manager(self, mock_backend, mock_config_manager):
        """Can initialize with AIBackend and ConfigManager."""
        fetcher = CursorMediatedFetcher(mock_backend, mock_config_manager)

        assert fetcher._backend is mock_backend
        assert fetcher._config is mock_config_manager

    def test_name_property(self, mock_backend):
        """Name property returns 'Cursor MCP Fetcher'."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher.name == "Cursor MCP Fetcher"


class TestCursorMediatedFetcherPlatformSupport:
    """Tests for supports_platform method."""

    def test_supports_platform_jira(self, mock_backend):
        """Jira is supported without config."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.JIRA) is True

    def test_supports_platform_linear(self, mock_backend):
        """Linear is supported without config."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.LINEAR) is True

    def test_supports_platform_github(self, mock_backend):
        """GitHub is supported without config."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_azure_devops_unsupported(self, mock_backend):
        """Azure DevOps is not supported."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher.supports_platform(Platform.AZURE_DEVOPS) is False

    def test_supports_platform_with_config_enabled(self, mock_backend, mock_config_manager):
        """Respects AgentConfig when platform is enabled."""
        fetcher = CursorMediatedFetcher(mock_backend, mock_config_manager)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is True
        assert fetcher.supports_platform(Platform.GITHUB) is True

    def test_supports_platform_with_config_disabled(
        self, mock_backend, mock_config_manager_jira_only
    ):
        """Respects AgentConfig when platform is disabled."""
        fetcher = CursorMediatedFetcher(mock_backend, mock_config_manager_jira_only)

        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.LINEAR) is False
        assert fetcher.supports_platform(Platform.GITHUB) is False

    def test_supports_platform_no_config_defaults_true(self, mock_backend):
        """Without config, supported platforms default to True."""
        fetcher = CursorMediatedFetcher(mock_backend)

        for platform in SUPPORTED_PLATFORMS:
            assert fetcher.supports_platform(platform) is True


class TestCursorMediatedFetcherPromptTemplates:
    """Tests for _get_prompt_template method."""

    def test_get_prompt_template_jira(self, mock_backend):
        """Returns Jira template with {ticket_id} placeholder."""
        fetcher = CursorMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.JIRA)

        assert "{ticket_id}" in template
        assert "Jira" in template
        assert "JSON" in template

    def test_get_prompt_template_linear(self, mock_backend):
        """Returns Linear template with {ticket_id} placeholder."""
        fetcher = CursorMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.LINEAR)

        assert "{ticket_id}" in template
        assert "Linear" in template
        assert "JSON" in template

    def test_get_prompt_template_github(self, mock_backend):
        """Returns GitHub template with {ticket_id} placeholder."""
        fetcher = CursorMediatedFetcher(mock_backend)

        template = fetcher._get_prompt_template(Platform.GITHUB)

        assert "{ticket_id}" in template
        assert "GitHub" in template
        assert "JSON" in template

    def test_get_prompt_template_unsupported_raises(self, mock_backend):
        """Raises AgentIntegrationError for unsupported platform."""
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            fetcher._get_prompt_template(Platform.AZURE_DEVOPS)

        assert "No prompt template" in str(exc_info.value)
        assert "AZURE_DEVOPS" in str(exc_info.value)

    def test_all_supported_platforms_have_templates(self, mock_backend):
        """All platforms in SUPPORTED_PLATFORMS have templates."""
        fetcher = CursorMediatedFetcher(mock_backend)

        for platform in SUPPORTED_PLATFORMS:
            template = fetcher._get_prompt_template(platform)
            assert template is not None
            assert "{ticket_id}" in template

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


class TestCursorMediatedFetcherFetchRaw:
    """Integration tests for fetch_raw method."""

    @pytest.mark.asyncio
    async def test_fetch_raw_jira_success(self, mock_backend):
        """Full flow with mocked backend returning JSON for Jira."""
        mock_backend.run_print_quiet.return_value = (
            '{"key": "PROJ-123", "summary": "Test issue", "status": "Open"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert result == {"key": "PROJ-123", "summary": "Test issue", "status": "Open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_linear_success(self, mock_backend):
        """Full flow with mocked backend returning JSON for Linear."""
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert result == {"identifier": "TEAM-42", "title": "Linear issue"}

    @pytest.mark.asyncio
    async def test_fetch_raw_github_success(self, mock_backend):
        """Full flow with mocked backend returning JSON for GitHub."""
        mock_backend.run_print_quiet.return_value = (
            '{"number": 123, "title": "GitHub issue", "state": "open"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert result == {"number": 123, "title": "GitHub issue", "state": "open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_unsupported_platform_raises(self, mock_backend):
        """Raises PlatformNotSupportedError for unsupported platform."""
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(PlatformNotSupportedError) as exc_info:
            await fetcher.fetch_raw("TICKET-1", Platform.AZURE_DEVOPS)

        assert exc_info.value.platform == "AZURE_DEVOPS"
        assert exc_info.value.fetcher_name == "Cursor MCP Fetcher"

    @pytest.mark.asyncio
    async def test_fetch_raw_parses_json_from_markdown_block(self, mock_backend):
        """Parses JSON from markdown code block in response."""
        mock_backend.run_print_quiet.return_value = """Here is the ticket:

```json
{"key": "PROJ-456", "summary": "Markdown wrapped"}
```

Let me know if you need more info."""
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-456", Platform.JIRA)

        assert result == {"key": "PROJ-456", "summary": "Markdown wrapped"}

    @pytest.mark.asyncio
    async def test_fetch_raw_prompt_contains_ticket_id(self, mock_backend):
        """Prompt sent to backend contains the ticket ID."""
        mock_backend.run_print_quiet.return_value = '{"key": "ABC-999", "summary": "Test issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        await fetcher.fetch_raw("ABC-999", Platform.JIRA)

        call_args = mock_backend.run_print_quiet.call_args[0][0]
        assert "ABC-999" in call_args


class TestCursorMediatedFetcherFetch:
    """Tests for fetch() method with string platform parameter."""

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_jira(self, mock_backend):
        """Can fetch using platform string 'jira'."""
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch("PROJ-123", "jira")

        assert result == {"key": "PROJ-123", "summary": "Test issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_linear(self, mock_backend):
        """Can fetch using platform string 'linear'."""
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch("TEAM-42", "linear")

        assert result == {"identifier": "TEAM-42", "title": "Linear issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_github(self, mock_backend):
        """Can fetch using platform string 'github'."""
        mock_backend.run_print_quiet.return_value = '{"number": 123, "title": "GitHub issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch("owner/repo#123", "github")

        assert result == {"number": 123, "title": "GitHub issue"}

    @pytest.mark.asyncio
    async def test_fetch_with_string_platform_case_insensitive(self, mock_backend):
        """Platform string is case-insensitive."""
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        result_upper = await fetcher.fetch("PROJ-123", "JIRA")
        result_mixed = await fetcher.fetch("PROJ-123", "Jira")

        assert result_upper["key"] == "PROJ-123"
        assert result_mixed["key"] == "PROJ-123"

    @pytest.mark.asyncio
    async def test_fetch_with_invalid_platform_string_raises(self, mock_backend):
        """Raises AgentIntegrationError for unknown platform string."""
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch("TICKET-1", "unknown_platform")

        assert "Unknown platform" in str(exc_info.value)
        assert "unknown_platform" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_with_timeout_override(self, mock_backend):
        """Can override timeout in fetch() call."""
        mock_backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test"}'
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=30.0)

        result = await fetcher.fetch("PROJ-123", "jira", timeout_seconds=10.0)

        assert result == {"key": "PROJ-123", "summary": "Test"}
        assert fetcher._timeout_seconds == 30.0

    @pytest.mark.asyncio
    async def test_fetch_with_unsupported_platform_enum_raises(self, mock_backend):
        """Raises AgentIntegrationError for known but unsupported platform enum."""
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch("TICKET-1", "azure_devops")

        assert "not supported" in str(exc_info.value)
        assert "AZURE_DEVOPS" in str(exc_info.value)


class TestCursorMediatedFetcherTimeout:
    """Tests for timeout functionality."""

    def test_timeout_default_value(self, mock_backend):
        """Default timeout is DEFAULT_TIMEOUT_SECONDS."""
        fetcher = CursorMediatedFetcher(mock_backend)

        assert fetcher._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert fetcher._timeout_seconds == 60.0

    def test_timeout_custom_value_in_init(self, mock_backend):
        """Can set custom timeout in __init__."""
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=120.0)

        assert fetcher._timeout_seconds == 120.0

    @pytest.mark.asyncio
    async def test_timeout_raises_agent_fetch_error(self, mock_backend):
        """BackendTimeoutError from backend becomes AgentFetchError."""
        mock_backend.run_print_quiet.side_effect = BackendTimeoutError(
            "Operation timed out after 30.0s", timeout_seconds=30.0
        )
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=30.0)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        assert "timed out" in str(exc_info.value)
        assert "30.0s" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_passed_to_backend(self, mock_backend):
        """Effective timeout is forwarded to backend.run_print_quiet()."""
        mock_backend.run_print_quiet.return_value = '{"key": "X-1", "summary": "T"}'
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=42.0)

        await fetcher._execute_fetch_prompt("test prompt", Platform.JIRA)

        call_kwargs = mock_backend.run_print_quiet.call_args.kwargs
        assert call_kwargs.get("timeout_seconds") == 42.0

    @pytest.mark.asyncio
    async def test_fetch_passes_timeout_through_without_resolving(self, mock_backend):
        """fetch() passes timeout_seconds directly without resolving to instance default."""
        mock_backend.run_print_quiet.return_value = '{"key": "X-1", "summary": "T"}'
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=60.0)

        await fetcher.fetch("X-1", "jira", timeout_seconds=15.0)

        call_kwargs = mock_backend.run_print_quiet.call_args.kwargs
        assert call_kwargs.get("timeout_seconds") == 15.0

    @pytest.mark.asyncio
    async def test_fetch_none_timeout_uses_instance_default(self, mock_backend):
        """fetch() with no timeout_seconds uses instance default via _execute_fetch_prompt."""
        mock_backend.run_print_quiet.return_value = '{"key": "X-1", "summary": "T"}'
        fetcher = CursorMediatedFetcher(mock_backend, timeout_seconds=99.0)

        await fetcher.fetch("X-1", "jira")

        call_kwargs = mock_backend.run_print_quiet.call_args.kwargs
        assert call_kwargs.get("timeout_seconds") == 99.0


class TestCursorMediatedFetcherValidation:
    """Tests for response validation."""

    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_jira(self, mock_backend):
        """Validation passes when all required Jira fields present."""
        mock_backend.run_print_quiet.return_value = (
            '{"key": "PROJ-123", "summary": "Test", "status": "Open"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert result["key"] == "PROJ-123"
        assert result["summary"] == "Test"

    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_linear(self, mock_backend):
        """Validation passes when all required Linear fields present."""
        mock_backend.run_print_quiet.return_value = (
            '{"identifier": "TEAM-42", "title": "Linear issue"}'
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert result["identifier"] == "TEAM-42"
        assert result["title"] == "Linear issue"

    @pytest.mark.asyncio
    async def test_validation_passes_with_required_fields_github(self, mock_backend):
        """Validation passes when all required GitHub fields present."""
        mock_backend.run_print_quiet.return_value = '{"number": 123, "title": "GitHub issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        result = await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert result["number"] == 123
        assert result["title"] == "GitHub issue"

    @pytest.mark.asyncio
    async def test_validation_fails_missing_jira_key(self, mock_backend):
        """Raises AgentResponseParseError when Jira 'key' missing."""
        mock_backend.run_print_quiet.return_value = '{"summary": "Test issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert "missing required fields" in str(exc_info.value)
        assert "key" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_fails_missing_linear_identifier(self, mock_backend):
        """Raises AgentResponseParseError when Linear 'identifier' missing."""
        mock_backend.run_print_quiet.return_value = '{"title": "Linear issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("TEAM-42", Platform.LINEAR)

        assert "missing required fields" in str(exc_info.value)
        assert "identifier" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validation_fails_missing_github_number(self, mock_backend):
        """Raises AgentResponseParseError when GitHub 'number' missing."""
        mock_backend.run_print_quiet.return_value = '{"title": "GitHub issue"}'
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("owner/repo#123", Platform.GITHUB)

        assert "missing required fields" in str(exc_info.value)
        assert "number" in str(exc_info.value)

    def test_required_fields_defined_for_all_supported_platforms(self):
        """REQUIRED_FIELDS has entries for all SUPPORTED_PLATFORMS."""
        for platform in SUPPORTED_PLATFORMS:
            assert platform in REQUIRED_FIELDS, f"Missing REQUIRED_FIELDS for {platform}"
            assert len(REQUIRED_FIELDS[platform]) > 0, f"Empty REQUIRED_FIELDS for {platform}"


class TestCursorMediatedFetcherExceptionTaxonomy:
    """Tests for correct exception types in fetch_raw."""

    @pytest.mark.asyncio
    async def test_agent_fetch_error_not_rewrapped(self, mock_backend):
        """AgentFetchError from _execute_fetch_prompt is NOT wrapped into AgentIntegrationError."""
        mock_backend.run_print_quiet.side_effect = RuntimeError("connection refused")
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        # Should be AgentFetchError, NOT AgentIntegrationError
        assert type(exc_info.value) is AgentFetchError
        assert "connection refused" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_agent_response_parse_error_not_rewrapped(self, mock_backend):
        """AgentResponseParseError is NOT wrapped into another exception type."""
        mock_backend.run_print_quiet.return_value = "not valid json at all"
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentResponseParseError):
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

    @pytest.mark.asyncio
    async def test_agent_integration_error_passes_through(self, mock_backend):
        """AgentIntegrationError from _execute_fetch_prompt passes through unchanged."""
        mock_backend.run_print_quiet.side_effect = AgentIntegrationError(
            message="MCP tool not available", agent_name="test"
        )
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert "MCP tool not available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unexpected_exception_becomes_agent_fetch_error(self, mock_backend):
        """Unexpected exceptions become AgentFetchError (not AgentIntegrationError)."""
        mock_backend.run_print_quiet.side_effect = ValueError("unexpected error")
        fetcher = CursorMediatedFetcher(mock_backend)

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert type(exc_info.value) is AgentFetchError
        assert "unexpected error" in str(exc_info.value)
