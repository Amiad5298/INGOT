"""Tests for spec.ui.plan_tui module (StreamingOperationUI)."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from specflow.ui.plan_tui import (
    DEFAULT_VERBOSE_LINES,
    MAX_LIVENESS_WIDTH,
    StreamingOperationUI,
    REFRESH_RATE,
)


class TestStreamingOperationUICreation:
    """Tests for StreamingOperationUI initialization."""

    def test_creates_with_defaults(self):
        """StreamingOperationUI can be created with default values."""
        ui = StreamingOperationUI()
        assert ui.status_message == "Processing..."
        assert ui.ticket_id == ""
        assert ui.verbose_mode is False

    def test_creates_with_custom_values(self):
        """StreamingOperationUI can be created with custom values."""
        ui = StreamingOperationUI(
            status_message="Generating plan...",
            ticket_id="TEST-123",
            verbose_mode=True,
        )
        assert ui.status_message == "Generating plan..."
        assert ui.ticket_id == "TEST-123"
        assert ui.verbose_mode is True

    def test_internal_state_initialized(self):
        """Internal state is properly initialized."""
        ui = StreamingOperationUI()
        assert ui._log_buffer is None
        assert ui._log_path is None
        assert ui._live is None
        assert ui._start_time == 0.0
        assert ui._latest_output_line == ""
        assert ui.quit_requested is False


class TestStreamingOperationUISetLogPath:
    """Tests for set_log_path method."""

    def test_sets_log_path(self, tmp_path: Path):
        """set_log_path sets the log path."""
        ui = StreamingOperationUI()
        log_path = tmp_path / "test.log"
        ui.set_log_path(log_path)
        assert ui._log_path == log_path

    def test_creates_log_buffer(self, tmp_path: Path):
        """set_log_path creates a TaskLogBuffer."""
        ui = StreamingOperationUI()
        log_path = tmp_path / "test.log"
        ui.set_log_path(log_path)
        assert ui._log_buffer is not None
        assert ui._log_buffer.log_path == log_path


class TestStreamingOperationUIHandleOutputLine:
    """Tests for handle_output_line method."""

    def test_writes_to_log_buffer(self, tmp_path: Path):
        """handle_output_line writes lines to log buffer."""
        ui = StreamingOperationUI()
        ui.set_log_path(tmp_path / "test.log")

        ui.handle_output_line("First line")
        ui.handle_output_line("Second line")

        assert ui._log_buffer.line_count == 2
        ui._log_buffer.close()

    def test_updates_liveness_indicator(self, tmp_path: Path):
        """handle_output_line updates the latest output line."""
        ui = StreamingOperationUI()
        ui.set_log_path(tmp_path / "test.log")

        ui.handle_output_line("First line")
        assert ui._latest_output_line == "First line"

        ui.handle_output_line("Second line")
        assert ui._latest_output_line == "Second line"

        ui._log_buffer.close()

    def test_ignores_empty_lines_for_liveness(self, tmp_path: Path):
        """handle_output_line ignores empty lines for liveness indicator."""
        ui = StreamingOperationUI()
        ui.set_log_path(tmp_path / "test.log")

        ui.handle_output_line("First line")
        ui.handle_output_line("")
        ui.handle_output_line("   ")

        # Liveness should still show first line
        assert ui._latest_output_line == "First line"
        ui._log_buffer.close()

    def test_handles_no_log_buffer(self):
        """handle_output_line works without log buffer."""
        ui = StreamingOperationUI()
        # Should not raise
        ui.handle_output_line("Test line")
        assert ui._latest_output_line == "Test line"


class TestStreamingOperationUITruncateLine:
    """Tests for _truncate_line method."""

    def test_returns_short_lines_unchanged(self):
        """Short lines are returned unchanged."""
        ui = StreamingOperationUI()
        short = "Hello world"
        assert ui._truncate_line(short) == short

    def test_truncates_long_lines(self):
        """Long lines are truncated with ellipsis."""
        ui = StreamingOperationUI()
        long_line = "A" * 100
        result = ui._truncate_line(long_line, max_width=50)
        assert len(result) == 50
        assert result.endswith("…")

    def test_exact_width_unchanged(self):
        """Lines at exact max width are unchanged."""
        ui = StreamingOperationUI()
        exact = "A" * 70
        result = ui._truncate_line(exact, max_width=70)
        assert result == exact


class TestStreamingOperationUIFormatElapsedTime:
    """Tests for _format_elapsed_time method."""

    def test_formats_seconds_only(self):
        """Formats short times as seconds only."""
        ui = StreamingOperationUI()
        ui._start_time = time.time() - 45
        result = ui._format_elapsed_time()
        assert result == "45s"

    def test_formats_minutes_and_seconds(self):
        """Formats longer times with minutes."""
        ui = StreamingOperationUI()
        ui._start_time = time.time() - 125  # 2m 5s
        result = ui._format_elapsed_time()
        assert result == "2m 05s"


class TestStreamingOperationUIVerboseMode:
    """Tests for verbose mode toggle."""

    def test_toggle_verbose_mode(self):
        """_toggle_verbose_mode toggles verbose_mode flag."""
        ui = StreamingOperationUI()
        assert ui.verbose_mode is False

        ui._toggle_verbose_mode()
        assert ui.verbose_mode is True

        ui._toggle_verbose_mode()
        assert ui.verbose_mode is False


class TestStreamingOperationUIQuitRequest:
    """Tests for quit/cancel request handling."""

    def test_handle_quit_sets_flag(self):
        """_handle_quit sets quit_requested flag."""
        ui = StreamingOperationUI()
        assert ui.quit_requested is False

        ui._handle_quit()
        assert ui.quit_requested is True


class TestStreamingOperationUIContextManager:
    """Tests for context manager protocol."""

    @patch("specflow.ui.plan_tui.Live")
    @patch.object(StreamingOperationUI, "_input_loop")
    def test_context_manager_starts_and_stops(self, mock_input_loop, mock_live_class, tmp_path: Path):
        """Context manager starts and stops TUI."""
        mock_live = MagicMock()
        mock_live_class.return_value = mock_live

        ui = StreamingOperationUI()
        ui.set_log_path(tmp_path / "test.log")

        with ui:
            # Live should have been started
            mock_live.start.assert_called_once()

        # Live should have been stopped
        mock_live.stop.assert_called_once()

    @patch("specflow.ui.plan_tui.Live")
    @patch.object(StreamingOperationUI, "_input_loop")
    def test_context_manager_closes_log_buffer(self, mock_input_loop, mock_live_class, tmp_path: Path):
        """Context manager closes log buffer on exit."""
        mock_live_class.return_value = MagicMock()

        ui = StreamingOperationUI()
        log_path = tmp_path / "test.log"
        ui.set_log_path(log_path)
        ui.handle_output_line("Test line")

        with ui:
            assert ui._log_buffer._file_handle is not None

        # After context, buffer should be closed
        assert ui._log_buffer._file_handle is None

    @patch("specflow.ui.plan_tui.Live")
    @patch.object(StreamingOperationUI, "_input_loop")
    def test_context_manager_returns_self(self, mock_input_loop, mock_live_class):
        """Context manager returns self on entry."""
        mock_live_class.return_value = MagicMock()

        ui = StreamingOperationUI()

        with ui as context:
            assert context is ui


class TestStreamingOperationUIRendering:
    """Tests for rendering methods."""

    def test_render_layout_returns_group(self, tmp_path: Path):
        """_render_layout returns a Rich Group."""
        from rich.console import Group

        ui = StreamingOperationUI(status_message="Test", ticket_id="TEST-1")
        ui.set_log_path(tmp_path / "test.log")
        ui._start_time = time.time()

        result = ui._render_layout()
        assert isinstance(result, Group)

    def test_render_status_bar_shows_shortcuts(self):
        """_render_status_bar shows keyboard shortcuts."""
        from rich.text import Text

        ui = StreamingOperationUI()
        result = ui._render_status_bar()

        assert isinstance(result, Text)
        plain_text = result.plain
        assert "[v]" in plain_text
        assert "[Enter]" in plain_text
        assert "[q]" in plain_text

    def test_render_normal_panel_shows_status(self, tmp_path: Path):
        """_render_normal_panel shows status message."""
        from rich.panel import Panel
        from rich.spinner import Spinner

        ui = StreamingOperationUI(status_message="Generating plan...")
        ui.set_log_path(tmp_path / "test.log")
        ui._start_time = time.time()

        spinner = Spinner("dots")
        result = ui._render_normal_panel(spinner, "5s")

        assert isinstance(result, Panel)

    def test_render_verbose_panel_shows_log_output(self, tmp_path: Path):
        """_render_verbose_panel shows log output."""
        from rich.panel import Panel
        from rich.spinner import Spinner

        ui = StreamingOperationUI(status_message="Generating plan...")
        ui.set_log_path(tmp_path / "test.log")
        ui._start_time = time.time()
        ui.handle_output_line("Log line 1")
        ui.handle_output_line("Log line 2")

        spinner = Spinner("dots")
        result = ui._render_verbose_panel(spinner, "10s")

        assert isinstance(result, Panel)


class TestStreamingOperationUIPrintSummary:
    """Tests for print_summary method."""

    def test_print_summary_success(self, tmp_path: Path, capsys):
        """print_summary shows success message."""
        ui = StreamingOperationUI()
        ui._start_time = time.time() - 30
        ui.set_log_path(tmp_path / "test.log")

        ui.print_summary(success=True)

        # Note: Rich output may not be captured by capsys
        # We're mainly testing that it doesn't raise

    def test_print_summary_failure(self, tmp_path: Path, capsys):
        """print_summary shows failure message."""
        ui = StreamingOperationUI()
        ui._start_time = time.time() - 60
        ui.set_log_path(tmp_path / "test.log")

        ui.print_summary(success=False)

        # Note: Rich output may not be captured by capsys
        # We're mainly testing that it doesn't raise


class TestStreamingOperationUIKeyboardHandling:
    """Tests for keyboard handling."""

    def test_handle_key_v_toggles_verbose(self):
        """Pressing 'v' toggles verbose mode."""
        from specflow.ui.keyboard import Key

        ui = StreamingOperationUI()
        assert ui.verbose_mode is False

        ui._handle_key(Key.V)
        assert ui.verbose_mode is True

    def test_handle_key_q_sets_quit(self):
        """Pressing 'q' sets quit_requested."""
        from specflow.ui.keyboard import Key

        ui = StreamingOperationUI()
        assert ui.quit_requested is False

        ui._handle_key(Key.Q)
        assert ui.quit_requested is True


class TestConstants:
    """Tests for module constants."""

    def test_refresh_rate_is_positive(self):
        """REFRESH_RATE is a positive number."""
        assert REFRESH_RATE > 0

    def test_default_verbose_lines_is_positive(self):
        """DEFAULT_VERBOSE_LINES is a positive number."""
        assert DEFAULT_VERBOSE_LINES > 0

    def test_max_liveness_width_is_positive(self):
        """MAX_LIVENESS_WIDTH is a positive number."""
        assert MAX_LIVENESS_WIDTH > 0


# =============================================================================
# Integration Tests for Step 1 TUI Mode
# =============================================================================


class TestStep1TUIIntegration:
    """Integration tests for step 1 with TUI mode."""

    @pytest.fixture
    def workflow_state(self, tmp_path: Path):
        """Create a workflow state for testing."""
        from specflow.integrations.jira import JiraTicket
        from specflow.workflow.state import WorkflowState

        ticket = JiraTicket(
            ticket_id="TEST-456",
            ticket_url="https://jira.example.com/TEST-456",
            summary="Test Feature",
            title="Implement test feature",
            description="Test description for the feature",
        )
        state = WorkflowState(ticket=ticket)

        # Set specs directory to tmp_path
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        state._specs_dir = specs_dir

        return state

    @patch("specflow.ui.plan_tui.StreamingOperationUI")
    @patch("specflow.workflow.step1_plan.AuggieClient")
    def test_uses_tui_when_enabled(
        self,
        mock_auggie_class,
        mock_ui_class,
        workflow_state,
        tmp_path: Path,
        monkeypatch,
    ):
        """Step 1 uses TUI when _should_use_tui returns True."""
        from specflow.workflow.step1_plan import _generate_plan_with_tui

        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        # Setup
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.quit_requested = False

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Generated plan")
        mock_auggie_class.return_value = mock_client

        # Act - note: new signature is (state, plan_path), prompt is built internally
        plan_path = workflow_state.get_plan_path()
        result = _generate_plan_with_tui(workflow_state, plan_path)

        # Assert
        assert result is True
        mock_ui_class.assert_called_once()
        mock_client.run_with_callback.assert_called_once()

    @patch("specflow.ui.plan_tui.StreamingOperationUI")
    @patch("specflow.workflow.step1_plan.AuggieClient")
    def test_tui_quit_returns_false(
        self,
        mock_auggie_class,
        mock_ui_class,
        workflow_state,
        tmp_path: Path,
        monkeypatch,
    ):
        """TUI returns False when user requests quit."""
        from specflow.workflow.step1_plan import _generate_plan_with_tui

        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        # Setup
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.__enter__ = MagicMock(return_value=mock_ui)
        mock_ui.__exit__ = MagicMock(return_value=None)
        mock_ui.quit_requested = True  # User pressed 'q'

        mock_client = MagicMock()
        mock_client.run_with_callback.return_value = (True, "Generated plan")
        mock_auggie_class.return_value = mock_client

        # Act - note: new signature is (state, plan_path), prompt is built internally
        plan_path = workflow_state.get_plan_path()
        result = _generate_plan_with_tui(workflow_state, plan_path)

        # Assert - should return False due to quit
        assert result is False

    def test_creates_log_directory(self, tmp_path: Path, monkeypatch):
        """Log directory is created for plan generation."""
        from specflow.workflow.step1_plan import _create_plan_log_dir

        # Set log base dir to tmp_path
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(tmp_path))

        # Act
        log_dir = _create_plan_log_dir("TEST-789")

        # Assert
        assert log_dir.exists()
        assert "TEST-789" in str(log_dir)
        assert "plan_generation" in str(log_dir)

    def test_get_log_base_dir_uses_env_var(self, tmp_path: Path, monkeypatch):
        """Log base dir uses SPECFLOW_LOG_DIR env var."""
        from specflow.workflow.step1_plan import _get_log_base_dir

        custom_dir = tmp_path / "custom_logs"
        monkeypatch.setenv("SPECFLOW_LOG_DIR", str(custom_dir))

        result = _get_log_base_dir()
        assert result == custom_dir

    def test_get_log_base_dir_default(self, monkeypatch):
        """Log base dir defaults to .specflow/runs."""
        from specflow.workflow.step1_plan import _get_log_base_dir

        monkeypatch.delenv("SPECFLOW_LOG_DIR", raising=False)

        result = _get_log_base_dir()
        assert result == Path(".specflow/runs")

