"""Gemini CLI backend implementation.

This module provides the GeminiBackend class that wraps the GeminiClient
for use with the pluggable multi-agent architecture.

GeminiBackend injects subagent instructions via the GEMINI_SYSTEM_MD
environment variable, which points to a temp file containing the system
prompt. This is analogous to Claude's --append-system-prompt-file but
uses an env var instead of a CLI flag.
"""

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import BaseBackend
from ingot.integrations.backends.errors import BackendTimeoutError
from ingot.integrations.gemini import (
    GeminiClient,
    check_gemini_installed,
    looks_like_rate_limit,
)
from ingot.utils.logging import log_once


class GeminiBackend(BaseBackend):
    """Gemini CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the GeminiClient for actual CLI execution.

    System prompt injection uses the GEMINI_SYSTEM_MD env var pointing
    to a temp file, rather than embedding in the user prompt.

    Attributes:
        _client: The underlying GeminiClient instance for CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Gemini backend.

        Args:
            model: Default model to use for commands.
        """
        super().__init__(model=model)
        self._client = GeminiClient(model=model)

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "Gemini CLI"

    @property
    def platform(self) -> AgentPlatform:
        """Return the platform identifier."""
        return AgentPlatform.GEMINI

    @property
    def supports_parallel(self) -> bool:
        """Return whether this backend supports parallel execution."""
        return True

    @property
    def supports_plan_mode(self) -> bool:
        """Whether this backend can enforce read-only plan mode via --approval-mode=plan.

        Returns True, meaning callers can rely on plan_mode=True producing
        enforced read-only behavior through Gemini CLI flags.
        """
        return True

    # _resolve_subagent() inherited from BaseBackend

    @staticmethod
    def _resolve_approval_mode(plan_mode: bool) -> str:
        """Resolve the Gemini approval mode and log a one-time warning if needed.

        Args:
            plan_mode: If True, use "plan" mode; otherwise "yolo".

        Returns:
            The approval mode string for the Gemini CLI.
        """
        if plan_mode:
            log_once(
                "gemini_plan_mode",
                "Gemini plan mode (--approval-mode=plan) requires the following "
                "in ~/.gemini/settings.json:\n"
                '  {"experimental": {"plan": true}}\n'
                "Ensure your Gemini CLI version supports 'experimental.plan'. "
                "A restart of the Gemini CLI may be required after changing settings.",
            )
            return "plan"
        return "yolo"

    def _build_system_prompt_env(
        self, subagent_prompt: str | None
    ) -> tuple[dict[str, str] | None, str | None]:
        """Build env dict with GEMINI_SYSTEM_MD if subagent prompt is provided.

        Writes the subagent prompt to a temp file and returns the env dict
        along with the temp file path (for cleanup).

        Args:
            subagent_prompt: Optional subagent instructions.

        Returns:
            Tuple of (env_dict_or_None, temp_file_path_or_None).
        """
        if not subagent_prompt:
            return None, None

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="ingot_gemini_system_"
        ) as f:
            f.write(subagent_prompt)
            temp_path = f.name
        return {"GEMINI_SYSTEM_MD": temp_path}, temp_path

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        """Execute with streaming callback and optional timeout.

        Args:
            prompt: The prompt to send to Gemini.
            output_callback: Callback function for streaming output.
            subagent: Optional subagent name.
            model: Optional model override.
            dont_save_session: Unused (Gemini has no session persistence).
            timeout_seconds: Optional timeout in seconds (None = no timeout).
            plan_mode: If True, use --approval-mode=plan instead of yolo.

        Returns:
            Tuple of (success, output).

        Raises:
            BackendTimeoutError: If timeout_seconds is specified and exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        env, temp_path = self._build_system_prompt_env(subagent_prompt)
        approval_mode = self._resolve_approval_mode(plan_mode)

        try:
            if timeout_seconds is not None:
                cmd = self._client.build_command(
                    prompt, model=resolved_model, approval_mode=approval_mode
                )
                exit_code, output = self._run_streaming_with_timeout(
                    cmd,
                    output_callback=output_callback,
                    timeout_seconds=timeout_seconds,
                    env=env,
                )
                success = exit_code == 0
                return success, output
            else:
                return self._client.run_with_callback(
                    prompt,
                    output_callback=output_callback,
                    model=resolved_model,
                    env=env,
                    approval_mode=approval_mode,
                )
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        """Run and return success status and captured output.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        env, temp_path = self._build_system_prompt_env(subagent_prompt)
        approval_mode = self._resolve_approval_mode(plan_mode)

        try:
            return self._client.run_print_with_output(
                prompt,
                model=resolved_model,
                timeout_seconds=timeout_seconds,
                env=env,
                approval_mode=approval_mode,
            )
        except subprocess.TimeoutExpired:
            raise BackendTimeoutError(
                f"Operation timed out after {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
            ) from None
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
        plan_mode: bool = False,
    ) -> str:
        """Run quietly, return output only.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        env, temp_path = self._build_system_prompt_env(subagent_prompt)
        approval_mode = self._resolve_approval_mode(plan_mode)

        try:
            return self._client.run_print_quiet(
                prompt,
                model=resolved_model,
                timeout_seconds=timeout_seconds,
                env=env,
                approval_mode=approval_mode,
            )
        except subprocess.TimeoutExpired:
            raise BackendTimeoutError(
                f"Operation timed out after {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
            ) from None
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        """Execute in streaming mode (non-interactive).

        Uses run_print_with_output internally.
        """
        return self.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            timeout_seconds=timeout_seconds,
            plan_mode=plan_mode,
        )

    def check_installed(self) -> tuple[bool, str]:
        """Check if Gemini CLI is installed."""
        return check_gemini_installed()

    def detect_rate_limit(self, output: str) -> bool:
        """Detect if output indicates a rate limit error."""
        return looks_like_rate_limit(output)


__all__ = [
    "GeminiBackend",
]
