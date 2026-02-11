"""Tests for ingot.workflow.autofix module.

Tests cover:
- Prompt construction with review feedback and plan path
- Success/failure handling from AIBackend
- Exception handling during auto-fix execution
- Backwards compatibility alias
"""

import pytest

from ingot.workflow.autofix import _MAX_REVIEW_FEEDBACK_LENGTH, _run_auto_fix, run_auto_fix
from ingot.workflow.state import WorkflowState


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
    def test_returns_true_on_success(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Fixed all issues")

        result = run_auto_fix(workflow_state, "Missing tests", log_dir, mock_backend)

        assert result is True
        mock_backend.run_with_callback.assert_called_once()

    def test_returns_false_on_agent_failure(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (False, "Could not fix")

        result = run_auto_fix(workflow_state, "Complex issues", log_dir, mock_backend)

        assert result is False

    def test_returns_false_on_exception(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.side_effect = RuntimeError("Connection failed")

        result = run_auto_fix(workflow_state, "Some feedback", log_dir, mock_backend)

        assert result is False

    def test_prompt_contains_review_feedback(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        feedback = "[MISSING_TEST] Function foo() has no test coverage"
        run_auto_fix(workflow_state, feedback, log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        assert feedback in prompt

    def test_prompt_contains_plan_path(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Issues found", log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        assert str(workflow_state.get_plan_path()) in prompt

    def test_uses_fixer_agent(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Fix this", log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        expected = workflow_state.subagent_names.get(
            "fixer", workflow_state.subagent_names["implementer"]
        )
        assert call_args[1]["subagent"] == expected
        assert call_args[1]["dont_save_session"] is True

    def test_prompt_includes_no_commit_instruction(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        run_auto_fix(workflow_state, "Issues", log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        assert "Do NOT commit" in prompt


class TestReviewFeedbackTruncation:
    def test_truncates_long_feedback(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        overflow = _MAX_REVIEW_FEEDBACK_LENGTH + 2000
        long_feedback = "x" * overflow
        run_auto_fix(workflow_state, long_feedback, log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        # Full feedback must not appear, but truncated portion must
        assert long_feedback not in prompt
        assert "x" * _MAX_REVIEW_FEEDBACK_LENGTH in prompt
        assert "review feedback truncated" in prompt

    def test_truncates_at_newline_boundary(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        # Build feedback with newlines so truncation snaps to line boundary
        line = "issue line\n"
        repeat_count = (_MAX_REVIEW_FEEDBACK_LENGTH // len(line)) + 100
        long_feedback = line * repeat_count  # well over the limit
        run_auto_fix(workflow_state, long_feedback, log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        assert "review feedback truncated" in prompt
        # Should cut at a newline, not mid-word
        truncated_part = prompt.split("... [review feedback truncated")[0]
        feedback_part = truncated_part.split(
            "Fix the following issues identified during code review:\n\n"
        )[1]
        assert feedback_part.endswith("\n\n")

    def test_short_feedback_unchanged(self, mock_backend, workflow_state, log_dir):
        mock_backend.run_with_callback.return_value = (True, "Done")

        short_feedback = "Missing test for function foo()"
        run_auto_fix(workflow_state, short_feedback, log_dir, mock_backend)

        call_args = mock_backend.run_with_callback.call_args
        prompt = call_args[0][0]
        assert short_feedback in prompt
        assert "truncated" not in prompt


class TestBackwardsCompatibility:
    def test_underscore_alias_is_same_function(self):
        assert _run_auto_fix is run_auto_fix
