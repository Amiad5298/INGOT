"""Utility modules for AI Workflow.

This package contains:
- console: Rich-based terminal output utilities
- errors: Custom exceptions and exit codes
- error_analysis: Structured error parsing for better retry prompts
- logging: Logging configuration
"""

from ai_workflow.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
    show_banner,
)
from ai_workflow.utils.error_analysis import ErrorAnalysis, analyze_error_output
from ai_workflow.utils.errors import (
    AIWorkflowError,
    AuggieNotInstalledError,
    ExitCode,
    GitOperationError,
    JiraNotConfiguredError,
    UserCancelledError,
)
from ai_workflow.utils.logging import log_command, log_message, setup_logging

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
    "AIWorkflowError",
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
]

