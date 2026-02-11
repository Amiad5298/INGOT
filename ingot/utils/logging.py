"""Logging configuration and shared CLI utilities for INGOT.

This module provides logging functionality that matches the original
Bash script's logging behavior, controlled by environment variables.

Environment Variables:
    INGOT_LOG: Set to "true" to enable logging (default: "false")
    INGOT_LOG_FILE: Path to log file (default: ~/.ingot.log)
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

# Environment variable configuration
LOG_ENABLED = os.environ.get("INGOT_LOG", "false").lower() == "true"
LOG_FILE = Path(os.environ.get("INGOT_LOG_FILE", str(Path.home() / ".ingot.log")))

# Module-level logger instance
_logger: logging.Logger | None = None


def setup_logging() -> logging.Logger:
    """Configure logging based on environment variables.

    Creates a logger that writes to the configured log file when
    INGOT_LOG is set to "true". Otherwise, uses a NullHandler
    to suppress all log output.

    Returns:
        Configured logger instance
    """
    global _logger

    if _logger is not None:
        return _logger

    logger = logging.getLogger("ingot")

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
    Messages are only written to the log file if INGOT_LOG=true.

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


def check_cli_installed(cli_name: str) -> tuple[bool, str]:
    """Check if a CLI tool is installed and accessible.

    Shared implementation for check_aider_installed, check_gemini_installed,
    check_codex_installed, etc. Looks up the CLI in PATH and runs --version.

    Args:
        cli_name: The CLI executable name (e.g. "aider", "gemini", "codex")

    Returns:
        (is_valid, message) tuple where message is the version string
        if installed, or an error message if not.
    """
    if shutil.which(cli_name):
        try:
            result = subprocess.run(
                [cli_name, "--version"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            log_command(f"{cli_name} --version", result.returncode)

            version_output = result.stdout.strip() or result.stderr.strip()
            if result.returncode == 0 and version_output:
                return True, version_output

        except Exception as e:
            log_message(f"Failed to check {cli_name} CLI: {e}")

    return False, f"{cli_name} CLI is not installed or not in PATH"


def log_backend_metadata(
    backend_name: str,
    *,
    model: str | None = None,
    timeout: float | None = None,
) -> None:
    """Log sanitized backend command metadata for debugging.

    Used by CLI client wrappers to log model/timeout info without
    leaking prompt contents.

    Args:
        backend_name: Name of the backend (e.g. "aider", "gemini", "codex")
        model: Model name if specified
        timeout: Timeout in seconds if specified
    """
    parts: list[str] = []
    if model:
        parts.append(f"model={model}")
    if timeout is not None:
        parts.append(f"timeout={timeout}s")
    if parts:
        log_message(f"  {backend_name} metadata: {', '.join(parts)}")


__all__ = [
    "LOG_ENABLED",
    "LOG_FILE",
    "setup_logging",
    "get_logger",
    "log_message",
    "log_command",
    "log_backend_metadata",
    "check_cli_installed",
]
