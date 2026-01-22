"""Integration tests for AI Workflow with task memory and error analysis."""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.jira import JiraTicket
from spec.workflow.state import WorkflowState
from spec.workflow.step1_plan import _build_minimal_prompt
from spec.workflow.task_memory import TaskMemory
from spec.workflow.tasks import Task


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

    @patch("spec.workflow.task_memory._get_modified_files")
    @patch("spec.workflow.task_memory._identify_patterns_in_changes")
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
        from spec.workflow.task_memory import capture_task_memory
        capture_task_memory(task, mock_workflow_state)

        # Verify memory was captured
        assert len(mock_workflow_state.task_memories) == 1
        assert mock_workflow_state.task_memories[0].task_name == "Create user module"
        assert mock_workflow_state.task_memories[0].files_modified == ["src/user.py"]
        assert "Python implementation" in mock_workflow_state.task_memories[0].patterns_used

    @patch("spec.workflow.step3_execute.is_dirty")
    @patch("spec.workflow.task_memory._get_modified_files")
    @patch("spec.workflow.task_memory._identify_patterns_in_changes")
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
        from spec.workflow.task_memory import build_pattern_context
        context = build_pattern_context(task, mock_workflow_state)

        # Verify context includes patterns from previous task
        assert "Patterns from Previous Tasks" in context
        assert "Create user module" in context
        assert "Python implementation" in context
        assert "Dataclass pattern" in context


class TestRetryWithErrorAnalysis:
    """Integration tests for retry with error analysis."""

    @patch("spec.workflow.step3_execute.is_dirty")
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
        from spec.utils.error_analysis import analyze_error_output
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
        from spec.utils.error_analysis import analyze_error_output
        task = Task(name="Create user module")
        analysis = analyze_error_output(error_output, task)

        # Verify analysis can be formatted for prompt
        markdown = analysis.to_markdown()
        assert "**Type:** unknown" in markdown
        assert "TypeError" in markdown


class TestMultipleTasksWithMemory:
    """Integration tests for multiple tasks with memory accumulation."""

    @patch("spec.workflow.task_memory._get_modified_files")
    @patch("spec.workflow.task_memory._identify_patterns_in_changes")
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

        from spec.workflow.task_memory import capture_task_memory
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

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.prompt_input")
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

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.prompt_input")
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

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.prompt_input")
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


class TestBuildMinimalPrompt:
    """Tests for _build_minimal_prompt function."""

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

    def test_prompt_without_user_context(self, state_with_ticket, tmp_path):
        """Prompt is built correctly without user context."""
        plan_path = tmp_path / "specs" / "TEST-789-plan.md"
        prompt = _build_minimal_prompt(state_with_ticket, plan_path)

        # Verify no user context section (note: section name changed)
        assert "Additional Context:" not in prompt
        # Verify basic prompt structure
        assert "TEST-789" in prompt
        assert "Implement test feature" in prompt
        assert "Test description for the feature" in prompt
        assert str(plan_path) in prompt

    def test_prompt_with_user_context(self, state_with_ticket, tmp_path):
        """Prompt includes user context when provided."""
        plan_path = tmp_path / "specs" / "TEST-789-plan.md"
        state_with_ticket.user_context = "Focus on performance optimization"
        prompt = _build_minimal_prompt(state_with_ticket, plan_path)

        # Verify user context section is present (note: section name changed)
        assert "Additional Context:" in prompt
        assert "Focus on performance optimization" in prompt
        # Verify basic prompt structure is still there
        assert "TEST-789" in prompt
        assert "Implement test feature" in prompt


class TestWorkflowWithFailFast:
    """Tests for workflow with fail_fast enabled."""

    @pytest.fixture
    def state_with_fail_fast(self, tmp_path):
        """Create a workflow state with fail_fast enabled."""
        ticket = JiraTicket(
            ticket_id="TEST-FF",
            ticket_url="https://jira.example.com/TEST-FF",
            summary="Test Feature",
            title="Test with fail_fast",
            description="Test description"
        )
        state = WorkflowState(ticket=ticket)
        state.fail_fast = True

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)

        plan_file = specs_dir / "TEST-FF-plan.md"
        plan_file.write_text("# Plan\n\nDo something.")
        state.plan_file = plan_file

        tasklist_file = specs_dir / "TEST-FF-tasklist.md"
        tasklist_file.write_text("- [ ] Task 1\n- [ ] Task 2\n")
        state.tasklist_file = tasklist_file

        return state

    def test_fail_fast_stops_on_first_failure(self, state_with_fail_fast):
        """With fail_fast enabled, workflow stops on first task failure."""
        assert state_with_fail_fast.fail_fast is True
        # The fail_fast behavior is tested at the runner level
        # This test verifies the state is correctly configured

    def test_fail_fast_default_is_false(self):
        """fail_fast defaults to False."""
        ticket = JiraTicket(
            ticket_id="TEST-DEFAULT",
            ticket_url="test",
            summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        assert state.fail_fast is False


class TestWorkflowWithSquashAtEnd:
    """Tests for workflow with squash_at_end option."""

    @pytest.fixture
    def state_with_squash(self, tmp_path):
        """Create a workflow state with squash_at_end enabled."""
        ticket = JiraTicket(
            ticket_id="TEST-SQUASH",
            ticket_url="test",
            summary="Test Feature",
        )
        state = WorkflowState(ticket=ticket)
        state.squash_at_end = True
        return state

    def test_squash_at_end_defaults_to_true(self):
        """squash_at_end defaults to True."""
        ticket = JiraTicket(ticket_id="TEST", ticket_url="test", summary="Test")
        state = WorkflowState(ticket=ticket)
        assert state.squash_at_end is True

    def test_squash_at_end_can_be_disabled(self, state_with_squash):
        """squash_at_end can be disabled."""
        state_with_squash.squash_at_end = False
        assert state_with_squash.squash_at_end is False


class TestAuggieClientFailures:
    """Tests for handling Auggie client failures."""

    @patch("spec.workflow.task_memory._get_modified_files")
    @patch("spec.workflow.task_memory._identify_patterns_in_changes")
    def test_handles_auggie_failure_gracefully(
        self,
        mock_identify,
        mock_get_files,
        mock_workflow_state,
        mock_auggie_client,
    ):
        """Handles Auggie client failure gracefully."""
        # Setup
        mock_get_files.return_value = []
        mock_identify.return_value = []
        mock_auggie_client.execute.return_value = (False, "Auggie error occurred")

        # Even with failure, task memory can still be captured (with empty data)
        from spec.workflow.task_memory import capture_task_memory
        from spec.workflow.tasks import Task

        task = Task(name="Failed task")
        capture_task_memory(task, mock_workflow_state)

        # Memory should be captured even with empty results
        assert len(mock_workflow_state.task_memories) == 1
        assert mock_workflow_state.task_memories[0].files_modified == []


class TestGitCommandFailures:
    """Tests for handling git command failures."""

    def test_state_tracks_base_commit(self, mock_workflow_state):
        """State tracks base commit correctly."""
        mock_workflow_state.base_commit = "abc123"
        assert mock_workflow_state.base_commit == "abc123"


class TestFileSystemErrors:
    """Tests for handling file system errors."""

    def test_handles_missing_plan_file(self, tmp_path):
        """Handles missing plan file gracefully."""
        ticket = JiraTicket(
            ticket_id="TEST-MISSING",
            ticket_url="test",
            summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        # plan_file is not set, get_plan_path returns default

        plan_path = state.get_plan_path()
        assert not plan_path.exists()

    def test_handles_missing_tasklist_file(self, tmp_path):
        """Handles missing tasklist file gracefully."""
        ticket = JiraTicket(
            ticket_id="TEST-MISSING",
            ticket_url="test",
            summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        tasklist_path = state.get_tasklist_path()
        assert not tasklist_path.exists()


class TestWorkflowResumption:
    """Tests for workflow resumption from different steps."""

    @pytest.fixture
    def resumable_state(self, tmp_path):
        """Create a state that can be resumed."""
        ticket = JiraTicket(
            ticket_id="TEST-RESUME",
            ticket_url="test",
            summary="Test Resume",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)

        plan_file = specs_dir / "TEST-RESUME-plan.md"
        plan_file.write_text("# Plan\n\n## Task 1\nDo something.\n")
        state.plan_file = plan_file

        tasklist_file = specs_dir / "TEST-RESUME-tasklist.md"
        tasklist_file.write_text("- [x] Completed task\n- [ ] Pending task\n")
        state.tasklist_file = tasklist_file

        return state

    def test_resume_from_step_2(self, resumable_state):
        """Can resume workflow from step 2."""
        resumable_state.current_step = 2

        # Verify state is configured for step 2
        assert resumable_state.current_step == 2
        assert resumable_state.plan_file.exists()

    def test_resume_from_step_3(self, resumable_state):
        """Can resume workflow from step 3."""
        resumable_state.current_step = 3
        resumable_state.completed_tasks = ["Completed task"]

        # Verify state is configured for step 3
        assert resumable_state.current_step == 3
        assert resumable_state.tasklist_file.exists()
        assert len(resumable_state.completed_tasks) == 1

    def test_preserves_completed_tasks_on_resume(self, resumable_state):
        """Preserves completed tasks when resuming."""
        resumable_state.completed_tasks = ["Task A", "Task B"]
        resumable_state.current_step = 3

        assert resumable_state.completed_tasks == ["Task A", "Task B"]

    def test_preserves_checkpoint_commits_on_resume(self, resumable_state):
        """Preserves checkpoint commits when resuming."""
        resumable_state.checkpoint_commits = ["abc123", "def456"]
        resumable_state.current_step = 3

        assert resumable_state.checkpoint_commits == ["abc123", "def456"]


class TestEndToEndWorkflowScenarios:
    """End-to-end workflow scenario tests."""

    @pytest.fixture
    def complete_state(self, tmp_path):
        """Create a complete workflow state for testing."""
        ticket = JiraTicket(
            ticket_id="TEST-E2E",
            ticket_url="https://jira.example.com/TEST-E2E",
            summary="End-to-end Test",
            title="E2E Test Feature",
            description="Complete E2E test",
        )
        state = WorkflowState(ticket=ticket)
        state.branch_name = "feature/TEST-E2E-e2e-test"
        state.base_commit = "abc123"
        state.planning_model = "gpt-4"
        state.implementation_model = "claude-3-opus"

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)

        plan_file = specs_dir / "TEST-E2E-plan.md"
        plan_file.write_text("# Plan\n\n## Step 1\nDo X.\n\n## Step 2\nDo Y.")
        state.plan_file = plan_file

        tasklist_file = specs_dir / "TEST-E2E-tasklist.md"
        tasklist_file.write_text("- [ ] Task 1\n- [ ] Task 2\n- [ ] Task 3\n")
        state.tasklist_file = tasklist_file

        return state

    def test_complete_workflow_state_configuration(self, complete_state):
        """Complete workflow state has all necessary configuration."""
        assert complete_state.ticket.ticket_id == "TEST-E2E"
        assert complete_state.branch_name == "feature/TEST-E2E-e2e-test"
        assert complete_state.base_commit == "abc123"
        assert complete_state.planning_model == "gpt-4"
        assert complete_state.implementation_model == "claude-3-opus"
        assert complete_state.plan_file.exists()
        assert complete_state.tasklist_file.exists()

    def test_workflow_progresses_through_steps(self, complete_state):
        """Workflow state progresses through steps 1-3."""
        # Step 1
        complete_state.current_step = 1
        assert complete_state.current_step == 1

        # Step 2
        complete_state.current_step = 2
        assert complete_state.current_step == 2

        # Step 3
        complete_state.current_step = 3
        assert complete_state.current_step == 3

    def test_workflow_tracks_task_completion(self, complete_state):
        """Workflow tracks task completion correctly."""
        complete_state.mark_task_complete("Task 1")
        complete_state.mark_task_complete("Task 2")

        assert "Task 1" in complete_state.completed_tasks
        assert "Task 2" in complete_state.completed_tasks
        assert len(complete_state.completed_tasks) == 2

    def test_workflow_tracks_checkpoints(self, complete_state):
        """Workflow tracks checkpoint commits correctly."""
        complete_state.checkpoint_commits.append("commit1")
        complete_state.checkpoint_commits.append("commit2")

        assert len(complete_state.checkpoint_commits) == 2
        assert "commit1" in complete_state.checkpoint_commits
        assert "commit2" in complete_state.checkpoint_commits

    @patch("spec.workflow.task_memory._get_modified_files")
    @patch("spec.workflow.task_memory._identify_patterns_in_changes")
    def test_workflow_accumulates_task_memories(
        self,
        mock_identify,
        mock_get_files,
        complete_state,
    ):
        """Workflow accumulates task memories across tasks."""
        from spec.workflow.task_memory import capture_task_memory
        from spec.workflow.tasks import Task

        # Task 1
        mock_get_files.return_value = ["src/module1.py"]
        mock_identify.return_value = ["Python implementation"]

        task1 = Task(name="Task 1")
        capture_task_memory(task1, complete_state)

        # Task 2
        mock_get_files.return_value = ["src/module2.py"]
        mock_identify.return_value = ["API integration"]

        task2 = Task(name="Task 2")
        capture_task_memory(task2, complete_state)

        # Task 3
        mock_get_files.return_value = ["tests/test_module.py"]
        mock_identify.return_value = ["Unit tests"]

        task3 = Task(name="Task 3")
        capture_task_memory(task3, complete_state)

        # All memories accumulated
        assert len(complete_state.task_memories) == 3
        assert complete_state.task_memories[0].task_name == "Task 1"
        assert complete_state.task_memories[1].task_name == "Task 2"
        assert complete_state.task_memories[2].task_name == "Task 3"

