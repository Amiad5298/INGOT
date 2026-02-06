# Implementation Plan: AMI-103 - Phase 1.0.1: Update Config Template for Claude Rename

**Ticket:** [AMI-103](https://linear.app/amiadspec/issue/AMI-103/phase-101-update-config-template-for-claude-rename)
**Status:** Done (verification complete; ready to close in Linear)
**Date:** 2026-02-02
**Labels:** MultiAgent
**Reference:** [Pluggable Multi-Agent Support.md](./Pluggable%20Multi-Agent%20Support.md) - Phase 1.0 follow-up

---

## Summary

This ticket addresses a follow-up task discovered during the code review of AMI-46 (Phase 1.0: Rename Claude Platform Enum). The goal is to update the configuration template file to reflect the `claude_desktop` → `claude` rename that was completed in AMI-46.

**Background:**
- AMI-46 renamed the enum member `AgentPlatform.CLAUDE_DESKTOP` → `AgentPlatform.CLAUDE`
- AMI-46 changed the enum value from `"claude_desktop"` → `"claude"`
- During AMI-46 code review, it was discovered that the template file still referenced `claude_desktop` in comments
- This template update was out of scope for AMI-46 (which focused on Python enum and tests)

**Why This Matters:**
- Configuration templates serve as reference documentation for users
- Template comments listing valid values should match actual enum values
- Inconsistency between template comments and code causes user confusion
- "Claude Desktop" is an outdated name; the CLI is now "Claude Code CLI" or simply "Claude"

**Scope:**
- Update `spec/config/templates/fetch_config.template` line 24 comment
- Verify no other template files reference `claude_desktop`

**Out of Scope:**
- This ticket does NOT change `AI_BACKEND` → `AI_BACKEND` in templates (tracked separately in the multi-backend migration, see parent spec Section "AI_BACKEND Removal Plan")
- This ticket only addresses the `claude_desktop` → `claude` comment update

**Reference:** Code review feedback from AMI-46 implementation

---

## Current Status Assessment

### ⚠️ Important: Template Already Updated

Upon investigation, the template file has **already been updated**. The current state of `spec/config/templates/fetch_config.template` line 24 is:

```
# AI backend: auggie, claude, cursor, aider, manual
```

This matches the target state specified in the Linear ticket. Verification:

```bash
$ rg -n 'claude_desktop' --glob '*.template' spec/
# Returns no matches (empty output)
```

**Conclusion:** The work described in AMI-103 has already been completed, likely during or shortly after AMI-46. This implementation plan documents the verification and acceptance criteria confirmation.

**Verified:** 2026-02-02 - Template confirmed updated; all acceptance criteria satisfied.

### Evidence of Completion

The change was made in commit `440fc046` on 2026-01-31:

```bash
$ git blame -L 24,24 spec/config/templates/fetch_config.template
440fc046 (Amiad5298 2026-01-31 19:55:13 +0200 24) # AI backend: auggie, claude, cursor, aider, manual
```

Additional verification (no `claude_desktop` references in source code):

```bash
$ rg -n 'claude_desktop' spec/ tests/
# Returns no matches (empty output)
```

---

## Technical Approach

### Files Requiring Changes

| File | Change Type | Description | Status |
|------|-------------|-------------|--------|
| `spec/config/templates/fetch_config.template` | Template | Update line 24 comment from `claude_desktop` to `claude` | ✅ **Already Done** |

### Target Change (Already Applied)

**File:** `spec/config/templates/fetch_config.template`

**Original Code (line 24, per AMI-103 ticket):**
```
# AI backend: auggie, claude_desktop, cursor, aider, manual
```

**Current Code (line 24):**
```
# AI backend: auggie, claude, cursor, aider, manual
```

The change has already been applied.

---

## Implementation Steps

### Phase 1: Verification (No Changes Required)

Since the template has already been updated, the implementation consists of verification only.

#### Step 1.1: Verify No `claude_desktop` References in Template Files

**Command:**
```bash
rg -n 'claude_desktop' --glob '*.template' spec/
# Expected: No matches (empty output)
```

**Result:** ✅ Verified - No matches found

#### Step 1.2: Verify Template Line 24 Content

**Command:**
```bash
sed -n '24p' spec/config/templates/fetch_config.template
```

**Expected Output:**
```
# AI backend: auggie, claude, cursor, aider, manual
```

**Result:** ✅ Verified - Line 24 matches expected content

---

## Acceptance Criteria

### From Linear Ticket AMI-103

| AC | Description | Verification Method | Status |
|----|-------------|---------------------|--------|
| **AC1** | Template file comment updated from `claude_desktop` to `claude` | Visual inspection of line 24 | ✅ Done |
| **AC2** | No other references to `claude_desktop` in template files | `rg -n 'claude_desktop' --glob '*.template' spec/` returns empty | ✅ Done |

### Verification Command (Per Ticket)

```bash
rg -n 'claude_desktop' --glob '*.template' spec/
# Should return no matches (empty output)
```

**Result:** ✅ Returns no matches

---

## Dependencies

### Upstream Dependencies (Must Be Complete First)

| Ticket | Component | Status | Description |
|--------|-----------|--------|-------------|
| [AMI-46](https://linear.app/amiadspec/issue/AMI-46/phase-10-rename-claude-platform-enum) | Phase 1.0: Rename Claude Platform Enum | ✅ Done | Primary rename completed (2026-01-31) |

### Downstream Dependents

None - this is a documentation/template update with no downstream dependencies.

### Related Tickets

| Ticket | Title | Relationship |
|--------|-------|--------------|
| [AMI-45](https://linear.app/amiadspec/issue/AMI-45) | Phase 1: Backend Infrastructure | Parent ticket |
| [AMI-46](https://linear.app/amiadspec/issue/AMI-46) | Phase 1.0: Rename Claude Platform Enum | Blocks this ticket (completed) |

---

## Summary of Changes

| File | Change | Lines Changed | Status |
|------|--------|---------------|--------|
| `spec/config/templates/fetch_config.template` | Comment updated from `claude_desktop` to `claude` | 1 line | ✅ Already Done |

---

## Estimated Effort

| Phase | Description | Estimate |
|-------|-------------|----------|
| Verification | Confirm template already updated | 0.01 day |
| **Total** | | **~0.01 day (trivial)** |

**Original Estimate (from ticket):** 0.05 day

---

## Testing Strategy

### Manual Verification Only

This change is a comment-only template update with no runtime impact. Verification is performed via grep commands documented in Implementation Steps.

No automated tests are required or affected by this change.

---

## Definition of Done

- [x] Template file line 24 updated from `claude_desktop` to `claude`
- [x] No other references to `claude_desktop` in template files
- [x] Verification command returns no matches

### Administrative Closeout (Out of Repo)

- [ ] Move AMI-103 ticket to Done in Linear

---

## Notes

### Template Already Updated

The template file was updated at some point after the AMI-46 code review but before this implementation plan was created. Possible scenarios:
1. Template was updated as part of AMI-46 itself (merged after code review)
2. Template was updated in a separate commit addressing the code review feedback
3. Template was proactively updated by another contributor

Since the acceptance criteria are already satisfied, this ticket can be marked as **Done** after verification.

### No Backward Compatibility Concerns

- Configuration templates are reference documentation
- Users copy templates and customize them
- Existing user configuration files are not affected
- The change is purely cosmetic (comment update, not value change)

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-02-02 | AI Assistant | Initial draft created - noted template already updated |
| 2026-02-02 | AI Assistant | Finalized status and DoD wording; clarified Linear closeout as manual |
| 2026-02-02 | AI Assistant | Added: commit evidence (440fc046), Out of Scope section, parent spec reference, clarified grep→rg commands, fixed Status/DoD inconsistency |
