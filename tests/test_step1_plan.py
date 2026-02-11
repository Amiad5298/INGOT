"""Tests for ingot.workflow.step1_plan module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingot.workflow.state import WorkflowState
from ingot.workflow.step1_plan import (
    _build_minimal_prompt,
    _create_plan_log_dir,
    _display_plan_summary,
    _generate_plan_with_tui,
    _get_log_base_dir,
    _save_plan_from_output,
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


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend."""
    backend = MagicMock()
    backend.run_streaming.return_value = (True, "Plan generated successfully")
    backend.run_with_callback.return_value = (True, "Plan generated successfully")
    return backend


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
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_returns_true_on_successful_generation(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert result is True

    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_returns_false_when_user_requests_quit(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = True  # User requested quit
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert result is False

    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_log_path_is_set_on_ui(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        mock_tui.set_log_path.assert_called_once()
        log_path_arg = mock_tui.set_log_path.call_args[0][0]
        assert isinstance(log_path_arg, Path)
        assert ".log" in str(log_path_arg)

    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_auggie_client_uses_subagent(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (True, "Plan output")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        # Verify subagent from state.subagent_names is passed
        call_kwargs = mock_backend.run_with_callback.call_args.kwargs
        assert "subagent" in call_kwargs
        assert call_kwargs["subagent"] == workflow_state.subagent_names["planner"]

    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_returns_false_on_auggie_failure(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_backend.run_with_callback.return_value = (False, "Error")

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path, mock_backend)

        assert result is False

    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_dont_save_session_flag_is_passed(
        self, mock_tui_class, workflow_state, tmp_path, monkeypatch, mock_backend
    ):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
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

    def test_prompt_includes_user_context_when_provided(self, workflow_state, tmp_path):
        workflow_state.user_context = "Additional context from the user about the implementation."
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Additional context from the user" in result
        assert "Additional Context" in result

    def test_prompt_excludes_user_context_section_when_not_provided(self, workflow_state, tmp_path):
        workflow_state.user_context = ""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Additional Context" not in result

    def test_prompt_includes_plan_file_path(self, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        # Should mention where to save the plan
        assert str(plan_path) in result


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
    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    @patch("ingot.ui.tui._should_use_tui")
    def test_creates_specs_directory_if_not_exists(
        self,
        mock_should_tui,
        mock_generate,
        mock_display,
        mock_confirm,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_should_tui.return_value = True
        mock_generate.return_value = True
        mock_confirm.return_value = True

        # Create plan file to simulate successful generation
        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        assert specs_dir.exists()

    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_generate_plan_with_tui(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        mock_generate.assert_called_once()

    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_generation_fails(
        self, mock_generate, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = False  # Generation fails

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False


class TestStep1CreatePlanFileHandling:
    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_saves_plan_file_on_success(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Generated Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        # Compare resolved paths since the function uses relative paths
        assert workflow_state.plan_file.resolve() == plan_path.resolve()

    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._save_plan_from_output")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_save_plan_from_output_when_plan_file_not_created(
        self,
        mock_generate,
        mock_save_plan,
        mock_display,
        mock_confirm,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = True  # Success but no file
        mock_confirm.return_value = True

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        specs_dir / "TEST-123-plan.md"

        # Mock _save_plan_from_output to create the file
        def create_plan_file(path, state):
            path.write_text("# Fallback Plan")

        mock_save_plan.side_effect = create_plan_file
        workflow_state.skip_clarification = True

        step_1_create_plan(workflow_state, MagicMock())

        mock_save_plan.assert_called_once()

    @patch("ingot.workflow.step1_plan.print_error")
    @patch("ingot.workflow.step1_plan._save_plan_from_output")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_save_fails_to_create_file(
        self, mock_generate, mock_save_plan, mock_print_error, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = True  # Generation succeeds but no file

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
    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_true_when_plan_confirmed(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True  # User confirms

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is True

    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_rejected(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = False  # User rejects

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False

    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_updates_current_step_to_2_on_success(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        assert workflow_state.current_step == 1  # Initially 1

        step_1_create_plan(workflow_state, MagicMock())

        assert workflow_state.current_step == 2  # Updated to 2

    @patch("ingot.workflow.step1_plan.prompt_confirm")
    @patch("ingot.workflow.step1_plan._display_plan_summary")
    @patch("ingot.workflow.step1_plan._generate_plan_with_tui")
    def test_does_not_update_current_step_on_rejection(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = False  # Rejected

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True

        assert workflow_state.current_step == 1

        step_1_create_plan(workflow_state, MagicMock())

        assert workflow_state.current_step == 1  # Unchanged
