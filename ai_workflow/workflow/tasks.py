"""Task parsing and management for AI Workflow.

This module provides functions for parsing task lists from markdown files,
tracking task completion, and managing task state.
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from ai_workflow.utils.logging import log_message


class TaskStatus(Enum):
    """Task completion status."""

    PENDING = "pending"
    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    SKIPPED = "skipped"


@dataclass
class Task:
    """Represents a single task from the task list.

    Attributes:
        name: Task name/description
        status: Current task status
        line_number: Line number in the task list file
        indent_level: Indentation level (for nested tasks)
        parent: Parent task name (if nested)
    """

    name: str
    status: TaskStatus = TaskStatus.PENDING
    line_number: int = 0
    indent_level: int = 0
    parent: Optional[str] = None


def parse_task_list(content: str) -> list[Task]:
    """Parse task list from markdown content.

    Supports formats:
    - [ ] Task name (pending)
    - [x] Task name (complete)
    - [X] Task name (complete)
    - * [ ] Task name (alternate bullet)
    - - [ ] Task name (dash bullet)

    Args:
        content: Markdown content with task list

    Returns:
        List of Task objects
    """
    tasks: list[Task] = []

    # Pattern for task items: optional bullet, checkbox, task name
    # Captures: indent, checkbox state, task name
    pattern = re.compile(
        r"^(\s*)[-*]?\s*\[([xX ])\]\s*(.+)$",
        re.MULTILINE,
    )

    for line_num, line in enumerate(content.splitlines(), start=1):
        match = pattern.match(line)
        if match:
            indent, checkbox, name = match.groups()
            indent_level = len(indent) // 2  # Assume 2-space indentation

            status = TaskStatus.COMPLETE if checkbox.lower() == "x" else TaskStatus.PENDING

            task = Task(
                name=name.strip(),
                status=status,
                line_number=line_num,
                indent_level=indent_level,
            )

            # Set parent for nested tasks
            if indent_level > 0 and tasks:
                for prev_task in reversed(tasks):
                    if prev_task.indent_level < indent_level:
                        task.parent = prev_task.name
                        break

            tasks.append(task)
            log_message(f"Parsed task: {task.name} ({task.status.value})")

    log_message(f"Total tasks parsed: {len(tasks)}")
    return tasks


def get_pending_tasks(tasks: list[Task]) -> list[Task]:
    """Get list of pending (incomplete) tasks.

    Args:
        tasks: List of all tasks

    Returns:
        List of pending tasks
    """
    return [t for t in tasks if t.status == TaskStatus.PENDING]


def get_completed_tasks(tasks: list[Task]) -> list[Task]:
    """Get list of completed tasks.

    Args:
        tasks: List of all tasks

    Returns:
        List of completed tasks
    """
    return [t for t in tasks if t.status == TaskStatus.COMPLETE]


def mark_task_complete(
    tasklist_path: Path,
    task_name: str,
) -> bool:
    """Mark a task as complete in the task list file.

    Updates the checkbox from [ ] to [x] for the matching task.

    Args:
        tasklist_path: Path to task list file
        task_name: Name of task to mark complete

    Returns:
        True if task was found and marked
    """
    if not tasklist_path.exists():
        log_message(f"Task list file not found: {tasklist_path}")
        return False

    content = tasklist_path.read_text()
    lines = content.splitlines()
    modified = False

    # Pattern to match the specific task
    task_pattern = re.compile(
        rf"^(\s*[-*]?\s*)\[ \](\s*{re.escape(task_name)}\s*)$"
    )

    for i, line in enumerate(lines):
        match = task_pattern.match(line)
        if match:
            prefix, suffix = match.groups()
            lines[i] = f"{prefix}[x]{suffix}"
            modified = True
            log_message(f"Marked task complete: {task_name}")
            break

    if modified:
        tasklist_path.write_text("\n".join(lines) + "\n")
        return True

    log_message(f"Task not found in file: {task_name}")
    return False


def format_task_list(tasks: list[Task]) -> str:
    """Format tasks as markdown task list.

    Args:
        tasks: List of tasks

    Returns:
        Markdown formatted task list
    """
    lines = []
    for task in tasks:
        indent = "  " * task.indent_level
        checkbox = "[x]" if task.status == TaskStatus.COMPLETE else "[ ]"
        lines.append(f"{indent}- {checkbox} {task.name}")
    return "\n".join(lines)


__all__ = [
    "TaskStatus",
    "Task",
    "parse_task_list",
    "get_pending_tasks",
    "get_completed_tasks",
    "mark_task_complete",
    "format_task_list",
]

