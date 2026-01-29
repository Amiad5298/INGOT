# Pluggable Multi-AI-Backend Support

## Overview

This document outlines the implementation plan for extending SPEC to support multiple AI backends beyond Auggie. The goal is to add support for **Claude Code CLI** and **Cursor CLI** as alternative backends while maintaining identical workflow behavior.

### Key Principle

> **The behavior of the code should be the same.** We only need to modify the architecture to support multiple AI providers. All prompts, MCP integrations, workflow steps, TUI, and task parsing remain unchanged.

### Naming Convention

To avoid confusion with the existing "subagent" system (`.augment/agents/*.md` prompt files), we use:
- **`AIBackend`** - Refers to the AI provider/service (Auggie, Claude Code, Cursor)
- **Subagent** - Refers to specialized prompt personas (spec-planner, spec-implementer, etc.)

---

## Architecture

### Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Workflow Steps  →  AuggieClient  →  Auggie CLI                 │
│  (step1, step2,      (subprocess      (auggie command)          │
│   step3, step4)       wrapper)                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                    ┌→ AuggieClient → Auggie CLI │
│  Workflow Steps  →  AIBackend ─────┼→ ClaudeClient → Claude CLI │
│                                    └→ CursorClient → Cursor CLI │
└─────────────────────────────────────────────────────────────────┘
```

### What Changes

| Component | Change Required |
|-----------|-----------------|
| `AIBackend` interface | **NEW** - Abstract base class |
| `AuggieBackend` | **NEW** - Wraps existing `AuggieClient` |
| `ClaudeClient` | **NEW** - Subprocess wrapper for Claude CLI |
| `ClaudeBackend` | **NEW** - Implements `AIBackend` |
| `CursorClient` | **NEW** - Subprocess wrapper for Cursor CLI |
| `CursorBackend` | **NEW** - Implements `AIBackend` |
| `BackendFactory` | **NEW** - Creates backend from config |
| `runner.py` | **MODIFY** - Accept `AIBackend` parameter |
| `step*.py` files | **MODIFY** - Use `AIBackend` instead of `AuggieClient` |
| Config/CLI | **MODIFY** - Add `--backend` option |

### What Stays The Same

| Component | Reason |
|-----------|--------|
| Subagent prompts (`.augment/agents/*.md`) | Generic, reusable across all backends |
| Workflow step logic | Backend-agnostic orchestration |
| MCP integrations (Jira, Linear, GitHub) | All backends support MCP |
| TUI and output handling | Uses callback pattern all backends support |
| Task parsing and execution | Backend-agnostic |
| Parallel execution logic | Works with any backend |

---

## Backend Capabilities

All three backends support the required capabilities:

| Capability | Auggie CLI | Claude Code CLI | Cursor CLI |
|------------|------------|-----------------|------------|
| Custom system prompts | ✅ Via prompt prepending | ✅ `--system-prompt` | ✅ `--system-prompt` |
| Codebase context retrieval | ✅ `codebase-retrieval` | ✅ Built-in | ✅ Built-in |
| Session isolation | ✅ `--dont-save-session` | ✅ Default (fresh session each run) | ✅ Default (isolated by default) |
| MCP integrations | ✅ Jira, Linear, GitHub | ✅ MCP support | ✅ MCP support |
| Streaming output | ✅ Line-by-line | ✅ Line-by-line | ✅ Line-by-line |
| Non-interactive mode | ✅ `--print` | ✅ `--print` | ✅ `-p` |

**Session Isolation Notes:**
- **Auggie**: Requires explicit `--dont-save-session` flag to isolate execution
- **Claude Code CLI**: Each execution starts a fresh session by default (history archived but context is clean). Use `-c`/`--continue` to maintain context across runs
- **Cursor CLI**: Interactions are isolated by default in Agent mode. New Chat (Cmd+L) provides isolation in IDE mode

---

## Subagent Prompt Reusability

The existing subagent prompts in `.augment/agents/` are **generic and reusable across all backends**:

- `spec-planner.md` - Creates implementation plans
- `spec-tasklist.md` - Generates task lists
- `spec-tasklist-refiner.md` - Extracts tests to independent tasks
- `spec-implementer.md` - Executes individual tasks
- `spec-reviewer.md` - Validates completed tasks
- `spec-doc-updater.md` - Updates documentation

These prompts reference capabilities like "codebase-retrieval" which all backends provide (with equivalent functionality). **No duplication or modification of prompts is needed.**

Each backend will:
1. Read the same prompt files from `.augment/agents/`
2. Prepend the prompt content as a system prompt
3. Execute with the user's task prompt

---

## Implementation Plan

### Phase 1: Infrastructure (Low Risk)

#### 1.1 Create AIBackend Interface

Create `spec/integrations/backends/base.py`:

```python
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Callable

class AIBackendType(Enum):
    """Supported AI backend types."""
    AUGGIE = auto()
    CLAUDE = auto()
    CURSOR = auto()

class AIBackend(ABC):
    """Abstract base class for AI backend integrations.

    This defines the contract for AI providers (Auggie, Claude Code, Cursor).
    Each backend wraps its respective CLI tool.

    Note: This is distinct from "subagents" which are prompt personas
    defined in .augment/agents/*.md files.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name."""
        pass

    @property
    @abstractmethod
    def backend_type(self) -> AIBackendType:
        """The backend type enum value."""
        pass

    @abstractmethod
    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Execute prompt with streaming output."""
        pass

    @abstractmethod
    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Execute prompt and return output."""
        pass

    @abstractmethod
    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> str:
        """Execute prompt quietly and return output only."""
        pass

    @abstractmethod
    def check_installed(self) -> tuple[bool, str]:
        """Check if the backend CLI is installed."""
        pass

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle parallel requests."""
        return True

    @abstractmethod
    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error."""
        pass
```

#### 1.2 Create AuggieBackend

Create `spec/integrations/backends/auggie.py`:

```python
from spec.integrations.auggie import AuggieClient, _looks_like_rate_limit
from spec.integrations.backends.base import AIBackend, AIBackendType

class AuggieBackend(AIBackend):
    """Auggie CLI backend implementation.

    Wraps the existing AuggieClient to implement the AIBackend interface.
    """

    def __init__(self, model: str = "") -> None:
        self._client = AuggieClient(model=model)

    @property
    def name(self) -> str:
        return "Auggie"

    @property
    def backend_type(self) -> AIBackendType:
        return AIBackendType.AUGGIE

    def run_with_callback(self, prompt, *, output_callback, subagent=None,
                          model=None, dont_save_session=False):
        return self._client.run_with_callback(
            prompt,
            output_callback=output_callback,
            agent=subagent,  # Note: AuggieClient uses 'agent' param
            model=model,
            dont_save_session=dont_save_session,
        )

    def run_print_with_output(self, prompt, *, subagent=None, model=None,
                               dont_save_session=False):
        return self._client.run_print_with_output(
            prompt, agent=subagent, model=model,
            dont_save_session=dont_save_session,
        )

    def run_print_quiet(self, prompt, *, subagent=None, model=None,
                        dont_save_session=False):
        return self._client.run_print_quiet(
            prompt, agent=subagent, model=model,
            dont_save_session=dont_save_session,
        )

    def check_installed(self) -> tuple[bool, str]:
        from spec.integrations.auggie import check_auggie_installed
        return check_auggie_installed()

    def detect_rate_limit(self, output: str) -> bool:
        return _looks_like_rate_limit(output)
```

#### 1.3 Create Backend Factory

Create `spec/integrations/backends/factory.py`:

```python
from spec.integrations.backends.base import AIBackend, AIBackendType

class BackendFactory:
    """Factory for creating AI backend instances."""

    @staticmethod
    def create(backend_type: AIBackendType | str, model: str = "") -> AIBackend:
        """Create an AI backend instance.

        Args:
            backend_type: Backend type enum or string name
            model: Default model to use

        Returns:
            Configured AIBackend instance
        """
        if isinstance(backend_type, str):
            backend_type = AIBackendType[backend_type.upper()]

        if backend_type == AIBackendType.AUGGIE:
            from spec.integrations.backends.auggie import AuggieBackend
            return AuggieBackend(model=model)

        elif backend_type == AIBackendType.CLAUDE:
            from spec.integrations.backends.claude import ClaudeBackend
            return ClaudeBackend(model=model)

        elif backend_type == AIBackendType.CURSOR:
            from spec.integrations.backends.cursor import CursorBackend
            return CursorBackend(model=model)

        else:
            raise ValueError(f"Unknown backend type: {backend_type}")
```

#### 1.4 Add Configuration

Update `spec/config/settings.py`:

```python
# Add new setting
ai_backend: str = "auggie"  # One of: auggie, claude, cursor
```

Update `spec/cli.py`:

```python
@click.option(
    "--backend",
    type=click.Choice(["auggie", "claude", "cursor"], case_sensitive=False),
    default=None,
    help="AI backend to use (default: from config or 'auggie')"
)
```

---

### Phase 2: Workflow Refactoring (Medium Risk)

#### 2.1 Update runner.py

Modify `spec/workflow/runner.py` to accept and use `AIBackend`:

```python
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.factory import BackendFactory

def run_spec_driven_workflow(
    ticket: GenericTicket,
    config: ConfigManager,
    backend: AIBackend | None = None,  # NEW parameter
    planning_model: str = "",
    implementation_model: str = "",
) -> bool:
    # Initialize backend from config if not provided
    if backend is None:
        backend = BackendFactory.create(
            config.settings.ai_backend,
            model=planning_model or config.settings.default_model,
        )

    # Check backend is installed
    is_valid, message = backend.check_installed()
    if not is_valid:
        print_error(f"Backend not available: {message}")
        return False

    # Pass backend to steps
    if not step_1_create_plan(state, backend):
        return False
    # ... rest of workflow
```

#### 2.2 Update Step Functions

Update each step to use `AIBackend` instead of `AuggieClient`:

**step1_plan.py:**
```python
def step_1_create_plan(state: WorkflowState, backend: AIBackend) -> bool:
    success, _output = backend.run_with_callback(
        prompt,
        subagent=state.subagent_names["planner"],
        output_callback=ui.handle_output_line,
        dont_save_session=True,
    )
```

**step3_execute.py:**
```python
def _execute_task_with_callback(
    state: WorkflowState,
    task: Task,
    plan_path: Path,
    backend: AIBackend,  # NEW parameter
    *,
    callback: Callable[[str], None],
) -> bool:
    success, output = backend.run_with_callback(
        prompt,
        subagent=state.subagent_names["implementer"],
        output_callback=callback,
        dont_save_session=True,
    )

    # Use backend-specific rate limit detection
    if not success and backend.detect_rate_limit(output):
        raise RateLimitError("Rate limit detected", output=output)

    return success
```

---

### Phase 3: Claude Backend Implementation (Medium Risk)

#### 3.1 Create ClaudeClient

Create `spec/integrations/claude.py`:

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

    Claude Code CLI is installed via:
        curl -fsSL https://claude.ai/install.sh | bash
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
from spec.integrations.claude import ClaudeClient, check_claude_installed
from spec.integrations.backends.base import AIBackend, AIBackendType

# Claude-specific rate limit patterns
CLAUDE_RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "too many requests",
    "429", "overloaded", "capacity",
]

class ClaudeBackend(AIBackend):
    """Claude Code CLI backend implementation."""

    def __init__(self, model: str = "") -> None:
        self._client = ClaudeClient(model=model)

    @property
    def name(self) -> str:
        return "Claude Code"

    @property
    def backend_type(self) -> AIBackendType:
        return AIBackendType.CLAUDE

    def run_with_callback(self, prompt, *, output_callback, subagent=None,
                          model=None, dont_save_session=False):
        return self._client.run_with_callback(
            prompt, output_callback=output_callback, subagent=subagent,
            model=model, no_save=dont_save_session,
        )

    # ... other methods follow same pattern

    def check_installed(self) -> tuple[bool, str]:
        return check_claude_installed()

    def detect_rate_limit(self, output: str) -> bool:
        output_lower = output.lower()
        return any(p in output_lower for p in CLAUDE_RATE_LIMIT_PATTERNS)
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

Cursor CLI is installed via:
    curl https://cursor.com/install -fsS | bash
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
        no_session: bool = False,
    ) -> list[str]:
        """Build cursor command list."""
        cmd = [self._cli_command]

        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if no_session:
            cmd.append("--no-session")

        if print_mode:
            cmd.append("-p")  # Cursor uses -p for print mode

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
        no_session: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback."""
        cmd = self._build_command(prompt, subagent, model, True, no_session)

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
from spec.integrations.cursor import CursorClient, check_cursor_installed
from spec.integrations.backends.base import AIBackend, AIBackendType

# Cursor-specific rate limit patterns
CURSOR_RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "too many requests",
    "429", "quota exceeded", "throttl",
]

class CursorBackend(AIBackend):
    """Cursor CLI backend implementation."""

    def __init__(self, model: str = "") -> None:
        self._client = CursorClient(model=model)

    @property
    def name(self) -> str:
        return "Cursor"

    @property
    def backend_type(self) -> AIBackendType:
        return AIBackendType.CURSOR

    def run_with_callback(self, prompt, *, output_callback, subagent=None,
                          model=None, dont_save_session=False):
        return self._client.run_with_callback(
            prompt, output_callback=output_callback, subagent=subagent,
            model=model, no_session=dont_save_session,
        )

    # ... other methods follow same pattern

    def check_installed(self) -> tuple[bool, str]:
        return check_cursor_installed()

    def detect_rate_limit(self, output: str) -> bool:
        output_lower = output.lower()
        return any(p in output_lower for p in CURSOR_RATE_LIMIT_PATTERNS)
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

---

### Phase 5: Rate Limit Handling (Low Risk)

#### 5.1 Abstract Rate Limit Error

Update `spec/utils/retry.py` to work with any backend:

```python
class BackendRateLimitError(Exception):
    """Raised when any backend indicates a rate limit error."""

    def __init__(self, message: str, output: str, backend_name: str):
        super().__init__(message)
        self.output = output
        self.backend_name = backend_name
```

#### 5.2 Update Retry Logic

Update `spec/workflow/step3_execute.py` to use backend-specific detection:

```python
def _execute_task_with_callback(..., backend: AIBackend, ...):
    success, output = backend.run_with_callback(...)

    if not success and backend.detect_rate_limit(output):
        raise BackendRateLimitError(
            "Rate limit detected",
            output=output,
            backend_name=backend.name,
        )
```

---

### Phase 6: Testing (Medium Risk)

#### 6.1 Unit Tests for Backends

Create `tests/test_backends.py`:

```python
import pytest
from spec.integrations.backends.factory import BackendFactory
from spec.integrations.backends.base import AIBackendType

class TestBackendFactory:
    def test_create_auggie_backend(self):
        backend = BackendFactory.create("auggie")
        assert backend.backend_type == AIBackendType.AUGGIE

    def test_create_claude_backend(self):
        backend = BackendFactory.create("claude")
        assert backend.backend_type == AIBackendType.CLAUDE

    def test_create_cursor_backend(self):
        backend = BackendFactory.create("cursor")
        assert backend.backend_type == AIBackendType.CURSOR

    def test_create_unknown_backend_raises(self):
        with pytest.raises(ValueError):
            BackendFactory.create("unknown")

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
```

#### 6.2 Integration Tests

Create `tests/test_backend_integration.py`:

```python
import pytest
from spec.integrations.backends.factory import BackendFactory

@pytest.mark.parametrize("backend_type", ["auggie", "claude", "cursor"])
def test_backend_interface_compliance(backend_type):
    """Verify all backends implement the required interface."""
    backend = BackendFactory.create(backend_type)

    # Check required properties
    assert hasattr(backend, 'name')
    assert hasattr(backend, 'backend_type')

    # Check required methods
    assert callable(getattr(backend, 'run_with_callback', None))
    assert callable(getattr(backend, 'run_print_with_output', None))
    assert callable(getattr(backend, 'run_print_quiet', None))
    assert callable(getattr(backend, 'check_installed', None))
    assert callable(getattr(backend, 'detect_rate_limit', None))
```

---

### Phase 7: Documentation (Low Risk)

#### 7.1 Update README.md

Add section on backend selection:

```markdown
## AI Backend Selection

SPEC supports multiple AI backends:

| Backend | CLI Command | Installation |
|---------|-------------|--------------|
| Auggie (default) | `auggie` | `npm install -g @augmentcode/auggie` |
| Claude Code | `claude` | `curl -fsSL https://claude.ai/install.sh \| bash` |
| Cursor | `cursor` | `curl https://cursor.com/install -fsS \| bash` |

### Selecting a Backend

Via CLI flag:
```bash
spec run TICKET-123 --backend=claude
```

Via configuration (spec.toml):
```toml
[settings]
ai_backend = "cursor"
```

### Backend Prerequisites

Each backend requires authentication before first use:

- **Auggie**: Run `auggie login`
- **Claude Code**: Run `claude` interactively to complete login
- **Cursor**: Run `cursor` interactively to complete login
```

---

## File Structure Summary

```
spec/integrations/
├── auggie.py                    # Existing (unchanged)
├── claude.py                    # NEW: Claude CLI wrapper
├── cursor.py                    # NEW: Cursor CLI wrapper
├── backends/
│   ├── __init__.py              # NEW: Package exports
│   ├── base.py                  # NEW: AIBackend interface + AIBackendType enum
│   ├── auggie.py                # NEW: AuggieBackend implementation
│   ├── claude.py                # NEW: ClaudeBackend implementation
│   ├── cursor.py                # NEW: CursorBackend implementation
│   └── factory.py               # NEW: BackendFactory
├── fetchers/
│   ├── auggie_fetcher.py        # Existing (unchanged)
│   ├── claude_fetcher.py        # NEW: ClaudeMediatedFetcher
│   └── cursor_fetcher.py        # NEW: CursorMediatedFetcher

spec/workflow/
├── runner.py                    # MODIFY: Accept AIBackend parameter
├── step1_plan.py                # MODIFY: Use AIBackend
├── step2_tasklist.py            # MODIFY: Use AIBackend
├── step3_execute.py             # MODIFY: Use AIBackend + rate limit abstraction
└── step4_update_docs.py         # MODIFY: Use AIBackend

spec/config/
└── settings.py                  # MODIFY: Add ai_backend setting

spec/cli.py                      # MODIFY: Add --backend option

tests/
├── test_backends.py             # NEW: Backend unit tests
└── test_backend_integration.py  # NEW: Integration tests
```

---

## Migration Notes

### Backward Compatibility

- Default backend is `auggie` - existing users see no change
- All existing tests continue to work
- No changes to subagent prompt files

### Breaking Changes

None - this is a purely additive change.

---

## Success Criteria

1. ✅ `spec run TICKET-123` works with default Auggie backend
2. ✅ `spec run TICKET-123 --backend=claude` works with Claude Code CLI
3. ✅ `spec run TICKET-123 --backend=cursor` works with Cursor CLI
4. ✅ All existing tests pass
5. ✅ New backend tests pass
6. ✅ Rate limiting works correctly for each backend
7. ✅ Parallel execution works for all backends
8. ✅ MCP ticket fetching works for all backends
