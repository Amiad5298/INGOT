"""Claude Code CLI integration for SPEC.

This module provides the Claude Code CLI wrapper, installation checking,
rate limit detection, and command execution.

Key difference from Auggie: Subagent instructions are injected via
--append-system-prompt-file (print mode only), which keeps prompt
content out of the process argument list (avoids ps/proc exposure
and OS ARG_MAX limits).
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from spec.utils.logging import log_command, log_message

CLAUDE_CLI_NAME = "claude"


def check_claude_installed() -> tuple[bool, str]:
    """Check if Claude Code CLI is installed and accessible.

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    if not shutil.which(CLAUDE_CLI_NAME):
        return False, "Claude Code CLI is not installed or not in PATH"

    try:
        result = subprocess.run(
            [CLAUDE_CLI_NAME, "--version"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        log_command(f"{CLAUDE_CLI_NAME} --version", result.returncode)

        version_output = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0 and version_output:
            return True, version_output

        return False, "Claude Code CLI found but could not determine version"
    except Exception as e:
        log_message(f"Failed to check Claude Code CLI: {e}")
        return False, f"Error checking Claude Code CLI: {e}"


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in Claude/Anthropic output.

    Detects rate limit errors by checking for common HTTP status codes
    and rate limit keywords in the output.

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    output_lower = output.lower()
    patterns = [
        "429",
        "rate limit",
        "rate_limit",
        "overloaded",
        "529",
        "too many requests",
        "quota exceeded",
        "throttl",
        "502",
        "503",
        "504",
        "capacity",
    ]
    return any(p in output_lower for p in patterns)


@contextmanager
def _system_prompt_file_context(
    system_prompt: str | None,
) -> Iterator[str | None]:
    """Write system_prompt to a temp file for --append-system-prompt-file.

    Yields the temp file path if system_prompt is provided, None otherwise.
    The file is cleaned up when the context exits.
    """
    if not system_prompt:
        yield None
        return

    fd, path = tempfile.mkstemp(suffix=".md", prefix="claude-sp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(system_prompt)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _log_command_metadata(
    *,
    model: str | None = None,
    has_system_prompt: bool = False,
    timeout: float | None = None,
) -> None:
    """Log sanitized command metadata for debugging without leaking prompts."""
    parts = []
    if model:
        parts.append(f"model={model}")
    if has_system_prompt:
        parts.append("system_prompt=yes")
    if timeout is not None:
        parts.append(f"timeout={timeout}s")
    if parts:
        log_message(f"  {CLAUDE_CLI_NAME} metadata: {', '.join(parts)}")


class ClaudeClient:
    """Wrapper for Claude Code CLI commands.

    This is a thin subprocess wrapper. Model resolution and subagent parsing
    are handled by ClaudeBackend (via BaseBackend). The client accepts
    pre-resolved values. System prompts are written to temp files and passed
    via --append-system-prompt-file to avoid ARG_MAX and process list exposure.

    Attributes:
        model: Default model to use for commands
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Claude client.

        Args:
            model: Default model to use for commands
        """
        self.model = model

    def build_command(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_prompt_file: str | None = None,
        print_mode: bool = False,
        dont_save_session: bool = False,
    ) -> list[str]:
        """Build claude command list.

        All parameters are pre-resolved by the caller (typically ClaudeBackend).
        This method just assembles the CLI arguments.

        Args:
            prompt: The prompt to send to Claude
            model: Resolved model name (None = use instance default)
            system_prompt_file: Path to file containing system prompt
                (injected via --append-system-prompt-file, print mode only)
            print_mode: Use -p (print) flag
            dont_save_session: Use --no-session-persistence flag

        Returns:
            List of command arguments for subprocess
        """
        cmd = [CLAUDE_CLI_NAME]

        if print_mode:
            cmd.append("-p")

        # Use explicit model or fall back to instance default
        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if dont_save_session:
            cmd.append("--no-session-persistence")

        # Inject subagent prompt via file (avoids ARG_MAX / ps exposure)
        if system_prompt_file:
            cmd.extend(["--append-system-prompt-file", system_prompt_file])

        # Prompt as final positional argument
        cmd.append(prompt)
        return cmd

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: str | None = None,
        system_prompt: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Uses subprocess.Popen with line-by-line output processing.
        Each line is passed to output_callback AND collected for return.

        Args:
            prompt: The prompt to send to Claude
            output_callback: Callback function invoked for each output line
            model: Resolved model name
            system_prompt: Resolved subagent prompt body
            dont_save_session: If True, use --no-session-persistence

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        log_message(f"Running {CLAUDE_CLI_NAME} with callback (streaming)")
        _log_command_metadata(model=model, has_system_prompt=bool(system_prompt))

        with _system_prompt_file_context(system_prompt) as prompt_file:
            cmd = self.build_command(
                prompt,
                model=model,
                system_prompt_file=prompt_file,
                print_mode=True,
                dont_save_session=dont_save_session,
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
            log_command(CLAUDE_CLI_NAME, process.returncode)

        return process.returncode == 0, "".join(output_lines)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Run with -p flag, return success status and captured output.

        Captures output silently (no stdout printing). The backend layer
        does not own terminal output; SPEC owns the TUI.

        Args:
            prompt: The prompt to send
            model: Resolved model name
            system_prompt: Resolved subagent prompt body
            dont_save_session: If True, use --no-session-persistence
            timeout_seconds: Maximum execution time. When exceeded the
                subprocess is killed and subprocess.TimeoutExpired is raised.

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {CLAUDE_CLI_NAME} with output capture")
        _log_command_metadata(
            model=model, has_system_prompt=bool(system_prompt), timeout=timeout_seconds
        )

        with _system_prompt_file_context(system_prompt) as prompt_file:
            cmd = self.build_command(
                prompt,
                model=model,
                system_prompt_file=prompt_file,
                print_mode=True,
                dont_save_session=dont_save_session,
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(CLAUDE_CLI_NAME, result.returncode)

        success = result.returncode == 0
        output = result.stdout or ""

        # Include stderr context when CLI fails with no stdout
        if not success and not output and result.stderr:
            output = result.stderr

        return success, output

    def run_print_quiet(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run with -p flag quietly, return output only.

        Args:
            prompt: The prompt to send
            model: Resolved model name
            system_prompt: Resolved subagent prompt body
            dont_save_session: If True, use --no-session-persistence
            timeout_seconds: Maximum execution time. When exceeded the
                subprocess is killed and subprocess.TimeoutExpired is raised.

        Returns:
            Command stdout (or stderr if stdout is empty and command failed)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {CLAUDE_CLI_NAME} quietly")
        _log_command_metadata(
            model=model, has_system_prompt=bool(system_prompt), timeout=timeout_seconds
        )

        with _system_prompt_file_context(system_prompt) as prompt_file:
            cmd = self.build_command(
                prompt,
                model=model,
                system_prompt_file=prompt_file,
                print_mode=True,
                dont_save_session=dont_save_session,
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(CLAUDE_CLI_NAME, result.returncode)

        output = result.stdout or ""

        # Include stderr context when CLI fails with no stdout
        if not output and result.returncode != 0 and result.stderr:
            output = result.stderr

        return output


__all__ = [
    "CLAUDE_CLI_NAME",
    "ClaudeClient",
    "check_claude_installed",
    "looks_like_rate_limit",
]
