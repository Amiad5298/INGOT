"""Tests for specflow.workflow.step4_update_docs module."""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from specflow.integrations.git import DiffResult
from specflow.workflow.step4_update_docs import (
    step_4_update_docs,
    _build_doc_update_prompt,
    is_doc_file,
    Step4Result,
    FileSnapshot,
    NonDocSnapshot,
    MAX_DIFF_SIZE,
    DOC_FILE_EXTENSIONS,
)
from specflow.workflow.state import WorkflowState
from specflow.integrations.jira import JiraTicket


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description",
    )


@pytest.fixture
def workflow_state(ticket):
    """Create a workflow state for testing."""
    state = WorkflowState(ticket=ticket)
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

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_and_no_base_commit(
        self, mock_has_any_changes, mock_print_info, mock_print_header, ticket
    ):
        """Skips documentation update when no changes and no base commit."""
        mock_has_any_changes.return_value = False
        state = WorkflowState(ticket=ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state)

        assert isinstance(result, Step4Result)
        assert result.success
        mock_print_info.assert_called()

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_no_changes(
        self, mock_has_any_changes, mock_get_diff, mock_print_info, mock_print_header,
        workflow_state
    ):
        """Skips documentation update when diff has no changes."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="", has_error=False)

        result = step_4_update_docs(workflow_state)

        assert isinstance(result, Step4Result)
        assert result.success
        assert not result.agent_ran

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_diff_has_error(
        self, mock_has_any_changes, mock_get_diff, mock_print_warning, mock_print_header,
        workflow_state
    ):
        """Skips documentation update when diff computation fails."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(
            has_error=True, error_message="git diff failed"
        )

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

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_calls_auggie_with_diff(
        self, mock_has_any_changes, mock_get_diff, mock_print_success,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
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

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        mock_auggie_client.run_print_with_output.assert_called_once()
        call_kwargs = mock_auggie_client.run_print_with_output.call_args[1]
        assert call_kwargs["agent"] == "spec-doc-updater"
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for step_4_update_docs() - Agent failure
# =============================================================================


class TestStep4AgentFailure:
    """Tests for step_4_update_docs when agent fails."""

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_returns_success_when_agent_returns_failure_non_blocking(
        self, mock_has_any_changes, mock_get_diff, mock_print_warning,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state
    ):
        """Returns success (non-blocking) even when agent returns failure status."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (False, "Error occurred")

        result = step_4_update_docs(workflow_state, auggie_client=mock_client)

        # Step 4 is non-blocking - always returns success
        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert not result.docs_updated
        mock_print_warning.assert_called()

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_error")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_returns_success_when_agent_raises_exception(
        self, mock_has_any_changes, mock_get_diff, mock_print_error,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state
    ):
        """Returns success (non-blocking) when agent raises exception."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        mock_client = MagicMock()
        mock_client.run_print_with_output.side_effect = Exception("Agent crashed")

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

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.print_error")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_reverts_non_doc_changes_made_by_agent(
        self, mock_has_any_changes, mock_get_diff, mock_print_error, mock_print_warning,
        mock_print_success, mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
    ):
        """Reverts non-doc file changes made by the agent."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")

        # Simulate agent modifying a non-doc file
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/main.py"]
        mock_snapshot.revert_changes.return_value = ["src/main.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert isinstance(result, Step4Result)
        assert result.success
        assert result.agent_ran
        assert "src/main.py" in result.non_doc_reverted
        mock_snapshot.revert_changes.assert_called_once_with(["src/main.py"])
        # Violations should trigger error messages
        mock_print_error.assert_called()

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_no_revert_when_only_doc_files_changed(
        self, mock_has_any_changes, mock_get_diff, mock_print_success,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
    ):
        """Does not revert when agent only changes doc files."""
        mock_has_any_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")

        # No non-doc changes detected
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = []
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

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

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_runs_when_only_untracked_files_exist(
        self, mock_has_changes, mock_get_diff, mock_print_success,
        mock_print_info, mock_print_header, mock_snapshot_class,
        ticket, mock_auggie_client
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

        state = WorkflowState(ticket=ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state, auggie_client=mock_auggie_client)

        assert result.success
        assert result.agent_ran  # Agent should run!
        mock_auggie_client.run_print_with_output.assert_called_once()

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_skips_when_no_changes_at_all(
        self, mock_has_changes, mock_print_info, mock_print_header, ticket
    ):
        """Step 4 skips when there are truly no changes (including untracked)."""
        mock_has_changes.return_value = False

        state = WorkflowState(ticket=ticket)
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

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_falls_back_to_staged_unstaged_when_no_base_commit(
        self, mock_has_changes, mock_get_diff, mock_print_success,
        mock_print_info, mock_print_header, mock_snapshot_class,
        ticket, mock_auggie_client
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

        state = WorkflowState(ticket=ticket)
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

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.print_error")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_tracks_violations_in_result(
        self, mock_has_changes, mock_get_diff, mock_print_error, mock_print_warning,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
    ):
        """Result tracks had_violations flag when agent modifies non-doc files."""
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert result.success  # Still non-blocking
        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.print_error")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_tracks_failed_reverts(
        self, mock_has_changes, mock_get_diff, mock_print_error, mock_print_warning,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
    ):
        """Result tracks files that failed to revert."""
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py", "src/other.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]  # Only one reverted
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        result = step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        assert result.had_violations is True
        assert "src/code.py" in result.non_doc_reverted
        assert "src/other.py" in result.non_doc_revert_failed

    @patch("specflow.workflow.step4_update_docs.NonDocSnapshot")
    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.print_error")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.has_any_changes")
    def test_prints_error_banner_on_violations(
        self, mock_has_changes, mock_get_diff, mock_print_error, mock_print_warning,
        mock_print_info, mock_print_header, mock_snapshot_class,
        workflow_state, mock_auggie_client
    ):
        """Prints prominent error banner when violations occur."""
        mock_has_changes.return_value = True
        mock_get_diff.return_value = DiffResult(diff="diff content")
        mock_snapshot = MagicMock()
        mock_snapshot.detect_changes.return_value = ["src/code.py"]
        mock_snapshot.revert_changes.return_value = ["src/code.py"]
        mock_snapshot_class.capture_non_doc_state.return_value = mock_snapshot

        step_4_update_docs(workflow_state, auggie_client=mock_auggie_client)

        # Verify prominent error messages were printed
        error_calls = [str(c) for c in mock_print_error.call_args_list]
        error_text = " ".join(error_calls)
        assert "GUARDRAIL VIOLATION" in error_text or "VIOLATION" in error_text.upper()

