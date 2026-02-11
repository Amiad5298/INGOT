"""Factory for creating AI backend instances.

This module provides a centralized factory for creating AI backend instances
by platform. It encapsulates backend-specific import logic (lazy imports to
avoid circular dependencies) and validates CLI installation when requested.
"""

from ingot.config.fetch_config import AgentPlatform, parse_ai_backend
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import BackendNotInstalledError

__all__ = ["BackendFactory"]


class BackendFactory:
    """Factory for creating AI backend instances.

    Use this factory instead of instantiating backends directly.
    This ensures consistent initialization and enables future extensions.

    The factory is stateless - all logic is in the static create() method.
    Each call creates a new, independent backend instance (no caching).

    Example:
        >>> from ingot.integrations.backends.factory import BackendFactory
        >>> backend = BackendFactory.create("auggie", verify_installed=True)
        >>> success, output = backend.run_print_with_output("Hello")
    """

    @staticmethod
    def create(
        platform: AgentPlatform | str,
        model: str = "",
        verify_installed: bool = False,
    ) -> AIBackend:
        """Create an AI backend instance.

        Args:
            platform: Agent platform enum or string name (e.g., "auggie", "claude")
            model: Default model to use for this backend instance
            verify_installed: If True, verify CLI is installed before returning

        Returns:
            Configured AIBackend instance

        Raises:
            ConfigValidationError: If the platform string is invalid
                (from parse_ai_backend)
            NotImplementedError: If the platform is planned but not yet
                implemented
            ValueError: If the platform is not supported (Aider, Manual)
            BackendNotInstalledError: If verify_installed=True and CLI is missing
        """
        if isinstance(platform, str):
            platform = parse_ai_backend(platform)

        backend: AIBackend

        if platform == AgentPlatform.AUGGIE:
            from ingot.integrations.backends.auggie import AuggieBackend

            backend = AuggieBackend(model=model)

        elif platform == AgentPlatform.CLAUDE:
            from ingot.integrations.backends.claude import ClaudeBackend

            backend = ClaudeBackend(model=model)

        elif platform == AgentPlatform.CURSOR:
            from ingot.integrations.backends.cursor import CursorBackend

            backend = CursorBackend(model=model)

        elif platform == AgentPlatform.AIDER:
            from ingot.integrations.backends.aider import AiderBackend

            backend = AiderBackend(model=model)

        elif platform == AgentPlatform.GEMINI:
            from ingot.integrations.backends.gemini import GeminiBackend

            backend = GeminiBackend(model=model)

        elif platform == AgentPlatform.CODEX:
            from ingot.integrations.backends.codex import CodexBackend

            backend = CodexBackend(model=model)

        elif platform == AgentPlatform.MANUAL:
            raise ValueError("Manual mode does not use an AI backend")

        else:
            # Defensive: catches any future AgentPlatform values not yet handled
            raise ValueError(f"Unknown platform: {platform}")

        if verify_installed:
            installed, message = backend.check_installed()
            if not installed:
                raise BackendNotInstalledError(message)

        return backend
