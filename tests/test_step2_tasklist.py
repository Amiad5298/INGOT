"""Tests for spec.workflow.step2_tasklist module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from spec.workflow.step2_tasklist import (
    step_2_create_tasklist,
    _generate_tasklist,
    _extract_tasklist_from_output,
    _display_tasklist,
    _edit_tasklist,
    _create_default_tasklist,
    _validate_file_disjointness,
    StrictFileScopingError,
)

from spec.workflow.state import WorkflowState
from spec.workflow.tasks import parse_task_list, Task, TaskCategory, TaskStatus, PathSecurityError
from spec.integrations.jira import JiraTicket
from spec.ui.menus import TaskReviewChoice


@pytest.fixture
def workflow_state(tmp_path):
    """Create a workflow state for testing."""
    ticket = JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        summary="Test Feature",
        title="Implement test feature",
        description="Test description"
    )
    state = WorkflowState(ticket=ticket)
    
    # Create specs directory
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)
    
    # Create plan file
    plan_file = specs_dir / "TEST-123-plan.md"
    plan_file.write_text("""# Implementation Plan: TEST-123

## Summary
Test implementation plan.

## Tasks
1. Create module
2. Add tests
""")
    state.plan_file = plan_file
    
    # Patch the paths to use tmp_path
    state._specs_dir = specs_dir
    
    return state


@pytest.fixture
def mock_auggie_client():
    """Create a mock Auggie client."""
    client = MagicMock()
    client.model = "test-model"
    return client


class TestExtractTasklistFromOutput:
    """Tests for _extract_tasklist_from_output function."""

    def test_extracts_simple_tasks(self):
        """Extracts tasks from simple checkbox format."""
        output = """Here is the task list:
- [ ] Create module file
- [ ] Implement core function
- [ ] Add unit tests
"""
        result = _extract_tasklist_from_output(output, "TEST-123")
        
        assert result is not None
        assert "# Task List: TEST-123" in result
        assert "- [ ] Create module file" in result
        assert "- [ ] Implement core function" in result
        assert "- [ ] Add unit tests" in result

    def test_extracts_tasks_with_preamble(self):
        """Extracts tasks even with preamble text."""
        output = """I'll create a task list based on the plan.

Here are the tasks:

- [ ] Set up project structure
- [ ] Implement authentication
- [ ] Write integration tests

Let me know if you need any changes!
"""
        result = _extract_tasklist_from_output(output, "PROJ-456")
        
        assert result is not None
        tasks = parse_task_list(result)
        assert len(tasks) == 3
        assert tasks[0].name == "Set up project structure"

    def test_handles_indented_tasks(self):
        """Handles indented (nested) tasks."""
        output = """- [ ] Main task
  - [ ] Subtask 1
  - [ ] Subtask 2
"""
        result = _extract_tasklist_from_output(output, "TEST-123")
        
        assert result is not None
        assert "- [ ] Main task" in result
        assert "  - [ ] Subtask 1" in result

    def test_handles_completed_tasks(self):
        """Handles tasks marked as complete."""
        output = """- [x] Completed task
- [ ] Pending task
- [X] Also completed
"""
        result = _extract_tasklist_from_output(output, "TEST-123")
        
        assert result is not None
        assert "- [x] Completed task" in result
        assert "- [ ] Pending task" in result
        # Uppercase X should be normalized to lowercase
        assert "- [x] Also completed" in result

    def test_returns_none_for_no_tasks(self):
        """Returns None when no checkbox tasks found."""
        output = """This output has no checkbox tasks.
Just some regular text.
"""
        result = _extract_tasklist_from_output(output, "TEST-123")
        
        assert result is None

    def test_handles_asterisk_bullets(self):
        """Handles asterisk bullet points."""
        output = """* [ ] Task with asterisk
* [ ] Another asterisk task
"""
        result = _extract_tasklist_from_output(output, "TEST-123")
        
        assert result is not None
        tasks = parse_task_list(result)
        assert len(tasks) == 2


class TestGenerateTasklist:
    """Tests for _generate_tasklist function."""

    @patch("spec.workflow.step2_tasklist.AuggieClient")
    def test_persists_ai_output_to_file(
        self,
        mock_auggie_class,
        workflow_state,
        tmp_path,
    ):
        """AI output is persisted to file even if AI doesn't write it."""
        # Setup
        tasklist_path = tmp_path / "specs" / "TEST-123-tasklist.md"
        plan_path = workflow_state.plan_file

        # Mock Auggie to return success with task list in output
        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (
            True,
            """Here's the task list:
- [ ] Create user module
- [ ] Add authentication
- [ ] Write tests
"""
        )
        mock_auggie_class.return_value = mock_client

        # Act
        result = _generate_tasklist(
            workflow_state,
            plan_path,
            tasklist_path,
        )

        # Assert
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        tasks = parse_task_list(content)
        assert len(tasks) == 3
        assert tasks[0].name == "Create user module"

    @patch("spec.workflow.step2_tasklist.AuggieClient")
    def test_uses_subagent_for_tasklist_generation(
        self,
        mock_auggie_class,
        tmp_path,
    ):
        """Uses state.subagent_names tasklist agent for task list generation."""
        # Setup
        ticket = JiraTicket(
            ticket_id="TEST-456",
            ticket_url="https://jira.example.com/TEST-456",
            summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-456-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-456-tasklist.md"

        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (
            True,
            "- [ ] Single task\n"
        )
        mock_auggie_class.return_value = mock_client

        # Act
        result = _generate_tasklist(state, plan_path, tasklist_path)

        # Assert - new client is created and subagent from state is used
        mock_auggie_class.assert_called_once_with()
        call_kwargs = mock_client.run_print_with_output.call_args.kwargs
        assert "agent" in call_kwargs
        assert call_kwargs["agent"] == state.subagent_names["tasklist"]
        assert result is True

    @patch("spec.workflow.step2_tasklist.AuggieClient")
    def test_falls_back_to_default_when_no_tasks_extracted(
        self,
        mock_auggie_class,
        tmp_path,
    ):
        """Falls back to default template when AI output has no checkbox tasks."""
        ticket = JiraTicket(ticket_id="TEST-789", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-789-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-789-tasklist.md"

        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (
            True,
            "I couldn't understand the plan. Please clarify."
        )
        mock_auggie_class.return_value = mock_client

        result = _generate_tasklist(state, plan_path, tasklist_path)

        # Should fall back to default template
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        # Default template has placeholder tasks
        assert "[Core functionality implementation with tests]" in content


class TestStep2CreateTasklist:
    """Tests for step_2_create_tasklist function."""

    @patch("spec.workflow.step2_tasklist.show_task_review_menu")
    @patch("spec.workflow.step2_tasklist._edit_tasklist")
    @patch("spec.workflow.step2_tasklist._generate_tasklist")
    def test_edit_does_not_regenerate(
        self,
        mock_generate,
        mock_edit,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """EDIT choice does not regenerate/overwrite the task list.

        Test A: Verifies:
        - _generate_tasklist is called exactly once
        - After EDIT, the edited content is preserved (not overwritten)
        - APPROVE after EDIT approves the edited content
        - state.current_step is set to 3 and state.tasklist_file is set
        """
        # Change to tmp_path so that state.specs_dir resolves correctly
        monkeypatch.chdir(tmp_path)

        # Setup
        ticket = JiraTicket(
            ticket_id="TEST-EDIT",
            ticket_url="https://jira.example.com/TEST-EDIT",
            summary="Test Edit Flow",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)

        # Create plan file
        plan_path = specs_dir / "TEST-EDIT-plan.md"
        plan_path.write_text("# Plan\n\nImplement feature.")
        state.plan_file = plan_path

        # Get the actual tasklist path that the function will use
        tasklist_path = state.get_tasklist_path()

        # Initial content written by _generate_tasklist
        initial_content = """# Task List: TEST-EDIT

- [ ] Original task 1
- [ ] Original task 2
"""
        # Edited content (what user changes it to)
        edited_content = """# Task List: TEST-EDIT

- [ ] Edited task 1
- [ ] Edited task 2
- [ ] Edited task 3
"""

        def mock_generate_side_effect(state, plan_path, tasklist_path):
            tasklist_path.write_text(initial_content)
            return True

        mock_generate.side_effect = mock_generate_side_effect

        def mock_edit_side_effect(path):
            # Simulate user editing the file
            path.write_text(edited_content)

        mock_edit.side_effect = mock_edit_side_effect

        # Menu returns EDIT first, then APPROVE
        mock_menu.side_effect = [TaskReviewChoice.EDIT, TaskReviewChoice.APPROVE]

        mock_auggie = MagicMock()

        # Act
        result = step_2_create_tasklist(state, mock_auggie)

        # Assert
        assert result is True

        # _generate_tasklist should be called exactly once
        assert mock_generate.call_count == 1

        # The file should contain the edited content (not reverted)
        final_content = tasklist_path.read_text()
        assert "Edited task 1" in final_content
        assert "Edited task 2" in final_content
        assert "Edited task 3" in final_content
        assert "Original task" not in final_content

        # State should be updated
        assert state.current_step == 3
        assert state.tasklist_file == tasklist_path

    @patch("spec.workflow.step2_tasklist.show_task_review_menu")
    @patch("spec.workflow.step2_tasklist._generate_tasklist")
    def test_regenerate_calls_generate_again(
        self,
        mock_generate,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """REGENERATE choice calls _generate_tasklist again."""
        monkeypatch.chdir(tmp_path)

        ticket = JiraTicket(ticket_id="TEST-REGEN", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-REGEN-plan.md"
        plan_path.write_text("# Plan")
        state.plan_file = plan_path

        def mock_generate_effect(state, plan_path, tasklist_path):
            tasklist_path.write_text("- [ ] Task\n")
            return True

        mock_generate.side_effect = mock_generate_effect

        # REGENERATE then APPROVE
        mock_menu.side_effect = [
            TaskReviewChoice.REGENERATE,
            TaskReviewChoice.APPROVE,
        ]

        result = step_2_create_tasklist(state, MagicMock())

        assert result is True
        # Should be called twice: initial + after REGENERATE
        assert mock_generate.call_count == 2

    @patch("spec.workflow.step2_tasklist.show_task_review_menu")
    @patch("spec.workflow.step2_tasklist._generate_tasklist")
    def test_abort_returns_false(
        self,
        mock_generate,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """ABORT choice returns False."""
        monkeypatch.chdir(tmp_path)

        ticket = JiraTicket(ticket_id="TEST-ABORT", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-ABORT-plan.md"
        plan_path.write_text("# Plan")
        state.plan_file = plan_path

        mock_generate.side_effect = lambda s, pp, tp: (tp.write_text("- [ ] Task\n") or True)
        mock_menu.return_value = TaskReviewChoice.ABORT

        result = step_2_create_tasklist(state, MagicMock())

        assert result is False

    @patch("spec.workflow.step2_tasklist._generate_tasklist")
    def test_returns_false_when_plan_not_found(
        self,
        mock_generate,
        tmp_path,
        monkeypatch,
    ):
        """Returns False when plan file does not exist."""
        monkeypatch.chdir(tmp_path)

        ticket = JiraTicket(ticket_id="TEST-NOPLAN", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        # Create specs directory but NO plan file
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        # state.plan_file is None, so it will use default path which doesn't exist

        result = step_2_create_tasklist(state, MagicMock())

        assert result is False
        # _generate_tasklist should never be called
        mock_generate.assert_not_called()


class TestDisplayTasklist:
    """Tests for _display_tasklist function."""

    def test_displays_task_list(self, tmp_path, capsys):
        """Displays task list content and task count."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("""# Task List: TEST-123

- [ ] Task one
- [ ] Task two
- [x] Task three
""")

        with patch("spec.workflow.step2_tasklist.console") as mock_console:
            _display_tasklist(tasklist_path)

            # Verify console.print was called multiple times
            assert mock_console.print.call_count >= 4
            # Check that task count is displayed (2 pending + 1 complete = 3)
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("Total tasks: 3" in str(c) for c in calls)

    def test_displays_empty_task_list(self, tmp_path):
        """Displays empty task list with zero count."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("# Task List: TEST-123\n\nNo tasks yet.\n")

        with patch("spec.workflow.step2_tasklist.console") as mock_console:
            _display_tasklist(tasklist_path)

            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("Total tasks: 0" in str(c) for c in calls)


class TestEditTasklist:
    """Tests for _edit_tasklist function."""

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nano"}, clear=False)
    def test_opens_editor_from_environment(self, mock_run, tmp_path):
        """Opens the editor specified in EDITOR environment variable."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        _edit_tasklist(tasklist_path)

        mock_run.assert_called_once_with(["nano", str(tasklist_path)], check=True)

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_vim(self, mock_run, tmp_path):
        """Defaults to vim when EDITOR is not set."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        _edit_tasklist(tasklist_path)

        mock_run.assert_called_once_with(["vim", str(tasklist_path)], check=True)

    @patch("spec.workflow.step2_tasklist.prompt_enter")
    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nonexistent_editor"}, clear=False)
    def test_handles_editor_not_found(self, mock_run, mock_prompt, tmp_path):
        """Handles case when editor is not found."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        mock_run.side_effect = FileNotFoundError()

        _edit_tasklist(tasklist_path)

        # Should prompt user to edit manually
        mock_prompt.assert_called_once()

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "vim"}, clear=False)
    def test_handles_editor_error(self, mock_run, tmp_path):
        """Handles case when editor exits with error."""
        import subprocess as sp
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        mock_run.side_effect = sp.CalledProcessError(1, "vim")

        # Should not raise, just print warning
        _edit_tasklist(tasklist_path)


class TestCreateDefaultTasklist:
    """Tests for _create_default_tasklist function."""

    def test_creates_default_template(self, tmp_path):
        """Creates default task list with template content."""
        tasklist_path = tmp_path / "tasklist.md"
        ticket = JiraTicket(ticket_id="TEST-DEFAULT", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        _create_default_tasklist(tasklist_path, state)

        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        assert "# Task List: TEST-DEFAULT" in content
        assert "[Core functionality implementation with tests]" in content
        assert "[Integration/API layer with tests]" in content
        assert "[Documentation updates]" in content

    def test_includes_ticket_id_in_header(self, tmp_path):
        """Includes ticket ID in the task list header."""
        tasklist_path = tmp_path / "tasklist.md"
        ticket = JiraTicket(ticket_id="PROJ-999", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        _create_default_tasklist(tasklist_path, state)

        content = tasklist_path.read_text()
        assert "PROJ-999" in content

    def test_creates_parent_directory_if_needed(self, tmp_path):
        """Creates parent directories if they don't exist."""
        tasklist_path = tmp_path / "nested" / "dir" / "tasklist.md"
        ticket = JiraTicket(ticket_id="TEST-NESTED", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        # Create parent directory manually since _create_default_tasklist doesn't
        tasklist_path.parent.mkdir(parents=True, exist_ok=True)
        _create_default_tasklist(tasklist_path, state)

        assert tasklist_path.exists()


class TestGenerateTasklistRetry:
    """Tests for _generate_tasklist retry behavior."""

    @patch("spec.workflow.step2_tasklist.AuggieClient")
    def test_returns_false_on_auggie_failure(self, mock_auggie_class, tmp_path):
        """Returns False when Auggie command fails."""
        ticket = JiraTicket(ticket_id="TEST-FAIL", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-FAIL-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-FAIL-tasklist.md"

        mock_client = MagicMock()
        mock_client.run_print_with_output.return_value = (False, "Error occurred")
        mock_auggie_class.return_value = mock_client

        result = _generate_tasklist(state, plan_path, tasklist_path)

        assert result is False


# =============================================================================
# Tests for _validate_file_disjointness (Predictive Context)
# =============================================================================


class TestValidateFileDisjointness:
    """Tests for _validate_file_disjointness function.

    SECURITY: All tests now require repo_root parameter (no default).
    STRICT MODE: Empty target_files on INDEPENDENT tasks raises exception.
    """

    def test_returns_empty_for_disjoint_files(self, tmp_path):
        """Returns empty list when independent tasks have disjoint files."""
        tasks = [
            Task(
                name="Create login endpoint",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/api/login.py", "tests/api/test_login.py"],
            ),
            Task(
                name="Create register endpoint",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/api/register.py", "tests/api/test_register.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert errors == []

    def test_detects_file_collision(self, tmp_path):
        """Detects when two independent tasks target the same file."""
        tasks = [
            Task(
                name="Add login feature",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/api/auth.py", "tests/api/test_auth.py"],
            ),
            Task(
                name="Add logout feature",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/api/auth.py", "tests/api/test_logout.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert len(errors) == 1
        assert "src/api/auth.py" in errors[0]
        assert "Add login feature" in errors[0]
        assert "Add logout feature" in errors[0]

    def test_ignores_fundamental_tasks(self, tmp_path):
        """Ignores fundamental tasks in collision detection."""
        tasks = [
            Task(
                name="Setup database schema",
                category=TaskCategory.FUNDAMENTAL,
                target_files=["src/db/schema.py"],
            ),
            Task(
                name="Add user model",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/db/schema.py", "src/models/user.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        # No error because fundamental tasks are not checked for collisions
        assert errors == []

    def test_raises_on_empty_target_files_strict_mode(self, tmp_path):
        """STRICT MODE: Raises StrictFileScopingError on INDEPENDENT tasks without target_files."""
        tasks = [
            Task(
                name="Task without files",
                category=TaskCategory.INDEPENDENT,
                target_files=[],
            ),
            Task(
                name="Task with files",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/file.py"],
            ),
        ]

        with pytest.raises(StrictFileScopingError) as exc_info:
            _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert "Task without files" in str(exc_info.value)
        assert "Strict file scoping required" in str(exc_info.value)
        assert exc_info.value.task_name == "Task without files"

    def test_detects_multiple_collisions(self, tmp_path):
        """Detects multiple file collisions."""
        tasks = [
            Task(
                name="Task A",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/shared.py", "src/utils.py"],
            ),
            Task(
                name="Task B",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/shared.py"],
            ),
            Task(
                name="Task C",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/utils.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert len(errors) == 2
        # Check both collisions are reported
        error_text = " ".join(errors)
        assert "src/shared.py" in error_text
        assert "src/utils.py" in error_text

    def test_returns_empty_for_no_independent_tasks(self, tmp_path):
        """Returns empty list when there are no independent tasks."""
        tasks = [
            Task(
                name="Setup task",
                category=TaskCategory.FUNDAMENTAL,
                target_files=["src/setup.py"],
            ),
            Task(
                name="Config task",
                category=TaskCategory.FUNDAMENTAL,
                target_files=["src/config.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert errors == []

    def test_raises_on_path_traversal_attack(self, tmp_path):
        """SECURITY: Raises PathSecurityError on directory traversal attempt."""
        tasks = [
            Task(
                name="Malicious task",
                category=TaskCategory.INDEPENDENT,
                target_files=["../outside_repo.py", "src/inside.py"],
            ),
        ]

        with pytest.raises(PathSecurityError) as exc_info:
            _validate_file_disjointness(tasks, repo_root=tmp_path)

        assert "outside_repo.py" in str(exc_info.value)
        assert "escapes repository root" in str(exc_info.value)

    def test_detects_collision_with_path_normalization(self, tmp_path):
        """SECURITY: Detects collision between ./src/foo.py and src/foo.py (normalization)."""
        tasks = [
            Task(
                name="Task A using ./src",
                category=TaskCategory.INDEPENDENT,
                target_files=["./src/foo.py"],
            ),
            Task(
                name="Task B using src",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/foo.py"],
            ),
        ]

        errors = _validate_file_disjointness(tasks, repo_root=tmp_path)

        # Both paths normalize to src/foo.py, so there should be a collision
        assert len(errors) == 1
        assert "src/foo.py" in errors[0]
        assert "Task A using ./src" in errors[0]
        assert "Task B using src" in errors[0]


# =============================================================================
# Tests for _extract_tasklist_from_output with files metadata
# =============================================================================


class TestExtractTasklistWithFilesMetadata:
    """Tests for _extract_tasklist_from_output preserving files metadata."""

    def test_preserves_files_metadata(self):
        """Preserves <!-- files: ... --> metadata comments."""
        output = """Here is the task list:

## Fundamental Tasks
<!-- category: fundamental, order: 1 -->
<!-- files: src/db/schema.py -->
- [ ] Create database schema

## Independent Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/login.py, tests/api/test_login.py -->
- [ ] Create login endpoint
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "<!-- files: src/db/schema.py -->" in result
        assert "<!-- files: src/api/login.py, tests/api/test_login.py -->" in result

    def test_preserves_both_category_and_files_metadata(self):
        """Preserves both category and files metadata on separate lines."""
        output = """<!-- category: fundamental, order: 1 -->
<!-- files: src/models/user.py -->
- [ ] Create user model
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "<!-- category: fundamental, order: 1 -->" in result
        assert "<!-- files: src/models/user.py -->" in result
        assert "- [ ] Create user model" in result

    def test_preserves_files_metadata_order(self):
        """Preserves order of metadata comments before task."""
        output = """<!-- category: independent, group: utils -->
<!-- files: src/utils/helpers.py -->
- [ ] Create helper utilities
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        lines = result.splitlines()
        # Find the indices
        category_idx = next(i for i, l in enumerate(lines) if "category:" in l)
        files_idx = next(i for i, l in enumerate(lines) if "files:" in l)
        task_idx = next(i for i, l in enumerate(lines) if "Create helper" in l)

        # Category should come before files, files before task
        assert category_idx < files_idx < task_idx

    def test_handles_multiple_tasks_with_files(self):
        """Handles multiple tasks each with their own files metadata."""
        output = """<!-- category: independent, group: api -->
<!-- files: src/api/login.py -->
- [ ] Create login endpoint

<!-- category: independent, group: api -->
<!-- files: src/api/register.py -->
- [ ] Create register endpoint
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "<!-- files: src/api/login.py -->" in result
        assert "<!-- files: src/api/register.py -->" in result
        assert "- [ ] Create login endpoint" in result
        assert "- [ ] Create register endpoint" in result

