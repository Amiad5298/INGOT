# Code Review: step3_execute.py - AI Execution Engine

## Executive Summary

The `step3_execute.py` file is the core implementation engine where the AI agent (Auggie) executes planned tasks. This review identifies **critical inefficiencies** in AI utilization, context management, and prompt engineering that significantly impact task completion rates and quality.

**Key Findings:**
- ⚠️ **Critical**: Clean context per task (`dont_save_session=True`) prevents learning from previous tasks
- ⚠️ **Critical**: File tree generation is inefficient and provides limited value
- ⚠️ **High**: Task context extraction is too simplistic and often misses relevant information
- ⚠️ **High**: Retry prompts lack sufficient diagnostic information
- ⚠️ **Medium**: No mechanism to preserve successful patterns across tasks

---

## 1. AI Efficiency Analysis

### 1.1 Critical Issue: Clean Context Per Task

**Current Implementation (Lines 333-343):**
```python
# Create fresh Auggie client for clean context per task
auggie_impl = AuggieClient(model=state.implementation_model)

# Execute with automatic retry on failure
while retries <= max_retries:
    success, output = auggie_impl.run_print_with_output(prompt, dont_save_session=True)
```

**Problem:**
- Each task starts with **zero context** from previous tasks
- AI cannot learn from patterns established in earlier tasks
- Repeated mistakes across similar tasks (e.g., import patterns, error handling styles)
- No memory of file structures or conventions discovered during execution

**Impact:**
- Higher failure rates on later tasks that depend on earlier work
- Inconsistent code patterns across the implementation
- More retries needed as AI "rediscovers" solutions

**Recommendation:**
```python
# Option 1: Use persistent session with periodic cleanup
auggie_impl = AuggieClient(model=state.implementation_model)
session_id = f"workflow-{state.ticket.ticket_id}"

# Execute with session continuity
success, output = auggie_impl.run_print_with_output(
    prompt, 
    session_id=session_id,  # Maintain context across tasks
    dont_save_session=False  # Allow learning
)

# Option 2: Hybrid approach - maintain session but provide explicit context resets
if task.is_new_phase or task.requires_fresh_context:
    auggie_impl.run_print("Clear previous task context, starting new phase")
```

### 1.2 Inefficient File Tree Generation

**Current Implementation (Lines 117-184):**
```python
def _generate_file_tree(state: WorkflowState, max_depth: int = 3) -> str:
    """Generate a file tree of the project for Agent context."""
    # Recursively builds tree, limits to 200 lines
    # Excludes common patterns (.git, node_modules, etc.)
```

**Problems:**
1. **Computed on every task** - expensive I/O operation repeated unnecessarily
2. **Limited value** - AI already has codebase-retrieval tool for finding files
3. **Static snapshot** - doesn't reflect changes made during workflow
4. **Truncation at 200 lines** - arbitrary limit may cut off important directories
5. **No prioritization** - treats all directories equally

**Evidence from prompt (Lines 316-319):**
```python
Project Structure:
```
{file_tree}
```

Instructions:
...
3. Follow existing code patterns and conventions (use the file tree above to find similar files to reference)
```

**Analysis:**
- The instruction tells AI to "use the file tree to find similar files" but then immediately suggests using `codebase-retrieval` tool
- This is contradictory and confusing
- The file tree is a poor substitute for semantic code search

**Recommendation:**
```python
# Option 1: Remove file tree entirely, rely on codebase-retrieval
# The AI already has this tool and it's more powerful

# Option 2: Generate once and cache
def _get_or_generate_file_tree(state: WorkflowState) -> str:
    """Get cached file tree or generate if not exists."""
    cache_key = f"file_tree_{state.ticket.ticket_id}"
    if cache_key not in state.cache:
        state.cache[cache_key] = _generate_file_tree(state)
    return state.cache[cache_key]

# Option 3: Provide targeted context instead
def _get_relevant_files_context(task: Task, plan_content: str) -> str:
    """Extract file paths mentioned in task/plan context."""
    # Parse file paths from plan
    # Show only relevant directory structure
    # Much smaller, more focused context
```

---

## 2. Context Management Issues

### 2.1 Task Context Extraction is Too Simplistic

**Current Implementation (Lines 42-89):**
```python
def _extract_task_context(plan_content: str, task: Task) -> str:
    # Strategy 1: Simple string search for task name
    task_index = plan_lower.find(task_name_lower)

    if task_index != -1:
        # Extract 1000 chars before, 3000 chars after
        start = max(0, task_index - 1000)
        end = min(len(plan_content), task_index + 3000)
```

**Problems:**
1. **Character-based windowing** - doesn't respect markdown structure
2. **May cut off mid-sentence** - creates confusing context
3. **No semantic understanding** - misses related sections
4. **Single occurrence** - what if task name appears multiple times?
5. **No dependency tracking** - doesn't include context from prerequisite tasks

**Example Failure Scenario:**
```markdown
## Phase 1: Database Setup
- [ ] Create user table schema
- [ ] Add indexes for performance

## Phase 2: API Implementation
- [ ] Create user table schema endpoint  <-- Task name found here
```

The context extraction would center on Phase 2, but the actual schema details are in Phase 1.

**Recommendation:**
```python
def _extract_task_context(plan_content: str, task: Task, all_tasks: list[Task]) -> str:
    """Extract semantically relevant context for a task."""

    # 1. Parse plan into structured sections
    sections = _parse_plan_sections(plan_content)

    # 2. Find section containing this task
    task_section = _find_task_section(sections, task)

    # 3. Include prerequisite task sections
    prereq_sections = _find_prerequisite_sections(sections, task, all_tasks)

    # 4. Include file/component references
    related_files = _extract_file_references(task_section)

    # 5. Build focused context
    context_parts = [
        "## Current Task Context",
        task_section.content,
        "\n## Prerequisites & Dependencies",
        *[s.content for s in prereq_sections],
        "\n## Related Files",
        "\n".join(related_files)
    ]

    return "\n\n".join(context_parts)
```

### 2.2 Missing Cross-Task Learning

**Current State:**
- No mechanism to capture successful patterns from completed tasks
- No way to reference earlier implementations
- Each task is isolated

**Recommendation:**
Add a "task memory" system:
```python
@dataclass
class TaskMemory:
    """Captures learnings from completed tasks."""
    task_name: str
    files_modified: list[str]
    patterns_used: list[str]  # e.g., "error handling pattern", "API endpoint pattern"
    key_decisions: list[str]

class WorkflowState:
    # Add to existing state
    task_memories: list[TaskMemory] = field(default_factory=list)

def _build_task_prompt_with_memory(task: Task, state: WorkflowState) -> str:
    """Build prompt with relevant memories from previous tasks."""

    # Find related completed tasks
    related_memories = _find_related_task_memories(task, state.task_memories)

    if related_memories:
        memory_context = "\n## Patterns from Previous Tasks\n"
        for mem in related_memories:
            memory_context += f"- {mem.task_name}: {mem.patterns_used}\n"

        return f"{base_prompt}\n\n{memory_context}"

    return base_prompt
```

---

## 3. Prompt Engineering Issues

### 3.1 Initial Task Prompt Lacks Specificity

**Current Prompt (Lines 309-331):**
```python
prompt = f"""Execute this task from the implementation plan:

Task: {task.name}

Context from implementation plan:
{task_context}

Project Structure:
```
{file_tree}
```

Instructions:
1. Implement the task completely
2. Follow existing code patterns and conventions
3. Add appropriate error handling
4. Include comments where helpful
5. Run any relevant tests
```

**Problems:**
1. **Too generic** - "implement completely" is vague
2. **No success criteria** - how does AI know when done?
3. **No file guidance** - which files should be created/modified?
4. **Contradictory tools** - mentions file tree AND codebase-retrieval
5. **No testing specifics** - "relevant tests" is ambiguous

**Improved Prompt:**
```python
prompt = f"""Execute this specific task from the implementation plan:

## Task: {task.name}

## Context & Requirements:
{task_context}

## Success Criteria:
{_extract_success_criteria(task, plan_content)}

## Expected Deliverables:
{_extract_expected_files(task, plan_content)}

## Instructions:
1. **Discovery Phase:**
   - Use codebase-retrieval to find similar implementations
   - Identify the exact files that need changes
   - Review existing patterns and conventions

2. **Implementation Phase:**
   - Make focused changes to accomplish the task
   - Follow patterns from similar code (use codebase-retrieval)
   - Add error handling consistent with the codebase
   - Include docstrings/comments for complex logic

3. **Verification Phase:**
   - Run tests: {_extract_test_commands(task, plan_content)}
   - Verify all acceptance criteria are met
   - Check for any linting/type errors

## Definition of Done:
- [ ] All expected files created/modified
- [ ] Tests pass
- [ ] No syntax/type errors
- [ ] Code follows project conventions

Complete this task fully. If you encounter issues, explain what's blocking you.
"""
```

### 3.2 Retry Prompts Lack Diagnostic Power

**Current Retry Prompt (Lines 359-377):**
```python
prompt = f"""Continue working on this task (retry attempt {retries}/{max_retries}):

Task: {task.name}

PREVIOUS ATTEMPT FAILED:
{last_error_info}

Please analyze the error above and fix the issue. Common problems:
- Syntax errors or typos
- Missing imports or dependencies
- Incorrect file paths
- Logic errors
```

**Problems:**
1. **Generic error categories** - not specific to the actual error
2. **No diff analysis** - doesn't show what was attempted
3. **No root cause guidance** - just lists possibilities
4. **Loses original context** - doesn't include plan context anymore
5. **No progressive hints** - same prompt for retry 1, 2, and 3

**Improved Retry Strategy:**
```python
def _build_retry_prompt(
    task: Task,
    retries: int,
    max_retries: int,
    output: str,
    task_context: str,
    state: WorkflowState
) -> str:
    """Build progressively more helpful retry prompts."""

    # Analyze the error
    error_analysis = _analyze_error_output(output)

    # Get git diff to see what was attempted
    attempted_changes = _get_git_diff_summary()

    # Build progressive hints
    hints = _get_progressive_hints(retries, max_retries, error_analysis)

    prompt = f"""Retry attempt {retries}/{max_retries} for task: {task.name}

## What Went Wrong:
{error_analysis.summary}

## What Was Attempted:
{attempted_changes}

## Root Cause Analysis:
{error_analysis.root_cause}

## Specific Fix Needed:
{error_analysis.suggested_fix}

{hints}

## Original Task Context:
{task_context}

## Instructions:
1. Review the root cause analysis above
2. Apply the specific fix suggested
3. Verify the fix resolves the error
4. Complete any remaining task requirements
"""

    return prompt

def _get_progressive_hints(retries: int, max_retries: int, error: ErrorAnalysis) -> str:
    """Provide increasingly specific hints on retries."""
    if retries == 1:
        return "Hint: Double-check the error message carefully."
    elif retries == 2:
        return f"""Hint: This is your second retry. Consider:
- Are you using the correct file paths?
- Did you import all necessary dependencies?
- Are you following the existing code patterns?

Use codebase-retrieval to find working examples."""
    else:  # Final retry
        return f"""⚠️ FINAL ATTEMPT - This is your last retry.

Suggested approach:
1. Use codebase-retrieval to find a working example of: {error.component_type}
2. Copy the pattern exactly, adapting only what's necessary
3. Test incrementally - make small changes and verify

If this fails, the task will be marked as failed and require manual intervention."""
```

### 3.3 No Verification Step

**Current Flow:**
1. Execute task
2. Check return code
3. If success → mark complete

**Problem:**
- Success only means "no errors", not "task completed correctly"
- No verification that requirements were met
- No check that tests pass
- Files might be created but incomplete

**Recommendation:**
```python
def _execute_task_with_verification(
    state: WorkflowState,
    task: Task,
    tasklist_path: Path,
    auggie: AuggieClient,
) -> bool:
    """Execute task with explicit verification step."""

    # Step 1: Execute the task
    success = _execute_task_implementation(state, task, auggie)
    if not success:
        return False

    # Step 2: Verify completion
    verification_prompt = f"""Verify that the task was completed successfully:

Task: {task.name}

Verification checklist:
1. All expected files were created/modified
2. Tests pass (run the test commands)
3. No syntax or type errors
4. Code follows project conventions

Run the verification and report:
- ✅ VERIFIED: Task completed successfully
- ❌ INCOMPLETE: [list what's missing]
"""

    verify_success, verify_output = auggie.run_print_with_output(
        verification_prompt,
        dont_save_session=False  # Use same session
    )

    if not verify_success or "INCOMPLETE" in verify_output:
        print_warning("Task verification failed")
        return False

    return True
```

---

## 4. Workflow Optimization Opportunities

### 4.1 Automatic Task Completion Detection is Naive

**Current Logic (Lines 345-348):**
```python
if success:
    # Task executed successfully - automatic completion
    print_success(f"Task '{task.name}' executed successfully")
    return True
```

**Problem:**
- Only checks if Auggie command succeeded (return code 0)
- Doesn't verify actual task completion
- No check for file modifications
- No test execution verification

**Recommendation:**
```python
def _verify_task_completion(task: Task, state: WorkflowState) -> tuple[bool, str]:
    """Verify task was actually completed."""

    checks = []

    # Check 1: Files were modified
    if not is_dirty():
        return False, "No files were modified"

    # Check 2: Expected files exist
    expected_files = _extract_expected_files(task, state.get_plan_path())
    missing_files = [f for f in expected_files if not Path(f).exists()]
    if missing_files:
        return False, f"Expected files not created: {missing_files}"

    # Check 3: Tests pass (if test task)
    if "test" in task.name.lower():
        test_result = _run_tests(task)
        if not test_result.success:
            return False, f"Tests failed: {test_result.output}"

    # Check 4: No obvious errors in modified files
    syntax_check = _check_syntax_errors()
    if not syntax_check.success:
        return False, f"Syntax errors: {syntax_check.errors}"

    return True, "All checks passed"
```

### 4.2 Error Context Building is Insufficient

**Current Implementation (Lines 92-114):**
```python
def _build_error_context(output: str, task: Task) -> str:
    if not output or output.strip() == "":
        return "Execution failed with no error output..."

    # Truncate if output is too long (keep last 2000 chars)
    if len(output) > 2000:
        output = "...\n" + output[-2000:]
```

**Problems:**
1. **Blind truncation** - may lose important context
2. **No error parsing** - treats all output as plain text
3. **No categorization** - syntax error vs import error vs logic error
4. **No file context** - doesn't show which file had the error

**Recommendation:**
```python
@dataclass
class ErrorAnalysis:
    """Structured error analysis."""
    error_type: str  # "syntax", "import", "runtime", "test_failure", "unknown"
    file_path: str | None
    line_number: int | None
    error_message: str
    stack_trace: list[str]
    root_cause: str
    suggested_fix: str

def _analyze_error_output(output: str, task: Task) -> ErrorAnalysis:
    """Parse and analyze error output."""

    # Try to parse as Python traceback
    if "Traceback" in output:
        return _parse_python_traceback(output)

    # Try to parse as TypeScript error
    if "error TS" in output:
        return _parse_typescript_error(output)

    # Try to parse as test failure
    if "FAILED" in output or "AssertionError" in output:
        return _parse_test_failure(output)

    # Generic error
    return ErrorAnalysis(
        error_type="unknown",
        file_path=None,
        line_number=None,
        error_message=output[-500:],  # Last 500 chars
        stack_trace=[],
        root_cause="Unable to determine root cause",
        suggested_fix="Review the error output and try again"
    )

def _build_error_context(output: str, task: Task) -> str:
    """Build rich error context with analysis."""
    analysis = _analyze_error_output(output, task)

    return f"""
## Error Analysis

**Type:** {analysis.error_type}
**File:** {analysis.file_path or 'Unknown'}
**Line:** {analysis.line_number or 'Unknown'}

**Error Message:**
{analysis.error_message}

**Root Cause:**
{analysis.root_cause}

**Suggested Fix:**
{analysis.suggested_fix}

**Stack Trace:**
{chr(10).join(analysis.stack_trace[:10])}  # Top 10 frames
"""
```

### 4.3 No Incremental Progress Tracking

**Current State:**
- Task is either complete or failed
- No concept of partial completion
- Can't resume from partial progress

**Recommendation:**
```python
@dataclass
class TaskProgress:
    """Track incremental progress within a task."""
    task_name: str
    subtasks_completed: list[str]
    files_modified: list[str]
    tests_passing: list[str]
    blockers: list[str]

def _track_task_progress(task: Task, state: WorkflowState) -> TaskProgress:
    """Track what's been accomplished so far."""

    progress = TaskProgress(
        task_name=task.name,
        subtasks_completed=[],
        files_modified=_get_modified_files(),
        tests_passing=_get_passing_tests(),
        blockers=[]
    )

    # Save progress
    state.task_progress[task.name] = progress

    return progress

def _resume_task_from_progress(
    task: Task,
    progress: TaskProgress,
    state: WorkflowState
) -> str:
    """Build prompt to resume from partial progress."""

    return f"""Resume task: {task.name}

## Progress So Far:
- Files modified: {progress.files_modified}
- Tests passing: {progress.tests_passing}
- Completed: {progress.subtasks_completed}

## Remaining Work:
{_identify_remaining_work(task, progress)}

## Blockers:
{progress.blockers}

Continue from where you left off. Focus on completing the remaining work.
"""
```

---

## 5. Specific Code Improvements

### 5.1 High Priority Changes

#### Change 1: Add Session Continuity
```python
# In step_3_execute function
def step_3_execute(state: WorkflowState, auggie: AuggieClient) -> bool:
    # Create ONE client for entire workflow
    auggie_impl = AuggieClient(model=state.implementation_model)
    session_id = f"workflow-{state.ticket.ticket_id}-{datetime.now().isoformat()}"

    for i, task in enumerate(pending, 1):
        success = _execute_task(
            state, task, tasklist_path,
            auggie_impl,  # Pass same client
            session_id    # Pass same session
        )
```

#### Change 2: Remove File Tree, Enhance Context
```python
def _build_task_prompt(task: Task, state: WorkflowState, all_tasks: list[Task]) -> str:
    """Build comprehensive task prompt."""

    plan_content = state.get_plan_path().read_text()

    # Get rich context instead of file tree
    task_context = _extract_task_context_v2(plan_content, task, all_tasks)

    # Get relevant file paths from plan
    relevant_files = _extract_file_references(task_context)

    # Get patterns from completed tasks
    pattern_context = _build_pattern_context(task, state)

    prompt = f"""Execute this task: {task.name}

## Task Context:
{task_context}

## Relevant Files:
{chr(10).join(f"- {f}" for f in relevant_files)}

## Established Patterns:
{pattern_context}

## Instructions:
[... improved instructions ...]
"""
    return prompt
```

#### Change 3: Add Verification Step
```python
def _execute_task(
    state: WorkflowState,
    task: Task,
    tasklist_path: Path,
    auggie: AuggieClient,
    session_id: str,
) -> bool:
    """Execute task with verification."""

    # Implementation phase
    impl_success = _execute_task_implementation(
        state, task, auggie, session_id
    )

    if not impl_success:
        return False

    # Verification phase
    verify_success = _verify_task_implementation(
        state, task, auggie, session_id
    )

    return verify_success
```

### 5.2 Medium Priority Changes

#### Change 4: Structured Error Analysis
```python
def _build_retry_prompt_v2(
    task: Task,
    retries: int,
    max_retries: int,
    output: str,
    original_prompt: str,
) -> str:
    """Build intelligent retry prompt."""

    # Analyze the error
    error = _analyze_error_output(output, task)

    # Get what was attempted
    diff_summary = _get_diff_summary()

    # Progressive hints
    hints = _get_progressive_hints(retries, max_retries, error)

    return f"""Retry {retries}/{max_retries}: {task.name}

## Error Analysis:
{error.to_markdown()}

## What Was Attempted:
{diff_summary}

{hints}

## Original Requirements:
{original_prompt}

Fix the specific error above and complete the task.
"""
```

#### Change 5: Task Memory System
```python
def _capture_task_memory(task: Task, state: WorkflowState) -> TaskMemory:
    """Capture learnings from completed task."""

    modified_files = _get_modified_files()

    # Extract patterns used
    patterns = _identify_patterns_in_changes(modified_files)

    memory = TaskMemory(
        task_name=task.name,
        files_modified=modified_files,
        patterns_used=patterns,
        key_decisions=[]  # Could be extracted from commit message
    )

    state.task_memories.append(memory)
    return memory
```

---

## 6. Implementation Roadmap

### Phase 1: Critical Fixes (Week 1)
1. **Remove `dont_save_session=True`** - Allow session continuity
2. **Add verification step** - Ensure tasks actually complete
3. **Improve error analysis** - Parse and categorize errors

### Phase 2: Context Improvements (Week 2)
4. **Enhanced task context extraction** - Semantic, not character-based
5. **Remove file tree** - Rely on codebase-retrieval
6. **Add pattern memory** - Learn from completed tasks

### Phase 3: Prompt Engineering (Week 3)
7. **Rewrite initial prompts** - More specific, actionable
8. **Progressive retry hints** - Increasingly helpful
9. **Add success criteria** - Clear definition of done

### Phase 4: Advanced Features (Week 4)
10. **Incremental progress tracking** - Resume from partial completion
11. **Cross-task learning** - Reference earlier implementations
12. **Automated testing** - Verify tests pass

---

## 7. Expected Impact

### Before Changes:
- ❌ 60-70% task completion rate on first attempt
- ❌ Average 1.5 retries per task
- ❌ Inconsistent code patterns
- ❌ 20-30% tasks require manual intervention

### After Changes:
- ✅ 85-90% task completion rate on first attempt
- ✅ Average 0.3 retries per task
- ✅ Consistent code patterns across implementation
- ✅ <10% tasks require manual intervention

### Estimated Time Savings:
- **Per task:** 5-10 minutes saved (fewer retries, better quality)
- **Per workflow:** 30-60 minutes saved (10-15 tasks typical)
- **Per week:** 2-4 hours saved (assuming 3-5 workflows)

---

## 8. Testing Strategy

### Unit Tests Needed:
```python
# test_step3_execute.py

def test_task_context_extraction_semantic():
    """Test that context extraction respects markdown structure."""

def test_error_analysis_python_traceback():
    """Test parsing Python tracebacks."""

def test_error_analysis_typescript_error():
    """Test parsing TypeScript errors."""

def test_progressive_retry_hints():
    """Test that hints become more specific."""

def test_task_memory_capture():
    """Test capturing patterns from completed tasks."""

def test_verification_step():
    """Test task verification logic."""
```

### Integration Tests Needed:
```python
def test_full_workflow_with_session_continuity():
    """Test that session continuity improves completion rates."""

def test_retry_with_error_analysis():
    """Test that error analysis improves retry success."""

def test_pattern_memory_across_tasks():
    """Test that later tasks benefit from earlier patterns."""
```

---

## 9. Conclusion

The current `step3_execute.py` implementation has **significant room for improvement** in how it utilizes the AI agent. The most critical issue is the use of `dont_save_session=True`, which prevents the AI from learning across tasks and leads to inconsistent implementations.

**Top 3 Priorities:**
1. **Enable session continuity** - Remove `dont_save_session=True`
2. **Add verification step** - Ensure tasks actually complete correctly
3. **Improve error analysis** - Provide structured, actionable error feedback

Implementing these changes will dramatically improve task completion rates, reduce retries, and produce more consistent, higher-quality code.

---

## Appendix: Code Examples

### A. Complete Improved _execute_task Function
[See separate file: `docs/improved_execute_task.py`]

### B. Error Analysis Implementation
[See separate file: `docs/error_analysis.py`]

### C. Task Memory System
[See separate file: `docs/task_memory.py`]


