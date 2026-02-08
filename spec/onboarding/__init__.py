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

    Checks the raw AI_BACKEND config key directly. This is the same key
    that resolve_backend_platform() uses, ensuring consistent detection.

    Note: We intentionally do NOT check agent_config.platform here because
    get_agent_config() defaults to AgentPlatform.AUGGIE when AI_BACKEND is
    empty, making that check always truthy and preventing onboarding from
    ever triggering.

    Args:
        config: Configuration manager (must already be loaded)

    Returns:
        True if no backend is configured
    """
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
