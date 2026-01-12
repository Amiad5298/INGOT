"""Tests for ai_workflow.workflow.step2_tasklist module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from ai_workflow.workflow.step2_tasklist import (
    step_2_create_tasklist,
    _generate_tasklist,
    _extract_tasklist_from_output,
)
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.tasks import parse_task_list
from ai_workflow.integrations.jira import JiraTicket
from ai_workflow.ui.menus import TaskReviewChoice


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

    @patch("ai_workflow.workflow.step2_tasklist.AuggieClient")
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
        workflow_state.planning_model = "test-model"
        
        # Act
        result = _generate_tasklist(
            workflow_state,
            plan_path,
            tasklist_path,
            mock_client,
        )

        # Assert
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        tasks = parse_task_list(content)
        assert len(tasks) == 3
        assert tasks[0].name == "Create user module"

    def test_uses_passed_auggie_when_no_planning_model(
        self,
        tmp_path,
    ):
        """Uses the passed auggie client when no planning_model is set."""
        # Setup
        ticket = JiraTicket(
            ticket_id="TEST-456",
            ticket_url="https://jira.example.com/TEST-456",
            summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.planning_model = ""  # No planning model

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-456-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-456-tasklist.md"

        mock_auggie = MagicMock()
        mock_auggie.run_print_with_output.return_value = (
            True,
            "- [ ] Single task\n"
        )

        # Act
        result = _generate_tasklist(state, plan_path, tasklist_path, mock_auggie)

        # Assert - the passed client should be used
        mock_auggie.run_print_with_output.assert_called_once()
        assert result is True

    def test_falls_back_to_default_when_no_tasks_extracted(
        self,
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

        mock_auggie = MagicMock()
        mock_auggie.run_print_with_output.return_value = (
            True,
            "I couldn't understand the plan. Please clarify."
        )

        result = _generate_tasklist(state, plan_path, tasklist_path, mock_auggie)

        # Should fall back to default template
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        # Default template has placeholder tasks
        assert "[Core functionality implementation with tests]" in content


class TestStep2CreateTasklist:
    """Tests for step_2_create_tasklist function."""

    @patch("ai_workflow.workflow.step2_tasklist.show_task_review_menu")
    @patch("ai_workflow.workflow.step2_tasklist._edit_tasklist")
    @patch("ai_workflow.workflow.step2_tasklist._generate_tasklist")
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

        def mock_generate_side_effect(state, plan_path, tasklist_path, auggie):
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

    @patch("ai_workflow.workflow.step2_tasklist.show_task_review_menu")
    @patch("ai_workflow.workflow.step2_tasklist._generate_tasklist")
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

        def mock_generate_effect(state, plan_path, tasklist_path, auggie):
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

    @patch("ai_workflow.workflow.step2_tasklist.show_task_review_menu")
    @patch("ai_workflow.workflow.step2_tasklist._generate_tasklist")
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

        mock_generate.side_effect = lambda s, pp, tp, a: (tp.write_text("- [ ] Task\n") or True)
        mock_menu.return_value = TaskReviewChoice.ABORT

        result = step_2_create_tasklist(state, MagicMock())

        assert result is False

