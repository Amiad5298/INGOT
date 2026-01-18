"""Log management utilities for Step 3 execution.

This module provides utilities for managing run log directories,
including creating timestamped directories and cleaning up old runs.
"""

import os
import shutil
from pathlib import Path

from spec.workflow.events import format_run_directory


# Default log retention count
DEFAULT_LOG_RETENTION = 10


def get_log_base_dir() -> Path:
    """Get the base directory for run logs.

    Returns:
        Path to the log base directory.
    """
    env_dir = os.environ.get("SPEC_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".spec/runs")


def create_run_log_dir(ticket_id: str) -> Path:
    """Create a timestamped log directory for this run.

    Args:
        ticket_id: Ticket identifier for directory naming.

    Returns:
        Path to the created log directory.
    """
    base_dir = get_log_base_dir()
    ticket_dir = base_dir / ticket_id
    run_dir = ticket_dir / format_run_directory()

    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def cleanup_old_runs(ticket_id: str, keep_count: int = DEFAULT_LOG_RETENTION) -> None:
    """Remove old run directories beyond retention limit.

    Args:
        ticket_id: Ticket identifier.
        keep_count: Number of runs to keep.
    """
    base_dir = get_log_base_dir()
    ticket_dir = base_dir / ticket_id

    if not ticket_dir.exists():
        return

    # Get all run directories sorted by name (timestamp order)
    run_dirs = sorted(
        [d for d in ticket_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    # Remove directories beyond retention limit
    for old_dir in run_dirs[keep_count:]:
        try:
            shutil.rmtree(old_dir)
        except Exception:
            pass  # Ignore cleanup errors


# Backwards-compatible aliases (underscore-prefixed)
_get_log_base_dir = get_log_base_dir
_create_run_log_dir = create_run_log_dir
_cleanup_old_runs = cleanup_old_runs


__all__ = [
    "DEFAULT_LOG_RETENTION",
    "get_log_base_dir",
    "create_run_log_dir",
    "cleanup_old_runs",
    # Backwards-compatible aliases
    "_get_log_base_dir",
    "_create_run_log_dir",
    "_cleanup_old_runs",
]

