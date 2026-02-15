"""Async helpers for the CLI.

Provides utilities for running async code from synchronous CLI contexts.
"""

import asyncio
from collections.abc import Callable, Coroutine

from ingot.utils.errors import ExitCode, IngotError


class AsyncLoopAlreadyRunningError(IngotError):
    """Raised when trying to run async code in an existing event loop.

    This occurs in environments like Jupyter notebooks or when already
    running inside an async context.
    """

    _default_exit_code = ExitCode.GENERAL_ERROR


def run_async[T](coro_factory: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run an async coroutine safely, handling existing event loops.

    This helper detects if an event loop is already running (e.g., in Jupyter
    notebooks or dev environments) and raises a clear error instead of
    crashing with asyncio.run().

    Takes a factory function (callable that returns a coroutine) instead of
    a coroutine object directly. This ensures we check for a running loop
    BEFORE creating the coroutine, avoiding the need to close an uncalled
    coroutine and the subtle footgun of discarding side effects that might
    have occurred before the first await.

    Raises:
        AsyncLoopAlreadyRunningError: If an event loop is already running.
            This provides a clear error message instead of cryptic asyncio errors.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        loop = None

    if loop is not None:
        # Raise BEFORE creating the coroutine - no cleanup needed
        raise AsyncLoopAlreadyRunningError(
            "Cannot run async operation: an event loop is already running. "
            "This can happen in Jupyter notebooks or when running inside an async context. "
            "Consider using 'await' directly or running from a synchronous environment."
        )

    return asyncio.run(coro_factory())
