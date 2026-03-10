"""Tests for the runner replan loop in ingot.workflow.runner.

Covers:
- Successful replan cycle (fail → replan → succeed)
- Max replans exhausted
- Replan failure
- Tasklist regeneration failure
- Plain failure without replan
- Working tree restore via restore_to_baseline
- State reset (current_step, completed_tasks)
"""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.providers import GenericTicket, Platform
from ingot.workflow.git_utils import DirtyTreePolicy
from ingot.workflow.review import ReviewOutcome
from ingot.workflow.runner import run_ingot_workflow
from ingot.workflow.step3_execute import Step3Result
from ingot.workflow.step5_commit import Step5Result


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return GenericTicket(
        id="TEST-REPLAN",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-REPLAN",
        title="Test Replan Feature",
        description="Test description",
        branch_summary="test-replan",
    )


@pytest.fixture
def mock_config():
    """Create a mock ConfigManager."""
    config = MagicMock()
    config.settings = MagicMock()
    return config


# Common patch decorator for all workflow setup steps
def _workflow_patches(func):
    """Apply common patches needed for run_ingot_workflow to reach step 3."""
    patches = [
        patch("ingot.workflow.runner.get_current_branch", return_value="main"),
        patch("ingot.workflow.runner.is_dirty", return_value=False),
        patch("ingot.workflow.runner.prompt_confirm", return_value=False),
        patch("ingot.workflow.runner._setup_branch", return_value=True),
        patch("ingot.workflow.runner.get_current_commit", return_value="abc123"),
        patch("ingot.workflow.runner.step_1_create_plan", return_value=True),
        patch("ingot.workflow.runner.step_2_create_tasklist", return_value=True),
    ]
    for p in reversed(patches):
        func = p(func)
    return func


class TestReplanSuccessfulCycle:
    """Step 3 fails with replan, replan succeeds, step 3 succeeds on retry."""

    @_workflow_patches
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.restore_to_baseline")
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_successful_replan_cycle(
        self,
        mock_step3,
        mock_replan,
        mock_restore,
        mock_step5,
        mock_completion,
        # _workflow_patches args (in reverse order of patches):
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        # First call: fail with replan; second call: succeed
        mock_step3.side_effect = [
            Step3Result(
                success=False,
                needs_replan=True,
                replan_feedback="Plan is wrong",
                replan_mode=ReviewOutcome.REPLAN_WITH_AI,
            ),
            Step3Result(success=True),
        ]
        mock_replan.return_value = True
        mock_restore.return_value = True
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is True
        mock_replan.assert_called_once()
        # replan_with_feedback receives the feedback string
        assert mock_replan.call_args[0][2] == "Plan is wrong"
        # step 3 called twice (fail then success)
        assert mock_step3.call_count == 2
        # step 2 called twice (initial + regeneration after replan)
        assert mock_step2.call_count == 2


class TestReplanMaxExhausted:
    """Replan count at max, returns failure."""

    @_workflow_patches
    @patch("ingot.workflow.runner.step_3_execute")
    def test_max_replans_exhausted(
        self,
        mock_step3,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        # Always return needs_replan - will exhaust max_replans
        mock_step3.return_value = Step3Result(
            success=False,
            needs_replan=True,
            replan_feedback="Plan is wrong",
            replan_mode=ReviewOutcome.REPLAN_WITH_AI,
        )

        with patch("ingot.workflow.runner.replan_with_feedback", return_value=True):
            with patch("ingot.workflow.runner.restore_to_baseline", return_value=True):
                result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is False
        assert result.error == "Max replans exhausted"


class TestReplanFailure:
    """replan_with_feedback returns False."""

    @_workflow_patches
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_replan_failure(
        self,
        mock_step3,
        mock_replan,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_step3.return_value = Step3Result(
            success=False,
            needs_replan=True,
            replan_feedback="feedback",
            replan_mode=ReviewOutcome.REPLAN_WITH_AI,
        )
        mock_replan.return_value = False  # Replan fails

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is False
        assert result.error == "Re-planning failed"


class TestReplanTasklistFailure:
    """Tasklist regeneration fails after successful replan."""

    @_workflow_patches
    @patch("ingot.workflow.runner.restore_to_baseline")
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_tasklist_regeneration_failure(
        self,
        mock_step3,
        mock_replan,
        mock_restore,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_step3.return_value = Step3Result(
            success=False,
            needs_replan=True,
            replan_feedback="feedback",
            replan_mode=ReviewOutcome.REPLAN_WITH_AI,
        )
        mock_replan.return_value = True
        mock_restore.return_value = True
        # step_2 succeeds first time (initial), fails second time (regeneration)
        mock_step2.side_effect = [True, False]

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is False
        assert result.error == "Task list regeneration failed"


class TestStep3FailsWithoutReplan:
    """Plain failure, no replan triggered."""

    @_workflow_patches
    @patch("ingot.workflow.runner.step_3_execute")
    def test_plain_failure_no_replan(
        self,
        mock_step3,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_step3.return_value = Step3Result(success=False)

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is False
        assert result.error == "Step 3 (execute) failed"
        mock_step3.assert_called_once()


class TestReplanRestoresWorkingTree:
    """restore_to_baseline called correctly during replan."""

    @_workflow_patches
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.restore_to_baseline")
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_restore_called_with_baseline_ref(
        self,
        mock_step3,
        mock_replan,
        mock_restore,
        mock_step5,
        mock_completion,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        call_count = [0]

        def step3_side_effect(state, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                state.diff_baseline_ref = "baseline123"
                return Step3Result(
                    success=False,
                    needs_replan=True,
                    replan_feedback="feedback",
                    replan_mode=ReviewOutcome.REPLAN_WITH_AI,
                )
            return Step3Result(success=True)

        mock_step3.side_effect = step3_side_effect
        mock_replan.return_value = True
        mock_restore.return_value = True
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is True
        mock_restore.assert_called_once_with("baseline123", pre_execution_untracked=frozenset())

    @_workflow_patches
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.restore_to_baseline")
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_restore_failure_falls_back_to_warn_and_continue(
        self,
        mock_step3,
        mock_replan,
        mock_restore,
        mock_step5,
        mock_completion,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        call_count = [0]

        def step3_side_effect(state, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                state.diff_baseline_ref = "baseline123"
                return Step3Result(
                    success=False,
                    needs_replan=True,
                    replan_feedback="feedback",
                    replan_mode=ReviewOutcome.REPLAN_WITH_AI,
                )
            return Step3Result(success=True)

        mock_step3.side_effect = step3_side_effect
        mock_replan.return_value = True
        mock_restore.return_value = False  # Restore fails
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is True
        # Verify dirty tree policy was set to WARN_AND_CONTINUE
        # (checked via state passed to step3 second call)
        call_args = mock_step3.call_args_list[1]
        state = call_args[0][0]
        assert state.dirty_tree_policy == DirtyTreePolicy.WARN_AND_CONTINUE


class TestReplanResetsState:
    """current_step reset to 3 and completed_tasks cleared."""

    @_workflow_patches
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.restore_to_baseline")
    @patch("ingot.workflow.runner.replan_with_feedback")
    @patch("ingot.workflow.runner.step_3_execute")
    def test_completed_tasks_cleared_and_step_reset(
        self,
        mock_step3,
        mock_replan,
        mock_restore,
        mock_step5,
        mock_completion,
        mock_step2,
        mock_step1,
        mock_commit,
        mock_setup_branch,
        mock_confirm,
        mock_is_dirty,
        mock_get_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        call_count = [0]

        def step3_side_effect(state, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate some completed tasks
                state.completed_tasks = ["Task 1", "Task 2"]
                return Step3Result(
                    success=False,
                    needs_replan=True,
                    replan_feedback="feedback",
                    replan_mode=ReviewOutcome.REPLAN_WITH_AI,
                )
            else:
                # On second call, verify state was reset
                assert state.completed_tasks == []
                assert state.current_step == 3
                return Step3Result(success=True)

        mock_step3.side_effect = step3_side_effect
        mock_replan.return_value = True
        mock_restore.return_value = True
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result.success is True
        assert mock_step3.call_count == 2
