# Implementation Plan: AMI-52 - Phase 1.6: Create Backend Factory

**Ticket:** [AMI-52](https://linear.app/amiadspec/issue/AMI-52/phase-16-create-backend-factory)
**Status:** Draft
**Date:** 2026-02-01
**Labels:** MultiAgent
**Parent:** [AMI-45: Pluggable Multi-Agent Support](https://linear.app/amiadspec/issue/AMI-45)

---

## Summary

This ticket creates the `BackendFactory` class that provides a centralized factory for creating AI backend instances by platform. This follows the factory pattern similar to `ProviderRegistry` (AMI-17) but with a simpler, static approach.

**Why This Matters:**
- Provides a single entry point for backend instantiation across the entire SPEC codebase
- Encapsulates backend-specific import logic (lazy imports to avoid circular dependencies)
- Validates CLI installation with `verify_installed=True` option, providing actionable `BackendNotInstalledError` messages
- Enables Step 3 parallel execution to create fresh backend instances per task via `BackendFactory.create(platform)`
- Foundation for the onboarding flow and CLI integration in Phase 1.5+ and Phase 2

**Scope:**
- Create `spec/integrations/backends/factory.py` containing:
  - `BackendFactory` class with static `create()` method
  - Platform-to-backend mapping with lazy imports
  - Installation verification via `backend.check_installed()`
  - Support for string or `AgentPlatform` enum input
- Update `spec/integrations/backends/__init__.py` to export `BackendFactory`

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.6 (lines 1920-1990)

---

## Context

This is **Phase 1.6** of the Backend Infrastructure work (AMI-45), positioned immediately after the first concrete backend implementation:

### Related Phase Ordering

| Phase | Ticket | Description | Status |
|-------|--------|-------------|--------|
| 0 | AMI-44 | Baseline Behavior Tests | ✅ Done |
| 1.1 | AMI-47 | Backend Error Types | ✅ Done |
| 1.2 | AMI-48 | AIBackend Protocol | ✅ Done |
| 1.3 | AMI-49 | BaseBackend Abstract Class | ✅ Done |
| 1.4 | AMI-50 | Move Subagent Constants | ✅ Done |
| 1.5 | AMI-51 | Create AuggieBackend | ⏳ In Progress |
| **1.6** | **AMI-52** | **Create Backend Factory** | **← This Ticket** |
| 1.7 | AMI-53+ | Backend Platform Resolver | ⏳ Pending |

> **⚠️ Pre-Implementation Verification Required:** Before starting this ticket, verify that `spec/integrations/backends/auggie.py` exists and exports `AuggieBackend`. Run:
> ```bash
> python -c "from spec.integrations.backends.auggie import AuggieBackend; print('AuggieBackend available')"
> ```

> **📝 Note on Parent Specification:** The parent specification (`specs/Pluggable Multi-Agent Support.md`, lines 1967-1973) shows the *final* state of the factory with working imports for `ClaudeBackend` and `CursorBackend`. This implementation plan describes the *intermediate* state for Phase 1.6, where Claude and Cursor backends don't exist yet and raise `NotImplementedError` placeholders. The factory will be updated in Phase 3 (Claude) and Phase 4 (Cursor) to replace these placeholders with actual imports.

### Position in Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     spec/integrations/backends/                             │
│                                                                             │
│   errors.py (AMI-47)         base.py (AMI-48, AMI-49)                      │
│   ├── BackendError           ├── AIBackend (Protocol)                      │
│   ├── BackendNotConfiguredError  ├── BaseBackend (ABC)                     │
│   ├── BackendNotInstalledError   └── SubagentMetadata                      │
│   ├── BackendRateLimitError                                                │
│   └── BackendTimeoutError    auggie.py (AMI-51)                            │
│                              └── AuggieBackend                             │
│                                                                             │
│   factory.py (AMI-52) ← THIS TICKET                                        │
│   └── BackendFactory                                                        │
│       └── create(platform, model, verify_installed) -> AIBackend           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ used by
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   CLI Entry (spec/cli.py)                                                   │
│       backend = BackendFactory.create(platform, verify_installed=True)     │
│                                                                             │
│   Step 3 Parallel Execution (spec/workflow/step3_execute.py)               │
│       # Create fresh backend per parallel task                             │
│       task_backend = BackendFactory.create(state.backend_platform)         │
│                                                                             │
│   Onboarding Flow (spec/onboarding/flow.py)                                │
│       backend = BackendFactory.create(platform)                            │
│       installed, message = backend.check_installed()                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Comparison to ProviderRegistry (AMI-17)

| Aspect | ProviderRegistry | BackendFactory |
|--------|------------------|----------------|
| Pattern | Registry + Singleton | Static Factory |
| Registration | Decorator-based | Hardcoded mapping |
| Instance Caching | Yes (singleton per platform) | No (fresh instance each call) |
| Thread Safety | Lock-protected | Not needed (no shared state) |
| Use Case | Long-lived provider instances | Short-lived backend per-task |

**Rationale for Differences:**
- Backends are intentionally not cached because Step 3 creates fresh instances per parallel task
- Static factory is simpler since we have a known, fixed set of backends
- No decorator registration needed since backends are internal implementation details

---

## Current State Analysis

### Existing Infrastructure (Dependencies)

1. **`spec/integrations/backends/errors.py`** (AMI-47)
   - `BackendNotInstalledError` - Raised when CLI is not installed
   - Constructor: `BackendNotInstalledError(message: str)`

2. **`spec/integrations/backends/base.py`** (AMI-48, AMI-49)
   - `AIBackend` Protocol - Return type for factory
   - `BaseBackend` ABC - Extended by all concrete backends

3. **`spec/integrations/backends/auggie.py`** (AMI-51)
   - `AuggieBackend` - First concrete backend implementation
   - Constructor: `AuggieBackend(model: str = "")`
   - `check_installed()` method for CLI verification

4. **`spec/config/fetch_config.py`**
   - `AgentPlatform` enum: `AUGGIE`, `CLAUDE`, `CURSOR`, `AIDER`, `MANUAL`
   - `parse_ai_backend()` - Converts string to enum

### Future Backends (Placeholder Handling)

| Platform | Backend Class | Status | Factory Behavior |
|----------|---------------|--------|------------------|
| AUGGIE | `AuggieBackend` | ✅ Implemented | Create instance |
| CLAUDE | `ClaudeBackend` | ⏳ Phase 3 | Raise `NotImplementedError("Claude backend not yet implemented...")` |
| CURSOR | `CursorBackend` | ⏳ Phase 4 | Raise `NotImplementedError("Cursor backend not yet implemented...")` |
| AIDER | `AiderBackend` | ⏳ Future | Raise `ValueError("Aider backend not yet implemented")` |
| MANUAL | N/A | N/A | Raise `ValueError("Manual mode does not use an AI backend")` |

---

## Technical Approach

### File Structure

**Create:** `spec/integrations/backends/factory.py`

### Class Definition

```python
"""Factory for creating AI backend instances."""
from spec.config.fetch_config import AgentPlatform, parse_ai_backend
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendNotInstalledError


class BackendFactory:
    """Factory for creating AI backend instances.

    Use this factory instead of instantiating backends directly.
    This ensures consistent initialization and enables future extensions.

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
            platform: AI backend enum or string name (e.g., "auggie", "claude")
            model: Default model to use for this backend instance
            verify_installed: If True, verify CLI is installed before returning

        Returns:
            Configured AIBackend instance

        Raises:
            ConfigValidationError: If the platform string is invalid (from parse_ai_backend)
            NotImplementedError: If the platform is planned but not yet implemented (Claude, Cursor)
            ValueError: If the platform is not supported (Aider, Manual)
            BackendNotInstalledError: If verify_installed=True and CLI is missing
        """
        if isinstance(platform, str):
            platform = parse_ai_backend(platform)

        backend: AIBackend

        if platform == AgentPlatform.AUGGIE:
            from spec.integrations.backends.auggie import AuggieBackend
            backend = AuggieBackend(model=model)

        elif platform == AgentPlatform.CLAUDE:
            # Phase 3: Replace with actual import when ClaudeBackend is implemented
            # from spec.integrations.backends.claude import ClaudeBackend
            # backend = ClaudeBackend(model=model)
            raise NotImplementedError(
                "Claude backend not yet implemented. See Phase 3 of AMI-45."
            )

        elif platform == AgentPlatform.CURSOR:
            # Phase 4: Replace with actual import when CursorBackend is implemented
            # from spec.integrations.backends.cursor import CursorBackend
            # backend = CursorBackend(model=model)
            raise NotImplementedError(
                "Cursor backend not yet implemented. See Phase 4 of AMI-45."
            )

        elif platform == AgentPlatform.AIDER:
            # Future: Replace with actual import when AiderBackend is implemented
            # Note: Uses ValueError (not NotImplementedError) per parent spec line 1976
            # because Aider support is deferred indefinitely, not a planned phase.
            raise ValueError("Aider backend not yet implemented")

        elif platform == AgentPlatform.MANUAL:
            raise ValueError("Manual mode does not use an AI backend")

        else:
            raise ValueError(f"Unknown platform: {platform}")

        if verify_installed:
            installed, message = backend.check_installed()
            if not installed:
                raise BackendNotInstalledError(message)

        return backend
```

### Key Design Decisions

1. **Static method, no instance state**: The factory is stateless - all logic is in the static `create()` method. This is simpler than a class-based registry and matches the usage pattern (create fresh instances per-task).

2. **Lazy imports**: Backend classes are imported inside the `if` branches to avoid circular dependencies and reduce import time when only some backends are needed.

3. **String-to-enum conversion**: Accepts both `AgentPlatform` enum and string values (e.g., `"auggie"`, `"claude"`). Uses `parse_ai_backend()` from fetch_config.py for consistent parsing.

4. **verify_installed option**: When `True`, calls `backend.check_installed()` and raises `BackendNotInstalledError` if CLI is missing. This provides fail-fast behavior at creation time rather than at first use.

5. **Placeholder errors for unimplemented backends**: Claude and Cursor raise `NotImplementedError` with clear "not yet implemented" messages and phase references (these are planned phases). Aider raises `ValueError` because it's deferred indefinitely (not a planned phase). These will be replaced with actual imports as each phase completes.

6. **Manual mode error**: `AgentPlatform.MANUAL` explicitly raises an error since it doesn't use an AI backend.

---

## Implementation Phases

### Phase 1: Create File and Factory Class (~0.25 hours)

1. Create `spec/integrations/backends/factory.py`
2. Add module docstring and imports
3. Implement `BackendFactory` class with `create()` method
4. Add placeholder error handling for unimplemented backends
5. Verify imports work correctly

### Phase 2: Update Package Exports (~0.1 hours)

1. Add `BackendFactory` to `spec/integrations/backends/__init__.py`
2. Verify export works: `from spec.integrations.backends import BackendFactory`

### Phase 3: Write Unit Tests (~0.5 hours)

1. Create test file `tests/test_backend_factory.py` (follows existing flat pattern: `tests/test_backend_errors.py`, `tests/test_backend_protocol.py`)
2. Implement tests for all success and error cases
3. Run tests and fix any issues

**Total Estimated Time: ~0.85 hours (~0.35 days)**

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_backend_factory.py`

> **Note:** This follows the existing flat test file pattern in the repo (e.g., `tests/test_backend_errors.py`, `tests/test_backend_protocol.py`, `tests/test_base_backend.py`) rather than nested directories.

```python
"""Tests for spec.integrations.backends.factory module."""

import pytest

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendNotInstalledError
from spec.integrations.backends.factory import BackendFactory


class TestBackendFactoryCreate:
    """Tests for BackendFactory.create() method."""

    def test_create_auggie_backend_from_enum(self):
        """Create AuggieBackend from AgentPlatform enum."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_from_string(self):
        """Create AuggieBackend from string name."""
        backend = BackendFactory.create("auggie")
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_case_insensitive(self):
        """String platform name is case-insensitive."""
        backend = BackendFactory.create("AUGGIE")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_with_model_parameter(self):
        """Model parameter is passed to backend constructor."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="claude-3-opus")
        # Model is stored internally (implementation detail)
        assert backend is not None

    def test_create_returns_aibackend_instance(self):
        """Returned backend satisfies AIBackend protocol."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert isinstance(backend, AIBackend)


class TestBackendFactoryUnimplementedPlatforms:
    """Tests for unimplemented backend platforms."""

    def test_create_claude_raises_not_implemented(self):
        """Claude backend raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError, match="Claude backend not yet implemented"):
            BackendFactory.create(AgentPlatform.CLAUDE)

    def test_create_cursor_raises_not_implemented(self):
        """Cursor backend raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError, match="Cursor backend not yet implemented"):
            BackendFactory.create(AgentPlatform.CURSOR)

    def test_create_aider_raises_value_error(self):
        """Aider backend raises ValueError (deferred indefinitely, not a planned phase)."""
        with pytest.raises(ValueError, match="Aider backend not yet implemented"):
            BackendFactory.create(AgentPlatform.AIDER)

    def test_create_manual_raises_value_error(self):
        """Manual mode raises ValueError (no AI backend - this is permanent, not unimplemented)."""
        with pytest.raises(ValueError, match="Manual mode does not use an AI backend"):
            BackendFactory.create(AgentPlatform.MANUAL)


class TestBackendFactoryVerifyInstalled:
    """Tests for verify_installed parameter."""

    def test_verify_installed_true_with_installed_cli(self, mocker):
        """verify_installed=True succeeds when CLI is installed."""
        # Mock check_installed to return (True, "version info")
        mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(True, "Auggie CLI v1.0.0"),
        )
        backend = BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        assert backend is not None

    def test_verify_installed_true_raises_when_cli_missing(self, mocker):
        """verify_installed=True raises BackendNotInstalledError when CLI missing."""
        # Mock check_installed to return (False, "error message")
        mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(False, "Auggie CLI not found. Install from https://..."),
        )
        with pytest.raises(BackendNotInstalledError):
            BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)

    def test_verify_installed_false_skips_check(self, mocker):
        """verify_installed=False (default) does not call check_installed."""
        mock_check = mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
        )
        BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=False)
        mock_check.assert_not_called()


class TestBackendFactoryInvalidInput:
    """Tests for invalid input handling."""

    def test_create_unknown_platform_string_raises(self):
        """Unknown platform string raises ConfigValidationError.

        Note: The parent spec's TestBackendFactory (line 4366-4368) shows
        `pytest.raises(ValueError)`, but the actual behavior is ConfigValidationError
        because parse_ai_backend() raises ConfigValidationError for invalid values.
        This test reflects the actual implementation behavior.
        """
        from spec.config.fetch_config import ConfigValidationError
        with pytest.raises(ConfigValidationError):
            BackendFactory.create("unknown_platform")


class TestBackendFactoryStringNormalization:
    """Tests for string input normalization (Linear ticket requirement)."""

    def test_create_strips_whitespace_from_string(self):
        """String platform name handles leading/trailing whitespace."""
        backend = BackendFactory.create("  auggie  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_handles_mixed_case_with_whitespace(self):
        """String platform name handles mixed case and whitespace."""
        backend = BackendFactory.create("  AuGgIe  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_empty_string_returns_default(self):
        """Empty string returns default platform (AUGGIE).

        Note: This behavior comes from parse_ai_backend() which has
        default=AgentPlatform.AUGGIE. If the "no default backend" policy
        from Final Decision #2 is enforced in parse_ai_backend(),
        this test should be updated to expect ConfigValidationError.
        """
        # Current behavior: empty string returns default (AUGGIE)
        backend = BackendFactory.create("")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_whitespace_only_string_returns_default(self):
        """Whitespace-only string returns default platform."""
        backend = BackendFactory.create("   ")
        assert backend.platform == AgentPlatform.AUGGIE


class TestBackendFactoryThreadSafety:
    """Tests for thread safety in concurrent usage."""

    def test_create_is_thread_safe(self):
        """Factory creates independent instances for concurrent calls."""
        import threading

        backends = []
        errors = []
        lock = threading.Lock()

        def create_backend():
            try:
                backend = BackendFactory.create(AgentPlatform.AUGGIE)
                with lock:
                    backends.append(backend)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=create_backend) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent creation: {errors}"
        assert len(backends) == 10
        # Verify all are independent instances (different object IDs)
        assert len(set(id(b) for b in backends)) == 10


class TestBackendFactoryLazyImports:
    """Tests for lazy import behavior.

    ⚠️ IMPORTANT: These tests verify that factory.py itself uses lazy imports
    (imports inside if-branches). However, the package __init__.py currently
    imports AuggieBackend eagerly at package load time:

        from spec.integrations.backends.auggie import AuggieBackend

    This means importing `spec.integrations.backends.factory` will trigger
    the package __init__.py, which imports auggie.py anyway.

    The lazy import pattern in factory.py is still valuable because:
    1. Direct imports of factory.py bypass the package __init__.py
    2. It sets up the correct pattern for when/if we switch to PEP 562 lazy exports
    3. It avoids circular imports within the factory module itself

    If true lazy loading at the package level is required, the __init__.py
    would need to be refactored to use PEP 562 __getattr__ lazy exports.
    """

    def test_factory_module_has_no_toplevel_backend_imports(self):
        """Verify factory.py doesn't have top-level backend imports.

        This is a code structure test, not a runtime import test.
        It verifies the factory follows the lazy import pattern by checking
        that backend imports are inside the create() method, not at module level.
        """
        import ast
        from pathlib import Path

        factory_path = Path("spec/integrations/backends/factory.py")
        if not factory_path.exists():
            pytest.skip("factory.py not yet created")

        source = factory_path.read_text()
        tree = ast.parse(source)

        # Find all top-level imports (not inside functions/classes)
        toplevel_imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    toplevel_imports.append(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        toplevel_imports.append(alias.name)

        # Backend modules should NOT be in top-level imports
        backend_modules = [
            "spec.integrations.backends.auggie",
            "spec.integrations.backends.claude",
            "spec.integrations.backends.cursor",
        ]
        for backend_module in backend_modules:
            assert backend_module not in toplevel_imports, (
                f"Backend module {backend_module} should not be imported at top level. "
                f"Use lazy import inside create() method."
            )


# NOTE: TestBackendFactoryImportErrors has been removed.
#
# The original test used `__builtins__.__import__` patching which is fragile
# because `__builtins__` can be either a module or a dict depending on context.
# This approach is unreliable across different Python environments and test runners.
#
# Import error propagation is implicitly tested by Python's normal import behavior -
# if a backend module fails to import, the ImportError will naturally propagate.
# Adding an explicit test for this edge case provides minimal value and introduces
# test fragility. If import error handling becomes a requirement, consider using
# `unittest.mock.patch.dict(sys.modules, ...)` or a custom import hook instead.
```

### Integration Tests (Gated)

Integration tests with real CLI are gated behind `SPEC_INTEGRATION_TESTS=1`:

```python
import os
import pytest

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.factory import BackendFactory

pytestmark = pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests require SPEC_INTEGRATION_TESTS=1",
)


class TestBackendFactoryIntegration:
    """Integration tests with real CLI."""

    def test_create_auggie_with_verify_installed(self):
        """Create AuggieBackend and verify CLI is installed."""
        # This will fail if Auggie CLI is not installed
        backend = BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        assert backend.name == "Auggie"

    # TODO (Phase 3): Add test_create_claude_with_verify_installed
    # TODO (Phase 4): Add test_create_cursor_with_verify_installed
    # These tests should be added when the respective backends are implemented.
```

---

## Edge Cases & Error Handling

### Edge Case 1: Missing CLI Executables

**Scenario:** User tries to create a backend but the CLI is not installed.

**Handling:**
- If `verify_installed=True`: Raise `BackendNotInstalledError` with actionable message
- If `verify_installed=False` (default): Backend is created, error occurs at first use

**Example:**
```python
try:
    backend = BackendFactory.create("auggie", verify_installed=True)
except BackendNotInstalledError as e:
    print(f"CLI not installed: {e}")
    print("Install from: https://docs.augmentcode.com/cli")
```

### Edge Case 2: Invalid Platform Names

**Scenario:** User passes an invalid platform string like "chatgpt" or "openai".

**Handling:** `parse_ai_backend()` raises `ConfigValidationError` with list of valid platforms.

**Example:**
```python
>>> BackendFactory.create("chatgpt")
ConfigValidationError: Invalid AI backend 'chatgpt'. Allowed values: auggie, claude, cursor, aider, manual
```

### Edge Case 2.5: Empty or Whitespace-Only String

**Scenario:** User passes an empty string `""` or whitespace-only string `"   "`.

**Current Handling:** `parse_ai_backend()` has `default=AgentPlatform.AUGGIE`, so empty/whitespace strings return AUGGIE.

```python
>>> BackendFactory.create("")
<AuggieBackend>  # Returns default

>>> BackendFactory.create("   ")
<AuggieBackend>  # Returns default
```

**⚠️ Note on "No Default Backend" Policy:** The parent specification (Final Decision #2) states "No default backend: if neither CLI `--backend` nor `AI_BACKEND` config is set, fail fast with `BackendNotConfiguredError`." However, this policy is enforced at the **resolver level** (`resolve_backend_platform()`), not at the factory level. The factory delegates to `parse_ai_backend()` which currently has a default.

If the "no default" policy should be enforced at the factory level, `parse_ai_backend()` would need to be called with `default=None` and handle the resulting error. This is a design decision for a future ticket if needed.

### Edge Case 3: Model Configuration Precedence

**Scenario:** Model is specified at factory creation, but subagent frontmatter also has a model.

**Handling:** This is handled by `BaseBackend._resolve_model()` in the concrete backends, not by the factory. The factory simply passes the `model` parameter to the backend constructor.

**Precedence (in backend execution):**
1. Explicit `model` parameter in method call
2. Subagent YAML frontmatter `model:` field
3. Instance default (from factory's `model` parameter)

### Edge Case 4: Thread Safety in Parallel Execution

**Scenario:** Step 3 creates multiple backends concurrently via `ThreadPoolExecutor`.

**Handling:** `BackendFactory.create()` is stateless and thread-safe. Each call creates a new, independent backend instance.

```python
def execute_task(task: Task) -> None:
    # Thread-safe: each task gets its own backend
    backend = BackendFactory.create(state.backend_platform)
    try:
        success, output = backend.run_with_callback(...)
    finally:
        backend.close()
```

---

## Dependencies

### Upstream Dependencies (Required Before Starting)

| Ticket | Description | Status |
|--------|-------------|--------|
| AMI-47 | Backend Error Types (`BackendNotInstalledError`) | ✅ Done |
| AMI-48 | AIBackend Protocol | ✅ Done |
| AMI-49 | BaseBackend Abstract Class | ✅ Done |
| AMI-50 | Move Subagent Constants | ✅ Done |
| AMI-51 | Create AuggieBackend | ⏳ In Progress |

> **⚠️ Blocking Dependency:** AMI-51 must be completed before starting this ticket. Verify with:
> ```bash
> python -c "from spec.integrations.backends.auggie import AuggieBackend; print('Ready')"
> ```

### Downstream Dependencies (Blocked By This)

| Ticket | Description | How Factory is Used |
|--------|-------------|---------------------|
| AMI-53+ | Backend Platform Resolver | Uses factory to create backends after resolution |
| Phase 1.5+ | Fetcher Refactoring | Uses factory to create backends for fetchers |
| Phase 2 | Workflow Refactoring | Step 3 uses factory for parallel task execution |
| Phase 3 | ClaudeBackend | Factory imports and instantiates ClaudeBackend |
| Phase 4 | CursorBackend | Factory imports and instantiates CursorBackend |
| Phase 5 | Onboarding Flow | Factory creates backends for CLI verification |

---

## Verification Commands

```bash
# Verify file exists
ls -la spec/integrations/backends/factory.py

# Verify imports work without cycles
python -c "from spec.integrations.backends.factory import BackendFactory; print('Import OK')"

# Verify factory creates Auggie backend
python -c "
from spec.integrations.backends.factory import BackendFactory
from spec.config.fetch_config import AgentPlatform
backend = BackendFactory.create(AgentPlatform.AUGGIE)
assert backend.name == 'Auggie'
print('Factory creates AuggieBackend: OK')
"

# Verify factory accepts string input
python -c "
from spec.integrations.backends.factory import BackendFactory
backend = BackendFactory.create('auggie')
assert backend.name == 'Auggie'
print('Factory accepts string: OK')
"

# Verify case insensitivity
python -c "
from spec.integrations.backends.factory import BackendFactory
backend = BackendFactory.create('AUGGIE')
assert backend.name == 'Auggie'
print('Case insensitivity: OK')
"

# Verify whitespace handling
python -c "
from spec.integrations.backends.factory import BackendFactory
backend = BackendFactory.create('  auggie  ')
assert backend.name == 'Auggie'
print('Whitespace handling: OK')
"

# Verify unimplemented backends raise NotImplementedError
python -c "
from spec.integrations.backends.factory import BackendFactory
try:
    BackendFactory.create('claude')
except NotImplementedError as e:
    assert 'not yet implemented' in str(e)
    print('Claude placeholder: OK')
"

# Verify Aider raises ValueError (deferred indefinitely, not a planned phase)
python -c "
from spec.integrations.backends.factory import BackendFactory
try:
    BackendFactory.create('aider')
except ValueError as e:
    assert 'Aider backend not yet implemented' in str(e)
    print('Aider error: OK')
"

# Verify Manual mode raises ValueError (permanent, not unimplemented)
python -c "
from spec.integrations.backends.factory import BackendFactory
try:
    BackendFactory.create('manual')
except ValueError as e:
    assert 'Manual mode does not use an AI backend' in str(e)
    print('Manual mode error: OK')
"

# Verify package export
python -c "from spec.integrations.backends import BackendFactory; print('Export OK')"

# Run unit tests
pytest tests/test_backend_factory.py -v

# Run mypy type checking (uses project's pyproject.toml config, no --strict override)
mypy spec/integrations/backends/factory.py

# Verify no import cycles
python -c "
from spec.integrations.backends.factory import BackendFactory
from spec.integrations.backends.base import AIBackend, BaseBackend
from spec.integrations.backends.errors import BackendNotInstalledError
print('No import cycles detected')
"
```

---

## Definition of Done

### Implementation Checklist

- [ ] `spec/integrations/backends/factory.py` created
- [ ] `BackendFactory` class with static `create()` method
- [ ] `create()` accepts `AgentPlatform` enum or string
- [ ] `create()` returns `AIBackend` instance for supported platforms
- [ ] Lazy imports for backend classes (inside `if` branches)
- [ ] `verify_installed=True` calls `check_installed()` and raises `BackendNotInstalledError`
- [ ] `verify_installed=False` (default) skips installation check
- [ ] Placeholder `NotImplementedError` for unimplemented backends (Claude, Cursor) with phase references
- [ ] `ValueError` for Aider (deferred indefinitely, not a planned phase)
- [ ] `ValueError` for Manual mode (permanent behavior, not unimplemented)
- [ ] `BackendFactory` exported from `spec/integrations/backends/__init__.py`

### Quality Checklist

- [ ] All methods have complete docstrings with Args, Returns, Raises
- [ ] `mypy` reports no type errors (uses project's pyproject.toml config)
- [ ] No import cycles introduced
- [ ] Unit tests pass (`pytest tests/test_backend_factory.py`)
- [ ] No regressions in existing tests (`pytest tests/`)

### Acceptance Criteria

| AC | Description | Verification Method | Status |
|----|-------------|---------------------|--------|
| **AC1** | `BackendFactory.create(AgentPlatform.AUGGIE)` returns `AuggieBackend` | Unit test | [ ] |
| **AC2** | `BackendFactory.create("auggie")` returns `AuggieBackend` | Unit test | [ ] |
| **AC3** | `verify_installed=True` raises `BackendNotInstalledError` when CLI missing | Unit test with mock | [ ] |
| **AC4** | Unimplemented backends (Claude, Cursor) raise `NotImplementedError` with phase reference | Unit tests | [ ] |
| **AC4b** | Aider raises `ValueError` (deferred indefinitely, per parent spec line 1976) | Unit test | [ ] |
| **AC5** | Manual mode raises `ValueError` (permanent, not unimplemented) | Unit test | [ ] |
| **AC6** | `BackendFactory` exported from `spec/integrations/backends` | Import test | [ ] |
| **AC7** | String input is case-insensitive and whitespace-trimmed | Unit tests | [ ] |
| **AC8** | Factory is thread-safe (creates independent instances) | Unit test | [ ] |
| **AC9** | Backend imports are lazy (inside `if` branches in factory.py) | AST-based unit test | [ ] |

> **Note:** AC10 (import error propagation) was removed. Import errors naturally propagate via Python's import mechanism; adding a fragile mock-based test provides minimal value.

---

## References

### Specification References

| Document | Section | Description |
|----------|---------|-------------|
| `specs/Pluggable Multi-Agent Support.md` | Lines 1920-1990 | Phase 1.6: Backend Factory specification |
| `specs/Pluggable Multi-Agent Support.md` | Lines 2044-2055 | Phase 1 Testing Strategy for factory |
| `specs/Pluggable Multi-Agent Support.md` | Lines 4343-4373 | TestBackendFactory test examples |

### Codebase References

| File | Description |
|------|-------------|
| `spec/integrations/backends/errors.py` | BackendNotInstalledError definition |
| `spec/integrations/backends/base.py` | AIBackend protocol, BaseBackend class |
| `spec/integrations/backends/auggie.py` | AuggieBackend implementation |
| `spec/config/fetch_config.py` | AgentPlatform enum, parse_ai_backend() |
| `spec/integrations/providers/registry.py` | ProviderRegistry for pattern comparison |

### Related Implementation Plans

| Document | Description |
|----------|-------------|
| `specs/AMI-47-implementation-plan.md` | Backend Error Types |
| `specs/AMI-48-implementation-plan.md` | AIBackend Protocol |
| `specs/AMI-49-implementation-plan.md` | BaseBackend Abstract Class |
| `specs/AMI-50-implementation-plan.md` | Move Subagent Constants |
| `specs/AMI-51-implementation-plan.md` | Create AuggieBackend |

---

## Appendix: __init__.py Update

Update `spec/integrations/backends/__init__.py` to **add** `BackendFactory` export while **keeping all existing exports** (including `AuggieBackend`):

> **⚠️ Important:** The current `__init__.py` already exports `AuggieBackend`. This update adds `BackendFactory` to the existing exports—it does NOT replace them.

```python
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

from spec.integrations.backends.auggie import AuggieBackend  # Keep existing export
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
from spec.integrations.backends.factory import BackendFactory  # NEW: Add factory export

# Explicit public API for IDE support and documentation.
# All exported symbols should be listed here.
__all__ = [
    # Protocol and base class
    "AIBackend",
    "BaseBackend",
    "SubagentMetadata",
    # Backend implementations
    "AuggieBackend",  # Keep existing export
    # Error types
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
    # Factory
    "BackendFactory",  # NEW
]
```

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-02-01 | AI Assistant | Initial draft created following AMI-51 template |
| 2026-02-01 | AI Assistant | **Review updates:** (1) Changed AMI-51 status to "In Progress" with pre-implementation verification step; (2) Changed unimplemented backends from `ValueError` to `NotImplementedError` with phase references; (3) Added string normalization tests (whitespace, case); (4) Added empty string edge case documentation; (5) Added thread safety test; (6) Added lazy import verification test; (7) Added verification commands for case insensitivity and whitespace handling; (8) Updated acceptance criteria with AC6-AC9; (9) Added Edge Case 2.5 documenting empty string behavior and "no default" policy note |
| 2026-02-01 | AI Assistant | **Completeness review updates:** (1) **CRITICAL:** Changed AIDER error type from `NotImplementedError` to `ValueError` to match parent spec line 1976 - Aider is deferred indefinitely, not a planned phase; (2) Added clarifying note that parent spec's factory code (lines 1967-1973) shows *final* state with Claude/Cursor imports, while this implementation is *intermediate* state for Phase 1.6; (3) Added note to `test_create_unknown_platform_string_raises` explaining that `ConfigValidationError` is correct (not `ValueError` as shown in parent spec line 4367); (4) Added `TestBackendFactoryImportErrors` class with test for handling missing backend module imports; (5) Added verification command for Aider error; (6) Split AC4 into AC4 (Claude/Cursor → NotImplementedError) and AC4b (Aider → ValueError); (7) Added AC10 for import error propagation; (8) Updated implementation checklist to distinguish Aider from Claude/Cursor error handling |
| 2026-02-01 | AI Assistant | **Peer review fixes:** Addressed all issues from external review: (1) Fixed "Future Backends" table - Claude/Cursor now show `NotImplementedError` (was incorrectly `ValueError`); (2) Fixed "Key Design Decisions" section - now correctly states Aider raises `ValueError`, not `NotImplementedError`; (3) Updated docstring Raises section to document `ConfigValidationError` for invalid strings (was incorrectly `ValueError`); (4) Changed test file location from `tests/integrations/backends/test_factory.py` to `tests/test_backend_factory.py` to match repo's flat test pattern; (5) Rewrote `TestBackendFactoryLazyImports` - replaced fragile runtime test with AST-based code structure test, added documentation about package `__init__.py` eager imports; (6) Removed `TestBackendFactoryImportErrors` - `__builtins__.__import__` patching is fragile across environments; (7) Fixed `__init__.py` appendix to **add** `BackendFactory` while **keeping** existing `AuggieBackend` export; (8) Removed `--strict` from mypy command to use project's pyproject.toml config; (9) Updated Quality Checklist and verification commands with correct test path; (10) Removed AC10 (import error propagation) since test was removed |
