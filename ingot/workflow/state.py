"""Workflow state management for INGOT.

This module provides the WorkflowState dataclass that tracks the
current state of the workflow execution.
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.providers import GenericTicket

# Import subagent constants as single source of truth
from ingot.workflow.constants import (
    INGOT_AGENT_DOC_UPDATER,
    INGOT_AGENT_FIXER,
    INGOT_AGENT_IMPLEMENTER,
    INGOT_AGENT_PLANNER,
    INGOT_AGENT_RESEARCHER,
    INGOT_AGENT_REVIEWER,
    INGOT_AGENT_TASKLIST,
    INGOT_AGENT_TASKLIST_REFINER,
    SESSION_RESET_INTERVAL,
)
from ingot.workflow.git_utils import DirtyTreePolicy

if TYPE_CHECKING:
    from ingot.workflow.task_memory import TaskMemory


@dataclass
class RateLimitConfig:
    """Configuration for API rate limit handling.

    Implements exponential backoff with jitter to handle rate limit errors
    (HTTP 429) from concurrent API calls during parallel task execution.

    """

    max_retries: int = 5  # Maximum retry attempts
    base_delay_seconds: float = 2.0  # Initial delay
    max_delay_seconds: float = 60.0  # Cap on delay
    jitter_factor: float = 0.5  # Random jitter (0-50% of delay)

    # HTTP status codes that trigger retry
    retryable_status_codes: tuple[int, ...] = (429, 502, 503, 504)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.max_retries > 0 and self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be > 0 when max_retries > 0")
        if self.jitter_factor < 0 or self.jitter_factor > 1:
            raise ValueError("jitter_factor must be in [0, 1]")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")


@dataclass
class WorkflowState:
    """Tracks the current state of workflow execution.

    This dataclass holds all the state needed to execute and resume
    the AI-assisted development workflow.

    """

    # Ticket information (platform-agnostic)
    ticket: GenericTicket

    # Git state
    branch_name: str = ""
    base_commit: str = ""
    # Baseline ref for Step 3 diff operations (captured at execution start)
    diff_baseline_ref: str = ""

    # Model configuration
    planning_model: str = ""
    implementation_model: str = ""

    # Workflow options
    skip_clarification: bool = False
    squash_at_end: bool = True
    fail_fast: bool = False  # Stop execution on first task failure
    max_self_corrections: int = 3  # Max self-correction attempts per task (0 = disable)
    max_review_fix_attempts: int = 3  # Max auto-fix attempts during review (0 = disable)
    session_reset_interval: int = SESSION_RESET_INTERVAL  # Reset session every N sequential tasks

    # User-provided constraints & preferences
    user_constraints: str = ""

    # Ticket signals extracted from ticket text (e.g., "metric", "alert", "migration")
    ticket_signals: list[str] = field(default_factory=list)

    # Conflict detection (Fail-Fast Semantic Check)
    # Detects semantic conflicts between ticket description and user constraints
    conflict_detected: bool = False
    conflict_summary: str = ""

    # File paths
    plan_file: Path | None = None
    tasklist_file: Path | None = None

    # Progress tracking
    completed_tasks: list[str] = field(default_factory=list)
    checkpoint_commits: list[str] = field(default_factory=list)

    # Execution state
    current_step: int = 1
    retry_count: int = 0
    max_retries: int = 3

    # Task memory system (for cross-task learning without context pollution)
    task_memories: list["TaskMemory"] = field(default_factory=list)

    # Parallel execution configuration
    max_parallel_tasks: int = 3  # Default concurrency limit
    parallel_execution_enabled: bool = True

    # Rate limit configuration
    rate_limit_config: RateLimitConfig = field(default_factory=RateLimitConfig)

    # Review configuration
    enable_phase_review: bool = False  # Enable phase reviews after task execution

    # Plan validation
    enable_plan_validation: bool = True
    validation_strict: bool = True  # Block workflow on validation errors (vs. warn-and-proceed)

    # Re-planning state
    replan_count: int = 0  # Number of execution replans (Step 3 post-review)
    plan_revision_count: int = 0  # Number of plan revisions (Step 1 regenerations)
    max_replans: int = 2  # Maximum replan attempts (prevents infinite loops)

    # Snapshot of untracked files before step 3 execution, used by
    # restore_to_baseline to avoid deleting pre-existing untracked files.
    pre_execution_untracked: frozenset[str] = field(default_factory=frozenset)

    # Dirty tree policy for baseline diff operations
    dirty_tree_policy: DirtyTreePolicy = DirtyTreePolicy.FAIL_FAST

    # AI Backend platform (set by runner from injected backend)
    backend_platform: AgentPlatform | None = None
    # AI Backend model (set by runner from injected backend)
    backend_model: str | None = None
    # AI Backend display name (set by runner from injected backend)
    backend_name: str | None = None

    # Subagent configuration (names loaded from settings)
    # Defaults from workflow constants - the single source of truth
    subagent_names: dict[str, str] = field(
        default_factory=lambda: {
            "planner": INGOT_AGENT_PLANNER,
            "tasklist": INGOT_AGENT_TASKLIST,
            "tasklist_refiner": INGOT_AGENT_TASKLIST_REFINER,
            "implementer": INGOT_AGENT_IMPLEMENTER,
            "reviewer": INGOT_AGENT_REVIEWER,
            "fixer": INGOT_AGENT_FIXER,
            "doc_updater": INGOT_AGENT_DOC_UPDATER,
            "researcher": INGOT_AGENT_RESEARCHER,
        }
    )

    # Threading lock for thread-safe state mutations (parallel execution)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.max_review_fix_attempts < 0 or self.max_review_fix_attempts > 10:
            raise ValueError(
                f"max_review_fix_attempts must be 0-10, got {self.max_review_fix_attempts}"
            )
        if self.max_self_corrections < 0 or self.max_self_corrections > 10:
            raise ValueError(f"max_self_corrections must be 0-10, got {self.max_self_corrections}")
        if self.max_replans < 0 or self.max_replans > 5:
            raise ValueError(f"max_replans must be 0-5, got {self.max_replans}")
        if self.session_reset_interval < 1 or self.session_reset_interval > 100:
            raise ValueError(
                f"session_reset_interval must be 1-100, got {self.session_reset_interval}"
            )

    @property
    def spec_verified(self) -> bool:
        """Whether the ticket has verified platform content (derived from ticket)."""
        return self.ticket.has_verified_content

    @property
    def specs_dir(self) -> Path:
        """Get the specs directory path."""
        return Path("specs")

    @property
    def plan_filename(self) -> str:
        """Get the plan filename based on ticket ID (filesystem-safe)."""
        return f"{self.ticket.safe_filename_stem}-plan.md"

    @property
    def tasklist_filename(self) -> str:
        """Get the task list filename based on ticket ID (filesystem-safe)."""
        return f"{self.ticket.safe_filename_stem}-tasklist.md"

    def get_plan_path(self) -> Path:
        """Get full path to plan file."""
        if self.plan_file:
            return self.plan_file
        return self.specs_dir / self.plan_filename

    def get_tasklist_path(self) -> Path:
        """Get full path to task list file."""
        if self.tasklist_file:
            return self.tasklist_file
        return self.specs_dir / self.tasklist_filename

    def mark_task_complete(self, task_name: str) -> None:
        """Mark a task as complete (thread-safe)."""
        with self._lock:
            if task_name not in self.completed_tasks:
                self.completed_tasks.append(task_name)


__all__ = [
    "DirtyTreePolicy",
    "RateLimitConfig",
    "WorkflowState",
]
