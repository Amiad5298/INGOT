"""Tests for spec.workflow.autofix module.

Tests cover:
- Prompt construction with review feedback and plan path
- Success/failure handling from AuggieClient
- Exception handling during auto-fix execution
- Backwards compatibility alias
"""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.jira import JiraTicket
from spec.workflow.autofix import _run_auto_fix, run_auto_fix
from spec.workflow.state import WorkflowState


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        title="Test ticket",
        description="Test description",
    )


@pytest.fixture
def workflow_state(ticket, tmp_path):
    """Create a test workflow state with valid paths."""
    state = WorkflowState(ticket=ticket)
    # Create the specs directory and plan file
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)
    plan_file = specs_dir / "TEST-123-plan.md"
    plan_file.write_text("# Implementation Plan\n\n## Tasks\n1. Do something")
    state.plan_file = plan_file
    return state


@pytest.fixture
def log_dir(tmp_path):
    """Create a test log directory."""
    log_path = tmp_path / "logs"
    log_path.mkdir(parents=True)
    return log_path


class TestRunAutoFix:
    """Tests for run_auto_fix function."""

    @patch("spec.workflow.autofix.AuggieClient")
    def test_returns_true_on_success(self, mock_client_class, workflow_state, log_dir):
        """Returns True when agent completes successfully."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Fixed all issues")
        mock_client_class.return_value = mock_client

        result = run_auto_fix(workflow_state, "Missing tests", log_dir)

        assert result is True
        mock_client.run_print_with_output.assert_called_once()

    @patch("spec.workflow.autofix.AuggieClient")
    def test_returns_false_on_agent_failure(self, mock_client_class, workflow_state, log_dir):
        """Returns False when agent reports failure."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (False, "Could not fix")
        mock_client_class.return_value = mock_client

        result = run_auto_fix(workflow_state, "Complex issues", log_dir)

        assert result is False

    @patch("spec.workflow.autofix.AuggieClient")
    def test_returns_false_on_exception(self, mock_client_class, workflow_state, log_dir):
        """Returns False when exception occurs."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.side_effect = RuntimeError("Connection failed")
        mock_client_class.return_value = mock_client

        result = run_auto_fix(workflow_state, "Some feedback", log_dir)

        assert result is False

    @patch("spec.workflow.autofix.AuggieClient")
    def test_prompt_contains_review_feedback(self, mock_client_class, workflow_state, log_dir):
        """Prompt includes the review feedback."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Done")
        mock_client_class.return_value = mock_client

        feedback = "[MISSING_TEST] Function foo() has no test coverage"
        run_auto_fix(workflow_state, feedback, log_dir)

        call_args = mock_client.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert feedback in prompt

    @patch("spec.workflow.autofix.AuggieClient")
    def test_prompt_contains_plan_path(self, mock_client_class, workflow_state, log_dir):
        """Prompt includes the plan path for context."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Done")
        mock_client_class.return_value = mock_client

        run_auto_fix(workflow_state, "Issues found", log_dir)

        call_args = mock_client.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert str(workflow_state.get_plan_path()) in prompt

    @patch("spec.workflow.autofix.AuggieClient")
    def test_uses_implementer_agent(self, mock_client_class, workflow_state, log_dir):
        """Uses the implementer agent from subagent_names."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Done")
        mock_client_class.return_value = mock_client

        run_auto_fix(workflow_state, "Fix this", log_dir)

        call_args = mock_client.run_print_with_output.call_args
        assert call_args[1]["agent"] == workflow_state.subagent_names["implementer"]
        assert call_args[1]["dont_save_session"] is True

    @patch("spec.workflow.autofix.AuggieClient")
    def test_prompt_includes_no_commit_instruction(self, mock_client_class, workflow_state, log_dir):
        """Prompt explicitly tells agent not to commit."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Done")
        mock_client_class.return_value = mock_client

        run_auto_fix(workflow_state, "Issues", log_dir)

        call_args = mock_client.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert "Do NOT commit" in prompt


class TestBackwardsCompatibility:
    """Tests for backwards compatibility alias."""

    def test_underscore_alias_is_same_function(self):
        """_run_auto_fix is an alias for run_auto_fix."""
        assert _run_auto_fix is run_auto_fix

