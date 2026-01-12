# Step 3 TUI Specification

## Problem Statement

### Current UX Pain

The current Step 3 executor (`ai_workflow/workflow/step3_execute.py`) uses `AuggieClient.run_print_with_output()` which prints the full AI agent output directly to the terminal. When executing multiple tasks, users experience:

1. **Information Overload**: Thousands of lines of AI reasoning, tool calls, and file edits flood the terminal
2. **Lost Progress Context**: Users cannot see which tasks are done, running, or pending without scrolling through extensive output
3. **No Navigation**: Cannot jump to a specific task's output or review completed task logs
4. **No Status Overview**: Current task index (`[3/10] task name`) quickly scrolls off screen
5. **Difficult Debugging**: When a task fails, relevant error context is buried in verbose output

### User Impact

- Developers lose confidence in workflow progress
- Debugging failures requires manual log file review
- Multitasking is impossible (must watch terminal constantly)
- Terminal history exhausted by single workflow run

---

## User Stories / UX Requirements

### Must Have

1. **US-1**: As a developer, I want to see a persistent status panel showing all tasks (pending/running/success/failed) so I know workflow progress at a glance
2. **US-2**: As a developer, I want verbose AI output captured to log files (not terminal) so I can review them on-demand
3. **US-3**: As a developer, I want to navigate to any task and view its logs so I can debug issues
4. **US-4**: As a developer, I want to see real-time log tail for the currently running task so I can monitor progress
5. **US-5**: As a CI/CD system, I need fallback behavior that preserves current output when TTY is unavailable

### Nice to Have

6. **US-6**: As a developer, I want to toggle between compact view (status only) and verbose view (with log panel)
7. **US-7**: As a developer, I want keyboard shortcuts to navigate tasks and toggle log following

---

## Proposed TUI Design

### Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 3: Execute Implementation                    [TICK-123] [3/10 tasks]   │
├─────────────────────────────────────────────────────────────────────────────┤
│ TASKS                                                                       │
│  ✓ Implement user authentication module                              [1.2s]│
│  ✓ Add password validation                                           [0.8s]│
│  ⟳ Create login endpoint ← Running                                   [12s] │
│  ○ Add session management                                                   │
│  ○ Write unit tests for auth module                                         │
│  ○ Update API documentation                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ LOG OUTPUT (Task 3: Create login endpoint)                    [f] follow    │
│─────────────────────────────────────────────────────────────────────────────│
│ [12:34:56] Using codebase-retrieval to find existing patterns...            │
│ [12:34:58] Found auth patterns in services/auth/base.py                     │
│ [12:35:01] Creating file: api/endpoints/login.py                            │
│ [12:35:03] Adding route handler for POST /login...                          │
│ █                                                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ [↑↓] Navigate  [Enter] View logs  [f] Follow  [v] Verbose  [q] Quit         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Status States

| State      | Symbol | Color       | Description                    |
|------------|--------|-------------|--------------------------------|
| `Pending`  | `○`    | dim white   | Not yet started                |
| `Running`  | `⟳`    | bold cyan   | Currently executing (animated) |
| `Success`  | `✓`    | bold green  | Completed successfully         |
| `Failed`   | `✗`    | bold red    | Execution failed               |
| `Skipped`  | `⊘`    | yellow      | Skipped due to fail_fast       |

### Keyboard Controls

| Key       | Action                                           |
|-----------|--------------------------------------------------|
| `↑` / `k` | Move selection up                                |
| `↓` / `j` | Move selection down                              |
| `Enter`   | Open full log for selected task (less/pager)     |
| `f`       | Toggle log follow mode (auto-scroll)             |
| `v`       | Toggle verbose mode (show/hide log panel)        |
| `l`       | Show log file path for selected task             |
| `q`       | Quit TUI (prompts if tasks still running)        |
| `Ctrl+C`  | Abort current task (with confirmation)           |

### Default vs On-Demand Content

**Shown by Default:**
- Task list with status icons
- Current task name and elapsed time
- Last 10-15 lines of current task's log (tail)
- Overall progress indicator

**Available On-Demand:**
- Full task log (via `Enter` to open pager)
- Log file paths (via `l` key)
- Verbose mode with expanded log panel

---

## Technical Design

### Event Model

Task execution will emit events that the TUI can consume:

```python
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

class TaskEventType(Enum):
    TASK_STARTED = "task_started"
    TASK_OUTPUT = "task_output"       # Streaming output line
    TASK_FINISHED = "task_finished"
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"

@dataclass
class TaskEvent:
    event_type: TaskEventType
    task_index: int
    task_name: str
    timestamp: float
    data: Optional[dict] = None  # success, output_line, duration, etc.

# Callback type for event consumers
TaskEventCallback = Callable[[TaskEvent], None]
```

### Capturing Agent Output Without Flooding Terminal

**Current Problem**: `AuggieClient.run()` uses `subprocess.run()` which either:
- Prints to terminal directly (`capture_output=False`)
- Blocks until completion (`capture_output=True`)

**Solution**: Add a streaming callback mode to `AuggieClient`:

```python
def run_with_callback(
    self,
    prompt: str,
    *,
    output_callback: Callable[[str], None],
    model: Optional[str] = None,
    dont_save_session: bool = False,
) -> tuple[bool, str]:
    """Run command with streaming output callback.

    Uses subprocess.Popen with line-by-line output processing.
    Each line is passed to output_callback AND collected for return.

    Returns:
        Tuple of (success, full_output)
    """
    cmd = self._build_command(prompt, model, print_mode=True)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
    )

    output_lines = []
    for line in process.stdout:
        output_callback(line.rstrip('\n'))
        output_lines.append(line)

    process.wait()
    return process.returncode == 0, ''.join(output_lines)
```

### Per-Task Log Storage

**Directory Structure:**
```
.ai_workflow/
└── runs/
    └── <ticket_id>/
        └── <timestamp>/
            ├── run.log           # Overall run log
            ├── task_001_implement_auth.log
            ├── task_002_add_validation.log
            └── task_003_create_endpoint.log
```

**Naming Convention:**
- `task_{index:03d}_{slug}.log` where `slug` = task name slugified (max 40 chars)
- Timestamp format: `YYYYMMDD_HHMMSS`

**Retention:**
- Keep last 10 runs per ticket (configurable via `AI_WORKFLOW_LOG_RETENTION`)
- Clean up older runs at start of new run

**Log Format:**
```
[2026-01-11 12:34:56.123] [INFO] Task started: Create login endpoint
[2026-01-11 12:34:56.456] [AGENT] Using codebase-retrieval to find existing patterns...
[2026-01-11 12:34:58.789] [AGENT] Found auth patterns in services/auth/base.py
...
[2026-01-11 12:35:45.123] [INFO] Task completed successfully (duration: 48.7s)
```


### Memory Usage Strategy

**Problem**: Keeping full task output in RAM could exhaust memory for long-running tasks.

**Solution**: Sliding window buffer with file backing:

```python
@dataclass
class TaskLogBuffer:
    """Memory-efficient log buffer with file backing."""

    log_path: Path
    tail_lines: int = 100  # Lines kept in RAM
    _buffer: collections.deque = field(default_factory=lambda: collections.deque(maxlen=100))
    _file_handle: Optional[TextIO] = None

    def write(self, line: str) -> None:
        """Write line to file and update in-memory tail."""
        self._ensure_file_open()
        self._file_handle.write(f"{line}\n")
        self._file_handle.flush()
        self._buffer.append(line)

    def get_tail(self, n: int = 15) -> list[str]:
        """Get last n lines from in-memory buffer."""
        return list(self._buffer)[-n:]

    def close(self) -> None:
        """Close file handle."""
        if self._file_handle:
            self._file_handle.close()
```

### Integration with AuggieClient

**Required Changes to `ai_workflow/integrations/auggie.py`:**

1. **Add `_build_command()` helper** to DRY up command construction
2. **Add `run_with_callback()` method** for streaming output with callback
3. **Keep existing methods unchanged** for backward compatibility

```python
class AuggieClient:
    def _build_command(
        self,
        prompt: str,
        model: Optional[str] = None,
        print_mode: bool = False,
        quiet: bool = False,
        dont_save_session: bool = False,
    ) -> list[str]:
        """Build auggie command list."""
        cmd = ["auggie"]

        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if dont_save_session:
            cmd.append("--dont-save-session")
        if print_mode:
            cmd.append("--print")
        if quiet:
            cmd.append("--quiet")

        cmd.append(prompt)
        return cmd

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: Optional[str] = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Each output line is passed to callback AND written to return value.
        """
        cmd = self._build_command(
            prompt,
            model=model,
            print_mode=True,
            dont_save_session=dont_save_session
        )

        log_message(f"Running auggie command with callback: {' '.join(cmd[:3])}...")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        output_lines = []
        for line in process.stdout:
            stripped = line.rstrip('\n')
            output_callback(stripped)
            output_lines.append(line)

        process.wait()
        log_command(" ".join(cmd), process.returncode)

        return process.returncode == 0, ''.join(output_lines)
```

### Integration with Console Utilities

**New module: `ai_workflow/ui/tui.py`**

Uses Rich's Live display and Layout for the TUI:

```python
from rich.console import Console, Group
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
```

**Integration Points:**
- Reuse existing `console` instance from `ai_workflow.utils.console`
- Reuse theme colors defined in `custom_theme`
- Status icons match existing emoji patterns (✓, ✗, etc.)

### Configuration / Flags

**CLI Flags (in `ai_workflow/cli.py`):**

```python
tui: Annotated[
    bool,
    typer.Option(
        "--tui/--no-tui",
        help="Enable/disable TUI mode (default: auto-detect TTY)",
    ),
] = None  # None = auto-detect

verbose: Annotated[
    bool,
    typer.Option(
        "--verbose", "-V",
        help="Show verbose output in TUI log panel",
    ),
] = False
```

**Environment Variables:**

| Variable                    | Default    | Description                          |
|-----------------------------|------------|--------------------------------------|
| `AI_WORKFLOW_TUI`           | `auto`     | `true`, `false`, or `auto`           |
| `AI_WORKFLOW_LOG_DIR`       | `.ai_workflow/runs` | Base directory for logs     |
| `AI_WORKFLOW_LOG_RETENTION` | `10`       | Number of runs to keep per ticket    |
| `AI_WORKFLOW_LOG_TAIL`      | `100`      | Lines to keep in memory buffer       |

### Error Handling

**Agent Crash:**
- Catch exception in task runner
- Mark task as `Failed`
- Write exception to task log
- Continue to next task (unless `fail_fast=True`)

**Task Failure (non-zero exit):**
- Mark task as `Failed`
- Show failure icon in task list
- Highlight task row in red
- Continue to next task (unless `fail_fast=True`)

**fail_fast Behavior:**
- When enabled: stop execution, mark remaining tasks as `Skipped`
- Show summary with skip count
- Existing behavior preserved

**UI Exit (q key):**
- If task running: prompt "Task in progress. Abort?"
- If confirmed: send SIGTERM to subprocess, mark as `Failed`
- Clean up log files (keep partial logs)

**Ctrl+C Handling:**
- Graceful shutdown: finish writing current log line
- Save partial progress to log
- Show message: "Interrupted. Logs saved to: <path>"

### Cross-Platform Notes

**macOS/Linux:**
- Full TUI support with Unicode symbols
- ANSI colors work in standard terminals

**Windows:**
- Rich handles Windows console mode automatically
- Unicode symbols may need fallback (`[x]` instead of `✓`)
- Test in cmd.exe, PowerShell, and Windows Terminal

**CI/Non-TTY Environments:**
- Auto-detect via `sys.stdout.isatty()`
- Fallback to current behavior (print to stdout)
- Still write log files for artifact collection

---

## Fallback Mode (Non-Interactive / CI)

When TTY is not detected or `--no-tui` is specified:

1. **Output**: Print directly to stdout (current behavior)
2. **Progress**: Simple line-based progress: `[3/10] Running: Create login endpoint`
3. **Logs**: Still write per-task log files
4. **Summary**: Print log directory path at end

```python
def _should_use_tui() -> bool:
    """Determine if TUI should be used."""
    env_setting = os.environ.get("AI_WORKFLOW_TUI", "auto").lower()

    if env_setting == "true":
        return True
    elif env_setting == "false":
        return False
    else:  # auto
        return sys.stdout.isatty()
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] **AC-1**: Task list shows all tasks with correct status icons (pending/running/success/failed)
- [ ] **AC-2**: Currently running task is visually highlighted with spinner animation
- [ ] **AC-3**: Log panel shows last 15 lines of current task output in real-time
- [ ] **AC-4**: Arrow keys navigate task selection
- [ ] **AC-5**: Enter key opens full log in system pager
- [ ] **AC-6**: `f` key toggles log follow mode
- [ ] **AC-7**: `q` key exits TUI with confirmation if task running
- [ ] **AC-8**: Per-task logs are written to `.ai_workflow/runs/<ticket>/<timestamp>/`
- [ ] **AC-9**: Log file paths are printed at run completion
- [ ] **AC-10**: Fallback mode works in non-TTY (CI) environments
- [ ] **AC-11**: Existing task semantics preserved (ordering, fail_fast, marking complete)

### Non-Functional Requirements

- [ ] **AC-12**: Memory usage stays under 50MB for log buffers (100-line tail per task)
- [ ] **AC-13**: TUI refresh rate ≤ 10Hz to avoid CPU overhead
- [ ] **AC-14**: No blocking I/O in main event loop
- [ ] **AC-15**: Clean shutdown on SIGINT/SIGTERM

---

## Testing Plan

### Unit Tests

1. **TaskLogBuffer**: Test write, tail retrieval, file creation, memory bounds
2. **TaskEvent**: Test event creation and serialization
3. **run_with_callback**: Mock subprocess, verify callback invocation per line
4. **_should_use_tui**: Test env var and TTY detection combinations

### Integration Tests

1. **Full TUI render**: Use Rich's `Console(force_terminal=True, record=True)` to capture output
2. **Event flow**: Execute mock tasks, verify event sequence
3. **Log file creation**: Verify directory structure and file contents
4. **Fallback mode**: Test with `force_terminal=False`

### Manual Test Scenarios

| Scenario                        | Expected Result                                    |
|---------------------------------|----------------------------------------------------|
| Run with 5 tasks, all succeed   | All show ✓, logs created, summary printed          |
| Run with task 3 failing         | Task 3 shows ✗, continues to task 4-5              |
| Run with fail_fast + failure    | Stops at failure, remaining show ⊘ (skipped)       |
| Press q during task execution   | Prompts confirmation, aborts if yes                |
| Run in CI (no TTY)              | Fallback output, logs still created                |
| Press Enter on completed task   | Opens full log in less/pager                       |
| Navigate with arrow keys        | Selection moves, log panel updates                 |

---

## Implementation Plan

### Phase 1: Foundation (New Modules)

**Step 1.1: Create TaskLogBuffer class**
- File: `ai_workflow/ui/log_buffer.py`
- Implements memory-efficient log storage with file backing
- Provides `write()`, `get_tail()`, `close()` methods

**Step 1.2: Create TaskEvent and TaskEventType**
- File: `ai_workflow/workflow/events.py`
- Define event types and dataclass
- Define `TaskEventCallback` type alias

**Step 1.3: Create TaskRunRecord**
- File: `ai_workflow/workflow/events.py`
- Tracks per-task state: status, start_time, duration, log_buffer, error

### Phase 2: AuggieClient Enhancement

**Step 2.1: Add `_build_command()` helper**
- File: `ai_workflow/integrations/auggie.py`
- Extract command building from `run()` method
- Internal helper, not exported

**Step 2.2: Add `run_with_callback()` method**
- File: `ai_workflow/integrations/auggie.py`
- Uses `subprocess.Popen` with line-by-line streaming
- Calls callback for each output line
- Returns `(success, full_output)` tuple

**Step 2.3: Add unit tests**
- File: `tests/test_auggie.py`
- Test callback invocation, error handling

### Phase 3: TUI Implementation

**Step 3.1: Create TUI layout components**
- File: `ai_workflow/ui/tui.py`
- `TaskListPanel`: Renders task list with status icons
- `LogPanel`: Renders log tail with scroll
- `StatusBar`: Renders keyboard shortcuts and progress

**Step 3.2: Create TaskRunnerUI class**
- File: `ai_workflow/ui/tui.py`
- Manages Rich Live display
- Handles keyboard input (via threading or Rich's built-in)
- Orchestrates layout updates

**Step 3.3: Implement event handlers**
- Connect TaskEvents to UI updates
- Update task status, log panel on events

### Phase 4: Step 3 Executor Integration

**Step 4.1: Add log directory management**
- File: `ai_workflow/workflow/step3_execute.py`
- Create run directory with timestamp
- Implement retention cleanup

**Step 4.2: Modify `_execute_task()` to use callback**
- Replace `run_print_with_output()` with `run_with_callback()`
- Pass callback that writes to TaskLogBuffer and emits events

**Step 4.3: Add TUI orchestration in `step_3_execute()`
- Initialize TaskRunnerUI if TTY detected
- Start Live display before task loop
- Stop Live display after loop

**Step 4.4: Preserve fallback mode**
- Check `_should_use_tui()`
- If false, use current `run_print_with_output()` behavior
- Still write log files in fallback mode

### Phase 5: CLI Integration

**Step 5.1: Add `--tui/--no-tui` flag**
- File: `ai_workflow/cli.py`
- Pass to `step_3_execute()` via state or parameter

**Step 5.2: Add `--verbose` flag**
- Controls initial TUI mode (compact vs expanded log panel)

### Phase 6: Testing & Polish

**Step 6.1: Unit tests for all new modules**
**Step 6.2: Integration tests for TUI rendering**
**Step 6.3: Manual testing on macOS, Linux, Windows**
**Step 6.4: Documentation updates**

---

## Risk Areas and Mitigations

| Risk                                   | Mitigation                                                |
|----------------------------------------|-----------------------------------------------------------|
| Rich TUI compatibility issues          | Test early on target platforms; use fallback for edge cases |
| Subprocess output buffering            | Use `bufsize=1` and explicit flush                        |
| Memory growth for many tasks           | Fixed-size deque in TaskLogBuffer                         |
| Keyboard input blocking main thread    | Use threading or async for input handling                 |
| Breaking existing CI workflows         | Fallback mode preserves current behavior                  |
| AuggieClient API changes               | Add new method without modifying existing ones            |

---

## Dependencies

**Existing (no changes):**
- `rich>=13.0.0` - Already in pyproject.toml

**No new dependencies required.** The implementation uses Rich's existing Live, Layout, Panel, and Table components.

---

## Out of Scope

- Web-based dashboard
- Persistent task history database
- Real-time collaboration features
- Custom log viewers (use system pager)
- Changes to task semantics or fail_fast logic
- Automatic retry loops (per optimistic execution philosophy)

