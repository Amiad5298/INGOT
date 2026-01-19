# Predictive Context Specification

## Overview

This specification describes enhancements to the SPEC workflow to reduce AI hallucinations and prevent file collisions during parallel execution by explicitly scoping files for each task.

## Problem Statement

### Current Architecture Issues

1. **Step 2 (Task List Generation)**: The `spec-tasklist` agent generates task descriptions but provides no explicit file targeting. Tasks are text-only descriptions.

2. **Step 3 (Execution)**: The `spec-implementer` agent must independently "discover" which files to modify using general `codebase-retrieval`. This leads to:
   - **Hallucinations**: Agent may misidentify or invent files that don't exist
   - **File Collisions**: Parallel tasks may accidentally touch the same files
   - **Wasted Tokens**: Repeated retrieval calls to find the same context
   - **Scope Creep**: Without explicit boundaries, agents may over-reach

### Current Flow

```
Step 2: spec-tasklist
┌──────────────────────────────────────────────────────┐
│ Input: Implementation Plan                           │
│ Output: Task descriptions only                       │
│         <!-- category: fundamental, order: 1 -->     │
│         - [ ] Add user authentication service        │
└──────────────────────────────────────────────────────┘
                         ↓
Step 3: spec-implementer
┌──────────────────────────────────────────────────────┐
│ Input: Task description + plan path                  │
│ Problem: Agent must guess which files to modify      │
│ Uses: codebase-retrieval to "find" relevant files    │
└──────────────────────────────────────────────────────┘
```

## Proposed Solution

### Enhanced Flow

```
Step 2: spec-tasklist (ENHANCED)
┌──────────────────────────────────────────────────────┐
│ Input: Implementation Plan                           │
│ Output: Task descriptions + TARGET FILES             │
│         <!-- category: fundamental, order: 1 -->     │
│         <!-- files: src/auth/service.py,             │
│                     src/auth/models.py,              │
│                     tests/test_auth.py -->           │
│         - [ ] Add user authentication service        │
└──────────────────────────────────────────────────────┘
                         ↓
Step 3: spec-implementer (ENHANCED)
┌──────────────────────────────────────────────────────┐
│ Input: Task description + TARGET FILES + plan path   │
│ Benefit: Explicit file scope in prompt               │
│ Future: Context restriction to only target files     │
└──────────────────────────────────────────────────────┘
```

---

## Data Structure Changes

### File: `spec/workflow/tasks.py`

#### Modify the `Task` dataclass

```python
@dataclass
class Task:
    """Represents a single task from the task list.

    Attributes:
        name: Task name/description
        status: Current task status
        line_number: Line number in the task list file
        indent_level: Indentation level (for nested tasks)
        parent: Parent task name (if nested)
        category: Task execution category (fundamental or independent)
        dependency_order: Order for fundamental tasks (sequential execution)
        group_id: Group identifier for parallel tasks
        target_files: List of files this task should modify (predictive context)
    """

    name: str
    status: TaskStatus = TaskStatus.PENDING
    line_number: int = 0
    indent_level: int = 0
    parent: Optional[str] = None
    # Fields for parallel execution
    category: TaskCategory = TaskCategory.FUNDAMENTAL
    dependency_order: int = 0  # For fundamental tasks ordering
    group_id: Optional[str] = None  # For grouping parallel tasks
    # Predictive context - explicit file targeting
    target_files: list[str] = field(default_factory=list)
```

#### Update `_parse_task_metadata()` function

Extend the metadata parser to extract the `files:` field from comments:

```python
def _parse_task_metadata(
    lines: list[str], task_line_num: int
) -> tuple[TaskCategory, int, Optional[str], list[str]]:
    """Parse task metadata from comment lines above task.

    Returns:
        Tuple of (category, order, group_id, target_files)
    """
    # ... existing logic ...
    target_files: list[str] = []

    # Parse files metadata - may be on separate line
    # <!-- files: path/to/file1.py, path/to/file2.py -->
    files_match = re.search(r'files:\s*([^>]+)', metadata_content)
    if files_match:
        files_str = files_match.group(1).strip()
        # Handle multi-line: remove --> if present
        files_str = files_str.rstrip(' ->')
        target_files = [f.strip() for f in files_str.split(',') if f.strip()]

    return category, order, group_id, target_files
```

#### Update `parse_task_list()` function

```python
# In the parsing loop:
category, order, group_id, target_files = _parse_task_metadata(lines, line_num)

task = Task(
    name=name.strip(),
    status=status,
    line_number=line_num + 1,
    indent_level=indent_level,
    category=category,
    dependency_order=order,
    group_id=group_id,
    target_files=target_files,  # NEW
)
```

---

## Step 2: Task List Agent Updates

### File: `.augment/agents/spec-tasklist.md`

Add file prediction requirements to the agent instructions:

```markdown
## Output Format

**IMPORTANT:** Output ONLY the task list as plain markdown text. Do NOT use any task management tools.

For each task, include a `files:` metadata comment listing the files that task should create or modify.

```markdown
# Task List: [TICKET-ID]

## Fundamental Tasks (Sequential)
<!-- category: fundamental, order: 1 -->
<!-- files: src/models/user.py, src/db/migrations/001_users.py -->
- [ ] Create User model and database migration

<!-- category: fundamental, order: 2 -->
<!-- files: src/services/auth_service.py, src/utils/password.py -->
- [ ] Implement authentication service with password hashing

## Independent Tasks (Parallel)
<!-- category: independent, group: api -->
<!-- files: src/api/endpoints/login.py, tests/api/test_login.py -->
- [ ] Create login API endpoint with tests

<!-- category: independent, group: api -->
<!-- files: src/api/endpoints/register.py, tests/api/test_register.py -->
- [ ] Create registration API endpoint with tests
```

### File Prediction Guidelines (Add to Agent)

```markdown
## File Prediction Requirements

For each task, you MUST include a `<!-- files: ... -->` comment listing ALL files the task will create or modify.

### Guidelines for File Prediction

1. **Be Specific**: Use full relative paths from repository root
2. **Include Tests**: If the task includes testing, list test files
3. **New Files**: Include files that will be created (they don't need to exist yet)
4. **Shared Files**: If a file is shared between tasks, use the Setup Task Pattern

### How to Predict Files

1. Read the implementation plan carefully for file references
2. Infer files from the task description:
   - "Add user model" → `src/models/user.py`
   - "Create login endpoint" → `src/api/login.py`
3. Follow project conventions visible in the plan
4. When uncertain, err on the side of inclusion

### Validation Rules

- Independent (parallel) tasks MUST have disjoint file sets
- If two independent tasks list the same file, you MUST:
  1. Extract shared file edits to a FUNDAMENTAL setup task, OR
  2. Merge the tasks into one
```

---

## Step 3: Execution Updates

### File: `spec/workflow/prompts.py`

#### Modify `build_task_prompt()` function

```python
def build_task_prompt(task: Task, plan_path: Path, *, is_parallel: bool = False) -> str:
    """Build a minimal prompt for task execution.

    Now includes explicit target files for predictive context.

    Args:
        task: Task to execute
        plan_path: Path to the implementation plan file
        is_parallel: Whether this task runs in parallel with others

    Returns:
        Minimal prompt string with task context and file targeting
    """
    parallel_mode = "YES" if is_parallel else "NO"

    # Base prompt with task name and parallel mode
    prompt = f"""Execute task: {task.name}

Parallel mode: {parallel_mode}"""

    # Add target files if available (predictive context)
    if task.target_files:
        files_list = "\n".join(f"  - {f}" for f in task.target_files)
        prompt += f"""

Target Files (focus your changes on these files):
{files_list}

IMPORTANT: Limit your modifications to the target files listed above.
If you believe additional files need changes, complete the listed files first,
then briefly note what else might need updating."""
    else:
        prompt += """

No specific target files provided. Use codebase-retrieval to identify relevant files."""

    # Add plan reference if file exists
    if plan_path.exists():
        prompt += f"""

Implementation plan: {plan_path}
Use codebase-retrieval to read relevant sections of the plan as needed."""
    else:
        prompt += """

Use codebase-retrieval to understand existing patterns before making changes."""

    # Add critical constraints reminder
    prompt += """

Do NOT commit, git add, or push any changes."""

    return prompt
```

---

## Spec-Implementer Agent Updates

### File: `.augment/agents/spec-implementer.md`

Add guidance for handling target files:

```markdown
## Target File Handling

When you receive a list of **Target Files** in your prompt:

1. **These are your PRIMARY scope** - focus your edits on these files
2. **Create new files** if they don't exist yet
3. **Read target files first** before making changes (if they exist)
4. **Stay within boundaries** - avoid modifying files outside the list unless:
   - A minor import statement is needed in a file you're already changing
   - An obvious bug prevents your target file from working

### File Boundaries in Parallel Mode

When `Parallel mode: YES`:
- Other AI agents are working simultaneously on DIFFERENT files
- Modifying files outside your Target Files list risks conflicts
- If you absolutely must touch an unlisted file, document it clearly in your summary

### No Target Files Provided

If no target files are listed:
- Use codebase-retrieval to understand the codebase structure
- Identify files based on the task description and plan
- Be conservative in your scope
```

---

## Future Enhancement: Context Restriction

### Investigation Required

Explore whether Auggie/subagent context can be restricted to ONLY the target files:

```
Current: spec-implementer has full codebase access via codebase-retrieval
Goal: Restrict retrieval results to only target files + their imports

Potential Approaches:
1. Auggie API parameter for context restriction (if available)
2. Pre-filter codebase-retrieval results in the prompt
3. Custom retrieval wrapper that enforces file boundaries
```

### Proposed API (If Auggie Supports)

```python
auggie_client.run_with_callback(
    prompt,
    agent=state.subagent_names["implementer"],
    context_filter=task.target_files,  # Hypothetical parameter
    dont_save_session=True,
)
```

### Fallback: Prompt-Based Enforcement

If API-level restriction isn't available, rely on strong prompt guidance:

```markdown
**STRICT FILE SCOPE**: You are restricted to the following files:
{target_files_list}

Do NOT use codebase-retrieval to find additional files.
Do NOT modify files outside this list.
If you encounter issues, report them rather than expanding scope.
```

---

## Validation Logic

### File: `spec/workflow/step2_tasklist.py`

Add validation after task list generation:

```python
def _validate_file_disjointness(tasks: list[Task]) -> list[str]:
    """Validate that independent tasks have disjoint file sets.

    Returns:
        List of warning messages for overlapping files
    """
    independent = [t for t in tasks if t.category == TaskCategory.INDEPENDENT]
    warnings = []

    # Build file -> tasks mapping
    file_to_tasks: dict[str, list[str]] = {}
    for task in independent:
        for file_path in task.target_files:
            if file_path not in file_to_tasks:
                file_to_tasks[file_path] = []
            file_to_tasks[file_path].append(task.name)

    # Check for conflicts
    for file_path, task_names in file_to_tasks.items():
        if len(task_names) > 1:
            warnings.append(
                f"File collision detected: '{file_path}' is targeted by multiple "
                f"independent tasks: {', '.join(task_names)}"
            )

    return warnings
```

### Integration Point

Call validation after parsing the generated task list:

```python
# In _generate_tasklist() after parsing:
tasks = parse_task_list(tasklist_content)
warnings = _validate_file_disjointness(tasks)
for warning in warnings:
    print_warning(warning)

if warnings:
    print_warning(
        "File collisions detected! Consider extracting shared files to a "
        "FUNDAMENTAL setup task or merging the conflicting tasks."
    )
```

---

## Implementation Tasks

### Phase 1: Data Structure Updates

- [ ] **Update `Task` dataclass**
  - File: `spec/workflow/tasks.py`
  - Add `target_files: list[str]` field with default empty list
  - Use `field(default_factory=list)` for mutable default

- [ ] **Update `_parse_task_metadata()` function**
  - File: `spec/workflow/tasks.py`
  - Parse `<!-- files: ... -->` metadata comments
  - Return tuple extended with `target_files`

- [ ] **Update `parse_task_list()` function**
  - File: `spec/workflow/tasks.py`
  - Pass `target_files` to Task constructor

### Phase 2: Task List Generation

- [ ] **Update spec-tasklist agent instructions**
  - File: `.augment/agents/spec-tasklist.md`
  - Add file prediction requirements
  - Update output format with `<!-- files: ... -->` examples
  - Add file prediction guidelines

### Phase 3: Task Execution

- [ ] **Update `build_task_prompt()` function**
  - File: `spec/workflow/prompts.py`
  - Include target files in prompt when available
  - Add scope enforcement language

- [ ] **Update spec-implementer agent instructions**
  - File: `.augment/agents/spec-implementer.md`
  - Add target file handling guidelines
  - Add parallel mode file boundary rules

### Phase 4: Validation

- [ ] **Add file disjointness validation**
  - File: `spec/workflow/step2_tasklist.py`
  - Create `_validate_file_disjointness()` function
  - Integrate validation after task list parsing
  - Warn on file collisions between independent tasks

### Phase 5: Testing

- [ ] **Add unit tests for metadata parsing**
  - Test parsing `<!-- files: ... -->` comments
  - Test multi-file lists with commas
  - Test empty file lists

- [ ] **Add unit tests for validation**
  - Test file collision detection
  - Test disjoint file sets pass validation

---

## Rollout Strategy

### Phase 1: Soft Launch (Prompt-Only)
- Update agent instructions to request file predictions
- Add target files to prompts
- No enforcement - agents can still use retrieval

### Phase 2: Validation
- Add file collision warnings
- Alert users to potential parallel execution issues
- Collect metrics on file prediction accuracy

### Phase 3: Enforcement (Future)
- Investigate context restriction capabilities
- Implement strict file boundaries if supported
- Add option to fail-fast on file boundary violations

---

## Success Metrics

1. **Reduced Hallucinations**: Track instances where agent references non-existent files
2. **Fewer File Collisions**: Monitor parallel execution conflicts
3. **Faster Execution**: Measure token usage reduction from targeted context
4. **Higher Success Rate**: Track task completion rates before/after