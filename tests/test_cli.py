"""Tests for ai_workflow.cli module."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from ai_workflow.cli import app
from ai_workflow.utils.errors import ExitCode


runner = CliRunner()


class TestCLIVersion:
    """Tests for --version flag."""

    def test_version_flag(self):
        """--version shows version and exits."""
        result = runner.invoke(app, ["--version"])
        
        assert result.exit_code == 0
        assert "2.0.0" in result.stdout

    def test_short_version_flag(self):
        """-v shows version and exits."""
        result = runner.invoke(app, ["-v"])
        
        assert result.exit_code == 0
        assert "2.0.0" in result.stdout


class TestCLIConfig:
    """Tests for --config flag."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    def test_config_flag_shows_config(self, mock_config_class, mock_banner):
        """--config shows configuration and exits."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["--config"])
        
        mock_config.show.assert_called_once()


class TestCLIPrerequisites:
    """Tests for prerequisite checking."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli.is_git_repo")
    def test_fails_outside_git_repo(self, mock_git, mock_config_class, mock_banner):
        """Fails when not in a git repository."""
        mock_git.return_value = False
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["TEST-123"])
        
        assert result.exit_code == ExitCode.GENERAL_ERROR

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli.is_git_repo")
    @patch("ai_workflow.cli.check_auggie_installed")
    @patch("ai_workflow.ui.prompts.prompt_confirm")
    def test_prompts_auggie_install(
        self, mock_confirm, mock_check, mock_git, mock_config_class, mock_banner
    ):
        """Prompts to install Auggie when not installed."""
        mock_git.return_value = True
        mock_check.return_value = (False, "Auggie not installed")
        mock_confirm.return_value = False
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestCLIWorkflow:
    """Tests for workflow execution."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_runs_workflow_with_ticket(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """Runs workflow when ticket is provided."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = "PROJ"
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["TEST-123"])
        
        mock_run.assert_called_once()

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_main_menu")
    def test_shows_menu_without_ticket(
        self, mock_menu, mock_prereq, mock_config_class, mock_banner
    ):
        """Shows main menu when no ticket provided."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, [])
        
        mock_menu.assert_called_once()


class TestCLIFlags:
    """Tests for CLI flags."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_model_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--model flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["--model", "claude-3", "TEST-123"])
        
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "claude-3"

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_skip_clarification_flag(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--skip-clarification flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["--skip-clarification", "TEST-123"])
        
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["skip_clarification"] is True

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_no_squash_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--no-squash flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--no-squash", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["squash_at_end"] is False


class TestParallelFlags:
    """Tests for parallel execution CLI flags."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_parallel_flag_enables_parallel(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--parallel flag enables parallel execution."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is True

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_no_parallel_flag_disables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--no-parallel flag disables parallel execution."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--no-parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is False

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_max_parallel_sets_value(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--max-parallel sets the maximum parallel tasks."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--max-parallel", "4", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] == 4

    @patch("ai_workflow.cli.show_banner")
    def test_max_parallel_validates_range(self, mock_banner):
        """--max-parallel validates range (1-5)."""
        # Test value too low
        result = runner.invoke(app, ["--max-parallel", "0", "TEST-123"])
        assert result.exit_code != 0

        # Test value too high
        result = runner.invoke(app, ["--max-parallel", "10", "TEST-123"])
        assert result.exit_code != 0

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_fail_fast_flag(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--fail-fast flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is True


class TestRetryFlags:
    """Tests for retry CLI flags."""

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_max_retries_sets_value(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--max-retries sets the maximum retry count."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--max-retries", "10", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 10

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_max_retries_zero_disables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--max-retries 0 disables retries."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--max-retries", "0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 0

    @patch("ai_workflow.cli.show_banner")
    @patch("ai_workflow.cli.ConfigManager")
    @patch("ai_workflow.cli._check_prerequisites")
    @patch("ai_workflow.cli._run_workflow")
    def test_retry_base_delay_sets_value(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--retry-base-delay sets the base delay."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--retry-base-delay", "5.0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["retry_base_delay"] == 5.0

