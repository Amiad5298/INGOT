"""Custom exceptions and exit codes for SPEC.

This module defines the exit codes and exception hierarchy used throughout
the application, matching the original Bash script's error handling.
"""

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
    JIRA_NOT_CONFIGURED = 3
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

    exit_code: ClassVar[ExitCode] = ExitCode.GENERAL_ERROR

    def __init__(self, message: str, exit_code: ExitCode | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Error message describing what went wrong
            exit_code: Optional override for the default exit code
        """
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class AuggieNotInstalledError(SpecError):
    """Auggie CLI is not installed or version is too old.

    Raised when:
    - The 'auggie' command is not found in PATH
    - The installed Auggie version is older than required
    - Auggie installation fails
    """

    exit_code: ClassVar[ExitCode] = ExitCode.AUGGIE_NOT_INSTALLED


class JiraNotConfiguredError(SpecError):
    """Jira integration is not configured in Auggie.

    Raised when:
    - Jira MCP server is not configured
    - Jira API token is missing or invalid
    - Jira integration check fails
    """

    exit_code: ClassVar[ExitCode] = ExitCode.JIRA_NOT_CONFIGURED


class UserCancelledError(SpecError):
    """User cancelled the operation.

    Raised when:
    - User presses Ctrl+C
    - User selects 'abort' or 'cancel' option
    - User answers 'no' to a required confirmation
    """

    exit_code: ClassVar[ExitCode] = ExitCode.USER_CANCELLED


class GitOperationError(SpecError):
    """Git operation failed.

    Raised when:
    - Not in a git repository
    - Branch creation fails
    - Commit operation fails
    - Merge conflicts occur
    - Any other git command fails
    """

    exit_code: ClassVar[ExitCode] = ExitCode.GIT_ERROR


__all__ = [
    "ExitCode",
    "SpecError",
    "AuggieNotInstalledError",
    "JiraNotConfiguredError",
    "UserCancelledError",
    "GitOperationError",
]

