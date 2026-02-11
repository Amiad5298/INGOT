"""Codex CLI integration for INGOT.

This module provides the OpenAI Codex CLI wrapper, installation checking,
rate limit detection, and command execution.

Key difference from other CLIs: Codex uses `codex exec "prompt"` subcommand
pattern. stderr is merged into stdout for unified streaming.
"""

import subprocess
from collections.abc import Callable

from ingot.utils.logging import check_cli_installed, log_backend_metadata, log_command, log_message

CODEX_CLI_NAME = "codex"


def check_codex_installed() -> tuple[bool, str]:
    """Check if Codex CLI is installed and accessible.

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    return check_cli_installed(CODEX_CLI_NAME)


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in Codex output.

    OpenAI-specific additions beyond common patterns:
    - ``overloaded``: API overloaded response
    - ``capacity``: Capacity exceeded
    - ``server_error``: OpenAI server error

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    # Lazy import to break circular dependency
    from ingot.integrations.backends.base import matches_common_rate_limit

    return matches_common_rate_limit(
        output, extra_keywords=("overloaded", "capacity", "server_error")
    )


class CodexClient:
    """Wrapper for Codex CLI commands.

    This is a thin subprocess wrapper. Model resolution and subagent parsing
    are handled by CodexBackend (via BaseBackend). The client accepts
    pre-resolved values and a pre-composed prompt.

    Uses `codex exec "prompt"` subcommand pattern. stderr is merged
    into stdout (stderr=subprocess.STDOUT) for unified streaming.

    Attributes:
        model: Default model to use for commands
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Codex client.

        Args:
            model: Default model to use for commands
        """
        self.model = model

    def build_command(
        self,
        prompt: str,
        *,
        model: str | None = None,
        ephemeral: bool = False,
        full_auto: bool = True,
    ) -> list[str]:
        """Build codex command list.

        Args:
            prompt: The prompt to send to Codex (pre-composed with any
                subagent instructions)
            model: Resolved model name (None = use instance default)
            ephemeral: If True, use --ephemeral for session isolation
            full_auto: If True, use --full-auto for auto-approve

        Returns:
            List of command arguments for subprocess
        """
        cmd = [CODEX_CLI_NAME, "exec"]

        if full_auto:
            cmd.append("--full-auto")

        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        if ephemeral:
            cmd.append("--ephemeral")

        # Prompt as final positional argument.
        # NOTE: Unlike Aider (which uses --message-file), Codex only accepts
        # a positional prompt. Very large prompts (>256KB) may hit OS ARG_MAX
        # limits. This is a Codex CLI limitation with no upstream workaround.
        cmd.append(prompt)
        return cmd

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: str | None = None,
        ephemeral: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Merges stderr into stdout for unified streaming.

        Args:
            prompt: The prompt to send to Codex (pre-composed)
            output_callback: Callback function invoked for each output line
            model: Resolved model name
            ephemeral: If True, use --ephemeral for session isolation

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        log_message(f"Running {CODEX_CLI_NAME} with callback (streaming)")
        log_backend_metadata("codex", model=model)

        cmd = self.build_command(prompt, model=model, ephemeral=ephemeral)

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
        log_command(CODEX_CLI_NAME, process.returncode)

        return process.returncode == 0, "".join(output_lines)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        model: str | None = None,
        ephemeral: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Run and return success status and captured output.

        Merges stderr into stdout for unified output.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            ephemeral: If True, use --ephemeral for session isolation
            timeout_seconds: Maximum execution time.

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {CODEX_CLI_NAME} with output capture")
        log_backend_metadata("codex", model=model, timeout=timeout_seconds)

        cmd = self.build_command(prompt, model=model, ephemeral=ephemeral)

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
        log_command(CODEX_CLI_NAME, result.returncode)

        success = result.returncode == 0
        output = result.stdout or ""

        return success, output

    def run_print_quiet(
        self,
        prompt: str,
        *,
        model: str | None = None,
        ephemeral: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run quietly, return output only.

        Merges stderr into stdout for unified output.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            ephemeral: If True, use --ephemeral for session isolation
            timeout_seconds: Maximum execution time.

        Returns:
            Command output (stdout + stderr merged)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {CODEX_CLI_NAME} quietly")
        log_backend_metadata("codex", model=model, timeout=timeout_seconds)

        cmd = self.build_command(prompt, model=model, ephemeral=ephemeral)

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
        log_command(CODEX_CLI_NAME, result.returncode)

        return result.stdout or ""


__all__ = [
    "CODEX_CLI_NAME",
    "CodexClient",
    "check_codex_installed",
    "looks_like_rate_limit",
]
