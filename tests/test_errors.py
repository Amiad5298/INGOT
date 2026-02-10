"""Tests for ingot.utils.errors module."""

from ingot.utils.errors import (
    AuggieNotInstalledError,
    ExitCode,
    GitOperationError,
    IngotError,
    PlatformNotConfiguredError,
    UserCancelledError,
)


class TestExitCode:
    def test_exit_code_values(self):
        assert ExitCode.SUCCESS == 0
        assert ExitCode.GENERAL_ERROR == 1
        assert ExitCode.AUGGIE_NOT_INSTALLED == 2
        assert ExitCode.PLATFORM_NOT_CONFIGURED == 3
        assert ExitCode.USER_CANCELLED == 4
        assert ExitCode.GIT_ERROR == 5

    def test_platform_not_configured_is_canonical(self):
        assert ExitCode.PLATFORM_NOT_CONFIGURED.name == "PLATFORM_NOT_CONFIGURED"

    def test_exit_code_is_int(self):
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.GENERAL_ERROR) == 1


class TestIngotError:
    def test_default_exit_code(self):
        error = IngotError("Test error")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_custom_exit_code(self):
        error = IngotError("Test error", exit_code=ExitCode.GIT_ERROR)
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_message(self):
        error = IngotError("Test error message")
        assert str(error) == "Test error message"


class TestAuggieNotInstalledError:
    def test_exit_code(self):
        error = AuggieNotInstalledError("Auggie not found")
        assert error.exit_code == ExitCode.AUGGIE_NOT_INSTALLED

    def test_inheritance(self):
        error = AuggieNotInstalledError("Test")
        assert isinstance(error, IngotError)


class TestPlatformNotConfiguredError:
    def test_default_exit_code(self):
        error = PlatformNotConfiguredError("Test error")
        assert error.exit_code == ExitCode.PLATFORM_NOT_CONFIGURED

    def test_with_platform_attribute_stored(self):
        error = PlatformNotConfiguredError("Test error", platform="Linear")
        assert error.platform == "Linear"

    def test_with_platform_message_prefixed(self):
        error = PlatformNotConfiguredError("API credentials missing", platform="Linear")
        assert str(error).startswith("[Linear] ")
        assert "API credentials missing" in str(error)

    def test_without_platform_no_prefix(self):
        error = PlatformNotConfiguredError("Generic error")
        assert not str(error).startswith("[")
        assert str(error) == "Generic error"

    def test_without_platform_attribute_is_none(self):
        error = PlatformNotConfiguredError("Generic error")
        assert error.platform is None

    def test_inheritance(self):
        error = PlatformNotConfiguredError("Test")
        assert isinstance(error, IngotError)

    def test_custom_exit_code_override(self):
        error = PlatformNotConfiguredError(
            "Test", platform="Jira", exit_code=ExitCode.GENERAL_ERROR
        )
        assert error.exit_code == ExitCode.GENERAL_ERROR


class TestUserCancelledError:
    def test_exit_code(self):
        error = UserCancelledError("User cancelled")
        assert error.exit_code == ExitCode.USER_CANCELLED

    def test_inheritance(self):
        error = UserCancelledError("Test")
        assert isinstance(error, IngotError)


class TestGitOperationError:
    def test_exit_code(self):
        error = GitOperationError("Git failed")
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_inheritance(self):
        error = GitOperationError("Test")
        assert isinstance(error, IngotError)
