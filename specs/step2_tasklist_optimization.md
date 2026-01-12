# Specification: Step 2 Task List Optimization for AI Execution Quality

## Overview

**Goal:** Optimize the task list generation in Step 2 to improve AI execution quality in Step 3.

**Core Insight:** The current task generation is designed for human task management (small, time-boxed units) but executes via AI agents that benefit from larger, coherent units of work.

**Constraint:** Do NOT implement any changes yet - this is a specification document only.

---

## Problem Statement

### Current Implementation

The `_generate_tasklist()` function in `step2_tasklist.py` (lines 136-222) generates tasks with these requirements:

```python
prompt = f"""Based on this implementation plan, create a detailed task list.
...
Requirements:
1. Use markdown checkbox format: - [ ] Task description
2. Break down into small, atomic tasks (15-30 minutes each)  # ← PROBLEM
3. Order tasks logically (dependencies first)
4. Include testing tasks
5. Each task should be independently verifiable            # ← PROBLEM
...
Be specific and actionable. Each task should be clear enough to execute without ambiguity."""
```

**Note:** The function now uses `run_print_with_output()` and `_extract_tasklist_from_output()` to capture and persist the task list from AI output, fixing a previous bug where task lists were lost.

### Core Issues

#### Issue 1: Time-Based Granularity is Human-Centric

The "15-30 minutes each" guideline assumes:
- Human developers who need mental breaks
- Human sprint planning with story points
- Human progress tracking and standup updates

AI agents have **none** of these constraints. They:
- Don't fatigue within a session
- Don't need progress checkpoints for morale
- Benefit from maintaining context continuity

**Example of Problematic Task Breakdown:**

```markdown
# Current: Over-fragmented
- [ ] Create new file src/services/user.py
- [ ] Add import statements for dependencies
- [ ] Implement UserService class skeleton
- [ ] Add create_user() method
- [ ] Add get_user() method  
- [ ] Add update_user() method
- [ ] Add delete_user() method
- [ ] Add type hints to all methods
- [ ] Write unit test for create_user
- [ ] Write unit test for get_user
- [ ] Write unit test for update_user
- [ ] Write unit test for delete_user
```

```markdown
# Better: Coherent units
- [ ] Implement UserService with CRUD operations (create, get, update, delete)
- [ ] Add comprehensive unit tests for UserService
```

#### Issue 2: Context Discontinuity in Step 3

Each task in Step 3 executes with:
- `dont_save_session=True` - clean context per task
- Minimal prompt: just task name + plan file reference

When tasks are too granular:

| Task N | Task N+1 |
|--------|----------|
| AI learns codebase patterns | AI must **re-discover** same patterns |
| AI reads plan context | AI must **re-read** same context |
| AI establishes coding style | AI may use **different** style |

**Quantified Impact:**
- 12 micro-tasks × ~2 min context setup = 24 min overhead
- 2 coherent tasks × ~2 min context setup = 4 min overhead
- **20 minute waste** on a single feature

#### Issue 3: "Independently Verifiable" Creates Artificial Boundaries

The requirement that "each task should be independently verifiable" leads to:
- Incomplete code units that can't run on their own
- Test tasks separated from implementation tasks
- Tasks like "Add type hints" which are meaningless in isolation

**Reality:** A function without its tests is NOT independently verifiable. They're one unit.

#### Issue 4: Mismatch with Optimistic Execution Model

Step 3's philosophy (from `step3_execute.py` docstring):

```
Philosophy: Trust the AI. If it returns success, it succeeded.
Don't nanny it with file checks and retry loops.
```

But the task list assumes a defensive model with:
- Frequent checkpoints
- Incremental verification
- Small, reversible changes

**The task structure fights the execution philosophy.**

---

## Proposed Solution

### New Task Generation Philosophy

**Principle: Tasks should represent complete, coherent units of work that align with natural code boundaries.**

A "good task" for AI execution:
1. **Feature-complete:** Implements a working capability, not a fragment
2. **Testable as a unit:** Includes implementation + tests together
3. **Context-preserving:** Minimizes context resets
4. **Outcome-focused:** Describes WHAT to achieve, not HOW to do it step-by-step

### New Prompt Engineering

Replace the current prompt with:

```python
prompt = f"""Based on this implementation plan, create a task list optimized for AI agent execution.

Plan:
{plan_content}

## Task Generation Guidelines:

### Size & Scope
- Each task should represent a **complete, coherent unit of work**
- Target 3-8 tasks for a typical feature (not 15-25 micro-tasks)
- A task should implement a full capability, not fragments
- Include tests WITH implementation, not as separate tasks

### Good Task Examples:
- "Implement UserService with CRUD operations and unit tests"
- "Add authentication middleware with JWT validation and integration tests"
- "Create database migration for users table and seed data"
- "Refactor payment module to use new pricing engine"

### Bad Task Examples (avoid these):
- "Create new file" (too granular)
- "Add import statements" (not a real unit of work)
- "Write test for function X" (tests should be with implementation)
- "Add type hints" (should be part of implementation task)

### Task Boundaries
- Align tasks with **natural code boundaries**: modules, features, layers
- A task should leave the codebase in a **working state**
- If tasks depend on each other, note the dependency

### Format
- Use markdown checkbox format: - [ ] Task description
- Order tasks by dependency (prerequisites first)
- Keep descriptions concise but specific

Be outcome-focused: describe WHAT to achieve, not HOW to do it step-by-step.
The AI agent will determine the implementation approach."""
```

---

## Implementation Plan

### Phase 1: Prompt Update (Low Risk)

**File:** `ai_workflow/workflow/step2_tasklist.py`

**Changes:**
1. Replace the prompt in `_generate_tasklist()` (lines 158-176)
2. Update the example format section
3. Remove time-based guidance ("15-30 minutes")

**Estimated Effort:** 30 minutes

**Rollback:** Revert to previous prompt if issues arise

### Phase 2: Default Template Update

**File:** `ai_workflow/workflow/step2_tasklist.py`

**Changes:**
Update `_create_default_tasklist()` (lines 225-248) to match new philosophy:

```python
template = f"""# Task List: {state.ticket.ticket_id}

## Implementation Tasks

- [ ] [Core functionality implementation with tests]
- [ ] [Integration/API layer with tests]
- [ ] [Documentation updates]

## Notes
Tasks represent complete units of work, not micro-steps.
Each task should leave the codebase in a working state.
"""
```


---

## Success Criteria

### Quantitative Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Average tasks per feature | 12-20 | 4-8 |
| First-attempt task success rate | ~70% | ~85% |
| Average retries per workflow | 3-5 | 1-2 |
| Context setup overhead | 24+ min | <10 min |

### Qualitative Indicators

- [ ] Tasks describe outcomes, not micro-steps
- [ ] Implementation and tests are grouped together
- [ ] Each task leaves codebase in working state
- [ ] Code patterns are consistent across tasks
- [ ] Fewer "continuation" tasks needed

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tasks too large for AI context | Low | Medium | AI will use codebase-retrieval; can split if needed |
| User expects granular tracking | Medium | Low | Education; user can edit task list |
| Regression in task quality | Low | Medium | A/B test with subset of users |

---

## Appendix: Research Notes

### Why Clean Context (`dont_save_session=True`) is Correct

From `specs/step3_execute_refactor_spec.md`:
> **Constraint:** Maintain isolation (`dont_save_session=True`) - this is correct for quality.

The isolation prevents context pollution across unrelated tasks. The solution is NOT to remove isolation, but to make each isolated unit **complete enough** that it doesn't need prior context.

### Existing Task Memory System

`ai_workflow/workflow/task_memory.py` captures patterns from completed tasks:
- Files modified
- Patterns used (async/await, error handling, etc.)
- Key decisions

This is for **analytics**, not prompt injection. The pattern context is intentionally NOT injected into prompts to avoid bloat.

### Related Documentation

- `docs/code-review-step3-execute.md` - Step 3 execution analysis
- `docs/step3-improvements-summary.md` - Step 3 improvement roadmap
- `specs/step3_execute_refactor_spec.md` - Step 3 refactoring spec

---

## Code Change Summary

### File: `ai_workflow/workflow/step2_tasklist.py`

**Function:** `_generate_tasklist()` (lines 136-222)

**Before:**
```python
prompt = f"""Based on this implementation plan, create a detailed task list.

Plan:
{plan_content}

Requirements:
1. Use markdown checkbox format: - [ ] Task description
2. Break down into small, atomic tasks (15-30 minutes each)
3. Order tasks logically (dependencies first)
4. Include testing tasks
5. Each task should be independently verifiable

Example format:
- [ ] Create new module file
- [ ] Implement core function
- [ ] Add unit tests
- [ ] Update documentation

Be specific and actionable. Each task should be clear enough to execute without ambiguity."""
```

**Note:** The prompt no longer asks the AI to save to a file path. The `_extract_tasklist_from_output()` function now extracts and persists tasks from the AI's response.

**After:** (See "New Prompt Engineering" section above for full prompt)

Key differences:
1. Remove "15-30 minutes" time-based guidance
2. Remove "small, atomic tasks" language
3. Add "complete, coherent unit of work" guidance
4. Add good/bad task examples
5. Emphasize outcome-focused descriptions
6. Group tests with implementation

---

## Next Steps (Do NOT Implement Yet)

1. **Review this specification** with stakeholders
2. **Gather baseline metrics** on current task generation
3. **Implement Phase 1** (prompt update only)
4. **A/B test** new prompt vs old prompt
5. **Measure impact** on Step 3 execution quality
6. **Iterate** based on results

