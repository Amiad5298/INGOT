"""Platform-agnostic issue tracker provider framework.

This package provides:
- Base classes and interfaces for issue tracker integrations
- Platform-agnostic data models (GenericTicket)
- Custom exceptions for issue tracker operations
- User interaction abstraction for testable providers
- Platform detection for URL and ticket ID pattern matching

Example usage:
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        IssueTrackerProvider,
        PlatformDetector,
    )
"""

from spec.integrations.providers.base import (
    GenericTicket,
    IssueTrackerProvider,
    Platform,
    PlatformMetadata,
    TicketStatus,
    TicketType,
    sanitize_title_for_branch,
)
from spec.integrations.providers.detector import (
    PLATFORM_PATTERNS,
    PlatformDetector,
    PlatformPattern,
)
from spec.integrations.providers.exceptions import (
    AuthenticationError,
    IssueTrackerError,
    PlatformNotSupportedError,
    RateLimitError,
    TicketNotFoundError,
)
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    NonInteractiveUserInteraction,
    SelectOption,
    UserInteractionInterface,
)

__all__ = [
    # Enums
    "Platform",
    "TicketStatus",
    "TicketType",
    # Data Models
    "GenericTicket",
    "PlatformMetadata",
    "PlatformPattern",
    # Utility Functions
    "sanitize_title_for_branch",
    # Platform Detection
    "PlatformDetector",
    "PLATFORM_PATTERNS",
    # Abstract Base Classes
    "IssueTrackerProvider",
    "UserInteractionInterface",
    # User Interaction Implementations
    "CLIUserInteraction",
    "NonInteractiveUserInteraction",
    "SelectOption",
    # Exceptions
    "IssueTrackerError",
    "AuthenticationError",
    "TicketNotFoundError",
    "RateLimitError",
    "PlatformNotSupportedError",
]
