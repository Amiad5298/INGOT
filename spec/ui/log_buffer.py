"""Memory-efficient log buffer with file backing.

This module provides TaskLogBuffer for capturing task output without
flooding memory. Lines are written to disk immediately and a sliding
window buffer keeps recent lines available for display.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from types import TracebackType


@dataclass
class TaskLogBuffer:
    """Memory-efficient log buffer with file backing.

    Writes all output to a log file while keeping only the last N lines
    in memory for efficient tail display. Uses a deque with fixed maxlen
    to bound memory usage.

    Attributes:
        log_path: Path to the log file.
        tail_lines: Maximum number of lines to keep in memory buffer.

    Example:
        >>> with TaskLogBuffer(Path("/tmp/task.log")) as buffer:
        ...     buffer.write("Starting task...")
        ...     buffer.write("Processing...")
        ...     print(buffer.get_tail(2))
        ['Starting task...', 'Processing...']
    """

    log_path: Path
    tail_lines: int = 100
    _buffer: collections.deque[str] = field(
        default_factory=lambda: collections.deque(maxlen=100),
        init=False,
        repr=False,
    )
    _file_handle: TextIO | None = field(default=None, init=False, repr=False)
    _line_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize buffer with correct maxlen based on tail_lines."""
        # Re-create deque with user-specified maxlen
        self._buffer = collections.deque(maxlen=self.tail_lines)

    def _ensure_file_open(self) -> None:
        """Open the log file if not already open.

        Creates parent directories if they don't exist.
        """
        if self._file_handle is None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(self.log_path, "a", encoding="utf-8")

    def write(self, line: str, *, with_timestamp: bool = True) -> None:
        """Write a line to the log file and in-memory buffer.

        Args:
            line: The line to write (without trailing newline).
            with_timestamp: If True, prepend timestamp to file output.
        """
        self._ensure_file_open()

        # Format line for file output
        if with_timestamp:
            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S.%f]")[:-3] + "]"
            file_line = f"{timestamp} {line}"
        else:
            file_line = line

        # Write to file
        assert self._file_handle is not None
        self._file_handle.write(f"{file_line}\n")
        self._file_handle.flush()

        # Add to in-memory buffer (without timestamp for cleaner display)
        self._buffer.append(line)
        self._line_count += 1

    def write_raw(self, line: str) -> None:
        """Write a line without timestamp.

        Args:
            line: The line to write (without trailing newline).
        """
        self.write(line, with_timestamp=False)

    def get_tail(self, n: int = 15) -> list[str]:
        """Get the last n lines from the in-memory buffer.

        Args:
            n: Number of lines to return. Returns all if n > buffer size.

        Returns:
            List of the last n lines (or fewer if buffer has less).
        """
        if n >= len(self._buffer):
            return list(self._buffer)
        return list(self._buffer)[-n:]

    @property
    def line_count(self) -> int:
        """Total number of lines written."""
        return self._line_count

    def close(self) -> None:
        """Close the file handle.

        Safe to call multiple times (idempotent).
        """
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None

    def __enter__(self) -> TaskLogBuffer:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager, ensuring file is closed."""
        self.close()


__all__ = ["TaskLogBuffer"]

