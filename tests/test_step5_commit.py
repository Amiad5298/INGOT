"""Tests for ingot.workflow.step5_commit module."""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.providers import GenericTicket, Platform
from ingot.ui.menus import CommitFailureChoice
from ingot.workflow.state import WorkflowState
from ingot.workflow.step5_commit import (
    Step5Result,
    _execute_commit,
    _generate_commit_message,
    _get_stageable_files,
    _show_diff_summary,
    _stage_files,
    step_5_commit,
)


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return GenericTicket(
        id="TEST-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description",
        branch_summary="test-feature",
    )


@pytest.fixture
def workflow_state(ticket):
    """Create a workflow state for testing."""
    state = WorkflowState(ticket=ticket)
    state.completed_tasks = ["Add user model", "Create API endpoint"]
    return state


class TestGenerateCommitMessage:
    def test_single_task_format(self):
        result = _generate_commit_message("TEST-123", ["Add user authentication"])
        assert result == "feat(TEST-123): Add user authentication"

    def test_multi_task_format(self):
        tasks = ["Add user model", "Create API endpoint", "Write tests"]
        result = _generate_commit_message("PROJ-456", tasks)
        assert result.startswith("feat(PROJ-456): implement 3 tasks")
        assert "- Add user model" in result
        assert "- Create API endpoint" in result
        assert "- Write tests" in result

    def test_two_tasks_uses_multi_format(self):
        result = _generate_commit_message("X-1", ["Task A", "Task B"])
        assert "implement 2 tasks" in result
        assert "- Task A" in result
        assert "- Task B" in result


class TestGetStageableFiles:
    """Tests use NUL-delimited (``-z``) porcelain format."""

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_filters_ingot_artifacts(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M src/main.py\0?? .ingot/runs/log.txt\0 M README.md\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "src/main.py" in stageable
        assert "README.md" in stageable
        assert ".ingot/runs/log.txt" in excluded

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_filters_augment_artifacts(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="?? .augment/agents/planner.md\0 M src/app.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "src/app.py" in stageable
        assert ".augment/agents/planner.md" in excluded

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_filters_specs_artifacts(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="?? specs/TEST-123-plan.md\0 M src/module.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "src/module.py" in stageable
        assert "specs/TEST-123-plan.md" in excluded

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_filters_ds_store(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="?? .DS_Store\0 M code.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "code.py" in stageable
        assert ".DS_Store" in excluded

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_filters_gitignore(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M .gitignore\0 M src/app.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "src/app.py" in stageable
        assert ".gitignore" in excluded

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_handles_rename_format(self, mock_run):
        # -z rename: "R  new_path\0old_path\0"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="R  new_name.py\0old_name.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "new_name.py" in stageable

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_handles_paths_with_spaces(self, mock_run):
        # -z format gives raw paths (no C-style quoting)
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M path with spaces/file.py\0",
        )

        stageable, excluded = _get_stageable_files()

        assert "path with spaces/file.py" in stageable

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_empty_status_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        stageable, excluded = _get_stageable_files()

        assert stageable == []
        assert excluded == []

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_error_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        stageable, excluded = _get_stageable_files()

        assert stageable == []
        assert excluded == []


class TestStageFiles:
    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_stages_files_successfully(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        assert _stage_files(["src/main.py", "src/utils.py"]) is True
        mock_run.assert_called_once_with(
            ["git", "add", "--", "src/main.py", "src/utils.py"],
            capture_output=True,
            text=True,
            check=False,
        )

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_returns_false_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)

        assert _stage_files(["src/main.py"]) is False

    def test_returns_false_for_empty_list(self):
        assert _stage_files([]) is False


class TestExecuteCommit:
    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_successful_commit(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="abc1234\n"),
        ]

        success, commit_hash = _execute_commit("feat(X): test")

        assert success is True
        assert commit_hash == "abc1234"

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_failed_commit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="pre-commit hook failed")

        success, error = _execute_commit("feat(X): test")

        assert success is False
        assert "pre-commit hook failed" in error

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_failed_commit_no_stderr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="")

        success, error = _execute_commit("feat(X): test")

        assert success is False
        assert error == "unknown error"


class TestShowDiffSummary:
    @patch("ingot.workflow.step5_commit.get_working_tree_diff_from_baseline")
    def test_uses_baseline_when_available(self, mock_baseline, workflow_state):
        workflow_state.diff_baseline_ref = "abc123"
        mock_baseline.return_value = ("3 files changed", False)

        result = _show_diff_summary(workflow_state)

        assert result == "3 files changed"

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_falls_back_to_git_diff_stat(self, mock_run, workflow_state):
        workflow_state.diff_baseline_ref = ""
        mock_run.return_value = MagicMock(returncode=0, stdout="2 files changed\n")

        result = _show_diff_summary(workflow_state)

        assert "2 files changed" in result

    @patch("ingot.workflow.step5_commit.subprocess.run")
    def test_falls_back_to_git_status_short(self, mock_run, workflow_state):
        workflow_state.diff_baseline_ref = ""
        # First call (git diff --stat) returns empty, second (git status --short) has output
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="?? new_file.py\n"),
        ]

        result = _show_diff_summary(workflow_state)

        assert "new_file.py" in result


class TestStep5Commit:
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_skips_when_no_changes(self, mock_changes, workflow_state):
        mock_changes.return_value = False

        result = step_5_commit(workflow_state)

        assert result.success is True
        assert result.committed is False
        assert result.skipped_reason == "no_changes"

    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_skips_when_only_artifacts(
        self, mock_changes, mock_diff, mock_stageable, workflow_state
    ):
        mock_changes.return_value = True
        mock_diff.return_value = "some diff"
        mock_stageable.return_value = ([], [".ingot/runs/log.txt", "specs/plan.md"])

        result = step_5_commit(workflow_state)

        assert result.committed is False
        assert result.skipped_reason == "artifacts_only"
        assert result.artifacts_excluded == 2

    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_skips_when_user_declines(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = "diff stat"
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = False

        result = step_5_commit(workflow_state)

        assert result.committed is False
        assert result.skipped_reason == "user_declined"

    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_happy_path_commit(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = "1 file changed"
        mock_stageable.return_value = (["src/main.py"], [".ingot/log.txt"])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = True
        mock_stage.return_value = True
        mock_commit.return_value = (True, "abc1234")

        result = step_5_commit(workflow_state)

        assert result.committed is True
        assert result.commit_hash == "abc1234"
        assert result.files_staged == 1
        assert result.artifacts_excluded == 1
        mock_stage.assert_called_once_with(["src/main.py"])

    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_custom_subject_line(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "fix(TEST-123): custom message"
        mock_confirm.return_value = True
        mock_stage.return_value = True
        mock_commit.return_value = (True, "def5678")

        result = step_5_commit(workflow_state)

        assert result.committed is True
        assert "custom message" in result.commit_message

    @patch("ingot.workflow.step5_commit.show_commit_failure_menu")
    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_retry_on_stage_failure_then_success(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        mock_menu,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = True
        # First stage fails, user retries, second succeeds
        mock_stage.side_effect = [False, True]
        mock_menu.return_value = CommitFailureChoice.RETRY
        mock_commit.return_value = (True, "abc1234")

        result = step_5_commit(workflow_state)

        assert result.committed is True
        assert mock_stage.call_count == 2
        mock_menu.assert_called_once()

    @patch("ingot.workflow.step5_commit.show_commit_failure_menu")
    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_retry_on_commit_failure_then_success(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        mock_menu,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = True
        mock_stage.return_value = True
        # First commit fails, user retries, second succeeds
        mock_commit.side_effect = [(False, "lock error"), (True, "abc1234")]
        mock_menu.return_value = CommitFailureChoice.RETRY

        result = step_5_commit(workflow_state)

        assert result.committed is True
        assert mock_commit.call_count == 2
        mock_menu.assert_called_once()

    @patch("ingot.workflow.step5_commit.show_commit_failure_menu")
    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_user_skips_after_commit_failure(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        mock_menu,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = True
        mock_stage.return_value = True
        mock_commit.return_value = (False, "pre-commit hook failed")
        mock_menu.return_value = CommitFailureChoice.SKIP

        result = step_5_commit(workflow_state)

        assert result.committed is False
        assert result.skipped_reason == "user_skipped"
        assert "pre-commit hook failed" in result.error_message

    @patch("ingot.workflow.step5_commit.show_commit_failure_menu")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_user_skips_after_stage_failure(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_menu,
        workflow_state,
    ):
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement 2 tasks"
        mock_confirm.return_value = True
        mock_stage.return_value = False
        mock_menu.return_value = CommitFailureChoice.SKIP

        result = step_5_commit(workflow_state)

        assert result.committed is False
        assert result.skipped_reason == "user_skipped"

    @patch("ingot.workflow.step5_commit._execute_commit")
    @patch("ingot.workflow.step5_commit._stage_files")
    @patch("ingot.workflow.step5_commit.prompt_confirm")
    @patch("ingot.workflow.step5_commit.prompt_input")
    @patch("ingot.workflow.step5_commit._get_stageable_files")
    @patch("ingot.workflow.step5_commit._show_diff_summary")
    @patch("ingot.workflow.step5_commit.has_any_changes")
    def test_uses_fallback_tasks_when_no_completed(
        self,
        mock_changes,
        mock_diff,
        mock_stageable,
        mock_input,
        mock_confirm,
        mock_stage,
        mock_commit,
        workflow_state,
    ):
        workflow_state.completed_tasks = []
        mock_changes.return_value = True
        mock_diff.return_value = ""
        mock_stageable.return_value = (["src/main.py"], [])
        mock_input.return_value = "feat(TEST-123): implement changes"
        mock_confirm.return_value = True
        mock_stage.return_value = True
        mock_commit.return_value = (True, "abc1234")

        result = step_5_commit(workflow_state)

        assert result.committed is True
        assert "implement changes" in result.commit_message

    def test_accepts_backend_parameter(self, workflow_state):
        """Verify step_5_commit accepts an optional backend parameter."""
        mock_backend = MagicMock()
        with patch("ingot.workflow.step5_commit.has_any_changes", return_value=False):
            result = step_5_commit(workflow_state, backend=mock_backend)

        assert result.skipped_reason == "no_changes"


class TestStep5Result:
    def test_defaults(self):
        result = Step5Result()
        assert result.success is True
        assert result.committed is False
        assert result.commit_hash == ""
        assert result.commit_message == ""
        assert result.skipped_reason == ""
        assert result.error_message == ""
        assert result.files_staged == 0
        assert result.artifacts_excluded == 0
