"""Reusable FakeBackend for testing rate limit and retry flows.

Provides a configurable fake that implements the AIBackend protocol,
allowing tests to control responses, track calls, and simulate
rate limit scenarios without real CLI invocations.
"""

from __future__ import annotations

from collections.abc import Callable

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import matches_common_rate_limit


class FakeBackend:
    """Fake AIBackend that returns pre-configured responses in order.

    Uses the same ``matches_common_rate_limit`` helper as real backends
    so that rate-limit detection behaviour is consistent in tests.

    By default, raises ``IndexError`` when all responses have been consumed.
    This catches tests that make more calls than expected, preventing silent
    bugs.

    Attributes:
        call_count: Total number of run_with_callback calls made.
        calls: List of (prompt, kwargs) tuples for each call.
    """

    def __init__(
        self,
        responses: list[tuple[bool, str]],
        *,
        installed: bool = True,
        platform: AgentPlatform = AgentPlatform.AUGGIE,
    ) -> None:
        """Initialize with a list of (success, output) responses.

        Args:
            responses: Ordered list of (success, output) tuples to return.
                       Raises IndexError if more calls than responses.
            installed: Value returned by check_installed(). Default True.
            platform: AgentPlatform to report. Default AUGGIE.
        """
        self._responses = responses
        self._installed = installed
        self._platform = platform
        self.call_count: int = 0
        self.calls: list[tuple[str, dict]] = []

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
        return "FakeBackend"

    @property
    def platform(self) -> AgentPlatform:
        return self._platform

    @property
    def model(self) -> str:
        return ""

    @property
    def supports_parallel(self) -> bool:
        return True

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
        kwargs = {
            "subagent": subagent,
            "model": model,
            "dont_save_session": dont_save_session,
            "timeout_seconds": timeout_seconds,
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
    ) -> tuple[bool, str]:
        return self._next_response()

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return self._next_response()[1]

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
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
        pass


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
