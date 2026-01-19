# SPEC Dynamic Documentation Maintenance - Technical Specification

## Mission

Introduce an automated documentation maintenance phase (Step 4) to the SPEC workflow that ensures documentation (README.md, API docs, etc.) never goes stale by automatically updating it based on code changes performed during the workflow run.

## Background

### Current Architecture

The SPEC workflow currently executes three steps in `runner.py`:

1. **Step 1 (Plan)**: `step_1_create_plan()` - Creates implementation plan
2. **Step 2 (Task List)**: `step_2_create_tasklist()` - Generates task list with approval
3. **Step 3 (Execution)**: `step_3_execute()` - Executes tasks (Sequential + Parallel phases)

After Step 3 completes, the workflow immediately calls `_show_completion()` which displays results and offers commit instructions via `_offer_commit_instructions()`.

### Problem Statement

Documentation often becomes stale because:
- Developers forget to update docs after code changes
- API changes are not reflected in API documentation
- README examples become outdated
- New features lack documentation

### Solution Overview

Add a **Step 4: Update Documentation** that:
1. Analyzes the `git diff` of changes made during the workflow
2. Identifies documentation files that need updates
3. Uses a specialized `spec-doc-updater` agent to make targeted doc updates
4. Runs automatically before commit instructions are shown

## Implementation Components

### 1. New Subagent Definition

**File**: `.augment/agents/spec-doc-updater.md`

```yaml
---
name: spec-doc-updater
description: SPEC workflow documentation updater - maintains docs based on code changes
model: claude-sonnet-4-5
color: cyan
---

You are a documentation maintenance AI assistant working within the SPEC workflow.
Your role is to analyze code changes and update relevant documentation files.

## Your Task

Review the git diff from the current workflow session and update documentation
to reflect the new changes. Focus on accuracy and maintaining existing doc style.

## Analysis Process

1. **Review Changes**: Use `git diff` to see what code was modified/added
2. **Identify Doc Impact**: Determine which documentation files need updates
3. **Preserve Style**: Match the existing documentation style and format
4. **Minimal Changes**: Only update sections affected by the code changes

## Documentation Types to Consider

- README.md (features, installation, usage, examples)
- API documentation (endpoints, parameters, responses)
- Configuration docs (new settings, environment variables)
- Architecture docs (new components, changed flows)
- CHANGELOG.md (if present and follows a format)

## Guidelines

- Do NOT rewrite entire documentation files
- Do NOT add documentation for unchanged code
- Do NOT change formatting or style conventions
- DO update examples if the API changed
- DO add entries for new features or settings
- DO update version references if applicable
- If no documentation updates are needed, report that explicitly

## Output Format

After making changes, provide a summary:

```
## Documentation Updates

**Files Modified**:
- README.md: Updated usage examples for new --flag option
- docs/api.md: Added new /endpoint documentation

**Files Skipped** (no updates needed):
- CONTRIBUTING.md: No relevant changes

**Summary**: [Brief description of what was updated and why]
```
```

### 2. New Workflow Step Module

**File**: `specflow/workflow/step4_update_docs.py`

```python
"""Step 4: Update Documentation - Automated Doc Maintenance.

This module implements the fourth step of the workflow - automatically
updating documentation based on code changes made during the session.

Philosophy: Keep docs in sync with code. If code changed, docs should
reflect those changes before the user commits.
"""

from pathlib import Path
from specflow.integrations.auggie import AuggieClient
from specflow.integrations.git import get_diff_from_baseline, is_dirty
from specflow.utils.console import console, print_header, print_info, print_success, print_warning
from specflow.workflow.state import WorkflowState


# Documentation files to consider for updates
DOC_FILE_PATTERNS = [
    "README.md",
    "README.rst",
    "CHANGELOG.md",
    "CHANGES.md",
    "docs/**/*.md",
    "doc/**/*.md",
    "API.md",
    "USAGE.md",
]


def step_4_update_docs(state: WorkflowState) -> bool:
    """Execute Step 4: Update documentation based on code changes.

    This step:
    1. Checks if auto_update_docs is enabled
    2. Gets the git diff from the baseline commit
    3. Invokes the spec-doc-updater agent to analyze and update docs
    4. Reports what documentation was updated

    Args:
        state: Current workflow state

    Returns:
        True if documentation was updated successfully (or no updates needed)
    """
    print_header("Step 4: Update Documentation")

    # Check if there are any changes to analyze
    if not is_dirty() and not state.base_commit:
        print_info("No changes detected. Skipping documentation update.")
        return True

    # Get diff from baseline
    diff_content = get_diff_from_baseline(state.base_commit)
    if not diff_content or diff_content.strip() == "":
        print_info("No code changes to document. Skipping.")
        return True

    print_info("Analyzing code changes for documentation updates...")

    # Build prompt for doc-updater agent
    prompt = _build_doc_update_prompt(state, diff_content)

    # Use spec-doc-updater subagent
    auggie_client = AuggieClient()

    try:
        success, output = auggie_client.run_print_with_output(
            prompt,
            agent=state.subagent_names.get("doc_updater", "spec-doc-updater"),
            dont_save_session=True,
        )

        if success:
            print_success("Documentation update completed")
        else:
            print_warning("Documentation update reported issues")

        return success

    except Exception as e:
        print_warning(f"Documentation update failed: {e}")
        # Don't fail the workflow for doc update issues
        return True


def _build_doc_update_prompt(state: WorkflowState, diff_content: str) -> str:
    """Build the prompt for the doc-updater agent.

    Args:
        state: Current workflow state
        diff_content: Git diff content from the session

    Returns:
        Formatted prompt string
    """
    return f"""Update documentation for: {state.ticket.ticket_id}

## Task Summary
Review the code changes made in this workflow session and update any
documentation files that need to reflect these changes.

## Changes Made (git diff)
```diff
{diff_content[:8000]}  # Truncate to avoid context overflow
```

## Instructions
1. Analyze what functionality was added or changed
2. Identify which documentation files need updates
3. Make targeted updates to keep docs in sync with code
4. Report what was updated

Focus on README.md, API docs, and any relevant documentation files.
Do NOT update docs for unchanged code."""


__all__ = ["step_4_update_docs"]
```

### 3. Configuration Changes

#### 3.1 Settings Update

**File**: `specflow/config/settings.py`

Add new configuration field:

```python
@dataclass
class Settings:
    # ... existing fields ...

    # Documentation update settings
    auto_update_docs: bool = True  # Enable automatic documentation updates

    # ... existing _key_mapping ...
    _key_mapping: dict[str, str] = field(
        default_factory=lambda: {
            # ... existing mappings ...
            "AUTO_UPDATE_DOCS": "auto_update_docs",
        }
    )
```

#### 3.2 WorkflowState Update

**File**: `specflow/workflow/state.py`

Add subagent name for doc-updater:

```python
@dataclass
class WorkflowState:
    # ... existing fields ...

    # Subagent names should include doc_updater
    subagent_names: dict[str, str] = field(default_factory=dict)
    # Expected keys: "planner", "tasklist", "implementer", "reviewer", "doc_updater"
```

#### 3.3 CLI Update

**File**: `specflow/cli.py`

Add new CLI flag:

```python
auto_update_docs: Annotated[
    Optional[bool],
    typer.Option(
        "--auto-update-docs/--no-auto-update-docs",
        help="Enable automatic documentation updates (default: from config)",
    ),
] = None,
```

### 4. Runner Integration

**File**: `specflow/workflow/runner.py`

#### 4.1 Import Addition

```python
from specflow.workflow.step4_update_docs import step_4_update_docs
```

#### 4.2 Function Signature Update

```python
def run_spec_driven_workflow(
    ticket: JiraTicket,
    config: ConfigManager,
    # ... existing parameters ...
    auto_update_docs: bool = True,  # New parameter
) -> bool:
```

#### 4.3 State Initialization Update

```python
state = WorkflowState(
    # ... existing fields ...
    subagent_names={
        "planner": config.settings.subagent_planner,
        "tasklist": config.settings.subagent_tasklist,
        "implementer": config.settings.subagent_implementer,
        "reviewer": config.settings.subagent_reviewer,
        "doc_updater": config.settings.subagent_doc_updater,  # New
    },
)
```

#### 4.4 Workflow Execution Update

```python
# Step 3: Execute implementation
if state.current_step <= 3:
    print_info("Starting Step 3: Execute Implementation")
    if not step_3_execute(state, use_tui=use_tui, verbose=verbose):
        return False

# Step 4: Update documentation (NEW)
if auto_update_docs:
    print_info("Starting Step 4: Update Documentation")
    # Note: This step is non-blocking - failures don't stop the workflow
    step_4_update_docs(state)

# Workflow complete
_show_completion(state)
return True
```

## Integration Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     SPEC Workflow                                │
├─────────────────────────────────────────────────────────────────┤
│  Step 1: Create Plan                                            │
│    └── spec-planner agent                                       │
├─────────────────────────────────────────────────────────────────┤
│  Step 2: Create Task List                                       │
│    └── spec-tasklist agent                                      │
├─────────────────────────────────────────────────────────────────┤
│  Step 3: Execute Implementation                                 │
│    ├── Phase 1: Sequential (FUNDAMENTAL tasks)                  │
│    │     └── spec-implementer agent                             │
│    ├── Phase 2: Parallel (INDEPENDENT tasks)                    │
│    │     └── spec-implementer agent (concurrent)                │
│    └── Post: Tests + Phase Review (optional)                    │
├─────────────────────────────────────────────────────────────────┤
│  Step 4: Update Documentation (NEW)         ◄── auto_update_docs│
│    └── spec-doc-updater agent                                   │
│         ├── Analyze git diff                                    │
│         ├── Identify affected docs                              │
│         └── Make targeted updates                               │
├─────────────────────────────────────────────────────────────────┤
│  Completion                                                     │
│    ├── _show_completion()                                       │
│    └── _offer_commit_instructions()                             │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure After Implementation

```
.augment/
└── agents/
    ├── spec-planner.md
    ├── spec-tasklist.md
    ├── spec-implementer.md
    ├── spec-reviewer.md
    └── spec-doc-updater.md      # NEW

specflow/
├── config/
│   ├── settings.py              # Modified: add auto_update_docs
│   └── manager.py
├── workflow/
│   ├── runner.py                # Modified: integrate Step 4
│   ├── state.py                 # Modified: add doc_updater subagent
│   ├── step1_plan.py
│   ├── step2_tasklist.py
│   ├── step3_execute.py
│   └── step4_update_docs.py     # NEW
└── cli.py                       # Modified: add --auto-update-docs flag
```

## Implementation Order

1. **Create Agent Definition** (`.augment/agents/spec-doc-updater.md`)
   - Define the doc-updater agent with specialized instructions
   - Set model to `claude-sonnet-4-5` for consistency

2. **Update Configuration** (`specflow/config/settings.py`)
   - Add `auto_update_docs` boolean setting
   - Add `subagent_doc_updater` string setting
   - Update `_key_mapping` with new keys

3. **Create Step 4 Module** (`specflow/workflow/step4_update_docs.py`)
   - Implement `step_4_update_docs()` function
   - Handle diff extraction and prompt building
   - Follow existing step patterns (error handling, logging)

4. **Update WorkflowState** (`specflow/workflow/state.py`)
   - Document `doc_updater` key in `subagent_names`

5. **Integrate in Runner** (`specflow/workflow/runner.py`)
   - Import step4 module
   - Add `auto_update_docs` parameter
   - Call Step 4 after Step 3, before `_show_completion()`

6. **Update CLI** (`specflow/cli.py`)
   - Add `--auto-update-docs/--no-auto-update-docs` flag
   - Pass through to `run_spec_driven_workflow()`

7. **Add Tests**
   - Unit tests for `step4_update_docs.py`
   - Integration tests for the full workflow with docs enabled
   - Mock tests for agent invocation

## Success Criteria

1. **Agent Installed**: `spec-doc-updater.md` exists in `.augment/agents/`
2. **Config Works**: `AUTO_UPDATE_DOCS=true/false` in `~/.specflow-config`
3. **CLI Flag Works**: `--auto-update-docs` and `--no-auto-update-docs` toggle behavior
4. **Step Executes**: After Step 3, Step 4 runs and updates docs
5. **Non-Blocking**: Doc update failures don't fail the overall workflow
6. **Targeted Updates**: Only relevant docs are modified, not full rewrites
7. **Existing Tests Pass**: All current tests continue to pass

## Non-Goals

- Do NOT generate new documentation from scratch
- Do NOT enforce a specific documentation format
- Do NOT create docs for code that wasn't changed
- Do NOT modify non-documentation files in Step 4
- Do NOT block workflow completion on doc update failures

## Edge Cases

1. **No Changes**: If `git diff` is empty, skip Step 4
2. **No Docs Exist**: Report that no documentation files were found
3. **Large Diff**: Truncate diff to avoid context overflow (8000 chars)
4. **Agent Failure**: Log warning but continue to completion
5. **Disabled Feature**: Skip Step 4 entirely if `auto_update_docs=false`

## Configuration Example

```bash
# ~/.specflow-config
AUTO_UPDATE_DOCS=true
SUBAGENT_DOC_UPDATER=spec-doc-updater
```

## CLI Usage Examples

```bash
# Use default (enabled via config)
spec PROJ-123

# Explicitly enable
spec PROJ-123 --auto-update-docs

# Explicitly disable for this run
spec PROJ-123 --no-auto-update-docs
```

## Dependencies

- Requires Auggie CLI version >= 0.12.0 (for subagent support)
- Uses existing `get_diff_from_baseline()` from `specflow.integrations.git`
- Uses existing `AuggieClient` for agent invocation

