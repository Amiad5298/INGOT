"""Configuration validation functions for INGOT.

Standalone functions extracted from ConfigManager for validating
configuration state (active platforms, fetch config validation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ingot.config.fetch_config import (
    AgentConfig,
    AgentPlatform,
    ConfigValidationError,
    FetchStrategy,
    FetchStrategyConfig,
    get_active_platforms,
    validate_credentials,
    validate_strategy_for_platform,
)
from ingot.utils.env_utils import EnvVarExpansionError

if TYPE_CHECKING:
    from ingot.config.manager import ConfigManager


def get_active_platforms_from_config(manager: ConfigManager) -> set[str]:
    """Get the set of 'active' platforms that need validation.

    Active platforms are those explicitly defined in per_platform
    strategy overrides, agent integrations, or fallback_credentials.
    """
    return get_active_platforms(
        raw_config_keys=set(manager._raw_values.keys()),
        strategy_config=manager.get_fetch_strategy_config(),
        agent_config=manager.get_agent_config(),
    )


def validate_fetch_config(manager: ConfigManager, strict: bool = True) -> list[str]:
    """Validate the complete fetch configuration.

    Performs scoped validation only on 'active' platforms that are explicitly
    configured (defined in per_platform, integrations, or fallback_credentials).
    This reduces noise by not checking all KNOWN_PLATFORMS by default.

    Validation includes:
    - Strategy/platform compatibility
    - Credential availability and completeness
    - Per-platform override references
    - Enum parsing (agent platform, fetch strategies)

    Raises:
        ConfigValidationError: If strict=True and validation fails.
    """
    errors: list[str] = []

    # Get agent config - may raise ConfigValidationError for invalid enum values
    try:
        agent_config = manager.get_agent_config()
    except ConfigValidationError as e:
        if strict:
            raise
        errors.append(str(e))
        # Use default agent config to continue validation
        agent_config = AgentConfig(
            platform=AgentPlatform.AUGGIE,
            integrations={},
        )

    # Get strategy config - may raise ConfigValidationError for invalid enum values
    try:
        strategy_config = manager.get_fetch_strategy_config()
    except ConfigValidationError as e:
        if strict:
            raise
        errors.append(str(e))
        # Use default strategy config to continue validation
        strategy_config = FetchStrategyConfig(
            default=FetchStrategy.AUTO,
            per_platform={},
        )

    # Validate per-platform overrides reference known platforms
    override_warnings = strategy_config.validate_platform_overrides(strict=False)
    errors.extend(override_warnings)

    # Get only the active platforms that need validation
    # Use the already-parsed configs to avoid re-calling getters (which could raise)
    active_platforms = get_active_platforms(
        raw_config_keys=set(manager._raw_values.keys()),
        strategy_config=strategy_config,
        agent_config=agent_config,
    )

    # Validate only active platforms' strategies
    for platform in active_platforms:
        strategy = strategy_config.get_strategy(platform)
        has_agent_support = agent_config.supports_platform(platform)

        # Determine if credentials are required for this platform
        # - DIRECT strategy: always requires credentials
        # - AUTO strategy: requires credentials if no agent support (direct is only path)
        credentials_required = strategy == FetchStrategy.DIRECT or (
            strategy == FetchStrategy.AUTO and not has_agent_support
        )

        # Use strict mode for env var expansion when credentials are required
        # This fail-fast behavior prevents silent 401/403 errors at runtime
        credentials = None
        try:
            credentials = manager.get_fallback_credentials(platform, strict=credentials_required)
        except EnvVarExpansionError as e:
            # Missing env vars in required credentials is a config error
            errors.append(
                f"Platform '{platform}' requires credentials but has missing "
                f"environment variable(s): {e}"
            )

        has_credentials = credentials is not None and len(credentials) > 0

        platform_errors = validate_strategy_for_platform(
            platform=platform,
            strategy=strategy,
            agent_config=agent_config,
            has_credentials=has_credentials,
            strict=False,
        )
        errors.extend(platform_errors)

        # If direct or auto strategy with credentials, validate credential fields
        if has_credentials and strategy.value in ("direct", "auto"):
            cred_errors = validate_credentials(platform, credentials, strict=False)
            errors.extend(cred_errors)

    if strict and errors:
        raise ConfigValidationError(
            "Fetch configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return errors
