"""User interaction abstraction for issue tracker providers.

This module provides an abstraction layer for user interactions, ensuring
that providers never call print() or input() directly. This enables:
- Testable providers in isolation
- CI/CD usage without interactive prompts
- Different UI implementations (CLI, GUI, web)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class SelectOption(Generic[T]):
    """An option for user selection.

    Attributes:
        value: The value returned when this option is selected
        label: Display label for the option
        description: Optional additional description
    """

    value: T
    label: str
    description: str = ""


class UserInteractionInterface(ABC):
    """Abstract interface for user interactions.

    All user-facing prompts and confirmations must go through this interface.
    Providers receive an instance via dependency injection.
    """

    @abstractmethod
    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True,
    ) -> T | None:
        """Present options to user and get selection.

        Args:
            options: List of options to present
            prompt: Message to display to user
            allow_cancel: If True, user can cancel (returns None)

        Returns:
            Selected option value, or None if cancelled
        """
        pass

    @abstractmethod
    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True,
    ) -> str | None:
        """Prompt user for text input.

        Args:
            message: Prompt message to display
            default: Default value if user enters nothing
            required: If True, empty input is not accepted

        Returns:
            User input string, or None if cancelled
        """
        pass

    @abstractmethod
    def confirm(
        self,
        message: str,
        default: bool = False,
    ) -> bool:
        """Ask user for yes/no confirmation.

        Args:
            message: Question to ask
            default: Default answer if user presses Enter

        Returns:
            True for yes, False for no
        """
        pass

    @abstractmethod
    def display_message(
        self,
        message: str,
        level: str = "info",
    ) -> None:
        """Display a message to the user.

        Args:
            message: Message to display
            level: One of "info", "warning", "error", "success"
        """
        pass


class CLIUserInteraction(UserInteractionInterface):
    """Command-line implementation of user interaction.

    Uses standard input/print for terminal-based interaction.
    Handles KeyboardInterrupt and EOFError gracefully for all prompts.
    """

    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True,
    ) -> T | None:
        """Present numbered options and get user selection.

        Args:
            options: List of options to present
            prompt: Message to display to user
            allow_cancel: If True, user can cancel (returns None)

        Returns:
            Selected option value, or None if cancelled

        Raises:
            ValueError: If options is empty and allow_cancel is False
        """
        # Handle empty options list
        if not options:
            if allow_cancel:
                return None
            raise ValueError("No options provided and cancellation not allowed")

        print(f"\n{prompt}")
        for i, opt in enumerate(options, 1):
            desc = f" - {opt.description}" if opt.description else ""
            print(f"  [{i}] {opt.label}{desc}")

        if allow_cancel:
            print("  [0] Cancel")

        while True:
            try:
                choice = input("\nEnter selection: ").strip()
                if not choice:
                    continue

                idx = int(choice)
                if allow_cancel and idx == 0:
                    return None
                if 1 <= idx <= len(options):
                    return options[idx - 1].value

                print(f"Invalid selection. Enter 1-{len(options)}")
            except ValueError:
                print("Please enter a number")
            except (KeyboardInterrupt, EOFError):
                print()  # Clean newline after ^C or EOF
                return None

    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True,
    ) -> str | None:
        """Prompt for text input with optional default."""
        default_hint = f" [{default}]" if default else ""
        try:
            while True:
                result = input(f"{message}{default_hint}: ").strip()
                if not result and default:
                    return default
                if result or not required:
                    return result
                print("This field is required.")
        except (KeyboardInterrupt, EOFError):
            print()  # Clean newline after ^C or EOF
            return None

    def confirm(
        self,
        message: str,
        default: bool = False,
    ) -> bool:
        """Ask for yes/no confirmation."""
        hint = "[Y/n]" if default else "[y/N]"
        try:
            result = input(f"{message} {hint}: ").strip().lower()
            if not result:
                return default
            return result in ("y", "yes", "true", "1")
        except (KeyboardInterrupt, EOFError):
            print()  # Clean newline after ^C or EOF
            return default

    def display_message(
        self,
        message: str,
        level: str = "info",
    ) -> None:
        """Display a message with appropriate prefix."""
        prefixes = {
            "info": "ℹ️  ",
            "warning": "⚠️  ",
            "error": "❌ ",
            "success": "✅ ",
        }
        print(f"{prefixes.get(level, '')}{message}")


class NonInteractiveUserInteraction(UserInteractionInterface):
    """Non-interactive implementation for CI/CD and testing.

    Returns defaults or raises errors for required interactions.
    Useful for automated pipelines where user input is not available.
    """

    def __init__(self, fail_on_interaction: bool = True) -> None:
        """Initialize non-interactive handler.

        Args:
            fail_on_interaction: If True, raise RuntimeError when
                interaction is required. If False, return defaults.
        """
        self.fail_on_interaction = fail_on_interaction

    def select_option(
        self,
        options: list[SelectOption[T]],
        prompt: str,
        allow_cancel: bool = True,
    ) -> T | None:
        """Return first option or raise if fail_on_interaction is True."""
        if self.fail_on_interaction:
            raise RuntimeError(
                f"Interactive selection required but running in non-interactive mode. "
                f"Prompt: {prompt}"
            )
        return options[0].value if options else None

    def prompt_text(
        self,
        message: str,
        default: str = "",
        required: bool = True,
    ) -> str | None:
        """Return default or raise if required and fail_on_interaction is True."""
        if required and not default and self.fail_on_interaction:
            raise RuntimeError(
                f"Required text input but running in non-interactive mode. "
                f"Prompt: {message}"
            )
        return default

    def confirm(
        self,
        message: str,
        default: bool = False,
    ) -> bool:
        """Return the default value."""
        return default

    def display_message(
        self,
        message: str,
        level: str = "info",
    ) -> None:
        """Silent in non-interactive mode (could log to stderr if needed)."""
        pass

