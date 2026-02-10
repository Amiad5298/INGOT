"""End-to-end integration tests for TicketService.

These tests verify the full pipeline: FakeBackend → real fetcher → real
create_ticket_service() → real TicketService.get_ticket() → real provider
normalize(). Only ProviderRegistry.get_provider_for_input() is patched
(to control platform detection).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.cache import InMemoryTicketCache
from ingot.integrations.fetchers import AuggieMediatedFetcher
from ingot.integrations.fetchers.exceptions import AgentResponseParseError
from ingot.integrations.providers.base import IssueTrackerProvider, Platform
from ingot.integrations.providers.github import GitHubProvider
from ingot.integrations.providers.jira import JiraProvider
from ingot.integrations.providers.linear import LinearProvider
from ingot.integrations.ticket_service import TicketService, create_ticket_service
from tests.fakes.fake_backend import FakeBackend

# ---------------------------------------------------------------------------
# Valid JSON fixtures per ticket platform
# ---------------------------------------------------------------------------

# Jira: needs "key" + "fields" dict (JiraProvider.normalize reads fields)
# Note: The fetcher validates top-level "key" + "summary" (REQUIRED_FIELDS),
# while JiraProvider.normalize() reads from the "fields" dict. Agent-mediated
# responses include both: top-level summary for validation and fields for normalization.
JIRA_RESPONSE = {
    "key": "PROJ-123",
    "summary": "Fix login bug",
    "self": "https://mycompany.atlassian.net/rest/api/2/issue/12345",
    "fields": {
        "summary": "Fix login bug",
        "description": "Users cannot login with SSO",
        "status": {"name": "In Progress"},
        "issuetype": {"name": "Bug"},
        "assignee": {"displayName": "Alice"},
        "labels": ["backend", "auth"],
        "created": "2024-01-15T10:30:00Z",
        "updated": "2024-01-16T14:20:00Z",
        "priority": {"name": "High"},
        "project": {"key": "PROJ", "name": "Project"},
    },
}

# Linear: flat format (LinearProvider.normalize reads top-level fields)
LINEAR_RESPONSE = {
    "identifier": "ENG-42",
    "title": "Add dark mode",
    "description": "Implement dark mode theme",
    "state": {"name": "Todo", "type": "unstarted"},
    "assignee": {"name": "Bob", "email": "bob@example.com"},
    "labels": {"nodes": [{"name": "frontend"}]},
    "createdAt": "2024-02-01T09:00:00Z",
    "updatedAt": "2024-02-02T11:00:00Z",
    "priority": 2,
    "team": {"key": "ENG", "name": "Engineering"},
    "url": "https://linear.app/eng/issue/ENG-42",
}

# GitHub: flat format (GitHubProvider.normalize reads top-level fields)
GITHUB_RESPONSE = {
    "number": 99,
    "title": "Update README",
    "body": "Add installation instructions",
    "state": "open",
    "user": {"login": "charlie"},
    "labels": [{"name": "documentation"}],
    "created_at": "2024-03-01T08:00:00Z",
    "updated_at": "2024-03-02T10:00:00Z",
    "html_url": "https://github.com/acme/repo/issues/99",
    "milestone": None,
    "assignee": {"login": "charlie"},
}


def _make_real_provider(platform: str) -> IssueTrackerProvider:
    """Create a real provider instance for the given platform."""
    providers: dict[str, IssueTrackerProvider] = {
        "jira": JiraProvider(),
        "linear": LinearProvider(),
        "github": GitHubProvider(),
    }
    return providers[platform]


PLATFORM_RESPONSES = {
    "jira": JIRA_RESPONSE,
    "linear": LINEAR_RESPONSE,
    "github": GITHUB_RESPONSE,
}

PLATFORM_EXPECTED = {
    "jira": {"id": "PROJ-123", "platform": Platform.JIRA, "title": "Fix login bug"},
    "linear": {"id": "ENG-42", "platform": Platform.LINEAR, "title": "Add dark mode"},
    "github": {"id": "acme/repo#99", "platform": Platform.GITHUB, "title": "Update README"},
}

PLATFORM_INPUTS = {
    "jira": "PROJ-123",
    "linear": "ENG-42",
    "github": "acme/repo#99",
}


# ---------------------------------------------------------------------------
# TestE2EFetcherSelection
# ---------------------------------------------------------------------------


class TestE2EFetcherSelection:
    @pytest.mark.parametrize(
        ("backend_platform", "expected_name"),
        [
            (AgentPlatform.AUGGIE, "Auggie MCP Fetcher"),
            (AgentPlatform.CLAUDE, "Claude MCP Fetcher"),
            (AgentPlatform.CURSOR, "Cursor MCP Fetcher"),
        ],
    )
    @pytest.mark.asyncio
    async def test_fetcher_selection_by_platform(
        self, backend_platform: AgentPlatform, expected_name: str
    ) -> None:
        backend = FakeBackend(responses=[], platform=backend_platform)
        service = await create_ticket_service(backend=backend)
        assert service.primary_fetcher_name == expected_name


# ---------------------------------------------------------------------------
# TestE2EFullPipeline
# ---------------------------------------------------------------------------


class TestE2EFullPipeline:
    @pytest.mark.parametrize(
        "backend_platform", [AgentPlatform.AUGGIE, AgentPlatform.CLAUDE, AgentPlatform.CURSOR]
    )
    @pytest.mark.parametrize("ticket_platform", ["jira", "linear", "github"])
    @pytest.mark.asyncio
    async def test_full_pipeline(
        self, backend_platform: AgentPlatform, ticket_platform: str
    ) -> None:
        response_json = json.dumps(PLATFORM_RESPONSES[ticket_platform])
        backend = FakeBackend(
            responses=[(True, response_json)],
            platform=backend_platform,
        )

        service = await create_ticket_service(backend=backend, enable_fallback=False)
        provider = _make_real_provider(ticket_platform)

        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket(PLATFORM_INPUTS[ticket_platform], skip_cache=True)

        expected = PLATFORM_EXPECTED[ticket_platform]
        assert ticket.id == expected["id"]
        assert ticket.platform == expected["platform"]
        assert ticket.title == expected["title"]
        assert backend.call_count == 1


# ---------------------------------------------------------------------------
# TestE2EFallbackBehavior
# ---------------------------------------------------------------------------


class TestE2EFallbackBehavior:
    @pytest.mark.asyncio
    async def test_fallback_on_parse_error(self) -> None:
        backend = FakeBackend(
            responses=[(True, "not valid json at all")],
            platform=AgentPlatform.AUGGIE,
        )

        fallback_fetcher = MagicMock()
        fallback_fetcher.name = "MockFallback"
        fallback_fetcher.supports_platform.return_value = True
        fallback_fetcher.fetch = AsyncMock(return_value=JIRA_RESPONSE)

        primary = AuggieMediatedFetcher(backend=backend)
        service = TicketService(
            primary_fetcher=primary,
            fallback_fetcher=fallback_fetcher,
        )

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("PROJ-123", skip_cache=True)

        assert ticket.id == "PROJ-123"
        assert ticket.title == "Fix login bug"
        fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self) -> None:
        backend = FakeBackend(
            responses=[(True, "")],
            platform=AgentPlatform.AUGGIE,
        )

        fallback_fetcher = MagicMock()
        fallback_fetcher.name = "MockFallback"
        fallback_fetcher.supports_platform.return_value = True
        fallback_fetcher.fetch = AsyncMock(return_value=LINEAR_RESPONSE)

        primary = AuggieMediatedFetcher(backend=backend)
        service = TicketService(
            primary_fetcher=primary,
            fallback_fetcher=fallback_fetcher,
        )

        provider = LinearProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("ENG-42", skip_cache=True)

        assert ticket.id == "ENG-42"
        assert ticket.title == "Add dark mode"

    @pytest.mark.asyncio
    async def test_fallback_on_missing_required_fields(self) -> None:
        # Valid JSON but missing "key" and "summary" required by Jira validation
        incomplete_response = json.dumps({"fields": {"summary": "Test"}})
        backend = FakeBackend(
            responses=[(True, incomplete_response)],
            platform=AgentPlatform.AUGGIE,
        )

        fallback_fetcher = MagicMock()
        fallback_fetcher.name = "MockFallback"
        fallback_fetcher.supports_platform.return_value = True
        fallback_fetcher.fetch = AsyncMock(return_value=JIRA_RESPONSE)

        primary = AuggieMediatedFetcher(backend=backend)
        service = TicketService(
            primary_fetcher=primary,
            fallback_fetcher=fallback_fetcher,
        )

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("PROJ-123", skip_cache=True)

        assert ticket.id == "PROJ-123"
        assert ticket.title == "Fix login bug"
        fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_fallback_propagates_error(self) -> None:
        backend = FakeBackend(
            responses=[(True, "not json")],
            platform=AgentPlatform.AUGGIE,
        )

        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            with pytest.raises(AgentResponseParseError):
                await service.get_ticket("PROJ-123", skip_cache=True)


# ---------------------------------------------------------------------------
# TestE2ENoMediatedFetcherPlatforms
# ---------------------------------------------------------------------------


class TestE2ENoMediatedFetcherPlatforms:
    @pytest.mark.asyncio
    async def test_manual_backend_uses_direct_api(self) -> None:
        backend = FakeBackend(responses=[], platform=AgentPlatform.MANUAL)
        auth_manager = MagicMock()
        service = await create_ticket_service(backend=backend, auth_manager=auth_manager)
        assert service.primary_fetcher_name == "Direct API Fetcher"

    @pytest.mark.asyncio
    async def test_aider_backend_uses_direct_api(self) -> None:
        backend = FakeBackend(responses=[], platform=AgentPlatform.AIDER)
        auth_manager = MagicMock()
        service = await create_ticket_service(backend=backend, auth_manager=auth_manager)
        assert service.primary_fetcher_name == "Direct API Fetcher"

    @pytest.mark.asyncio
    async def test_manual_no_auth_raises(self) -> None:
        backend = FakeBackend(responses=[], platform=AgentPlatform.MANUAL)
        with pytest.raises(ValueError, match="no fetchers configured"):
            await create_ticket_service(backend=backend, enable_fallback=False)


# ---------------------------------------------------------------------------
# TestE2ECacheIntegration
# ---------------------------------------------------------------------------


class TestE2ECacheIntegration:
    @pytest.mark.asyncio
    async def test_second_fetch_returns_cached(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json)],
            platform=AgentPlatform.AUGGIE,
        )
        cache = InMemoryTicketCache()
        service = await create_ticket_service(backend=backend, cache=cache, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket1 = await service.get_ticket("PROJ-123")
            ticket2 = await service.get_ticket("PROJ-123")

        assert ticket1.id == ticket2.id == "PROJ-123"
        assert backend.call_count == 1

    @pytest.mark.asyncio
    async def test_skip_cache_refetches(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json), (True, response_json)],
            platform=AgentPlatform.AUGGIE,
        )
        cache = InMemoryTicketCache()
        service = await create_ticket_service(backend=backend, cache=cache, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            await service.get_ticket("PROJ-123", skip_cache=True)
            await service.get_ticket("PROJ-123", skip_cache=True)

        assert backend.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_invalidation_forces_refetch(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json), (True, response_json)],
            platform=AgentPlatform.AUGGIE,
        )
        cache = InMemoryTicketCache()
        service = await create_ticket_service(backend=backend, cache=cache, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            await service.get_ticket("PROJ-123")
            service.invalidate_cache(Platform.JIRA, "PROJ-123")
            await service.get_ticket("PROJ-123")

        assert backend.call_count == 2


# ---------------------------------------------------------------------------
# TestE2ECallVerification
# ---------------------------------------------------------------------------


class TestE2ECallVerification:
    @pytest.mark.asyncio
    async def test_auggie_no_timeout_in_backend_call(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json)],
            platform=AgentPlatform.AUGGIE,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            await service.get_ticket("PROJ-123", skip_cache=True)

        assert len(backend.quiet_calls) == 1
        _, kwargs = backend.quiet_calls[0]
        # Auggie uses asyncio-only timeout; does NOT pass timeout_seconds
        assert kwargs.get("timeout_seconds") is None
        assert kwargs["dont_save_session"] is True

    @pytest.mark.asyncio
    async def test_claude_passes_timeout_to_backend(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json)],
            platform=AgentPlatform.CLAUDE,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            await service.get_ticket("PROJ-123", skip_cache=True)

        assert len(backend.quiet_calls) == 1
        _, kwargs = backend.quiet_calls[0]
        # Claude/Cursor use base class which passes timeout_seconds
        assert kwargs["timeout_seconds"] is not None
        assert kwargs["dont_save_session"] is True

    @pytest.mark.asyncio
    async def test_cursor_passes_timeout_to_backend(self) -> None:
        response_json = json.dumps(JIRA_RESPONSE)
        backend = FakeBackend(
            responses=[(True, response_json)],
            platform=AgentPlatform.CURSOR,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            await service.get_ticket("PROJ-123", skip_cache=True)

        assert len(backend.quiet_calls) == 1
        _, kwargs = backend.quiet_calls[0]
        assert kwargs["timeout_seconds"] is not None
        assert kwargs["dont_save_session"] is True


# ---------------------------------------------------------------------------
# TestE2EJsonParsingVariants
# ---------------------------------------------------------------------------


class TestE2EJsonParsingVariants:
    @pytest.mark.asyncio
    async def test_json_in_markdown_code_block(self) -> None:
        wrapped = f"```json\n{json.dumps(JIRA_RESPONSE)}\n```"
        backend = FakeBackend(
            responses=[(True, wrapped)],
            platform=AgentPlatform.AUGGIE,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = JiraProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("PROJ-123", skip_cache=True)

        assert ticket.id == "PROJ-123"
        assert ticket.title == "Fix login bug"

    @pytest.mark.asyncio
    async def test_json_with_surrounding_text(self) -> None:
        wrapped = f"Here is the data: {json.dumps(LINEAR_RESPONSE)}"
        backend = FakeBackend(
            responses=[(True, wrapped)],
            platform=AgentPlatform.CLAUDE,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = LinearProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("ENG-42", skip_cache=True)

        assert ticket.id == "ENG-42"
        assert ticket.title == "Add dark mode"

    @pytest.mark.asyncio
    async def test_bare_json_object(self) -> None:
        backend = FakeBackend(
            responses=[(True, json.dumps(GITHUB_RESPONSE))],
            platform=AgentPlatform.CURSOR,
        )
        service = await create_ticket_service(backend=backend, enable_fallback=False)

        provider = GitHubProvider()
        with patch(
            "ingot.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=provider,
        ):
            ticket = await service.get_ticket("acme/repo#99", skip_cache=True)

        assert ticket.id == "acme/repo#99"
        assert ticket.title == "Update README"
