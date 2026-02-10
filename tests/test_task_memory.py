"""Tests for ingot.workflow.task_memory module."""

import subprocess
from unittest.mock import MagicMock, patch

from ingot.integrations.providers import GenericTicket, Platform
from ingot.workflow.state import WorkflowState
from ingot.workflow.task_memory import (
    TaskMemory,
    _extract_test_commands,
    _get_modified_files,
    _identify_patterns_in_changes,
    build_pattern_context,
    capture_task_memory,
    find_related_task_memories,
)
from ingot.workflow.tasks import Task


class TestTaskMemory:
    def test_init_with_defaults(self):
        memory = TaskMemory(task_name="Test task")

        assert memory.task_name == "Test task"
        assert memory.files_modified == []
        assert memory.patterns_used == []
        assert memory.key_decisions == []
        assert memory.test_commands == []

    def test_to_markdown_basic(self):
        memory = TaskMemory(
            task_name="Test task",
            files_modified=["file1.py", "file2.py"],
        )

        markdown = memory.to_markdown()

        assert "### Test task" in markdown
        assert "**Files:** file1.py, file2.py" in markdown

    def test_to_markdown_with_patterns(self):
        memory = TaskMemory(
            task_name="Test task",
            patterns_used=["Python implementation", "Added Python tests"],
        )

        markdown = memory.to_markdown()

        assert "**Patterns:**" in markdown
        assert "- Python implementation" in markdown
        assert "- Added Python tests" in markdown

    def test_to_markdown_with_decisions(self):
        memory = TaskMemory(
            task_name="Test task",
            key_decisions=["Use async/await", "Add error handling"],
        )

        markdown = memory.to_markdown()

        assert "**Key Decisions:**" in markdown
        assert "- Use async/await" in markdown
        assert "- Add error handling" in markdown


class TestGetModifiedFiles:
    @patch("subprocess.run")
    def test_returns_modified_files(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="file1.py\nfile2.py\nfile3.ts\n",
        )

        files = _get_modified_files()

        assert files == ["file1.py", "file2.py", "file3.ts"]
        mock_run.assert_called_once_with(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("subprocess.run")
    def test_returns_empty_on_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        files = _get_modified_files()

        assert files == []


class TestIdentifyPatternsInChanges:
    def test_identifies_python_pattern(self):
        files = ["src/module.py", "src/utils.py"]

        patterns = _identify_patterns_in_changes(files)

        assert "Python implementation" in patterns

    def test_identifies_python_test_pattern(self):
        files = ["tests/test_module.py", "src/module.py"]

        patterns = _identify_patterns_in_changes(files)

        assert "Python implementation" in patterns
        assert "Added Python tests" in patterns

    def test_identifies_typescript_pattern(self):
        files = ["src/component.ts", "src/utils.tsx"]

        patterns = _identify_patterns_in_changes(files)

        assert "TypeScript implementation" in patterns

    def test_identifies_typescript_test_pattern(self):
        files = ["src/component.test.ts", "src/component.ts"]

        patterns = _identify_patterns_in_changes(files)

        assert "TypeScript implementation" in patterns
        assert "Added TypeScript tests" in patterns

    def test_identifies_api_pattern(self):
        files = ["src/api/users.py", "src/api/auth.py"]

        patterns = _identify_patterns_in_changes(files)

        assert "API endpoint implementation" in patterns

    def test_identifies_database_pattern(self):
        files = ["src/models/user.py", "src/schema/tables.py"]

        patterns = _identify_patterns_in_changes(files)

        assert "Database schema/model" in patterns

    def test_identifies_ui_pattern(self):
        files = ["src/components/Button.tsx", "src/ui/Modal.tsx"]

        patterns = _identify_patterns_in_changes(files)

        assert "UI component" in patterns

    @patch("subprocess.run")
    def test_identifies_async_pattern_from_diff(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="+ async def fetch_data():\n+     await client.get()\n",
        )

        patterns = _identify_patterns_in_changes(["src/api.py"])

        assert "Async/await pattern" in patterns

    @patch("subprocess.run")
    def test_identifies_error_handling_pattern_from_diff(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="+ try:\n+     result = process()\n+ except Exception:\n+     handle_error()\n",
        )

        patterns = _identify_patterns_in_changes(["src/utils.py"])

        assert "Error handling with try/catch" in patterns

    @patch("subprocess.run")
    def test_identifies_dataclass_pattern_from_diff(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="+ @dataclass\n+ class User:\n+     name: str\n",
        )

        patterns = _identify_patterns_in_changes(["src/models.py"])

        assert "Dataclass pattern" in patterns

    @patch("subprocess.run")
    def test_identifies_test_suite_pattern_from_diff(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="+ def test_user_creation():\n+     pytest.fixture()\n+     assert user.name == 'test'\n",
        )

        patterns = _identify_patterns_in_changes(["tests/test_user.py"])

        assert "Test suite structure" in patterns


class TestExtractTestCommands:
    def test_extracts_pytest_command(self):
        task = Task(name="Write unit tests for user module")
        files = ["tests/test_user.py", "src/user.py"]

        commands = _extract_test_commands(task, files)

        assert "pytest tests/test_user.py" in commands

    def test_extracts_npm_test_command(self):
        task = Task(name="Write tests for Button component")
        files = ["src/Button.test.ts", "src/Button.ts"]

        commands = _extract_test_commands(task, files)

        assert "npm test src/Button.test.ts" in commands

    def test_returns_empty_for_non_test_task(self):
        task = Task(name="Implement user authentication")
        files = ["src/auth.py", "src/user.py"]

        commands = _extract_test_commands(task, files)

        assert commands == []

    def test_handles_multiple_test_files(self):
        task = Task(name="Write tests for API endpoints")
        files = ["tests/test_users.py", "tests/test_auth.py", "src/api.py"]

        commands = _extract_test_commands(task, files)

        assert len(commands) == 2
        assert "pytest tests/test_users.py" in commands
        assert "pytest tests/test_auth.py" in commands


class TestCaptureTaskMemory:
    @patch("ingot.workflow.task_memory._get_modified_files")
    @patch("ingot.workflow.task_memory._identify_patterns_in_changes")
    @patch("ingot.workflow.task_memory._extract_test_commands")
    def test_captures_task_memory(self, mock_extract, mock_identify, mock_get_files):
        mock_get_files.return_value = ["file1.py", "file2.py"]
        mock_identify.return_value = ["Python implementation"]
        mock_extract.return_value = ["pytest tests/test_file.py"]

        task = Task(name="Implement user module")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        memory = capture_task_memory(task, state)

        assert memory.task_name == "Implement user module"
        assert memory.files_modified == ["file1.py", "file2.py"]
        assert memory.patterns_used == ["Python implementation"]
        assert memory.test_commands == ["pytest tests/test_file.py"]

    @patch("ingot.workflow.task_memory._get_modified_files")
    @patch("ingot.workflow.task_memory._identify_patterns_in_changes")
    @patch("ingot.workflow.task_memory._extract_test_commands")
    def test_adds_memory_to_state(self, mock_extract, mock_identify, mock_get_files):
        mock_get_files.return_value = ["file1.py"]
        mock_identify.return_value = []
        mock_extract.return_value = []

        task = Task(name="Test task")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        capture_task_memory(task, state)

        assert len(state.task_memories) == 1
        assert state.task_memories[0].task_name == "Test task"


class TestFindRelatedTaskMemories:
    def test_finds_related_by_keyword_overlap(self):
        task = Task(name="Write unit tests for user authentication")
        memories = [
            TaskMemory(task_name="Implement user authentication"),
            TaskMemory(task_name="Add database schema"),
            TaskMemory(task_name="Write integration tests for authentication"),
        ]

        related = find_related_task_memories(task, memories)

        assert len(related) == 2
        task_names = [m.task_name for m in related]
        assert "Implement user authentication" in task_names
        assert "Write integration tests for authentication" in task_names

    def test_requires_minimum_keyword_overlap(self):
        task = Task(name="Write tests for user module")
        memories = [
            TaskMemory(task_name="Write documentation"),  # Only 1 keyword: "write"
            TaskMemory(task_name="Write tests for auth"),  # 2 keywords: "write", "tests"
        ]

        related = find_related_task_memories(task, memories)

        assert len(related) == 1
        assert related[0].task_name == "Write tests for auth"

    def test_returns_empty_for_no_memories(self):
        task = Task(name="Test task")

        related = find_related_task_memories(task, [])

        assert related == []

    def test_case_insensitive_matching(self):
        task = Task(name="Write Unit Tests")
        memories = [
            TaskMemory(task_name="write unit tests for API"),
        ]

        related = find_related_task_memories(task, memories)

        assert len(related) == 1


class TestBuildPatternContext:
    def test_returns_empty_for_no_memories(self):
        task = Task(name="Test task")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        context = build_pattern_context(task, state)

        assert context == ""

    def test_returns_general_patterns_when_no_related(self):
        task = Task(name="Implement new feature")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.task_memories = [
            TaskMemory(
                task_name="Different task",
                patterns_used=["Python implementation", "Async/await pattern"],
            ),
        ]

        context = build_pattern_context(task, state)

        assert "Established Patterns" in context
        assert "Python implementation" in context
        assert "Async/await pattern" in context

    def test_returns_related_patterns(self):
        task = Task(name="Write unit tests for user authentication")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.task_memories = [
            TaskMemory(
                task_name="Implement user authentication module",
                files_modified=["src/auth.py"],
                patterns_used=["Python implementation", "Error handling"],
            ),
            TaskMemory(
                task_name="Add database schema",
                patterns_used=["Database schema/model"],
            ),
        ]

        context = build_pattern_context(task, state)

        assert "Patterns from Previous Tasks" in context
        assert "Implement user authentication module" in context
        assert "Python implementation" in context
        assert "Error handling" in context
        # Should not include unrelated task
        assert "Add database schema" not in context

    def test_formats_context_as_markdown(self):
        task = Task(name="Write tests for user module")
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.task_memories = [
            TaskMemory(
                task_name="Implement user module",
                files_modified=["src/user.py"],
                patterns_used=["Python implementation"],
                key_decisions=["Use dataclass for User model"],
            ),
        ]

        context = build_pattern_context(task, state)

        assert "## Patterns from Previous Tasks" in context
        assert "### Implement user module" in context
        assert "**Files:** src/user.py" in context
        assert "**Patterns:**" in context
        assert "- Python implementation" in context
        assert "**Key Decisions:**" in context
        assert "- Use dataclass for User model" in context
        assert "Follow these established patterns for consistency" in context
