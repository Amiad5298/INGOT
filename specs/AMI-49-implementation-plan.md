# Implementation Plan: AMI-49 - Phase 1.3: Create BaseBackend Abstract Class

**Ticket:** [AMI-49](https://linear.app/amiadspec/issue/AMI-49/phase-13-create-basebackend-abstract-class)
**Status:** Draft
**Date:** 2026-02-01
**Labels:** MultiAgent

---

## Summary

This ticket creates the `BaseBackend` abstract base class that implements shared logic across all backend implementations. The abstract class reduces code duplication by providing common functionality for subagent prompt loading, model resolution, timeout enforcement, and rate limit detection patterns.

**Why This Matters:**
- All backends need to parse subagent prompts from `.augment/agents/*.md` files
- All backends need to strip YAML frontmatter and resolve model settings
- All backends need streaming-safe timeout enforcement via watchdog pattern
- Without a shared base class, this logic would be duplicated 3+ times (Auggie, Claude, Cursor, Aider)

**Scope:**
- Extend `spec/integrations/backends/base.py` to include:
  - `SubagentMetadata` dataclass for parsed frontmatter
  - `BaseBackend` abstract class implementing `AIBackend` protocol
  - Shared methods: `_parse_subagent_prompt()`, `_resolve_model()`, `_run_streaming_with_timeout()`
  - Default implementations: `supports_parallel_execution()`, `close()`
  - Abstract methods that subclasses must implement
- Update `spec/integrations/backends/__init__.py` to export `BaseBackend` and `SubagentMetadata`

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.3 (lines 1436-1716)

---

## Context

This is **Phase 1.3** of the Backend Infrastructure work (AMI-45), which is part of the larger Pluggable Multi-Agent Support initiative.

### Parent Specification

The [Pluggable Multi-Agent Support](./Pluggable%20Multi-Agent%20Support.md) specification defines a phased approach to support multiple AI backends:

- **Phase 0:** Baseline Behavior Tests (AMI-44) ✅ Done
- **Phase 1.0:** Rename Claude Platform Enum (AMI-46) ⏳ Backlog
- **Phase 1.1:** Create Backend Error Types (AMI-47) ✅ Done
- **Phase 1.2:** Create AIBackend Protocol (AMI-48) ✅ Done
- **Phase 1.3:** Create BaseBackend Abstract Class (AMI-49) ← **This Ticket**
- **Phase 1.4:** Create AuggieBackend (AMI-50)
- **Phase 1.5:** Create Backend Config Resolution (AMI-51)
- **Phase 1.6+:** BackendFactory, Workflow Integration, etc.

### Position in Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     spec/integrations/backends/base.py                       │
│                                                                              │
│   AIBackend (Protocol) ← Phase 1.2 (AMI-48) ✅ Done                          │
│       ├── name: str (property)                                              │
│       ├── platform: AgentPlatform (property)                                │
│       ├── supports_parallel: bool (property)                                │
│       ├── run_with_callback(...) -> tuple[bool, str]                        │
│       ├── run_print_with_output(...) -> tuple[bool, str]                    │
│       ├── run_print_quiet(...) -> str                                       │
│       ├── run_streaming(...) -> tuple[bool, str]                            │
│       ├── check_installed() -> tuple[bool, str]                             │
│       ├── detect_rate_limit(output: str) -> bool                            │
│       ├── supports_parallel_execution() -> bool                             │
│       └── close() -> None                                                   │
│                                                                              │
│   BaseBackend (ABC) ← Phase 1.3 (AMI-49) **THIS TICKET**                    │
│       ├── __init__(model: str = "")                                         │
│       ├── _model: str                                                       │
│       ├── supports_parallel: bool (default True)                            │
│       ├── supports_parallel_execution() -> bool (concrete)                  │
│       ├── close() -> None (concrete, no-op)                                 │
│       ├── _parse_subagent_prompt(subagent) -> (metadata, body)              │
│       ├── _resolve_model(explicit, subagent) -> str | None                  │
│       ├── _run_streaming_with_timeout(cmd, callback, timeout) -> (int, str) │
│       ├── @abstractmethod name, platform                                    │
│       ├── @abstractmethod run_with_callback(...)                            │
│       ├── @abstractmethod run_print_with_output(...)                        │
│       ├── @abstractmethod run_print_quiet(...)                              │
│       ├── @abstractmethod run_streaming(...)                                │
│       ├── @abstractmethod check_installed()                                 │
│       └── @abstractmethod detect_rate_limit(output)                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ extended by (Phase 1.4+)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│   AuggieBackend (Phase 1.4)      ←  Wraps AuggieClient                      │
│   ClaudeBackend (Phase 3)        ←  Wraps ClaudeClient                      │
│   CursorBackend (Phase 4)        ←  Wraps CursorClient                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Relationship to AIBackend Protocol

The `AIBackend` protocol (created in AMI-48) defines the **contract** that all backends must satisfy. The `BaseBackend` abstract class **implements** this protocol with:

1. **Concrete implementations** for methods that are identical across backends
2. **Abstract method declarations** for methods that require backend-specific logic
3. **Protected helper methods** (`_parse_subagent_prompt`, `_resolve_model`, `_run_streaming_with_timeout`) for code reuse

| AIBackend Protocol (Contract) | BaseBackend (Shared Implementation) |
|-------------------------------|-------------------------------------|
| `name: str` property | `@abstractmethod` - subclass provides |
| `platform: AgentPlatform` property | `@abstractmethod` - subclass provides |
| `supports_parallel: bool` property | Default `True`, overridable |
| `supports_parallel_execution()` | Concrete - returns `self.supports_parallel` |
| `close()` | Concrete - no-op default |
| `run_with_callback(...)` | `@abstractmethod` - subclass implements |
| `run_print_with_output(...)` | `@abstractmethod` - subclass implements |
| `run_print_quiet(...)` | `@abstractmethod` - subclass implements |
| `run_streaming(...)` | `@abstractmethod` - subclass implements |
| `check_installed()` | `@abstractmethod` - subclass implements |
| `detect_rate_limit(...)` | `@abstractmethod` - subclass implements |

---

## Technical Approach

### Comparison: Without vs. With BaseBackend

| Without BaseBackend | With BaseBackend |
|---------------------|------------------|
| Each backend duplicates subagent parsing | Shared `_parse_subagent_prompt()` |
| Each backend duplicates model resolution | Shared `_resolve_model()` |
| Each backend implements timeout watchdog | Shared `_run_streaming_with_timeout()` |
| Each backend implements `close()` | Default no-op in base class |
| No guarantee of consistent behavior | Consistent YAML parsing across backends |
| ~100+ lines duplicated per backend | ~15 lines per backend for abstract methods |

### Key Design Decisions

1. **Inherit from ABC, not Protocol**: `BaseBackend` is an abstract base class (ABC), not a Protocol. This allows concrete method implementations while still enforcing that subclasses implement abstract methods.

2. **Use `@abstractmethod` for backend-specific logic**: Methods like `check_installed()` and `detect_rate_limit()` differ per backend (CLI path, rate limit patterns).

3. **Provide protected helper methods**: Methods prefixed with `_` are for internal use by subclasses:
   - `_parse_subagent_prompt()` - Strips YAML frontmatter (per Decision 6: Subagent Frontmatter Handling)
   - `_resolve_model()` - Implements model precedence (per-call → frontmatter → config)
   - `_run_streaming_with_timeout()` - Watchdog pattern for timeout enforcement

4. **Default `supports_parallel = True`**: Most backends support parallel execution. Subclasses override if needed.

5. **Model parameter stored as instance attribute**: `self._model` stores the default model, resolved via `_resolve_model()`.

6. **YAML parsing uses `yaml.safe_load`**: Secure parsing that prevents code execution from malicious frontmatter.

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `spec/integrations/backends/base.py` | **MODIFY** | Add `SubagentMetadata` dataclass and `BaseBackend` ABC |
| `spec/integrations/backends/__init__.py` | **MODIFY** | Export `BaseBackend` and `SubagentMetadata` |

---

## Implementation Phases

### Phase 1: Create SubagentMetadata Dataclass

#### Step 1.1: Add SubagentMetadata to base.py

**File:** `spec/integrations/backends/base.py`

Add the dataclass after the imports, before the `AIBackend` protocol:

```python
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
import logging
import subprocess
import threading

import yaml

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.errors import BackendTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class SubagentMetadata:
    """Parsed frontmatter from subagent prompt files.

    Subagent prompts in `.augment/agents/*.md` may contain YAML frontmatter
    with metadata fields. This dataclass holds the parsed values.

    Per Decision 6 (Subagent Frontmatter Handling), YAML frontmatter is stripped
    from prompts before sending to backends. Only the body content is used.

    Attributes:
        model: Model override specified in frontmatter (e.g., "claude-3-opus")
        temperature: Temperature setting for this subagent (optional)

    Example frontmatter:
        ---
        model: claude-3-opus
        temperature: 0.7
        ---
        You are a planning assistant...
    """

    model: str | None = None
    temperature: float | None = None
```

### Phase 2: Create BaseBackend Abstract Class

#### Step 2.1: Add BaseBackend Class with Core Structure

**File:** `spec/integrations/backends/base.py`

Add after the `AIBackend` protocol definition:

```python
class BaseBackend(ABC):
    """Abstract base class with common functionality for all backends.

    Concrete backends (AuggieBackend, ClaudeBackend, CursorBackend) extend this
    class to inherit shared logic while implementing backend-specific behavior.

    This class implements the AIBackend protocol, providing:
    - Default implementations for supports_parallel_execution() and close()
    - Protected helper methods for subagent parsing, model resolution, and timeouts
    - Abstract method declarations that subclasses must implement

    Example:
        >>> class MyBackend(BaseBackend):
        ...     @property
        ...     def name(self) -> str:
        ...         return "MyBackend"
        ...
        ...     @property
        ...     def platform(self) -> AgentPlatform:
        ...         return AgentPlatform.AUGGIE
        ...
        ...     # ... implement abstract methods ...
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the backend with optional default model.

        Args:
            model: Default model to use when not specified per-call or in frontmatter
        """
        self._model = model

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name.

        Examples: 'Auggie', 'Claude Code', 'Cursor'
        """
        ...

    @property
    @abstractmethod
    def platform(self) -> AgentPlatform:
        """The AI backend enum value.

        Returns the AgentPlatform enum member for this backend.
        Used for configuration and logging.
        """
        ...

    @property
    def supports_parallel(self) -> bool:
        """Whether this backend supports parallel execution.

        Override in subclass if different from default (True).
        Most backends support concurrent CLI invocations.
        """
        return True

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle concurrent invocations.

        Returns the value of the supports_parallel property.
        This method exists for explicit API clarity in workflow code.

        Returns:
            True if multiple CLI invocations can run concurrently
        """
        return self.supports_parallel

    def close(self) -> None:
        """Release any resources held by the backend.

        Default implementation is no-op. Override if cleanup needed.

        Called when workflow completes or on cleanup. Implementations may:
        - Terminate subprocess connections
        - Close file handles
        - Clean up temporary files
        """
        pass
```

#### Step 2.2: Add Protected Helper Methods

Continue in `spec/integrations/backends/base.py`:

```python
    def _parse_subagent_prompt(self, subagent: str) -> tuple[SubagentMetadata, str]:
        """Parse subagent prompt file and extract frontmatter.

        Shared across all backends to ensure consistent parsing.
        Per Decision 6 (Subagent Frontmatter Handling), YAML frontmatter is stripped from prompts.

        The function looks for files in `.augment/agents/{subagent}.md`.
        If the file starts with `---`, it parses the YAML frontmatter.

        Args:
            subagent: Subagent name (e.g., "spec-planner")

        Returns:
            Tuple of (metadata, prompt_body) where:
            - metadata: Parsed SubagentMetadata from frontmatter
            - prompt_body: The prompt content without frontmatter

        Example:
            >>> metadata, body = backend._parse_subagent_prompt("spec-planner")
            >>> if metadata.model:
            ...     print(f"Using model: {metadata.model}")
        """
        agent_path = Path(".augment/agents") / f"{subagent}.md"
        if not agent_path.exists():
            logger.debug(
                "Subagent file not found",
                extra={"subagent": subagent, "path": str(agent_path)},
            )
            return SubagentMetadata(), ""

        content = agent_path.read_text()

        # Parse YAML frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    metadata = SubagentMetadata(
                        model=frontmatter.get("model"),
                        temperature=frontmatter.get("temperature"),
                    )
                    logger.debug(
                        "Parsed subagent frontmatter",
                        extra={
                            "subagent": subagent,
                            "model": metadata.model,
                            "temperature": metadata.temperature,
                        },
                    )
                    return metadata, parts[2].strip()
                except yaml.YAMLError as e:
                    logger.warning(
                        "Failed to parse subagent frontmatter",
                        extra={"subagent": subagent, "error": str(e)},
                    )

        return SubagentMetadata(), content

    def _resolve_model(
        self,
        explicit_model: str | None,
        subagent: str | None,
    ) -> str | None:
        """Resolve which model to use based on precedence.

        Implements Decision 6 model selection precedence:
        1. Explicit per-call model override (highest precedence)
        2. Subagent frontmatter model field
        3. Instance default model (self._model)

        Args:
            explicit_model: Model passed to run_* method
            subagent: Subagent name for frontmatter lookup

        Returns:
            Resolved model name or None if no model specified
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
```

#### Step 2.3: Add Streaming Timeout Method

Continue in `spec/integrations/backends/base.py`:

```python
    def _run_streaming_with_timeout(
        self,
        cmd: list[str],
        output_callback: Callable[[str], None],
        timeout_seconds: float | None,
    ) -> tuple[int, str]:
        """Run subprocess with streaming output and timeout enforcement.

        This is the shared timeout implementation used by all backends.
        Uses a watchdog thread pattern for streaming-safe timeout enforcement.

        Backends call this method from their run_with_callback() implementations
        to get consistent timeout behavior across all backend types.

        The watchdog thread:
        1. Starts when timeout_seconds is provided
        2. Waits on a stop_event for timeout_seconds
        3. If not stopped, terminates the process (SIGTERM → SIGKILL)

        Args:
            cmd: Command to execute as subprocess
            output_callback: Called for each line of output (stripped of newline)
            timeout_seconds: Maximum execution time (None = no timeout)

        Returns:
            Tuple of (return_code, full_output) where return_code is the
            subprocess exit code and full_output is all output joined.

        Raises:
            BackendTimeoutError: If execution exceeds timeout_seconds

        Example:
            >>> return_code, output = self._run_streaming_with_timeout(
            ...     ["augment", "agent", "--print", "-p", prompt],
            ...     output_callback=lambda line: print(line),
            ...     timeout_seconds=120.0,
            ... )
        """
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line-buffered
        )

        output_lines: list[str] = []
        stop_watchdog_event = threading.Event()
        did_timeout = False

        def watchdog() -> None:
            nonlocal did_timeout
            stopped = stop_watchdog_event.wait(timeout=timeout_seconds)
            if not stopped:
                did_timeout = True
                logger.warning(
                    "Backend execution timed out",
                    extra={"timeout_seconds": timeout_seconds, "cmd": cmd[0]},
                )
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Process did not terminate, sending SIGKILL")
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

            # process.returncode could be None if process was killed unexpectedly
            return process.returncode or -1, "".join(output_lines)

        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
```

### Phase 3: Add Abstract Method Declarations

#### Step 3.1: Declare Abstract Methods

Continue in `spec/integrations/backends/base.py`:

```python
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
        """Execute prompt with streaming output (non-interactive).

        Subclasses implement this to invoke their specific CLI tool.
        Use _resolve_model() and _parse_subagent_prompt() for model/prompt resolution.
        Use _run_streaming_with_timeout() for consistent timeout handling.
        """
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
        """Check if the backend CLI is installed and functional."""
        ...

    @abstractmethod
    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error."""
        ...
```



### Phase 4: Update Package Exports

#### Step 4.1: Update __init__.py

**File:** `spec/integrations/backends/__init__.py`

```python
"""Backend infrastructure for AI agent integrations.

This package provides a unified abstraction layer for AI backends:
- Auggie (Augment Code CLI)
- Claude (Claude Code CLI)
- Cursor (Cursor IDE)
- Aider (Aider CLI)

Modules:
- errors: Backend-related error types
- base: AIBackend protocol, BaseBackend class, and SubagentMetadata
- factory: Backend factory for instantiation (Phase 1.6+)
"""

from spec.integrations.backends.base import (
    AIBackend,
    BaseBackend,
    SubagentMetadata,
)
from spec.integrations.backends.errors import (
    BackendNotConfiguredError,
    BackendNotInstalledError,
    BackendRateLimitError,
    BackendTimeoutError,
)

# Explicit public API for IDE support and documentation.
# All exported symbols should be listed here.
__all__ = [
    # Protocol and base class
    "AIBackend",
    "BaseBackend",
    "SubagentMetadata",
    # Error types
    "BackendRateLimitError",
    "BackendNotInstalledError",
    "BackendNotConfiguredError",
    "BackendTimeoutError",
]
```

---

## Dependencies

### Upstream Dependencies (Must Be Complete)

| Ticket | Status | Description |
|--------|--------|-------------|
| AMI-47 | ✅ Done | Backend Error Types - Provides `BackendTimeoutError` used by `_run_streaming_with_timeout()` |
| AMI-48 | ✅ Done | AIBackend Protocol - Defines the contract that `BaseBackend` implements |

### Downstream Dependencies (Blocked by This Ticket)

| Ticket | Status | Description |
|--------|--------|-------------|
| AMI-50 | 🔜 Ready | Create AuggieBackend - Will extend `BaseBackend` |
| AMI-51 | 🔜 Ready | Backend Config Resolution - May use `SubagentMetadata` |

### Related Tickets

| Ticket | Relationship | Description |
|--------|--------------|-------------|
| AMI-45 | Parent | Backend Infrastructure (parent epic) |
| AMI-46 | Sibling | Rename Claude Platform Enum |
| AMI-44 | Phase 0 | Baseline Behavior Tests |

---

## Testing Strategy

### Test File

**File:** `tests/test_base_backend.py`

### Integration Testing Note

The unit tests in this plan use mocked subprocesses for `_run_streaming_with_timeout()`. For full integration testing with real subprocess execution, tests can be gated behind `SPEC_INTEGRATION_TESTS=1` (following the pattern established in AMI-44):

```python
@pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests require SPEC_INTEGRATION_TESTS=1",
)
def test_run_streaming_with_timeout_real_subprocess():
    """Integration test: verify timeout with real subprocess."""
    backend = ConcreteTestBackend()
    output_lines = []
    return_code, output = backend._run_streaming_with_timeout(
        ["echo", "hello world"],
        output_callback=output_lines.append,
        timeout_seconds=10.0,
    )
    assert return_code == 0
    assert "hello world" in output
```

This integration test is **optional** for AMI-49 since the unit tests with mocked subprocesses provide sufficient coverage. Integration tests become more valuable in AMI-50 (AuggieBackend) where real CLI invocations are tested.

### Test Categories

#### 1. SubagentMetadata Dataclass Tests

```python
def test_subagent_metadata_defaults():
    """SubagentMetadata has None defaults for all fields."""
    metadata = SubagentMetadata()
    assert metadata.model is None
    assert metadata.temperature is None


def test_subagent_metadata_with_values():
    """SubagentMetadata accepts model and temperature."""
    metadata = SubagentMetadata(model="claude-3-opus", temperature=0.7)
    assert metadata.model == "claude-3-opus"
    assert metadata.temperature == 0.7
```

#### 2. _parse_subagent_prompt Tests

```python
def test_parse_subagent_prompt_with_frontmatter(tmp_path, monkeypatch):
    """Parses YAML frontmatter and returns metadata + body."""
    # Create test subagent file
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "test-agent.md"
    subagent_file.write_text(
        "---\nmodel: claude-3-opus\ntemperature: 0.5\n---\nYou are a test agent."
    )
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("test-agent")

    assert metadata.model == "claude-3-opus"
    assert metadata.temperature == 0.5
    assert body == "You are a test agent."


def test_parse_subagent_prompt_without_frontmatter(tmp_path, monkeypatch):
    """Returns empty metadata and full content when no frontmatter."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "plain-agent.md"
    subagent_file.write_text("You are a plain agent without frontmatter.")
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("plain-agent")

    assert metadata.model is None
    assert body == "You are a plain agent without frontmatter."


def test_parse_subagent_prompt_file_not_found(tmp_path, monkeypatch):
    """Returns empty metadata and empty body when file not found."""
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("nonexistent")

    assert metadata.model is None
    assert body == ""


def test_parse_subagent_prompt_invalid_yaml(tmp_path, monkeypatch):
    """Returns empty metadata when YAML is invalid."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "invalid-agent.md"
    subagent_file.write_text("---\ninvalid: yaml: content:\n---\nBody text.")
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("invalid-agent")

    # Should fall back gracefully
    assert metadata.model is None
```

#### 3. _resolve_model Tests

```python
def test_resolve_model_explicit_override():
    """Explicit model takes highest precedence."""
    backend = ConcreteTestBackend(model="default-model")
    result = backend._resolve_model(explicit_model="override-model", subagent=None)
    assert result == "override-model"


def test_resolve_model_from_frontmatter(tmp_path, monkeypatch):
    """Model from subagent frontmatter used when no explicit override."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "model-agent.md").write_text("---\nmodel: frontmatter-model\n---\n")
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend(model="default-model")
    result = backend._resolve_model(explicit_model=None, subagent="model-agent")
    assert result == "frontmatter-model"


def test_resolve_model_instance_default():
    """Falls back to instance default when no override or frontmatter."""
    backend = ConcreteTestBackend(model="default-model")
    result = backend._resolve_model(explicit_model=None, subagent=None)
    assert result == "default-model"


def test_resolve_model_returns_none_when_empty():
    """Returns None when no model specified anywhere."""
    backend = ConcreteTestBackend()
    result = backend._resolve_model(explicit_model=None, subagent=None)
    assert result is None
```

#### 4. Abstract Class Enforcement Tests

```python
def test_basebackend_cannot_be_instantiated():
    """BaseBackend raises TypeError on direct instantiation."""
    with pytest.raises(TypeError, match="abstract"):
        BaseBackend()


def test_concrete_backend_must_implement_abstract_methods():
    """Subclass without implementations raises TypeError."""
    class IncompleteBackend(BaseBackend):
        pass

    with pytest.raises(TypeError, match="abstract"):
        IncompleteBackend()
```

#### 5. Default Implementation Tests

```python
def test_supports_parallel_default_true():
    """Default supports_parallel is True."""
    backend = ConcreteTestBackend()
    assert backend.supports_parallel is True
    assert backend.supports_parallel_execution() is True


def test_close_is_noop():
    """close() is a no-op and doesn't raise."""
    backend = ConcreteTestBackend()
    backend.close()  # Should not raise
```

#### 6. _run_streaming_with_timeout Tests

```python
def test_run_streaming_with_timeout_success(mocker):
    """Process completes before timeout - returns output and exit code."""
    mock_process = mocker.MagicMock()
    mock_process.stdout = iter(["line1\n", "line2\n"])
    mock_process.returncode = 0
    mock_process.poll.return_value = 0
    mock_process.wait.return_value = None

    mocker.patch("subprocess.Popen", return_value=mock_process)

    backend = ConcreteTestBackend()
    output_lines = []
    return_code, output = backend._run_streaming_with_timeout(
        ["echo", "test"],
        output_callback=output_lines.append,
        timeout_seconds=10.0,
    )

    assert return_code == 0
    assert output == "line1\nline2\n"
    assert output_lines == ["line1", "line2"]


def test_run_streaming_with_timeout_exceeds(mocker):
    """Process killed when timeout exceeded - raises BackendTimeoutError."""
    import threading
    from spec.integrations.backends.errors import BackendTimeoutError

    # Create a process that hangs (stdout blocks indefinitely)
    mock_process = mocker.MagicMock()
    hang_event = threading.Event()

    def blocking_stdout():
        hang_event.wait()  # Block until test completes
        return iter([])

    mock_process.stdout = blocking_stdout()
    mock_process.returncode = -15  # SIGTERM
    mock_process.poll.return_value = None  # Process still running
    mock_process.wait.return_value = None
    mock_process.terminate.side_effect = lambda: hang_event.set()

    mocker.patch("subprocess.Popen", return_value=mock_process)

    backend = ConcreteTestBackend()
    with pytest.raises(BackendTimeoutError) as exc_info:
        backend._run_streaming_with_timeout(
            ["sleep", "100"],
            output_callback=lambda x: None,
            timeout_seconds=0.1,  # Very short timeout
        )

    assert "timed out after 0.1s" in str(exc_info.value)


def test_run_streaming_with_timeout_no_timeout(mocker):
    """Process runs without timeout when timeout_seconds=None - no watchdog started."""
    mock_process = mocker.MagicMock()
    mock_process.stdout = iter(["output\n"])
    mock_process.returncode = 0
    mock_process.poll.return_value = 0
    mock_process.wait.return_value = None

    mocker.patch("subprocess.Popen", return_value=mock_process)
    mock_thread = mocker.patch("threading.Thread")

    backend = ConcreteTestBackend()
    return_code, output = backend._run_streaming_with_timeout(
        ["echo", "test"],
        output_callback=lambda x: None,
        timeout_seconds=None,  # No timeout
    )

    # Verify no watchdog thread was created when timeout is None
    mock_thread.assert_not_called()
    assert return_code == 0
    assert output == "output\n"


def test_run_streaming_with_timeout_callback_receives_stripped_lines(mocker):
    """Output callback receives lines with newlines stripped."""
    mock_process = mocker.MagicMock()
    mock_process.stdout = iter(["  line with spaces  \n", "another line\n"])
    mock_process.returncode = 0
    mock_process.poll.return_value = 0
    mock_process.wait.return_value = None

    mocker.patch("subprocess.Popen", return_value=mock_process)

    backend = ConcreteTestBackend()
    output_lines = []
    backend._run_streaming_with_timeout(
        ["echo", "test"],
        output_callback=output_lines.append,
        timeout_seconds=10.0,
    )

    # Callback receives stripped lines (no trailing newline)
    assert output_lines == ["  line with spaces  ", "another line"]
```

#### 7. Edge Case Tests for _parse_subagent_prompt

```python
def test_parse_subagent_prompt_model_only(tmp_path, monkeypatch):
    """Frontmatter with only model field, no temperature."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "model-only.md"
    subagent_file.write_text("---\nmodel: gpt-4\n---\nPrompt body here.")
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("model-only")

    assert metadata.model == "gpt-4"
    assert metadata.temperature is None
    assert body == "Prompt body here."


def test_parse_subagent_prompt_empty_frontmatter(tmp_path, monkeypatch):
    """Handles empty frontmatter `---\\n---\\n` gracefully."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "empty-frontmatter.md"
    subagent_file.write_text("---\n---\nBody after empty frontmatter.")
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("empty-frontmatter")

    assert metadata.model is None
    assert metadata.temperature is None
    assert body == "Body after empty frontmatter."


def test_parse_subagent_prompt_frontmatter_with_extra_fields(tmp_path, monkeypatch):
    """Unknown frontmatter fields are ignored gracefully."""
    agents_dir = tmp_path / ".augment" / "agents"
    agents_dir.mkdir(parents=True)
    subagent_file = agents_dir / "extra-fields.md"
    subagent_file.write_text(
        "---\nmodel: claude-3\ntemperature: 0.5\nunknown_field: value\n---\nBody."
    )
    monkeypatch.chdir(tmp_path)

    backend = ConcreteTestBackend()
    metadata, body = backend._parse_subagent_prompt("extra-fields")

    assert metadata.model == "claude-3"
    assert metadata.temperature == 0.5
    # Unknown fields don't cause errors
    assert body == "Body."
```

### Test Fixture: ConcreteTestBackend

```python
class ConcreteTestBackend(BaseBackend):
    """Minimal concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "TestBackend"

    @property
    def platform(self) -> AgentPlatform:
        return AgentPlatform.AUGGIE

    def run_with_callback(self, prompt, *, output_callback, **kwargs):
        return True, "output"

    def run_print_with_output(self, prompt, **kwargs):
        return True, "output"

    def run_print_quiet(self, prompt, **kwargs):
        return "output"

    def run_streaming(self, prompt, **kwargs):
        return True, "output"

    def check_installed(self):
        return True, "1.0.0"

    def detect_rate_limit(self, output):
        return "rate limit" in output.lower()
```


---

## Risk Assessment

### Risk 1: YAML Parsing Errors

**Risk:** Malformed YAML frontmatter in subagent files could crash the parser.

**Mitigation:**
- Use `yaml.safe_load()` for secure parsing
- Wrap parsing in try/except and log warnings
- Fall back to empty metadata on parse failure
- Never propagate YAML errors to callers

**Severity:** Low (handled gracefully)

### Risk 2: Timeout Watchdog Thread Safety

**Risk:** Race conditions between watchdog thread and main thread could cause issues.

**Mitigation:**
- Use `threading.Event` for coordination (thread-safe)
- Set `daemon=True` so watchdog doesn't block shutdown
- Check `process.poll()` before killing in finally block
- Join watchdog thread with timeout to prevent hanging

**Severity:** Low (standard patterns used)

### Risk 3: Subagent File Not Found

**Risk:** Callers may pass invalid subagent names that don't have corresponding files.

**Mitigation:**
- Return empty metadata and empty body (graceful degradation)
- Log debug message for troubleshooting
- Don't raise exceptions for missing files
- Document that subagent parameter is optional

**Severity:** Low (graceful fallback)

### Risk 4: Import Cycles

**Risk:** Importing from `spec.integrations.backends.errors` in `base.py` could create cycles.

**Mitigation:**
- Keep imports at module level (already done in AMI-48)
- `errors.py` has no imports from `base.py`
- Follow established import patterns in codebase

**Severity:** Very Low (already verified)

### Risk 5: Output Callback Thread Safety

**Risk:** Callers might assume `output_callback` needs to be thread-safe.

**Mitigation:**
- Document that `output_callback` is called from the **main thread** (the thread that reads stdout), NOT from the watchdog thread
- The watchdog thread only terminates the process; it never calls the callback
- Callers do NOT need to make their callbacks thread-safe for `_run_streaming_with_timeout()`
- Note: When Step 3 runs tasks in parallel, each task has its own `_run_streaming_with_timeout()` call, so callbacks are still single-threaded per task

**Severity:** Very Low (documented behavior)

### Risk 6: PyYAML Type Stubs

**Risk:** Running `mypy --strict` may fail due to missing type stubs for PyYAML.

**Mitigation:**
- Install `types-PyYAML` package: `pip install types-PyYAML`
- Or use `--ignore-missing-imports` flag for mypy
- Add `types-PyYAML` to dev dependencies if not already present

**Severity:** Very Low (tooling configuration)

---

## Notes

### Linear Ticket Description Discrepancy

The Linear ticket (AMI-49) description mentions:
- `_load_subagent_prompt(subagent)` → Implemented as `_parse_subagent_prompt(subagent)` (name change)
- `_run_with_timeout(func, timeout_seconds)` → Implemented as `_run_streaming_with_timeout(cmd, callback, timeout)` (different signature for streaming)
- `_get_rate_limit_patterns() -> list[str]` → **NOT implemented** (specification uses `detect_rate_limit(output: str) -> bool` as abstract method instead)

**Resolution:** The parent specification (`specs/Pluggable Multi-Agent Support.md` lines 1436-1716) takes precedence over the Linear ticket description. The specification does NOT include `_get_rate_limit_patterns()` - it makes `detect_rate_limit()` an abstract method that each backend implements with its own patterns. This implementation plan follows the specification.

---

## Verification Commands

### 1. Verify File Creation

```bash
# Check that BaseBackend and SubagentMetadata exist in base.py
grep -n "class BaseBackend" spec/integrations/backends/base.py
grep -n "class SubagentMetadata" spec/integrations/backends/base.py
```

### 2. Verify Imports

```bash
# Test imports work correctly
python -c "from spec.integrations.backends import BaseBackend, SubagentMetadata; print('OK')"

# Test all exports
python -c "from spec.integrations.backends import AIBackend, BaseBackend, SubagentMetadata, BackendTimeoutError; print('All imports OK')"
```

### 3. Verify Abstract Class Behavior

```bash
# This should raise TypeError because BaseBackend is abstract
python -c "from spec.integrations.backends.base import BaseBackend; BaseBackend()" 2>&1 | grep -q "TypeError" && echo "Abstract enforcement works"
```

### 4. Run Type Checking

```bash
# Ensure PyYAML type stubs are installed (required for --strict)
pip install types-PyYAML

# Run mypy on the backends module
mypy spec/integrations/backends/base.py --strict

# Or run full type check
mypy spec/ --strict

# Alternative if types-PyYAML is not installed:
mypy spec/integrations/backends/base.py --strict --ignore-missing-imports
```

### 5. Run Tests

```bash
# Run unit tests for BaseBackend
pytest tests/test_base_backend.py -v

# Run all backend tests
pytest tests/test_*backend*.py -v
```

---

## Definition of Done

### Code Changes

- [ ] `SubagentMetadata` dataclass added to `spec/integrations/backends/base.py`
- [ ] `BaseBackend` abstract class added to `spec/integrations/backends/base.py`
- [ ] Protected helper methods implemented:
  - [ ] `_parse_subagent_prompt()` - YAML frontmatter parsing
  - [ ] `_resolve_model()` - Model precedence resolution
  - [ ] `_run_streaming_with_timeout()` - Watchdog timeout pattern
- [ ] Default implementations provided:
  - [ ] `supports_parallel` property (default True)
  - [ ] `supports_parallel_execution()` method
  - [ ] `close()` method (no-op)
- [ ] Abstract method declarations added:
  - [ ] `name` property
  - [ ] `platform` property
  - [ ] `run_with_callback()`
  - [ ] `run_print_with_output()`
  - [ ] `run_print_quiet()`
  - [ ] `run_streaming()`
  - [ ] `check_installed()`
  - [ ] `detect_rate_limit()`
- [ ] `spec/integrations/backends/__init__.py` exports `BaseBackend` and `SubagentMetadata`

### Testing

- [ ] Unit tests for `SubagentMetadata` dataclass
- [ ] Unit tests for `_parse_subagent_prompt()`:
  - [ ] With frontmatter (model + temperature)
  - [ ] Without frontmatter
  - [ ] Invalid YAML (graceful fallback)
  - [ ] Missing file (returns empty)
  - [ ] Model only (no temperature)
  - [ ] Empty frontmatter (`---\n---\n`)
  - [ ] Extra unknown fields (ignored gracefully)
- [ ] Unit tests for `_resolve_model()` (explicit override, frontmatter, default, none)
- [ ] Unit tests for `_run_streaming_with_timeout()`:
  - [ ] Process completes before timeout
  - [ ] Process exceeds timeout (raises `BackendTimeoutError`)
  - [ ] No timeout specified (`timeout_seconds=None`)
  - [ ] Callback receives stripped lines
- [ ] Unit tests for abstract class enforcement (cannot instantiate, must implement all)
- [ ] Unit tests for default implementations (`supports_parallel`, `close`)
- [ ] All tests pass: `pytest tests/test_base_backend.py -v`

### Type Checking

- [ ] `types-PyYAML` installed for type stubs
- [ ] No mypy errors: `mypy spec/integrations/backends/base.py --strict`

### Documentation

- [ ] Docstrings for all public classes and methods
- [ ] Examples in docstrings where appropriate
- [ ] Module docstring updated to mention BaseBackend

### Code Review

- [ ] PR approved by at least one reviewer
- [ ] No unresolved comments

---

## Estimated Effort

| Phase | Description | Estimated Time |
|-------|-------------|----------------|
| Phase 1 | Create SubagentMetadata dataclass | 0.05 days |
| Phase 2 | Create BaseBackend class with helpers | 0.15 days |
| Phase 3 | Add abstract method declarations | 0.05 days |
| Phase 4 | Update package exports | 0.02 days |
| Testing | Write and run unit tests | 0.15 days |
| Review | Code review and refinements | 0.05 days |
| **Total** | | **~0.45 days** |

**Comparison to Similar Tickets:**
- AMI-47 (Backend Error Types): ~0.35-0.4 days
- AMI-48 (AIBackend Protocol): ~0.35 days
- AMI-49 (BaseBackend): ~0.45 days (slightly more due to timeout watchdog implementation)

---

## References

### Code References

| File | Lines | Description |
|------|-------|-------------|
| `spec/integrations/backends/base.py` | 1-248 | Current AIBackend Protocol (AMI-48) |
| `spec/integrations/backends/errors.py` | 1-118 | Backend error types including BackendTimeoutError |
| `spec/integrations/backends/__init__.py` | 1-34 | Current package exports |
| `spec/config/fetch_config.py` | 49-64 | AgentPlatform enum definition |

### Specification References

| Document | Section | Description |
|----------|---------|-------------|
| `specs/Pluggable Multi-Agent Support.md` | Lines 1436-1716 | Phase 1.3: BaseBackend specification |
| `specs/Pluggable Multi-Agent Support.md` | Lines 577-711 | Timeout Enforcement watchdog implementation |
| `specs/Pluggable Multi-Agent Support.md` | Lines 267-295 | Final Decision #8: YAML Frontmatter Stripping |

### Related Implementation Plans

| Document | Description |
|----------|-------------|
| `specs/AMI-47-implementation-plan.md` | Backend Error Types implementation |
| `specs/AMI-48-implementation-plan.md` | AIBackend Protocol implementation |
| `specs/AMI-44-implementation-plan.md` | Baseline Behavior Tests |

---

## Appendix: Full BaseBackend Class Structure

```python
# spec/integrations/backends/base.py (after AMI-49 implementation)

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
import logging
import subprocess
import threading

import yaml

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.errors import BackendTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class SubagentMetadata:
    model: str | None = None
    temperature: float | None = None


@runtime_checkable
class AIBackend(Protocol):
    # ... (existing protocol from AMI-48) ...


class BaseBackend(ABC):
    """Abstract base class with common functionality for all backends."""

    def __init__(self, model: str = "") -> None:
        self._model = model

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def platform(self) -> AgentPlatform: ...

    @property
    def supports_parallel(self) -> bool:
        return True

    def supports_parallel_execution(self) -> bool:
        return self.supports_parallel

    def close(self) -> None:
        pass

    def _parse_subagent_prompt(self, subagent: str) -> tuple[SubagentMetadata, str]:
        # ... implementation ...

    def _resolve_model(
        self,
        explicit_model: str | None,
        subagent: str | None,
    ) -> str | None:
        # ... implementation ...

    def _run_streaming_with_timeout(
        self,
        cmd: list[str],
        output_callback: Callable[[str], None],
        timeout_seconds: float | None,
    ) -> tuple[int, str]:
        # ... implementation ...

    @abstractmethod
    def run_with_callback(...) -> tuple[bool, str]: ...

    @abstractmethod
    def run_print_with_output(...) -> tuple[bool, str]: ...

    @abstractmethod
    def run_print_quiet(...) -> str: ...

    @abstractmethod
    def run_streaming(...) -> tuple[bool, str]: ...

    @abstractmethod
    def check_installed(self) -> tuple[bool, str]: ...

    @abstractmethod
    def detect_rate_limit(self, output: str) -> bool: ...
```
