"""Custom exceptions for ticket fetching operations.

This module defines the exception hierarchy for the fetchers package:
- TicketFetchError: Base exception for all fetch failures
- PlatformNotSupportedError: Fetcher doesn't support the requested platform
- AgentIntegrationError: Agent integration (e.g., MCP) failure
- AgentFetchError: Tool execution failed during fetch
- AgentResponseParseError: JSON output was malformed

Handler-specific exceptions (raised by PlatformHandler implementations):
- CredentialValidationError: Missing or invalid credential keys
- TicketIdFormatError: Invalid ticket ID format for platform
- PlatformApiError: Platform API returned an error (GraphQL errors, etc.)
"""

from __future__ import annotations


class TicketFetchError(Exception):
    """Base exception for ticket fetch failures.

    All fetcher-related exceptions inherit from this class,
    enabling catch-all error handling when needed.
    """

    pass


# ============================================================================
# Handler-specific exceptions (raised by PlatformHandler implementations)
# ============================================================================


class CredentialValidationError(TicketFetchError):
    """Raised when credential validation fails in a handler.

    This indicates missing or invalid credential keys required by the platform.

    Attributes:
        platform_name: Name of the platform (e.g., "Jira", "Linear", "GitHub", "Azure DevOps")
        missing_keys: Set of credential keys that are missing
    """

    def __init__(
        self,
        platform_name: str,
        missing_keys: set[str] | frozenset[str],
        message: str | None = None,
    ) -> None:
        """Initialize CredentialValidationError.

        Args:
            platform_name: The platform that requires the credentials
            missing_keys: Set of missing credential key names
            message: Optional custom message (auto-generated if not provided)
        """
        self.platform_name = platform_name
        self.missing_keys = missing_keys
        if message is None:
            message = (
                f"{platform_name} handler missing required credentials: " f"{sorted(missing_keys)}"
            )
        super().__init__(message)


class TicketIdFormatError(TicketFetchError):
    """Raised when ticket ID format is invalid for the platform.

    Each platform has specific ticket ID format requirements
    (e.g., "owner/repo#number" for GitHub).

    Attributes:
        platform_name: Name of the platform
        ticket_id: The invalid ticket ID that was provided
        expected_format: Description of expected format (optional)
    """

    def __init__(
        self,
        platform_name: str,
        ticket_id: str,
        expected_format: str | None = None,
        message: str | None = None,
    ) -> None:
        """Initialize TicketIdFormatError.

        Args:
            platform_name: The platform that rejected the ticket ID
            ticket_id: The invalid ticket ID
            expected_format: Optional description of expected format
            message: Optional custom message (auto-generated if not provided)
        """
        self.platform_name = platform_name
        self.ticket_id = ticket_id
        self.expected_format = expected_format
        if message is None:
            message = f"Invalid {platform_name} ticket format: {ticket_id}"
            if expected_format:
                message += f" (expected: {expected_format})"
        super().__init__(message)


class PlatformApiError(TicketFetchError):
    """Raised when platform API returns a logical error.

    This is for API-level errors that are not HTTP status errors,
    such as GraphQL errors in successful HTTP calls, etc.

    Note: For "not found" scenarios (empty list, null result), use
    PlatformNotFoundError instead.

    Attributes:
        platform_name: Name of the platform
        error_details: Details about the API error
        ticket_id: Optional ticket ID related to the error
    """

    def __init__(
        self,
        platform_name: str,
        error_details: str,
        ticket_id: str | None = None,
        message: str | None = None,
    ) -> None:
        """Initialize PlatformApiError.

        Args:
            platform_name: The platform that returned the error
            error_details: Details about what went wrong
            ticket_id: Optional related ticket ID
            message: Optional custom message (auto-generated if not provided)
        """
        self.platform_name = platform_name
        self.error_details = error_details
        self.ticket_id = ticket_id
        if message is None:
            message = f"{platform_name} API error: {error_details}"
            if ticket_id:
                message = f"{platform_name} API error for {ticket_id}: {error_details}"
        super().__init__(message)


class PlatformNotFoundError(PlatformApiError):
    """Raised when a ticket/item is not found on the platform.

    This is a semantic subclass of PlatformApiError specifically for
    "not found" scenarios (e.g., empty list, null result in GraphQL).

    Use this instead of PlatformApiError when the API successfully responded
    but the requested item does not exist.

    Attributes:
        platform_name: Name of the platform
        ticket_id: The ticket ID that was not found
    """

    def __init__(
        self,
        platform_name: str,
        ticket_id: str,
        message: str | None = None,
    ) -> None:
        """Initialize PlatformNotFoundError.

        Args:
            platform_name: The platform that was queried
            ticket_id: The ticket ID that was not found
            message: Optional custom message (auto-generated if not provided)
        """
        if message is None:
            message = f"{platform_name}: Ticket '{ticket_id}' not found"
        super().__init__(
            platform_name=platform_name,
            error_details="Ticket not found",
            ticket_id=ticket_id,
            message=message,
        )


class PlatformNotSupportedError(TicketFetchError):
    """Raised when fetcher doesn't support the requested platform.

    This indicates a configuration or usage error - the caller
    should use a different fetcher for the requested platform.

    Attributes:
        platform: The unsupported platform that was requested
        fetcher_name: Name of the fetcher that doesn't support it
    """

    def __init__(
        self,
        platform: str,
        fetcher_name: str,
        message: str | None = None,
    ) -> None:
        """Initialize PlatformNotSupportedError.

        Args:
            platform: The platform that was requested
            fetcher_name: The fetcher that doesn't support it
            message: Optional custom message (auto-generated if not provided)
        """
        self.platform = platform
        self.fetcher_name = fetcher_name
        if message is None:
            message = f"Fetcher '{fetcher_name}' does not support platform '{platform}'"
        super().__init__(message)


class AgentIntegrationError(TicketFetchError):
    """Raised when agent integration is not available or misconfigured.

    This indicates a configuration issue with the agent - the platform
    is not supported or the agent is not properly configured.

    Use cases:
    - Platform not supported/configured for the agent
    - Agent not available or not responding
    - MCP tool not available

    Attributes:
        agent_name: Name of the agent that failed
        original_error: The underlying error if available
    """

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize AgentIntegrationError.

        Args:
            message: Description of the failure
            agent_name: Optional name of the agent that failed
            original_error: Optional underlying exception
        """
        self.agent_name = agent_name
        self.original_error = original_error
        super().__init__(message)


class AgentFetchError(TicketFetchError):
    """Raised when agent tool execution fails.

    This indicates the agent was invoked but the tool execution
    failed - e.g., network error, API error, timeout.

    Attributes:
        agent_name: Name of the agent that failed
        original_error: The underlying error if available
    """

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize AgentFetchError.

        Args:
            message: Description of the failure
            agent_name: Optional name of the agent that failed
            original_error: Optional underlying exception
        """
        self.agent_name = agent_name
        self.original_error = original_error
        super().__init__(message)


class AgentResponseParseError(TicketFetchError):
    """Raised when agent response cannot be parsed.

    This indicates the agent returned a response but it could
    not be parsed as valid JSON or is missing required fields.

    Attributes:
        agent_name: Name of the agent that returned invalid response
        raw_response: The raw response that failed to parse
        original_error: The underlying parse error if available
    """

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        raw_response: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """Initialize AgentResponseParseError.

        Args:
            message: Description of the parse failure
            agent_name: Optional name of the agent
            raw_response: Optional raw response that failed to parse
            original_error: Optional underlying exception
        """
        self.agent_name = agent_name
        self.raw_response = raw_response
        self.original_error = original_error
        super().__init__(message)
