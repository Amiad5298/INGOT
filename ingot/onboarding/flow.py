"""Interactive onboarding wizard for first-run backend setup.

Guides the user through:
1. Selecting an AI backend (Auggie, Claude Code, Cursor)
2. Verifying the backend CLI is installed
3. Saving the configuration
"""

from __future__ import annotations

import logging

from ingot.config.fetch_config import AgentPlatform
from ingot.config.manager import ConfigManager
from ingot.integrations.backends.factory import BackendFactory
from ingot.onboarding import OnboardingResult
from ingot.ui.menus import show_model_selection
from ingot.ui.prompts import prompt_confirm, prompt_select
from ingot.utils.console import print_error, print_header, print_info, print_success
from ingot.utils.errors import IngotError, UserCancelledError

logger = logging.getLogger(__name__)

# Display label → AgentPlatform mapping (order determines prompt order)
BACKEND_CHOICES: dict[str, AgentPlatform] = {
    "Auggie (Augment Code CLI)": AgentPlatform.AUGGIE,
    "Claude Code CLI": AgentPlatform.CLAUDE,
    "Cursor": AgentPlatform.CURSOR,
    "Aider": AgentPlatform.AIDER,
    "Gemini CLI": AgentPlatform.GEMINI,
    "Codex (OpenAI)": AgentPlatform.CODEX,
}

INSTALLATION_URLS: dict[AgentPlatform, str] = {
    AgentPlatform.AUGGIE: "https://docs.augmentcode.com/cli",
    AgentPlatform.CLAUDE: "https://docs.anthropic.com/claude-code",
    AgentPlatform.CURSOR: "https://www.cursor.com/downloads",
    AgentPlatform.AIDER: "https://aider.chat/docs/install.html",
    AgentPlatform.GEMINI: "https://github.com/google-gemini/gemini-cli",
    AgentPlatform.CODEX: "https://github.com/openai/codex",
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
            print_header("Welcome to INGOT!")
            print_info(
                "Let's set up your AI backend. You can change this later with 'ingot config'."
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

            planning_model, impl_model = self._select_models(verified_backend)
            self._save_configuration(
                verified_backend,
                planning_model=planning_model,
                impl_model=impl_model,
            )
            return OnboardingResult(success=True, backend=verified_backend)

        except UserCancelledError:
            return OnboardingResult(
                success=False,
                error_message="Onboarding cancelled by user.",
            )
        except IngotError as e:
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

    def _select_models(self, backend_platform: AgentPlatform) -> tuple[str | None, str | None]:
        """Optionally prompt user to configure AI models.

        Args:
            backend_platform: The verified backend platform.

        Returns:
            Tuple of (planning_model, implementation_model). Both None
            if user declines or selection fails.
        """
        if not prompt_confirm(
            "Configure AI models now? (you can do this later with 'ingot config')",
            default=False,
        ):
            return None, None

        try:
            backend_instance = BackendFactory.create(backend_platform)
        except Exception:
            logger.debug("Could not create backend for model selection", exc_info=True)
            return None, None

        planning_model = show_model_selection(
            purpose="planning (Steps 1-2)",
            backend=backend_instance,
        )
        impl_model = show_model_selection(
            purpose="implementation (Step 3)",
            backend=backend_instance,
        )
        return planning_model, impl_model

    def _save_configuration(
        self,
        backend: AgentPlatform,
        *,
        planning_model: str | None = None,
        impl_model: str | None = None,
    ) -> None:
        """Persist the selected backend and verify the save.

        Args:
            backend: The backend to persist

        Raises:
            IngotError: If readback verification fails
        """
        self._config.save("AI_BACKEND", backend.value)

        if planning_model:
            self._config.save("PLANNING_MODEL", planning_model)
            print_success(f"Planning model set to '{planning_model}'.")

        if impl_model:
            self._config.save("IMPLEMENTATION_MODEL", impl_model)
            print_success(f"Implementation model set to '{impl_model}'.")

        # Readback verification
        self._config.load()
        persisted = self._config.get("AI_BACKEND", "")
        if persisted != backend.value:
            raise IngotError(
                f"Configuration readback mismatch: expected '{backend.value}', got '{persisted}'"
            )

        print_success(f"AI backend set to '{backend.value}'.")


__all__ = ["OnboardingFlow", "BACKEND_CHOICES", "INSTALLATION_URLS"]
