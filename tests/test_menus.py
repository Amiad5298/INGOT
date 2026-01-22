"""Tests for spec.ui.menus module."""

from unittest.mock import patch

import pytest

from spec.integrations.git import DirtyStateAction
from spec.ui.menus import (
    MainMenuChoice,
    TaskReviewChoice,
    show_git_dirty_menu,
    show_main_menu,
    show_model_selection,
    show_task_checkboxes,
    show_task_review_menu,
)
from spec.utils.errors import UserCancelledError


class TestMainMenuChoice:
    """Tests for MainMenuChoice enum."""

    def test_has_start_workflow(self):
        """Has START_WORKFLOW choice."""
        assert MainMenuChoice.START_WORKFLOW.value == "start"

    def test_has_configure(self):
        """Has CONFIGURE choice."""
        assert MainMenuChoice.CONFIGURE.value == "configure"

    def test_has_quit(self):
        """Has QUIT choice."""
        assert MainMenuChoice.QUIT.value == "quit"


class TestTaskReviewChoice:
    """Tests for TaskReviewChoice enum."""

    def test_has_approve(self):
        """Has APPROVE choice."""
        assert TaskReviewChoice.APPROVE.value == "approve"

    def test_has_regenerate(self):
        """Has REGENERATE choice."""
        assert TaskReviewChoice.REGENERATE.value == "regenerate"

    def test_has_abort(self):
        """Has ABORT choice."""
        assert TaskReviewChoice.ABORT.value == "abort"


class TestShowMainMenu:
    """Tests for show_main_menu function."""

    @patch("spec.ui.menus.print_header")
    @patch("questionary.select")
    def test_returns_selection(self, mock_select, mock_header):
        """Returns selected choice."""
        mock_select.return_value.ask.return_value = MainMenuChoice.START_WORKFLOW

        result = show_main_menu()

        assert result == MainMenuChoice.START_WORKFLOW

    @patch("spec.ui.menus.print_header")
    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select, mock_header):
        """Raises UserCancelledError when cancelled."""
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_main_menu()


class TestShowTaskReviewMenu:
    """Tests for show_task_review_menu function."""

    @patch("questionary.select")
    def test_returns_selection(self, mock_select):
        """Returns selected choice."""
        mock_select.return_value.ask.return_value = TaskReviewChoice.APPROVE

        result = show_task_review_menu()

        assert result == TaskReviewChoice.APPROVE

    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select):
        """Raises UserCancelledError when cancelled."""
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_task_review_menu()


class TestShowGitDirtyMenu:
    """Tests for show_git_dirty_menu function."""

    @patch("spec.ui.menus.print_info")
    @patch("spec.ui.menus.console")
    @patch("questionary.select")
    def test_returns_stash(self, mock_select, mock_console, mock_info):
        """Returns STASH action."""
        mock_select.return_value.ask.return_value = DirtyStateAction.STASH

        result = show_git_dirty_menu("branch switch")

        assert result == DirtyStateAction.STASH

    @patch("spec.ui.menus.print_info")
    @patch("spec.ui.menus.console")
    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select, mock_console, mock_info):
        """Raises UserCancelledError when cancelled."""
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_git_dirty_menu("branch switch")


class TestShowModelSelection:
    """Tests for show_model_selection function."""

    @patch("spec.ui.menus.print_header")
    @patch("spec.ui.menus.list_models")
    @patch("questionary.select")
    def test_returns_selected_model(self, mock_select, mock_list, mock_header):
        """Returns selected model ID."""
        from spec.integrations.auggie import AuggieModel

        mock_list.return_value = [
            AuggieModel(name="Claude 3", id="claude-3"),
            AuggieModel(name="GPT-4", id="gpt-4"),
        ]
        mock_select.return_value.ask.return_value = "claude-3"

        result = show_model_selection()

        assert result == "claude-3"

    @patch("spec.ui.menus.print_header")
    @patch("spec.ui.menus.list_models")
    @patch("spec.ui.menus.print_info")
    @patch("spec.ui.prompts.prompt_input")
    def test_prompts_manual_input_when_no_models(
        self, mock_input, mock_info, mock_list, mock_header
    ):
        """Prompts for manual input when model list is empty."""
        mock_list.return_value = []
        mock_input.return_value = "custom-model"

        result = show_model_selection()

        assert result == "custom-model"


class TestShowTaskCheckboxes:
    """Tests for show_task_checkboxes function."""

    @patch("questionary.checkbox")
    def test_returns_selected_tasks(self, mock_checkbox):
        """Returns list of selected tasks."""
        mock_checkbox.return_value.ask.return_value = ["Task 1", "Task 3"]

        result = show_task_checkboxes(["Task 1", "Task 2", "Task 3"])

        assert result == ["Task 1", "Task 3"]

    @patch("questionary.checkbox")
    def test_raises_on_cancel(self, mock_checkbox):
        """Raises UserCancelledError when cancelled."""
        mock_checkbox.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_task_checkboxes(["Task 1", "Task 2"])

