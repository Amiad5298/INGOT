"""Task execution events and run records for Step 3 TUI.

This module provides:
- TaskEventType: Enum of event types emitted during task execution
- TaskEvent: Dataclass representing a single event
- TaskRunStatus: Enum of task execution states
- TaskRunRecord: Dataclass tracking per-task execution state
- Utility functions for log file naming and formatting
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from spec.ui.log_buffer import TaskLogBuffer


class TaskEventType(Enum):
    """Types of events emitted during task execution."""

    RUN_STARTED = "run_started"
    TASK_STARTED = "task_started"
    TASK_OUTPUT = "task_output"
    TASK_FINISHED = "task_finished"
    RUN_FINISHED = "run_finished"


@dataclass
class TaskEvent:
    """Event emitted during task execution.

    Attributes:
        event_type: The type of event.
        task_index: Zero-based index of the task (0 for run-level events).
        task_name: Name of the task (empty for run-level events).
        timestamp: Unix timestamp when the event occurred.
        data: Optional additional data (success, output_line, duration, etc.).
    """

    event_type: TaskEventType
    task_index: int
    task_name: str
    timestamp: float
    data: dict | None = None


# Type alias for event callback functions
TaskEventCallback = Callable[[TaskEvent], None]


class TaskRunStatus(Enum):
    """Status states for task execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# Status display configuration
_STATUS_ICONS: dict[TaskRunStatus, str] = {
    TaskRunStatus.PENDING: "○",
    TaskRunStatus.RUNNING: "⟳",
    TaskRunStatus.SUCCESS: "✓",
    TaskRunStatus.FAILED: "✗",
    TaskRunStatus.SKIPPED: "⊘",
}

_STATUS_COLORS: dict[TaskRunStatus, str] = {
    TaskRunStatus.PENDING: "dim white",
    TaskRunStatus.RUNNING: "bold cyan",
    TaskRunStatus.SUCCESS: "bold green",
    TaskRunStatus.FAILED: "bold red",
    TaskRunStatus.SKIPPED: "yellow",
}


@dataclass
class TaskRunRecord:
    """Record tracking the execution state of a single task.

    Attributes:
        task_index: Zero-based index of the task.
        task_name: Display name of the task.
        status: Current execution status.
        start_time: Unix timestamp when execution started.
        end_time: Unix timestamp when execution ended.
        log_buffer: Optional log buffer for capturing output.
        error: Error message if task failed.
    """

    task_index: int
    task_name: str
    status: TaskRunStatus = TaskRunStatus.PENDING
    start_time: float | None = None
    end_time: float | None = None
    log_buffer: TaskLogBuffer | None = field(default=None, repr=False)
    error: str | None = None

    @property
    def duration(self) -> float | None:
        """Calculate duration in seconds.

        Returns:
            Duration if task has ended, None otherwise.
        """
        if self.start_time is None:
            return None
        if self.end_time is not None:
            return self.end_time - self.start_time
        return None

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time for running or completed tasks.

        Returns:
            Elapsed time in seconds. Returns 0 if not started.
        """
        if self.start_time is None:
            return 0.0
        if self.end_time is not None:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def get_status_icon(self) -> str:
        """Get Unicode icon for current status."""
        return _STATUS_ICONS.get(self.status, "?")

    def get_status_color(self) -> str:
        """Get Rich color name for current status."""
        return _STATUS_COLORS.get(self.status, "white")

    def format_duration(self) -> str:
        """Format elapsed time for display.

        Returns:
            Formatted duration string (e.g., "1.2s", "1m 23s").
        """
        elapsed = self.elapsed_time
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        minutes = int(elapsed // 60)
        seconds = elapsed % 60
        return f"{minutes}m {seconds:.0f}s"


# =============================================================================
# Utility Functions
# =============================================================================


def slugify_task_name(name: str, max_length: int = 40) -> str:
    """Convert task name to filesystem-safe slug.

    Args:
        name: The task name to slugify.
        max_length: Maximum length of the resulting slug.

    Returns:
        Lowercase slug with special characters replaced by underscores.

    Example:
        >>> slugify_task_name("Implement user authentication!")
        'implement_user_authentication'
    """
    # Convert to lowercase
    slug = name.lower()
    # Replace non-alphanumeric characters with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    # Remove leading/trailing underscores
    slug = slug.strip("_")
    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)
    # Truncate to max length, avoiding mid-word cuts
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("_", 1)[0]
    return slug


def format_log_filename(task_index: int, task_name: str) -> str:
    """Generate log filename for a task.

    Args:
        task_index: Zero-based index of the task.
        task_name: Display name of the task.

    Returns:
        Filename in format: task_001_task_name_slug.log

    Example:
        >>> format_log_filename(0, "Implement authentication")
        'task_001_implement_authentication.log'
    """
    slug = slugify_task_name(task_name)
    return f"task_{task_index + 1:03d}_{slug}.log"


def format_timestamp() -> str:
    """Get current timestamp formatted for log lines.

    Returns:
        Timestamp string in format: [YYYY-MM-DD HH:MM:SS.mmm]

    Example:
        >>> format_timestamp()
        '[2026-01-11 12:34:56.123]'
    """
    now = datetime.now()
    return now.strftime("[%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}]"


def format_run_directory() -> str:
    """Get timestamp string for run directory naming.

    Returns:
        Timestamp string in format: YYYYMMDD_HHMMSS
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# =============================================================================
# Event Factory Functions
# =============================================================================


def create_run_started_event(total_tasks: int) -> TaskEvent:
    """Create a RUN_STARTED event.

    Args:
        total_tasks: Total number of tasks in the run.

    Returns:
        TaskEvent with RUN_STARTED type.
    """
    return TaskEvent(
        event_type=TaskEventType.RUN_STARTED,
        task_index=0,
        task_name="",
        timestamp=time.time(),
        data={"total_tasks": total_tasks},
    )


def create_task_started_event(task_index: int, task_name: str) -> TaskEvent:
    """Create a TASK_STARTED event.

    Args:
        task_index: Zero-based index of the task.
        task_name: Name of the task.

    Returns:
        TaskEvent with TASK_STARTED type.
    """
    return TaskEvent(
        event_type=TaskEventType.TASK_STARTED,
        task_index=task_index,
        task_name=task_name,
        timestamp=time.time(),
    )


def create_task_output_event(task_index: int, task_name: str, line: str) -> TaskEvent:
    """Create a TASK_OUTPUT event.

    Args:
        task_index: Zero-based index of the task.
        task_name: Name of the task.
        line: Output line from the task.

    Returns:
        TaskEvent with TASK_OUTPUT type.
    """
    return TaskEvent(
        event_type=TaskEventType.TASK_OUTPUT,
        task_index=task_index,
        task_name=task_name,
        timestamp=time.time(),
        data={"line": line},
    )


def create_task_finished_event(
    task_index: int,
    task_name: str,
    status: Literal["success", "failed", "skipped"],
    duration: float,
    error: str | None = None,
) -> TaskEvent:
    """Create a TASK_FINISHED event.

    Args:
        task_index: Zero-based index of the task.
        task_name: Name of the task.
        status: Task completion status - one of "success", "failed", "skipped".
        duration: Task duration in seconds.
        error: Optional error message if task failed.

    Returns:
        TaskEvent with TASK_FINISHED type.
    """
    return TaskEvent(
        event_type=TaskEventType.TASK_FINISHED,
        task_index=task_index,
        task_name=task_name,
        timestamp=time.time(),
        data={"status": status, "duration": duration, "error": error},
    )


def create_run_finished_event(
    total_tasks: int,
    success_count: int,
    failed_count: int,
    skipped_count: int,
) -> TaskEvent:
    """Create a RUN_FINISHED event.

    Args:
        total_tasks: Total number of tasks.
        success_count: Number of successful tasks.
        failed_count: Number of failed tasks.
        skipped_count: Number of skipped tasks.

    Returns:
        TaskEvent with RUN_FINISHED type.
    """
    return TaskEvent(
        event_type=TaskEventType.RUN_FINISHED,
        task_index=0,
        task_name="",
        timestamp=time.time(),
        data={
            "total_tasks": total_tasks,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
        },
    )


__all__ = [
    # Event types
    "TaskEventType",
    "TaskEvent",
    "TaskEventCallback",
    # Run status
    "TaskRunStatus",
    "TaskRunRecord",
    # Utility functions
    "slugify_task_name",
    "format_log_filename",
    "format_timestamp",
    "format_run_directory",
    # Event factories
    "create_run_started_event",
    "create_task_started_event",
    "create_task_output_event",
    "create_task_finished_event",
    "create_run_finished_event",
]

