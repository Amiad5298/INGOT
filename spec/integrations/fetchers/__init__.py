"""Ticket fetchers package.

This package provides the fetcher abstraction layer for retrieving
raw ticket data from various issue tracking platforms.

The fetcher layer separates HOW to fetch data (fetching strategy) from
HOW to normalize data (provider responsibility).

Classes:
    TicketFetcher: Abstract base class for all fetchers
    AgentMediatedFetcher: Base class for AI agent-mediated fetching
    AuggieMediatedFetcher: Fetcher using Auggie's MCP integrations

Exceptions:
    TicketFetchError: Base exception for fetch failures
    PlatformNotSupportedError: Fetcher doesn't support requested platform
    AgentIntegrationError: Agent integration failure
"""

from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
from spec.integrations.fetchers.base import (
    AgentMediatedFetcher,
    TicketFetcher,
)
from spec.integrations.fetchers.exceptions import (
    AgentIntegrationError,
    PlatformNotSupportedError,
    TicketFetchError,
)

__all__ = [
    # Base classes
    "TicketFetcher",
    "AgentMediatedFetcher",
    # Concrete fetchers
    "AuggieMediatedFetcher",
    # Exceptions
    "TicketFetchError",
    "PlatformNotSupportedError",
    "AgentIntegrationError",
]
