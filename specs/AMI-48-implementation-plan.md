# Implementation Plan: AMI-48 - Phase 1.2: Create AIBackend Protocol

**Ticket:** [AMI-48](https://linear.app/amiadspec/issue/AMI-48/phase-12-create-aibackend-protocol)
**Status:** Draft
**Date:** 2026-02-01
**Labels:** MultiAgent

---

## Summary

This ticket defines the `AIBackend` Protocol that all backend implementations must satisfy. The protocol serves as the foundational contract for the multi-backend abstraction layer, enabling workflow code to interact with any AI backend (Auggie, Claude, Cursor) through a unified interface.

**Why This Matters:**
- The current codebase has an `AuggieClientProtocol` in `spec/workflow/step4_update_docs.py` (lines 517-539) that is Auggie-specific
- The new `AIBackend` protocol provides a generalized abstraction for all backends
- This enables dependency injection of backends into workflow steps
- Protocol-based design allows for static type checking and runtime validation via `@runtime_checkable`

**Scope:**
- Create `spec/integrations/backends/base.py` with:
  - `AIBackend` Protocol (defines contract for all backends)
  - All required properties: `name`, `platform`, `supports_parallel`
  - All required methods: execution methods, `check_installed()`, `detect_rate_limit()`, `close()`
- Update `spec/integrations/backends/__init__.py` to export the new protocol

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.2 (lines 1297-1432)

---

## Context

This is **Phase 1.2** of the Backend Infrastructure work (AMI-45), which is part of the larger Pluggable Multi-Agent Support initiative.

### Parent Specification

The [Pluggable Multi-Agent Support](./Pluggable%20Multi-Agent%20Support.md) specification defines a phased approach to support multiple AI backends:

- **Phase 0:** Baseline Behavior Tests (AMI-44) ✅ Done
- **Phase 1.0:** Rename Claude Platform Enum (AMI-46) ⏳ Backlog
- **Phase 1.1:** Create Backend Error Types (AMI-47) ⏳ Backlog - **Dependency**
- **Phase 1.2:** Create AIBackend Protocol (AMI-48) ← **This Ticket**
- **Phase 1.3+:** BaseBackend, AuggieBackend, Factory, etc.

### Position in Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     spec/integrations/backends/base.py                       │
│                                                                              │
│   AIBackend (Protocol)                                                       │
│       ├── name: str (property)                                              │
│       ├── platform: AgentPlatform (property)                                │
│       ├── supports_parallel: bool (property)                                │
│       ├── run_with_callback(...) -> tuple[bool, str]                        │
│       ├── run_print_with_output(...) -> tuple[bool, str]                    │
│       ├── run_print_quiet(...) -> str                                       │
│       ├── run_streaming(...) -> tuple[bool, str]                            │
│       ├── check_installed() -> tuple[bool, str]                             │
│       ├── detect_rate_limit(output: str) -> bool                            │
│       ├── supports_parallel_execution() -> bool                             │
│       └── close() -> None                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ implemented by (Phase 1.3+)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   BaseBackend (ABC)           ←  Shared implementation (Phase 1.3)          │
│       ├── AuggieBackend       ←  Wraps AuggieClient (Phase 1.4)             │
│       ├── ClaudeBackend       ←  Wraps ClaudeClient (Phase 3)               │
│       └── CursorBackend       ←  Wraps CursorClient (Phase 4)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Replaces AuggieClientProtocol

The current `AuggieClientProtocol` in `step4_update_docs.py` (lines 517-539) is a minimal protocol specific to Auggie:

```python
class AuggieClientProtocol(Protocol):
    """Protocol for AuggieClient to allow dependency injection."""
    def run_print_with_output(...) -> tuple[bool, str]: ...
    def run_with_callback(...) -> tuple[bool, str]: ...
```

The new `AIBackend` protocol:
- Is more comprehensive (includes all execution methods)
- Adds capability discovery (`supports_parallel`, `check_installed()`)
- Adds error handling support (`detect_rate_limit()`)
- Is backend-agnostic (no Auggie-specific naming)
- Will completely replace `AuggieClientProtocol` in Phase 2 workflow integration

---

## Technical Approach

### Comparison: Current vs. New

| Current (`AuggieClientProtocol`) | New (`AIBackend`) |
|----------------------------------|-------------------|
| In `step4_update_docs.py` | In `spec/integrations/backends/base.py` |
| 2 methods only | 8 methods + 3 properties |
| Auggie-specific naming | Backend-agnostic |
| No capability flags | `supports_parallel` property |
| No installation check | `check_installed()` method |
| No rate limit detection | `detect_rate_limit()` method |
| Not runtime checkable | `@runtime_checkable` decorator |

### Key Design Decisions

1. **Use `typing.Protocol`**: Enables structural subtyping for static type checking without requiring inheritance.

2. **Apply `@runtime_checkable`**: Allows `isinstance()` checks at runtime for validation in factories.

3. **Properties for Immutable Attributes**: `name`, `platform`, and `supports_parallel` are properties, not methods, because they are intrinsic to the backend and don't change.

4. **No `run_print()` Method**: Per Final Decision #4 in the spec, the protocol does NOT include `run_print()` (interactive mode). SPEC owns interactive UX; backends execute in non-interactive mode only.

5. **Consistent Return Types**:
   - Execution methods return `tuple[bool, str]` (success, output)
   - `run_print_quiet()` returns `str` only (matches existing `AuggieClient` behavior)
   - `check_installed()` returns `tuple[bool, str]` (installed, message)

6. **Timeout Parameter**: All execution methods accept `timeout_seconds: float | None` for streaming-safe timeout enforcement.

7. **Import Dependencies**: The protocol imports from existing modules:
   - `AgentPlatform` from `spec.config.fetch_config`
   - Error types from `spec.integrations.backends.errors` (AMI-47 dependency)

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `spec/integrations/backends/base.py` | **CREATE** | AIBackend Protocol definition |
| `spec/integrations/backends/__init__.py` | **MODIFY** | Export AIBackend |

---

## Implementation Phases

### Phase 1: Create AIBackend Protocol

#### Step 1.1: Create base.py with AIBackend Protocol

**File:** `spec/integrations/backends/base.py`

```python
"""AI Backend protocol and base types.

This module defines the contract for AI backend integrations:
- AIBackend: Protocol for all backend implementations
- BaseBackend: Abstract base class with shared logic (Phase 1.3)

All backends execute in non-interactive mode for deterministic behavior.
User input is collected via the TUI, then included in prompts.
"""

from typing import Callable, Protocol, runtime_checkable

from spec.config.fetch_config import AgentPlatform


@runtime_checkable
class AIBackend(Protocol):
    """Protocol for AI backend integrations.

    This defines the contract for AI providers (Auggie, Claude Code, Cursor).
    Each backend wraps its respective CLI tool.

    All methods execute in non-interactive mode for deterministic behavior.
    User input is collected via the TUI, then included in prompts.

    Note: This protocol does NOT include run_print() (interactive mode).
    SPEC owns interactive UX; backends operate in streaming/print mode only.

    Example:
        >>> def run_workflow(backend: AIBackend) -> None:
        ...     success, output = backend.run_with_callback(
        ...         "Generate a plan",
        ...         output_callback=print,
        ...         subagent="spec-planner",
        ...     )
        ...     if not success:
        ...         if backend.detect_rate_limit(output):
        ...             raise BackendRateLimitError(...)
    """

    @property
    def name(self) -> str:
        """Human-readable backend name.

        Examples: 'Auggie', 'Claude Code', 'Cursor'
        """
        ...

    @property
    def platform(self) -> AgentPlatform:
        """The agent platform enum value.

        Returns the AgentPlatform enum member for this backend.
        Used for configuration and logging.
        """
        ...

    @property
    def supports_parallel(self) -> bool:
        """Whether this backend supports parallel execution.

        If False, Step 3 falls back to sequential task execution.
        If True, Step 3 can spawn concurrent backend invocations.

        Note: This property indicates capability, not a setting.
        Use --no-parallel CLI flag to disable parallel execution
        even for backends that support it.
        """
        ...

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt with streaming output (non-interactive).

        This is the primary execution method. Output is streamed line-by-line
        to the callback while also being accumulated for the return value.

        Args:
            prompt: The prompt to send to the AI
            output_callback: Called for each line of output (stripped of newline)
            subagent: Subagent name (loads prompt from .augment/agents/{name}.md)
            model: Model override (best-effort, safely ignored if unsupported)
            dont_save_session: If True, isolate this execution (no session persistence)
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            Tuple of (success, full_output) where:
            - success: True if command returned exit code 0
            - full_output: All output lines joined (preserves newlines)

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded
            BackendNotInstalledError: If CLI is not installed
        """
        ...

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt (non-interactive) and return output.

        Convenience method that wraps run_with_callback with a default
        print callback. Output is printed to stdout as it streams.

        Args:
            prompt: The prompt to send to the AI
            subagent: Subagent name (loads prompt from .augment/agents/{name}.md)
            model: Model override (best-effort, safely ignored if unsupported)
            dont_save_session: If True, isolate this execution
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            Tuple of (success, full_output)
        """
        ...

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute prompt quietly (non-interactive) and return output only.

        No output is printed during execution. This is used for background
        operations where only the final result matters.

        Args:
            prompt: The prompt to send to the AI
            subagent: Subagent name (loads prompt from .augment/agents/{name}.md)
            model: Model override (best-effort, safely ignored if unsupported)
            dont_save_session: If True, isolate this execution
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            The full output as a string (success is not indicated)

        Note:
            Callers must check the content to determine success/failure.
            This matches the existing AuggieClient.run_print_quiet() behavior.
        """
        ...

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt in streaming/print mode (non-interactive).

        This replaces interactive run_print() usage. User input should be
        collected via TUI first, then included in the prompt.

        Args:
            prompt: The prompt to send (with any user input already included)
            subagent: Subagent name (loads prompt from .augment/agents/{name}.md)
            model: Model override (best-effort, safely ignored if unsupported)
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            Tuple of (success, full_output)
        """
        ...

    def check_installed(self) -> tuple[bool, str]:
        """Check if the backend CLI is installed and functional.

        Verifies that the CLI executable is available in PATH and can
        execute a basic command (typically --version).

        Returns:
            Tuple of (is_installed, message) where:
            - is_installed: True if CLI is available and functional
            - message: Version string if installed, error message if not

        Example:
            >>> installed, msg = backend.check_installed()
            >>> if not installed:
            ...     raise BackendNotInstalledError(msg)
        """
        ...

    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error.

        Backend-specific pattern matching for rate limit detection.
        Each backend implements patterns appropriate for its provider.

        Args:
            output: The output text to check

        Returns:
            True if output contains rate limit indicators

        Example patterns:
            - HTTP 429 status codes
            - "rate limit", "rate_limit"
            - "quota exceeded"
            - "too many requests"
            - "throttle", "throttling"
        """
        ...

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle concurrent invocations.

        Returns the value of the `supports_parallel` property.
        This method exists for explicit API clarity in workflow code.

        Returns:
            True if multiple CLI invocations can run concurrently
        """
        ...

    def close(self) -> None:
        """Release any resources held by the backend.

        Called when workflow completes or on cleanup.
        Default implementation is no-op for stateless backends.

        Implementations may:
        - Terminate subprocess connections
        - Close file handles
        - Clean up temporary files
        """
        ...
```

### Phase 2: Update Package Exports

#### Step 2.1: Update __init__.py to Export AIBackend

**File:** `spec/integrations/backends/__init__.py`

Add the AIBackend import and export:

```python
"""Backend infrastructure for AI agent integrations.

This package provides a unified abstraction layer for AI backends:
- Auggie (Augment Code CLI)
- Claude (Claude Code CLI)
- Cursor (Cursor IDE)
- Aider (Aider CLI)

Modules:
- errors: Backend-related error types
- base: AIBackend protocol and BaseBackend class
- factory: Backend factory for instantiation (Phase 1.6+)
"""

from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)

# Explicit public API for IDE support and documentation.
# All exported symbols should be listed here.
__all__ = [
    # Protocol
    "AIBackend",
    # Error types
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
]
```

---

## Dependencies

### Upstream Dependencies (Must Be Complete First)

| Ticket | Component | Status | Description |
|--------|-----------|--------|-------------|
| [AMI-44](https://linear.app/amiadspec/issue/AMI-44) | Phase 0: Baseline Tests | ✅ Done | Baseline tests capture current behavior |
| [AMI-47](https://linear.app/amiadspec/issue/AMI-47) | Phase 1.1: Backend Error Types | ⏳ Backlog | Error types must exist before protocol references them |

### Downstream Dependents (Blocked by This Ticket)

| Ticket | Component | Description |
|--------|-----------|-------------|
| **Phase 1.3** | BaseBackend Abstract Class | Implements shared logic, uses AIBackend protocol |
| **Phase 1.4** | AuggieBackend | First concrete implementation of AIBackend |
| **Phase 1.6** | BackendFactory | Creates backends; uses AIBackend as return type |
| **Phase 2** | Workflow Step Integration | Steps accept `AIBackend` instead of `AuggieClient` |

### Related Tickets

| Ticket | Title | Relationship |
|--------|-------|--------------|
| [AMI-45](https://linear.app/amiadspec/issue/AMI-45) | Phase 1: Backend Infrastructure | Parent ticket |
| [AMI-46](https://linear.app/amiadspec/issue/AMI-46) | Phase 1.0: Rename Claude Platform Enum | Sibling - parallel work |
| [Pluggable Multi-Agent Support](./Pluggable%20Multi-Agent%20Support.md) | Specification | Parent specification |

---

## Testing Strategy

### Unit Tests for AIBackend Protocol

Create test file: `tests/test_backend_protocol.py`

```python
"""Tests for spec.integrations.backends.base module."""

import pytest
from typing import Protocol

from spec.integrations.backends.base import AIBackend
from spec.config.fetch_config import AgentPlatform


class TestAIBackendProtocol:
    """Tests for AIBackend protocol definition."""

    def test_aibackend_is_protocol(self):
        """AIBackend is a Protocol class."""
        assert issubclass(AIBackend, Protocol)

    def test_aibackend_is_runtime_checkable(self):
        """AIBackend can be used with isinstance checks."""
        # The @runtime_checkable decorator enables isinstance
        assert hasattr(AIBackend, "__protocol_attrs__") or hasattr(
            AIBackend, "_is_runtime_protocol"
        )

    def test_protocol_has_name_property(self):
        """Protocol defines name property."""
        # Check that 'name' is in the protocol's annotations
        assert "name" in dir(AIBackend)

    def test_protocol_has_platform_property(self):
        """Protocol defines platform property."""
        assert "platform" in dir(AIBackend)

    def test_protocol_has_supports_parallel_property(self):
        """Protocol defines supports_parallel property."""
        assert "supports_parallel" in dir(AIBackend)

    def test_protocol_has_run_with_callback_method(self):
        """Protocol defines run_with_callback method."""
        assert hasattr(AIBackend, "run_with_callback")
        assert callable(getattr(AIBackend, "run_with_callback", None))

    def test_protocol_has_run_print_with_output_method(self):
        """Protocol defines run_print_with_output method."""
        assert hasattr(AIBackend, "run_print_with_output")

    def test_protocol_has_run_print_quiet_method(self):
        """Protocol defines run_print_quiet method."""
        assert hasattr(AIBackend, "run_print_quiet")

    def test_protocol_has_run_streaming_method(self):
        """Protocol defines run_streaming method."""
        assert hasattr(AIBackend, "run_streaming")

    def test_protocol_has_check_installed_method(self):
        """Protocol defines check_installed method."""
        assert hasattr(AIBackend, "check_installed")

    def test_protocol_has_detect_rate_limit_method(self):
        """Protocol defines detect_rate_limit method."""
        assert hasattr(AIBackend, "detect_rate_limit")

    def test_protocol_has_supports_parallel_execution_method(self):
        """Protocol defines supports_parallel_execution method."""
        assert hasattr(AIBackend, "supports_parallel_execution")

    def test_protocol_has_close_method(self):
        """Protocol defines close method."""
        assert hasattr(AIBackend, "close")

    def test_protocol_does_not_have_run_print(self):
        """Protocol does NOT define run_print (interactive mode).

        Per Final Decision #4, AIBackend does not include run_print().
        SPEC owns interactive UX; backends operate in non-interactive mode.
        """
        # Verify run_print is not defined as a method in the protocol.
        # Check __protocol_attrs__ which contains the protocol's defined members.
        protocol_attrs = getattr(AIBackend, "__protocol_attrs__", set())
        assert "run_print" not in protocol_attrs, (
            "run_print should NOT be in AIBackend protocol - "
            "see Final Decision #4 (Non-Interactive Execution)"
        )


class TestAIBackendCompliance:
    """Tests verifying protocol compliance detection."""

    def test_fake_backend_satisfies_protocol(self):
        """A properly implemented fake backend satisfies AIBackend."""
        from typing import Callable

        class FakeBackend:
            @property
            def name(self) -> str:
                return "Fake"

            @property
            def platform(self) -> AgentPlatform:
                return AgentPlatform.AUGGIE

            @property
            def supports_parallel(self) -> bool:
                return True

            def run_with_callback(
                self,
                prompt: str,
                *,
                output_callback: Callable[[str], None],
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
            ) -> tuple[bool, str]:
                return True, "output"

            def run_print_with_output(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
            ) -> tuple[bool, str]:
                return True, "output"

            def run_print_quiet(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
            ) -> str:
                return "output"

            def run_streaming(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                timeout_seconds: float | None = None,
            ) -> tuple[bool, str]:
                return True, "output"

            def check_installed(self) -> tuple[bool, str]:
                return True, "Fake v1.0"

            def detect_rate_limit(self, output: str) -> bool:
                return False

            def supports_parallel_execution(self) -> bool:
                return self.supports_parallel

            def close(self) -> None:
                pass

        fake = FakeBackend()
        assert isinstance(fake, AIBackend)

    def test_incomplete_backend_does_not_satisfy_protocol(self):
        """An incomplete implementation does not satisfy AIBackend."""

        class IncompleteBackend:
            @property
            def name(self) -> str:
                return "Incomplete"

            # Missing other required methods/properties

        incomplete = IncompleteBackend()
        # isinstance check should fail for incomplete implementation
        assert not isinstance(incomplete, AIBackend)


class TestAIBackendImports:
    """Tests for module imports."""

    def test_aibackend_importable_from_package(self):
        """AIBackend can be imported from backends package."""
        from spec.integrations.backends import AIBackend

        assert AIBackend is not None

    def test_all_exports_available(self):
        """All expected exports are available from backends package."""
        from spec.integrations.backends import (
            AIBackend,
            BackendNotConfiguredError,
            BackendNotInstalledError,
            BackendRateLimitError,
            BackendTimeoutError,
        )

        # Verify they're the correct classes
        assert AIBackend.__name__ == "AIBackend"
        assert BackendRateLimitError.__name__ == "BackendRateLimitError"
```

### Running Tests

```bash
# Run protocol tests
pytest tests/test_backend_protocol.py -v

# Run with coverage
pytest tests/test_backend_protocol.py --cov=spec.integrations.backends.base -v

# Run type checking
mypy spec/integrations/backends/base.py

# Verify no regressions
pytest tests/ -v
```

---

## Acceptance Criteria

### From Linear Ticket AMI-48

| AC | Description | Verification Method | Status |
|----|-------------|---------------------|--------|
| **AC1** | `AIBackend` Protocol defined in `spec/integrations/backends/base.py` | File exists | [ ] |
| **AC2** | All method signatures match spec exactly | Code review + type checking | [ ] |
| **AC3** | Protocol uses `typing.Protocol` for static type checking | Code inspection | [ ] |
| **AC4** | Protocol methods have complete docstrings | Code inspection | [ ] |
| **AC5** | `@runtime_checkable` decorator applied | `isinstance()` check works | [ ] |
| **AC6** | Unit tests verifying protocol compliance detection | Tests pass | [ ] |

### Additional Quality Criteria

| QC | Description | Validation Method |
|----|-------------|-------------------|
| **QC1** | Module docstring explains purpose | Code review |
| **QC2** | All properties have docstrings | Code inspection |
| **QC3** | `__all__` exports include AIBackend | Import verification |
| **QC4** | Type hints on all method parameters | mypy check |
| **QC5** | No import cycles introduced | Import test |
| **QC6** | Protocol does NOT include `run_print()` | Code inspection |
| **QC7** | FakeBackend test demonstrates compliance | Unit test |

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Import cycle between `base.py` and `errors.py` | Low | Medium | Protocol only imports types, not error classes |
| Signature mismatch with AuggieClient | Low | High | Tests verify return types match baseline tests |
| Runtime checkable not working | Low | Medium | Unit test explicitly tests isinstance() |
| Future methods needed in protocol | Medium | Medium | Protocol can be extended; existing implementations not affected |

---

## Verification Commands

After implementation, run these commands to verify:

```bash
# 1. Verify file created
ls -la spec/integrations/backends/base.py
# Expected: base.py exists

# 2. Verify AIBackend is importable
python -c "
from spec.integrations.backends.base import AIBackend
print('✅ AIBackend importable from base.py')
"

# 3. Verify AIBackend is runtime checkable
python -c "
from spec.integrations.backends import AIBackend
from typing import runtime_checkable, Protocol

# Check it's a Protocol
assert issubclass(type(AIBackend), type(Protocol))
print('✅ AIBackend is a Protocol')
"

# 4. Verify package export
python -c "
from spec.integrations.backends import AIBackend
assert AIBackend.__name__ == 'AIBackend'
print('✅ AIBackend exported from package')
"

# 5. Run unit tests
pytest tests/test_backend_protocol.py -v

# 6. Run type checking
mypy spec/integrations/backends/base.py
```

---

## Definition of Done

- [ ] `spec/integrations/backends/base.py` created with `AIBackend` Protocol
- [ ] Protocol includes all 3 properties (`name`, `platform`, `supports_parallel`)
- [ ] Protocol includes all 8 methods (execution methods + utility methods)
- [ ] `@runtime_checkable` decorator applied
- [ ] All methods and properties have complete docstrings
- [ ] `spec/integrations/backends/__init__.py` exports `AIBackend`
- [ ] Unit tests created in `tests/test_backend_protocol.py`
- [ ] All tests pass
- [ ] mypy reports no type errors
- [ ] Code review approved
- [ ] AMI-48 ticket moved to Done

---

## Estimated Effort

| Phase | Description | Estimate |
|-------|-------------|----------|
| Phase 1 | Create `base.py` with AIBackend Protocol | 0.15 day |
| Phase 2 | Update `__init__.py` exports | 0.05 day |
| Testing | Create unit tests for protocol | 0.1 day |
| Validation | Run verification commands | 0.05 day |
| **Total** | | **~0.35 day** |

---

## References

### Code References

| File | Relevant Code |
|------|--------------|
| `spec/workflow/step4_update_docs.py:517-539` | Current `AuggieClientProtocol` (to be replaced) |
| `spec/integrations/backends/errors.py` | Error types used by protocol methods |
| `spec/config/fetch_config.py:49-64` | `AgentPlatform` enum |
| `spec/integrations/auggie.py` | `AuggieClient` implementation (reference for signatures) |

### Specification References

| Document | Section |
|----------|---------|
| [Pluggable Multi-Agent Support.md](./Pluggable%20Multi-Agent%20Support.md) | Phase 1.2 (lines 1297-1432) |
| [Pluggable Multi-Agent Support.md](./Pluggable%20Multi-Agent%20Support.md) | Final Decision #4 (Non-Interactive Execution) |
| [Pluggable Multi-Agent Support.md](./Pluggable%20Multi-Agent%20Support.md) | Final Decision #15 (run_streaming Semantics) |

### Related Implementation Plans

| Document | Purpose |
|----------|---------|
| [AMI-44-implementation-plan.md](./AMI-44-implementation-plan.md) | Baseline behavior tests (upstream) |
| [AMI-47-implementation-plan.md](./AMI-47-implementation-plan.md) | Backend error types (upstream dependency) |
| [AMI-46-implementation-plan.md](./AMI-46-implementation-plan.md) | Claude platform enum rename (sibling) |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-02-01 | AI Assistant | Initial draft created |
