"""Custom exceptions for ticket fetching operations.

This module defines the exception hierarchy for the fetchers package:
- TicketFetchError: Base exception for all fetch failures
- PlatformNotSupportedError: Fetcher doesn't support the requested platform
- AgentIntegrationError: Agent integration (e.g., MCP) failure
- AgentFetchError: Tool execution failed during fetch
- AgentResponseParseError: JSON output was malformed
"""

from __future__ import annotations


class TicketFetchError(Exception):
    """Base exception for ticket fetch failures.

    All fetcher-related exceptions inherit from this class,
    enabling catch-all error handling when needed.
    """

    pass


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
