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


class TestDeeplyNestedTasks:
    """Tests for deeply nested tasks (3+ levels)."""

    def test_parses_three_level_nesting(self):
        """Parses tasks with 3 levels of nesting."""
        content = """- [ ] Parent task
  - [ ] Child task
    - [ ] Grandchild task"""
        tasks = parse_task_list(content)

        assert len(tasks) == 3
        assert tasks[0].indent_level == 0
        assert tasks[1].indent_level == 1
        assert tasks[2].indent_level == 2
        assert tasks[1].parent == "Parent task"
        assert tasks[2].parent == "Child task"

    def test_parses_four_level_nesting(self):
        """Parses tasks with 4 levels of nesting."""
        content = """- [ ] Level 0
  - [ ] Level 1
    - [ ] Level 2
      - [ ] Level 3"""
        tasks = parse_task_list(content)

        assert len(tasks) == 4
        assert tasks[3].indent_level == 3
        assert tasks[3].parent == "Level 2"

    def test_formats_deeply_nested_tasks(self):
        """Formats deeply nested tasks correctly."""
        tasks = [
            Task(name="Level 0", indent_level=0),
            Task(name="Level 1", indent_level=1),
            Task(name="Level 2", indent_level=2),
            Task(name="Level 3", indent_level=3),
        ]

        result = format_task_list(tasks)

        assert "- [ ] Level 0" in result
        assert "  - [ ] Level 1" in result
        assert "    - [ ] Level 2" in result
        assert "      - [ ] Level 3" in result


class TestMixedIndentationStyles:
    """Tests for mixed indentation styles."""

    def test_parses_mixed_bullets(self):
        """Parses tasks with mixed bullet styles."""
        content = """- [ ] Dash task
* [ ] Asterisk task
[ ] No bullet task"""
        tasks = parse_task_list(content)

        assert len(tasks) == 3
        assert tasks[0].name == "Dash task"
        assert tasks[1].name == "Asterisk task"
        assert tasks[2].name == "No bullet task"

    def test_parses_mixed_checkbox_cases(self):
        """Parses tasks with mixed checkbox cases."""
        content = """- [x] Lowercase complete
- [X] Uppercase complete
- [ ] Pending task"""
        tasks = parse_task_list(content)

        assert len(tasks) == 3
        assert tasks[0].status == TaskStatus.COMPLETE
        assert tasks[1].status == TaskStatus.COMPLETE
        assert tasks[2].status == TaskStatus.PENDING


class TestEdgeCases:
    """Tests for edge cases."""

    def test_parses_empty_content(self):
        """Handles empty content."""
        tasks = parse_task_list("")
        assert tasks == []

    def test_parses_content_with_only_headers(self):
        """Handles content with only headers."""
        content = """# Header 1

## Header 2

Some text without tasks.
"""
        tasks = parse_task_list(content)
        assert tasks == []

    def test_parses_whitespace_only_content(self):
        """Handles content with only whitespace."""
        tasks = parse_task_list("   \n\n   \n")
        assert tasks == []

    def test_parses_task_with_special_characters(self):
        """Parses task with special characters in name."""
        content = "- [ ] Task with special: [brackets], (parens), {braces}, `backticks`"
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        assert "[brackets]" in tasks[0].name
        assert "(parens)" in tasks[0].name
        assert "`backticks`" in tasks[0].name

    def test_parses_task_with_emojis(self):
        """Parses task with emojis in name."""
        content = "- [ ] Task with emoji 🎉 and 🚀"
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        assert "🎉" in tasks[0].name
        assert "🚀" in tasks[0].name

    def test_parses_task_with_urls(self):
        """Parses task with URLs in name."""
        content = "- [ ] Review PR at https://github.com/org/repo/pull/123"
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        assert "https://github.com/org/repo/pull/123" in tasks[0].name


class TestMarkTaskCompleteEdgeCases:
    """Tests for mark_task_complete edge cases."""

    def test_returns_false_when_task_not_found(self, tmp_path):
        """Returns False when task is not found in file."""
        tasklist = tmp_path / "tasks.md"
        tasklist.write_text("- [ ] Different task\n- [ ] Another task\n")

        result = mark_task_complete(tasklist, "Nonexistent task")

        assert result is False
        # File should be unchanged
        content = tasklist.read_text()
        assert "[ ] Different task" in content
        assert "[ ] Another task" in content

    def test_only_marks_exact_match(self, tmp_path):
        """Only marks the task with exact name match."""
        tasklist = tmp_path / "tasks.md"
        tasklist.write_text("- [ ] Task\n- [ ] Task with suffix\n- [ ] Prefix Task\n")

        result = mark_task_complete(tasklist, "Task")

        assert result is True
        content = tasklist.read_text()
        assert "[x] Task\n" in content
        assert "[ ] Task with suffix" in content
        assert "[ ] Prefix Task" in content

    def test_handles_already_complete_task(self, tmp_path):
        """Handles case when task is already complete."""
        tasklist = tmp_path / "tasks.md"
        tasklist.write_text("- [x] Already done\n- [ ] Not done\n")

        # Trying to mark already complete task returns False (no match for [ ])
        result = mark_task_complete(tasklist, "Already done")

        assert result is False

    def test_handles_special_regex_characters_in_task_name(self, tmp_path):
        """Handles special regex characters in task name."""
        tasklist = tmp_path / "tasks.md"
        tasklist.write_text("- [ ] Fix bug (issue #123)\n")

        result = mark_task_complete(tasklist, "Fix bug (issue #123)")

        assert result is True
        content = tasklist.read_text()
        assert "[x] Fix bug (issue #123)" in content


# =============================================================================
# Tests for TaskCategory enum
# =============================================================================


class TestTaskCategory:
    """Tests for TaskCategory enum."""

    def test_fundamental_value(self):
        """FUNDAMENTAL has correct string value."""
        from ai_workflow.workflow.tasks import TaskCategory
        assert TaskCategory.FUNDAMENTAL.value == "fundamental"

    def test_independent_value(self):
        """INDEPENDENT has correct string value."""
        from ai_workflow.workflow.tasks import TaskCategory
        assert TaskCategory.INDEPENDENT.value == "independent"


# =============================================================================
# Tests for _parse_task_metadata
# =============================================================================


class TestParseTaskMetadata:
    """Tests for _parse_task_metadata function."""

    def test_parses_fundamental_category(self):
        """Parses 'category: fundamental' correctly."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 1 -->",
            "- [ ] Setup database",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 1
        assert group_id is None

    def test_parses_independent_category(self):
        """Parses 'category: independent' correctly."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: ui -->",
            "- [ ] Create UI component",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.INDEPENDENT
        assert group_id == "ui"

    def test_parses_order_field(self):
        """Parses 'order: N' correctly."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 5 -->",
            "- [ ] Task with order 5",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert order == 5

    def test_parses_group_field(self):
        """Parses 'group: name' correctly."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: backend -->",
            "- [ ] API endpoint",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert group_id == "backend"

    def test_handles_missing_metadata(self):
        """Returns defaults when no metadata comment."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "## Tasks",
            "- [ ] Task without metadata",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL  # Default
        assert order == 0
        assert group_id is None

    def test_handles_partial_metadata(self):
        """Handles metadata with only some fields."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental -->",
            "- [ ] Task without order",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 0  # Default when not specified

    def test_case_insensitive_parsing(self):
        """Parses 'Category: FUNDAMENTAL' correctly."""
        from ai_workflow.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: FUNDAMENTAL, order: 2 -->",
            "- [ ] Task with uppercase",
        ]
        category, order, group_id = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 2


# =============================================================================
# Tests for get_fundamental_tasks
# =============================================================================


class TestGetFundamentalTasks:
    """Tests for get_fundamental_tasks function."""

    def test_returns_only_fundamental_tasks(self):
        """Filters to fundamental category only."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, TaskStatus, get_fundamental_tasks
        )

        tasks = [
            Task(name="Schema", category=TaskCategory.FUNDAMENTAL),
            Task(name="UI Component", category=TaskCategory.INDEPENDENT),
            Task(name="API Endpoint", category=TaskCategory.FUNDAMENTAL),
        ]

        result = get_fundamental_tasks(tasks)

        assert len(result) == 2
        assert all(t.category == TaskCategory.FUNDAMENTAL for t in result)

    def test_returns_empty_when_none_exist(self):
        """Returns empty list when no fundamental tasks."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        tasks = [
            Task(name="UI Component", category=TaskCategory.INDEPENDENT),
            Task(name="Utils", category=TaskCategory.INDEPENDENT),
        ]

        result = get_fundamental_tasks(tasks)

        assert result == []

    def test_preserves_order(self):
        """Tasks returned in dependency_order."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        tasks = [
            Task(name="Third", category=TaskCategory.FUNDAMENTAL, dependency_order=3),
            Task(name="First", category=TaskCategory.FUNDAMENTAL, dependency_order=1),
            Task(name="Second", category=TaskCategory.FUNDAMENTAL, dependency_order=2),
        ]

        result = get_fundamental_tasks(tasks)

        assert [t.name for t in result] == ["First", "Second", "Third"]


# =============================================================================
# Tests for get_independent_tasks
# =============================================================================


class TestGetIndependentTasks:
    """Tests for get_independent_tasks function."""

    def test_returns_only_independent_tasks(self):
        """Filters to independent category only."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_independent_tasks
        )

        tasks = [
            Task(name="Schema", category=TaskCategory.FUNDAMENTAL),
            Task(name="UI Component", category=TaskCategory.INDEPENDENT),
            Task(name="Utils", category=TaskCategory.INDEPENDENT),
        ]

        result = get_independent_tasks(tasks)

        assert len(result) == 2
        assert all(t.category == TaskCategory.INDEPENDENT for t in result)

    def test_returns_empty_when_none_exist(self):
        """Returns empty list when no independent tasks."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_independent_tasks
        )

        tasks = [
            Task(name="Schema", category=TaskCategory.FUNDAMENTAL),
            Task(name="API", category=TaskCategory.FUNDAMENTAL),
        ]

        result = get_independent_tasks(tasks)

        assert result == []


# =============================================================================
# Tests for get_pending_fundamental_tasks
# =============================================================================


class TestGetPendingFundamentalTasks:
    """Tests for get_pending_fundamental_tasks function."""

    def test_excludes_completed_tasks(self):
        """Only returns non-completed fundamental tasks."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, TaskStatus, get_pending_fundamental_tasks
        )

        tasks = [
            Task(name="Done", category=TaskCategory.FUNDAMENTAL, status=TaskStatus.COMPLETE),
            Task(name="Pending", category=TaskCategory.FUNDAMENTAL, status=TaskStatus.PENDING),
        ]

        result = get_pending_fundamental_tasks(tasks)

        assert len(result) == 1
        assert result[0].name == "Pending"

    def test_excludes_independent_tasks(self):
        """Only returns fundamental tasks, not independent."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, TaskStatus, get_pending_fundamental_tasks
        )

        tasks = [
            Task(name="Fundamental", category=TaskCategory.FUNDAMENTAL, status=TaskStatus.PENDING),
            Task(name="Independent", category=TaskCategory.INDEPENDENT, status=TaskStatus.PENDING),
        ]

        result = get_pending_fundamental_tasks(tasks)

        assert len(result) == 1
        assert result[0].name == "Fundamental"


# =============================================================================
# Tests for get_pending_independent_tasks
# =============================================================================


class TestGetPendingIndependentTasks:
    """Tests for get_pending_independent_tasks function."""

    def test_excludes_completed_tasks(self):
        """Only returns non-completed independent tasks."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, TaskStatus, get_pending_independent_tasks
        )

        tasks = [
            Task(name="Done", category=TaskCategory.INDEPENDENT, status=TaskStatus.COMPLETE),
            Task(name="Pending", category=TaskCategory.INDEPENDENT, status=TaskStatus.PENDING),
            Task(name="Fundamental", category=TaskCategory.FUNDAMENTAL, status=TaskStatus.PENDING),
        ]

        result = get_pending_independent_tasks(tasks)

        assert len(result) == 1
        assert result[0].name == "Pending"


class TestFundamentalTaskOrdering:
    """Tests for stable ordering of fundamental tasks."""

    def test_sorts_by_dependency_order_then_line_number(self):
        """Fundamental tasks sort by dependency_order, then line_number."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        tasks = [
            Task(name="Task C", category=TaskCategory.FUNDAMENTAL, dependency_order=1, line_number=30),
            Task(name="Task A", category=TaskCategory.FUNDAMENTAL, dependency_order=1, line_number=10),
            Task(name="Task B", category=TaskCategory.FUNDAMENTAL, dependency_order=1, line_number=20),
            Task(name="Task D", category=TaskCategory.FUNDAMENTAL, dependency_order=2, line_number=5),
        ]

        result = get_fundamental_tasks(tasks)

        # Same dependency_order should be sorted by line_number
        assert result[0].name == "Task A"  # order=1, line=10
        assert result[1].name == "Task B"  # order=1, line=20
        assert result[2].name == "Task C"  # order=1, line=30
        assert result[3].name == "Task D"  # order=2, line=5

    def test_stable_ordering_with_same_values(self):
        """Tasks with same dependency_order and line_number maintain stable order."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        # All tasks have same dependency_order and line_number
        tasks = [
            Task(name="First", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=0),
            Task(name="Second", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=0),
            Task(name="Third", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=0),
        ]

        result = get_fundamental_tasks(tasks)

        # Python's sort is stable, so original order should be preserved
        assert len(result) == 3
        assert result[0].name == "First"
        assert result[1].name == "Second"
        assert result[2].name == "Third"

    def test_explicit_order_comes_before_order_zero(self):
        """Tasks with explicit order (>0) come before tasks with order=0."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        tasks = [
            Task(name="NoOrder1", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=10),
            Task(name="Order2", category=TaskCategory.FUNDAMENTAL, dependency_order=2, line_number=20),
            Task(name="NoOrder2", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=30),
            Task(name="Order1", category=TaskCategory.FUNDAMENTAL, dependency_order=1, line_number=40),
        ]

        result = get_fundamental_tasks(tasks)

        # Explicit orders (>0) should come first, sorted by order
        # Then order=0 tasks, sorted by line_number
        assert result[0].name == "Order1"  # order=1 comes first (explicit order)
        assert result[1].name == "Order2"  # order=2 comes second (explicit order)
        assert result[2].name == "NoOrder1"  # order=0, line=10 (implicit order)
        assert result[3].name == "NoOrder2"  # order=0, line=30 (implicit order)

    def test_mixed_explicit_and_implicit_ordering(self):
        """Mixed explicit and implicit orders produce correct sequence."""
        from ai_workflow.workflow.tasks import (
            Task, TaskCategory, get_fundamental_tasks
        )

        tasks = [
            # Implicit order tasks (order=0), sorted by line_number
            Task(name="Implicit1", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=5),
            Task(name="Implicit2", category=TaskCategory.FUNDAMENTAL, dependency_order=0, line_number=15),
            # Explicit order tasks (order>0), sorted by order, then line_number
            Task(name="Explicit3A", category=TaskCategory.FUNDAMENTAL, dependency_order=3, line_number=100),
            Task(name="Explicit3B", category=TaskCategory.FUNDAMENTAL, dependency_order=3, line_number=50),
            Task(name="Explicit1", category=TaskCategory.FUNDAMENTAL, dependency_order=1, line_number=200),
        ]

        result = get_fundamental_tasks(tasks)

        # Expected order:
        # 1. Explicit order=1 (line=200)
        # 2. Explicit order=3 (line=50) - same order, lower line_number first
        # 3. Explicit order=3 (line=100)
        # 4. Implicit order=0 (line=5)
        # 5. Implicit order=0 (line=15)
        assert [t.name for t in result] == [
            "Explicit1",  # order=1
            "Explicit3B",  # order=3, line=50
            "Explicit3A",  # order=3, line=100
            "Implicit1",  # order=0, line=5
            "Implicit2",  # order=0, line=15
        ]
