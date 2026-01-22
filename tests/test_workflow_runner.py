"""Tests for spec.workflow.runner module."""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.jira import JiraTicket
from spec.utils.errors import SpecError, UserCancelledError
from spec.workflow.conflict_detection import _detect_context_conflict
from spec.workflow.runner import (
    _offer_cleanup,
    _setup_branch,
    _show_completion,
    run_spec_driven_workflow,
    workflow_cleanup,
)
from spec.workflow.state import WorkflowState
from spec.workflow.step4_update_docs import Step4Result


@pytest.fixture
def ticket():
    """Create a test ticket."""
    return JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description for the feature implementation.",
        summary="test-feature-summary",
    )


@pytest.fixture
def ticket_no_summary():
    """Create a test ticket without summary."""
    return JiraTicket(
        ticket_id="TEST-456",
        ticket_url="https://jira.example.com/TEST-456",
        title="Test Feature No Summary",
        description="Test description.",
        summary="",
    )


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


# =============================================================================
# Tests for _setup_branch() - Branch name generation
# =============================================================================


class TestSetupBranchNameGeneration:
    """Tests for _setup_branch branch name generation."""

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_generates_branch_name_with_summary(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        """Generates branch name with summary format: {ticket_id}-{summary}."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        assert workflow_state.branch_name == "test-123-test-feature-summary"

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_generates_fallback_branch_name_without_summary(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket_no_summary
    ):
        """Generates fallback format feature/{ticket_id} when no summary available."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Update workflow_state with no-summary ticket
        workflow_state.ticket = ticket_no_summary

        result = _setup_branch(workflow_state, ticket_no_summary)

        assert result is True
        assert workflow_state.branch_name == "feature/test-456"


# =============================================================================
# Tests for _setup_branch() - Already on feature branch
# =============================================================================


class TestSetupBranchAlreadyOnFeature:
    """Tests for _setup_branch when already on feature branch."""

    @patch("spec.workflow.runner.get_current_branch")
    def test_stays_on_current_branch_if_already_on_feature_branch(
        self, mock_get_branch, workflow_state, ticket
    ):
        """Stays on current branch if already on the expected feature branch."""
        expected_branch = "test-123-test-feature-summary"
        mock_get_branch.return_value = expected_branch

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        assert workflow_state.branch_name == expected_branch

    @patch("spec.workflow.runner.get_current_branch")
    def test_updates_state_branch_name_correctly(self, mock_get_branch, workflow_state, ticket):
        """Updates state.branch_name correctly when already on branch."""
        expected_branch = "test-123-test-feature-summary"
        mock_get_branch.return_value = expected_branch

        _setup_branch(workflow_state, ticket)

        assert workflow_state.branch_name == expected_branch


# =============================================================================
# Tests for _setup_branch() - Create new branch
# =============================================================================


class TestSetupBranchCreateNew:
    """Tests for _setup_branch creating new branch."""

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_creates_new_branch_when_user_confirms(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        """Creates new branch when user confirms."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True
        mock_create.assert_called_once_with("test-123-test-feature-summary")

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_true_on_successful_branch_creation(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        """Returns True on successful branch creation."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        result = _setup_branch(workflow_state, ticket)

        assert result is True

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_false_on_branch_creation_failure(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state, ticket
    ):
        """Returns False on branch creation failure."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = False  # Branch creation fails

        result = _setup_branch(workflow_state, ticket)

        assert result is False


# =============================================================================
# Tests for _setup_branch() - User declines
# =============================================================================


class TestSetupBranchUserDeclines:
    """Tests for _setup_branch when user declines branch creation."""

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.get_current_branch")
    def test_stays_on_current_branch_when_user_declines(
        self, mock_get_branch, mock_confirm, workflow_state, ticket
    ):
        """Stays on current branch when user declines."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = False  # User declines

        result = _setup_branch(workflow_state, ticket)

        assert result is True

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.get_current_branch")
    def test_updates_state_branch_name_to_current_branch(
        self, mock_get_branch, mock_confirm, workflow_state, ticket
    ):
        """Updates state.branch_name to current branch when user declines."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = False  # User declines

        _setup_branch(workflow_state, ticket)

        assert workflow_state.branch_name == "main"


# =============================================================================
# Tests for _show_completion()
# =============================================================================


class TestShowCompletion:
    """Tests for _show_completion function."""

    @patch("spec.workflow.runner.console")
    def test_displays_ticket_id(self, mock_console, workflow_state):
        """Displays ticket ID."""
        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("TEST-123" in c for c in calls)

    @patch("spec.workflow.runner.console")
    def test_displays_branch_name(self, mock_console, workflow_state):
        """Displays branch name."""
        workflow_state.branch_name = "feature/test-branch"

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("feature/test-branch" in c for c in calls)

    @patch("spec.workflow.runner.console")
    def test_displays_completed_task_count(self, mock_console, workflow_state):
        """Displays completed task count."""
        workflow_state.completed_tasks = ["Task 1", "Task 2", "Task 3"]

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("3" in c for c in calls)

    @patch("spec.workflow.runner.console")
    def test_displays_plan_file_if_exists(self, mock_console, workflow_state, tmp_path):
        """Displays plan file if exists."""
        plan_path = tmp_path / "specs" / "TEST-123-plan.md"
        workflow_state.plan_file = plan_path

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Plan" in c for c in calls)

    @patch("spec.workflow.runner.console")
    def test_displays_tasklist_file_if_exists(self, mock_console, workflow_state, tmp_path):
        """Displays tasklist file if exists."""
        tasklist_path = tmp_path / "specs" / "TEST-123-tasklist.md"
        workflow_state.tasklist_file = tasklist_path

        _show_completion(workflow_state)

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Tasks" in c for c in calls)

    @patch("spec.workflow.runner.print_info")
    @patch("spec.workflow.runner.console")
    def test_prints_next_steps(self, mock_console, mock_print_info, workflow_state):
        """Prints next steps."""
        _show_completion(workflow_state)

        calls = [str(c) for c in mock_print_info.call_args_list]
        assert any("Next steps" in c for c in calls)
        assert any("Review" in c for c in calls)
        assert any("pytest" in c for c in calls)


# =============================================================================
# Tests for workflow_cleanup() context manager - Normal execution
# =============================================================================


class TestWorkflowCleanupNormal:
    """Tests for workflow_cleanup context manager normal execution."""

    @patch("spec.workflow.runner.get_current_branch")
    def test_yields_normally_on_success(self, mock_get_branch, workflow_state):
        """Yields normally and completes without error on success path."""
        mock_get_branch.return_value = "main"

        executed = False
        with workflow_cleanup(workflow_state):
            executed = True

        assert executed is True


# =============================================================================
# Tests for workflow_cleanup() context manager - UserCancelledError
# =============================================================================


class TestWorkflowCleanupUserCancelled:
    """Tests for workflow_cleanup handling UserCancelledError."""

    @patch("spec.workflow.runner._offer_cleanup")
    @patch("spec.workflow.runner.print_info")
    @patch("spec.workflow.runner.get_current_branch")
    def test_catches_user_cancelled_error(
        self, mock_get_branch, mock_print_info, mock_offer_cleanup, workflow_state
    ):
        """Catches UserCancelledError, prints info, calls _offer_cleanup, then re-raises."""
        mock_get_branch.return_value = "main"

        with pytest.raises(UserCancelledError):
            with workflow_cleanup(workflow_state):
                raise UserCancelledError("User cancelled")

        mock_print_info.assert_called()
        mock_offer_cleanup.assert_called_once()


# =============================================================================
# Tests for workflow_cleanup() context manager - SpecError
# =============================================================================


class TestWorkflowCleanupSpecError:
    """Tests for workflow_cleanup handling SpecError."""

    @patch("spec.workflow.runner._offer_cleanup")
    @patch("spec.workflow.runner.print_error")
    @patch("spec.workflow.runner.get_current_branch")
    def test_catches_spec_error(
        self, mock_get_branch, mock_print_error, mock_offer_cleanup, workflow_state
    ):
        """Catches SpecError, prints error, calls _offer_cleanup, then re-raises."""
        mock_get_branch.return_value = "main"

        with pytest.raises(SpecError):
            with workflow_cleanup(workflow_state):
                raise SpecError("Workflow failed")

        mock_print_error.assert_called()
        mock_offer_cleanup.assert_called_once()


# =============================================================================
# Tests for workflow_cleanup() context manager - Generic Exception
# =============================================================================


class TestWorkflowCleanupGenericException:
    """Tests for workflow_cleanup handling generic exceptions."""

    @patch("spec.workflow.runner._offer_cleanup")
    @patch("spec.workflow.runner.print_error")
    @patch("spec.workflow.runner.get_current_branch")
    def test_catches_generic_exceptions(
        self, mock_get_branch, mock_print_error, mock_offer_cleanup, workflow_state
    ):
        """Catches generic exceptions, prints error, calls _offer_cleanup, then re-raises."""
        mock_get_branch.return_value = "main"

        with pytest.raises(RuntimeError):
            with workflow_cleanup(workflow_state):
                raise RuntimeError("Unexpected error")

        mock_print_error.assert_called()
        mock_offer_cleanup.assert_called_once()


# =============================================================================
# Tests for _offer_cleanup() - Checkpoint commits
# =============================================================================


class TestOfferCleanupCheckpointCommits:
    """Tests for _offer_cleanup checkpoint commits display."""

    @patch("spec.workflow.runner.console")
    @patch("spec.workflow.runner.print_info")
    @patch("spec.workflow.runner.print_warning")
    def test_prints_checkpoint_commit_count(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        """Prints checkpoint commit count when state.checkpoint_commits is non-empty."""
        workflow_state.checkpoint_commits = ["abc123", "def456", "ghi789"]

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        assert any("3" in c and "checkpoint" in c.lower() for c in calls)


# =============================================================================
# Tests for _offer_cleanup() - Branch information
# =============================================================================


class TestOfferCleanupBranchInfo:
    """Tests for _offer_cleanup branch information display."""

    @patch("spec.workflow.runner.console")
    @patch("spec.workflow.runner.print_info")
    @patch("spec.workflow.runner.print_warning")
    def test_prints_branch_info_when_different(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        """Prints current branch and original branch info when they differ."""
        workflow_state.branch_name = "feature/test-branch"

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        assert any("feature/test-branch" in c for c in calls)
        assert any("main" in c for c in calls)

    @patch("spec.workflow.runner.console")
    @patch("spec.workflow.runner.print_info")
    @patch("spec.workflow.runner.print_warning")
    def test_does_not_print_branch_info_when_same(
        self, mock_warning, mock_info, mock_console, workflow_state
    ):
        """Does not print branch info when they are the same."""
        workflow_state.branch_name = "main"

        _offer_cleanup(workflow_state, "main")

        calls = [str(c) for c in mock_info.call_args_list]
        # Should not have branch-related info calls when branches are the same
        assert not any("On branch" in c for c in calls)


# =============================================================================
# Tests for run_spec_driven_workflow() - Initialization
# =============================================================================


class TestRunSpecDrivenWorkflowInit:
    """Tests for run_spec_driven_workflow initialization."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_initializes_workflow_state_correctly(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that WorkflowState is initialized correctly with all parameters."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False  # No additional context
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        result = run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
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


# =============================================================================
# Tests for run_spec_driven_workflow() - Dirty state handling
# =============================================================================


class TestRunSpecDrivenWorkflowDirtyState:
    """Tests for run_spec_driven_workflow dirty state handling."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner.handle_dirty_state")
    @patch("spec.workflow.runner.show_git_dirty_menu")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_handles_dirty_state_at_start(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_menu,
        mock_handle,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that dirty state is detected and handled at start."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = True
        mock_menu.return_value = "stash"
        mock_handle.return_value = False  # Handling fails

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        assert result is False
        mock_menu.assert_called_once()
        mock_handle.assert_called_once()


# =============================================================================
# Tests for run_spec_driven_workflow() - Fetch ticket info
# =============================================================================


class TestRunSpecDrivenWorkflowFetchTicket:
    """Tests for run_spec_driven_workflow fetch ticket info."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_fetches_and_updates_ticket_info(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test successful ticket info fetch updates state.ticket."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False

        updated_ticket = JiraTicket(
            ticket_id="TEST-123",
            ticket_url="https://jira.example.com/TEST-123",
            title="Updated Title",
            description="Updated description",
        )
        mock_fetch.return_value = updated_ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        mock_fetch.assert_called_once()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner.print_warning")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_handles_fetch_ticket_info_failure_gracefully(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_warning,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test handles fetch_ticket_info failure gracefully (prints warning, continues)."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.side_effect = Exception("Jira API error")
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        # Should continue despite fetch failure
        assert result is True
        mock_warning.assert_called()


# =============================================================================
# Tests for run_spec_driven_workflow() - User context prompt
# =============================================================================


class TestRunSpecDrivenWorkflowUserContext:
    """Tests for run_spec_driven_workflow user context prompt."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_input")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_stores_user_context_when_confirmed(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_input,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test prompts for additional user context and stores it in state."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.side_effect = [True, True]  # Add context, then other prompts
        mock_input.return_value = "Additional implementation details"
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        mock_input.assert_called_once()
        # Verify state received the context
        call_args = mock_step1.call_args[0]
        state = call_args[0]
        assert state.user_context == "Additional implementation details"


# =============================================================================
# Tests for run_spec_driven_workflow() - Branch setup and base commit
# =============================================================================


class TestRunSpecDrivenWorkflowBranchSetup:
    """Tests for run_spec_driven_workflow branch setup and base commit."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_records_base_commit(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test records base commit via get_current_commit."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123def456"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        mock_commit.assert_called_once()
        call_args = mock_step1.call_args[0]
        state = call_args[0]
        assert state.base_commit == "abc123def456"

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_false_when_branch_setup_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test returns False when branch setup fails."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = False  # Branch setup fails

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        assert result is False


# =============================================================================
# Tests for run_spec_driven_workflow() - Step orchestration
# =============================================================================


class TestRunSpecDrivenWorkflowStepOrchestration:
    """Tests for run_spec_driven_workflow step orchestration."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_calls_all_steps_in_sequence(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test calls step_1, step_2, step_3 in sequence."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        mock_step1.assert_called_once()
        mock_step2.assert_called_once()
        mock_step3.assert_called_once()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_false_when_step1_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test returns False when step_1 fails."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = False  # Step 1 fails

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        assert result is False
        mock_step2.assert_not_called()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_false_when_step2_fails(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test returns False when step_2 fails."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = False  # Step 2 fails

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        assert result is False
        mock_step3.assert_not_called()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_returns_true_when_all_steps_succeed(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test returns True when all steps succeed."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        result = run_spec_driven_workflow(ticket=ticket, config=mock_config)

        assert result is True


# =============================================================================
# Tests for run_spec_driven_workflow() - Completion
# =============================================================================


class TestRunSpecDrivenWorkflowCompletion:
    """Tests for run_spec_driven_workflow completion."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_shows_completion_on_success(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test shows completion via _show_completion on success."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        mock_completion.assert_called_once()


# =============================================================================
# Tests for run_spec_driven_workflow() - Step 3 Arguments (use_tui, verbose)
# =============================================================================


class TestRunSpecDrivenWorkflowStep3Arguments:
    """Tests for run_spec_driven_workflow passing correct arguments to step_3_execute."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_passes_use_tui_and_verbose_to_step_3_execute(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that use_tui and verbose are passed correctly to step_3_execute."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
            use_tui=True,
            verbose=True,
        )

        # Verify step_3_execute was called with correct keyword arguments
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is True
        assert call_kwargs["verbose"] is True

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_passes_use_tui_false_and_verbose_false_to_step_3_execute(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that use_tui=False and verbose=False are passed correctly."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
            use_tui=False,
            verbose=False,
        )

        # Verify step_3_execute was called with correct keyword arguments
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is False
        assert call_kwargs["verbose"] is False

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_passes_use_tui_none_for_auto_detection(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that use_tui=None is passed for auto-detection mode."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        # Call without specifying use_tui (defaults to None)
        run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
        )

        # Verify step_3_execute was called with use_tui=None
        mock_step3.assert_called_once()
        call_kwargs = mock_step3.call_args[1]
        assert call_kwargs["use_tui"] is None
        assert call_kwargs["verbose"] is False


# =============================================================================
# Tests for run_spec_driven_workflow() - Resume Logic (Step Skipping)
# =============================================================================


class TestRunSpecDrivenWorkflowResumeLogic:
    """Tests for run_spec_driven_workflow resume logic based on current_step."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    @patch("spec.workflow.runner.WorkflowState")
    def test_skips_step_1_when_current_step_is_2(
        self,
        mock_state_class,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that step_1 is skipped when state.current_step = 2."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        # Create a mock state with current_step = 2
        mock_state = MagicMock()
        mock_state.current_step = 2
        mock_state.ticket = ticket
        mock_state_class.return_value = mock_state

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        # Step 1 should NOT be called because current_step > 1
        mock_step1.assert_not_called()
        # Step 2 and 3 should be called
        mock_step2.assert_called_once()
        mock_step3.assert_called_once()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    @patch("spec.workflow.runner.WorkflowState")
    def test_skips_step_1_and_step_2_when_current_step_is_3(
        self,
        mock_state_class,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that step_1 and step_2 are skipped when state.current_step = 3."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        # Create a mock state with current_step = 3
        mock_state = MagicMock()
        mock_state.current_step = 3
        mock_state.ticket = ticket
        mock_state_class.return_value = mock_state

        run_spec_driven_workflow(ticket=ticket, config=mock_config)

        # Step 1 and 2 should NOT be called because current_step > 2
        mock_step1.assert_not_called()
        mock_step2.assert_not_called()
        # Only Step 3 should be called
        mock_step3.assert_called_once()


# =============================================================================
# Tests for _setup_branch() - Branch name with special characters
# =============================================================================


class TestSetupBranchSpecialCharacters:
    """Tests for _setup_branch with special characters in ticket summary."""

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_branch_name_with_spaces_and_special_chars(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state
    ):
        """Test branch name generation with spaces and special characters in summary."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Create ticket with special characters in summary
        special_ticket = JiraTicket(
            ticket_id="TEST-789",
            ticket_url="https://jira.example.com/TEST-789",
            title="Update: GraphQL query!",
            description="Test description.",
            summary="Update: GraphQL query!",
        )
        workflow_state.ticket = special_ticket

        result = _setup_branch(workflow_state, special_ticket)

        assert result is True
        # The branch name should be generated with the raw summary
        # (no sanitization exists yet per the ticket description)
        expected_branch = "test-789-Update: GraphQL query!"
        assert workflow_state.branch_name == expected_branch
        mock_create.assert_called_once_with(expected_branch)

    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.create_branch")
    @patch("spec.workflow.runner.get_current_branch")
    def test_branch_name_with_multiple_special_chars(
        self, mock_get_branch, mock_create, mock_confirm, workflow_state
    ):
        """Test branch name with multiple special characters."""
        mock_get_branch.return_value = "main"
        mock_confirm.return_value = True
        mock_create.return_value = True

        # Create ticket with multiple special characters
        special_ticket = JiraTicket(
            ticket_id="TEST-999",
            ticket_url="https://jira.example.com/TEST-999",
            title="Fix: API/endpoint (v2) - urgent!!!",
            description="Urgent fix needed.",
            summary="Fix: API/endpoint (v2) - urgent!!!",
        )
        workflow_state.ticket = special_ticket

        result = _setup_branch(workflow_state, special_ticket)

        assert result is True
        # Raw string formatting (no sanitization)
        expected_branch = "test-999-Fix: API/endpoint (v2) - urgent!!!"
        assert workflow_state.branch_name == expected_branch


# =============================================================================
# Tests for run_spec_driven_workflow() - Step 4 (Documentation Updates)
# =============================================================================


class TestRunSpecDrivenWorkflowStep4:
    """Tests for run_spec_driven_workflow Step 4 documentation updates."""

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_4_update_docs")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_calls_step_4_when_auto_update_docs_enabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that step_4_update_docs is called when auto_update_docs=True."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        mock_step4.return_value = Step4Result(success=True)

        run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
            auto_update_docs=True,
        )

        mock_step4.assert_called_once()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_4_update_docs")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_skips_step_4_when_auto_update_docs_disabled(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that step_4_update_docs is NOT called when auto_update_docs=False."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True

        run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
            auto_update_docs=False,
        )

        mock_step4.assert_not_called()

    @patch("spec.workflow.runner.AuggieClient")
    @patch("spec.workflow.runner._show_completion")
    @patch("spec.workflow.runner.step_4_update_docs")
    @patch("spec.workflow.runner.step_3_execute")
    @patch("spec.workflow.runner.step_2_create_tasklist")
    @patch("spec.workflow.runner.step_1_create_plan")
    @patch("spec.workflow.runner.get_current_commit")
    @patch("spec.workflow.runner._setup_branch")
    @patch("spec.workflow.runner.prompt_confirm")
    @patch("spec.workflow.runner.fetch_ticket_info")
    @patch("spec.workflow.runner.is_dirty")
    @patch("spec.workflow.runner.get_current_branch")
    def test_step_4_failure_does_not_fail_workflow(
        self,
        mock_get_branch,
        mock_is_dirty,
        mock_fetch,
        mock_confirm,
        mock_setup_branch,
        mock_commit,
        mock_step1,
        mock_step2,
        mock_step3,
        mock_step4,
        mock_completion,
        mock_auggie_client,
        ticket,
        mock_config,
    ):
        """Test that step_4 failure does not fail the overall workflow."""
        mock_get_branch.return_value = "main"
        mock_is_dirty.return_value = False
        mock_fetch.return_value = ticket
        mock_confirm.return_value = False
        mock_setup_branch.return_value = True
        mock_commit.return_value = "abc123"
        mock_step1.return_value = True
        mock_step2.return_value = True
        mock_step3.return_value = True
        # Step 4 result with error (non-blocking)
        mock_step4.return_value = Step4Result(success=True, error_message="Agent failed")

        result = run_spec_driven_workflow(
            ticket=ticket,
            config=mock_config,
            auto_update_docs=True,
        )

        # Workflow should still succeed even if step 4 has issues
        assert result is True
        mock_completion.assert_called_once()


# =============================================================================
# Tests for _detect_context_conflict()
# =============================================================================


class TestDetectContextConflict:
    """Tests for _detect_context_conflict function."""

    def test_returns_false_when_user_context_empty(self, ticket, workflow_state):
        """Returns (False, '') when user_context is empty."""
        mock_auggie = MagicMock()

        result = _detect_context_conflict(ticket, "", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_returns_false_when_user_context_whitespace_only(self, ticket, workflow_state):
        """Returns (False, '') when user_context is only whitespace."""
        mock_auggie = MagicMock()

        result = _detect_context_conflict(ticket, "   \n\t  ", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_returns_false_when_no_ticket_info(self, workflow_state):
        """Returns (False, '') when ticket has no title or description."""
        empty_ticket = JiraTicket(
            ticket_id="TEST-999",
            ticket_url="TEST-999",
            title="",
            description="",
        )
        mock_auggie = MagicMock()

        result = _detect_context_conflict(empty_ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")
        mock_auggie.run_with_callback.assert_not_called()

    def test_calls_auggie_with_correct_prompt(self, ticket, workflow_state):
        """Calls Auggie with prompt containing ticket info and user context."""
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

    def test_calls_auggie_with_planner_agent(self, ticket, workflow_state):
        """Calls Auggie with the planner subagent for conflict detection."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: NO\nSUMMARY: No conflicts detected.",
        )

        _detect_context_conflict(ticket, "Additional context here", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert call_kwargs["agent"] == workflow_state.subagent_names["planner"]

    def test_detects_conflict_when_llm_returns_yes(self, ticket, workflow_state):
        """Returns (True, summary) when LLM detects conflict."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT: YES\nSUMMARY: The ticket says add X but user says remove X.",
        )

        result = _detect_context_conflict(ticket, "Remove feature X", mock_auggie, workflow_state)

        assert result[0] is True
        assert "add X but user says remove X" in result[1]

    def test_no_conflict_when_llm_returns_no(self, ticket, workflow_state):
        """Returns (False, '') when LLM detects no conflict."""
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
        """Returns (False, '') when Auggie call fails."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (False, "")

        result = _detect_context_conflict(ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")

    def test_handles_auggie_exception_gracefully(self, ticket, workflow_state):
        """Returns (False, '') when Auggie raises exception."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.side_effect = Exception("API error")

        result = _detect_context_conflict(ticket, "Some context", mock_auggie, workflow_state)

        assert result == (False, "")

    def test_uses_silent_callback(self, ticket, workflow_state):
        """Uses a no-op callback to avoid printing to console."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: NO\nSUMMARY: None.")

        _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert "output_callback" in call_kwargs
        # Callback should be callable and do nothing
        callback = call_kwargs["output_callback"]
        callback("test line")  # Should not raise

    def test_uses_dont_save_session(self, ticket, workflow_state):
        """Uses dont_save_session=True for lightweight call."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: NO\nSUMMARY: None.")

        _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        call_kwargs = mock_auggie.run_with_callback.call_args[1]
        assert call_kwargs["dont_save_session"] is True

    def test_handles_conflict_yes_without_summary(self, ticket, workflow_state):
        """Provides default summary when LLM returns YES but no summary."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (True, "CONFLICT: YES")

        result = _detect_context_conflict(ticket, "Conflicting info", mock_auggie, workflow_state)

        assert result[0] is True
        assert "conflict detected" in result[1].lower()

    def test_handles_lowercase_conflict_response(self, ticket, workflow_state):
        """Handles lowercase 'conflict: yes' response."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "conflict: yes\nsummary: Scope mismatch detected.",
        )

        result = _detect_context_conflict(ticket, "Wrong scope", mock_auggie, workflow_state)

        assert result[0] is True
        assert "Scope mismatch" in result[1]

    def test_handles_multiline_summary(self, ticket, workflow_state):
        """Handles multi-line summary in LLM response."""
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
        """Handles extra whitespace in CONFLICT: YES response."""
        mock_auggie = MagicMock()
        mock_auggie.run_with_callback.return_value = (
            True,
            "CONFLICT:   YES\nSUMMARY:   Conflict found.",
        )

        result = _detect_context_conflict(ticket, "Context", mock_auggie, workflow_state)

        assert result[0] is True
        assert "Conflict found" in result[1]
