"""Tests for ingot.workflow.runner module."""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.providers import GenericTicket, Platform
from ingot.utils.errors import IngotError, UserCancelledError
from ingot.workflow.conflict_detection import _detect_context_conflict
from ingot.workflow.runner import (
    _offer_cleanup,
    _setup_branch,
    _show_completion,
    run_ingot_workflow,
    workflow_cleanup,
)
from ingot.workflow.state import WorkflowState
from ingot.workflow.step4_update_docs import Step4Result
from ingot.workflow.step5_commit import Step5Result


# Use generic_ticket and generic_ticket_no_summary fixtures from conftest.py
# These are aliased below for local compatibility
@pytest.fixture
def ticket(generic_ticket):
    """Alias for generic_ticket fixture from conftest.py."""
    return generic_ticket


@pytest.fixture
def ticket_no_summary(generic_ticket_no_summary):
    """Alias for generic_ticket_no_summary fixture from conftest.py."""
    return generic_ticket_no_summary


@pytest.fixture
def workflow_state(ticket, tmp_path):
    """Create a workflow state for testing."""
    state = WorkflowState(ticket=ticket)
    state.planning_model = "test-planning-model"
    state.implementation_model = "test-implementation-model"

    # Create specs directory
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    return state


@pytest.fixture
def mock_config():
    """Create a mock ConfigManager."""
    config = MagicMock()
    config.settings = MagicMock()
    config.settings.default_model = "default-model"
    return config


class TestSetupBranchNameGeneration:
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_generates_branch_name_with_summary(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        # From conftest: branch_summary="test-feature" → slug="test-123-test-feature"
        assert workflow_state.branch_name == "feature/test-123-test-feature"

    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_generates_fallback_branch_name_without_summary(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket_no_summary
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Update workflow_state with no-summary ticket
        workflow_state.ticket = ticket_no_summary

        result = _setup_branch(workflow_state, ticket_no_summary)

        assert result is True
        # When no branch_summary, GenericTicket uses title to generate branch name
        assert workflow_state.branch_name == "feature/test-456-test-feature-no-summary"


class TestSetupBranchAlreadyOnFeature:
    @patch("ingot.workflow.runner.get_current_branch")
    def test_stays_on_current_branch_if_already_on_feature_branch(
        self, mock_get_branch, workflow_state, ticket
    ):
        # From conftest: branch_summary="test-feature" → slug="test-123-test-feature"
        expected_branch = "feature/test-123-test-feature"
        mock_get_branch.return_value = expected_branch

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        assert workflow_state.branch_name == expected_branch

    @patch("ingot.workflow.runner.get_current_branch")
    def test_updates_state_branch_name_correctly(self, mock_get_branch, workflow_state, ticket):
        # From conftest: branch_summary="test-feature" → slug="test-123-test-feature"
        expected_branch = "feature/test-123-test-feature"
        mock_get_branch.return_value = expected_branch

        _setup_branch(workflow_state, ticket)

        assert workflow_state.branch_name == expected_branch


class TestSetupBranchCreateNew:
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_creates_new_branch_when_user_confirms(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        # From conftest: branch_summary="test-feature" → slug="test-123-test-feature"
        mock_create.assert_called_once_with("feature/test-123-test-feature")

    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_true_on_successful_branch_creation(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True

    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_false_on_branch_creation_failure(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = False  # Branch creation fails

        result = _setup_branch(workflow_state, ticket)

        assert result is False


class TestSetupBranchUserDeclines:
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_stays_on_current_branch_when_user_declines(
        self, mock_get_branch, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = False  # User declines

        result = _setup_branch(workflow_state, ticket)

        assert result is True

    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_updates_state_branch_name_to_current_branch(
        self, mock_get_branch, mock_confirm, workflow_state, ticket
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = False  # User declines

        _setup_branch(workflow_state, ticket)

        assert workflow_state.branch_name == "main"


class TestShowCompletion:
    @patch("ingot.workflow.runner.console")
    def test_displays_ticket_id(self, mock_console, workflow_state):
        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("TEST-123" in c for c in calls)

    @patch("ingot.workflow.runner.console")
    def test_displays_branch_name(self, mock_console, workflow_state):
        workflow_state.branch_name = "feature/test-branch"

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("feature/test-branch" in c for c in calls)

    @patch("ingot.workflow.runner.console")
    def test_displays_completed_task_count(self, mock_console, workflow_state):
        workflow_state.completed_tasks = ["Task 1", "Task 2", "Task 3"]

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("3" in c for c in calls)

    @patch("ingot.workflow.runner.console")
    def test_displays_plan_file_if_exists(self, mock_console, workflow_state, tmp_path):
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        workflow_state.plan_file = plan_path

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Plan" in c for c in calls)

    @patch("ingot.workflow.runner.console")
    def test_displays_tasklist_file_if_exists(self, mock_console, workflow_state, tmp_path):
        tasklist_path = tmp_path / "specs" / "TEST-123-tasklist.md"
        workflow_state.tasklist_file = tasklist_path

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Tasks" in c for c in calls)

    @patch("ingot.workflow.runner.print_info")
    @patch("ingot.workflow.runner.console")
    def test_prints_next_steps(self, mock_console, mock_print_info, workflow_state):
        _show_completion(workflow_state)

        calls = [str(c) for c in mock_print_info.call_args_list]
        assert any("Next steps" in c for c in calls)
        assert any("Review" in c for c in calls)
        assert any("tests" in c for c in calls)


class TestWorkflowCleanupNormal:
    @patch("ingot.workflow.runner.get_current_branch")
    def test_yields_normally_on_success(self, mock_get_branch, workflow_state):
        mock_get_branch.return_value = "main"

        executed = False
        with workflow_cleanup(workflow_state):
            executed = True

        assert executed is True


class TestWorkflowCleanupUserCancelled:
    @patch("ingot.workflow.runner._offer_cleanup")
    @patch("ingot.workflow.runner.print_info")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_catches_user_cancelled_error(
        self, mock_get_branch, mock_print_info, mock_offer_cleanup, workflow_state
    ):
        mock_get_branch.return_value = "main"

        with pytest.raises(UserCancelledError):
            with workflow_cleanup(workflow_state):
                raise UserCancelledError("User cancelled")

        mock_print_info.assert_called()
        mock_offer_cleanup.assert_called_once()


class TestWorkflowCleanupIngotError:
    @patch("ingot.workflow.runner._offer_cleanup")
    @patch("ingot.workflow.runner.print_error")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_catches_spec_error(
        self, mock_get_branch, mock_print_error, mock_offer_cleanup, workflow_state
    ):
        mock_get_branch.return_value = "main"

        with pytest.raises(IngotError):
            with workflow_cleanup(workflow_state):
                raise IngotError("Workflow failed")

        mock_print_error.assert_called()
        mock_offer_cleanup.assert_called_once()


class TestWorkflowCleanupGenericException:
    @patch("ingot.workflow.runner._offer_cleanup")
    @patch("ingot.workflow.runner.print_error")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_catches_generic_exceptions(
        self, mock_get_branch, mock_print_error, mock_offer_cleanup, workflow_state
    ):
        mock_get_branch.return_value = "main"

        with pytest.raises(RuntimeError):
            with workflow_cleanup(workflow_state):
                raise RuntimeError("Unexpected error")

        mock_print_error.assert_called()
        mock_offer_cleanup.assert_called_once()


class TestOfferCleanupCheckpointCommits:
    @patch("ingot.workflow.runner.console")
    @patch("ingot.workflow.runner.print_info")
    @patch("ingot.workflow.runner.print_warning")
    def test_prints_checkpoint_commit_count(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        workflow_state.checkpoint_commits = ["abc123", "def456", "ghi789"]

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        assert any("3" in c and "checkpoint" in c.lower() for c in calls)


class TestOfferCleanupBranchInfo:
    @patch("ingot.workflow.runner.console")
    @patch("ingot.workflow.runner.print_info")
    @patch("ingot.workflow.runner.print_warning")
    def test_prints_branch_info_when_different(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        workflow_state.branch_name = "feature/test-branch"

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        assert any("feature/test-branch" in c for c in calls)
        assert any("main" in c for c in calls)

    @patch("ingot.workflow.runner.console")
    @patch("ingot.workflow.runner.print_info")
    @patch("ingot.workflow.runner.print_warning")
    def test_does_not_print_branch_info_when_same(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        workflow_state.branch_name = "main"

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        # Should not have branch-related info calls when branches are the same
        assert not any("On branch" in c for c in calls)


class TestRunIngotWorkflowInit:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_initializes_workflow_state_correctly(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False  # No additional context
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            planning_model="custom-planning",
            implementation_model="custom-impl",
            skip_clarification=True,
            squash_at_end=False,
        )

        assert result is True
        # Verify step1 was called with a state that has correct values
        call_args = mock_step1.call_args[0]
        state = call_args[0]
        assert state.planning_model == "custom-planning"
        assert state.implementation_model == "custom-impl"
        assert state.skip_clarification is True
        assert state.squash_at_end is False


class TestRunIngotWorkflowDirtyState:
    @patch("ingot.workflow.runner.handle_dirty_state")
    @patch("ingot.workflow.runner.show_git_dirty_menu")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_handles_dirty_state_at_start(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_menu,
        mock_handle,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = True
        mock_menu.return_value = "stash"
        mock_handle.return_value = False  # Handling fails

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result is False
        mock_menu.assert_called_once()
        mock_handle.assert_called_once()


class TestRunIngotWorkflowUserContext:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_input")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_stores_user_context_when_confirmed(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_input,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.side_effect = [True, True]  # Add context, then other prompts
        mock_input.return_value = "Additional implementation details"
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        mock_input.assert_called_once()
        # Verify state received the context
        call_args = mock_step1.call_args[0]
        state = call_args[0]
        assert state.user_context == "Additional implementation details"


class TestRunIngotWorkflowBranchSetup:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_records_base_commit(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123def456"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        mock_commit.assert_called_once()
        call_args = mock_step1.call_args[0]
        state = call_args[0]
        assert state.base_commit == "abc123def456"

    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_false_when_branch_setup_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = False  # Branch setup fails

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result is False


class TestRunIngotWorkflowStepOrchestration:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_calls_all_steps_in_sequence(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        mock_step1.assert_called_once()
        mock_step2.assert_called_once()
        mock_step3.assert_called_once()

    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_false_when_step1_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = False  # Step 1 fails

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result is False
        mock_step2.assert_not_called()

    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_false_when_step2_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = False  # Step 2 fails

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result is False
        mock_step3.assert_not_called()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_returns_true_when_all_steps_succeed(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        assert result is True


class TestRunIngotWorkflowCompletion:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_shows_completion_on_success(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        mock_completion.assert_called_once()


class TestRunIngotWorkflowStep3Arguments:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_passes_use_tui_and_verbose_to_step_3_execute(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            use_tui=True,
            verbose=True,
        )

        # Verify step_3_execute was called with correct keyword arguments
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is True
        assert call_kwargs["verbose"] is True

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_passes_use_tui_false_and_verbose_false_to_step_3_execute(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            use_tui=False,
            verbose=False,
        )

        # Verify step_3_execute was called with correct keyword arguments
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is False
        assert call_kwargs["verbose"] is False

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_passes_use_tui_none_for_auto_detection(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        # Call without specifying use_tui (defaults to None)
        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
        )

        # Verify step_3_execute was called with use_tui=None
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is None
        assert call_kwargs["verbose"] is False


class TestRunIngotWorkflowResumeLogic:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    @patch("ingot.workflow.runner.WorkflowState")
    def test_skips_step_1_when_current_step_is_2(
        self,
        mock_state_class,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        # Create a mock state with current_step = 2
        mock_state = MagicMock()
        mock_state.current_step = 2
        mock_state.ticket = ticket
        mock_state_class.return_value = mock_state

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        # Step 1 should NOT be called because current_step > 1
        mock_step1.assert_not_called()
        # Step 2 and 3 should be called
        mock_step2.assert_called_once()
        mock_step3.assert_called_once()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    @patch("ingot.workflow.runner.WorkflowState")
    def test_skips_step_1_and_step_2_when_current_step_is_3(
        self,
        mock_state_class,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        # Create a mock state with current_step = 3
        mock_state = MagicMock()
        mock_state.current_step = 3
        mock_state.ticket = ticket
        mock_state_class.return_value = mock_state

        run_ingot_workflow(ticket=ticket, config=mock_config, backend=mock_backend)

        # Step 1 and 2 should NOT be called because current_step > 2
        mock_step1.assert_not_called()
        mock_step2.assert_not_called()
        # Only Step 3 should be called
        mock_step3.assert_called_once()


class TestSetupBranchSpecialCharacters:
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_branch_name_with_spaces_and_special_chars(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Create ticket with special characters in branch_summary
        special_ticket = GenericTicket(
            id="TEST-789",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-789",
            title="Update: GraphQL query!",
            description="Test description.",
            branch_summary="Update: GraphQL query!",
        )
        workflow_state.ticket = special_ticket

        result = _setup_branch(workflow_state, special_ticket)

        assert result is True
        # _setup_branch prepends "feature/" to ticket.branch_slug which sanitizes special chars
        expected_branch = "feature/test-789-update-graphql-query"
        assert workflow_state.branch_name == expected_branch
        mock_create.assert_called_once_with(expected_branch)

    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.create_branch")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_branch_name_with_multiple_special_chars(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state
    ):
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Create ticket with multiple special characters
        special_ticket = GenericTicket(
            id="TEST-999",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-999",
            title="Fix: API/endpoint (v2) - urgent!!!",
            description="Urgent fix needed.",
            branch_summary="Fix: API/endpoint (v2) - urgent!!!",
        )
        workflow_state.ticket = special_ticket

        result = _setup_branch(workflow_state, special_ticket)

        assert result is True
        # _setup_branch prepends "feature/" to ticket.branch_slug which sanitizes special chars
        expected_branch = "feature/test-999-fix-api-endpoint-v2-urgent"
        assert workflow_state.branch_name == expected_branch


class TestRunIngotWorkflowStep4:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_4_update_docs")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_calls_step_4_when_auto_update_docs_enabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step4.return_value = Step4Result(success=True)
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            auto_update_docs=True,
        )

        mock_step4.assert_called_once()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_4_update_docs")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_skips_step_4_when_auto_update_docs_disabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            auto_update_docs=False,
        )

        mock_step4.assert_not_called()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_4_update_docs")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_step_4_failure_does_not_fail_workflow(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        # Step 4 result with error (non-blocking)
        mock_step4.return_value = Step4Result(success=True, error_message="Agent failed")
        mock_step5.return_value = Step5Result()

        result = run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            auto_update_docs=True,
        )

        # Workflow should still succeed even if step 4 has issues
        assert result is True
        mock_completion.assert_called_once()


class TestRunIngotWorkflowStep5:
    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_calls_step_5_when_auto_commit_enabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            auto_commit=True,
        )

        mock_step5.assert_called_once()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_skips_step_5_when_auto_commit_disabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
            auto_commit=False,
        )

        mock_step5.assert_not_called()

    @patch("ingot.workflow.runner._show_completion")
    @patch("ingot.workflow.runner.step_5_commit")
    @patch("ingot.workflow.runner.step_3_execute")
    @patch("ingot.workflow.runner.step_2_create_tasklist")
    @patch("ingot.workflow.runner.step_1_create_plan")
    @patch("ingot.workflow.runner.get_current_commit")
    @patch("ingot.workflow.runner._setup_branch")
    @patch("ingot.workflow.runner.prompt_confirm")
    @patch("ingot.workflow.runner.is_dirty")
    @patch("ingot.workflow.runner.get_current_branch")
    def test_step_5_passes_backend(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step5,
        mock_completion,
        mock_backend,
        ticket,
        mock_config,
    ):
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step5.return_value = Step5Result()

        run_ingot_workflow(
            ticket=ticket,
            config=mock_config,
            backend=mock_backend,
        )

        mock_step5.assert_called_once()
        call_kwargs = mock_step5.call_args[1]
        assert call_kwargs["backend"] is mock_backend


class TestDetectContextConflict:
    def test_returns_false_when_user_context_empty(self, ticket, workflow_state):
        mock_auggie = MagicMock()

        result = _detect_context_conflict(ticket, "", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_returns_false_when_user_context_whitespace_only(self, ticket, workflow_state):
        mock_auggie = MagicMock()

        result = _detect_context_conflict(ticket, "   \n\t  ", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_returns_false_when_no_ticket_info(self, workflow_state):
        empty_ticket = GenericTicket(
            id="TEST-999",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-999",
            title="",
            description="",
            branch_summary="",
        )
        mock_auggie = MagicMock()

        result = _detect_context_conflict(empty_ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_calls_auggie_with_correct_prompt(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: NO\nSUMMARY: No conflicts detected.",
        )

        _detect_context_conflict(ticket, "Additional context here", mock_auggie, workflow_state)

        mock_auggie.run_with_callback.assert_called_once()
        call_args = mock_auggie.run_with_callback.call_args
        prompt = call_args[0][0]

        assert "Test Feature" in prompt  # ticket title
        assert "Test description for the feature implementation" in prompt  # ticket description
        assert "Additional context here" in prompt  # user context
        assert "CONFLICT:" in prompt  # expected response format

    def test_calls_auggie_with_no_subagent(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: NO\nSUMMARY: No conflicts detected.",
        )

        _detect_context_conflict(ticket, "Additional context here", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert call_kwargs["subagent"] is None

    def test_detects_conflict_when_llm_returns_yes(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: YES\nSUMMARY: The ticket says add X but user says remove X.",
        )

        result = _detect_context_conflict(ticket, "Remove feature X", mock_auggie, workflow_state)

        assert result[0] is True
        assert "add X but user says remove X" in result[1]

    def test_no_conflict_when_llm_returns_no(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: NO\nSUMMARY: No conflicts detected.",
        )

        result = _detect_context_conflict(
            ticket, "Extra implementation notes", mock_auggie, workflow_state
        )

        assert result == (False, "")

    def test_handles_auggie_failure_gracefully(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (False, "")

        result = _detect_context_conflict(ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")

    def test_handles_auggie_exception_gracefully(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.side_effect = Exception("API error")

        result = _detect_context_conflict(ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")

    def test_uses_silent_callback(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: NO\nSUMMARY: None.")

        _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert "output_callback" in call_kwargs
        # Callback should be callable and do nothing
        callback = call_kwargs["output_callback"]
        callback("test line")  # Should not raise

    def test_uses_dont_save_session(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: NO\nSUMMARY: None.")

        _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert call_kwargs["dont_save_session"] is True

    def test_handles_conflict_yes_without_summary(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: YES")

        result = _detect_context_conflict(ticket, "Conflicting info", mock_auggie, workflow_state)

        assert result[0] is True
        assert "conflict detected" in result[1].lower()

    def test_handles_lowercase_conflict_response(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "conflict: yes\nsummary: Scope mismatch detected.",
        )

        result = _detect_context_conflict(ticket, "Wrong scope", mock_auggie, workflow_state)

        assert result[0] is True
        assert "Scope mismatch" in result[1]

    def test_handles_multiline_summary(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: YES\nSUMMARY: The ticket requires adding feature X.\nHowever, user context says to remove it.",
        )

        result = _detect_context_conflict(ticket, "Remove feature X", mock_auggie, workflow_state)

        assert result[0] is True
        # Should capture the full multi-line summary
        assert "adding feature X" in result[1]
        assert "remove it" in result[1]

    def test_handles_whitespace_in_conflict_response(self, ticket, workflow_state):
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT:   YES\nSUMMARY:   Conflict found.",
        )

        result = _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        assert result[0] is True
        assert "Conflict found" in result[1]
