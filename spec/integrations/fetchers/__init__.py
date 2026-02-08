"""Ticket fetchers package.

This package provides the fetcher abstraction layer for retrieving
raw ticket data from various issue tracking platforms.

The fetcher layer separates HOW to fetch data (fetching strategy) from
HOW to normalize data (provider responsibility).

Classes:
    TicketFetcher: Abstract base class for all fetchers
    AgentMediatedFetcher: Base class for AI agent-mediated fetching
    AuggieMediatedFetcher: Fetcher using Auggie's MCP integrations
    DirectAPIFetcher: Fallback fetcher using direct REST/GraphQL API calls

Exceptions:
    TicketFetchError: Base exception for fetch failures
    PlatformNotSupportedError: Fetcher doesn't support requested platform
    AgentIntegrationError: Agent integration/configuration failure
    AgentFetchError: Tool execution failed during fetch
    AgentResponseParseError: JSON output was malformed
"""

from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
from spec.integrations.fetchers.base import (
    AgentMediatedFetcher,
    TicketFetcher,
)
from spec.integrations.fetchers.claude_fetcher import ClaudeMediatedFetcher
from spec.integrations.fetchers.direct_api_fetcher import DirectAPIFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
    TicketFetchError,
)

__all__ = [
    # Base classes
    "TicketFetcher",
    "AgentMediatedFetcher",
    # Concrete fetchers
    "AuggieMediatedFetcher",
    "ClaudeMediatedFetcher",
    "DirectAPIFetcher",
    # Exceptions
    "TicketFetchError",
    "PlatformNotSupportedError",
    "AgentIntegrationError",
    "AgentFetchError",
    "AgentResponseParseError",
]
