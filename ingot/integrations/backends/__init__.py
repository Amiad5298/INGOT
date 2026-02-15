"""Backend infrastructure for AI agent integrations.

This package provides a unified abstraction layer for AI backends:
- Auggie (Augment Code CLI)
- Claude (Claude Code CLI)
- Cursor (Cursor IDE)
- Aider (Aider CLI)
- Gemini (Gemini CLI)
- Codex (OpenAI Codex CLI)

Modules:
- errors: Backend-related error types
- base: AIBackend protocol, BaseBackend class, and SubagentMetadata
- auggie: AuggieBackend implementation (Phase 1.5)
- factory: Backend factory for instantiation (Phase 1.6+)
"""

# Eager imports: base types, errors, factory (no circular risk)
from ingot.integrations.backends.base import (
    AIBackend,
    BackendModel,
    BaseBackend,
    SubagentMetadata,
)
from ingot.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)
from ingot.integrations.backends.factory import BackendFactory

# Lazy imports for concrete backend classes to break circular import chains.
# The eager import of all 6 backends triggers: backends/__init__ → auggie.py →
# ingot.utils → ingot.utils.retry → backends/__init__ (cycle).
# __getattr__ defers the import until the class is actually accessed.
_LAZY_BACKENDS = {
    "AiderBackend": "ingot.integrations.backends.aider",
    "AuggieBackend": "ingot.integrations.backends.auggie",
    "ClaudeBackend": "ingot.integrations.backends.claude",
    "CodexBackend": "ingot.integrations.backends.codex",
    "CursorBackend": "ingot.integrations.backends.cursor",
    "GeminiBackend": "ingot.integrations.backends.gemini",
}


def __getattr__(name: str) -> type:
    if name in _LAZY_BACKENDS:
        import importlib

        mod = importlib.import_module(_LAZY_BACKENDS[name])
        cls: type = getattr(mod, name)
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Explicit public API for IDE support and documentation.
# All exported symbols should be listed here.
__all__ = [
    # Protocol and base class
    "AIBackend",
    "BackendModel",
    "BaseBackend",
    "SubagentMetadata",
    # Backend implementations
    "AiderBackend",
    "AuggieBackend",
    "ClaudeBackend",
    "CodexBackend",
    "CursorBackend",
    "GeminiBackend",
    # Error types
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
    # Factory
    "BackendFactory",
]
