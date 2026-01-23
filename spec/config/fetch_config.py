"""Fetch strategy configuration for SPECFLOW.

This module defines configuration classes for the hybrid ticket fetching
architecture, including agent platform settings, fetch strategies, and
performance tuning options.
"""

from dataclasses import dataclass, field
from enum import Enum


class FetchStrategy(Enum):
    """Ticket fetching strategy.

    Attributes:
        AGENT: Use agent-mediated fetch (fail if not supported)
        DIRECT: Use direct API (requires credentials)
        AUTO: Try agent first, fall back to direct
    """

    AGENT = "agent"
    DIRECT = "direct"
    AUTO = "auto"


class AgentPlatform(Enum):
    """Supported AI agent platforms.

    Attributes:
        AUGGIE: Augment Code agent
        CLAUDE_DESKTOP: Claude Desktop application
        CURSOR: Cursor IDE
        AIDER: Aider CLI tool
        MANUAL: Manual/no agent (direct API only)
    """

    AUGGIE = "auggie"
    CLAUDE_DESKTOP = "claude_desktop"
    CURSOR = "cursor"
    AIDER = "aider"
    MANUAL = "manual"


@dataclass
class AgentConfig:
    """Configuration for the connected AI agent.

    Attributes:
        platform: The AI agent platform being used
        integrations: Dict mapping platform names to integration availability
    """

    platform: AgentPlatform = AgentPlatform.AUGGIE
    integrations: dict[str, bool] = field(default_factory=dict)

    def supports_platform(self, platform: str) -> bool:
        """Check if agent has integration for platform.

        Args:
            platform: Platform name (e.g., 'jira', 'linear', 'github')

        Returns:
            True if the agent has an integration for this platform
        """
        return self.integrations.get(platform.lower(), False)


@dataclass
class FetchStrategyConfig:
    """Configuration for ticket fetching strategy.

    Attributes:
        default: Default fetch strategy for all platforms
        per_platform: Dict mapping platform names to specific strategies
    """

    default: FetchStrategy = FetchStrategy.AUTO
    per_platform: dict[str, FetchStrategy] = field(default_factory=dict)

    def get_strategy(self, platform: str) -> FetchStrategy:
        """Get strategy for a specific platform.

        Args:
            platform: Platform name (e.g., 'jira', 'linear', 'azure_devops')

        Returns:
            The fetch strategy for this platform (platform-specific or default)
        """
        return self.per_platform.get(platform.lower(), self.default)


@dataclass
class FetchPerformanceConfig:
    """Performance settings for ticket fetching.

    Attributes:
        cache_duration_hours: How long to cache fetched ticket data
        timeout_seconds: HTTP request timeout
        max_retries: Maximum number of retry attempts
        retry_delay_seconds: Delay between retry attempts
    """

    cache_duration_hours: int = 24
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


__all__ = [
    "FetchStrategy",
    "AgentPlatform",
    "AgentConfig",
    "FetchStrategyConfig",
    "FetchPerformanceConfig",
]
