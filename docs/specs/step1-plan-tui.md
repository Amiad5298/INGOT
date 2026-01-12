# Technical Specification: Step 1 Plan Generation TUI

## Overview

This document outlines the implementation of a TUI-style progress display for the plan generation phase in `ai_workflow/workflow/step1_plan.py`. The goal is to improve UX by hiding verbose AI output during plan creation while showing a clean progress indicator.

## Problem Statement

### Current Behavior

In `step1_plan.py`, the plan generation uses:

```python
print_step("Generating implementation plan...")
auggie_planning = AuggieClient(model=state.planning_model)
success = auggie_planning.run_print(prompt, dont_save_session=True)
```

The `run_print()` method streams all AI output directly to the terminal, creating a cluttered, hard-to-follow experience. Users see:
- Verbose AI reasoning and processing
- Long scrolling text
- Difficulty tracking overall progress

### Desired Behavior

Users should see:
- A clean progress indicator (spinner) with "Generating implementation plan..."
- AI output hidden by default but logged to a file
- Option to view detailed output if needed
- Interactive clarification phase remains unchanged

## Current Architecture Analysis

### Step 3 TUI Approach (Reference Implementation)

**Location:** `ai_workflow/workflow/step3_execute.py`

Step 3 handles **multiple discrete tasks**, using:

1. **`TaskRunnerUI`** (`ai_workflow/ui/tui.py`)
   - Rich `Live` display with panels
   - Task list panel showing progress
   - Log panel showing output tail
   - Keyboard navigation (↑↓, f=follow, v=verbose, q=quit)

2. **`TaskLogBuffer`** (`ai_workflow/ui/log_buffer.py`)
   - Memory-efficient log storage
   - Writes to disk, keeps N lines in memory
   - Used for real-time log display

3. **`AuggieClient.run_with_callback()`**
   - Streams output line-by-line to callback
   - Returns `(success: bool, full_output: str)`

4. **Event System** (`ai_workflow/workflow/events.py`)
   - `TaskEvent`, `TaskEventType` for communication
   - `TaskRunRecord`, `TaskRunStatus` for state tracking

### Step 1 Differences

Step 1 has **single long-running task** characteristics:
- One plan generation (typically 30-120 seconds)
- No task list to display
- Single output stream
- Optional interactive clarification phase afterward

## Proposed Solution

### Option A: Simplified Single-Task TUI (Recommended)

Create a new lightweight `PlanGeneratorUI` component specifically for single long-running operations.

#### Key Characteristics

1. **Single panel layout** instead of task list + log panel
2. **Simple spinner** with status message
3. **Log capture** to file for debugging
4. **Optional verbose mode** to show AI output inline
5. **Reusable** for other single-task operations

### Option B: Minimal Progress Indicator

Use Rich's `Progress` or `Status` directly without custom TUI class.

- Simplest approach
- Less control over keyboard input
- Limited log viewing capability

**Recommendation:** Option A provides better UX and follows established patterns.

---

## Detailed Design

### New Component: `PlanGeneratorUI`

**Location:** `ai_workflow/ui/plan_tui.py`

```python
@dataclass
class PlanGeneratorUI:
    """TUI for single long-running operations like plan generation.
    
    Features:
    - Spinner with status message
    - Log capture to file
    - Optional verbose mode to show output
    - Keyboard controls (v=toggle verbose, q=quit)
    """
    status_message: str = "Processing..."
    log_buffer: TaskLogBuffer | None = None
    verbose_mode: bool = False
    _live: Live | None = None
```

### UI Layout

The UI includes a **liveness indicator** - a dimmed line showing the latest AI output - to prevent users from thinking the application is frozen during long generation times.

```
┌─────────────────────────────────────────────────────────────────┐
│  ⟳ Generating implementation plan...                    1m 23s │
│                                                                 │
│  [dim]► Analyzing codebase structure and identifying key comp… │
│                                                                 │
│  [dim]Logs: .ai_workflow/runs/TICKET-123/plan_generation.log   │
└─────────────────────────────────────────────────────────────────┘
[v] Toggle verbose  [Enter] View log  [q] Cancel

# When verbose mode is enabled:
┌─────────────────────────────────────────────────────────────────┐
│  ⟳ Generating implementation plan...                    1m 23s │
├─────────────────────────────────────────────────────────────────┤
│  Creating implementation plan for ticket SOF-123...             │
│  Analyzing requirements...                                      │
│  Identifying key components...                                  │
│  [more output lines...]                                         │
└─────────────────────────────────────────────────────────────────┘
[v] Toggle verbose  [Enter] View log  [q] Cancel
```

**Liveness Indicator Details:**
- Shows the most recent AI output line, truncated with `…` if too long
- Prefixed with `►` to indicate activity
- Styled as dim text to avoid visual clutter
- Updates in real-time as new output arrives
- Provides visual feedback that the AI is actively working

### Integration with Step 1

```python
def step_1_create_plan(state: WorkflowState, auggie: AuggieClient) -> bool:
    # ... existing setup ...
    
    print_step("Generating implementation plan...")
    plan_path = state.get_plan_path()
    prompt = _build_plan_prompt(state)
    
    # Determine TUI mode
    from ai_workflow.ui.tui import _should_use_tui
    
    if _should_use_tui():
        success = _generate_plan_with_tui(state, prompt, plan_path)
    else:
        success = _generate_plan_fallback(state, prompt)
    
    # ... rest of function unchanged ...
```

### New Helper Functions

```python
def _generate_plan_with_tui(
    state: WorkflowState, 
    prompt: str, 
    plan_path: Path
) -> bool:
    """Generate plan with TUI progress display."""
    from ai_workflow.ui.plan_tui import PlanGeneratorUI
    
    # Create log directory
    log_dir = _create_plan_log_dir(state.ticket.ticket_id)
    log_path = log_dir / "plan_generation.log"
    
    ui = PlanGeneratorUI(
        status_message="Generating implementation plan...",
        ticket_id=state.ticket.ticket_id,
    )
    ui.set_log_path(log_path)
    
    auggie_planning = AuggieClient(model=state.planning_model)
    
    with ui:
        success, output = auggie_planning.run_with_callback(
            prompt,
            output_callback=ui.handle_output_line,
            dont_save_session=True,
        )
    
    ui.print_summary(success)
    return success


def _generate_plan_fallback(state: WorkflowState, prompt: str) -> bool:
    """Generate plan with simple line-based output (non-TUI mode)."""
    auggie_planning = AuggieClient(model=state.planning_model)
    return auggie_planning.run_print(prompt, dont_save_session=True)
```

---

## Implementation Plan

### Phase 1: Create PlanGeneratorUI Component

**File:** `ai_workflow/ui/plan_tui.py`

| Step | Description | Effort |
|------|-------------|--------|
| 1.1 | Create `PlanGeneratorUI` dataclass with basic state | Small |
| 1.2 | Implement `_render_layout()` - spinner panel | Medium |
| 1.3 | Implement `start()`/`stop()` with Rich Live | Small |
| 1.4 | Add `handle_output_line()` callback method | Small |
| 1.5 | Integrate `TaskLogBuffer` for log capture | Small |
| 1.6 | Add keyboard handling (v, Enter, q) | Medium |
| 1.7 | Implement verbose mode toggle | Small |
| 1.8 | Add `print_summary()` method | Small |

### Phase 2: Integrate with Step 1

**File:** `ai_workflow/workflow/step1_plan.py`

| Step | Description | Effort |
|------|-------------|--------|
| 2.1 | Add `_generate_plan_with_tui()` function | Medium |
| 2.2 | Add `_generate_plan_fallback()` function | Small |
| 2.3 | Add `_create_plan_log_dir()` helper | Small |
| 2.4 | Modify `step_1_create_plan()` to use TUI | Small |
| 2.5 | Update imports | Small |

### Phase 3: Testing

| Step | Description | Effort |
|------|-------------|--------|
| 3.1 | Unit tests for `PlanGeneratorUI` | Medium |
| 3.2 | Integration test for step 1 with TUI mode | Medium |
| 3.3 | Manual testing in TTY and non-TTY environments | Medium |

---

## Component Details

### PlanGeneratorUI Class Structure

```python
@dataclass
class PlanGeneratorUI:
    """TUI for single long-running operations.

    Supports context manager protocol for use with `with` statement:

        with PlanGeneratorUI(status_message="Generating...") as ui:
            success, output = auggie.run_with_callback(
                prompt, output_callback=ui.handle_output_line
            )
    """

    # Configuration
    status_message: str = "Processing..."
    ticket_id: str = ""
    verbose_mode: bool = False

    # Internal state
    _log_buffer: TaskLogBuffer | None = field(default=None, init=False)
    _log_path: Path | None = field(default=None, init=False)
    _live: Live | None = field(default=None, init=False)
    _start_time: float = field(default=0.0, init=False)
    _keyboard_reader: KeyboardReader = field(default_factory=KeyboardReader, init=False)
    _stop_requested: bool = field(default=False, init=False)
    _latest_output_line: str = field(default="", init=False)  # For liveness indicator

    def set_log_path(self, path: Path) -> None:
        """Set log file path and create buffer."""

    def handle_output_line(self, line: str) -> None:
        """Callback for AI output lines.

        Called for each line of AI output. This method:
        1. Writes the line to the log buffer (file + memory)
        2. Updates the liveness indicator with the latest line (truncated)
        3. Triggers a display refresh to show the updated liveness text

        Args:
            line: A single line of AI output (without trailing newline).
        """

    def start(self) -> None:
        """Start the TUI display and keyboard input handling."""

    def stop(self) -> None:
        """Stop the TUI display and keyboard input handling."""

    def __enter__(self) -> "PlanGeneratorUI":
        """Context manager entry - starts the TUI display.

        Returns:
            self for use in `with ... as ui:` pattern.
        """
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - stops the TUI display.

        Ensures cleanup even if an exception occurs during execution.
        """
        self.stop()

    def _render_layout(self) -> Group:
        """Render the TUI layout including liveness indicator."""

    def _input_loop(self) -> None:
        """Background thread for keyboard input."""

    def print_summary(self, success: bool) -> None:
        """Print summary after completion."""
```

### Keyboard Controls

| Key | Action | Description |
|-----|--------|-------------|
| `v` | Toggle verbose | Show/hide AI output in log panel |
| `Enter` | Open log | Open full log in system pager |
| `q` | Cancel | Stop plan generation (with confirmation) |

### Log File Location

Logs will be stored alongside task execution logs:

```
.ai_workflow/runs/
└── TICKET-123/
    ├── 20260111_143000/           # Step 3 run
    │   ├── task_001_implement.log
    │   └── task_002_test.log
    └── plan_generation/           # Step 1 logs
        └── 20260111_142500.log
```

---

## Clarification Phase Handling

The clarification phase (`_run_clarification()`) should remain **unchanged**:

- It uses interactive `auggie_planning.run_print()` which requires user input
- Users need to see AI questions and type responses
- This is intentionally NOT hidden behind TUI

```python
# Clarification remains interactive (line 165)
success = auggie_planning.run_print(prompt)  # No changes needed
```

---

## Fallback Behavior

For non-TTY environments (CI, piped output):

1. Detect using `_should_use_tui()` (already exists in `ai_workflow/ui/tui.py`)
2. Fall back to current `run_print()` behavior
3. This ensures backward compatibility

---

## Configuration Options

### CLI Flags (Optional Enhancement)

```python
# In ai_workflow/cli.py
verbose: Annotated[
    bool,
    typer.Option(
        "--verbose", "-v",
        help="Show verbose AI output during plan generation",
    ),
] = False
```

### Environment Variable

```bash
AI_WORKFLOW_TUI=false  # Disable TUI globally
AI_WORKFLOW_TUI=true   # Force TUI even in non-TTY
AI_WORKFLOW_TUI=auto   # Auto-detect (default)
```

---

## Potential Challenges & Mitigations

### Challenge 1: Keyboard Input Conflicts

**Issue:** Reading keyboard during AI execution may interfere with subprocess.

**Mitigation:**
- AI subprocess uses `stdin=subprocess.DEVNULL` (already implemented in `run_with_callback`)
- Keyboard reader operates on parent process stdin only

### Challenge 2: Long Running Operations

**Issue:** Plan generation can take 2+ minutes.

**Mitigation:**
- Display elapsed time in spinner panel
- Allow user to cancel with 'q'
- Show progress via log line count

### Challenge 3: AI Output Parsing

**Issue:** Some AI output may need to be parsed for plan file creation.

**Mitigation:**
- `run_with_callback` already returns full output in tuple
- Output is still captured even when not displayed
- `_save_plan_from_output()` continues to work

---

## Success Criteria

1. ✅ Clean spinner display during plan generation
2. ✅ Verbose AI output hidden by default
3. ✅ Toggle verbose mode with 'v' key
4. ✅ Logs saved to file for debugging
5. ✅ Clarification phase remains interactive
6. ✅ Falls back gracefully in non-TTY environments
7. ✅ Plan file created correctly (functionality unchanged)

---

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Phase 1: PlanGeneratorUI | 4-6 hours |
| Phase 2: Step 1 Integration | 2-3 hours |
| Phase 3: Testing | 2-3 hours |
| **Total** | **8-12 hours** |

---

## Appendix: Code References

### Key Files

| File | Purpose |
|------|---------|
| `ai_workflow/workflow/step1_plan.py` | Plan generation step (to modify) |
| `ai_workflow/workflow/step3_execute.py` | Reference implementation with TUI |
| `ai_workflow/ui/tui.py` | Existing TUI components |
| `ai_workflow/ui/log_buffer.py` | Log capture utility |
| `ai_workflow/ui/keyboard.py` | Keyboard input handler |
| `ai_workflow/integrations/auggie.py` | AI client with callback support |

### Existing Methods to Reuse

- `AuggieClient.run_with_callback()` - Already supports output callback
- `TaskLogBuffer` - Can be reused as-is
- `KeyboardReader` - Can be reused as-is
- `_should_use_tui()` - Already exists for TUI detection
- `format_run_directory()` - For log directory naming

