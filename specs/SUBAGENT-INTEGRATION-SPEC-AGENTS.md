# Subagent Integration - Agent Definitions

## Overview

This specification defines the subagent markdown files to be created in `.augment/agents/`.
Each file uses YAML frontmatter for configuration and markdown body for the agent prompt.

---

## Agent 1: spec-planner.md

**Purpose**: Step 1 - Create implementation plan from ticket/requirements

**Location**: `.augment/agents/spec-planner.md`

### Frontmatter
```yaml
---
name: spec-planner
description: SPEC workflow planner - creates implementation plans from requirements
model: claude-sonnet-4-5
color: blue
---
```

### Prompt Body
Extract and adapt the planning prompt from `spec/workflow/step1_plan.py`:
- Focus on analyzing requirements and creating structured implementation plans
- Include guidelines for clarity, completeness, and actionability
- Reference the ticket context and codebase analysis
- Output format: Markdown with clear sections

**Key sections to include**:
1. Role definition (implementation planner)
2. Analysis guidelines (understand requirements, identify components)
3. Plan structure (overview, phases, considerations)
4. Output format requirements

---

## Agent 2: spec-tasklist.md

**Purpose**: Step 2 - Generate task list from implementation plan

**Location**: `.augment/agents/spec-tasklist.md`

### Frontmatter
```yaml
---
name: spec-tasklist
description: SPEC workflow task generator - creates executable task lists
model: claude-sonnet-4-5
color: cyan
---
```

### Prompt Body
Extract and adapt the task list prompt from `spec/workflow/step2_tasklist.py`:
- Task categorization (FUNDAMENTAL vs INDEPENDENT)
- Size and scope guidelines
- File disjointness requirements for parallel tasks
- Setup Task Pattern for shared file conflicts
- Output format: Markdown task list with category markers

**Key sections to include**:
1. Role definition (task list generator)
2. Task sizing guidelines (3-8 tasks typically)
3. Category definitions with examples
4. File conflict resolution strategies
5. Output format with category markers

---

## Agent 3: spec-implementer.md

**Purpose**: Step 3 - Execute individual implementation tasks

**Location**: `.augment/agents/spec-implementer.md`

### Frontmatter
```yaml
---
name: spec-implementer
description: SPEC workflow implementer - executes individual tasks
model: claude-sonnet-4-5
color: green
---
```

### Prompt Body
Extract and adapt the task execution prompt from `spec/workflow/step3_execute.py`:
- Focus on completing ONE specific task
- Reference implementation plan for context
- Include testing with implementation
- Commit guidelines (don't commit, SPEC handles checkpoints)

**Key sections to include**:
1. Role definition (task executor)
2. Single-task focus guidelines
3. Implementation quality standards
4. Testing requirements
5. What NOT to do (no commits, no scope creep)

---

## Agent 4: spec-reviewer.md (Optional)

**Purpose**: Post-task validation and code review

**Location**: `.augment/agents/spec-reviewer.md`

### Frontmatter
```yaml
---
name: spec-reviewer
description: SPEC workflow reviewer - validates completed tasks
model: claude-sonnet-4-5
color: purple
---
```

### Prompt Body
Create a review-focused prompt:
- Verify task completion against requirements
- Check for common issues (missing tests, incomplete implementation)
- Validate no unintended changes
- Quick sanity check, not full code review

**Key sections to include**:
1. Role definition (task validator)
2. Validation checklist
3. What to flag vs what to accept
4. Output format (pass/fail with notes)

---

## Implementation Notes

### Extracting Prompts
The current prompts are embedded in Python files as f-strings. When extracting:
1. Remove Python-specific formatting (`{variable}` becomes placeholder documentation)
2. Document which dynamic values will be injected at runtime
3. Keep the core instruction structure intact

### Dynamic Value Injection
Subagent prompts are static. Dynamic values (ticket ID, plan content, task name) must be passed in the user prompt when invoking the agent:

```bash
# Example invocation pattern
auggie --agent spec-planner "Create implementation plan for ticket PROJ-123. Context: {ticket_description}"
```

---

## Validation Checklist

- [ ] All four agent files created in `.augment/agents/`
- [ ] Each file has valid YAML frontmatter
- [ ] Prompts are comprehensive and self-contained
- [ ] Dynamic value placeholders are documented
- [ ] Agent names match expected values in code
- [ ] Models are correctly specified
- [ ] Test each agent manually: `auggie --agent <name> "test"`

