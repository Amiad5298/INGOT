"""Custom exceptions for issue tracker operations.

This module defines a hierarchy of exceptions for platform-agnostic
issue tracker operations, enabling consistent error handling across
all provider implementations.
"""



class IssueTrackerError(Exception):
    """Base exception for all issue tracker operations.

    All provider-specific exceptions should inherit from this class
    to enable consistent error handling across platforms.
    """

    def __init__(self, message: str, platform: str | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error message
            platform: Optional platform name for context
        """
        self.platform = platform
        super().__init__(message)


class AuthenticationError(IssueTrackerError):
    """Raised when authentication with the issue tracker fails.

    This can occur due to:
    - Invalid or expired API tokens
    - Missing credentials in configuration
    - Insufficient permissions for the requested operation
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        platform: str | None = None,
        missing_credentials: list[str] | None = None,
    ) -> None:
        """Initialize the authentication error.

        Args:
            message: Human-readable error message
            platform: Optional platform name for context
            missing_credentials: List of missing credential keys
        """
        self.missing_credentials = missing_credentials or []
        super().__init__(message, platform)


class TicketNotFoundError(IssueTrackerError):
    """Raised when a requested ticket cannot be found.

    This typically occurs when:
    - The ticket ID does not exist
    - The user lacks permission to view the ticket
    - The ticket has been deleted

    Note: ticket_id is keyword-only to prevent misuse like:
        raise TicketNotFoundError("Some error message")  # Wrong!
    Instead, use:
        raise TicketNotFoundError(ticket_id="PROJ-123")  # Correct
    """

    def __init__(
        self,
        *,  # All following parameters are keyword-only
        ticket_id: str,
        message: str | None = None,
        platform: str | None = None,
    ) -> None:
        """Initialize the ticket not found error.

        Args:
            ticket_id: The ticket ID that was not found (keyword-only)
            message: Optional custom message
            platform: Optional platform name for context
        """
        self.ticket_id = ticket_id
        default_message = f"Ticket '{ticket_id}' not found"
        super().__init__(message or default_message, platform)


class RateLimitError(IssueTrackerError):
    """Raised when the API rate limit is exceeded.

    Providers should catch this and implement appropriate
    backoff strategies or inform the user to wait.
    """

    def __init__(
        self,
        retry_after: int | None = None,
        message: str | None = None,
        platform: str | None = None,
    ) -> None:
        """Initialize the rate limit error.

        Args:
            retry_after: Seconds to wait before retrying (if known)
            message: Optional custom message
            platform: Optional platform name for context
        """
        self.retry_after = retry_after
        if message:
            default_message = message
        elif retry_after:
            default_message = f"Rate limited. Retry after {retry_after} seconds"
        else:
            default_message = "Rate limit exceeded"
        super().__init__(default_message, platform)


class PlatformNotSupportedError(IssueTrackerError):
    """Raised when a platform is not recognized or supported.

    This occurs when:
    - The input URL/ID doesn't match any known platform patterns
    - No provider is registered for the detected platform
    - The platform is explicitly disabled in configuration
    """

    def __init__(
        self,
        input_str: str | None = None,
        message: str | None = None,
        supported_platforms: list[str] | None = None,
    ) -> None:
        """Initialize the platform not supported error.

        Args:
            input_str: The input that couldn't be matched to a platform
            message: Optional custom message
            supported_platforms: List of supported platform names
        """
        self.input_str = input_str
        self.supported_platforms = supported_platforms or []

        if message:
            default_message = message
        elif input_str:
            default_message = f"Could not detect platform from input: {input_str}"
            if supported_platforms:
                default_message += f"\nSupported platforms: {', '.join(supported_platforms)}"
        else:
            default_message = "Platform not supported"

        super().__init__(default_message, platform=None)

