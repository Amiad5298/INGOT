"""Reusable FakeBackend for testing rate limit and retry flows.

Provides a configurable fake that implements the AIBackend protocol,
allowing tests to control responses, track calls, and simulate
rate limit scenarios without real CLI invocations.
"""

from __future__ import annotations

from collections.abc import Callable

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import matches_common_rate_limit


class FakeBackend:
    """Fake AIBackend that returns pre-configured responses in order.

    Uses the same ``matches_common_rate_limit`` helper as real backends
    so that rate-limit detection behaviour is consistent in tests.

    By default, raises ``IndexError`` when all responses have been consumed.
    This catches tests that make more calls than expected, preventing silent
    bugs.

    Attributes:
        call_count: Total number of calls made (across all run_* methods).
        calls: List of (prompt, kwargs) tuples for each run_with_callback call.
        quiet_calls: List of (prompt, kwargs) tuples for each run_print_quiet call.
        print_with_output_calls: List of (prompt, kwargs) tuples for each run_print_with_output call.
        streaming_calls: List of (prompt, kwargs) tuples for each run_streaming call.
    """

    def __init__(
        self,
        responses: list[tuple[bool, str]],
        *,
        installed: bool = True,
        platform: AgentPlatform = AgentPlatform.AUGGIE,
        name: str = "FakeBackend",
        supports_parallel: bool = True,
        supports_plan_mode: bool = False,
    ) -> None:
        """Initialize with a list of (success, output) responses.

        Args:
            responses: Ordered list of (success, output) tuples to return.
                       Raises IndexError if more calls than responses.
            installed: Value returned by check_installed(). Default True.
            platform: AgentPlatform to report. Default AUGGIE.
            name: Human-readable backend name. Default "FakeBackend".
            supports_parallel: Whether backend supports parallel execution. Default True.
            supports_plan_mode: Whether backend supports plan mode. Default False.
        """
        self._responses = responses
        self._installed = installed
        self._platform = platform
        self._name = name
        self._supports_parallel = supports_parallel
        self._supports_plan_mode = supports_plan_mode
        self.closed: bool = False
        self.call_count: int = 0
        self.calls: list[tuple[str, dict]] = []
        self.quiet_calls: list[tuple[str, dict]] = []
        self.print_with_output_calls: list[tuple[str, dict]] = []
        self.streaming_calls: list[tuple[str, dict]] = []

    def _next_response(self) -> tuple[bool, str]:
        """Return the next response, raising IndexError if exhausted."""
        if self.call_count >= len(self._responses):
            raise IndexError(
                f"FakeBackend exhausted: {self.call_count} calls made "
                f"but only {len(self._responses)} responses configured"
            )
        idx = self.call_count
        self.call_count += 1
        return self._responses[idx]

    @property
    def name(self) -> str:
        return self._name

    @property
    def platform(self) -> AgentPlatform:
        return self._platform

    @property
    def model(self) -> str:
        return ""

    @property
    def supports_parallel(self) -> bool:
        return self._supports_parallel

    @property
    def supports_plan_mode(self) -> bool:
        return self._supports_plan_mode

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
        kwargs = {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
            "timeout_seconds": timeout_seconds,
            "plan_mode": plan_mode,
        }
        self.calls.append((prompt, kwargs))
        success, output = self._next_response()
        # Stream output to callback line-by-line
        for line in output.splitlines():
            output_callback(line)
        return success, output

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
        kwargs = {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
            "timeout_seconds": timeout_seconds,
            "plan_mode": plan_mode,
        }
        self.print_with_output_calls.append((prompt, kwargs))
        return self._next_response()

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
        kwargs = {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
            "timeout_seconds": timeout_seconds,
            "plan_mode": plan_mode,
        }
        self.quiet_calls.append((prompt, kwargs))
        return self._next_response()[1]

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        plan_mode: bool = False,
    ) -> tuple[bool, str]:
        kwargs = {
            "subagent": subagent,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "plan_mode": plan_mode,
        }
        self.streaming_calls.append((prompt, kwargs))
        return self._next_response()

    def check_installed(self) -> tuple[bool, str]:
        if self._installed:
            return True, "FakeBackend 1.0.0"
        return False, "FakeBackend is not installed"

    def detect_rate_limit(self, output: str) -> bool:
        return matches_common_rate_limit(output)

    def supports_parallel_execution(self) -> bool:
        return self.supports_parallel

    def close(self) -> None:
        self.closed = True


def make_successful_backend(output: str = "success") -> FakeBackend:
    """Create a FakeBackend that returns a single successful response.

    Args:
        output: The output string to return. Default "success".

    Returns:
        Configured FakeBackend instance.
    """
    return FakeBackend([(True, output)])


def make_failing_backend(error: str = "error") -> FakeBackend:
    """Create a FakeBackend that returns a single failed response.

    Args:
        error: The error output string to return. Default "error".

    Returns:
        Configured FakeBackend instance.
    """
    return FakeBackend([(False, error)])


def make_rate_limited_backend(fail_count: int = 2) -> FakeBackend:
    """Create a FakeBackend that fails with rate limit output N times then succeeds.

    The first `fail_count` calls return (False, "Error 429: rate limit hit").
    Subsequent calls return (True, "Task completed successfully").

    Args:
        fail_count: Number of rate-limited failures before success.

    Returns:
        Configured FakeBackend instance.
    """
    responses: list[tuple[bool, str]] = []
    for _ in range(fail_count):
        responses.append((False, "Error 429: rate limit hit"))
    responses.append((True, "Task completed successfully"))
    return FakeBackend(responses)
