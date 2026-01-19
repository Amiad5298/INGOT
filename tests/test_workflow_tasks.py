"""Tests for spec.workflow.tasks module."""

import pytest
from pathlib import Path
from unittest.mock import patch

from spec.workflow.tasks import (
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
        """Formats pending task correctly with category metadata."""
        tasks = [Task(name="Task one", status=TaskStatus.PENDING)]

        result = format_task_list(tasks)

        # Now includes category metadata comment
        assert "<!-- category: fundamental -->" in result
        assert "- [ ] Task one" in result

    def test_formats_complete_task(self):
        """Formats complete task correctly with category metadata."""
        tasks = [Task(name="Task one", status=TaskStatus.COMPLETE)]

        result = format_task_list(tasks)

        # Now includes category metadata comment
        assert "<!-- category: fundamental -->" in result
        assert "- [x] Task one" in result

    def test_formats_indented_task(self):
        """Formats indented task correctly with category metadata."""
        tasks = [Task(name="Child task", indent_level=1)]

        result = format_task_list(tasks)

        # Now includes category metadata comment with proper indentation
        assert "<!-- category: fundamental -->" in result
        assert "- [ ] Child task" in result


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
        from spec.workflow.tasks import TaskCategory
        assert TaskCategory.FUNDAMENTAL.value == "fundamental"

    def test_independent_value(self):
        """INDEPENDENT has correct string value."""
        from spec.workflow.tasks import TaskCategory
        assert TaskCategory.INDEPENDENT.value == "independent"


# =============================================================================
# Tests for _parse_task_metadata
# =============================================================================


class TestParseTaskMetadata:
    """Tests for _parse_task_metadata function."""

    def test_parses_fundamental_category(self):
        """Parses 'category: fundamental' correctly."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 1 -->",
            "- [ ] Setup database",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 1
        assert group_id is None
        assert target_files == []

    def test_parses_independent_category(self):
        """Parses 'category: independent' correctly."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: ui -->",
            "- [ ] Create UI component",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.INDEPENDENT
        assert group_id == "ui"
        assert target_files == []

    def test_parses_order_field(self):
        """Parses 'order: N' correctly."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 5 -->",
            "- [ ] Task with order 5",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert order == 5

    def test_parses_group_field(self):
        """Parses 'group: name' correctly."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: backend -->",
            "- [ ] API endpoint",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert group_id == "backend"

    def test_handles_missing_metadata(self):
        """Returns defaults when no metadata comment."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "## Tasks",
            "- [ ] Task without metadata",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL  # Default
        assert order == 0
        assert group_id is None
        assert target_files == []

    def test_handles_partial_metadata(self):
        """Handles metadata with only some fields."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental -->",
            "- [ ] Task without order",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 0  # Default when not specified

    def test_case_insensitive_parsing(self):
        """Parses 'Category: FUNDAMENTAL' correctly."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: FUNDAMENTAL, order: 2 -->",
            "- [ ] Task with uppercase",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 2


# =============================================================================
# Tests for target_files metadata parsing (Predictive Context)
# =============================================================================


class TestTargetFilesMetadataParsing:
    """Tests for parsing <!-- files: ... --> metadata comments."""

    def test_parses_single_file(self):
        """Parses single file in files metadata."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- files: src/models/user.py -->",
            "- [ ] Create user model",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert target_files == ["src/models/user.py"]

    def test_parses_multiple_comma_separated_files(self):
        """Parses multiple comma-separated files."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- files: src/models/user.py, src/db/migrations/001.py, tests/test_user.py -->",
            "- [ ] Create user model with migration and tests",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert target_files == [
            "src/models/user.py",
            "src/db/migrations/001.py",
            "tests/test_user.py",
        ]

    def test_parses_files_on_separate_line_from_category(self):
        """Parses files metadata on separate line from category."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 1 -->",
            "<!-- files: src/auth/service.py, src/utils/password.py -->",
            "- [ ] Implement authentication service",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 2)

        assert category == TaskCategory.FUNDAMENTAL
        assert order == 1
        assert target_files == ["src/auth/service.py", "src/utils/password.py"]

    def test_parses_files_above_category(self):
        """Parses files metadata above category line."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- files: src/api/login.py -->",
            "<!-- category: independent, group: api -->",
            "- [ ] Create login endpoint",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 2)

        assert category == TaskCategory.INDEPENDENT
        assert group_id == "api"
        assert target_files == ["src/api/login.py"]

    def test_handles_empty_files_list(self):
        """Handles empty files metadata gracefully."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- files: -->",
            "- [ ] Task with empty files",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert target_files == []

    def test_handles_missing_files_metadata(self):
        """Returns empty list when no files metadata present."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: fundamental, order: 1 -->",
            "- [ ] Task without files",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert target_files == []

    def test_handles_whitespace_in_file_paths(self):
        """Handles extra whitespace around file paths."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- files:   src/file1.py  ,  src/file2.py  -->",
            "- [ ] Task with whitespace",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 1)

        assert target_files == ["src/file1.py", "src/file2.py"]

    def test_parses_files_with_blank_lines_above_task(self):
        """Parses files metadata with blank lines between metadata and task."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: utils -->",
            "<!-- files: src/utils/helpers.py -->",
            "",
            "- [ ] Create helper utilities",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 3)

        assert category == TaskCategory.INDEPENDENT
        assert target_files == ["src/utils/helpers.py"]


class TestTaskWithTargetFiles:
    """Tests for Task dataclass with target_files field."""

    def test_default_target_files_is_empty_list(self):
        """Default target_files is an empty list."""
        task = Task(name="Test task")
        assert task.target_files == []

    def test_target_files_can_be_set(self):
        """target_files can be set on construction."""
        task = Task(
            name="Test task",
            target_files=["src/file1.py", "src/file2.py"],
        )
        assert task.target_files == ["src/file1.py", "src/file2.py"]

    def test_parse_task_list_populates_target_files(self):
        """parse_task_list populates target_files from metadata."""
        content = """## Tasks
<!-- category: fundamental, order: 1 -->
<!-- files: src/models/user.py, tests/test_user.py -->
- [ ] Create user model with tests
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        assert tasks[0].target_files == ["src/models/user.py", "tests/test_user.py"]

    def test_parse_task_list_handles_multiple_tasks_with_files(self):
        """parse_task_list handles multiple tasks with different target files."""
        content = """## Fundamental Tasks
<!-- category: fundamental, order: 1 -->
<!-- files: src/db/schema.py -->
- [ ] Create database schema

## Independent Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/login.py, tests/api/test_login.py -->
- [ ] Create login endpoint

<!-- category: independent, group: api -->
<!-- files: src/api/register.py, tests/api/test_register.py -->
- [ ] Create registration endpoint
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 3
        assert tasks[0].target_files == ["src/db/schema.py"]
        assert tasks[1].target_files == ["src/api/login.py", "tests/api/test_login.py"]
        assert tasks[2].target_files == ["src/api/register.py", "tests/api/test_register.py"]


# =============================================================================
# Tests for get_fundamental_tasks
# =============================================================================


class TestGetFundamentalTasks:
    """Tests for get_fundamental_tasks function."""

    def test_returns_only_fundamental_tasks(self):
        """Filters to fundamental category only."""
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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
        from spec.workflow.tasks import (
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



# =============================================================================
# Tests for normalize_path and deduplicate_paths (Path Normalization & Security)
# =============================================================================


class TestNormalizePath:
    """Tests for normalize_path function.

    SECURITY: repo_root is now REQUIRED for all normalize_path calls.
    All tests use tmp_path fixture to provide a valid repo_root.
    """

    def test_trims_whitespace(self, tmp_path):
        """Trims leading and trailing whitespace."""
        from spec.workflow.tasks import normalize_path

        assert normalize_path("  src/file.py  ", repo_root=tmp_path) == "src/file.py"
        assert normalize_path("\tsrc/file.py\n", repo_root=tmp_path) == "src/file.py"

    def test_standardizes_separators(self, tmp_path):
        """Converts backslashes to forward slashes."""
        from spec.workflow.tasks import normalize_path

        assert normalize_path("src\\utils\\file.py", repo_root=tmp_path) == "src/utils/file.py"
        assert normalize_path("src\\\\nested\\\\file.py", repo_root=tmp_path) == "src/nested/file.py"

    def test_resolves_dot_components(self, tmp_path):
        """Resolves ./ and removes it."""
        from spec.workflow.tasks import normalize_path

        assert normalize_path("./src/file.py", repo_root=tmp_path) == "src/file.py"
        assert normalize_path("src/./utils/./file.py", repo_root=tmp_path) == "src/utils/file.py"

    def test_resolves_double_dot_components(self, tmp_path):
        """Resolves ../ components in paths that stay within repo."""
        from spec.workflow.tasks import normalize_path

        # Create directories so paths resolve correctly
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()

        assert normalize_path("src/../lib/file.py", repo_root=tmp_path) == "lib/file.py"
        assert normalize_path("src/utils/../file.py", repo_root=tmp_path) == "src/file.py"

    def test_empty_path_returns_empty_string(self, tmp_path):
        """Empty or whitespace-only paths return empty string."""
        from spec.workflow.tasks import normalize_path

        assert normalize_path("", repo_root=tmp_path) == ""
        assert normalize_path("   ", repo_root=tmp_path) == ""
        assert normalize_path("\t\n", repo_root=tmp_path) == ""

    def test_equivalent_paths_normalize_same(self, tmp_path):
        """Equivalent paths normalize to the same string."""
        from spec.workflow.tasks import normalize_path

        # Create src directory
        (tmp_path / "src").mkdir()

        path1 = normalize_path("./src/file.py", repo_root=tmp_path)
        path2 = normalize_path("src/file.py", repo_root=tmp_path)
        path3 = normalize_path("src/../src/file.py", repo_root=tmp_path)

        assert path1 == path2 == path3 == "src/file.py"


class TestNormalizePathWithRepoRoot:
    """Tests for normalize_path with repo_root (jail check)."""

    def test_resolves_relative_to_repo_root(self, tmp_path):
        """Resolves relative paths against repo_root."""
        from spec.workflow.tasks import normalize_path

        # Create a file structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file.py").touch()

        result = normalize_path("src/file.py", repo_root=tmp_path)
        assert result == "src/file.py"

    def test_jail_check_raises_on_escape(self, tmp_path):
        """Raises PathSecurityError when path escapes repo_root."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        with pytest.raises(PathSecurityError) as exc_info:
            normalize_path("../outside_repo.txt", repo_root=tmp_path)

        assert "outside_repo.txt" in str(exc_info.value)
        assert "escapes repository root" in str(exc_info.value)

    def test_jail_check_on_deeply_nested_escape(self, tmp_path):
        """Raises PathSecurityError on deeply nested escape attempt."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        with pytest.raises(PathSecurityError):
            normalize_path("src/../../../../../../etc/passwd", repo_root=tmp_path)

    def test_jail_check_allows_valid_nested_paths(self, tmp_path):
        """Allows valid nested paths that stay within repo."""
        from spec.workflow.tasks import normalize_path

        # Path that goes up and back down but stays within repo
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()

        result = normalize_path("src/../lib/file.py", repo_root=tmp_path)
        assert result == "lib/file.py"

    def test_jail_check_on_absolute_path_outside_repo(self, tmp_path):
        """Raises PathSecurityError on absolute path outside repo."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        with pytest.raises(PathSecurityError):
            normalize_path("/etc/passwd", repo_root=tmp_path)


class TestDeduplicatePaths:
    """Tests for deduplicate_paths function.

    SECURITY: repo_root is now REQUIRED for all deduplicate_paths calls.
    All tests use tmp_path fixture to provide a valid repo_root.
    """

    def test_removes_exact_duplicates(self, tmp_path):
        """Removes exact duplicate paths."""
        from spec.workflow.tasks import deduplicate_paths

        paths = ["src/file.py", "src/other.py", "src/file.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        assert result == ["src/file.py", "src/other.py"]

    def test_removes_equivalent_duplicates(self, tmp_path):
        """Removes duplicates that differ only by normalization."""
        from spec.workflow.tasks import deduplicate_paths

        # Create src directory
        (tmp_path / "src").mkdir()

        paths = ["./src/file.py", "src/file.py", "src/../src/file.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        assert len(result) == 1
        assert result[0] == "src/file.py"

    def test_preserves_order(self, tmp_path):
        """Preserves insertion order of first occurrence."""
        from spec.workflow.tasks import deduplicate_paths

        paths = ["z_file.py", "a_file.py", "m_file.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        assert result == ["z_file.py", "a_file.py", "m_file.py"]

    def test_removes_empty_paths(self, tmp_path):
        """Removes empty strings from result."""
        from spec.workflow.tasks import deduplicate_paths

        paths = ["src/file.py", "", "  ", "src/other.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        assert result == ["src/file.py", "src/other.py"]

    def test_handles_empty_list(self, tmp_path):
        """Handles empty input list."""
        from spec.workflow.tasks import deduplicate_paths

        assert deduplicate_paths([], repo_root=tmp_path) == []

    def test_deduplicates_with_repo_root(self, tmp_path):
        """Deduplicates using repo_root for normalization."""
        from spec.workflow.tasks import deduplicate_paths

        (tmp_path / "src").mkdir()

        paths = ["./src/file.py", "src/file.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        assert len(result) == 1
        assert result[0] == "src/file.py"

    def test_raises_on_security_violation(self, tmp_path):
        """Raises PathSecurityError if any path escapes repo."""
        from spec.workflow.tasks import deduplicate_paths, PathSecurityError

        paths = ["src/file.py", "../outside.py"]

        with pytest.raises(PathSecurityError):
            deduplicate_paths(paths, repo_root=tmp_path)


class TestPathSecurityError:
    """Tests for PathSecurityError exception."""

    def test_exception_attributes(self):
        """Exception stores path and repo_root attributes."""
        from spec.workflow.tasks import PathSecurityError

        error = PathSecurityError("../bad/path.txt", "/repo/root")

        assert error.path == "../bad/path.txt"
        assert error.repo_root == "/repo/root"

    def test_exception_message(self):
        """Exception message contains path and repo info."""
        from spec.workflow.tasks import PathSecurityError

        error = PathSecurityError("../escape.txt", "/my/repo")

        assert "../escape.txt" in str(error)
        assert "/my/repo" in str(error)
        assert "Security violation" in str(error)



# =============================================================================
# Tests for Multiline Metadata Parsing
# =============================================================================


class TestMultilineMetadataParsing:
    """Tests for multiline HTML comment metadata parsing."""

    def test_parses_multiline_files_comment(self):
        """Parses files metadata spanning multiple lines."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!--",
            "  files: src/api/login.py,",
            "         src/api/register.py,",
            "         tests/test_auth.py",
            "-->",
            "- [ ] Implement authentication",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 5)

        assert target_files == [
            "src/api/login.py",
            "src/api/register.py",
            "tests/test_auth.py",
        ]

    def test_parses_multiline_category_and_files(self):
        """Parses multiline comment with both category and files."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!--",
            "  category: independent, group: api",
            "  files: src/api/endpoint.py",
            "-->",
            "- [ ] Create API endpoint",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 4)

        assert category == TaskCategory.INDEPENDENT
        assert group_id == "api"
        assert target_files == ["src/api/endpoint.py"]

    def test_parses_files_with_newline_separators(self):
        """Parses files separated by newlines with trailing commas."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        # Note: When files are on separate lines, trailing commas are recommended
        # to ensure proper parsing after multiline comment joining
        lines = [
            "<!--",
            "  files:",
            "    src/file1.py,",
            "    src/file2.py,",
            "    src/file3.py",
            "-->",
            "- [ ] Multi-file task",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 6)

        assert target_files == ["src/file1.py", "src/file2.py", "src/file3.py"]

    def test_parses_three_plus_line_comment(self):
        """Parses metadata block spanning 3+ lines (required test case)."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!--
  category: independent, group: refactor
  files: src/module/component.py,
         src/module/helper.py,
         tests/module/test_component.py,
         tests/module/test_helper.py
-->
- [ ] Refactor module with comprehensive tests
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        task = tasks[0]
        assert task.category.value == "independent"
        assert task.group_id == "refactor"
        assert len(task.target_files) == 4
        assert "src/module/component.py" in task.target_files
        assert "src/module/helper.py" in task.target_files
        assert "tests/module/test_component.py" in task.target_files
        assert "tests/module/test_helper.py" in task.target_files

    def test_handles_mixed_single_and_multiline_comments(self):
        """Handles mix of single-line and multi-line comments."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!-- category: fundamental, order: 1 -->
- [ ] Single-line metadata task

<!--
  category: independent, group: batch
  files: src/batch/processor.py,
         src/batch/handler.py
-->
- [ ] Multi-line metadata task
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 2

        # First task: single-line
        assert tasks[0].category.value == "fundamental"
        assert tasks[0].dependency_order == 1
        assert tasks[0].target_files == []

        # Second task: multi-line
        assert tasks[1].category.value == "independent"
        assert tasks[1].group_id == "batch"
        assert len(tasks[1].target_files) == 2

    def test_multiline_with_blank_lines_above_task(self):
        """Handles multiline comment with blank lines before task."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!--",
            "  files: src/file.py",
            "-->",
            "",
            "- [ ] Task with gap",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 4)

        assert target_files == ["src/file.py"]



# =============================================================================
# Tests for Round-Trip Persistence (Parse -> Format -> Parse)
# =============================================================================


class TestRoundTripPersistence:
    """Tests for round-trip integrity: parse -> format -> parse preserves data."""

    def test_round_trip_preserves_target_files(self):
        """Parse -> format -> parse preserves target_files exactly."""
        from spec.workflow.tasks import parse_task_list, format_task_list

        original_content = """## Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/login.py, tests/api/test_login.py -->
- [ ] Create login endpoint

<!-- category: independent, group: api -->
<!-- files: src/api/register.py -->
- [ ] Create register endpoint
"""
        # First parse
        tasks1 = parse_task_list(original_content)
        assert len(tasks1) == 2
        assert tasks1[0].target_files == ["src/api/login.py", "tests/api/test_login.py"]
        assert tasks1[1].target_files == ["src/api/register.py"]

        # Format back to string
        formatted = format_task_list(tasks1)

        # Parse again
        tasks2 = parse_task_list(formatted)
        assert len(tasks2) == 2

        # Verify target_files are preserved
        assert tasks2[0].target_files == tasks1[0].target_files
        assert tasks2[1].target_files == tasks1[1].target_files

    def test_round_trip_preserves_category_and_order(self):
        """Parse -> format -> parse preserves category and order."""
        from spec.workflow.tasks import parse_task_list, format_task_list, TaskCategory

        original_content = """## Fundamental Tasks
<!-- category: fundamental, order: 1 -->
- [ ] Setup database

<!-- category: fundamental, order: 2 -->
- [ ] Create schema

## Independent Tasks
<!-- category: independent, group: features -->
- [ ] Add user feature
"""
        tasks1 = parse_task_list(original_content)
        formatted = format_task_list(tasks1)
        tasks2 = parse_task_list(formatted)

        assert len(tasks2) == 3

        # Fundamental tasks
        assert tasks2[0].category == TaskCategory.FUNDAMENTAL
        assert tasks2[0].dependency_order == 1
        assert tasks2[1].category == TaskCategory.FUNDAMENTAL
        assert tasks2[1].dependency_order == 2

        # Independent task
        assert tasks2[2].category == TaskCategory.INDEPENDENT
        assert tasks2[2].group_id == "features"

    def test_round_trip_preserves_task_status(self):
        """Parse -> format -> parse preserves complete/pending status."""
        from spec.workflow.tasks import parse_task_list, format_task_list, TaskStatus

        original_content = """<!-- category: fundamental, order: 1 -->
- [x] Completed task

<!-- category: fundamental, order: 2 -->
- [ ] Pending task
"""
        tasks1 = parse_task_list(original_content)
        formatted = format_task_list(tasks1)
        tasks2 = parse_task_list(formatted)

        assert tasks2[0].status == TaskStatus.COMPLETE
        assert tasks2[1].status == TaskStatus.PENDING

    def test_round_trip_preserves_indentation(self):
        """Parse -> format -> parse preserves task indentation."""
        from spec.workflow.tasks import parse_task_list, format_task_list

        original_content = """<!-- category: fundamental -->
- [ ] Parent task
  <!-- category: fundamental -->
  - [ ] Child task
    <!-- category: fundamental -->
    - [ ] Grandchild task
"""
        tasks1 = parse_task_list(original_content)
        formatted = format_task_list(tasks1)
        tasks2 = parse_task_list(formatted)

        assert tasks2[0].indent_level == 0
        assert tasks2[1].indent_level == 1
        assert tasks2[2].indent_level == 2

    def test_round_trip_with_empty_target_files(self):
        """Parse -> format -> parse handles tasks with no target_files."""
        from spec.workflow.tasks import parse_task_list, format_task_list

        original_content = """<!-- category: fundamental, order: 1 -->
- [ ] Task without files
"""
        tasks1 = parse_task_list(original_content)
        assert tasks1[0].target_files == []

        formatted = format_task_list(tasks1)
        # Should not contain files: comment for empty list
        assert "files:" not in formatted

        tasks2 = parse_task_list(formatted)
        assert tasks2[0].target_files == []

    def test_round_trip_preserves_all_metadata_fields(self):
        """Full round-trip test preserving all metadata fields."""
        from spec.workflow.tasks import parse_task_list, format_task_list, TaskCategory

        original_content = """<!-- category: independent, group: batch -->
<!-- files: src/batch/processor.py, src/batch/handler.py, tests/batch/test_processor.py -->
- [ ] Implement batch processor
"""
        tasks1 = parse_task_list(original_content)
        formatted = format_task_list(tasks1)
        tasks2 = parse_task_list(formatted)

        assert len(tasks2) == 1
        task = tasks2[0]

        # All fields preserved
        assert task.name == "Implement batch processor"
        assert task.category == TaskCategory.INDEPENDENT
        assert task.group_id == "batch"
        assert task.target_files == [
            "src/batch/processor.py",
            "src/batch/handler.py",
            "tests/batch/test_processor.py",
        ]

    def test_format_includes_category_metadata(self):
        """format_task_list includes category metadata in output."""
        from spec.workflow.tasks import format_task_list, Task, TaskCategory

        tasks = [
            Task(
                name="Fundamental task",
                category=TaskCategory.FUNDAMENTAL,
                dependency_order=1,
            ),
            Task(
                name="Independent task",
                category=TaskCategory.INDEPENDENT,
                group_id="utils",
            ),
        ]

        result = format_task_list(tasks)

        assert "<!-- category: fundamental, order: 1 -->" in result
        assert "<!-- category: independent, group: utils -->" in result

    def test_format_includes_files_metadata(self):
        """format_task_list includes files metadata in output."""
        from spec.workflow.tasks import format_task_list, Task, TaskCategory

        tasks = [
            Task(
                name="Task with files",
                category=TaskCategory.INDEPENDENT,
                target_files=["src/file1.py", "src/file2.py"],
            ),
        ]

        result = format_task_list(tasks)

        assert "<!-- files: src/file1.py, src/file2.py -->" in result



# =============================================================================
# Tests for Metadata Bleed Prevention
# =============================================================================


class TestMetadataBleedPrevention:
    """Tests to ensure metadata doesn't 'bleed' to unrelated tasks."""

    def test_metadata_followed_by_text_then_task(self):
        """Metadata followed by text paragraph, then task - metadata should NOT attach."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/endpoint.py -->

This is a paragraph of text that separates the metadata from the task below.
It should prevent the metadata from attaching to the task.

- [ ] Task that should NOT have the metadata above
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        task = tasks[0]

        # The metadata should NOT have attached to this task
        # because there was a text paragraph in between
        assert task.target_files == []
        # Category should be default (fundamental) since metadata didn't attach
        # Note: depending on implementation, this might vary

    def test_metadata_immediately_before_task(self):
        """Metadata immediately before task should attach correctly."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/endpoint.py -->
- [ ] Task that SHOULD have the metadata
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        task = tasks[0]

        # Metadata should attach
        assert task.target_files == ["src/api/endpoint.py"]
        assert task.group_id == "api"

    def test_metadata_with_blank_lines_still_attaches(self):
        """Metadata with only blank lines before task should still attach."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!-- category: independent, group: api -->
<!-- files: src/api/endpoint.py -->

- [ ] Task with blank line gap
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        task = tasks[0]

        # Blank lines should not prevent attachment
        assert task.target_files == ["src/api/endpoint.py"]

    def test_text_between_metadata_and_task_blocks_attachment(self):
        """Text content between metadata and task blocks attachment."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: api -->",
            "<!-- files: src/api/endpoint.py -->",
            "",
            "Some explanatory text here.",
            "",
            "- [ ] Task after text",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 5)

        # Metadata should NOT attach due to text in between
        assert target_files == []

    def test_multiple_tasks_each_get_own_metadata(self):
        """Each task gets only its own metadata, not from other tasks."""
        from spec.workflow.tasks import parse_task_list

        content = """## Tasks
<!-- category: independent, group: group1 -->
<!-- files: src/file1.py -->
- [ ] First task

<!-- category: independent, group: group2 -->
<!-- files: src/file2.py -->
- [ ] Second task
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 2

        # First task gets first metadata
        assert tasks[0].group_id == "group1"
        assert tasks[0].target_files == ["src/file1.py"]

        # Second task gets second metadata
        assert tasks[1].group_id == "group2"
        assert tasks[1].target_files == ["src/file2.py"]

    def test_orphan_metadata_does_not_attach_to_later_task(self):
        """Orphan metadata (no task after) doesn't attach to later tasks."""
        from spec.workflow.tasks import parse_task_list

        content = """## Section 1
<!-- category: independent, group: orphan -->
<!-- files: src/orphan.py -->

## Section 2
- [ ] Task in different section
"""
        tasks = parse_task_list(content)

        assert len(tasks) == 1
        task = tasks[0]

        # The orphan metadata should NOT attach to this task
        assert task.target_files == []
        assert task.group_id is None

    def test_heading_between_metadata_and_task_blocks_attachment(self):
        """Heading between metadata and task blocks attachment."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: api -->",
            "<!-- files: src/api/endpoint.py -->",
            "",
            "## New Section",
            "",
            "- [ ] Task after heading",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 5)

        # Metadata should NOT attach due to heading in between
        assert target_files == []

    def test_code_block_between_metadata_and_task_blocks_attachment(self):
        """Code block between metadata and task blocks attachment."""
        from spec.workflow.tasks import _parse_task_metadata, TaskCategory

        lines = [
            "<!-- category: independent, group: api -->",
            "<!-- files: src/api/endpoint.py -->",
            "",
            "```python",
            "def example():",
            "    pass",
            "```",
            "",
            "- [ ] Task after code block",
        ]
        category, order, group_id, target_files = _parse_task_metadata(lines, 8)

        # Metadata should NOT attach due to code block in between
        assert target_files == []



# =============================================================================
# Security Regression Tests (Predictive Context)
# =============================================================================


class TestSecurityRegressions:
    """Security regression tests for path normalization and jail check.

    These tests verify that the security primitives correctly prevent:
    1. Directory traversal attacks (../outside.py)
    2. Path collision via normalization bypass (./src/foo.py vs src/foo.py)

    CRITICAL: These tests must NEVER be removed or weakened.
    """

    def test_malicious_path_traversal_raises_security_error(self, tmp_path):
        """SECURITY: Malicious path ../outside.py with repo_root raises PathSecurityError."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        # Attempt directory traversal attack
        with pytest.raises(PathSecurityError) as exc_info:
            normalize_path("../outside.py", repo_root=tmp_path)

        # Verify exception contains attack path and repo info
        assert "../outside.py" in str(exc_info.value)
        assert "escapes repository root" in str(exc_info.value)
        assert exc_info.value.path == "../outside.py"

    def test_deeply_nested_traversal_attack(self, tmp_path):
        """SECURITY: Deeply nested traversal ../../../../../../etc/passwd is blocked."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        with pytest.raises(PathSecurityError):
            normalize_path("src/../../../../../../etc/passwd", repo_root=tmp_path)

    def test_path_normalization_detects_collision(self, tmp_path):
        """SECURITY: src/foo.py and ./src/foo.py normalize to same path (collision detection)."""
        from spec.workflow.tasks import normalize_path

        # Create src directory
        (tmp_path / "src").mkdir()

        # Both paths should normalize to the same value
        path1 = normalize_path("src/foo.py", repo_root=tmp_path)
        path2 = normalize_path("./src/foo.py", repo_root=tmp_path)

        assert path1 == path2 == "src/foo.py"

    def test_deduplicate_detects_normalized_collision(self, tmp_path):
        """SECURITY: deduplicate_paths treats ./src/foo.py and src/foo.py as same file."""
        from spec.workflow.tasks import deduplicate_paths

        # Create src directory
        (tmp_path / "src").mkdir()

        paths = ["./src/foo.py", "src/foo.py", "src/bar.py"]
        result = deduplicate_paths(paths, repo_root=tmp_path)

        # Should deduplicate to 2 unique paths
        assert len(result) == 2
        assert "src/foo.py" in result
        assert "src/bar.py" in result

    def test_absolute_path_outside_repo_blocked(self, tmp_path):
        """SECURITY: Absolute paths outside repo are blocked."""
        from spec.workflow.tasks import normalize_path, PathSecurityError

        with pytest.raises(PathSecurityError):
            normalize_path("/etc/passwd", repo_root=tmp_path)

    def test_symlink_escape_attempt_blocked(self, tmp_path):
        """SECURITY: Symlink-based escape attempts are blocked by resolve()."""
        from spec.workflow.tasks import normalize_path, PathSecurityError
        import os

        # Create a symlink pointing outside the repo
        outside_dir = tmp_path.parent / "outside_target"
        outside_dir.mkdir(exist_ok=True)
        (outside_dir / "secret.txt").touch()

        symlink_path = tmp_path / "escape_link"
        try:
            symlink_path.symlink_to(outside_dir)
        except OSError:
            pytest.skip("Cannot create symlinks on this system")

        # Attempting to access file through symlink should be blocked
        with pytest.raises(PathSecurityError):
            normalize_path("escape_link/secret.txt", repo_root=tmp_path)

    def test_repo_root_is_required_not_optional(self, tmp_path):
        """SECURITY: normalize_path requires repo_root (no default None)."""
        from spec.workflow.tasks import normalize_path
        import inspect

        # Verify repo_root has no default value (is required)
        sig = inspect.signature(normalize_path)
        repo_root_param = sig.parameters.get("repo_root")

        assert repo_root_param is not None
        assert repo_root_param.default is inspect.Parameter.empty, \
            "repo_root must be required (no default) for security"

    def test_deduplicate_paths_repo_root_is_required(self, tmp_path):
        """SECURITY: deduplicate_paths requires repo_root (no default None)."""
        from spec.workflow.tasks import deduplicate_paths
        import inspect

        # Verify repo_root has no default value (is required)
        sig = inspect.signature(deduplicate_paths)
        repo_root_param = sig.parameters.get("repo_root")

        assert repo_root_param is not None
        assert repo_root_param.default is inspect.Parameter.empty, \
            "repo_root must be required (no default) for security"