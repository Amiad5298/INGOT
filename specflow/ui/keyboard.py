"""Keyboard input handling for TUI.

This module provides non-blocking keyboard input reading for the TUI.
Uses termios/tty on Unix systems for raw terminal input.
"""

from __future__ import annotations

import os
import select
import sys
from enum import Enum
from typing import Optional

# Check if we're on a Unix-like system
_IS_UNIX = hasattr(sys.stdin, "fileno") and os.name != "nt"

if _IS_UNIX:
    import termios
    import tty


class Key(Enum):
    """Recognized key codes."""

    UP = "up"
    DOWN = "down"
    ENTER = "enter"
    ESCAPE = "escape"
    # Letters
    Q = "q"
    F = "f"
    V = "v"
    J = "j"
    K = "k"
    L = "l"
    # Unknown
    UNKNOWN = "unknown"


# Escape sequence mappings for arrow keys
_ESCAPE_SEQUENCES = {
    "[A": Key.UP,      # Arrow up
    "[B": Key.DOWN,    # Arrow down
    "OA": Key.UP,      # Arrow up (alternate)
    "OB": Key.DOWN,    # Arrow down (alternate)
}

# Single character mappings
_CHAR_MAPPINGS = {
    "\r": Key.ENTER,
    "\n": Key.ENTER,
    "\x1b": Key.ESCAPE,  # Just escape alone
    "q": Key.Q,
    "Q": Key.Q,
    "f": Key.F,
    "F": Key.F,
    "v": Key.V,
    "V": Key.V,
    "j": Key.J,
    "J": Key.J,
    "k": Key.K,
    "K": Key.K,
    "l": Key.L,
    "L": Key.L,
}


class KeyboardReader:
    """Non-blocking keyboard reader for TUI.

    Uses raw terminal mode on Unix to read individual keypresses
    without waiting for Enter.

    Usage:
        reader = KeyboardReader()
        reader.start()
        try:
            while running:
                key = reader.read_key(timeout=0.1)
                if key:
                    handle_key(key)
        finally:
            reader.stop()
    """

    def __init__(self) -> None:
        """Initialize the keyboard reader."""
        self._old_settings: Optional[list] = None
        self._is_started: bool = False

    def start(self) -> None:
        """Enter raw terminal mode to read individual keypresses."""
        if not _IS_UNIX:
            return

        if self._is_started:
            return

        try:
            # Save current terminal settings
            self._old_settings = termios.tcgetattr(sys.stdin.fileno())
            # Set raw mode (disable line buffering and echo)
            tty.setcbreak(sys.stdin.fileno())
            self._is_started = True
        except (termios.error, OSError):
            # Not a TTY or other error
            self._old_settings = None

    def stop(self) -> None:
        """Restore terminal to normal mode."""
        if not _IS_UNIX:
            return

        if self._old_settings is not None:
            try:
                termios.tcsetattr(
                    sys.stdin.fileno(),
                    termios.TCSADRAIN,
                    self._old_settings,
                )
            except (termios.error, OSError):
                pass
            self._old_settings = None
        self._is_started = False

    def read_key(self, timeout: float = 0.0) -> Optional[Key]:
        """Read a single keypress without blocking.

        Args:
            timeout: Maximum time to wait for input (seconds). 0 = non-blocking.

        Returns:
            Key enum if a key was pressed, None otherwise.
        """
        if not _IS_UNIX or not self._is_started:
            return None

        try:
            # Check if input is available
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready:
                return None

            # Read the first character
            char = sys.stdin.read(1)
            if not char:
                return None

            # Handle escape sequences (arrow keys, etc.)
            if char == "\x1b":
                return self._read_escape_sequence()

            # Map single characters
            return _CHAR_MAPPINGS.get(char, Key.UNKNOWN)

        except (OSError, select.error):
            return None

    def _read_escape_sequence(self) -> Key:
        """Read and decode an escape sequence."""
        # Check for more characters (escape sequences)
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if not ready:
            # Just escape key alone
            return Key.ESCAPE

        # Read the sequence
        seq = ""
        for _ in range(3):  # Max sequence length
            ready, _, _ = select.select([sys.stdin], [], [], 0.01)
            if not ready:
                break
            seq += sys.stdin.read(1)

        return _ESCAPE_SEQUENCES.get(seq, Key.UNKNOWN)

    def __enter__(self) -> "KeyboardReader":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()

