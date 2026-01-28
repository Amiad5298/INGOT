"""Integration tests for multi-platform CLI.

2-Layer Test Strategy:
- Layer A (CLI Contract): Mock at create_ticket_service_from_config factory
- Layer B (CLI→Service Integration): Mock only at fetcher class boundaries
  (AuggieMediatedFetcher / DirectAPIFetcher constructors)

All tests use runner.invoke(app, ...) to exercise the real CLI entry point.

This file implements AMI-40: Add End-to-End Integration Tests for Multi-Platform CLI.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from spec.cli import app
from spec.integrations.providers import Platform
from spec.utils.errors import ExitCode

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

        Typer raises BadParameter which results in exit code 2 (not ExitCode.GENERAL_ERROR).
        """
        result = runner.invoke(app, ["PROJ-123", "--platform", "invalid"])

        # Typer's BadParameter produces exit code 2
        assert result.exit_code != 0, f"Expected non-zero exit code, got {result.exit_code}"
        # Use result.output consistently (combines stdout/stderr)
        output = result.output
        assert "Invalid platform" in output
        # Should list valid options - check for all platforms
        for platform_name in ["jira", "linear", "github", "azure-devops", "monday", "trello"]:
            assert platform_name in output.lower()

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
        mock_config.settings.default_jira_project = ""
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
        mock_config.settings.default_jira_project = ""
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
        mock_config.settings.default_jira_project = ""
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
        mock_config.settings.default_jira_project = ""
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
        mock_config.settings.default_jira_project = ""
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

        This test:
        1. Invokes CLI with a platform-specific URL
        2. Lets REAL _run_workflow, _fetch_ticket_async, TicketService, and Provider code run
        3. Mocks only fetcher constructors to return mock instances with .fetch()
        4. Mocks run_spec_driven_workflow to prevent actual workflow execution
        5. Verifies the workflow receives correctly normalized GenericTicket
        """
        test_data = self.PLATFORM_TEST_DATA[platform]
        raw_data = request.getfixturevalue(test_data["raw_fixture"])

        mock_config_class.return_value = mock_config_for_cli

        # Create mock fetcher that returns raw data for this platform
        mock_fetcher = MagicMock()
        mock_fetcher.name = "MockAuggieFetcher"
        mock_fetcher.supports_platform.return_value = True
        mock_fetcher.fetch = AsyncMock(return_value=raw_data)
        mock_fetcher.close = AsyncMock()

        # Mock fetcher class constructors - this is the KEY Layer B approach
        # The real TicketService, create_ticket_service, ProviderRegistry all run
        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher",
            return_value=mock_fetcher,
        ), patch(
            "spec.integrations.ticket_service.DirectAPIFetcher",
            return_value=mock_fetcher,
        ):
            result = runner.invoke(app, [test_data["url"]])

        # Verify workflow runner was called with correct ticket
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        mock_workflow_runner.assert_called_once()

        # Verify the ticket passed to workflow has correct platform and title
        # run_spec_driven_workflow is called with ticket=generic_ticket (GenericTicket object)
        call_kwargs = mock_workflow_runner.call_args.kwargs
        ticket = call_kwargs.get("ticket")
        assert ticket is not None, "Workflow should receive a ticket"
        assert ticket.platform == platform, f"Expected {platform}, got {ticket.platform}"
        assert (
            ticket.title == test_data["expected_title"]
        ), f"Expected title '{test_data['expected_title']}', got '{ticket.title}'"


class TestFallbackBehaviorViaCLI:
    """Layer B: Test primary→fallback fetcher chain via CLI.

    These tests verify the REAL fallback mechanism in TicketService:
    - Primary fetcher (AuggieMediatedFetcher) fails with AgentIntegrationError
    - Fallback fetcher (DirectAPIFetcher) is invoked and succeeds
    - Both fetchers' fetch() methods are called in order
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

        This is a TRUE fallback test that:
        1. Mocks primary fetcher to raise AgentIntegrationError
        2. Mocks fallback fetcher to return valid data
        3. Asserts BOTH fetch() methods were called (primary first, then fallback)
        """
        from spec.integrations.fetchers.exceptions import AgentIntegrationError

        mock_config_class.return_value = mock_config_for_cli

        # Primary fetcher FAILS with AgentIntegrationError
        mock_primary = MagicMock()
        mock_primary.name = "AuggieMediatedFetcher"
        mock_primary.supports_platform.return_value = True
        mock_primary.fetch = AsyncMock(side_effect=AgentIntegrationError("Auggie unavailable"))
        mock_primary.close = AsyncMock()

        # Fallback fetcher SUCCEEDS
        mock_fallback = MagicMock()
        mock_fallback.name = "DirectAPIFetcher"
        mock_fallback.supports_platform.return_value = True
        mock_fallback.fetch = AsyncMock(return_value=mock_jira_raw_data)
        mock_fallback.close = AsyncMock()

        # Mock fetcher constructors to return our mock instances
        with patch(
            "spec.integrations.ticket_service.AuggieMediatedFetcher",
            return_value=mock_primary,
        ), patch(
            "spec.integrations.ticket_service.DirectAPIFetcher",
            return_value=mock_fallback,
        ):
            result = runner.invoke(app, ["https://company.atlassian.net/browse/PROJ-123"])

        # Key assertions: both fetchers were called in correct order
        mock_primary.fetch.assert_called_once()
        mock_fallback.fetch.assert_called_once()

        # Verify CLI succeeded (fallback worked)
        assert result.exit_code == 0, f"CLI should succeed after fallback: {result.output}"
        mock_workflow_runner.assert_called_once()

        # Verify ticket was correctly normalized from fallback data
        call_kwargs = mock_workflow_runner.call_args.kwargs
        ticket = call_kwargs.get("ticket")
        assert ticket is not None
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
        """When primary succeeds, fallback should NOT be called."""
        mock_config_class.return_value = mock_config_for_cli

        # Primary fetcher SUCCEEDS
        mock_primary = MagicMock()
        mock_primary.name = "AuggieMediatedFetcher"
        mock_primary.supports_platform.return_value = True
        mock_primary.fetch = AsyncMock(return_value=mock_jira_raw_data)
        mock_primary.close = AsyncMock()

        # Fallback fetcher (should NOT be called)
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
            result = runner.invoke(app, ["https://company.atlassian.net/browse/PROJ-123"])

        # Primary was called, fallback was NOT called
        mock_primary.fetch.assert_called_once()
        mock_fallback.fetch.assert_not_called()

        assert result.exit_code == 0


class TestErrorPropagationViaCLI:
    """Layer B: Test error propagation from service layer to CLI.

    These tests verify that errors from TicketService surface correctly
    at the CLI level with appropriate exit codes and user-friendly messages.

    Uses SPECIFIC assertions for exit codes and error message content.
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
        """TicketNotFoundError surfaces with ticket ID in error message."""
        from spec.integrations.providers.exceptions import TicketNotFoundError

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        # Create mock service that raises TicketNotFoundError
        async def mock_create_service(*args, **kwargs):
            mock_service = MagicMock()
            mock_service.get_ticket = AsyncMock(
                side_effect=TicketNotFoundError(ticket_id="NOTFOUND-999", platform="jira")
            )
            mock_service.close = AsyncMock()
            mock_service.__aenter__ = AsyncMock(return_value=mock_service)
            mock_service.__aexit__ = AsyncMock(return_value=None)
            return mock_service

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            result = runner.invoke(app, ["NOTFOUND-999", "--platform", "jira"])

        # Specific assertions
        assert (
            result.exit_code == ExitCode.GENERAL_ERROR
        ), f"Expected exit code {ExitCode.GENERAL_ERROR}, got {result.exit_code}"
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
        """AuthenticationError surfaces with auth-related message."""
        from spec.integrations.providers.exceptions import AuthenticationError

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config

        async def mock_create_service(*args, **kwargs):
            mock_service = MagicMock()
            mock_service.get_ticket = AsyncMock(
                side_effect=AuthenticationError("Invalid API token", platform="jira")
            )
            mock_service.close = AsyncMock()
            mock_service.__aenter__ = AsyncMock(return_value=mock_service)
            mock_service.__aexit__ = AsyncMock(return_value=None)
            return mock_service

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", "jira"])

        # Specific assertions
        assert result.exit_code == ExitCode.GENERAL_ERROR
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
        """Unconfigured platform error shows platform name and configuration hint."""
        from spec.integrations.fetchers.exceptions import (
            PlatformNotSupportedError as FetcherPlatformNotSupportedError,
        )

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
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
            mock_service.__aenter__ = AsyncMock(return_value=mock_service)
            mock_service.__aexit__ = AsyncMock(return_value=None)
            return mock_service

        with patch(
            "spec.cli.create_ticket_service_from_config",
            side_effect=mock_create_service,
        ):
            result = runner.invoke(app, ["TRL-123", "--platform", "trello"])

        # Specific assertions
        assert result.exit_code == ExitCode.GENERAL_ERROR
        output = result.output
        # Should mention the platform or configuration issue
        assert (
            "trello" in output.lower()
            or "not configured" in output.lower()
            or "not supported" in output.lower()
        ), f"Expected platform-related message in output: {output}"
