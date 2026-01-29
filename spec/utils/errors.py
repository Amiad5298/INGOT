"""Custom exceptions and exit codes for SPEC.

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


class SpecError(Exception):
    """Base exception for SPEC errors.

    All custom exceptions in this application should inherit from this class.
    Each exception type has an associated exit code for proper error reporting.

    Attributes:
        exit_code: The exit code to use when this exception causes program termination
        message: The error message
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.GENERAL_ERROR

    def __init__(self, message: str, exit_code: ExitCode | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Error message describing what went wrong
            exit_code: Optional override for the default exit code
        """
        super().__init__(message)
        self._exit_code = exit_code

    @property
    def exit_code(self) -> ExitCode:
        """Get the exit code for this exception.

        Returns:
            The instance exit code if set, otherwise the class default exit code.
        """
        if self._exit_code is not None:
            return self._exit_code
        return self.__class__._default_exit_code


class AuggieNotInstalledError(SpecError):
    """Auggie CLI is not installed or version is too old.

    Raised when:
    - The 'auggie' command is not found in PATH
    - The installed Auggie version is older than required
    - Auggie installation fails
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.AUGGIE_NOT_INSTALLED


class PlatformNotConfiguredError(SpecError):
    """Platform integration is not configured.

    Raised when:
    - Platform MCP server is not configured
    - Platform API credentials are missing or invalid
    - Platform integration check fails

    Attributes:
        platform: The platform that is not configured (optional)
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.PLATFORM_NOT_CONFIGURED

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        exit_code: ExitCode | None = None,
    ) -> None:
        """Initialize the exception.

        Args:
            message: Error message describing what went wrong
            platform: Optional platform name for context. The platform prefix
                [Platform] is added automatically if not already present.
            exit_code: Optional override for the default exit code
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


class UserCancelledError(SpecError):
    """User cancelled the operation.

    Raised when:
    - User presses Ctrl+C
    - User selects 'abort' or 'cancel' option
    - User answers 'no' to a required confirmation
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.USER_CANCELLED


class GitOperationError(SpecError):
    """Git operation failed.

    Raised when:
    - Not in a git repository
    - Branch creation fails
    - Commit operation fails
    - Merge conflicts occur
    - Any other git command fails
    """

    _default_exit_code: ClassVar[ExitCode] = ExitCode.GIT_ERROR


__all__ = [
    "ExitCode",
    "SpecError",
    "AuggieNotInstalledError",
    "PlatformNotConfiguredError",
    "UserCancelledError",
    "GitOperationError",
]
