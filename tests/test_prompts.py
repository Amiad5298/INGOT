"""Tests for spec.ui.prompts module."""

from unittest.mock import patch

import pytest

from spec.ui.prompts import (
    custom_style,
    prompt_checkbox,
    prompt_confirm,
    prompt_enter,
    prompt_input,
    prompt_select,
)
from spec.utils.errors import UserCancelledError


class TestCustomStyle:
    """Tests for custom_style."""

    def test_style_has_qmark(self):
        """Style defines qmark."""
        assert any("qmark" in str(s) for s in custom_style.style_rules)

    def test_style_has_question(self):
        """Style defines question."""
        assert any("question" in str(s) for s in custom_style.style_rules)


class TestPromptConfirm:
    """Tests for prompt_confirm function."""

    @patch("questionary.confirm")
    def test_returns_true_for_yes(self, mock_confirm):
        """Returns True when user confirms."""
        mock_confirm.return_value.ask.return_value = True

        result = prompt_confirm("Continue?")

        assert result is True

    @patch("questionary.confirm")
    def test_returns_false_for_no(self, mock_confirm):
        """Returns False when user declines."""
        mock_confirm.return_value.ask.return_value = False

        result = prompt_confirm("Continue?")

        assert result is False

    @patch("questionary.confirm")
    def test_raises_on_cancel(self, mock_confirm):
        """Raises UserCancelledError when cancelled."""
        mock_confirm.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            prompt_confirm("Continue?")

    def test_auto_enter_returns_default(self):
        """Auto-enter returns default value."""
        result = prompt_confirm("Continue?", default=True, auto_enter=True)

        assert result is True

    def test_auto_enter_returns_false_default(self):
        """Auto-enter returns False when default is False."""
        result = prompt_confirm("Continue?", default=False, auto_enter=True)

        assert result is False


class TestPromptInput:
    """Tests for prompt_input function."""

    @patch("questionary.text")
    def test_returns_user_input(self, mock_text):
        """Returns user input."""
        mock_text.return_value.ask.return_value = "user input"

        result = prompt_input("Enter value")

        assert result == "user input"

    @patch("questionary.text")
    def test_raises_on_cancel(self, mock_text):
        """Raises UserCancelledError when cancelled."""
        mock_text.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            prompt_input("Enter value")


class TestPromptEnter:
    """Tests for prompt_enter function."""

    @patch("questionary.press_any_key_to_continue")
    def test_waits_for_enter(self, mock_press):
        """Waits for user to press Enter."""
        mock_press.return_value.ask.return_value = None

        # Should not raise
        prompt_enter()

        mock_press.assert_called_once()


class TestPromptSelect:
    """Tests for prompt_select function."""

    @patch("questionary.select")
    def test_returns_selection(self, mock_select):
        """Returns selected choice."""
        mock_select.return_value.ask.return_value = "option2"

        result = prompt_select("Choose", ["option1", "option2", "option3"])

        assert result == "option2"

    @patch("questionary.select")
    def test_raises_on_cancel(self, mock_select):
        """Raises UserCancelledError when cancelled."""
        mock_select.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            prompt_select("Choose", ["option1", "option2"])


class TestPromptCheckbox:
    """Tests for prompt_checkbox function."""

    @patch("questionary.checkbox")
    def test_returns_selections(self, mock_checkbox):
        """Returns list of selected choices."""
        mock_checkbox.return_value.ask.return_value = ["option1", "option3"]

        result = prompt_checkbox("Select", ["option1", "option2", "option3"])

        assert result == ["option1", "option3"]

    @patch("questionary.checkbox")
    def test_raises_on_cancel(self, mock_checkbox):
        """Raises UserCancelledError when cancelled."""
        mock_checkbox.return_value.ask.return_value = None

        with pytest.raises(UserCancelledError):
            prompt_checkbox("Select", ["option1", "option2"])

