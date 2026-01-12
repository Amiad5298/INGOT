"""Tests for ai_workflow.workflow.tasks module."""

import pytest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.workflow.tasks import (
    TaskStatus,
    Task,
    parse_task_list,
    get_pending_tasks,
    get_completed_tasks,
    mark_task_complete,
    format_task_list,
)


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_pending_value(self):
        """PENDING has correct value."""
        assert TaskStatus.PENDING.value == "pending"

    def test_complete_value(self):
        """COMPLETE has correct value."""
        assert TaskStatus.COMPLETE.value == "complete"


class TestTask:
    """Tests for Task dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        task = Task(name="Test task")
        assert task.status == TaskStatus.PENDING
        assert task.line_number == 0
        assert task.indent_level == 0
        assert task.parent is None


class TestParseTaskList:
    """Tests for parse_task_list function."""

    def test_parses_pending_task(self):
        """Parses pending task with [ ]."""
        content = "- [ ] Task one"
        tasks = parse_task_list(content)
        
        assert len(tasks) == 1
        assert tasks[0].name == "Task one"
        assert tasks[0].status == TaskStatus.PENDING

    def test_parses_complete_task(self):
        """Parses complete task with [x]."""
        content = "- [x] Task one"
        tasks = parse_task_list(content)
        
        assert len(tasks) == 1
        assert tasks[0].status == TaskStatus.COMPLETE

    def test_parses_uppercase_x(self):
        """Parses complete task with [X]."""
        content = "- [X] Task one"
        tasks = parse_task_list(content)
        
        assert tasks[0].status == TaskStatus.COMPLETE

    def test_parses_multiple_tasks(self):
        """Parses multiple tasks."""
        content = """- [ ] Task one
- [x] Task two
- [ ] Task three"""
        tasks = parse_task_list(content)
        
        assert len(tasks) == 3

    def test_parses_asterisk_bullet(self):
        """Parses task with * bullet."""
        content = "* [ ] Task one"
        tasks = parse_task_list(content)
        
        assert len(tasks) == 1
        assert tasks[0].name == "Task one"

    def test_parses_no_bullet(self):
        """Parses task without bullet."""
        content = "[ ] Task one"
        tasks = parse_task_list(content)
        
        assert len(tasks) == 1

    def test_parses_indented_tasks(self):
        """Parses indented (nested) tasks."""
        content = """- [ ] Parent task
  - [ ] Child task"""
        tasks = parse_task_list(content)
        
        assert len(tasks) == 2
        assert tasks[1].indent_level == 1
        assert tasks[1].parent == "Parent task"

    def test_ignores_non_task_lines(self):
        """Ignores lines that aren't tasks."""
        content = """# Header
Some text
- [ ] Actual task
More text"""
        tasks = parse_task_list(content)
        
        assert len(tasks) == 1


class TestGetPendingTasks:
    """Tests for get_pending_tasks function."""

    def test_returns_only_pending(self):
        """Returns only pending tasks."""
        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.COMPLETE),
            Task(name="Task 3", status=TaskStatus.PENDING),
        ]
        
        pending = get_pending_tasks(tasks)
        
        assert len(pending) == 2
        assert all(t.status == TaskStatus.PENDING for t in pending)


class TestGetCompletedTasks:
    """Tests for get_completed_tasks function."""

    def test_returns_only_completed(self):
        """Returns only completed tasks."""
        tasks = [
            Task(name="Task 1", status=TaskStatus.PENDING),
            Task(name="Task 2", status=TaskStatus.COMPLETE),
        ]
        
        completed = get_completed_tasks(tasks)
        
        assert len(completed) == 1
        assert completed[0].name == "Task 2"


class TestMarkTaskComplete:
    """Tests for mark_task_complete function."""

    def test_marks_task_complete(self, tmp_path):
        """Marks task as complete in file."""
        tasklist = tmp_path / "tasks.md"
        tasklist.write_text("- [ ] Task one\n- [ ] Task two\n")
        
        result = mark_task_complete(tasklist, "Task one")
        
        assert result is True
        content = tasklist.read_text()
        assert "[x] Task one" in content
        assert "[ ] Task two" in content

    def test_returns_false_for_missing_file(self, tmp_path):
        """Returns False when file doesn't exist."""
        tasklist = tmp_path / "nonexistent.md"
        
        result = mark_task_complete(tasklist, "Task one")
        
        assert result is False


class TestFormatTaskList:
    """Tests for format_task_list function."""

    def test_formats_pending_task(self):
        """Formats pending task correctly."""
        tasks = [Task(name="Task one", status=TaskStatus.PENDING)]
        
        result = format_task_list(tasks)
        
        assert result == "- [ ] Task one"

    def test_formats_complete_task(self):
        """Formats complete task correctly."""
        tasks = [Task(name="Task one", status=TaskStatus.COMPLETE)]
        
        result = format_task_list(tasks)
        
        assert result == "- [x] Task one"

    def test_formats_indented_task(self):
        """Formats indented task correctly."""
        tasks = [Task(name="Child task", indent_level=1)]
        
        result = format_task_list(tasks)
        
        assert result == "  - [ ] Child task"

