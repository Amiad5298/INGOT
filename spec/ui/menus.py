"""Interactive menus for SPEC.

This module provides menu functions for the main menu, task review,
git dirty state handling, and model selection.
"""

from enum import Enum

import questionary

from spec.integrations.auggie import list_models
from spec.integrations.git import DirtyStateAction
from spec.ui.prompts import custom_style
from spec.utils.console import console, print_header, print_info
from spec.utils.errors import UserCancelledError
from spec.utils.logging import log_message


class MainMenuChoice(Enum):
    """Main menu choices."""

    START_WORKFLOW = "start"
    CONFIGURE = "configure"
    SHOW_CONFIG = "show_config"
    HELP = "help"
    QUIT = "quit"


def show_main_menu() -> MainMenuChoice:
    """Display main menu and get user choice.

    Returns:
        Selected MainMenuChoice

    Raises:
        UserCancelledError: If user cancels
    """
    print_header("Main Menu")

    choices = [
        questionary.Choice("Start AI-Assisted Workflow", value=MainMenuChoice.START_WORKFLOW),
        questionary.Choice("Configure Settings", value=MainMenuChoice.CONFIGURE),
        questionary.Choice("Show Current Configuration", value=MainMenuChoice.SHOW_CONFIG),
        questionary.Choice("Help", value=MainMenuChoice.HELP),
        questionary.Choice("Quit", value=MainMenuChoice.QUIT),
    ]

    try:
        result = questionary.select(
            "What would you like to do?",
            choices=choices,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled main menu")

        log_message(f"Main menu selection: {result.value}")
        # Cast to expected type since questionary returns Any
        return MainMenuChoice(result.value)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


class TaskReviewChoice(Enum):
    """Task review menu choices."""

    APPROVE = "approve"
    REGENERATE = "regenerate"
    EDIT = "edit"
    ABORT = "abort"


def show_task_review_menu() -> TaskReviewChoice:
    """Display task review menu.

    Returns:
        Selected TaskReviewChoice

    Raises:
        UserCancelledError: If user cancels
    """
    choices = [
        questionary.Choice("Approve task list and continue", value=TaskReviewChoice.APPROVE),
        questionary.Choice("Regenerate task list", value=TaskReviewChoice.REGENERATE),
        questionary.Choice("Edit task list manually", value=TaskReviewChoice.EDIT),
        questionary.Choice("Abort workflow", value=TaskReviewChoice.ABORT),
    ]

    try:
        result = questionary.select(
            "Review the task list above. What would you like to do?",
            choices=choices,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled task review")

        log_message(f"Task review selection: {result.value}")
        # Cast to expected type since questionary returns Any
        return TaskReviewChoice(result.value)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def show_git_dirty_menu(context: str) -> DirtyStateAction:
    """Display menu for handling uncommitted changes.

    Args:
        context: Description of pending operation

    Returns:
        Selected DirtyStateAction

    Raises:
        UserCancelledError: If user cancels
    """
    print_info(f"You have uncommitted changes before: {context}")
    console.print()

    choices = [
        questionary.Choice("Stash changes (recommended)", value=DirtyStateAction.STASH),
        questionary.Choice("Commit changes", value=DirtyStateAction.COMMIT),
        questionary.Choice("Discard changes (DANGEROUS)", value=DirtyStateAction.DISCARD),
        questionary.Choice("Continue anyway (not recommended)", value=DirtyStateAction.CONTINUE),
        questionary.Choice("Abort", value=DirtyStateAction.ABORT),
    ]

    try:
        result = questionary.select(
            "How would you like to handle uncommitted changes?",
            choices=choices,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled dirty state menu")

        log_message(f"Dirty state selection: {result.value}")
        # Cast to expected type since questionary returns Any
        return DirtyStateAction(result.value)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def show_model_selection(
    current_model: str = "",
    purpose: str = "default",
) -> str | None:
    """Display model selection menu.

    Args:
        current_model: Currently selected model
        purpose: Purpose description (e.g., "planning", "implementation")

    Returns:
        Selected model ID or None if cancelled

    Raises:
        UserCancelledError: If user cancels
    """
    print_header(f"Select Model for {purpose.title()}")

    models = list_models()

    if not models:
        print_info("Could not retrieve model list. Enter model ID manually.")
        from spec.ui.prompts import prompt_input

        return prompt_input("Enter model ID", default=current_model)

    choices = []
    for model in models:
        label = f"{model.name} [{model.id}]"
        if model.id == current_model:
            label += " (current)"
        choices.append(questionary.Choice(label, value=model.id))

    choices.append(questionary.Choice("Keep current / Skip", value=None))

    try:
        result = questionary.select(
            f"Select model for {purpose}:",
            choices=choices,
            style=custom_style,
        ).ask()

        if result is None:
            return current_model or None

        log_message(f"Model selection for {purpose}: {result}")
        return str(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def show_task_checkboxes(
    tasks: list[str],
    completed: list[str] | None = None,
) -> list[str]:
    """Display task checkboxes for selection.

    Args:
        tasks: List of task names
        completed: List of already completed tasks

    Returns:
        List of selected task names

    Raises:
        UserCancelledError: If user cancels
    """
    completed = completed or []

    choices = []
    for task in tasks:
        is_done = task in completed
        choices.append(
            questionary.Choice(
                task,
                checked=is_done,
                disabled="(completed)" if is_done else None,
            )
        )

    try:
        result = questionary.checkbox(
            "Select tasks to mark as complete:",
            choices=choices,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled task selection")

        log_message(f"Tasks selected: {result}")
        return list(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


__all__ = [
    "MainMenuChoice",
    "TaskReviewChoice",
    "show_main_menu",
    "show_task_review_menu",
    "show_git_dirty_menu",
    "show_model_selection",
    "show_task_checkboxes",
]

