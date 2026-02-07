# Implementation Plan: AMI-53 - Phase 1.7: Create Backend Platform Resolver

**Ticket:** [AMI-53](https://linear.app/amiadspec/issue/AMI-53/phase-17-create-backend-platform-resolver)
**Status:** Draft
**Date:** 2026-02-01
**Labels:** MultiAgent
**Parent:** [AMI-45: Pluggable Multi-Agent Support](https://linear.app/amiadspec/issue/AMI-45)

---

## Summary

This ticket creates the `resolve_backend_platform()` function that serves as the single source of truth for backend selection. The resolver enforces explicit precedence rules and the "no default backend" policy, ensuring users explicitly choose their AI provider.

**Why This Matters:**
- Provides a centralized location for backend resolution logic (DRY principle)
- Enforces the "no default backend" policy with clear error messages
- Enables fail-fast behavior at CLI entry points before workflows begin
- Foundation for the onboarding flow (when resolver raises `BackendNotConfiguredError`, prompt user to run `spec init`)

**Scope:**
- Create `spec/config/backend_resolver.py` containing:
  - `resolve_backend_platform()` function with CLI → config precedence
  - Clear error messages directing users to `spec init`
- Does NOT modify CLI or workflow code (that's downstream work in Phase 1.5+/Phase 2)

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.7 (lines 1992-2039)

> **Note:** The Linear ticket AMI-53 shows a different parameter order and names (`cli_backend: str | None, config: ConfigManager`) and states that invalid platforms raise `ValueError`. This implementation plan follows the **parent specification** as the source of truth:
> - Parameter order: `config_manager: ConfigManager, cli_backend_override: str | None = None`
> - Invalid platforms raise `ConfigValidationError` (from `parse_ai_backend()`)
> The Linear ticket should be updated to match.

---

## Context

This is **Phase 1.7** of the Backend Infrastructure work (AMI-45), completing the core infrastructure before Phase 1.8 (Testing Strategy).

### Related Phase Ordering

| Phase | Ticket | Description | Status |
|-------|--------|-------------|--------|
| 0 | AMI-44 | Baseline Behavior Tests | ✅ Done |
| 1.1 | AMI-47 | Backend Error Types | ✅ Done |
| 1.2 | AMI-48 | AIBackend Protocol | ✅ Done |
| 1.3 | AMI-49 | BaseBackend Abstract Class | ✅ Done |
| 1.4 | AMI-50 | Move Subagent Constants | ✅ Done |
| 1.5 | AMI-51 | Create AuggieBackend | ✅ Done |
| 1.6 | AMI-52 | Create Backend Factory | ✅ Done |
| **1.7** | **AMI-53** | **Create Backend Platform Resolver** | **← This Ticket** |
| 1.8 | N/A | Phase 1 Testing Strategy | ⏳ Pending |

> **⚠️ Pre-Implementation Verification Required:** Before starting this ticket, verify that `BackendFactory` and `BackendNotConfiguredError` exist. Run:
> ```bash
> python -c "from spec.integrations.backends.factory import BackendFactory; from spec.integrations.backends.errors import BackendNotConfiguredError; print('Dependencies available')"
> ```

### Position in Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     spec/config/backend_resolver.py                          │
│                     ← THIS TICKET (AMI-53)                                   │
│                                                                              │
│   resolve_backend_platform(                                                  │
│       config_manager: ConfigManager,                                         │
│       cli_backend_override: str | None = None,                              │
│   ) -> AgentPlatform                                                         │
│                                                                              │
│   Precedence:                                                                │
│   1. CLI --backend flag (highest priority)                                   │
│   2. Persisted config AI_BACKEND                                            │
│   3. Raise BackendNotConfiguredError (no implicit default)                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ used by
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   CLI Entry Points (Phase 1.5+)                                             │
│   spec/cli.py                                                                │
│                                                                              │
│   @app.command()                                                             │
│   def run(ticket_id: str, backend: str | None = None):                      │
│       try:                                                                   │
│           platform = resolve_backend_platform(config, cli_backend_override=backend)
│           ai_backend = BackendFactory.create(platform, verify_installed=True)│
│       except BackendNotConfiguredError:                                      │
│           print_error("No AI backend configured.")                          │
│           print_info("Run 'spec init' to configure a backend.")             │
│           return                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ creates
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   BackendFactory.create() (AMI-52)                                          │
│   → AuggieBackend | ClaudeBackend | CursorBackend                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Design Rationale: Resolver vs Factory

| Aspect | `resolve_backend_platform()` | `BackendFactory.create()` |
|--------|------------------------------|---------------------------|
| Purpose | Determine **which** platform to use | Create **instance** of platform |
| Input | ConfigManager + CLI override | AgentPlatform enum/string |
| Output | `AgentPlatform` enum | `AIBackend` instance |
| Policy | Enforces "no default backend" | Accepts any valid platform |
| Error | `BackendNotConfiguredError` | `BackendNotInstalledError` |

The resolver answers "which backend?" while the factory answers "give me that backend."

---

## Current State Analysis

### Existing Infrastructure (Dependencies)

1. **`spec/integrations/backends/errors.py`** (AMI-47)
   - `BackendNotConfiguredError` - Raised when no backend is configured
   - Constructor: `BackendNotConfiguredError(message: str)`

2. **`spec/config/fetch_config.py`**
   - `AgentPlatform` enum: `AUGGIE`, `CLAUDE`, `CURSOR`, `AIDER`, `MANUAL`
   - `parse_ai_backend()` - Converts string to enum, raises `ConfigValidationError`

3. **`spec/config/manager.py`**
   - `ConfigManager` class - Provides `get(key, default)` method for reading config values
   - Currently reads `AI_BACKEND` key (to be migrated to `AI_BACKEND` in future)

### Current Backend Resolution (To Be Replaced)

The current codebase has scattered backend resolution logic:
- `spec/config/manager.py` line 580: `self._raw_values.get("AI_BACKEND")`
- `spec/cli.py` line 98: `_disambiguate_platform()` for ticket platforms (different concern)

This ticket creates a single source of truth that will eventually replace scattered logic.

---

## Technical Approach

### File Structure

**Create:** `spec/config/backend_resolver.py`

### Function Definition

```python
"""Single source of truth for backend platform resolution."""
from spec.config.fetch_config import AgentPlatform, parse_ai_backend
from spec.config.manager import ConfigManager
from spec.integrations.backends.errors import BackendNotConfiguredError


def resolve_backend_platform(
    config_manager: ConfigManager,
    cli_backend_override: str | None = None,
) -> AgentPlatform:
    """Resolve the backend platform with explicit precedence.

    Precedence (highest to lowest):
    1. CLI --backend override (one-run override)
    2. Persisted config AI_BACKEND (stored by ConfigManager/onboarding)

    If neither is set, raises BackendNotConfiguredError.

    Args:
        config_manager: Configuration manager for reading persisted config
        cli_backend_override: CLI --backend flag value (if provided)

    Returns:
        Resolved AgentPlatform enum value

    Raises:
        BackendNotConfiguredError: If no backend is configured via CLI or config
        ConfigValidationError: If an invalid platform string is provided
    """
    # 1. CLI override takes precedence (one-run override)
    # Note: Check both truthiness and non-whitespace to handle "" and "   " cases
    if cli_backend_override and cli_backend_override.strip():
        return parse_ai_backend(cli_backend_override.strip())

    # 2. Check AI_BACKEND in persisted config
    # Note: Legacy AI_BACKEND migration is handled separately (see Final Decision #2).
    # This resolver only reads AI_BACKEND. Migration from AI_BACKEND to AI_BACKEND
    # is out of scope for this ticket.
    ai_backend = config_manager.get("AI_BACKEND", "")
    if ai_backend.strip():
        return parse_ai_backend(ai_backend)

    # 3. No backend configured - raise error with helpful message
    raise BackendNotConfiguredError(
        "No AI backend configured. Please run 'spec init' to configure a backend, "
        "or use the --backend flag to specify one."
    )
```

### Key Design Decisions

1. **CLI override first**: The `--backend` flag allows one-time overrides without modifying persisted config. This is useful for testing different backends.

2. **Persisted config second**: The `AI_BACKEND` key in config (set by `spec init` or manual edit) is the default for normal usage.

3. **No implicit default**: Unlike `parse_ai_backend()` which accepts a `default` parameter, the resolver explicitly raises `BackendNotConfiguredError` when no backend is configured. This enforces the "no default backend" policy from Final Decision #2.

4. **Delegation to parse_ai_backend()**: Uses the existing parser for string-to-enum conversion. This ensures consistent validation and error messages.

5. **Helpful error messages**: The `BackendNotConfiguredError` message guides users to either run `spec init` or use `--backend` flag.

6. **Whitespace handling**: CLI override is stripped of whitespace before parsing. Empty string `""` and whitespace-only `"   "` are treated as "no override" (falsy check + strip).

7. **Legacy migration out of scope**: This resolver only reads `AI_BACKEND`. Migration from legacy `AI_BACKEND` to `AI_BACKEND` is a separate concern (see Final Decision #2 in parent spec).

---

## Implementation Phases

### Phase 1: Create File and Function (~0.25 hours)

1. Create `spec/config/backend_resolver.py`
2. Add module docstring and imports
3. Implement `resolve_backend_platform()` function
4. Add `__all__` export list

### Phase 2: Write Unit Tests (~0.5 hours)

1. Create test file `tests/test_backend_resolver.py`
2. Implement tests for all precedence scenarios
3. Implement tests for error cases
4. Run tests and fix any issues

**Total Estimated Time: ~0.75 hours (~0.3 days)**

---

## Testing Strategy

### Unit Tests

**File:** `tests/test_backend_resolver.py`

> **Note:** This follows the existing flat test file pattern in the repo (e.g., `tests/test_backend_errors.py`, `tests/test_backend_factory.py`).

```python
"""Tests for spec.config.backend_resolver module."""

import pytest
from unittest.mock import MagicMock

from spec.config.fetch_config import AgentPlatform, ConfigValidationError
from spec.config.backend_resolver import resolve_backend_platform
from spec.integrations.backends.errors import BackendNotConfiguredError


class TestResolveBackendPlatformPrecedence:
    """Tests for precedence order in resolve_backend_platform()."""

    def test_cli_override_takes_precedence_over_config(self):
        """CLI --backend flag overrides persisted config."""
        config = MagicMock()
        config.get.return_value = "auggie"  # Config says auggie

        # CLI says claude - should win
        result = resolve_backend_platform(config, cli_backend_override="claude")

        assert result == AgentPlatform.CLAUDE  # CLI wins

    def test_cli_override_with_empty_config(self):
        """CLI override works when config has no AI_BACKEND."""
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="auggie")

        assert result == AgentPlatform.AUGGIE

    def test_config_used_when_no_cli_override(self):
        """Persisted config is used when CLI override is None."""
        config = MagicMock()
        config.get.return_value = "cursor"

        result = resolve_backend_platform(config, cli_backend_override=None)

        assert result == AgentPlatform.CURSOR

    def test_empty_string_cli_override_uses_config(self):
        """Empty string CLI override falls through to config (falsy check)."""
        config = MagicMock()
        config.get.return_value = "cursor"

        # Empty string is falsy, so config should be used
        result = resolve_backend_platform(config, cli_backend_override="")

        assert result == AgentPlatform.CURSOR

    def test_whitespace_only_cli_override_uses_config(self):
        """Whitespace-only CLI override falls through to config."""
        config = MagicMock()
        config.get.return_value = "auggie"

        # Whitespace-only is stripped and treated as empty
        result = resolve_backend_platform(config, cli_backend_override="   ")

        assert result == AgentPlatform.AUGGIE


class TestResolveBackendPlatformNoBackend:
    """Tests for 'no backend configured' error."""

    def test_raises_when_no_cli_and_empty_config(self):
        """Raises BackendNotConfiguredError when both CLI and config are empty."""
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            resolve_backend_platform(config, cli_backend_override=None)

        assert "No AI backend configured" in str(exc_info.value)
        assert "spec init" in str(exc_info.value)

    def test_raises_when_config_is_whitespace_only(self):
        """Whitespace-only config is treated as empty."""
        config = MagicMock()
        config.get.return_value = "   "

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(config, cli_backend_override=None)

    def test_whitespace_cli_and_empty_config_raises_error(self):
        """Whitespace-only CLI + empty config raises BackendNotConfiguredError.

        This ensures whitespace CLI doesn't silently fall through to
        parse_ai_backend()'s default (AUGGIE).
        """
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(config, cli_backend_override="   ")


class TestResolveBackendPlatformInvalidInput:
    """Tests for invalid platform string handling.

    Note: The Linear ticket states that invalid platforms raise ValueError,
    but the actual behavior is ConfigValidationError because parse_ai_backend()
    raises ConfigValidationError for invalid values. This test reflects the
    actual implementation behavior per the parent specification.
    """

    def test_invalid_cli_override_raises_config_validation_error(self):
        """Invalid CLI platform string raises ConfigValidationError."""
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(ConfigValidationError) as exc_info:
            resolve_backend_platform(config, cli_backend_override="chatgpt")

        # Check error message indicates invalid platform (avoid asserting full list
        # of allowed values to prevent test brittleness when enum changes)
        assert "Invalid AI backend" in str(exc_info.value)
        assert "chatgpt" in str(exc_info.value)

    def test_invalid_config_value_raises_config_validation_error(self):
        """Invalid config platform string raises ConfigValidationError."""
        config = MagicMock()
        config.get.return_value = "openai"  # Not a valid platform

        with pytest.raises(ConfigValidationError):
            resolve_backend_platform(config, cli_backend_override=None)


class TestResolveBackendPlatformStringNormalization:
    """Tests for string input normalization."""

    def test_cli_override_is_case_insensitive(self):
        """CLI override handles mixed case."""
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="AUGGIE")

        assert result == AgentPlatform.AUGGIE

    def test_config_value_is_case_insensitive(self):
        """Config value handles mixed case."""
        config = MagicMock()
        config.get.return_value = "AuGgIe"

        result = resolve_backend_platform(config, cli_backend_override=None)

        assert result == AgentPlatform.AUGGIE

    def test_cli_override_strips_whitespace(self):
        """CLI override strips leading/trailing whitespace."""
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="  auggie  ")

        assert result == AgentPlatform.AUGGIE
```

---

## Edge Cases & Error Handling

### Edge Case 1: No Backend Configured

**Scenario:** User runs `spec run TICKET-123` without ever running `spec init` or setting `AI_BACKEND`.

**Handling:** Raise `BackendNotConfiguredError` with actionable message directing to `spec init` or `--backend` flag.

**Example:**
```python
>>> resolve_backend_platform(config, cli_backend_override=None)
BackendNotConfiguredError: No AI backend configured. Please run 'spec init' to configure a backend, or use the --backend flag to specify one.
```

### Edge Case 2: Invalid Platform String

**Scenario:** User provides invalid platform string via `--backend=openai` or config.

**Handling:** `parse_ai_backend()` raises `ConfigValidationError` with list of valid options.

**Example:**
```python
>>> resolve_backend_platform(config, cli_backend_override="openai")
ConfigValidationError: Invalid AI backend 'openai'. Allowed values: auggie, claude, cursor, aider, manual
```

### Edge Case 3: Whitespace-Only Values

**Scenario:** Config has `AI_BACKEND = "   "` (whitespace only).

**Handling:** Treated as empty - raises `BackendNotConfiguredError` (via `.strip()` check).

### Edge Case 4: CLI Override Bypasses Config

**Scenario:** User has `AI_BACKEND=auggie` in config but runs `spec run --backend=cursor TICKET-123`.

**Handling:** CLI wins. Returns `AgentPlatform.CURSOR`. Config is not modified.

---

## Dependencies

### Upstream Dependencies (Required Before Starting)

| Ticket | Description | Status |
|--------|-------------|--------|
| AMI-47 | Backend Error Types (`BackendNotConfiguredError`) | ✅ Done |
| AMI-52 | Create Backend Factory | ✅ Done |

> **Note:** While the resolver doesn't directly use `BackendFactory`, they work together: resolver determines *which* platform, factory creates the *instance*.

### Downstream Dependencies (Blocked By This)

| Ticket | Description | How Resolver is Used |
|--------|-------------|---------------------|
| Phase 1.5+ | Fetcher Refactoring | CLI entry calls `resolve_backend_platform()` before creating backend |
| Phase 2 | Workflow Refactoring | Workflow state holds resolved `AgentPlatform` |
| Phase 5 | Onboarding Flow | Catches `BackendNotConfiguredError` to trigger onboarding |

---

## Verification Commands

```bash
# Verify file exists
ls -la spec/config/backend_resolver.py

# Verify imports work without cycles
python -c "from spec.config.backend_resolver import resolve_backend_platform; print('Import OK')"

# Verify resolver with CLI override
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import AgentPlatform

config = MagicMock()
config.get.return_value = ''
result = resolve_backend_platform(config, cli_backend_override='auggie')
assert result == AgentPlatform.AUGGIE
print('CLI override: OK')
"

# Verify resolver with config value
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import AgentPlatform

config = MagicMock()
config.get.return_value = 'cursor'
result = resolve_backend_platform(config, cli_backend_override=None)
assert result == AgentPlatform.CURSOR
print('Config value: OK')
"

# Verify 'no backend' raises BackendNotConfiguredError
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.integrations.backends.errors import BackendNotConfiguredError

config = MagicMock()
config.get.return_value = ''
try:
    resolve_backend_platform(config, cli_backend_override=None)
except BackendNotConfiguredError as e:
    assert 'spec init' in str(e)
    print('No backend error: OK')
"

# Verify CLI precedence over config
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import AgentPlatform

config = MagicMock()
config.get.return_value = 'auggie'  # Config says auggie
result = resolve_backend_platform(config, cli_backend_override='cursor')  # CLI says cursor
assert result == AgentPlatform.CURSOR  # CLI wins
print('CLI precedence: OK')
"

# Verify invalid platform raises ConfigValidationError
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import ConfigValidationError

config = MagicMock()
config.get.return_value = ''
try:
    resolve_backend_platform(config, cli_backend_override='chatgpt')
except ConfigValidationError as e:
    assert 'Invalid AI backend' in str(e)
    print('Invalid platform error: OK')
"

# Verify empty string CLI override falls through to config
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import AgentPlatform

config = MagicMock()
config.get.return_value = 'cursor'
result = resolve_backend_platform(config, cli_backend_override='')  # Empty string
assert result == AgentPlatform.CURSOR  # Config wins
print('Empty string CLI override: OK')
"

# Verify whitespace-only CLI override falls through to config
python -c "
from unittest.mock import MagicMock
from spec.config.backend_resolver import resolve_backend_platform
from spec.config.fetch_config import AgentPlatform

config = MagicMock()
config.get.return_value = 'auggie'
result = resolve_backend_platform(config, cli_backend_override='   ')  # Whitespace only
assert result == AgentPlatform.AUGGIE  # Config wins
print('Whitespace-only CLI override: OK')
"

# Run unit tests
pytest tests/test_backend_resolver.py -v

# Run mypy type checking (uses project's pyproject.toml config)
mypy spec/config/backend_resolver.py

# Verify no import cycles
python -c "
from spec.config.backend_resolver import resolve_backend_platform
from spec.integrations.backends.factory import BackendFactory
from spec.config.manager import ConfigManager
print('No import cycles detected')
"
```

---

## Definition of Done

### Implementation Checklist

- [ ] `spec/config/backend_resolver.py` created
- [ ] `resolve_backend_platform()` function implemented
- [ ] Function accepts `ConfigManager` and optional `cli_backend_override`
- [ ] Returns `AgentPlatform` enum for valid inputs
- [ ] CLI override takes precedence over config
- [ ] Raises `BackendNotConfiguredError` when no backend configured
- [ ] Raises `ConfigValidationError` for invalid platform strings
- [ ] Module has `__all__` export list

### Quality Checklist

- [ ] Function has complete docstring with Args, Returns, Raises
- [ ] `mypy` reports no type errors (uses project's pyproject.toml config)
- [ ] No import cycles introduced
- [ ] Unit tests pass (`pytest tests/test_backend_resolver.py`)
- [ ] No regressions in existing tests (`pytest tests/`)

### Acceptance Criteria

| AC | Description | Verification Method | Status |
|----|-------------|---------------------|--------|
| **AC1** | CLI flag takes precedence over config | Unit test | [ ] |
| **AC2** | Config value used when no CLI flag | Unit test | [ ] |
| **AC3** | Raises `BackendNotConfiguredError` when no backend configured | Unit test | [ ] |
| **AC4** | Raises `ConfigValidationError` for invalid platform strings | Unit test | [ ] |
| **AC5** | String inputs are case-insensitive | Unit test | [ ] |
| **AC6** | Whitespace is stripped from inputs | Unit test | [ ] |
| **AC7** | Error message mentions `spec init` | Unit test | [ ] |
| **AC8** | Empty string CLI override falls through to config | Unit test | [ ] |
| **AC9** | Whitespace-only CLI override falls through to config | Unit test | [ ] |
| **AC10** | Whitespace-only CLI + empty config raises `BackendNotConfiguredError` | Unit test | [ ] |

> **Note on AC4:** The Linear ticket states `ValueError` for invalid platforms, but the actual behavior is `ConfigValidationError` because `parse_ai_backend()` raises `ConfigValidationError`. This follows the parent specification.

---

## References

### Specification References

| Document | Section | Description |
|----------|---------|-------------|
| `specs/Pluggable Multi-Agent Support.md` | Lines 1992-2039 | Phase 1.7: Backend Platform Resolver specification |
| `specs/Pluggable Multi-Agent Support.md` | Lines 2041-2055 | Phase 1.8: Testing Strategy (includes resolver tests) |
| `specs/Pluggable Multi-Agent Support.md` | Lines 139-147 | Final Decisions: Configuration Precedence |

### Codebase References

| File | Description |
|------|-------------|
| `spec/integrations/backends/errors.py` | BackendNotConfiguredError definition |
| `spec/config/fetch_config.py` | AgentPlatform enum, parse_ai_backend() |
| `spec/config/manager.py` | ConfigManager class |
| `spec/integrations/backends/factory.py` | BackendFactory (companion to resolver) |

### Related Implementation Plans

| Document | Description |
|----------|-------------|
| `specs/AMI-47-implementation-plan.md` | Backend Error Types (includes BackendNotConfiguredError) |
| `specs/AMI-52-implementation-plan.md` | Backend Factory (companion component) |
| `specs/AMI-51-implementation-plan.md` | AuggieBackend (first backend implementation) |

---

## Future CLI Integration

> **Note:** This section documents how the resolver will be used in Phase 1.5+ when CLI is updated. This is informational only - CLI changes are **out of scope** for this ticket.

```python
# Future: spec/cli.py integration example

@app.command()
def run(
    ticket_id: str,
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="AI backend to use"),
):
    """Run SPEC workflow for a ticket."""
    from spec.config.backend_resolver import resolve_backend_platform
    from spec.integrations.backends.errors import BackendNotConfiguredError
    from spec.integrations.backends.factory import BackendFactory

    try:
        platform = resolve_backend_platform(config, cli_backend_override=backend)
        ai_backend = BackendFactory.create(platform, verify_installed=True)
    except BackendNotConfiguredError as e:
        print_error(str(e))
        print_info("Available backends: auggie, claude, cursor")
        print_info("Run 'spec init' to configure a backend interactively.")
        raise typer.Exit(1)

    # Continue with workflow using ai_backend...
```

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-02-01 | AI Assistant | Initial draft created following AMI-52 template |
| 2026-02-01 | AI Assistant | **Review fixes:** (1) Added discrepancy note about Linear ticket parameter order and ValueError vs ConfigValidationError; (2) Added `.strip()` to CLI override handling for whitespace safety; (3) Added test cases for empty string and whitespace-only CLI override; (4) Clarified legacy AI_BACKEND migration is out of scope; (5) Added ConfigValidationError note to test class docstring; (6) Added AC8 and AC9 for empty/whitespace CLI override tests; (7) Added Key Design Decisions #6 and #7 for whitespace handling and legacy migration scope |
| 2026-02-01 | AI Assistant | **Peer review fixes:** (1) Fixed `AgentPlatform.CLAUDE_DESKTOP` → `AgentPlatform.CLAUDE` to match actual codebase (enum is `CLAUDE`, not `CLAUDE_DESKTOP`); (2) Added missing test `test_whitespace_cli_and_empty_config_raises_error()` for whitespace CLI + empty config edge case; (3) Made error message assertions less brittle by avoiding full allowed-values list checks; (4) Added AC10 for whitespace CLI + empty config test |
