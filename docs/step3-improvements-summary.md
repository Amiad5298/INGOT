# Step 3 Execute Improvements - Action Plan

## Quick Summary

The code review of `ai_workflow/workflow/step3_execute.py` identified **critical inefficiencies** in how the AI agent executes tasks. The most impactful issue is using `dont_save_session=True`, which prevents the AI from learning across tasks.

## Critical Issues Found

### 🔴 Priority 1: Session Continuity (CRITICAL)
**Problem:** Each task runs in a clean context with no memory of previous tasks.
**Impact:** Higher failure rates, inconsistent patterns, more retries needed.
**Fix:** Remove `dont_save_session=True` and use persistent sessions.

### 🔴 Priority 2: No Verification Step (CRITICAL)
**Problem:** Tasks marked complete based only on return code, not actual completion.
**Impact:** Incomplete implementations, missing tests, broken code.
**Fix:** Add explicit verification step after each task.

### 🟡 Priority 3: Poor Error Analysis (HIGH)
**Problem:** Generic error messages, no structured parsing, blind truncation.
**Impact:** Retry prompts lack actionable information, AI can't fix issues effectively.
**Fix:** Implement structured error parsing and analysis.

### 🟡 Priority 4: Weak Context Extraction (HIGH)
**Problem:** Character-based windowing, doesn't respect markdown structure.
**Impact:** AI gets incomplete or irrelevant context, misses dependencies.
**Fix:** Semantic context extraction based on plan structure.

### 🟢 Priority 5: Inefficient File Tree (MEDIUM)
**Problem:** Generated on every task, provides limited value, contradicts codebase-retrieval.
**Impact:** Wasted I/O, confusing instructions, token bloat.
**Fix:** Remove file tree, rely on codebase-retrieval tool.

## Implementation Roadmap

### Week 1: Critical Fixes
**Goal:** Improve task completion rate from 60-70% to 80-85%

1. **Day 1-2: Enable Session Continuity**
   - [ ] Remove `dont_save_session=True` from line 343
   - [ ] Add `session_id` parameter to `_execute_task`
   - [ ] Create session ID per workflow: `f"workflow-{ticket_id}"`
   - [ ] Test with 3-5 task workflow

2. **Day 3-4: Add Verification Step**
   - [ ] Implement `_verify_task_completion()` function
   - [ ] Check: files modified, expected files exist, tests pass
   - [ ] Add verification prompt after task execution
   - [ ] Test verification catches incomplete tasks

3. **Day 5: Error Analysis Foundation**
   - [ ] Implement `ErrorAnalysis` dataclass
   - [ ] Add `_analyze_error_output()` with Python traceback parsing
   - [ ] Update `_build_error_context()` to use structured analysis
   - [ ] Test with common error types

### Week 2: Context Improvements
**Goal:** Reduce retries from 1.5 to 0.5 per task

4. **Day 1-2: Semantic Context Extraction**
   - [ ] Implement `_parse_plan_sections()` to understand markdown structure
   - [ ] Update `_extract_task_context()` to use sections, not characters
   - [ ] Include prerequisite task context
   - [ ] Test with complex multi-phase plans

5. **Day 3: Remove File Tree**
   - [ ] Remove `_generate_file_tree()` function
   - [ ] Remove file tree from task prompt
   - [ ] Update instructions to emphasize codebase-retrieval
   - [ ] Verify AI still finds relevant files

6. **Day 4-5: Task Memory System**
   - [ ] Implement `TaskMemory` dataclass
   - [ ] Add `_capture_task_memory()` after successful tasks
   - [ ] Add `_build_pattern_context()` to include in prompts
   - [ ] Test pattern reuse across similar tasks

### Week 3: Prompt Engineering
**Goal:** Improve first-attempt success rate to 85-90%

7. **Day 1-2: Rewrite Initial Prompts**
   - [ ] Add explicit success criteria section
   - [ ] Add expected deliverables section
   - [ ] Structure as Discovery → Implementation → Verification
   - [ ] Add "Definition of Done" checklist

8. **Day 3-4: Progressive Retry Hints**
   - [ ] Implement `_get_progressive_hints()` function
   - [ ] Retry 1: Basic hint
   - [ ] Retry 2: Suggest codebase-retrieval
   - [ ] Retry 3: Detailed guidance, warn final attempt
   - [ ] Test retry success rates improve

9. **Day 5: Integration Testing**
   - [ ] Run full workflow tests with improvements
   - [ ] Measure completion rates, retry rates
   - [ ] Compare before/after metrics
   - [ ] Document findings

### Week 4: Polish & Advanced Features
**Goal:** Reduce manual intervention to <10%

10. **Day 1-2: Enhanced Error Parsing**
    - [ ] Add TypeScript error parsing
    - [ ] Add test failure parsing
    - [ ] Add import error parsing
    - [ ] Test with real error outputs

11. **Day 3-4: Incremental Progress Tracking**
    - [ ] Implement `TaskProgress` dataclass
    - [ ] Track files modified, tests passing
    - [ ] Enable resume from partial completion
    - [ ] Test with interrupted tasks

12. **Day 5: Documentation & Metrics**
    - [ ] Document all changes
    - [ ] Create before/after comparison
    - [ ] Measure time savings
    - [ ] Share results with team

## Quick Wins (Can Do Today)

### 1. Enable Session Continuity (30 minutes)
```python
# In step3_execute.py, line 333-343
# BEFORE:
auggie_impl = AuggieClient(model=state.implementation_model)
success, output = auggie_impl.run_print_with_output(prompt, dont_save_session=True)

# AFTER:
auggie_impl = AuggieClient(model=state.implementation_model)
session_id = f"workflow-{state.ticket.ticket_id}"
success, output = auggie_impl.run_print_with_output(
    prompt, 
    dont_save_session=False,
    session_id=session_id
)
```

### 2. Remove File Tree (15 minutes)
```python
# In step3_execute.py, line 306-319
# REMOVE these lines:
# file_tree = _generate_file_tree(state)
# Project Structure:
# ```
# {file_tree}
# ```

# UPDATE instructions to emphasize codebase-retrieval
```

### 3. Add Basic Verification (1 hour)
```python
# Add after line 345
if success:
    # Verify files were actually modified
    if not is_dirty():
        print_warning("Task succeeded but no files were modified")
        success = False
        output = "No files were modified. Task may be incomplete."
```

## Expected Results

### Before Improvements:
- ❌ 60-70% first-attempt success rate
- ❌ 1.5 average retries per task
- ❌ 20-30% tasks need manual intervention
- ❌ Inconsistent code patterns
- ❌ 45-60 minutes per workflow

### After Improvements:
- ✅ 85-90% first-attempt success rate
- ✅ 0.3 average retries per task
- ✅ <10% tasks need manual intervention
- ✅ Consistent code patterns
- ✅ 30-40 minutes per workflow

### Time Savings:
- **Per workflow:** 15-20 minutes saved
- **Per week (5 workflows):** 75-100 minutes saved
- **Per month:** 5-7 hours saved

## Testing Strategy

### Unit Tests to Add:
```python
# tests/test_step3_execute.py

def test_session_continuity_improves_completion():
    """Test that persistent sessions improve task completion."""
    
def test_verification_catches_incomplete_tasks():
    """Test that verification step catches incomplete work."""
    
def test_error_analysis_parses_python_traceback():
    """Test structured error parsing."""
    
def test_semantic_context_extraction():
    """Test context extraction respects markdown structure."""
    
def test_task_memory_captures_patterns():
    """Test that patterns are captured from completed tasks."""
```

### Integration Tests:
```python
def test_full_workflow_with_improvements():
    """Test complete workflow with all improvements."""
    # Should show higher completion rate, fewer retries
    
def test_cross_task_learning():
    """Test that later tasks benefit from earlier patterns."""
    # Task 2 should reference patterns from Task 1
```

## Metrics to Track

1. **Task Completion Rate:** % of tasks that complete on first attempt
2. **Average Retries:** Average number of retries per task
3. **Manual Intervention Rate:** % of tasks requiring manual fixes
4. **Time per Workflow:** Total time from start to finish
5. **Code Quality:** Consistency of patterns, test coverage

## Next Steps

1. **Review this document** with the team
2. **Prioritize quick wins** - can be done today
3. **Start Week 1 implementation** - critical fixes
4. **Set up metrics tracking** - measure improvements
5. **Schedule weekly check-ins** - review progress

## Resources

- **Full Code Review:** `docs/code-review-step3-execute.md`
- **Improved Implementation:** `docs/improved_execute_task.py`
- **Error Analysis:** `docs/error_analysis.py`
- **Task Memory System:** `docs/task_memory.py`

## Questions?

Contact the AI Workflow team or open an issue in the repository.

