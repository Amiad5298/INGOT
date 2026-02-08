"""Tests for spec.integrations.fetchers.base module.

Tests cover:
- TicketFetcher ABC contract (cannot instantiate, must implement methods)
- AgentMediatedFetcher base class functionality
- JSON parsing edge cases (bare JSON, markdown blocks, nested structures)
- Platform support checking
- Error handling and exceptions
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from spec.integrations.backends.base import AIBackend
from spec.integrations.fetchers import (
    AgentFetchError,
    AgentIntegrationError,
    AgentMediatedFetcher,
    AgentResponseParseError,
    PlatformNotSupportedError,
    TicketFetcher,
    TicketFetchError,
)
from spec.integrations.providers.base import Platform


class TestTicketFetcherABC:
    """Tests for TicketFetcher abstract base class."""

    def test_cannot_instantiate_directly(self):
        """TicketFetcher cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            TicketFetcher()  # type: ignore[abstract]

    def test_subclass_must_implement_name(self):
        """Subclass must implement name property."""

        class IncompleteFetcher(TicketFetcher):
            def supports_platform(self, platform: Platform) -> bool:
                return True

            async def fetch_raw(self, ticket_id: str, platform: Platform) -> dict[str, Any]:
                return {}

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()  # type: ignore[abstract]

    def test_subclass_must_implement_supports_platform(self):
        """Subclass must implement supports_platform method."""

        class IncompleteFetcher(TicketFetcher):
            @property
            def name(self) -> str:
                return "Test"

            async def fetch_raw(self, ticket_id: str, platform: Platform) -> dict[str, Any]:
                return {}

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch_raw(self):
        """Subclass must implement fetch_raw method."""

        class IncompleteFetcher(TicketFetcher):
            @property
            def name(self) -> str:
                return "Test"

            def supports_platform(self, platform: Platform) -> bool:
                return True

        with pytest.raises(TypeError, match="abstract"):
            IncompleteFetcher()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self):
        """Complete subclass with all methods can be instantiated."""

        class CompleteFetcher(TicketFetcher):
            @property
            def name(self) -> str:
                return "Complete Test Fetcher"

            def supports_platform(self, platform: Platform) -> bool:
                return platform == Platform.JIRA

            async def fetch_raw(self, ticket_id: str, platform: Platform) -> dict[str, Any]:
                return {"id": ticket_id}

        fetcher = CompleteFetcher()
        assert fetcher.name == "Complete Test Fetcher"
        assert fetcher.supports_platform(Platform.JIRA) is True
        assert fetcher.supports_platform(Platform.GITHUB) is False


class MockAgentFetcher(AgentMediatedFetcher):
    """Mock implementation of AgentMediatedFetcher for testing.

    Overrides _execute_fetch_prompt to return a configurable response
    without touching a real backend. Also overrides supports_platform
    and _get_prompt_template for controlled test behavior.
    """

    def __init__(self, response: str = '{"key": "value"}'):
        """Initialize with configurable response."""
        super().__init__(backend=MagicMock(spec=AIBackend))
        self._response = response
        self._last_prompt: str | None = None
        self._last_platform: Platform | None = None

    @property
    def name(self) -> str:
        return "Mock Agent Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        return platform in (Platform.JIRA, Platform.LINEAR)

    async def _execute_fetch_prompt(
        self,
        prompt: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> str:
        self._last_prompt = prompt
        self._last_platform = platform
        return self._response

    def _get_prompt_template(self, platform: Platform) -> str:
        return f"Fetch ticket {{ticket_id}} from {platform.name}"

    def _validate_response(self, data: dict[str, Any], platform: Platform) -> dict[str, Any]:
        # Skip validation in mock — these tests focus on JSON parsing
        return data


class TestAgentMediatedFetcherABC:
    """Tests for AgentMediatedFetcher abstract methods."""

    def test_cannot_instantiate_directly(self):
        """AgentMediatedFetcher cannot be instantiated directly (name is abstract)."""
        mock_backend = MagicMock(spec=AIBackend)
        with pytest.raises(TypeError, match="abstract"):
            AgentMediatedFetcher(backend=mock_backend)  # type: ignore[abstract]

    def test_subclass_only_needs_name(self):
        """Subclass only needs to implement the name property."""

        class MinimalFetcher(AgentMediatedFetcher):
            @property
            def name(self) -> str:
                return "Minimal"

        mock_backend = MagicMock(spec=AIBackend)
        fetcher = MinimalFetcher(backend=mock_backend)
        assert fetcher.name == "Minimal"

    def test_mock_fetcher_can_be_instantiated(self):
        """MockAgentFetcher can be instantiated."""
        fetcher = MockAgentFetcher()
        assert fetcher.name == "Mock Agent Fetcher"


class TestAgentMediatedFetcherJSONParsing:
    """Tests for _parse_response JSON extraction."""

    def test_parse_bare_json_object(self):
        """Parses bare JSON object."""
        fetcher = MockAgentFetcher()
        result = fetcher._parse_response('{"id": "PROJ-123", "title": "Test"}')
        assert result == {"id": "PROJ-123", "title": "Test"}

    def test_parse_json_with_whitespace(self):
        """Parses JSON with leading/trailing whitespace."""
        fetcher = MockAgentFetcher()
        result = fetcher._parse_response('  \n{"key": "value"}\n  ')
        assert result == {"key": "value"}

    def test_parse_markdown_code_block_with_json_hint(self):
        """Parses JSON from markdown code block with json language hint."""
        fetcher = MockAgentFetcher()
        response = '```json\n{"id": "TEST-1", "status": "open"}\n```'
        result = fetcher._parse_response(response)
        assert result == {"id": "TEST-1", "status": "open"}

    def test_parse_markdown_code_block_without_hint(self):
        """Parses JSON from markdown code block without language hint."""
        fetcher = MockAgentFetcher()
        response = '```\n{"id": "TEST-2"}\n```'
        result = fetcher._parse_response(response)
        assert result == {"id": "TEST-2"}

    def test_parse_markdown_code_block_uppercase_json(self):
        """Parses JSON from markdown code block with uppercase JSON hint."""
        fetcher = MockAgentFetcher()
        response = '```JSON\n{"key": "value"}\n```'
        result = fetcher._parse_response(response)
        assert result == {"key": "value"}

    def test_parse_nested_json(self):
        """Parses nested JSON structures."""
        fetcher = MockAgentFetcher()
        response = '{"outer": {"inner": {"deep": "value"}}, "list": [1, 2, 3]}'
        result = fetcher._parse_response(response)
        assert result == {"outer": {"inner": {"deep": "value"}}, "list": [1, 2, 3]}

    def test_parse_json_with_text_before(self):
        """Parses JSON when there's text before the JSON object."""
        fetcher = MockAgentFetcher()
        response = 'Here is the ticket data:\n{"id": "PROJ-1"}'
        result = fetcher._parse_response(response)
        assert result == {"id": "PROJ-1"}

    def test_parse_json_with_text_after(self):
        """Parses JSON when there's text after the JSON object."""
        fetcher = MockAgentFetcher()
        response = '{"id": "PROJ-2"}\nThis is additional context.'
        result = fetcher._parse_response(response)
        assert result == {"id": "PROJ-2"}

    def test_parse_json_with_text_before_and_after(self):
        """Parses JSON when surrounded by text."""
        fetcher = MockAgentFetcher()
        response = 'Ticket info:\n{"id": "X-1"}\nDone.'
        result = fetcher._parse_response(response)
        assert result == {"id": "X-1"}

    def test_parse_empty_response_raises_error(self):
        """Empty response raises AgentResponseParseError."""
        fetcher = MockAgentFetcher()
        with pytest.raises(AgentResponseParseError, match="Empty response"):
            fetcher._parse_response("")

    def test_parse_whitespace_only_raises_error(self):
        """Whitespace-only response raises AgentResponseParseError."""
        fetcher = MockAgentFetcher()
        with pytest.raises(AgentResponseParseError, match="Empty response"):
            fetcher._parse_response("   \n\t  ")

    def test_parse_invalid_json_raises_error(self):
        """Invalid JSON raises AgentResponseParseError."""
        fetcher = MockAgentFetcher()
        with pytest.raises(AgentResponseParseError, match="Failed to parse JSON"):
            fetcher._parse_response("not json at all")

    def test_parse_json_array_raises_error(self):
        """JSON array (not object) raises AgentResponseParseError."""
        fetcher = MockAgentFetcher()
        with pytest.raises(AgentResponseParseError, match="Failed to parse JSON"):
            fetcher._parse_response("[1, 2, 3]")

    def test_parse_json_string_raises_error(self):
        """JSON string raises AgentResponseParseError."""
        fetcher = MockAgentFetcher()
        with pytest.raises(AgentResponseParseError, match="Failed to parse JSON"):
            fetcher._parse_response('"just a string"')

    def test_parse_first_code_block_when_multiple_exist(self):
        """When multiple json-tagged code blocks exist, parses the first one."""
        fetcher = MockAgentFetcher()
        response = '```json\n{"id": "first"}\n```\nSome text\n```json\n{"id": "second"}\n```'
        result = fetcher._parse_response(response)
        assert result == {"id": "first"}

    def test_parse_json_tagged_block_prioritized_over_untagged(self):
        """JSON-tagged blocks are prioritized over untagged blocks."""
        fetcher = MockAgentFetcher()
        # Untagged block appears first, but json-tagged block should be prioritized
        response = '```\n{"id": "untagged"}\n```\nMore text\n```json\n{"id": "tagged"}\n```'
        result = fetcher._parse_response(response)
        assert result == {"id": "tagged"}

    def test_parse_fallback_to_untagged_block(self):
        """Falls back to untagged code block if no json-tagged blocks exist."""
        fetcher = MockAgentFetcher()
        response = '```\n{"id": "untagged"}\n```\nSome text after'
        result = fetcher._parse_response(response)
        assert result == {"id": "untagged"}

    def test_parse_multiple_json_objects_in_text(self):
        """Extracts first valid JSON object when multiple exist in raw text."""
        fetcher = MockAgentFetcher()
        response = 'First object: {"id": "first"} and second: {"id": "second"}'
        result = fetcher._parse_response(response)
        assert result == {"id": "first"}


class TestAgentMediatedFetcherFetchRaw:
    """Tests for fetch_raw method."""

    @pytest.mark.asyncio
    async def test_fetch_raw_success(self):
        """fetch_raw returns parsed JSON for supported platform."""
        fetcher = MockAgentFetcher('{"id": "PROJ-123", "status": "open"}')
        result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)
        assert result == {"id": "PROJ-123", "status": "open"}

    @pytest.mark.asyncio
    async def test_fetch_raw_builds_correct_prompt(self):
        """fetch_raw builds prompt using template and ticket ID."""
        fetcher = MockAgentFetcher('{"id": "TEST-1"}')
        await fetcher.fetch_raw("TEST-1", Platform.JIRA)
        assert fetcher._last_prompt == "Fetch ticket TEST-1 from JIRA"
        assert fetcher._last_platform == Platform.JIRA

    @pytest.mark.asyncio
    async def test_fetch_raw_unsupported_platform_raises_error(self):
        """fetch_raw raises PlatformNotSupportedError for unsupported platform."""
        fetcher = MockAgentFetcher()
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            await fetcher.fetch_raw("TEST-1", Platform.GITHUB)
        assert exc_info.value.platform == "GITHUB"
        assert exc_info.value.fetcher_name == "Mock Agent Fetcher"

    @pytest.mark.asyncio
    async def test_fetch_raw_with_markdown_response(self):
        """fetch_raw handles markdown-wrapped JSON response."""
        fetcher = MockAgentFetcher('```json\n{"id": "MD-1"}\n```')
        result = await fetcher.fetch_raw("MD-1", Platform.LINEAR)
        assert result == {"id": "MD-1"}

    @pytest.mark.asyncio
    async def test_fetch_raw_wraps_unexpected_exceptions(self):
        """fetch_raw wraps unexpected exceptions in AgentFetchError."""

        class FailingFetcher(AgentMediatedFetcher):
            @property
            def name(self) -> str:
                return "Failing Fetcher"

            def supports_platform(self, platform: Platform) -> bool:
                return True

            async def _execute_fetch_prompt(
                self, prompt: str, platform: Platform, timeout_seconds: float | None = None
            ) -> str:
                raise ValueError("Network timeout")

            def _get_prompt_template(self, platform: Platform) -> str:
                return "Fetch {ticket_id}"

        fetcher = FailingFetcher(backend=MagicMock(spec=AIBackend))
        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher.fetch_raw("TEST-1", Platform.JIRA)
        assert "Unexpected error" in str(exc_info.value)
        assert exc_info.value.original_error is not None
        assert isinstance(exc_info.value.original_error, ValueError)
        # Verify exception chaining
        assert exc_info.value.__cause__ is exc_info.value.original_error

    @pytest.mark.asyncio
    async def test_fetch_raw_preserves_agent_integration_errors(self):
        """fetch_raw re-raises AgentIntegrationError without wrapping."""

        class AgentErrorFetcher(AgentMediatedFetcher):
            @property
            def name(self) -> str:
                return "Agent Error Fetcher"

            def supports_platform(self, platform: Platform) -> bool:
                return True

            async def _execute_fetch_prompt(
                self, prompt: str, platform: Platform, timeout_seconds: float | None = None
            ) -> str:
                raise AgentIntegrationError("Agent unavailable", agent_name="Test")

            def _get_prompt_template(self, platform: Platform) -> str:
                return "Fetch {ticket_id}"

        fetcher = AgentErrorFetcher(backend=MagicMock(spec=AIBackend))
        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch_raw("TEST-1", Platform.JIRA)
        assert str(exc_info.value) == "Agent unavailable"
        assert exc_info.value.agent_name == "Test"

    @pytest.mark.asyncio
    async def test_fetch_raw_preserves_agent_fetch_errors(self):
        """fetch_raw re-raises AgentFetchError without wrapping."""

        class FetchErrorFetcher(AgentMediatedFetcher):
            @property
            def name(self) -> str:
                return "Fetch Error Fetcher"

            def supports_platform(self, platform: Platform) -> bool:
                return True

            async def _execute_fetch_prompt(
                self, prompt: str, platform: Platform, timeout_seconds: float | None = None
            ) -> str:
                raise AgentFetchError("Timeout during fetch", agent_name="Test")

            def _get_prompt_template(self, platform: Platform) -> str:
                return "Fetch {ticket_id}"

        fetcher = FetchErrorFetcher(backend=MagicMock(spec=AIBackend))
        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher.fetch_raw("TEST-1", Platform.JIRA)
        assert str(exc_info.value) == "Timeout during fetch"
        assert exc_info.value.agent_name == "Test"

    @pytest.mark.asyncio
    async def test_fetch_raw_preserves_agent_response_parse_errors(self):
        """fetch_raw re-raises AgentResponseParseError without wrapping."""

        class ParseErrorFetcher(AgentMediatedFetcher):
            @property
            def name(self) -> str:
                return "Parse Error Fetcher"

            def supports_platform(self, platform: Platform) -> bool:
                return True

            async def _execute_fetch_prompt(
                self, prompt: str, platform: Platform, timeout_seconds: float | None = None
            ) -> str:
                raise AgentResponseParseError(
                    "Invalid JSON", agent_name="Test", raw_response="not json"
                )

            def _get_prompt_template(self, platform: Platform) -> str:
                return "Fetch {ticket_id}"

        fetcher = ParseErrorFetcher(backend=MagicMock(spec=AIBackend))
        with pytest.raises(AgentResponseParseError) as exc_info:
            await fetcher.fetch_raw("TEST-1", Platform.JIRA)
        assert str(exc_info.value) == "Invalid JSON"
        assert exc_info.value.agent_name == "Test"


class TestAgentMediatedFetcherBuildPrompt:
    """Tests for _build_prompt method."""

    def test_build_prompt_uses_template(self):
        """_build_prompt formats template with ticket_id."""
        fetcher = MockAgentFetcher()
        prompt = fetcher._build_prompt("ABC-123", Platform.JIRA)
        assert prompt == "Fetch ticket ABC-123 from JIRA"

    def test_build_prompt_different_platforms(self):
        """_build_prompt uses platform name in template."""
        fetcher = MockAgentFetcher()
        jira_prompt = fetcher._build_prompt("X-1", Platform.JIRA)
        linear_prompt = fetcher._build_prompt("X-1", Platform.LINEAR)
        assert "JIRA" in jira_prompt
        assert "LINEAR" in linear_prompt


class TestExceptionHierarchy:
    """Tests for exception classes."""

    def test_ticket_fetch_error_is_base(self):
        """TicketFetchError is the base exception."""
        error = TicketFetchError("test error")
        assert str(error) == "test error"

    def test_platform_not_supported_inherits_from_base(self):
        """PlatformNotSupportedError inherits from TicketFetchError."""
        error = PlatformNotSupportedError("GITHUB", "TestFetcher")
        assert isinstance(error, TicketFetchError)

    def test_platform_not_supported_auto_message(self):
        """PlatformNotSupportedError generates message automatically."""
        error = PlatformNotSupportedError("GITHUB", "TestFetcher")
        assert "TestFetcher" in str(error)
        assert "GITHUB" in str(error)

    def test_platform_not_supported_custom_message(self):
        """PlatformNotSupportedError accepts custom message."""
        error = PlatformNotSupportedError("X", "Y", message="Custom msg")
        assert str(error) == "Custom msg"

    def test_platform_not_supported_attributes(self):
        """PlatformNotSupportedError stores platform and fetcher name."""
        error = PlatformNotSupportedError("JIRA", "MyFetcher")
        assert error.platform == "JIRA"
        assert error.fetcher_name == "MyFetcher"

    def test_agent_integration_error_inherits_from_base(self):
        """AgentIntegrationError inherits from TicketFetchError."""
        error = AgentIntegrationError("failed")
        assert isinstance(error, TicketFetchError)

    def test_agent_integration_error_with_agent_name(self):
        """AgentIntegrationError stores agent name."""
        error = AgentIntegrationError("timeout", agent_name="Auggie")
        assert error.agent_name == "Auggie"

    def test_agent_integration_error_with_original_error(self):
        """AgentIntegrationError stores original error."""
        original = ValueError("parse error")
        error = AgentIntegrationError("failed", original_error=original)
        assert error.original_error is original

    def test_can_catch_all_fetch_errors(self):
        """All fetch errors can be caught with TicketFetchError."""
        errors = [
            TicketFetchError("base"),
            PlatformNotSupportedError("X", "Y"),
            AgentIntegrationError("z"),
        ]
        for error in errors:
            try:
                raise error
            except TicketFetchError:
                pass  # Expected - all should be caught
