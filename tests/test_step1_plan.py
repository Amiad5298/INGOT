"""Tests for spec.workflow.step1_plan module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.workflow.state import WorkflowState
from spec.workflow.step1_plan import (
    _build_minimal_prompt,
    _create_plan_log_dir,
    _display_plan_summary,
    _generate_plan_with_tui,
    _get_log_base_dir,
    _run_clarification,
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
def mock_auggie_client():
    """Create a mock AuggieClient."""
    client = MagicMock()
    client.run_print.return_value = True
    client.run_print_with_output.return_value = (True, "Plan generated successfully")
    client.run_with_callback.return_value = (True, "Plan generated successfully")
    return client


# =============================================================================
# Tests for _get_log_base_dir()
# =============================================================================


class TestGetLogBaseDir:
    """Tests for _get_log_base_dir function."""

    def test_default_returns_spec_runs(self, monkeypatch):
        """Default returns Path('.spec/runs')."""
        monkeypatch.delenv("SPECFLOW_LOG_DIR", raising=False)
        result = _get_log_base_dir()
        assert result == Path(".spec/runs")

    def test_respects_environment_variable(self, monkeypatch):
        """Respects SPECFLOW_LOG_DIR environment variable."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", "/custom/log/dir")
        result = _get_log_base_dir()
        assert result == Path("/custom/log/dir")


# =============================================================================
# Tests for _create_plan_log_dir()
# =============================================================================


class TestCreatePlanLogDir:
    """Tests for _create_plan_log_dir function."""

    def test_creates_directory_with_correct_structure(self, tmp_path, monkeypatch):
        """Creates directory with correct structure ({base}/ticket_id/plan_generation)."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        result = _create_plan_log_dir("TEST-123")

        assert result.exists()
        assert result.is_dir()
        assert result.name == "plan_generation"
        assert result.parent.name == "TEST-123"

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        """Creates parent directories with parents=True."""
        log_dir = tmp_path / "deep" / "nested" / "path"
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(log_dir))

        result = _create_plan_log_dir("TEST-456")

        assert result.exists()
        assert "TEST-456" in str(result)
        assert "plan_generation" in str(result)

    def test_returns_correct_path(self, tmp_path, monkeypatch):
        """Returns correct Path object."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        result = _create_plan_log_dir("PROJ-789")

        assert isinstance(result, Path)
        assert result == tmp_path / "PROJ-789" / "plan_generation"


# =============================================================================
# Tests for _generate_plan_with_tui()
# =============================================================================


class TestGeneratePlanWithTui:
    """Tests for _generate_plan_with_tui function."""

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_returns_true_on_successful_generation(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Returns True on successful generation."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Plan output")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path)

        assert result is True

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_returns_false_when_user_requests_quit(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Returns False when user requests quit (via ui.check_quit_requested())."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = True  # User requested quit
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Plan output")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path)

        assert result is False

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_log_path_is_set_on_ui(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Log path is set on UI."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Plan output")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path)

        mock_tui.set_log_path.assert_called_once()
        log_path_arg = mock_tui.set_log_path.call_args[0][0]
        assert isinstance(log_path_arg, Path)
        assert ".log" in str(log_path_arg)

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_auggie_client_uses_subagent(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Auggie client is called with spec-planner subagent."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Plan output")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path)

        # Client is created without model (agent provides it)
        mock_auggie_class.assert_called_once_with()
        # Verify agent from state.subagent_names is passed
        call_kwargs = mock_client.run_with_callback.call_args.kwargs
        assert "agent" in call_kwargs
        assert call_kwargs["agent"] == workflow_state.subagent_names["planner"]

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_returns_false_on_auggie_failure(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Returns False on Auggie failure."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (False, "Error")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _generate_plan_with_tui(workflow_state, plan_path)

        assert result is False

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_dont_save_session_flag_is_passed(
        self, mock_tui_class, mock_auggie_class, workflow_state, tmp_path, monkeypatch
    ):
        """Verifies dont_save_session=True is passed to Auggie client."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui_class.return_value = mock_tui

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Plan output")
        mock_auggie_class.return_value = mock_client

        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        _generate_plan_with_tui(workflow_state, plan_path)

        # Verify dont_save_session=True is passed in the call
        mock_client.run_with_callback.assert_called_once()
        call_kwargs = mock_client.run_with_callback.call_args.kwargs
        assert "dont_save_session" in call_kwargs
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for _build_minimal_prompt()
# =============================================================================


class TestBuildMinimalPrompt:
    """Tests for _build_minimal_prompt function."""

    def test_prompt_includes_ticket_id(self, workflow_state, tmp_path):
        """Prompt includes ticket ID."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "TEST-123" in result

    def test_prompt_includes_ticket_title(self, workflow_state, tmp_path):
        """Prompt includes ticket title."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Test Feature" in result

    def test_prompt_includes_ticket_description(self, workflow_state, tmp_path):
        """Prompt includes ticket description."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Test description" in result

    def test_prompt_handles_empty_title(self, generic_ticket, tmp_path):
        """Prompt handles empty title gracefully by falling back to branch_summary."""
        generic_ticket.title = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path)

        # Should fall back to branch_summary when title is None
        assert generic_ticket.branch_summary in result
        assert "TEST-123" in result

    def test_prompt_handles_empty_description(self, generic_ticket, tmp_path):
        """Prompt handles empty description gracefully."""
        generic_ticket.description = None
        state = WorkflowState(ticket=generic_ticket)
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(state, plan_path)

        assert "Not available" in result

    def test_prompt_includes_user_context_when_provided(self, workflow_state, tmp_path):
        """Prompt includes user context when provided."""
        workflow_state.user_context = "Additional context from the user about the implementation."
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Additional context from the user" in result
        assert "Additional Context" in result

    def test_prompt_excludes_user_context_section_when_not_provided(self, workflow_state, tmp_path):
        """Prompt excludes user context section when not provided."""
        workflow_state.user_context = ""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"

        result = _build_minimal_prompt(workflow_state, plan_path)

        assert "Additional Context" not in result

    def test_prompt_includes_plan_file_path(self, workflow_state, tmp_path):
        """Prompt includes plan file path."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        result = _build_minimal_prompt(workflow_state, plan_path)

        # Should mention where to save the plan
        assert str(plan_path) in result


# =============================================================================
# Tests for _save_plan_from_output()
# =============================================================================


class TestSavePlanFromOutput:
    """Tests for _save_plan_from_output function."""

    def test_creates_template_with_ticket_id(self, workflow_state, tmp_path):
        """Creates template with ticket ID."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        content = plan_path.read_text()
        assert "TEST-123" in content

    def test_writes_to_correct_path(self, workflow_state, tmp_path):
        """Writes to correct path."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        assert plan_path.exists()

    def test_includes_all_template_sections(self, workflow_state, tmp_path):
        """Includes all template sections."""
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
        """Includes ticket title in summary."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        _save_plan_from_output(plan_path, workflow_state)

        content = plan_path.read_text()
        assert "Test Feature" in content


# =============================================================================
# Tests for _display_plan_summary()
# =============================================================================


class TestDisplayPlanSummary:
    """Tests for _display_plan_summary function."""

    @patch("spec.workflow.step1_plan.console")
    def test_reads_file_correctly(self, mock_console, tmp_path):
        """Reads file correctly."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n\nThis is the plan content.")

        _display_plan_summary(plan_path)

        # Should have printed something
        assert mock_console.print.called

    @patch("spec.workflow.step1_plan.console")
    def test_limits_preview_to_20_lines(self, mock_console, tmp_path):
        """Limits preview to 20 lines."""
        plan_path = tmp_path / "plan.md"
        # Create a file with 50 lines
        lines = [f"Line {i}" for i in range(50)]
        plan_path.write_text("\n".join(lines))

        _display_plan_summary(plan_path)

        # Should print "..." to indicate truncation
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("..." in c for c in calls)

    @patch("spec.workflow.step1_plan.console")
    def test_handles_short_files(self, mock_console, tmp_path):
        """Handles short files without truncation indicator."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan\n\nShort content.")

        _display_plan_summary(plan_path)

        # Should have printed the content
        assert mock_console.print.called


# =============================================================================
# Tests for _run_clarification()
# =============================================================================


class TestRunClarification:
    """Tests for _run_clarification function."""

    @patch("spec.workflow.step1_plan.AuggieClient")
    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_returns_true_when_user_declines_clarification(
        self, mock_confirm, mock_auggie_class, workflow_state, tmp_path
    ):
        """Returns True when user declines clarification prompt."""
        mock_confirm.return_value = False  # User declines

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")
        mock_auggie = MagicMock()

        result = _run_clarification(workflow_state, mock_auggie, plan_path)

        assert result is True
        mock_auggie_class.assert_not_called()

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_runs_auggie_with_clarification_prompt(self, mock_confirm, workflow_state, tmp_path):
        """Runs Auggie with correct clarification prompt."""
        mock_confirm.return_value = True  # User accepts
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = True

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        _run_clarification(workflow_state, mock_auggie, plan_path)

        mock_auggie.run_print.assert_called_once()
        prompt = mock_auggie.run_print.call_args[0][0]
        assert str(plan_path) in prompt
        assert "clarif" in prompt.lower()

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_always_returns_true_even_on_auggie_failure(
        self, mock_confirm, workflow_state, tmp_path
    ):
        """Always returns True (even on Auggie failure)."""
        mock_confirm.return_value = True
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = False  # Auggie fails

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        result = _run_clarification(workflow_state, mock_auggie, plan_path)

        assert result is True  # Should still return True

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_uses_planner_subagent(self, mock_confirm, workflow_state, tmp_path):
        """Uses spec-planner subagent for clarification."""
        mock_confirm.return_value = True
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = True

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        _run_clarification(workflow_state, mock_auggie, plan_path)

        # Verify run_print is called with the planner subagent
        mock_auggie.run_print.assert_called_once()
        call_kwargs = mock_auggie.run_print.call_args.kwargs
        assert "agent" in call_kwargs
        assert call_kwargs["agent"] == workflow_state.subagent_names["planner"]


# =============================================================================
# Tests for step_1_create_plan() - TUI mode
# =============================================================================


class TestStep1CreatePlanTuiMode:
    """Tests for step_1_create_plan in TUI mode."""

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    @patch("spec.ui.tui._should_use_tui")
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
        """Creates specs directory if not exists."""
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

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_generate_plan_with_tui(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Calls _generate_plan_with_tui for plan generation."""
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

    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_generation_fails(
        self, mock_generate, workflow_state, tmp_path, monkeypatch
    ):
        """Returns False when plan generation fails."""
        monkeypatch.chdir(tmp_path)
        mock_generate.return_value = False  # Generation fails

        result = step_1_create_plan(workflow_state, MagicMock())

        assert result is False


# =============================================================================
# Tests for step_1_create_plan() - Plan file handling
# =============================================================================


class TestStep1CreatePlanFileHandling:
    """Tests for step_1_create_plan plan file handling."""

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_saves_plan_file_on_success(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Saves plan file on success."""
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

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._save_plan_from_output")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
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
        """Calls _save_plan_from_output when plan file not created."""
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

    @patch("spec.workflow.step1_plan.print_error")
    @patch("spec.workflow.step1_plan._save_plan_from_output")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_save_fails_to_create_file(
        self, mock_generate, mock_save_plan, mock_print_error, workflow_state, tmp_path, monkeypatch
    ):
        """Returns False when _save_plan_from_output fails to create the file."""
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


# =============================================================================
# Tests for step_1_create_plan() - Clarification logic
# =============================================================================


class TestStep1CreatePlanClarification:
    """Tests for step_1_create_plan clarification logic."""

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._run_clarification")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_calls_run_clarification_when_skip_clarification_false(
        self,
        mock_generate,
        mock_clarify,
        mock_display,
        mock_confirm,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """Calls _run_clarification when skip_clarification=False."""
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True
        mock_clarify.return_value = True

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = False  # Don't skip

        step_1_create_plan(workflow_state, MagicMock())

        mock_clarify.assert_called_once()

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._run_clarification")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_skips_clarification_when_skip_clarification_true(
        self,
        mock_generate,
        mock_clarify,
        mock_display,
        mock_confirm,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """Skips clarification when skip_clarification=True."""
        monkeypatch.chdir(tmp_path)
        mock_confirm.return_value = True

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = True  # Skip

        step_1_create_plan(workflow_state, MagicMock())

        mock_clarify.assert_not_called()

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._run_clarification")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_clarification_returns_false(
        self,
        mock_generate,
        mock_clarify,
        mock_display,
        mock_confirm,
        workflow_state,
        tmp_path,
        monkeypatch,
    ):
        """Returns False immediately when _run_clarification returns False."""
        monkeypatch.chdir(tmp_path)
        mock_clarify.return_value = False  # Clarification fails/aborts

        specs_dir = tmp_path / "specs"
        plan_path = specs_dir / "TEST-123-plan.md"

        def create_plan(*args, **kwargs):
            specs_dir.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan")
            return True

        mock_generate.side_effect = create_plan
        workflow_state.skip_clarification = False  # Don't skip clarification

        result = step_1_create_plan(workflow_state, MagicMock())

        # Should return False because clarification returned False
        assert result is False
        # Clarification was called
        mock_clarify.assert_called_once()
        # Confirm was NOT called because we returned early
        mock_confirm.assert_not_called()


# =============================================================================
# Tests for step_1_create_plan() - Confirmation flow
# =============================================================================


class TestStep1CreatePlanConfirmation:
    """Tests for step_1_create_plan confirmation flow."""

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_true_when_plan_confirmed(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Returns True when plan confirmed."""
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

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_returns_false_when_plan_rejected(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Returns False when plan rejected."""
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

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_updates_current_step_to_2_on_success(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Updates state.current_step to 2 on success."""
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

    @patch("spec.workflow.step1_plan.prompt_confirm")
    @patch("spec.workflow.step1_plan._display_plan_summary")
    @patch("spec.workflow.step1_plan._generate_plan_with_tui")
    def test_does_not_update_current_step_on_rejection(
        self, mock_generate, mock_display, mock_confirm, workflow_state, tmp_path, monkeypatch
    ):
        """Does not update state.current_step when plan is rejected."""
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


# =============================================================================
# Tests for _run_clarification() with conflict detection
# =============================================================================


class TestRunClarificationWithConflict:
    """Tests for _run_clarification conflict-aware behavior."""

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_includes_conflict_summary_in_prompt_when_conflict_detected(
        self, mock_confirm, workflow_state, tmp_path
    ):
        """Prompt includes conflict summary when state.conflict_detected is True."""
        mock_confirm.return_value = True
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = True

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        # Set conflict fields
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = "Ticket says add X but user says remove X."

        _run_clarification(workflow_state, mock_auggie, plan_path)

        mock_auggie.run_print.assert_called_once()
        prompt = mock_auggie.run_print.call_args[0][0]

        # Verify conflict context is in prompt
        assert "conflict" in prompt.lower()
        assert "Ticket says add X but user says remove X" in prompt
        assert "FIRST priority" in prompt

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_no_conflict_context_when_conflict_not_detected(
        self, mock_confirm, workflow_state, tmp_path
    ):
        """Prompt does not include conflict context when state.conflict_detected is False."""
        mock_confirm.return_value = True
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = True

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        # Ensure no conflict
        workflow_state.conflict_detected = False
        workflow_state.conflict_summary = ""

        _run_clarification(workflow_state, mock_auggie, plan_path)

        mock_auggie.run_print.assert_called_once()
        prompt = mock_auggie.run_print.call_args[0][0]

        # Verify conflict-specific context is NOT in prompt
        assert "FIRST priority" not in prompt
        assert "IMPORTANT: A conflict was detected" not in prompt

    @patch("spec.workflow.step1_plan.prompt_confirm")
    def test_no_conflict_context_when_detected_but_no_summary(
        self, mock_confirm, workflow_state, tmp_path
    ):
        """Prompt does not include conflict context when conflict_detected but summary is empty."""
        mock_confirm.return_value = True
        mock_auggie = MagicMock()
        mock_auggie.run_print.return_value = True

        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        # conflict_detected but empty summary
        workflow_state.conflict_detected = True
        workflow_state.conflict_summary = ""

        _run_clarification(workflow_state, mock_auggie, plan_path)

        mock_auggie.run_print.assert_called_once()
        prompt = mock_auggie.run_print.call_args[0][0]

        # Verify conflict-specific context is NOT in prompt (empty summary)
        assert "FIRST priority" not in prompt
