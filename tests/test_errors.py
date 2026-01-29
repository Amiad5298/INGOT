"""Tests for spec.utils.errors module."""


from spec.utils.errors import (
    AuggieNotInstalledError,
    ExitCode,
    GitOperationError,
    PlatformNotConfiguredError,
    SpecError,
    UserCancelledError,
)


class TestExitCode:
    """Tests for ExitCode enum."""

    def test_exit_code_values(self):
        """Verify exit code values match Bash script."""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.GENERAL_ERROR == 1
        assert ExitCode.AUGGIE_NOT_INSTALLED == 2
        assert ExitCode.PLATFORM_NOT_CONFIGURED == 3
        assert ExitCode.USER_CANCELLED == 4
        assert ExitCode.GIT_ERROR == 5

    def test_platform_not_configured_is_canonical(self):
        """PLATFORM_NOT_CONFIGURED is the canonical name."""
        assert ExitCode.PLATFORM_NOT_CONFIGURED.name == "PLATFORM_NOT_CONFIGURED"

    def test_exit_code_is_int(self):
        """Exit codes should be usable as integers."""
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.GENERAL_ERROR) == 1


class TestSpecError:
    """Tests for base SpecError exception."""

    def test_default_exit_code(self):
        """Base exception has GENERAL_ERROR exit code."""
        error = SpecError("Test error")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_custom_exit_code(self):
        """Can override exit code in constructor."""
        error = SpecError("Test error", exit_code=ExitCode.GIT_ERROR)
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_message(self):
        """Exception message is accessible."""
        error = SpecError("Test error message")
        assert str(error) == "Test error message"


class TestAuggieNotInstalledError:
    """Tests for AuggieNotInstalledError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = AuggieNotInstalledError("Auggie not found")
        assert error.exit_code == ExitCode.AUGGIE_NOT_INSTALLED

    def test_inheritance(self):
        """Inherits from SpecError."""
        error = AuggieNotInstalledError("Test")
        assert isinstance(error, SpecError)


class TestPlatformNotConfiguredError:
    """Tests for PlatformNotConfiguredError exception."""

    def test_default_exit_code(self):
        """Uses PLATFORM_NOT_CONFIGURED exit code by default."""
        error = PlatformNotConfiguredError("Test error")
        assert error.exit_code == ExitCode.PLATFORM_NOT_CONFIGURED

    def test_with_platform_attribute_stored(self):
        """Platform attribute is stored correctly."""
        error = PlatformNotConfiguredError("Test error", platform="Linear")
        assert error.platform == "Linear"

    def test_with_platform_message_prefixed(self):
        """Platform name is prefixed into the message for clarity."""
        error = PlatformNotConfiguredError("API credentials missing", platform="Linear")
        assert str(error).startswith("[Linear] ")
        assert "API credentials missing" in str(error)

    def test_without_platform_no_prefix(self):
        """No platform prefix when platform not provided."""
        error = PlatformNotConfiguredError("Generic error")
        assert not str(error).startswith("[")
        assert str(error) == "Generic error"

    def test_without_platform_attribute_is_none(self):
        """Platform attribute is None when not provided."""
        error = PlatformNotConfiguredError("Generic error")
        assert error.platform is None

    def test_inheritance(self):
        """Inherits from SpecError."""
        error = PlatformNotConfiguredError("Test")
        assert isinstance(error, SpecError)

    def test_custom_exit_code_override(self):
        """Can override exit code in constructor."""
        error = PlatformNotConfiguredError(
            "Test", platform="Jira", exit_code=ExitCode.GENERAL_ERROR
        )
        assert error.exit_code == ExitCode.GENERAL_ERROR


class TestUserCancelledError:
    """Tests for UserCancelledError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = UserCancelledError("User cancelled")
        assert error.exit_code == ExitCode.USER_CANCELLED

    def test_inheritance(self):
        """Inherits from SpecError."""
        error = UserCancelledError("Test")
        assert isinstance(error, SpecError)


class TestGitOperationError:
    """Tests for GitOperationError exception."""

    def test_exit_code(self):
        """Has correct exit code."""
        error = GitOperationError("Git failed")
        assert error.exit_code == ExitCode.GIT_ERROR

    def test_inheritance(self):
        """Inherits from SpecError."""
        error = GitOperationError("Test")
        assert isinstance(error, SpecError)
