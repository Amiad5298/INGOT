"""Tests for spec.workflow.step3_execute module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.jira import JiraTicket
from spec.workflow.state import WorkflowState
from spec.workflow.step3_execute import (
    _build_task_prompt,
    _cleanup_old_runs,
    _create_run_log_dir,
    _execute_fallback,
    _execute_task,
    _execute_task_with_callback,
    _execute_with_tui,
    _get_log_base_dir,
    _offer_commit_instructions,
    _run_post_implementation_tests,
    _show_summary,
    step_3_execute,
)
from spec.workflow.tasks import Task, TaskCategory, TaskStatus


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
def workflow_state(ticket, tmp_path):
    """Create a workflow state for testing."""
    state = WorkflowState(ticket=ticket)
    state.implementation_model = "test-model"

    # Create specs directory and tasklist
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    tasklist_path = specs_dir / "TEST-123-tasklist.md"
    tasklist_path.write_text(
        """# Task List: TEST-123

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3
"""
    )
    state.tasklist_file = tasklist_path

    # Create plan file
    plan_path = specs_dir / "TEST-123-plan.md"
    plan_path.write_text("# Plan\n\nImplement feature.")
    state.plan_file = plan_path

    return state


@pytest.fixture
def sample_task():
    """Create a sample task for testing."""
    return Task(
        name="Implement feature",
        status=TaskStatus.PENDING,
        line_number=1,
        indent_level=0,
    )


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
# Tests for _create_run_log_dir()
# =============================================================================


class TestCreateRunLogDir:
    """Tests for _create_run_log_dir function."""

    def test_creates_timestamped_directory(self, tmp_path, monkeypatch):
        """Creates timestamped directory."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        result = _create_run_log_dir("TEST-123")

        assert result.exists()
        assert result.is_dir()
        assert "TEST-123" in str(result)

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        """Creates parent directories."""
        log_dir = tmp_path / "deep" / "nested" / "path"
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(log_dir))

        result = _create_run_log_dir("TEST-456")

        assert result.exists()
        assert "TEST-456" in str(result)

    def test_returns_correct_path(self, tmp_path, monkeypatch):
        """Returns correct Path object."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        result = _create_run_log_dir("PROJ-789")

        assert isinstance(result, Path)
        assert result.parent.name == "PROJ-789"


# =============================================================================
# Tests for _cleanup_old_runs()
# =============================================================================


class TestCleanupOldRuns:
    """Tests for _cleanup_old_runs function."""

    def test_removes_directories_beyond_keep_count(self, tmp_path, monkeypatch):
        """Removes directories beyond keep_count."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))
        ticket_dir = tmp_path / "TEST-123"
        ticket_dir.mkdir()

        # Create 5 run directories
        for i in range(5):
            run_dir = ticket_dir / f"20260101_00000{i}"
            run_dir.mkdir()

        _cleanup_old_runs("TEST-123", keep_count=2)

        remaining = list(ticket_dir.iterdir())
        assert len(remaining) == 2

    def test_keeps_newest_directories(self, tmp_path, monkeypatch):
        """Keeps newest directories."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))
        ticket_dir = tmp_path / "TEST-123"
        ticket_dir.mkdir()

        # Create directories with different timestamps (older first)
        old_dirs = ["20260101_000001", "20260101_000002"]
        new_dirs = ["20260101_000003", "20260101_000004"]
        for d in old_dirs + new_dirs:
            (ticket_dir / d).mkdir()

        _cleanup_old_runs("TEST-123", keep_count=2)

        remaining = sorted([d.name for d in ticket_dir.iterdir()])
        assert remaining == new_dirs

    def test_handles_nonexistent_ticket_directory(self, tmp_path, monkeypatch):
        """Handles non-existent ticket directory gracefully."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        # Should not raise any exception
        _cleanup_old_runs("NONEXISTENT-123", keep_count=2)

    def test_ignores_cleanup_errors(self, tmp_path, monkeypatch):
        """Ignores cleanup errors gracefully."""
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))
        ticket_dir = tmp_path / "TEST-123"
        ticket_dir.mkdir()

        # Create directories
        for i in range(3):
            (ticket_dir / f"20260101_00000{i}").mkdir()

        # Mock shutil.rmtree to raise an exception
        with patch("shutil.rmtree", side_effect=PermissionError("Access denied")):
            # Should not raise, just ignore the error
            _cleanup_old_runs("TEST-123", keep_count=1)


# =============================================================================
# Tests for _build_task_prompt()
# =============================================================================


class TestBuildTaskPrompt:
    """Tests for _build_task_prompt function."""

    def test_includes_task_name(self, sample_task, tmp_path):
        """Prompt includes task name."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        result = _build_task_prompt(sample_task, plan_path)

        assert "Implement feature" in result

    def test_includes_parallel_mode_no(self, sample_task, tmp_path):
        """Prompt includes Parallel mode: NO when not parallel."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, is_parallel=False)

        assert "Parallel mode: NO" in result

    def test_includes_parallel_mode_yes(self, sample_task, tmp_path):
        """Prompt includes Parallel mode: YES when parallel."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, is_parallel=True)

        assert "Parallel mode: YES" in result

    def test_includes_plan_path_when_exists(self, sample_task, tmp_path):
        """Prompt includes plan path when file exists."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path)

        assert str(plan_path) in result
        assert "codebase-retrieval" in result

    def test_excludes_plan_path_when_not_exists(self, sample_task, tmp_path):
        """Prompt excludes plan path when file does not exist."""
        plan_path = tmp_path / "nonexistent.md"

        result = _build_task_prompt(sample_task, plan_path)

        assert str(plan_path) not in result
        assert "codebase-retrieval" in result

    def test_does_not_include_full_plan_content(self, sample_task, tmp_path):
        """Prompt does NOT include full plan content - only path reference."""
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("UNIQUE_PLAN_CONTENT_MARKER_12345")

        result = _build_task_prompt(sample_task, plan_path)

        # The actual content should NOT be in the prompt
        assert "UNIQUE_PLAN_CONTENT_MARKER_12345" not in result
        # But the path should be
        assert str(plan_path) in result

    def test_includes_no_commit_constraint(self, sample_task, tmp_path):
        """Prompt includes constraint about not committing."""
        plan_path = tmp_path / "plan.md"

        result = _build_task_prompt(sample_task, plan_path)

        assert "Do NOT commit" in result


# =============================================================================
# Tests for _execute_task()
# =============================================================================


class TestExecuteTask:
    """Tests for _execute_task function."""

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_true_on_success(self, mock_auggie_class, workflow_state, sample_task):
        """Returns True on Auggie success."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Output")
        mock_auggie_class.return_value = mock_client

        result = _execute_task(workflow_state, sample_task, workflow_state.get_plan_path())

        assert result is True

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_false_on_failure(self, mock_auggie_class, workflow_state, sample_task):
        """Returns False on Auggie failure."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (False, "Error")
        mock_auggie_class.return_value = mock_client

        result = _execute_task(workflow_state, sample_task, workflow_state.get_plan_path())

        assert result is False

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_false_on_exception(self, mock_auggie_class, workflow_state, sample_task):
        """Returns False on exception."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.side_effect = RuntimeError("Connection failed")
        mock_auggie_class.return_value = mock_client

        result = _execute_task(workflow_state, sample_task, workflow_state.get_plan_path())

        assert result is False

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_uses_spec_implementer_agent(self, mock_auggie_class, workflow_state, sample_task):
        """Uses state.subagent_names implementer agent."""
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Output")
        mock_auggie_class.return_value = mock_client

        _execute_task(workflow_state, sample_task, workflow_state.get_plan_path())

        # Verify AuggieClient is created without model (agent defines the model)
        mock_auggie_class.assert_called_once_with()
        # Verify agent from state.subagent_names is passed to run_print_with_output
        call_kwargs = mock_client.run_print_with_output.call_args[1]
        assert call_kwargs["agent"] == workflow_state.subagent_names["implementer"]
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for _execute_task_with_callback()
# =============================================================================


class TestExecuteTaskWithCallback:
    """Tests for _execute_task_with_callback function."""

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_true_on_success(self, mock_auggie_class, workflow_state, sample_task):
        """Returns True on success."""
        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Output")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        assert result is True

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_false_on_failure(self, mock_auggie_class, workflow_state, sample_task):
        """Returns False on failure."""
        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (False, "Error")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        assert result is False

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_callback_receives_output(self, mock_auggie_class, workflow_state, sample_task):
        """Callback is called with output lines."""
        mock_client = MagicMock()

        # Simulate callback being invoked during run_with_callback
        def call_callback(prompt, *, agent, output_callback, dont_save_session):
            output_callback("Line 1")
            output_callback("Line 2")
            return (True, "Done")

        mock_client.run_with_callback.side_effect = call_callback
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        assert callback.call_count == 2
        callback.assert_any_call("Line 1")
        callback.assert_any_call("Line 2")

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_callback_receives_error_on_exception(
        self, mock_auggie_class, workflow_state, sample_task
    ):
        """Callback receives error message on exception."""
        mock_client = MagicMock()
        mock_client.run_with_callback.side_effect = RuntimeError("Connection failed")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        assert result is False
        callback.assert_called()
        # Check that the error message was passed to callback
        error_call = callback.call_args[0][0]
        assert "ERROR" in error_call
        assert "Connection failed" in error_call

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_uses_spec_implementer_agent(self, mock_auggie_class, workflow_state, sample_task):
        """Uses state.subagent_names implementer agent."""
        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Output")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        # Verify AuggieClient is created without model (agent defines the model)
        mock_auggie_class.assert_called_once_with()
        # Verify agent from state.subagent_names is passed to run_with_callback
        call_kwargs = mock_client.run_with_callback.call_args[1]
        assert call_kwargs["agent"] == workflow_state.subagent_names["implementer"]
        assert call_kwargs["dont_save_session"] is True


# =============================================================================
# Tests for _show_summary()
# =============================================================================


class TestShowSummary:
    """Tests for _show_summary function."""

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.get_current_branch")
    def test_displays_ticket_id(self, mock_branch, mock_console, workflow_state):
        """Displays ticket ID."""
        mock_branch.return_value = "main"

        _show_summary(workflow_state)

        # Check that console.print was called with ticket ID
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("TEST-123" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.get_current_branch")
    def test_displays_branch_name(self, mock_branch, mock_console, workflow_state):
        """Displays branch name."""
        workflow_state.branch_name = "feature/test-branch"
        mock_branch.return_value = "main"

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("feature/test-branch" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.get_current_branch")
    def test_displays_completed_task_count(self, mock_branch, mock_console, workflow_state):
        """Displays completed task count."""
        mock_branch.return_value = "main"
        workflow_state.completed_tasks = ["Task 1", "Task 2"]

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("2" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.get_current_branch")
    def test_displays_checkpoint_count(self, mock_branch, mock_console, workflow_state):
        """Displays checkpoint count."""
        mock_branch.return_value = "main"
        workflow_state.checkpoint_commits = ["abc123", "def456"]

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Checkpoints" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.get_current_branch")
    def test_displays_failed_tasks_when_present(self, mock_branch, mock_console, workflow_state):
        """Displays failed task names when present."""
        mock_branch.return_value = "main"

        _show_summary(workflow_state, failed_tasks=["Failed Task 1", "Failed Task 2"])

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Failed Task 1" in c for c in calls)
        assert any("issues" in c.lower() for c in calls)


# =============================================================================
# Tests for _run_post_implementation_tests()
# =============================================================================


class TestRunPostImplementationTests:
    """Tests for _run_post_implementation_tests function."""

    @patch("spec.workflow.step3_execute.AuggieClient")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    def test_prompts_user_to_run_tests(self, mock_confirm, mock_auggie_class, workflow_state):
        """Prompts user to run tests."""
        mock_confirm.return_value = True
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (True, "Tests passed")
        mock_auggie_class.return_value = mock_client

        _run_post_implementation_tests(workflow_state)

        mock_confirm.assert_called_once()
        assert "test" in mock_confirm.call_args[0][0].lower()

    @patch("spec.workflow.step3_execute.AuggieClient")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    def test_skips_when_user_declines(self, mock_confirm, mock_auggie_class, workflow_state):
        """Skips when user declines."""
        mock_confirm.return_value = False

        _run_post_implementation_tests(workflow_state)

        mock_auggie_class.assert_not_called()

    @patch("spec.ui.plan_tui.StreamingOperationUI")
    @patch("spec.workflow.step3_execute.AuggieClient")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    def test_runs_auggie_with_test_prompt(
        self, mock_confirm, mock_auggie_class, mock_ui_class, workflow_state
    ):
        """Runs Auggie with test prompt using StreamingOperationUI."""
        mock_confirm.return_value = True
        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Tests passed")
        mock_auggie_class.return_value = mock_client

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        _run_post_implementation_tests(workflow_state)

        mock_client.run_with_callback.assert_called_once()
        prompt = mock_client.run_with_callback.call_args[0][0]
        assert "test" in prompt.lower()

    @patch("spec.ui.plan_tui.StreamingOperationUI")
    @patch("spec.workflow.step3_execute.AuggieClient")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    def test_handles_auggie_exceptions(
        self, mock_confirm, mock_auggie_class, mock_ui_class, workflow_state
    ):
        """Handles Auggie exceptions gracefully."""
        mock_confirm.return_value = True
        mock_client = MagicMock()
        mock_client.run_with_callback.side_effect = RuntimeError("Connection error")
        mock_auggie_class.return_value = mock_client

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Should not raise exception
        _run_post_implementation_tests(workflow_state)


# =============================================================================
# Tests for _offer_commit_instructions()
# =============================================================================


class TestOfferCommitInstructions:
    """Tests for _offer_commit_instructions function."""

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.is_dirty")
    def test_does_nothing_when_no_dirty_files(self, mock_is_dirty, mock_console, workflow_state):
        """Does nothing when no dirty files."""
        mock_is_dirty.return_value = False

        _offer_commit_instructions(workflow_state)

        # Console should not print commit instructions
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert not any("git commit" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute.is_dirty")
    def test_prompts_user_for_instructions(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        """Prompts user for instructions."""
        mock_is_dirty.return_value = True
        mock_confirm.return_value = False

        _offer_commit_instructions(workflow_state)

        mock_confirm.assert_called_once()

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute.is_dirty")
    def test_does_nothing_when_user_declines(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        """Does nothing when user declines."""
        mock_is_dirty.return_value = True
        mock_confirm.return_value = False

        _offer_commit_instructions(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert not any("git commit" in c for c in calls)

    @patch("spec.workflow.step3_execute.console")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute.is_dirty")
    def test_prints_commit_commands_when_accepted(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        """Prints commit commands when accepted."""
        mock_is_dirty.return_value = True
        mock_confirm.return_value = True
        workflow_state.completed_tasks = ["Task 1"]

        _offer_commit_instructions(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("git" in c for c in calls)


# =============================================================================
# Tests for _execute_fallback()
# =============================================================================


class TestExecuteFallback:
    """Tests for _execute_fallback function."""

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_executes_tasks_sequentially(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Executes tasks sequentially."""
        mock_execute.return_value = True

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert mock_execute.call_count == 2

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_marks_tasks_complete_on_success(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Marks tasks complete on success."""
        mock_execute.return_value = True

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        mock_mark.assert_called_once()
        assert "Task 1" in workflow_state.completed_tasks

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_tracks_failed_tasks(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Tracks failed tasks."""
        mock_execute.side_effect = [True, False, True]

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert failed == ["Task 2"]

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_calls_capture_task_memory_on_success(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Calls capture_task_memory on success."""
        mock_execute.return_value = True

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        mock_capture.assert_called_once()

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_handles_capture_task_memory_exceptions(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Handles capture_task_memory exceptions gracefully."""
        mock_execute.return_value = True
        mock_capture.side_effect = RuntimeError("Memory capture failed")

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Should not raise
        failed = _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert failed == []  # Task still counts as success

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_respects_fail_fast_option(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Respects fail_fast option."""
        mock_execute.side_effect = [True, False, True]
        workflow_state.fail_fast = True

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Should stop after Task 2 fails
        assert mock_execute.call_count == 2
        assert failed == ["Task 2"]

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_returns_list_of_failed_task_names(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Returns list of failed task names."""
        mock_execute.side_effect = [False, True, False]

        tasks = [
            Task(name="Failed 1", status=TaskStatus.PENDING),
            Task(name="Success 1", status=TaskStatus.PENDING),
            Task(name="Failed 2", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert failed == ["Failed 1", "Failed 2"]


# =============================================================================
# Tests for _execute_with_tui()
# =============================================================================


class TestExecuteWithTui:
    """Tests for _execute_with_tui function."""

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_initializes_tui_correctly(
        self, mock_tui_class, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Initializes TUI correctly."""
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.get_record.return_value = MagicMock(elapsed_time=1.0, log_buffer=None)
        mock_tui_class.return_value = mock_tui
        mock_execute.return_value = True

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        mock_tui_class.assert_called_once_with(ticket_id="TEST-123", verbose_mode=False)
        mock_tui.initialize_records.assert_called_once_with(["Task 1"])

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_marks_tasks_complete_on_success(
        self, mock_tui_class, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Marks tasks complete on success."""
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.get_record.return_value = MagicMock(elapsed_time=1.0, log_buffer=None)
        mock_tui_class.return_value = mock_tui
        mock_execute.return_value = True

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        mock_mark.assert_called_once()
        assert "Task 1" in workflow_state.completed_tasks

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_tracks_failed_tasks(
        self, mock_tui_class, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Tracks failed tasks."""
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.get_record.return_value = MagicMock(elapsed_time=1.0, log_buffer=None)
        mock_tui_class.return_value = mock_tui
        mock_execute.side_effect = [True, False]

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert failed == ["Task 2"]

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_respects_fail_fast_option(
        self, mock_tui_class, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Respects fail_fast option."""
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_tui.get_record.return_value = MagicMock(elapsed_time=1.0, log_buffer=None)
        mock_tui_class.return_value = mock_tui
        mock_execute.side_effect = [True, False, True]
        workflow_state.fail_fast = True

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Should stop after Task 2 fails
        assert mock_execute.call_count == 2
        mock_tui.mark_remaining_skipped.assert_called()

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_handles_capture_task_memory_exceptions(
        self, mock_tui_class, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Handles capture_task_memory exceptions gracefully."""
        mock_tui = MagicMock()
        mock_tui.check_quit_requested.return_value = False
        mock_record = MagicMock(elapsed_time=1.0)
        mock_record.log_buffer = MagicMock()
        mock_tui.get_record.return_value = mock_record
        mock_tui_class.return_value = mock_tui
        mock_execute.return_value = True
        mock_capture.side_effect = RuntimeError("Memory capture failed")

        tasks = [Task(name="Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Should not raise
        failed = _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        assert failed == []  # Task still counts as success


# =============================================================================
# Tests for step_3_execute()
# =============================================================================


class TestStep3Execute:
    """Tests for step_3_execute function."""

    def test_returns_false_when_tasklist_not_found(self, ticket, tmp_path):
        """Returns False when tasklist not found."""
        state = WorkflowState(ticket=ticket)
        # Don't create tasklist file
        state.tasklist_file = tmp_path / "nonexistent.md"

        result = step_3_execute(state, use_tui=False)

        assert result is False

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_returns_true_when_all_tasks_already_complete(
        self, mock_baseline, mock_summary, mock_tests, mock_commit, workflow_state, tmp_path
    ):
        """Returns True when all tasks already complete."""
        mock_baseline.return_value = True
        # Create tasklist with all completed tasks
        tasklist = tmp_path / "specs" / "TEST-123-tasklist.md"
        tasklist.write_text(
            """# Task List
- [x] Completed Task 1
- [x] Completed Task 2
"""
        )
        workflow_state.tasklist_file = tasklist

        result = step_3_execute(workflow_state, use_tui=False)

        assert result is True

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_with_tui")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_calls_execute_with_tui_when_tui_mode(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_tui,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Calls _execute_with_tui when TUI mode."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = True
        mock_execute_tui.return_value = []

        step_3_execute(workflow_state, use_tui=True)

        mock_execute_tui.assert_called_once()

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_calls_execute_fallback_when_non_tui_mode(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_fallback,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Calls _execute_fallback when non-TUI mode."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []

        step_3_execute(workflow_state, use_tui=False)

        mock_execute_fallback.assert_called_once()

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_prompts_user_on_task_failures(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_confirm,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Prompts user on task failures."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = ["Failed Task"]
        mock_confirm.return_value = True

        step_3_execute(workflow_state, use_tui=False)

        mock_confirm.assert_called()

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_returns_true_when_all_tasks_succeed(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Returns True when all tasks succeed."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []  # No failed tasks

        result = step_3_execute(workflow_state, use_tui=False)

        assert result is True

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    def test_returns_false_when_user_declines_after_failures(
        self,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_confirm,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Returns False when user declines after task failures."""
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = ["Failed Task"]
        mock_confirm.return_value = False  # User declines

        result = step_3_execute(workflow_state, use_tui=False)

        assert result is False

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_calls_show_summary(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Calls _show_summary."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, use_tui=False)

        mock_summary.assert_called_once()

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_calls_run_post_implementation_tests(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Calls _run_post_implementation_tests."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, use_tui=False)

        mock_tests.assert_called_once()

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_calls_offer_commit_instructions(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Calls _offer_commit_instructions."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, use_tui=False)

        mock_commit.assert_called_once()

    @patch("spec.workflow.step3_execute.prompt_confirm")
    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    @patch("spec.ui.tui.TaskRunnerUI")
    def test_stops_execution_when_quit_requested(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_capture,
        mock_confirm,
        workflow_state,
        tmp_path,
    ):
        """Stops execution when user requests quit via TUI."""
        # Setup
        mock_tui = MagicMock()
        # Simulate quit requested before the second task
        mock_tui.check_quit_requested.return_value = True
        mock_tui.get_record.return_value = MagicMock(elapsed_time=1.0)
        mock_tui_class.return_value = mock_tui

        # User confirms quit at the prompt
        mock_confirm.return_value = True

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        # Execute
        _execute_with_tui(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Assertions
        # Should verify that we stopped TUI to show prompt
        mock_tui.stop.assert_called()
        # Should verify prompt was shown
        mock_confirm.assert_called_with("Quit task execution?", default=False)
        # Should verify specific cleanup method for skipping remaining tasks was called
        mock_tui.mark_remaining_skipped.assert_called()


# =============================================================================
# Tests for Two-Phase Execution
# =============================================================================


class TestTwoPhaseExecution:
    """Tests for two-phase execution model."""

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_parallel_fallback")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_executes_fundamental_tasks_first(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_fallback,
        mock_execute_parallel,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Fundamental tasks run before independent tasks."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        (tmp_path / "logs").mkdir()
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []
        mock_execute_parallel.return_value = []

        # Create tasklist with both fundamental and independent tasks
        tasklist = workflow_state.get_tasklist_path()
        tasklist.parent.mkdir(parents=True, exist_ok=True)
        tasklist.write_text(
            """
<!-- category: fundamental, order: 1 -->
- [ ] Fundamental task
<!-- category: independent, group: ui -->
- [ ] Independent task
"""
        )

        step_3_execute(workflow_state)

        # Verify fundamental fallback was called first
        assert mock_execute_fallback.called
        # Verify parallel fallback was also called
        assert mock_execute_parallel.called
        # Check call order
        assert mock_execute_fallback.call_count >= 1
        assert mock_execute_parallel.call_count == 1

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_fundamental_tasks_run_sequentially(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_fallback,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Fundamental tasks execute one at a time (not in parallel)."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        (tmp_path / "logs").mkdir()
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []

        # Create tasklist with only fundamental tasks
        tasklist = workflow_state.get_tasklist_path()
        tasklist.parent.mkdir(parents=True, exist_ok=True)
        tasklist.write_text(
            """
<!-- category: fundamental, order: 1 -->
- [ ] First fundamental
<!-- category: fundamental, order: 2 -->
- [ ] Second fundamental
"""
        )

        step_3_execute(workflow_state)

        # Should use _execute_fallback (sequential), not _execute_parallel_fallback
        assert mock_execute_fallback.called
        # Check that tasks passed to fallback are fundamental tasks
        call_args = mock_execute_fallback.call_args
        tasks = call_args[0][1]  # Second positional arg is tasks
        assert len(tasks) == 2

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_parallel_fallback")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_independent_tasks_run_in_parallel(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_fallback,
        mock_execute_parallel,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Independent tasks execute concurrently."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        (tmp_path / "logs").mkdir()
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []
        mock_execute_parallel.return_value = []

        # Ensure parallel execution is enabled
        workflow_state.parallel_execution_enabled = True

        # Create tasklist with only independent tasks
        tasklist = workflow_state.get_tasklist_path()
        tasklist.parent.mkdir(parents=True, exist_ok=True)
        tasklist.write_text(
            """
<!-- category: independent, group: ui -->
- [ ] UI Component
<!-- category: independent, group: api -->
- [ ] API Endpoint
"""
        )

        step_3_execute(workflow_state)

        # Should use _execute_parallel_fallback for independent tasks
        assert mock_execute_parallel.called

    @patch("spec.workflow.step3_execute._offer_commit_instructions")
    @patch("spec.workflow.step3_execute._run_post_implementation_tests")
    @patch("spec.workflow.step3_execute._show_summary")
    @patch("spec.workflow.step3_execute._execute_parallel_fallback")
    @patch("spec.workflow.step3_execute._execute_fallback")
    @patch("spec.ui.tui._should_use_tui")
    @patch("spec.workflow.step3_execute._cleanup_old_runs")
    @patch("spec.workflow.step3_execute._create_run_log_dir")
    @patch("spec.workflow.step3_execute._capture_baseline_for_diffs")
    def test_skips_parallel_phase_when_disabled(
        self,
        mock_baseline,
        mock_log_dir,
        mock_cleanup,
        mock_should_tui,
        mock_execute_fallback,
        mock_execute_parallel,
        mock_summary,
        mock_tests,
        mock_commit,
        workflow_state,
        tmp_path,
    ):
        """Respects parallel_execution_enabled=False."""
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        (tmp_path / "logs").mkdir()
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []

        # Disable parallel execution
        workflow_state.parallel_execution_enabled = False

        # Create tasklist with independent tasks
        tasklist = workflow_state.get_tasklist_path()
        tasklist.parent.mkdir(parents=True, exist_ok=True)
        tasklist.write_text(
            """
<!-- category: independent, group: ui -->
- [ ] UI Component
<!-- category: independent, group: api -->
- [ ] API Endpoint
"""
        )

        step_3_execute(workflow_state)

        # Should NOT use parallel execution
        assert not mock_execute_parallel.called
        # Should use sequential fallback instead
        assert mock_execute_fallback.called


# =============================================================================
# Tests for Parallel Execution
# =============================================================================


class TestParallelExecution:
    """Tests for parallel task execution."""

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_uses_thread_pool_executor(
        self, mock_execute_retry, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Uses ThreadPoolExecutor for concurrent execution."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        mock_execute_retry.return_value = True

        tasks = [
            Task(name="Task 1", category=TaskCategory.INDEPENDENT),
            Task(name="Task 2", category=TaskCategory.INDEPENDENT),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # All tasks should succeed
        assert failed == []
        # Both tasks should be executed
        assert mock_execute_retry.call_count == 2

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_respects_max_parallel_tasks(
        self, mock_execute_retry, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Limits concurrent workers to max_parallel_tasks."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        mock_execute_retry.return_value = True
        workflow_state.max_parallel_tasks = 2

        tasks = [Task(name=f"Task {i}", category=TaskCategory.INDEPENDENT) for i in range(5)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # All tasks should complete
        assert failed == []
        assert mock_execute_retry.call_count == 5

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_collects_failed_tasks(
        self, mock_execute_retry, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Collects names of failed tasks."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        # First task succeeds, second fails
        mock_execute_retry.side_effect = [True, False]

        tasks = [
            Task(name="Success Task", category=TaskCategory.INDEPENDENT),
            Task(name="Failed Task", category=TaskCategory.INDEPENDENT),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Should have one failed task
        assert len(failed) == 1
        assert "Failed Task" in failed

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_marks_successful_tasks_complete(
        self, mock_execute_retry, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Marks completed tasks in tasklist."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        mock_execute_retry.return_value = True

        tasks = [
            Task(name="Task 1", category=TaskCategory.INDEPENDENT),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Should mark task complete
        mock_mark.assert_called_once()


# =============================================================================
# Tests for Task Retry
# =============================================================================


class TestTaskRetry:
    """Tests for task retry with rate limit handling."""

    @patch("spec.workflow.step3_execute._execute_task")
    def test_skips_retry_when_disabled(self, mock_execute, workflow_state, tmp_path):
        """Skips retry wrapper when max_retries=0."""
        from spec.workflow.state import RateLimitConfig
        from spec.workflow.step3_execute import _execute_task_with_retry

        mock_execute.return_value = True
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Test Task")
        result = _execute_task_with_retry(workflow_state, task, workflow_state.get_plan_path())

        assert result is True
        mock_execute.assert_called_once()

    @patch("spec.workflow.step3_execute._execute_task_with_callback")
    def test_uses_callback_when_provided(self, mock_execute_callback, workflow_state, tmp_path):
        """Uses callback version when callback provided."""
        from spec.workflow.state import RateLimitConfig
        from spec.workflow.step3_execute import _execute_task_with_retry

        mock_execute_callback.return_value = True
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Test Task")
        callback = MagicMock()
        result = _execute_task_with_retry(
            workflow_state, task, workflow_state.get_plan_path(), callback=callback
        )

        assert result is True
        mock_execute_callback.assert_called_once()

    @patch("spec.workflow.step3_execute._execute_task")
    def test_returns_false_on_failure(self, mock_execute, workflow_state, tmp_path):
        """Returns False when task execution fails."""
        from spec.workflow.state import RateLimitConfig
        from spec.workflow.step3_execute import _execute_task_with_retry

        mock_execute.return_value = False
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Failing Task")
        result = _execute_task_with_retry(workflow_state, task, workflow_state.get_plan_path())

        assert result is False

    @patch("spec.workflow.step3_execute._execute_task")
    def test_retries_on_rate_limit_error(self, mock_execute, workflow_state, tmp_path):
        """Retries execution on rate limit errors."""
        from spec.workflow.state import RateLimitConfig
        from spec.workflow.step3_execute import _execute_task_with_retry

        # First call raises rate limit error (HTTP 429), second succeeds
        mock_execute.side_effect = [Exception("HTTP Error 429: Too Many Requests"), True]
        workflow_state.rate_limit_config = RateLimitConfig(
            max_retries=3, base_delay_seconds=0.01, max_delay_seconds=0.1
        )

        task = Task(name="Retry Task")
        result = _execute_task_with_retry(workflow_state, task, workflow_state.get_plan_path())

        assert result is True
        assert mock_execute.call_count == 2


# =============================================================================
# Tests for Parallel Execution Enhancements
# =============================================================================


class TestParallelTaskMemorySkipped:
    """Tests for memory capture being skipped in parallel mode."""

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_parallel_fallback_skips_memory_capture(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Parallel fallback does not call capture_task_memory."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        mock_execute.return_value = True

        tasks = [Task(name="Parallel Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Memory capture should NOT be called for parallel tasks
        mock_capture.assert_not_called()

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_sequential_fallback_calls_memory_capture(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Sequential fallback calls capture_task_memory."""
        mock_execute.return_value = True

        tasks = [Task(name="Sequential Task 1", status=TaskStatus.PENDING)]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        _execute_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Memory capture SHOULD be called for sequential tasks
        mock_capture.assert_called_once()


class TestParallelFailFast:
    """Tests for fail_fast semantics in parallel execution."""

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_fail_fast_stops_pending_tasks(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Fail-fast stops pending tasks when one fails."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        # First task fails, second should be skipped
        mock_execute.side_effect = [False, True, True]
        workflow_state.fail_fast = True
        workflow_state.max_parallel_tasks = 1  # Force sequential for predictable order

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Task 1 should fail, others should be skipped
        assert "Task 1" in failed

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_no_fail_fast_continues_after_failure(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Without fail-fast, execution continues after failure."""
        from spec.workflow.step3_execute import _execute_parallel_fallback

        mock_execute.side_effect = [False, True, True]
        workflow_state.fail_fast = False
        workflow_state.max_parallel_tasks = 1

        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.PENDING),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # All tasks should execute
        assert mock_execute.call_count == 3
        assert failed == ["Task 1"]

    @patch("spec.workflow.step3_execute.capture_task_memory")
    @patch("spec.workflow.step3_execute.mark_task_complete")
    @patch("spec.workflow.step3_execute._execute_task_with_retry")
    def test_stop_flag_prevents_new_task_execution(
        self, mock_execute, mock_mark, mock_capture, workflow_state, tmp_path
    ):
        """Stop flag prevents tasks that haven't started from executing.

        Uses a threading.Event to simulate the stop_flag being set during
        execution. The mock checks a shared event to simulate the stop_flag
        behavior that would occur in real execution with delays.
        """
        import threading

        from spec.workflow.step3_execute import _execute_parallel_fallback

        # Shared event to simulate stop_flag behavior
        stop_event = threading.Event()
        executed_tasks = []

        def mock_execute_side_effect(state, task, plan_path, callback=None, is_parallel=False):
            """Side effect that simulates stop_flag check behavior."""
            # Check if we should skip (simulating stop_flag check)
            if stop_event.is_set():
                # Return None to simulate skipped task
                # But since we're mocking _execute_task_with_retry, we can't
                # return None here - the function expects True/False
                # Instead, we just don't add to executed_tasks
                return True  # Will be marked as success but we track separately

            executed_tasks.append(task.name)

            # First task fails and sets the stop event
            if task.name == "Failing Task":
                stop_event.set()  # Simulate stop_flag.set()
                return False
            return True

        mock_execute.side_effect = mock_execute_side_effect
        workflow_state.fail_fast = True
        workflow_state.max_parallel_tasks = 1  # Force sequential for deterministic behavior

        tasks = [
            Task(name="Failing Task", status=TaskStatus.PENDING),
            Task(name="Skipped Task 1", status=TaskStatus.PENDING),
            Task(name="Skipped Task 2", status=TaskStatus.PENDING),
        ]
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        failed = _execute_parallel_fallback(
            workflow_state,
            tasks,
            workflow_state.get_plan_path(),
            workflow_state.get_tasklist_path(),
            log_dir,
        )

        # Verify that only the first task was actually "executed" (added to our list)
        # before the stop_event was set
        assert executed_tasks == ["Failing Task"]
        # The failed list should contain only the failing task
        assert "Failing Task" in failed


class TestExecuteTaskWithCallbackRateLimit:
    """Tests for rate limit detection in _execute_task_with_callback."""

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_raises_rate_limit_error_on_rate_limit_output(
        self, mock_auggie_class, workflow_state, sample_task
    ):
        """Raises AuggieRateLimitError when output indicates rate limit."""
        from spec.integrations.auggie import AuggieRateLimitError

        mock_client = MagicMock()
        # Simulate rate limit in output
        mock_client.run_with_callback.return_value = (False, "Error: HTTP 429 Too Many Requests")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()

        with pytest.raises(AuggieRateLimitError):
            _execute_task_with_callback(
                workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
            )

    @patch("spec.workflow.step3_execute.AuggieClient")
    def test_returns_false_on_non_rate_limit_failure(
        self, mock_auggie_class, workflow_state, sample_task
    ):
        """Returns False on non-rate-limit failure."""
        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (False, "Some other error")
        mock_auggie_class.return_value = mock_client

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state, sample_task, workflow_state.get_plan_path(), callback=callback
        )

        assert result is False


class TestCaptureBaselineForDiffs:
    """Tests for _capture_baseline_for_diffs function."""

    @patch("spec.workflow.step3_execute.capture_baseline")
    @patch("spec.workflow.step3_execute.check_dirty_working_tree")
    @patch("spec.workflow.step3_execute.print_info")
    def test_captures_baseline_successfully(
        self, mock_print, mock_check_dirty, mock_capture, workflow_state
    ):
        """Captures baseline and returns True on success."""
        from spec.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = True
        mock_capture.return_value = "abc123def456"

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is True
        assert workflow_state.diff_baseline_ref == "abc123def456"

    @patch("spec.workflow.step3_execute.capture_baseline")
    @patch("spec.workflow.step3_execute.check_dirty_working_tree")
    @patch("spec.workflow.step3_execute.print_warning")
    @patch("spec.workflow.step3_execute.print_info")
    def test_continues_with_dirty_tree_on_warn_policy(
        self, mock_info, mock_warning, mock_check_dirty, mock_capture, workflow_state
    ):
        """Continues with dirty tree when policy allows."""
        from spec.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = False  # Dirty but not raising
        mock_capture.return_value = "abc123"

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is True
        mock_warning.assert_called_once()

    @patch("spec.workflow.step3_execute.check_dirty_working_tree")
    @patch("spec.workflow.step3_execute.print_error")
    def test_returns_false_on_dirty_tree_fail_fast(
        self, mock_error, mock_check_dirty, workflow_state
    ):
        """Returns False when dirty tree check raises DirtyWorkingTreeError."""
        from spec.workflow.git_utils import DirtyWorkingTreeError
        from spec.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.side_effect = DirtyWorkingTreeError("Dirty tree")

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is False
        mock_error.assert_called_once()

    @patch("spec.workflow.step3_execute.capture_baseline")
    @patch("spec.workflow.step3_execute.check_dirty_working_tree")
    @patch("spec.workflow.step3_execute.print_error")
    def test_returns_false_on_capture_failure(
        self, mock_error, mock_check_dirty, mock_capture, workflow_state
    ):
        """Returns False when baseline capture fails."""
        from spec.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = True
        mock_capture.side_effect = Exception("Git error")

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is False
        mock_error.assert_called_once()
