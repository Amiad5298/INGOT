"""Tests for spec.workflow.autofix module.

Tests cover:
- Prompt construction with review feedback and plan path
- Success/failure handling from AIBackend
- Exception handling during auto-fix execution
- Backwards compatibility alias
"""

import pytest

from spec.workflow.autofix import _run_auto_fix, run_auto_fix
from spec.workflow.state import WorkflowState


@pytest.fixture
def workflow_state(generic_ticket, tmp_path):
    """Create a test workflow state with valid paths using shared generic_ticket fixture."""
    state = WorkflowState(ticket=generic_ticket)
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

    def test_returns_true_on_success(self, mock_backend, workflow_state, log_dir):
        """Returns True when agent completes successfully."""
        mock_backend.run_print_with_output.return_value = (True, "Fixed all issues")

        result = run_auto_fix(workflow_state, "Missing tests", log_dir, mock_backend)

        assert result is True
        mock_backend.run_print_with_output.assert_called_once()

    def test_returns_false_on_agent_failure(self, mock_backend, workflow_state, log_dir):
        """Returns False when agent reports failure."""
        mock_backend.run_print_with_output.return_value = (False, "Could not fix")

        result = run_auto_fix(workflow_state, "Complex issues", log_dir, mock_backend)

        assert result is False

    def test_returns_false_on_exception(self, mock_backend, workflow_state, log_dir):
        """Returns False when exception occurs."""
        mock_backend.run_print_with_output.side_effect = RuntimeError("Connection failed")

        result = run_auto_fix(workflow_state, "Some feedback", log_dir, mock_backend)

        assert result is False

    def test_prompt_contains_review_feedback(self, mock_backend, workflow_state, log_dir):
        """Prompt includes the review feedback."""
        mock_backend.run_print_with_output.return_value = (True, "Done")

        feedback = "[MISSING_TEST] Function foo() has no test coverage"
        run_auto_fix(workflow_state, feedback, log_dir, mock_backend)

        call_args = mock_backend.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert feedback in prompt

    def test_prompt_contains_plan_path(self, mock_backend, workflow_state, log_dir):
        """Prompt includes the plan path for context."""
        mock_backend.run_print_with_output.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Issues found", log_dir, mock_backend)

        call_args = mock_backend.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert str(workflow_state.get_plan_path()) in prompt

    def test_uses_implementer_agent(self, mock_backend, workflow_state, log_dir):
        """Uses the implementer agent from subagent_names."""
        mock_backend.run_print_with_output.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Fix this", log_dir, mock_backend)

        call_args = mock_backend.run_print_with_output.call_args
        assert call_args[1]["subagent"] == workflow_state.subagent_names["implementer"]
        assert call_args[1]["dont_save_session"] is True

    def test_prompt_includes_no_commit_instruction(self, mock_backend, workflow_state, log_dir):
        """Prompt explicitly tells agent not to commit."""
        mock_backend.run_print_with_output.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Issues", log_dir, mock_backend)

        call_args = mock_backend.run_print_with_output.call_args
        prompt = call_args[0][0]
        assert "Do NOT commit" in prompt


class TestBackwardsCompatibility:
    """Tests for backwards compatibility alias."""

    def test_underscore_alias_is_same_function(self):
        """_run_auto_fix is an alias for run_auto_fix."""
        assert _run_auto_fix is run_auto_fix
