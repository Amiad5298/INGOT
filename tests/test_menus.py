"""Tests for ingot.ui.menus module."""

from unittest.mock import patch

import pytest

from ingot.integrations.git import DirtyStateAction
from ingot.ui.menus import (
    MainMenuChoice,
    TaskReviewChoice,
    show_git_dirty_menu,
    show_main_menu,
    show_model_selection,
    show_task_checkboxes,
    show_task_review_menu,
)
from ingot.utils.errors import UserCancelledError


class TestMainMenuChoice:
    def test_has_start_workflow(self):
        assert MainMenuChoice.START_WORKFLOW.value == "start"

    def test_has_configure(self):
        assert MainMenuChoice.CONFIGURE.value == "configure"

    def test_has_quit(self):
        assert MainMenuChoice.QUIT.value == "quit"


class TestTaskReviewChoice:
    def test_has_approve(self):
        assert TaskReviewChoice.APPROVE.value == "approve"

    def test_has_regenerate(self):
        assert TaskReviewChoice.REGENERATE.value == "regenerate"

    def test_has_abort(self):
        assert TaskReviewChoice.ABORT.value == "abort"


class TestShowMainMenu:
    @patch("ingot.ui.menus.print_header")
    @patch("questionary.select")
    def test_returns_selection(self, mock_select, mock_header):
        mock_select.return_value.ask.return_value = MainMenuChoice.START_WORKFLOW

        result = show_main_menu()

        assert result == MainMenuChoice.START_WORKFLOW

    @patch("ingot.ui.menus.print_header")
    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select, mock_header):
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_main_menu()


class TestShowTaskReviewMenu:
    @patch("questionary.select")
    def test_returns_selection(self, mock_select):
        mock_select.return_value.ask.return_value = TaskReviewChoice.APPROVE

        result = show_task_review_menu()

        assert result == TaskReviewChoice.APPROVE

    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select):
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_task_review_menu()


class TestShowGitDirtyMenu:
    @patch("ingot.ui.menus.print_info")
    @patch("ingot.ui.menus.console")
    @patch("questionary.select")
    def test_returns_stash(self, mock_select, mock_console, mock_info):
        mock_select.return_value.ask.return_value = DirtyStateAction.STASH

        result = show_git_dirty_menu("branch switch")

        assert result == DirtyStateAction.STASH

    @patch("ingot.ui.menus.print_info")
    @patch("ingot.ui.menus.console")
    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select, mock_console, mock_info):
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_git_dirty_menu("branch switch")


class TestShowModelSelection:
    @patch("ingot.ui.menus.print_header")
    @patch("questionary.select")
    def test_returns_selected_model(self, mock_select, mock_header):
        from ingot.integrations.backends.base import BackendModel
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend(
            [],
            models=[
                BackendModel(name="Claude 3", id="claude-3"),
                BackendModel(name="GPT-4", id="gpt-4"),
            ],
        )
        mock_select.return_value.ask.return_value = "claude-3"

        result = show_model_selection(backend=backend)

        assert result == "claude-3"

    @patch("ingot.ui.menus.print_header")
    @patch("ingot.ui.menus.print_info")
    @patch("ingot.ui.prompts.prompt_input")
    def test_prompts_manual_input_when_no_backend(self, mock_input, mock_info, mock_header):
        mock_input.return_value = "custom-model"

        result = show_model_selection()

        assert result == "custom-model"

    @patch("ingot.ui.menus.print_header")
    @patch("ingot.ui.menus.print_info")
    @patch("ingot.ui.prompts.prompt_input")
    def test_prompts_manual_input_when_backend_returns_no_models(
        self, mock_input, mock_info, mock_header
    ):
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend([], models=[])
        mock_input.return_value = "custom-model"

        result = show_model_selection(backend=backend)

        assert result == "custom-model"

    @patch("ingot.ui.menus.print_header")
    @patch("questionary.select")
    @patch("ingot.ui.prompts.prompt_input")
    def test_manual_entry_choice(self, mock_input, mock_select, mock_header):
        from ingot.integrations.backends.base import BackendModel
        from tests.fakes.fake_backend import FakeBackend

        backend = FakeBackend(
            [],
            models=[BackendModel(name="Claude 3", id="claude-3")],
        )
        mock_select.return_value.ask.return_value = "__manual__"
        mock_input.return_value = "my-custom-model"

        result = show_model_selection(backend=backend)

        assert result == "my-custom-model"


class TestShowTaskCheckboxes:
    @patch("questionary.checkbox")
    def test_returns_selected_tasks(self, mock_checkbox):
        mock_checkbox.return_value.ask.return_value = ["Task 1", "Task 3"]

        result = show_task_checkboxes(["Task 1", "Task 2", "Task 3"])

        assert result == ["Task 1", "Task 3"]

    @patch("questionary.checkbox")
    def test_raises_on_cancel(self, mock_checkbox):
        mock_checkbox.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            show_task_checkboxes(["Task 1", "Task 2"])
