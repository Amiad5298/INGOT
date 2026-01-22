"""Logging configuration for SPECFLOW.

This module provides logging functionality that matches the original
Bash script's logging behavior, controlled by environment variables.

Environment Variables:
    SPEC_LOG: Set to "true" to enable logging (default: "false")
    SPEC_LOG_FILE: Path to log file (default: ~/.spec.log)
"""

import logging
import os
from pathlib import Path

# Environment variable configuration
LOG_ENABLED = os.environ.get("SPEC_LOG", "false").lower() == "true"
LOG_FILE = Path(os.environ.get("SPEC_LOG_FILE", str(Path.home() / ".spec.log")))

# Module-level logger instance
_logger: logging.Logger | None = None


def setup_logging() -> logging.Logger:
    """Configure logging based on environment variables.

    Creates a logger that writes to the configured log file when
    SPECFLOW_LOG is set to "true". Otherwise, uses a NullHandler
    to suppress all log output.

    Returns:
        Configured logger instance
    """
    global _logger

    if _logger is not None:
        return _logger

    logger = logging.getLogger("spec")

    # Clear any existing handlers
    logger.handlers.clear()

    if LOG_ENABLED:
        # Ensure log directory exists
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    else:
        logger.addHandler(logging.NullHandler())

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Get the configured logger instance.

    Returns:
        The configured logger, creating it if necessary
    """
    global _logger
    if _logger is None:
        return setup_logging()
    return _logger


def log_message(message: str) -> None:
    """Log a message if logging is enabled.

    This is the primary logging function used throughout the application.
    Messages are only written to the log file if SPECFLOW_LOG=true.

    Args:
        message: Message to log
    """
    logger = get_logger()
    logger.info(message)


def log_command(command: str, exit_code: int = 0) -> None:
    """Log command execution with exit code.

    Used to track external command execution (git, auggie, etc.)
    for debugging purposes.

    Args:
        command: The command that was executed
        exit_code: The exit code returned by the command
    """
    logger = get_logger()
    logger.info(f"COMMAND: {command} | EXIT_CODE: {exit_code}")


__all__ = [
    "LOG_ENABLED",
    "LOG_FILE",
    "setup_logging",
    "get_logger",
    "log_message",
    "log_command",
]

