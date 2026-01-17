# SPEC Subagent Integration - Master Specification

## Mission

Integrate Auggie CLI's new subagent feature into the SPEC workflow using a **hybrid approach** that:
1. Leverages subagents for specialized prompts, model selection, and observability
2. Preserves SPEC's robust Python-based orchestration (parallel execution, dependencies, checkpoints)
3. Makes agent configurations shareable and maintainable via markdown files

## Background

### Current Architecture
- SPEC uses `AuggieClient` to invoke `auggie` CLI commands
- Step 1-2 (Planning): Single Auggie calls with inline prompts
- Step 3 (Execution): Parallel task execution via `ThreadPoolExecutor` with separate Auggie processes
- Each task uses `--dont-save-session` for isolation

### New Auggie Subagent Feature (Jan 2026)
- Subagents are defined in markdown files with YAML frontmatter
- Location: `~/.augment/agents/` (user) or `.augment/agents/` (workspace)
- Each agent can have: `name`, `description`, `model`, `color`, and custom prompt
- Invoked via: `auggie --agent <agent-name> "<prompt>"`

## Hybrid Approach Design

### What We Keep (Python Orchestration)
- `ThreadPoolExecutor` for parallel task execution
- Task dependency detection and sequencing (FUNDAMENTAL vs INDEPENDENT)
- Checkpoint commits after each task
- Rate limit handling with retry logic
- Workflow state management
- TUI display and logging

### What We Add (Subagents)
- Specialized agent definitions for each workflow phase
- Per-agent model configuration (no more inline model overrides)
- Shareable, version-controlled agent prompts
- Cleaner prompt management (markdown files vs inline strings)

## Implementation Components

This spec is divided into the following sub-specifications:

| File | Purpose |
|------|---------|
| `SUBAGENT-INTEGRATION-SPEC-AGENTS.md` | Agent definition files to create |
| `SUBAGENT-INTEGRATION-SPEC-CODE.md` | Code changes to `AuggieClient` and workflow |
| `SUBAGENT-INTEGRATION-SPEC-CONFIG.md` | Configuration and settings updates |

## Success Criteria

1. **Agent Files Created**: All SPEC subagents defined in `.augment/agents/`
2. **AuggieClient Updated**: Supports `--agent` flag invocation
3. **Prompts Externalized**: Step 1-3 prompts moved to agent markdown files
4. **Inline Prompts Deleted**: Remove old inline prompt code from workflow steps
5. **Model Selection**: Per-agent model works correctly
6. **Tests Pass**: All existing tests pass, new tests added for subagent integration

## Non-Goals

- Do NOT use subagent's built-in parallel execution (keep Python orchestration)
- Do NOT remove `--dont-save-session` for task isolation
- Do NOT change the 3-step workflow structure
- Do NOT modify TUI or logging infrastructure
- Do NOT add fallback/backward compatibility - we require subagents

## Dependencies

- Auggie CLI version >= 0.12.0 (for subagent support)
- Update `REQUIRED_AUGGIE_VERSION` in `spec.sh` if needed

## File Structure After Implementation

```
.augment/
└── agents/
    ├── spec-planner.md          # Step 1: Plan generation
    ├── spec-tasklist.md         # Step 2: Task list creation  
    ├── spec-implementer.md      # Step 3: Task execution
    └── spec-reviewer.md         # Optional: Post-task review

spec/
└── integrations/
    └── auggie.py                # Updated AuggieClient with --agent support
```

## Implementation Order

1. Create agent definition files (`.augment/agents/*.md`)
2. Update `AuggieClient` to support `--agent` flag
3. Modify workflow steps to use named agents
4. **Delete inline prompt code** from workflow steps
5. Update configuration for agent-related settings
6. Add tests for subagent integration

