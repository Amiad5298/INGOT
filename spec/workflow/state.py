"""Workflow state management for SPEC.

This module provides the WorkflowState dataclass that tracks the
current state of the workflow execution.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from spec.config.fetch_config import AgentPlatform
from spec.integrations.providers import GenericTicket

# Import subagent constants as single source of truth
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
from spec.workflow.git_utils import DirtyTreePolicy

if TYPE_CHECKING:
    from spec.workflow.task_memory import TaskMemory


@dataclass
class RateLimitConfig:
    """Configuration for API rate limit handling.

    Implements exponential backoff with jitter to handle rate limit errors
    (HTTP 429) from concurrent API calls during parallel task execution.

    Attributes:
        max_retries: Maximum retry attempts before giving up
        base_delay_seconds: Initial delay before first retry
        max_delay_seconds: Maximum delay cap to prevent excessive waits
        jitter_factor: Random jitter factor (0.5 = up to 50% of delay)
        retryable_status_codes: HTTP status codes that trigger retry
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

    Attributes:
        ticket: Ticket information (platform-agnostic)
        branch_name: Git branch name for this workflow
        base_commit: Commit hash before workflow started
        planning_model: AI model for planning phases
        implementation_model: AI model for implementation phase
        skip_clarification: Whether to skip clarification step
        squash_at_end: Whether to squash commits at end
        plan_file: Path to the implementation plan file
        tasklist_file: Path to the task list file
        completed_tasks: List of completed task names
        checkpoint_commits: List of checkpoint commit hashes
        current_step: Current workflow step (1, 2, 3, or 4)
        retry_count: Number of retries for current task
        max_retries: Maximum retries before asking user
        subagent_names: Dictionary mapping role names to agent names
            (planner, tasklist, implementer, reviewer, doc_updater)
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

    # User-provided additional context
    user_context: str = ""

    # Conflict detection (Fail-Fast Semantic Check)
    # Detects semantic conflicts between ticket description and user context
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

    # Dirty tree policy for baseline diff operations
    dirty_tree_policy: DirtyTreePolicy = DirtyTreePolicy.FAIL_FAST

    # AI Backend platform (set by runner from injected backend)
    backend_platform: AgentPlatform | None = None

    # Subagent configuration (names loaded from settings)
    # Defaults from auggie.py constants - the single source of truth
    subagent_names: dict[str, str] = field(
        default_factory=lambda: {
            "planner": SPECFLOW_AGENT_PLANNER,
            "tasklist": SPECFLOW_AGENT_TASKLIST,
            "tasklist_refiner": SPECFLOW_AGENT_TASKLIST_REFINER,
            "implementer": SPECFLOW_AGENT_IMPLEMENTER,
            "reviewer": SPECFLOW_AGENT_REVIEWER,
            "doc_updater": SPECFLOW_AGENT_DOC_UPDATER,
        }
    )

    @property
    def specs_dir(self) -> Path:
        """Get the specs directory path.

        Returns:
            Path to specs directory
        """
        return Path("specs")

    @property
    def plan_filename(self) -> str:
        """Get the plan filename.

        Returns:
            Plan filename based on ticket ID (filesystem-safe)
        """
        return f"{self.ticket.safe_filename_stem}-plan.md"

    @property
    def tasklist_filename(self) -> str:
        """Get the task list filename.

        Returns:
            Task list filename based on ticket ID (filesystem-safe)
        """
        return f"{self.ticket.safe_filename_stem}-tasklist.md"

    def get_plan_path(self) -> Path:
        """Get full path to plan file.

        Returns:
            Full path to plan file
        """
        if self.plan_file:
            return self.plan_file
        return self.specs_dir / self.plan_filename

    def get_tasklist_path(self) -> Path:
        """Get full path to task list file.

        Returns:
            Full path to task list file
        """
        if self.tasklist_file:
            return self.tasklist_file
        return self.specs_dir / self.tasklist_filename

    def mark_task_complete(self, task_name: str) -> None:
        """Mark a task as complete.

        Args:
            task_name: Name of the completed task
        """
        if task_name not in self.completed_tasks:
            self.completed_tasks.append(task_name)


__all__ = [
    "DirtyTreePolicy",
    "RateLimitConfig",
    "WorkflowState",
]
