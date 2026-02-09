"""Backend-related errors.

Generic error types that apply to all AI backends. These errors provide
a unified error handling interface across Auggie, Claude, Cursor, and
other backends.

All errors inherit from SpecError to leverage exit code semantics and
the existing exception hierarchy.

Note: BackendRateLimitError and AuggieRateLimitError are defined in
spec.utils.errors (the dependency-free base error module) to break
circular imports. They are re-exported here for backward compatibility.
"""

from spec.utils.errors import (
    AuggieRateLimitError as AuggieRateLimitError,
)
from spec.utils.errors import (
    BackendRateLimitError as BackendRateLimitError,
)
from spec.utils.errors import (
    SpecError,
)


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
    "AuggieRateLimitError",
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
]
