"""First-run onboarding for SPEC.

Provides the interactive wizard that guides users through
AI backend selection and verification on first run.
"""

from __future__ import annotations

from dataclasses import dataclass

from spec.config.fetch_config import AgentPlatform
from spec.config.manager import ConfigManager


@dataclass
class OnboardingResult:
    """Result of the onboarding flow.

    Attributes:
        success: Whether onboarding completed successfully
        backend: The AgentPlatform that was configured, or None on failure
        error_message: Human-readable error if success is False
    """

    success: bool
    backend: AgentPlatform | None = None
    error_message: str = ""


def is_first_run(config: ConfigManager) -> bool:
    """Check whether onboarding is needed.

    Returns True when no backend is configured, meaning the user has
    never completed backend selection.

    Checks both the agent config (for migrating users) and the
    AI_BACKEND config key.

    Args:
        config: Configuration manager (must already be loaded)

    Returns:
        True if no backend is configured
    """
    agent_config = config.get_agent_config()
    if agent_config and agent_config.platform:
        return False
    return not config.get("AI_BACKEND", "").strip()


def run_onboarding(config: ConfigManager) -> OnboardingResult:
    """Run the interactive onboarding wizard.

    Delegates to OnboardingFlow for the actual UI interaction.

    Args:
        config: Configuration manager

    Returns:
        OnboardingResult with success status and configured backend
    """
    from spec.onboarding.flow import OnboardingFlow

    flow = OnboardingFlow(config)
    return flow.run()


__all__ = [
    "OnboardingResult",
    "is_first_run",
    "run_onboarding",
]
