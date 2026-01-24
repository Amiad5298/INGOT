"""Fetch strategy configuration for SPECFLOW.

This module defines configuration classes for the hybrid ticket fetching
architecture, including agent platform settings, fetch strategies, and
performance tuning options.

Validation:
    - Strategy validation enforces that configurations are viable:
        - AGENT strategy: agent must have integration for the platform
        - DIRECT strategy: fallback credentials must exist for the platform
        - AUTO strategy: agent integration OR fallback credentials must exist
    - Performance configs have upper bounds to prevent hanging
    - Credential validation ensures required fields per platform
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfigValidationError(Exception):
    """Raised when configuration validation fails.

    This exception is raised for fail-fast behavior when:
    - Strategy requires agent support but agent lacks integration
    - Strategy requires credentials but none are configured
    - Performance values exceed safe limits
    - Required credential fields are missing or malformed
    """

    pass


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


# Known ticket platforms for validation
KNOWN_PLATFORMS = frozenset(
    {
        "jira",
        "linear",
        "github",
        "azure_devops",
        "trello",
        "monday",
    }
)

# Required credential fields per platform for validation
PLATFORM_REQUIRED_CREDENTIALS: dict[str, frozenset[str]] = {
    "jira": frozenset({"url", "email", "token"}),
    "linear": frozenset({"api_key"}),
    "github": frozenset({"token"}),
    "azure_devops": frozenset({"organization", "pat"}),
    "trello": frozenset({"api_key", "token"}),
    "monday": frozenset({"api_key"}),
}


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

    def validate_platform_overrides(self, strict: bool = False) -> list[str]:
        """Validate that per-platform overrides reference known platforms.

        Args:
            strict: If True, raises ConfigValidationError for unknown platforms.
                    If False, returns list of warnings.

        Returns:
            List of warning messages for unknown platforms

        Raises:
            ConfigValidationError: If strict=True and unknown platforms found
        """
        warnings = []
        for platform in self.per_platform:
            if platform.lower() not in KNOWN_PLATFORMS:
                msg = f"Per-platform override for unknown platform: '{platform}'"
                warnings.append(msg)

        if strict and warnings:
            raise ConfigValidationError(
                "Unknown platforms in per_platform overrides: "
                + ", ".join(f"'{p}'" for p in self.per_platform if p.lower() not in KNOWN_PLATFORMS)
            )

        return warnings


# Performance config upper bounds to prevent system hangs
MAX_CACHE_DURATION_HOURS = 168  # 1 week
MAX_TIMEOUT_SECONDS = 300  # 5 minutes
MAX_RETRIES = 10
MAX_RETRY_DELAY_SECONDS = 60.0


@dataclass
class FetchPerformanceConfig:
    """Performance settings for ticket fetching.

    Attributes:
        cache_duration_hours: How long to cache fetched ticket data (max: 168h/1 week)
        timeout_seconds: HTTP request timeout (max: 300s/5 min)
        max_retries: Maximum number of retry attempts (max: 10)
        retry_delay_seconds: Delay between retry attempts (max: 60s)

    Upper bounds are enforced to prevent configurations that can block or hang.
    Values are clamped in __post_init__ using simple assignment (not frozen).
    """

    cache_duration_hours: int = 24
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        """Validate and clamp values to safe upper bounds."""
        import logging

        logger = logging.getLogger(__name__)

        # Cache duration - clamp to max using simple assignment
        if self.cache_duration_hours > MAX_CACHE_DURATION_HOURS:
            logger.warning(
                f"cache_duration_hours ({self.cache_duration_hours}) exceeds max "
                f"({MAX_CACHE_DURATION_HOURS}), clamping to max"
            )
            self.cache_duration_hours = MAX_CACHE_DURATION_HOURS

        # Timeout - clamp to max
        if self.timeout_seconds > MAX_TIMEOUT_SECONDS:
            logger.warning(
                f"timeout_seconds ({self.timeout_seconds}) exceeds max "
                f"({MAX_TIMEOUT_SECONDS}), clamping to max"
            )
            self.timeout_seconds = MAX_TIMEOUT_SECONDS

        # Retries - clamp to max
        if self.max_retries > MAX_RETRIES:
            logger.warning(
                f"max_retries ({self.max_retries}) exceeds max ({MAX_RETRIES}), clamping to max"
            )
            self.max_retries = MAX_RETRIES

        # Retry delay - clamp to max
        if self.retry_delay_seconds > MAX_RETRY_DELAY_SECONDS:
            logger.warning(
                f"retry_delay_seconds ({self.retry_delay_seconds}) exceeds max "
                f"({MAX_RETRY_DELAY_SECONDS}), clamping to max"
            )
            self.retry_delay_seconds = MAX_RETRY_DELAY_SECONDS


# Regex pattern for unexpanded environment variables like ${VAR}, prefix_${VAR}, ${VAR}_suffix
_UNEXPANDED_ENV_VAR_PATTERN = re.compile(r"\$\{[^}]+\}")


def _contains_unexpanded_env_var(value: str) -> bool:
    """Check if a string contains unexpanded environment variable patterns.

    Detects patterns like: ${VAR}, prefix_${VAR}, ${VAR}_suffix, prefix_${VAR}_suffix

    Args:
        value: The string to check

    Returns:
        True if the string contains unexpanded ${VAR} patterns
    """
    return bool(_UNEXPANDED_ENV_VAR_PATTERN.search(value))


def validate_credentials(
    platform: str,
    credentials: dict[str, Any] | None,
    strict: bool = True,
) -> list[str]:
    """Validate fallback credentials for a platform.

    Args:
        platform: Platform name (e.g., 'jira', 'azure_devops')
        credentials: Dictionary of credential key-value pairs
        strict: If True, raises ConfigValidationError for missing fields.
                If False, returns list of warnings/errors.

    Returns:
        List of validation messages

    Raises:
        ConfigValidationError: If strict=True and validation fails
    """
    errors: list[str] = []
    platform_lower = platform.lower()

    if credentials is None:
        if strict:
            raise ConfigValidationError(
                f"No fallback credentials configured for platform '{platform}'"
            )
        return [f"No fallback credentials configured for platform '{platform}'"]

    required_fields = PLATFORM_REQUIRED_CREDENTIALS.get(platform_lower)
    if required_fields is None:
        # Unknown platform - warn but don't fail
        return [f"Unknown platform '{platform}', cannot validate credentials"]

    # Normalize credential keys to lowercase
    normalized_creds = {k.lower(): v for k, v in credentials.items()}

    missing_fields = required_fields - set(normalized_creds.keys())
    if missing_fields:
        msg = (
            f"Missing required credential fields for '{platform}': "
            f"{', '.join(sorted(missing_fields))}"
        )
        errors.append(msg)

    # Check for empty values in provided credentials
    for field_name in required_fields:
        if field_name in normalized_creds:
            value = normalized_creds[field_name]
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"Credential field '{field_name}' for '{platform}' is empty")
            # Check for unexpanded env vars (indicates missing environment variable)
            # Handles patterns like: ${VAR}, prefix_${VAR}, ${VAR}_suffix, prefix_${VAR}_suffix
            if isinstance(value, str) and _contains_unexpanded_env_var(value):
                errors.append(
                    f"Credential field '{field_name}' for '{platform}' contains "
                    f"unexpanded environment variable: {value}"
                )

    if strict and errors:
        raise ConfigValidationError("; ".join(errors))

    return errors


def validate_strategy_for_platform(
    platform: str,
    strategy: FetchStrategy,
    agent_config: "AgentConfig",
    has_credentials: bool,
    strict: bool = True,
) -> list[str]:
    """Validate that a fetch strategy is viable for a platform.

    Args:
        platform: Platform name
        strategy: The fetch strategy to validate
        agent_config: Agent configuration with integrations
        has_credentials: Whether fallback credentials exist
        strict: If True, raises ConfigValidationError on failure

    Returns:
        List of validation errors/warnings

    Raises:
        ConfigValidationError: If strict=True and strategy is not viable
    """
    errors: list[str] = []
    has_agent_support = agent_config.supports_platform(platform)

    if strategy == FetchStrategy.AGENT:
        if not has_agent_support:
            msg = (
                f"Strategy 'agent' for platform '{platform}' requires agent "
                f"integration, but agent platform '{agent_config.platform.value}' "
                f"does not have '{platform}' integration enabled"
            )
            errors.append(msg)

    elif strategy == FetchStrategy.DIRECT:
        if not has_credentials:
            msg = (
                f"Strategy 'direct' for platform '{platform}' requires "
                f"fallback credentials, but none are configured"
            )
            errors.append(msg)

    elif strategy == FetchStrategy.AUTO:
        if not has_agent_support and not has_credentials:
            msg = (
                f"Strategy 'auto' for platform '{platform}' requires either "
                f"agent integration OR fallback credentials, but neither is available"
            )
            errors.append(msg)

    if strict and errors:
        raise ConfigValidationError("; ".join(errors))

    return errors


__all__ = [
    "ConfigValidationError",
    "FetchStrategy",
    "AgentPlatform",
    "AgentConfig",
    "FetchStrategyConfig",
    "FetchPerformanceConfig",
    "KNOWN_PLATFORMS",
    "PLATFORM_REQUIRED_CREDENTIALS",
    "MAX_CACHE_DURATION_HOURS",
    "MAX_TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "MAX_RETRY_DELAY_SECONDS",
    "validate_credentials",
    "validate_strategy_for_platform",
]
