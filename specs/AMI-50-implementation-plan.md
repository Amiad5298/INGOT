# Implementation Plan: AMI-50 - Phase 1.4: Move Subagent Constants

**Ticket:** [AMI-50](https://linear.app/amiadspec/issue/AMI-50/phase-14-move-subagent-constants)
**Status:** Draft
**Date:** 2026-02-01
**Labels:** MultiAgent

---

## Summary

This ticket moves subagent name constants from the Auggie-specific code (`spec/integrations/auggie.py`) to a neutral, backend-agnostic location (`spec/workflow/constants.py`). This decoupling is essential for the Pluggable Multi-Agent Support initiative, enabling other backends (Claude Code, Cursor, Aider) to access subagent constants without depending on Auggie-specific code.

**Why This Matters:**
- Subagent names are workflow concepts, not Auggie-specific concepts
- Other backends (Claude, Cursor, Aider) need access to these constants
- Eliminates circular dependency risk when backends need subagent names
- Clean separation of concerns between workflow and integration layers

**Scope:**
- Move 6 existing subagent constants from `spec/integrations/auggie.py` to new `spec/workflow/constants.py`
- Create 3 new timeout constants in `spec/workflow/constants.py` (these don't exist yet in the codebase)
- Update all import statements across the codebase
- Remove constants from `spec/integrations/auggie.py` entirely
- Expand `spec/integrations/__init__.py` exports from 4 to 6 subagent constants
- Update tests to import from new location
- Update Linear ticket AMI-50 to match parent specification

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.4 (lines 1718-1770)

> **Note:** The Linear ticket AMI-50 contains outdated constant names and file references that don't match the parent specification or current codebase. This implementation plan follows the **parent specification** as the source of truth. The Linear ticket should be updated to match.

> **Important:** The timeout constants (`DEFAULT_EXECUTION_TIMEOUT`, `FIRST_RUN_TIMEOUT`, `ONBOARDING_SMOKE_TEST_TIMEOUT`) are being **created as new constants**, not moved from an existing location. They are specified in the parent spec but do not currently exist in the codebase.

---

## Context

This is **Phase 1.4** of the Backend Infrastructure work (AMI-45), part of the Pluggable Multi-Agent Support initiative.

### Position in Architecture

```
Before (current state):
┌────────────────────────────────────┐
│  spec/integrations/auggie.py       │
│  ├── SPECFLOW_AGENT_PLANNER        │◄─┬─ spec/config/settings.py
│  ├── SPECFLOW_AGENT_TASKLIST       │  ├─ spec/workflow/state.py
│  ├── SPECFLOW_AGENT_TASKLIST_REFINER│  ├─ spec/integrations/agents.py
│  ├── SPECFLOW_AGENT_IMPLEMENTER    │  ├─ spec/integrations/__init__.py
│  ├── SPECFLOW_AGENT_REVIEWER       │  └─ tests/test_auggie.py
│  └── SPECFLOW_AGENT_DOC_UPDATER    │
│  └── AuggieClient (Auggie-specific)│
└────────────────────────────────────┘

After (target state):
┌────────────────────────────────────┐
│  spec/workflow/constants.py (NEW)  │
│  ├── SPECFLOW_AGENT_PLANNER        │◄─┬─ spec/config/settings.py
│  ├── SPECFLOW_AGENT_TASKLIST       │  ├─ spec/workflow/state.py
│  ├── SPECFLOW_AGENT_TASKLIST_REFINER│  ├─ spec/integrations/agents.py
│  ├── SPECFLOW_AGENT_IMPLEMENTER    │  ├─ spec/integrations/__init__.py
│  ├── SPECFLOW_AGENT_REVIEWER       │  ├─ tests/test_auggie.py
│  └── SPECFLOW_AGENT_DOC_UPDATER    │  └─ tests/test_baseline_auggie_behavior.py
└────────────────────────────────────┘

┌────────────────────────────────────┐
│  spec/integrations/auggie.py       │
│  └── AuggieClient (Auggie-specific)│
│  └── NO subagent constants         │
└────────────────────────────────────┘
```

### Related Phase Ordering

| Phase | Ticket | Description | Status |
|-------|--------|-------------|--------|
| 0 | AMI-44 | Baseline Behavior Tests | ✅ Done |
| 1.1 | AMI-47 | Backend Error Types | ✅ Done |
| 1.2 | AMI-48 | AIBackend Protocol | ✅ Done |
| 1.3 | AMI-49 | BaseBackend Abstract Class | ✅ Done |
| **1.4** | **AMI-50** | **Move Subagent Constants** | ← **This Ticket** |
| 1.5 | AMI-51 | Backend Config Resolution | 🔜 Ready |

---

## Current State Analysis

### Constants to Move (6 Subagent Constants)

From `spec/integrations/auggie.py` (lines 27-33):

```python
# Subagent names used by SPECFLOW workflow
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"
```

### Constants to Create (3 Timeout Constants - NEW)

These constants are specified in the parent spec but **do not currently exist** in the codebase:

```python
# Default timeout values (seconds)
DEFAULT_EXECUTION_TIMEOUT = 60
FIRST_RUN_TIMEOUT = 120
ONBOARDING_SMOKE_TEST_TIMEOUT = 60
```

### Files Currently Importing Subagent Constants from auggie.py

| File | Constants Imported | Line Numbers |
|------|-------------------|--------------|
| `spec/config/settings.py` | 6 constants (all) | 17-24 |
| `spec/workflow/state.py` | 6 constants (all) | 12-19 |
| `spec/integrations/agents.py` | 5 constants (no DOC_UPDATER) | 17-23 |
| `spec/integrations/__init__.py` | 4 constants (no TASKLIST_REFINER, DOC_UPDATER) | 10-14, 104-107 |
| `tests/test_auggie.py` | 5 constants (no DOC_UPDATER) | 6-22 |
| `tests/test_baseline_auggie_behavior.py` | 6 constants (all, inline imports) | 62-68, 503-509 |

### Files Importing from auggie.py That Do NOT Need Changes

These files import from `spec.integrations.auggie` but only use `AuggieClient`, `AuggieModel`, or other Auggie-specific symbols (not subagent constants):

| File | Imports Used |
|------|--------------|
| `spec/workflow/runner.py` | `AuggieClient` |
| `spec/workflow/step1_plan.py` | `AuggieClient` |
| `spec/workflow/step2_tasklist.py` | `AuggieClient` |
| `spec/workflow/step3_execute.py` | `AuggieClient`, `AuggieRateLimitError` |
| `spec/workflow/step4_update_docs.py` | `AuggieClient` |
| `spec/workflow/review.py` | `AuggieClient` |
| `spec/workflow/autofix.py` | `AuggieClient` |
| `spec/workflow/conflict_detection.py` | `AuggieClient` |
| `spec/cli.py` | `AuggieClient`, `check_auggie_installed`, `install_auggie` |
| `spec/config/manager.py` | `extract_model_id` |
| `spec/ui/menus.py` | `list_models` |
| `spec/integrations/fetchers/auggie_fetcher.py` | `AuggieClient` |
| `spec/integrations/ticket_service.py` | `AuggieClient` |
| `spec/integrations/jira.py` | `AuggieClient` |
| `tests/test_retry.py` | `AuggieRateLimitError` |
| `tests/test_menus.py` | `AuggieModel` |
| `tests/test_auggie_fetcher.py` | `AuggieClient` |
| `tests/test_step3_execute.py` | `AuggieRateLimitError` |

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `spec/workflow/constants.py` | **CREATE** | New home for subagent constants (6) + timeout constants (3) |
| `spec/workflow/__init__.py` | **MODIFY** | Export all 9 constants from new location |
| `spec/integrations/auggie.py` | **MODIFY** | Remove constant definitions and `__all__` entries |
| `spec/config/settings.py` | **MODIFY** | Update import source |
| `spec/workflow/state.py` | **MODIFY** | Update import source |
| `spec/integrations/agents.py` | **MODIFY** | Update import source |
| `spec/integrations/__init__.py` | **MODIFY** | Update import source, export all 6 subagent constants |
| `tests/test_auggie.py` | **MODIFY** | Update import source |
| `tests/test_baseline_auggie_behavior.py` | **MODIFY** | Update import source + fix docstring |

---

## Implementation Phases

### Phase 1: Create New Constants Module

#### Step 1.1: Create spec/workflow/constants.py

**File:** `spec/workflow/constants.py` (NEW)

```python
"""Workflow constants.

This module contains constants used across the workflow that are
not specific to any particular AI backend.

These constants define the canonical names for SPECFLOW subagents
used across all workflow steps, plus default timeout values.
"""

# Subagent names for SPEC workflow
# These are the canonical identifiers used by workflow steps
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"

# Default timeout values (seconds)
DEFAULT_EXECUTION_TIMEOUT = 60
FIRST_RUN_TIMEOUT = 120
ONBOARDING_SMOKE_TEST_TIMEOUT = 60

__all__ = [
    # Subagent constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_DOC_UPDATER",
    # Timeout constants
    "DEFAULT_EXECUTION_TIMEOUT",
    "FIRST_RUN_TIMEOUT",
    "ONBOARDING_SMOKE_TEST_TIMEOUT",
]
```

#### Step 1.2: Update spec/workflow/__init__.py

**File:** `spec/workflow/__init__.py`

Add exports for the new constants module:

```python
# Add to imports section:
from spec.workflow.constants import (
    DEFAULT_EXECUTION_TIMEOUT,
    FIRST_RUN_TIMEOUT,
    ONBOARDING_SMOKE_TEST_TIMEOUT,
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)

# Add to __all__ list:
    # Subagent Constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_DOC_UPDATER",
    # Timeout Constants
    "DEFAULT_EXECUTION_TIMEOUT",
    "FIRST_RUN_TIMEOUT",
    "ONBOARDING_SMOKE_TEST_TIMEOUT",
```

---

### Phase 2: Update Import Statements

#### Step 2.1: Update spec/config/settings.py

**File:** `spec/config/settings.py`

**BEFORE (lines 17-24):**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

**AFTER:**
```python
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

#### Step 2.2: Update spec/workflow/state.py

**File:** `spec/workflow/state.py`

**BEFORE (lines 12-19):**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

**AFTER:**
```python
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

#### Step 2.3: Update spec/integrations/agents.py

**File:** `spec/integrations/agents.py`

**BEFORE (lines 17-23):**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
    version_gte,
)
```

**AFTER:**
```python
from spec.integrations.auggie import version_gte
from spec.workflow.constants import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

#### Step 2.4: Update spec/integrations/__init__.py

**File:** `spec/integrations/__init__.py`

**BEFORE (lines 10-22):**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    AuggieClient,
    AuggieModel,
    check_auggie_installed,
    get_auggie_version,
    install_auggie,
    list_models,
    version_gte,
)
```

**AFTER:**
```python
from spec.integrations.auggie import (
    AuggieClient,
    AuggieModel,
    check_auggie_installed,
    get_auggie_version,
    install_auggie,
    list_models,
    version_gte,
)
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

**Also update `__all__` (lines 103-107):**

**BEFORE:**
```python
    # Subagent constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
```

**AFTER:**
```python
    # Subagent constants (all 6 now exported)
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_DOC_UPDATER",
```

> ⚠️ **Scope Expansion:** This migration adds `SPECFLOW_AGENT_TASKLIST_REFINER` and `SPECFLOW_AGENT_DOC_UPDATER` to the public API of `spec.integrations`. Previously only 4 constants were exported; after this change, all 6 will be exported. Code using `from spec.integrations import *` will now receive 2 additional symbols. This is intentional for API completeness.

---

### Phase 3: Remove Constants from spec/integrations/auggie.py

#### Step 3.1: Remove constant definitions from auggie.py

**File:** `spec/integrations/auggie.py`

**REMOVE (lines 27-33):**
```python
# Subagent names used by SPECFLOW workflow
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"
```

#### Step 3.2: Remove constants from __all__ in auggie.py

**File:** `spec/integrations/auggie.py`

**REMOVE from `__all__` (lines 755-761):**
```python
    # Subagent constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_DOC_UPDATER",
```

---

### Phase 4: Update Test Files

#### Step 4.1: Update tests/test_auggie.py

**File:** `tests/test_auggie.py`

**BEFORE (lines 6-22):**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
    AgentDefinition,
    AuggieClient,
    AuggieRateLimitError,
    _looks_like_rate_limit,
    _parse_model_list,
    check_auggie_installed,
    extract_model_id,
    get_auggie_version,
    get_node_version,
    version_gte,
)
```

**AFTER:**
```python
from spec.integrations.auggie import (
    AgentDefinition,
    AuggieClient,
    AuggieRateLimitError,
    _looks_like_rate_limit,
    _parse_model_list,
    check_auggie_installed,
    extract_model_id,
    get_auggie_version,
    get_node_version,
    version_gte,
)
from spec.workflow.constants import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
```

> **Note:** This file imports only 5 subagent constants (not `SPECFLOW_AGENT_DOC_UPDATER`). This is intentional - the test file only tests the constants it uses. No additional constants should be added.

#### Step 4.2: Update tests/test_baseline_auggie_behavior.py

**File:** `tests/test_baseline_auggie_behavior.py`

Update test methods that import constants inside the test function body:
- `test_specflow_agent_constants_are_importable` (lines 59-82)
- `test_subagent_names_match_constants` (lines 498-517)

**Change 1: Update imports in `test_specflow_agent_constants_are_importable` (line 62):**

**BEFORE:**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    ...
)
```

**AFTER:**
```python
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    ...
)
```

**Change 2: Update imports in `test_subagent_names_match_constants` (line 503):**

**BEFORE:**
```python
from spec.integrations.auggie import (
    SPECFLOW_AGENT_DOC_UPDATER,
    ...
)
```

**AFTER:**
```python
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    ...
)
```

**Change 3: Update docstring in `test_subagent_names_match_constants` (line 499):**

**BEFORE:**
```python
"""Verify subagent names match the constants in auggie.py.
```

**AFTER:**
```python
"""Verify subagent names match the constants in spec.workflow.constants.
```

**Note:** The baseline behavior test file tests that constants are importable. After migration, it should test import from the NEW location (`spec.workflow.constants`), not the old location.

---

## Circular Import Risk Analysis

### Potential Risk

Creating `spec/workflow/constants.py` that is imported by `spec/integrations/auggie.py` could create circular imports if:
- `spec/workflow/constants.py` imports from `spec/integrations/auggie.py` (it doesn't)
- Any transitive imports create a cycle

### Mitigation

The design is inherently safe because:

1. **`spec/workflow/constants.py`** is a leaf module with NO imports from:
   - `spec.integrations.*`
   - `spec.workflow.*`
   - Any project modules

2. **Import direction is one-way:**
   ```
   spec.workflow.constants  (no project imports)
         ↑
   spec.config.settings, spec.workflow.state, spec.integrations.agents, etc.
   ```

3. **Verification:** After implementation, run:
   ```bash
   python -c "from spec.workflow.constants import SPECFLOW_AGENT_PLANNER; print('OK')"
   python -c "from spec.config.settings import Settings; print('OK')"
   ```

---

## Testing Strategy

### 1. Verify New Module Imports

```bash
# Test direct import of subagent constants from new location
python -c "from spec.workflow.constants import SPECFLOW_AGENT_PLANNER, SPECFLOW_AGENT_TASKLIST, SPECFLOW_AGENT_TASKLIST_REFINER, SPECFLOW_AGENT_IMPLEMENTER, SPECFLOW_AGENT_REVIEWER, SPECFLOW_AGENT_DOC_UPDATER; print('Subagent constants import OK')"

# Test direct import of timeout constants from new location
python -c "from spec.workflow.constants import DEFAULT_EXECUTION_TIMEOUT, FIRST_RUN_TIMEOUT, ONBOARDING_SMOKE_TEST_TIMEOUT; print('Timeout constants import OK')"

# Test package-level import from spec.workflow
python -c "from spec.workflow import SPECFLOW_AGENT_PLANNER, DEFAULT_EXECUTION_TIMEOUT; print('Package import OK')"
```

### 2. Verify Constants Removed from auggie.py

```bash
# This should FAIL after migration (constants no longer in auggie.py)
python -c "from spec.integrations.auggie import SPECFLOW_AGENT_PLANNER" 2>&1 | grep -q "ImportError" && echo "Correctly removed from auggie.py"
```

### 3. Verify Constant Values Unchanged

```bash
python -c "
from spec.workflow.constants import (
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_DOC_UPDATER,
    DEFAULT_EXECUTION_TIMEOUT,
    FIRST_RUN_TIMEOUT,
    ONBOARDING_SMOKE_TEST_TIMEOUT,
)
# Verify subagent constant values
assert SPECFLOW_AGENT_PLANNER == 'spec-planner'
assert SPECFLOW_AGENT_TASKLIST == 'spec-tasklist'
assert SPECFLOW_AGENT_TASKLIST_REFINER == 'spec-tasklist-refiner'
assert SPECFLOW_AGENT_IMPLEMENTER == 'spec-implementer'
assert SPECFLOW_AGENT_REVIEWER == 'spec-reviewer'
assert SPECFLOW_AGENT_DOC_UPDATER == 'spec-doc-updater'
# Verify timeout constant values
assert DEFAULT_EXECUTION_TIMEOUT == 60
assert FIRST_RUN_TIMEOUT == 120
assert ONBOARDING_SMOKE_TEST_TIMEOUT == 60
print('All values correct')
"
```

### 4. Run Existing Tests

```bash
# Run tests that exercise the constants
pytest tests/test_auggie.py::TestSubagentConstants -v
pytest tests/test_baseline_auggie_behavior.py -v

# Run all tests to ensure no regressions
pytest tests/ -v --tb=short
```

### 5. Verify No Old Imports Remain

```bash
# After migration, this should return 0 matches (excluding re-export in auggie.py)
grep -rn "from spec.integrations.auggie import" --include="*.py" . | grep "SPECFLOW_AGENT" | grep -v "auggie.py" | grep -v "__pycache__"
# Expected: 0 matches

# Verify settings.py imports from new location
grep -n "from spec.workflow.constants import" spec/config/settings.py
# Expected: 1 match

# Verify state.py imports from new location
grep -n "from spec.workflow.constants import" spec/workflow/state.py
# Expected: 1 match
```

---

## Risk Assessment

### Risk 1: Circular Import

**Risk:** New import structure could create circular dependencies.

**Mitigation:**
- `spec/workflow/constants.py` has NO project imports
- Import direction is strictly one-way
- Verified by import tests

**Severity:** Very Low (design prevents this)

### Risk 2: Missing Import Updates

**Risk:** Some files might be missed during import updates.

**Mitigation:**
- Comprehensive grep search already performed
- Verification commands provided
- Test suite will catch missing updates

**Severity:** Low (automated verification)

---

## Definition of Done

### Code Changes

- [ ] `spec/workflow/constants.py` created with all 6 subagent constants + 3 timeout constants
- [ ] `spec/workflow/__init__.py` exports the new constants (9 total)
- [ ] `spec/config/settings.py` imports from new location
- [ ] `spec/workflow/state.py` imports from new location
- [ ] `spec/integrations/agents.py` imports from new location
- [ ] `spec/integrations/__init__.py` imports from new location (all 6 subagent constants)
- [ ] `spec/integrations/auggie.py` constants and `__all__` entries removed
- [ ] `tests/test_auggie.py` imports from new location
- [ ] `tests/test_baseline_auggie_behavior.py` imports from new location
- [ ] `tests/test_baseline_auggie_behavior.py` docstring updated (line 499)

### Testing

- [ ] Direct imports from `spec.workflow.constants` work (subagent + timeout constants)
- [ ] Package-level imports from `spec.workflow` work
- [ ] Constants no longer importable from `spec.integrations.auggie`
- [ ] Constant values are unchanged
- [ ] Timeout constants have correct values (60, 120, 60)
- [ ] No circular import issues
- [ ] All existing tests pass: `pytest tests/ -v`
- [ ] `TestSubagentConstants` tests pass

### Verification

- [ ] No imports of SPECFLOW_AGENT_* from `auggie.py` remain
- [ ] Grep verification commands return expected results
- [ ] Import chain verification passes
- [ ] Linear ticket AMI-50 updated to match parent spec

---

## Estimated Effort

| Phase | Description | Estimated Time |
|-------|-------------|----------------|
| Phase 1 | Create constants.py and update workflow __init__ | 0.05 days |
| Phase 2 | Update 4 source file imports | 0.1 days |
| Phase 3 | Remove constants from auggie.py | 0.05 days |
| Phase 4 | Update test file imports | 0.05 days |
| Testing | Run verification commands and test suite | 0.05 days |
| Review | Code review and any refinements | 0.05 days |
| **Total** | | **~0.35 days** |

**Comparison to Similar Tickets:**
- AMI-47 (Backend Error Types): ~0.35-0.4 days
- AMI-48 (AIBackend Protocol): ~0.35 days
- AMI-50 (Move Constants): ~0.35 days (straightforward refactoring)

---

## Dependencies

### Upstream Dependencies

None - this ticket can be implemented independently.

### Downstream Dependencies (Blocked by This Ticket)

| Ticket | Status | Description |
|--------|--------|-------------|
| AMI-51 | 🔜 Ready | Backend Config Resolution - May import from `spec.workflow.constants` |

### Related Tickets

| Ticket | Relationship | Description |
|--------|--------------|-------------|
| AMI-45 | Parent | Backend Infrastructure (parent epic) |
| AMI-44 | Phase 0 | Baseline Behavior Tests - tests import these constants |
| AMI-49 | Predecessor | BaseBackend Abstract Class |

---

## References

### Code References

| File | Lines | Description |
|------|-------|-------------|
| `spec/integrations/auggie.py` | 27-33 | Current constant definitions (including comment) |
| `spec/integrations/auggie.py` | 755-761 | Current `__all__` exports (including comment) |
| `spec/config/settings.py` | 17-24, 81-86 | Import and usage |
| `spec/workflow/state.py` | 12-19, 146-151 | Import and usage |
| `spec/integrations/agents.py` | 17-23, 187-217 | Import and usage (5 constants, no DOC_UPDATER) |
| `spec/integrations/__init__.py` | 10-14, 104-107 | Re-export (4 constants currently) |
| `tests/test_auggie.py` | 6-22, 654-671 | Test imports and assertions (5 constants) |
| `tests/test_baseline_auggie_behavior.py` | 62-82, 503-517 | Baseline behavior tests (6 constants) |

### Specification References

| Document | Section | Description |
|----------|---------|-------------|
| `specs/Pluggable Multi-Agent Support.md` | Lines 1718-1770 | Phase 1.4: Move Subagent Constants |
| `specs/Pluggable Multi-Agent Support.md` | Lines 111-136 | Import migration verification |

### Related Implementation Plans

| Document | Description |
|----------|-------------|
| `specs/AMI-44-implementation-plan.md` | Baseline Behavior Tests |
| `specs/AMI-49-implementation-plan.md` | BaseBackend Abstract Class |

---

## Appendix: Complete File Listing

### spec/workflow/constants.py (Complete)

```python
"""Workflow constants.

This module contains constants used across the workflow that are
not specific to any particular AI backend.

These constants define the canonical names for SPECFLOW subagents
used across all workflow steps, plus default timeout values.
"""

# Subagent names for SPEC workflow
# These are the canonical identifiers used by workflow steps
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"

# Default timeout values (seconds)
DEFAULT_EXECUTION_TIMEOUT = 60
FIRST_RUN_TIMEOUT = 120
ONBOARDING_SMOKE_TEST_TIMEOUT = 60

__all__ = [
    # Subagent constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_DOC_UPDATER",
    # Timeout constants
    "DEFAULT_EXECUTION_TIMEOUT",
    "FIRST_RUN_TIMEOUT",
    "ONBOARDING_SMOKE_TEST_TIMEOUT",
]
```

### Summary of All Import Changes

| File | Change Type |
|------|-------------|
| `spec/workflow/constants.py` | CREATE - new file with 6 moved subagent constants + 3 NEW timeout constants |
| `spec/workflow/__init__.py` | ADD - import and export all 9 constants |
| `spec/config/settings.py` | CHANGE - import 6 subagent constants from `spec.workflow.constants` |
| `spec/workflow/state.py` | CHANGE - import 6 subagent constants from `spec.workflow.constants` |
| `spec/integrations/agents.py` | CHANGE - import 5 subagent constants from `spec.workflow.constants` |
| `spec/integrations/__init__.py` | CHANGE - import 6 subagent constants from `spec.workflow.constants` (was 4) |
| `spec/integrations/auggie.py` | REMOVE - delete 6 constant definitions and `__all__` entries |
| `tests/test_auggie.py` | CHANGE - import 5 subagent constants from `spec.workflow.constants` |
| `tests/test_baseline_auggie_behavior.py` | CHANGE - import 6 subagent constants from `spec.workflow.constants` + fix docstring |
