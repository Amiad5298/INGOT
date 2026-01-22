"""Tests for spec.integrations.providers.user_interaction module.

Tests cover:
- SelectOption dataclass functionality
- CLIUserInteraction class methods with mocked input/print
- NonInteractiveUserInteraction class behavior
- KeyboardInterrupt handling
- Abstract interface contract
"""

from abc import ABC
from unittest.mock import patch

import pytest

from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    NonInteractiveUserInteraction,
    SelectOption,
    UserInteractionInterface,
)


class TestSelectOption:
    """Tests for SelectOption dataclass."""

    def test_basic_creation(self):
        """Can create with required fields."""
        option = SelectOption(value="test", label="Test Option")
        assert option.value == "test"
        assert option.label == "Test Option"

    def test_description_default_empty(self):
        """Description defaults to empty string."""
        option = SelectOption(value=1, label="One")
        assert option.description == ""

    def test_with_description(self):
        """Can include optional description."""
        option = SelectOption(
            value="feat",
            label="Feature",
            description="New functionality",
        )
        assert option.description == "New functionality"

    def test_generic_type_support(self):
        """Supports generic types for value."""
        # String value
        str_option = SelectOption(value="string", label="String")
        assert str_option.value == "string"

        # Integer value
        int_option = SelectOption(value=42, label="Answer")
        assert int_option.value == 42

        # Complex object value
        obj = {"key": "value"}
        obj_option = SelectOption(value=obj, label="Object")
        assert obj_option.value == obj


class TestUserInteractionInterface:
    """Tests for UserInteractionInterface abstract base class."""

    def test_is_abstract_class(self):
        """UserInteractionInterface is an ABC."""
        assert issubclass(UserInteractionInterface, ABC)

    def test_cannot_instantiate_directly(self):
        """Cannot instantiate abstract class directly."""
        with pytest.raises(TypeError):
            UserInteractionInterface()

    def test_requires_select_option_method(self):
        """Subclasses must implement select_option."""
        class IncompleteImpl(UserInteractionInterface):
            def prompt_text(self, message, default="", required=True):
                pass
            def confirm(self, message, default=False):
                pass
            def display_message(self, message, level="info"):
                pass

        with pytest.raises(TypeError):
            IncompleteImpl()

    def test_requires_all_abstract_methods(self):
        """Subclasses must implement all abstract methods."""
        class CompleteImpl(UserInteractionInterface):
            def select_option(self, options, prompt, allow_cancel=True):
                return None
            def prompt_text(self, message, default="", required=True):
                return None
            def confirm(self, message, default=False):
                return False
            def display_message(self, message, level="info"):
                pass

        # Should not raise
        impl = CompleteImpl()
        assert impl is not None


class TestCLIUserInteractionSelectOption:
    """Tests for CLIUserInteraction.select_option method."""

    @pytest.fixture
    def cli(self):
        """Create CLI interaction instance."""
        return CLIUserInteraction()

    @pytest.fixture
    def sample_options(self):
        """Create sample options for testing."""
        return [
            SelectOption(value="a", label="Option A", description="First"),
            SelectOption(value="b", label="Option B"),
            SelectOption(value="c", label="Option C", description="Third"),
        ]

    @patch("builtins.input", return_value="1")
    @patch("builtins.print")
    def test_returns_selected_option(self, mock_print, mock_input, cli, sample_options):
        """Returns value of selected option."""
        result = cli.select_option(sample_options, "Choose:")
        assert result == "a"

    @patch("builtins.input", return_value="2")
    @patch("builtins.print")
    def test_selects_second_option(self, mock_print, mock_input, cli, sample_options):
        """Can select any option by number."""
        result = cli.select_option(sample_options, "Choose:")
        assert result == "b"

    @patch("builtins.input", return_value="0")
    @patch("builtins.print")
    def test_cancel_returns_none(self, mock_print, mock_input, cli, sample_options):
        """Selecting 0 with allow_cancel returns None."""
        result = cli.select_option(sample_options, "Choose:", allow_cancel=True)
        assert result is None

    @patch("builtins.input", side_effect=["0", "1"])
    @patch("builtins.print")
    def test_cancel_not_allowed_requires_valid_selection(
        self, mock_print, mock_input, cli, sample_options
    ):
        """When cancel not allowed, 0 is invalid."""
        result = cli.select_option(sample_options, "Choose:", allow_cancel=False)
        assert result == "a"
        # Should have called input twice (0 was invalid)
        assert mock_input.call_count == 2

    @patch("builtins.input", side_effect=["", "1"])
    @patch("builtins.print")
    def test_empty_input_retries(self, mock_print, mock_input, cli, sample_options):
        """Empty input prompts again."""
        result = cli.select_option(sample_options, "Choose:")
        assert result == "a"
        assert mock_input.call_count == 2

    @patch("builtins.input", side_effect=["abc", "1"])
    @patch("builtins.print")
    def test_non_numeric_input_retries(self, mock_print, mock_input, cli, sample_options):
        """Non-numeric input shows error and retries."""
        result = cli.select_option(sample_options, "Choose:")
        assert result == "a"
        # Check that error message was printed
        print_calls = [str(c) for c in mock_print.call_args_list]
        assert any("number" in str(c).lower() for c in print_calls)

    @patch("builtins.input", side_effect=["99", "1"])
    @patch("builtins.print")
    def test_out_of_range_retries(self, mock_print, mock_input, cli, sample_options):
        """Out of range selection shows error and retries."""
        result = cli.select_option(sample_options, "Choose:")
        assert result == "a"

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    @patch("builtins.print")
    def test_keyboard_interrupt_returns_none(
        self, mock_print, mock_input, cli, sample_options
    ):
        """KeyboardInterrupt returns None."""
        result = cli.select_option(sample_options, "Choose:")
        assert result is None

    @patch("builtins.input", return_value="1")
    @patch("builtins.print")
    def test_prints_options_with_descriptions(
        self, mock_print, mock_input, cli, sample_options
    ):
        """Prints options with descriptions when available."""
        cli.select_option(sample_options, "Choose:")
        print_calls = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Option A" in print_calls
        assert "First" in print_calls  # description

    def test_empty_options_returns_none_when_cancel_allowed(self, cli):
        """Empty options list returns None when allow_cancel=True."""
        result = cli.select_option([], "Choose:", allow_cancel=True)
        assert result is None

    def test_empty_options_raises_when_cancel_not_allowed(self, cli):
        """Empty options list raises ValueError when allow_cancel=False."""
        with pytest.raises(ValueError, match="No options provided"):
            cli.select_option([], "Choose:", allow_cancel=False)

    @patch("builtins.input", side_effect=EOFError)
    @patch("builtins.print")
    def test_eof_error_returns_none(self, mock_print, mock_input, cli, sample_options):
        """EOFError returns None (treat as cancel)."""
        result = cli.select_option(sample_options, "Choose:")
        assert result is None


class TestCLIUserInteractionPromptText:
    """Tests for CLIUserInteraction.prompt_text method."""

    @pytest.fixture
    def cli(self):
        return CLIUserInteraction()

    @patch("builtins.input", return_value="user input")
    def test_returns_user_input(self, mock_input, cli):
        """Returns user's text input."""
        result = cli.prompt_text("Enter name:")
        assert result == "user input"

    @patch("builtins.input", return_value="")
    def test_returns_default_on_empty_input(self, mock_input, cli):
        """Returns default when user enters nothing."""
        result = cli.prompt_text("Enter name:", default="John")
        assert result == "John"

    @patch("builtins.input", side_effect=["", "valid"])
    @patch("builtins.print")
    def test_required_field_retries_on_empty(self, mock_print, mock_input, cli):
        """Required field prompts again if empty."""
        result = cli.prompt_text("Enter name:", required=True)
        assert result == "valid"
        assert mock_input.call_count == 2

    @patch("builtins.input", return_value="")
    def test_not_required_accepts_empty(self, mock_input, cli):
        """Non-required field accepts empty input."""
        result = cli.prompt_text("Enter name:", required=False)
        assert result == ""

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    @patch("builtins.print")
    def test_keyboard_interrupt_returns_none(self, mock_print, mock_input, cli):
        """KeyboardInterrupt returns None."""
        result = cli.prompt_text("Enter name:")
        assert result is None

    @patch("builtins.input", side_effect=EOFError)
    @patch("builtins.print")
    def test_eof_error_returns_none(self, mock_print, mock_input, cli):
        """EOFError returns None (treat as cancel)."""
        result = cli.prompt_text("Enter name:")
        assert result is None


class TestCLIUserInteractionConfirm:
    """Tests for CLIUserInteraction.confirm method."""

    @pytest.fixture
    def cli(self):
        return CLIUserInteraction()

    @patch("builtins.input", return_value="y")
    def test_y_returns_true(self, mock_input, cli):
        """'y' returns True."""
        assert cli.confirm("Continue?") is True

    @patch("builtins.input", return_value="yes")
    def test_yes_returns_true(self, mock_input, cli):
        """'yes' returns True."""
        assert cli.confirm("Continue?") is True

    @patch("builtins.input", return_value="n")
    def test_n_returns_false(self, mock_input, cli):
        """'n' returns False."""
        assert cli.confirm("Continue?") is False

    @patch("builtins.input", return_value="no")
    def test_no_returns_false(self, mock_input, cli):
        """'no' returns False."""
        assert cli.confirm("Continue?") is False

    @patch("builtins.input", return_value="")
    def test_empty_returns_default_true(self, mock_input, cli):
        """Empty input returns default (True)."""
        assert cli.confirm("Continue?", default=True) is True

    @patch("builtins.input", return_value="")
    def test_empty_returns_default_false(self, mock_input, cli):
        """Empty input returns default (False)."""
        assert cli.confirm("Continue?", default=False) is False

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    @patch("builtins.print")
    def test_keyboard_interrupt_returns_false(self, mock_print, mock_input, cli):
        """KeyboardInterrupt returns False."""
        assert cli.confirm("Continue?") is False

    @patch("builtins.input", side_effect=EOFError)
    @patch("builtins.print")
    def test_eof_error_returns_default(self, mock_print, mock_input, cli):
        """EOFError returns default value."""
        assert cli.confirm("Continue?", default=True) is True

    @patch("builtins.input", side_effect=EOFError)
    @patch("builtins.print")
    def test_eof_error_returns_default_false(self, mock_print, mock_input, cli):
        """EOFError returns default value (False)."""
        assert cli.confirm("Continue?", default=False) is False


class TestCLIUserInteractionDisplayMessage:
    """Tests for CLIUserInteraction.display_message method."""

    @pytest.fixture
    def cli(self):
        return CLIUserInteraction()

    @patch("builtins.print")
    def test_displays_info_message(self, mock_print, cli):
        """Displays info message with prefix."""
        cli.display_message("Test message", level="info")
        mock_print.assert_called_once()
        call_args = str(mock_print.call_args)
        assert "Test message" in call_args

    @patch("builtins.print")
    def test_displays_warning_message(self, mock_print, cli):
        """Displays warning message."""
        cli.display_message("Warning!", level="warning")
        mock_print.assert_called_once()

    @patch("builtins.print")
    def test_displays_error_message(self, mock_print, cli):
        """Displays error message."""
        cli.display_message("Error occurred", level="error")
        mock_print.assert_called_once()

    @patch("builtins.print")
    def test_displays_success_message(self, mock_print, cli):
        """Displays success message."""
        cli.display_message("Done!", level="success")
        mock_print.assert_called_once()


class TestNonInteractiveUserInteraction:
    """Tests for NonInteractiveUserInteraction class."""

    @pytest.fixture
    def non_interactive(self):
        """Create non-interactive instance with fail_on_interaction=False."""
        return NonInteractiveUserInteraction(fail_on_interaction=False)

    @pytest.fixture
    def fail_on_interaction(self):
        """Create instance that fails on interaction (default behavior)."""
        return NonInteractiveUserInteraction(fail_on_interaction=True)

    @pytest.fixture
    def sample_options(self):
        """Create sample options."""
        return [
            SelectOption(value="a", label="A"),
            SelectOption(value="b", label="B"),
        ]

    def test_default_fails_on_interaction(self):
        """Default constructor has fail_on_interaction=True."""
        non_int = NonInteractiveUserInteraction()
        assert non_int.fail_on_interaction is True

    def test_select_option_returns_first_when_not_failing(
        self, non_interactive, sample_options
    ):
        """Returns first option when fail_on_interaction=False."""
        result = non_interactive.select_option(sample_options, "Choose:")
        assert result == "a"

    def test_select_option_raises_when_fail_on_interaction(
        self, fail_on_interaction, sample_options
    ):
        """Raises error when fail_on_interaction is True."""
        with pytest.raises(RuntimeError) as exc_info:
            fail_on_interaction.select_option(sample_options, "Choose:")
        assert "interactive" in str(exc_info.value).lower()

    def test_prompt_text_returns_default(self, non_interactive):
        """Returns default value for text prompts."""
        result = non_interactive.prompt_text("Name:", default="Default")
        assert result == "Default"

    def test_prompt_text_returns_empty_when_not_required(self, non_interactive):
        """Returns empty string when not required and no default."""
        result = non_interactive.prompt_text("Name:", required=False)
        assert result == ""

    def test_prompt_text_raises_when_required_no_default(self, fail_on_interaction):
        """Raises error when required, no default, and fail_on_interaction."""
        with pytest.raises(RuntimeError):
            fail_on_interaction.prompt_text("Name:")

    def test_prompt_text_returns_default_even_with_fail_on_interaction(
        self, fail_on_interaction
    ):
        """Returns default even with fail_on_interaction if default provided."""
        result = fail_on_interaction.prompt_text("Name:", default="DefaultValue")
        assert result == "DefaultValue"

    def test_confirm_returns_default_true(self, non_interactive):
        """Returns True as default."""
        result = non_interactive.confirm("Continue?", default=True)
        assert result is True

    def test_confirm_returns_default_false(self, non_interactive):
        """Returns False when that's the default."""
        result = non_interactive.confirm("Continue?", default=False)
        assert result is False

    def test_confirm_does_not_raise_even_with_fail_on_interaction(
        self, fail_on_interaction
    ):
        """confirm() never raises - it just returns the default."""
        # confirm always has a default, so it should never need to fail
        result = fail_on_interaction.confirm("Continue?", default=True)
        assert result is True

    @patch("builtins.print")
    def test_display_message_does_not_raise(self, mock_print, non_interactive):
        """display_message works without error."""
        non_interactive.display_message("Test", level="info")
        # Should not raise, may or may not print

    @patch("builtins.print")
    def test_display_message_with_fail_on_interaction_does_not_raise(
        self, mock_print, fail_on_interaction
    ):
        """display_message does not raise even with fail_on_interaction."""
        fail_on_interaction.display_message("Test", level="error")
        # Should not raise, display is not interactive

    def test_empty_options_returns_none_when_not_failing(self, non_interactive):
        """Returns None when no options and fail_on_interaction=False."""
        result = non_interactive.select_option([], "Choose:", allow_cancel=True)
        assert result is None

    def test_empty_options_raises_when_fail_on_interaction(self, fail_on_interaction):
        """Raises when no options and fail_on_interaction."""
        with pytest.raises(RuntimeError):
            fail_on_interaction.select_option([], "Choose:")


class TestUserInteractionIntegration:
    """Integration tests for user interaction classes."""

    def test_cli_and_non_interactive_have_same_interface(self):
        """Both implementations have the same interface."""
        cli = CLIUserInteraction()
        non_int = NonInteractiveUserInteraction()

        methods = ["select_option", "prompt_text", "confirm", "display_message"]
        for method in methods:
            assert hasattr(cli, method)
            assert hasattr(non_int, method)
            assert callable(getattr(cli, method))
            assert callable(getattr(non_int, method))

    def test_both_inherit_from_interface(self):
        """Both implementations inherit from UserInteractionInterface."""
        assert issubclass(CLIUserInteraction, UserInteractionInterface)
        assert issubclass(NonInteractiveUserInteraction, UserInteractionInterface)

