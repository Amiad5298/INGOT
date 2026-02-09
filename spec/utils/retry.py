"""Retry utilities for handling rate limits and transient errors.

This module provides exponential backoff with jitter for API rate limit
handling during concurrent task execution. It includes:
- RateLimitExceededError: Custom exception for exhausted retries
- calculate_backoff_delay: Exponential backoff with jitter calculation
- with_rate_limit_retry: Decorator for automatic retry logic
"""

import random
import re
import time
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from spec.utils.errors import AuggieRateLimitError, BackendRateLimitError

if TYPE_CHECKING:
    from spec.workflow.state import RateLimitConfig

T = TypeVar("T")


class RateLimitExceededError(Exception):
    """Raised when rate limit is hit and retries are exhausted.

    Attributes:
        attempts: Number of retry attempts made
        total_wait_time: Total time spent waiting between retries
    """

    def __init__(self, message: str, attempts: int, total_wait_time: float):
        super().__init__(message)
        self.attempts = attempts
        self.total_wait_time = total_wait_time


def calculate_backoff_delay(
    attempt: int,
    config: "RateLimitConfig",
) -> float:
    """Calculate delay with exponential backoff and jitter.

    Formula: min(base * 2^attempt + jitter, max_delay)

    The jitter helps prevent thundering herd problems where multiple
    concurrent tasks retry at the same time.

    Args:
        attempt: Current attempt number (0-indexed)
        config: Rate limit configuration

    Returns:
        Delay in seconds

    Example delays with default config (base=2s, jitter=0.5):
        Attempt 0: 2.0 - 3.0s
        Attempt 1: 4.0 - 6.0s
        Attempt 2: 8.0 - 12.0s
        Attempt 3: 16.0 - 24.0s
        Attempt 4: 32.0 - 48.0s (capped at max_delay=60s)
    """
    # Exponential backoff: 2s, 4s, 8s, 16s, 32s...
    exponential_delay = config.base_delay_seconds * (2**attempt)

    # Add jitter: random value between 0 and jitter_factor * delay
    jitter = random.uniform(0, config.jitter_factor * exponential_delay)

    # Apply delay with jitter, capped at max
    delay: float = min(exponential_delay + jitter, config.max_delay_seconds)

    return delay


def with_rate_limit_retry(
    config: "RateLimitConfig",
    on_retry: Callable[[int, float, Exception], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retrying functions on rate limit errors.

    Wraps a function to automatically retry on rate limit or transient
    errors with exponential backoff and jitter.

    Args:
        config: Rate limit configuration
        on_retry: Optional callback called before each retry.
                  Receives (attempt_number, delay_seconds, exception).
                  Useful for logging retry attempts.

    Returns:
        Decorator function

    Usage:
        @with_rate_limit_retry(config, on_retry=log_retry)
        def call_api():
            ...

    Raises:
        RateLimitExceededError: When all retries are exhausted
        Exception: Non-retryable errors are re-raised immediately
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            total_wait_time = 0.0
            last_exception: Exception | None = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check if this is a retryable error
                    if not _is_retryable_error(e, config):
                        raise

                    last_exception = e

                    # Check if we have retries left
                    if attempt >= config.max_retries:
                        break

                    # Calculate delay
                    delay = calculate_backoff_delay(attempt, config)
                    total_wait_time += delay

                    # Notify callback if provided
                    if on_retry:
                        on_retry(attempt + 1, delay, e)

                    # Wait before retry
                    time.sleep(delay)

            # All retries exhausted
            raise RateLimitExceededError(
                f"Rate limit exceeded after {config.max_retries} retries "
                f"(total wait: {total_wait_time:.1f}s): {last_exception}",
                attempts=config.max_retries,
                total_wait_time=total_wait_time,
            )

        return wrapper

    return decorator


def _is_retryable_error(error: Exception, config: "RateLimitConfig") -> bool:
    """Check if an error should trigger a retry.

    Handles various error types from different API clients by checking
    both HTTP status codes and common rate limit keywords in error messages.

    Args:
        error: The exception to check
        config: Rate limit configuration with retryable status codes

    Returns:
        True if the error is retryable, False otherwise
    """
    if isinstance(error, BackendRateLimitError | AuggieRateLimitError):
        return True

    error_str = str(error).lower()

    # Check for HTTP status codes in error message using word boundaries
    # to avoid false positives (e.g., "PROJ-4290" should not match 429).
    # Compile a single combined regex for all configured status codes.
    if config.retryable_status_codes:
        codes_pattern = "|".join(str(c) for c in config.retryable_status_codes)
        if re.search(rf"\b(?:{codes_pattern})\b", error_str):
            return True

    # Check for common rate limit keywords
    rate_limit_keywords = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "throttl",
        "quota exceeded",
        "capacity",
    ]

    return any(keyword in error_str for keyword in rate_limit_keywords)


__all__ = [
    "RateLimitExceededError",
    "calculate_backoff_delay",
    "with_rate_limit_retry",
]
