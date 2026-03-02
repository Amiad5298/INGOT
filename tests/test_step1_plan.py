"""Tests for ingot.workflow.step1_plan module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingot.ui.menus import ReviewChoice
from ingot.validation.base import ValidationFinding, ValidationReport, ValidationSeverity
from ingot.workflow.state import WorkflowState
from ingot.workflow.step1_plan import (
    _build_minimal_prompt,
    _build_replan_prompt,
    _create_plan_log_dir,
    _display_plan_summary,
    _display_validation_report,
    _edit_plan,
    _extract_plan_markdown,
    _format_validation_feedback,
    _generate_plan_with_tui,
    _get_log_base_dir,
    _run_researcher,
    _save_plan_from_output,
    _truncate_researcher_context,
    _validate_plan,
    build_fix_prompt,
    fix_plan_with_ai,
    step_1_create_plan,
)


@pytest.fixture
def workflow_state(generic_ticket, tmp_path):
    """Create a workflow state for testing using shared generic_ticket fixture."""
    state = WorkflowState(ticket=generic_ticket)
    state.planning_model = "test-planning-model"

    # Create specs directory
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    return state


class TestGetLogBaseDir:
    def test_default_returns_spec_runs(self, monkeypatch):
        monkeypatch.delenv("INGOT_LOG_DIR", raising=False)
        result = _get_log_base_dir()
        assert result == Path(".ingot/runs")

    def test_respects_environment_variable(self, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", "/custom/log/dir")
        result = _get_log_base_dir()
        assert result == Path("/custom/log/dir")


class TestCreatePlanLogDir:
    def test_creates_directory_with_correct_structure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        result = _create_plan_log_dir("TEST-123")

        assert result.exists()
        assert result.is_dir()
        assert result.name == "plan_generation"
        assert result.parent.name == "TEST-123"

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "deep" / "nested" / "path"
        monkeypatch.setenv("INGOT_LOG_DIR", str(log_dir))

        result = _create_plan_log_dir("TEST-456")

        assert result.exists()
        assert "TEST-456" in str(result)
        assert "plan_generation" in str(result)

    def test_returns_correct_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        result = _create_plan_log_dir("PROJ-789")

        assert isinstance(result, Path)
        assert result == tmp_path / "PROJ-789" / "plan_generation"


class TestGeneratePlanWithTui:
    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_returns_true_on_successful_generation(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        success, output = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert success is True

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_returns_false_when_user_requests_quit(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = True  # User requested quit
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        success, output = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert success is False

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_log_path_is_set_on_ui(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        mock_tui.set_log_path.assert_called_once()
        log_path_arg = mock_tui.set_log_path.call_args[0][0]
        assert isinstance(log_path_arg, Path)
        assert ".log" in str(log_path_arg)

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_auggie_client_uses_subagent(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        # Verify subagent from state.subagent_names is passed
        call_kwargs = mock_backend.run_with_callback.call_args.kwargs
        assert "subagent" in call_kwargs
        assert call_kwargs["subagent"] == workflow_state.subagent_names["planner"]

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_returns_false_on_auggie_failure(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (False, "Error")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        success, output = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert success is False

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_dont_save_session_flag_is_passed(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        # Verify dont_save_session=True is passed in the call
        mock_backend.run_with_callback.assert_called_once()
        call_kwargs = mock_backend.run_with_callback.call_args.kwargs
        assert "dont_save_session" in call_kwargs
        assert call_kwargs["dont_save_session"] is True


class TestBuildMinimalPrompt:
    def test_prompt_includes_ticket_id(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "TEST-123" in result

    def test_prompt_includes_ticket_title(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Test Feature" in result

    def test_prompt_includes_ticket_description(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Test description" in result

    def test_prompt_handles_empty_title(self, generic_ticket, tmp_path):
        generic_ticket.title = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path)

        # Should fall back to branch_summary when title is None
        assert generic_ticket.branch_summary in result
        assert "TEST-123" in result

    def test_prompt_handles_empty_description(self, generic_ticket, tmp_path):
        generic_ticket.description = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path)

        assert "Not available" in result

    def test_prompt_includes_user_constraints_when_provided(self, workflow_state, tmp_path):
        workflow_state.user_constraints = (
            "Additional context from the user about the implementation."
        )
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Additional context from the user" in result
        assert "[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]" in result

    def test_prompt_excludes_user_constraints_section_when_not_provided(
        self, workflow_state, tmp_path
    ):
        workflow_state.user_constraints = ""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]" not in result

    def test_prompt_has_verified_source_label_when_spec_verified(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "[SOURCE: VERIFIED PLATFORM DATA]" in result
        assert "[SOURCE: NO VERIFIED PLATFORM DATA]" not in result

    def test_prompt_has_unverified_source_label_when_spec_not_verified(
        self, generic_ticket, tmp_path
    ):
        generic_ticket.title = None
        generic_ticket.description = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path)

        assert "[SOURCE: NO VERIFIED PLATFORM DATA]" in result
        assert "[SOURCE: VERIFIED PLATFORM DATA]" not in result
        assert "Do NOT reference" in result

    def test_plan_mode_includes_source_labels(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path, plan_mode=True)

        assert "[SOURCE: VERIFIED PLATFORM DATA]" in result
        assert "Output the complete implementation plan" in result
        assert "Do not attempt to create or write any files" in result
        # Should NOT mention saving to a file
        assert f"Save the plan to: {plan_path}" not in result

    def test_plan_mode_unverified_includes_source_labels(self, generic_ticket, tmp_path):
        generic_ticket.title = None
        generic_ticket.description = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path, plan_mode=True)

        assert "[SOURCE: NO VERIFIED PLATFORM DATA]" in result
        assert "Do NOT reference" in result
        assert "Output the complete implementation plan" in result

    def test_prompt_includes_plan_file_path(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        # Should mention where to save the plan
        assert str(plan_path) in result


class TestExtractPlanMarkdown:
    def test_extracts_from_first_heading(self):
        output = "Some preamble\nTool output\n# Plan Title\n\nPlan body here."
        result = _extract_plan_markdown(output)
        assert result == "# Plan Title\n\nPlan body here."

    def test_falls_back_when_no_heading(self):
        output = "Just some plain text output\nwith no headings"
        result = _extract_plan_markdown(output)
        assert result == output.strip()

    def test_strips_ansi_codes(self):
        output = "\x1b[32mSome colored preamble\x1b[0m\n# Plan\n\nContent"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"
        assert "\x1b" not in result

    def test_handles_empty_input(self):
        result = _extract_plan_markdown("")
        assert result == ""

    def test_handles_whitespace_only(self):
        result = _extract_plan_markdown("   \n  \n   ")
        assert result == ""

    def test_strips_trailing_whitespace(self):
        output = "# Plan\n\nContent\n\n\n  "
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"

    def test_preserves_multiple_headings(self):
        output = "preamble\n# Heading 1\nBody 1\n## Heading 2\nBody 2"
        result = _extract_plan_markdown(output)
        assert "# Heading 1" in result
        assert "## Heading 2" in result
        assert "preamble" not in result

    def test_non_heading_hash_not_matched(self):
        output = "#tag not a heading\nmore text\n# Real Heading\nBody"
        result = _extract_plan_markdown(output)
        assert result.startswith("# Real Heading")
        assert "#tag" not in result

    def test_strips_csi_with_parameter_byte(self):
        """CSI sequences with ? parameter byte (e.g., cursor hide/show)."""
        output = "\x1b[?25lHidden cursor\x1b[?25h\n# Plan\n\nContent"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"
        assert "\x1b" not in result

    def test_strips_24bit_color_sequences(self):
        """24-bit (true color) ANSI sequences: ESC[38;2;R;G;Bm."""
        output = "\x1b[38;2;255;0;128mColorful\x1b[0m preamble\n# Plan\n\nBody"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nBody"
        assert "\x1b" not in result

    def test_strips_osc_sequences(self):
        """OSC sequences like window title setting."""
        output = "\x1b]0;My Title\x07Some output\n# Plan\n\nContent"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"
        assert "\x1b" not in result

    def test_strips_osc_with_st_terminator(self):
        """OSC sequences terminated with ST (ESC \\)."""
        output = "\x1b]0;My Title\x1b\\Some output\n# Plan\n\nContent"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"
        assert "\x1b" not in result

    def test_strips_complex_mixed_ansi(self):
        """Mix of cursor hiding, 24-bit color, bold, reset, and OSC."""
        output = (
            "\x1b[?25l"  # Hide cursor
            "\x1b[1m\x1b[38;2;0;255;0m"  # Bold + 24-bit green
            "Thinking...\n"
            "\x1b[0m"  # Reset
            "\x1b]0;Agent Running\x07"  # OSC: set title
            "Tool: search_code\n"
            "# Implementation Plan\n\n"
            "## Step 1\n"
            "Do something\n"
            "\x1b[?25h"  # Show cursor
        )
        result = _extract_plan_markdown(output)
        assert result.startswith("# Implementation Plan")
        assert "## Step 1" in result
        assert "Do something" in result
        assert "\x1b" not in result

    def test_strips_thinking_blocks(self):
        """<thinking> blocks should be removed before heading extraction."""
        output = (
            "<thinking>\n# Internal Heading\nSome reasoning\n</thinking>\n"
            "# Actual Plan\n\nReal content"
        )
        result = _extract_plan_markdown(output)
        assert result.startswith("# Actual Plan")
        assert "Internal Heading" not in result
        assert "Some reasoning" not in result

    def test_strips_thinking_blocks_case_insensitive(self):
        output = "<Thinking>reasoning</Thinking>\n# Plan\n\nContent"
        result = _extract_plan_markdown(output)
        assert result == "# Plan\n\nContent"
        assert "reasoning" not in result

    def test_thinking_block_with_nested_markdown(self):
        """Thinking blocks containing markdown headings should not leak."""
        output = (
            "Preamble\n"
            "<thinking>\n"
            "## Analysis\n"
            "- point 1\n"
            "- point 2\n"
            "</thinking>\n"
            "# Real Plan\n\n"
            "## Steps\n"
            "1. First step"
        )
        result = _extract_plan_markdown(output)
        assert result.startswith("# Real Plan")
        assert "## Steps" in result
        assert "Analysis" not in result


class TestSavePlanFromOutput:
    def test_creates_template_with_ticket_id(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        content = plan_path.read_text()
        assert "TEST-123" in content

    def test_writes_to_correct_path(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        assert plan_path.exists()

    def test_includes_all_template_sections(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        content = plan_path.read_text()
        assert "## Summary" in content
        assert "## Description" in content
        assert "## Implementation Steps" in content
        assert "## Testing Strategy" in content
        assert "## Notes" in content

    def test_includes_ticket_title_in_summary(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        content = plan_path.read_text()
        assert "Test Feature" in content

    def test_saves_extracted_output_when_non_empty(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        output = "Tool log line\n# Implementation Plan\n\n## Steps\n1. Do stuff"
        _save_plan_from_output(plan_path, workflow_state, output=output)

        content = plan_path.read_text()
        assert content.startswith("# Implementation Plan")
        assert "Tool log line" not in content

    def test_saves_full_output_when_no_heading(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        output = "Just plain text plan with no headings"
        _save_plan_from_output(plan_path, workflow_state, output=output)

        content = plan_path.read_text()
        assert "Just plain text plan" in content


class TestDisplayPlanSummary:
    @patch("ingot.workflow.step1_plan.console")
    def test_reads_file_correctly(self, mock_console, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n\nThis is the plan content.")

        _display_plan_summary(plan_path)

        # Should have printed something
        assert mock_console.print.called

    @patch("ingot.workflow.step1_plan.console")
    def test_limits_preview_to_20_lines(self, mock_console, tmp_path):
        plan_path = tmp_path / "plan.md"
        # Create a file with 50 lines
        lines = [f"Line {i}" for i in range(50)]
        plan_path.write_text("\n".join(lines))

        _display_plan_summary(plan_path)

        # Should print "..." to indicate truncation
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("..." in c for c in calls)

    @patch("ingot.workflow.step1_plan.console")
    def test_handles_short_files(self, mock_console, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n\nShort content.")

        _display_plan_summary(plan_path)

        # Should have printed the content
        assert mock_console.print.called


class TestStep1CreatePlanTuiMode:
    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    @patch("ingot.ui.textual_runner.should_use_tui")
    def test_creates_specs_directory_if_not_exists(
        self,
        mock_should_tui,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_should_tui.return_value = True
        mock_generate.return_value = (True, "# Plan")
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        # Create plan file to simulate successful generation
        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        assert specs_dir.exists()

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_generate_plan_with_tui(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        mock_generate.assert_called_once()

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_generation_fails(
        self, mock_generate, mock_researcher, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = (False, "")  # Generation fails
        workflow_state.enable_plan_validation = False

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False


class TestStep1CreatePlanFileHandling:
    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_saves_plan_file_on_success(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Generated Plan")
            return True, "# Generated Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        # Compare resolved paths since the function uses relative paths
        assert workflow_state.plan_file.resolve() == plan_path.resolve()

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._save_plan_from_output")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_save_plan_from_output_when_plan_file_not_created(
        self,
        mock_generate,
        mock_save_plan,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = (True, "# Plan output")  # Success but no file
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)

        # Mock _save_plan_from_output to create the file
        def create_plan_file(path, state, *, output=""):
            path.write_text("# Fallback Plan")

        mock_save_plan.side_effect = create_plan_file
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        mock_save_plan.assert_called_once()

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.print_error")
    @patch("ingot.workflow.step1_plan._save_plan_from_output")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_save_fails_to_create_file(
        self,
        mock_generate,
        mock_save_plan,
        mock_print_error,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = (True, "# Plan output")  # Generation succeeds but no file
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        # Note: plan file intentionally NOT created

        # Mock _save_plan_from_output to do nothing (simulates failure to write)
        mock_save_plan.return_value = None  # Does not create the file

        workflow_state.skip_clarification = True

        result = step_1_create_plan(workflow_state, MagicMock())

        # Should return False because file still doesn't exist
        assert result is False
        # Should have called _save_plan_from_output
        mock_save_plan.assert_called_once()
        # Should have logged the error
        mock_print_error.assert_called_once()
        assert "Plan file was not created" in mock_print_error.call_args[0][0]


class TestStep1CreatePlanConfirmation:
    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_true_when_plan_approved(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_aborted(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.ABORT
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_updates_current_step_to_2_on_approve(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        assert workflow_state.current_step == 1  # Initially 1

        step_1_create_plan(workflow_state, MagicMock())

        assert workflow_state.current_step == 2  # Updated to 2

    @patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_does_not_update_current_step_on_abort(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.ABORT
        workflow_state.enable_plan_validation = False

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        assert workflow_state.current_step == 1

        step_1_create_plan(workflow_state, MagicMock())

        assert workflow_state.current_step == 1  # Unchanged


@patch("ingot.workflow.step1_plan._run_researcher", return_value=(False, ""))
class TestStep1PlanReviewLoop:
    """Tests for the plan review loop (regenerate, edit, abort flows)."""

    def _setup_plan(self, tmp_path, workflow_state, mock_generate):
        """Helper: set up plan file creation side effect."""
        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n\n## Steps\n1. Do stuff")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True
        workflow_state.enable_plan_validation = False
        return plan_path

    @patch("ingot.workflow.step1_plan.replan_with_feedback")
    @patch("ingot.workflow.step1_plan.prompt_input")
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_regenerate_collects_feedback_and_calls_replan(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_prompt_input,
        mock_replan,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        self._setup_plan(tmp_path, workflow_state, mock_generate)

        # First call: REGENERATE, second call: APPROVE
        mock_review_menu.side_effect = [ReviewChoice.REGENERATE, ReviewChoice.APPROVE]
        mock_prompt_input.return_value = "Add more error handling"
        mock_replan.return_value = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        mock_replan.assert_called_once()
        assert "Add more error handling" in mock_replan.call_args[0][2]
        # plan_revision_count should be incremented (not replan_count)
        assert workflow_state.plan_revision_count == 1
        # _display_plan_summary called: once initially + once after regenerate
        assert mock_display.call_count == 2

    @patch("ingot.workflow.step1_plan.prompt_input")
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_regenerate_empty_feedback_loops_again(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_prompt_input,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        self._setup_plan(tmp_path, workflow_state, mock_generate)

        # REGENERATE with empty feedback → loops, then ABORT
        mock_review_menu.side_effect = [
            ReviewChoice.REGENERATE,
            ReviewChoice.ABORT,
        ]
        mock_prompt_input.return_value = ""

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False
        # prompt_input called once for the empty feedback attempt
        mock_prompt_input.assert_called_once()

    @patch("ingot.workflow.step1_plan.replan_with_feedback")
    @patch("ingot.workflow.step1_plan.prompt_input")
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_regenerate_failure_stays_in_loop(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_prompt_input,
        mock_replan,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        self._setup_plan(tmp_path, workflow_state, mock_generate)

        # REGENERATE fails → stays in loop, then ABORT
        mock_review_menu.side_effect = [ReviewChoice.REGENERATE, ReviewChoice.ABORT]
        mock_prompt_input.return_value = "Fix the architecture section"
        mock_replan.return_value = False  # Replan fails

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False
        mock_replan.assert_called_once()

    @patch("ingot.workflow.step1_plan._edit_plan")
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_edit_opens_editor_and_redisplays(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_edit_plan,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        self._setup_plan(tmp_path, workflow_state, mock_generate)

        # EDIT → then APPROVE
        mock_review_menu.side_effect = [ReviewChoice.EDIT, ReviewChoice.APPROVE]

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        mock_edit_plan.assert_called_once()
        # _display_plan_summary called: once initially + once after edit
        assert mock_display.call_count == 2

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_max_review_iterations_returns_false(
        self,
        mock_generate,
        mock_display,
        mock_review_menu,
        mock_researcher,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        self._setup_plan(tmp_path, workflow_state, mock_generate)

        # Always choose EDIT to exhaust the iteration limit
        mock_review_menu.return_value = ReviewChoice.EDIT

        with patch("ingot.workflow.step1_plan._edit_plan"):
            result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False


class TestEditPlan:
    """Tests for the _edit_plan helper."""

    @patch("ingot.workflow.step1_plan.prompt_enter")
    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_falls_back_when_not_tty(self, mock_run, mock_enter, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: False)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        _edit_plan(plan_path)

        mock_run.assert_not_called()
        mock_enter.assert_called_once()

    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_opens_editor(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("EDITOR", "nano")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        _edit_plan(plan_path)

        mock_run.assert_called_once_with(["nano", str(plan_path)], check=True)

    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_handles_editor_with_flags(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("EDITOR", "code --wait")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        _edit_plan(plan_path)

        mock_run.assert_called_once_with(["code", "--wait", str(plan_path)], check=True)

    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_defaults_to_vim(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.delenv("EDITOR", raising=False)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        _edit_plan(plan_path)

        mock_run.assert_called_once_with(["vim", str(plan_path)], check=True)

    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_handles_editor_error(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("EDITOR", "nano")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")
        mock_run.side_effect = subprocess.CalledProcessError(1, "nano")

        _edit_plan(plan_path)

        # Should not raise, just print a warning
        mock_run.assert_called_once()

    @patch("ingot.workflow.step1_plan.prompt_enter")
    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_handles_missing_editor(self, mock_run, mock_enter, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("EDITOR", "nonexistent-editor")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")
        mock_run.side_effect = FileNotFoundError("No such file")

        _edit_plan(plan_path)

        mock_enter.assert_called_once()

    @patch("ingot.workflow.step1_plan.print_warning")
    @patch("ingot.workflow.step1_plan.subprocess.run")
    def test_edit_plan_warns_when_file_deleted(self, mock_run, mock_warning, tmp_path, monkeypatch):
        monkeypatch.setattr("ingot.workflow.step1_plan.sys.stdin.isatty", lambda: True)
        monkeypatch.setenv("EDITOR", "nano")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        # Simulate editor deleting the file
        def delete_file(*args, **kwargs):
            plan_path.unlink()

        mock_run.side_effect = delete_file

        _edit_plan(plan_path)

        mock_warning.assert_called_once()
        assert "no longer exists" in mock_warning.call_args[0][0].lower()


class TestBuildReplanPrompt:
    """Tests for _build_replan_prompt source label handling."""

    def test_includes_verified_source_label(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_replan_prompt(workflow_state, plan_path, "# Old plan", "Needs more detail")

        assert "[SOURCE: VERIFIED PLATFORM DATA]" in result
        assert "[SOURCE: NO VERIFIED PLATFORM DATA]" not in result

    def test_includes_unverified_source_label(self, generic_ticket, tmp_path):
        generic_ticket.title = None
        generic_ticket.description = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_replan_prompt(state, plan_path, "# Old plan", "Needs more detail")

        assert "[SOURCE: NO VERIFIED PLATFORM DATA]" in result
        assert "[SOURCE: VERIFIED PLATFORM DATA]" not in result
        assert "Do NOT reference" in result

    def test_includes_user_constraints_label(self, workflow_state, tmp_path):
        workflow_state.user_constraints = "Use Redis for caching"
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_replan_prompt(workflow_state, plan_path, "# Old plan", "Needs caching")

        assert "[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]" in result
        assert "Use Redis for caching" in result

    def test_excludes_user_constraints_when_empty(self, workflow_state, tmp_path):
        workflow_state.user_constraints = ""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_replan_prompt(workflow_state, plan_path, "# Old plan", "Needs work")

        assert "[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]" not in result


# =============================================================================
# Researcher Agent Tests
# =============================================================================


class TestRunResearcher:
    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_successful_researcher_call(self, mock_tui_class, workflow_state, mock_backend):
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (
            True,
            "### Verified Files\n- `src/main.py:1`",
        )

        success, output = _run_researcher(workflow_state, mock_backend)

        assert success is True
        assert "Verified Files" in output

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_failed_researcher_returns_false(self, mock_tui_class, workflow_state, mock_backend):
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.run_with_work.side_effect = lambda fn: fn()
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (False, "")

        success, output = _run_researcher(workflow_state, mock_backend)

        assert success is False

    def test_missing_researcher_key_graceful(self, workflow_state, mock_backend):
        # Remove researcher from subagent_names
        workflow_state.subagent_names.pop("researcher", None)

        success, output = _run_researcher(workflow_state, mock_backend)

        assert success is False
        assert output == ""
        # No KeyError raised

    @patch("ingot.ui.inline_runner.InlineRunner")
    def test_researcher_exception_returns_false(self, mock_tui_class, workflow_state, mock_backend):
        mock_tui = MagicMock()
        mock_tui.run_with_work.side_effect = RuntimeError("network error")
        mock_tui_class.return_value = mock_tui

        success, output = _run_researcher(workflow_state, mock_backend)

        assert success is False
        assert output == ""


# =============================================================================
# Truncation Tests
# =============================================================================


class TestTruncateResearcherContext:
    def test_short_context_unchanged(self):
        context = "### Verified Files\n- `src/main.py:1` — Main file"
        result = _truncate_researcher_context(context)
        assert result == context
        assert "[NOTE:" not in result

    def test_long_context_truncated(self):
        # Create context that exceeds the budget
        context = "### Verified Files\n" + "- `src/file.py:1` — Description\n" * 500
        result = _truncate_researcher_context(context, budget=500)
        assert len(result) <= 600  # Budget + header overhead
        assert "[NOTE: Research context truncated" in result

    def test_empty_context_returned(self):
        result = _truncate_researcher_context("")
        assert result == ""

    def test_sections_dropped_in_priority_order(self):
        context = (
            "### Verified Files\nFile list\n"
            "### Existing Code Patterns\nPatterns\n"
            "### Unresolved\nUnresolved items long text " + "x" * 500
        )
        result = _truncate_researcher_context(context, budget=200)
        # Should keep Verified Files (highest priority) and drop Unresolved (lowest)
        assert "Verified Files" in result


# =============================================================================
# Build Prompt with Researcher Context Tests
# =============================================================================


class TestBuildMinimalPromptWithResearcherContext:
    def test_includes_discovery_section_when_context_provided(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        researcher = "### Verified Files\n- `src/main.py:1`"

        result = _build_minimal_prompt(workflow_state, plan_path, researcher_context=researcher)

        assert "[SOURCE: CODEBASE DISCOVERY" in result
        assert "Verified Files" in result

    def test_omits_discovery_section_when_empty(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path, researcher_context="")

        assert "[SOURCE: CODEBASE DISCOVERY" not in result

    def test_truncation_applied_before_injection(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        # Create very long researcher output
        researcher = "### Verified Files\n" + "- `src/file.py:1` — Desc\n" * 2000

        result = _build_minimal_prompt(workflow_state, plan_path, researcher_context=researcher)

        # Should contain the truncation note
        assert "[SOURCE: CODEBASE DISCOVERY" in result
        # The full 2000-line output should NOT be in the prompt
        assert result.count("src/file.py") < 2000


# =============================================================================
# Validation Integration Tests
# =============================================================================


class TestValidatePlan:
    def test_validation_runs_with_complete_plan(self, workflow_state, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        plan = """\
# Plan

## Summary
Summary.

## Technical Approach
Approach.

## Implementation Steps
Steps.

## Testing Strategy
Tests.

## Potential Risks
Risks.

## Out of Scope
Nothing.
"""
        report = _validate_plan(plan, workflow_state)
        # Complete plan should have no section errors
        section_errors = [f for f in report.findings if f.validator_name == "Required Sections"]
        assert section_errors == []


class TestDisplayValidationReport:
    @patch("ingot.workflow.step1_plan.console")
    def test_empty_report_no_output(self, mock_console):
        report = ValidationReport()
        _display_validation_report(report)
        # Should not print anything significant
        mock_console.print.assert_not_called()

    @patch("ingot.workflow.step1_plan.print_warning")
    @patch("ingot.workflow.step1_plan.console")
    @patch("ingot.workflow.step1_plan.print_step")
    def test_report_with_errors_displayed(self, mock_step, mock_console, mock_warning):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Something is wrong",
                    suggestion="Fix it",
                ),
            ]
        )
        _display_validation_report(report)
        mock_step.assert_called_once()
        # Should warn about error count
        mock_warning.assert_called_once()


# =============================================================================
# Step 1 with Validation Tests
# =============================================================================


class TestStep1WithValidation:
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_validation_runs_when_enabled(
        self,
        mock_generate,
        mock_researcher,
        mock_validate,
        mock_display,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "### Verified Files\n")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_validate.return_value = ValidationReport()
        workflow_state.enable_plan_validation = True

        step_1_create_plan(workflow_state, MagicMock())

        mock_validate.assert_called_once()

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_validation_skipped_when_disabled(
        self,
        mock_generate,
        mock_researcher,
        mock_validate,
        mock_display,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        workflow_state.enable_plan_validation = False

        step_1_create_plan(workflow_state, MagicMock())

        mock_validate.assert_not_called()


class TestStep1RetryOnValidationError:
    """Tests for the auto-retry loop (no prompt_confirm — fully automatic)."""

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_auto_retry_on_errors_reruns_pipeline(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_display_report,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "### Verified Files\n")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Fixed Plan")

        # First call: errors -> auto-retry via AI fix, second call: clean
        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Bad",
                ),
            ]
        )
        clean_report = ValidationReport()
        mock_validate.side_effect = [error_report, clean_report]
        workflow_state.enable_plan_validation = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Generate called once (initial), fix called once (retry)
        assert mock_generate.call_count == 1
        assert mock_fix_ai.call_count == 1
        # Researcher runs once (before the retry loop), not on each retry
        assert mock_researcher.call_count == 1
        assert workflow_state.plan_revision_count == 1

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_warnings_only_no_retry(
        self,
        mock_generate,
        mock_researcher,
        mock_validate,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan

        warning_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.WARNING,
                    message="Minor issue",
                ),
            ]
        )
        mock_validate.return_value = warning_report
        workflow_state.enable_plan_validation = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Only generated once (warnings don't trigger retry)
        assert mock_generate.call_count == 1

    @patch("ingot.workflow.step1_plan.print_warning")
    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_exhausted_retries_shows_warning(
        self,
        mock_generate,
        mock_researcher,
        mock_validate,
        mock_display_report,
        mock_display_summary,
        mock_review_menu,
        mock_print_warning,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan

        # All attempts produce errors — retries will be exhausted
        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Bad",
                ),
            ]
        )
        mock_validate.return_value = error_report
        workflow_state.enable_plan_validation = True
        workflow_state.validation_strict = False  # Allow warn-and-proceed

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # On the last attempt, a warning about proceeding despite errors is shown
        warning_calls = [str(c) for c in mock_print_warning.call_args_list]
        assert any("Proceeding to review despite" in w for w in warning_calls)


# =============================================================================
# Additional Tests for PR #72 Fixes
# =============================================================================


class TestTruncationBudgetRespected:
    """Verify truncated output (including header) stays within budget."""

    def test_truncated_output_within_budget(self):
        budget = 500
        context = "### Verified Files\n" + "- `src/file.py:1` — Description\n" * 200
        result = _truncate_researcher_context(context, budget=budget)
        assert len(result) <= budget

    def test_small_budget_still_within_limit(self):
        budget = 200
        context = "### Verified Files\n" + "- `src/file.py:1` — Desc\n" * 100
        result = _truncate_researcher_context(context, budget=budget)
        assert len(result) <= budget


class TestBuildMinimalPromptFallback:
    """Empty researcher context produces fallback instruction."""

    def test_empty_researcher_context_has_fallback(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path, researcher_context="")
        assert "No automated codebase discovery was performed" in result
        assert "independently explore" in result

    def test_non_empty_researcher_context_no_fallback(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(
            workflow_state, plan_path, researcher_context="### Verified Files\n- `a.py:1`"
        )
        assert "No automated codebase discovery was performed" not in result
        assert "[SOURCE: CODEBASE DISCOVERY" in result


class TestResearcherNotRerunOnRetry:
    """Verify researcher runs once, not on every retry."""

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_researcher_called_once_on_retry(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_display_report,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "### Verified Files\n")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Fixed Plan")

        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Bad",
                ),
            ]
        )
        clean_report = ValidationReport()
        mock_validate.side_effect = [error_report, clean_report]
        workflow_state.enable_plan_validation = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Researcher should be called only once (before the loop)
        assert mock_researcher.call_count == 1
        # Generate called once (initial), fix called once (retry)
        assert mock_generate.call_count == 1
        assert mock_fix_ai.call_count == 1


class TestSectionsNotInPriority:
    """Unknown sections are dropped during truncation."""

    def test_unknown_sections_dropped(self):
        # Make context long enough to trigger truncation, with an unknown section
        context = (
            "### Verified Files\n"
            + "- `src/f.py:1` — Desc\n" * 20
            + "### Custom Unknown Section\nCustom content\n"
            + "### Existing Code Patterns\nPatterns"
        )
        # Use a budget that is smaller than the full context but large enough
        # to fit at least the Verified Files section
        budget = len(context) - 10
        result = _truncate_researcher_context(context, budget=budget)
        # Known sections should be present
        assert "Verified Files" in result
        # Unknown sections should be dropped (not in priority list)
        assert "Custom Unknown Section" not in result


class TestTruncationAtLineBoundary:
    """A5: Verify truncated content ends at a newline boundary."""

    def test_truncation_at_line_boundary(self):
        # Build content long enough to trigger within-section truncation
        lines = [f"- `src/file_{i}.py:1` — Description line {i}" for i in range(200)]
        context = "### Verified Files\n" + "\n".join(lines)
        # Budget small enough to truncate within the section
        budget = 400
        result = _truncate_researcher_context(context, budget=budget)
        assert "[NOTE: Research context truncated" in result
        # The truncated section should end with "..." on its own line
        # and the line before "..." should be a complete line (not mid-word)
        result_lines = result.splitlines()
        # Find the "..." marker
        ellipsis_indices = [i for i, ln in enumerate(result_lines) if ln.strip() == "..."]
        assert len(ellipsis_indices) > 0
        # The line before "..." should be a complete entry (starts with "- ")
        for idx in ellipsis_indices:
            if idx > 0:
                prev_line = result_lines[idx - 1]
                # Should not be cut mid-word — either a complete list item or heading
                assert prev_line.startswith("- ") or prev_line.startswith("###")


class TestFormatValidationFeedback:
    """Tests for _format_validation_feedback."""

    def test_formats_errors_and_warnings(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Missing section: Summary",
                    suggestion="Add a Summary section.",
                ),
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.WARNING,
                    message="Code block uncited",
                    suggestion="Add Pattern source.",
                ),
            ]
        )
        result = _format_validation_feedback(report)
        assert "[ERROR]" in result
        assert "Missing section: Summary" in result
        assert "[WARNING]" in result
        assert "Code block uncited" in result
        assert "Add a Summary section" in result

    def test_excludes_info_findings(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.INFO,
                    message="UNVERIFIED marker",
                ),
            ]
        )
        result = _format_validation_feedback(report)
        assert result == ""

    def test_empty_report_returns_empty(self):
        report = ValidationReport()
        result = _format_validation_feedback(report)
        assert result == ""


class TestStrictValidationGate:
    """A1: Test validation_strict blocks workflow on exhausted retries."""

    @patch("ingot.workflow.step1_plan.print_error")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_strict_mode_blocks_on_exhausted_retries(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_display_report,
        mock_print_error,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Still Bad Plan")

        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Bad",
                ),
            ]
        )
        mock_validate.return_value = error_report
        workflow_state.enable_plan_validation = True
        workflow_state.validation_strict = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False
        # Should have printed an error about AI not resolving
        error_calls = [str(c) for c in mock_print_error.call_args_list]
        assert any("could not auto-resolve" in c.lower() for c in error_calls)

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan.print_warning")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_non_strict_mode_proceeds_on_exhausted_retries(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_display_report,
        mock_print_warning,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Still Bad Plan")

        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Bad",
                ),
            ]
        )
        mock_validate.return_value = error_report
        workflow_state.enable_plan_validation = True
        workflow_state.validation_strict = False

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Should have printed a warning (not error) about proceeding
        warning_calls = [str(c) for c in mock_print_warning.call_args_list]
        assert any("Proceeding to review despite" in w for w in warning_calls)


# =============================================================================
# Self-Healing Auto-Fix Tests
# =============================================================================


class TestStep1AutoFixIntegration:
    """Tests for PlanFixer integration in the retry loop."""

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan.PlanFixer")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_auto_fix_resolves_errors_without_prompt(
        self,
        mock_generate,
        mock_researcher,
        mock_validate,
        mock_fixer_class,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """PlanFixer success -> no prompt, proceeds to review."""
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\nModify `src/missing.py`")
            return True, "# Plan"

        mock_generate.side_effect = create_plan

        # First validation: errors. After fix + revalidation: clean.
        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=2,
                ),
            ]
        )
        clean_report = ValidationReport()
        mock_validate.side_effect = [error_report, clean_report]

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = (
            "# Plan\nModify `src/missing.py` <!-- UNVERIFIED: auto-flagged, file not in repo -->",
            ["Marked `src/missing.py` as UNVERIFIED (line 2)"],
        )
        mock_fixer_class.return_value = mock_fixer

        workflow_state.enable_plan_validation = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Only generated once — auto-fix resolved the errors, no AI retry needed
        assert mock_generate.call_count == 1
        mock_fixer.fix.assert_called_once()

    @patch("ingot.workflow.step1_plan.show_plan_review_menu")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan.PlanFixer")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_auto_fix_partial_then_auto_retry(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_fixer_class,
        mock_display_report,
        mock_display_summary,
        mock_review_menu,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """PlanFixer fixes some but not all errors -> targeted AI fix."""
        monkeypatch.chdir(tmp_path)
        mock_review_menu.return_value = ReviewChoice.APPROVE
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Fixed Plan")

        # First validation: File Exists + Required Sections errors
        mixed_error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=2,
                ),
                ValidationFinding(
                    validator_name="Required Sections",
                    severity=ValidationSeverity.ERROR,
                    message="Missing required section: 'Summary'",
                ),
            ]
        )
        # After fixer: File Exists resolved but Required Sections remains
        still_error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Required Sections",
                    severity=ValidationSeverity.ERROR,
                    message="Missing required section: 'Summary'",
                ),
            ]
        )
        # Second attempt: clean
        clean_report = ValidationReport()
        mock_validate.side_effect = [mixed_error_report, still_error_report, clean_report]

        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = (
            "# Plan (fixed)",
            ["Marked `src/missing.py` as UNVERIFIED (line 2)"],
        )
        mock_fixer_class.return_value = mock_fixer

        workflow_state.enable_plan_validation = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True
        # Generate called once, AI fix called once (retry uses fix, not regenerate)
        assert mock_generate.call_count == 1
        assert mock_fix_ai.call_count == 1
        assert workflow_state.plan_revision_count == 1

    @patch("ingot.workflow.step1_plan.print_error")
    @patch("ingot.workflow.step1_plan._display_validation_report")
    @patch("ingot.workflow.step1_plan.PlanFixer")
    @patch("ingot.workflow.step1_plan._validate_plan")
    @patch("ingot.workflow.step1_plan._run_researcher")
    @patch("ingot.workflow.step1_plan.fix_plan_with_ai")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_auto_retry_respects_max_retries_strict(
        self,
        mock_generate,
        mock_fix_ai,
        mock_researcher,
        mock_validate,
        mock_fixer_class,
        mock_display_report,
        mock_print_error,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """After MAX_GENERATION_RETRIES, strict mode returns False with clear error."""
        monkeypatch.chdir(tmp_path)
        mock_researcher.return_value = (True, "")

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True, "# Plan"

        mock_generate.side_effect = create_plan
        mock_fix_ai.return_value = (True, "# Still Bad Plan")

        error_report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Required Sections",
                    severity=ValidationSeverity.ERROR,
                    message="Missing required section: 'Summary'",
                ),
            ]
        )
        mock_validate.return_value = error_report

        # PlanFixer can't fix RequiredSections errors
        mock_fixer = MagicMock()
        mock_fixer.fix.return_value = ("# Plan", [])
        mock_fixer_class.return_value = mock_fixer

        workflow_state.enable_plan_validation = True
        workflow_state.validation_strict = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False
        # Generate called once, AI fix called twice (MAX_GENERATION_RETRIES - 1 = 2)
        assert mock_generate.call_count == 1
        assert mock_fix_ai.call_count == 2
        error_calls = [str(c) for c in mock_print_error.call_args_list]
        assert any("could not auto-resolve" in c.lower() for c in error_calls)


# =============================================================================
# TestBuildFixPrompt
# =============================================================================


class TestBuildFixPrompt:
    """Tests for build_fix_prompt."""

    def test_includes_plan_content_and_errors(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        existing_plan = "# My Plan\n## Summary\nSome content."
        feedback = "- [ERROR] Missing required section: 'Testing Strategy'"

        result = build_fix_prompt(workflow_state, plan_path, existing_plan, feedback)

        assert "# My Plan" in result
        assert "Missing required section" in result
        assert "Fix ONLY the issues flagged" in result
        assert "TEST-123" in result

    def test_truncates_long_plan_with_head_and_tail(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        head = "HEAD_MARKER " + "a" * 5000
        tail = "b" * 4000 + " TAIL_MARKER"
        long_plan = head + tail
        feedback = "- [ERROR] Some error"

        result = build_fix_prompt(workflow_state, plan_path, long_plan, feedback)

        assert "... [middle truncated] ..." in result
        assert "HEAD_MARKER" in result
        assert "TAIL_MARKER" in result

    def test_includes_ticket_info(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = build_fix_prompt(workflow_state, plan_path, "# Plan", "- [ERROR] Bad")

        assert "TEST-123" in result
        assert "Title:" in result

    def test_plan_mode_stdout_instruction(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = build_fix_prompt(
            workflow_state,
            plan_path,
            "# Plan",
            "- [ERROR] Bad",
            plan_mode=True,
        )

        assert "stdout" in result
        assert "Do not attempt to create or write any files" in result

    def test_file_mode_save_instruction(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = build_fix_prompt(
            workflow_state,
            plan_path,
            "# Plan",
            "- [ERROR] Bad",
            plan_mode=False,
        )

        assert str(plan_path) in result

    def test_includes_user_constraints(self, workflow_state, tmp_path):
        workflow_state.user_constraints = "Use Python 3.12 features"
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = build_fix_prompt(workflow_state, plan_path, "# Plan", "- [ERROR] Bad")

        assert "Python 3.12" in result
        assert "USER-PROVIDED CONSTRAINTS" in result

    def test_unverified_ticket_note(self, workflow_state, tmp_path):
        # Clear title and description so has_verified_content returns False
        workflow_state.ticket.title = ""
        workflow_state.ticket.description = ""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = build_fix_prompt(workflow_state, plan_path, "# Plan", "- [ERROR] Bad")

        assert "NO VERIFIED PLATFORM DATA" in result


# =============================================================================
# TestFixPlanWithAi
# =============================================================================


class TestFixPlanWithAi:
    """Tests for fix_plan_with_ai."""

    def test_calls_backend_with_fix_prompt(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        workflow_state.plan_file = plan_path

        backend = MagicMock()
        backend.supports_plan_mode = False
        backend.run_with_callback.return_value = (True, "# Fixed Plan")

        success, output = fix_plan_with_ai(
            workflow_state,
            plan_path,
            backend,
            existing_plan="# Old Plan",
            validation_feedback="- [ERROR] Bad",
        )

        assert success is True
        assert output == "# Fixed Plan"
        backend.run_with_callback.assert_called_once()
        call_kwargs = backend.run_with_callback.call_args
        assert "ingot-planner" in str(call_kwargs)

    def test_returns_false_on_exception(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        backend = MagicMock()
        backend.supports_plan_mode = False
        backend.run_with_callback.side_effect = RuntimeError("API error")

        success, output = fix_plan_with_ai(
            workflow_state,
            plan_path,
            backend,
            existing_plan="# Plan",
            validation_feedback="- [ERROR] Bad",
        )

        assert success is False
        assert output == ""

    def test_returns_false_on_backend_failure(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        backend = MagicMock()
        backend.supports_plan_mode = False
        backend.run_with_callback.return_value = (False, "")

        success, output = fix_plan_with_ai(
            workflow_state,
            plan_path,
            backend,
            existing_plan="# Plan",
            validation_feedback="- [ERROR] Bad",
        )

        assert success is False
        assert output == ""
