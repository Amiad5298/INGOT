"""Tests for ingot.workflow.step1_5_clarification module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingot.utils.errors import UserCancelledError
from ingot.workflow.state import WorkflowState
from ingot.workflow.step1_5_clarification import (
    ClarificationQA,
    _append_clarifications_log,
    _build_rewrite_prompt,
    _build_single_question_prompt,
    _extract_question,
    _rewrite_plan_with_clarifications,
    _run_interactive_qa_loop,
    step_1_5_clarification,
)


@pytest.fixture
def workflow_state(generic_ticket, tmp_path):
    """Create a workflow state for testing."""
    state = WorkflowState(ticket=generic_ticket)
    state.planning_model = "test-planning-model"

    # Create specs directory and plan file
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)
    plan_path = specs_dir / "TEST-123-plan.md"
    plan_path.write_text("# Implementation Plan\n\n## Summary\nTest plan content.\n")
    state.plan_file = plan_path

    return state


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend."""
    backend = MagicMock()
    backend.run_with_callback.return_value = (True, "What database should we use?")
    return backend


SAMPLE_PLAN = "# Implementation Plan\n\n## Summary\nTest plan content.\n"


# =============================================================================
# Entry Point Tests
# =============================================================================


class TestStep15ClarificationEntryPoint:
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    def test_returns_true_when_user_declines(self, mock_confirm, workflow_state, mock_backend):
        mock_confirm.return_value = False

        result = step_1_5_clarification(workflow_state, mock_backend)

        assert result is True
        mock_backend.run_with_callback.assert_not_called()

    def test_returns_true_when_plan_file_missing(self, generic_ticket, tmp_path, mock_backend):
        state = WorkflowState(ticket=generic_ticket)
        # Don't set plan_file, and ensure the default path doesn't exist

        with patch("ingot.workflow.step1_5_clarification.prompt_confirm") as mock_confirm:
            result = step_1_5_clarification(state, mock_backend)

        assert result is True
        mock_confirm.assert_not_called()

    @patch("ingot.workflow.step1_5_clarification._display_plan_summary")
    @patch("ingot.workflow.step1_5_clarification._rewrite_plan_with_clarifications")
    @patch("ingot.workflow.step1_5_clarification._run_interactive_qa_loop")
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    def test_returns_true_when_no_qa_collected(
        self, mock_confirm, mock_loop, mock_rewrite, mock_display, workflow_state, mock_backend
    ):
        mock_confirm.return_value = True
        mock_loop.return_value = []  # No Q&A pairs

        result = step_1_5_clarification(workflow_state, mock_backend)

        assert result is True
        mock_rewrite.assert_not_called()

    @patch("ingot.workflow.step1_5_clarification._display_plan_summary")
    @patch("ingot.workflow.step1_5_clarification._rewrite_plan_with_clarifications")
    @patch("ingot.workflow.step1_5_clarification._run_interactive_qa_loop")
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    def test_calls_rewrite_on_successful_qa(
        self, mock_confirm, mock_loop, mock_rewrite, mock_display, workflow_state, mock_backend
    ):
        mock_confirm.return_value = True
        qa = [ClarificationQA(question="Q?", answer="A")]
        mock_loop.return_value = qa
        mock_rewrite.return_value = True

        result = step_1_5_clarification(workflow_state, mock_backend)

        assert result is True
        mock_rewrite.assert_called_once()
        mock_display.assert_called_once()

    @patch("ingot.workflow.step1_5_clarification._display_plan_summary")
    @patch("ingot.workflow.step1_5_clarification._append_clarifications_log")
    @patch("ingot.workflow.step1_5_clarification._rewrite_plan_with_clarifications")
    @patch("ingot.workflow.step1_5_clarification._run_interactive_qa_loop")
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    def test_falls_back_to_append_on_rewrite_failure(
        self,
        mock_confirm,
        mock_loop,
        mock_rewrite,
        mock_append,
        mock_display,
        workflow_state,
        mock_backend,
    ):
        mock_confirm.return_value = True
        qa = [ClarificationQA(question="Q?", answer="A")]
        mock_loop.return_value = qa
        mock_rewrite.return_value = False

        result = step_1_5_clarification(workflow_state, mock_backend)

        assert result is True
        mock_append.assert_called_once()

    @patch("ingot.workflow.step1_5_clarification._display_plan_summary")
    @patch("ingot.workflow.step1_5_clarification._rewrite_plan_with_clarifications")
    @patch("ingot.workflow.step1_5_clarification._run_interactive_qa_loop")
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    def test_always_returns_true(
        self, mock_confirm, mock_loop, mock_rewrite, mock_display, workflow_state, mock_backend
    ):
        """Step 1.5 is non-blocking - always returns True."""
        mock_confirm.return_value = True
        mock_loop.return_value = [ClarificationQA(question="Q?", answer="A")]
        mock_rewrite.return_value = False  # Even on failure

        result = step_1_5_clarification(workflow_state, mock_backend)

        assert result is True


# =============================================================================
# Interactive Q&A Loop Tests
# =============================================================================


class TestInteractiveQALoop:
    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_single_qa_then_user_stops(
        self, mock_input, mock_confirm, workflow_state, mock_backend
    ):
        mock_backend.run_with_callback.return_value = (True, "What DB?")
        mock_input.return_value = "PostgreSQL"
        mock_confirm.return_value = False  # Don't continue

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 1
        assert result[0].question == "What DB?"
        assert result[0].answer == "PostgreSQL"

    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_multiple_qa_pairs(self, mock_input, mock_confirm, workflow_state, mock_backend):
        mock_backend.run_with_callback.side_effect = [
            (True, "What DB?"),
            (True, "What auth?"),
            (True, "NO_MORE_QUESTIONS"),
        ]
        mock_input.side_effect = ["PostgreSQL", "JWT"]
        mock_confirm.return_value = True  # Continue

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 2

    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_exit_command_stops_loop(self, mock_input, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "What DB?")
        mock_input.return_value = "done"

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_skip_command_stops_loop(self, mock_input, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "What DB?")
        mock_input.return_value = "skip"

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_quit_command_stops_loop(self, mock_input, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "What DB?")
        mock_input.return_value = "quit"

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_ctrl_c_stops_loop_gracefully(self, mock_input, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "What DB?")
        mock_input.side_effect = UserCancelledError("Ctrl+C")

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_empty_answer_skips_question(
        self, mock_input, mock_confirm, workflow_state, mock_backend
    ):
        mock_backend.run_with_callback.side_effect = [
            (True, "What DB?"),
            (True, "NO_MORE_QUESTIONS"),
        ]
        mock_input.return_value = ""  # Empty answer
        mock_confirm.return_value = True

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    def test_backend_failure_stops_loop(self, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (False, "Error")

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    def test_no_more_questions_sentinel_stops_loop(self, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "NO_MORE_QUESTIONS")

        plan_path = workflow_state.get_plan_path()
        result = _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        assert len(result) == 0

    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_conflict_context_injected_in_first_round(
        self, mock_input, mock_confirm, workflow_state, mock_backend
    ):
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = "Ticket says X, user says Y."
        mock_backend.run_with_callback.side_effect = [
            (True, "About the conflict..."),
            (True, "NO_MORE_QUESTIONS"),
        ]
        mock_input.return_value = "Go with Y"
        mock_confirm.return_value = True

        plan_path = workflow_state.get_plan_path()
        _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        # Check first call prompt includes conflict context
        first_call_prompt = mock_backend.run_with_callback.call_args_list[0][0][0]
        assert "conflict" in first_call_prompt.lower()
        assert "Ticket says X, user says Y." in first_call_prompt

        # Check second call prompt does NOT include conflict context
        second_call_prompt = mock_backend.run_with_callback.call_args_list[1][0][0]
        assert "FIRST question" not in second_call_prompt

    @patch("ingot.workflow.step1_5_clarification.prompt_confirm")
    @patch("ingot.workflow.step1_5_clarification.prompt_input")
    def test_uses_planner_subagent(self, mock_input, mock_confirm, workflow_state, mock_backend):
        mock_backend.run_with_callback.return_value = (True, "NO_MORE_QUESTIONS")

        plan_path = workflow_state.get_plan_path()
        _run_interactive_qa_loop(workflow_state, mock_backend, plan_path)

        call_kwargs = mock_backend.run_with_callback.call_args.kwargs
        assert call_kwargs["subagent"] == workflow_state.subagent_names["planner"]
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Plan Rewrite Tests
# =============================================================================


class TestRewritePlanWithClarifications:
    def test_successful_rewrite(self, workflow_state, mock_backend, tmp_path):
        plan_path = workflow_state.get_plan_path()
        original_content = plan_path.read_text()
        qa = [ClarificationQA(question="What DB?", answer="PostgreSQL")]

        # Simulate backend writing the updated plan
        def write_updated_plan(prompt, **kwargs):
            plan_path.write_text(
                original_content + "\n\n## Clarifications Log\n\nQ1: What DB?\nA1: PostgreSQL\n"
            )
            return (True, "Done")

        mock_backend.run_with_callback.side_effect = write_updated_plan

        result = _rewrite_plan_with_clarifications(workflow_state, mock_backend, plan_path, qa)

        assert result is True

    def test_safety_check_rejects_short_rewrite(self, workflow_state, mock_backend):
        plan_path = workflow_state.get_plan_path()
        plan_path.write_text("A" * 1000)  # Long original
        qa = [ClarificationQA(question="Q?", answer="A")]

        # Simulate backend writing a much shorter plan
        def write_short_plan(prompt, **kwargs):
            plan_path.write_text("Short")  # Way too short
            return (True, "Done")

        mock_backend.run_with_callback.side_effect = write_short_plan

        result = _rewrite_plan_with_clarifications(workflow_state, mock_backend, plan_path, qa)

        assert result is False
        # Original content should be restored
        assert plan_path.read_text() == "A" * 1000

    def test_returns_false_on_backend_failure(self, workflow_state, mock_backend):
        plan_path = workflow_state.get_plan_path()
        qa = [ClarificationQA(question="Q?", answer="A")]
        mock_backend.run_with_callback.return_value = (False, "Error")

        result = _rewrite_plan_with_clarifications(workflow_state, mock_backend, plan_path, qa)

        assert result is False

    def test_appends_log_if_ai_omits_it(self, workflow_state, mock_backend):
        plan_path = workflow_state.get_plan_path()
        original_content = plan_path.read_text()
        qa = [ClarificationQA(question="What DB?", answer="PostgreSQL")]

        # Backend writes updated plan without Clarifications Log
        def write_without_log(prompt, **kwargs):
            plan_path.write_text(original_content + "\nUpdated section.\n")
            return (True, "Done")

        mock_backend.run_with_callback.side_effect = write_without_log

        result = _rewrite_plan_with_clarifications(workflow_state, mock_backend, plan_path, qa)

        assert result is True
        content = plan_path.read_text()
        assert "## Clarifications Log" in content
        assert "What DB?" in content
        assert "PostgreSQL" in content


# =============================================================================
# Prompt Builder Tests
# =============================================================================


class TestBuildSingleQuestionPrompt:
    def test_includes_plan_path_reference(self, workflow_state):
        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=1,
        )

        assert "/tmp/plan.md" in result
        assert "Read the plan file" in result

    def test_includes_conflict_context_in_first_round(self, workflow_state):
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = "Ticket says add, user says remove."

        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=1,
        )

        assert "conflict" in result.lower()
        assert "Ticket says add, user says remove." in result
        assert "FIRST question" in result

    def test_no_conflict_context_in_later_rounds(self, workflow_state):
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = "Some conflict."

        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=2,
        )

        assert "FIRST question" not in result

    def test_includes_previous_qa(self, workflow_state):
        qa = [ClarificationQA(question="What DB?", answer="PostgreSQL")]

        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=qa,
            round_num=2,
        )

        assert "What DB?" in result
        assert "PostgreSQL" in result

    def test_includes_sentinel(self, workflow_state):
        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=1,
        )

        assert "NO_MORE_QUESTIONS" in result

    def test_no_conflict_context_when_not_detected(self, workflow_state):
        workflow_state.conflict_detected = False

        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=1,
        )

        assert "FIRST question" not in result

    def test_no_conflict_context_when_detected_but_empty_summary(self, workflow_state):
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = ""

        result = _build_single_question_prompt(
            plan_path=Path("/tmp/plan.md"),
            state=workflow_state,
            previous_qa=[],
            round_num=1,
        )

        assert "FIRST question" not in result


class TestBuildRewritePrompt:
    def test_includes_plan_path_and_qa(self):
        qa = [ClarificationQA(question="What DB?", answer="PostgreSQL")]
        result = _build_rewrite_prompt(Path("plan.md"), qa)

        assert "plan.md" in result
        assert "Read the current plan file" in result
        assert "What DB?" in result
        assert "PostgreSQL" in result

    def test_includes_instructions(self):
        qa = [ClarificationQA(question="Q?", answer="A")]
        result = _build_rewrite_prompt(Path("plan.md"), qa)

        assert "Clarifications Log" in result
        assert "Do NOT remove" in result


# =============================================================================
# Extract Question Tests
# =============================================================================


class TestExtractQuestion:
    def test_returns_none_for_sentinel(self):
        assert _extract_question("NO_MORE_QUESTIONS") is None

    def test_returns_none_for_sentinel_in_text(self):
        assert _extract_question("I have NO_MORE_QUESTIONS to ask.") is None

    def test_returns_none_for_empty_output(self):
        assert _extract_question("") is None
        assert _extract_question("   ") is None
        assert _extract_question(None) is None

    def test_returns_question_text(self):
        assert _extract_question("What database should we use?") == "What database should we use?"

    def test_strips_whitespace(self):
        assert _extract_question("  What DB?  \n") == "What DB?"

    def test_joins_multiline(self):
        result = _extract_question("What database\nshould we use?")
        assert result == "What database should we use?"

    def test_skips_blank_lines(self):
        result = _extract_question("What DB?\n\nShould we use PostgreSQL?")
        assert result == "What DB? Should we use PostgreSQL?"


# =============================================================================
# Append Clarifications Log Tests
# =============================================================================


class TestAppendClarificationsLog:
    def test_appends_log_section(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n\nContent here.\n")

        qa = [
            ClarificationQA(question="What DB?", answer="PostgreSQL"),
            ClarificationQA(question="What auth?", answer="JWT"),
        ]

        _append_clarifications_log(plan_path, qa)

        content = plan_path.read_text()
        assert "## Clarifications Log" in content
        assert "**Q1:** What DB?" in content
        assert "**A1:** PostgreSQL" in content
        assert "**Q2:** What auth?" in content
        assert "**A2:** JWT" in content

    def test_preserves_original_content(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        original = "# Plan\n\nContent here.\n"
        plan_path.write_text(original)

        qa = [ClarificationQA(question="Q?", answer="A")]

        _append_clarifications_log(plan_path, qa)

        content = plan_path.read_text()
        assert content.startswith(original)

    def test_single_qa_pair(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n")

        qa = [ClarificationQA(question="Q?", answer="A")]

        _append_clarifications_log(plan_path, qa)

        content = plan_path.read_text()
        assert "**Q1:** Q?" in content
        assert "**A1:** A" in content
