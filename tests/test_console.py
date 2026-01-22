"""Tests for spec.utils.console module."""

from unittest.mock import patch

from spec.utils.console import (
    custom_theme,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
    show_banner,
    show_version,
)


class TestCustomTheme:
    """Tests for custom Rich theme."""

    def test_theme_has_error_style(self):
        """Theme defines error style."""
        assert "error" in custom_theme.styles

    def test_theme_has_success_style(self):
        """Theme defines success style."""
        assert "success" in custom_theme.styles

    def test_theme_has_warning_style(self):
        """Theme defines warning style."""
        assert "warning" in custom_theme.styles

    def test_theme_has_info_style(self):
        """Theme defines info style."""
        assert "info" in custom_theme.styles

    def test_theme_has_header_style(self):
        """Theme defines header style."""
        assert "header" in custom_theme.styles

    def test_theme_has_step_style(self):
        """Theme defines step style."""
        assert "step" in custom_theme.styles


class TestPrintFunctions:
    """Tests for print functions."""

    @patch("spec.utils.console.console_err")
    @patch("spec.utils.logging.log_message")
    def test_print_error(self, mock_log, mock_console_err):
        """print_error outputs error message."""
        print_error("Test error")

        mock_console_err.print.assert_called_once()
        call_args = mock_console_err.print.call_args
        assert "[ERROR]" in call_args[0][0]
        assert "Test error" in call_args[0][0]
        mock_log.assert_called_once_with("ERROR: Test error")

    @patch("spec.utils.console.console")
    @patch("spec.utils.logging.log_message")
    def test_print_success(self, mock_log, mock_console):
        """print_success outputs success message."""
        print_success("Test success")

        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        assert "[SUCCESS]" in call_args[0][0]
        assert "Test success" in call_args[0][0]
        mock_log.assert_called_once_with("SUCCESS: Test success")

    @patch("spec.utils.console.console")
    @patch("spec.utils.logging.log_message")
    def test_print_warning(self, mock_log, mock_console):
        """print_warning outputs warning message."""
        print_warning("Test warning")

        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        assert "[WARNING]" in call_args[0][0]
        assert "Test warning" in call_args[0][0]
        mock_log.assert_called_once_with("WARNING: Test warning")

    @patch("spec.utils.console.console")
    @patch("spec.utils.logging.log_message")
    def test_print_info(self, mock_log, mock_console):
        """print_info outputs info message."""
        print_info("Test info")

        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        assert "[INFO]" in call_args[0][0]
        assert "Test info" in call_args[0][0]
        mock_log.assert_called_once_with("INFO: Test info")

    @patch("spec.utils.console.console")
    def test_print_header(self, mock_console):
        """print_header outputs header with formatting."""
        print_header("Test Header")

        # Should print empty line, header, empty line
        assert mock_console.print.call_count == 3
        calls = mock_console.print.call_args_list
        assert "=== Test Header ===" in calls[1][0][0]

    @patch("spec.utils.console.console")
    def test_print_step(self, mock_console):
        """print_step outputs step with arrow."""
        print_step("Test step")

        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        assert "➜" in call_args[0][0]
        assert "Test step" in call_args[0][0]


class TestBanner:
    """Tests for banner display."""

    @patch("spec.utils.console.console")
    def test_show_banner(self, mock_console):
        """show_banner displays ASCII art."""
        show_banner()

        mock_console.print.assert_called_once()
        call_args = mock_console.print.call_args
        banner_text = call_args[0][0]
        # Check for "Spec-driven" in the banner text
        assert "Spec-driven" in banner_text


class TestVersion:
    """Tests for version display."""

    @patch("spec.utils.console.console")
    def test_show_version(self, mock_console):
        """show_version displays version info."""
        show_version()

        # Should print multiple lines
        assert mock_console.print.call_count >= 4

        # Check version is displayed
        calls = [str(c) for c in mock_console.print.call_args_list]
        version_shown = any("2.0.0" in c for c in calls)
        assert version_shown

