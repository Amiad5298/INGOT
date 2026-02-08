"""Tests for the onboarding infrastructure (spec.onboarding)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spec.config.fetch_config import AgentPlatform
from spec.onboarding import OnboardingResult, is_first_run
from spec.onboarding.flow import OnboardingFlow
from spec.utils.errors import SpecError, UserCancelledError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(ai_backend: str = "", platform_enum: AgentPlatform | None = None) -> MagicMock:
    """Create a mock ConfigManager with the given AI_BACKEND value."""
    config = MagicMock()
    config.get.side_effect = lambda key, default="": (
        ai_backend if key == "AI_BACKEND" else default
    )
    agent_config = MagicMock()
    agent_config.platform = platform_enum
    config.get_agent_config.return_value = agent_config
    return config


# ---------------------------------------------------------------------------
# is_first_run
# ---------------------------------------------------------------------------


class TestIsFirstRun:
    def test_no_config(self):
        config = _make_config("")
        assert is_first_run(config) is True

    def test_with_config(self):
        config = _make_config("auggie")
        assert is_first_run(config) is False

    def test_whitespace_config(self):
        config = _make_config("   ")
        assert is_first_run(config) is True

    def test_agent_config_platform_set(self):
        """Existing agent_config.platform means no onboarding needed."""
        config = _make_config("", platform_enum=AgentPlatform.AUGGIE)
        assert is_first_run(config) is False

    def test_agent_config_platform_none_and_no_backend(self):
        """No agent_config.platform and no AI_BACKEND means first run."""
        config = _make_config("", platform_enum=None)
        assert is_first_run(config) is True

    def test_get_agent_config_returns_none(self):
        """is_first_run handles get_agent_config() returning None."""
        config = _make_config("")
        config.get_agent_config.return_value = None
        assert is_first_run(config) is True

    def test_get_agent_config_returns_none_with_backend_set(self):
        """is_first_run returns False when AI_BACKEND is set even if agent_config is None."""
        config = _make_config("auggie")
        config.get_agent_config.return_value = None
        assert is_first_run(config) is False


# ---------------------------------------------------------------------------
# OnboardingFlow._select_backend
# ---------------------------------------------------------------------------


class TestSelectBackend:
    @patch("spec.onboarding.flow.prompt_select")
    def test_select_auggie(self, mock_select):
        mock_select.return_value = "Auggie (Augment Code CLI)"
        flow = OnboardingFlow(_make_config())
        assert flow._select_backend() == AgentPlatform.AUGGIE

    @patch("spec.onboarding.flow.prompt_select")
    def test_select_claude(self, mock_select):
        mock_select.return_value = "Claude Code CLI"
        flow = OnboardingFlow(_make_config())
        assert flow._select_backend() == AgentPlatform.CLAUDE

    @patch("spec.onboarding.flow.prompt_select")
    def test_select_cursor(self, mock_select):
        mock_select.return_value = "Cursor"
        flow = OnboardingFlow(_make_config())
        assert flow._select_backend() == AgentPlatform.CURSOR


# ---------------------------------------------------------------------------
# OnboardingFlow._verify_installation
# ---------------------------------------------------------------------------


class TestVerifyInstallation:
    @patch("spec.onboarding.flow.print_success")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_installed_success(self, mock_factory, mock_print_success):
        backend_instance = MagicMock()
        backend_instance.check_installed.return_value = (True, "Auggie v1.2.3 found")
        mock_factory.create.return_value = backend_instance

        flow = OnboardingFlow(_make_config())
        assert flow._verify_installation(AgentPlatform.AUGGIE) == AgentPlatform.AUGGIE
        mock_print_success.assert_called_once()

    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.prompt_confirm")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_not_installed_shows_instructions(
        self, mock_factory, mock_confirm, mock_error, mock_info
    ):
        backend_instance = MagicMock()
        backend_instance.check_installed.return_value = (False, "CLI not found")
        mock_factory.create.return_value = backend_instance
        # User declines retry and declines switch
        mock_confirm.side_effect = [False, False]

        flow = OnboardingFlow(_make_config())
        assert flow._verify_installation(AgentPlatform.AUGGIE) is None
        # Should have shown installation instructions
        mock_info.assert_called()

    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.print_success")
    @patch("spec.onboarding.flow.prompt_confirm")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_retry_succeeds(
        self, mock_factory, mock_confirm, mock_print_success, mock_error, mock_info
    ):
        backend_instance = MagicMock()
        # First check fails, second succeeds
        backend_instance.check_installed.side_effect = [
            (False, "CLI not found"),
            (True, "CLI v1.0 found"),
        ]
        mock_factory.create.return_value = backend_instance
        # User says yes to retry
        mock_confirm.return_value = True

        flow = OnboardingFlow(_make_config())
        assert flow._verify_installation(AgentPlatform.AUGGIE) == AgentPlatform.AUGGIE

    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.print_success")
    @patch("spec.onboarding.flow.prompt_confirm")
    @patch("spec.onboarding.flow.prompt_select")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_switch_backend(
        self,
        mock_factory,
        mock_select,
        mock_confirm,
        mock_print_success,
        mock_error,
        mock_info,
    ):
        auggie_instance = MagicMock()
        auggie_instance.check_installed.return_value = (False, "Auggie not found")

        claude_instance = MagicMock()
        claude_instance.check_installed.return_value = (True, "Claude v1.0 found")

        mock_factory.create.side_effect = [auggie_instance, claude_instance]
        # First: decline retry, accept switch
        mock_confirm.side_effect = [False, True]
        # When asked to pick a different backend, choose Claude
        mock_select.return_value = "Claude Code CLI"

        flow = OnboardingFlow(_make_config())
        # Returns the switched-to backend, not the original
        assert flow._verify_installation(AgentPlatform.AUGGIE) == AgentPlatform.CLAUDE

    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_factory_not_implemented_error(self, mock_factory, mock_error):
        """BackendFactory.create raising NotImplementedError returns None."""
        mock_factory.create.side_effect = NotImplementedError("Backend not implemented")

        flow = OnboardingFlow(_make_config())
        assert flow._verify_installation(AgentPlatform.AUGGIE) is None
        mock_error.assert_called_once()

    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.prompt_confirm")
    @patch("spec.onboarding.flow.BackendFactory")
    def test_user_cancelled_during_retry_prompt(
        self, mock_factory, mock_confirm, mock_error, mock_info
    ):
        """UserCancelledError during prompt_confirm in verify loop propagates."""
        backend_instance = MagicMock()
        backend_instance.check_installed.return_value = (False, "CLI not found")
        mock_factory.create.return_value = backend_instance
        mock_confirm.side_effect = UserCancelledError("Ctrl+C")

        flow = OnboardingFlow(_make_config())
        with pytest.raises(UserCancelledError):
            flow._verify_installation(AgentPlatform.AUGGIE)


# ---------------------------------------------------------------------------
# OnboardingFlow._save_configuration
# ---------------------------------------------------------------------------


class TestSaveConfiguration:
    @patch("spec.onboarding.flow.print_success")
    def test_save_calls_config_save(self, mock_print_success):
        config = _make_config()
        # After save + reload, get should return the saved value
        config.get.side_effect = lambda key, default="": (
            "claude" if key == "AI_BACKEND" else default
        )

        flow = OnboardingFlow(config)
        flow._save_configuration(AgentPlatform.CLAUDE)

        config.save.assert_called_once_with("AI_BACKEND", "claude")
        config.load.assert_called_once()

    @patch("spec.onboarding.flow.print_success")
    def test_readback_verification(self, mock_print_success):
        config = _make_config()
        # Simulate readback returning the correct value
        config.get.side_effect = lambda key, default="": (
            "auggie" if key == "AI_BACKEND" else default
        )

        flow = OnboardingFlow(config)
        flow._save_configuration(AgentPlatform.AUGGIE)

        config.load.assert_called_once()

    def test_readback_mismatch_raises(self):
        config = _make_config()
        # Simulate readback returning wrong value
        config.get.side_effect = lambda key, default="": (
            "wrong_value" if key == "AI_BACKEND" else default
        )

        flow = OnboardingFlow(config)
        with pytest.raises(SpecError, match="readback mismatch"):
            flow._save_configuration(AgentPlatform.CLAUDE)


# ---------------------------------------------------------------------------
# Full flow
# ---------------------------------------------------------------------------


class TestFullFlow:
    @patch("spec.onboarding.flow.print_success")
    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_header")
    @patch("spec.onboarding.flow.BackendFactory")
    @patch("spec.onboarding.flow.prompt_select")
    def test_full_flow_success(
        self,
        mock_select,
        mock_factory,
        mock_header,
        mock_info,
        mock_print_success,
    ):
        mock_select.return_value = "Auggie (Augment Code CLI)"

        backend_instance = MagicMock()
        backend_instance.check_installed.return_value = (True, "Auggie v1.0")
        mock_factory.create.return_value = backend_instance

        config = _make_config()
        config.get.side_effect = lambda key, default="": (
            "auggie" if key == "AI_BACKEND" else default
        )

        flow = OnboardingFlow(config)
        result = flow.run()

        assert result.success is True
        assert result.backend == AgentPlatform.AUGGIE
        config.save.assert_called_once_with("AI_BACKEND", "auggie")

    @patch("spec.onboarding.flow.print_success")
    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_error")
    @patch("spec.onboarding.flow.print_header")
    @patch("spec.onboarding.flow.BackendFactory")
    @patch("spec.onboarding.flow.prompt_confirm")
    @patch("spec.onboarding.flow.prompt_select")
    def test_full_flow_backend_switch_saves_correct_backend(
        self,
        mock_select,
        mock_confirm,
        mock_factory,
        mock_header,
        mock_error,
        mock_info,
        mock_print_success,
    ):
        """When user switches backends during verification, the switched-to backend is saved."""
        # First select Auggie, then when verification fails, switch to Claude
        mock_select.side_effect = ["Auggie (Augment Code CLI)", "Claude Code CLI"]

        auggie_instance = MagicMock()
        auggie_instance.check_installed.return_value = (False, "Auggie not found")
        claude_instance = MagicMock()
        claude_instance.check_installed.return_value = (True, "Claude v1.0 found")
        mock_factory.create.side_effect = [auggie_instance, claude_instance]

        # Decline retry, accept switch
        mock_confirm.side_effect = [False, True]

        config = _make_config()
        config.get.side_effect = lambda key, default="": (
            "claude" if key == "AI_BACKEND" else default
        )

        flow = OnboardingFlow(config)
        result = flow.run()

        assert result.success is True
        assert result.backend == AgentPlatform.CLAUDE
        config.save.assert_called_once_with("AI_BACKEND", "claude")

    @patch("spec.onboarding.flow.print_info")
    @patch("spec.onboarding.flow.print_header")
    @patch("spec.onboarding.flow.prompt_select")
    def test_full_flow_user_cancelled(self, mock_select, mock_header, mock_info):
        mock_select.side_effect = UserCancelledError("cancelled")

        flow = OnboardingFlow(_make_config())
        result = flow.run()

        assert result.success is False
        assert "cancelled" in result.error_message.lower()

    def test_subsequent_run_skips_onboarding(self):
        config = _make_config("auggie")
        assert is_first_run(config) is False


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    @patch("spec.cli.run_onboarding")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.is_git_repo")
    def test_check_prerequisites_triggers_onboarding(self, mock_git, mock_first_run, mock_onboard):
        from spec.cli import _check_prerequisites

        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = OnboardingResult(success=True, backend=AgentPlatform.CLAUDE)

        config = _make_config()
        assert _check_prerequisites(config, force_integration_check=False) is True
        mock_onboard.assert_called_once_with(config)

    @patch("spec.cli.run_onboarding")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.is_git_repo")
    def test_check_prerequisites_onboarding_failure(self, mock_git, mock_first_run, mock_onboard):
        from spec.cli import _check_prerequisites

        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = OnboardingResult(success=False, error_message="User cancelled")

        config = _make_config()
        assert _check_prerequisites(config, force_integration_check=False) is False

    @patch("spec.cli.is_first_run")
    @patch("spec.cli.is_git_repo")
    def test_check_prerequisites_skips_onboarding_when_configured(self, mock_git, mock_first_run):
        from spec.cli import _check_prerequisites

        mock_git.return_value = True
        mock_first_run.return_value = False

        config = _make_config("auggie")
        assert _check_prerequisites(config, force_integration_check=False) is True


# ---------------------------------------------------------------------------
# Compatibility matrix
# ---------------------------------------------------------------------------


class TestCompatibilityMatrix:
    def test_mcp_support_covers_all_backends(self):
        """Every AgentPlatform member has an entry in MCP_SUPPORT."""
        from spec.config.compatibility import MCP_SUPPORT

        for member in AgentPlatform:
            assert member in MCP_SUPPORT, f"MCP_SUPPORT missing entry for {member}"

    def test_get_platform_support_mcp(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers.base import Platform

        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.JIRA)
        assert supported is True
        assert mechanism == "mcp"

    def test_get_platform_support_api_fallback(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers.base import Platform

        supported, mechanism = get_platform_support(AgentPlatform.MANUAL, Platform.JIRA)
        assert supported is True
        assert mechanism == "api"

    def test_get_platform_support_aider_no_mcp(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers.base import Platform

        supported, mechanism = get_platform_support(AgentPlatform.AIDER, Platform.GITHUB)
        assert supported is True
        assert mechanism == "api"


# ---------------------------------------------------------------------------
# _fetch_ticket_with_onboarding
# ---------------------------------------------------------------------------


class TestFetchTicketWithOnboarding:
    @patch("spec.cli.run_async")
    def test_success_no_onboarding(self, mock_run_async):
        from spec.cli import _fetch_ticket_with_onboarding

        mock_ticket = MagicMock()
        mock_backend = MagicMock()
        mock_run_async.return_value = (mock_ticket, mock_backend)
        config = _make_config("auggie")

        result = _fetch_ticket_with_onboarding("TICKET-1", config, None, None)
        assert result == (mock_ticket, mock_backend)

    @patch("spec.cli.run_async")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.run_onboarding")
    def test_onboarding_then_retry_succeeds(self, mock_onboard, mock_first_run, mock_run_async):
        from spec.cli import _fetch_ticket_with_onboarding
        from spec.integrations.backends.errors import BackendNotConfiguredError

        mock_ticket = MagicMock()
        mock_backend = MagicMock()
        # First call raises BackendNotConfiguredError, second succeeds
        mock_run_async.side_effect = [
            BackendNotConfiguredError("No backend"),
            (mock_ticket, mock_backend),
        ]
        mock_first_run.return_value = True
        mock_onboard.return_value = OnboardingResult(success=True, backend=AgentPlatform.AUGGIE)
        config = _make_config()

        result = _fetch_ticket_with_onboarding("TICKET-1", config, None, None)
        assert result == (mock_ticket, mock_backend)
        mock_onboard.assert_called_once()

    @patch("spec.cli.run_async")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.run_onboarding")
    def test_onboarding_cancelled_exits(self, mock_onboard, mock_first_run, mock_run_async):
        import typer

        from spec.cli import _fetch_ticket_with_onboarding
        from spec.integrations.backends.errors import BackendNotConfiguredError

        mock_run_async.side_effect = BackendNotConfiguredError("No backend")
        mock_first_run.return_value = True
        mock_onboard.return_value = OnboardingResult(success=False, error_message="User cancelled")
        config = _make_config()

        with pytest.raises(typer.Exit):
            _fetch_ticket_with_onboarding("TICKET-1", config, None, None)

    @patch("spec.cli.run_async")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.run_onboarding")
    def test_retry_after_onboarding_fails_exits(self, mock_onboard, mock_first_run, mock_run_async):
        import typer

        from spec.cli import _fetch_ticket_with_onboarding
        from spec.integrations.backends.errors import BackendNotConfiguredError

        mock_run_async.side_effect = [
            BackendNotConfiguredError("No backend"),
            Exception("Network error"),
        ]
        mock_first_run.return_value = True
        mock_onboard.return_value = OnboardingResult(success=True, backend=AgentPlatform.AUGGIE)
        config = _make_config()

        with pytest.raises(typer.Exit):
            _fetch_ticket_with_onboarding("TICKET-1", config, None, None)

    @patch("spec.cli.run_async")
    @patch("spec.cli.run_onboarding")
    @patch("spec.cli.is_first_run")
    def test_no_double_onboarding_after_config_reload(
        self, mock_first_run, mock_onboard, mock_run_async
    ):
        """If config reload shows backend is already configured, skip onboarding."""
        import typer

        from spec.cli import _fetch_ticket_with_onboarding
        from spec.integrations.backends.errors import BackendNotConfiguredError

        mock_run_async.side_effect = BackendNotConfiguredError("No backend")
        # After config.load(), is_first_run returns False (backend was configured)
        mock_first_run.return_value = False
        config = _make_config("auggie")

        with pytest.raises(typer.Exit):
            _fetch_ticket_with_onboarding("TICKET-1", config, None, None)

        # Onboarding should NOT have been triggered
        mock_onboard.assert_not_called()
        # Config should have been reloaded
        config.load.assert_called_once()
