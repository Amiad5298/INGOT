"""Tests for spec.utils.retry module."""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.auggie import AuggieRateLimitError
from spec.utils.retry import (
    RateLimitExceededError,
    _is_retryable_error,
    calculate_backoff_delay,
    with_rate_limit_retry,
)
from spec.workflow.state import RateLimitConfig

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def rate_limit_config():
    """Standard rate limit config for testing with fast delays."""
    return RateLimitConfig(
        max_retries=3,
        base_delay_seconds=0.1,  # Fast for tests
        max_delay_seconds=1.0,
        jitter_factor=0.0,  # Deterministic for tests
    )


@pytest.fixture
def config_with_jitter():
    """Config with jitter enabled for randomness tests."""
    return RateLimitConfig(
        max_retries=3,
        base_delay_seconds=1.0,
        max_delay_seconds=10.0,
        jitter_factor=0.5,
    )


# =============================================================================
# Tests for RateLimitExceededError
# =============================================================================


class TestRateLimitExceededError:
    """Tests for RateLimitExceededError exception."""

    def test_creates_exception_with_message(self):
        """Exception stores message correctly."""
        error = RateLimitExceededError(
            "Rate limit exceeded", attempts=3, total_wait_time=5.0
        )
        assert "Rate limit exceeded" in str(error)

    def test_creates_exception_with_attempts(self):
        """Exception stores attempts value."""
        error = RateLimitExceededError(
            "Test error", attempts=5, total_wait_time=10.0
        )
        assert error.attempts == 5

    def test_creates_exception_with_total_wait_time(self):
        """Exception stores total_wait_time value."""
        error = RateLimitExceededError(
            "Test error", attempts=3, total_wait_time=7.5
        )
        assert error.total_wait_time == 7.5


# =============================================================================
# Tests for calculate_backoff_delay
# =============================================================================


class TestCalculateBackoffDelay:
    """Tests for calculate_backoff_delay function."""

    def test_first_attempt_uses_base_delay(self, rate_limit_config):
        """Attempt 0 returns approximately base_delay."""
        delay = calculate_backoff_delay(0, rate_limit_config)
        # With jitter_factor=0, should be exactly base_delay
        assert delay == rate_limit_config.base_delay_seconds

    def test_delay_increases_exponentially(self, rate_limit_config):
        """Each attempt roughly doubles the delay."""
        delay_0 = calculate_backoff_delay(0, rate_limit_config)
        delay_1 = calculate_backoff_delay(1, rate_limit_config)
        delay_2 = calculate_backoff_delay(2, rate_limit_config)

        # With jitter_factor=0, delays should double exactly
        assert delay_1 == delay_0 * 2
        assert delay_2 == delay_1 * 2

    def test_delay_respects_max_delay(self):
        """Delay never exceeds max_delay_seconds."""
        config = RateLimitConfig(
            base_delay_seconds=10.0,
            max_delay_seconds=15.0,
            jitter_factor=0.0,
        )
        # Attempt 2: 10 * 4 = 40, should be capped at 15
        delay = calculate_backoff_delay(2, config)
        assert delay == config.max_delay_seconds

    def test_jitter_adds_randomness(self, config_with_jitter):
        """Same attempt returns different values (jitter)."""
        delays = [calculate_backoff_delay(0, config_with_jitter) for _ in range(10)]
        # With jitter, not all values should be identical
        assert len(set(delays)) > 1

    def test_zero_jitter_returns_exact_delay(self, rate_limit_config):
        """With jitter_factor=0, returns exact exponential delay."""
        # Multiple calls should return the same value
        delays = [calculate_backoff_delay(1, rate_limit_config) for _ in range(5)]
        assert all(d == delays[0] for d in delays)
        assert delays[0] == rate_limit_config.base_delay_seconds * 2

    def test_custom_config_values(self):
        """Uses values from provided RateLimitConfig."""
        config = RateLimitConfig(
            base_delay_seconds=5.0,
            max_delay_seconds=100.0,
            jitter_factor=0.0,
        )
        delay = calculate_backoff_delay(0, config)
        assert delay == 5.0


# =============================================================================
# Tests for _is_retryable_error
# =============================================================================


class TestIsRetryableError:
    """Tests for _is_retryable_error function."""

    @pytest.fixture
    def default_config(self):
        """Default config with standard retryable status codes."""
        return RateLimitConfig()

    def test_detects_429_status_code(self, default_config):
        """HTTP 429 is retryable."""
        error = Exception("HTTP Error 429: Too Many Requests")
        assert _is_retryable_error(error, default_config) is True

    def test_detects_502_status_code(self, default_config):
        """HTTP 502 Bad Gateway is retryable."""
        error = Exception("HTTP Error 502: Bad Gateway")
        assert _is_retryable_error(error, default_config) is True

    def test_detects_503_status_code(self, default_config):
        """HTTP 503 Service Unavailable is retryable."""
        error = Exception("Service Unavailable (503)")
        assert _is_retryable_error(error, default_config) is True

    def test_detects_504_status_code(self, default_config):
        """HTTP 504 Gateway Timeout is retryable."""
        error = Exception("Gateway Timeout: 504")
        assert _is_retryable_error(error, default_config) is True

    def test_detects_rate_limit_text(self, default_config):
        """'rate limit' in message is retryable."""
        error = Exception("Rate limit exceeded, please wait")
        assert _is_retryable_error(error, default_config) is True

    def test_regular_error_not_retryable(self, default_config):
        """Normal exceptions are not retryable."""
        error = Exception("Connection refused")
        assert _is_retryable_error(error, default_config) is False

    def test_custom_status_codes(self):
        """Respects custom retryable_status_codes in config."""
        config = RateLimitConfig(retryable_status_codes=(418, 500))
        error_418 = Exception("I'm a teapot (418)")
        Exception("HTTP 429 Too Many Requests")

        assert _is_retryable_error(error_418, config) is True
        # 429 is not in custom list, but has "rate limit" keywords? No.
        # Actually 429 is in the error string, but not in config
        # Let's use a clean example
        error_500 = Exception("Internal Server Error 500")
        assert _is_retryable_error(error_500, config) is True


# =============================================================================
# Tests for with_rate_limit_retry decorator
# =============================================================================


class TestWithRateLimitRetry:
    """Tests for with_rate_limit_retry decorator."""

    def test_returns_result_on_success(self, rate_limit_config):
        """Decorated function returns normally on success."""
        @with_rate_limit_retry(rate_limit_config)
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"

    @patch("spec.utils.retry.time.sleep")
    def test_retries_on_retryable_error(self, mock_sleep, rate_limit_config):
        """Retries when retryable error occurs."""
        call_count = 0

        @with_rate_limit_retry(rate_limit_config)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("HTTP Error 429: Too Many Requests")
            return "eventual success"

        result = flaky_func()
        assert result == "eventual success"
        assert call_count == 3
        assert mock_sleep.call_count == 2  # 2 retries before success

    @patch("spec.utils.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep, rate_limit_config):
        """Raises RateLimitExceededError after max retries."""
        @with_rate_limit_retry(rate_limit_config)
        def always_fails():
            raise Exception("HTTP Error 429: Too Many Requests")

        with pytest.raises(RateLimitExceededError) as exc_info:
            always_fails()

        assert exc_info.value.attempts == rate_limit_config.max_retries
        assert "Rate limit exceeded" in str(exc_info.value)

    @patch("spec.utils.retry.time.sleep")
    def test_calls_on_retry_callback(self, mock_sleep, rate_limit_config):
        """Calls on_retry callback with attempt info."""
        callback = MagicMock()
        call_count = 0

        @with_rate_limit_retry(rate_limit_config, on_retry=callback)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Rate limit hit")
            return "success"

        flaky_func()

        # Callback should be called once (before the second attempt)
        assert callback.call_count == 1
        # Check callback args: (attempt_number, delay, exception)
        args = callback.call_args[0]
        assert args[0] == 1  # First retry attempt
        assert isinstance(args[1], float)  # delay
        assert isinstance(args[2], Exception)  # exception

    @patch("spec.utils.retry.time.sleep")
    def test_respects_calculated_delay(self, mock_sleep, rate_limit_config):
        """Uses calculated delay between retries."""
        call_count = 0

        @with_rate_limit_retry(rate_limit_config)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("429")
            return "success"

        flaky_func()

        # Verify sleep was called with the expected delay
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        # With jitter=0, first attempt delay should be base_delay
        assert delay == rate_limit_config.base_delay_seconds

    def test_non_retryable_error_raises_immediately(self, rate_limit_config):
        """Non-retryable errors are not retried."""
        call_count = 0

        @with_rate_limit_retry(rate_limit_config)
        def fails_with_normal_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")

        with pytest.raises(ValueError, match="Invalid input"):
            fails_with_normal_error()

        # Should only be called once (no retries)
        assert call_count == 1


class TestAuggieRateLimitErrorRetry:
    """Tests for retry behavior with AuggieRateLimitError."""

    @patch("spec.utils.retry.random.uniform", return_value=0.5)
    @patch("spec.utils.retry.time.sleep")
    def test_retry_triggers_on_auggie_rate_limit_error(self, mock_sleep, mock_random):
        """AuggieRateLimitError triggers retry with deterministic behavior.

        This test verifies that:
        1. AuggieRateLimitError is detected as retryable (contains rate limit keywords)
        2. Retry mechanism triggers with proper exponential backoff
        3. Mock sleep ensures deterministic, fast test execution
        4. Mock random.uniform ensures deterministic jitter calculation
        """
        config = RateLimitConfig(
            max_retries=3,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            jitter_factor=0.5,
        )
        call_count = 0

        @with_rate_limit_retry(config)
        def flaky_auggie_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # Simulate AuggieRateLimitError with rate limit output
                raise AuggieRateLimitError(
                    "Rate limit detected", output="HTTP 429 Too Many Requests"
                )
            return "eventual success"

        result = flaky_auggie_call()

        assert result == "eventual success"
        assert call_count == 3
        # 2 retries before success
        assert mock_sleep.call_count == 2
        # Verify jitter was calculated (random.uniform was called)
        assert mock_random.call_count >= 2

    @patch("spec.utils.retry.random.uniform", return_value=0.0)
    @patch("spec.utils.retry.time.sleep")
    def test_retry_exhaustion_on_persistent_rate_limit(self, mock_sleep, mock_random):
        """Persistent rate limit errors exhaust retries and raise RateLimitExceededError."""
        config = RateLimitConfig(
            max_retries=2,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
            jitter_factor=0.0,
        )

        @with_rate_limit_retry(config)
        def always_rate_limited():
            raise AuggieRateLimitError(
                "Rate limit", output="Error 429: rate limit exceeded"
            )

        with pytest.raises(RateLimitExceededError) as exc_info:
            always_rate_limited()

        assert exc_info.value.attempts == 2
        assert "Rate limit exceeded" in str(exc_info.value)
        # 2 retries means 2 sleep calls
        assert mock_sleep.call_count == 2

    @patch("spec.utils.retry.random.uniform", return_value=0.5)
    @patch("spec.utils.retry.time.sleep")
    def test_backoff_delay_calculation_deterministic(self, mock_sleep, mock_random):
        """Verify backoff delay calculation is deterministic with mocked random.

        Note: random.uniform(0, max) is mocked to return a fixed value (0.5).
        This becomes the actual jitter value added to the exponential delay.
        """
        config = RateLimitConfig(
            max_retries=3,
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
            jitter_factor=0.5,
        )
        call_count = 0

        @with_rate_limit_retry(config)
        def rate_limited_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise AuggieRateLimitError("Rate limit", output="429 error")
            return "success"

        rate_limited_then_succeeds()

        # Verify deterministic delay values:
        # random.uniform returns 0.5 (our mock value) as the jitter
        # Attempt 0: base * 2^0 = 2.0, jitter = 0.5, total = 2.5
        # Attempt 1: base * 2^1 = 4.0, jitter = 0.5, total = 4.5
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert len(calls) == 2
        assert calls[0] == pytest.approx(2.5)  # 2.0 + 0.5 jitter
        assert calls[1] == pytest.approx(4.5)  # 4.0 + 0.5 jitter

