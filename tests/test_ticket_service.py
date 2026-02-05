"""Tests for TicketService orchestration layer."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec.integrations.cache import CacheKey, InMemoryTicketCache
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
)
from spec.integrations.providers.base import (
    GenericTicket,
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.ticket_service import (
    TicketService,
    create_ticket_service,
)


@pytest.fixture
def sample_ticket():
    """Create a sample GenericTicket for testing."""
    return GenericTicket(
        id="PROJ-123",
        platform=Platform.JIRA,
        url="https://company.atlassian.net/browse/PROJ-123",
        title="Test Ticket",
        description="Test description",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.FEATURE,
        assignee="Test User",
        labels=["test", "feature"],
        created_at=None,
        updated_at=None,
        branch_summary="test-ticket",
        platform_metadata={},
    )


@pytest.fixture
def sample_raw_data():
    """Raw data returned by fetchers."""
    return {
        "key": "PROJ-123",
        "fields": {
            "summary": "Test Ticket",
            "description": "Test description",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "assignee": {"displayName": "Test User"},
            "labels": ["test", "feature"],
        },
    }


@pytest.fixture
def mock_primary_fetcher():
    """Mock primary fetcher (AuggieMediatedFetcher-like)."""
    fetcher = MagicMock()
    fetcher.name = "MockPrimaryFetcher"
    fetcher.supports_platform.return_value = True
    fetcher.fetch = AsyncMock(return_value={"key": "PROJ-123", "summary": "Test Ticket"})
    return fetcher


@pytest.fixture
def mock_fallback_fetcher():
    """Mock fallback fetcher (DirectAPIFetcher-like)."""
    fetcher = MagicMock()
    fetcher.name = "MockFallbackFetcher"
    fetcher.supports_platform.return_value = True
    fetcher.fetch = AsyncMock(
        return_value={"key": "PROJ-123", "summary": "Test Ticket from Fallback"}
    )
    fetcher.close = AsyncMock()
    return fetcher


@pytest.fixture
def mock_cache():
    """Mock cache."""
    cache = MagicMock()
    cache.get.return_value = None
    cache.set = MagicMock()
    cache.invalidate.return_value = True
    cache.clear.return_value = 5
    cache.clear_platform.return_value = 3
    return cache


@pytest.fixture
def mock_provider(sample_ticket):
    """Mock provider returned by ProviderRegistry."""
    provider = MagicMock()
    provider.platform = Platform.JIRA
    provider.parse_input.return_value = "PROJ-123"
    provider.normalize.return_value = sample_ticket
    return provider


class TestTicketServiceConstructor:
    """Test TicketService constructor."""

    def test_init_with_primary_only(self, mock_primary_fetcher):
        """Should initialize with primary fetcher only."""
        service = TicketService(primary_fetcher=mock_primary_fetcher)

        assert service.primary_fetcher_name == "MockPrimaryFetcher"
        assert service.fallback_fetcher_name is None
        assert service.has_cache is False

    def test_init_with_primary_and_fallback(self, mock_primary_fetcher, mock_fallback_fetcher):
        """Should initialize with both primary and fallback fetchers."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            fallback_fetcher=mock_fallback_fetcher,
        )

        assert service.primary_fetcher_name == "MockPrimaryFetcher"
        assert service.fallback_fetcher_name == "MockFallbackFetcher"

    def test_init_with_cache(self, mock_primary_fetcher, mock_cache):
        """Should initialize with cache."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )

        assert service.has_cache is True

    def test_init_with_custom_ttl(self, mock_primary_fetcher):
        """Should accept custom default TTL."""
        ttl = timedelta(hours=2)
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            default_ttl=ttl,
        )
        # TTL is stored internally
        assert service._default_ttl == ttl


class TestGetTicket:
    """Test get_ticket() orchestration method."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, mock_primary_fetcher, mock_provider, sample_ticket):
        """Should successfully fetch and return a ticket."""
        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(primary_fetcher=mock_primary_fetcher)
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_primary_fetcher.fetch.assert_called_once_with("PROJ-123", "jira")
            mock_provider.normalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_ticket(
        self, mock_primary_fetcher, mock_cache, mock_provider, sample_ticket
    ):
        """Should return cached ticket on cache hit."""
        mock_cache.get.return_value = sample_ticket

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                cache=mock_cache,
            )
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_cache.get.assert_called_once()
            mock_primary_fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_fetcher(
        self, mock_primary_fetcher, mock_cache, mock_provider, sample_ticket
    ):
        """Should fetch from fetcher on cache miss."""
        mock_cache.get.return_value = None

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                cache=mock_cache,
            )
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_cache.get.assert_called_once()
            mock_primary_fetcher.fetch.assert_called_once()
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_cache_bypasses_cache_lookup(
        self, mock_primary_fetcher, mock_cache, mock_provider, sample_ticket
    ):
        """Should skip cache lookup when skip_cache=True."""
        mock_cache.get.return_value = sample_ticket  # Would hit cache normally

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                cache=mock_cache,
            )
            ticket = await service.get_ticket("PROJ-123", skip_cache=True)

            assert ticket == sample_ticket
            mock_cache.get.assert_not_called()
            mock_primary_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_ttl_used_for_caching(
        self, mock_primary_fetcher, mock_cache, mock_provider, sample_ticket
    ):
        """Should use custom TTL when caching."""
        custom_ttl = timedelta(minutes=30)

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                cache=mock_cache,
            )
            await service.get_ticket("PROJ-123", ttl=custom_ttl)

            mock_cache.set.assert_called_once()
            call_args = mock_cache.set.call_args
            assert call_args.kwargs.get("ttl") == custom_ttl

    @pytest.mark.asyncio
    async def test_raises_error_when_closed(self, mock_primary_fetcher):
        """Should raise RuntimeError when service is closed."""
        service = TicketService(primary_fetcher=mock_primary_fetcher)
        await service.close()

        with pytest.raises(RuntimeError, match="has been closed"):
            await service.get_ticket("PROJ-123")


class TestFallbackBehavior:
    """Test fallback behavior on primary fetcher errors."""

    @pytest.mark.asyncio
    async def test_fallback_on_agent_integration_error(
        self, mock_primary_fetcher, mock_fallback_fetcher, mock_provider, sample_ticket
    ):
        """Should fallback to fallback fetcher on AgentIntegrationError."""
        mock_primary_fetcher.fetch = AsyncMock(
            side_effect=AgentIntegrationError("Connection failed")
        )

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                fallback_fetcher=mock_fallback_fetcher,
            )
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_primary_fetcher.fetch.assert_called_once()
            mock_fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_agent_fetch_error(
        self, mock_primary_fetcher, mock_fallback_fetcher, mock_provider, sample_ticket
    ):
        """Should fallback to fallback fetcher on AgentFetchError."""
        mock_primary_fetcher.fetch = AsyncMock(side_effect=AgentFetchError("Fetch failed"))

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                fallback_fetcher=mock_fallback_fetcher,
            )
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_agent_response_parse_error(
        self, mock_primary_fetcher, mock_fallback_fetcher, mock_provider, sample_ticket
    ):
        """Should fallback to fallback fetcher on AgentResponseParseError."""
        mock_primary_fetcher.fetch = AsyncMock(side_effect=AgentResponseParseError("Parse failed"))

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                fallback_fetcher=mock_fallback_fetcher,
            )
            ticket = await service.get_ticket("PROJ-123")

            assert ticket == sample_ticket
            mock_fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_propagation_when_no_fallback(self, mock_primary_fetcher, mock_provider):
        """Should propagate error when no fallback configured."""
        mock_primary_fetcher.fetch = AsyncMock(
            side_effect=AgentIntegrationError("Connection failed")
        )

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(primary_fetcher=mock_primary_fetcher)

            with pytest.raises(AgentIntegrationError):
                await service.get_ticket("PROJ-123")

    @pytest.mark.asyncio
    async def test_direct_api_only_platform_skips_primary(
        self, mock_primary_fetcher, mock_fallback_fetcher, mock_provider, sample_ticket
    ):
        """Should use fallback directly for platforms not supported by primary."""
        mock_primary_fetcher.supports_platform.return_value = False
        mock_provider.platform = Platform.AZURE_DEVOPS

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(
                primary_fetcher=mock_primary_fetcher,
                fallback_fetcher=mock_fallback_fetcher,
            )
            ticket = await service.get_ticket("https://dev.azure.com/org/proj/_workitems/edit/123")

            assert ticket == sample_ticket
            mock_primary_fetcher.fetch.assert_not_called()
            mock_fallback_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_platform_not_supported_error(self, mock_primary_fetcher, mock_provider):
        """Should raise PlatformNotSupportedError when no fetcher supports platform."""
        mock_primary_fetcher.supports_platform.return_value = False
        mock_provider.platform = Platform.AZURE_DEVOPS

        with patch(
            "spec.integrations.ticket_service.ProviderRegistry.get_provider_for_input",
            return_value=mock_provider,
        ):
            service = TicketService(primary_fetcher=mock_primary_fetcher)

            with pytest.raises(PlatformNotSupportedError):
                await service.get_ticket("https://dev.azure.com/org/proj/_workitems/edit/123")


class TestCacheManagement:
    """Test cache management methods."""

    def test_invalidate_cache(self, mock_primary_fetcher, mock_cache):
        """Should invalidate specific cached ticket."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )

        service.invalidate_cache(Platform.JIRA, "PROJ-123")

        mock_cache.invalidate.assert_called_once()
        call_args = mock_cache.invalidate.call_args[0][0]
        assert isinstance(call_args, CacheKey)
        assert call_args.platform == Platform.JIRA
        assert call_args.ticket_id == "PROJ-123"

    def test_invalidate_cache_no_cache(self, mock_primary_fetcher):
        """Should be no-op when no cache configured."""
        service = TicketService(primary_fetcher=mock_primary_fetcher)
        # Should not raise
        service.invalidate_cache(Platform.JIRA, "PROJ-123")

    def test_clear_cache_all(self, mock_primary_fetcher, mock_cache):
        """Should clear all cached tickets."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )

        service.clear_cache()

        mock_cache.clear.assert_called_once()
        mock_cache.clear_platform.assert_not_called()

    def test_clear_cache_by_platform(self, mock_primary_fetcher, mock_cache):
        """Should clear only tickets for specified platform."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )

        service.clear_cache(platform=Platform.LINEAR)

        mock_cache.clear_platform.assert_called_once_with(Platform.LINEAR)
        mock_cache.clear.assert_not_called()

    def test_clear_cache_no_cache(self, mock_primary_fetcher):
        """Should be no-op when no cache configured."""
        service = TicketService(primary_fetcher=mock_primary_fetcher)
        # Should not raise
        service.clear_cache()

    def test_has_cache_property(self, mock_primary_fetcher, mock_cache):
        """Should return correct has_cache value."""
        service_with = TicketService(
            primary_fetcher=mock_primary_fetcher,
            cache=mock_cache,
        )
        service_without = TicketService(primary_fetcher=mock_primary_fetcher)

        assert service_with.has_cache is True
        assert service_without.has_cache is False


class TestResourceManagement:
    """Test async resource management."""

    @pytest.mark.asyncio
    async def test_context_manager_closes_resources(
        self, mock_primary_fetcher, mock_fallback_fetcher
    ):
        """Should close resources when exiting context manager."""
        async with TicketService(
            primary_fetcher=mock_primary_fetcher,
            fallback_fetcher=mock_fallback_fetcher,
        ) as service:
            assert service.primary_fetcher_name == "MockPrimaryFetcher"

        mock_fallback_fetcher.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_close(self, mock_primary_fetcher, mock_fallback_fetcher):
        """Should close resources when close() called explicitly."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            fallback_fetcher=mock_fallback_fetcher,
        )

        await service.close()

        mock_fallback_fetcher.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, mock_primary_fetcher, mock_fallback_fetcher):
        """Should only close once even if called multiple times."""
        service = TicketService(
            primary_fetcher=mock_primary_fetcher,
            fallback_fetcher=mock_fallback_fetcher,
        )

        await service.close()
        await service.close()

        # Should only be called once
        assert mock_fallback_fetcher.close.call_count == 1

    @pytest.mark.asyncio
    async def test_close_without_fallback(self, mock_primary_fetcher):
        """Should close successfully without fallback fetcher."""
        service = TicketService(primary_fetcher=mock_primary_fetcher)
        # Should not raise
        await service.close()


class TestCreateTicketService:
    """Test create_ticket_service factory function."""

    @pytest.mark.asyncio
    async def test_create_with_auggie_client(self):
        """Should create service with AuggieMediatedFetcher as primary."""
        mock_auggie = MagicMock()
        mock_auth = MagicMock()

        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher"
        ) as mock_auggie_fetcher_class, patch(
            "spec.integrations.ticket_service.DirectAPIFetcher"
        ) as mock_direct_fetcher_class:
            mock_auggie_fetcher_class.return_value.name = "AuggieMediatedFetcher"
            mock_direct_fetcher_class.return_value.name = "DirectAPIFetcher"
            mock_direct_fetcher_class.return_value.close = AsyncMock()

            service = await create_ticket_service(
                backend=mock_auggie,
                auth_manager=mock_auth,
            )

            assert service.primary_fetcher_name == "AuggieMediatedFetcher"
            assert service.fallback_fetcher_name == "DirectAPIFetcher"
            assert service.has_cache is True

            await service.close()

    @pytest.mark.asyncio
    async def test_create_with_auth_manager_only(self):
        """Should use DirectAPIFetcher as primary when no backend."""
        mock_auth = MagicMock()

        with patch(
            "spec.integrations.ticket_service.DirectAPIFetcher"
        ) as mock_direct_fetcher_class:
            mock_direct_fetcher_class.return_value.name = "DirectAPIFetcher"
            mock_direct_fetcher_class.return_value.close = AsyncMock()

            service = await create_ticket_service(
                auth_manager=mock_auth,
            )

            assert service.primary_fetcher_name == "DirectAPIFetcher"
            assert service.fallback_fetcher_name is None
            assert service.has_cache is True

            await service.close()

    @pytest.mark.asyncio
    async def test_create_raises_without_any_client(self):
        """Should raise ValueError when no clients provided."""
        with pytest.raises(ValueError, match="no fetchers configured"):
            await create_ticket_service()

    @pytest.mark.asyncio
    async def test_create_with_custom_cache(self):
        """Should use provided custom cache."""
        mock_auth = MagicMock()
        custom_cache = InMemoryTicketCache(max_size=500)

        with patch(
            "spec.integrations.ticket_service.DirectAPIFetcher"
        ) as mock_direct_fetcher_class:
            mock_direct_fetcher_class.return_value.name = "DirectAPIFetcher"
            mock_direct_fetcher_class.return_value.close = AsyncMock()

            service = await create_ticket_service(
                auth_manager=mock_auth,
                cache=custom_cache,
            )

            assert service.has_cache is True
            assert service._cache is custom_cache

            await service.close()

    @pytest.mark.asyncio
    async def test_create_without_fallback(self):
        """Should disable fallback when enable_fallback=False."""
        mock_auggie = MagicMock()
        mock_auth = MagicMock()

        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher"
        ) as mock_auggie_fetcher_class:
            mock_auggie_fetcher_class.return_value.name = "AuggieMediatedFetcher"

            service = await create_ticket_service(
                backend=mock_auggie,
                auth_manager=mock_auth,
                enable_fallback=False,
            )

            assert service.primary_fetcher_name == "AuggieMediatedFetcher"
            assert service.fallback_fetcher_name is None

            await service.close()
