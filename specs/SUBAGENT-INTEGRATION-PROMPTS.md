# Implementation Prompts for AI Agents

Use these prompts to guide AI agents through implementing the subagent integration.
Each prompt is designed for a separate agent/session.

---

## Prompt 1: Create Agent Definition Files

```
Read the specification files in specs/SUBAGENT-INTEGRATION-SPEC*.md to understand the mission.

Your task: Create the subagent definition files.

1. Create directory: .augment/agents/

2. Create these 4 files using templates from specs/SUBAGENT-INTEGRATION-SPEC-TEMPLATES.md:
   - .augment/agents/spec-planner.md
   - .augment/agents/spec-tasklist.md
   - .augment/agents/spec-implementer.md
   - .augment/agents/spec-reviewer.md

3. For each agent file:
   - Copy the template from SUBAGENT-INTEGRATION-SPEC-TEMPLATES.md
   - Look at the CURRENT inline prompts in the spec/ code to extract relevant context
   - Ensure prompts are comprehensive and self-contained

4. Test each agent works: auggie --agent spec-planner "test"

Do not modify any Python code in this task.
```

---

## Prompt 2: Update AuggieClient

```
Read specs/SUBAGENT-INTEGRATION-SPEC-CODE.md for detailed requirements.

Your task: Update spec/integrations/auggie.py to support subagents.

1. Add subagent constants at module level:
   SPEC_AGENT_PLANNER = "spec-planner"
   SPEC_AGENT_TASKLIST = "spec-tasklist"  
   SPEC_AGENT_IMPLEMENTER = "spec-implementer"
   SPEC_AGENT_REVIEWER = "spec-reviewer"

2. Modify _build_command() to accept agent parameter:
   - Add agent: str parameter
   - Add --agent flag to command when agent is provided
   - Model comes from agent file, not from AuggieClient

3. Update all run methods to accept and pass agent parameter:
   - run()
   - run_print_with_output()
   - run_with_callback()

4. Update spec/integrations/__init__.py to export the new constants

5. Update any tests in the tests/ directory that test AuggieClient

Do not modify workflow files (step1, step2, step3) in this task.
```

---

## Prompt 3: Update Workflow Steps (Plan & Tasklist)

```
Read specs/SUBAGENT-INTEGRATION-SPEC-CODE.md for detailed requirements.

Your task: Update Step 1 and Step 2 to use subagents and DELETE inline prompts.

For spec/workflow/step1_plan.py:
1. Import SPEC_AGENT_PLANNER from spec/integrations/auggie
2. Replace inline prompt with minimal prompt that passes ticket context
3. Call auggie with agent=SPEC_AGENT_PLANNER
4. DELETE the old inline prompt building functions/strings
5. DELETE any fallback logic

For spec/workflow/step2_tasklist.py:
1. Import SPEC_AGENT_TASKLIST from spec/integrations/auggie
2. Replace inline prompt with minimal prompt that passes plan content
3. Call auggie with agent=SPEC_AGENT_TASKLIST
4. DELETE the old inline prompt building functions/strings
5. DELETE any fallback logic

Keep all other logic (file handling, parsing, state management) intact.
Update any affected tests.
```

---

## Prompt 4: Update Workflow Step 3 (Execution)

```
Read specs/SUBAGENT-INTEGRATION-SPEC-CODE.md for detailed requirements.

Your task: Update Step 3 to use subagents and DELETE inline prompts.

For spec/workflow/step3_execute.py:
1. Import SPEC_AGENT_IMPLEMENTER from spec/integrations/auggie
2. Replace inline prompt with minimal prompt that passes:
   - Task name
   - Reference plan content
3. Call auggie with agent=SPEC_AGENT_IMPLEMENTER
4. DELETE the old _build_task_prompt() function or inline prompt strings
5. DELETE any fallback logic

PRESERVE these critical features:
- ThreadPoolExecutor parallel execution
- Task dependency handling (FUNDAMENTAL vs INDEPENDENT)
- Checkpoint commits after tasks
- Retry logic and rate limiting
- Logging and TUI output
- --dont-save-session flag

Update any affected tests.
```

---

## Prompt 5: Configuration & Cleanup

```
Read specs/SUBAGENT-INTEGRATION-SPEC-CONFIG.md for requirements.

Your task: Add configuration for subagent names and clean up.

1. Update spec/config/settings.py:
   - Add subagent name settings (subagent_planner, subagent_tasklist, etc.)
   - These should be customizable strings

2. Update WorkflowState if needed to use configured agent names

3. Search the entire codebase for any remaining:
   - Inline prompt template strings that should be deleted
   - Fallback logic that should be removed
   - References to old prompt building functions

4. Run all tests and fix any failures

5. Verify the full workflow:
   - Create test ticket
   - Run SPEC with the ticket
   - Confirm agents are being invoked correctly
```

---

## Quick Single-Prompt Version

If you want to give it all to one agent:

```
Implement subagent integration for SPEC workflow.

Read ALL spec files in specs/SUBAGENT-INTEGRATION-SPEC*.md first.

Summary of work:
1. Create .augment/agents/ with 4 agent files (spec-planner, spec-tasklist, spec-implementer, spec-reviewer)
2. Update spec/integrations/auggie.py to support --agent flag
3. Update step1_plan.py to use spec-planner agent, DELETE inline prompts
4. Update step2_tasklist.py to use spec-tasklist agent, DELETE inline prompts
5. Update step3_execute.py to use spec-implementer agent, DELETE inline prompts
6. Update settings and exports

Key requirements:
- Subagents are REQUIRED, no fallback to inline prompts
- DELETE all inline prompt code after migrating to agents
- Preserve parallel execution, checkpoints, retry logic
- Model selection comes from agent files, not Python code
- Update tests for new behavior

Start by reading the spec files, then implement in order.
```

