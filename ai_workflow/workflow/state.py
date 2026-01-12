"""Workflow state management for AI Workflow.

This module provides the WorkflowState dataclass that tracks the
current state of the workflow execution.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ai_workflow.integrations.jira import JiraTicket

if TYPE_CHECKING:
    from ai_workflow.workflow.task_memory import TaskMemory


@dataclass
class WorkflowState:
    """Tracks the current state of workflow execution.

    This dataclass holds all the state needed to execute and resume
    the AI-assisted development workflow.

    Attributes:
        ticket: Jira ticket information
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
        current_step: Current workflow step (1, 2, or 3)
        retry_count: Number of retries for current task
        max_retries: Maximum retries before asking user
    """

    # Ticket information
    ticket: JiraTicket

    # Git state
    branch_name: str = ""
    base_commit: str = ""

    # Model configuration
    planning_model: str = ""
    implementation_model: str = ""

    # Workflow options
    skip_clarification: bool = False
    squash_at_end: bool = True
    fail_fast: bool = False  # Stop execution on first task failure

    # User-provided additional context
    user_context: str = ""

    # File paths
    plan_file: Optional[Path] = None
    tasklist_file: Optional[Path] = None

    # Progress tracking
    completed_tasks: list[str] = field(default_factory=list)
    checkpoint_commits: list[str] = field(default_factory=list)

    # Execution state
    current_step: int = 1
    retry_count: int = 0
    max_retries: int = 3

    # Task memory system (for cross-task learning without context pollution)
    task_memories: list["TaskMemory"] = field(default_factory=list)

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
            Plan filename based on ticket ID
        """
        return f"{self.ticket.ticket_id}-plan.md"

    @property
    def tasklist_filename(self) -> str:
        """Get the task list filename.

        Returns:
            Task list filename based on ticket ID
        """
        return f"{self.ticket.ticket_id}-tasklist.md"

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

    def add_checkpoint(self, commit_hash: str) -> None:
        """Add a checkpoint commit.

        Args:
            commit_hash: Short commit hash
        """
        self.checkpoint_commits.append(commit_hash)

    def reset_retries(self) -> None:
        """Reset retry counter."""
        self.retry_count = 0

    def increment_retries(self) -> bool:
        """Increment retry counter.

        Returns:
            True if more retries available, False if max reached
        """
        self.retry_count += 1
        return self.retry_count < self.max_retries


__all__ = [
    "WorkflowState",
]

