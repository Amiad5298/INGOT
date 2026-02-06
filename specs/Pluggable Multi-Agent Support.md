# Pluggable Multi-AI-Backend Support — Revised Implementation Plan

> **Version:** 3.3 (All Gaps Closed)
> **Status:** ✅ Ready for Execution
> **Last Updated:** 2026-01-30

---

## Review Status: All Gaps Closed

This specification has been reviewed and updated to address all identified gaps:

| # | Gap | Resolution |
|---|-----|------------|
| 1 | **Phase 0 Missing** | ✅ Added Phase 0 (Baseline Behavior Tests) with full test implementation |
| 2 | **`run_streaming()` Return Type Inconsistency** | ✅ Fixed `FakeBackend.run_streaming()` to return `tuple[bool, str]` per Final Decision #15 |
| 3 | **Missing ClaudeClient Methods** | ✅ Added `run_print_with_output()` and `run_print_quiet()` implementations |
| 4 | **Missing CursorClient Methods** | ✅ Added `run_print_with_output()` and `run_print_quiet()` implementations |
| 5 | **Timeout Implementation Unclear** | ✅ Added `_run_streaming_with_timeout()` method to BaseBackend with full watchdog implementation |
| 6 | **Thread Safety Not Exemplified** | ✅ Added `ThreadSafeTaskBuffer` example for parallel execution in Step 3 |
| 7 | **`prompt_user_for_clarification()` Undefined** | ✅ Added implementation note and example code for TUI function |
| 8 | **settings.py Import Verification Missing** | ✅ Added grep commands to verify imports from new `spec.workflow.constants` location |
| 9 | **Documentation URLs Unverified** | ✅ Added pre-release verification checklist for vendor URLs |

**Note:** This is a new system implementation. No backward compatibility or rollback mechanisms are required.

---

## Audit & Verified Touchpoints

This section provides the verified inventory of current codebase state, ensuring all references in this plan are accurate.

### A. Verified Inventory Table: AuggieClient() Instantiation Points

| # | File | Function | Current Call Pattern | Intended Replacement |
|---|------|----------|---------------------|----------------------|
| 1 | `spec/workflow/step1_plan.py:92` | `_generate_plan_with_tui()` | `auggie_client = AuggieClient()` followed by `auggie_client.run_with_callback(...)` | Use injected `backend: AIBackend` |
| 2 | `spec/workflow/step1_plan.py:144` | `step_1_create_plan()` | Function signature accepts `auggie: AuggieClient` param | Change param to `backend: AIBackend` |
| 3 | `spec/workflow/step1_plan.py:215` | `_run_clarification()` | Function accepts `auggie: AuggieClient`, calls `auggie.run_print()` on line 296 | **⚠️ REFACTOR: `run_print()` → TUI + `run_streaming()`** |
| 4 | `spec/workflow/step2_tasklist.py:27` | `step_2_create_tasklist()` | Function signature accepts `auggie: AuggieClient` param | Change param to `backend: AIBackend` |
| 5 | `spec/workflow/step2_tasklist.py:305` | `_generate_tasklist()` | `auggie_client = AuggieClient()` then `auggie_client.run_print_with_output(...)` | Use injected backend or factory |
| 6 | `spec/workflow/step2_tasklist.py:447` | `_refine_tasklist()` (inferred) | `auggie_client = AuggieClient()` then `auggie_client.run_print_with_output(...)` | Use injected backend or factory |
| 7 | `spec/workflow/step3_execute.py:816` | `_execute_task()` | `auggie_client = AuggieClient()` then `auggie_client.run_print_with_output(...)` | Create fresh backend via factory per-task |
| 8 | `spec/workflow/step3_execute.py:864` | `_execute_task_with_callback()` | `auggie_client = AuggieClient()` then `auggie_client.run_with_callback(...)` | Create fresh backend via factory per-task |
| 9 | `spec/workflow/step3_execute.py:1024` | `_run_post_implementation_tests()` | `auggie_client = AuggieClient()` then `auggie_client.run_with_callback(...)` | Use injected backend |
| 10 | `spec/workflow/step4_update_docs.py:604` | `step_4_update_docs()` | `client = auggie_client or AuggieClient()` | Use injected backend, **delete `AuggieClientProtocol`** (line 517) |
| 11 | `spec/workflow/autofix.py:62` | `run_auto_fix()` | `auggie_client = AuggieClient()` then `auggie_client.run_print_with_output(...)` | Use injected backend or factory |
| 12 | `spec/workflow/review.py:326` | `run_phase_review()` | `auggie_client = AuggieClient()` then `auggie_client.run_print_with_output(...)` | Use injected backend |
| 13 | `spec/workflow/review.py:211` | `_run_rereview_after_fix()` | Function accepts `auggie_client: AuggieClient` param | Change param to `backend: AIBackend` |
| 14 | `spec/workflow/conflict_detection.py:49` | `detect_context_conflict()` | Function accepts `auggie: AuggieClient` param | Change param to `backend: AIBackend` |

### B. Verified run_print / run_with_callback Usage Inventory

**Methods Used in Workflow (grep verified):**

| Method | Location | Count | Notes |
|--------|----------|-------|-------|
| `run_with_callback()` | `step1_plan.py:95`, `step3_execute.py:871`, `step3_execute.py:1028` | 3 | Streaming with callback - **keep as primary pattern** |
| `run_print_with_output()` | `step2_tasklist.py:308`, `step4_update_docs.py`, `autofix.py:65`, `review.py:328` | 4+ | Returns `(bool, str)` - maps to `backend.run_print_with_output()` |
| `run_print_quiet()` | Fetchers only (`auggie_fetcher.py`) | 1 | Returns `str` - maps to `backend.run_print_quiet()` |
| `run_print()` | **`step1_plan.py:296` ONLY** | 1 | **⚠️ INTERACTIVE - MUST REFACTOR** |

**Critical Finding:** `run_print()` (interactive mode) is used in exactly ONE location: `_run_clarification()` in `step1_plan.py:296`. This must be refactored to collect user input via TUI first, then call `backend.run_streaming()`.

**Verification Command (run before Phase 2):**
```bash
# Verify run_print() is only used in one location (excluding run_print_with_output, run_print_quiet)
grep -rn "\.run_print(" --include="*.py" spec/ | grep -v "run_print_"
# Expected output: spec/workflow/step1_plan.py:296:    success = auggie.run_print(...)
```

### C. AI_BACKEND Legacy Config — Verified Existing References

**Contrary to v3.1 assertion, AI_BACKEND DOES exist in the codebase. Full removal plan included below.**

| Category | File | Line | Current State | Required Action |
|----------|------|------|---------------|-----------------|
| SpecSettings field | `spec/config/settings.py:95` | `ai_backend: str = "auggie"` | Legacy field | **REMOVE or RENAME to `ai_backend`** |
| Config key mapping | `spec/config/settings.py:128` | `"AI_BACKEND": "ai_backend"` | Maps env var | **REMOVE from mapping** |
| ConfigManager parse | `spec/config/manager.py:580` | `platform_str = self._raw_values.get("AI_BACKEND")` | Reads legacy key | **CHANGE to `AI_BACKEND`** |
| Parser function | `spec/config/fetch_config.py:101` | `def parse_ai_backend(...)` | Used by manager | **RENAME to `parse_ai_backend()` or deprecate with alias** |
| Config template | `spec/config/templates/fetch_config.template:24-25` | `AI_BACKEND=auggie` and `claude_desktop` reference | Template file | **UPDATE to `AI_BACKEND=auggie` and `claude`** |
| Tests | `tests/test_config_manager.py` (22+ refs) | Various | Tests legacy behavior | **UPDATE all tests** |
| Documentation | `docs/platform-configuration.md:490` | Example shows `AI_BACKEND=auggie` | Docs reference | **UPDATE to `AI_BACKEND=auggie`** |
| Spec docs | `specs/AMI-33-implementation-plan.md`, `specs/AMI-39-implementation-plan.md` | Various | Plan references | **UPDATE to `AI_BACKEND`** |

### D. Verified Grep Checklist

Run these commands to verify migration progress:

```bash
# BEFORE migration - these WILL return matches:
grep -rn "AI_BACKEND" --include="*.py" spec/
# Expected: ~6 matches in settings.py, manager.py, fetch_config.py

grep -rn "ai_backend" --include="*.py" spec/config/
# Expected: ~4 matches

# AFTER migration - these should return 0 matches:
grep -rn "AI_BACKEND" --include="*.py" spec/
grep -rn 'ai_backend.*=.*"auggie"' --include="*.py" spec/

# These are ALLOWED (enum name, not config key):
grep -rn "AgentPlatform" --include="*.py" spec/
# Expected: Many matches (this is the enum, keep it)

# AI_BACKEND should be the only config key:
grep -rn "AI_BACKEND" --include="*.py" spec/
# Expected: Matches in backend_resolver.py, cli.py, onboarding

# Verify SPECFLOW_AGENT_* imports are from new location:
# AFTER migration - these should return 0 matches:
grep -rn "from spec.integrations.auggie import SPECFLOW_AGENT" --include="*.py" .
# Expected: 0 matches (all imports moved to spec.workflow.constants)

# Verify settings.py imports from new location:
grep -n "from spec.workflow.constants import" spec/config/settings.py
# Expected: 1 match showing SPECFLOW_AGENT_* import

# Verify state.py imports from new location:
grep -n "from spec.workflow.constants import" spec/workflow/state.py
# Expected: 1 match showing SPECFLOW_AGENT_* import
```

### E. SPECFLOW_AGENT Constants Import Sites

**All locations that import subagent constants from `spec/integrations/auggie.py`:**

| File | Current Import | Required Change |
|------|----------------|-----------------|
| `spec/workflow/state.py:12-19` | `from spec.integrations.auggie import SPECFLOW_AGENT_*` | Change to `from spec.workflow.constants import SPECFLOW_AGENT_*` |
| `spec/config/settings.py:18-23` | `from spec.integrations.auggie import SPECFLOW_AGENT_*` | Change to `from spec.workflow.constants import SPECFLOW_AGENT_*` |
| `spec/integrations/__init__.py:11-14` | Re-exports from `auggie` | Change to re-export from `spec.workflow.constants` |
| `spec/integrations/agents.py:18-20` | `from spec.integrations.auggie import SPECFLOW_AGENT_*` | Change to `from spec.workflow.constants import SPECFLOW_AGENT_*` |
| `tests/test_auggie.py:7-11` | `from spec.integrations.auggie import SPECFLOW_AGENT_*` | Change to `from spec.workflow.constants import SPECFLOW_AGENT_*` |

---

## Final Decisions

This section summarizes the architectural decisions that govern this implementation plan:

1. **Configuration Precedence**
   - CLI flag `--backend` has highest precedence (one-run override)
   - Otherwise use persisted config value `AI_BACKEND` (stored by ConfigManager / onboarding)
   - If neither is set, raise an error and prompt the user to configure a backend (no default)

2. **Configuration Terminology — With Legacy Migration**
   - `AI_BACKEND` is the **only** configuration key for backend selection (target state)
   - **Legacy `AI_BACKEND` exists and must be removed** — see "AI_BACKEND Removal Plan" section
   - Onboarding writes only `AI_BACKEND`
    - **Claude naming:** CLI/config uses `claude` (canonical). `AgentPlatform.CLAUDE` has value `"claude"` (rename from the current `CLAUDE_DESKTOP`).
   - `settings.ai_backend` replaces `settings.ai_backend` (single source of truth)
   - **No default backend**: if neither CLI `--backend` nor `AI_BACKEND` config is set, fail fast with `BackendNotConfiguredError`

3. **WorkflowState Stores Only Enum, Not Backend Instances**
   - `WorkflowState.backend_platform: AgentPlatform` stores the enum
   - Optionally `WorkflowState.backend_model: str` for logging
   - `backend: AIBackend` instances are passed explicitly through step functions and internal helpers

4. **Non-Interactive Execution Mode (STRICT ENFORCEMENT)**
   - All backends execute in non-interactive (streaming/print) mode for deterministic behavior
   - User input is collected via the TUI, then included in prompts sent to the backend
   - **The `AIBackend` protocol does NOT include `run_print()` (interactive mode)**
   - Any legacy `run_print()` usage MUST be refactored to:
     1. Collect user input via TUI functions first
     2. Call `backend.run_streaming()` with the input appended to the prompt
   - This enforces the architectural decision that SPEC owns interactive UX, not backends

5. **Parallel Execution Capability**
   - Each backend exposes `supports_parallel: bool` via `supports_parallel_execution()`
   - If `False`, Step 3 falls back to sequential execution (or respects `--no-parallel`)

6. **Timeout Enforcement**
   - The `AIBackend` protocol includes `timeout_seconds` parameter
   - Each CLI client wrapper implements streaming-safe timeout via watchdog thread with process terminate/kill

7. **Rate Limit Error Consistency**
   - Single generic exception type: `BackendRateLimitError`
   - Carries `backend_name` and `output` fields for context

8. **Subagent Frontmatter Handling**
   - YAML frontmatter in `.augment/agents/*.md` is parsed into `(metadata, body)`
   - For non-Auggie backends: ignore unsupported metadata fields; support `model` field when possible
   - Model selection precedence: (a) explicit per-call override → (b) subagent frontmatter `model` → (c) global config `default_model`
   - If a backend cannot accept a model flag, it safely ignores the model value
   - **Shared parsing logic lives in `BaseBackend._parse_subagent_prompt()`** to avoid duplication

9. **Testing Strategy**
   - Unit tests use mocks/fakes for backends (no external CLI required)
   - Integration tests are optional and gated behind `SPEC_INTEGRATION_TESTS=1` environment variable

10. **Cursor Parallel Execution**
    - `CursorBackend.supports_parallel` defaults to `True` (verified: Cursor CLI supports concurrent execution via worktrees/separate terminals)
    - Stability mechanism (startup delay or retry logic) handles potential race conditions during simultaneous agent spawning
    - Use detection logic in `CursorClient._detect_cli_command()` to handle `cursor` vs `agent` executable names

11. **Cold-Start Timeouts**
    - Onboarding smoke test timeout: 60 seconds
    - First real ticket fetch timeout: 120 seconds (generous for model loading/authentication)
    - Subsequent calls default timeout: 60 seconds
    - Display user-facing message during first run: "First run may take a moment while the AI backend initializes..."

12. **Decoupled Subagent Constants**
    - Subagent name constants (e.g., `SPECFLOW_AGENT_PLANNER`) are moved from `spec/integrations/auggie.py` to `spec/workflow/constants.py`
    - This breaks the conceptual coupling between workflow code and the Auggie module
    - All imports of these constants must be updated to use the new location

13. **BaseBackend Abstract Class**
    - A `BaseBackend` abstract class implements shared logic across all backends
    - Shared functionality includes: `_parse_subagent_prompt()`, default `close()`, `supports_parallel_execution()`
    - Concrete backends (`AuggieBackend`, `ClaudeBackend`, `CursorBackend`) extend `BaseBackend`
    - This reduces code duplication and ensures consistent behavior

14. **AI_BACKEND Legacy Removal (REQUIRED)**
    - **Contrary to v3.1 assertion**, `AI_BACKEND` exists in the current codebase
    - This is **legacy code that must be removed** before the new backend system is complete
    - All references must be migrated to `AI_BACKEND`
    - See "AI_BACKEND Removal Plan" section below for complete migration steps

15. **run_streaming Semantics (RESOLVED)**
    - `run_streaming()` returns `tuple[bool, str]` (not a generator)
    - All backends implement this consistently
    - For streaming use cases with callbacks, use `run_with_callback()` instead
    - `FakeBackend` in tests must also return `tuple[bool, str]` (not a generator)

16. **Thread Safety for Parallel Execution**
    - `output_callback` functions passed to `run_with_callback()` must be thread-safe when Step 3 runs in parallel
    - Worker threads must not write to shared `WorkflowState` without synchronization
    - Each parallel task uses its own `TaskLogBuffer` instance for safe output collection

17. **Backend Validation at Runner Entry**
    - `runner.py` must validate that `state.backend_platform` is not `None` before creating backends
    - `step3_execute.py` must fail fast with clear error if `state.backend_platform is None`
    - This prevents cryptic errors deep in execution

18. **Timeout Enforcement Responsibility**
    - AuggieClient currently does NOT support timeouts
    - **Decision:** AuggieBackend wraps AuggieClient and implements timeouts using the streaming-safe watchdog pattern
    - All backends use the same `_run_streaming_with_timeout()` helper for consistency
    - Timeout is enforced at the Backend layer, not the Client layer

19. **Cursor Backend Parameter Consistency**
    - Semantic name: `dont_save_session` (Backend protocol parameter)
    - Maps to: `no_save=True` (CursorClient internal parameter)
    - Maps to: `--no-save` (Cursor CLI flag)
    - `run_with_callback` always uses `--print` flag (streaming mode always enabled)

---

### AI_BACKEND Removal Plan

**Current State (Verified):**
The legacy `AI_BACKEND` config key exists in multiple locations. This section provides the complete removal plan.

#### Step 1: Update SpecSettings

**File:** `spec/config/settings.py`

```python
# REMOVE (line 95):
ai_backend: str = "auggie"

# ADD:
ai_backend: str = ""  # No default - must be configured

# REMOVE from CONFIG_KEY_MAPPING (line 128):
"AI_BACKEND": "ai_backend",

# ADD to CONFIG_KEY_MAPPING:
"AI_BACKEND": "ai_backend",
```

#### Step 2: Update ConfigManager

**File:** `spec/config/manager.py`

```python
# CHANGE (line 580):
# FROM:
platform_str = self._raw_values.get("AI_BACKEND")

# TO:
platform_str = self._raw_values.get("AI_BACKEND")

# UPDATE context string (line 593):
# FROM:
context="AI_BACKEND",

# TO:
context="AI_BACKEND",
```

#### Step 3: Rename parse_ai_backend (Optional Alias)

**File:** `spec/config/fetch_config.py`

```python
# Keep parse_ai_backend() for backward compatibility with callers
# but update the context default:

def parse_ai_backend(
    value: str | None,
    default: AgentPlatform | None = None,
    context: str = "AI_BACKEND",  # Changed from "AI_BACKEND"
) -> AgentPlatform:
    # IMPORTANT: No default backend.
    # If value is missing/empty and default is None, raise ConfigValidationError.
    if value is None or value.strip() == "":
        if default is None:
            context_msg = f" in {context}" if context else ""
            valid_values = ", ".join(e.value for e in AgentPlatform)
            raise ConfigValidationError(
                f"Missing AI backend{context_msg}. Allowed values: {valid_values}"
            )
        return default

    value_lower = value.strip().lower()
    try:
        return AgentPlatform(value_lower)
    except ValueError:
        context_msg = f" in {context}" if context else ""
        valid_values = ", ".join(e.value for e in AgentPlatform)
        raise ConfigValidationError(
            f"Invalid AI backend '{value}'{context_msg}. Allowed values: {valid_values}"
        ) from None

# Add alias for clarity (preferred name in new code):
parse_ai_backend = parse_ai_backend
```

#### Step 4: Update Tests

**File:** `tests/test_config_manager.py`

Replace all occurrences of:
- `'AI_BACKEND="auggie"'` → `'AI_BACKEND="auggie"'`
- `"AI_BACKEND=cursor"` → `"AI_BACKEND=cursor"`
- Test method names referencing `ai_backend` → `ai_backend`

Affected test methods (22+ occurrences):
- `test_ai_backend_values` → `test_ai_backend_values`
- `test_ai_backend_from_string` → `test_ai_backend_from_string`
- `test_ai_backend_invalid_value` → `test_ai_backend_invalid_value`
- `test_validate_fetch_config_strict_raises_on_invalid_ai_backend` → `test_validate_fetch_config_strict_raises_on_invalid_ai_backend`

#### Step 5: Update Documentation

**File:** `docs/platform-configuration.md`

```diff
- AI_BACKEND=auggie
+ AI_BACKEND=auggie
```

**Files:** `specs/AMI-33-implementation-plan.md`, `specs/AMI-39-implementation-plan.md`

Update all references to use `AI_BACKEND` instead of `AI_BACKEND`.

#### Step 6: Add CI Guard

**File:** `.github/workflows/lint.yml` (or equivalent)

```yaml
- name: Verify no AI_BACKEND references in source
  run: |
    # Check for AI_BACKEND in Python source (excluding tests temporarily)
    if grep -rn "AI_BACKEND" --include="*.py" spec/; then
      echo "ERROR: Found AI_BACKEND reference in spec/. Use AI_BACKEND instead."
      exit 1
    fi
    # Check for ai_backend as config field (excluding AgentPlatform enum)
    if grep -rn 'ai_backend.*=.*"' --include="*.py" spec/; then
      echo "ERROR: Found ai_backend field in spec/. Use ai_backend instead."
      exit 1
    fi
```

#### Verification Commands

```bash
# After migration, these should return 0 matches in spec/:
grep -rn "AI_BACKEND" --include="*.py" spec/
grep -rn 'ai_backend:' --include="*.py" spec/config/settings.py

# These are ALLOWED (enum name):
grep -rn "AgentPlatform" --include="*.py" spec/  # Enum references OK

# This should show AI_BACKEND usage:
grep -rn "AI_BACKEND" --include="*.py" spec/
```

**Source of Truth for Backend Configuration:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Backend Configuration Flow                        │
│                                                                      │
│  CLI flag --backend (highest precedence)                            │
│       │                                                              │
│       ▼                                                              │
│  Persisted config AI_BACKEND (~/.spec-config or project config)     │
│       │                                                              │
│       ▼                                                              │
│  No default → BackendNotConfiguredError (fail fast)                 │
│                                                                      │
│  ⚠️  AI_BACKEND is REMOVED - only AI_BACKEND exists             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Executive Summary

### What Changes

This plan extends SPEC to support **multiple AI backends** (Auggie, Claude Code CLI, Cursor CLI) through a unified abstraction layer. The refactoring:

1. **Introduces `AIBackend` protocol** — A thin abstraction over CLI execution
2. **Consolidates backend selection** — Single source of truth via `resolve_backend_platform()`
3. **Eliminates direct `AuggieClient` instantiation** — All workflow steps receive backend via dependency injection
4. **Adds generic error handling** — `BackendRateLimitError` replaces `AuggieRateLimitError`
5. **Implements timeout enforcement** — Subprocess-based backends support configurable timeouts
6. **Updates ticket service** — Platform-aware fetcher selection based on resolved backend

### Why

- **User choice**: Users may prefer Claude Code or Cursor over Auggie
- **Vendor independence**: Reduces coupling to a single AI provider
- **Testability**: Protocol-based design enables mocking for unit tests
- **Maintainability**: Centralized backend logic simplifies future additions

### Behavioral Guarantee

> **The workflow behavior remains identical.** Only the underlying AI execution mechanism changes. All prompts, MCP integrations, workflow orchestration, TUI, and task parsing remain unchanged.

---

## 2. Assumptions and Constraints

### Assumptions

1. **All target backends support MCP integrations** for Jira, Linear, and GitHub
2. **All backends can run in non-interactive print mode** with streaming output
3. **All backends support session isolation** (no context leak between runs)
4. **Claude Code CLI and Cursor CLI** have similar command-line interfaces to Auggie
5. **Subagent prompts are backend-agnostic** — no backend-specific prompt files needed
6. **Backend CLIs are installed system-wide** and available in PATH
7. **Rate limit patterns are identifiable** in CLI output text for each backend

### Constraints

1. **No "ask the agent if MCP works" verification** — MCP verified on first real use only
2. **WorkflowState stores only `backend_platform: AgentPlatform` enum** — never backend instances
3. **Backend instances are created fresh per-task** in Step 3 parallel execution
4. **Single source of truth for backend selection** — `resolve_backend_platform()` function
5. **Unified configuration flow** — `AI_BACKEND` is the persisted key; `settings.ai_backend` is derived (not a competing source)
6. **SPEC owns interactive UX** — backends are non-interactive (streaming/print only)
7. **Timeout enforcement via watchdog** — each CLI wrapper uses streaming-safe watchdog pattern with process terminate/kill

### Step 3 Parallel Execution Model

**SPEC orchestrates all concurrency.** The current Step 3 implementation spawns multiple backend invocations in parallel using `ThreadPoolExecutor` and aggregates results. The key points:

1. **SPEC owns parallelism** — Backends do NOT manage parallelism themselves. SPEC spawns N concurrent invocations via `ThreadPoolExecutor(max_workers=N)`.
2. **Fresh backend instances per task** — Each parallel task creates its own backend instance via `BackendFactory.create()` to ensure thread-safety.
3. **Streaming output aggregation** — Each task's stdout is consumed line-by-line and routed to a task-specific callback (TUI panel or log buffer).
4. **Fail-fast semantics** — If one task fails and `fail_fast=True`, a stop flag is set and pending tasks are cancelled.

**The question for backend feasibility is NOT "does the backend do parallelism" but "can multiple CLI invocations run concurrently without interference?"**

### Concurrency Limitations

| Backend | Parallel Execution Support | Notes |
|---------|---------------------------|-------|
| Auggie  | ✅ Yes | Handles concurrent CLI invocations |
| Claude Code | ✅ Yes | Each CLI invocation is isolated |
| Cursor  | ✅ Yes (with stability mechanism) | Concurrent execution verified; includes startup delay/retry for race conditions |

**Mitigation:** The `supports_parallel` property allows per-backend concurrency control. If a backend returns `False`, Step 3 will execute tasks sequentially.

### Cursor CLI Contract (Definitive)

This section defines the exact CLI contract for Cursor integration. These are final decisions, not placeholders.

#### Command Invocation

**Primary command:** `cursor`

**Rationale:** The `cursor` executable is the standard CLI entry point. The `agent` alias was considered but is less widely documented. The implementation uses `CursorClient._detect_cli_command()` to fall back to `agent` if `cursor` is not found, but `cursor` is the expected default.

```python
def _detect_cli_command(self) -> str:
    """Detect which CLI command is available."""
    if shutil.which("cursor"):
        return "cursor"
    if shutil.which("agent"):
        return "agent"
    return "cursor"  # Default; will fail on execution if not found
```

#### Non-Interactive / Print Mode

**Flag:** `--print` (long form)

**Behavior:** Executes the prompt and streams output to stdout without interactive TUI. This is required for SPEC's streaming output consumption.

**Example command:**
```bash
cursor --print "Your prompt here"
```

#### Session Persistence

**Flag:** `--no-save`

**Behavior:** Prevents the session/conversation from being saved to Cursor's history. Each invocation is isolated with no side effects on user's saved sessions.

**Example command:**
```bash
cursor --print --no-save "Your prompt here"
```

#### Model Selection

**Flag:** `--model <model-name>` (if supported by the Cursor version)

**Behavior:** When Cursor CLI supports model selection, this flag specifies the model. If the flag is not supported by the installed Cursor version, it is **ignored with a debug log message**.

**Debug log message fields when model flag is ignored:**
```python
logger.debug(
    "Cursor CLI does not support --model flag; ignoring model selection",
    extra={
        "backend": "cursor",
        "requested_model": model,
        "cursor_version": detected_version,
        "action": "model_flag_ignored",
    }
)
```

**Detection logic:** On first invocation, run `cursor --help` and check if `--model` appears in the output. Cache this result for the session.

#### Health Check

**Command:** `cursor --version`

**Acceptance criteria:**
- Exit code: `0`
- Output: Contains version string (e.g., `cursor version 1.2.3` or similar)

**Implementation:**
```python
def check_installed(self) -> tuple[bool, str]:
    """Check if Cursor CLI is installed and functional."""
    cli_cmd = self._detect_cli_command()

    if not shutil.which(cli_cmd):
        return False, f"Cursor CLI ('{cli_cmd}') not found in PATH"

    try:
        result = subprocess.run(
            [cli_cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            return True, f"Cursor CLI installed: {version}"
        return False, f"Cursor CLI version check failed (exit code {result.returncode})"
    except subprocess.TimeoutExpired:
        return False, "Cursor CLI version check timed out"
    except Exception as e:
        return False, f"Failed to check Cursor CLI: {e}"
```

#### Verification Subsection

**Manual verification steps (local development):**
1. Run `cursor --version` and confirm exit code 0
2. Run `cursor --print --no-save "echo hello"` and confirm streaming output
3. Run `cursor --help | grep -i model` to check model flag support
4. Spawn 2+ concurrent `cursor --print --no-save` processes and confirm no errors

**Automated integration test (gated behind `SPEC_INTEGRATION_TESTS=1`):**
```python
@pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled",
)
def test_cursor_cli_contract():
    """Verify Cursor CLI meets SPEC integration contract."""
    from spec.integrations.backends.cursor import CursorBackend

    backend = CursorBackend()

    # Health check
    installed, message = backend.check_installed()
    assert installed, f"Cursor CLI not installed: {message}"

    # Non-interactive execution
    output_lines = []
    success, output = backend.run_with_callback(
        "Say exactly: CURSOR_TEST_OK",
        output_callback=output_lines.append,
        dont_save_session=True,
        timeout_seconds=30,
    )
    assert success, f"Cursor execution failed: {output}"
    assert "CURSOR_TEST_OK" in output or any("CURSOR_TEST_OK" in l for l in output_lines)
```

**Failure diagnosis:**

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| `cursor: command not found` | CLI not installed | Install Cursor CLI per vendor docs |
| Exit code 1 with `--print` | Unknown flag | Cursor version too old; update CLI |
| Timeout on version check | CLI hung or PATH issue | Check `which cursor`, restart shell |
| `socket in use` during parallel | Race condition | Stability mechanism will retry |

#### Concurrent Invocation Safety

**Verified:** 2+ `cursor` CLI processes can run simultaneously.

**Stability mechanism required:** Community reports indicate potential race conditions when spawning multiple agents simultaneously. Implementation includes:
- Startup jitter (50-200ms random delay before spawn)
- Spawn retry with 1s delay on transient errors (see Phase 4.4)

#### Architecture Note

Step 3 parallelism is owned by SPEC (`ThreadPoolExecutor`), NOT by Cursor. Cursor CLI is invoked as a subprocess; it does not "manage" parallelism.

### Timeout Enforcement

Backend execution uses streaming output (line-by-line stdout consumption via `subprocess.Popen`). Standard `subprocess.communicate(timeout=...)` is **not suitable** for streaming because it buffers the entire output.

**Streaming-Safe Timeout Mechanism:**

Each CLI client wrapper implements a watchdog-based timeout that is compatible with line-by-line streaming.

**Signal Design (Two Distinct Signals):**

The implementation uses two separate signals to avoid confusion:
- `stop_watchdog_event`: Signals the watchdog thread to stop (set when process completes normally)
- `did_timeout`: Boolean flag indicating whether a timeout actually occurred

This design clearly differentiates between "process finished normally" and "timeout occurred and process was killed".

```python
def _run_streaming_with_timeout(
    self,
    cmd: list[str],
    output_callback: Callable[[str], None],
    timeout_seconds: float | None,
) -> tuple[int, str]:
    """Run subprocess with streaming output and timeout enforcement.

    Uses a background watchdog thread to enforce timeout while allowing
    line-by-line streaming output consumption.

    Signal design:
        - stop_watchdog_event: Signals watchdog to stop (process completed normally)
        - did_timeout: Boolean flag set True only when timeout actually occurred

    Args:
        cmd: Command to execute
        output_callback: Called for each line of output
        timeout_seconds: Maximum execution time (None = no timeout)

    Returns:
        Tuple of (return_code, full_output)

    Raises:
        BackendTimeoutError: If execution exceeds timeout
    """
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line-buffered for streaming
    )

    output_lines: list[str] = []
    stop_watchdog_event = threading.Event()  # Signals watchdog to stop
    did_timeout = False  # True only when timeout occurred

    def watchdog() -> None:
        """Background thread that kills process after timeout."""
        nonlocal did_timeout
        # Wait for either: (a) stop signal, or (b) timeout expiration
        stopped = stop_watchdog_event.wait(timeout=timeout_seconds)
        if not stopped:
            # Timeout expired and process still running - kill it
            logger.warning(
                "Timeout expired, terminating process",
                extra={
                    "timeout_seconds": timeout_seconds,
                    "pid": process.pid,
                    "action": "timeout_kill",
                }
            )
            did_timeout = True
            process.terminate()
            try:
                process.wait(timeout=5)  # Grace period for clean shutdown
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Process did not terminate gracefully, sending SIGKILL",
                    extra={"pid": process.pid, "action": "force_kill"}
                )
                process.kill()
                process.wait()

    # Start watchdog thread
    watchdog_thread: threading.Thread | None = None
    if timeout_seconds:
        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

    try:
        # Stream output line-by-line
        if process.stdout:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                output_callback(stripped)
                output_lines.append(line)

        process.wait()

        # Signal watchdog to stop (process completed normally)
        stop_watchdog_event.set()

        if watchdog_thread:
            watchdog_thread.join(timeout=1)

        # Check if we timed out (clear distinction from normal completion)
        if did_timeout:
            logger.info(
                "Process was killed due to timeout",
                extra={
                    "timeout_seconds": timeout_seconds,
                    "return_code": process.returncode,
                    "action": "timeout_detected",
                }
            )
            raise BackendTimeoutError(
                f"Operation timed out after {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
            )

        # Normal completion
        logger.debug(
            "Process completed normally",
            extra={
                "return_code": process.returncode,
                "output_lines": len(output_lines),
                "action": "normal_completion",
            }
        )
        return process.returncode, "".join(output_lines)

    finally:
        # Ensure process is cleaned up
        if process.poll() is None:
            process.kill()
            process.wait()
```

**Logging Clarity:**

| Scenario | Log Level | Action Field | Description |
|----------|-----------|--------------|-------------|
| Timeout expires, SIGTERM sent | WARNING | `timeout_kill` | Process exceeded timeout, attempting graceful shutdown |
| SIGTERM ignored, SIGKILL sent | WARNING | `force_kill` | Process didn't respond to SIGTERM |
| Timeout detected after wait | INFO | `timeout_detected` | Raising BackendTimeoutError |
| Normal completion | DEBUG | `normal_completion` | Process finished within timeout |

All backend implementations (`AuggieBackend`, `ClaudeBackend`, `CursorBackend`) use this streaming-safe pattern for timeout enforcement.

### Cleanup Policy

Backends implement `close()` method for resource cleanup:
- Called at end of workflow (in `finally` block)
- No-op for backends with no state (Auggie)
- May terminate subprocess connections for others

### Naming Convention

- **`AIBackend`** — The AI provider/service abstraction (Auggie, Claude Code, Cursor)
- **Subagent** — Specialized prompt personas (spec-planner, spec-implementer, etc.)
- **Client** — Low-level subprocess wrapper (e.g., `ClaudeClient`)
- **Backend** — High-level abstraction implementing `AIBackend` protocol (e.g., `ClaudeBackend`)

---

## 3. Architecture Overview

### Current State

```
┌─────────────────────────────────────────────────────────────────┐
│                           CLI Entry                             │
│                              ↓                                  │
│                    AuggieClient() created                       │
│                              ↓                                  │
│                 Ticket fetched via Auggie MCP                   │
│                              ↓                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │   Step 1    │→ │   Step 2    │→ │   Step 3    │→ │  Step 4 │ │
│  │ AuggieClient│  │ AuggieClient│  │ AuggieClient│  │  Auggie │ │
│  │  (created)  │  │  (created)  │  │ (per-task)  │  │ (maybe) │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Problems:**
- 12+ locations instantiate `AuggieClient()` directly
- No way to swap backends without modifying every step
- Backend selection scattered across files
- Rate limit detection hardcoded to Auggie patterns

### Target State

```
┌─────────────────────────────────────────────────────────────────┐
│                           CLI Entry                             │
│                              ↓                                  │
│            resolve_backend_platform(config, cli_override)       │
│                              ↓                                  │
│                  BackendFactory.create(platform)                │
│                              ↓                                  │
│         ┌────────────────────┴────────────────────┐             │
│         │              AIBackend                  │             │
│         │   (AuggieBackend | ClaudeBackend | ...) │             │
│         └────────────────────┬────────────────────┘             │
│                              ↓                                  │
│              create_ticket_service(backend=...)                 │
│                              ↓                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────┐ │
│  │   Step 1    │→ │   Step 2    │→ │   Step 3    │→ │  Step 4 │ │
│  │  (backend)  │  │  (backend)  │  │(factory per │  │(backend)│ │
│  │   injected  │  │  injected   │  │ parallel)   │  │injected │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions

#### Decision 1: Single Source of Truth for Backend Selection

**Location:** `spec/config/backend_resolver.py` (new file)

```python
def resolve_backend_platform(
    config_manager: ConfigManager,
    cli_backend_override: str | None = None,
) -> AgentPlatform:
    """Resolve the backend platform with explicit precedence.

    Precedence (highest to lowest):
    1. CLI --backend override (one-run override)
    2. Persisted config AI_BACKEND (stored by ConfigManager/onboarding)

    Raises BackendNotConfiguredError if neither is set.
    """
```

**Rationale:** The persisted key is `AI_BACKEND`. If `settings.ai_backend` exists, it is derived from `AI_BACKEND` and CLI — not a competing source of truth. There is no default backend; users must explicitly configure one.

#### Decision 2: No Backend Instance in WorkflowState

`WorkflowState` stores only:
```python
backend_platform: AgentPlatform | None = None  # enum value
backend_model: str = ""                         # optional snapshot
```

**Never** a backend object instance. Backend instances are:
- Created in runner and passed to steps explicitly
- Created fresh per-task in Step 3 parallel execution via factory

**Rationale:** Avoids serialization issues, ensures thread-safety, prevents stale state.

#### Decision 3: Client vs Backend Split

| Layer | Responsibility | Example |
|-------|---------------|---------|
| **Client** | Subprocess execution, streaming, timeout enforcement | `ClaudeClient` |
| **Backend** | Prompt/subagent composition, capability flags, rate-limit detection | `ClaudeBackend` |

**Rationale:**
- **Testability**: Mock at Backend level for unit tests; mock at Client level for integration tests
- **Reuse**: Client can be used standalone for simple calls
- **Separation**: Backend handles SPEC-specific concerns (subagent loading, frontmatter stripping)

#### Decision 4: Generic Error Types

Replace `AuggieRateLimitError` with:
```python
class BackendRateLimitError(SpecError):
    """Raised when any backend hits a rate limit."""
    pass
```

All backends implement `detect_rate_limit(output: str) -> bool` with provider-specific patterns.

#### Decision 5: MCP Verification Approach

**Onboarding verification:**
- CLI installed → checked via `check_installed()` (shutil.which + version command)
- End-to-end smoke test → optional, run a minimal prompt (e.g., `echo "test"`) to verify CLI execution works

**MCP integration verification:**
- **Do NOT ask the model "can you access Jira?"** — this is unreliable and wastes tokens
- MCP is verified **on first real use** (ticket fetch attempt)
- If ticket fetch fails, provide actionable error message with:
  - Which MCP integration failed (Jira, Linear, GitHub)
  - Link to vendor documentation for MCP setup
  - Suggestion to verify credentials/tokens

**Cold-start latency handling:**
- First backend invocation may be slow (model loading, authentication handshake)
- Display user-facing message: "First run may take a moment while the AI backend initializes..."
- Use a generous initial timeout (e.g., 120s for first call) to avoid false timeout errors
- Subsequent calls use standard timeout

#### Decision 6: Subagent Frontmatter Handling

```python
import yaml
from dataclasses import dataclass

@dataclass
class SubagentMetadata:
    """Parsed metadata from subagent frontmatter."""
    model: str | None = None
    # Other metadata fields can be added here

def _parse_subagent_prompt(self, subagent: str) -> tuple[SubagentMetadata, str]:
    """Parse subagent prompt, extracting YAML frontmatter and body.

    Returns:
        Tuple of (metadata, body)
    """
    agent_file = Path(".augment/agents") / f"{subagent}.md"
    content = agent_file.read_text()

    if content.startswith("---"):
        end_marker = content.find("---", 3)
        if end_marker != -1:
            frontmatter_str = content[3:end_marker].strip()
            body = content[end_marker + 3:].strip()
            try:
                frontmatter = yaml.safe_load(frontmatter_str) or {}
                metadata = SubagentMetadata(
                    model=frontmatter.get("model"),
                )
                return metadata, body
            except yaml.YAMLError:
                pass  # Fall through to return raw content

    return SubagentMetadata(), content
```

**Model Selection Precedence:**
1. Explicit per-call `model` override (passed to `run_with_callback()`)
2. Subagent frontmatter `model` field
3. Global config `default_model`

For backends that cannot accept a model flag, the model value is safely ignored.

#### Decision 7: Interactive UX Ownership (Non-Interactive Execution)

- **SPEC owns interactive UX** — prompts, confirmations, TUI
- **Backends execute in non-interactive mode** — streaming/print mode only for deterministic behavior
- Claude/Cursor do **not** "own" the conversation; SPEC orchestrates prompts across turns
- Any step that previously used interactive `run_print()` should:
  - Collect user input via the TUI
  - Run backend in print/streaming mode with that input included in the prompt

---

## 4. Phased Implementation Plan

### File Touchpoint Summary

| File | Phase | Change Type |
|------|-------|-------------|
| `spec/config/backend_resolver.py` | 1 | NEW |
| `spec/integrations/backends/__init__.py` | 1 | NEW |
| `spec/integrations/backends/base.py` | 1 | NEW (AIBackend Protocol + BaseBackend ABC) |
| `spec/integrations/backends/errors.py` | 1 | NEW |
| `spec/integrations/backends/auggie.py` | 1 | NEW (extends BaseBackend) |
| `spec/integrations/backends/factory.py` | 1 | NEW |
| `spec/workflow/constants.py` | 1 | NEW (subagent constants moved here) |
| `spec/integrations/auggie.py` | 1 | MODIFY (remove subagent constants) |
| `spec/workflow/state.py` | 1 | MODIFY (update imports for constants) |
| `spec/integrations/fetchers/auggie_fetcher.py` | 1.5 | MODIFY (accept AIBackend) |
| `spec/integrations/ticket_service.py` | 1.5 | MODIFY (accept AIBackend) |
| `spec/cli.py` | 1.5, 2 | MODIFY (backend resolution + workflow integration) |
| `spec/workflow/runner.py` | 2 | MODIFY |
| `spec/workflow/step1_plan.py` | 2 | MODIFY (refactor run_print to TUI + run_streaming) |
| `spec/workflow/step2_tasklist.py` | 2 | MODIFY |
| `spec/workflow/step3_execute.py` | 2 | MODIFY |
| `spec/workflow/step4_update_docs.py` | 2 | MODIFY (delete AuggieClientProtocol) |
| `spec/workflow/conflict_detection.py` | 2 | MODIFY |
| `spec/workflow/autofix.py` | 2 | MODIFY |
| `spec/workflow/review.py` | 2 | MODIFY |
| `spec/integrations/backends/claude.py` | 3 | NEW (extends BaseBackend) |
| `spec/integrations/claude.py` | 3 | NEW |
| `spec/integrations/fetchers/claude_fetcher.py` | 3 | NEW |
| `spec/integrations/backends/cursor.py` | 4 | NEW (extends BaseBackend) |
| `spec/integrations/cursor.py` | 4 | NEW |
| `spec/integrations/fetchers/cursor_fetcher.py` | 4 | NEW |
| `spec/onboarding/__init__.py` | 5 | NEW |
| `spec/onboarding/flow.py` | 5 | NEW |
| `spec/config/compatibility.py` | 5 | NEW |

---

### Phase 0: Baseline Behavior Tests (CRITICAL - DO FIRST)

**Goal:** Capture current Auggie workflow behavior before any refactoring to ensure the new backend abstraction maintains identical semantics.

**Why This Phase Exists:** The refactoring in Phases 1-2 changes how backends are instantiated and called. These baseline tests serve as a regression safety net, ensuring the new `AIBackend` protocol produces identical results to the current `AuggieClient` implementation.

#### 0.1 Create Baseline Test File

**File:** `tests/test_baseline_auggie_behavior.py`

```python
"""Baseline behavior tests for Auggie workflow.

These tests capture the current behavior of AuggieClient and workflow steps
BEFORE the multi-backend refactoring. They serve as regression tests to ensure
the new AIBackend abstraction maintains identical semantics.

Run with: SPEC_INTEGRATION_TESTS=1 pytest tests/test_baseline_auggie_behavior.py -v
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Skip all tests unless integration tests are enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Baseline tests require SPEC_INTEGRATION_TESTS=1",
)


class TestAuggieClientSemantics:
    """Capture current AuggieClient method semantics."""

    def test_run_with_callback_returns_tuple_bool_str(self):
        """Verify run_with_callback returns (bool, str) tuple."""
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        output_lines = []

        # Use a simple echo prompt that should succeed quickly
        success, output = client.run_with_callback(
            "Say exactly: BASELINE_TEST_OK",
            output_callback=output_lines.append,
            dont_save_session=True,
        )

        # Verify return type semantics
        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"
        # Verify callback was called
        assert len(output_lines) > 0, "Callback should receive output lines"

    def test_run_print_with_output_returns_tuple_bool_str(self):
        """Verify run_print_with_output returns (bool, str) tuple."""
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        success, output = client.run_print_with_output(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"

    def test_run_print_quiet_returns_str(self):
        """Verify run_print_quiet returns str only."""
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        output = client.run_print_quiet(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(output, str), "Must return str"


class TestRateLimitDetection:
    """Capture current rate limit detection behavior."""

    def test_looks_like_rate_limit_patterns(self):
        """Verify rate limit detection matches expected patterns."""
        from spec.integrations.auggie import _looks_like_rate_limit

        # These patterns MUST be detected as rate limits
        rate_limit_outputs = [
            "Error 429: Too many requests",
            "rate limit exceeded",
            "Rate limit hit, please wait",
            "quota exceeded for today",
        ]
        for output in rate_limit_outputs:
            assert _looks_like_rate_limit(output), f"Should detect: {output}"

        # These patterns must NOT be detected as rate limits
        normal_outputs = [
            "Task completed successfully",
            "File created: test.py",
            "Running tests...",
        ]
        for output in normal_outputs:
            assert not _looks_like_rate_limit(output), f"Should not detect: {output}"


class TestWorkflowStepBehavior:
    """Capture current workflow step behavior patterns."""

    @pytest.fixture
    def mock_state(self, tmp_path):
        """Create a minimal WorkflowState for testing."""
        from spec.workflow.state import WorkflowState
        from spec.integrations.providers import GenericTicket, Platform

        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.GITHUB,
            url="https://example.invalid/TEST-123",
            title="Test ticket",
            description="Test description",
        )

        state = WorkflowState(ticket=ticket)
        return state

    def test_step1_uses_spec_planner_subagent(self, mock_state):
        """Verify the default planner subagent name."""
        assert mock_state.subagent_names["planner"] == "spec-planner"

    def test_step2_uses_spec_tasklist_subagent(self, mock_state):
        """Verify the default tasklist subagent name."""
        assert mock_state.subagent_names["tasklist"] == "spec-tasklist"

    def test_step3_uses_spec_implementer_subagent(self, mock_state):
        """Verify the default implementer subagent name."""
        assert mock_state.subagent_names["implementer"] == "spec-implementer"


class TestParallelExecutionSemantics:
    """Capture parallel execution behavior in Step 3."""

    def test_parallel_tasks_use_independent_sessions(self):
        """Verify parallel tasks don't share session state.

        This test documents the expectation that each parallel task
        creates its own AuggieClient instance with dont_save_session=True.
        """
        from spec.integrations.auggie import AuggieClient

        # Create two independent clients (simulating parallel execution)
        client1 = AuggieClient()
        client2 = AuggieClient()

        # They should be independent instances
        assert client1 is not client2

        # Both should support dont_save_session parameter
        # (This is a signature check, not execution)
        import inspect
        sig = inspect.signature(client1.run_with_callback)
        assert "dont_save_session" in sig.parameters
```

#### 0.2 Run Baseline Tests Before Proceeding

**Execution Command:**
```bash
# Run baseline tests to capture current behavior
SPEC_INTEGRATION_TESTS=1 pytest tests/test_baseline_auggie_behavior.py -v

# All tests must pass before proceeding to Phase 1
```

**Acceptance Criteria for Phase 0:**
- [ ] All baseline tests pass with current codebase
- [ ] Tests document expected return types and semantics
- [ ] Rate limit detection patterns are captured
- [ ] Subagent names are verified

---

### Phase 1: Backend Infrastructure (Low Risk)

**Goal:** Create the abstraction layer without modifying existing workflow code.

#### 1.0 Rename Claude Platform Enum (REQUIRED)

**Decision:** Claude is canonically named `claude` in CLI/config. The enum member is `AgentPlatform.CLAUDE` with value `"claude"`.

**Why this step exists:** The current codebase uses `AgentPlatform.CLAUDE_DESKTOP = "claude_desktop"`. If we don't rename this early, we’ll either (a) bake the old naming into the new backend system or (b) have to churn many files later.

**Primary file:** `spec/config/fetch_config.py`

Required changes:
- Rename enum member `CLAUDE_DESKTOP` → `CLAUDE`
- Change value from `"claude_desktop"` → `"claude"`
- Update any docstrings/comments that say “Claude Desktop” to “Claude Code CLI” (or just “Claude”)

**Repo-wide touchpoints (expected after renaming):**
- All references in workflow/config/integrations/tests should use `AgentPlatform.CLAUDE`
- The CLI `--backend` choice list should include `claude`
- Any config parsing or validation errors should list `claude` (not `claude_desktop`)

**Verification commands (must be clean before proceeding past Phase 1):**
```bash
# After this rename, these should return 0 matches:
grep -rn "CLAUDE_DESKTOP" --include="*.py" spec/ tests/
grep -rn "claude_desktop" --include="*.py" spec/ tests/

# These should return matches:
grep -rn "AgentPlatform.CLAUDE" --include="*.py" spec/ tests/
```

#### 1.1 Create Backend Error Types

**File:** `spec/integrations/backends/errors.py`

```python
"""Backend-related errors.

Generic error types that apply to all AI backends.
"""
from spec.utils.errors import SpecError


class BackendRateLimitError(SpecError):
    """Raised when any backend hits a rate limit.

    Replaces AuggieRateLimitError for backend-agnostic handling.
    Carries backend_name and output for context.
    """
    def __init__(
        self,
        message: str,
        output: str = "",
        backend_name: str = "",
    ):
        super().__init__(message)
        self.output = output
        self.backend_name = backend_name


class BackendNotInstalledError(SpecError):
    """Raised when backend CLI is not installed."""
    pass


class BackendNotConfiguredError(SpecError):
    """Raised when no AI backend is configured.

    This error is raised when neither CLI --backend flag nor persisted
    AI_BACKEND config is set. Users should run 'spec init' to configure
    a backend or use --backend flag.
    """
    pass


class BackendTimeoutError(SpecError):
    """Raised when backend execution times out."""
    def __init__(
        self,
        message: str,
        timeout_seconds: float | None = None,
    ):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
```

#### 1.2 Create AIBackend Protocol

**File:** `spec/integrations/backends/base.py`

```python
"""AI Backend protocol and base types."""
from typing import Callable, Protocol, runtime_checkable
from spec.config.fetch_config import AgentPlatform


@runtime_checkable
class AIBackend(Protocol):
    """Protocol for AI backend integrations.

    This defines the contract for AI providers (Auggie, Claude Code, Cursor).
    Each backend wraps its respective CLI tool.

    All methods execute in non-interactive mode for deterministic behavior.
    User input is collected via the TUI, then included in prompts.
    """

    @property
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    def platform(self) -> AgentPlatform:
        """The AI backend enum value."""
        ...

    @property
    def supports_parallel(self) -> bool:
        """Whether this backend supports parallel execution.

        If False, Step 3 falls back to sequential execution.
        """
        ...

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt with streaming output (non-interactive).

        Args:
            prompt: The prompt to send to the AI
            output_callback: Called for each line of output
            subagent: Subagent name (loads prompt from .augment/agents/)
            model: Model override (best-effort, safely ignored if unsupported)
            dont_save_session: Isolate this execution
            timeout_seconds: Optional timeout for the operation

        Returns:
            Tuple of (success, full_output)

        Raises:
            BackendTimeoutError: If timeout_seconds exceeded
        """
        ...

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt (non-interactive) and return output."""
        ...

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute prompt quietly (non-interactive) and return output only."""
        ...

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt in streaming/print mode (non-interactive).

        This replaces interactive run_print() usage. User input should be
        collected via TUI first, then included in the prompt.
        """
        ...

    def check_installed(self) -> tuple[bool, str]:
        """Check if the backend CLI is installed.

        Returns:
            Tuple of (is_installed, message_with_version_or_error)
        """
        ...

    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error.

        Backend-specific pattern matching.
        """
        ...

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle concurrent invocations.

        Returns the value of `supports_parallel` property.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the backend.

        Called when workflow completes or on cleanup.
        Default implementation is no-op.
        """
        ...
```

**IMPORTANT:** The `AIBackend` protocol does **NOT** include `run_print()` (interactive mode). This is intentional — see Final Decision #4. Any legacy usage must be refactored to TUI + `run_streaming()`.

#### 1.3 Create BaseBackend Abstract Class

**File:** `spec/integrations/backends/base.py` (same file as AIBackend Protocol)

The `BaseBackend` abstract class implements shared logic to avoid code duplication across backends:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import yaml

from spec.config.fetch_config import AgentPlatform


@dataclass
class SubagentMetadata:
    """Parsed frontmatter from subagent prompt files."""
    model: str | None = None
    temperature: float | None = None
    # Add other fields as needed


class BaseBackend(ABC):
    """Abstract base class with common functionality for all backends.

    Concrete backends (AuggieBackend, ClaudeBackend, CursorBackend) extend this
    class to inherit shared logic while implementing backend-specific behavior.
    """

    def __init__(self, model: str = "") -> None:
        self._model = model

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    @abstractmethod
    def platform(self) -> AgentPlatform:
        """The AI backend enum value."""
        ...

    @property
    def supports_parallel(self) -> bool:
        """Whether this backend supports parallel execution.

        Override in subclass if different from default (True).
        """
        return True

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle concurrent invocations."""
        return self.supports_parallel

    def close(self) -> None:
        """Release any resources held by the backend.

        Default implementation is no-op. Override if cleanup needed.
        """
        pass

    def _run_streaming_with_timeout(
        self,
        cmd: list[str],
        output_callback: Callable[[str], None],
        timeout_seconds: float | None,
    ) -> tuple[int, str]:
        """Run subprocess with streaming output and timeout enforcement.

        This is the shared timeout implementation used by all backends.
        See "Timeout Enforcement" section in Assumptions and Constraints
        for the full implementation with watchdog thread.

        Backends call this method from their run_with_callback() implementations
        to get consistent timeout behavior.

        Args:
            cmd: Command to execute
            output_callback: Called for each line of output
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            Tuple of (return_code, full_output)

        Raises:
            BackendTimeoutError: If execution exceeds timeout
        """
        # Full implementation is in "Timeout Enforcement" section (lines 577-711)
        # This is a reference to that implementation
        from spec.integrations.backends.errors import BackendTimeoutError
        import subprocess
        import threading

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        output_lines: list[str] = []
        stop_watchdog_event = threading.Event()
        did_timeout = False

        def watchdog() -> None:
            nonlocal did_timeout
            stopped = stop_watchdog_event.wait(timeout=timeout_seconds)
            if not stopped:
                did_timeout = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        watchdog_thread: threading.Thread | None = None
        if timeout_seconds:
            watchdog_thread = threading.Thread(target=watchdog, daemon=True)
            watchdog_thread.start()

        try:
            if process.stdout:
                for line in process.stdout:
                    stripped = line.rstrip("\n")
                    output_callback(stripped)
                    output_lines.append(line)

            process.wait()
            stop_watchdog_event.set()

            if watchdog_thread:
                watchdog_thread.join(timeout=1)

            if did_timeout:
                raise BackendTimeoutError(
                    f"Operation timed out after {timeout_seconds}s",
                    timeout_seconds=timeout_seconds,
                )

            return process.returncode, "".join(output_lines)

        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def _parse_subagent_prompt(self, subagent: str) -> tuple[SubagentMetadata, str]:
        """Parse subagent prompt file and extract frontmatter.

        Shared across all backends to ensure consistent parsing.

        Args:
            subagent: Subagent name (e.g., "spec-planner")

        Returns:
            Tuple of (metadata, prompt_body)
        """
        agent_path = Path(".augment/agents") / f"{subagent}.md"
        if not agent_path.exists():
            return SubagentMetadata(), ""

        content = agent_path.read_text()

        # Parse YAML frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    metadata = SubagentMetadata(
                        model=frontmatter.get("model"),
                        temperature=frontmatter.get("temperature"),
                    )
                    return metadata, parts[2].strip()
                except yaml.YAMLError:
                    pass

        return SubagentMetadata(), content

    def _resolve_model(
        self,
        explicit_model: str | None,
        subagent: str | None,
    ) -> str | None:
        """Resolve which model to use based on precedence.

        Precedence (highest to lowest):
        1. Explicit per-call model override
        2. Subagent frontmatter model field
        3. Instance default model (self._model)

        Args:
            explicit_model: Model passed to run_* method
            subagent: Subagent name for frontmatter lookup

        Returns:
            Resolved model name or None
        """
        # 1. Explicit override takes precedence
        if explicit_model:
            return explicit_model

        # 2. Check subagent frontmatter
        if subagent:
            metadata, _ = self._parse_subagent_prompt(subagent)
            if metadata.model:
                return metadata.model

        # 3. Fall back to instance default
        return self._model or None

    # Abstract methods that each backend must implement
    @abstractmethod
    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt with streaming output (non-interactive)."""
        ...

    @abstractmethod
    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt (non-interactive) and return output."""
        ...

    @abstractmethod
    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute prompt quietly (non-interactive) and return output only."""
        ...

    @abstractmethod
    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute prompt in streaming/print mode (non-interactive)."""
        ...

    @abstractmethod
    def check_installed(self) -> tuple[bool, str]:
        """Check if the backend CLI is installed."""
        ...

    @abstractmethod
    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error."""
        ...
```

#### 1.4 Move Subagent Constants

**File:** `spec/workflow/constants.py` (NEW)

Move subagent constants from `spec/integrations/auggie.py` to a neutral location:

```python
"""Workflow constants.

This module contains constants used across the workflow that are
not specific to any particular AI backend.
"""

# Subagent names for SPEC workflow
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"

# Default timeout values (seconds)
DEFAULT_EXECUTION_TIMEOUT = 60
FIRST_RUN_TIMEOUT = 120
ONBOARDING_SMOKE_TEST_TIMEOUT = 60
```

**Update imports in `spec/workflow/state.py`:**
```python
# REMOVE:
from spec.integrations.auggie import (
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_TASKLIST,
    # ... etc
)

# ADD:
from spec.workflow.constants import (
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_DOC_UPDATER,
)
```

**Update `spec/integrations/auggie.py`:**
```python
# REMOVE the constant definitions (they now live in spec/workflow/constants.py)
# Keep only AuggieClient and related functionality
```

#### 1.5 Create AuggieBackend

**File:** `spec/integrations/backends/auggie.py`

```python
"""Auggie CLI backend implementation."""
from typing import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import BaseBackend
from spec.integrations.auggie import (
    AuggieClient,
    check_auggie_installed,
    _looks_like_rate_limit,
)


class AuggieBackend(BaseBackend):
    """Auggie CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the existing AuggieClient for actual CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        super().__init__(model=model)
        self._client = AuggieClient(model=model)

    @property
    def name(self) -> str:
        return "Auggie"

    @property
    def platform(self) -> AgentPlatform:
        return AgentPlatform.AUGGIE

    @property
    def supports_parallel(self) -> bool:
        return True  # Auggie handles concurrent invocations

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute with streaming callback and optional timeout.

        Uses BaseBackend._run_streaming_with_timeout() for timeout enforcement.
        This wraps the AuggieClient call with the streaming-safe watchdog pattern.
        """
        resolved_model = self._resolve_model(model, subagent)

        # Build auggie CLI command
        cmd = self._client._build_command(
            prompt,
            agent=subagent,
            model=resolved_model,
            dont_save_session=dont_save_session,
        )

        # Use streaming timeout wrapper from BaseBackend
        if timeout_seconds:
            exit_code, output = self._run_streaming_with_timeout(
                cmd,
                output_callback=output_callback,
                timeout_seconds=timeout_seconds,
            )
            success = exit_code == 0
            return success, output
        else:
            # No timeout - delegate to client's original implementation
            return self._client.run_with_callback(
                prompt,
                output_callback=output_callback,
                agent=subagent,
                model=resolved_model,
                dont_save_session=dont_save_session,
            )

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        resolved_model = self._resolve_model(model, subagent)
        return self._client.run_print_with_output(
            prompt,
            agent=subagent,
            model=resolved_model,
            dont_save_session=dont_save_session,
        )

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        resolved_model = self._resolve_model(model, subagent)
        return self._client.run_print_quiet(
            prompt,
            agent=subagent,
            model=resolved_model,
            dont_save_session=dont_save_session,
        )

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute in streaming mode (non-interactive).

        Uses run_print_with_output internally as Auggie's non-interactive mode.
        """
        return self.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    # NOTE: run_print() is NOT exposed - see Final Decision #4
    # Legacy callers must be refactored to use TUI + run_streaming()

    def check_installed(self) -> tuple[bool, str]:
        return check_auggie_installed()

    def detect_rate_limit(self, output: str) -> bool:
        return _looks_like_rate_limit(output)

    # supports_parallel_execution() and close() inherited from BaseBackend
```

#### 1.6 Create Backend Factory

**File:** `spec/integrations/backends/factory.py`

```python
"""Factory for creating AI backend instances."""
from spec.config.fetch_config import AgentPlatform, parse_ai_backend
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendNotInstalledError


class BackendFactory:
    """Factory for creating AI backend instances.

    Use this factory instead of instantiating backends directly.
    This ensures consistent initialization and enables future extensions.
    """

    @staticmethod
    def create(
        platform: AgentPlatform | str,
        model: str = "",
        verify_installed: bool = False,
    ) -> AIBackend:
        """Create an AI backend instance.

        Args:
            platform: AI backend enum or string name
            model: Default model to use
            verify_installed: If True, verify CLI is installed

        Returns:
            Configured AIBackend instance

        Raises:
            ValueError: If the platform is not supported
            BackendNotInstalledError: If verify_installed=True and CLI missing
        """
        if isinstance(platform, str):
            platform = parse_ai_backend(platform)

        backend: AIBackend

        if platform == AgentPlatform.AUGGIE:
            from spec.integrations.backends.auggie import AuggieBackend
            backend = AuggieBackend(model=model)

        elif platform == AgentPlatform.CLAUDE:
            from spec.integrations.backends.claude import ClaudeBackend
            backend = ClaudeBackend(model=model)

        elif platform == AgentPlatform.CURSOR:
            from spec.integrations.backends.cursor import CursorBackend
            backend = CursorBackend(model=model)

        elif platform == AgentPlatform.AIDER:
            raise ValueError("Aider backend not yet implemented")

        elif platform == AgentPlatform.MANUAL:
            raise ValueError("Manual mode does not use an AI backend")

        else:
            raise ValueError(f"Unknown platform: {platform}")

        if verify_installed:
            installed, message = backend.check_installed()
            if not installed:
                raise BackendNotInstalledError(message)

        return backend
```

#### 1.7 Create Backend Platform Resolver

**File:** `spec/config/backend_resolver.py`

```python
"""Single source of truth for backend platform resolution."""
from spec.config.fetch_config import AgentPlatform, parse_ai_backend
from spec.config.manager import ConfigManager
from spec.integrations.backends.errors import BackendNotConfiguredError


def resolve_backend_platform(
    config_manager: ConfigManager,
    cli_backend_override: str | None = None,
) -> AgentPlatform:
    """Resolve the backend platform with explicit precedence.

    Precedence (highest to lowest):
    1. CLI --backend override (one-run override)
    2. Persisted config AI_BACKEND (stored by ConfigManager/onboarding)

    If neither is set, raises BackendNotConfiguredError.

    Args:
        config_manager: Configuration manager
        cli_backend_override: CLI --backend flag value

    Returns:
        Resolved AgentPlatform enum value

    Raises:
        BackendNotConfiguredError: If no backend is configured
    """
    # 1. CLI override takes precedence (one-run override)
    if cli_backend_override:
        return parse_ai_backend(cli_backend_override)

    # 2. Check AI_BACKEND in persisted config
    ai_backend = config_manager.get("AI_BACKEND", "")
    if ai_backend.strip():
        return parse_ai_backend(ai_backend)

    # 3. No backend configured - raise error
    raise BackendNotConfiguredError(
        "No AI backend configured. Please run 'spec init' to configure a backend, "
        "or use the --backend flag to specify one."
    )
```

#### 1.8 Phase 1 Testing Strategy

**Unit Tests (mock/fakes, no external CLI required — default):**
- Test BackendFactory.create() returns correct backend types
- Test resolve_backend_platform() precedence (CLI → config → error)
- Test AuggieBackend extends BaseBackend correctly
- Test BaseBackend._parse_subagent_prompt() parses frontmatter
- Test BaseBackend._resolve_model() precedence (explicit → frontmatter → default)
- Test error type detection (BackendRateLimitError, BackendTimeoutError)
- Test subagent constants are accessible from `spec/workflow/constants.py`

**Integration Tests (gated behind `SPEC_INTEGRATION_TESTS=1` environment variable):**
- Test check_installed() returns correct results
- Test run_print_quiet() executes successfully
- These tests require external CLIs to be installed

---

### Phase 1.5: Fetcher Refactoring (Medium Risk)

**Goal:** Update fetchers and ticket service to use AIBackend instead of AuggieClient. This must happen BEFORE Phase 2 (Workflow Refactoring) to ensure the TicketService is ready.

**Why a Separate Phase?**
- Fetchers are used at CLI entry before the workflow starts
- Updating them requires the backend infrastructure from Phase 1
- Keeping this separate ensures we can test fetcher changes in isolation

#### 1.5.1 Update AuggieMediatedFetcher

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

```python
# BEFORE:
from spec.integrations.auggie import AuggieClient

class AuggieMediatedFetcher:
    def __init__(self, auggie_client: AuggieClient | None = None):
        self._client = auggie_client or AuggieClient()

# AFTER:
from spec.integrations.backends.base import AIBackend

class AuggieMediatedFetcher:
    """Fetcher that uses an AI backend for MCP-mediated ticket fetching.

    Note: Despite the name, this fetcher can work with any AIBackend,
    though Auggie-specific optimizations may apply. For other backends,
    use the appropriate fetcher (ClaudeMediatedFetcher, CursorMediatedFetcher).
    """
    def __init__(self, backend: AIBackend):
        """Initialize with an AI backend.

        Args:
            backend: AI backend instance (required, no default)
        """
        self._backend = backend

    def fetch(self, ticket_id: str) -> GenericTicket | None:
        """Fetch ticket using the backend's MCP integration."""
        prompt = self._build_fetch_prompt(ticket_id)
        success, output = self._backend.run_print_quiet(
            prompt,
            subagent=None,  # No subagent for simple fetch
            timeout_seconds=120,  # Generous for first-run cold start
        )
        if success:
            return self._parse_ticket_response(output)
        return None
```

#### 1.5.2 Update ticket_service.py

**File:** `spec/integrations/ticket_service.py`

**Current Signature (line 293):**
```python
async def create_ticket_service(
    auggie_client: AuggieClient | None = None,
    auth_manager: AuthenticationManager | None = None,
    config_manager: ConfigManager | None = None,
    cache: TicketCache | None = None,
    cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    enable_fallback: bool = True,
) -> TicketService:
```

**Decision: Keep Async, Replace AuggieClient with AIBackend**

The function is async because it may need to perform async initialization (e.g., async DirectAPIFetcher setup). We preserve this.

**New Signature:**
```python
from spec.integrations.backends.base import AIBackend
from spec.config.fetch_config import AgentPlatform

async def create_ticket_service(
    backend: AIBackend | None = None,
    auth_manager: AuthenticationManager | None = None,
    config_manager: ConfigManager | None = None,
    cache: TicketCache | None = None,
    cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    enable_fallback: bool = True,
) -> TicketService:
    """Create a TicketService with standard configuration.

    Factory function that creates a TicketService with:
    - MediatedFetcher as primary (using backend's MCP integration)
    - DirectAPIFetcher as fallback (if enable_fallback=True and auth_manager provided)
    - InMemoryTicketCache (if no cache provided)

    Args:
        backend: AI backend instance for mediated fetching (optional)
        auth_manager: For direct API fallback (passed to DirectAPIFetcher)
        config_manager: For configuration access
        cache: Ticket cache instance (or InMemoryTicketCache created)
        cache_ttl: Cache time-to-live
        enable_fallback: Whether to use DirectAPIFetcher as fallback

    Resource Management:
        The returned TicketService owns the lifecycle of the DirectAPIFetcher.
        Use as an async context manager or call close() explicitly.
    """
    # Select mediated fetcher based on backend platform
    mediated_fetcher = None
    if backend is not None:
        if backend.platform == AgentPlatform.AUGGIE:
            from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
            mediated_fetcher = AuggieMediatedFetcher(backend=backend)

        elif backend.platform == AgentPlatform.CLAUDE:
            from spec.integrations.fetchers.claude_fetcher import ClaudeMediatedFetcher
            mediated_fetcher = ClaudeMediatedFetcher(backend=backend)

        elif backend.platform == AgentPlatform.CURSOR:
            from spec.integrations.fetchers.cursor_fetcher import CursorMediatedFetcher
            mediated_fetcher = CursorMediatedFetcher(backend=backend)
        # AIDER, MANUAL - no mediated fetcher

    # Create direct API fetcher as fallback (preserves auth_manager handling)
    direct_fetcher = None
    if enable_fallback and auth_manager is not None:
        direct_fetcher = DirectAPIFetcher(
            auth_manager=auth_manager,
            config_manager=config_manager,
        )

    # ... rest of existing logic for combining fetchers and cache ...
    return TicketService(
        fetcher=_create_combined_fetcher(mediated_fetcher, direct_fetcher),
        cache=cache or InMemoryTicketCache(ttl=cache_ttl),
    )
```

**Migration for Existing Callers (line 356):**
```python
# CURRENT (line 356):
primary = AuggieMediatedFetcher(auggie_client=auggie_client, config_manager=config_manager)

# CHANGE TO:
primary = AuggieMediatedFetcher(backend=backend, config_manager=config_manager)
```

#### 1.5.3 Update CLI Entry Point for Ticket Fetching

**File:** `spec/cli.py`

Update callers to use async properly and pass AIBackend:

```python
# BEFORE (typical call pattern):
from spec.integrations.auggie import AuggieClient
auggie_client = AuggieClient()
service = await create_ticket_service(auggie_client=auggie_client, auth_manager=auth)

# AFTER:
from spec.config.backend_resolver import resolve_backend_platform
from spec.integrations.backends.factory import BackendFactory

async def create_ticket_service_from_config(
    config_manager: ConfigManager,
    auth_manager: AuthenticationManager | None = None,
    cli_backend_override: str | None = None,
) -> tuple[TicketService, AIBackend]:
    """Create ticket service with backend from config.

    This is an async factory that:
    1. Resolves the backend platform from CLI/config
    2. Creates and verifies the backend
    3. Creates the TicketService with appropriate fetchers

    Returns:
        Tuple of (TicketService, AIBackend) - backend returned for reuse in workflow

    Raises:
        BackendNotConfiguredError: If no backend configured and no CLI override
        BackendNotInstalledError: If backend CLI is not installed
    """
    platform = resolve_backend_platform(config_manager, cli_backend_override)
    backend = BackendFactory.create(platform, verify_installed=True)

    service = await create_ticket_service(
        backend=backend,
        auth_manager=auth_manager,
        config_manager=config_manager,
    )
    return service, backend
```

**Key Points:**
- Function remains `async` because `create_ticket_service` is async
- Returns both `TicketService` and `AIBackend` so workflow can reuse the backend
- `auth_manager` preserved for DirectAPIFetcher fallback
- `config_manager` passed through for configuration access

#### 1.5.4 Phase 1.5 Testing Strategy

**Unit Tests:**
- Test AuggieMediatedFetcher accepts AIBackend in constructor
- Test create_ticket_service() creates correct fetcher for each platform
- Test create_ticket_service_from_config() resolves backend correctly

**Integration Tests (gated):**
- Test actual ticket fetching with AuggieBackend
- Verify identical behavior to current AuggieClient-based implementation

---

### Phase 2: Workflow Refactoring (Medium Risk)

**Goal:** Update all workflow components to use the AIBackend protocol.

#### 2.1 Update WorkflowState

**File:** `spec/workflow/state.py`

```python
from typing import TYPE_CHECKING
from spec.config.fetch_config import AgentPlatform

if TYPE_CHECKING:
    from spec.integrations.backends.base import AIBackend

@dataclass
class WorkflowState:
    # ... existing fields ...

    # Backend platform enum (for factory creation in parallel execution)
    backend_platform: AgentPlatform | None = None

    # Optional: snapshot of model used (for logging/debugging)
    backend_model: str = ""

    # NOTE: Never store backend instance here - create fresh per-task
```

**Key Design Decision:** WorkflowState stores only `backend_platform` (an enum), never backend instances. This avoids serialization issues and ensures thread-safety in parallel execution.

#### 2.2 Update CLI Entry Point

**File:** `spec/cli.py`

```python
@click.option(
    "--backend",
    type=click.Choice(["auggie", "claude", "cursor"], case_sensitive=False),
    default=None,
    help="AI backend to use (overrides config)"
)
def run_command(
    ticket_id: str,
    backend: str | None = None,
    ...
):
    # Resolve backend platform once at entry point
    from spec.config.backend_resolver import resolve_backend_platform
    from spec.integrations.backends.errors import BackendNotConfiguredError
    from spec.integrations.backends.factory import BackendFactory

    try:
        platform = resolve_backend_platform(config, cli_backend_override=backend)
    except BackendNotConfiguredError as e:
        # No backend configured - prompt user to configure one
        print_error(str(e))
        print_info("Available backends: auggie, claude, cursor")
        print_info("Run 'spec init' to configure a backend interactively.")
        return

    # Create backend instance
    ai_backend = BackendFactory.create(platform, verify_installed=True)

    # Fetch ticket BEFORE entering runner
    ticket_service = create_ticket_service(config=agent_config, backend=ai_backend)
    ticket = ticket_service.fetch(ticket_id)

    # Pass backend to runner
    run_spec_driven_workflow(
        ticket=ticket,
        config=config,
        backend=ai_backend,
        ...
    )
```

**File:** `spec/workflow/runner.py`

```python
from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.factory import BackendFactory

def run_spec_driven_workflow(
    ticket: GenericTicket,
    config: ConfigManager,
    backend: AIBackend,  # Now required - created by CLI
    planning_model: str = "",
    implementation_model: str = "",
) -> bool:
    """Run the SPEC-driven workflow with the provided backend.

    Args:
        ticket: The ticket to implement
        config: Configuration manager
        backend: AI backend instance (required, created by CLI)
        ...
    """
    # Store platform enum in state (NOT the backend instance)
    state.backend_platform = backend.platform
    state.backend_model = getattr(backend, '_model', '')

    try:
        # Pass backend to all steps explicitly
        if not step_1_create_plan(state, backend):
            return False
        if not step_2_create_tasklist(state, backend):
            return False
        if not step_3_execute(state, backend):
            return False
        if not step_4_update_docs(state, backend=backend):
            return False
        return True
    finally:
        backend.close()  # Cleanup
```

#### 2.3 Delete Legacy AuggieClientProtocol

**File:** `spec/workflow/step4_update_docs.py`

**CRITICAL:** Step 4 currently defines its own `AuggieClientProtocol` for dependency injection. This must be deleted and replaced with `AIBackend`:

```python
# DELETE THIS ENTIRE BLOCK (lines 517-538 approximately):
class AuggieClientProtocol(Protocol):
    """Protocol for Auggie client for type hints and testing."""
    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        ...

    def run_print_with_output(
        self,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        ...

# REPLACE WITH:
from spec.integrations.backends.base import AIBackend
# Use AIBackend type hints instead of AuggieClientProtocol
```

**Rationale:** Having two protocols (`AuggieClientProtocol` and `AIBackend`) creates confusion and maintenance burden. The new `AIBackend` protocol is the single source of truth for backend interfaces.

#### 2.4 Update Step 1 (Plan Creation) — CRITICAL: run_print() Refactoring

**File:** `spec/workflow/step1_plan.py`

**Current instantiation points to replace:**
- Line 92: `auggie_client = AuggieClient()` in `_generate_plan_with_tui()`
- Line 215: `_run_clarification(state, auggie: AuggieClient, plan_path)` - **uses `auggie.run_print()` (INTERACTIVE)**

**IMPORTANT — Interactive Mode Elimination:**

The `_run_clarification()` function currently uses `auggie.run_print()` which is an interactive method. The `AIBackend` protocol does **NOT** include `run_print()`. This call must be refactored to:

1. Collect user input via TUI functions first
2. Call `backend.run_streaming()` with the input appended to the prompt

See the code example below for the exact transformation.

```python
# Change function signatures from:
def step_1_create_plan(state: WorkflowState, auggie: AuggieClient) -> bool:

# To:
from spec.integrations.backends.base import AIBackend

def step_1_create_plan(state: WorkflowState, backend: AIBackend) -> bool:
    """Create implementation plan using the provided backend."""
    ...

def _generate_plan_with_tui(state: WorkflowState, backend: AIBackend) -> bool:
    """Generate plan with TUI - use injected backend, don't create new."""
    # REMOVE: auggie_client = AuggieClient()
    # USE: backend parameter instead
    success, output = backend.run_with_callback(
        prompt,
        output_callback=tui_callback,
        subagent="spec-planner",
        dont_save_session=True,
    )
    ...

def _run_clarification(state: WorkflowState, backend: AIBackend, plan_path: Path) -> bool:
    """Run clarification in non-interactive mode.

    User input is collected via TUI first, then included in the prompt
    sent to the backend in streaming mode.
    """
    # Collect user input via TUI
    user_response = prompt_user_for_clarification(state)

    # Include user response in prompt and run in streaming mode
    clarification_prompt_with_input = (
        f"{clarification_prompt}\n\n## User Response\n\n{user_response}"
    )
    success, output = backend.run_streaming(
        clarification_prompt_with_input,
        subagent="spec-planner",
    )
    return success
```

**Note: `prompt_user_for_clarification()` Implementation**

The function `prompt_user_for_clarification()` must be created as part of this refactoring. It should:

1. Display the clarification questions from the plan to the user via TUI
2. Prompt the user to enter their responses (text input)
3. Return the user's response as a string

**Implementation location:** `spec/workflow/step1_plan.py` (same file as `_run_clarification`)

```python
def prompt_user_for_clarification(state: WorkflowState) -> str:
    """Prompt user for clarification responses via TUI.

    This function handles the user-facing interactive input that was
    previously handled by auggie.run_print()'s interactive mode.

    Args:
        state: Workflow state containing clarification questions

    Returns:
        User's response text to be appended to the clarification prompt
    """
    from spec.ui.prompts import prompt_input
    from spec.utils.console import print_header

    # Display clarification questions to user
    print_header("Clarification Needed")
    print(state.clarification_questions)

    # Collect user input using existing TUI function with multiline support
    user_response = prompt_input(
        "Enter your responses to the clarification questions above:",
        multiline=True
    )

    return user_response
```

**Note:** This uses existing TUI functions from `spec/ui/prompts.py` (`prompt_input` with `multiline=True`) and `spec/utils/console.py` (`print_header`). The key requirement is that user input collection happens in SPEC's TUI layer, not inside the backend.

#### 2.5 Update Step 2 (Tasklist Creation)

**File:** `spec/workflow/step2_tasklist.py`

**Current instantiation points to replace:**
- Line 305: `auggie_client = AuggieClient()` in `_generate_tasklist()`
- Line 447: `auggie_client = AuggieClient()` in `_refine_tasklist()`

```python
# Change function signatures from:
def step_2_create_tasklist(state: WorkflowState, auggie: AuggieClient) -> bool:

# To:
from spec.integrations.backends.base import AIBackend

def step_2_create_tasklist(state: WorkflowState, backend: AIBackend) -> bool:
    ...

def _generate_tasklist(state: WorkflowState, backend: AIBackend) -> bool:
    # REMOVE: auggie_client = AuggieClient()
    # USE: backend parameter
    ...

def _refine_tasklist(state: WorkflowState, backend: AIBackend) -> bool:
    # REMOVE: auggie_client = AuggieClient()
    # USE: backend parameter
    ...
```

#### 2.6 Update Step 3 (Task Execution) - CRITICAL

**File:** `spec/workflow/step3_execute.py`

**Current instantiation points to replace (actual function names from codebase):**
- `_execute_task()` — single task execution
- `_execute_task_with_callback()` — task execution with streaming callback
- `_execute_task_with_retry()` — task execution with rate limit retry
- `_execute_fallback()` — sequential execution (non-TUI)
- `_execute_parallel_fallback()` — parallel execution (non-TUI)
- `_run_post_implementation_tests()` — post-implementation test runner

**Critical Design: Parallel Execution with supports_parallel Check**

Step 3 runs tasks in parallel using ThreadPoolExecutor. Each parallel task needs its own fresh backend instance (NOT shared). The backend platform enum is passed, and factory creates fresh instances.

If `backend.supports_parallel` is `False`, Step 3 falls back to sequential execution.

```python
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.factory import BackendFactory
from spec.config.fetch_config import AgentPlatform

def step_3_execute(state: WorkflowState, backend: AIBackend) -> bool:
    """Execute tasks using the provided backend.

    For parallel execution, fresh backend instances are created per-task
    using BackendFactory and the platform enum stored in state.

    If backend.supports_parallel is False, falls back to sequential execution.
    """
    # Check parallel execution support
    if not backend.supports_parallel:
        print_info(f"{backend.name} does not support parallel execution. Using sequential mode.")
        state.parallel_execution_enabled = False
    ...

def _execute_parallel_fallback(
    state: WorkflowState,
    tasks: list[Task],
    plan_path: Path,
    tasklist_path: Path,
    log_dir: Path,
    backend_platform: AgentPlatform,  # Enum, not instance
    model: str = "",
) -> list[str]:
    """Execute tasks in parallel with fresh backend per task.

    Args:
        state: Workflow state
        tasks: Tasks to execute
        plan_path: Path to plan file
        tasklist_path: Path to tasklist file
        log_dir: Directory for log files
        backend_platform: Platform enum for factory creation
        model: Model override

    Returns:
        List of failed task names
    """
    def execute_single_task(task_info: tuple[int, Task]) -> tuple[Task, bool]:
        idx, task = task_info
        # Create fresh backend for this thread
        task_backend = BackendFactory.create(backend_platform, model=model)
        try:
            success = _execute_task_with_retry(state, task, plan_path, ...)
            return task, success
        finally:
            task_backend.close()

    with ThreadPoolExecutor(max_workers=parallel_count) as executor:
        results = list(executor.map(execute_single_task, enumerate(tasks)))
    return [task.name for task, success in results if not success]

def _execute_task(state: WorkflowState, task: Task, plan_path: Path, backend: AIBackend) -> bool:
    """Execute a single task with the provided backend.

    CRITICAL: This function receives a backend instance, does NOT create its own.
    """
    # REMOVE: auggie_client = AuggieClient()
    success, output = backend.run_with_callback(
        prompt,
        output_callback=output_handler,
        subagent="spec-implementer",
        dont_save_session=True,
    )
    ...

def _execute_task_with_callback(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    backend: AIBackend,
    callback: Callable[[str], None],
    is_parallel: bool = False,
) -> bool:
    """Execute task with callback - use injected backend."""
    # REMOVE: auggie_client = AuggieClient()
    ...

# ============================================================================
# THREAD-SAFE CALLBACK HANDLING FOR PARALLEL EXECUTION
# ============================================================================
# Per Final Decision #16: output_callback functions must be thread-safe when
# Step 3 runs in parallel. Use per-task buffers to avoid interleaved output.
#
# Example implementation:
# ============================================================================

import threading
from typing import Callable

class ThreadSafeTaskBuffer:
    """Per-task output buffer for parallel execution.

    Each parallel task writes to its own buffer. Buffers are flushed
    to the shared output only after the task completes, preventing
    interleaved output from concurrent tasks.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._buffer: list[str] = []
        self._lock = threading.Lock()

    def callback(self, line: str) -> None:
        """Thread-safe callback for appending output lines."""
        with self._lock:
            self._buffer.append(line)

    def get_output(self) -> str:
        """Get accumulated output (call after task completes)."""
        with self._lock:
            return "\n".join(self._buffer)


def _execute_parallel_with_safe_callbacks(
    tasks: list[Task],
    backend_platform: AgentPlatform,
    model: str = "",
) -> dict[str, tuple[bool, str]]:
    """Execute tasks in parallel with thread-safe per-task buffers.

    Returns:
        Dict mapping task_id -> (success, output)
    """
    results: dict[str, tuple[bool, str]] = {}
    results_lock = threading.Lock()

    def execute_single_task(task: Task) -> None:
        # Create fresh backend AND buffer for this thread
        task_backend = BackendFactory.create(backend_platform, model=model)
        task_buffer = ThreadSafeTaskBuffer(task.id)

        try:
            success, _ = task_backend.run_with_callback(
                task.prompt,
                output_callback=task_buffer.callback,  # Thread-safe callback
                subagent="spec-implementer",
                dont_save_session=True,
            )
            output = task_buffer.get_output()

            with results_lock:
                results[task.id] = (success, output)
        finally:
            task_backend.close()

    with ThreadPoolExecutor(max_workers=parallel_count) as executor:
        executor.map(execute_single_task, tasks)

    return results

def _run_post_implementation_tests(state: WorkflowState, backend: AIBackend) -> bool:
    """Run tests after implementation - use injected backend."""
    # REMOVE: auggie_client = AuggieClient()
    ...
```

#### 2.7 Update Step 4 (Documentation Update)

**File:** `spec/workflow/step4_update_docs.py`

Step 4 already supports dependency injection via `AuggieClientProtocol`. This must be replaced with `AIBackend`:

**Changes required:**
1. **Delete `AuggieClientProtocol`** class definition (see section 2.3)
2. **Update function signature** to use `AIBackend`
3. **Make backend parameter required** (no default creation)

```python
# BEFORE:
def step_4_update_docs(
    state: WorkflowState,
    *,
    auggie_client: AuggieClientProtocol | None = None
) -> bool:
    client = auggie_client or AuggieClient()

# AFTER:
from spec.integrations.backends.base import AIBackend

def step_4_update_docs(
    state: WorkflowState,
    *,
    backend: AIBackend,  # Now required, no default
) -> bool:
    """Update documentation using the provided backend."""
    # Use backend directly - no fallback creation
    ...
```

#### 2.8 Update Helper Files

**File:** `spec/workflow/conflict_detection.py`

```python
# Change from:
def detect_context_conflict(ticket, user_context, auggie: AuggieClient, state):

# To:
from spec.integrations.backends.base import AIBackend

def detect_context_conflict(
    ticket,
    user_context,
    backend: AIBackend,
    state: WorkflowState,
) -> bool:
    success, output = backend.run_with_callback(
        conflict_prompt,
        output_callback=lambda _: None,  # No-op callback
        subagent="spec-planner",
        dont_save_session=True,
    )
    ...
```

**File:** `spec/workflow/autofix.py`

```python
# Line 62: auggie_client = AuggieClient() in run_auto_fix()

from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.factory import BackendFactory

def run_auto_fix(
    state: WorkflowState,
    error: Exception,
    backend: AIBackend | None = None,
) -> bool:
    """Run automatic fix for an error.

    Args:
        state: Workflow state
        error: The error to fix
        backend: Backend to use (creates fresh if None)
    """
    if backend is None:
        backend = BackendFactory.create(state.backend_platform)
    ...
```

**File:** `spec/workflow/review.py`

```python
# Line 326: auggie_client = AuggieClient() in run_phase_review()

from spec.integrations.backends.base import AIBackend

def run_phase_review(
    state: WorkflowState,
    phase: str,
    backend: AIBackend,
) -> ReviewResult:
    """Run review for a phase using the provided backend."""
    # REMOVE: auggie_client = AuggieClient()
    ...

def _run_rereview_after_fix(
    state: WorkflowState,
    log_dir: Path,
    phase: str,
    backend: AIBackend,  # Changed from auggie_client: AuggieClient
) -> bool:
    ...
```

#### 2.9 Complete AuggieClient() Instantiation Point List

**All locations that create AuggieClient() to be replaced (correct function names):**

| # | File | Function | Replacement Strategy | Notes |
|---|------|----------|---------------------|-------|
| 1 | `cli.py` | `create_ticket_service_from_config()` | Use backend from CLI | See Phase 1.5 |
| 2 | `runner.py` | `run_spec_driven_workflow()` | Receive from CLI | |
| 3 | `step1_plan.py` | `_generate_plan_with_tui()` | Use injected backend | |
| 4 | `step1_plan.py` | `_run_clarification()` | Use injected backend | **⚠️ run_print() → TUI + run_streaming()** |
| 5 | `step2_tasklist.py` | `_generate_tasklist()` | Use injected backend | |
| 6 | `step2_tasklist.py` | `_refine_tasklist()` | Use injected backend | |
| 7 | `step3_execute.py` | `_execute_task()` | Factory per-task | |
| 8 | `step3_execute.py` | `_execute_task_with_callback()` | Factory per-task | |
| 9 | `step3_execute.py` | `_execute_task_with_retry()` | Factory per-task | |
| 10 | `step3_execute.py` | `_execute_fallback()` | Use injected backend | |
| 11 | `step3_execute.py` | `_execute_parallel_fallback()` | Factory per-task | |
| 12 | `step3_execute.py` | `_run_post_implementation_tests()` | Use injected backend | |
| 13 | `step4_update_docs.py` | `step_4_update_docs()` | Use injected backend | **Delete AuggieClientProtocol** |
| 14 | `autofix.py` | `run_auto_fix()` | Factory or injected | |
| 15 | `review.py` | `run_phase_review()` | Use injected backend | |

**Special Attention Required:**
- **Item #4**: The `_run_clarification()` function uses `auggie.run_print()` (interactive). This MUST be refactored to collect user input via TUI first, then call `backend.run_streaming()`.
- **Item #13**: Delete the `AuggieClientProtocol` class entirely and use `AIBackend` instead (see section 2.3).

#### 2.10 Rate Limit Error Migration

**File:** `spec/workflow/step3_execute.py`

Replace `AuggieRateLimitError` with `BackendRateLimitError` throughout the file:

**Import changes:**
```python
# REMOVE:
from spec.integrations.auggie import (
    AuggieClient,
    AuggieRateLimitError,
    _looks_like_rate_limit,
)

# ADD:
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendRateLimitError
from spec.integrations.backends.factory import BackendFactory
```

**Rate limit detection changes:**
```python
# REMOVE this pattern:
if _looks_like_rate_limit(output):
    raise AuggieRateLimitError("Rate limit detected", output=output)

# REPLACE with:
if backend.detect_rate_limit(output):
    raise BackendRateLimitError(
        "Rate limit detected",
        output=output,
        backend_name=backend.name,
    )
```

**Retry logic updates in `_execute_task_with_retry()`:**
```python
def _execute_task_with_retry(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    backend: AIBackend,  # Changed from auggie_client
    callback: Callable[[str], None],
    max_retries: int = 3,
) -> bool:
    """Execute task with retry on rate limit errors."""
    for attempt in range(max_retries + 1):
        try:
            success, output = backend.run_with_callback(
                prompt,
                output_callback=callback,
                subagent="spec-implementer",
                dont_save_session=True,
            )

            if not success and backend.detect_rate_limit(output):
                raise BackendRateLimitError(
                    "Rate limit detected",
                    output=output,
                    backend_name=backend.name,
                )
            return success

        except BackendRateLimitError as e:
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff
                print_warning(f"Rate limit hit ({e.backend_name}), waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    return False
```

#### 2.11 Phase 2 Testing Strategy

**Unit Tests (mock/fakes, no external CLI required — default):**
- Test all step functions accept AIBackend parameter
- Test parallel execution creates fresh backends
- Test supports_parallel check triggers sequential fallback
- Test rate limit detection uses backend-specific method
- Test cleanup (close) is called

**Integration Tests (gated behind `SPEC_INTEGRATION_TESTS=1`):**
- Run full workflow with AuggieBackend
- Verify identical behavior to current implementation
- Verify no `AuggieClient()` direct instantiations remain

---

### Phase 3: Claude Backend Implementation (Medium Risk)

**Goal:** Implement ClaudeBackend following the same patterns as AuggieBackend.

#### 3.1 Create ClaudeClient



```python
"""Claude Code CLI integration for SPEC.

This module provides the Claude Code CLI wrapper, following the same
pattern as AuggieClient for consistency.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

class ClaudeClient:
    """Wrapper for Claude Code CLI commands.

    Installation: See https://docs.anthropic.com/claude-code for current instructions.
    The CLI executable is typically named 'claude'.
    """

    def __init__(self, model: str = "") -> None:
        self.model = model

    def _build_command(
        self,
        prompt: str,
        subagent: str | None = None,
        model: str | None = None,
        print_mode: bool = False,
        no_save: bool = False,
    ) -> list[str]:
        """Build claude command list."""
        cmd = ["claude"]

        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if no_save:
            cmd.append("--no-save")

        if print_mode:
            cmd.append("--print")

        # Handle subagent prompt
        effective_prompt = prompt
        if subagent:
            subagent_prompt = self._load_subagent_prompt(subagent)
            if subagent_prompt:
                effective_prompt = (
                    f"## Agent Instructions\n\n{subagent_prompt}\n\n"
                    f"## Task\n\n{prompt}"
                )

        cmd.extend(["--prompt", effective_prompt])
        return cmd

    def _load_subagent_prompt(self, subagent: str) -> str | None:
        """Load subagent prompt from .augment/agents/ directory."""
        agent_file = Path(".augment/agents") / f"{subagent}.md"
        if agent_file.exists():
            content = agent_file.read_text()
            # Extract body after frontmatter
            if content.startswith("---"):
                end_marker = content.find("---", 3)
                if end_marker != -1:
                    return content[end_marker + 3:].strip()
            return content
        return None

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback."""
        cmd = self._build_command(prompt, subagent, model, True, no_save)

        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )

        output_lines = []
        if process.stdout is not None:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                output_callback(stripped)
                output_lines.append(line)

        process.wait()
        return process.returncode == 0, "".join(output_lines)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> tuple[bool, str]:
        """Run in print mode and return (success, output)."""
        cmd = self._build_command(prompt, subagent, model, print_mode=True, no_save=no_save)

        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return result.returncode == 0, result.stdout

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> str:
        """Run in print mode and return output only."""
        _, output = self.run_print_with_output(
            prompt, subagent=subagent, model=model, no_save=no_save
        )
        return output


def check_claude_installed() -> tuple[bool, str]:
    """Check if Claude Code CLI is installed."""
    if not shutil.which("claude"):
        return False, "Claude Code CLI is not installed"

    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True, f"Claude Code CLI installed: {result.stdout.strip()}"
        return False, "Claude Code CLI version check failed"
    except Exception as e:
        return False, f"Failed to check Claude Code CLI: {e}"
```

#### 3.2 Create ClaudeBackend

Create `spec/integrations/backends/claude.py`:

```python
"""Claude Code CLI backend implementation."""

from typing import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.claude import ClaudeClient, check_claude_installed

# Claude-specific rate limit patterns
CLAUDE_RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "too many requests",
    "429", "overloaded", "capacity",
]


class ClaudeBackend:
    """Claude Code CLI backend implementation."""

    def __init__(self, model: str = "") -> None:
        self._client = ClaudeClient(model=model)

    @property
    def name(self) -> str:
        return "Claude Code"

    @property
    def platform(self) -> AgentPlatform:
        return AgentPlatform.CLAUDE

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        return self._client.run_with_callback(
            prompt,
            output_callback=output_callback,
            subagent=subagent,
            model=model,
            no_save=dont_save_session,
        )

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        return self._client.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            no_save=dont_save_session,
        )

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> str:
        return self._client.run_print_quiet(
            prompt,
            subagent=subagent,
            model=model,
            no_save=dont_save_session,
        )

    def check_installed(self) -> tuple[bool, str]:
        return check_claude_installed()

    def detect_rate_limit(self, output: str) -> bool:
        output_lower = output.lower()
        return any(p in output_lower for p in CLAUDE_RATE_LIMIT_PATTERNS)

    def supports_parallel_execution(self) -> bool:
        return True  # Claude CLI invocations are isolated

    def close(self) -> None:
        pass  # ClaudeClient has no resources to release
```

#### 3.3 Create ClaudeMediatedFetcher

Create `spec/integrations/fetchers/claude_fetcher.py`:

```python
"""Claude-mediated ticket fetcher using MCP integrations."""

from spec.integrations.claude import ClaudeClient
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.providers.base import Platform

SUPPORTED_PLATFORMS = frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB})

class ClaudeMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Claude Code CLI's MCP integrations."""

    def __init__(self, claude_client: ClaudeClient | None = None):
        self._claude = claude_client or ClaudeClient()

    @property
    def name(self) -> str:
        return "Claude MCP Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        return platform in SUPPORTED_PLATFORMS

    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._claude.run_print_quiet(prompt, no_save=True)
        )

    def _get_prompt_template(self, platform: Platform) -> str:
        from spec.integrations.fetchers.auggie_fetcher import PLATFORM_PROMPT_TEMPLATES
        return PLATFORM_PROMPT_TEMPLATES.get(platform, "")
```

---

### Phase 4: Cursor Backend Implementation (Medium Risk)

#### 4.1 Create CursorClient

Create `spec/integrations/cursor.py`:

```python
"""Cursor CLI integration for SPEC.

Installation: See https://www.cursor.com/cli for current instructions.
The CLI executable may be 'cursor' or 'agent' depending on version.
"""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

class CursorClient:
    """Wrapper for Cursor CLI commands."""

    def __init__(self, model: str = "") -> None:
        self.model = model
        self._cli_command = self._detect_cli_command()

    def _detect_cli_command(self) -> str:
        """Detect which CLI command is available."""
        if shutil.which("cursor"):
            return "cursor"
        if shutil.which("agent"):
            return "agent"
        return "cursor"  # Default

    def _build_command(
        self,
        prompt: str,
        subagent: str | None = None,
        model: str | None = None,
        print_mode: bool = False,
        no_save: bool = False,
    ) -> list[str]:
        """Build cursor command list.

        Flag contract (see Cursor CLI Contract section):
        - --print: Non-interactive streaming output mode
        - --no-save: Prevent session persistence
        - --model: Model selection (if supported; ignored otherwise)
        """
        cmd = [self._cli_command]

        # Non-interactive mode (required for SPEC streaming output)
        if print_mode:
            cmd.append("--print")

        # Session isolation (prevents side effects on user's saved sessions)
        if no_save:
            cmd.append("--no-save")

        # Model selection (best-effort; ignored if unsupported)
        effective_model = model or self.model
        if effective_model and self._supports_model_flag():
            cmd.extend(["--model", effective_model])
        elif effective_model:
            logger.debug(
                "Cursor CLI does not support --model flag; ignoring model selection",
                extra={
                    "backend": "cursor",
                    "requested_model": effective_model,
                    "action": "model_flag_ignored",
                }
            )

        # Handle subagent prompt
        effective_prompt = prompt
        if subagent:
            subagent_prompt = self._load_subagent_prompt(subagent)
            if subagent_prompt:
                effective_prompt = (
                    f"## Agent Instructions\n\n{subagent_prompt}\n\n"
                    f"## Task\n\n{prompt}"
                )

        cmd.append(effective_prompt)
        return cmd

    def _supports_model_flag(self) -> bool:
        """Check if the installed Cursor CLI supports --model flag.

        Cached for the session to avoid repeated subprocess calls.
        """
        if not hasattr(self, "_model_flag_supported"):
            try:
                result = subprocess.run(
                    [self._cli_command, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self._model_flag_supported = "--model" in result.stdout
            except Exception:
                self._model_flag_supported = False
        return self._model_flag_supported

    def _load_subagent_prompt(self, subagent: str) -> str | None:
        """Load subagent prompt from .augment/agents/ directory."""
        agent_file = Path(".augment/agents") / f"{subagent}.md"
        if agent_file.exists():
            content = agent_file.read_text()
            if content.startswith("---"):
                end_marker = content.find("---", 3)
                if end_marker != -1:
                    return content[end_marker + 3:].strip()
            return content
        return None

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback in non-interactive mode.

        Args:
            prompt: The prompt to execute
            output_callback: Called for each line of output
            subagent: Optional subagent name for prompt composition
            model: Optional model override
            no_save: If True, prevents session persistence (--no-save flag)

        Returns:
            Tuple of (success, full_output)
        """
        cmd = self._build_command(
            prompt,
            subagent=subagent,
            model=model,
            print_mode=True,  # Always use --print for streaming
            no_save=no_save,
        )

        process = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )

        output_lines = []
        if process.stdout is not None:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                output_callback(stripped)
                output_lines.append(line)

        process.wait()
        return process.returncode == 0, "".join(output_lines)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> tuple[bool, str]:
        """Run in print mode and return (success, output)."""
        cmd = self._build_command(
            prompt, subagent=subagent, model=model, print_mode=True, no_save=no_save
        )

        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return result.returncode == 0, result.stdout

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        no_save: bool = False,
    ) -> str:
        """Run in print mode and return output only."""
        _, output = self.run_print_with_output(
            prompt, subagent=subagent, model=model, no_save=no_save
        )
        return output


def check_cursor_installed() -> tuple[bool, str]:
    """Check if Cursor CLI is installed."""
    cursor_cmd = "cursor" if shutil.which("cursor") else "agent"

    if not shutil.which(cursor_cmd):
        return False, "Cursor CLI is not installed"

    try:
        result = subprocess.run([cursor_cmd, "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True, f"Cursor CLI installed: {result.stdout.strip()}"
        return False, "Cursor CLI version check failed"
    except Exception as e:
        return False, f"Failed to check Cursor CLI: {e}"
```

#### 4.2 Create CursorBackend

Create `spec/integrations/backends/cursor.py`:

```python
"""Cursor CLI backend implementation."""

from typing import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.cursor import CursorClient, check_cursor_installed

# Cursor-specific rate limit patterns
CURSOR_RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "too many requests",
    "429", "quota exceeded", "throttl",
]


class CursorBackend:
    """Cursor CLI backend implementation."""

    def __init__(self, model: str = "") -> None:
        self._client = CursorClient(model=model)

    @property
    def name(self) -> str:
        return "Cursor"

    @property
    def platform(self) -> AgentPlatform:
        return AgentPlatform.CURSOR

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        return self._client.run_with_callback(
            prompt,
            output_callback=output_callback,
            subagent=subagent,
            model=model,
            no_session=dont_save_session,
        )

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        return self._client.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            no_session=dont_save_session,
        )

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> str:
        return self._client.run_print_quiet(
            prompt,
            subagent=subagent,
            model=model,
            no_session=dont_save_session,
        )

    def check_installed(self) -> tuple[bool, str]:
        return check_cursor_installed()

    def detect_rate_limit(self, output: str) -> bool:
        output_lower = output.lower()
        return any(p in output_lower for p in CURSOR_RATE_LIMIT_PATTERNS)

    @property
    def supports_parallel(self) -> bool:
        # Verified: Cursor CLI supports concurrent execution via worktrees/separate terminals
        # Stability mechanism (startup delay) handles potential race conditions
        return True

    def supports_parallel_execution(self) -> bool:
        return self.supports_parallel

    def close(self) -> None:
        pass  # CursorClient has no resources to release
```

#### 4.3 Create CursorMediatedFetcher

Create `spec/integrations/fetchers/cursor_fetcher.py`:

```python
"""Cursor-mediated ticket fetcher using MCP integrations."""

from spec.integrations.cursor import CursorClient
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.providers.base import Platform

SUPPORTED_PLATFORMS = frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB})

class CursorMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Cursor CLI's MCP integrations."""

    def __init__(self, cursor_client: CursorClient | None = None):
        self._cursor = cursor_client or CursorClient()

    @property
    def name(self) -> str:
        return "Cursor MCP Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        return platform in SUPPORTED_PLATFORMS

    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._cursor.run_print_quiet(prompt, no_session=True)
        )

    def _get_prompt_template(self, platform: Platform) -> str:
        from spec.integrations.fetchers.auggie_fetcher import PLATFORM_PROMPT_TEMPLATES
        return PLATFORM_PROMPT_TEMPLATES.get(platform, "")
```

#### 4.4 Implement Stability Mechanism for Concurrent Cursor Invocations

**Context:** Community reports indicate potential race conditions when spawning multiple Cursor CLI agents simultaneously. This task implements a stability mechanism to handle these edge cases.

**File:** `spec/integrations/cursor.py`

Add startup delay and retry logic to `CursorClient`:

```python
import random
import time

# Stability constants for concurrent execution
CURSOR_STARTUP_DELAY_MIN_MS = 50   # Minimum delay between concurrent spawns
CURSOR_STARTUP_DELAY_MAX_MS = 200  # Maximum delay between concurrent spawns
CURSOR_SPAWN_MAX_RETRIES = 2       # Max retries on spawn failure
CURSOR_SPAWN_RETRY_DELAY_S = 1.0   # Delay between spawn retries

class CursorClient:
    """Wrapper for Cursor CLI commands with stability mechanisms."""

    def __init__(self, model: str = "", enable_startup_jitter: bool = True) -> None:
        self.model = model
        self._enable_startup_jitter = enable_startup_jitter

    def _apply_startup_jitter(self) -> None:
        """Apply small random delay to reduce concurrent spawn race conditions.

        When multiple SPEC tasks spawn Cursor CLI simultaneously, a brief
        staggered delay helps avoid potential lock contention or socket
        conflicts that have been reported in the community.
        """
        if self._enable_startup_jitter:
            delay_ms = random.randint(
                CURSOR_STARTUP_DELAY_MIN_MS,
                CURSOR_STARTUP_DELAY_MAX_MS
            )
            time.sleep(delay_ms / 1000.0)

    def _run_with_spawn_retry(
        self,
        run_func: Callable[[], tuple[bool, str]],
    ) -> tuple[bool, str]:
        """Execute run function with retry on spawn-related failures.

        Certain transient errors (e.g., "socket in use", "server busy")
        may occur when spawning multiple Cursor CLI processes. This
        wrapper retries such failures with a brief delay.
        """
        last_error: Exception | None = None

        for attempt in range(CURSOR_SPAWN_MAX_RETRIES + 1):
            self._apply_startup_jitter()
            try:
                success, output = run_func()
                # Check for spawn-related transient errors
                if not success and self._is_transient_spawn_error(output):
                    if attempt < CURSOR_SPAWN_MAX_RETRIES:
                        time.sleep(CURSOR_SPAWN_RETRY_DELAY_S)
                        continue
                return success, output
            except OSError as e:
                # Handle OS-level spawn failures
                last_error = e
                if attempt < CURSOR_SPAWN_MAX_RETRIES:
                    time.sleep(CURSOR_SPAWN_RETRY_DELAY_S)
                    continue
                raise

        # Should not reach here, but handle gracefully
        return False, f"Spawn failed after retries: {last_error}"

    def _is_transient_spawn_error(self, output: str) -> bool:
        """Detect transient spawn-related errors that may be retried."""
        transient_patterns = [
            "socket in use",
            "server busy",
            "connection refused",
            "unable to connect",
            "spawn failed",
        ]
        output_lower = output.lower()
        return any(p in output_lower for p in transient_patterns)
```

**Update `run_with_callback()` to use stability mechanism:**

```python
def run_with_callback(
    self,
    prompt: str,
    *,
    output_callback: Callable[[str], None],
    subagent: str | None = None,
    model: str | None = None,
    no_session: bool = False,
) -> tuple[bool, str]:
    """Run with output callback, using stability mechanism for spawn."""
    def _inner_run() -> tuple[bool, str]:
        cmd = self._build_command(prompt, subagent, model, print_mode=False, no_save=no_session)
        return self._run_streaming_with_callback(cmd, output_callback)

    return self._run_with_spawn_retry(_inner_run)
```

**Testing:** Add unit tests for stability mechanism:

```python
class TestCursorStabilityMechanism:
    def test_startup_jitter_applied(self, mocker):
        """Verify startup jitter is applied before spawn."""
        sleep_mock = mocker.patch('time.sleep')
        client = CursorClient(enable_startup_jitter=True)
        client._apply_startup_jitter()
        sleep_mock.assert_called_once()

    def test_spawn_retry_on_transient_error(self, mocker):
        """Verify spawn is retried on transient errors."""
        client = CursorClient()
        call_count = 0

        def flaky_run():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return False, "connection refused"
            return True, "success"

        success, output = client._run_with_spawn_retry(flaky_run)
        assert success
        assert call_count == 2  # First attempt failed, second succeeded
```

---

### Phase 5: Onboarding Infrastructure (Low Risk)

**Goal:** Implement first-run onboarding flow for backend selection and verification.

**TUI Dependencies (Verified Available):** The onboarding flow should use existing TUI functions from `spec/ui/prompts.py`:
- `prompt_select()` - For backend selection (replaces raw `input()`)
- `prompt_confirm()` - For confirmation prompts
- `prompt_input()` - For text input with optional validation
- `print_header()` / `print_info()` from `spec/utils/console.py` - For styled output

These functions are already implemented and handle keyboard interrupts gracefully by raising `UserCancelledError`.

#### 5.1 Create Compatibility Matrix

**File:** `spec/config/compatibility.py`

```python
"""Backend-platform compatibility matrix."""
from spec.config.fetch_config import AgentPlatform
from spec.integrations.providers import Platform

MCP_SUPPORT: dict[AgentPlatform, frozenset[Platform]] = {
    AgentPlatform.AUGGIE: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.CLAUDE: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.CURSOR: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.AIDER: frozenset(),
    AgentPlatform.MANUAL: frozenset(),
}

API_SUPPORT: frozenset[Platform] = frozenset({
    Platform.JIRA, Platform.LINEAR, Platform.GITHUB,
    Platform.AZURE_DEVOPS, Platform.TRELLO, Platform.MONDAY,
})

def get_platform_support(backend: AgentPlatform, platform: Platform) -> tuple[bool, str]:
    """Return (is_supported, mechanism) where mechanism is 'mcp', 'api', or 'unsupported'."""
    if platform in MCP_SUPPORT.get(backend, frozenset()):
        return True, "mcp"
    if platform in API_SUPPORT:
        return True, "api"
    return False, "unsupported"
```

#### 5.2 Create Onboarding Module

**File:** `spec/onboarding/__init__.py`

```python
"""First-run onboarding for SPEC."""
from dataclasses import dataclass
from spec.config.fetch_config import AgentPlatform
from spec.config.manager import ConfigManager

@dataclass
class OnboardingResult:
    success: bool
    backend: AgentPlatform | None = None
    error_message: str = ""

def is_first_run(config: ConfigManager) -> bool:
    """Check if onboarding is needed (no backend configured)."""
    agent_config = config.get_agent_config()
    if agent_config and agent_config.platform:
        return False
    ai_backend = config.get("AI_BACKEND", "")
    return not ai_backend.strip()

def run_onboarding(config: ConfigManager) -> OnboardingResult:
    from spec.onboarding.flow import OnboardingFlow
    return OnboardingFlow(config).run()
```

#### 5.3 Create Onboarding Flow

**File:** `spec/onboarding/flow.py`

```python
"""Interactive onboarding flow implementation.

Uses existing TUI functions from spec/ui/prompts.py for consistent UX.
"""
from spec.config.fetch_config import AgentPlatform
from spec.config.manager import ConfigManager
from spec.integrations.backends.factory import BackendFactory
from spec.onboarding import OnboardingResult
from spec.ui.prompts import prompt_select, prompt_confirm
from spec.utils.console import print_header, print_info, print_success, print_error
from spec.utils.errors import UserCancelledError

BACKEND_CHOICES = [
    ("Auggie (Augment Code CLI)", AgentPlatform.AUGGIE),
    ("Claude Code CLI", AgentPlatform.CLAUDE),
    ("Cursor", AgentPlatform.CURSOR),
]

class OnboardingFlow:
    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def run(self) -> OnboardingResult:
        try:
            print_header("Welcome to SPEC!")
            print_info("Let's set up your AI provider.\n")

            # Step 1: Select backend
            backend = self._select_backend()
            if backend is None:
                return OnboardingResult(success=False, error_message="No backend selected")

            # Step 2: Verify installation
            if not self._verify_installation(backend):
                return OnboardingResult(
                    success=False, backend=backend,
                    error_message=f"{backend.value} CLI not installed"
                )

            # Step 3: Save configuration
            self._save_configuration(backend)
            print_success(f"Configuration saved. Using {backend.value}.")
            return OnboardingResult(success=True, backend=backend)
        except UserCancelledError:
            return OnboardingResult(success=False, error_message="User cancelled")

    def _select_backend(self) -> AgentPlatform | None:
        """Use TUI prompt_select for backend selection."""
        choice_names = [name for name, _ in BACKEND_CHOICES]
        selected = prompt_select(
            "Which AI provider would you like to use?",
            choices=choice_names,
        )
        for name, platform in BACKEND_CHOICES:
            if name == selected:
                return platform
        return None

    def _verify_installation(self, backend: AgentPlatform) -> bool:
        print_info(f"Checking {backend.value} installation...")
        try:
            backend_instance = BackendFactory.create(backend)
            installed, message = backend_instance.check_installed()
            if installed:
                print_success(message)
                return True
            print_error(message)
            self._show_installation_instructions(backend)
            return False
        except Exception as e:
            print(f"✗ Failed to check installation: {e}")
            return False

    def _save_configuration(self, backend: AgentPlatform) -> None:
        self._config.set("AI_BACKEND", backend.value)
        self._config.save()

    def _show_installation_instructions(self, backend: AgentPlatform) -> None:
        """Display installation instructions with links to vendor documentation."""
        docs = {
            AgentPlatform.AUGGIE: "https://docs.augmentcode.com/cli",
            AgentPlatform.CLAUDE: "https://docs.anthropic.com/claude-code",
            AgentPlatform.CURSOR: "https://www.cursor.com/cli",
        }
        url = docs.get(backend, "the vendor documentation")
        print(f"\n{backend.value} CLI is not installed.")
        print(f"See installation instructions at: {url}")
```

#### 5.4 Onboarding Design Notes

**MCP Verification:**
- NO "ask the agent if MCP works" checks during onboarding
- MCP is verified on **first real use** (ticket fetch)
- If ticket fetch fails, provide actionable error with setup instructions

**Cold-Start Latency:**
- First backend invocation may be slow (model loading, authentication)
- Onboarding warns user: "First run may take a moment..."

**Documentation URL Verification:**

> ⚠️ **Pre-Release Task:** Before shipping, verify all vendor documentation URLs are valid and point to current installation instructions:
>
> | Backend | URL | Status |
> |---------|-----|--------|
> | Auggie | `https://docs.augmentcode.com/cli` | ☐ Verify before release |
> | Claude Code | `https://docs.anthropic.com/claude-code` | ☐ Verify before release |
> | Cursor | `https://www.cursor.com/cli` | ☐ Verify before release |
>
> These URLs appear in:
> - `spec/integrations/claude.py` (docstring)
> - `spec/integrations/cursor.py` (docstring)
> - `spec/onboarding/backend_setup.py` (`_show_installation_instructions`)
> - `docs/getting-started.md` (user documentation)
>
> If URLs change, update all locations. Consider extracting URLs to a constants file for single-point maintenance.

---

### Phase 6: Rate Limit Handling (Low Risk)

#### 6.1 Abstract Rate Limit Error

**File:** `spec/integrations/backends/errors.py` (already created in Phase 1)

```python
class BackendRateLimitError(SpecError):
    """Raised when any backend indicates a rate limit error."""
    def __init__(self, message: str, output: str = "", backend_name: str = ""):
        super().__init__(message)
        self.output = output
        self.backend_name = backend_name
```

#### 6.2 Update Retry Logic

Update `spec/workflow/step3_execute.py` to use backend-specific detection:

```python
from spec.integrations.backends.errors import BackendRateLimitError

def _execute_task_with_callback(state, task, backend: AIBackend, ...):
    success, output = backend.run_with_callback(...)

    if not success and backend.detect_rate_limit(output):
        raise BackendRateLimitError(
            "Rate limit detected",
            output=output,
            backend_name=backend.name,
        )
```

---

### Phase 7: Ticket Service Integration (Medium Risk)

Update the ticket service to select the appropriate fetcher based on the configured backend.

#### 7.1 Refactor AuggieMediatedFetcher to Accept AIBackend

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

The current `AuggieMediatedFetcher` constructor expects an `AuggieClient`. This must be refactored to accept the generic `AIBackend` protocol instead, enabling all mediated fetchers to share the same interface.

**Before (current implementation):**
```python
from spec.integrations.auggie import AuggieClient

class AuggieMediatedFetcher(AgentMediatedFetcher):
    def __init__(
        self,
        auggie_client: AuggieClient,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._auggie = auggie_client
        self._config = config_manager
```

**After (refactored):**
```python
from spec.integrations.backends.base import AIBackend

class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie CLI's MCP integrations."""

    def __init__(
        self,
        backend: AIBackend,
        config_manager: ConfigManager | None = None,
    ) -> None:
        """Initialize with AI backend.

        Args:
            backend: AIBackend instance (AuggieBackend, ClaudeBackend, etc.)
            config_manager: Optional config manager for timeout settings
        """
        self._backend = backend
        self._config = config_manager
```

**Update internal method calls:**
```python
# Before:
output = self._auggie.run_print_quiet(prompt, no_session=True)

# After:
output = self._backend.run_print_quiet(prompt, dont_save_session=True)
```

**Update `_execute_fetch_prompt()` method:**
```python
async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
    """Execute fetch prompt using the injected backend."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: self._backend.run_print_quiet(prompt, dont_save_session=True)
    )
```

**Apply same pattern to ClaudeMediatedFetcher and CursorMediatedFetcher:**

All mediated fetchers should accept `backend: AIBackend` in their constructor, not their specific client type. This enables the unified `create_ticket_service()` shown in section 7.2.

#### 7.2 Update create_ticket_service()

Modify `spec/integrations/ticket_service.py`:

```python
from spec.integrations.backends.base import AIBackend
from spec.config.fetch_config import AgentPlatform


def create_ticket_service(
    config: AgentConfig,
    backend: AIBackend,
) -> TicketService:
    """Create a ticket service with the appropriate fetcher.

    Args:
        config: Agent configuration with platform and integrations
        backend: AI backend instance (required for mediated fetching)

    Returns:
        Configured TicketService instance

    Note:
        The backend platform is derived from backend.platform.
        Ticket fetching uses the actual backend instance for MCP-mediated fetching.
    """
    # Select fetcher based on backend platform (derived from backend instance)
    if backend.platform == AgentPlatform.AUGGIE:
        from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
        mediated_fetcher = AuggieMediatedFetcher(backend=backend)

    elif backend.platform == AgentPlatform.CLAUDE:
        from spec.integrations.fetchers.claude_fetcher import ClaudeMediatedFetcher
        mediated_fetcher = ClaudeMediatedFetcher(backend=backend)

    elif backend.platform == AgentPlatform.CURSOR:
        from spec.integrations.fetchers.cursor_fetcher import CursorMediatedFetcher
        mediated_fetcher = CursorMediatedFetcher(backend=backend)

    else:
        # AIDER, MANUAL - no mediated fetcher, use direct API only
        mediated_fetcher = None

    # Create direct API fetcher as fallback
    direct_fetcher = DirectAPIFetcher(config.integrations)

    # Combine with fallback logic
    if mediated_fetcher:
        fetcher = FallbackFetcher(
            primary=mediated_fetcher,
            fallback=direct_fetcher,
        )
    else:
        fetcher = direct_fetcher

    return TicketService(fetcher=fetcher, config=config)
```

#### 7.3 Update Runner to Pass Backend

Modify `spec/workflow/runner.py` to pass backend to ticket service:

```python
# When creating ticket service, pass the backend instance
ticket_service = create_ticket_service(
    config=agent_config,
    backend=ai_backend,
)
```

---

### Phase 8: Testing (Medium Risk)

**Testing Strategy:**
- **Unit tests** use mocks/fakes for backends (no external CLI required)
- **Integration tests** are optional and gated behind `SPEC_INTEGRATION_TESTS=1` environment variable
- No mandatory external CLIs in CI

#### 8.1 Create FakeBackend for Unit Testing

**File:** `tests/fakes/fake_backend.py`

Create a `FakeBackend` class that implements the `AIBackend` protocol for unit testing workflow steps without external CLI dependencies:

```python
"""Fake backend for unit testing workflow steps."""

from collections.abc import Callable
from typing import Generator

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import AIBackend


class FakeBackend:
    """A fake backend for unit testing.

    Implements the AIBackend protocol with configurable responses.
    Records all invocations for assertion in tests.

    Example usage:
        # Simple success response
        backend = FakeBackend(responses=[(True, "Task completed")])
        success, output = backend.run_with_callback(prompt, output_callback=lambda x: None)
        assert success
        assert backend.calls[0][0] == "run_with_callback"

        # Simulate rate limit then success
        backend = FakeBackend(responses=[
            (False, "Error 429: rate limit exceeded"),
            (True, "Task completed"),
        ])

        # Simulate failure
        backend = FakeBackend(responses=[(False, "Error: file not found")])
    """

    def __init__(
        self,
        responses: list[tuple[bool, str]] | None = None,
        platform: AgentPlatform = AgentPlatform.AUGGIE,
        name: str = "FakeBackend",
        supports_parallel: bool = True,
    ) -> None:
        """Initialize fake backend.

        Args:
            responses: List of (success, output) tuples to return in order.
                       If exhausted, returns (True, "") for subsequent calls.
            platform: Platform to report (defaults to AUGGIE for test convenience)
            name: Backend name to report
            supports_parallel: Whether to report parallel execution support
        """
        self._responses = list(responses) if responses else [(True, "success")]
        self._platform = platform
        self._name = name
        self._supports_parallel = supports_parallel
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def platform(self) -> AgentPlatform:
        return self._platform

    @property
    def supports_parallel(self) -> bool:
        return self._supports_parallel

    def _get_next_response(self) -> tuple[bool, str]:
        """Get next response, defaulting to success if exhausted."""
        if self._responses:
            return self._responses.pop(0)
        return True, ""

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Record call and return next configured response."""
        self.calls.append(("run_with_callback", prompt, {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
            "timeout_seconds": timeout_seconds,
        }))
        success, output = self._get_next_response()
        # Simulate streaming by calling callback with output
        if output:
            for line in output.split("\n"):
                output_callback(line)
        return success, output

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Record call and return next configured response."""
        self.calls.append(("run_print_with_output", prompt, {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
        }))
        return self._get_next_response()

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> str:
        """Record call and return output from next configured response."""
        self.calls.append(("run_print_quiet", prompt, {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
        }))
        _, output = self._get_next_response()
        return output

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Record call and return next configured response.

        Note: Returns tuple[bool, str] per Final Decision #15.
        This is NOT a generator - streaming is handled via run_with_callback.
        """
        self.calls.append(("run_streaming", prompt, {
            "subagent": subagent,
            "model": model,
            "timeout_seconds": timeout_seconds,
        }))
        return self._get_next_response()

    def check_installed(self) -> tuple[bool, str]:
        """Always report as installed for tests."""
        return True, f"{self._name} (fake) installed"

    def detect_rate_limit(self, output: str) -> bool:
        """Detect rate limit patterns in output."""
        patterns = ["rate limit", "429", "quota exceeded", "too many requests"]
        output_lower = output.lower()
        return any(p in output_lower for p in patterns)

    def supports_parallel_execution(self) -> bool:
        return self._supports_parallel

    def close(self) -> None:
        """Mark as closed for verification in tests."""
        self.closed = True


# Convenience factories for common test scenarios
def make_successful_backend(output: str = "success") -> FakeBackend:
    """Create a FakeBackend that always succeeds."""
    return FakeBackend(responses=[(True, output)])


def make_failing_backend(error: str = "error") -> FakeBackend:
    """Create a FakeBackend that always fails."""
    return FakeBackend(responses=[(False, error)])


def make_rate_limited_backend(retries_before_success: int = 1) -> FakeBackend:
    """Create a FakeBackend that simulates rate limiting."""
    responses = [(False, "Error 429: rate limit exceeded")] * retries_before_success
    responses.append((True, "success after retry"))
    return FakeBackend(responses=responses)
```

**Usage in workflow step tests:**

```python
from tests.fakes.fake_backend import FakeBackend, make_rate_limited_backend

class TestStep1CreatePlan:
    def test_successful_plan_creation(self, tmp_path):
        backend = FakeBackend(responses=[(True, "# Implementation Plan\n...")])
        state = WorkflowState(...)

        result = step_1_create_plan(state, backend)

        assert result is True
        assert len(backend.calls) == 1
        assert backend.calls[0][0] == "run_with_callback"
        assert "spec-planner" in str(backend.calls[0][2])


class TestStep3ExecuteWithRetry:
    def test_retry_on_rate_limit(self, tmp_path):
        backend = make_rate_limited_backend(retries_before_success=2)
        state = WorkflowState(...)

        # Should succeed after 2 rate limit retries
        result = _execute_task_with_retry(state, task, plan_path, backend, callback)

        assert result is True
        assert len(backend.calls) == 3  # 2 failures + 1 success
```

#### 8.2 Unit Tests for Backends (Default — No External CLI)

Create `tests/test_backends.py`:

```python
import pytest
from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.factory import BackendFactory


class TestBackendFactory:
    def test_create_auggie_backend(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.platform == AgentPlatform.AUGGIE
        assert backend.name == "Auggie"

    def test_create_claude_backend(self):
        backend = BackendFactory.create(AgentPlatform.CLAUDE)
        assert backend.platform == AgentPlatform.CLAUDE
        assert backend.name == "Claude Code"

    def test_create_cursor_backend(self):
        backend = BackendFactory.create(AgentPlatform.CURSOR)
        assert backend.platform == AgentPlatform.CURSOR
        assert backend.name == "Cursor"

    def test_create_from_string(self):
        backend = BackendFactory.create("auggie")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_unknown_backend_raises(self):
        with pytest.raises(ValueError):
            BackendFactory.create("unknown")

    def test_manual_backend_raises(self):
        with pytest.raises(ValueError, match="Manual mode"):
            BackendFactory.create(AgentPlatform.MANUAL)


class TestRateLimitDetection:
    def test_auggie_rate_limit_detection(self):
        from spec.integrations.backends.auggie import AuggieBackend
        backend = AuggieBackend()
        assert backend.detect_rate_limit("Error 429: Too many requests")
        assert not backend.detect_rate_limit("Task completed successfully")

    def test_claude_rate_limit_detection(self):
        from spec.integrations.backends.claude import ClaudeBackend
        backend = ClaudeBackend()
        assert backend.detect_rate_limit("rate limit exceeded")
        assert not backend.detect_rate_limit("Task completed successfully")

    def test_cursor_rate_limit_detection(self):
        from spec.integrations.backends.cursor import CursorBackend
        backend = CursorBackend()
        assert backend.detect_rate_limit("quota exceeded")
        assert not backend.detect_rate_limit("Task completed successfully")


class TestCompatibilityMatrix:
    def test_auggie_supports_jira_mcp(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers import Platform
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.JIRA)
        assert supported
        assert mechanism == "mcp"

    def test_auggie_supports_trello_api(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers import Platform
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.TRELLO)
        assert supported
        assert mechanism == "api"

    def test_manual_no_mcp_support(self):
        from spec.config.compatibility import get_platform_support
        from spec.integrations.providers import Platform
        supported, mechanism = get_platform_support(AgentPlatform.MANUAL, Platform.JIRA)
        assert supported  # Has API fallback
        assert mechanism == "api"


class TestOnboarding:
    def test_is_first_run_no_config(self, tmp_path):
        from spec.config.manager import ConfigManager
        from spec.onboarding.setup import is_first_run
        config = ConfigManager(config_dir=tmp_path)
        assert is_first_run(config)

    def test_is_first_run_with_config(self, tmp_path):
        from spec.config.manager import ConfigManager
        from spec.onboarding.setup import is_first_run
        config = ConfigManager(config_dir=tmp_path)
        config.set("AI_BACKEND", "auggie")
        assert not is_first_run(config)
```

#### 8.3 Integration Tests (Gated Behind Environment Variable)

Create `tests/test_backend_integration.py`:

**Note:** These tests require external CLIs to be installed. They are skipped in CI unless `SPEC_INTEGRATION_TESTS=1` is set.

```python
import os
import pytest
from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.factory import BackendFactory
from spec.integrations.backends.base import AIBackend

# Skip all integration tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled. Set SPEC_INTEGRATION_TESTS=1 to enable.",
)


@pytest.mark.parametrize("platform", [
    AgentPlatform.AUGGIE,
    AgentPlatform.CLAUDE,
    AgentPlatform.CURSOR,
])
def test_backend_protocol_compliance(platform):
    """Verify all backends implement the AIBackend protocol."""
    backend = BackendFactory.create(platform)

    # Verify it satisfies the protocol
    assert isinstance(backend, AIBackend)

    # Check required properties
    assert hasattr(backend, 'name')
    assert isinstance(backend.name, str)
    assert hasattr(backend, 'platform')
    assert isinstance(backend.platform, AgentPlatform)
    assert hasattr(backend, 'supports_parallel')
    assert isinstance(backend.supports_parallel, bool)

    # Check required methods exist and are callable
    assert callable(getattr(backend, 'run_with_callback', None))
    assert callable(getattr(backend, 'run_print_with_output', None))
    assert callable(getattr(backend, 'run_print_quiet', None))
    assert callable(getattr(backend, 'run_streaming', None))
    assert callable(getattr(backend, 'check_installed', None))
    assert callable(getattr(backend, 'detect_rate_limit', None))


@pytest.mark.parametrize("platform", [
    AgentPlatform.AUGGIE,
    AgentPlatform.CLAUDE,
    AgentPlatform.CURSOR,
])
def test_backend_check_installed(platform):
    """Verify check_installed returns valid results."""
    backend = BackendFactory.create(platform)
    installed, message = backend.check_installed()
    assert isinstance(installed, bool)
    assert isinstance(message, str)
```

---

### Phase 9: Documentation (Low Risk)

#### 9.1 Update README.md

Add section on backend selection:

```markdown
## AI Backend Selection

SPEC supports multiple AI backends:

| Backend | CLI Command | Documentation |
|---------|-------------|---------------|
| Auggie | `auggie` | [Augment CLI Docs](https://docs.augmentcode.com/cli) |
| Claude Code | `claude` | [Claude Code Docs](https://docs.anthropic.com/claude-code) |
| Cursor | `cursor` or `agent` | [Cursor CLI Docs](https://www.cursor.com/cli) |

### First-Run Setup

On first run, SPEC will guide you through selecting your AI backend:

```bash
$ spec run TICKET-123

Welcome to SPEC! Let's set up your AI provider.

Which AI provider would you like to use?
  ❯ Auggie (Augment Code CLI)
    Claude Code CLI
    Cursor
```

Your selection is saved and used for all future runs.

### Changing Backends

Via CLI flag (temporary override):
```bash
spec run TICKET-123 --backend=claude
```

Via configuration (~/.spec-config):
```
AI_BACKEND=cursor
```

### Backend Prerequisites

Each backend requires installation and authentication. See vendor documentation for current installation instructions:

- **Auggie**: [https://docs.augmentcode.com/cli](https://docs.augmentcode.com/cli)
- **Claude Code**: [https://docs.anthropic.com/claude-code](https://docs.anthropic.com/claude-code)
- **Cursor**: [https://www.cursor.com/cli](https://www.cursor.com/cli)

SPEC will verify CLI installation on first run via version detection (`--version` flag).
```

---

## File Structure Summary

```
spec/
├── onboarding/                  # NEW: First-run setup
│   ├── __init__.py
│   ├── setup.py                 # is_first_run(), run_onboarding()
│   └── flow.py                  # OnboardingFlow interactive wizard
│
├── config/
│   ├── compatibility.py         # NEW: Backend-platform compatibility matrix
│   ├── fetch_config.py          # EXISTING: AgentPlatform enum (reused)
│   └── settings.py              # MODIFY: Add ai_backend setting
│
├── integrations/
│   ├── auggie.py                # Existing (unchanged)
│   ├── claude.py                # NEW: Claude CLI wrapper
│   ├── cursor.py                # NEW: Cursor CLI wrapper
│   ├── ticket_service.py        # MODIFY: Backend-aware fetcher selection
│   ├── backends/
│   │   ├── __init__.py          # NEW: Package exports
│   │   ├── base.py              # NEW: AIBackend Protocol (uses AgentPlatform)
│   │   ├── auggie.py            # NEW: AuggieBackend implementation
│   │   ├── claude.py            # NEW: ClaudeBackend implementation
│   │   ├── cursor.py            # NEW: CursorBackend implementation
│   │   └── factory.py           # NEW: BackendFactory
│   └── fetchers/
│       ├── auggie_fetcher.py    # Existing (unchanged)
│       ├── claude_fetcher.py    # NEW: ClaudeMediatedFetcher
│       └── cursor_fetcher.py    # NEW: CursorMediatedFetcher
│
├── workflow/
│   ├── state.py                 # MODIFY: Add backend_platform (and optional backend_model/backend_name) fields
│   ├── runner.py                # MODIFY: Accept AIBackend, pass to all steps
│   ├── step1_plan.py            # MODIFY: Use AIBackend instead of AuggieClient
│   ├── step2_tasklist.py        # MODIFY: Use AIBackend instead of AuggieClient
│   ├── step3_execute.py         # MODIFY: Major refactor - pass backend through parallel execution
│   └── step4_update_docs.py     # MODIFY: Use AIBackend instead of AuggieClient
│
├── utils/
│   └── retry.py                 # MODIFY: Add BackendRateLimitError
│
└── cli.py                       # MODIFY: Add --backend option, onboarding check

tests/
├── test_backends.py             # NEW: Backend unit tests
├── test_backend_integration.py  # NEW: Protocol compliance tests
├── test_compatibility.py        # NEW: Compatibility matrix tests
└── test_onboarding.py           # NEW: Onboarding flow tests
```

---

## Design Notes

### New System — No Legacy Constraints

This is a new system with no prior releases. There are no backward compatibility requirements:

- All code paths use the new `AIBackend` protocol exclusively
- No fallback shims or wrapper code for legacy clients
- No deprecated parameters in public APIs
- `resolve_backend_platform()` is the single, explicit backend selection path

### Backend Configuration Behavior

- No default backend — users must explicitly configure one via `spec init` or `--backend` flag
- If no backend is configured, SPEC displays an error with instructions to configure one
- First-run onboarding triggers when `AI_BACKEND` is not set
- Existing `AgentPlatform` enum is reused (no new enum defined)

---

## Acceptance Criteria Checklist

### Phase 1: Backend Infrastructure
- [ ] `AIBackend` protocol defined in `spec/integrations/backends/base.py`
- [ ] `BackendRateLimitError`, `BackendNotInstalledError`, `BackendNotConfiguredError`, `BackendTimeoutError` defined in `errors.py`
- [ ] `AuggieBackend` wraps existing `AuggieClient` with protocol compliance
- [ ] `BackendFactory.create()` returns correct backend for each `AgentPlatform`
- [ ] `resolve_backend_platform()` implements correct precedence (CLI → config → error)

### Phase 2: Workflow Refactoring
- [ ] All 12+ `AuggieClient()` instantiation points replaced with backend injection
- [ ] `WorkflowState.backend_platform` stores `AgentPlatform` enum only
- [ ] `run_spec_driven_workflow()` accepts `backend: AIBackend` parameter
- [ ] `step_1_create_plan()` accepts and uses injected backend
- [ ] `step_2_create_tasklist()` accepts and uses injected backend
- [ ] `_execute_task()` and `_execute_task_with_callback()` create fresh backends via factory
- [ ] `step_4_update_docs()` accepts and uses injected backend
- [ ] Helper functions (`conflict_detection`, `autofix`, `review`) refactored
- [ ] `AuggieRateLimitError` replaced with `BackendRateLimitError` in `step3_execute.py`
- [ ] `_looks_like_rate_limit()` replaced with `backend.detect_rate_limit()` usage
- [ ] Verified: No `AI_BACKEND` string exists in codebase (grep returns 0 matches)
- [ ] Only `AI_BACKEND` used for backend configuration key

### Phase 3: Claude Backend
- [ ] `ClaudeClient` implemented in `spec/integrations/claude.py`
- [ ] `ClaudeBackend` implements `AIBackend` protocol
- [ ] `ClaudeMediatedFetcher` created for ticket fetching via MCP
- [ ] Subagent prompt loading strips YAML frontmatter

### Phase 4: Cursor Backend
- [ ] `CursorClient` implemented in `spec/integrations/cursor.py`
- [ ] `CursorBackend` implements `AIBackend` protocol with `supports_parallel = True`
- [ ] `CursorMediatedFetcher` created for ticket fetching via MCP
- [ ] Stability mechanism implemented (startup jitter + spawn retry for concurrent invocations)

### Phase 5: Onboarding
- [ ] `is_first_run()` correctly detects missing configuration
- [ ] Interactive backend selection works
- [ ] Installation verification provides actionable error messages
- [ ] Configuration persisted to `~/.spec-config`

### Phase 6: Rate Limiting
- [ ] Each backend implements `detect_rate_limit(output: str) -> bool`
- [ ] `BackendRateLimitError` raised with backend-specific context
- [ ] Retry logic in Step 3 handles rate limits for all backends

### Phase 7: Ticket Service
- [ ] `AuggieMediatedFetcher` refactored to accept `backend: AIBackend` instead of `auggie_client: AuggieClient`
- [ ] `create_ticket_service()` selects fetcher based on backend platform
- [ ] Fallback to direct API works when MCP unavailable

### Phase 8: Testing
- [ ] `FakeBackend` class created for unit testing workflow steps
- [ ] Unit tests for `BackendFactory`
- [ ] Protocol compliance tests for all backends
- [ ] Rate limit detection tests
- [ ] Onboarding flow tests
- [ ] All existing tests pass
- [ ] **Baseline behavior tests created BEFORE refactoring (Phase 0)**

### Phase 0: Baseline Behavior Tests (CRITICAL - Run Before Any Refactoring)
- [ ] Create `tests/test_baseline_auggie_behavior.py` capturing current Auggie workflow behavior
- [ ] Tests are gated behind `SPEC_INTEGRATION_TESTS=1` environment variable
- [ ] Baseline tests verify:
  - [ ] `run_with_callback()` returns `(bool, str)` with correct semantics
  - [ ] `run_print_with_output()` returns `(bool, str)` with correct semantics
  - [ ] Rate limit detection matches current `_looks_like_rate_limit()` behavior
  - [ ] Step 1 plan creation succeeds with typical ticket input
  - [ ] Step 2 tasklist creation succeeds with typical plan input
  - [ ] Step 3 parallel execution creates independent sessions
  - [ ] Step 4 documentation update works with existing patterns
- [ ] Baseline tests will fail if refactoring breaks existing behavior

### Phase 9: Documentation
- [ ] README updated with backend selection instructions
- [ ] Installation instructions for each backend CLI

---

## Success Criteria

### Core Functionality
1. ✅ `spec run TICKET-123` works when backend is configured (via `AI_BACKEND` config or `--backend` flag)
2. ✅ `spec run TICKET-123` shows clear error when no backend is configured
3. ✅ `spec run TICKET-123 --backend=claude` works with Claude Code CLI
4. ✅ `spec run TICKET-123 --backend=cursor` works with Cursor CLI
5. ✅ All existing tests pass
6. ✅ New backend tests pass

### Backend Features
6. ✅ Rate limiting works correctly for each backend
7. ✅ Parallel execution works for all backends
8. ✅ MCP ticket fetching works for all backends

### Onboarding
9. ✅ First-run triggers onboarding wizard when no config exists
10. ✅ Onboarding verifies backend CLI is installed
11. ✅ Onboarding saves configuration for future runs
12. ✅ Subsequent runs proceed without onboarding

### Multi-Platform Support
13. ✅ Users can work with Jira, Linear, and GitHub tickets with any backend
14. ✅ Direct API fallback works when MCP unavailable
15. ✅ Unsupported platform combinations show helpful error messages

---

## Recommended Implementation Order

Execute the phases in strict order. Each phase builds on the previous:

```
Phase 0: Baseline Behavior Tests (CRITICAL - DO FIRST)
    ├── Create tests/test_baseline_auggie_behavior.py
    ├── Capture current run_with_callback() semantics
    ├── Capture current run_print_with_output() semantics
    ├── Capture current rate limit detection behavior
    ├── Capture current workflow step behavior
    └── Gate behind SPEC_INTEGRATION_TESTS=1
          ↓
Phase 1: Backend Infrastructure (Low Risk)
    ├── 1.1 Backend Error Types
    ├── 1.2 AIBackend Protocol
    ├── 1.3 BaseBackend Abstract Class
    ├── 1.4 Move Subagent Constants
    ├── 1.5 AuggieBackend (extends BaseBackend)
    ├── 1.6 Backend Factory
    ├── 1.7 Backend Platform Resolver
    └── 1.8 Phase 1 Testing
          ↓
Phase 1.5: Fetcher Refactoring (Medium Risk)
    ├── 1.5.1 Update AuggieMediatedFetcher
    ├── 1.5.2 Update ticket_service.py (async preserved)
    ├── 1.5.3 Update CLI Entry Point for Ticket Fetching
    └── 1.5.4 Phase 1.5 Testing
          ↓
Phase 1.6: AI_BACKEND Removal (REQUIRED)
    ├── Update spec/config/settings.py (remove ai_backend, add ai_backend)
    ├── Update spec/config/manager.py (AI_BACKEND → AI_BACKEND)
    ├── Update spec/config/fetch_config.py (context param)
    ├── Update all tests
    ├── Update documentation
    └── Add CI guard
          ↓
Phase 2: Workflow Refactoring (Medium Risk)
    ├── 2.1 Update WorkflowState
    ├── 2.2 Update CLI Entry Point
    ├── 2.3 Delete Legacy AuggieClientProtocol
    ├── 2.4 Update Step 1 (refactor run_print() → TUI + run_streaming())
    ├── 2.5 Update Step 2
    ├── 2.6 Update Step 3 (CRITICAL - parallel execution, thread safety)
    ├── 2.7 Update Step 4
    ├── 2.8 Update Helper Files
    ├── 2.9 Validate against Instantiation Point Inventory (Section A)
    ├── 2.10 Rate Limit Error Migration
    └── 2.11 Phase 2 Testing
          ↓
Phase 3: Claude Backend + Phase 4: Cursor Backend (can be parallel)
          ↓
Phase 5: Onboarding UX
```

**Key Checkpoint:** After Phase 2, the codebase should have:
- Zero direct `AuggieClient()` instantiations
- Zero `AuggieClientProtocol` usage
- Zero `run_print()` calls (all converted to TUI + `run_streaming()`)
- All subagent constants in `spec/workflow/constants.py`
- Zero occurrences of `AI_BACKEND` string (verified via grep)
- Only `AI_BACKEND` used for backend configuration

**Verification Command:**
```bash
# Run after Phase 2 completion to verify clean state:
echo "Checking for legacy patterns..."
if grep -ri "AI_BACKEND\|AuggieClientProtocol\|run_print()" --include="*.py" . 2>/dev/null | grep -v "test_" | grep -v "__pycache__"; then
  echo "FAIL: Legacy patterns found"
  exit 1
else
  echo "PASS: No legacy patterns found"
fi
```

---

*End of Implementation Plan*
