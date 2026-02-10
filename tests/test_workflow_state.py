"""Tests for ingot.workflow.state module."""

from pathlib import Path

import pytest

from ingot.workflow.state import RateLimitConfig, WorkflowState


@pytest.fixture
def state(generic_ticket):
    """Create a test workflow state using shared generic_ticket fixture."""
    return WorkflowState(ticket=generic_ticket)


class TestWorkflowState:
    def test_default_values(self, state):
        assert state.branch_name == ""
        assert state.base_commit == ""
        assert state.skip_clarification is False
        assert state.squash_at_end is True
        assert state.current_step == 1
        assert state.retry_count == 0
        assert state.max_retries == 3

    def test_specs_dir(self, state):
        assert state.specs_dir == Path("specs")

    def test_plan_filename(self, state):
        assert state.plan_filename == "TEST-123-plan.md"

    def test_tasklist_filename(self, state):
        assert state.tasklist_filename == "TEST-123-tasklist.md"

    def test_get_plan_path(self, state):
        assert state.get_plan_path() == Path("specs/TEST-123-plan.md")

    def test_get_plan_path_with_override(self, state):
        state.plan_file = Path("/custom/plan.md")
        assert state.get_plan_path() == Path("/custom/plan.md")

    def test_get_tasklist_path(self, state):
        assert state.get_tasklist_path() == Path("specs/TEST-123-tasklist.md")

    def test_mark_task_complete(self, state):
        state.mark_task_complete("Task 1")
        assert "Task 1" in state.completed_tasks

    def test_mark_task_complete_no_duplicates(self, state):
        state.mark_task_complete("Task 1")
        state.mark_task_complete("Task 1")
        assert state.completed_tasks.count("Task 1") == 1

    def test_user_context_default_empty(self, state):
        assert state.user_context == ""

    def test_user_context_can_be_set(self, state):
        state.user_context = "Additional details"
        assert state.user_context == "Additional details"

    def test_fail_fast_default_false(self, state):
        assert state.fail_fast is False

    def test_fail_fast_can_be_set(self, state):
        state.fail_fast = True
        assert state.fail_fast is True

    def test_planning_model_default_empty(self, state):
        assert state.planning_model == ""

    def test_implementation_model_default_empty(self, state):
        assert state.implementation_model == ""

    def test_planning_model_can_be_set(self, state):
        state.planning_model = "gpt-4"
        assert state.planning_model == "gpt-4"

    def test_implementation_model_can_be_set(self, state):
        state.implementation_model = "claude-3-opus"
        assert state.implementation_model == "claude-3-opus"

    def test_task_memories_default_empty_list(self, state):
        assert state.task_memories == []
        assert isinstance(state.task_memories, list)

    def test_task_memories_can_be_appended(self, state):
        from ingot.workflow.task_memory import TaskMemory

        memory = TaskMemory(
            task_name="Test Task",
            files_modified=["src/test.py"],
            patterns_used=["Python implementation"],
        )
        state.task_memories.append(memory)

        assert len(state.task_memories) == 1
        assert state.task_memories[0].task_name == "Test Task"

    def test_get_tasklist_path_with_override(self, state):
        state.tasklist_file = Path("/custom/tasklist.md")
        assert state.get_tasklist_path() == Path("/custom/tasklist.md")

    def test_completed_tasks_default_empty(self, state):
        assert state.completed_tasks == []
        assert isinstance(state.completed_tasks, list)

    def test_checkpoint_commits_default_empty(self, state):
        assert state.checkpoint_commits == []
        assert isinstance(state.checkpoint_commits, list)


class TestRateLimitConfig:
    def test_default_max_retries(self):
        config = RateLimitConfig()
        assert config.max_retries == 5

    def test_default_base_delay(self):
        config = RateLimitConfig()
        assert config.base_delay_seconds == 2.0

    def test_default_max_delay(self):
        config = RateLimitConfig()
        assert config.max_delay_seconds == 60.0

    def test_default_jitter_factor(self):
        config = RateLimitConfig()
        assert config.jitter_factor == 0.5

    def test_default_retryable_status_codes(self):
        config = RateLimitConfig()
        assert config.retryable_status_codes == (429, 502, 503, 504)

    def test_custom_values(self):
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
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            RateLimitConfig(max_retries=-1)

    def test_zero_max_retries_allows_zero_base_delay(self):
        config = RateLimitConfig(max_retries=0, base_delay_seconds=0.0)
        assert config.max_retries == 0
        assert config.base_delay_seconds == 0.0

    def test_positive_max_retries_requires_positive_base_delay(self):
        with pytest.raises(ValueError, match="base_delay_seconds must be > 0"):
            RateLimitConfig(max_retries=3, base_delay_seconds=0.0)
        with pytest.raises(ValueError, match="base_delay_seconds must be > 0"):
            RateLimitConfig(max_retries=1, base_delay_seconds=-1.0)

    def test_jitter_factor_negative_raises_error(self):
        with pytest.raises(ValueError, match="jitter_factor must be in"):
            RateLimitConfig(jitter_factor=-0.1)

    def test_jitter_factor_above_one_raises_error(self):
        with pytest.raises(ValueError, match="jitter_factor must be in"):
            RateLimitConfig(jitter_factor=1.1)

    def test_jitter_factor_at_bounds_valid(self):
        config_zero = RateLimitConfig(jitter_factor=0.0)
        assert config_zero.jitter_factor == 0.0
        config_one = RateLimitConfig(jitter_factor=1.0)
        assert config_one.jitter_factor == 1.0

    def test_max_delay_less_than_base_raises_error(self):
        with pytest.raises(ValueError, match="max_delay_seconds must be >= base_delay_seconds"):
            RateLimitConfig(base_delay_seconds=10.0, max_delay_seconds=5.0)

    def test_max_delay_equals_base_delay_valid(self):
        config = RateLimitConfig(base_delay_seconds=5.0, max_delay_seconds=5.0)
        assert config.max_delay_seconds == config.base_delay_seconds


class TestWorkflowStateParallelFields:
    def test_max_parallel_tasks_default(self, state):
        assert state.max_parallel_tasks == 3

    def test_parallel_execution_enabled_default(self, state):
        assert state.parallel_execution_enabled is True

    def test_fail_fast_default(self, state):
        assert state.fail_fast is False

    def test_rate_limit_config_default(self, state):
        assert isinstance(state.rate_limit_config, RateLimitConfig)
        assert state.rate_limit_config.max_retries == 5

    def test_subagent_names_default(self, state):
        assert state.subagent_names == {
            "planner": "ingot-planner",
            "tasklist": "ingot-tasklist",
            "tasklist_refiner": "ingot-tasklist-refiner",
            "implementer": "ingot-implementer",
            "reviewer": "ingot-reviewer",
            "fixer": "ingot-implementer",
            "doc_updater": "ingot-doc-updater",
        }

    def test_subagent_names_custom(self, generic_ticket):
        state = WorkflowState(
            ticket=generic_ticket,
            subagent_names={
                "planner": "custom-planner",
                "tasklist": "custom-tasklist",
                "tasklist_refiner": "custom-tasklist-refiner",
                "implementer": "custom-implementer",
                "reviewer": "custom-reviewer",
                "doc_updater": "custom-doc-updater",
            },
        )
        assert state.subagent_names["planner"] == "custom-planner"
        assert state.subagent_names["tasklist_refiner"] == "custom-tasklist-refiner"
        assert state.subagent_names["implementer"] == "custom-implementer"
        assert state.subagent_names["doc_updater"] == "custom-doc-updater"


class TestWorkflowStateConflictDetectionFields:
    def test_conflict_detected_default_false(self, state):
        assert state.conflict_detected is False

    def test_conflict_detected_can_be_set(self, state):
        state.conflict_detected = True
        assert state.conflict_detected is True

    def test_conflict_summary_default_empty(self, state):
        assert state.conflict_summary == ""

    def test_conflict_summary_can_be_set(self, state):
        state.conflict_summary = "Ticket says add X but user says remove X."
        assert state.conflict_summary == "Ticket says add X but user says remove X."

    def test_conflict_fields_initialized_via_constructor(self, generic_ticket):
        state = WorkflowState(
            ticket=generic_ticket,
            conflict_detected=True,
            conflict_summary="Test conflict summary",
        )
        assert state.conflict_detected is True
        assert state.conflict_summary == "Test conflict summary"
