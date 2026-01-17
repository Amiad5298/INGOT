"""Tests for spec.workflow.state module."""

import pytest
from pathlib import Path

from spec.workflow.state import WorkflowState, RateLimitConfig
from spec.integrations.jira import JiraTicket


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

    def test_fail_fast_default_false(self, state):
        """fail_fast defaults to False."""
        assert state.fail_fast is False

    def test_fail_fast_can_be_set(self, state):
        """fail_fast can be set to True."""
        state.fail_fast = True
        assert state.fail_fast is True

    def test_planning_model_default_empty(self, state):
        """planning_model defaults to empty string."""
        assert state.planning_model == ""

    def test_implementation_model_default_empty(self, state):
        """implementation_model defaults to empty string."""
        assert state.implementation_model == ""

    def test_planning_model_can_be_set(self, state):
        """planning_model can be set."""
        state.planning_model = "gpt-4"
        assert state.planning_model == "gpt-4"

    def test_implementation_model_can_be_set(self, state):
        """implementation_model can be set."""
        state.implementation_model = "claude-3-opus"
        assert state.implementation_model == "claude-3-opus"

    def test_task_memories_default_empty_list(self, state):
        """task_memories defaults to empty list."""
        assert state.task_memories == []
        assert isinstance(state.task_memories, list)

    def test_task_memories_can_be_appended(self, state):
        """task_memories can have items appended."""
        from spec.workflow.task_memory import TaskMemory

        memory = TaskMemory(
            task_name="Test Task",
            files_modified=["src/test.py"],
            patterns_used=["Python implementation"],
        )
        state.task_memories.append(memory)

        assert len(state.task_memories) == 1
        assert state.task_memories[0].task_name == "Test Task"

    def test_get_tasklist_path_with_override(self, state):
        """get_tasklist_path uses override if set."""
        state.tasklist_file = Path("/custom/tasklist.md")
        assert state.get_tasklist_path() == Path("/custom/tasklist.md")

    def test_completed_tasks_default_empty(self, state):
        """completed_tasks defaults to empty list."""
        assert state.completed_tasks == []
        assert isinstance(state.completed_tasks, list)

    def test_checkpoint_commits_default_empty(self, state):
        """checkpoint_commits defaults to empty list."""
        assert state.checkpoint_commits == []
        assert isinstance(state.checkpoint_commits, list)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_max_retries(self):
        """max_retries defaults to 5."""
        config = RateLimitConfig()
        assert config.max_retries == 5

    def test_default_base_delay(self):
        """base_delay_seconds defaults to 2.0."""
        config = RateLimitConfig()
        assert config.base_delay_seconds == 2.0

    def test_default_max_delay(self):
        """max_delay_seconds defaults to 60.0."""
        config = RateLimitConfig()
        assert config.max_delay_seconds == 60.0

    def test_default_jitter_factor(self):
        """jitter_factor defaults to 0.5."""
        config = RateLimitConfig()
        assert config.jitter_factor == 0.5

    def test_default_retryable_status_codes(self):
        """retryable_status_codes defaults to (429, 502, 503, 504)."""
        config = RateLimitConfig()
        assert config.retryable_status_codes == (429, 502, 503, 504)

    def test_custom_values(self):
        """RateLimitConfig accepts custom values."""
        config = RateLimitConfig(
            max_retries=10,
            base_delay_seconds=5.0,
            max_delay_seconds=120.0,
            jitter_factor=0.3,
        )
        assert config.max_retries == 10
        assert config.base_delay_seconds == 5.0
        assert config.max_delay_seconds == 120.0
        assert config.jitter_factor == 0.3

    def test_negative_max_retries_raises_error(self):
        """max_retries < 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            RateLimitConfig(max_retries=-1)

    def test_zero_max_retries_allows_zero_base_delay(self):
        """max_retries=0 allows base_delay_seconds=0."""
        config = RateLimitConfig(max_retries=0, base_delay_seconds=0.0)
        assert config.max_retries == 0
        assert config.base_delay_seconds == 0.0

    def test_positive_max_retries_requires_positive_base_delay(self):
        """base_delay_seconds must be > 0 when max_retries > 0."""
        with pytest.raises(ValueError, match="base_delay_seconds must be > 0"):
            RateLimitConfig(max_retries=3, base_delay_seconds=0.0)
        with pytest.raises(ValueError, match="base_delay_seconds must be > 0"):
            RateLimitConfig(max_retries=1, base_delay_seconds=-1.0)

    def test_jitter_factor_negative_raises_error(self):
        """jitter_factor < 0 raises ValueError."""
        with pytest.raises(ValueError, match="jitter_factor must be in"):
            RateLimitConfig(jitter_factor=-0.1)

    def test_jitter_factor_above_one_raises_error(self):
        """jitter_factor > 1 raises ValueError."""
        with pytest.raises(ValueError, match="jitter_factor must be in"):
            RateLimitConfig(jitter_factor=1.1)

    def test_jitter_factor_at_bounds_valid(self):
        """jitter_factor=0 and jitter_factor=1 are valid."""
        config_zero = RateLimitConfig(jitter_factor=0.0)
        assert config_zero.jitter_factor == 0.0
        config_one = RateLimitConfig(jitter_factor=1.0)
        assert config_one.jitter_factor == 1.0

    def test_max_delay_less_than_base_raises_error(self):
        """max_delay_seconds < base_delay_seconds raises ValueError."""
        with pytest.raises(ValueError, match="max_delay_seconds must be >= base_delay_seconds"):
            RateLimitConfig(base_delay_seconds=10.0, max_delay_seconds=5.0)

    def test_max_delay_equals_base_delay_valid(self):
        """max_delay_seconds == base_delay_seconds is valid."""
        config = RateLimitConfig(base_delay_seconds=5.0, max_delay_seconds=5.0)
        assert config.max_delay_seconds == config.base_delay_seconds


class TestWorkflowStateParallelFields:
    """Tests for WorkflowState parallel execution fields."""

    def test_max_parallel_tasks_default(self, state):
        """max_parallel_tasks defaults to 3."""
        assert state.max_parallel_tasks == 3

    def test_parallel_execution_enabled_default(self, state):
        """parallel_execution_enabled defaults to True."""
        assert state.parallel_execution_enabled is True

    def test_parallel_tasks_completed_default(self, state):
        """parallel_tasks_completed defaults to empty list."""
        assert state.parallel_tasks_completed == []
        assert isinstance(state.parallel_tasks_completed, list)

    def test_parallel_tasks_failed_default(self, state):
        """parallel_tasks_failed defaults to empty list."""
        assert state.parallel_tasks_failed == []
        assert isinstance(state.parallel_tasks_failed, list)

    def test_fail_fast_default(self, state):
        """fail_fast defaults to False."""
        assert state.fail_fast is False

    def test_rate_limit_config_default(self, state):
        """rate_limit_config defaults to RateLimitConfig instance."""
        assert isinstance(state.rate_limit_config, RateLimitConfig)
        assert state.rate_limit_config.max_retries == 5

    def test_subagent_names_default(self, state):
        """subagent_names has correct defaults."""
        assert state.subagent_names == {
            "planner": "spec-planner",
            "tasklist": "spec-tasklist",
            "implementer": "spec-implementer",
            "reviewer": "spec-reviewer",
        }

    def test_subagent_names_custom(self, ticket):
        """subagent_names accepts custom values."""
        state = WorkflowState(
            ticket=ticket,
            subagent_names={
                "planner": "custom-planner",
                "tasklist": "custom-tasklist",
                "implementer": "custom-implementer",
                "reviewer": "custom-reviewer",
            },
        )
        assert state.subagent_names["planner"] == "custom-planner"
        assert state.subagent_names["implementer"] == "custom-implementer"

