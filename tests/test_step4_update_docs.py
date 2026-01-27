"""Tests for spec.workflow.step4_update_docs module."""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.git import DiffResult
from spec.workflow.state import WorkflowState
from spec.workflow.step4_update_docs import (
    MAX_DIFF_SIZE,
    NonDocSnapshot,
    Step4Result,
    _build_doc_update_prompt,
    _parse_porcelain_z_output,
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
def mock_auggie_client():
    """Create a mock AuggieClient."""
    client = MagicMock()
    client.run_print_with_output.return_value = (True, "Updated docs")
    return client


# =============================================================================
# Tests for is_doc_file()
# =============================================================================


class TestIsDocFile:
    """Tests for is_doc_file function."""

    def test_markdown_files_are_docs(self):
        """Markdown files are documentation."""
        assert is_doc_file("README.md")
        assert is_doc_file("docs/guide.md")
        assert is_doc_file("CHANGELOG.MD")

    def test_rst_files_are_docs(self):
        """RST files are documentation."""
        assert is_doc_file("index.rst")
        assert is_doc_file("docs/api.rst")

    def test_files_in_docs_dir_are_docs(self):
        """Files in docs/ directory are documentation."""
        assert is_doc_file("docs/config.yaml")
        assert is_doc_file("documentation/setup.py")

    def test_source_files_are_not_docs(self):
        """Source code files are not documentation."""
        assert not is_doc_file("main.py")
        assert not is_doc_file("src/utils.js")
        assert not is_doc_file("lib/helper.go")

    def test_config_files_are_not_docs(self):
        """Config files are not documentation."""
        assert not is_doc_file("config.yaml")
        assert not is_doc_file("settings.json")
        assert not is_doc_file("pyproject.toml")


# =============================================================================
# Tests for _parse_porcelain_z_output helper
# =============================================================================


class TestParsePorcelainZOutput:
    """Tests for _parse_porcelain_z_output helper function."""

    def test_parses_empty_output(self):
        """Returns empty list for empty output."""
        assert _parse_porcelain_z_output("") == []

    def test_parses_single_modified_file(self):
        """Parses a single modified file."""
        # Format: "XY path\0"
        output = " M file.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [(" M", "file.py")]

    def test_parses_multiple_files(self):
        """Parses multiple files."""
        output = " M file1.py\0?? newfile.txt\0A  staged.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [(" M", "file1.py"), ("??", "newfile.txt"), ("A ", "staged.py")]

    def test_parses_file_with_spaces(self):
        """Correctly parses filenames with spaces."""
        output = " M file with spaces.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [(" M", "file with spaces.py")]

    def test_parses_renamed_file(self):
        """Parses renamed files (R status) - returns new path."""
        # For renames: "R  old_path\0new_path\0"
        output = "R  old_name.py\0new_name.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [("R ", "new_name.py")]

    def test_parses_copied_file(self):
        """Parses copied files (C status) - returns new path."""
        output = "C  source.py\0copy.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [("C ", "copy.py")]

    def test_parses_untracked_file(self):
        """Parses untracked files."""
        output = "?? untracked.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [("??", "untracked.py")]

    def test_handles_mixed_entries(self):
        """Handles mix of regular and renamed files."""
        output = " M regular.py\0R  old.py\0new.py\0?? untracked.py\0"
        result = _parse_porcelain_z_output(output)
        assert result == [(" M", "regular.py"), ("R ", "new.py"), ("??", "untracked.py")]


# =============================================================================
# Tests for MAX_DIFF_SIZE constant
# =============================================================================


class TestMaxDiffSize:
    """Tests for MAX_DIFF_SIZE constant."""

    def test_max_diff_size_is_8000(self):
        """MAX_DIFF_SIZE is 8000."""
        assert MAX_DIFF_SIZE == 8000


# =============================================================================
# Tests for step_4_update_docs() - No changes
# =============================================================================


class TestStep4NoChanges:
    """Tests for step_4_update_docs when there are no changes."""

    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_and_no_base_commit(
        self, mock_has_any_changes, mock_print_info, mock_print_header, generic_ticket
    ):
        """Skips documentation update when no changes and no base commit."""
        mock_has_any_changes.return_value = False
        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state)

        assert isinstance(result, Step4Result)
        assert result.success
        mock_print_info.assert_called()

    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_no_changes(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_info,
        mock_print_header,
        workflow_state,
    ):
        """Skips documentation update when diff has no changes."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="", has_error=False)

        result = step_4_update_docs(workflow_state)

        assert isinstance(result, Step4Result)
        assert result.success
        assert not result.agent_ran

    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_error(
        self,
        mock_has_any_changes,
        mock_get_diff,
        mock_print_warning,
        mock_print_header,
        workflow_state,
    ):
        """Skips documentation update when diff computation fails."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(has_error=True, error_message="git diff failed")

        result = step_4_update_docs(workflow_state)

        assert isinstance(result, Step4Result)
        assert result.success  # Non-blocking
        assert not result.agent_ran
        assert "git diff failed" in result.error_message


# =============================================================================
# Tests for step_4_update_docs() - With changes
# =============================================================================


class TestStep4WithChanges:
    """Tests for step_4_update_docs when there are changes."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_success")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Calls AuggieClient with diff content when changes exist."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        mock_auggie_client.run_with_callback.assert_called_once()
        call_kwargs = mock_auggie_client.run_with_callback.call_args[1]
        assert call_kwargs["agent"] == "spec-doc-updater"
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for step_4_update_docs() - Agent failure
# =============================================================================


class TestStep4AgentFailure:
    """Tests for step_4_update_docs when agent fails."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        """Returns success (non-blocking) even when agent returns failure status."""
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

        result = step_4_update_docs(workflow_state, auggie_client=mock_client)

        # Step 4 is non-blocking - always returns success
        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert not result.docs_updated
        mock_print_warning.assert_called()

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_error")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        """Returns success (non-blocking) when agent raises exception."""
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

        result = step_4_update_docs(workflow_state, auggie_client=mock_client)

        # Should return success to not block workflow
        assert isinstance(result, Step4Result)
        assert result.success
        assert "Agent crashed" in result.error_message
        mock_print_error.assert_called()


# =============================================================================
# Tests for step_4_update_docs() - Non-doc enforcement
# =============================================================================


class TestStep4NonDocEnforcement:
    """Tests for non-documentation file change enforcement."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_success")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.print_error")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Reverts non-doc file changes made by the agent."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert "src/main.py" in result.non_doc_reverted
        mock_snapshot.revert_changes.assert_called_once_with(["src/main.py"])
        # Violations should trigger error messages
        mock_print_error.assert_called()

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_success")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Does not revert when agent only changes doc files."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.docs_updated
        assert result.non_doc_reverted == []
        mock_snapshot.revert_changes.assert_not_called()


# =============================================================================
# Tests for _build_doc_update_prompt()
# =============================================================================


class TestBuildDocUpdatePrompt:
    """Tests for _build_doc_update_prompt function."""

    def test_includes_ticket_id(self, workflow_state):
        """Prompt includes ticket ID."""
        diff_result = DiffResult(diff="diff content")
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "TEST-123" in prompt

    def test_includes_diff_content(self, workflow_state):
        """Prompt includes diff content."""
        diff = "diff --git a/file.py b/file.py\n+new line"
        diff_result = DiffResult(diff=diff)
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert diff in prompt

    def test_truncates_large_diff(self, workflow_state):
        """Prompt truncates diff larger than MAX_DIFF_SIZE."""
        large_diff = "x" * (MAX_DIFF_SIZE + 1000)
        diff_result = DiffResult(diff=large_diff)
        prompt = _build_doc_update_prompt(workflow_state, diff_result)

        # Should be truncated
        assert len(prompt) < len(large_diff) + 1500
        assert "truncated" in prompt.lower()

    def test_includes_critical_restriction(self, workflow_state):
        """Prompt includes critical restriction about doc-only edits."""
        diff_result = DiffResult(diff="diff")
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "CRITICAL RESTRICTION" in prompt
        assert "ONLY EDIT DOCUMENTATION FILES" in prompt
        assert "DO NOT EDIT" in prompt

    def test_includes_changed_files_list(self, workflow_state):
        """Prompt includes list of changed files."""
        diff_result = DiffResult(
            diff="diff content",
            changed_files=["src/main.py", "lib/utils.py"],
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Changed Files" in prompt
        assert "src/main.py" in prompt
        assert "lib/utils.py" in prompt

    def test_includes_diffstat(self, workflow_state):
        """Prompt includes diffstat summary."""
        diff_result = DiffResult(
            diff="diff content",
            diffstat=" file.py | 10 +++++++---\n 1 file changed",
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Change Statistics" in prompt
        assert "10 +++++++" in prompt

    def test_includes_untracked_files(self, workflow_state):
        """Prompt includes untracked files list."""
        diff_result = DiffResult(
            diff="diff content",
            untracked_files=["new_file.txt", "another.md"],
        )
        prompt = _build_doc_update_prompt(workflow_state, diff_result)
        assert "Untracked" in prompt
        assert "new_file.txt" in prompt


# =============================================================================
# Tests for untracked-only scenarios
# =============================================================================


class TestStep4UntrackedOnly:
    """Tests for Step 4 with only untracked files (no staged/unstaged)."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_success")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Step 4 runs when only untracked files exist (not staged/unstaged)."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state, auggie_client=mock_auggie_client)

        assert result.success
        assert result.agent_ran  # Agent should run!
        mock_auggie_client.run_with_callback.assert_called_once()

    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_at_all(
        self, mock_has_changes, mock_print_info, mock_print_header, generic_ticket
    ):
        """Step 4 skips when there are truly no changes (including untracked)."""
        mock_has_changes.return_value = False

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""

        result = step_4_update_docs(state)

        assert result.success
        assert not result.agent_ran
        mock_print_info.assert_called()


# =============================================================================
# Tests for missing base_commit with dirty repo
# =============================================================================


class TestStep4MissingBaseCommit:
    """Tests for Step 4 when base_commit is missing but repo is dirty."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_success")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Uses staged+unstaged+untracked when base_commit is empty."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        state = WorkflowState(ticket=generic_ticket)
        state.base_commit = ""

        result = step_4_update_docs(state, auggie_client=mock_auggie_client)

        assert result.success
        assert result.agent_ran
        # Verify get_diff_from_baseline was called with empty string
        mock_get_diff.assert_called_once_with("")


# =============================================================================
# Tests for violation tracking and visibility
# =============================================================================


class TestStep4ViolationTracking:
    """Tests for non-doc violation tracking and visibility."""

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.print_error")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Result tracks had_violations flag when agent modifies non-doc files."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert result.success  # Still non-blocking
        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.print_error")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Result tracks files that failed to revert."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted
        assert "src/other.py" in result.non_doc_revert_failed

    @patch("spec.ui.tui.TaskRunnerUI")
    @patch("spec.workflow.step4_update_docs.NonDocSnapshot")
    @patch("spec.workflow.step4_update_docs.print_header")
    @patch("spec.workflow.step4_update_docs.print_info")
    @patch("spec.workflow.step4_update_docs.print_warning")
    @patch("spec.workflow.step4_update_docs.print_error")
    @patch("spec.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("spec.workflow.step4_update_docs.has_any_changes")
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
        mock_auggie_client,
    ):
        """Prints prominent error banner when violations occur."""
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

        # Configure mock client to use run_with_callback (TUI mode)
        mock_auggie_client.run_with_callback.return_value = (True, "Updated docs")

        step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        # Verify prominent error messages were printed
        error_calls = [str(c) for c in mock_print_error.call_args_list]
        error_text = " ".join(error_calls)
        assert "GUARDRAIL VIOLATION" in error_text or "VIOLATION" in error_text.upper()


# =============================================================================
# Tests for is_doc_file .github/ substring false positives (E2)
# =============================================================================


class TestIsDocFileGithubSubstring:
    """Regression tests for .github/ path substring matching bugs."""

    def test_github_readme_scripts_is_not_doc(self):
        """Files in .github/readme-scripts/ should NOT be docs (substring regression)."""
        assert not is_doc_file(".github/readme-scripts/tool.py")
        assert not is_doc_file(".github/readme-generator/build.js")
        assert not is_doc_file(".github/contributing-bot/index.ts")

    def test_github_issue_template_is_doc(self):
        """ISSUE_TEMPLATE files should be docs."""
        assert is_doc_file(".github/ISSUE_TEMPLATE/bug_report.md")
        assert is_doc_file(".github/issue_template/feature_request.md")

    def test_github_workflows_md_is_not_doc(self):
        """Even .md files in .github/workflows/ are NOT docs."""
        assert not is_doc_file(".github/workflows/ci.md")
        assert not is_doc_file(".github/workflows/README.md")

    def test_github_readme_direct_is_doc(self):
        """Direct README files in .github/ are docs."""
        assert is_doc_file(".github/README.md")
        assert is_doc_file(".github/CONTRIBUTING.md")

    def test_github_funding_is_doc(self):
        """FUNDING files in .github/ are docs."""
        assert is_doc_file(".github/FUNDING.yml")


# =============================================================================
# Tests for NonDocSnapshot guardrail correctness (D1, D2, D3)
# =============================================================================


class TestNonDocSnapshotGuardrailFixes:
    """Tests for guardrail enforcement correctness (A1, A2, A3 fixes)."""

    def test_new_untracked_non_doc_file_is_deleted(self, tmp_path, monkeypatch):
        """D1: New untracked non-doc file created by agent is deleted."""
        monkeypatch.chdir(tmp_path)

        # Create a file (simulating agent creating it)
        new_file = tmp_path / "new_code.py"
        new_file.write_text("print('created by agent')")

        # Create snapshot (starts empty - file didn't exist before Step 4)
        snapshot = NonDocSnapshot()

        # Mock subprocess.run for detect_changes() - reports new untracked file
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
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
        """D2: Pre-existing untracked non-doc file modified is detected and restored."""
        monkeypatch.chdir(tmp_path)

        # Create original file
        scratch_file = tmp_path / "scratch.py"
        scratch_file.write_text("ORIGINAL")

        # Mock for capture_non_doc_state - file is untracked
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
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
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
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
        """D3: Pre-step tracked deletion is enforced - recreated file removed, no git restore."""
        monkeypatch.chdir(tmp_path)

        # Scenario: tracked file was deleted before Step 4
        # Simulate by creating snapshot where file didn't exist (deleted state)

        # Mock for capture_non_doc_state - file shows as deleted ("D " or " D")
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
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
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",  # File might show as modified or nothing
            )
            changed = snapshot.detect_changes()

        # Should detect the recreated file (A3 fix: existed=False but file exists now)
        assert "src/foo.py" in changed

        # Mock _git_restore_file and verify it's NOT called
        with patch("spec.workflow.step4_update_docs._git_restore_file") as mock_restore:
            reverted = snapshot.revert_changes(["src/foo.py"])

            # Should NOT call git restore (A3 fix)
            mock_restore.assert_not_called()

        # File should be deleted (restoring the "deleted" state)
        assert "src/foo.py" in reverted
        assert not recreated_file.exists()

    def test_clean_tracked_file_modified_by_agent_uses_git_restore(self, tmp_path, monkeypatch):
        """CRITICAL FIX: Clean tracked file modified by agent is reverted with git restore, NOT deleted.

        Scenario:
        - Pre-step4 repo is clean (snapshot has no entry for src/code.py)
        - Agent modifies src/code.py (git status shows ' M src/code.py')

        Expected:
        - detect_changes returns ["src/code.py"]
        - revert_changes calls _git_restore_file("src/code.py")
        - File is NOT deleted
        """
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
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
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
        with patch("spec.workflow.step4_update_docs._git_restore_file") as mock_restore:
            mock_restore.return_value = True  # git restore succeeds

            reverted = snapshot.revert_changes(["src/code.py"])

            # MUST call git restore for tracked files
            mock_restore.assert_called_once_with("src/code.py")

        assert "src/code.py" in reverted
        # File should still exist (not deleted)
        assert tracked_file.exists()

    def test_rename_status_both_paths_handled(self, tmp_path, monkeypatch):
        """Optional hardening: Rename status restores correctly."""
        monkeypatch.chdir(tmp_path)

        # Create snapshot (starts empty)
        snapshot = NonDocSnapshot()

        # Mock subprocess.run for detect_changes() - reports renamed file
        with patch("spec.workflow.step4_update_docs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="R  old_name.py\0new_name.py\0")

            changed = snapshot.detect_changes()

        # Should detect the new path from rename
        assert "new_name.py" in changed

        # Snapshot should have the new name with existed=True (tracked)
        assert "new_name.py" in snapshot.snapshots
        file_snap = snapshot.snapshots["new_name.py"]
        assert file_snap.was_untracked is False  # Renames are tracked
        assert file_snap.existed is True  # Tracked files use git restore
