"""Aider CLI integration for INGOT.

This module provides the Aider CLI wrapper, installation checking,
rate limit detection, and command execution.

Like Cursor, Aider has no system prompt file equivalent. Subagent prompt
composition is AiderBackend's responsibility (not the client's).
The client receives a pre-composed prompt.

Uses --message-file (temp file) instead of --message to avoid ARG_MAX
limits on large prompts.
"""

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ingot.utils.logging import check_cli_installed, log_backend_metadata, log_command, log_message

AIDER_CLI_NAME = "aider"


def check_aider_installed() -> tuple[bool, str]:
    """Check if Aider CLI is installed and accessible.

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    return check_cli_installed(AIDER_CLI_NAME)


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in Aider output.

    Aider proxies multiple LLM providers, so we add extra keywords
    for capacity and overloaded errors.

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    # Lazy import to break circular dependency
    from ingot.integrations.backends.base import matches_common_rate_limit

    return matches_common_rate_limit(output, extra_keywords=("capacity", "overloaded"))


class AiderClient:
    """Wrapper for Aider CLI commands.

    This is a thin subprocess wrapper. Model resolution and subagent parsing
    are handled by AiderBackend (via BaseBackend). The client accepts
    pre-resolved values and a pre-composed prompt.

    Uses --message-file with a temp file instead of --message to avoid
    ARG_MAX limits on large prompts.

    Attributes:
        model: Default model to use for commands
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Aider client.

        Args:
            model: Default model to use for commands
        """
        self.model = model

    def build_command(
        self,
        prompt: str,
        *,
        model: str | None = None,
        message_file: str | None = None,
    ) -> list[str]:
        """Build aider command list.

        All parameters are pre-resolved by the caller (typically AiderBackend).

        Args:
            prompt: The prompt to send to Aider (pre-composed with any
                subagent instructions). Ignored if message_file is provided.
            model: Resolved model name (None = use instance default)
            message_file: Path to a file containing the prompt. If provided,
                uses --message-file instead of --message.

        Returns:
            List of command arguments for subprocess
        """
        cmd = [AIDER_CLI_NAME]

        cmd.append("--yes-always")
        cmd.append("--no-auto-commits")
        cmd.append("--no-detect-urls")

        # Use explicit model or fall back to instance default
        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if message_file:
            cmd.extend(["--message-file", message_file])
        else:
            cmd.extend(["--message", prompt])

        return cmd

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: str | None = None,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Uses a temp file for the prompt to avoid ARG_MAX limits.

        Args:
            prompt: The prompt to send to Aider (pre-composed)
            output_callback: Callback function invoked for each output line
            model: Resolved model name

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        log_message(f"Running {AIDER_CLI_NAME} with callback (streaming)")
        log_backend_metadata("aider", model=model)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="ingot_aider_"
        ) as f:
            f.write(prompt)
            message_file = f.name

        try:
            cmd = self.build_command(prompt, model=model, message_file=message_file)

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines: list[str] = []
            if process.stdout is not None:
                for line in process.stdout:
                    stripped = line.rstrip("\n")
                    output_callback(stripped)
                    output_lines.append(line)

            process.wait()
            log_command(AIDER_CLI_NAME, process.returncode)

            return process.returncode == 0, "".join(output_lines)
        finally:
            Path(message_file).unlink(missing_ok=True)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Run and return success status and captured output.

        Uses a temp file for the prompt to avoid ARG_MAX limits.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            timeout_seconds: Maximum execution time.

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {AIDER_CLI_NAME} with output capture")
        log_backend_metadata("aider", model=model, timeout=timeout_seconds)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="ingot_aider_"
        ) as f:
            f.write(prompt)
            message_file = f.name

        try:
            cmd = self.build_command(prompt, model=model, message_file=message_file)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(AIDER_CLI_NAME, result.returncode)

            success = result.returncode == 0
            output = result.stdout or ""

            if not success and not output and result.stderr:
                output = result.stderr

            return success, output
        finally:
            Path(message_file).unlink(missing_ok=True)

    def run_print_quiet(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run quietly, return output only.

        Uses a temp file for the prompt to avoid ARG_MAX limits.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            timeout_seconds: Maximum execution time.

        Returns:
            Command stdout (or stderr if stdout is empty and command failed)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {AIDER_CLI_NAME} quietly")
        log_backend_metadata("aider", model=model, timeout=timeout_seconds)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="ingot_aider_"
        ) as f:
            f.write(prompt)
            message_file = f.name

        try:
            cmd = self.build_command(prompt, model=model, message_file=message_file)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
            )
            log_command(AIDER_CLI_NAME, result.returncode)

            output = result.stdout or ""

            if not output and result.returncode != 0 and result.stderr:
                output = result.stderr

            return output
        finally:
            Path(message_file).unlink(missing_ok=True)


__all__ = [
    "AIDER_CLI_NAME",
    "AiderClient",
    "check_aider_installed",
    "looks_like_rate_limit",
]
