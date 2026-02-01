"""Backend infrastructure for AI agent integrations.

This package provides a unified abstraction layer for AI backends:
- Auggie (Augment Code CLI)
- Claude (Claude Code CLI)
- Cursor (Cursor IDE)
- Aider (Aider CLI)

Modules:
- errors: Backend-related error types
- base: AIBackend protocol, BaseBackend class, and SubagentMetadata
- auggie: AuggieBackend implementation (Phase 1.5)
- factory: Backend factory for instantiation (Phase 1.6+)
"""

from spec.integrations.backends.auggie import AuggieBackend
from spec.integrations.backends.base import (
    AIBackend,
    BaseBackend,
    SubagentMetadata,
)
from spec.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)
from spec.integrations.backends.factory import BackendFactory

# Explicit public API for IDE support and documentation.
# All exported symbols should be listed here.
__all__ = [
    # Protocol and base class
    "AIBackend",
    "BaseBackend",
    "SubagentMetadata",
    # Backend implementations
    "AuggieBackend",
    # Error types
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
    # Factory
    "BackendFactory",
]
