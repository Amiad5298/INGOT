"""Cursor IDE CLI backend implementation.

This module provides the CursorBackend class that wraps the CursorClient
for use with the pluggable multi-agent architecture.

CursorBackend follows the same delegation pattern as ClaudeBackend:
- Extends BaseBackend to inherit shared functionality
- Implements the AIBackend protocol
- Wraps the CursorClient (delegation pattern)

Key difference from ClaudeBackend: Cursor has no --append-system-prompt-file
equivalent. Subagent instructions are embedded directly in the user prompt
(via _compose_prompt) instead of being passed as a separate system prompt file.

Model resolution and subagent parsing happen ONLY in this backend layer
(via BaseBackend helpers). The client receives pre-resolved values.
"""

import subprocess
from collections.abc import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import BaseBackend
from spec.integrations.backends.errors import BackendTimeoutError
from spec.integrations.cursor import (
    CursorClient,
    check_cursor_installed,
    looks_like_rate_limit,
)


class CursorBackend(BaseBackend):
    """Cursor IDE CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the CursorClient for actual CLI execution.

    Unlike ClaudeBackend which passes system_prompt to the client for file-based
    injection, CursorBackend composes the full prompt itself (embedding subagent
    instructions directly in the prompt) before passing to the client.

    Attributes:
        _client: The underlying CursorClient instance for CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Cursor backend.

        Args:
            model: Default model to use for commands.
        """
        super().__init__(model=model)
        self._client = CursorClient(model=model)

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "Cursor"

    @property
    def platform(self) -> AgentPlatform:
        """Return the platform identifier."""
        return AgentPlatform.CURSOR

    @property
    def supports_parallel(self) -> bool:
        """Return whether this backend supports parallel execution."""
        return True

    def _resolve_subagent(
        self,
        subagent: str | None,
        model: str | None,
    ) -> tuple[str | None, str | None]:
        """Resolve subagent and model in one pass.

        Uses BaseBackend._parse_subagent_prompt() to get both the prompt
        body and model from frontmatter. Avoids reading the subagent
        file multiple times.

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

            # Model precedence: explicit > frontmatter > instance default
            if not model and metadata.model:
                model = metadata.model

        # Fall back to instance default if nothing else set
        resolved_model = model or self._model or None
        return resolved_model, subagent_prompt

    def _compose_prompt(self, prompt: str, subagent_prompt: str | None) -> str:
        """Compose the final prompt with optional subagent instructions.

        Since Cursor has no --append-system-prompt-file equivalent, subagent
        instructions are embedded directly in the prompt.

        Args:
            prompt: The user/task prompt.
            subagent_prompt: Optional subagent instructions to embed.

        Returns:
            The composed prompt string.
        """
        if subagent_prompt:
            return f"## Agent Instructions\n\n{subagent_prompt}\n\n## Task\n\n{prompt}"
        return prompt

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

        Uses BaseBackend._run_streaming_with_timeout() for timeout enforcement.

        Args:
            prompt: The prompt to send to Cursor.
            output_callback: Callback function for streaming output.
            subagent: Optional subagent name.
            model: Optional model override.
            dont_save_session: If True, don't persist the session.
            timeout_seconds: Optional timeout in seconds (None = no timeout).

        Returns:
            Tuple of (success, output).

        Raises:
            BackendTimeoutError: If timeout_seconds is specified and exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)

        if timeout_seconds is not None:
            cmd = self._client.build_command(
                composed_prompt,
                model=resolved_model,
                print_mode=True,
                no_save=dont_save_session,
            )
            exit_code, output = self._run_streaming_with_timeout(
                cmd,
                output_callback=output_callback,
                timeout_seconds=timeout_seconds,
            )
            success = exit_code == 0
            return success, output
        else:
            return self._client.run_with_callback(
                composed_prompt,
                output_callback=output_callback,
                model=resolved_model,
                no_save=dont_save_session,
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
        """Run with --print flag, return success status and captured output.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)
        try:
            return self._client.run_print_with_output(
                composed_prompt,
                model=resolved_model,
                no_save=dont_save_session,
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
        """Run with --print flag quietly, return output only.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, subagent_prompt = self._resolve_subagent(subagent, model)
        composed_prompt = self._compose_prompt(prompt, subagent_prompt)
        try:
            return self._client.run_print_quiet(
                composed_prompt,
                model=resolved_model,
                no_save=dont_save_session,
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

        Args:
            prompt: The prompt to send (with any user input already included).
            subagent: Optional subagent name.
            model: Optional model override.
            timeout_seconds: Optional timeout in seconds.

        Returns:
            Tuple of (success, full_output).
        """
        return self.run_print_with_output(
            prompt,
            subagent=subagent,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def check_installed(self) -> tuple[bool, str]:
        """Check if Cursor CLI is installed.

        Returns:
            Tuple of (is_installed, version_or_error_message).
        """
        return check_cursor_installed()

    def detect_rate_limit(self, output: str) -> bool:
        """Detect if output indicates a rate limit error.

        Args:
            output: The output string to check.

        Returns:
            True if output looks like a rate limit error.
        """
        return looks_like_rate_limit(output)

    # supports_parallel_execution() and close() inherited from BaseBackend


__all__ = [
    "CursorBackend",
]
