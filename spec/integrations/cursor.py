"""Cursor IDE CLI integration for SPEC.

This module provides the Cursor CLI wrapper, installation checking,
rate limit detection, and command execution.

Key difference from Claude: Cursor has no --append-system-prompt-file
equivalent. Subagent prompt composition is CursorBackend's responsibility
(not the client's). The client receives a pre-composed prompt.

Stability mechanisms (startup jitter, spawn retry) are included for
reliable parallel execution of multiple Cursor CLI invocations.
"""

import random
import shutil
import subprocess
import time
from collections.abc import Callable

from spec.utils.logging import log_command, log_message

CURSOR_CLI_NAME = "cursor"

# Stability mechanism constants for parallel execution
CURSOR_STARTUP_DELAY_MIN_MS = 50
CURSOR_STARTUP_DELAY_MAX_MS = 200
CURSOR_SPAWN_MAX_RETRIES = 2
CURSOR_SPAWN_RETRY_DELAY_S = 1.0


def check_cursor_installed() -> tuple[bool, str]:
    """Check if Cursor CLI is installed and accessible.

    Checks for both "cursor" and "agent" CLI commands.

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    # Try "cursor" first, then "agent" fallback
    for cmd_name in (CURSOR_CLI_NAME, "agent"):
        if shutil.which(cmd_name):
            try:
                result = subprocess.run(
                    [cmd_name, "--version"],
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    timeout=10,
                )
                log_command(f"{cmd_name} --version", result.returncode)

                version_output = result.stdout.strip() or result.stderr.strip()
                if result.returncode == 0 and version_output:
                    return True, version_output

            except Exception as e:
                log_message(f"Failed to check {cmd_name} CLI: {e}")
                continue

    return False, "Cursor CLI is not installed or not in PATH"


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in Cursor output.

    Detects rate limit errors by checking for common HTTP status codes
    and rate limit keywords in the output.  Uses word-boundary matching
    for numeric status codes to avoid false positives on ticket IDs.

    Cursor-specific additions beyond common patterns:
    - ``overloaded``: Cursor API overloaded response

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    # Lazy import to break circular dependency:
    # cursor.py -> backends/__init__.py -> base.py (circular at import time).
    from spec.integrations.backends.base import matches_common_rate_limit

    return matches_common_rate_limit(output, extra_keywords=("overloaded",))


def _log_command_metadata(
    *,
    model: str | None = None,
    timeout: float | None = None,
) -> None:
    """Log sanitized command metadata for debugging without leaking prompts."""
    parts = []
    if model:
        parts.append(f"model={model}")
    if timeout is not None:
        parts.append(f"timeout={timeout}s")
    if parts:
        log_message(f"  cursor metadata: {', '.join(parts)}")


class CursorClient:
    """Wrapper for Cursor CLI commands.

    This is a thin subprocess wrapper. Model resolution and subagent parsing
    are handled by CursorBackend (via BaseBackend). The client accepts
    pre-resolved values and a pre-composed prompt (subagent instructions
    already embedded by CursorBackend).

    Unlike ClaudeClient, this client has no system_prompt parameter since
    Cursor has no --append-system-prompt-file equivalent.

    Stability mechanisms (startup jitter, spawn retry) are included for
    reliable parallel execution.

    Attributes:
        model: Default model to use for commands
        _enable_startup_jitter: Whether to apply random startup delay
        _cli_command: Cached detected CLI command name
        _model_flag_supported: Cached result of --model flag check
    """

    def __init__(self, model: str = "", enable_startup_jitter: bool = True) -> None:
        """Initialize the Cursor client.

        Args:
            model: Default model to use for commands
            enable_startup_jitter: Whether to apply random startup delay
                for parallel execution stability (default: True)
        """
        self.model = model
        self._enable_startup_jitter = enable_startup_jitter
        self._cli_command: str | None = None
        self._model_flag_supported: bool | None = None

    def _detect_cli_command(self) -> str:
        """Detect the available CLI command.

        Checks for "cursor" first, then "agent" as fallback.
        Caches the result for the session.

        Returns:
            The detected CLI command name.
        """
        if self._cli_command is not None:
            return self._cli_command

        for cmd_name in (CURSOR_CLI_NAME, "agent"):
            if shutil.which(cmd_name):
                self._cli_command = cmd_name
                return cmd_name

        # Default to "cursor" even if not found (will fail at execution)
        self._cli_command = CURSOR_CLI_NAME
        return CURSOR_CLI_NAME

    def _supports_model_flag(self) -> bool:
        """Check if the CLI supports --model flag.

        Inspects --help output. Caches the result per session.

        Returns:
            True if --model flag is supported.
        """
        if self._model_flag_supported is not None:
            return self._model_flag_supported

        cli = self._detect_cli_command()
        try:
            result = subprocess.run(
                [cli, "--help"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            help_output = result.stdout + result.stderr
            self._model_flag_supported = "--model" in help_output
        except Exception:
            self._model_flag_supported = False

        return self._model_flag_supported

    def build_command(
        self,
        prompt: str,
        *,
        model: str | None = None,
        print_mode: bool = False,
        no_save: bool = False,
    ) -> list[str]:
        """Build cursor command list.

        All parameters are pre-resolved by the caller (typically CursorBackend).
        This method just assembles the CLI arguments.

        Args:
            prompt: The prompt to send to Cursor (pre-composed with any
                subagent instructions)
            model: Resolved model name (None = use instance default)
            print_mode: Use --print flag for non-interactive mode
            no_save: Use --no-save flag for session isolation

        Returns:
            List of command arguments for subprocess
        """
        cli = self._detect_cli_command()
        cmd = [cli]

        if print_mode:
            cmd.append("--print")

        # Use explicit model or fall back to instance default
        effective_model = model or self.model
        if effective_model and self._supports_model_flag():
            cmd.extend(["--model", effective_model])

        if no_save:
            cmd.append("--no-save")

        # Prompt as final positional argument
        cmd.append(prompt)
        return cmd

    def _apply_startup_jitter(self) -> None:
        """Apply random startup delay for parallel execution stability.

        Spreads out parallel CLI invocations to avoid resource contention.
        Delay is between CURSOR_STARTUP_DELAY_MIN_MS and
        CURSOR_STARTUP_DELAY_MAX_MS milliseconds.
        """
        if not self._enable_startup_jitter:
            return

        delay_ms = random.randint(  # noqa: S311
            CURSOR_STARTUP_DELAY_MIN_MS, CURSOR_STARTUP_DELAY_MAX_MS
        )
        time.sleep(delay_ms / 1000.0)

    def _is_transient_spawn_error(self, output: str) -> bool:
        """Detect transient spawn errors that may resolve on retry.

        Args:
            output: The output/error string to check

        Returns:
            True if the error looks transient and retryable.
        """
        output_lower = output.lower()
        patterns = [
            "socket in use",
            "server busy",
            "eaddrinuse",
            "connection refused",
            "spawn error",
            "failed to start",
        ]
        return any(p in output_lower for p in patterns)

    def _run_with_spawn_retry(self, run_func: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
        """Wrap a run function with spawn retry logic.

        Retries on transient spawn errors (e.g., socket in use) and
        OSError (e.g., too many open files).

        Args:
            run_func: The function to execute (returns (success, output))

        Returns:
            Tuple of (success, output) from the run function.
        """
        last_error: Exception | None = None
        last_output = ""

        for attempt in range(1 + CURSOR_SPAWN_MAX_RETRIES):
            try:
                success, output = run_func()
                if success or not self._is_transient_spawn_error(output):
                    return success, output
                last_output = output
            except OSError as e:
                last_error = e
                last_output = str(e)

            if attempt < CURSOR_SPAWN_MAX_RETRIES:
                delay = CURSOR_SPAWN_RETRY_DELAY_S * (2**attempt)
                log_message(
                    f"Transient spawn error on attempt {attempt + 1}, "
                    f"retrying in {delay}s "
                    f"({CURSOR_SPAWN_MAX_RETRIES - attempt} retries left)"
                )
                time.sleep(delay)

        if last_error is not None:
            raise last_error

        return False, last_output

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: str | None = None,
        no_save: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Uses subprocess.Popen with line-by-line output processing.
        Each line is passed to output_callback AND collected for return.
        Applies startup jitter and spawn retry for stability.

        Args:
            prompt: The prompt to send to Cursor (pre-composed)
            output_callback: Callback function invoked for each output line
            model: Resolved model name
            no_save: If True, use --no-save for session isolation

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        cli = self._detect_cli_command()
        log_message(f"Running {cli} with callback (streaming)")
        _log_command_metadata(model=model)

        self._apply_startup_jitter()

        def _run() -> tuple[bool, str]:
            cmd = self.build_command(
                prompt,
                model=model,
                print_mode=True,
                no_save=no_save,
            )

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
            )

            output_lines: list[str] = []
            if process.stdout is not None:
                for line in process.stdout:
                    stripped = line.rstrip("\n")
                    output_callback(stripped)
                    output_lines.append(line)

            process.wait()
            log_command(cli, process.returncode)

            return process.returncode == 0, "".join(output_lines)

        return self._run_with_spawn_retry(_run)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        model: str | None = None,
        no_save: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Run with --print flag, return success status and captured output.

        Captures output silently (no stdout printing). The backend layer
        does not own terminal output; SPEC owns the TUI.
        Applies startup jitter and spawn retry for stability.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            no_save: If True, use --no-save for session isolation
            timeout_seconds: Maximum execution time. When exceeded the
                subprocess is killed and subprocess.TimeoutExpired is raised.

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        cli = self._detect_cli_command()
        log_message(f"Running {cli} with output capture")
        _log_command_metadata(model=model, timeout=timeout_seconds)

        self._apply_startup_jitter()

        def _run() -> tuple[bool, str]:
            cmd = self.build_command(
                prompt,
                model=model,
                print_mode=True,
                no_save=no_save,
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(cli, result.returncode)

            success = result.returncode == 0
            output = result.stdout or ""

            # Include stderr context when CLI fails with no stdout
            if not success and not output and result.stderr:
                output = result.stderr

            return success, output

        return self._run_with_spawn_retry(_run)

    def run_print_quiet(
        self,
        prompt: str,
        *,
        model: str | None = None,
        no_save: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run with --print flag quietly, return output only.

        Applies startup jitter and spawn retry for stability.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            no_save: If True, use --no-save for session isolation
            timeout_seconds: Maximum execution time. When exceeded the
                subprocess is killed and subprocess.TimeoutExpired is raised.

        Returns:
            Command stdout (or stderr if stdout is empty and command failed)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        cli = self._detect_cli_command()
        log_message(f"Running {cli} quietly")
        _log_command_metadata(model=model, timeout=timeout_seconds)

        self._apply_startup_jitter()

        def _run() -> tuple[bool, str]:
            cmd = self.build_command(
                prompt,
                model=model,
                print_mode=True,
                no_save=no_save,
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(cli, result.returncode)

            output = result.stdout or ""

            # Include stderr context when CLI fails with no stdout
            if not output and result.returncode != 0 and result.stderr:
                output = result.stderr

            return result.returncode == 0, output

        _, output = self._run_with_spawn_retry(_run)
        return output


__all__ = [
    "CURSOR_CLI_NAME",
    "CURSOR_SPAWN_MAX_RETRIES",
    "CURSOR_SPAWN_RETRY_DELAY_S",
    "CURSOR_STARTUP_DELAY_MAX_MS",
    "CURSOR_STARTUP_DELAY_MIN_MS",
    "CursorClient",
    "check_cursor_installed",
    "looks_like_rate_limit",
]
