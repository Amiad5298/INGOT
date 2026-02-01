"""Single source of truth for backend platform resolution.

This module provides the resolve_backend_platform() function that determines
which AI backend to use based on explicit precedence rules:
1. CLI --backend flag (highest priority)
2. Persisted config AI_BACKEND
3. Raise BackendNotConfiguredError (no implicit default)

This enforces the "no default backend" policy, ensuring users explicitly
choose their AI provider.
"""

from spec.config.fetch_config import AgentPlatform, parse_agent_platform
from spec.config.manager import ConfigManager
from spec.integrations.backends.errors import BackendNotConfiguredError


def resolve_backend_platform(
    config_manager: ConfigManager,
    cli_backend_override: str | None = None,
) -> AgentPlatform:
    """Resolve the backend platform with explicit precedence.

    Precedence (highest to lowest):
    1. CLI --backend override (one-run override)
    2. Persisted config AI_BACKEND (stored by ConfigManager/onboarding)

    If neither is set, raises BackendNotConfiguredError.

    Args:
        config_manager: Configuration manager for reading persisted config
        cli_backend_override: CLI --backend flag value (if provided)

    Returns:
        Resolved AgentPlatform enum value

    Raises:
        BackendNotConfiguredError: If no backend is configured via CLI or config
        ConfigValidationError: If an invalid platform string is provided
    """
    # 1. CLI override takes precedence (one-run override)
    # Note: Check both truthiness and non-whitespace to handle "" and "   " cases
    if cli_backend_override and cli_backend_override.strip():
        return parse_agent_platform(cli_backend_override.strip())

    # 2. Check AI_BACKEND in persisted config
    # Note: Legacy AGENT_PLATFORM migration is handled separately.
    # This resolver only reads AI_BACKEND. Migration from AGENT_PLATFORM to AI_BACKEND
    # is out of scope for this ticket.
    ai_backend = config_manager.get("AI_BACKEND", "")
    if ai_backend.strip():
        return parse_agent_platform(ai_backend)

    # 3. No backend configured - raise error with helpful message
    raise BackendNotConfiguredError(
        "No AI backend configured. Please run 'spec init' to configure a backend, "
        "or use the --backend flag to specify one."
    )


__all__ = ["resolve_backend_platform"]
