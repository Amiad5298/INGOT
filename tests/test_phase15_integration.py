"""Phase 1.5 Integration Tests for Fetcher Refactoring.

This module tests the complete Phase 1.5 fetcher refactoring (AMI-56 through AMI-58)
working together as an integrated system.

Test Categories:
1. Import Chain Validation - No circular dependencies in Phase 1.5 modules
2. Factory Flow - resolve_backend_platform() → BackendFactory.create() → create_ticket_service()
3. Error Propagation - Errors flow correctly through the Phase 1.5 stack
4. Regression Checks - Phase 1 and baseline behaviors preserved

These tests follow the pattern established by tests/test_phase1_integration.py.
"""

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
)
from ingot.utils.errors import IngotError


class TestPhase15ImportChain:
    def test_create_ticket_service_from_config_importable(self):
        from ingot.cli import create_ticket_service_from_config

        assert create_ticket_service_from_config is not None
        assert callable(create_ticket_service_from_config)

    def test_all_phase15_modules_import_without_circular_deps(self):
        # Order: errors → base → factory → resolver → fetcher → ticket_service → cli
        from ingot.cli import create_ticket_service_from_config
        from ingot.config.backend_resolver import resolve_backend_platform
        from ingot.integrations.backends.base import AIBackend
        from ingot.integrations.backends.errors import BackendNotConfiguredError
        from ingot.integrations.backends.factory import BackendFactory
        from ingot.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
        from ingot.integrations.ticket_service import create_ticket_service

        assert all(
            [
                BackendNotConfiguredError,
                AIBackend,
                BackendFactory,
                resolve_backend_platform,
                AuggieMediatedFetcher,
                create_ticket_service,
                create_ticket_service_from_config,
            ]
        )

    def test_backend_errors_importable(self):
        from ingot.integrations.backends.errors import (
            BackendNotConfiguredError,
            BackendNotInstalledError,
            BackendRateLimitError,
            BackendTimeoutError,
        )

        assert all(
            [
                BackendNotConfiguredError,
                BackendNotInstalledError,
                BackendRateLimitError,
                BackendTimeoutError,
            ]
        )

    def test_ticket_service_factory_importable(self):
        from ingot.integrations.ticket_service import create_ticket_service

        assert create_ticket_service is not None
        assert callable(create_ticket_service)

    def test_auggie_fetcher_importable(self):
        from ingot.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher

        assert AuggieMediatedFetcher is not None


class TestPhase15FactoryFlow:
    @pytest.mark.asyncio
    async def test_full_resolution_to_service_creation_flow(self):
        from ingot.config.backend_resolver import resolve_backend_platform
        from ingot.integrations.backends.factory import BackendFactory

        # Step 1: Resolve platform from config
        mock_config = MagicMock()
        mock_config.get.return_value = "auggie"

        platform = resolve_backend_platform(mock_config)
        assert platform == AgentPlatform.AUGGIE

        # Step 2: Create backend
        backend = BackendFactory.create(platform)
        assert backend.platform == AgentPlatform.AUGGIE

        # Step 3: Create ticket service with patched fetcher constructors
        mock_auth = MagicMock()
        mock_fetcher = MagicMock()
        mock_fetcher.name = "AuggieMediatedFetcher"

        with (
            patch(
                "ingot.integrations.ticket_service.AuggieMediatedFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "ingot.integrations.ticket_service.DirectAPIFetcher",
                return_value=MagicMock(name="DirectAPIFetcher"),
            ),
        ):
            from ingot.integrations.ticket_service import create_ticket_service

            service = await create_ticket_service(
                backend=backend,
                auth_manager=mock_auth,
                config_manager=mock_config,
            )

            assert service is not None

    def test_full_flow_no_backend_raises_not_configured(self):
        from ingot.config.backend_resolver import resolve_backend_platform

        mock_config = MagicMock()
        mock_config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(mock_config, cli_backend_override=None)

    @pytest.mark.asyncio
    async def test_create_ticket_service_from_config_wires_dependencies(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = AgentPlatform.AUGGIE
        mock_backend = MagicMock()
        mock_backend.platform = AgentPlatform.AUGGIE
        mock_service = MagicMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform",
                return_value=mock_platform,
            ) as mock_resolve,
            patch(
                "ingot.integrations.backends.factory.BackendFactory",
            ) as mock_factory_class,
            patch(
                "ingot.cli.ticket.AuthenticationManager",
                return_value=MagicMock(),
            ) as mock_auth_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ) as mock_create_svc,
        ):
            mock_factory_class.create.return_value = mock_backend

            service, backend = await create_ticket_service_from_config(
                config_manager=mock_config,
            )

            # Resolver called with config and no override
            mock_resolve.assert_called_once_with(mock_config, None)
            # Factory called with resolved platform
            mock_factory_class.create.assert_called_once_with(mock_platform, verify_installed=True)
            # AuthenticationManager created from config
            mock_auth_class.assert_called_once_with(mock_config)
            # create_ticket_service called with all wired deps
            mock_create_svc.assert_called_once()
            call_kwargs = mock_create_svc.call_args[1]
            assert call_kwargs["backend"] is mock_backend
            assert call_kwargs["config_manager"] is mock_config


class TestPhase15ErrorPropagation:
    def test_backend_not_configured_is_spec_error(self):
        error = BackendNotConfiguredError("No backend configured")
        assert isinstance(error, IngotError)
        assert isinstance(error, Exception)

    def test_backend_not_installed_is_spec_error(self):
        error = BackendNotInstalledError("CLI not installed")
        assert isinstance(error, IngotError)
        assert isinstance(error, Exception)

    @pytest.mark.asyncio
    async def test_error_propagates_unchanged_through_factory_function(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        original_error = BackendNotConfiguredError("No AI backend configured. Run 'spec init'.")

        with patch(
            "ingot.config.backend_resolver.resolve_backend_platform",
            side_effect=original_error,
        ):
            with pytest.raises(BackendNotConfiguredError) as exc_info:
                await create_ticket_service_from_config(config_manager=mock_config)

            # The exact same error instance propagates (not wrapped)
            assert exc_info.value is original_error


class TestPhase15RegressionChecks:
    def test_phase1_imports_still_work(self):
        from ingot.config.backend_resolver import resolve_backend_platform
        from ingot.integrations.backends.auggie import AuggieBackend
        from ingot.integrations.backends.base import AIBackend, BaseBackend
        from ingot.integrations.backends.errors import (
            BackendNotConfiguredError,
            BackendNotInstalledError,
            BackendRateLimitError,
            BackendTimeoutError,
        )
        from ingot.integrations.backends.factory import BackendFactory

        assert all(
            [
                BackendNotConfiguredError,
                BackendNotInstalledError,
                BackendRateLimitError,
                BackendTimeoutError,
                AIBackend,
                BaseBackend,
                AuggieBackend,
                BackendFactory,
                resolve_backend_platform,
            ]
        )

    def test_create_ticket_service_signature_has_backend_param(self):
        from ingot.integrations.ticket_service import create_ticket_service

        sig = inspect.signature(create_ticket_service)
        param_names = list(sig.parameters.keys())

        assert (
            "backend" in param_names
        ), f"create_ticket_service missing 'backend' parameter. Found: {param_names}"

    def test_auggie_fetcher_signature_has_backend_param(self):
        from ingot.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher

        sig = inspect.signature(AuggieMediatedFetcher.__init__)
        param_names = list(sig.parameters.keys())

        assert (
            "backend" in param_names
        ), f"AuggieMediatedFetcher.__init__ missing 'backend' parameter. Found: {param_names}"

    def test_baseline_auggie_behavior_compatible(self):
        from ingot.integrations.auggie import AuggieClient

        assert AuggieClient is not None
        # AuggieClient should still be a class
        assert inspect.isclass(AuggieClient)


# Integration tests requiring real CLI
integration_tests_enabled = os.environ.get("INGOT_INTEGRATION_TESTS") == "1"


@pytest.mark.skipif(
    not integration_tests_enabled,
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestPhase15IntegrationWithRealCLI:
    @pytest.mark.asyncio
    async def test_create_ticket_service_from_config_with_real_backend(self):
        from ingot.cli import create_ticket_service_from_config
        from ingot.config.manager import ConfigManager

        config = ConfigManager()

        try:
            service, backend = await create_ticket_service_from_config(
                config_manager=config,
            )
            # If we get here, the backend is configured and installed
            assert service is not None
            assert backend is not None
            assert hasattr(backend, "platform")
        except BackendNotConfiguredError:
            pytest.skip("No AI backend configured in environment")
        except BackendNotInstalledError:
            pytest.skip("AI backend CLI not installed in environment")
