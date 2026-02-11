"""Tests for ingot.workflow.step3_execute module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.providers import GenericTicket, Platform
from ingot.workflow.state import WorkflowState
from ingot.workflow.step3_execute import (
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
from ingot.workflow.tasks import Task, TaskCategory, TaskStatus


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return GenericTicket(
        id="TEST-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description",
        branch_summary="test-feature",
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


class TestGetLogBaseDir:
    def test_default_returns_spec_runs(self, monkeypatch):
        monkeypatch.delenv("INGOT_LOG_DIR", raising=False)
        result = _get_log_base_dir()
        assert result == Path(".ingot/runs")

    def test_respects_environment_variable(self, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", "/custom/log/dir")
        result = _get_log_base_dir()
        assert result == Path("/custom/log/dir")


class TestCreateRunLogDir:
    def test_creates_timestamped_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        result = _create_run_log_dir("TEST-123")

        assert result.exists()
        assert result.is_dir()
        assert "TEST-123" in str(result)

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "deep" / "nested" / "path"
        monkeypatch.setenv("INGOT_LOG_DIR", str(log_dir))

        result = _create_run_log_dir("TEST-456")

        assert result.exists()
        assert "TEST-456" in str(result)

    def test_returns_correct_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        result = _create_run_log_dir("PROJ-789")

        assert isinstance(result, Path)
        assert result.parent.name == "PROJ-789"


class TestCleanupOldRuns:
    def test_removes_directories_beyond_keep_count(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))
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
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))
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
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))

        # Should not raise any exception
        _cleanup_old_runs("NONEXISTENT-123", keep_count=2)

    def test_ignores_cleanup_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INGOT_LOG_DIR", str(tmp_path))
        ticket_dir = tmp_path / "TEST-123"
        ticket_dir.mkdir()

        # Create directories
        for i in range(3):
            (ticket_dir / f"20260101_00000{i}").mkdir()

        # Mock shutil.rmtree to raise an exception
        with patch("shutil.rmtree", side_effect=PermissionError("Access denied")):
            # Should not raise, just ignore the error
            _cleanup_old_runs("TEST-123", keep_count=1)


class TestBuildTaskPrompt:
    def test_includes_task_name(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan content")

        result = _build_task_prompt(sample_task, plan_path)

        assert "Implement feature" in result

    def test_includes_parallel_mode_no(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, is_parallel=False)

        assert "Parallel mode: NO" in result

    def test_includes_parallel_mode_yes(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, is_parallel=True)

        assert "Parallel mode: YES" in result

    def test_includes_plan_path_when_exists(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path)

        assert str(plan_path) in result
        assert "codebase-retrieval" in result

    def test_excludes_plan_path_when_not_exists(self, sample_task, tmp_path):
        plan_path = tmp_path / "nonexistent.md"

        result = _build_task_prompt(sample_task, plan_path)

        assert str(plan_path) not in result
        assert "codebase-retrieval" in result

    def test_does_not_include_full_plan_content(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("UNIQUE_PLAN_CONTENT_MARKER_12345")

        result = _build_task_prompt(sample_task, plan_path)

        # The actual content should NOT be in the prompt
        assert "UNIQUE_PLAN_CONTENT_MARKER_12345" not in result
        # But the path should be
        assert str(plan_path) in result

    def test_includes_no_commit_constraint(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"

        result = _build_task_prompt(sample_task, plan_path)

        assert "Do NOT commit" in result

    def test_includes_target_files_when_present(self, tmp_path):
        task = Task(name="Fix module", target_files=["src/foo.py", "src/bar.py"])
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(task, plan_path)

        assert "Target files for this task:" in result
        assert "- src/foo.py" in result
        assert "- src/bar.py" in result
        assert "Focus your changes on these files" in result

    def test_excludes_target_files_when_empty(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path)

        assert "Target files for this task:" not in result

    def test_includes_user_context_when_provided(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(
            sample_task, plan_path, user_context="Use the new API v2 endpoints"
        )

        assert "Additional Context:" in result
        assert "Use the new API v2 endpoints" in result

    def test_excludes_user_context_when_empty(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, user_context="")

        assert "Additional Context:" not in result

    def test_includes_both_target_files_and_user_context(self, tmp_path):
        task = Task(name="Update handler", target_files=["handler.py"])
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(task, plan_path, user_context="Follow REST conventions")

        assert "Target files for this task:" in result
        assert "Additional Context:" in result
        # Target files should appear before user context
        target_pos = result.index("Target files for this task:")
        context_pos = result.index("Additional Context:")
        assert target_pos < context_pos

    def test_excludes_user_context_when_whitespace_only(self, sample_task, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(sample_task, plan_path, user_context="   \n  ")

        assert "Additional Context:" not in result

    def test_no_commit_constraint_last_with_all_sections(self, tmp_path):
        task = Task(name="Update handler", target_files=["handler.py"])
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        result = _build_task_prompt(task, plan_path, user_context="Extra info")

        assert "Do NOT commit" in result
        # No-commit constraint should be after user context
        context_pos = result.index("Extra info")
        commit_pos = result.index("Do NOT commit")
        assert commit_pos > context_pos


class TestExecuteTask:
    def test_returns_true_on_success(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")

        result = _execute_task(
            workflow_state, sample_task, workflow_state.get_plan_path(), mock_backend
        )

        assert result is True

    def test_returns_false_on_failure(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (False, "Error")

        result = _execute_task(
            workflow_state, sample_task, workflow_state.get_plan_path(), mock_backend
        )

        assert result is False

    def test_returns_false_on_exception(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.side_effect = RuntimeError("Connection failed")

        result = _execute_task(
            workflow_state, sample_task, workflow_state.get_plan_path(), mock_backend
        )

        assert result is False

    def test_uses_spec_implementer_agent(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")

        _execute_task(workflow_state, sample_task, workflow_state.get_plan_path(), mock_backend)

        # Verify subagent from state.subagent_names is passed to run_with_callback
        call_kwargs = mock_backend.run_with_callback.call_args[1]
        assert call_kwargs["subagent"] == workflow_state.subagent_names["implementer"]
        assert call_kwargs["dont_save_session"] is True

    def test_propagates_user_context_to_prompt(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")
        workflow_state.user_context = "Use the legacy API adapter"

        _execute_task(workflow_state, sample_task, workflow_state.get_plan_path(), mock_backend)

        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "Additional Context:" in prompt
        assert "Use the legacy API adapter" in prompt


class TestExecuteTaskWithCallback:
    def test_returns_true_on_success(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert result is True

    def test_returns_false_on_failure(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (False, "Error")

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert result is False

    def test_callback_receives_output(self, mock_backend, workflow_state, sample_task):
        # Simulate callback being invoked during run_with_callback
        def call_callback(prompt, *, subagent, output_callback, dont_save_session):
            output_callback("Line 1")
            output_callback("Line 2")
            return (True, "Done")

        mock_backend.run_with_callback.side_effect = call_callback

        callback = MagicMock()
        _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert callback.call_count == 2
        callback.assert_any_call("Line 1")
        callback.assert_any_call("Line 2")

    def test_callback_receives_error_on_exception(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.side_effect = RuntimeError("Connection failed")

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert result is False
        callback.assert_called()
        # Check that the error message was passed to callback
        error_call = callback.call_args[0][0]
        assert "ERROR" in error_call
        assert "Connection failed" in error_call

    def test_uses_spec_implementer_agent(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")

        callback = MagicMock()
        _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        # Verify subagent from state.subagent_names is passed to run_with_callback
        call_kwargs = mock_backend.run_with_callback.call_args[1]
        assert call_kwargs["subagent"] == workflow_state.subagent_names["implementer"]
        assert call_kwargs["dont_save_session"] is True

    def test_propagates_user_context_to_prompt(self, mock_backend, workflow_state, sample_task):
        mock_backend.run_with_callback.return_value = (True, "Output")
        workflow_state.user_context = "Prefer functional style"

        callback = MagicMock()
        _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "Additional Context:" in prompt
        assert "Prefer functional style" in prompt


class TestShowSummary:
    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.get_current_branch")
    def test_displays_ticket_id(self, mock_branch, mock_console, workflow_state):
        mock_branch.return_value = "main"

        _show_summary(workflow_state)

        # Check that console.print was called with ticket ID
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("TEST-123" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.get_current_branch")
    def test_displays_branch_name(self, mock_branch, mock_console, workflow_state):
        workflow_state.branch_name = "feature/test-branch"
        mock_branch.return_value = "main"

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("feature/test-branch" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.get_current_branch")
    def test_displays_completed_task_count(self, mock_branch, mock_console, workflow_state):
        mock_branch.return_value = "main"
        workflow_state.completed_tasks = ["Task 1", "Task 2"]

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("2" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.get_current_branch")
    def test_displays_checkpoint_count(self, mock_branch, mock_console, workflow_state):
        mock_branch.return_value = "main"
        workflow_state.checkpoint_commits = ["abc123", "def456"]

        _show_summary(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Checkpoints" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.get_current_branch")
    def test_displays_failed_tasks_when_present(self, mock_branch, mock_console, workflow_state):
        mock_branch.return_value = "main"

        _show_summary(workflow_state, failed_tasks=["Failed Task 1", "Failed Task 2"])

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Failed Task 1" in c for c in calls)
        assert any("issues" in c.lower() for c in calls)


class TestRunPostImplementationTests:
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    def test_prompts_user_to_run_tests(self, mock_confirm, mock_backend, workflow_state):
        mock_confirm.return_value = True
        mock_backend.run_with_callback.return_value = (True, "Tests passed")

        _run_post_implementation_tests(workflow_state, mock_backend)

        mock_confirm.assert_called_once()
        assert "test" in mock_confirm.call_args[0][0].lower()

    @patch("ingot.workflow.step3_execute.prompt_confirm")
    def test_skips_when_user_declines(self, mock_confirm, mock_backend, workflow_state):
        mock_confirm.return_value = False

        _run_post_implementation_tests(workflow_state, mock_backend)

        mock_backend.run_with_callback.assert_not_called()

    @patch("ingot.ui.plan_tui.StreamingOperationUI")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    def test_runs_auggie_with_test_prompt(
        self, mock_confirm, mock_ui_class, mock_backend, workflow_state
    ):
        mock_confirm.return_value = True
        mock_backend.run_with_callback.return_value = (True, "Tests passed")

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        _run_post_implementation_tests(workflow_state, mock_backend)

        mock_backend.run_with_callback.assert_called_once()
        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "test" in prompt.lower()

    @patch("ingot.ui.plan_tui.StreamingOperationUI")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    def test_handles_auggie_exceptions(
        self, mock_confirm, mock_ui_class, mock_backend, workflow_state
    ):
        mock_confirm.return_value = True
        mock_backend.run_with_callback.side_effect = RuntimeError("Connection error")

        # Setup mock UI
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.check_quit_requested.return_value = False

        # Should not raise exception
        _run_post_implementation_tests(workflow_state, mock_backend)


class TestOfferCommitInstructions:
    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.is_dirty")
    def test_does_nothing_when_no_dirty_files(self, mock_is_dirty, mock_console, workflow_state):
        mock_is_dirty.return_value = False

        _offer_commit_instructions(workflow_state)

        # Console should not print commit instructions
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert not any("git commit" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute.is_dirty")
    def test_prompts_user_for_instructions(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        mock_is_dirty.return_value = True
        mock_confirm.return_value = False

        _offer_commit_instructions(workflow_state)

        mock_confirm.assert_called_once()

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute.is_dirty")
    def test_does_nothing_when_user_declines(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        mock_is_dirty.return_value = True
        mock_confirm.return_value = False

        _offer_commit_instructions(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert not any("git commit" in c for c in calls)

    @patch("ingot.workflow.step3_execute.console")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute.is_dirty")
    def test_prints_commit_commands_when_accepted(
        self, mock_is_dirty, mock_confirm, mock_console, workflow_state
    ):
        mock_is_dirty.return_value = True
        mock_confirm.return_value = True
        workflow_state.completed_tasks = ["Task 1"]

        _offer_commit_instructions(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("git" in c for c in calls)


class TestExecuteFallback:
    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_executes_tasks_sequentially(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
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
            backend=mock_backend,
        )

        assert mock_execute.call_count == 2

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_marks_tasks_complete_on_success(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
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
            backend=mock_backend,
        )

        mock_mark.assert_called_once()
        assert "Task 1" in workflow_state.completed_tasks

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_tracks_failed_tasks(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
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
            backend=mock_backend,
        )

        assert failed == ["Task 2"]

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_respects_fail_fast_option(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
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
            backend=mock_backend,
        )

        # Should stop after Task 2 fails
        assert mock_execute.call_count == 2
        assert failed == ["Task 2"]

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_returns_list_of_failed_task_names(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
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
            backend=mock_backend,
        )

        assert failed == ["Failed 1", "Failed 2"]


class TestExecuteWithTui:
    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_initializes_tui_correctly(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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
            backend=mock_backend,
        )

        mock_tui_class.assert_called_once_with(ticket_id="TEST-123", verbose_mode=False)
        mock_tui.initialize_records.assert_called_once_with(["Task 1"])

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_marks_tasks_complete_on_success(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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
            backend=mock_backend,
        )

        mock_mark.assert_called_once()
        assert "Task 1" in workflow_state.completed_tasks

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_tracks_failed_tasks(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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
            backend=mock_backend,
        )

        assert failed == ["Task 2"]

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_respects_fail_fast_option(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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
            backend=mock_backend,
        )

        # Should stop after Task 2 fails
        assert mock_execute.call_count == 2
        mock_tui.mark_remaining_skipped.assert_called()


class TestStep3Execute:
    def test_returns_false_when_tasklist_not_found(self, ticket, tmp_path):
        state = WorkflowState(ticket=ticket)
        # Don't create tasklist file
        state.tasklist_file = tmp_path / "nonexistent.md"

        result = step_3_execute(state, backend=MagicMock(), use_tui=False)

        assert result is False

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
    def test_returns_true_when_all_tasks_already_complete(
        self,
        mock_baseline,
        mock_summary,
        mock_tests,
        mock_commit,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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

        result = step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        assert result is True

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_with_tui")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = True
        mock_execute_tui.return_value = []

        step_3_execute(workflow_state, backend=mock_backend, use_tui=True)

        mock_execute_tui.assert_called_once()

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute_fallback.return_value = []

        step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        mock_execute_fallback.assert_called_once()

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = ["Failed Task"]
        mock_confirm.return_value = True

        step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        mock_confirm.assert_called()

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []  # No failed tasks

        result = step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        assert result is True

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
    def test_returns_false_when_user_declines_after_failures(
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = ["Failed Task"]
        mock_confirm.return_value = False  # User declines

        result = step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        assert result is False

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        mock_summary.assert_called_once()

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        mock_tests.assert_called_once()

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
        mock_baseline.return_value = True
        mock_log_dir.return_value = tmp_path / "logs"
        mock_should_tui.return_value = False
        mock_execute.return_value = []

        step_3_execute(workflow_state, backend=mock_backend, use_tui=False)

        mock_commit.assert_called_once()

    @patch("ingot.workflow.step3_execute.prompt_confirm")
    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    @patch("ingot.ui.tui.TaskRunnerUI")
    def test_stops_execution_when_quit_requested(
        self,
        mock_tui_class,
        mock_execute,
        mock_mark,
        mock_confirm,
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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
            backend=mock_backend,
        )

        # Assertions
        # Should verify that we stopped TUI to show prompt
        mock_tui.stop.assert_called()
        # Should verify prompt was shown
        mock_confirm.assert_called_with("Quit task execution?", default=False)
        # Should verify specific cleanup method for skipping remaining tasks was called
        mock_tui.mark_remaining_skipped.assert_called()


class TestTwoPhaseExecution:
    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_parallel_fallback")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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

        step_3_execute(workflow_state, backend=mock_backend)

        # Verify fundamental fallback was called first
        assert mock_execute_fallback.called
        # Verify parallel fallback was also called
        assert mock_execute_parallel.called
        # Check call order
        assert mock_execute_fallback.call_count >= 1
        assert mock_execute_parallel.call_count == 1

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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

        step_3_execute(workflow_state, backend=mock_backend)

        # Should use _execute_fallback (sequential), not _execute_parallel_fallback
        assert mock_execute_fallback.called
        # Check that tasks passed to fallback are fundamental tasks
        call_args = mock_execute_fallback.call_args
        tasks = call_args[0][1]  # Second positional arg is tasks
        assert len(tasks) == 2

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_parallel_fallback")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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

        step_3_execute(workflow_state, backend=mock_backend)

        # Should use _execute_parallel_fallback for independent tasks
        assert mock_execute_parallel.called

    @patch("ingot.workflow.step3_execute._offer_commit_instructions")
    @patch("ingot.workflow.step3_execute._run_post_implementation_tests")
    @patch("ingot.workflow.step3_execute._show_summary")
    @patch("ingot.workflow.step3_execute._execute_parallel_fallback")
    @patch("ingot.workflow.step3_execute._execute_fallback")
    @patch("ingot.ui.tui._should_use_tui")
    @patch("ingot.workflow.step3_execute._cleanup_old_runs")
    @patch("ingot.workflow.step3_execute._create_run_log_dir")
    @patch("ingot.workflow.step3_execute._capture_baseline_for_diffs")
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
        mock_backend,
        workflow_state,
        tmp_path,
    ):
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

        step_3_execute(workflow_state, backend=mock_backend)

        # Should NOT use parallel execution
        assert not mock_execute_parallel.called
        # Should use sequential fallback instead
        assert mock_execute_fallback.called


class TestParallelExecution:
    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_uses_thread_pool_executor(
        self, mock_execute_retry, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # All tasks should succeed
        assert failed == []
        # Both tasks should be executed
        assert mock_execute_retry.call_count == 2

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_respects_max_parallel_tasks(
        self, mock_execute_retry, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # All tasks should complete
        assert failed == []
        assert mock_execute_retry.call_count == 5

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_collects_failed_tasks(
        self, mock_execute_retry, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # Should have one failed task
        assert len(failed) == 1
        assert "Failed Task" in failed

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_marks_successful_tasks_complete(
        self, mock_execute_retry, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # Should mark task complete
        mock_mark.assert_called_once()


class TestTaskRetry:
    @patch("ingot.workflow.step3_execute._execute_task")
    def test_skips_retry_when_disabled(self, mock_execute, mock_backend, workflow_state, tmp_path):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry

        mock_execute.return_value = True
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Test Task")
        result = _execute_task_with_retry(
            workflow_state, task, workflow_state.get_plan_path(), backend=mock_backend
        )

        assert result is True
        mock_execute.assert_called_once()

    @patch("ingot.workflow.step3_execute._execute_task_with_callback")
    def test_uses_callback_when_provided(
        self, mock_execute_callback, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry

        mock_execute_callback.return_value = True
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Test Task")
        callback = MagicMock()
        result = _execute_task_with_retry(
            workflow_state,
            task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert result is True
        mock_execute_callback.assert_called_once()

    @patch("ingot.workflow.step3_execute._execute_task")
    def test_returns_false_on_failure(self, mock_execute, mock_backend, workflow_state, tmp_path):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry

        mock_execute.return_value = False
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="Failing Task")
        result = _execute_task_with_retry(
            workflow_state, task, workflow_state.get_plan_path(), backend=mock_backend
        )

        assert result is False

    @patch("ingot.workflow.step3_execute._execute_task")
    def test_retries_on_rate_limit_error(
        self, mock_execute, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry

        # First call raises rate limit error (HTTP 429), second succeeds
        mock_execute.side_effect = [Exception("HTTP Error 429: Too Many Requests"), True]
        workflow_state.rate_limit_config = RateLimitConfig(
            max_retries=3, base_delay_seconds=0.01, max_delay_seconds=0.1
        )

        task = Task(name="Retry Task")
        result = _execute_task_with_retry(
            workflow_state, task, workflow_state.get_plan_path(), backend=mock_backend
        )

        assert result is True
        assert mock_execute.call_count == 2

    @patch("ingot.workflow.step3_execute._execute_task")
    def test_rate_limit_error_returns_false_when_retries_disabled(
        self, mock_execute, mock_backend, workflow_state, tmp_path
    ):
        from ingot.integrations.backends.errors import BackendRateLimitError
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry

        mock_execute.side_effect = BackendRateLimitError(
            "Rate limit detected", output="429 error", backend_name="Test"
        )
        workflow_state.rate_limit_config = RateLimitConfig(max_retries=0)

        task = Task(name="No-Retry Task")
        result = _execute_task_with_retry(
            workflow_state, task, workflow_state.get_plan_path(), backend=mock_backend
        )

        assert result is False


class TestParallelFailFast:
    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_fail_fast_stops_pending_tasks(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # Task 1 should fail, others should be skipped
        assert "Task 1" in failed

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_no_fail_fast_continues_after_failure(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        from ingot.workflow.step3_execute import _execute_parallel_fallback

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
            backend=mock_backend,
        )

        # All tasks should execute
        assert mock_execute.call_count == 3
        assert failed == ["Task 1"]

    @patch("ingot.workflow.step3_execute.mark_task_complete")
    @patch("ingot.workflow.step3_execute._execute_task_with_retry")
    def test_stop_flag_prevents_new_task_execution(
        self, mock_execute, mock_mark, mock_backend, workflow_state, tmp_path
    ):
        import threading

        from ingot.workflow.step3_execute import _execute_parallel_fallback

        # Shared event to simulate stop_flag behavior
        stop_event = threading.Event()
        executed_tasks = []

        def mock_execute_side_effect(state, task, plan_path, **kwargs):
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
            backend=mock_backend,
        )

        # Verify that only the first task was actually "executed" (added to our list)
        # before the stop_event was set
        assert executed_tasks == ["Failing Task"]
        # The failed list should contain only the failing task
        assert "Failing Task" in failed


class TestExecuteTaskWithCallbackRateLimit:
    def test_raises_rate_limit_error_on_rate_limit_output(
        self, mock_backend, workflow_state, sample_task
    ):
        from ingot.integrations.backends.errors import BackendRateLimitError

        # Simulate rate limit in output
        mock_backend.run_with_callback.return_value = (False, "Error: HTTP 429 Too Many Requests")
        mock_backend.detect_rate_limit.return_value = True

        callback = MagicMock()

        with pytest.raises(BackendRateLimitError):
            _execute_task_with_callback(
                workflow_state,
                sample_task,
                workflow_state.get_plan_path(),
                backend=mock_backend,
                callback=callback,
            )

    def test_returns_false_on_non_rate_limit_failure(
        self, mock_backend, workflow_state, sample_task
    ):
        mock_backend.run_with_callback.return_value = (False, "Some other error")
        mock_backend.detect_rate_limit.return_value = False

        callback = MagicMock()
        result = _execute_task_with_callback(
            workflow_state,
            sample_task,
            workflow_state.get_plan_path(),
            backend=mock_backend,
            callback=callback,
        )

        assert result is False


class TestRateLimitFlowWithFakeBackend:
    """End-to-end rate limit retry flow tests using FakeBackend."""

    def test_full_rate_limit_retry_flow(self, workflow_state):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry
        from tests.fakes.fake_backend import make_rate_limited_backend

        backend = make_rate_limited_backend(fail_count=2)
        workflow_state.rate_limit_config = RateLimitConfig(
            max_retries=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.1,
            jitter_factor=0.0,
        )

        task = Task(name="Retry Task")
        callback = MagicMock()
        result = _execute_task_with_retry(
            workflow_state,
            task,
            workflow_state.get_plan_path(),
            backend=backend,
            callback=callback,
        )

        assert result is True
        assert backend.call_count == 3

    def test_rate_limit_exhaustion_with_fake_backend(self, workflow_state):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry
        from tests.fakes.fake_backend import FakeBackend

        # 5 rate-limit failures, only 2 retries allowed
        responses = [(False, "Error 429: rate limit hit")] * 5
        backend = FakeBackend(responses)
        workflow_state.rate_limit_config = RateLimitConfig(
            max_retries=2,
            base_delay_seconds=0.01,
            max_delay_seconds=0.1,
            jitter_factor=0.0,
        )

        task = Task(name="Exhaustion Task")
        callback = MagicMock()
        result = _execute_task_with_retry(
            workflow_state,
            task,
            workflow_state.get_plan_path(),
            backend=backend,
            callback=callback,
        )

        assert result is False

    def test_non_callback_path_retries_on_rate_limit(self, workflow_state):
        from ingot.workflow.state import RateLimitConfig
        from ingot.workflow.step3_execute import _execute_task_with_retry
        from tests.fakes.fake_backend import make_rate_limited_backend

        backend = make_rate_limited_backend(fail_count=1)
        workflow_state.rate_limit_config = RateLimitConfig(
            max_retries=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.1,
            jitter_factor=0.0,
        )

        task = Task(name="No-Callback Retry Task")
        result = _execute_task_with_retry(
            workflow_state,
            task,
            workflow_state.get_plan_path(),
            backend=backend,
            callback=None,
        )

        assert result is True
        assert backend.call_count == 2


class TestFakeBackendConfiguration:
    def test_check_installed_default_true(self):
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend([(True, "ok")])
        installed, msg = backend.check_installed()
        assert installed is True

    def test_check_installed_false(self):
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend([(True, "ok")], installed=False)
        installed, msg = backend.check_installed()
        assert installed is False
        assert "not installed" in msg.lower()

    def test_custom_platform(self):
        from ingot.config.fetch_config import AgentPlatform
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend([(True, "ok")], platform=AgentPlatform.CLAUDE)
        assert backend.platform == AgentPlatform.CLAUDE


class TestCaptureBaselineForDiffs:
    @patch("ingot.workflow.step3_execute.capture_baseline")
    @patch("ingot.workflow.step3_execute.check_dirty_working_tree")
    @patch("ingot.workflow.step3_execute.print_info")
    def test_captures_baseline_successfully(
        self, mock_print, mock_check_dirty, mock_capture, workflow_state
    ):
        from ingot.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = True
        mock_capture.return_value = "abc123def456"

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is True
        assert workflow_state.diff_baseline_ref == "abc123def456"

    @patch("ingot.workflow.step3_execute.capture_baseline")
    @patch("ingot.workflow.step3_execute.check_dirty_working_tree")
    @patch("ingot.workflow.step3_execute.print_warning")
    @patch("ingot.workflow.step3_execute.print_info")
    def test_continues_with_dirty_tree_on_warn_policy(
        self, mock_info, mock_warning, mock_check_dirty, mock_capture, workflow_state
    ):
        from ingot.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = False  # Dirty but not raising
        mock_capture.return_value = "abc123"

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is True
        mock_warning.assert_called_once()

    @patch("ingot.workflow.step3_execute.check_dirty_working_tree")
    @patch("ingot.workflow.step3_execute.print_error")
    def test_returns_false_on_dirty_tree_fail_fast(
        self, mock_error, mock_check_dirty, workflow_state
    ):
        from ingot.workflow.git_utils import DirtyWorkingTreeError
        from ingot.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.side_effect = DirtyWorkingTreeError("Dirty tree")

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is False
        mock_error.assert_called_once()

    @patch("ingot.workflow.step3_execute.capture_baseline")
    @patch("ingot.workflow.step3_execute.check_dirty_working_tree")
    @patch("ingot.workflow.step3_execute.print_error")
    def test_returns_false_on_capture_failure(
        self, mock_error, mock_check_dirty, mock_capture, workflow_state
    ):
        from ingot.workflow.step3_execute import _capture_baseline_for_diffs

        mock_check_dirty.return_value = True
        mock_capture.side_effect = Exception("Git error")

        result = _capture_baseline_for_diffs(workflow_state)

        assert result is False
        mock_error.assert_called_once()
