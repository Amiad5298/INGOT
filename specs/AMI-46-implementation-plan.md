# Implementation Plan: AMI-46 - Phase 1.0: Rename Claude Platform Enum

**Ticket:** [AMI-46](https://linear.app/amiadspec/issue/AMI-46/phase-10-rename-claude-platform-enum)
**Status:** Draft
**Date:** 2026-01-31
**Labels:** MultiAgent

---

## Summary

This ticket renames the `AgentPlatform.CLAUDE_DESKTOP` enum member to `AgentPlatform.CLAUDE` with value `"claude"` (instead of `"claude_desktop"`). This is a required preparatory step before the multi-backend refactoring in Phases 1-3 of the Pluggable Multi-Agent Support specification.

**Why This Matters:**
- The current codebase uses `AgentPlatform.CLAUDE_DESKTOP = "claude_desktop"`
- If we don't rename this early, we'll either:
  - Bake the old naming into the new backend system, or
  - Have to churn many files later when adding `ClaudeBackend`
- "Claude Desktop" is an outdated name; the CLI is now "Claude Code CLI" or simply "Claude"
- The CLI `--backend` choice list should include `claude` (not `claude_desktop`)

**Scope:**
- Rename enum member `CLAUDE_DESKTOP` → `CLAUDE`
- Change enum value from `"claude_desktop"` → `"claude"`
- Update docstrings/comments that reference "Claude Desktop"
- Update all references in tests

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.0 (lines 1214-1240)

---

## Technical Approach

### Naming Decision

Per the Pluggable Multi-Agent Support specification:
- **Claude is canonically named `claude` in CLI/config**
- The enum member is `AgentPlatform.CLAUDE` with value `"claude"`
- Documentation should reference "Claude Code CLI" or simply "Claude" (not "Claude Desktop")

### Files Requiring Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `spec/config/fetch_config.py` | **PRIMARY** | Rename enum member and value, update docstring |
| `tests/test_config_manager.py` | **Test Update** | Update test assertions for new enum name/value |

### Verification Commands

After the rename, these commands should pass:

```bash
# These should return 0 matches (verify old names are gone):
grep -rn "CLAUDE_DESKTOP" --include="*.py" spec/ tests/
grep -rn "claude_desktop" --include="*.py" spec/ tests/

# These should return matches (verify new names exist):
grep -rn "AgentPlatform.CLAUDE" --include="*.py" spec/ tests/
```

---

## Implementation Phases

### Phase 1: Update Primary File (fetch_config.py)

#### Step 1.1: Rename Enum Member and Value

**File:** `spec/config/fetch_config.py`

**Current Code (lines 49-64):**
```python
class AgentPlatform(Enum):
    """Supported AI backends.

    Attributes:
        AUGGIE: Augment Code agent
        CLAUDE_DESKTOP: Claude Desktop application
        CURSOR: Cursor IDE
        AIDER: Aider CLI tool
        MANUAL: Manual/no agent (direct API only)
    """

    AUGGIE = "auggie"
    CLAUDE_DESKTOP = "claude_desktop"
    CURSOR = "cursor"
    AIDER = "aider"
    MANUAL = "manual"
```

**New Code:**
```python
class AgentPlatform(Enum):
    """Supported AI backends.

    Attributes:
        AUGGIE: Augment Code agent
        CLAUDE: Claude Code CLI
        CURSOR: Cursor IDE
        AIDER: Aider CLI tool
        MANUAL: Manual/no agent (direct API only)
    """

    AUGGIE = "auggie"
    CLAUDE = "claude"
    CURSOR = "cursor"
    AIDER = "aider"
    MANUAL = "manual"
```

**Changes:**
1. Rename enum member `CLAUDE_DESKTOP` → `CLAUDE`
2. Change value from `"claude_desktop"` → `"claude"`
3. Update docstring from "Claude Desktop application" → "Claude Code CLI"

---

### Phase 2: Update Test File

#### Step 2.1: Update Test Assertions

**File:** `tests/test_config_manager.py`

**Current Code (lines 1409-1413):**
```python
    def test_ai_backend_values(self):
        """AgentPlatform enum has correct values."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform.AUGGIE.value == "auggie"
        assert AgentPlatform.CLAUDE_DESKTOP.value == "claude_desktop"
        assert AgentPlatform.CURSOR.value == "cursor"
        assert AgentPlatform.AIDER.value == "aider"
        assert AgentPlatform.MANUAL.value == "manual"
```

**New Code:**
```python
    def test_ai_backend_values(self):
        """AgentPlatform enum has correct values."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform.AUGGIE.value == "auggie"
        assert AgentPlatform.CLAUDE.value == "claude"
        assert AgentPlatform.CURSOR.value == "cursor"
        assert AgentPlatform.AIDER.value == "aider"
        assert AgentPlatform.MANUAL.value == "manual"
```

#### Step 2.2: Add Test for Claude String Parsing

**File:** `tests/test_config_manager.py`

The existing `test_ai_backend_from_string` test (lines 1415-1420) tests `auggie` and `cursor` but not `claude`. Add a test case for the renamed value.

**Current Code (lines 1415-1420):**
```python
    def test_ai_backend_from_string(self):
        """AgentPlatform can be created from string value."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform("auggie") == AgentPlatform.AUGGIE
        assert AgentPlatform("cursor") == AgentPlatform.CURSOR
```

**New Code:**
```python
    def test_ai_backend_from_string(self):
        """AgentPlatform can be created from string value."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform("auggie") == AgentPlatform.AUGGIE
        assert AgentPlatform("claude") == AgentPlatform.CLAUDE
        assert AgentPlatform("cursor") == AgentPlatform.CURSOR
```

---

## Acceptance Criteria

### From Linear Ticket AMI-46

| AC | Description | Verification Method | Status |
|----|-------------|---------------------|--------|
| **AC1** | `AgentPlatform.CLAUDE` exists with value `'claude'` | `python -c "from spec.config.fetch_config import AgentPlatform; assert AgentPlatform.CLAUDE.value == 'claude'"` | [ ] |
| **AC2** | No references to `CLAUDE_DESKTOP` remain in codebase | `grep -rn 'CLAUDE_DESKTOP' --include='*.py' spec/ tests/` returns 0 | [ ] |
| **AC3** | No references to `claude_desktop` string remain in codebase | `grep -rn 'claude_desktop' --include='*.py' spec/ tests/` returns 0 | [ ] |
| **AC4** | All existing tests pass | `pytest tests/ -v` | [ ] |
| **AC5** | CLI `--backend` choice list includes `claude` | Valid backend values include `claude` | [ ] |

---

## Dependencies

### Upstream Dependencies (Must Be Complete First)

| Ticket | Component | Status | Description |
|--------|-----------|--------|-------------|
| [AMI-44](https://linear.app/amiadspec/issue/AMI-44) | Phase 0: Baseline Tests | ✅ Done | Baseline tests completed (2026-01-31) |

### Downstream Dependents (Blocked by This Ticket)

| Ticket | Component | Description |
|--------|-----------|-------------|
| **Phase 1.1+** | Backend Infrastructure | Cannot create ClaudeBackend until enum is renamed |
| **Phase 3** | Claude Backend Implementation | Uses `AgentPlatform.CLAUDE` throughout |

### Related Tickets

| Ticket | Title | Relationship |
|--------|-------|--------------|
| [AMI-45](https://linear.app/amiadspec/issue/AMI-45) | Phase 1: Backend Infrastructure | Parent ticket |
| [Pluggable Multi-Agent Support](./Pluggable%20Multi-Agent%20Support.md) | Specification | Parent specification |

---

## Testing Strategy

### Automated Testing

```bash
# Run all tests to ensure no regressions
pytest tests/ -v

# Run config manager tests specifically
pytest tests/test_config_manager.py -v -k "ai_backend"

# Run type checking
mypy spec/config/fetch_config.py
```

### Manual Verification

```bash
# 1. Verify enum exists with correct value
python -c "
from spec.config.fetch_config import AgentPlatform
assert AgentPlatform.CLAUDE.value == 'claude'
print('✅ AgentPlatform.CLAUDE exists with value claude')
"

# 2. Verify old enum member no longer exists
python -c "
from spec.config.fetch_config import AgentPlatform
try:
    _ = AgentPlatform.CLAUDE_DESKTOP
    print('❌ CLAUDE_DESKTOP still exists!')
    exit(1)
except AttributeError:
    print('✅ CLAUDE_DESKTOP correctly removed')
"

# 3. Verify parse_ai_backend accepts 'claude'
python -c "
from spec.config.fetch_config import parse_ai_backend, AgentPlatform
result = parse_ai_backend('claude')
assert result == AgentPlatform.CLAUDE
print('✅ parse_ai_backend correctly parses claude')
"

# 4. Verify no old references remain
echo '=== Checking for CLAUDE_DESKTOP references ==='
grep -rn 'CLAUDE_DESKTOP' --include='*.py' spec/ tests/ && echo '❌ Found references!' || echo '✅ No references found'

echo '=== Checking for claude_desktop references ==='
grep -rn 'claude_desktop' --include='*.py' spec/ tests/ && echo '❌ Found references!' || echo '✅ No references found'
```

---

## Backward Compatibility

### Breaking Changes

This is a **breaking change** for any code that:
1. References `AgentPlatform.CLAUDE_DESKTOP` directly
2. Uses the string `"claude_desktop"` for backend configuration

### Migration Path

Since this is Phase 1.0 of the multi-backend refactoring and the enum is not yet widely used externally:
- **No backward compatibility alias is provided**
- All internal references are updated as part of this ticket
- External users (if any) must update to use `AgentPlatform.CLAUDE` and `"claude"`

### Configuration Impact

| Config Key | Old Value | New Value |
|------------|-----------|-----------|
| `AI_BACKEND` | `claude_desktop` | `claude` |

Users with existing configuration files using `claude_desktop` will need to update to `claude`. This is acceptable because:
1. The multi-backend system is not yet released
2. `AI_BACKEND` is the current config key (the legacy key has been removed)
3. Early renaming prevents future migration pain

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Code using `CLAUDE_DESKTOP` directly | Low | Medium | Comprehensive grep audit confirms only 3 references exist |
| Config files with `claude_desktop` | Low | Low | Multi-backend not yet released; config key change is acceptable |
| Missing a reference | Low | Low | Verification commands catch any missed references |
| Test failures | Low | Medium | Run full test suite before and after changes |

---

## Estimated Effort

| Phase | Description | Estimate |
|-------|-------------|----------|
| Phase 1 | Update `fetch_config.py` (enum + docstring) | 0.05 day |
| Phase 2 | Update test file | 0.05 day |
| Validation | Run tests and verification commands | 0.05 day |
| **Total** | | **~0.15 day** |

---

## Summary of Changes

| File | Change | Lines Changed |
|------|--------|---------------|
| `spec/config/fetch_config.py` | Rename `CLAUDE_DESKTOP` → `CLAUDE`, value `"claude_desktop"` → `"claude"`, update docstring | ~3 lines |
| `tests/test_config_manager.py` | Update `test_ai_backend_values` assertion for new enum name/value | 1 line |
| `tests/test_config_manager.py` | Add `claude` test case to `test_ai_backend_from_string` | 1 line |

---

## Notes

### Mypy Cache

The `.mypy_cache/` directory contains cached type information that references `CLAUDE_DESKTOP`. This cache will automatically regenerate on the next mypy run. No manual action is required, but if verification commands show unexpected results, clear the cache:

```bash
rm -rf .mypy_cache/
mypy spec/config/fetch_config.py
```

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-31 | AI Assistant | Initial draft created |
| 2026-01-31 | AI Assistant | Updated AMI-44 status to Done; added Step 2.2 for claude string parsing test; added mypy cache note |
