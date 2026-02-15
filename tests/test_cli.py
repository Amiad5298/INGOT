"""Tests for ingot.cli module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ingot.cli import app
from ingot.utils.errors import ExitCode

runner = CliRunner()


class TestCLIVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "0.0.0-dev" in result.stdout

    def test_short_version_flag(self):
        result = runner.invoke(app, ["-v"])

        assert result.exit_code == 0
        assert "0.0.0-dev" in result.stdout


class TestCLIConfig:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    def test_config_flag_shows_config(self, mock_config_class, mock_banner):
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--config"])

        mock_config.show.assert_called_once()


class TestCLIPrerequisites:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.workflow.is_git_repo")
    def test_fails_outside_git_repo(self, mock_git, mock_config_class, mock_banner):
        mock_git.return_value = False
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.workflow.is_git_repo")
    @patch("ingot.cli.workflow.is_first_run")
    @patch("ingot.cli.workflow.run_onboarding")
    def test_onboarding_failure_exits(
        self, mock_onboard, mock_first_run, mock_git, mock_config_class, mock_banner
    ):
        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = MagicMock(success=False, error_message="User cancelled")
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestCLIWorkflow:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_runs_workflow_with_ticket(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        mock_run.assert_called_once()

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_main_menu")
    def test_shows_menu_without_ticket(
        self, mock_menu, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, [])

        mock_menu.assert_called_once()


class TestCLIFlags:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_model_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--model", "claude-3", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "claude-3"

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_skip_clarification_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--skip-clarification", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["skip_clarification"] is True

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_no_squash_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-squash", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["squash_at_end"] is False


class TestParallelFlags:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_parallel_flag_enables_parallel(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is True

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_no_parallel_flag_disables(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is False

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_max_parallel_sets_value(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-parallel", "4", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] == 4

    @patch("ingot.cli.app.show_banner")
    def test_max_parallel_validates_range(self, mock_banner):
        # Test value too low
        result = runner.invoke(app, ["--max-parallel", "0", "TEST-123"])
        assert result.exit_code != 0

        # Test value too high
        result = runner.invoke(app, ["--max-parallel", "10", "TEST-123"])
        assert result.exit_code != 0

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_fail_fast_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is True

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_no_fail_fast_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is False

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_max_parallel_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] is None

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_fail_fast_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is None


class TestRetryFlags:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_max_retries_sets_value(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-retries", "10", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 10

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_max_retries_zero_disables(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-retries", "0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 0

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_retry_base_delay_sets_value(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--retry-base-delay", "5.0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["retry_base_delay"] == 5.0


class TestAutoUpdateDocsFlags:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_auto_update_docs_flag_enables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is True

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_no_auto_update_docs_flag_disables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is False

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_auto_update_docs_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is None


class TestShowHelp:
    def test_show_help_displays_usage(self, capsys):
        from ingot.cli import show_help

        show_help()

        captured = capsys.readouterr()
        assert "INGOT Help" in captured.out or "Usage:" in captured.out


class TestExceptionHandlers:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_user_cancelled_error_handled(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        from ingot.utils.errors import UserCancelledError

        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_run.side_effect = UserCancelledError("User cancelled")

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.USER_CANCELLED

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_spec_error_handled(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        from ingot.utils.errors import IngotError

        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_run.side_effect = IngotError("Something went wrong", ExitCode.GENERAL_ERROR)

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestDirtyTreePolicy:
    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_dirty_tree_policy_fail_fast(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow
        from ingot.workflow.state import DirtyTreePolicy

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            dirty_tree_policy="fail-fast",
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["dirty_tree_policy"] == DirtyTreePolicy.FAIL_FAST

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_dirty_tree_policy_warn(self, mock_run_async, mock_run_workflow, mock_is_ambiguous):
        from ingot.cli import _run_workflow
        from ingot.workflow.state import DirtyTreePolicy

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        _run_workflow(
            ticket="TEST-123",
            config=mock_config,
            dirty_tree_policy="warn",
        )

        call_kwargs = mock_run_workflow.call_args[1]
        assert call_kwargs["dirty_tree_policy"] == DirtyTreePolicy.WARN_AND_CONTINUE

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.cli.ticket.run_async")
    def test_dirty_tree_policy_invalid_rejected(self, mock_run_async, mock_is_ambiguous):
        import click

        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True

        with pytest.raises(click.exceptions.Exit) as exc_info:
            _run_workflow(
                ticket="TEST-123",
                config=mock_config,
                dirty_tree_policy="invalid-policy",
            )
        assert exc_info.value.exit_code == ExitCode.GENERAL_ERROR


class TestOnboardingFlow:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.workflow.is_git_repo")
    @patch("ingot.cli.workflow.is_first_run")
    @patch("ingot.cli.workflow.run_onboarding")
    def test_onboarding_triggered_on_first_run(
        self, mock_onboard, mock_first_run, mock_git, mock_config_class, mock_banner
    ):
        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = MagicMock(success=False, error_message="Setup failed")
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        mock_onboard.assert_called_once()
        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestEffectiveValueOverrides:
    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_max_parallel_override_cli_beats_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 5
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_max_parallel_none_uses_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 5
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_no_fail_fast_overrides_config_true(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = True  # Config says fail_fast
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_fail_fast_none_uses_config(self, mock_run_async, mock_run_workflow, mock_is_ambiguous):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = True  # Config has fail_fast=True
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.cli.ticket.run_async")
    def test_invalid_config_max_parallel_rejected(self, mock_run_async, mock_is_ambiguous):
        import click

        from ingot.cli import _run_workflow
        from ingot.utils.errors import ExitCode

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 10  # Invalid config value
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_auto_update_docs_override_cli_beats_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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

    @patch("ingot.cli.workflow._is_ambiguous_ticket_id", return_value=False)
    @patch("ingot.workflow.runner.run_ingot_workflow")
    @patch("ingot.cli.ticket.run_async")
    def test_auto_update_docs_none_uses_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        from ingot.cli import _run_workflow

        mock_run_async.return_value = (MagicMock(), MagicMock())
        mock_config = MagicMock()
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
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


class TestValidatePlatform:
    def test_validate_platform_valid_jira(self):
        from ingot.cli import _validate_platform
        from ingot.integrations.providers import Platform

        assert _validate_platform("jira") == Platform.JIRA
        assert _validate_platform("JIRA") == Platform.JIRA
        assert _validate_platform("Jira") == Platform.JIRA

    def test_validate_platform_valid_linear(self):
        from ingot.cli import _validate_platform
        from ingot.integrations.providers import Platform

        assert _validate_platform("linear") == Platform.LINEAR
        assert _validate_platform("LINEAR") == Platform.LINEAR

    def test_validate_platform_valid_github(self):
        from ingot.cli import _validate_platform
        from ingot.integrations.providers import Platform

        assert _validate_platform("github") == Platform.GITHUB

    def test_validate_platform_none(self):
        from ingot.cli import _validate_platform

        assert _validate_platform(None) is None

    def test_validate_platform_invalid(self):
        import typer

        from ingot.cli import _validate_platform

        with pytest.raises(typer.BadParameter) as exc_info:
            _validate_platform("invalid")
        assert "Invalid platform" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_validate_platform_hyphen_normalization(self):
        from ingot.cli import _validate_platform
        from ingot.integrations.providers import Platform

        # azure-devops should be normalized to AZURE_DEVOPS
        assert _validate_platform("azure-devops") == Platform.AZURE_DEVOPS
        assert _validate_platform("AZURE-DEVOPS") == Platform.AZURE_DEVOPS
        assert _validate_platform("Azure-DevOps") == Platform.AZURE_DEVOPS

    def test_validate_platform_underscore_format(self):
        from ingot.cli import _validate_platform
        from ingot.integrations.providers import Platform

        assert _validate_platform("azure_devops") == Platform.AZURE_DEVOPS


class TestIsAmbiguousTicketId:
    def test_bare_project_id_is_ambiguous(self):
        from ingot.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("PROJ-123") is True
        assert _is_ambiguous_ticket_id("ENG-456") is True
        assert _is_ambiguous_ticket_id("ABC-1") is True
        assert _is_ambiguous_ticket_id("A1-999") is True

    def test_url_is_not_ambiguous(self):
        from ingot.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("https://jira.example.com/browse/PROJ-123") is False
        assert _is_ambiguous_ticket_id("https://linear.app/team/issue/ENG-456") is False
        assert _is_ambiguous_ticket_id("http://example.com/ticket") is False

    def test_github_format_is_not_ambiguous(self):
        from ingot.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("owner/repo#42") is False
        assert _is_ambiguous_ticket_id("my-org/my-repo#123") is False

    def test_invalid_formats_are_not_ambiguous(self):
        from ingot.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("123") is False
        assert _is_ambiguous_ticket_id("just-text") is False
        assert _is_ambiguous_ticket_id("") is False

    def test_underscore_in_project_key_is_ambiguous(self):
        from ingot.cli import _is_ambiguous_ticket_id

        # Jira supports underscores in project keys
        assert _is_ambiguous_ticket_id("MY_PROJ-123") is True
        assert _is_ambiguous_ticket_id("TEST_PROJECT-1") is True
        assert _is_ambiguous_ticket_id("A_B_C-999") is True


class TestResolveWithPlatformHint:
    def test_jira_keeps_bare_id(self):
        from ingot.cli import _resolve_with_platform_hint
        from ingot.integrations.providers import Platform

        result = _resolve_with_platform_hint("PROJ-123", Platform.JIRA)
        assert result == "PROJ-123"

    def test_linear_converts_to_url(self):
        from ingot.cli import _resolve_with_platform_hint
        from ingot.integrations.providers import Platform

        result = _resolve_with_platform_hint("ENG-456", Platform.LINEAR)
        assert result == "https://linear.app/team/issue/ENG-456"

    def test_github_keeps_bare_id(self):
        from ingot.cli import _resolve_with_platform_hint
        from ingot.integrations.providers import Platform

        result = _resolve_with_platform_hint("owner/repo#42", Platform.GITHUB)
        assert result == "owner/repo#42"

    def test_other_platforms_keep_bare_id(self):
        from ingot.cli import _resolve_with_platform_hint
        from ingot.integrations.providers import Platform

        result = _resolve_with_platform_hint("PROJ-123", Platform.AZURE_DEVOPS)
        assert result == "PROJ-123"


class TestDisambiguatePlatform:
    @patch("ingot.ui.prompts.prompt_select")
    @patch("ingot.cli.platform.print_info")
    def test_uses_config_default_when_set(self, mock_print, mock_prompt):
        from ingot.cli import _disambiguate_platform
        from ingot.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = Platform.LINEAR

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.LINEAR
        mock_prompt.assert_not_called()

    @patch("ingot.ui.prompts.prompt_select")
    @patch("ingot.cli.platform.print_info")
    def test_prompts_when_no_default(self, mock_print, mock_prompt):
        from ingot.cli import _disambiguate_platform
        from ingot.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        # Now uses kebab-case display names
        mock_prompt.return_value = "jira"

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.JIRA
        mock_prompt.assert_called_once()
        mock_print.assert_called_once()

    @patch("ingot.ui.prompts.prompt_select")
    @patch("ingot.cli.platform.print_info")
    def test_prompt_linear_selection(self, mock_print, mock_prompt):
        from ingot.cli import _disambiguate_platform
        from ingot.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        # Now uses kebab-case display names
        mock_prompt.return_value = "linear"

        result = _disambiguate_platform("ENG-456", mock_config)

        assert result == Platform.LINEAR

    @patch("ingot.ui.prompts.prompt_select")
    @patch("ingot.cli.platform.print_info")
    def test_uses_explicit_mapping_not_string_parsing(self, mock_print, mock_prompt):
        from ingot.cli import AMBIGUOUS_PLATFORMS, _disambiguate_platform, _platform_display_name

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None

        # Test each platform in AMBIGUOUS_PLATFORMS: simulate user selecting it
        for expected_platform in AMBIGUOUS_PLATFORMS:
            mock_prompt.reset_mock()
            choice_key = _platform_display_name(expected_platform)
            mock_prompt.return_value = choice_key

            result = _disambiguate_platform("PROJ-123", mock_config)

            # Verify the mapping returns the correct enum
            assert (
                result == expected_platform
            ), f"Expected {expected_platform}, got {result} for choice '{choice_key}'"

            # Verify prompt was called with kebab-case choices (the mapping keys)
            call_kwargs = mock_prompt.call_args[1]
            choices = call_kwargs["choices"]
            assert choice_key in choices, f"Choice '{choice_key}' not in {choices}"

    @patch("ingot.ui.prompts.prompt_select")
    @patch("ingot.cli.platform.print_info")
    def test_prompt_choices_ordering_is_stable(self, mock_print, mock_prompt):
        from ingot.cli import AMBIGUOUS_PLATFORMS, _disambiguate_platform, _platform_display_name

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        mock_prompt.return_value = "jira"

        _disambiguate_platform("PROJ-123", mock_config)

        call_kwargs = mock_prompt.call_args[1]
        choices = call_kwargs["choices"]

        # Expected order: derived from AMBIGUOUS_PLATFORMS tuple order
        expected_choices = [_platform_display_name(p) for p in AMBIGUOUS_PLATFORMS]
        assert (
            choices == expected_choices
        ), f"Choices {choices} don't match expected order {expected_choices}"


class TestFetchTicketAsyncIntegration:
    @pytest.mark.asyncio
    async def test_fetch_ticket_async_calls_ticket_service(self):
        from ingot.cli import _fetch_ticket_async
        from ingot.integrations.providers import GenericTicket, Platform

        # Create mock ticket
        mock_ticket = GenericTicket(
            id="PROJ-123",
            title="Test Ticket",
            description="Test description",
            platform=Platform.JIRA,
            url="https://jira.example.com/browse/PROJ-123",
        )

        # Create mock service with async context manager support
        mock_service = AsyncMock()
        mock_service.get_ticket = AsyncMock(return_value=mock_ticket)
        mock_service.__aenter__ = AsyncMock(return_value=mock_service)
        mock_service.__aexit__ = AsyncMock(return_value=None)

        mock_config = MagicMock()

        # Patch create_ticket_service_from_config to return (service, backend) tuple
        mock_backend = MagicMock()

        async def mock_create_service_from_config(*args, **kwargs):
            return mock_service, mock_backend

        with patch(
            "ingot.cli.ticket.create_ticket_service_from_config",
            side_effect=mock_create_service_from_config,
        ):
            result = await _fetch_ticket_async(
                ticket_input="PROJ-123",
                config=mock_config,
                platform_hint=None,
            )

        ticket_result, backend_result = result
        assert ticket_result == mock_ticket
        assert backend_result == mock_backend
        mock_service.get_ticket.assert_called_once_with("PROJ-123")

    @pytest.mark.asyncio
    async def test_fetch_ticket_async_with_platform_hint_linear(self):
        from ingot.cli import _fetch_ticket_async
        from ingot.integrations.providers import GenericTicket, Platform

        mock_ticket = GenericTicket(
            id="ENG-456",
            title="Linear Ticket",
            description="Test",
            platform=Platform.LINEAR,
            url="https://linear.app/team/issue/ENG-456",
        )

        mock_service = AsyncMock()
        mock_service.get_ticket = AsyncMock(return_value=mock_ticket)
        mock_service.__aenter__ = AsyncMock(return_value=mock_service)
        mock_service.__aexit__ = AsyncMock(return_value=None)

        mock_config = MagicMock()
        mock_backend = MagicMock()

        async def mock_create_service_from_config(*args, **kwargs):
            return mock_service, mock_backend

        with patch(
            "ingot.cli.ticket.create_ticket_service_from_config",
            side_effect=mock_create_service_from_config,
        ):
            result = await _fetch_ticket_async(
                ticket_input="ENG-456",
                config=mock_config,
                platform_hint=Platform.LINEAR,
            )

        ticket_result, backend_result = result
        assert ticket_result == mock_ticket
        assert backend_result == mock_backend
        # Should have converted to Linear URL format
        mock_service.get_ticket.assert_called_once_with("https://linear.app/team/issue/ENG-456")

    @pytest.mark.asyncio
    async def test_fetch_ticket_async_url_not_modified(self):
        from ingot.cli import _fetch_ticket_async
        from ingot.integrations.providers import GenericTicket, Platform

        mock_ticket = GenericTicket(
            id="PROJ-123",
            title="Jira Ticket",
            description="Test",
            platform=Platform.JIRA,
            url="https://jira.example.com/browse/PROJ-123",
        )

        mock_service = AsyncMock()
        mock_service.get_ticket = AsyncMock(return_value=mock_ticket)
        mock_service.__aenter__ = AsyncMock(return_value=mock_service)
        mock_service.__aexit__ = AsyncMock(return_value=None)

        mock_config = MagicMock()
        original_url = "https://jira.example.com/browse/PROJ-123"
        mock_backend = MagicMock()

        async def mock_create_service_from_config(*args, **kwargs):
            return mock_service, mock_backend

        with patch(
            "ingot.cli.ticket.create_ticket_service_from_config",
            side_effect=mock_create_service_from_config,
        ):
            result = await _fetch_ticket_async(
                ticket_input=original_url,
                config=mock_config,
                platform_hint=Platform.LINEAR,  # Hint should be ignored for URLs
            )

        ticket_result, backend_result = result
        assert ticket_result == mock_ticket
        assert backend_result == mock_backend
        # URL should pass through unchanged
        mock_service.get_ticket.assert_called_once_with(original_url)


class TestRunAsync:
    def test_run_async_executes_coroutine_factory(self):
        from ingot.cli import run_async

        async def sample_coro():
            return "test_result"

        # Now takes a factory (callable) instead of a coroutine
        result = run_async(lambda: sample_coro())
        assert result == "test_result"

    def test_run_async_raises_when_loop_running_without_creating_coroutine(self):
        import asyncio

        from ingot.cli import AsyncLoopAlreadyRunningError, run_async

        factory_called = False

        async def inner_coro():
            return "should not execute"

        def coro_factory():
            nonlocal factory_called
            factory_called = True
            return inner_coro()

        async def outer():
            # This should raise because we're already in an async context
            with pytest.raises(AsyncLoopAlreadyRunningError) as exc_info:
                run_async(coro_factory)

            assert "event loop is already running" in str(exc_info.value)
            # Factory should NOT be called when loop is already running
            assert factory_called is False

        asyncio.run(outer())

    def test_run_async_calls_factory_when_no_loop(self):
        from ingot.cli import run_async

        factory_call_count = 0

        async def coro():
            return 42

        def coro_factory():
            nonlocal factory_call_count
            factory_call_count += 1
            return coro()

        result = run_async(coro_factory)
        assert result == 42
        assert factory_call_count == 1


class TestAmbiguousIdWithPlatformFlag:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    @patch("ingot.ui.prompts.prompt_select")
    def test_ambiguous_id_with_platform_flag_no_prompt(
        self, mock_prompt, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        # Run with ambiguous ID but explicit platform
        runner.invoke(app, ["PROJ-123", "--platform", "linear"])

        # Should NOT call prompt_select since platform is explicit
        mock_prompt.assert_not_called()

        # Verify _run_workflow was called with correct platform
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        from ingot.integrations.providers import Platform

        assert call_kwargs["platform"] == Platform.LINEAR


class TestInvalidDefaultPlatformWarning:
    def test_invalid_default_platform_logs_warning(self, caplog):
        import logging

        from ingot.config.settings import Settings

        settings = Settings(default_platform="invalid_platform")

        with caplog.at_level(logging.WARNING):
            result = settings.get_default_platform()

        assert result is None
        assert "Invalid DEFAULT_PLATFORM value" in caplog.text
        assert "invalid_platform" in caplog.text

    def test_valid_default_platform_no_warning(self, caplog):
        import logging

        from ingot.config.settings import Settings

        settings = Settings(default_platform="jira")

        with caplog.at_level(logging.WARNING):
            result = settings.get_default_platform()

        from ingot.integrations.providers import Platform

        assert result == Platform.JIRA
        assert "Invalid DEFAULT_PLATFORM value" not in caplog.text


class TestForceIntegrationCheckWarning:
    @patch("ingot.cli.workflow.is_git_repo")
    @patch("ingot.cli.workflow.is_first_run")
    @patch("ingot.cli.workflow.print_warning")
    def test_force_integration_check_prints_warning(
        self, mock_print_warning, mock_is_first_run, mock_is_git_repo
    ):
        from ingot.cli import _check_prerequisites

        mock_is_git_repo.return_value = True
        mock_is_first_run.return_value = False

        mock_config = MagicMock()
        result = _check_prerequisites(mock_config, force_integration_check=True)

        assert result is True
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        assert "no effect" in warning_msg.lower() or "currently has no effect" in warning_msg

    @patch("ingot.cli.workflow.is_git_repo")
    @patch("ingot.cli.workflow.is_first_run")
    @patch("ingot.cli.workflow.print_warning")
    def test_force_integration_check_false_no_warning(
        self, mock_print_warning, mock_is_first_run, mock_is_git_repo
    ):
        from ingot.cli import _check_prerequisites

        mock_is_git_repo.return_value = True
        mock_is_first_run.return_value = False

        mock_config = MagicMock()
        result = _check_prerequisites(mock_config, force_integration_check=False)

        assert result is True
        mock_print_warning.assert_not_called()


class TestCLIProviderRegistryReset:
    def setup_method(self):
        """Reset ProviderRegistry before each test."""
        from ingot.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.reset_instances()

    def teardown_method(self):
        """Reset ProviderRegistry after each test."""
        from ingot.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.reset_instances()

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_main_menu")
    @patch("ingot.cli.app.ConfigManager")
    def test_multi_run_clears_stale_config(
        self, mock_config_class, mock_menu, mock_prereq, mock_banner
    ):
        from ingot.integrations.providers.registry import ProviderRegistry

        mock_prereq.return_value = True

        # First run: config has DEFAULT_JIRA_PROJECT set
        mock_config_first = MagicMock()
        mock_config_first.settings.default_jira_project = "PROJ1"
        mock_config_class.return_value = mock_config_first

        runner.invoke(app, [])

        # Capture config after first run
        first_run_config = ProviderRegistry._config.copy()

        # Second run: config has NO default Jira project (empty string)
        mock_config_second = MagicMock()
        mock_config_second.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config_second

        runner.invoke(app, [])

        # Capture config after second run
        second_run_config = ProviderRegistry._config.copy()

        # First run should have had the project configured
        assert first_run_config.get("default_jira_project") == "PROJ1"

        # Second run should NOT have the stale config from first run
        # It should be empty string (the default when not configured)
        assert second_run_config.get("default_jira_project") == ""


class TestCreateTicketServiceFromConfig:
    @pytest.mark.asyncio
    async def test_calls_resolve_backend_platform(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ) as mock_resolve,
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ),
        ):
            mock_factory_class.create.return_value = mock_backend

            service, backend = await create_ticket_service_from_config(
                config_manager=mock_config,
                cli_backend_override="auggie",
            )

        mock_resolve.assert_called_once_with(mock_config, "auggie")

    @pytest.mark.asyncio
    async def test_calls_backend_factory_create(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ),
        ):
            mock_factory_class.create.return_value = mock_backend

            service, backend = await create_ticket_service_from_config(
                config_manager=mock_config,
            )

        mock_factory_class.create.assert_called_once_with(mock_platform, verify_installed=True)

    @pytest.mark.asyncio
    async def test_returns_service_and_backend_tuple(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ),
        ):
            mock_factory_class.create.return_value = mock_backend

            result = await create_ticket_service_from_config(
                config_manager=mock_config,
            )

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == mock_service
        assert result[1] == mock_backend

    @pytest.mark.asyncio
    async def test_cli_backend_override_passed_to_resolver(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ) as mock_resolve,
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ),
        ):
            mock_factory_class.create.return_value = mock_backend

            await create_ticket_service_from_config(
                config_manager=mock_config,
                cli_backend_override="claude",
            )

        mock_resolve.assert_called_once_with(mock_config, "claude")

    @pytest.mark.asyncio
    async def test_backend_not_configured_error_propagates(self):
        from ingot.cli import create_ticket_service_from_config
        from ingot.integrations.backends.errors import BackendNotConfiguredError

        mock_config = MagicMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform",
                side_effect=BackendNotConfiguredError("No backend configured"),
            ),
            pytest.raises(BackendNotConfiguredError, match="No backend configured"),
        ):
            await create_ticket_service_from_config(config_manager=mock_config)

    @pytest.mark.asyncio
    async def test_backend_not_installed_error_propagates(self):
        from ingot.cli import create_ticket_service_from_config
        from ingot.integrations.backends.errors import BackendNotInstalledError

        mock_config = MagicMock()
        mock_platform = MagicMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            pytest.raises(BackendNotInstalledError, match="CLI not installed"),
        ):
            mock_factory_class.create.side_effect = BackendNotInstalledError("CLI not installed")
            await create_ticket_service_from_config(config_manager=mock_config)

    @pytest.mark.asyncio
    async def test_default_auth_manager_created_when_none(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ),
            patch("ingot.cli.ticket.AuthenticationManager") as mock_auth_class,
        ):
            mock_factory_class.create.return_value = mock_backend

            await create_ticket_service_from_config(config_manager=mock_config)

        mock_auth_class.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_provided_auth_manager_used(self):
        from ingot.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()
        mock_auth = MagicMock()

        with (
            patch(
                "ingot.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("ingot.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "ingot.cli.ticket.create_ticket_service",
                new_callable=AsyncMock,
                return_value=mock_service,
            ) as mock_create,
            patch("ingot.cli.ticket.AuthenticationManager") as mock_auth_class,
        ):
            mock_factory_class.create.return_value = mock_backend

            await create_ticket_service_from_config(
                config_manager=mock_config,
                auth_manager=mock_auth,
            )

        # Should NOT create a new AuthenticationManager
        mock_auth_class.assert_not_called()
        # Should pass the provided auth_manager to create_ticket_service
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["auth_manager"] == mock_auth


class TestBackendFlag:
    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_backend_flag_passed_to_workflow(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--backend", "auggie", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] == "auggie"

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_backend_short_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["-b", "claude", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] == "claude"

    @patch("ingot.cli.app.show_banner")
    @patch("ingot.cli.app.ConfigManager")
    @patch("ingot.cli.app._check_prerequisites")
    @patch("ingot.cli.app._run_workflow")
    def test_backend_none_when_not_provided(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] is None
