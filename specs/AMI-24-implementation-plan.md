# Implementation Plan: AMI-24 - Migrate WorkflowState from JiraTicket to GenericTicket

**Ticket:** [AMI-24](https://linear.app/amiadspec/issue/AMI-24/migrate-workflowstate-from-jiraticket-to-genericticket)
**Status:** Draft
**Date:** 2026-01-27

---

## Summary

This ticket migrates the `WorkflowState` class and related workflow modules from using the platform-specific `JiraTicket` dataclass to the platform-agnostic `GenericTicket` abstraction. This is a critical architectural migration that enables the workflow engine to work with **any supported issue tracking platform** (Jira, GitHub, Linear, Azure DevOps, Monday, Trello).

**Migration Scope (AMI-24):**
- Core workflow state (`spec/workflow/state.py`)
- Workflow runner (`spec/workflow/runner.py`)
- Workflow steps (`step1_plan.py`, `step2_tasklist.py`, `step3_execute.py`)
- Conflict detection module (`spec/workflow/conflict_detection.py`)
- All related test files (10+ test files)

> **Note:** CLI migration (`spec/cli.py`) is handled separately by [AMI-25](https://linear.app/amiadspec/issue/AMI-25).

**Key Transformation:**
```python
# Before (JiraTicket - platform-specific)
from spec.integrations.jira import JiraTicket
ticket: JiraTicket
ticket.ticket_id      # "PROJECT-123"
ticket.ticket_url     # URL or ID string
ticket.summary        # Branch name hint
ticket.title          # Full title
ticket.description    # Description

# After (GenericTicket - platform-agnostic)
from spec.integrations.providers import GenericTicket
ticket: GenericTicket
ticket.id             # Platform-specific ID (e.g., "PROJECT-123", "owner/repo#42")
ticket.url            # Full URL to ticket
ticket.branch_summary # Short summary for branch name
ticket.title          # Full title
ticket.description    # Description
ticket.safe_branch_name  # Property: generates git-safe branch name
```

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SPECFLOW CLI                                        │
│  spec <ticket_url_or_id>                                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     TicketService (AMI-32) - CURRENT ENTRY POINT                 │
│                                                                                  │
│   async def get_ticket(input_str: str) -> GenericTicket                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                  WorkflowState (THIS TICKET - MIGRATION)                         │
│                                                                                  │
│   @dataclass                                                                    │
│   class WorkflowState:                                                          │
│       ticket: GenericTicket  # ← Changed from JiraTicket                        │
│       ...                                                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  step1_plan.py  │      │step2_tasklist.py│      │step3_execute.py │
│                 │      │                 │      │                 │
│ ticket.id       │      │ ticket.id       │      │ ticket.id       │
│ ticket.title    │      │ ticket.title    │      │ ticket.title    │
│ ticket.desc     │      │                 │      │                 │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

### Key Design Decisions

1. **GenericTicket is Already Production-Ready** - The `GenericTicket` dataclass in `spec/integrations/providers/base.py` is fully implemented with all required fields and properties (`id`, `url`, `title`, `description`, `branch_summary`, `safe_branch_name`).

2. **CLI Integration Path** - The CLI (`spec/cli.py`) currently uses `parse_jira_ticket()` to create `JiraTicket`. This will be replaced with `TicketService.get_ticket()` which returns `GenericTicket`.

3. **fetch_ticket_info Replacement** - The `fetch_ticket_info()` function in `spec/integrations/jira.py` that populates `JiraTicket` fields will be replaced by the `TicketService` orchestration layer.

4. **Backward Compatibility Strategy** - During migration, the legacy `JiraTicket` and `parse_jira_ticket()` functions remain available but are no longer used by the workflow. This allows gradual deprecation.

5. **Synchronous Wrapper for CLI** - Since `TicketService.get_ticket()` is async but the CLI is synchronous, we'll need a synchronous wrapper using `asyncio.run()`.

---

## Field Mapping: JiraTicket → GenericTicket

| JiraTicket Field | GenericTicket Field | Usage in Codebase | Notes |
|------------------|---------------------|-------------------|-------|
| `ticket_id` | `id` | Plan/tasklist filenames, branch names, logging | Direct 1:1 mapping |
| `ticket_url` | `url` | Display and linking | Direct 1:1 mapping |
| `summary` | `branch_summary` | Branch name generation | Direct 1:1 mapping |
| `title` | `title` | Display, prompts, context | Direct 1:1 mapping |
| `description` | `description` | Planning context, prompts | Direct 1:1 mapping |
| `full_info` | `full_info` | Extended context | Direct 1:1 mapping |
| *(N/A)* | `platform` | Platform identification | New field (Platform enum) |
| *(N/A)* | `status` | Ticket status | New field (TicketStatus enum) |
| *(N/A)* | `type` | Ticket type | New field (TicketType enum) |
| *(N/A)* | `safe_branch_name` | Git branch name property | New computed property |
| *(N/A)* | `display_id` | Human-readable ID property | New computed property |

---

## Files Requiring Changes

### Production Code Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `spec/workflow/state.py` | **Core Migration** | Change `ticket: JiraTicket` → `ticket: GenericTicket`, update import |
| `spec/workflow/runner.py` | **Core Migration** | Update function signature, remove `fetch_ticket_info()` call |
| `spec/workflow/conflict_detection.py` | **Type Update** | Change type hint from `JiraTicket` to `GenericTicket` |
| `spec/workflow/step1_plan.py` | **Field Rename** | `ticket.ticket_id` → `ticket.id` |
| `spec/workflow/step2_tasklist.py` | **Field Rename** | `ticket.ticket_id` → `ticket.id` |
| `spec/workflow/step3_execute.py` | **Field Rename** | `ticket.ticket_id` → `ticket.id` |

> **Note:** `spec/cli.py` changes are handled by AMI-25, not this ticket.

### Test File Changes

| File | Changes Needed |
|------|----------------|
| `tests/test_workflow_state.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_workflow_runner.py` | Replace `JiraTicket` fixtures, update mocks |
| `tests/test_step1_plan.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_step2_tasklist.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_step3_execute.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_step4_update_docs.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_integration_workflow.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_autofix.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_task_memory.py` | Replace `JiraTicket` fixtures with `GenericTicket` |
| `tests/test_plan_tui.py` | Replace `JiraTicket` fixtures with `GenericTicket` |

---

## Implementation Steps

### Phase 1: Core State Migration

#### Step 1.1: Update WorkflowState

**File:** `spec/workflow/state.py`

```python
# Before
from spec.integrations.jira import JiraTicket

@dataclass
class WorkflowState:
    ticket: JiraTicket
    ...

# After
from spec.integrations.providers import GenericTicket

@dataclass
class WorkflowState:
    ticket: GenericTicket
    ...
```

**Specific Changes:**
1. Change import from `from spec.integrations.jira import JiraTicket` to `from spec.integrations.providers import GenericTicket`
2. Change field type annotation `ticket: JiraTicket` to `ticket: GenericTicket`
3. Update docstring from "Jira ticket information" to "Ticket information (platform-agnostic)"

#### Step 1.2: Update Conflict Detection

**File:** `spec/workflow/conflict_detection.py`

```python
# Before
from spec.integrations.jira import JiraTicket

def detect_context_conflict(
    ticket: JiraTicket,
    ...
) -> tuple[bool, str]:

# After
from spec.integrations.providers import GenericTicket

def detect_context_conflict(
    ticket: GenericTicket,
    ...
) -> tuple[bool, str]:
```

**Specific Changes:**
1. Change import from `from spec.integrations.jira import JiraTicket` to `from spec.integrations.providers import GenericTicket`
2. Update function signature type hint
3. Update docstring references from "JiraTicket" to "GenericTicket"

### Phase 2: Workflow Runner Migration

#### Step 2.1: Update run_spec_driven_workflow

**File:** `spec/workflow/runner.py`

```python
# Before
from spec.integrations.jira import JiraTicket, fetch_ticket_info

def run_spec_driven_workflow(
    ticket: JiraTicket,
    config: ConfigManager,
    ...
) -> bool:
    print_header(f"Starting Workflow: {ticket.ticket_id}")
    state = WorkflowState(ticket=ticket, ...)
    ...
    state.ticket = fetch_ticket_info(state.ticket, auggie)

# After
from spec.integrations.providers import GenericTicket

def run_spec_driven_workflow(
    ticket: GenericTicket,
    config: ConfigManager,
    ...
) -> bool:
    print_header(f"Starting Workflow: {ticket.id}")
    state = WorkflowState(ticket=ticket, ...)
    # Note: ticket info already fetched via TicketService before this point
```

**Specific Changes:**
1. Change import to `from spec.integrations.providers import GenericTicket`
2. Remove `fetch_ticket_info` import (no longer needed - TicketService handles this)
3. Change function parameter type from `JiraTicket` to `GenericTicket`
4. Update `ticket.ticket_id` → `ticket.id` in print statement
5. Remove `fetch_ticket_info()` call - ticket info is now pre-populated by TicketService
6. Update docstring references

#### Step 2.2: Update _setup_branch

**File:** `spec/workflow/runner.py`

```python
# Before
def _setup_branch(state: WorkflowState, ticket: JiraTicket) -> bool:
    if ticket.summary:
        branch_name = f"{ticket.ticket_id.lower()}-{ticket.summary}"
    else:
        branch_name = f"feature/{ticket.ticket_id.lower()}"

# After
def _setup_branch(state: WorkflowState, ticket: GenericTicket) -> bool:
    # Use GenericTicket's safe_branch_name property
    branch_name = ticket.safe_branch_name
```

**Specific Changes:**
1. Change type hint from `JiraTicket` to `GenericTicket`
2. Replace manual branch name generation with `ticket.safe_branch_name` property
3. Update docstring from "Jira ticket" to "Ticket"

### Phase 3: CLI Integration (OUT OF SCOPE - See AMI-25)

> **Note:** CLI migration is handled by [AMI-25](https://linear.app/amiadspec/issue/AMI-25). This ticket (AMI-24) focuses on workflow internals only.
>
> AMI-25 will:
> - Replace `parse_jira_ticket()` with `TicketService.get_ticket()`
> - Add `--platform` flag for disambiguation
> - Handle Jira/Linear ID ambiguity with user prompts
> - Use proper async context management for TicketService

For AMI-24, the CLI continues to use `parse_jira_ticket()` temporarily. The workflow runner signature changes to accept `GenericTicket`, so AMI-25 will need to convert the ticket before calling `run_spec_driven_workflow()`.

### Phase 4: Workflow Step Updates

#### Step 4.1: Update step1_plan.py

**File:** `spec/workflow/step1_plan.py`

Field renames in `_build_minimal_prompt()`:
- `state.ticket.ticket_id` → `state.ticket.id`

No import changes needed (uses `state.ticket` which is already `WorkflowState.ticket`).

#### Step 4.2: Update step2_tasklist.py

**File:** `spec/workflow/step2_tasklist.py`

Field renames:
- `state.ticket.ticket_id` → `state.ticket.id`

Affected functions:
- `_extract_tasklist_from_output()` - parameter rename only
- `_run_tasklist_generation()` - `state.ticket.ticket_id` → `state.ticket.id`
- `_run_tasklist_postprocess()` - `state.ticket.ticket_id` → `state.ticket.id`
- `_create_default_tasklist()` - `state.ticket.ticket_id` → `state.ticket.id`

#### Step 4.3: Update step3_execute.py

**File:** `spec/workflow/step3_execute.py`

Field renames:
- `state.ticket.ticket_id` → `state.ticket.id`

Affected locations (8 occurrences):
- `_create_run_log_dir(state.ticket.ticket_id)`
- `_cleanup_old_runs(state.ticket.ticket_id)`
- `TaskRunnerUI(ticket_id=state.ticket.ticket_id, ...)`
- `_print_execution_summary()` - console print
- `_run_tests_for_changed_code()` - log directory and UI
- `_suggest_commit()` - commit message generation

---

## Breaking Changes

> **Note:** This is a greenfield system with no production users. Breaking changes are acceptable and expected.

1. **Type Change in WorkflowState** - `WorkflowState.ticket` changes from `JiraTicket` to `GenericTicket`
2. **Field Name Changes** - All code accessing `ticket.ticket_id` must use `ticket.id`
3. **Function Signature Changes** - `run_spec_driven_workflow()` and related functions now accept `GenericTicket`
4. **Removed Function** - `fetch_ticket_info()` call is removed from workflow runner (TicketService handles this)

No backward compatibility or migration path is needed.

---

## Testing Strategy

### Unit Test Updates

All test files creating `JiraTicket` fixtures must be updated to create `GenericTicket` fixtures:

```python
# Before
from spec.integrations.jira import JiraTicket

@pytest.fixture
def ticket():
    return JiraTicket(
        ticket_id="TEST-123",
        ticket_url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description",
        summary="test-feature",
    )

# After
from spec.integrations.providers import GenericTicket, Platform

@pytest.fixture
def ticket():
    return GenericTicket(
        id="TEST-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description",
        branch_summary="test-feature",
    )
```

### Test File Update Checklist

| Test File | JiraTicket Occurrences | Priority |
|-----------|------------------------|----------|
| `tests/test_workflow_runner.py` | 7 fixtures | High |
| `tests/test_integration_workflow.py` | 13 fixtures | High |
| `tests/test_step2_tasklist.py` | 12 fixtures | High |
| `tests/test_task_memory.py` | 6 fixtures | Medium |
| `tests/test_step3_execute.py` | 1 fixture | Medium |
| `tests/test_step4_update_docs.py` | 1 fixture | Medium |
| `tests/test_step1_plan.py` | 1 fixture | Medium |
| `tests/test_workflow_state.py` | 1 fixture | Medium |
| `tests/test_autofix.py` | 1 fixture | Low |
| `tests/test_plan_tui.py` | 1 fixture | Low |

### Shared Test Fixture (Recommended)

Create a shared fixture in `tests/conftest.py` to reduce duplication:

```python
# tests/conftest.py
import pytest
from spec.integrations.providers import GenericTicket, Platform

@pytest.fixture
def generic_ticket():
    """Create a standard test ticket using GenericTicket."""
    return GenericTicket(
        id="TEST-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description for the feature implementation.",
        branch_summary="test-feature",
    )

@pytest.fixture
def generic_ticket_no_summary():
    """Create a test ticket without branch summary."""
    return GenericTicket(
        id="TEST-456",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-456",
        title="Test Feature No Summary",
        description="Test description.",
        branch_summary="",
    )
```

### Integration Test Scenarios

1. **End-to-end workflow with GenericTicket** - Verify full workflow executes correctly
2. **Branch name generation** - Verify `ticket.safe_branch_name` produces correct branch names
3. **Plan/tasklist file naming** - Verify files are named using `ticket.id`
4. **Multi-platform support** - Test with different Platform enum values

### Regression Tests

1. **Existing behavior preserved** - All existing tests should pass after migration
2. **No Jira-specific assumptions** - Tests should work with any platform's GenericTicket

---

## Dependencies

### Upstream Dependencies (Must be Complete First)

| Ticket | Component | Status |
|--------|-----------|--------|
| AMI-17 | ProviderRegistry | ✅ Implemented |
| AMI-18 | JiraProvider | ✅ Implemented |
| AMI-19 | GitHubProvider | ✅ Implemented |
| AMI-20 | LinearProvider | ✅ Implemented |
| AMI-21 | AzureDevOpsProvider | ✅ Implemented |
| AMI-22 | MondayProvider/TrelloProvider | ✅ Implemented |
| AMI-23 | TicketCache | ✅ Implemented |
| AMI-29 | TicketFetcher Protocol | ✅ Implemented |
| AMI-30 | AuggieMediatedFetcher | ✅ Implemented |
| AMI-31 | DirectAPIFetcher | ✅ Implemented |
| AMI-32 | TicketService Orchestration | ✅ Implemented |

### Downstream Dependencies (Blocked by This Ticket)

| Ticket | Description |
|--------|-------------|
| [AMI-25](https://linear.app/amiadspec/issue/AMI-25) | CLI migration to platform-agnostic providers (final ticket) |

### Scope Split: AMI-24 vs AMI-25

| Scope | AMI-24 (This Ticket) | AMI-25 (Next Ticket) |
|-------|----------------------|----------------------|
| WorkflowState | ✅ Migrate to GenericTicket | - |
| Workflow Runner | ✅ Update signatures | - |
| Workflow Steps | ✅ Update field access | - |
| Conflict Detection | ✅ Update type hints | - |
| CLI Entry Point | ❌ Out of scope | ✅ Replace parse_jira_ticket with TicketService |
| Platform Disambiguation | ❌ Out of scope | ✅ Handle ambiguous IDs (Jira vs Linear) |
| --platform flag | ❌ Out of scope | ✅ Add CLI flag |
| Test Updates | ✅ Update fixtures | ✅ CLI-specific tests |

### Integration Points

| Component | Integration Type | Notes |
|-----------|------------------|-------|
| `TicketService` (AMI-32) | Provides GenericTicket | Entry point for ticket fetching |
| `ProviderRegistry` (AMI-17) | Platform detection | Determines which provider to use |
| All 6 Providers (AMI-18-22) | Normalization | Convert raw API data to GenericTicket |
| `TicketCache` (AMI-23) | Caching | Caches GenericTicket instances |

---

## Acceptance Criteria

### Core Migration
- [ ] `WorkflowState.ticket` type changed to `GenericTicket`
- [ ] Import changed from `spec.integrations.jira` to `spec.integrations.providers`
- [ ] `run_spec_driven_workflow()` accepts `GenericTicket` parameter
- [ ] `_setup_branch()` uses `GenericTicket.safe_branch_name`
- [ ] `detect_context_conflict()` accepts `GenericTicket` parameter
- [ ] `fetch_ticket_info()` call removed from runner

### Field Renames
- [ ] All `ticket.ticket_id` usages changed to `ticket.id`
- [ ] All `ticket.ticket_url` usages changed to `ticket.url`
- [ ] All `ticket.summary` usages changed to `ticket.branch_summary`
- [ ] Branch name generation uses `ticket.safe_branch_name` property

### Workflow Steps
- [ ] `step1_plan.py` updated
- [ ] `step2_tasklist.py` updated
- [ ] `step3_execute.py` updated

### Tests
- [ ] All test files updated to use `GenericTicket` fixtures
- [ ] All existing tests pass
- [ ] No type errors reported by mypy/pyright

> **Note:** CLI changes (`spec/cli.py`) are out of scope - see AMI-25.

---

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| Phase 1: Core State Migration | 1 hour | Low |
| Phase 2: Workflow Runner Migration | 1-2 hours | Low |
| Phase 3: CLI Integration | *(Out of scope - AMI-25)* | - |
| Phase 4: Workflow Step Updates | 1 hour | Low |
| Test Updates | 2-3 hours | Low |
| **Total** | **5-7 hours** | **Low** |

---

## References

- `specs/00_Architecture_Refactor_Spec.md` - Original architecture specification
- `specs/AMI-32-implementation-plan.md` - TicketService orchestration (entry point)
- `specs/AMI-18-implementation-plan.md` - JiraProvider (example provider implementation)
- `spec/integrations/providers/base.py` - GenericTicket dataclass definition

---

## Appendix: Current Codebase State

### JiraTicket Usage Summary (as of 2026-01-27)

**Production Code (7 files):**
```
spec/integrations/jira.py        - JiraTicket class definition + parse_jira_ticket()
spec/integrations/__init__.py    - Re-exports JiraTicket
spec/workflow/state.py           - WorkflowState.ticket: JiraTicket
spec/workflow/runner.py          - JiraTicket parameter, fetch_ticket_info()
spec/workflow/conflict_detection.py - JiraTicket parameter
spec/cli.py                      - parse_jira_ticket() usage
```

**Test Files (10 files with JiraTicket fixtures):**
```
tests/test_workflow_runner.py    - 7 JiraTicket fixtures
tests/test_integration_workflow.py - 13 JiraTicket fixtures
tests/test_step2_tasklist.py     - 12 JiraTicket fixtures
tests/test_task_memory.py        - 6 JiraTicket fixtures
tests/test_workflow_state.py     - 1 JiraTicket fixture
tests/test_step1_plan.py         - 1 JiraTicket fixture
tests/test_step3_execute.py      - 1 JiraTicket fixture
tests/test_step4_update_docs.py  - 1 JiraTicket fixture
tests/test_autofix.py            - 1 JiraTicket fixture
tests/test_plan_tui.py           - 1 JiraTicket fixture
tests/test_jira.py               - JiraTicket tests (keep for parse_jira_ticket)
```

### GenericTicket Properties Used by Workflow

| Property | Type | Description |
|----------|------|-------------|
| `id` | `str` | Unique ticket identifier |
| `platform` | `Platform` | Source platform enum |
| `url` | `str` | Full URL to ticket |
| `title` | `str` | Ticket title |
| `description` | `str` | Full description |
| `branch_summary` | `str` | Short summary for branch name |
| `full_info` | `str` | Complete raw ticket information |
| `safe_branch_name` | property | Git-safe branch name (computed) |
| `display_id` | property | Human-readable ID (computed) |
