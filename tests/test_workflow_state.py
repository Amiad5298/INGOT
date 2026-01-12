"""Tests for ai_workflow.workflow.state module."""

import pytest
from pathlib import Path

from ai_workflow.workflow.state import WorkflowState
from ai_workflow.integrations.jira import JiraTicket


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return JiraTicket(
        ticket_id="TEST-123",
        ticket_url="TEST-123",
        title="Test ticket",
        description="Test description",
    )


@pytest.fixture
def state(ticket):
    """Create a test workflow state."""
    return WorkflowState(ticket=ticket)


class TestWorkflowState:
    """Tests for WorkflowState dataclass."""

    def test_default_values(self, state):
        """Default values are set correctly."""
        assert state.branch_name == ""
        assert state.base_commit == ""
        assert state.skip_clarification is False
        assert state.squash_at_end is True
        assert state.current_step == 1
        assert state.retry_count == 0
        assert state.max_retries == 3

    def test_specs_dir(self, state):
        """specs_dir returns correct path."""
        assert state.specs_dir == Path("specs")

    def test_plan_filename(self, state):
        """plan_filename uses ticket ID."""
        assert state.plan_filename == "TEST-123-plan.md"

    def test_tasklist_filename(self, state):
        """tasklist_filename uses ticket ID."""
        assert state.tasklist_filename == "TEST-123-tasklist.md"

    def test_get_plan_path(self, state):
        """get_plan_path returns full path."""
        assert state.get_plan_path() == Path("specs/TEST-123-plan.md")

    def test_get_plan_path_with_override(self, state):
        """get_plan_path uses override if set."""
        state.plan_file = Path("/custom/plan.md")
        assert state.get_plan_path() == Path("/custom/plan.md")

    def test_get_tasklist_path(self, state):
        """get_tasklist_path returns full path."""
        assert state.get_tasklist_path() == Path("specs/TEST-123-tasklist.md")

    def test_mark_task_complete(self, state):
        """mark_task_complete adds task to list."""
        state.mark_task_complete("Task 1")
        assert "Task 1" in state.completed_tasks

    def test_mark_task_complete_no_duplicates(self, state):
        """mark_task_complete doesn't add duplicates."""
        state.mark_task_complete("Task 1")
        state.mark_task_complete("Task 1")
        assert state.completed_tasks.count("Task 1") == 1

    def test_add_checkpoint(self, state):
        """add_checkpoint adds commit hash."""
        state.add_checkpoint("abc123")
        assert "abc123" in state.checkpoint_commits

    def test_reset_retries(self, state):
        """reset_retries sets count to zero."""
        state.retry_count = 5
        state.reset_retries()
        assert state.retry_count == 0

    def test_increment_retries_returns_true(self, state):
        """increment_retries returns True when retries available."""
        assert state.increment_retries() is True
        assert state.retry_count == 1

    def test_increment_retries_returns_false_at_max(self, state):
        """increment_retries returns False at max."""
        state.retry_count = 2
        assert state.increment_retries() is False
        assert state.retry_count == 3

    def test_user_context_default_empty(self, state):
        """user_context defaults to empty string."""
        assert state.user_context == ""

    def test_user_context_can_be_set(self, state):
        """user_context can be set."""
        state.user_context = "Additional details"
        assert state.user_context == "Additional details"

