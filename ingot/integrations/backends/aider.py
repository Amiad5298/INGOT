"""Aider CLI backend implementation.

This module provides the AiderBackend class that wraps the AiderClient
for use with the pluggable multi-agent architecture.

AiderBackend follows the same delegation pattern as CursorBackend:
- Extends BaseBackend to inherit shared functionality
- Implements the AIBackend protocol
- Wraps the AiderClient (delegation pattern)

Like CursorBackend, Aider has no system prompt file equivalent. Subagent
instructions are embedded directly in the user prompt (via _compose_prompt).
"""

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.aider import (
    AiderClient,
    check_aider_installed,
    looks_like_rate_limit,
)
from ingot.integrations.backends.base import BaseBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class AiderBackend(BaseBackend):
    """Aider CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the AiderClient for actual CLI execution.

    Subagent instructions are embedded directly in the prompt before passing
    to the client (same approach as CursorBackend).

    Attributes:
        _client: The underlying AiderClient instance for CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Aider backend.

        Args:
            model: Default model to use for commands.
        """
        super().__init__(model=model)
        self._client = AiderClient(model=model)

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "Aider"

    @property
    def platform(self) -> AgentPlatform:
        """Return the platform identifier."""
        return AgentPlatform.AIDER

    @property
    def supports_parallel(self) -> bool:
        """Return whether this backend supports parallel execution."""
        return True

    # _resolve_subagent() and _compose_prompt() inherited from BaseBackend

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
        """Execute with streaming callback and optional timeout.

        Args:
            prompt: The prompt to send to Aider.
            output_callback: Callback function for streaming output.
            subagent: Optional subagent name.
            model: Optional model override.
            dont_save_session: Unused (Aider has no session persistence).
            timeout_seconds: Optional timeout in seconds (None = no timeout).

        Returns:
            Tuple of (success, output).

        Raises:
            BackendTimeoutError: If timeout_seconds is specified and exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)

        if timeout_seconds is not None:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, prefix="ingot_aider_"
            ) as f:
                f.write(composed_prompt)
                message_file = f.name
            try:
                cmd = self._client.build_command(
                    composed_prompt,
                    model=resolved_model,
                    message_file=message_file,
                )
                exit_code, output = self._run_streaming_with_timeout(
                    cmd,
                    output_callback=output_callback,
                    timeout_seconds=timeout_seconds,
                )
                success = exit_code == 0
                return success, output
            finally:
                Path(message_file).unlink(missing_ok=True)
        else:
            return self._client.run_with_callback(
                composed_prompt,
                output_callback=output_callback,
                model=resolved_model,
            )

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Run and return success status and captured output.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)
        try:
            return self._client.run_print_with_output(
                composed_prompt,
                model=resolved_model,
                timeout_seconds=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise BackendTimeoutError(
                f"Operation timed out after {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
            ) from None

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run quietly, return output only.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)
        try:
            return self._client.run_print_quiet(
                composed_prompt,
                model=resolved_model,
                timeout_seconds=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise BackendTimeoutError(
                f"Operation timed out after {timeout_seconds}s",
                timeout_seconds=timeout_seconds,
            ) from None

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute in streaming mode (non-interactive).

        Uses run_print_with_output internally.
        """
        return self.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def check_installed(self) -> tuple[bool, str]:
        """Check if Aider CLI is installed."""
        return check_aider_installed()

    def detect_rate_limit(self, output: str) -> bool:
        """Detect if output indicates a rate limit error."""
        return looks_like_rate_limit(output)


__all__ = [
    "AiderBackend",
]
