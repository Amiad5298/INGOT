"""Integration tests for multi-platform CLI.

2-Layer Test Strategy:
- Layer A (CLI Contract): Mock at create_ticket_service_from_config factory
- Layer B (CLI→Service Integration): Mock only at fetcher class boundaries
  (AuggieMediatedFetcher / DirectAPIFetcher constructors) and workflow runner

Mocking Boundaries:
- Layer A mocks create_ticket_service_from_config to test CLI behavior in isolation
- Layer B mocks:
  1. Fetcher constructors (AuggieMediatedFetcher, DirectAPIFetcher) - prevents external API calls
  2. run_spec_driven_workflow - prevents actual workflow execution
  3. Uses SEPARATE mock instances for primary/fallback fetchers to catch lifecycle bugs

All tests use runner.invoke(app, ...) to exercise the real CLI entry point.
Tests run in isolated_filesystem() for deterministic behavior.

This file implements AMI-40: Add End-to-End Integration Tests for Multi-Platform CLI.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from spec.cli import app
from spec.integrations.providers import Platform
from spec.utils.errors import ExitCode
from tests.helpers.async_cm import make_async_context_manager
from tests.helpers.workflow import get_ticket_from_workflow_call

# CLI integration fixtures are loaded via tests/cli/conftest.py

runner = CliRunner()


# =============================================================================
# LAYER A: CLI Contract Tests (Mock at create_ticket_service_from_config factory)
# =============================================================================


class TestPlatformFlagValidation:
    """Test --platform flag parsing and validation (Layer A: contract tests)."""

    def test_invalid_platform_shows_error(self):
        """Invalid --platform value produces clear error message.

        Note: This test doesn't need any mocks - validation fails before
        TicketService is called.

        Assertions are kept resilient to Click/Typer wording changes:
        - Exit code 2 (standard Typer/Click usage error, not ExitCode.AUGGIE_NOT_INSTALLED)
        - Output mentions "invalid" (case-insensitive)
        - Output mentions at least some valid platforms
        """
        # Typer/Click CLI usage error is conventionally exit code 2
        # Note: This is NOT the same as ExitCode.AUGGIE_NOT_INSTALLED (which is also 2)
        # We use a local constant to document this distinction
        TYPER_USAGE_ERROR = 2

        result = runner.invoke(app, ["PROJ-123", "--platform", "invalid"])

        assert (
            result.exit_code == TYPER_USAGE_ERROR
        ), f"Expected Typer usage error (exit code 2), got {result.exit_code}"

        output = result.output.lower()
        # Should indicate invalid value - accept multiple possible phrasings from Click/Typer
        # Common variations: "Invalid value", "invalid choice", "is not one of"
        invalid_indicators = ["invalid", "not one of", "not a valid"]
        assert any(
            indicator in output for indicator in invalid_indicators
        ), f"Expected error phrasing indicating invalid input. Got: {result.output}"
        # Should mention at least ONE valid platform (not specific ones to avoid brittleness)
        valid_platforms = ["jira", "linear", "github", "azure_devops", "monday", "trello"]
        assert any(
            p in output for p in valid_platforms
        ), f"Expected at least one valid platform mentioned in error. Got: {result.output}"

    @pytest.mark.parametrize(
        "platform_name,expected_platform",
        [
            ("jira", Platform.JIRA),
            ("linear", Platform.LINEAR),
            ("github", Platform.GITHUB),
            ("azure_devops", Platform.AZURE_DEVOPS),
            ("monday", Platform.MONDAY),
            ("trello", Platform.TRELLO),
        ],
    )
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_valid_platform_values(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        platform_name,
        expected_platform,
        mock_ticket_service_factory,
        mock_jira_ticket,
    ):
        """All 6 platform values are accepted by --platform flag."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        # Mock at create_ticket_service_from_config factory (Layer A approach)
        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket}),
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", platform_name])

        # Should not error on platform validation
        assert "Invalid platform" not in result.output

    @pytest.mark.parametrize("variant", ["JIRA", "Jira", "JiRa", "jira"])
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_platform_flag_case_insensitive(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        variant,
        mock_ticket_service_factory,
        mock_jira_ticket,
    ):
        """--platform flag is case-insensitive."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket}),
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", variant])

        assert "Invalid platform" not in result.output

    @pytest.mark.parametrize(
        "platform_name",
        ["jira", "linear", "github", "azure_devops", "monday", "trello"],
    )
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_short_flag_alias(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        platform_name,
        mock_ticket_service_factory,
        mock_jira_ticket,
    ):
        """-p shorthand works for all platform values."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"TEST-123": mock_jira_ticket}),
        ):
            result = runner.invoke(app, ["TEST-123", "-p", platform_name])

        assert "Invalid platform" not in result.output


class TestDisambiguationFlow:
    """Test disambiguation flow for ambiguous ticket IDs (Layer A)."""

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_disambiguation_prompts_user(self, mock_print, mock_prompt):
        """Disambiguation prompts user to choose platform for ambiguous IDs."""
        from spec.cli import _disambiguate_platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_prompt.return_value = "jira"

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.JIRA
        mock_prompt.assert_called_once()

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_default_platform_skips_prompt(self, mock_print, mock_prompt):
        """Default platform config skips user prompt for ambiguous IDs."""
        from spec.cli import _disambiguate_platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = Platform.LINEAR

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.LINEAR
        mock_prompt.assert_not_called()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    @patch("spec.ui.prompts.prompt_select")
    def test_ambiguous_id_triggers_disambiguation_via_cli(
        self,
        mock_prompt,
        mock_config_class,
        mock_prereq,
        mock_banner,
        mock_ticket_service_factory,
        mock_jira_ticket,
    ):
        """Ambiguous ticket ID triggers disambiguation when no default configured."""
        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config
        mock_prompt.return_value = "jira"

        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket}),
        ):
            _result = runner.invoke(app, ["PROJ-123"])

        # Prompt should have been called for disambiguation
        mock_prompt.assert_called_once()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    @patch("spec.ui.prompts.prompt_select")
    def test_flag_overrides_disambiguation(
        self,
        mock_prompt,
        mock_config_class,
        mock_prereq,
        mock_banner,
        mock_ticket_service_factory,
        mock_jira_ticket,
    ):
        """--platform flag bypasses disambiguation entirely."""
        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket}),
        ):
            _result = runner.invoke(app, ["PROJ-123", "--platform", "linear"])

        # Prompt should NOT be called since --platform was provided
        mock_prompt.assert_not_called()

    def test_github_format_no_disambiguation(self):
        """GitHub owner/repo#123 format is unambiguous - no disambiguation needed."""
        from spec.cli import _is_ambiguous_ticket_id

        # GitHub format should not be considered ambiguous
        assert _is_ambiguous_ticket_id("owner/repo#42") is False
        assert _is_ambiguous_ticket_id("my-org/my-repo#123") is False

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_config_default_platform_used(self, mock_print, mock_prompt):
        """Configured default_platform is used for ambiguous IDs without prompting."""
        from spec.cli import _disambiguate_platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = Platform.AZURE_DEVOPS

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.AZURE_DEVOPS
        mock_prompt.assert_not_called()


# =============================================================================
# LAYER B: CLI→Service Integration Tests (Mock at fetcher class boundaries)
#
# These tests exercise the REAL TicketService, ProviderRegistry, and Providers.
# Only the AuggieMediatedFetcher and DirectAPIFetcher constructors are mocked
# to return mock instances with stubbed .fetch() methods.
# =============================================================================


class TestCLIServiceIntegration:
    """Layer B: Full CLI→TicketService→Provider integration tests.

    These tests:
    1. Use runner.invoke(app, ...) to exercise the real CLI entry point
    2. Allow real TicketService and real Provider code to run
    3. Mock only fetcher CLASS constructors (not create_ticket_service_from_config)
    4. Verify the complete chain works with proper platform detection/normalization
    """

    # Mapping of platforms to their test URLs and raw data fixtures
    PLATFORM_TEST_DATA = {
        Platform.JIRA: {
            "url": "https://company.atlassian.net/browse/PROJ-123",
            "raw_fixture": "mock_jira_raw_data",
            "expected_title": "Test Jira Ticket",
        },
        Platform.LINEAR: {
            "url": "https://linear.app/team/issue/ENG-456",
            "raw_fixture": "mock_linear_raw_data",
            "expected_title": "Test Linear Issue",
        },
        Platform.GITHUB: {
            "url": "https://github.com/owner/repo/issues/42",
            "raw_fixture": "mock_github_raw_data",
            "expected_title": "Test GitHub Issue",
        },
        Platform.AZURE_DEVOPS: {
            "url": "https://dev.azure.com/org/project/_workitems/edit/789",
            "raw_fixture": "mock_azure_devops_raw_data",
            "expected_title": "Test ADO Work Item",
        },
        Platform.MONDAY: {
            "url": "https://myorg.monday.com/boards/987654321/pulses/123456789",
            "raw_fixture": "mock_monday_raw_data",
            "expected_title": "Test Monday Item",
        },
        Platform.TRELLO: {
            "url": "https://trello.com/c/abc123/test-card",
            "raw_fixture": "mock_trello_raw_data",
            "expected_title": "Test Trello Card",
        },
    }

    @pytest.mark.parametrize("platform", list(PLATFORM_TEST_DATA.keys()))
    @patch("spec.workflow.runner.run_spec_driven_workflow")  # Mock at workflow runner level
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_platform_via_cli_real_service(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        mock_workflow_runner,
        platform,
        mock_config_for_cli,
        request,
    ):
        """Layer B: All 6 platforms work through CLI→TicketService→Provider chain.

        Mocking boundaries:
        - Fetcher constructors: AuggieMediatedFetcher and DirectAPIFetcher (SEPARATE instances)
        - Workflow runner: run_spec_driven_workflow
        - ConfigManager, show_banner, _check_prerequisites (CLI infrastructure)

        What runs real:
        - CLI entry point, argument parsing
        - TicketService, ProviderRegistry, Provider normalization
        """
        test_data = self.PLATFORM_TEST_DATA[platform]
        raw_data = request.getfixturevalue(test_data["raw_fixture"])

        mock_config_class.return_value = mock_config_for_cli

        # Create SEPARATE mock fetchers for primary and fallback
        # This ensures we don't hide bugs where primary vs fallback are confused
        mock_primary_fetcher = MagicMock()
        mock_primary_fetcher.name = "MockAuggieFetcher"
        mock_primary_fetcher.supports_platform.return_value = True
        mock_primary_fetcher.fetch = AsyncMock(return_value=raw_data)
        mock_primary_fetcher.close = AsyncMock()

        mock_fallback_fetcher = MagicMock()
        mock_fallback_fetcher.name = "MockDirectAPIFetcher"
        mock_fallback_fetcher.supports_platform.return_value = True
        mock_fallback_fetcher.fetch = AsyncMock(return_value=raw_data)
        mock_fallback_fetcher.close = AsyncMock()

        # Mock fetcher class constructors with DISTINCT instances
        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher",
            return_value=mock_primary_fetcher,
        ), patch(
            "spec.integrations.ticket_service.DirectAPIFetcher",
            return_value=mock_fallback_fetcher,
        ):
            # Use isolated_filesystem to prevent filesystem I/O flakiness
            with runner.isolated_filesystem():
                result = runner.invoke(app, [test_data["url"]])

        # Verify workflow runner was called with correct ticket
        assert (
            result.exit_code == ExitCode.SUCCESS.value
        ), f"CLI failed with exit code {result.exit_code}: {result.output}"
        mock_workflow_runner.assert_called_once()

        # Verify primary fetcher was used and fallback was NOT used (primary succeeded)
        mock_primary_fetcher.fetch.assert_called_once()
        mock_fallback_fetcher.fetch.assert_not_called()

        # Use robust ticket extraction (handles positional and keyword args)
        ticket = get_ticket_from_workflow_call(mock_workflow_runner)
        assert ticket is not None, "Workflow should receive a ticket"
        assert hasattr(ticket, "platform"), "Ticket should have platform attribute"
        assert hasattr(ticket, "title"), "Ticket should have title attribute"
        assert ticket.platform == platform, f"Expected {platform}, got {ticket.platform}"
        assert (
            ticket.title == test_data["expected_title"]
        ), f"Expected title '{test_data['expected_title']}', got '{ticket.title}'"


class TestFallbackBehaviorViaCLI:
    """Layer B: Test primary→fallback fetcher chain via CLI.

    Mocking boundaries:
    - Fetcher constructors: AuggieMediatedFetcher and DirectAPIFetcher (SEPARATE instances)
    - Workflow runner: run_spec_driven_workflow
    - ConfigManager, show_banner, _check_prerequisites (CLI infrastructure)

    What runs real:
    - CLI entry point, TicketService fallback logic, Provider normalization

    These tests verify the REAL fallback mechanism in TicketService:
    - Primary fetcher (AuggieMediatedFetcher) fails with AgentIntegrationError
    - Fallback fetcher (DirectAPIFetcher) is invoked and succeeds
    - SEPARATE mock instances verify call order and prevent lifecycle confusion
    """

    @patch("spec.workflow.runner.run_spec_driven_workflow")  # Mock at workflow runner level
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_fallback_on_primary_failure(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        mock_workflow_runner,
        mock_jira_raw_data,
        mock_config_for_cli,
    ):
        """Primary fetcher failure triggers fallback - both fetchers called.

        Mocking boundaries:
        - Primary fetcher: raises AgentIntegrationError
        - Fallback fetcher: returns valid raw data
        - Workflow runner: mocked to verify ticket passed correctly
        """
        from spec.integrations.fetchers.exceptions import AgentIntegrationError

        mock_config_class.return_value = mock_config_for_cli

        # Create a parent mock to track call order across fetchers
        call_order_tracker = MagicMock()

        # Primary fetcher FAILS with AgentIntegrationError
        mock_primary = MagicMock()
        mock_primary.name = "AuggieMediatedFetcher"
        mock_primary.supports_platform.return_value = True
        mock_primary.close = AsyncMock()

        async def primary_fetch_side_effect(*args, **kwargs):
            call_order_tracker.primary_fetch()
            raise AgentIntegrationError("Auggie unavailable")

        mock_primary.fetch = AsyncMock(side_effect=primary_fetch_side_effect)

        # Fallback fetcher SUCCEEDS - DISTINCT mock instance
        mock_fallback = MagicMock()
        mock_fallback.name = "DirectAPIFetcher"
        mock_fallback.supports_platform.return_value = True
        mock_fallback.close = AsyncMock()

        async def fallback_fetch_side_effect(*args, **kwargs):
            call_order_tracker.fallback_fetch()
            return mock_jira_raw_data

        mock_fallback.fetch = AsyncMock(side_effect=fallback_fetch_side_effect)

        # Mock fetcher constructors to return SEPARATE mock instances
        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher",
            return_value=mock_primary,
        ), patch(
            "spec.integrations.ticket_service.DirectAPIFetcher",
            return_value=mock_fallback,
        ):
            with runner.isolated_filesystem():
                result = runner.invoke(app, ["https://company.atlassian.net/browse/PROJ-123"])

        # Key assertions: both fetchers were called
        mock_primary.fetch.assert_called_once()
        mock_fallback.fetch.assert_called_once()

        # Verify call order: primary was attempted BEFORE fallback
        # Extract method names from call order tracker
        call_names = [call[0] for call in call_order_tracker.method_calls]
        assert (
            "primary_fetch" in call_names
        ), f"Expected primary_fetch to be called, got: {call_names}"
        assert (
            "fallback_fetch" in call_names
        ), f"Expected fallback_fetch to be called, got: {call_names}"
        primary_idx = call_names.index("primary_fetch")
        fallback_idx = call_names.index("fallback_fetch")
        assert primary_idx < fallback_idx, (
            f"Expected primary_fetch (index {primary_idx}) before fallback_fetch "
            f"(index {fallback_idx}), call order: {call_names}"
        )

        # Verify CLI succeeded (fallback worked)
        assert (
            result.exit_code == ExitCode.SUCCESS.value
        ), f"CLI should succeed after fallback: {result.output}"
        mock_workflow_runner.assert_called_once()

        # Use robust ticket extraction (handles positional and keyword args)
        ticket = get_ticket_from_workflow_call(mock_workflow_runner)
        assert ticket is not None, "Workflow should receive a ticket from fallback"
        assert ticket.platform == Platform.JIRA
        assert ticket.title == "Test Jira Ticket"

    @patch("spec.workflow.runner.run_spec_driven_workflow")  # Mock at workflow runner level
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_primary_success_skips_fallback(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
        mock_workflow_runner,
        mock_jira_raw_data,
        mock_config_for_cli,
    ):
        """When primary succeeds, fallback should NOT be called.

        Mocking boundaries:
        - Primary fetcher: returns valid raw data (success case)
        - Fallback fetcher: should NOT be invoked
        """
        mock_config_class.return_value = mock_config_for_cli

        # Primary fetcher SUCCEEDS
        mock_primary = MagicMock()
        mock_primary.name = "AuggieMediatedFetcher"
        mock_primary.supports_platform.return_value = True
        mock_primary.fetch = AsyncMock(return_value=mock_jira_raw_data)
        mock_primary.close = AsyncMock()

        # Fallback fetcher - DISTINCT instance, should NOT be called
        mock_fallback = MagicMock()
        mock_fallback.name = "DirectAPIFetcher"
        mock_fallback.supports_platform.return_value = True
        mock_fallback.fetch = AsyncMock(return_value=mock_jira_raw_data)
        mock_fallback.close = AsyncMock()

        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher",
            return_value=mock_primary,
        ), patch(
            "spec.integrations.ticket_service.DirectAPIFetcher",
            return_value=mock_fallback,
        ):
            with runner.isolated_filesystem():
                result = runner.invoke(app, ["https://company.atlassian.net/browse/PROJ-123"])

        # Primary was called, fallback was NOT called
        mock_primary.fetch.assert_called_once()
        mock_fallback.fetch.assert_not_called()

        assert result.exit_code == ExitCode.SUCCESS.value


class TestCLIErrorContract:
    """Layer A: CLI error contract tests - verify error→exit code mapping.

    Mocking boundaries:
    - create_ticket_service_from_config: returns mock service that raises errors
    - ConfigManager, show_banner, _check_prerequisites (CLI infrastructure)

    What runs real:
    - CLI entry point, error handling, exit code mapping

    Exit code assertions use ExitCode.X.value for explicit int comparison.
    """

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_ticket_not_found_via_cli(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
    ):
        """TicketNotFoundError surfaces with ticket ID in error message.

        Mocking: create_ticket_service_from_config raises TicketNotFoundError
        """
        from spec.integrations.providers.exceptions import TicketNotFoundError

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        # Create mock service that raises TicketNotFoundError
        async def mock_create_service(*args, **kwargs):
            mock_service = MagicMock()
            mock_service.get_ticket = AsyncMock(
                side_effect=TicketNotFoundError(ticket_id="NOTFOUND-999", platform="jira")
            )
            mock_service.close = AsyncMock()
            return make_async_context_manager(mock_service)

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            with runner.isolated_filesystem():
                result = runner.invoke(app, ["NOTFOUND-999", "--platform", "jira"])

        # Compare against ExitCode.X.value for explicit int comparison
        assert (
            result.exit_code == ExitCode.GENERAL_ERROR.value
        ), f"Expected exit code {ExitCode.GENERAL_ERROR.value}, got {result.exit_code}"
        output = result.output
        # Should mention the ticket ID and indicate it wasn't found
        assert (
            "NOTFOUND-999" in output or "not found" in output.lower()
        ), f"Expected 'NOTFOUND-999' or 'not found' in output: {output}"

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_auth_error_via_cli(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
    ):
        """AuthenticationError surfaces with auth-related message.

        Mocking: create_ticket_service_from_config raises AuthenticationError
        """
        from spec.integrations.providers.exceptions import AuthenticationError

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        async def mock_create_service(*args, **kwargs):
            mock_service = MagicMock()
            mock_service.get_ticket = AsyncMock(
                side_effect=AuthenticationError("Invalid API token", platform="jira")
            )
            mock_service.close = AsyncMock()
            return make_async_context_manager(mock_service)

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            with runner.isolated_filesystem():
                result = runner.invoke(app, ["PROJ-123", "--platform", "jira"])

        # Compare against ExitCode.X.value for explicit int comparison
        assert result.exit_code == ExitCode.GENERAL_ERROR.value
        output = result.output
        # Should indicate authentication issue
        assert (
            "auth" in output.lower() or "token" in output.lower() or "jira" in output.lower()
        ), f"Expected auth-related message in output: {output}"

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_unconfigured_platform_error_via_cli(
        self,
        mock_config_class,
        mock_prereq,
        mock_banner,
    ):
        """Unconfigured platform error shows platform name and configuration hint.

        Mocking: create_ticket_service_from_config raises PlatformNotSupportedError
        """
        from spec.integrations.fetchers.exceptions import (
            PlatformNotSupportedError as FetcherPlatformNotSupportedError,
        )

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        async def mock_create_service(*args, **kwargs):
            mock_service = MagicMock()
            mock_service.get_ticket = AsyncMock(
                side_effect=FetcherPlatformNotSupportedError(
                    platform="trello",
                    fetcher_name="direct_api",
                    message="Trello is not configured",
                )
            )
            mock_service.close = AsyncMock()
            return make_async_context_manager(mock_service)

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            with runner.isolated_filesystem():
                result = runner.invoke(app, ["TRL-123", "--platform", "trello"])

        # Compare against ExitCode.X.value for explicit int comparison
        assert result.exit_code == ExitCode.GENERAL_ERROR.value
        output = result.output
        # Should mention the platform or configuration issue
        assert (
            "trello" in output.lower()
            or "not configured" in output.lower()
            or "not supported" in output.lower()
        ), f"Expected platform-related message in output: {output}"
