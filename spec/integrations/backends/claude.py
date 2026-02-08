"""Claude Code CLI backend implementation.

This module provides the ClaudeBackend class that wraps the ClaudeClient
for use with the pluggable multi-agent architecture.

ClaudeBackend follows the same delegation pattern as AuggieBackend:
- Extends BaseBackend to inherit shared functionality
- Implements the AIBackend protocol
- Wraps the ClaudeClient (delegation pattern)

Key difference from AuggieBackend: ClaudeClient uses system_prompt natively
(via --append-system-prompt-file), and subagent instructions are injected via
that flag instead of being embedded in the user prompt.

Model resolution and subagent parsing happen ONLY in this backend layer
(via BaseBackend helpers). The client receives pre-resolved values.
System prompts are passed to the client as strings; the client writes
them to temp files for --append-system-prompt-file (avoids ARG_MAX
and hides prompts from the process list).
"""

import subprocess
from collections.abc import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import BaseBackend
from spec.integrations.backends.errors import BackendTimeoutError
from spec.integrations.claude import (
    ClaudeClient,
    _looks_like_rate_limit,
    _system_prompt_file_context,
    check_claude_installed,
)


class ClaudeBackend(BaseBackend):
    """Claude Code CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the ClaudeClient for actual CLI execution.

    Model resolution and subagent prompt parsing happen here (via BaseBackend
    helpers). The ClaudeClient receives pre-resolved model and system_prompt
    values, avoiding double I/O and duplicated parsing logic.

    Attributes:
        _client: The underlying ClaudeClient instance for CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Claude backend.

        Args:
            model: Default model to use for commands.
        """
        super().__init__(model=model)
        self._client = ClaudeClient(model=model)

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "Claude Code"

    @property
    def platform(self) -> AgentPlatform:
        """Return the platform identifier."""
        return AgentPlatform.CLAUDE

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

        Uses BaseBackend._parse_subagent_prompt() to get both the system
        prompt body and model from frontmatter. Avoids reading the subagent
        file multiple times.

        Args:
            subagent: Optional subagent name.
            model: Optional explicit model override.

        Returns:
            Tuple of (resolved_model, system_prompt).
        """
        system_prompt: str | None = None

        if subagent:
            metadata, prompt_body = self._parse_subagent_prompt(subagent)
            system_prompt = prompt_body if prompt_body else None

            # Model precedence: explicit > frontmatter > instance default
            if not model and metadata.model:
                model = metadata.model

        # Fall back to instance default if nothing else set
        resolved_model = model or self._model or None
        return resolved_model, system_prompt

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
            prompt: The prompt to send to Claude.
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
        resolved_model, system_prompt = self._resolve_subagent(subagent, model)

        if timeout_seconds is not None:
            with _system_prompt_file_context(system_prompt) as prompt_file:
                cmd = self._client.build_command(
                    prompt,
                    model=resolved_model,
                    system_prompt_file=prompt_file,
                    print_mode=True,
                    dont_save_session=dont_save_session,
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
                prompt,
                output_callback=output_callback,
                model=resolved_model,
                system_prompt=system_prompt,
                dont_save_session=dont_save_session,
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
        """Run with -p flag, return success status and captured output.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, system_prompt = self._resolve_subagent(subagent, model)
        try:
            return self._client.run_print_with_output(
                prompt,
                model=resolved_model,
                system_prompt=system_prompt,
                dont_save_session=dont_save_session,
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
        """Run with -p flag quietly, return output only.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model, system_prompt = self._resolve_subagent(subagent, model)
        try:
            return self._client.run_print_quiet(
                prompt,
                model=resolved_model,
                system_prompt=system_prompt,
                dont_save_session=dont_save_session,
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
        """Check if Claude Code CLI is installed.

        Returns:
            Tuple of (is_installed, version_or_error_message).
        """
        return check_claude_installed()

    def detect_rate_limit(self, output: str) -> bool:
        """Detect if output indicates a rate limit error.

        Args:
            output: The output string to check.

        Returns:
            True if output looks like a rate limit error.
        """
        return _looks_like_rate_limit(output)

    # supports_parallel_execution() and close() inherited from BaseBackend
