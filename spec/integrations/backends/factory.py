"""Factory for creating AI backend instances.

This module provides a centralized factory for creating AI backend instances
by platform. It encapsulates backend-specific import logic (lazy imports to
avoid circular dependencies) and validates CLI installation when requested.
"""

from spec.config.fetch_config import AgentPlatform, parse_agent_platform
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendNotInstalledError

__all__ = ["BackendFactory"]


class BackendFactory:
    """Factory for creating AI backend instances.

    Use this factory instead of instantiating backends directly.
    This ensures consistent initialization and enables future extensions.

    The factory is stateless - all logic is in the static create() method.
    Each call creates a new, independent backend instance (no caching).

    Example:
        >>> from spec.integrations.backends.factory import BackendFactory
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
                (from parse_agent_platform)
            NotImplementedError: If the platform is planned but not yet
                implemented (Claude, Cursor)
            ValueError: If the platform is not supported (Aider, Manual)
            BackendNotInstalledError: If verify_installed=True and CLI is missing
        """
        if isinstance(platform, str):
            platform = parse_agent_platform(platform)

        backend: AIBackend

        if platform == AgentPlatform.AUGGIE:
            from spec.integrations.backends.auggie import AuggieBackend

            backend = AuggieBackend(model=model)

        elif platform == AgentPlatform.CLAUDE:
            # Phase 3: Replace with actual import when ClaudeBackend is implemented
            # from spec.integrations.backends.claude import ClaudeBackend
            # backend = ClaudeBackend(model=model)
            raise NotImplementedError("Claude backend not yet implemented. See Phase 3 of AMI-45.")

        elif platform == AgentPlatform.CURSOR:
            # Phase 4: Replace with actual import when CursorBackend is implemented
            # from spec.integrations.backends.cursor import CursorBackend
            # backend = CursorBackend(model=model)
            raise NotImplementedError("Cursor backend not yet implemented. See Phase 4 of AMI-45.")

        elif platform == AgentPlatform.AIDER:
            # Future: Replace with actual import when AiderBackend is implemented
            # Note: Uses ValueError (not NotImplementedError) per parent spec line 1976
            # because Aider support is deferred indefinitely, not a planned phase.
            raise ValueError("Aider backend not yet implemented")

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
