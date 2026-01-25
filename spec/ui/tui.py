"""TUI (Text User Interface) for workflow execution.

This module provides a rich terminal interface for visualizing and
interacting with workflow execution. Uses Rich's Live display
for real-time updates.

Supports two modes:
1. **Multi-task mode** (default): For Step 3 task execution with task list,
   navigation, and parallel execution support.
2. **Single-operation mode**: For Steps 1/4 with simplified spinner display,
   liveness indicator, and streaming output.

Features:
- Task list panel with status icons (multi-task mode)
- Spinner with liveness indicator (single-operation mode)
- Real-time log output panel
- Keyboard navigation
- Auto-scroll log following
- Thread-safe state management
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from spec.ui.keyboard import Key, KeyboardReader
from spec.ui.log_buffer import TaskLogBuffer
from spec.utils.console import console
from spec.workflow.events import (
    TaskEvent,
    TaskEventType,
    TaskRunRecord,
    TaskRunStatus,
)

if TYPE_CHECKING:
    pass  # Keep for future type-only imports


# =============================================================================
# Configuration
# =============================================================================

# Default number of log lines to display
DEFAULT_LOG_TAIL_LINES = 15

# Refresh rate for the TUI (times per second)
REFRESH_RATE = 10

# Default number of log lines to display in verbose mode (single-operation mode)
DEFAULT_VERBOSE_LINES = 10

# Maximum width for liveness indicator text (single-operation mode)
MAX_LIVENESS_WIDTH = 70


def _should_use_tui(override: bool | None = None) -> bool:
    """Determine if TUI should be used.

    Args:
        override: Explicit override from CLI. None means auto-detect.

    Returns:
        True if TUI should be used.
    """
    # CLI override takes precedence
    if override is not None:
        return override

    # Check environment variable
    env_setting = os.environ.get("SPECFLOW_TUI", "auto").lower()

    if env_setting == "true":
        return True
    elif env_setting == "false":
        return False
    else:  # auto
        return sys.stdout.isatty()


# =============================================================================
# Panel Components
# =============================================================================


def render_task_list(
    records: list[TaskRunRecord],
    selected_index: int = -1,
    ticket_id: str = "",
    parallel_mode: bool = False,
    spinners: dict[int, Spinner] | None = None,
) -> Panel:
    """Render the task list panel with parallel execution support.

    Args:
        records: List of task run records.
        selected_index: Index of currently selected task (-1 for none).
        ticket_id: Ticket ID for header display.
        parallel_mode: Whether parallel execution mode is enabled.
        spinners: Optional cache of spinner objects keyed by task index.
            If provided, spinners are reused to maintain animation state.

    Returns:
        Rich Panel containing the task table.
    """
    table = Table(
        show_header=False,
        box=None,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Status", width=3)
    table.add_column("Task", ratio=1)
    table.add_column("Duration", width=10, justify="right")

    running_count = sum(1 for r in records if r.status == TaskRunStatus.RUNNING)

    for i, record in enumerate(records):
        # Status icon with color
        icon = record.get_status_icon()
        color = record.get_status_color()

        # Determine status cell: use cached spinner for running tasks, static Text otherwise.
        # IMPORTANT: Do NOT instantiate a new Spinner("dots") here if missing from cache,
        # as Rich's Spinner tracks an internal frame counter that resets on instantiation.
        # Creating a new Spinner each render cycle would freeze the animation at frame 0.
        # Spinners are created in _handle_task_started and removed in _handle_task_finished.
        # Check status first to skip dictionary lookup for non-running tasks.
        cached_spinner = (
            spinners.get(record.task_index)
            if record.status == TaskRunStatus.RUNNING and spinners
            else None
        )
        # Use cached spinner if available; otherwise fall back to static Text icon.
        # For RUNNING tasks without a cached spinner (rare race condition), the icon
        # is "⟳" which clearly indicates a loading/in-progress state.
        status_cell: Spinner | Text = cached_spinner if cached_spinner else Text(icon, style=color)

        # Task name with optional selection highlight
        name_style = ""
        if i == selected_index:
            name_style = "reverse"
        elif record.status == TaskRunStatus.RUNNING:
            name_style = "bold"

        # Running indicator with parallel support
        name_text = record.task_name
        if record.status == TaskRunStatus.RUNNING and parallel_mode:
            name_text = f"{name_text} ⚡"  # Parallel indicator
        elif record.status == TaskRunStatus.RUNNING:
            name_text = f"{name_text} ← Running"

        # Duration
        duration_text = ""
        if record.status in (TaskRunStatus.RUNNING, TaskRunStatus.SUCCESS, TaskRunStatus.FAILED):
            duration_text = f"[dim]{record.format_duration()}[/dim]"

        table.add_row(
            status_cell,
            Text(name_text, style=name_style),
            Text.from_markup(duration_text),
        )

    # Build header with parallel mode indicator
    total = len(records)
    completed = sum(1 for r in records if r.status == TaskRunStatus.SUCCESS)

    if parallel_mode and running_count > 0:
        header = f"TASKS [{ticket_id}] [{completed}/{total}] [⚡ {running_count} parallel]"
    elif ticket_id:
        header = f"TASKS [{ticket_id}] [{completed}/{total} tasks]"
    else:
        header = f"TASKS [{completed}/{total} tasks]"

    return Panel(
        table,
        title=header,
        border_style="blue",
    )


def render_log_panel(
    log_buffer: TaskLogBuffer | None,
    task_name: str = "",
    follow_mode: bool = True,
    num_lines: int = DEFAULT_LOG_TAIL_LINES,
) -> Panel:
    """Render the log output panel.

    Args:
        log_buffer: Task log buffer to display.
        task_name: Name of the task for the header.
        follow_mode: Whether auto-scroll is enabled.
        num_lines: Number of log lines to show.

    Returns:
        Rich Panel containing log output.
    """
    # Get log lines
    if log_buffer is not None:
        lines = log_buffer.get_tail(num_lines)
    else:
        lines = ["[dim]No log output yet...[/dim]"]

    # Build content
    content = Text()
    for line in lines:
        content.append(line + "\n")

    # Header with follow indicator
    follow_indicator = "[f] follow" if follow_mode else "[f] paused"
    header = f"LOG OUTPUT (Task: {task_name})" if task_name else "LOG OUTPUT"

    return Panel(
        content,
        title=header,
        subtitle=follow_indicator,
        border_style="green" if follow_mode else "yellow",
    )


def render_status_bar(
    running: bool = False,
    verbose_mode: bool = False,
    parallel_mode: bool = False,
    running_count: int = 0,
) -> Text:
    """Render the keyboard shortcuts status bar.

    Args:
        running: Whether a task is currently running.
        verbose_mode: Whether verbose mode is enabled.
        parallel_mode: Whether parallel execution mode is enabled.
        running_count: Number of currently running tasks in parallel mode.

    Returns:
        Rich Text with keyboard shortcuts.
    """
    shortcuts = [
        ("[↑↓]", "Navigate"),
        ("[Enter]", "View logs"),
        ("[f]", "Follow"),
        ("[v]", "Verbose"),
        ("[q]", "Quit"),
    ]

    text = Text()
    for key, action in shortcuts:
        text.append(key, style="bold cyan")
        text.append(f" {action}  ", style="dim")

    if parallel_mode and running_count > 0:
        text.append(f" | ⚡ {running_count} tasks running", style="bold yellow")

    return text


# =============================================================================
# TaskRunnerUI Class
# =============================================================================


@dataclass
class TaskRunnerUI:
    """Unified TUI manager for workflow execution.

    Supports two display modes:
    1. **Multi-task mode** (default): Shows task list with navigation, used for
       Step 3 with multiple tasks and parallel execution support.
    2. **Single-operation mode**: Shows simplified spinner with liveness indicator,
       used for Steps 1/4 with streaming AI output.

    Manages Rich Live display, handles keyboard input,
    and orchestrates layout updates based on task events.

    Attributes:
        ticket_id: Ticket identifier for display.
        records: List of task run records (multi-task mode).
        selected_index: Currently selected task index.
        follow_mode: Whether log auto-scroll is enabled.
        verbose_mode: Whether verbose mode is enabled.
        parallel_mode: Whether multiple tasks can run simultaneously.
        single_operation_mode: If True, use simplified single-spinner display.
        status_message: Message to display next to spinner (single-operation mode).
    """

    ticket_id: str = ""
    records: list[TaskRunRecord] = field(default_factory=list)
    selected_index: int = -1
    follow_mode: bool = True
    verbose_mode: bool = False
    parallel_mode: bool = False  # Multiple tasks can run simultaneously
    # Single-operation mode configuration (for Steps 1/4)
    single_operation_mode: bool = False
    status_message: str = "Processing..."
    _current_task_index: int = -1
    _running_task_indices: set[int] = field(default_factory=set)  # Track parallel tasks
    _live: Live | None = field(default=None, init=False, repr=False)
    _log_dir: Path | None = field(default=None, init=False, repr=False)
    # Single-operation mode state
    _log_buffer: TaskLogBuffer | None = field(default=None, init=False, repr=False)
    _log_path: Path | None = field(default=None, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)
    _latest_output_line: str = field(default="", init=False, repr=False)
    # Keyboard input handling
    _keyboard_reader: KeyboardReader = field(default_factory=KeyboardReader, init=False, repr=False)
    _input_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_input_thread: bool = field(default=False, init=False, repr=False)
    # Background refresh thread for spinner animation
    _refresh_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_refresh_thread: bool = field(default=False, init=False, repr=False)
    # Quit signal for execution loop.
    # WARNING: Do not access directly. Use check_quit_requested() and
    # clear_quit_request() to ensure thread safety.
    _quit_requested: bool = field(default=False, init=False, repr=False)
    # Thread-safe event queue for parallel execution
    _event_queue: queue.Queue = field(default_factory=queue.Queue, init=False, repr=False)
    # Lock for thread-safe refresh operations
    _refresh_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    # Lock for thread-safe state access (selected_index, _running_task_indices, etc.)
    # Uses RLock to support reentrant locking (e.g., methods that call other locked methods)
    _state_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    # Cache for spinner objects to maintain animation state across renders
    _spinners: dict[int, Spinner] = field(default_factory=dict, init=False, repr=False)

    def initialize_records(self, task_names: list[str]) -> None:
        """Initialize task run records from task names.

        Args:
            task_names: List of task names to create records for.
        """
        self.records = [
            TaskRunRecord(task_index=i, task_name=name) for i, name in enumerate(task_names)
        ]
        self._spinners.clear()  # Clear spinner cache for new run

    def set_log_dir(self, log_dir: Path) -> None:
        """Set the log directory for this run (multi-task mode).

        Args:
            log_dir: Path to the log directory.
        """
        self._log_dir = log_dir

    def set_log_path(self, path: Path) -> None:
        """Set log file path and create buffer (single-operation mode).

        Args:
            path: Path to the log file.
        """
        self._log_path = path
        self._log_buffer = TaskLogBuffer(log_path=path)

    def handle_output_line(self, line: str) -> None:
        """Callback for AI output lines (single-operation mode).

        Called for each line of AI output. This method:
        1. Writes the line to the log buffer (file + memory)
        2. Updates the liveness indicator with the latest line
        3. Triggers a display refresh to show the updated liveness text

        Thread-safe: can be called from any thread.

        Args:
            line: A single line of AI output (without trailing newline).
        """
        # Write to log buffer
        if self._log_buffer is not None:
            self._log_buffer.write(line)

        # Update liveness indicator (truncate if too long)
        with self._state_lock:
            if line.strip():
                self._latest_output_line = line

        # Refresh display (already thread-safe via _refresh_lock)
        self.refresh()

    def set_parallel_mode(self, enabled: bool) -> None:
        """Enable or disable parallel execution display mode.

        Args:
            enabled: Whether parallel mode should be enabled.
        """
        self.parallel_mode = enabled

    def get_record(self, task_index: int) -> TaskRunRecord | None:
        """Get a task record by index.

        Args:
            task_index: Zero-based task index.

        Returns:
            TaskRunRecord or None if not found.
        """
        if 0 <= task_index < len(self.records):
            return self.records[task_index]
        return None

    def get_current_log_buffer(self) -> TaskLogBuffer | None:
        """Get the log buffer for the currently selected or running task.

        Returns:
            TaskLogBuffer or None.
        """
        with self._state_lock:
            # Prefer selected task, fall back to running task
            index = self.selected_index if self.selected_index >= 0 else self._current_task_index

            # In parallel mode, if no selection, pick first running task
            if index < 0 and self.parallel_mode and self._running_task_indices:
                index = min(self._running_task_indices)

            # Access record inside lock to avoid check-then-act race
            record = self.get_record(index)
            return record.log_buffer if record else None

    def get_current_task_name(self) -> str:
        """Get the name of the currently displayed task.

        Returns:
            Task name or empty string.
        """
        with self._state_lock:
            index = self.selected_index if self.selected_index >= 0 else self._current_task_index

            # In parallel mode, if no selection, pick first running task
            if index < 0 and self.parallel_mode and self._running_task_indices:
                index = min(self._running_task_indices)

            # Access record inside lock to avoid check-then-act race
            record = self.get_record(index)
            return record.task_name if record else ""

    def _get_running_count(self) -> int:
        """Get the number of currently running tasks.

        Returns:
            Number of running tasks (from set in parallel mode, or 1/0 in sequential).
        """
        with self._state_lock:
            if self.parallel_mode:
                return len(self._running_task_indices)
            return 1 if self._current_task_index >= 0 else 0

    def _find_next_running_task(self, finished_index: int) -> int:
        """Find the next running task index using 'Next Neighbor' logic.

        Prefers the next running task after the finished one (cyclic/modulo).
        This provides a less jarring UX than always jumping to the first task.

        For example, if Task 3 finishes and Tasks 1, 4, 5 are running:
        - Returns 4 (next after 3)

        If Task 5 finishes and Tasks 1, 2 are running:
        - Returns 1 (wraps around to beginning)

        Args:
            finished_index: Index of the task that just finished.

        Returns:
            Index of the next running task to select.

        Precondition:
            self._running_task_indices must not be empty.
            Caller must hold _state_lock.
        """
        # NOTE: Caller must hold _state_lock
        # Find running tasks with indices greater than finished_index
        later_tasks = [i for i in self._running_task_indices if i > finished_index]
        if later_tasks:
            # Pick the smallest index among later tasks (closest neighbor)
            return min(later_tasks)
        # No later tasks, wrap around to the beginning
        return min(self._running_task_indices)

    def _render_layout(self) -> Group:
        """Render the complete TUI layout.

        Renders different layouts based on mode:
        - Single-operation mode: Simple spinner with liveness indicator
        - Multi-task mode: Task list with log panel

        Returns:
            Rich Group containing all panels.
        """
        # Single-operation mode: simplified layout
        if self.single_operation_mode:
            return self._render_single_operation_layout()

        # Multi-task mode: full layout with task list
        return self._render_multi_task_layout()

    def _render_single_operation_layout(self) -> Group:
        """Render simplified layout for single-operation mode.

        Returns:
            Rich Group with spinner panel and status bar.
        """
        with self._state_lock:
            verbose_mode_snapshot = self.verbose_mode
            latest_line = self._latest_output_line

        # Build spinner line with elapsed time
        elapsed = self._format_elapsed_time()

        elements: list[Panel | Text] = []

        if verbose_mode_snapshot:
            elements.append(self._render_single_op_verbose_panel(elapsed))
        else:
            elements.append(self._render_single_op_normal_panel(elapsed, latest_line))

        elements.append(self._render_single_op_status_bar())

        return Group(*elements)

    def _render_multi_task_layout(self) -> Group:
        """Render full layout for multi-task mode.

        Returns:
            Rich Group with task panel, log panel, and status bar.
        """
        # Snapshot ALL state under lock once to avoid races and redundant locking
        with self._state_lock:
            selected_idx = self.selected_index
            current_task_idx = self._current_task_index
            parallel_mode_snapshot = self.parallel_mode
            follow_mode_snapshot = self.follow_mode
            verbose_mode_snapshot = self.verbose_mode

            # Calculate running_count directly here to avoid re-locking
            if self.parallel_mode:
                running_count = len(self._running_task_indices)
            else:
                running_count = 1 if self._current_task_index >= 0 else 0

            # Snapshot log buffer and task name here to avoid redundant lock acquisition
            # (get_current_log_buffer and get_current_task_name also acquire _state_lock)
            display_index = selected_idx if selected_idx >= 0 else current_task_idx
            if display_index < 0 and self.parallel_mode and self._running_task_indices:
                display_index = min(self._running_task_indices)
            display_record = self.get_record(display_index)
            current_log_buffer = display_record.log_buffer if display_record else None
            current_task_name = display_record.task_name if display_record else ""

        task_panel = render_task_list(
            self.records,
            selected_index=selected_idx,
            ticket_id=self.ticket_id,
            parallel_mode=parallel_mode_snapshot,
            spinners=self._spinners,
        )

        log_panel = render_log_panel(
            current_log_buffer,
            task_name=current_task_name,
            follow_mode=follow_mode_snapshot,
        )

        status_bar = render_status_bar(
            running=current_task_idx >= 0 or running_count > 0,
            verbose_mode=verbose_mode_snapshot,
            parallel_mode=parallel_mode_snapshot,
            running_count=running_count,
        )

        return Group(task_panel, log_panel, status_bar)

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

    def _render_single_op_normal_panel(self, elapsed: str, latest_line: str) -> Panel:
        """Render the normal (non-verbose) panel for single-operation mode.

        Args:
            elapsed: Formatted elapsed time string.
            latest_line: Latest output line for liveness indicator.

        Returns:
            Rich Panel with spinner, status, and liveness indicator.
        """
        content_lines = []

        # Main status line
        status_text = Text()
        status_text.append("  ")
        status_text.append(self.status_message, style="bold")
        status_text.append(f"  {elapsed}", style="dim")
        content_lines.append(status_text)

        # Empty line
        content_lines.append(Text())

        # Liveness indicator
        if latest_line:
            truncated = self._truncate_line(latest_line.strip())
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

        # Build header - use ticket_id if provided
        header = f"⟳ {self.ticket_id}" if self.ticket_id else "⟳ Operation"

        return Panel(
            content,
            title=header,
            border_style="blue",
        )

    def _render_single_op_verbose_panel(self, elapsed: str) -> Panel:
        """Render the verbose panel for single-operation mode.

        Args:
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

        # Build header
        header = f"⟳ {self.ticket_id}" if self.ticket_id else "⟳ Operation"

        return Panel(
            content,
            title=header,
            border_style="green",
        )

    def _render_single_op_status_bar(self) -> Text:
        """Render the keyboard shortcuts status bar for single-operation mode.

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

    def start(self) -> None:
        """Start the Live display and keyboard input handling."""
        # Initialize start time for elapsed time tracking
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
            auto_refresh=False,  # We rely entirely on manual background refresh
            refresh_per_second=REFRESH_RATE,
            vertical_overflow="visible",
        )
        self._live.start(refresh=True)

        # Start background refresh thread for smooth spinner animation.
        # This ensures the spinner keeps animating even when the main thread
        # is blocked waiting for subprocess output (both sequential and parallel modes).
        # The refresh loop runs at ~10 Hz with time.sleep() to yield the GIL.
        self._stop_refresh_thread = False
        self._refresh_thread = threading.Thread(target=self._background_refresh_loop, daemon=True)
        self._refresh_thread.start()

    def stop(self) -> None:
        """Stop the Live display and keyboard input handling."""
        # Stop background refresh thread
        self._stop_refresh_thread = True
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=0.5)
            self._refresh_thread = None

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

        # Close log buffer (single-operation mode)
        if self._log_buffer is not None:
            self._log_buffer.close()
            self._log_buffer = None

    def _background_refresh_loop(self) -> None:
        """Background thread loop for refreshing the display.

        Runs at ~10 Hz to ensure smooth spinner animation and responsive
        log updates while the main thread is blocked (e.g., waiting for
        subprocess output in sequential mode, or wait() in parallel mode).
        Uses time.sleep() to yield the GIL and prevent UI starvation.
        """
        refresh_interval = 0.1  # 10 Hz refresh rate
        while not self._stop_refresh_thread:
            time.sleep(refresh_interval)
            if not self._stop_refresh_thread:
                self.refresh()

    def refresh(self) -> None:
        """Refresh the display with current state.

        Drains the event queue first (for thread-safe parallel mode),
        then updates the Live display. Thread-safe via _refresh_lock.
        """
        with self._refresh_lock:
            self._drain_event_queue()
            if self._live is not None:
                self._live.update(self._render_layout(), refresh=True)

    def post_event(self, event: TaskEvent) -> None:
        """Thread-safe: push event to queue (called from worker threads).

        Args:
            event: The task event to queue for processing.
        """
        self._event_queue.put(event)

    def _drain_event_queue(self) -> None:
        """Main thread: process all pending events from the queue."""
        while True:
            try:
                event = self._event_queue.get_nowait()
                self._apply_event(event)
            except queue.Empty:
                break

    def __enter__(self) -> TaskRunnerUI:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        self.stop()

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
        if self.single_operation_mode:
            # Single-operation mode: limited keyboard handling
            if key == Key.ENTER:
                self._open_log_in_pager()
            elif key == Key.V:
                self._toggle_verbose_mode()
            elif key == Key.Q:
                self._handle_quit()
            return

        # Multi-task mode: full keyboard handling
        if key == Key.UP or key == Key.K:
            self._move_selection_up()
        elif key == Key.DOWN or key == Key.J:
            self._move_selection_down()
        elif key == Key.ENTER:
            self._open_log_in_pager()
        elif key == Key.F:
            self._toggle_follow_mode()
        elif key == Key.V:
            self._toggle_verbose_mode()
        elif key == Key.L:
            self._show_log_path()
        elif key == Key.Q:
            self._handle_quit()

    def _move_selection_up(self) -> None:
        """Move task selection up."""
        if len(self.records) == 0:
            return
        with self._state_lock:
            if self.selected_index < 0:
                # In parallel mode, start from first running task or first task
                if self.parallel_mode and self._running_task_indices:
                    self.selected_index = min(self._running_task_indices)
                else:
                    self.selected_index = max(0, self._current_task_index)
            elif self.selected_index > 0:
                self.selected_index -= 1
        self.refresh()

    def _move_selection_down(self) -> None:
        """Move task selection down."""
        if len(self.records) == 0:
            return
        with self._state_lock:
            if self.selected_index < 0:
                # In parallel mode, start from first running task or first task
                if self.parallel_mode and self._running_task_indices:
                    self.selected_index = min(self._running_task_indices)
                else:
                    self.selected_index = max(0, self._current_task_index)
            elif self.selected_index < len(self.records) - 1:
                self.selected_index += 1
        self.refresh()

    def _toggle_follow_mode(self) -> None:
        """Toggle log auto-scroll mode."""
        with self._state_lock:
            self.follow_mode = not self.follow_mode
        self.refresh()

    def _toggle_verbose_mode(self) -> None:
        """Toggle verbose mode (expanded log panel)."""
        with self._state_lock:
            self.verbose_mode = not self.verbose_mode
        self.refresh()

    def _show_log_path(self) -> None:
        """Show the log file path for the selected task."""
        with self._state_lock:
            index = self.selected_index if self.selected_index >= 0 else self._current_task_index
        record = self.get_record(index)
        if record and record.log_buffer and record.log_buffer.log_path:
            # This will be shown in the next refresh via a message
            # For now, just refresh to indicate the key was received
            self.refresh()

    def _open_log_in_pager(self) -> None:
        """Open the full log file in system pager."""
        log_path: Path | None = None

        if self.single_operation_mode:
            # Single-operation mode: use _log_path directly
            log_path = self._log_path
        else:
            # Multi-task mode: get log path from selected record
            with self._state_lock:
                index = (
                    self.selected_index if self.selected_index >= 0 else self._current_task_index
                )
            record = self.get_record(index)
            if record and record.log_buffer and record.log_buffer.log_path:
                log_path = record.log_buffer.log_path

        if log_path and log_path.exists():
            # Temporarily stop the TUI to show pager
            if self._live is not None:
                self._live.stop()
            try:
                # Use 'less' or 'more' as pager
                pager = os.environ.get("PAGER", "less")
                subprocess.run([pager, str(log_path)])
            finally:
                # Restart the TUI
                if self._live is not None:
                    self._live.start(refresh=True)

    def _handle_quit(self) -> None:
        """Handle quit request."""
        # Set quit flag under lock for consistency
        with self._state_lock:
            self._quit_requested = True

    def check_quit_requested(self) -> bool:
        """Thread-safe check for quit request.

        Returns:
            True if quit was requested, False otherwise.
        """
        with self._state_lock:
            return self._quit_requested

    def clear_quit_request(self) -> None:
        """Thread-safe clear of quit request flag."""
        with self._state_lock:
            self._quit_requested = False

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def handle_event(self, event: TaskEvent) -> None:
        """Handle a task event and update UI accordingly (sequential mode).

        For sequential mode: applies the event and refreshes immediately.
        For parallel mode: use post_event() to queue events, then refresh()
        to drain the queue on the main thread.

        Args:
            event: The task event to process.
        """
        self._apply_event(event)
        self.refresh()

    def _apply_event(self, event: TaskEvent) -> None:
        """Apply event to TUI state (main thread only).

        This is the core event processing logic, extracted from handle_event
        to support both sequential mode (direct call) and parallel mode
        (called from _drain_event_queue).

        Args:
            event: The task event to apply.
        """
        if event.event_type == TaskEventType.TASK_STARTED:
            self._handle_task_started(event)
        elif event.event_type == TaskEventType.TASK_OUTPUT:
            self._handle_task_output(event)
        elif event.event_type == TaskEventType.TASK_FINISHED:
            self._handle_task_finished(event)
        elif event.event_type == TaskEventType.RUN_FINISHED:
            self._handle_run_finished(event)

    def _handle_task_started(self, event: TaskEvent) -> None:
        """Handle TASK_STARTED event with parallel support.

        Args:
            event: The task started event.
        """
        record = self.get_record(event.task_index)
        if record:
            record.status = TaskRunStatus.RUNNING
            record.start_time = event.timestamp

            # Create the spinner instance here (Event-Driven)
            # This ensures the spinner is created once and maintains its animation state
            self._spinners[event.task_index] = Spinner("dots", style=record.get_status_color())

            with self._state_lock:
                if self.parallel_mode:
                    self._running_task_indices.add(event.task_index)
                    # Auto-select first task if nothing selected yet
                    if self.selected_index < 0:
                        self.selected_index = event.task_index
                else:
                    self._current_task_index = event.task_index

    def _handle_task_output(self, event: TaskEvent) -> None:
        """Handle TASK_OUTPUT event.

        Args:
            event: The task output event.
        """
        record = self.get_record(event.task_index)
        if record and record.log_buffer and event.data:
            line = event.data.get("line", "")
            record.log_buffer.write(line)

    def _handle_task_finished(self, event: TaskEvent) -> None:
        """Handle TASK_FINISHED event with parallel support and tri-state status.

        Args:
            event: The task finished event.
        """
        record = self.get_record(event.task_index)
        if record:
            record.end_time = event.timestamp
            if event.data:
                # Support tri-state status: "success", "failed", "skipped"
                status_str = event.data.get("status")
                if status_str == "success":
                    record.status = TaskRunStatus.SUCCESS
                elif status_str == "skipped":
                    record.status = TaskRunStatus.SKIPPED
                else:
                    record.status = TaskRunStatus.FAILED
                    record.error = event.data.get("error")

            # CRITICAL: Close log buffer for ALL statuses (success, failed, skipped)
            # Best-effort cleanup - catch exceptions to avoid breaking event processing
            if record.log_buffer is not None:
                try:
                    record.log_buffer.close()
                except Exception:
                    pass  # Best-effort cleanup
                record.log_buffer = None

            # Cleanup spinner to prevent stale state
            self._spinners.pop(event.task_index, None)

            with self._state_lock:
                if self.parallel_mode:
                    self._running_task_indices.discard(event.task_index)
                    # Auto-switch to another running task if the finished task was selected
                    # and follow_mode is enabled. This keeps the UI showing live output.
                    # Uses "Next Neighbor" logic: prefer the next running task after the
                    # finished one, wrapping around if necessary for less jarring UX.
                    if (
                        self.follow_mode
                        and self.selected_index == event.task_index
                        and self._running_task_indices
                    ):
                        self.selected_index = self._find_next_running_task(event.task_index)

    def _handle_run_finished(self, event: TaskEvent) -> None:
        """Handle RUN_FINISHED event.

        Args:
            event: The run finished event.
        """
        with self._state_lock:
            self._current_task_index = -1

    def mark_remaining_skipped(self, from_index: int) -> None:
        """Mark remaining tasks as skipped (for fail_fast).

        Args:
            from_index: Index from which to start marking tasks as skipped.
        """
        for i in range(from_index, len(self.records)):
            record = self.records[i]
            if record.status == TaskRunStatus.PENDING:
                record.status = TaskRunStatus.SKIPPED
        self.refresh()

    def print_summary(self, success: bool | None = None) -> None:
        """Print execution summary after TUI stops.

        Args:
            success: For single-operation mode, whether operation succeeded.
                     For multi-task mode, ignored (success determined from records).
        """
        if self.single_operation_mode:
            # Single-operation mode summary
            elapsed = self._format_elapsed_time()
            console.print()
            if success:
                console.print(f"[green]✓[/green] Operation completed in {elapsed}")
            elif success is False:
                console.print(f"[red]✗[/red] Operation failed after {elapsed}")
            else:
                console.print(f"[yellow]⊘[/yellow] Operation cancelled after {elapsed}")
            if self._log_path:
                console.print(f"[dim]Logs saved to: {self._log_path}[/dim]")
            return

        # Multi-task mode summary
        success_count = sum(1 for r in self.records if r.status == TaskRunStatus.SUCCESS)
        failed_count = sum(1 for r in self.records if r.status == TaskRunStatus.FAILED)
        skipped_count = sum(1 for r in self.records if r.status == TaskRunStatus.SKIPPED)

        console.print()
        console.print("[bold]Execution Complete[/bold]")
        console.print(f"  [green]✓ Succeeded:[/green] {success_count}")
        if failed_count > 0:
            console.print(f"  [red]✗ Failed:[/red] {failed_count}")
        if skipped_count > 0:
            console.print(f"  [yellow]⊘ Skipped:[/yellow] {skipped_count}")

        if self._log_dir:
            console.print()
            console.print(f"[dim]Logs saved to: {self._log_dir}[/dim]")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TaskRunnerUI",
    "render_task_list",
    "render_log_panel",
    "render_status_bar",
    "_should_use_tui",
    "DEFAULT_LOG_TAIL_LINES",
    "DEFAULT_VERBOSE_LINES",
    "MAX_LIVENESS_WIDTH",
    "REFRESH_RATE",
]
