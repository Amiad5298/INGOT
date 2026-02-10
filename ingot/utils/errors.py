"""Custom exceptions and exit codes for INGOT.

This module defines the exit codes and exception hierarchy used throughout
the application, matching the original Bash script's error handling.
"""

import re
from enum import IntEnum
from typing import ClassVar


class ExitCode(IntEnum):
    """Exit codes matching the original Bash script.

    These codes are used for consistent error reporting and can be
    checked by calling scripts or CI systems.
    """

    SUCCESS = 0
    GENERAL_ERROR = 1
    AUGGIE_NOT_INSTALLED = 2
    PLATFORM_NOT_CONFIGURED = 3  # Platform not configured
    USER_CANCELLED = 4
    GIT_ERROR = 5


class IngotError(Exception):
    """Base exception for INGOT errors.

    All custom exceptions in this application should inherit from this class.
    Each exception type has an associated exit code for proper error reporting.

    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.GENERAL_ERROR

    def __init__(self, message: str, exit_code: ExitCode | None = None) -> None:
        """Initialize the exception."""
        super().__init__(message)
        self._exit_code = exit_code

    @property
    def exit_code(self) -> ExitCode:
        """Get the exit code for this exception."""
        if self._exit_code is not None:
            return self._exit_code
        return self.__class__._default_exit_code


class AuggieNotInstalledError(IngotError):
    """Auggie CLI is not installed or version is too old.

    Raised when:
    - The 'auggie' command is not found in PATH
    - The installed Auggie version is older than required
    - Auggie installation fails
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.AUGGIE_NOT_INSTALLED


class PlatformNotConfiguredError(IngotError):
    """Platform integration is not configured.

    Raised when:
    - Platform MCP server is not configured
    - Platform API credentials are missing or invalid
    - Platform integration check fails

    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.PLATFORM_NOT_CONFIGURED

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        exit_code: ExitCode | None = None,
    ) -> None:
        """Initialize the exception.

        The [Platform] prefix is added automatically to the message
        if not already present.
        """
        self.platform = platform
        if platform:
            # Normalize platform name for prefix check
            platform_normalized = platform.strip().lower()
            # Use regex to check if message already has the platform prefix
            # Handles variations like [Linear], [ Linear ], [LINEAR], etc.
            # Pattern: ^\[\s*platform\s*\] (case-insensitive, optional whitespace inside brackets)
            prefix_pattern = re.compile(
                rf"^\[\s*{re.escape(platform_normalized)}\s*\]",
                re.IGNORECASE,
            )
            if not prefix_pattern.match(message.strip()):
                # Add platform prefix for clarity
                message = f"[{platform.strip()}] {message}"
        super().__init__(message, exit_code)


class UserCancelledError(IngotError):
    """User cancelled the operation.

    Raised when:
    - User presses Ctrl+C
    - User selects 'abort' or 'cancel' option
    - User answers 'no' to a required confirmation
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.USER_CANCELLED


class GitOperationError(IngotError):
    """Git operation failed.

    Raised when:
    - Not in a git repository
    - Branch creation fails
    - Commit operation fails
    - Merge conflicts occur
    - Any other git command fails
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.GIT_ERROR


# ── Rate-limit exceptions ────────────────────────────────────────────────────
# Defined here (in the dependency-free base error module) to break the
# circular import chain: auggie.py → utils → utils.retry → auggie.py.
# Re-exported from their original modules for backward compatibility.


class AuggieRateLimitError(Exception):
    """Raised when Auggie CLI output indicates a rate limit error.

    Re-exported from ingot.integrations.auggie for backward compatibility.

    Attributes:
        output: The output that triggered rate limit detection
    """

    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


class BackendRateLimitError(IngotError):
    """Raised when any backend hits a rate limit.

    Re-exported from ingot.integrations.backends.errors for backward compatibility.

    Attributes:
        output: The output that triggered rate limit detection
        backend_name: Name of the backend that hit the rate limit
    """

    def __init__(
        self,
        message: str,
        output: str = "",
        backend_name: str = "",
    ) -> None:
        super().__init__(message)
        self.output = output
        self.backend_name = backend_name


__all__ = [
    "ExitCode",
    "IngotError",
    "AuggieNotInstalledError",
    "AuggieRateLimitError",
    "BackendRateLimitError",
    "PlatformNotConfiguredError",
    "UserCancelledError",
    "GitOperationError",
]
