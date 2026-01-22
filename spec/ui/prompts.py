"""Interactive prompts for SPEC.

This module provides Questionary-based user input prompts with
consistent styling and error handling.
"""

from collections.abc import Callable

import questionary
from questionary import Style

from spec.utils.errors import UserCancelledError
from spec.utils.logging import log_message

# Custom style matching the application theme
custom_style = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:cyan"),
        ("instruction", "fg:white"),
        ("text", ""),
        ("disabled", "fg:gray italic"),
    ]
)


def prompt_confirm(
    message: str,
    default: bool = True,
    *,
    auto_enter: bool = False,
) -> bool:
    """Prompt for yes/no confirmation.

    Args:
        message: Question to ask
        default: Default value if user presses Enter
        auto_enter: If True, automatically accept default

    Returns:
        True for yes, False for no

    Raises:
        UserCancelledError: If user presses Ctrl+C
    """
    log_message(f"Prompt confirm: {message}")

    if auto_enter:
        log_message(f"Auto-enter: returning default {default}")
        return default

    try:
        result = questionary.confirm(
            message,
            default=default,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled confirmation prompt")

        log_message(f"User response: {result}")
        return bool(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def prompt_input(
    message: str,
    default: str = "",
    *,
    validate: Callable[[str], bool] | None = None,
    multiline: bool = False,
) -> str:
    """Prompt for text input.

    Args:
        message: Prompt message
        default: Default value
        validate: Optional validation function
        multiline: Allow multiline input

    Returns:
        User input string

    Raises:
        UserCancelledError: If user presses Ctrl+C
    """
    log_message(f"Prompt input: {message}")

    try:
        result = questionary.text(
            message,
            default=default,
            validate=validate,
            multiline=multiline,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled input prompt")

        log_message(f"User input: {result[:50]}...")
        return str(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def prompt_enter(message: str = "Press Enter to continue...") -> None:
    """Wait for user to press Enter.

    Args:
        message: Message to display

    Raises:
        UserCancelledError: If user presses Ctrl+C
    """
    log_message(f"Prompt enter: {message}")

    try:
        questionary.press_any_key_to_continue(
            message,
            style=custom_style,
        ).ask()
    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def prompt_select(
    message: str,
    choices: list[str],
    default: str | None = None,
) -> str:
    """Prompt for single selection from list.

    Args:
        message: Prompt message
        choices: List of choices
        default: Default selection

    Returns:
        Selected choice

    Raises:
        UserCancelledError: If user presses Ctrl+C
    """
    log_message(f"Prompt select: {message}")

    try:
        result = questionary.select(
            message,
            choices=choices,
            default=default,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled selection prompt")

        log_message(f"User selected: {result}")
        return str(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


def prompt_checkbox(
    message: str,
    choices: list[str],
    default: list[str] | None = None,
) -> list[str]:
    """Prompt for multiple selections from list.

    Args:
        message: Prompt message
        choices: List of choices
        default: Default selections

    Returns:
        List of selected choices

    Raises:
        UserCancelledError: If user presses Ctrl+C
    """
    log_message(f"Prompt checkbox: {message}")

    # Convert choices to Choice objects with pre-selected defaults
    default_set = set(default) if default else set()
    choice_objects = [
        questionary.Choice(choice, checked=(choice in default_set))
        for choice in choices
    ]

    try:
        result = questionary.checkbox(
            message,
            choices=choice_objects,
            style=custom_style,
        ).ask()

        if result is None:
            raise UserCancelledError("User cancelled checkbox prompt")

        log_message(f"User selected: {result}")
        return list(result)

    except KeyboardInterrupt as e:
        raise UserCancelledError("User cancelled with Ctrl+C") from e


__all__ = [
    "custom_style",
    "prompt_confirm",
    "prompt_input",
    "prompt_enter",
    "prompt_select",
    "prompt_checkbox",
]

