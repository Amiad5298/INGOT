"""Tests for ingot.integrations.fetchers.direct_api_fetcher module.

Tests cover:
- DirectAPIFetcher initialization
- Platform support checking via AuthenticationManager
- fetch() and fetch_raw() methods
- Retry logic with exponential backoff
- Platform resolution from string
- Error handling and exception mapping
- Timeout functionality
"""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ingot.config.fetch_config import FetchPerformanceConfig
from ingot.config.manager import ConfigManager
from ingot.integrations.auth import AuthenticationManager, PlatformCredentials
from ingot.integrations.fetchers import (
    AgentFetchError,
    AgentIntegrationError,
    DirectAPIFetcher,
)
from ingot.integrations.fetchers.exceptions import PlatformApiError
from ingot.integrations.providers.base import Platform


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager."""
    config = MagicMock(spec=ConfigManager)
    config.get_fetch_performance_config.return_value = FetchPerformanceConfig(
        timeout_seconds=30.0,
        max_retries=3,
        retry_delay_seconds=1.0,
    )
    return config


@pytest.fixture
def mock_auth_manager():
    """Create a mock AuthenticationManager."""
    auth = MagicMock(spec=AuthenticationManager)
    auth.has_fallback_configured.return_value = True
    auth.get_credentials.return_value = PlatformCredentials(
        platform=Platform.JIRA,
        is_configured=True,
        credentials=MappingProxyType(
            {
                "url": "https://company.atlassian.net",
                "email": "user@example.com",
                "token": "test-token",
            }
        ),
    )
    return auth


@pytest.fixture
def mock_auth_manager_no_creds():
    """Create a mock AuthenticationManager with no credentials."""
    auth = MagicMock(spec=AuthenticationManager)
    auth.has_fallback_configured.return_value = False
    auth.get_credentials.return_value = PlatformCredentials(
        platform=Platform.JIRA,
        is_configured=False,
        credentials=MappingProxyType({}),
        error_message="No fallback credentials configured for jira",
    )
    return auth


@pytest.fixture
def fetcher(mock_auth_manager, mock_config_manager):
    """Create a DirectAPIFetcher with mocked dependencies."""
    return DirectAPIFetcher(mock_auth_manager, mock_config_manager)


class TestDirectAPIFetcherInit:
    def test_init_with_auth_manager(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)

        assert fetcher._auth is mock_auth_manager

    def test_init_with_config_manager(self, mock_auth_manager, mock_config_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, mock_config_manager)

        assert fetcher._config is mock_config_manager
        mock_config_manager.get_fetch_performance_config.assert_called_once()

    def test_init_with_timeout_override(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, timeout_seconds=60.0)

        assert fetcher._timeout_seconds == 60.0

    def test_init_uses_default_performance_config(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)

        assert fetcher._performance is not None
        assert isinstance(fetcher._performance, FetchPerformanceConfig)

    def test_name_property(self, fetcher):
        assert fetcher.name == "Direct API Fetcher"


class TestDirectAPIFetcherSupport:
    def test_supports_platform_when_configured(self, mock_auth_manager):
        # mock_auth_manager already returns has_fallback_configured=True by default
        fetcher = DirectAPIFetcher(mock_auth_manager)

        assert fetcher.supports_platform(Platform.JIRA) is True
        mock_auth_manager.has_fallback_configured.assert_called_with(Platform.JIRA)

    def test_supports_platform_when_not_configured(self, mock_auth_manager_no_creds):
        # mock_auth_manager_no_creds returns has_fallback_configured=False
        fetcher = DirectAPIFetcher(mock_auth_manager_no_creds)

        assert fetcher.supports_platform(Platform.GITHUB) is False

    def test_supports_platform_checks_all_platforms(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)

        for platform in Platform:
            fetcher.supports_platform(platform)

        assert mock_auth_manager.has_fallback_configured.call_count == len(Platform)


class TestDirectAPIFetcherPlatformResolution:
    def test_resolve_platform_lowercase(self, fetcher):
        assert fetcher._resolve_platform("jira") == Platform.JIRA
        assert fetcher._resolve_platform("github") == Platform.GITHUB
        assert fetcher._resolve_platform("linear") == Platform.LINEAR

    def test_resolve_platform_uppercase(self, fetcher):
        assert fetcher._resolve_platform("JIRA") == Platform.JIRA
        assert fetcher._resolve_platform("GITHUB") == Platform.GITHUB

    def test_resolve_platform_mixed_case(self, fetcher):
        assert fetcher._resolve_platform("Jira") == Platform.JIRA
        assert fetcher._resolve_platform("GitHub") == Platform.GITHUB

    def test_resolve_platform_invalid(self, fetcher):
        with pytest.raises(AgentIntegrationError) as exc_info:
            fetcher._resolve_platform("invalid_platform")

        assert "Unknown platform" in str(exc_info.value)

    def test_resolve_platform_azure_devops(self, fetcher):
        assert fetcher._resolve_platform("azure_devops") == Platform.AZURE_DEVOPS
        assert fetcher._resolve_platform("AZURE_DEVOPS") == Platform.AZURE_DEVOPS


class TestDirectAPIFetcherHandlers:
    """Tests for _get_platform_handler method.

    Note: _get_platform_handler is async for concurrency-safe lazy initialization.
    """

    async def test_get_handler_jira(self, fetcher):
        from ingot.integrations.fetchers.handlers import JiraHandler

        handler = await fetcher._get_platform_handler(Platform.JIRA)
        assert isinstance(handler, JiraHandler)

    async def test_get_handler_linear(self, fetcher):
        from ingot.integrations.fetchers.handlers import LinearHandler

        handler = await fetcher._get_platform_handler(Platform.LINEAR)
        assert isinstance(handler, LinearHandler)

    async def test_get_handler_github(self, fetcher):
        from ingot.integrations.fetchers.handlers import GitHubHandler

        handler = await fetcher._get_platform_handler(Platform.GITHUB)
        assert isinstance(handler, GitHubHandler)

    async def test_get_handler_azure_devops(self, fetcher):
        from ingot.integrations.fetchers.handlers import AzureDevOpsHandler

        handler = await fetcher._get_platform_handler(Platform.AZURE_DEVOPS)
        assert isinstance(handler, AzureDevOpsHandler)

    async def test_get_handler_trello(self, fetcher):
        from ingot.integrations.fetchers.handlers import TrelloHandler

        handler = await fetcher._get_platform_handler(Platform.TRELLO)
        assert isinstance(handler, TrelloHandler)

    async def test_get_handler_monday(self, fetcher):
        from ingot.integrations.fetchers.handlers import MondayHandler

        handler = await fetcher._get_platform_handler(Platform.MONDAY)
        assert isinstance(handler, MondayHandler)

    async def test_handlers_are_cached(self, fetcher):
        handler1 = await fetcher._get_platform_handler(Platform.JIRA)
        handler2 = await fetcher._get_platform_handler(Platform.JIRA)

        assert handler1 is handler2


class TestDirectAPIFetcherFetch:
    @pytest.mark.asyncio
    async def test_fetch_with_string_platform(self, mock_auth_manager, mock_config_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, mock_config_manager)

        with patch.object(fetcher, "fetch_raw", new_callable=AsyncMock) as mock_fetch_raw:
            mock_fetch_raw.return_value = {"key": "PROJ-123"}

            result = await fetcher.fetch("PROJ-123", "jira")

            assert result == {"key": "PROJ-123"}
            mock_fetch_raw.assert_called_once_with("PROJ-123", Platform.JIRA, None)

    @pytest.mark.asyncio
    async def test_fetch_with_timeout(self, mock_auth_manager, mock_config_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, mock_config_manager)

        with patch.object(fetcher, "fetch_raw", new_callable=AsyncMock) as mock_fetch_raw:
            mock_fetch_raw.return_value = {"key": "PROJ-123"}

            await fetcher.fetch("PROJ-123", "jira", timeout_seconds=10.0)

            mock_fetch_raw.assert_called_once_with("PROJ-123", Platform.JIRA, 10.0)

    @pytest.mark.asyncio
    async def test_fetch_invalid_platform_raises_error(self, fetcher):
        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch("PROJ-123", "invalid")

        assert "Unknown platform" in str(exc_info.value)


class TestDirectAPIFetcherFetchRaw:
    @pytest.mark.asyncio
    async def test_fetch_raw_no_credentials_raises_error(
        self, mock_auth_manager_no_creds, mock_config_manager
    ):
        fetcher = DirectAPIFetcher(mock_auth_manager_no_creds, mock_config_manager)

        with pytest.raises(AgentIntegrationError) as exc_info:
            await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

        assert "No fallback credentials configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_raw_success(self, mock_auth_manager, mock_config_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, mock_config_manager)

        with patch.object(fetcher, "_fetch_with_retry", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"key": "PROJ-123", "summary": "Test"}

            result = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)

            assert result == {"key": "PROJ-123", "summary": "Test"}

    @pytest.mark.asyncio
    async def test_fetch_raw_uses_timeout_override(self, mock_auth_manager, mock_config_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager, mock_config_manager, timeout_seconds=30.0)

        with patch.object(fetcher, "_fetch_with_retry", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = {"key": "PROJ-123"}

            await fetcher.fetch_raw("PROJ-123", Platform.JIRA, timeout_seconds=10.0)

            # Check that timeout_seconds=10.0 was passed
            call_args = mock_retry.call_args
            assert call_args[1]["timeout_seconds"] == 10.0


class TestDirectAPIFetcherRetry:
    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)
        fetcher._performance = FetchPerformanceConfig(max_retries=2, retry_delay_seconds=0.01)

        mock_handler = MagicMock()
        mock_handler.fetch = AsyncMock(
            side_effect=[
                httpx.TimeoutException("timeout"),
                {"key": "PROJ-123"},
            ]
        )

        result = await fetcher._fetch_with_retry(
            handler=mock_handler,
            ticket_id="PROJ-123",
            credentials={"token": "test"},
            timeout_seconds=5.0,
        )

        assert result == {"key": "PROJ-123"}
        assert mock_handler.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_4xx_error(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)
        fetcher._performance = FetchPerformanceConfig(max_retries=3, retry_delay_seconds=0.01)

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_handler = MagicMock()
        mock_handler.fetch = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=mock_response
            )
        )

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._fetch_with_retry(
                handler=mock_handler,
                ticket_id="PROJ-123",
                credentials={"token": "test"},
                timeout_seconds=5.0,
            )

        assert "404" in str(exc_info.value)
        assert mock_handler.fetch.call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_retry_on_5xx_error(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)
        fetcher._performance = FetchPerformanceConfig(max_retries=2, retry_delay_seconds=0.01)

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        mock_handler = MagicMock()
        mock_handler.fetch = AsyncMock(
            side_effect=[
                httpx.HTTPStatusError(
                    "Service Unavailable", request=MagicMock(), response=mock_response
                ),
                {"key": "PROJ-123"},
            ]
        )

        result = await fetcher._fetch_with_retry(
            handler=mock_handler,
            ticket_id="PROJ-123",
            credentials={"token": "test"},
            timeout_seconds=5.0,
        )

        assert result == {"key": "PROJ-123"}
        assert mock_handler.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_platform_api_error(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)
        fetcher._performance = FetchPerformanceConfig(max_retries=3, retry_delay_seconds=0.01)

        mock_handler = MagicMock()
        mock_handler.platform_name = "Linear"
        mock_handler.fetch = AsyncMock(
            side_effect=PlatformApiError(
                platform_name="Linear",
                error_details="GraphQL errors",
                ticket_id="PROJ-123",
            )
        )

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._fetch_with_retry(
                handler=mock_handler,
                ticket_id="PROJ-123",
                credentials={"token": "test"},
                timeout_seconds=5.0,
            )

        assert "GraphQL errors" in str(exc_info.value)
        assert mock_handler.fetch.call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_exhausts_retries(self, mock_auth_manager):
        fetcher = DirectAPIFetcher(mock_auth_manager)
        fetcher._performance = FetchPerformanceConfig(max_retries=2, retry_delay_seconds=0.01)

        mock_handler = MagicMock()
        mock_handler.fetch = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(AgentFetchError) as exc_info:
            await fetcher._fetch_with_retry(
                handler=mock_handler,
                ticket_id="PROJ-123",
                credentials={"token": "test"},
                timeout_seconds=5.0,
            )

        assert "after 3 attempts" in str(exc_info.value)
        assert mock_handler.fetch.call_count == 3  # 1 initial + 2 retries
