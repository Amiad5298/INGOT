"""Tests for spec.cli module."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from specflow.cli import app
from specflow.utils.errors import ExitCode


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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    def test_config_flag_shows_config(self, mock_config_class, mock_banner):
        """--config shows configuration and exits."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["--config"])
        
        mock_config.show.assert_called_once()


class TestCLIPrerequisites:
    """Tests for prerequisite checking."""

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli.is_git_repo")
    def test_fails_outside_git_repo(self, mock_git, mock_config_class, mock_banner):
        """Fails when not in a git repository."""
        mock_git.return_value = False
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["TEST-123"])
        
        assert result.exit_code == ExitCode.GENERAL_ERROR

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli.is_git_repo")
    @patch("specflow.cli.check_auggie_installed")
    @patch("specflow.ui.prompts.prompt_confirm")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_main_menu")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_model_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--model flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config
        
        result = runner.invoke(app, ["--model", "claude-3", "TEST-123"])
        
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "claude-3"

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    def test_max_parallel_validates_range(self, mock_banner):
        """--max-parallel validates range (1-5)."""
        # Test value too low
        result = runner.invoke(app, ["--max-parallel", "0", "TEST-123"])
        assert result.exit_code != 0

        # Test value too high
        result = runner.invoke(app, ["--max-parallel", "10", "TEST-123"])
        assert result.exit_code != 0

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_no_fail_fast_flag(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--no-fail-fast flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--no-fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is False

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_max_parallel_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --max-parallel flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] is None

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_fail_fast_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --fail-fast/--no-fail-fast flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is None


class TestRetryFlags:
    """Tests for retry CLI flags."""

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
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


class TestAutoUpdateDocsFlags:
    """Tests for --auto-update-docs CLI flag."""

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_auto_update_docs_flag_enables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--auto-update-docs flag enables documentation updates."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is True

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_no_auto_update_docs_flag_disables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--no-auto-update-docs flag disables documentation updates."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["--no-auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is False

    @patch("specflow.cli.show_banner")
    @patch("specflow.cli.ConfigManager")
    @patch("specflow.cli._check_prerequisites")
    @patch("specflow.cli._run_workflow")
    def test_auto_update_docs_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --auto-update-docs flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is None


class TestEffectiveValueOverrides:
    """Tests for effective value computation and override semantics in _run_workflow."""

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_max_parallel_override_cli_beats_config(
        self, mock_parse, mock_run_workflow
    ):
        """CLI --max-parallel 3 overrides config max_parallel_tasks=5."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 5
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            max_parallel=3,  # CLI provides 3
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["max_parallel_tasks"] == 3  # CLI wins over config=5

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_max_parallel_none_uses_config(
        self, mock_parse, mock_run_workflow
    ):
        """When CLI max_parallel is None, uses config.settings.max_parallel_tasks."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 5
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            max_parallel=None,  # CLI not provided
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["max_parallel_tasks"] == 5  # Uses config value

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_no_fail_fast_overrides_config_true(
        self, mock_parse, mock_run_workflow
    ):
        """CLI --no-fail-fast (False) overrides config fail_fast=True."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = True  # Config says fail_fast
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            fail_fast=False,  # CLI says --no-fail-fast
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["fail_fast"] is False  # CLI wins

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_fail_fast_none_uses_config(
        self, mock_parse, mock_run_workflow
    ):
        """When CLI fail_fast is None, uses config.settings.fail_fast."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = True  # Config has fail_fast=True
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            fail_fast=None,  # CLI not provided
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["fail_fast"] is True  # Uses config value

    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_invalid_config_max_parallel_rejected(self, mock_parse):
        """Invalid config max_parallel_tasks (e.g., 10) is rejected via effective validation."""
        import click
        from specflow.cli import _run_workflow
        from specflow.utils.errors import ExitCode

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 10  # Invalid config value
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        with pytest.raises(click.exceptions.Exit) as exc_info:
            _run_workflow(
                ticket="TEST-123",
                config=mock_config,
                max_parallel=None,  # Uses invalid config
            )
        assert exc_info.value.exit_code == ExitCode.GENERAL_ERROR

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_auto_update_docs_override_cli_beats_config(
        self, mock_parse, mock_run_workflow
    ):
        """CLI --no-auto-update-docs overrides config auto_update_docs=True."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True  # Config says True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            auto_update_docs=False,  # CLI says --no-auto-update-docs
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["auto_update_docs"] is False  # CLI wins

    @patch("specflow.workflow.runner.run_spec_driven_workflow")
    @patch("specflow.integrations.jira.parse_jira_ticket")
    def test_auto_update_docs_none_uses_config(
        self, mock_parse, mock_run_workflow
    ):
        """When CLI auto_update_docs is None, uses config.settings.auto_update_docs."""
        from specflow.cli import _run_workflow

        mock_parse.return_value = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.default_jira_project = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = False  # Config says False

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            auto_update_docs=None,  # CLI not provided
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["auto_update_docs"] is False  # Uses config value

