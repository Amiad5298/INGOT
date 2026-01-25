"""Platform-specific API handlers for DirectAPIFetcher.

This module provides:
1. Handler classes for all supported platforms
2. Handler Registry pattern for clean handler instantiation

The Handler Registry eliminates inline imports in DirectAPIFetcher._create_handler,
improving static analysis support and making the codebase more maintainable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spec.integrations.fetchers.handlers.azure_devops import AzureDevOpsHandler
from spec.integrations.fetchers.handlers.base import GraphQLPlatformHandler, PlatformHandler
from spec.integrations.fetchers.handlers.github import GitHubHandler
from spec.integrations.fetchers.handlers.jira import JiraHandler
from spec.integrations.fetchers.handlers.linear import LinearHandler
from spec.integrations.fetchers.handlers.monday import MondayHandler
from spec.integrations.fetchers.handlers.trello import TrelloHandler

if TYPE_CHECKING:
    from spec.integrations.providers.base import Platform

# =============================================================================
# Handler Registry
# =============================================================================
# Architecture Decision: Handler Registry Pattern
#
# This registry maps Platform enums to handler classes, eliminating the need
# for inline imports in DirectAPIFetcher._create_handler. Benefits:
# 1. Better static analysis support (linters can trace imports)
# 2. Single source of truth for platform -> handler mapping
# 3. Easier to extend with new platforms
# 4. More testable (registry can be mocked or replaced)
#
# The registry uses lazy evaluation via a function to avoid circular imports
# when spec.integrations.providers.base imports from this module.
# =============================================================================


def _build_handler_registry() -> dict[Platform, type[PlatformHandler]]:
    """Build the platform to handler class registry.

    Uses lazy import of Platform enum to avoid circular dependency issues
    while maintaining clean static analysis support.

    Returns:
        Mapping of Platform enum values to their handler classes
    """
    # Import here to avoid circular dependency with providers.base
    from spec.integrations.providers.base import Platform

    return {
        Platform.JIRA: JiraHandler,
        Platform.LINEAR: LinearHandler,
        Platform.GITHUB: GitHubHandler,
        Platform.AZURE_DEVOPS: AzureDevOpsHandler,
        Platform.TRELLO: TrelloHandler,
        Platform.MONDAY: MondayHandler,
    }


# Cached registry instance (built on first access)
_handler_registry: dict[Platform, type[PlatformHandler]] | None = None


def get_handler_registry() -> dict[Platform, type[PlatformHandler]]:
    """Get the handler registry, building it if necessary.

    Returns:
        Mapping of Platform enum values to their handler classes
    """
    global _handler_registry
    if _handler_registry is None:
        _handler_registry = _build_handler_registry()
    return _handler_registry


def create_handler(platform: Platform) -> PlatformHandler | None:
    """Create a handler instance for the given platform.

    This is the main entry point for DirectAPIFetcher to obtain handlers.
    It encapsulates the registry lookup and handler instantiation.

    Args:
        platform: Platform enum value

    Returns:
        Handler instance, or None if platform not supported
    """
    registry = get_handler_registry()
    handler_class = registry.get(platform)
    if handler_class is None:
        return None
    return handler_class()


__all__ = [
    # Base classes
    "PlatformHandler",
    "GraphQLPlatformHandler",
    # Handler classes
    "JiraHandler",
    "LinearHandler",
    "GitHubHandler",
    "AzureDevOpsHandler",
    "TrelloHandler",
    "MondayHandler",
    # Registry functions
    "get_handler_registry",
    "create_handler",
]
