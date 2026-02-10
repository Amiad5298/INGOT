"""Phase 1 Integration Tests for Backend Infrastructure.

This module tests the complete Phase 1 backend infrastructure (AMI-47 through AMI-53)
working together as an integrated system.

Test Categories:
1. Import Chain Validation - No circular dependencies
2. Factory → Resolver Integration - resolve_backend_platform() → BackendFactory.create()
3. Error Propagation - Errors flow correctly through the stack
4. "No Default Backend" Policy - Enforced at all entry points
5. Regression Validation - Baseline tests still pass

These tests are gated behind INGOT_INTEGRATION_TESTS=1 for real CLI execution.
"""

import os
from typing import get_args, get_origin, get_type_hints
from unittest.mock import MagicMock

import pytest

from ingot.config.backend_resolver import resolve_backend_platform
from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)
from ingot.integrations.backends.factory import BackendFactory
from ingot.workflow.constants import (
    DEFAULT_EXECUTION_TIMEOUT,
    FIRST_RUN_TIMEOUT,
    INGOT_AGENT_DOC_UPDATER,
    INGOT_AGENT_IMPLEMENTER,
    INGOT_AGENT_PLANNER,
    INGOT_AGENT_REVIEWER,
    INGOT_AGENT_TASKLIST,
    INGOT_AGENT_TASKLIST_REFINER,
    ONBOARDING_SMOKE_TEST_TIMEOUT,
)


class TestPhase1ImportChain:
    def test_errors_import_standalone(self):
        from ingot.integrations.backends.errors import (
            BackendNotConfiguredError,
        )

        assert BackendNotConfiguredError is not None

    def test_base_imports_after_errors(self):
        from ingot.integrations.backends.base import BaseBackend

        assert BaseBackend is not None

    def test_auggie_imports_after_base(self):
        from ingot.integrations.backends.auggie import AuggieBackend

        assert AuggieBackend is not None

    def test_factory_imports_after_auggie(self):
        from ingot.integrations.backends.factory import BackendFactory

        assert BackendFactory is not None

    def test_resolver_imports_after_factory(self):
        from ingot.config.backend_resolver import resolve_backend_platform

        assert resolve_backend_platform is not None

    def test_package_init_exports_all(self):
        from ingot.integrations.backends import (
            AIBackend,
            AuggieBackend,
            BackendFactory,
            BackendNotConfiguredError,
            BackendNotInstalledError,
            BackendRateLimitError,
            BackendTimeoutError,
            BaseBackend,
            SubagentMetadata,
        )

        assert all(
            [
                AIBackend,
                AuggieBackend,
                BackendFactory,
                BackendNotConfiguredError,
                BackendNotInstalledError,
                BackendRateLimitError,
                BackendTimeoutError,
                BaseBackend,
                SubagentMetadata,
            ]
        )

    def test_auggie_backend_extends_base_backend(self):
        from ingot.integrations.backends.auggie import AuggieBackend
        from ingot.integrations.backends.base import BaseBackend

        assert issubclass(AuggieBackend, BaseBackend)


class TestFactoryResolverIntegration:
    def test_resolver_output_accepted_by_factory(self):
        config = MagicMock()
        config.get.return_value = "auggie"

        platform = resolve_backend_platform(config)
        backend = BackendFactory.create(platform)

        assert backend.platform == AgentPlatform.AUGGIE
        assert isinstance(backend, AIBackend)

    def test_cli_override_flows_through_to_factory(self):
        config = MagicMock()
        config.get.return_value = ""  # No config

        # CLI says auggie
        platform = resolve_backend_platform(config, cli_backend_override="auggie")
        backend = BackendFactory.create(platform)

        assert backend.platform == AgentPlatform.AUGGIE

    def test_backend_not_configured_prevents_factory_call(self):
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(config, cli_backend_override=None)
        # Factory.create() is never called


class TestNoDefaultBackendPolicy:
    """Verify 'no default backend' policy is enforced at the resolver level.

    Note: The policy is enforced by resolve_backend_platform(), NOT by BackendFactory.
    BackendFactory.create("") defaults to AUGGIE via parse_ai_backend().
    The resolver prevents reaching the factory without explicit configuration.
    """

    def test_resolver_raises_when_no_backend(self):
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            resolve_backend_platform(config, cli_backend_override=None)

        # Error message guides user to spec init
        assert "ingot init" in str(exc_info.value)

    def test_factory_defaults_to_auggie_for_empty_string(self):
        backend = BackendFactory.create("")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_error_message_is_actionable(self):
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            resolve_backend_platform(config)

        error_msg = str(exc_info.value)
        # Should mention BOTH spec init AND --backend flag for complete guidance
        assert "ingot init" in error_msg, "Error should mention 'spec init' command"
        assert "--backend" in error_msg, "Error should mention '--backend' flag option"


class TestErrorPropagation:
    def test_backend_not_configured_from_resolver(self):
        config = MagicMock()
        config.get.return_value = ""

        try:
            resolve_backend_platform(config)
            raise AssertionError("Should have raised BackendNotConfiguredError")
        except BackendNotConfiguredError as e:
            assert isinstance(e, Exception)
            # Verify it's a IngotError subclass
            from ingot.utils.errors import IngotError

            assert isinstance(e, IngotError)

    def test_backend_not_installed_from_factory(self, mocker):
        # Mock the underlying check_auggie_installed function
        # IMPORTANT: Patch in the backends.auggie module where it's imported
        mocker.patch(
            "ingot.integrations.backends.auggie.check_auggie_installed",
            return_value=(False, "Auggie CLI not found"),
        )

        try:
            BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
            raise AssertionError("Should have raised BackendNotInstalledError")
        except BackendNotInstalledError as e:
            # BackendNotInstalledError takes a single message parameter
            assert "auggie" in str(e).lower() or "not installed" in str(e).lower()

    def test_backend_rate_limit_has_required_attributes(self):
        error = BackendRateLimitError(
            "Rate limit hit",
            output="429 Too Many Requests",
            backend_name="Auggie",
        )
        assert error.output == "429 Too Many Requests"
        assert error.backend_name == "Auggie"

    def test_backend_timeout_has_timeout_seconds_attribute(self):
        error = BackendTimeoutError(
            "Execution timed out",
            timeout_seconds=300.0,
        )
        assert error.timeout_seconds == 300.0

    def test_all_errors_extend_spec_error(self):
        from ingot.utils.errors import IngotError

        # Note: BackendNotInstalledError takes a single message parameter
        errors = [
            BackendNotConfiguredError("No backend configured"),
            BackendNotInstalledError("Auggie CLI is not installed"),
            BackendRateLimitError("Rate limit exceeded"),
            BackendTimeoutError("Execution timed out"),
        ]
        for error in errors:
            assert isinstance(error, IngotError), f"{type(error)} should extend IngotError"


class TestSubagentConstantsAccessibility:
    def test_all_subagent_constants_importable(self):
        assert INGOT_AGENT_PLANNER is not None
        assert INGOT_AGENT_TASKLIST is not None
        assert INGOT_AGENT_TASKLIST_REFINER is not None
        assert INGOT_AGENT_IMPLEMENTER is not None
        assert INGOT_AGENT_REVIEWER is not None
        assert INGOT_AGENT_DOC_UPDATER is not None

    def test_all_timeout_constants_importable(self):
        assert DEFAULT_EXECUTION_TIMEOUT is not None
        assert FIRST_RUN_TIMEOUT is not None
        assert ONBOARDING_SMOKE_TEST_TIMEOUT is not None

    def test_subagent_constants_are_strings(self):
        assert isinstance(INGOT_AGENT_PLANNER, str)
        assert isinstance(INGOT_AGENT_TASKLIST, str)
        assert isinstance(INGOT_AGENT_IMPLEMENTER, str)

    def test_timeout_constants_are_numeric(self):
        assert isinstance(DEFAULT_EXECUTION_TIMEOUT, int | float)
        assert isinstance(FIRST_RUN_TIMEOUT, int | float)
        assert isinstance(ONBOARDING_SMOKE_TEST_TIMEOUT, int | float)


class TestBaselineRegressionChecks:
    def test_auggie_backend_run_with_callback_signature_matches_baseline(self):
        import inspect

        from ingot.integrations.auggie import AuggieClient
        from ingot.integrations.backends.auggie import AuggieBackend

        backend_sig = inspect.signature(AuggieBackend.run_with_callback)
        client_sig = inspect.signature(AuggieClient.run_with_callback)

        # Parameter names should match (excluding self)
        backend_params = list(backend_sig.parameters.keys())[1:]  # Skip self
        client_params = list(client_sig.parameters.keys())[1:]  # Skip self

        # Known allowed differences between Backend and Client:
        # - 'subagent' (backend) vs 'agent' (client) - naming convention
        # - 'timeout_seconds' - added at Backend layer per spec Final Decision #18
        allowed_backend_additions = {"timeout_seconds"}

        # Normalize known renames: backend uses 'subagent', client uses 'agent'
        def normalize_param(name: str) -> str:
            return "agent" if name == "subagent" else name

        # Filter out allowed backend additions for comparison
        backend_params_for_comparison = [
            p for p in backend_params if p not in allowed_backend_additions
        ]

        normalized_backend = [normalize_param(p) for p in backend_params_for_comparison]
        normalized_client = [normalize_param(p) for p in client_params]

        # Compare parameter counts (excluding allowed additions)
        assert len(normalized_backend) == len(normalized_client), (
            f"Parameter count mismatch: backend has {len(normalized_backend)} params "
            f"({backend_params_for_comparison}), client has {len(normalized_client)} params "
            f"({client_params}). Allowed additions: {allowed_backend_additions}"
        )

        # Compare parameter names (order matters for positional args)
        for i, (bp, cp) in enumerate(zip(normalized_backend, normalized_client, strict=False)):
            assert bp == cp, (
                f"Parameter mismatch at position {i}: backend has "
                f"'{backend_params_for_comparison[i]}', client has '{client_params[i]}' "
                f"(after normalization: '{bp}' vs '{cp}')"
            )

        # Verify core parameters exist (sanity check)
        assert "prompt" in backend_params, "Backend missing 'prompt' parameter"
        assert "output_callback" in backend_params, "Backend missing 'output_callback' parameter"

        # Verify the allowed addition is actually present (documents the intentional difference)
        assert (
            "timeout_seconds" in backend_params
        ), "Backend should have 'timeout_seconds' parameter per spec Final Decision #18"

    def test_auggie_backend_run_print_with_output_return_type(self):
        from ingot.integrations.backends.auggie import AuggieBackend

        backend = AuggieBackend()
        # Method exists and is callable
        assert callable(backend.run_print_with_output)
        # Return type should be tuple[bool, str]
        # Use get_origin/get_args for robust cross-version type hint checking
        hints = get_type_hints(backend.run_print_with_output)
        return_type = hints.get("return")
        assert get_origin(return_type) is tuple, "Return type should be a tuple"
        args = get_args(return_type)
        assert len(args) == 2, "Tuple should have 2 elements"
        assert args[0] is bool, "First element should be bool"
        assert args[1] is str, "Second element should be str"

    def test_auggie_backend_rate_limit_detection_matches_baseline(self):
        # Import the actual rate limit detection function used by AuggieBackend
        from ingot.integrations.auggie import looks_like_rate_limit

        # Test known rate limit patterns - these MUST be detected as rate limits
        positive_samples = [
            "Error: Rate limit exceeded",
            "rate limited",
            "too many requests",
            "429",
            "quota exceeded",
        ]
        for output in positive_samples:
            result = looks_like_rate_limit(output)
            assert result is True, f"Rate limit pattern not detected: '{output}' returned {result}"

        # Test negative samples - these should NOT be detected as rate limits
        negative_samples = [
            "Success: Task completed",
            "Hello world",
            "Error: File not found",
            "Connection established",
        ]
        for output in negative_samples:
            result = looks_like_rate_limit(output)
            assert (
                result is False
            ), f"False positive rate limit detection: '{output}' returned {result}"

    def test_subagent_names_match_baseline(self):
        # These values should not change during refactoring
        assert "planner" in INGOT_AGENT_PLANNER.lower()
        assert "tasklist" in INGOT_AGENT_TASKLIST.lower()
        assert "refiner" in INGOT_AGENT_TASKLIST_REFINER.lower()
        assert "implementer" in INGOT_AGENT_IMPLEMENTER.lower()
        assert "review" in INGOT_AGENT_REVIEWER.lower()
        assert "doc" in INGOT_AGENT_DOC_UPDATER.lower()


# Integration tests requiring real CLI
integration_tests_enabled = os.environ.get("INGOT_INTEGRATION_TESTS") == "1"


@pytest.mark.skipif(
    not integration_tests_enabled,
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestPhase1IntegrationWithRealCLI:
    def test_auggie_check_installed_returns_correct_types(self):
        from ingot.integrations.backends.auggie import AuggieBackend

        backend = AuggieBackend()
        installed, message = backend.check_installed()

        # Verify return types
        assert isinstance(installed, bool), "First return value should be bool"
        assert isinstance(message, str), "Second return value should be str"

        if installed:
            # On success, message is empty string (not version info)
            # This matches the actual check_auggie_installed() contract
            assert message == "", "Message should be empty on success"
        else:
            # Not installed - message contains error info
            assert message, "Message should be non-empty on failure"

    def test_factory_create_with_verify_installed(self):
        try:
            backend = BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
            # CLI is installed
            assert backend is not None
        except BackendNotInstalledError as e:
            # CLI is not installed - error message is helpful
            assert "auggie" in str(e).lower()

    def test_full_resolution_and_creation_flow(self):
        config = MagicMock()
        config.get.return_value = "auggie"

        # Resolve platform
        platform = resolve_backend_platform(config)
        assert platform == AgentPlatform.AUGGIE

        # Create backend
        backend = BackendFactory.create(platform)
        assert isinstance(backend, AIBackend)

        # Backend is usable
        assert callable(backend.run_print_quiet)
        assert callable(backend.check_installed)

    def test_run_print_quiet_executes_successfully(self):
        from ingot.integrations.backends.auggie import AuggieBackend

        backend = AuggieBackend()
        installed, _ = backend.check_installed()
        if not installed:
            pytest.skip("Auggie CLI not installed")

        # Execute a minimal prompt
        # Note: run_print_quiet returns str, NOT (bool, str)
        output = backend.run_print_quiet("Say 'hello world'")

        # Verify return type semantics
        assert isinstance(output, str), "Return value should be str"
        # Note: We don't assert output is non-empty because the prompt may fail
        # for various reasons (rate limits, network, etc.) - we just verify
        # the method executes and returns the correct type.
