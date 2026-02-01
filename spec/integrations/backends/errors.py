"""Backend-related errors.

Generic error types that apply to all AI backends. These errors provide
a unified error handling interface across Auggie, Claude, Cursor, and
other backends.

All errors inherit from SpecError to leverage exit code semantics and
the existing exception hierarchy.
"""

from spec.utils.errors import SpecError


class BackendRateLimitError(SpecError):
    """Raised when any backend hits a rate limit.

    Replaces AuggieRateLimitError for backend-agnostic handling.
    Carries backend_name and output for context.

    Attributes:
        output: The output that triggered rate limit detection
        backend_name: Name of the backend that hit the rate limit

    Example:
        >>> raise BackendRateLimitError(
        ...     "Rate limit detected",
        ...     output="Error 429: Too Many Requests",
        ...     backend_name="Auggie",
        ... )
    """

    def __init__(
        self,
        message: str,
        output: str = "",
        backend_name: str = "",
    ) -> None:
        """Initialize the rate limit error.

        Args:
            message: Error message describing the rate limit
            output: The output that triggered rate limit detection
            backend_name: Name of the backend (e.g., "Auggie", "Claude")
        """
        super().__init__(message)
        self.output = output
        self.backend_name = backend_name


class BackendNotInstalledError(SpecError):
    """Raised when backend CLI is not installed.

    This error is raised when attempting to use a backend whose CLI
    tool is not found in the system PATH.

    Example:
        >>> raise BackendNotInstalledError(
        ...     "Claude CLI is not installed. Install with: npm install -g @anthropic/claude-code"
        ... )
    """

    pass


class BackendNotConfiguredError(SpecError):
    """Raised when no AI backend is configured.

    This error is raised when neither CLI --backend flag nor persisted
    AI_BACKEND config is set. Users should run 'spec init' to configure
    a backend or use --backend flag.

    Example:
        >>> raise BackendNotConfiguredError(
        ...     "No AI backend configured. Run 'spec init' or use --backend flag."
        ... )
    """

    pass


class BackendTimeoutError(SpecError):
    """Raised when backend execution times out.

    This error is raised when a backend operation exceeds the configured
    timeout duration. Carries the timeout value for user feedback.

    Attributes:
        timeout_seconds: The timeout duration that was exceeded (if known)

    Example:
        >>> raise BackendTimeoutError(
        ...     "Backend execution timed out after 120 seconds",
        ...     timeout_seconds=120.0,
        ... )
    """

    def __init__(
        self,
        message: str,
        timeout_seconds: float | None = None,
    ) -> None:
        """Initialize the timeout error.

        Args:
            message: Error message describing the timeout
            timeout_seconds: The timeout duration that was exceeded
        """
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


__all__ = [
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
]
