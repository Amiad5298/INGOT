"""Tests for ai_workflow.utils.errors module."""

import pytest

from ai_workflow.utils.errors import (
    AIWorkflowError,
    AuggieNotInstalledError,
    ExitCode,
    GitOperationError,
    JiraNotConfiguredError,
    UserCancelledError,
)


class TestExitCode:
    """Tests for ExitCode enum."""

    def test_exit_code_values(self):
        """Verify exit code values match Bash script."""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.GENERAL_ERROR == 1
        assert ExitCode.AUGGIE_NOT_INSTALLED == 2
        assert ExitCode.JIRA_NOT_CONFIGURED == 3
        assert ExitCode.USER_CANCELLED == 4
        assert ExitCode.GIT_ERROR == 5

    def test_exit_code_is_int(self):
        """Exit codes should be usable as integers."""
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.GENERAL_ERROR) == 1


class TestAIWorkflowError:
    """Tests for base AIWorkflowError exception."""

    def test_default_exit_code(self):
        """Base exception has GENERAL_ERROR exit code."""
        error = AIWorkflowError("Test error")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_custom_exit_code(self):
        """Can override exit code in constructor."""
        error = AIWorkflowError("Test error", exit_code=ExitCode.GIT_ERROR)
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_message(self):
        """Exception message is accessible."""
        error = AIWorkflowError("Test error message")
        assert str(error) == "Test error message"


class TestAuggieNotInstalledError:
    """Tests for AuggieNotInstalledError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = AuggieNotInstalledError("Auggie not found")
        assert error.exit_code == ExitCode.AUGGIE_NOT_INSTALLED

    def test_inheritance(self):
        """Inherits from AIWorkflowError."""
        error = AuggieNotInstalledError("Test")
        assert isinstance(error, AIWorkflowError)


class TestJiraNotConfiguredError:
    """Tests for JiraNotConfiguredError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = JiraNotConfiguredError("Jira not configured")
        assert error.exit_code == ExitCode.JIRA_NOT_CONFIGURED

    def test_inheritance(self):
        """Inherits from AIWorkflowError."""
        error = JiraNotConfiguredError("Test")
        assert isinstance(error, AIWorkflowError)


class TestUserCancelledError:
    """Tests for UserCancelledError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = UserCancelledError("User cancelled")
        assert error.exit_code == ExitCode.USER_CANCELLED

    def test_inheritance(self):
        """Inherits from AIWorkflowError."""
        error = UserCancelledError("Test")
        assert isinstance(error, AIWorkflowError)


class TestGitOperationError:
    """Tests for GitOperationError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = GitOperationError("Git failed")
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_inheritance(self):
        """Inherits from AIWorkflowError."""
        error = GitOperationError("Test")
        assert isinstance(error, AIWorkflowError)

