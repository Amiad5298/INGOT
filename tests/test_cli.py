"""Tests for spec.cli module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from spec.cli import app
from spec.utils.errors import ExitCode

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

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    def test_config_flag_shows_config(self, mock_config_class, mock_banner):
        """--config shows configuration and exits."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--config"])

        mock_config.show.assert_called_once()


class TestCLIPrerequisites:
    """Tests for prerequisite checking."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli.is_git_repo")
    def test_fails_outside_git_repo(self, mock_git, mock_config_class, mock_banner):
        """Fails when not in a git repository."""
        mock_git.return_value = False
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli.is_git_repo")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.run_onboarding")
    def test_onboarding_failure_exits(
        self, mock_onboard, mock_first_run, mock_git, mock_config_class, mock_banner
    ):
        """Exits when onboarding fails (replaces old Auggie install test)."""
        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = MagicMock(success=False, error_message="User cancelled")
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestCLIWorkflow:
    """Tests for workflow execution."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_runs_workflow_with_ticket(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """Runs workflow when ticket is provided."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        mock_run.assert_called_once()

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_main_menu")
    def test_shows_menu_without_ticket(
        self, mock_menu, mock_prereq, mock_config_class, mock_banner
    ):
        """Shows main menu when no ticket provided."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, [])

        mock_menu.assert_called_once()


class TestCLIFlags:
    """Tests for CLI flags."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_model_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--model flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--model", "claude-3", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "claude-3"

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_skip_clarification_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--skip-clarification flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--skip-clarification", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["skip_clarification"] is True

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_no_squash_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--no-squash flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-squash", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["squash_at_end"] is False


class TestParallelFlags:
    """Tests for parallel execution CLI flags."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_parallel_flag_enables_parallel(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--parallel flag enables parallel execution."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is True

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_no_parallel_flag_disables(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--no-parallel flag disables parallel execution."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-parallel", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["parallel"] is False

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_max_parallel_sets_value(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--max-parallel sets the maximum parallel tasks."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-parallel", "4", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] == 4

    @patch("spec.cli.show_banner")
    def test_max_parallel_validates_range(self, mock_banner):
        """--max-parallel validates range (1-5)."""
        # Test value too low
        result = runner.invoke(app, ["--max-parallel", "0", "TEST-123"])
        assert result.exit_code != 0

        # Test value too high
        result = runner.invoke(app, ["--max-parallel", "10", "TEST-123"])
        assert result.exit_code != 0

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_fail_fast_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--fail-fast flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is True

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_no_fail_fast_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--no-fail-fast flag is passed to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-fail-fast", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is False

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_max_parallel_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --max-parallel flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_parallel"] is None

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_fail_fast_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --fail-fast/--no-fail-fast flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["fail_fast"] is None


class TestRetryFlags:
    """Tests for retry CLI flags."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_max_retries_sets_value(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--max-retries sets the maximum retry count."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-retries", "10", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 10

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_max_retries_zero_disables(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """--max-retries 0 disables retries."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--max-retries", "0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["max_retries"] == 0

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_retry_base_delay_sets_value(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--retry-base-delay sets the base delay."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--retry-base-delay", "5.0", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["retry_base_delay"] == 5.0


class TestAutoUpdateDocsFlags:
    """Tests for --auto-update-docs CLI flag."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_auto_update_docs_flag_enables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--auto-update-docs flag enables documentation updates."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is True

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_no_auto_update_docs_flag_disables(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--no-auto-update-docs flag disables documentation updates."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--no-auto-update-docs", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is False

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_auto_update_docs_none_uses_config(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --auto-update-docs flag passes None to workflow (uses config)."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["auto_update_docs"] is None


class TestShowHelp:
    """Tests for show_help function."""

    def test_show_help_displays_usage(self, capsys):
        """show_help displays usage information."""
        from spec.cli import show_help

        show_help()

        captured = capsys.readouterr()
        assert "SPEC Help" in captured.out or "Usage:" in captured.out


class TestExceptionHandlers:
    """Tests for exception handling in main command."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_user_cancelled_error_handled(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """UserCancelledError is handled gracefully."""
        from spec.utils.errors import UserCancelledError

        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_run.side_effect = UserCancelledError("User cancelled")

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.USER_CANCELLED

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_spec_error_handled(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """SpecError is handled gracefully."""
        from spec.utils.errors import SpecError

        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_run.side_effect = SpecError("Something went wrong", ExitCode.GENERAL_ERROR)

        result = runner.invoke(app, ["TEST-123"])

        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestDirtyTreePolicy:
    """Tests for dirty tree policy parsing."""

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_dirty_tree_policy_fail_fast(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """--dirty-tree-policy fail-fast sets FAIL_FAST policy."""
        from spec.cli import _run_workflow
        from spec.workflow.state import DirtyTreePolicy

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_dirty_tree_policy_warn(self, mock_run_async, mock_run_workflow, mock_is_ambiguous):
        """--dirty-tree-policy warn sets WARN_AND_CONTINUE policy."""
        from spec.cli import _run_workflow
        from spec.workflow.state import DirtyTreePolicy

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.cli.run_async")
    def test_dirty_tree_policy_invalid_rejected(self, mock_run_async, mock_is_ambiguous):
        """Invalid --dirty-tree-policy value is rejected."""
        import click

        from spec.cli import _run_workflow

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
    """Tests for onboarding flow triggered from CLI."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli.is_git_repo")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.run_onboarding")
    def test_onboarding_triggered_on_first_run(
        self, mock_onboard, mock_first_run, mock_git, mock_config_class, mock_banner
    ):
        """Onboarding is triggered when is_first_run returns True."""
        mock_git.return_value = True
        mock_first_run.return_value = True
        mock_onboard.return_value = MagicMock(success=False, error_message="Setup failed")
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        result = runner.invoke(app, ["TEST-123"])

        mock_onboard.assert_called_once()
        assert result.exit_code == ExitCode.GENERAL_ERROR


class TestEffectiveValueOverrides:
    """Tests for effective value computation and override semantics in _run_workflow."""

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_max_parallel_override_cli_beats_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """CLI --max-parallel 3 overrides config max_parallel_tasks=5."""
        from spec.cli import _run_workflow

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_max_parallel_none_uses_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """When CLI max_parallel is None, uses config.settings.max_parallel_tasks."""
        from spec.cli import _run_workflow

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_no_fail_fast_overrides_config_true(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """CLI --no-fail-fast (False) overrides config fail_fast=True."""
        from spec.cli import _run_workflow

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_fail_fast_none_uses_config(self, mock_run_async, mock_run_workflow, mock_is_ambiguous):
        """When CLI fail_fast is None, uses config.settings.fail_fast."""
        from spec.cli import _run_workflow

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.cli.run_async")
    def test_invalid_config_max_parallel_rejected(self, mock_run_async, mock_is_ambiguous):
        """Invalid config max_parallel_tasks (e.g., 10) is rejected via effective validation."""
        import click

        from spec.cli import _run_workflow
        from spec.utils.errors import ExitCode

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_auto_update_docs_override_cli_beats_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """CLI --no-auto-update-docs overrides config auto_update_docs=True."""
        from spec.cli import _run_workflow

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

    @patch("spec.cli._is_ambiguous_ticket_id", return_value=False)
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    @patch("spec.cli.run_async")
    def test_auto_update_docs_none_uses_config(
        self, mock_run_async, mock_run_workflow, mock_is_ambiguous
    ):
        """When CLI auto_update_docs is None, uses config.settings.auto_update_docs."""
        from spec.cli import _run_workflow

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
    """Tests for _validate_platform helper function."""

    def test_validate_platform_valid_jira(self):
        """Valid Jira platform string returns Platform.JIRA."""
        from spec.cli import _validate_platform
        from spec.integrations.providers import Platform

        assert _validate_platform("jira") == Platform.JIRA
        assert _validate_platform("JIRA") == Platform.JIRA
        assert _validate_platform("Jira") == Platform.JIRA

    def test_validate_platform_valid_linear(self):
        """Valid Linear platform string returns Platform.LINEAR."""
        from spec.cli import _validate_platform
        from spec.integrations.providers import Platform

        assert _validate_platform("linear") == Platform.LINEAR
        assert _validate_platform("LINEAR") == Platform.LINEAR

    def test_validate_platform_valid_github(self):
        """Valid GitHub platform string returns Platform.GITHUB."""
        from spec.cli import _validate_platform
        from spec.integrations.providers import Platform

        assert _validate_platform("github") == Platform.GITHUB

    def test_validate_platform_none(self):
        """None input returns None."""
        from spec.cli import _validate_platform

        assert _validate_platform(None) is None

    def test_validate_platform_invalid(self):
        """Invalid platform raises BadParameter."""
        import typer

        from spec.cli import _validate_platform

        with pytest.raises(typer.BadParameter) as exc_info:
            _validate_platform("invalid")
        assert "Invalid platform" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_validate_platform_hyphen_normalization(self):
        """Platform names with hyphens are normalized to underscores."""
        from spec.cli import _validate_platform
        from spec.integrations.providers import Platform

        # azure-devops should be normalized to AZURE_DEVOPS
        assert _validate_platform("azure-devops") == Platform.AZURE_DEVOPS
        assert _validate_platform("AZURE-DEVOPS") == Platform.AZURE_DEVOPS
        assert _validate_platform("Azure-DevOps") == Platform.AZURE_DEVOPS

    def test_validate_platform_underscore_format(self):
        """Platform names with underscores also work."""
        from spec.cli import _validate_platform
        from spec.integrations.providers import Platform

        assert _validate_platform("azure_devops") == Platform.AZURE_DEVOPS


class TestIsAmbiguousTicketId:
    """Tests for _is_ambiguous_ticket_id helper function."""

    def test_bare_project_id_is_ambiguous(self):
        """Bare PROJECT-123 format is ambiguous."""
        from spec.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("PROJ-123") is True
        assert _is_ambiguous_ticket_id("ENG-456") is True
        assert _is_ambiguous_ticket_id("ABC-1") is True
        assert _is_ambiguous_ticket_id("A1-999") is True

    def test_url_is_not_ambiguous(self):
        """URLs are not ambiguous."""
        from spec.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("https://jira.example.com/browse/PROJ-123") is False
        assert _is_ambiguous_ticket_id("https://linear.app/team/issue/ENG-456") is False
        assert _is_ambiguous_ticket_id("http://example.com/ticket") is False

    def test_github_format_is_not_ambiguous(self):
        """GitHub format (owner/repo#123) is not ambiguous."""
        from spec.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("owner/repo#42") is False
        assert _is_ambiguous_ticket_id("my-org/my-repo#123") is False

    def test_invalid_formats_are_not_ambiguous(self):
        """Invalid formats are not considered ambiguous."""
        from spec.cli import _is_ambiguous_ticket_id

        assert _is_ambiguous_ticket_id("123") is False
        assert _is_ambiguous_ticket_id("just-text") is False
        assert _is_ambiguous_ticket_id("") is False

    def test_underscore_in_project_key_is_ambiguous(self):
        """Project keys with underscores (Jira-style) are ambiguous."""
        from spec.cli import _is_ambiguous_ticket_id

        # Jira supports underscores in project keys
        assert _is_ambiguous_ticket_id("MY_PROJ-123") is True
        assert _is_ambiguous_ticket_id("TEST_PROJECT-1") is True
        assert _is_ambiguous_ticket_id("A_B_C-999") is True


class TestResolveWithPlatformHint:
    """Tests for _resolve_with_platform_hint helper function."""

    def test_jira_keeps_bare_id(self):
        """Jira keeps bare ID as-is."""
        from spec.cli import _resolve_with_platform_hint
        from spec.integrations.providers import Platform

        result = _resolve_with_platform_hint("PROJ-123", Platform.JIRA)
        assert result == "PROJ-123"

    def test_linear_converts_to_url(self):
        """Linear converts to URL format."""
        from spec.cli import _resolve_with_platform_hint
        from spec.integrations.providers import Platform

        result = _resolve_with_platform_hint("ENG-456", Platform.LINEAR)
        assert result == "https://linear.app/team/issue/ENG-456"

    def test_github_keeps_bare_id(self):
        """GitHub keeps bare ID as-is (fallback behavior)."""
        from spec.cli import _resolve_with_platform_hint
        from spec.integrations.providers import Platform

        result = _resolve_with_platform_hint("owner/repo#42", Platform.GITHUB)
        assert result == "owner/repo#42"

    def test_other_platforms_keep_bare_id(self):
        """Other platforms keep bare ID as-is."""
        from spec.cli import _resolve_with_platform_hint
        from spec.integrations.providers import Platform

        result = _resolve_with_platform_hint("PROJ-123", Platform.AZURE_DEVOPS)
        assert result == "PROJ-123"


class TestDisambiguatePlatform:
    """Tests for _disambiguate_platform helper function."""

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_uses_config_default_when_set(self, mock_print, mock_prompt):
        """Uses config default_platform when set."""
        from spec.cli import _disambiguate_platform
        from spec.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = Platform.LINEAR

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.LINEAR
        mock_prompt.assert_not_called()

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_prompts_when_no_default(self, mock_print, mock_prompt):
        """Prompts user when no default_platform configured."""
        from spec.cli import _disambiguate_platform
        from spec.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        # Now uses kebab-case display names
        mock_prompt.return_value = "jira"

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.JIRA
        mock_prompt.assert_called_once()
        mock_print.assert_called_once()

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_prompt_linear_selection(self, mock_print, mock_prompt):
        """User selecting Linear from prompt returns Platform.LINEAR."""
        from spec.cli import _disambiguate_platform
        from spec.integrations.providers import Platform

        mock_config = MagicMock()
        mock_config.settings.get_default_platform.return_value = None
        # Now uses kebab-case display names
        mock_prompt.return_value = "linear"

        result = _disambiguate_platform("ENG-456", mock_config)

        assert result == Platform.LINEAR

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_uses_explicit_mapping_not_string_parsing(self, mock_print, mock_prompt):
        """Verifies _disambiguate_platform uses explicit dict mapping end-to-end.

        This test exercises the full flow:
        1. Prompt receives kebab-case choices (the mapping keys)
        2. Returning a choice string yields the correct Platform enum via mapping

        Why this matters: If the implementation used choice.upper() + Platform[...],
        it would fail for enums with underscores (e.g., "azure-devops".upper() gives
        "AZURE-DEVOPS", but the enum is AZURE_DEVOPS). Our mapping avoids this.
        """
        from spec.cli import AMBIGUOUS_PLATFORMS, _disambiguate_platform, _platform_display_name

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

    @patch("spec.ui.prompts.prompt_select")
    @patch("spec.cli.print_info")
    def test_prompt_choices_ordering_is_stable(self, mock_print, mock_prompt):
        """Prompt choices maintain stable ordering matching AMBIGUOUS_PLATFORMS.

        This ensures future changes (e.g., dict iteration order, set usage) don't
        accidentally alter the user-facing choice order.
        """
        from spec.cli import AMBIGUOUS_PLATFORMS, _disambiguate_platform, _platform_display_name

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
    """Integration tests for _fetch_ticket_async with mocked TicketService."""

    @pytest.mark.asyncio
    async def test_fetch_ticket_async_calls_ticket_service(self):
        """_fetch_ticket_async properly calls TicketService.get_ticket."""

        from spec.cli import _fetch_ticket_async
        from spec.integrations.providers import GenericTicket, Platform

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
            "spec.cli.create_ticket_service_from_config",
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
        """_fetch_ticket_async converts ambiguous ID to Linear URL when hint provided."""

        from spec.cli import _fetch_ticket_async
        from spec.integrations.providers import GenericTicket, Platform

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
            "spec.cli.create_ticket_service_from_config",
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
        """_fetch_ticket_async does not modify URL inputs even with platform hint."""

        from spec.cli import _fetch_ticket_async
        from spec.integrations.providers import GenericTicket, Platform

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
            "spec.cli.create_ticket_service_from_config",
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
    """Tests for run_async helper function."""

    def test_run_async_executes_coroutine_factory(self):
        """run_async executes a coroutine factory and returns its result."""
        from spec.cli import run_async

        async def sample_coro():
            return "test_result"

        # Now takes a factory (callable) instead of a coroutine
        result = run_async(lambda: sample_coro())
        assert result == "test_result"

    def test_run_async_raises_when_loop_running_without_creating_coroutine(self):
        """run_async raises AsyncLoopAlreadyRunningError without creating coroutine.

        The factory pattern ensures we check for a running loop BEFORE calling
        the factory, so no coroutine needs to be created and then closed.
        """
        import asyncio

        from spec.cli import AsyncLoopAlreadyRunningError, run_async

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
        """run_async calls the factory when no event loop is running."""
        from spec.cli import run_async

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
    """Tests verifying ambiguous IDs with --platform flag do not trigger prompts."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    @patch("spec.ui.prompts.prompt_select")
    def test_ambiguous_id_with_platform_flag_no_prompt(
        self, mock_prompt, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """Ambiguous ID with explicit --platform flag does not prompt user."""
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
        from spec.integrations.providers import Platform

        assert call_kwargs["platform"] == Platform.LINEAR


class TestInvalidDefaultPlatformWarning:
    """Tests for invalid default_platform config warning behavior."""

    def test_invalid_default_platform_logs_warning(self, caplog):
        """Invalid default_platform value logs a warning."""
        import logging

        from spec.config.settings import Settings

        settings = Settings(default_platform="invalid_platform")

        with caplog.at_level(logging.WARNING):
            result = settings.get_default_platform()

        assert result is None
        assert "Invalid DEFAULT_PLATFORM value" in caplog.text
        assert "invalid_platform" in caplog.text

    def test_valid_default_platform_no_warning(self, caplog):
        """Valid default_platform does not log a warning."""
        import logging

        from spec.config.settings import Settings

        settings = Settings(default_platform="jira")

        with caplog.at_level(logging.WARNING):
            result = settings.get_default_platform()

        from spec.integrations.providers import Platform

        assert result == Platform.JIRA
        assert "Invalid DEFAULT_PLATFORM value" not in caplog.text


class TestForceIntegrationCheckWarning:
    """Tests for force_integration_check flag warning."""

    @patch("spec.cli.is_git_repo")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.print_warning")
    def test_force_integration_check_prints_warning(
        self, mock_print_warning, mock_is_first_run, mock_is_git_repo
    ):
        """force_integration_check=True prints a warning about no effect."""
        from spec.cli import _check_prerequisites

        mock_is_git_repo.return_value = True
        mock_is_first_run.return_value = False

        mock_config = MagicMock()
        result = _check_prerequisites(mock_config, force_integration_check=True)

        assert result is True
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        assert "no effect" in warning_msg.lower() or "currently has no effect" in warning_msg

    @patch("spec.cli.is_git_repo")
    @patch("spec.cli.is_first_run")
    @patch("spec.cli.print_warning")
    def test_force_integration_check_false_no_warning(
        self, mock_print_warning, mock_is_first_run, mock_is_git_repo
    ):
        """force_integration_check=False does not print warning."""
        from spec.cli import _check_prerequisites

        mock_is_git_repo.return_value = True
        mock_is_first_run.return_value = False

        mock_config = MagicMock()
        result = _check_prerequisites(mock_config, force_integration_check=False)

        assert result is True
        mock_print_warning.assert_not_called()


class TestCLIProviderRegistryReset:
    """Tests for ProviderRegistry reset on CLI startup."""

    def setup_method(self):
        """Reset ProviderRegistry before each test."""
        from spec.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.reset_instances()

    def teardown_method(self):
        """Reset ProviderRegistry after each test."""
        from spec.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.reset_instances()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_main_menu")
    @patch("spec.cli.ConfigManager")
    def test_multi_run_clears_stale_config(
        self, mock_config_class, mock_menu, mock_prereq, mock_banner
    ):
        """CLI invoked twice clears stale config from first run.

        Verifies that running CLI initialization twice in the same process
        (first with a default Jira project set, then without) does not
        keep the old default - the key acceptance criteria for Task 1.
        """
        from spec.integrations.providers.registry import ProviderRegistry

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
    """Tests for create_ticket_service_from_config with dynamic backend resolution."""

    @pytest.mark.asyncio
    async def test_calls_resolve_backend_platform(self):
        """create_ticket_service_from_config calls resolve_backend_platform with correct args."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ) as mock_resolve,
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
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
        """create_ticket_service_from_config calls BackendFactory.create with resolved platform."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
            ),
        ):
            mock_factory_class.create.return_value = mock_backend

            service, backend = await create_ticket_service_from_config(
                config_manager=mock_config,
            )

        mock_factory_class.create.assert_called_once_with(mock_platform, verify_installed=True)

    @pytest.mark.asyncio
    async def test_returns_service_and_backend_tuple(self):
        """create_ticket_service_from_config returns (TicketService, AIBackend) tuple."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
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
        """cli_backend_override is forwarded to resolve_backend_platform."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ) as mock_resolve,
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
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
        """BackendNotConfiguredError propagates from resolve_backend_platform."""
        from spec.cli import create_ticket_service_from_config
        from spec.integrations.backends.errors import BackendNotConfiguredError

        mock_config = MagicMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform",
                side_effect=BackendNotConfiguredError("No backend configured"),
            ),
            pytest.raises(BackendNotConfiguredError, match="No backend configured"),
        ):
            await create_ticket_service_from_config(config_manager=mock_config)

    @pytest.mark.asyncio
    async def test_backend_not_installed_error_propagates(self):
        """BackendNotInstalledError propagates from BackendFactory.create."""
        from spec.cli import create_ticket_service_from_config
        from spec.integrations.backends.errors import BackendNotInstalledError

        mock_config = MagicMock()
        mock_platform = MagicMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            pytest.raises(BackendNotInstalledError, match="CLI not installed"),
        ):
            mock_factory_class.create.side_effect = BackendNotInstalledError("CLI not installed")
            await create_ticket_service_from_config(config_manager=mock_config)

    @pytest.mark.asyncio
    async def test_default_auth_manager_created_when_none(self):
        """AuthenticationManager is created from config when not provided."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
            ),
            patch("spec.cli.AuthenticationManager") as mock_auth_class,
        ):
            mock_factory_class.create.return_value = mock_backend

            await create_ticket_service_from_config(config_manager=mock_config)

        mock_auth_class.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_provided_auth_manager_used(self):
        """Provided auth_manager is used instead of creating a new one."""

        from spec.cli import create_ticket_service_from_config

        mock_config = MagicMock()
        mock_platform = MagicMock()
        mock_backend = MagicMock()
        mock_service = AsyncMock()
        mock_auth = MagicMock()

        with (
            patch(
                "spec.config.backend_resolver.resolve_backend_platform", return_value=mock_platform
            ),
            patch("spec.integrations.backends.factory.BackendFactory") as mock_factory_class,
            patch(
                "spec.cli.create_ticket_service", new_callable=AsyncMock, return_value=mock_service
            ) as mock_create,
            patch("spec.cli.AuthenticationManager") as mock_auth_class,
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
    """Tests for --backend CLI flag."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_backend_flag_passed_to_workflow(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """--backend flag is passed to _run_workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["--backend", "auggie", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] == "auggie"

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_backend_short_flag(self, mock_run, mock_prereq, mock_config_class, mock_banner):
        """-b shorthand works for --backend."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["-b", "claude", "TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] == "claude"

    @patch("spec.cli.show_banner")
    @patch("spec.cli.ConfigManager")
    @patch("spec.cli._check_prerequisites")
    @patch("spec.cli._run_workflow")
    def test_backend_none_when_not_provided(
        self, mock_run, mock_prereq, mock_config_class, mock_banner
    ):
        """No --backend flag passes None to workflow."""
        mock_prereq.return_value = True
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        runner.invoke(app, ["TEST-123"])

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["backend"] is None
