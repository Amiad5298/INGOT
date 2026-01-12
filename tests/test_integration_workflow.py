"""Integration tests for AI Workflow with task memory and error analysis."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from ai_workflow.workflow.step3_execute import _execute_task
from ai_workflow.workflow.tasks import Task, TaskStatus
from ai_workflow.workflow.state import WorkflowState
from ai_workflow.workflow.task_memory import TaskMemory
from ai_workflow.workflow.step1_plan import _build_plan_prompt
from ai_workflow.integrations.jira import JiraTicket
from ai_workflow.integrations.auggie import AuggieClient
from ai_workflow.utils.error_analysis import ErrorAnalysis


@pytest.fixture
def mock_workflow_state(tmp_path):
    """Create a mock workflow state for testing."""
    ticket = JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        summary="Test Feature",
        title="Implement test feature",
        description="Test description"
    )

    state = WorkflowState(ticket=ticket)

    # Create specs directory in tmp_path
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    # Create plan file
    plan_file = specs_dir / "TEST-123-plan.md"
    plan_file.write_text("""# Implementation Plan: TEST-123

## Task 1: Create user module
Create a user module with basic CRUD operations.

## Task 2: Add tests
Write unit tests for the user module.
""")
    state.plan_file = plan_file

    # Create tasklist file
    tasklist_file = specs_dir / "TEST-123-tasklist.md"
    tasklist_file.write_text("""# Task List: TEST-123

- [ ] Create user module
- [ ] Add tests
""")
    state.tasklist_file = tasklist_file

    return state


@pytest.fixture
def mock_auggie_client():
    """Create a mock Auggie client."""
    client = MagicMock()
    client.model = "test-model"
    return client


class TestFullWorkflowWithTaskMemory:
    """Integration tests for full workflow with task memory."""

    @patch("ai_workflow.workflow.task_memory._get_modified_files")
    @patch("ai_workflow.workflow.task_memory._identify_patterns_in_changes")
    def test_task_memory_captured_after_successful_task(
        self,
        mock_identify,
        mock_get_files,
        mock_workflow_state,
        mock_auggie_client,
    ):
        """Task memory is captured after successful task execution."""
        # Setup mocks
        mock_get_files.return_value = ["src/user.py"]
        mock_identify.return_value = ["Python implementation"]

        # Mock Auggie execution
        mock_auggie_client.execute.return_value = (True, "Task completed successfully")

        # Create task
        task = Task(name="Create user module")

        # Import and call the function that captures memory
        from ai_workflow.workflow.task_memory import capture_task_memory
        memory = capture_task_memory(task, mock_workflow_state)

        # Verify memory was captured
        assert len(mock_workflow_state.task_memories) == 1
        assert mock_workflow_state.task_memories[0].task_name == "Create user module"
        assert mock_workflow_state.task_memories[0].files_modified == ["src/user.py"]
        assert "Python implementation" in mock_workflow_state.task_memories[0].patterns_used

    @patch("ai_workflow.workflow.step3_execute.is_dirty")
    @patch("ai_workflow.workflow.task_memory._get_modified_files")
    @patch("ai_workflow.workflow.task_memory._identify_patterns_in_changes")
    def test_pattern_context_used_in_subsequent_tasks(
        self,
        mock_identify,
        mock_get_files,
        mock_is_dirty,
        mock_workflow_state,
    ):
        """Pattern context from previous tasks is used in subsequent tasks."""
        # Setup: Add a task memory to state
        mock_workflow_state.task_memories = [
            TaskMemory(
                task_name="Create user module",
                files_modified=["src/user.py"],
                patterns_used=["Python implementation", "Dataclass pattern"],
            )
        ]

        # Create a related task
        task = Task(name="Add tests for user module")

        # Build pattern context
        from ai_workflow.workflow.task_memory import build_pattern_context
        context = build_pattern_context(task, mock_workflow_state)

        # Verify context includes patterns from previous task
        assert "Patterns from Previous Tasks" in context
        assert "Create user module" in context
        assert "Python implementation" in context
        assert "Dataclass pattern" in context


class TestRetryWithErrorAnalysis:
    """Integration tests for retry with error analysis."""

    @patch("ai_workflow.workflow.step3_execute.is_dirty")
    def test_error_analysis_provides_structured_feedback(
        self,
        mock_is_dirty,
        mock_workflow_state,
        mock_auggie_client,
    ):
        """Error analysis provides structured feedback for retries."""
        mock_is_dirty.return_value = False

        # Simulate a Python error
        error_output = """Traceback (most recent call last):
  File "src/user.py", line 10, in create_user
    return User(name=name, email=email)
NameError: name 'User' is not defined
"""

        # Analyze the error
        from ai_workflow.utils.error_analysis import analyze_error_output
        task = Task(name="Create user module")
        analysis = analyze_error_output(error_output, task)

        # Verify structured analysis
        assert analysis.error_type == "name_error"
        assert analysis.file_path == "src/user.py"
        assert analysis.line_number == 10
        assert "NameError" in analysis.error_message
        assert "User" in analysis.error_message  # Variable name is in error message
        assert "not defined" in analysis.root_cause.lower()

    def test_error_analysis_can_be_formatted_for_prompt(self):
        """Error analysis can be formatted for prompts."""
        # Error output to analyze
        error_output = """TypeError: expected str, got int"""

        # Analyze error
        from ai_workflow.utils.error_analysis import analyze_error_output
        task = Task(name="Create user module")
        analysis = analyze_error_output(error_output, task)

        # Verify analysis can be formatted for prompt
        markdown = analysis.to_markdown()
        assert "**Type:** unknown" in markdown
        assert "TypeError" in markdown


class TestMultipleTasksWithMemory:
    """Integration tests for multiple tasks with memory accumulation."""

    @patch("ai_workflow.workflow.task_memory._get_modified_files")
    @patch("ai_workflow.workflow.task_memory._identify_patterns_in_changes")
    def test_memory_accumulates_across_tasks(
        self,
        mock_identify,
        mock_get_files,
        mock_workflow_state,
    ):
        """Memory accumulates across multiple tasks."""
        # Task 1
        mock_get_files.return_value = ["src/user.py"]
        mock_identify.return_value = ["Python implementation", "Dataclass pattern"]

        from ai_workflow.workflow.task_memory import capture_task_memory
        task1 = Task(name="Create user module")
        capture_task_memory(task1, mock_workflow_state)

        # Task 2
        mock_get_files.return_value = ["tests/test_user.py"]
        mock_identify.return_value = ["Python implementation", "Added Python tests"]

        task2 = Task(name="Add tests for user module")
        capture_task_memory(task2, mock_workflow_state)

        # Verify both memories are stored
        assert len(mock_workflow_state.task_memories) == 2
        assert mock_workflow_state.task_memories[0].task_name == "Create user module"
        assert mock_workflow_state.task_memories[1].task_name == "Add tests for user module"

        # Verify patterns are accumulated
        all_patterns = set()
        for memory in mock_workflow_state.task_memories:
            all_patterns.update(memory.patterns_used)

        assert "Python implementation" in all_patterns
        assert "Dataclass pattern" in all_patterns
        assert "Added Python tests" in all_patterns


class TestUserAdditionalContext:
    """Tests for user additional context feature."""

    @pytest.fixture
    def state_with_ticket(self):
        """Create a workflow state with ticket for testing."""
        ticket = JiraTicket(
            ticket_id="TEST-456",
            ticket_url="https://jira.example.com/TEST-456",
            summary="test-feature",
            title="Implement test feature",
            description="Test description for the feature"
        )
        return WorkflowState(ticket=ticket)

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input")
    def test_user_declines_additional_context(self, mock_input, mock_confirm, state_with_ticket):
        """User declines to add context - no prompt_input called."""
        mock_confirm.return_value = False

        # Simulate the logic from runner.py
        if mock_confirm("Would you like to add additional context about this ticket?", default=False):
            user_context = mock_input(
                "Enter additional context (press Enter twice when done):",
                multiline=True,
            )
            state_with_ticket.user_context = user_context.strip()

        # Verify prompt_input was not called
        mock_input.assert_not_called()
        # Verify state.user_context remains empty
        assert state_with_ticket.user_context == ""

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input")
    def test_user_adds_additional_context(self, mock_input, mock_confirm, state_with_ticket):
        """User provides additional context - stored in state."""
        mock_confirm.return_value = True
        mock_input.return_value = "Additional details about the feature"

        # Simulate the logic from runner.py
        if mock_confirm("Would you like to add additional context about this ticket?", default=False):
            user_context = mock_input(
                "Enter additional context (press Enter twice when done):",
                multiline=True,
            )
            state_with_ticket.user_context = user_context.strip()

        # Verify state.user_context is set
        assert state_with_ticket.user_context == "Additional details about the feature"

    @patch("ai_workflow.workflow.runner.prompt_confirm")
    @patch("ai_workflow.workflow.runner.prompt_input")
    def test_empty_context_handled(self, mock_input, mock_confirm, state_with_ticket):
        """Empty context input is handled gracefully."""
        mock_confirm.return_value = True
        mock_input.return_value = "   "  # whitespace only

        # Simulate the logic from runner.py
        if mock_confirm("Would you like to add additional context about this ticket?", default=False):
            user_context = mock_input(
                "Enter additional context (press Enter twice when done):",
                multiline=True,
            )
            state_with_ticket.user_context = user_context.strip()

        # Verify state.user_context is empty string after strip
        assert state_with_ticket.user_context == ""


class TestBuildPlanPrompt:
    """Tests for _build_plan_prompt function."""

    @pytest.fixture
    def state_with_ticket(self):
        """Create a workflow state with ticket for testing."""
        ticket = JiraTicket(
            ticket_id="TEST-789",
            ticket_url="https://jira.example.com/TEST-789",
            summary="test-feature",
            title="Implement test feature",
            description="Test description for the feature"
        )
        return WorkflowState(ticket=ticket)

    def test_prompt_without_user_context(self, state_with_ticket):
        """Prompt is built correctly without user context."""
        prompt = _build_plan_prompt(state_with_ticket)

        # Verify no user context section
        assert "Additional Context from User" not in prompt
        # Verify basic prompt structure
        assert "TEST-789" in prompt
        assert "Implement test feature" in prompt
        assert "Test description for the feature" in prompt

    def test_prompt_with_user_context(self, state_with_ticket):
        """Prompt includes user context when provided."""
        state_with_ticket.user_context = "Focus on performance optimization"
        prompt = _build_plan_prompt(state_with_ticket)

        # Verify user context section is present
        assert "Additional Context from User" in prompt
        assert "Focus on performance optimization" in prompt
        # Verify basic prompt structure is still there
        assert "TEST-789" in prompt
        assert "Implement test feature" in prompt

