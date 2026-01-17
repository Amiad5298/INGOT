# Subagent Integration - Implementation Task List

## Overview

This is the executable task list for implementing the subagent integration.
Each task is designed to be completed independently where possible.

---

## Phase 1: Foundation

### Fundamental Tasks

- [ ] **Create agent directory structure**
  - Create `.augment/agents/` directory in repository root
  - Add `.augment/agents/` to `.gitignore` if agents should be user-local
  - OR commit agents if they should be shared (recommended)

- [ ] **Create spec-planner.md agent file**
  - Copy template from SUBAGENT-INTEGRATION-SPEC-TEMPLATES.md
  - Extract relevant prompt content from `spec/workflow/step1_plan.py`
  - Adapt inline prompt to standalone agent format
  - Test with: `auggie --agent spec-planner "Test prompt"`

- [ ] **Create spec-tasklist.md agent file**
  - Copy template from SUBAGENT-INTEGRATION-SPEC-TEMPLATES.md
  - Extract relevant prompt content from `spec/workflow/step2_tasklist.py`
  - Include task categorization guidelines
  - Test with: `auggie --agent spec-tasklist "Test prompt"`

- [ ] **Create spec-implementer.md agent file**
  - Copy template from SUBAGENT-INTEGRATION-SPEC-TEMPLATES.md
  - Extract relevant prompt content from `spec/workflow/step3_execute.py`
  - Focus on single-task execution guidelines
  - Test with: `auggie --agent spec-implementer "Test prompt"`

---

## Phase 2: AuggieClient Updates

### Fundamental Tasks

- [ ] **Add agent parameter to _build_command()**
  - File: `spec/integrations/auggie.py`
  - Add `agent: str` parameter (required for workflow calls)
  - Add `--agent` flag construction
  - Model comes from agent file, not from AuggieClient

- [ ] **Add agent parameter to run methods**
  - Update `run()` method signature and implementation
  - Update `run_print_with_output()` method
  - Update `run_with_callback()` method
  - All should pass `agent` to `_build_command()`

- [ ] **Add subagent constants**
  - Define `SPEC_AGENT_PLANNER`, `SPEC_AGENT_TASKLIST`, etc.
  - Export from `spec/integrations/__init__.py`

---

## Phase 3: Workflow Integration

### Independent Tasks (can run in parallel after Phase 2)

- [ ] **Update Step 1 to use spec-planner agent**
  - File: `spec/workflow/step1_plan.py`
  - Use `SPEC_AGENT_PLANNER` agent with minimal prompt
  - **DELETE inline prompt building code**
  - Preserve all other existing functionality

- [ ] **Update Step 2 to use spec-tasklist agent**
  - File: `spec/workflow/step2_tasklist.py`
  - Use `SPEC_AGENT_TASKLIST` agent with plan content
  - **DELETE inline prompt building code**
  - Preserve task list parsing logic

- [ ] **Update Step 3 to use spec-implementer agent**
  - File: `spec/workflow/step3_execute.py`
  - Use `SPEC_AGENT_IMPLEMENTER` agent with task details
  - **DELETE inline prompt building code**
  - Preserve parallel execution, retry logic, logging

---

## Phase 4: Configuration

### Independent Tasks

- [ ] **Add subagent settings to Settings dataclass**
  - File: `spec/config/settings.py`
  - Add customizable agent name fields

- [ ] **Add CLI flags for subagent control** (optional)
  - Add optional agent name overrides if needed

- [ ] **Add environment variable support** (optional)
  - `SPEC_AGENT_*` for custom agent names

---

## Phase 5: Testing & Documentation

### Independent Tasks

- [ ] **Add unit tests for AuggieClient agent support**
  - Test `_build_command()` with agent parameter
  - Test `agent_exists()` helper
  - Mock file system for agent detection tests

- [ ] **Add integration tests for subagent workflow**
  - Test fallback behavior when agents don't exist
  - Test that agents are invoked correctly when present

- [ ] **Update README with subagent documentation**
  - Explain what subagents are
  - Document how to customize agent prompts
  - Explain configuration options

---

## Validation Checklist

After implementation, verify:

- [ ] `auggie --agent spec-planner "test"` works from command line
- [ ] `auggie --agent spec-tasklist "test"` works from command line
- [ ] `auggie --agent spec-implementer "test"` works from command line
- [ ] SPEC workflow completes successfully with agents
- [ ] All existing tests pass (updated for new behavior)
- [ ] New tests pass
- [ ] **Inline prompt code has been deleted**

