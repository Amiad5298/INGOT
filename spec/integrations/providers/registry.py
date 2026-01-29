"""Provider Registry for issue tracker provider management.

This module provides:
- ProviderRegistry class for centralized provider registration and lookup
- Factory pattern for provider instantiation
- Singleton pattern for memory efficiency and connection reuse
- Decorator-based registration for providers
- Thread-safe operations with full lock protection
- Dependency injection for UserInteractionInterface

Example usage:
    from spec.integrations.providers import ProviderRegistry, Platform

    # Register a provider (typically done via decorator)
    @ProviderRegistry.register
    class JiraProvider(IssueTrackerProvider):
        PLATFORM = Platform.JIRA
        ...

    # Get provider instance
    provider = ProviderRegistry.get_provider(Platform.JIRA)

    # Or auto-detect from input
    provider = ProviderRegistry.get_provider_for_input("PROJ-123")

    # Set custom UserInteraction for testing
    ProviderRegistry.set_user_interaction(NonInteractiveUserInteraction())
"""

from __future__ import annotations

import inspect
import logging
import threading
from typing import ClassVar

from spec.integrations.providers.base import IssueTrackerProvider, Platform
from spec.integrations.providers.detector import PlatformDetector
from spec.integrations.providers.exceptions import PlatformNotSupportedError
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    UserInteractionInterface,
)

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry for issue tracker providers.

    Provides centralized factory for provider instantiation using:
    - Factory Pattern: Provider classes register themselves
    - Singleton Pattern: One provider instance per platform
    - Decorator-based Registration: Providers use @ProviderRegistry.register
    - Dependency Injection: UserInteractionInterface and config injected into providers

    All methods are class methods - no instance needed.
    Thread-safe operations using threading.Lock for all state mutations.

    Thread Safety:
        All access to _providers, _instances, _user_interaction, and _config is
        protected by _lock to ensure safe concurrent access.
    """

    _providers: ClassVar[dict[Platform, type[IssueTrackerProvider]]] = {}
    _instances: ClassVar[dict[Platform, IssueTrackerProvider]] = {}
    _user_interaction: ClassVar[UserInteractionInterface] = CLIUserInteraction()
    _config: ClassVar[dict[str, str]] = {}  # Provider configuration (e.g., default_jira_project)
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(cls, provider_class: type[IssueTrackerProvider]) -> type[IssueTrackerProvider]:
        """Decorator to register a provider class.

        The provider class must:
        - Be a subclass of IssueTrackerProvider
        - Have a PLATFORM class attribute that is a Platform enum value

        Thread-safe: Uses lock to protect registry mutations.

        Args:
            provider_class: The provider class to register

        Returns:
            The provider class unchanged (for decorator chaining)

        Raises:
            TypeError: If provider_class is not a subclass of IssueTrackerProvider,
                doesn't have a PLATFORM attribute, or PLATFORM is not a Platform enum

        Note:
            If a different provider is already registered for this platform, the
            existing provider will be replaced and a warning will be logged. The
            cached instance for that platform will also be cleared.
        """
        # Validate provider_class is a subclass of IssueTrackerProvider
        if not isinstance(provider_class, type) or not issubclass(
            provider_class, IssueTrackerProvider
        ):
            raise TypeError(
                f"Provider class must be a subclass of IssueTrackerProvider, "
                f"got {type(provider_class).__name__}"
            )

        # Validate PLATFORM attribute exists
        if not hasattr(provider_class, "PLATFORM"):
            raise TypeError(
                f"Provider class {provider_class.__name__} must have a PLATFORM class attribute"
            )

        platform = provider_class.PLATFORM
        # Validate PLATFORM is a Platform enum value
        if not isinstance(platform, Platform):
            raise TypeError(
                f"PLATFORM attribute of {provider_class.__name__} must be a "
                f"Platform enum value, got {type(platform).__name__}"
            )

        with cls._lock:
            # Check for duplicate registration
            if platform in cls._providers:
                existing_class = cls._providers[platform]
                if existing_class is not provider_class:
                    # Log warning for different class being registered
                    logger.warning(
                        f"Replacing existing provider {existing_class.__name__} "
                        f"with {provider_class.__name__} for platform {platform.name}"
                    )
                    # Clear existing instance if present so new provider will be used
                    cls._instances.pop(platform, None)
                else:
                    # Same class registered again - no-op with debug log
                    logger.debug(
                        f"Provider {provider_class.__name__} already registered "
                        f"for platform {platform.name}"
                    )
                    return provider_class

            cls._providers[platform] = provider_class

        return provider_class

    @classmethod
    def _create_provider_instance(
        cls, provider_class: type[IssueTrackerProvider]
    ) -> IssueTrackerProvider:
        """Create a provider instance with dependency injection.

        Injects dependencies based on provider's __init__ signature:
        - user_interaction: UserInteractionInterface for interactive operations
        - default_project: Default Jira project key (from set_config)

        Args:
            provider_class: The provider class to instantiate

        Returns:
            New provider instance with dependencies injected
        """
        # Check which parameters the provider accepts
        sig = inspect.signature(provider_class.__init__)
        params = sig.parameters

        # Build kwargs for dependency injection
        kwargs: dict[str, object] = {}

        if "user_interaction" in params:
            kwargs["user_interaction"] = cls._user_interaction

        if "default_project" in params:
            # Inject default_jira_project from config if available
            default_project = cls._config.get("default_jira_project")
            if default_project:
                kwargs["default_project"] = default_project

        # Dynamic injection based on runtime inspection - mypy can't verify this
        return provider_class(**kwargs)  # type: ignore[call-arg]

    @classmethod
    def get_provider(cls, platform: Platform) -> IssueTrackerProvider:
        """Get singleton provider instance for a platform.

        Uses lazy instantiation - provider is only created when first requested.
        Thread-safe: All lookups and instantiation are protected by lock.
        Dependency Injection: UserInteractionInterface is injected into providers
        that accept it via their __init__ method.

        Args:
            platform: The platform to get provider for

        Returns:
            The singleton provider instance

        Raises:
            PlatformNotSupportedError: If no provider is registered for platform
        """
        with cls._lock:
            if platform not in cls._providers:
                registered = sorted([p.name for p in cls._providers.keys()])
                raise PlatformNotSupportedError(
                    message=f"No provider registered for platform: {platform.name}",
                    supported_platforms=registered,
                )

            # Lazy singleton instantiation
            if platform not in cls._instances:
                provider_class = cls._providers[platform]
                cls._instances[platform] = cls._create_provider_instance(provider_class)

            return cls._instances[platform]

    @classmethod
    def get_provider_for_input(cls, input_str: str) -> IssueTrackerProvider:
        """Get provider instance based on input URL or ticket ID.

        Convenience method that combines platform detection with provider lookup.
        Uses PlatformDetector to determine the platform from the input.

        Thread-safe: Platform detection is done first, then get_provider is called.

        Args:
            input_str: URL or ticket ID to detect platform from

        Returns:
            The singleton provider instance for the detected platform

        Raises:
            PlatformNotSupportedError: If platform cannot be detected or
                no provider is registered for the detected platform
        """
        try:
            platform, _ = PlatformDetector.detect(input_str)
        except PlatformNotSupportedError:
            # Re-raise as-is since PlatformDetector already raises this
            raise
        except Exception as e:
            # Normalize any unexpected exceptions to PlatformNotSupportedError
            with cls._lock:
                registered = sorted([p.name for p in cls._providers.keys()])
            raise PlatformNotSupportedError(
                input_str=input_str,
                message=f"Failed to detect platform from input: {e}",
                supported_platforms=registered,
            ) from e

        return cls.get_provider(platform)

    @classmethod
    def list_platforms(cls) -> list[Platform]:
        """List all registered platforms.

        Thread-safe: Returns a sorted copy of registered platforms.

        Returns:
            Sorted list of Platform enum values that have registered providers.
            Sorting is by platform name for deterministic output.
        """
        with cls._lock:
            return sorted(cls._providers.keys(), key=lambda p: p.name)

    @classmethod
    def set_user_interaction(cls, ui: UserInteractionInterface) -> None:
        """Set the user interaction implementation.

        Enables dependency injection for testing or different UI implementations.
        Note: This does NOT update already-instantiated providers. Call clear()
        first if you need providers to be re-instantiated with the new UI.

        Thread-safe: Uses lock to protect mutation.

        Args:
            ui: The UserInteractionInterface implementation to use
        """
        with cls._lock:
            cls._user_interaction = ui

    @classmethod
    def get_user_interaction(cls) -> UserInteractionInterface:
        """Get the current user interaction implementation.

        Thread-safe: Uses lock to protect read.

        Returns:
            The current UserInteractionInterface implementation
        """
        with cls._lock:
            return cls._user_interaction

    @classmethod
    def set_config(cls, config: dict[str, str]) -> None:
        """Set provider configuration for dependency injection.

        Configuration values are passed to providers during instantiation.
        Currently supported keys:
        - default_jira_project: Default Jira project key for numeric ticket IDs

        Note: This does NOT update already-instantiated providers. Call clear()
        first if you need providers to be re-instantiated with new config.

        Thread-safe: Uses lock to protect mutation.

        Args:
            config: Dictionary of configuration values
        """
        with cls._lock:
            cls._config = dict(config)  # Copy to prevent external mutation

    @classmethod
    def reset_instances(cls) -> None:
        """Reset instances, config, and user interaction without clearing provider registrations.

        Use this method when you need to reset runtime state but preserve provider
        registrations. This is particularly useful in tests that need to reset
        between test cases without re-registering providers.

        Thread-safe: Uses lock to protect mutations.

        After resetting:
        - All singleton instances are destroyed (will be recreated on next get_provider)
        - UserInteractionInterface is reset to CLIUserInteraction
        - Configuration is cleared

        Provider class registrations are preserved.
        """
        with cls._lock:
            cls._instances.clear()
            cls._user_interaction = CLIUserInteraction()
            cls._config.clear()

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations and instances.

        Used for test isolation to reset registry state between tests.
        Thread-safe: Uses lock to protect mutations.

        After clearing:
        - All provider class registrations are removed
        - All singleton instances are destroyed
        - UserInteractionInterface is reset to CLIUserInteraction
        - Configuration is cleared
        """
        with cls._lock:
            cls._providers.clear()
            cls._instances.clear()
            cls._user_interaction = CLIUserInteraction()
            cls._config.clear()
