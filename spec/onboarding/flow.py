"""Interactive onboarding wizard for first-run backend setup.

Guides the user through:
1. Selecting an AI backend (Auggie, Claude Code, Cursor)
2. Verifying the backend CLI is installed
3. Saving the configuration
"""

from __future__ import annotations

import logging

from spec.config.fetch_config import AgentPlatform
from spec.config.manager import ConfigManager
from spec.integrations.backends.factory import BackendFactory
from spec.onboarding import OnboardingResult
from spec.ui.prompts import prompt_confirm, prompt_select
from spec.utils.console import print_error, print_header, print_info, print_success
from spec.utils.errors import SpecError, UserCancelledError

logger = logging.getLogger(__name__)

# Display label → AgentPlatform mapping (order determines prompt order)
BACKEND_CHOICES: dict[str, AgentPlatform] = {
    "Auggie (Augment Code CLI)": AgentPlatform.AUGGIE,
    "Claude Code CLI": AgentPlatform.CLAUDE,
    "Cursor": AgentPlatform.CURSOR,
}

INSTALLATION_URLS: dict[AgentPlatform, str] = {
    AgentPlatform.AUGGIE: "https://docs.augmentcode.com/cli",
    AgentPlatform.CLAUDE: "https://docs.anthropic.com/claude-code",
    AgentPlatform.CURSOR: "https://www.cursor.com/downloads",
}


class OnboardingFlow:
    """Interactive wizard for first-run backend configuration.

    Args:
        config: ConfigManager instance (already loaded)
    """

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def run(self) -> OnboardingResult:
        """Execute the full onboarding flow.

        Returns:
            OnboardingResult indicating success/failure and the configured backend.
        """
        try:
            print_header("Welcome to SPEC!")
            print_info(
                "Let's set up your AI backend. You can change this later with 'spec config'."
            )

            backend = self._select_backend()
            if backend is None:
                return OnboardingResult(
                    success=False,
                    error_message="No backend selected.",
                )

            verified_backend = self._verify_installation(backend)
            if verified_backend is None:
                return OnboardingResult(
                    success=False,
                    error_message="Backend verification failed.",
                )

            self._save_configuration(verified_backend)
            return OnboardingResult(success=True, backend=verified_backend)

        except UserCancelledError:
            return OnboardingResult(
                success=False,
                error_message="Onboarding cancelled by user.",
            )
        except SpecError as e:
            print_error(f"Onboarding failed: {e}")
            return OnboardingResult(
                success=False,
                error_message=str(e),
            )

    def _select_backend(self) -> AgentPlatform | None:
        """Prompt user to choose an AI backend.

        Returns:
            Selected AgentPlatform, or None if selection is somehow empty.
        """
        choice = prompt_select(
            message="Which AI backend would you like to use?",
            choices=list(BACKEND_CHOICES.keys()),
        )
        return BACKEND_CHOICES.get(choice)

    def _verify_installation(self, backend: AgentPlatform) -> AgentPlatform | None:
        """Verify that the selected backend CLI is installed.

        Loops to allow retry or switching backends.

        Args:
            backend: The backend to verify

        Returns:
            The verified AgentPlatform (may differ from input if user switched),
            or None on failure.
        """
        while True:
            try:
                backend_instance = BackendFactory.create(backend)
            except (ValueError, NotImplementedError) as exc:
                print_error(f"Cannot create backend: {exc}")
                return None

            installed, message = backend_instance.check_installed()

            if installed:
                print_success(message)
                return backend

            print_error(message)
            self._show_installation_instructions(backend)

            if prompt_confirm("Retry verification?", default=True):
                continue

            if prompt_confirm("Choose a different backend?", default=True):
                new_backend = self._select_backend()
                if new_backend is None:
                    return None
                backend = new_backend
                continue

            return None

    @staticmethod
    def _show_installation_instructions(backend: AgentPlatform) -> None:
        """Print installation instructions for a backend."""
        url = INSTALLATION_URLS.get(backend, "")
        if url:
            print_info(f"Install instructions: {url}")

    def _save_configuration(self, backend: AgentPlatform) -> None:
        """Persist the selected backend and verify the save.

        Args:
            backend: The backend to persist

        Raises:
            SpecError: If readback verification fails
        """
        self._config.save("AI_BACKEND", backend.value)

        # Readback verification
        self._config.load()
        persisted = self._config.get("AI_BACKEND", "")
        if persisted != backend.value:
            raise SpecError(
                f"Configuration readback mismatch: expected '{backend.value}', got '{persisted}'"
            )

        print_success(f"AI backend set to '{backend.value}'.")


__all__ = ["OnboardingFlow", "BACKEND_CHOICES", "INSTALLATION_URLS"]
