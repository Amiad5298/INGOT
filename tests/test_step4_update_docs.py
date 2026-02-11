"""Tests for ingot.workflow.step4_update_docs module."""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.git import DiffResult
from ingot.workflow.git_utils import parse_porcelain_z_output
from ingot.workflow.state import WorkflowState
from ingot.workflow.step4_update_docs import (
    MAX_DIFF_SIZE,
    NonDocSnapshot,
    Step4Result,
    _build_doc_update_prompt,
    is_doc_file,
    step_4_update_docs,
)


@pytest.fixture
def workflow_state(generic_ticket):
    """Create a workflow state for testing using shared generic_ticket fixture."""
    state = WorkflowState(ticket=generic_ticket)
    state.base_commit = "abc123"
    return state


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend."""
    backend = MagicMock()
    backend.run_print_with_output.return_value = (True, "Updated docs")
    backend.run_with_callback.return_value = (True, "Updated docs")
    return backend


class TestIsDocFile:
    def test_markdown_files_are_docs(self):
        assert is_doc_file("README.md")
        assert is_doc_file("docs/guide.md")
        assert is_doc_file("CHANGELOG.MD")

    def test_rst_files_are_docs(self):
        assert is_doc_file("index.rst")
        assert is_doc_file("docs/api.rst")

    def test_files_in_docs_dir_are_docs(self):
        assert is_doc_file("docs/config.yaml")
        assert is_doc_file("documentation/setup.py")

    def test_source_files_are_not_docs(self):
        assert not is_doc_file("main.py")
        assert not is_doc_file("src/utils.js")
        assert not is_doc_file("lib/helper.go")

    def test_config_files_are_not_docs(self):
        assert not is_doc_file("config.yaml")
        assert not is_doc_file("settings.json")
        assert not is_doc_file("pyproject.toml")


class TestParsePorcelainZOutput:
    """Tests for parse_porcelain_z_output (now in git_utils).

    Note: with -z, rename/copy entries use reversed field order vs the arrow
    format: the inline path is the NEW path, followed by OLD path after NUL.
    """

    def test_parses_empty_output(self):
        assert parse_porcelain_z_output("") == []

    def test_parses_single_modified_file(self):
        output = " M file.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [(" M", "file.py")]

    def test_parses_multiple_files(self):
        output = " M file1.py\0?? newfile.txt\0A  staged.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [(" M", "file1.py"), ("??", "newfile.txt"), ("A ", "staged.py")]

    def test_parses_file_with_spaces(self):
        output = " M file with spaces.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [(" M", "file with spaces.py")]

    def test_parses_renamed_file(self):
        # -z rename format: "R  new_path\0old_path\0" (new first, old second)
        output = "R  new_name.py\0old_name.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [("R ", "new_name.py")]

    def test_parses_copied_file(self):
        # -z copy format: "C  dest.py\0source.py\0" (dest first, source second)
        output = "C  copy.py\0source.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [("C ", "copy.py")]

    def test_parses_untracked_file(self):
        output = "?? untracked.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [("??", "untracked.py")]

    def test_handles_mixed_entries(self):
        output = " M regular.py\0R  new.py\0old.py\0?? untracked.py\0"
        result = parse_porcelain_z_output(output)
        assert result == [(" M", "regular.py"), ("R ", "new.py"), ("??", "untracked.py")]


class TestMaxDiffSize:
    def test_max_diff_size_is_positive(self):
        assert MAX_DIFF_SIZE > 0


class TestStep4NoChanges:
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_and_no_base_commit(
        self, mock_has_any_changes, mock_print_info, mock_print_header, generic_ticket
    ):
        mock_has_any_changes.return_value = False
        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state, backend=MagicMock())

        assert isinstance(result, Step4Result)
        assert result.success
        mock_print_info.assert_called()

    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_no_changes(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_info,
        mock_print_header,
        workflow_state,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="", has_error=False)

        result = step_4_update_docs(workflow_state, backend=MagicMock())

        assert isinstance(result, Step4Result)
        assert result.success
        assert not result.agent_ran

    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_error(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_warning,
        mock_print_header,
        workflow_state,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(has_error=True, error_message="git diff failed")

        result = step_4_update_docs(workflow_state, backend=MagicMock())

        assert isinstance(result, Step4Result)
        assert result.success  # Non-blocking
        assert not result.agent_ran
        assert "git diff failed" in result.error_message


class TestStep4WithChanges:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_success")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_calls_auggie_with_diff(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_success,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(
            diff="diff --git a/file.py b/file.py\n+new line",
            changed_files=["file.py"],
        )
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, backend=mock_backend)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        mock_backend.run_with_callback.assert_called_once()
        call_kwargs = mock_backend.run_with_callback.call_args[1]
        assert call_kwargs["subagent"] == "ingot-doc-updater"
        assert call_kwargs["dont_save_session"] is True


class TestStep4AgentFailure:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_returns_success_when_agent_returns_failure_non_blocking(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_warning,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (False, "Error occurred")

        result = step_4_update_docs(workflow_state, backend=mock_client)

        # Step 4 is non-blocking - always returns success
        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert not result.docs_updated
        mock_print_warning.assert_called()

    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_error")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_returns_success_when_agent_raises_exception(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_error,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        mock_client = MagicMock()
        mock_client.run_with_callback.side_effect = Exception("Agent crashed")

        result = step_4_update_docs(workflow_state, backend=mock_client)

        # Should return success to not block workflow
        assert isinstance(result, Step4Result)
        assert result.success
        assert "Agent crashed" in result.error_message
        mock_print_error.assert_called()


class TestStep4NonDocEnforcement:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_success")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.print_error")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_reverts_non_doc_changes_made_by_agent(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_error,
        mock_print_warning,
        mock_print_success,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")

        # Simulate agent modifying a non-doc file
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/main.py"]
        mock_snapshot.revert_changes.return_value = ["src/main.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, backend=mock_backend)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert "src/main.py" in result.non_doc_reverted
        mock_snapshot.revert_changes.assert_called_once_with(["src/main.py"])
        # Violations should trigger error messages
        mock_print_error.assert_called()

    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_success")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_no_revert_when_only_doc_files_changed(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_success,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")

        # No non-doc changes detected
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, backend=mock_backend)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.docs_updated
        assert result.non_doc_reverted == []
        mock_snapshot.revert_changes.assert_not_called()


class TestBuildDocUpdatePrompt:
    def test_includes_ticket_id(self, workflow_state):
        diff_result = DiffResult(diff="diff content")
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "TEST-123" in prompt

    def test_includes_diff_content(self, workflow_state):
        diff = "diff --git a/file.py b/file.py\n+new line"
        diff_result = DiffResult(diff=diff)
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert diff in prompt

    def test_truncates_large_diff(self, workflow_state):
        large_diff = "x" * (MAX_DIFF_SIZE + 1000)
        diff_result = DiffResult(diff=large_diff)
        prompt = _build_doc_update_prompt(workflow_state, diff_result)

        # Should be truncated
        assert len(prompt) < len(large_diff) + 1500
        assert "truncated" in prompt.lower()

    def test_includes_critical_restriction(self, workflow_state):
        diff_result = DiffResult(diff="diff")
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "CRITICAL RESTRICTION" in prompt
        assert "ONLY EDIT DOCUMENTATION FILES" in prompt
        assert "DO NOT EDIT" in prompt

    def test_includes_changed_files_when_diff_truncated(self, workflow_state):
        diff_result = DiffResult(
            diff="x" * (MAX_DIFF_SIZE + 100),
            changed_files=["src/main.py", "lib/utils.py"],
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Changed Files" in prompt
        assert "src/main.py" in prompt
        assert "lib/utils.py" in prompt

    def test_excludes_changed_files_when_diff_not_truncated(self, workflow_state):
        diff_result = DiffResult(
            diff="diff content",
            changed_files=["src/main.py", "lib/utils.py"],
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Changed Files" not in prompt

    def test_includes_diffstat_when_diff_truncated(self, workflow_state):
        diff_result = DiffResult(
            diff="x" * (MAX_DIFF_SIZE + 100),
            diffstat=" file.py | 10 +++++++---\n 1 file changed",
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Change Statistics" in prompt
        assert "10 +++++++" in prompt

    def test_excludes_diffstat_when_diff_not_truncated(self, workflow_state):
        diff_result = DiffResult(
            diff="diff content",
            diffstat=" file.py | 10 +++++++---\n 1 file changed",
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Change Statistics" not in prompt

    def test_includes_untracked_files(self, workflow_state):
        diff_result = DiffResult(
            diff="diff content",
            untracked_files=["new_file.txt", "another.md"],
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Untracked" in prompt
        assert "new_file.txt" in prompt


class TestStep4UntrackedOnly:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_success")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_runs_when_only_untracked_files_exist(
        self,
        mock_has_changes,
        mock_get_diff,
        mock_print_success,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        generic_ticket,
        mock_backend,
    ):
        mock_has_changes.return_value = True  # has_any_changes includes untracked
        mock_get_diff.return_value = DiffResult(
            diff="=== Untracked Files ===\ndiff --git a/new_file.txt",
            untracked_files=["new_file.txt"],
        )
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state, backend=mock_backend)

        assert result.success
        assert result.agent_ran  # Agent should run!
        mock_backend.run_with_callback.assert_called_once()

    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_at_all(
        self, mock_has_changes, mock_print_info, mock_print_header, generic_ticket
    ):
        mock_has_changes.return_value = False

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""

        result = step_4_update_docs(state, backend=MagicMock())

        assert result.success
        assert not result.agent_ran
        mock_print_info.assert_called()


class TestStep4MissingBaseCommit:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_success")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_falls_back_to_staged_unstaged_when_no_base_commit(
        self,
        mock_has_changes,
        mock_get_diff,
        mock_print_success,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        generic_ticket,
        mock_backend,
    ):
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(
            diff="=== Staged Changes ===\ndiff content\n\n=== Unstaged Changes ===\nmore diff",
            changed_files=["file.py"],
        )
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""

        result = step_4_update_docs(state, backend=mock_backend)

        assert result.success
        assert result.agent_ran
        # Verify get_diff_from_baseline was called with empty string
        mock_get_diff.assert_called_once_with("")


class TestStep4ViolationTracking:
    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.print_error")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_tracks_violations_in_result(
        self,
        mock_has_changes,
        mock_get_diff,
        mock_print_error,
        mock_print_warning,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, backend=mock_backend)

        assert result.success  # Still non-blocking
        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted

    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.print_error")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_tracks_failed_reverts(
        self,
        mock_has_changes,
        mock_get_diff,
        mock_print_error,
        mock_print_warning,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py", "src/other.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]  # Only one reverted
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, backend=mock_backend)

        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted
        assert "src/other.py" in result.non_doc_revert_failed

    @patch("ingot.ui.tui.TaskRunnerUI")
    @patch("ingot.workflow.step4_update_docs.NonDocSnapshot")
    @patch("ingot.workflow.step4_update_docs.print_header")
    @patch("ingot.workflow.step4_update_docs.print_info")
    @patch("ingot.workflow.step4_update_docs.print_warning")
    @patch("ingot.workflow.step4_update_docs.print_error")
    @patch("ingot.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("ingot.workflow.step4_update_docs.has_any_changes")
    def test_prints_error_banner_on_violations(
        self,
        mock_has_changes,
        mock_get_diff,
        mock_print_error,
        mock_print_warning,
        mock_print_info,
        mock_print_header,
        mock_snapshot_class,
        mock_ui_class,
        workflow_state,
        mock_backend,
    ):
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Configure mock backend to use run_with_callback (TUI mode)
        mock_backend.run_with_callback.return_value = (True, "Updated docs")

        step_4_update_docs(workflow_state, backend=mock_backend)

        # Verify prominent error messages were printed
        error_calls = [str(c) for c in mock_print_error.call_args_list]
        error_text = " ".join(error_calls)
        assert "GUARDRAIL VIOLATION" in error_text or "VIOLATION" in error_text.upper()


class TestIsDocFileGithubSubstring:
    def test_github_readme_scripts_is_not_doc(self):
        assert not is_doc_file(".github/readme-scripts/tool.py")
        assert not is_doc_file(".github/readme-generator/build.js")
        assert not is_doc_file(".github/contributing-bot/index.ts")

    def test_github_issue_template_is_doc(self):
        assert is_doc_file(".github/ISSUE_TEMPLATE/bug_report.md")
        assert is_doc_file(".github/issue_template/feature_request.md")

    def test_github_workflows_md_is_not_doc(self):
        assert not is_doc_file(".github/workflows/ci.md")
        assert not is_doc_file(".github/workflows/README.md")

    def test_github_readme_direct_is_doc(self):
        assert is_doc_file(".github/README.md")
        assert is_doc_file(".github/CONTRIBUTING.md")

    def test_github_funding_is_doc(self):
        assert is_doc_file(".github/FUNDING.yml")


class TestNonDocSnapshotGuardrailFixes:
    def test_new_untracked_non_doc_file_is_deleted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create a file (simulating agent creating it)
        new_file = tmp_path / "new_code.py"
        new_file.write_text("print('created by agent')")

        # Create snapshot (starts empty - file didn't exist before Step 4)
        snapshot = NonDocSnapshot()

        # Mock subprocess.run for detect_changes() - reports new untracked file
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="?? new_code.py\0")

            changed = snapshot.detect_changes()

        # Should detect the new file
        assert "new_code.py" in changed

        # Check snapshot was created with correct flags
        assert "new_code.py" in snapshot.snapshots
        file_snap = snapshot.snapshots["new_code.py"]
        assert file_snap.was_untracked is True
        assert file_snap.existed is False  # A1 FIX: should be False for new files

        # Revert should delete the file
        reverted = snapshot.revert_changes(["new_code.py"])

        assert "new_code.py" in reverted
        assert not new_file.exists()  # File should be deleted

    def test_preexisting_untracked_file_modified_is_restored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create original file
        scratch_file = tmp_path / "scratch.py"
        scratch_file.write_text("ORIGINAL")

        # Mock for capture_non_doc_state - file is untracked
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="?? scratch.py\0")
            snapshot = NonDocSnapshot.capture_non_doc_state()

        # Verify snapshot captured the content
        assert "scratch.py" in snapshot.snapshots
        assert snapshot.snapshots["scratch.py"].content == b"ORIGINAL"
        assert snapshot.snapshots["scratch.py"].was_untracked is True
        assert snapshot.snapshots["scratch.py"].existed is True

        # Modify the file (simulating agent modification)
        scratch_file.write_text("MODIFIED")

        # Mock for detect_changes - file still shows as untracked
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="?? scratch.py\0")
            changed = snapshot.detect_changes()

        # Should detect the change (A2 fix)
        assert "scratch.py" in changed

        # Revert should restore original content
        reverted = snapshot.revert_changes(["scratch.py"])

        assert "scratch.py" in reverted
        assert scratch_file.exists()  # File should still exist
        assert scratch_file.read_text() == "ORIGINAL"  # Content restored

    def test_prestep_tracked_deletion_is_enforced(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Scenario: tracked file was deleted before Step 4
        # Simulate by creating snapshot where file didn't exist (deleted state)

        # Mock for capture_non_doc_state - file shows as deleted ("D " or " D")
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=" D src/foo.py\0",  # Deleted in worktree
            )
            snapshot = NonDocSnapshot.capture_non_doc_state()

        # Verify snapshot: file was deleted so existed=False, content=None
        assert "src/foo.py" in snapshot.snapshots
        file_snap = snapshot.snapshots["src/foo.py"]
        assert file_snap.existed is False
        assert file_snap.content is None

        # Agent recreates the file
        src_dir = tmp_path / "src"
        src_dir.mkdir(exist_ok=True)
        recreated_file = src_dir / "foo.py"
        recreated_file.write_text("agent recreated this")

        # Mock for detect_changes
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",  # File might show as modified or nothing
            )
            changed = snapshot.detect_changes()

        # Should detect the recreated file (A3 fix: existed=False but file exists now)
        assert "src/foo.py" in changed

        # Mock _git_restore_file and verify it's NOT called
        with patch("ingot.workflow.step4_update_docs._git_restore_file") as mock_restore:
            reverted = snapshot.revert_changes(["src/foo.py"])

            # Should NOT call git restore (A3 fix)
            mock_restore.assert_not_called()

        # File should be deleted (restoring the "deleted" state)
        assert "src/foo.py" in reverted
        assert not recreated_file.exists()

    def test_clean_tracked_file_modified_by_agent_uses_git_restore(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create the file (simulating a tracked file that exists)
        src_dir = tmp_path / "src"
        src_dir.mkdir(exist_ok=True)
        tracked_file = src_dir / "code.py"
        tracked_file.write_text("original content from repo")

        # Create snapshot (starts empty - no dirty or untracked files before Step 4)
        snapshot = NonDocSnapshot()

        # Mock subprocess.run for detect_changes() - reports modified tracked file
        # " M" = modified in worktree (unstaged modification of tracked file)
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=" M src/code.py\0")

            changed = snapshot.detect_changes()

        # Should detect the changed file
        assert "src/code.py" in changed

        # Check snapshot was created with correct flags
        assert "src/code.py" in snapshot.snapshots
        file_snap = snapshot.snapshots["src/code.py"]
        assert file_snap.was_untracked is False  # It's tracked
        assert file_snap.was_dirty is False  # It wasn't dirty before agent ran
        # CRITICAL: existed=True for tracked files so git restore is used
        assert file_snap.existed is True

        # Revert should call git restore (not delete the file)
        with patch("ingot.workflow.step4_update_docs._git_restore_file") as mock_restore:
            mock_restore.return_value = True  # git restore succeeds

            reverted = snapshot.revert_changes(["src/code.py"])

            # MUST call git restore for tracked files
            mock_restore.assert_called_once_with("src/code.py")

        assert "src/code.py" in reverted
        # File should still exist (not deleted)
        assert tracked_file.exists()

    def test_rename_status_both_paths_handled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create snapshot (starts empty)
        snapshot = NonDocSnapshot()

        # Mock subprocess.run for detect_changes() - reports renamed file
        # -z rename format: "R  new_path\0old_path\0" (new first, old second)
        with patch("ingot.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="R  new_name.py\0old_name.py\0")

            changed = snapshot.detect_changes()

        # Should detect the new path from rename
        assert "new_name.py" in changed

        # Snapshot should have the new name with existed=True (tracked)
        assert "new_name.py" in snapshot.snapshots
        file_snap = snapshot.snapshots["new_name.py"]
        assert file_snap.was_untracked is False  # Renames are tracked
        assert file_snap.existed is True  # Tracked files use git restore
