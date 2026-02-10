"""Tests for ingot.integrations.backends.errors module."""

import pytest

from ingot.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)
from ingot.utils.errors import ExitCode, IngotError


class TestBackendRateLimitError:
    def test_inherits_from_spec_error(self):
        error = BackendRateLimitError("Rate limit hit")
        assert isinstance(error, IngotError)

    def test_message_stored(self):
        error = BackendRateLimitError("Rate limit hit")
        assert str(error) == "Rate limit hit"

    def test_output_attribute(self):
        error = BackendRateLimitError(
            "Rate limit hit",
            output="429 Too Many Requests",
        )
        assert error.output == "429 Too Many Requests"

    def test_backend_name_attribute(self):
        error = BackendRateLimitError(
            "Rate limit hit",
            backend_name="Auggie",
        )
        assert error.backend_name == "Auggie"

    def test_output_default_empty_string(self):
        error = BackendRateLimitError("Rate limit hit")
        assert error.output == ""

    def test_backend_name_default_empty_string(self):
        error = BackendRateLimitError("Rate limit hit")
        assert error.backend_name == ""

    def test_all_attributes_set(self):
        error = BackendRateLimitError(
            "Rate limit detected",
            output="Error 429",
            backend_name="Claude",
        )
        assert str(error) == "Rate limit detected"
        assert error.output == "Error 429"
        assert error.backend_name == "Claude"

    def test_has_default_exit_code(self):
        error = BackendRateLimitError("Rate limit hit")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_can_be_raised_and_caught(self):
        with pytest.raises(BackendRateLimitError) as exc_info:
            raise BackendRateLimitError(
                "Rate limit hit",
                output="429",
                backend_name="Auggie",
            )
        assert exc_info.value.output == "429"
        assert exc_info.value.backend_name == "Auggie"


class TestBackendNotInstalledError:
    def test_inherits_from_spec_error(self):
        error = BackendNotInstalledError("CLI not found")
        assert isinstance(error, IngotError)

    def test_message_stored(self):
        error = BackendNotInstalledError("Claude CLI is not installed")
        assert str(error) == "Claude CLI is not installed"

    def test_has_default_exit_code(self):
        error = BackendNotInstalledError("CLI not found")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_can_be_raised_and_caught(self):
        with pytest.raises(BackendNotInstalledError) as exc_info:
            raise BackendNotInstalledError("Claude CLI is not installed")
        assert str(exc_info.value) == "Claude CLI is not installed"


class TestBackendNotConfiguredError:
    def test_inherits_from_spec_error(self):
        error = BackendNotConfiguredError("No backend configured")
        assert isinstance(error, IngotError)

    def test_message_stored(self):
        error = BackendNotConfiguredError("Run 'spec init' to configure")
        assert str(error) == "Run 'spec init' to configure"

    def test_has_default_exit_code(self):
        error = BackendNotConfiguredError("No backend configured")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_can_be_raised_and_caught(self):
        with pytest.raises(BackendNotConfiguredError) as exc_info:
            raise BackendNotConfiguredError("No backend configured")
        assert str(exc_info.value) == "No backend configured"


class TestBackendTimeoutError:
    def test_inherits_from_spec_error(self):
        error = BackendTimeoutError("Execution timed out")
        assert isinstance(error, IngotError)

    def test_message_stored(self):
        error = BackendTimeoutError("Timed out after 120 seconds")
        assert str(error) == "Timed out after 120 seconds"

    def test_timeout_seconds_attribute(self):
        error = BackendTimeoutError(
            "Timed out",
            timeout_seconds=120.0,
        )
        assert error.timeout_seconds == 120.0

    def test_timeout_seconds_default_none(self):
        error = BackendTimeoutError("Timed out")
        assert error.timeout_seconds is None

    def test_has_default_exit_code(self):
        error = BackendTimeoutError("Execution timed out")
        assert error.exit_code == ExitCode.GENERAL_ERROR

    def test_can_be_raised_and_caught(self):
        with pytest.raises(BackendTimeoutError) as exc_info:
            raise BackendTimeoutError("Timed out", timeout_seconds=60.0)
        assert exc_info.value.timeout_seconds == 60.0


class TestErrorImports:
    def test_all_errors_importable_from_package(self):
        from ingot.integrations.backends import (
            BackendNotConfiguredError,
            BackendNotInstalledError,
            BackendRateLimitError,
            BackendTimeoutError,
        )

        # Verify they're the correct classes
        assert BackendRateLimitError.__name__ == "BackendRateLimitError"
        assert BackendNotInstalledError.__name__ == "BackendNotInstalledError"
        assert BackendNotConfiguredError.__name__ == "BackendNotConfiguredError"
        assert BackendTimeoutError.__name__ == "BackendTimeoutError"

    def test_all_errors_in_module_all(self):
        from ingot.integrations.backends import errors

        assert "BackendRateLimitError" in errors.__all__
        assert "BackendNotInstalledError" in errors.__all__
        assert "BackendNotConfiguredError" in errors.__all__
        assert "BackendTimeoutError" in errors.__all__
