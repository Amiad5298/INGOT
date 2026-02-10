"""Tests for ingot.integrations.providers.exceptions module.

Tests cover:
- Exception inheritance hierarchy
- Context information storage and accessibility
- String representations and error messages
- Default values and optional parameters
"""

import pytest

from ingot.integrations.providers.exceptions import (
    AuthenticationError,
    IssueTrackerError,
    PlatformNotSupportedError,
    RateLimitError,
    TicketNotFoundError,
)


class TestIssueTrackerError:
    def test_inherits_from_exception(self):
        assert issubclass(IssueTrackerError, Exception)

    def test_basic_instantiation(self):
        error = IssueTrackerError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_stores_platform(self):
        error = IssueTrackerError("Error", platform="Jira")
        assert error.platform == "Jira"

    def test_platform_default_is_none(self):
        error = IssueTrackerError("Error")
        assert error.platform is None

    def test_can_be_raised_and_caught(self):
        with pytest.raises(IssueTrackerError) as exc_info:
            raise IssueTrackerError("Test error", platform="GitHub")

        assert "Test error" in str(exc_info.value)
        assert exc_info.value.platform == "GitHub"


class TestAuthenticationError:
    def test_inherits_from_issue_tracker_error(self):
        assert issubclass(AuthenticationError, IssueTrackerError)

    def test_default_message(self):
        error = AuthenticationError()
        assert str(error) == "Authentication failed"

    def test_custom_message(self):
        error = AuthenticationError("Invalid API token")
        assert str(error) == "Invalid API token"

    def test_stores_platform(self):
        error = AuthenticationError(platform="Linear")
        assert error.platform == "Linear"

    def test_stores_missing_credentials(self):
        missing = ["API_TOKEN", "API_KEY"]
        error = AuthenticationError(missing_credentials=missing)
        assert error.missing_credentials == missing

    def test_missing_credentials_default_empty(self):
        error = AuthenticationError()
        assert error.missing_credentials == []

    def test_full_context(self):
        error = AuthenticationError(
            message="Auth failed",
            platform="Jira",
            missing_credentials=["TOKEN"],
        )
        assert str(error) == "Auth failed"
        assert error.platform == "Jira"
        assert error.missing_credentials == ["TOKEN"]


class TestTicketNotFoundError:
    def test_inherits_from_issue_tracker_error(self):
        assert issubclass(TicketNotFoundError, IssueTrackerError)

    def test_requires_ticket_id(self):
        error = TicketNotFoundError(ticket_id="PROJ-123")
        assert error.ticket_id == "PROJ-123"

    def test_default_message_includes_ticket_id(self):
        error = TicketNotFoundError(ticket_id="TEST-456")
        assert "TEST-456" in str(error)
        assert "not found" in str(error).lower()

    def test_custom_message(self):
        error = TicketNotFoundError(
            ticket_id="ABC-1",
            message="Ticket deleted",
        )
        assert str(error) == "Ticket deleted"
        assert error.ticket_id == "ABC-1"

    def test_stores_platform(self):
        error = TicketNotFoundError(ticket_id="GH-1", platform="GitHub")
        assert error.platform == "GitHub"

    def test_ticket_id_stores_actual_id_not_error_string(self):
        # Correct usage pattern
        error = TicketNotFoundError(
            ticket_id="ENG-456",
            message="Issue not found in Linear",
            platform="Linear",
        )
        # ticket_id should be the clean ID
        assert error.ticket_id == "ENG-456"
        assert "Issue not found" not in error.ticket_id
        # Message is separate
        assert "Issue not found" in str(error)

    def test_ticket_id_is_not_a_dict_representation(self):
        # The ticket_id should be a clean identifier
        error = TicketNotFoundError(ticket_id="owner/repo#42", platform="GitHub")
        assert error.ticket_id == "owner/repo#42"
        # Should not contain dict-like representations
        assert "{" not in error.ticket_id
        assert "}" not in error.ticket_id

    def test_ticket_id_is_keyword_only(self):
        # Positional usage should raise TypeError
        with pytest.raises(TypeError, match="positional"):
            TicketNotFoundError("PROJ-123")  # type: ignore[misc]

        # Keyword usage should work
        error = TicketNotFoundError(ticket_id="PROJ-123")
        assert error.ticket_id == "PROJ-123"


class TestRateLimitError:
    def test_inherits_from_issue_tracker_error(self):
        assert issubclass(RateLimitError, IssueTrackerError)

    def test_default_message(self):
        error = RateLimitError()
        assert "rate limit" in str(error).lower()

    def test_message_with_retry_after(self):
        error = RateLimitError(retry_after=60)
        assert "60" in str(error)
        assert error.retry_after == 60

    def test_stores_retry_after(self):
        error = RateLimitError(retry_after=120)
        assert error.retry_after == 120

    def test_retry_after_default_none(self):
        error = RateLimitError()
        assert error.retry_after is None

    def test_custom_message_overrides_default(self):
        error = RateLimitError(retry_after=30, message="Too many requests")
        assert str(error) == "Too many requests"
        assert error.retry_after == 30

    def test_stores_platform(self):
        error = RateLimitError(platform="Azure DevOps")
        assert error.platform == "Azure DevOps"


class TestPlatformNotSupportedError:
    def test_inherits_from_issue_tracker_error(self):
        assert issubclass(PlatformNotSupportedError, IssueTrackerError)

    def test_default_message(self):
        error = PlatformNotSupportedError()
        assert "not supported" in str(error).lower()

    def test_message_with_input_str(self):
        error = PlatformNotSupportedError(input_str="http://unknown.com/ticket/1")
        assert "http://unknown.com/ticket/1" in str(error)
        assert "could not detect" in str(error).lower()

    def test_stores_input_str(self):
        error = PlatformNotSupportedError(input_str="XYZ-999")
        assert error.input_str == "XYZ-999"

    def test_input_str_default_none(self):
        error = PlatformNotSupportedError()
        assert error.input_str is None

    def test_stores_supported_platforms(self):
        platforms = ["Jira", "GitHub", "Linear"]
        error = PlatformNotSupportedError(supported_platforms=platforms)
        assert error.supported_platforms == platforms

    def test_supported_platforms_default_empty(self):
        error = PlatformNotSupportedError()
        assert error.supported_platforms == []

    def test_message_includes_supported_platforms(self):
        error = PlatformNotSupportedError(
            input_str="bad-input",
            supported_platforms=["Jira", "GitHub"],
        )
        message = str(error)
        assert "Jira" in message
        assert "GitHub" in message

    def test_custom_message(self):
        error = PlatformNotSupportedError(message="Custom error")
        assert str(error) == "Custom error"

    def test_platform_is_none(self):
        error = PlatformNotSupportedError(input_str="test")
        assert error.platform is None


class TestExceptionHierarchy:
    def test_all_exceptions_are_issue_tracker_errors(self):
        exceptions = [
            AuthenticationError,
            TicketNotFoundError,
            RateLimitError,
            PlatformNotSupportedError,
        ]
        for exc_class in exceptions:
            assert issubclass(exc_class, IssueTrackerError)

    def test_can_catch_all_with_base_class(self):
        exceptions_to_test = [
            AuthenticationError("auth"),
            TicketNotFoundError(ticket_id="T-1"),
            RateLimitError(retry_after=10),
            PlatformNotSupportedError(input_str="x"),
        ]

        for exc in exceptions_to_test:
            with pytest.raises(IssueTrackerError):
                raise exc

    def test_can_catch_with_standard_exception(self):
        error = AuthenticationError("test")
        # Verify exception is instance of Exception (inherits from it)
        assert isinstance(error, Exception)
        with pytest.raises(AuthenticationError):
            raise error
