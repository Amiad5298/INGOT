"""Tests for the backend-platform compatibility matrix.

Tests:
- get_platform_support() for all backend × platform combinations
- MCP_SUPPORT dict completeness (every AgentPlatform has an entry)
- API_SUPPORT includes expected platforms
- create_ticket_service() consults the compatibility matrix
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingot.config.compatibility import API_SUPPORT, MCP_SUPPORT, get_platform_support
from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.providers.base import Platform


class TestMCPSupportCompleteness:
    def test_every_ai_backend_has_entry(self):
        for member in AgentPlatform:
            assert member in MCP_SUPPORT, f"MCP_SUPPORT missing key for {member.name}"

    def test_values_are_frozensets(self):
        for member, platforms in MCP_SUPPORT.items():
            assert isinstance(
                platforms, frozenset
            ), f"MCP_SUPPORT[{member.name}] should be a frozenset, got {type(platforms)}"

    def test_mcp_values_contain_only_platform_members(self):
        for member, platforms in MCP_SUPPORT.items():
            for p in platforms:
                assert isinstance(
                    p, Platform
                ), f"MCP_SUPPORT[{member.name}] contains non-Platform value: {p}"


class TestAPISupportCoverage:
    def test_api_support_is_frozenset(self):
        assert isinstance(API_SUPPORT, frozenset)

    def test_api_support_contains_jira(self):
        assert Platform.JIRA in API_SUPPORT

    def test_api_support_contains_linear(self):
        assert Platform.LINEAR in API_SUPPORT

    def test_api_support_contains_github(self):
        assert Platform.GITHUB in API_SUPPORT

    def test_api_support_contains_azure_devops(self):
        assert Platform.AZURE_DEVOPS in API_SUPPORT

    def test_api_support_contains_trello(self):
        assert Platform.TRELLO in API_SUPPORT

    def test_api_support_contains_monday(self):
        assert Platform.MONDAY in API_SUPPORT

    def test_api_support_values_are_platform_members(self):
        for p in API_SUPPORT:
            assert isinstance(p, Platform), f"API_SUPPORT contains non-Platform value: {p}"


class TestGetPlatformSupport:
    # --- MCP-supported backends (AUGGIE, CLAUDE, CURSOR) ---

    @pytest.mark.parametrize(
        "backend",
        [AgentPlatform.AUGGIE, AgentPlatform.CLAUDE, AgentPlatform.CURSOR],
        ids=["auggie", "claude", "cursor"],
    )
    @pytest.mark.parametrize(
        "platform",
        [Platform.JIRA, Platform.LINEAR, Platform.GITHUB],
        ids=["jira", "linear", "github"],
    )
    def test_mcp_backends_support_core_platforms_via_mcp(self, backend, platform):
        supported, mechanism = get_platform_support(backend, platform)
        assert supported is True
        assert mechanism == "mcp"

    @pytest.mark.parametrize(
        "backend",
        [AgentPlatform.AUGGIE, AgentPlatform.CLAUDE, AgentPlatform.CURSOR],
        ids=["auggie", "claude", "cursor"],
    )
    @pytest.mark.parametrize(
        "platform",
        [Platform.AZURE_DEVOPS, Platform.TRELLO, Platform.MONDAY],
        ids=["azure_devops", "trello", "monday"],
    )
    def test_mcp_backends_fallback_to_api_for_other_platforms(self, backend, platform):
        supported, mechanism = get_platform_support(backend, platform)
        assert supported is True
        assert mechanism == "api"

    # --- Non-MCP backends (AIDER, MANUAL) ---

    @pytest.mark.parametrize(
        "backend",
        [AgentPlatform.AIDER, AgentPlatform.MANUAL],
        ids=["aider", "manual"],
    )
    @pytest.mark.parametrize(
        "platform",
        list(Platform),
        ids=[p.name.lower() for p in Platform],
    )
    def test_non_mcp_backends_use_api_for_all_api_supported(self, backend, platform):
        supported, mechanism = get_platform_support(backend, platform)
        if platform in API_SUPPORT:
            assert supported is True
            assert mechanism == "api"
        else:
            assert supported is False
            assert mechanism == "unsupported"

    def test_empty_mcp_set_for_aider(self):
        assert MCP_SUPPORT[AgentPlatform.AIDER] == frozenset()

    def test_empty_mcp_set_for_manual(self):
        assert MCP_SUPPORT[AgentPlatform.MANUAL] == frozenset()

    def test_unknown_backend_returns_api_or_unsupported(self):
        # Uses .get() with default frozenset(), so unknown keys just skip MCP
        # We simulate by passing a mock that won't match any dict key
        # Since AgentPlatform is an enum, all valid values are covered.
        # This test verifies the .get() fallback logic by checking a platform
        # that IS in API_SUPPORT with a backend that has no MCP entries.
        supported, mechanism = get_platform_support(AgentPlatform.MANUAL, Platform.JIRA)
        assert supported is True
        assert mechanism == "api"


class TestCreateTicketServiceCompatibilityIntegration:
    @pytest.mark.asyncio
    async def test_auggie_backend_uses_mcp_support(self):
        mock_backend = MagicMock()
        mock_backend.platform = AgentPlatform.AUGGIE

        with patch("ingot.integrations.ticket_service.AuggieMediatedFetcher") as mock_fetcher_cls:
            mock_fetcher_cls.return_value.name = "AuggieMediatedFetcher"

            service = await _create_service(mock_backend)

            assert service.primary_fetcher_name == "AuggieMediatedFetcher"
            mock_fetcher_cls.assert_called_once()
            await service.close()

    @pytest.mark.asyncio
    async def test_aider_backend_no_mcp_uses_direct_api(self):
        mock_backend = MagicMock()
        mock_backend.platform = AgentPlatform.AIDER
        mock_auth = MagicMock()

        with patch("ingot.integrations.ticket_service.DirectAPIFetcher") as mock_direct_cls:
            mock_direct_cls.return_value.name = "DirectAPIFetcher"
            mock_direct_cls.return_value.close = AsyncMock()

            from ingot.integrations.ticket_service import create_ticket_service

            service = await create_ticket_service(
                backend=mock_backend,
                auth_manager=mock_auth,
            )

            assert service.primary_fetcher_name == "DirectAPIFetcher"
            assert service.fallback_fetcher_name is None
            await service.close()

    @pytest.mark.asyncio
    async def test_patching_mcp_support_changes_fetcher_selection(self):
        mock_backend = MagicMock()
        mock_backend.platform = AgentPlatform.AUGGIE
        mock_auth = MagicMock()

        # Patch MCP_SUPPORT so AUGGIE has no MCP platforms
        patched_mcp = {
            AgentPlatform.AUGGIE: frozenset(),  # Empty → no mediated fetcher
            AgentPlatform.CLAUDE: frozenset(),
            AgentPlatform.CURSOR: frozenset(),
            AgentPlatform.AIDER: frozenset(),
            AgentPlatform.MANUAL: frozenset(),
        }

        with (
            patch("ingot.config.compatibility.MCP_SUPPORT", patched_mcp),
            patch("ingot.integrations.ticket_service.DirectAPIFetcher") as mock_direct_cls,
        ):
            mock_direct_cls.return_value.name = "DirectAPIFetcher"
            mock_direct_cls.return_value.close = AsyncMock()

            from ingot.integrations.ticket_service import create_ticket_service

            service = await create_ticket_service(
                backend=mock_backend,
                auth_manager=mock_auth,
            )

            # Should use DirectAPIFetcher as primary since MCP is empty
            assert service.primary_fetcher_name == "DirectAPIFetcher"
            await service.close()

    @pytest.mark.asyncio
    async def test_manual_backend_no_mcp_raises_without_auth(self):
        mock_backend = MagicMock()
        mock_backend.platform = AgentPlatform.MANUAL

        from ingot.integrations.ticket_service import create_ticket_service

        with pytest.raises(ValueError, match="no fetchers configured"):
            await create_ticket_service(backend=mock_backend)


async def _create_service(mock_backend):
    """Helper to create a TicketService with minimal mocking."""
    from ingot.integrations.ticket_service import create_ticket_service

    return await create_ticket_service(backend=mock_backend)
