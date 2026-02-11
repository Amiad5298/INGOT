"""AI Backend protocol and base types.

This module defines the contract for AI backend integrations:
- AIBackend: Protocol for all backend implementations
- BaseBackend: Abstract base class with shared logic (Phase 1.3)
- SubagentMetadata: Parsed frontmatter from subagent prompt files

All backends execute in non-interactive mode for deterministic behavior.
User input is collected via the TUI, then included in prompts.
"""

import logging
import os
import re
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.errors import BackendTimeoutError

# ── Shared rate-limit detection ──────────────────────────────────────────────
# Only match actual rate-limit status codes with word boundaries to prevent
# false positives on ticket IDs (e.g., "PROJ-4290").
# Server errors (502/503/504) are NOT rate limits — they are retried
# separately via _is_retryable_error() using config.retryable_status_codes.
_HTTP_RATE_LIMIT_STATUS_RE = re.compile(r"\b429\b")

_COMMON_RATE_LIMIT_KEYWORDS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota exceeded",
    "throttl",
)


def matches_common_rate_limit(
    output: str,
    *,
    extra_keywords: tuple[str, ...] = (),
    extra_status_re: re.Pattern[str] | None = None,
) -> bool:
    """Check if output matches common rate-limit patterns.

    Shared by all backend looks_like_rate_limit functions. Backends call
    this with their own ``extra_keywords`` / ``extra_status_re`` to layer
    provider-specific patterns on top of the common set.
    """
    if not output:
        return False
    output_lower = output.lower()
    if _HTTP_RATE_LIMIT_STATUS_RE.search(output_lower):
        return True
    if extra_status_re and extra_status_re.search(output_lower):
        return True
    all_keywords = _COMMON_RATE_LIMIT_KEYWORDS + extra_keywords
    return any(kw in output_lower for kw in all_keywords)


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


@runtime_checkable
class AIBackend(Protocol):
    """Protocol for AI backend integrations.

    This defines the contract for AI providers (Auggie, Claude Code, Cursor).
    Each backend wraps its respective CLI tool.

    All methods execute in non-interactive mode for deterministic behavior.
    User input is collected via the TUI, then included in prompts.

    Note: This protocol does NOT include run_print() (interactive mode).
    INGOT owns interactive UX; backends operate in streaming/print mode only.

    Note on timeout_seconds: Timeout enforcement is optional per backend.
    run_with_callback() enforces timeouts via BaseBackend._run_streaming_with_timeout().
    Other methods (run_print_with_output, run_print_quiet) may accept timeout_seconds
    per the protocol but not enforce it. Check backend-specific docs for details.

    Example:
        >>> def run_workflow(backend: AIBackend) -> None:
        ...     success, output = backend.run_with_callback(
        ...         "Generate a plan",
        ...         output_callback=print,
        ...         subagent="ingot-planner",
        ...     )
        ...     if not success:
        ...         if backend.detect_rate_limit(output):
        ...             raise BackendRateLimitError(...)
    """

    @property
    def name(self) -> str:
        """Human-readable backend name.

        Examples: 'Auggie', 'Claude Code', 'Cursor'
        """
        ...

    @property
    def platform(self) -> AgentPlatform:
        """The agent platform enum value."""
        ...

    @property
    def model(self) -> str:
        """Default model for this backend instance.

        Used by BackendFactory to forward the model when creating
        fresh backend instances (e.g., for parallel execution workers).
        """
        ...

    @property
    def supports_parallel(self) -> bool:
        """Whether this backend supports parallel execution.

        If False, Step 3 falls back to sequential task execution.
        If True, Step 3 can spawn concurrent backend invocations.

        Note: This property indicates capability, not a setting.
        Use --no-parallel CLI flag to disable parallel execution
        even for backends that support it.
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

        This is the primary execution method. Output is streamed line-by-line
        to the callback while also being accumulated for the return value.

        Args:
            prompt: The prompt to send to the AI.
            output_callback: Called for each line of output (stripped of newline).
            subagent: Subagent name (loads prompt from .augment/agents/{name}.md).
            model: Model override (best-effort, safely ignored if unsupported).
            dont_save_session: If True, isolate this execution (no session persistence).
            timeout_seconds: Maximum execution time (None = no timeout).

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
            BackendNotInstalledError: If CLI is not installed.
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
        """Execute prompt (non-interactive) and return output.

        Convenience method that wraps run_with_callback with a default
        print callback. Output is printed to stdout as it streams.
        """
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
        """Execute prompt quietly (non-interactive) and return output only.

        No output is printed during execution. This is used for background
        operations where only the final result matters.

        Note:
            Callers must check the content to determine success/failure.
            This matches the existing AuggieClient.run_print_quiet() behavior.
        """
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
        """Check if the backend CLI is installed and functional.

        Verifies that the CLI executable is available in PATH and can
        execute a basic command (typically --version).

        Example:
            >>> installed, msg = backend.check_installed()
            >>> if not installed:
            ...     raise BackendNotInstalledError(msg)
        """
        ...

    def detect_rate_limit(self, output: str) -> bool:
        """Check if output indicates a rate limit error.

        Backend-specific pattern matching for rate limit detection.
        Each backend implements patterns appropriate for its provider.

        Example patterns:
            - HTTP 429 status codes
            - "rate limit", "rate_limit"
            - "quota exceeded"
            - "too many requests"
            - "throttle", "throttling"
        """
        ...

    def supports_parallel_execution(self) -> bool:
        """Whether this backend can handle concurrent invocations.

        Returns the value of the `supports_parallel` property.
        This method exists for explicit API clarity in workflow code.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the backend.

        Called when workflow completes or on cleanup.
        Default implementation is no-op for stateless backends.

        Implementations may:
        - Terminate subprocess connections
        - Close file handles
        - Clean up temporary files
        """
        ...


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
        """Initialize the backend with optional default model."""
        self._model = model

    @property
    def model(self) -> str:
        """Default model for this backend instance."""
        return self._model

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
        """The agent platform enum value."""
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
        """
        return self.supports_parallel

    def close(self) -> None:  # noqa: B027
        """Release any resources held by the backend.

        Default implementation is no-op. Override if cleanup needed.

        Called when workflow completes or on cleanup. Implementations may:
        - Terminate subprocess connections
        - Close file handles
        - Clean up temporary files
        """
        pass

    def _parse_subagent_prompt(self, subagent: str) -> tuple[SubagentMetadata, str]:
        """Parse subagent prompt file and extract frontmatter.

        Shared across all backends to ensure consistent parsing.
        Per Decision 6 (Subagent Frontmatter Handling), YAML frontmatter is
        stripped from prompts.

        The function looks for files in `.augment/agents/{subagent}.md`.
        If the file starts with `---`, it parses the YAML frontmatter.

        Example:
            >>> metadata, body = backend._parse_subagent_prompt("ingot-planner")
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

    def _resolve_subagent(
        self,
        subagent: str | None,
        model: str | None,
    ) -> tuple[str | None, str | None]:
        """Resolve subagent and model in one pass.

        Uses _parse_subagent_prompt() to get both the prompt body and
        model from frontmatter. Avoids reading the subagent file twice.

        Model precedence: explicit > frontmatter > instance default.

        Args:
            subagent: Optional subagent name.
            model: Optional explicit model override.

        Returns:
            Tuple of (resolved_model, subagent_prompt_body).
        """
        subagent_prompt: str | None = None

        if subagent:
            metadata, prompt_body = self._parse_subagent_prompt(subagent)
            subagent_prompt = prompt_body if prompt_body else None

            if not model and metadata.model:
                model = metadata.model

        resolved_model = model or self._model or None
        return resolved_model, subagent_prompt

    def _compose_prompt(self, prompt: str, subagent_prompt: str | None) -> str:
        """Compose the final prompt with optional subagent instructions.

        For backends without a system prompt file mechanism, subagent
        instructions are embedded directly in the user prompt.

        Args:
            prompt: The user/task prompt.
            subagent_prompt: Optional subagent instructions to embed.

        Returns:
            The composed prompt string.
        """
        if subagent_prompt:
            return f"## Agent Instructions\n\n{subagent_prompt}\n\n## Task\n\n{prompt}"
        return prompt

    def _run_streaming_with_timeout(
        self,
        cmd: list[str],
        output_callback: Callable[[str], None],
        timeout_seconds: float | None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        """Run subprocess with streaming output and timeout enforcement.

        This is the shared timeout implementation used by all backends.
        Uses a watchdog thread pattern for streaming-safe timeout enforcement.

        Backends call this method from their run_with_callback() implementations
        to get consistent timeout behavior across all backend types.

        The watchdog thread:
        1. Starts when timeout_seconds is provided
        2. Waits on a stop_event for timeout_seconds
        3. If not stopped, terminates the process (SIGTERM -> SIGKILL)

        Raises:
            BackendTimeoutError: If execution exceeds timeout_seconds.

        Example:
            >>> return_code, output = self._run_streaming_with_timeout(
            ...     ["augment", "agent", "--print", "-p", prompt],
            ...     output_callback=lambda line: print(line),
            ...     timeout_seconds=120.0,
            ... )
        """
        process_env = None
        if env:
            process_env = {**os.environ, **env}

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line-buffered
            env=process_env,
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
        if timeout_seconds is not None:
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
            return_code = process.returncode if process.returncode is not None else -1
            return return_code, "".join(output_lines)

        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

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
