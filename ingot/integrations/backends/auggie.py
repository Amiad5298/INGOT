"""Auggie CLI backend implementation.

This module provides the AuggieBackend class that wraps the existing AuggieClient
for use with the pluggable multi-agent architecture.

AuggieBackend is the reference implementation demonstrating how concrete backends:
- Extend BaseBackend to inherit shared functionality
- Implement the AIBackend protocol
- Wrap existing CLI clients (delegation pattern)
- Map parameters between protocol and client APIs
"""

import subprocess
from collections.abc import Callable

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.auggie import (
    AuggieClient,
    check_auggie_installed,
    looks_like_rate_limit,
)
from ingot.integrations.auggie import (
    list_models as auggie_list_models,
)
from ingot.integrations.backends.base import BackendModel, BaseBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class AuggieBackend(BaseBackend):
    """Auggie CLI backend implementation.

    Extends BaseBackend to inherit shared logic (subagent parsing, model resolution).
    Wraps the existing AuggieClient for actual CLI execution.

    Note: This class depends on AuggieClient.build_command() for command
    construction. This is an intentional design choice per the delegation
    pattern. If AuggieClient internals change, this class may need
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
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        """Execute with streaming callback and optional timeout.

        Uses BaseBackend._run_streaming_with_timeout() for timeout enforcement.
        This wraps the AuggieClient call with the streaming-safe watchdog pattern.

        Args:
            prompt: The prompt to send to Auggie.
            output_callback: Callback function for streaming output.
            subagent: Optional subagent name (mapped to 'agent' in AuggieClient).
            model: Optional model override.
            dont_save_session: If True, don't save the session.
            timeout_seconds: Optional timeout in seconds (None = no timeout).
            plan_mode: Accepted for protocol compliance; not yet mapped to
                an Auggie CLI flag.

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
            # We only call build_command() here to avoid duplicate work when
            # delegating to AuggieClient.run_with_callback() in the else branch.
            cmd = self._client.build_command(
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
            # (which calls build_command() internally)
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
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        """Run with --print flag, return success status and captured output.

        Args:
            prompt: The prompt to send to Auggie.
            subagent: Optional subagent name (mapped to 'agent' in AuggieClient).
            model: Optional model override.
            dont_save_session: If True, don't save the session.
            timeout_seconds: Optional timeout in seconds (None = no timeout).

        Returns:
            Tuple of (success, output).

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model = self._resolve_model(model, subagent)

        if timeout_seconds is not None:
            cmd = self._client.build_command(
                prompt,
                agent=subagent,
                model=resolved_model,
                print_mode=True,
                dont_save_session=dont_save_session,
            )
            try:
                result = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_seconds,
                )
                return result.returncode == 0, result.stdout
            except subprocess.TimeoutExpired:
                raise BackendTimeoutError(
                    f"Operation timed out after {timeout_seconds}s",
                    timeout_seconds=timeout_seconds,
                ) from None

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
        plan_mode: bool = False,
    ) -> str:
        """Run with --print --quiet, return output only.

        Args:
            prompt: The prompt to send to Auggie.
            subagent: Optional subagent name (mapped to 'agent' in AuggieClient).
            model: Optional model override.
            dont_save_session: If True, don't save the session.
            timeout_seconds: Optional timeout in seconds (None = no timeout).

        Returns:
            Command output string.

        Raises:
            BackendTimeoutError: If timeout_seconds is exceeded.
        """
        resolved_model = self._resolve_model(model, subagent)

        if timeout_seconds is not None:
            cmd = self._client.build_command(
                prompt,
                agent=subagent,
                model=resolved_model,
                print_mode=True,
                quiet=True,
                dont_save_session=dont_save_session,
            )
            try:
                result = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_seconds,
                )
                return result.stdout
            except subprocess.TimeoutExpired:
                raise BackendTimeoutError(
                    f"Operation timed out after {timeout_seconds}s",
                    timeout_seconds=timeout_seconds,
                ) from None

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
        plan_mode: bool = False,
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

    def list_models(self) -> list[BackendModel]:
        """Return models from the Auggie CLI ``auggie models list`` command."""
        auggie_models = auggie_list_models()
        return [
            BackendModel(id=m.id, name=m.name, description=m.description) for m in auggie_models
        ]

    # close() inherited from BaseBackend
