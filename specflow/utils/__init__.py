"""Utility modules for SPEC.

This package contains:
- console: Rich-based terminal output utilities
- errors: Custom exceptions and exit codes
- error_analysis: Structured error parsing for better retry prompts
- logging: Logging configuration
- retry: Rate limit handling with exponential backoff
"""

from specflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
    show_banner,
)
from specflow.utils.error_analysis import ErrorAnalysis, analyze_error_output
from specflow.utils.errors import (
    SpecError,
    AuggieNotInstalledError,
    ExitCode,
    GitOperationError,
    JiraNotConfiguredError,
    UserCancelledError,
)
from specflow.utils.logging import log_command, log_message, setup_logging
from specflow.utils.retry import (
    RateLimitExceededError,
    calculate_backoff_delay,
    with_rate_limit_retry,
)

__all__ = [
    # Console
    "console",
    "print_error",
    "print_success",
    "print_warning",
    "print_info",
    "print_header",
    "print_step",
    "show_banner",
    # Errors
    "ExitCode",
    "SpecError",
    "AuggieNotInstalledError",
    "JiraNotConfiguredError",
    "UserCancelledError",
    "GitOperationError",
    # Error Analysis
    "ErrorAnalysis",
    "analyze_error_output",
    # Logging
    "setup_logging",
    "log_message",
    "log_command",
    # Retry
    "RateLimitExceededError",
    "calculate_backoff_delay",
    "with_rate_limit_retry",
]

