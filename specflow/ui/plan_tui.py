"""TUI for single long-running streaming operations.

This module provides a simplified TUI component for displaying progress
during long-running AI operations. Unlike the multi-task TUI in step 3,
this shows a single spinner with status and liveness indicator.

Used for:
- Step 1: Plan generation
- Post-implementation test execution
- Step 4: Documentation updates

Features:
- Spinner with status message and elapsed time
- Liveness indicator showing latest AI output
- Log capture to file
- Optional verbose mode to show full output
- Keyboard controls (v=toggle verbose, Enter=view log, q=quit)
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from specflow.ui.keyboard import Key, KeyboardReader
from specflow.ui.log_buffer import TaskLogBuffer
from specflow.utils.console import console

if TYPE_CHECKING:
    pass


# =============================================================================
# Configuration
# =============================================================================

# Refresh rate for the TUI (times per second)
REFRESH_RATE = 4

# Default number of log lines to display in verbose mode
DEFAULT_VERBOSE_LINES = 10

# Maximum width for liveness indicator text
MAX_LIVENESS_WIDTH = 70


# =============================================================================
# StreamingOperationUI Class
# =============================================================================


@dataclass
class StreamingOperationUI:
    """TUI for single long-running streaming operations.

    A generic UI component for displaying progress during any AI operation
    that produces streaming output. Supports context manager protocol:

        with StreamingOperationUI(status_message="Running...") as ui:
            success, output = auggie.run_with_callback(
                prompt, output_callback=ui.handle_output_line
            )

    Attributes:
        status_message: Message to display next to spinner.
        ticket_id: Ticket ID for display in header.
        verbose_mode: Whether to show full log output.
    """

    # Configuration
    status_message: str = "Processing..."
    ticket_id: str = ""
    verbose_mode: bool = False

    # Internal state (not set by user)
    _log_buffer: TaskLogBuffer | None = field(default=None, init=False, repr=False)
    _log_path: Path | None = field(default=None, init=False, repr=False)
    _live: Live | None = field(default=None, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)
    _keyboard_reader: KeyboardReader = field(
        default_factory=KeyboardReader, init=False, repr=False
    )
    _input_thread: threading.Thread | None = field(
        default=None, init=False, repr=False
    )
    _stop_input_thread: bool = field(default=False, init=False, repr=False)
    _latest_output_line: str = field(default="", init=False, repr=False)
    # Quit/cancel signal
    quit_requested: bool = field(default=False, init=False, repr=False)

    def set_log_path(self, path: Path) -> None:
        """Set log file path and create buffer.

        Args:
            path: Path to the log file.
        """
        self._log_path = path
        self._log_buffer = TaskLogBuffer(log_path=path)

    def handle_output_line(self, line: str) -> None:
        """Callback for AI output lines.

        Called for each line of AI output. This method:
        1. Writes the line to the log buffer (file + memory)
        2. Updates the liveness indicator with the latest line (truncated)
        3. Triggers a display refresh to show the updated liveness text

        Args:
            line: A single line of AI output (without trailing newline).
        """
        # Write to log buffer
        if self._log_buffer is not None:
            self._log_buffer.write(line)

        # Update liveness indicator (truncate if too long)
        if line.strip():
            self._latest_output_line = line

        # Refresh display
        self.refresh()

    def start(self) -> None:
        """Start the TUI display and keyboard input handling."""
        self._start_time = time.time()

        # Start keyboard reader
        self._keyboard_reader.start()
        self._stop_input_thread = False
        self._input_thread = threading.Thread(target=self._input_loop, daemon=True)
        self._input_thread.start()

        # Start Rich Live display
        self._live = Live(
            self._render_layout(),
            console=console,
            refresh_per_second=REFRESH_RATE,
            vertical_overflow="visible",
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the TUI display and keyboard input handling."""
        # Stop input thread
        self._stop_input_thread = True
        if self._input_thread is not None:
            self._input_thread.join(timeout=0.5)
            self._input_thread = None

        # Stop keyboard reader
        self._keyboard_reader.stop()

        # Stop Live display
        if self._live is not None:
            self._live.stop()
            self._live = None

        # Close log buffer
        if self._log_buffer is not None:
            self._log_buffer.close()

    def __enter__(self) -> StreamingOperationUI:
        """Context manager entry - starts the TUI display.

        Returns:
            self for use in `with ... as ui:` pattern.
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit - stops the TUI display.

        Ensures cleanup even if an exception occurs during execution.
        """
        self.stop()

    def refresh(self) -> None:
        """Refresh the display with current state."""
        if self._live is not None:
            self._live.update(self._render_layout())

    def _format_elapsed_time(self) -> str:
        """Format elapsed time since start.

        Returns:
            Formatted time string like '1m 23s'.
        """
        elapsed = time.time() - self._start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _truncate_line(self, line: str, max_width: int = MAX_LIVENESS_WIDTH) -> str:
        """Truncate a line to max width with ellipsis.

        Args:
            line: Line to truncate.
            max_width: Maximum width.

        Returns:
            Truncated line with '…' if needed.
        """
        if len(line) <= max_width:
            return line
        return line[: max_width - 1] + "…"

    def _render_layout(self) -> Group:
        """Render the TUI layout including liveness indicator.

        Returns:
            Rich Group containing all panels and status bar.
        """
        elements: list[Panel | Text] = []

        # Build spinner line with elapsed time
        elapsed = self._format_elapsed_time()
        spinner = Spinner("dots", style="cyan")

        # Main status panel content
        if self.verbose_mode:
            # Verbose mode: show log output
            elements.append(self._render_verbose_panel(spinner, elapsed))
        else:
            # Normal mode: show spinner with liveness indicator
            elements.append(self._render_normal_panel(spinner, elapsed))

        # Status bar with keyboard shortcuts
        elements.append(self._render_status_bar())

        return Group(*elements)

    def _render_normal_panel(self, spinner: Spinner, elapsed: str) -> Panel:
        """Render the normal (non-verbose) panel.

        Args:
            spinner: Rich Spinner object.
            elapsed: Formatted elapsed time string.

        Returns:
            Rich Panel with spinner, status, and liveness indicator.
        """
        content_lines = []

        # Main status line with spinner placeholder
        status_text = Text()
        status_text.append("  ")
        status_text.append(self.status_message, style="bold")
        status_text.append(f"  {elapsed}", style="dim")
        content_lines.append(status_text)

        # Empty line
        content_lines.append(Text())

        # Liveness indicator
        if self._latest_output_line:
            truncated = self._truncate_line(self._latest_output_line.strip())
            liveness = Text()
            liveness.append("  ► ", style="dim cyan")
            liveness.append(truncated, style="dim")
            content_lines.append(liveness)
        else:
            content_lines.append(Text("  [dim]Waiting for output...[/dim]"))

        # Empty line
        content_lines.append(Text())

        # Log path
        if self._log_path:
            log_text = Text()
            log_text.append("  Logs: ", style="dim")
            log_text.append(str(self._log_path), style="dim italic")
            content_lines.append(log_text)

        content = Group(*content_lines)

        # Build header - use ticket_id if provided, otherwise use status message
        header = f"⟳ {self.ticket_id}" if self.ticket_id else "⟳ Operation"

        return Panel(
            content,
            title=header,
            border_style="blue",
        )

    def _render_verbose_panel(self, spinner: Spinner, elapsed: str) -> Panel:
        """Render the verbose panel with log output.

        Args:
            spinner: Rich Spinner object.
            elapsed: Formatted elapsed time string.

        Returns:
            Rich Panel with spinner, status, and log output.
        """
        content_lines = []

        # Main status line
        status_text = Text()
        status_text.append("  ")
        status_text.append(self.status_message, style="bold")
        status_text.append(f"  {elapsed}", style="dim")
        content_lines.append(status_text)

        # Separator
        content_lines.append(Text("  " + "─" * 60, style="dim"))

        # Log output
        if self._log_buffer is not None:
            lines = self._log_buffer.get_tail(DEFAULT_VERBOSE_LINES)
            for line in lines:
                content_lines.append(Text(f"  {line}"))
        else:
            content_lines.append(Text("  [dim]No output yet...[/dim]"))

        content = Group(*content_lines)

        # Build header - use ticket_id if provided, otherwise use status message
        header = f"⟳ {self.ticket_id}" if self.ticket_id else "⟳ Operation"

        return Panel(
            content,
            title=header,
            border_style="green",
        )

    def _render_status_bar(self) -> Text:
        """Render the keyboard shortcuts status bar.

        Returns:
            Rich Text with keyboard shortcuts.
        """
        shortcuts = [
            ("[v]", "Toggle verbose"),
            ("[Enter]", "View log"),
            ("[q]", "Cancel"),
        ]

        text = Text()
        for key, action in shortcuts:
            text.append(key, style="bold cyan")
            text.append(f" {action}  ", style="dim")

        return text

    # =========================================================================
    # Keyboard Input Handling
    # =========================================================================

    def _input_loop(self) -> None:
        """Background thread loop for reading keyboard input."""
        while not self._stop_input_thread:
            key = self._keyboard_reader.read_key(timeout=0.1)
            if key is not None:
                self._handle_key(key)

    def _handle_key(self, key: Key) -> None:
        """Handle a keypress.

        Args:
            key: The key that was pressed.
        """
        if key == Key.V:
            self._toggle_verbose_mode()
        elif key == Key.ENTER:
            self._open_log_in_pager()
        elif key == Key.Q:
            self._handle_quit()

    def _toggle_verbose_mode(self) -> None:
        """Toggle verbose mode (show/hide log output)."""
        self.verbose_mode = not self.verbose_mode
        self.refresh()

    def _open_log_in_pager(self) -> None:
        """Open the full log file in system pager."""
        if self._log_path and self._log_path.exists():
            # Temporarily stop the TUI to show pager
            if self._live is not None:
                self._live.stop()
            try:
                # Use 'less' or 'more' as pager
                pager = os.environ.get("PAGER", "less")
                subprocess.run([pager, str(self._log_path)])
            finally:
                # Restart the TUI
                if self._live is not None:
                    self._live.start()

    def _handle_quit(self) -> None:
        """Handle quit/cancel request."""
        self.quit_requested = True

    # =========================================================================
    # Summary Output
    # =========================================================================

    def print_summary(self, success: bool) -> None:
        """Print summary after completion.

        Args:
            success: Whether the operation completed successfully.
        """
        elapsed = self._format_elapsed_time()

        console.print()
        if success:
            console.print(f"[green]✓[/green] Plan generation completed in {elapsed}")
        else:
            console.print(f"[red]✗[/red] Plan generation failed after {elapsed}")

        if self._log_path:
            console.print(f"[dim]Logs saved to: {self._log_path}[/dim]")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "StreamingOperationUI",
    "REFRESH_RATE",
    "DEFAULT_VERBOSE_LINES",
]

