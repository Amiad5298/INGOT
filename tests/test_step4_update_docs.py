"""Tests for specflow.workflow.step4_update_docs module."""

import pytest
from unittest.mock import MagicMock, patch

from specflow.workflow.step4_update_docs import (
    step_4_update_docs,
    _build_doc_update_prompt,
    MAX_DIFF_SIZE,
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
    @patch("specflow.workflow.step4_update_docs.is_dirty")
    def test_skips_when_no_dirty_and_no_base_commit(
        self, mock_is_dirty, mock_print_info, mock_print_header, ticket
    ):
        """Skips documentation update when not dirty and no base commit."""
        mock_is_dirty.return_value = False
        state = WorkflowState(ticket=ticket)
        state.base_commit = ""  # No base commit

        result = step_4_update_docs(state)

        assert result is True
        mock_print_info.assert_called()

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.is_dirty")
    def test_skips_when_diff_is_empty(
        self, mock_is_dirty, mock_get_diff, mock_print_info, mock_print_header,
        workflow_state
    ):
        """Skips documentation update when diff is empty."""
        mock_is_dirty.return_value = True
        mock_get_diff.return_value = ""

        result = step_4_update_docs(workflow_state)

        assert result is True


# =============================================================================
# Tests for step_4_update_docs() - With changes
# =============================================================================


class TestStep4WithChanges:
    """Tests for step_4_update_docs when there are changes."""

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_success")
    @patch("specflow.workflow.step4_update_docs.AuggieClient")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.is_dirty")
    def test_calls_auggie_with_diff(
        self, mock_is_dirty, mock_get_diff, mock_auggie_class, mock_print_success,
        mock_print_info, mock_print_header, workflow_state
    ):
        """Calls AuggieClient with diff content when changes exist."""
        mock_is_dirty.return_value = True
        mock_get_diff.return_value = "diff --git a/file.py b/file.py\n+new line"
        mock_auggie = MagicMock()
        mock_auggie.run_print_with_output.return_value = (True, "Updated README.md")
        mock_auggie_class.return_value = mock_auggie

        result = step_4_update_docs(workflow_state)

        assert result is True
        mock_auggie.run_print_with_output.assert_called_once()
        call_kwargs = mock_auggie.run_print_with_output.call_args[1]
        assert call_kwargs["agent"] == "spec-doc-updater"
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for step_4_update_docs() - Agent failure
# =============================================================================


class TestStep4AgentFailure:
    """Tests for step_4_update_docs when agent fails."""

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.AuggieClient")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.is_dirty")
    def test_returns_true_when_agent_returns_failure_non_blocking(
        self, mock_is_dirty, mock_get_diff, mock_auggie_class, mock_print_warning,
        mock_print_info, mock_print_header, workflow_state
    ):
        """Returns True (non-blocking) even when agent returns failure status."""
        mock_is_dirty.return_value = True
        mock_get_diff.return_value = "diff content"
        mock_auggie = MagicMock()
        mock_auggie.run_print_with_output.return_value = (False, "Error occurred")
        mock_auggie_class.return_value = mock_auggie

        result = step_4_update_docs(workflow_state)

        # Step 4 is non-blocking - always returns True to not fail workflow
        assert result is True
        mock_print_warning.assert_called()

    @patch("specflow.workflow.step4_update_docs.print_header")
    @patch("specflow.workflow.step4_update_docs.print_info")
    @patch("specflow.workflow.step4_update_docs.print_warning")
    @patch("specflow.workflow.step4_update_docs.AuggieClient")
    @patch("specflow.workflow.step4_update_docs.get_diff_from_baseline")
    @patch("specflow.workflow.step4_update_docs.is_dirty")
    def test_returns_true_when_agent_raises_exception(
        self, mock_is_dirty, mock_get_diff, mock_auggie_class, mock_print_warning,
        mock_print_info, mock_print_header, workflow_state
    ):
        """Returns True (non-blocking) when agent raises exception."""
        mock_is_dirty.return_value = True
        mock_get_diff.return_value = "diff content"
        mock_auggie = MagicMock()
        mock_auggie.run_print_with_output.side_effect = Exception("Agent crashed")
        mock_auggie_class.return_value = mock_auggie

        result = step_4_update_docs(workflow_state)

        # Should return True to not block workflow
        assert result is True
        mock_print_warning.assert_called()


# =============================================================================
# Tests for _build_doc_update_prompt()
# =============================================================================


class TestBuildDocUpdatePrompt:
    """Tests for _build_doc_update_prompt function."""

    def test_includes_ticket_id(self, workflow_state):
        """Prompt includes ticket ID."""
        prompt = _build_doc_update_prompt(workflow_state, "diff content")
        assert "TEST-123" in prompt

    def test_includes_diff_content(self, workflow_state):
        """Prompt includes diff content."""
        diff = "diff --git a/file.py b/file.py\n+new line"
        prompt = _build_doc_update_prompt(workflow_state, diff)
        assert diff in prompt

    def test_truncates_large_diff(self, workflow_state):
        """Prompt truncates diff larger than MAX_DIFF_SIZE."""
        large_diff = "x" * (MAX_DIFF_SIZE + 1000)
        prompt = _build_doc_update_prompt(workflow_state, large_diff)

        # Should be truncated
        assert len(prompt) < len(large_diff) + 500
        assert "truncated" in prompt.lower()

    def test_includes_instructions(self, workflow_state):
        """Prompt includes instructions for the agent."""
        prompt = _build_doc_update_prompt(workflow_state, "diff")
        assert "Instructions" in prompt
        assert "README.md" in prompt

    def test_diff_exactly_at_max_size_not_truncated(self, workflow_state):
        """Diff exactly at MAX_DIFF_SIZE is not truncated."""
        exact_diff = "x" * MAX_DIFF_SIZE
        prompt = _build_doc_update_prompt(workflow_state, exact_diff)
        assert "truncated" not in prompt.lower()

