"""Gemini CLI integration for INGOT.

This module provides the Gemini CLI wrapper, installation checking,
rate limit detection, and command execution.

Key difference: Gemini CLI uses the GEMINI_SYSTEM_MD environment variable
to specify a system prompt file. The GeminiBackend writes subagent
instructions to a temp file and passes it via this env var.
"""

import os
import re
import subprocess
from collections.abc import Callable

from ingot.utils.logging import check_cli_installed, log_backend_metadata, log_command, log_message

GEMINI_CLI_NAME = "gemini"

# Google uses 403 for quota exhaustion
_GEMINI_EXTRA_STATUS_RE = re.compile(r"\b403\b")


def check_gemini_installed() -> tuple[bool, str]:
    """Check if Gemini CLI is installed and accessible.

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    return check_cli_installed(GEMINI_CLI_NAME)


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in Gemini output.

    Google-specific additions beyond common patterns:
    - ``resource exhausted``: Google API quota error
    - ``overloaded``: API overloaded response
    - HTTP 403: Google uses 403 for quota exhaustion

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    # Lazy import to break circular dependency
    from ingot.integrations.backends.base import matches_common_rate_limit

    return matches_common_rate_limit(
        output,
        extra_keywords=("resource exhausted", "overloaded"),
        extra_status_re=_GEMINI_EXTRA_STATUS_RE,
    )


class GeminiClient:
    """Wrapper for Gemini CLI commands.

    This is a thin subprocess wrapper. Model resolution and subagent parsing
    are handled by GeminiBackend (via BaseBackend).

    System prompt is injected via the GEMINI_SYSTEM_MD environment variable,
    which points to a temp .md file containing the subagent instructions.

    Attributes:
        model: Default model to use for commands
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Gemini client.

        Args:
            model: Default model to use for commands
        """
        self.model = model

    def build_command(
        self,
        prompt: str,
        *,
        model: str | None = None,
    ) -> list[str]:
        """Build gemini command list.

        Args:
            prompt: The prompt to send to Gemini.
            model: Resolved model name (None = use instance default)

        Returns:
            List of command arguments for subprocess
        """
        cmd = [GEMINI_CLI_NAME]

        cmd.append("--yolo")

        effective_model = model or self.model
        if effective_model:
            cmd.extend(["--model", effective_model])

        cmd.extend(["-p", prompt])

        return cmd

    @staticmethod
    def _build_env(extra_env: dict[str, str] | None = None) -> dict[str, str] | None:
        """Build environment dict with optional overrides.

        Args:
            extra_env: Additional environment variables to set.

        Returns:
            Environment dict, or None if no overrides.
        """
        if not extra_env:
            return None
        env = os.environ.copy()
        env.update(extra_env)
        return env

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        model: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Args:
            prompt: The prompt to send to Gemini (pre-composed)
            output_callback: Callback function invoked for each output line
            model: Resolved model name
            env: Optional extra environment variables

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        log_message(f"Running {GEMINI_CLI_NAME} with callback (streaming)")
        log_backend_metadata("gemini", model=model)

        cmd = self.build_command(prompt, model=model)
        process_env = self._build_env(env)

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=process_env,
        )

        output_lines: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                output_callback(stripped)
                output_lines.append(line)

        process.wait()
        log_command(GEMINI_CLI_NAME, process.returncode)

        return process.returncode == 0, "".join(output_lines)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """Run and return success status and captured output.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            timeout_seconds: Maximum execution time.
            env: Optional extra environment variables

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {GEMINI_CLI_NAME} with output capture")
        log_backend_metadata("gemini", model=model, timeout=timeout_seconds)

        cmd = self.build_command(prompt, model=model)
        process_env = self._build_env(env)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            env=process_env,
        )
        log_command(GEMINI_CLI_NAME, result.returncode)

        success = result.returncode == 0
        output = result.stdout or ""

        if not success and not output and result.stderr:
            output = result.stderr

        return success, output

    def run_print_quiet(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Run quietly, return output only.

        Args:
            prompt: The prompt to send (pre-composed)
            model: Resolved model name
            timeout_seconds: Maximum execution time.
            env: Optional extra environment variables

        Returns:
            Command stdout (or stderr if stdout is empty and command failed)

        Raises:
            subprocess.TimeoutExpired: If timeout_seconds is exceeded.
        """
        log_message(f"Running {GEMINI_CLI_NAME} quietly")
        log_backend_metadata("gemini", model=model, timeout=timeout_seconds)

        cmd = self.build_command(prompt, model=model)
        process_env = self._build_env(env)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            env=process_env,
        )
        log_command(GEMINI_CLI_NAME, result.returncode)

        output = result.stdout or ""

        if not output and result.returncode != 0 and result.stderr:
            output = result.stderr

        return output


__all__ = [
    "GEMINI_CLI_NAME",
    "GeminiClient",
    "check_gemini_installed",
    "looks_like_rate_limit",
]
