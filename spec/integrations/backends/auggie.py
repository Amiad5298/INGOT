"""Auggie CLI backend implementation.

This module provides the AuggieBackend class that wraps the existing AuggieClient
for use with the pluggable multi-agent architecture.

AuggieBackend is the reference implementation demonstrating how concrete backends:
- Extend BaseBackend to inherit shared functionality
- Implement the AIBackend protocol
- Wrap existing CLI clients (delegation pattern)
- Map parameters between protocol and client APIs
"""

from collections.abc import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.auggie import (
    AuggieClient,
    check_auggie_installed,
    looks_like_rate_limit,
)
from spec.integrations.backends.base import BaseBackend


class AuggieBackend(BaseBackend):
    """Auggie CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the existing AuggieClient for actual CLI execution.

    Note: This class depends on AuggieClient._build_command() which is a private
    method. This is an intentional design choice per the parent specification
    (delegation pattern). If AuggieClient internals change, this class may need
    updates.

    Attributes:
        _client: The underlying AuggieClient instance for CLI execution.
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Auggie backend.

        Args:
            model: Default model to use for commands.
        """
        super().__init__(model=model)
        self._client = AuggieClient(model=model)

    @property
    def name(self) -> str:
        """Return the backend name."""
        return "Auggie"

    @property
    def platform(self) -> AgentPlatform:
        """Return the platform identifier."""
        return AgentPlatform.AUGGIE

    @property
    def supports_parallel(self) -> bool:
        """Return whether this backend supports parallel execution."""
        return True  # Auggie handles concurrent invocations

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
        This wraps the AuggieClient call with the streaming-safe watchdog pattern.

        Note on model resolution: _resolve_model() returns the correct precedence
        (explicit → frontmatter → default), but when subagent is set, Auggie's
        _build_command() may ignore the resolved model and use the agent
        definition's model instead. This is a known limitation of the Auggie CLI.

        Args:
            prompt: The prompt to send to Auggie.
            output_callback: Callback function for streaming output.
            subagent: Optional subagent name (mapped to 'agent' in AuggieClient).
            model: Optional model override.
            dont_save_session: If True, don't save the session.
            timeout_seconds: Optional timeout in seconds (None = no timeout).

        Returns:
            Tuple of (success, output).

        Raises:
            BackendTimeoutError: If timeout_seconds is specified and exceeded.
        """
        resolved_model = self._resolve_model(model, subagent)

        # Use streaming timeout wrapper from BaseBackend when timeout is specified
        if timeout_seconds is not None:
            # Build auggie CLI command using AuggieClient's private method
            # Note: This coupling is intentional per the delegation pattern.
            # We only call _build_command() here to avoid duplicate work when
            # delegating to AuggieClient.run_with_callback() in the else branch.
            cmd = self._client._build_command(
                prompt,
                agent=subagent,
                model=resolved_model,
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
            # No timeout - delegate directly to client's implementation
            # (which calls _build_command() internally)
            return self._client.run_with_callback(
                prompt,
                output_callback=output_callback,
                agent=subagent,
                model=resolved_model,
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
        """Run with --print flag, return success status and captured output.

        Warning: timeout_seconds is accepted per protocol but NOT enforced in
        this version. Callers should not assume timeout works for this method.
        Timeout support can be added in a future enhancement if needed.
        """
        resolved_model = self._resolve_model(model, subagent)
        return self._client.run_print_with_output(
            prompt,
            agent=subagent,
            model=resolved_model,
            dont_save_session=dont_save_session,
        )

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run with --print --quiet, return output only.

        Warning: timeout_seconds is accepted per protocol but NOT enforced in
        this version. Callers should not assume timeout works for this method.
        Timeout support can be added in a future enhancement if needed.
        """
        resolved_model = self._resolve_model(model, subagent)
        return self._client.run_print_quiet(
            prompt,
            agent=subagent,
            model=resolved_model,
            dont_save_session=dont_save_session,
        )

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        """Execute in streaming mode (non-interactive).

        Uses run_print_with_output internally as Auggie's non-interactive mode.

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

    # NOTE: run_print() is NOT exposed - see Final Decision #4 in parent spec
    # Legacy callers must be refactored to use TUI + run_streaming()

    def check_installed(self) -> tuple[bool, str]:
        """Check if Auggie CLI is installed.

        Returns:
            Tuple of (is_installed, version_or_error_message).
        """
        return check_auggie_installed()

    def detect_rate_limit(self, output: str) -> bool:
        """Detect if output indicates a rate limit error.

        Args:
            output: The output string to check.

        Returns:
            True if output looks like a rate limit error.
        """
        return looks_like_rate_limit(output)

    # supports_parallel_execution() and close() inherited from BaseBackend
