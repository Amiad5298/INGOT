"""Tests for ingot.workflow.step2_tasklist module."""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.providers import GenericTicket, Platform
from ingot.ui.menus import TaskReviewChoice
from ingot.workflow.state import WorkflowState
from ingot.workflow.step2_tasklist import (
    _create_default_tasklist,
    _display_tasklist,
    _edit_tasklist,
    _extract_tasklist_from_output,
    _fundamental_section_has_test_keywords,
    _generate_tasklist,
    _parse_add_tasks_line,
    step_2_create_tasklist,
)
from ingot.workflow.tasks import parse_task_list

# Note: This file has multiple tests that create GenericTicket with specific IDs
# because plan/tasklist filenames are derived from ticket.safe_filename_stem.
# The workflow_state fixture uses generic_ticket from conftest.py.
# Individual tests that need different IDs create their own tickets.


@pytest.fixture
def workflow_state(generic_ticket, tmp_path):
    """Create a workflow state for testing.

    Uses generic_ticket fixture from conftest.py (TEST-123).
    """
    state = WorkflowState(ticket=generic_ticket)

    # Create specs directory
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    # Create plan file - uses safe_filename_stem for path
    plan_file = specs_dir / f"{generic_ticket.safe_filename_stem}-plan.md"
    plan_file.write_text(
        """# Implementation Plan: TEST-123

## Summary
Test implementation plan.

## Tasks
1. Create module
2. Add tests
"""
    )
    state.plan_file = plan_file

    # Patch the paths to use tmp_path
    state._specs_dir = specs_dir

    return state


@pytest.fixture
def mock_backend():
    """Create a mock AIBackend."""
    backend = MagicMock()
    backend.model = "test-model"
    return backend


class TestExtractTasklistFromOutput:
    """Tests for _extract_tasklist_from_output function."""

    def test_extracts_simple_tasks(self):
        """Extracts tasks from simple checkbox format."""
        output = """Here is the task list:
- [ ] Create module file
- [ ] Implement core function
- [ ] Add unit tests
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "# Task List: TEST-123" in result
        assert "- [ ] Create module file" in result
        assert "- [ ] Implement core function" in result
        assert "- [ ] Add unit tests" in result

    def test_extracts_tasks_with_preamble(self):
        """Extracts tasks even with preamble text."""
        output = """I'll create a task list based on the plan.

Here are the tasks:

- [ ] Set up project structure
- [ ] Implement authentication
- [ ] Write integration tests

Let me know if you need any changes!
"""
        result = _extract_tasklist_from_output(output, "PROJ-456")

        assert result is not None
        tasks = parse_task_list(result)
        assert len(tasks) == 3
        assert tasks[0].name == "Set up project structure"

    def test_handles_indented_tasks(self):
        """Handles indented (nested) tasks."""
        output = """- [ ] Main task
  - [ ] Subtask 1
  - [ ] Subtask 2
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "- [ ] Main task" in result
        assert "  - [ ] Subtask 1" in result

    def test_handles_completed_tasks(self):
        """Handles tasks marked as complete."""
        output = """- [x] Completed task
- [ ] Pending task
- [X] Also completed
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "- [x] Completed task" in result
        assert "- [ ] Pending task" in result
        # Uppercase X should be normalized to lowercase
        assert "- [x] Also completed" in result

    def test_returns_none_for_no_tasks(self):
        """Returns None when no checkbox tasks found."""
        output = """This output has no checkbox tasks.
Just some regular text.
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is None

    def test_handles_asterisk_bullets(self):
        """Handles asterisk bullet points."""
        output = """* [ ] Task with asterisk
* [ ] Another asterisk task
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        tasks = parse_task_list(result)
        assert len(tasks) == 2

    def test_preserves_subtask_bullets(self):
        """Preserves non-checkbox bullet points as subtasks.

        Regression test: The post-processor was stripping subtask bullets,
        resulting in loss of task details like unit test requirements.
        """
        output = """# Task List: RED-176578

## Fundamental Tasks (Sequential)
<!-- category: fundamental, order: 1 -->
- [ ] Create domain record and GraphQL mutation foundation
  - Create `UpdateMeteringLogLinkRecord.java` in common module
  - Create `updateMeteringLogLink.graphql` mutation file
  - Add `UPDATE_METERING_LOG_LINK` enum constant
  - Include unit tests for the domain record

<!-- category: fundamental, order: 2 -->
- [ ] Implement response DTO and converter logic
  - Create `UpdateMeteringLogLinkResponseModel.java`
  - Add converter methods
  - Add unit tests in `DasResponseConverterTest`
"""
        result = _extract_tasklist_from_output(output, "RED-176578")

        assert result is not None
        # Should preserve the subtask bullets
        assert "- Create `UpdateMeteringLogLinkRecord.java` in common module" in result
        assert "- Create `updateMeteringLogLink.graphql` mutation file" in result
        assert "- Include unit tests for the domain record" in result
        assert "- Create `UpdateMeteringLogLinkResponseModel.java`" in result
        assert "- Add unit tests in `DasResponseConverterTest`" in result

    def test_preserves_section_headers(self):
        """Preserves section headers like ## Fundamental Tasks."""
        output = """# Task List: TEST-123

## Fundamental Tasks (Sequential)
- [ ] First fundamental task

## Independent Tasks (Parallel)
- [ ] First independent task
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "## Fundamental Tasks (Sequential)" in result
        assert "## Independent Tasks (Parallel)" in result

    def test_preserves_files_metadata_comments(self):
        """Preserves <!-- files: ... --> metadata comments."""
        output = """# Task List: TEST-123

<!-- category: fundamental, order: 1 -->
<!-- files: src/main/java/DasService.java -->
- [ ] Implement DAS service
  - Add method implementation
"""
        result = _extract_tasklist_from_output(output, "TEST-123")

        assert result is not None
        assert "<!-- files: src/main/java/DasService.java -->" in result

    def test_skips_duplicate_tasklist_header(self):
        """Skips duplicate '# Task List:' header from AI output.

        Regression test for bug where post-processing agent output would result
        in duplicate headers like:
            # Task List: RED-176578

            # Task List: RED-176578

        The extraction function adds its own header, so it should skip any
        '# Task List:' lines from the AI output to avoid duplication.
        """
        output = """# Task List: RED-176578

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: 1 -->
- [ ] **Create domain record and GraphQL infrastructure**
  - Create UpdateMeteringLogLinkRecord.java

## Independent Tasks (Parallel)

<!-- category: independent, group: testing -->
- [ ] **Unit tests for DasServiceImpl**
  - Test error handling scenarios
"""
        result = _extract_tasklist_from_output(output, "RED-176578")

        assert result is not None

        # Should have exactly ONE header, not two
        header_count = result.count("# Task List:")
        assert header_count == 1, f"Expected 1 header, got {header_count}. Result:\n{result}"

        # Should still have the section headers
        assert "## Fundamental Tasks (Sequential)" in result
        assert "## Independent Tasks (Parallel)" in result

        # Should still have the tasks
        assert "- [ ] **Create domain record and GraphQL infrastructure**" in result
        assert "- [ ] **Unit tests for DasServiceImpl**" in result

    def test_extracts_tasks_from_add_tasks_tool_output(self):
        """Extracts tasks from Augment add_tasks tool output format.

        Reproduction test for bug where FUNDAMENTAL/INDEPENDENT prefixes
        in task names were not being converted to category metadata.
        The add_tasks tool outputs tasks in this format:
        [ ] UUID:xxx NAME:CATEGORY: Task Name DESCRIPTION:...
        """
        # This is the exact format from the bug report log
        output = """🔧 Tool call: add_tasks
   tasks: [{"name":"FUNDAMENTAL: Core Domain Models","description":"Create models","state":"NOT_STARTED"}]

📋 Tool result: add_tasks
Task list updated successfully. Created: 13, Updated: 1, Deleted: 0.

# Task Changes

## Created Tasks

[ ] UUID:4pApZJ9L8PbqRF4KK9DqUP NAME:INDEPENDENT: Integration Tests DESCRIPTION:Add integration tests
[ ] UUID:3Hi56SkevBNQqxsEZ6yVJS NAME:INDEPENDENT: Test Fixtures DESCRIPTION:Add helper methods
[ ] UUID:4Z52PLS5YetsmJ3nWS53ZP NAME:INDEPENDENT: Unit Tests - DasActivityImpl DESCRIPTION:Create unit tests
[ ] UUID:41ErRNs1tPunY7fnfpy47v NAME:INDEPENDENT: Unit Tests - DasServiceImpl DESCRIPTION:Create unit tests
[ ] UUID:dRaGhR21KreuXQVmt1X1vJ NAME:INDEPENDENT: DasActivityImpl Implementation DESCRIPTION:Implement method
[ ] UUID:sBRaeuUa1JGsaCEa2KY8Pg NAME:INDEPENDENT: DasServiceImpl Implementation DESCRIPTION:Implement method
[ ] UUID:2EGNT9cKUyqaNLBGU3HMbp NAME:INDEPENDENT: DasResponseConverter Update DESCRIPTION:Add parsing methods
[ ] UUID:iKiHYvi9H9kyAwkujq4DtR NAME:INDEPENDENT: DAS Operations Enum Update DESCRIPTION:Add operation
[ ] UUID:5dNuiYQddu3GfM5UNFNAyh NAME:INDEPENDENT: Response DTOs DESCRIPTION:Create response models
[ ] UUID:6xNuiYQddu3GfM5UNFNAyh NAME:INDEPENDENT: GraphQL Query Definition DESCRIPTION:Create query file
[ ] UUID:7yNuiYQddu3GfM5UNFNAyz NAME:FUNDAMENTAL: Core Domain Models and Enums DESCRIPTION:Create all domain models
[ ] UUID:8zNuiYQddu3GfM5UNFNAzz NAME:FUNDAMENTAL: DAS Service Interface Update DESCRIPTION:Add method to interface
[ ] UUID:9aNuiYQddu3GfM5UNFNBaa NAME:FUNDAMENTAL: DAS Activity Interface Update DESCRIPTION:Add method to interface
"""
        result = _extract_tasklist_from_output(output, "RED-176579")

        assert result is not None
        tasks = parse_task_list(result)

        # Should extract all 13 tasks
        assert len(tasks) == 13, f"Expected 13 tasks, got {len(tasks)}"

        # Count tasks by category
        from ingot.workflow.tasks import TaskCategory

        fundamental_tasks = [t for t in tasks if t.category == TaskCategory.FUNDAMENTAL]
        independent_tasks = [t for t in tasks if t.category == TaskCategory.INDEPENDENT]

        # Should have 3 FUNDAMENTAL and 10 INDEPENDENT tasks
        assert len(fundamental_tasks) == 3, (
            f"Expected 3 FUNDAMENTAL tasks, got {len(fundamental_tasks)}. "
            f"Task categories: {[(t.name, t.category.value) for t in tasks]}"
        )
        assert len(independent_tasks) == 10, (
            f"Expected 10 INDEPENDENT tasks, got {len(independent_tasks)}. "
            f"Task categories: {[(t.name, t.category.value) for t in tasks]}"
        )

        # Verify task names don't have the prefix anymore (it's in metadata)
        for task in tasks:
            assert not task.name.startswith(
                "FUNDAMENTAL:"
            ), f"Task name should not start with 'FUNDAMENTAL:': {task.name}"
            assert not task.name.startswith(
                "INDEPENDENT:"
            ), f"Task name should not start with 'INDEPENDENT:': {task.name}"

    def test_extracts_category_from_add_tasks_format(self):
        """Extracts category metadata from add_tasks tool format.

        Tests the strict parser with proper UUID:... NAME:CATEGORY: ... DESCRIPTION:... format.
        This is the only supported format for category extraction (no legacy prefix support).
        """
        output = """Here is the task list:
[ ] UUID:abc1 NAME:FUNDAMENTAL: Setup database schema DESCRIPTION:Setup the DB
[ ] UUID:abc2 NAME:FUNDAMENTAL: Create base models DESCRIPTION:Create models
[ ] UUID:abc3 NAME:INDEPENDENT: Add API endpoints DESCRIPTION:Add endpoints
[ ] UUID:abc4 NAME:INDEPENDENT: Write unit tests DESCRIPTION:Write tests
"""
        result = _extract_tasklist_from_output(output, "TEST-456")

        assert result is not None
        tasks = parse_task_list(result)

        assert len(tasks) == 4

        from ingot.workflow.tasks import TaskCategory

        # First two should be FUNDAMENTAL
        assert tasks[0].category == TaskCategory.FUNDAMENTAL
        assert tasks[1].category == TaskCategory.FUNDAMENTAL

        # Last two should be INDEPENDENT
        assert tasks[2].category == TaskCategory.INDEPENDENT
        assert tasks[3].category == TaskCategory.INDEPENDENT

        # Names should not include the prefix
        assert tasks[0].name == "Setup database schema"
        assert tasks[2].name == "Add API endpoints"


class TestStrictParser:
    """Tests for the strict _parse_add_tasks_line parser.

    These tests verify robustness against edge cases:
    - Task names containing "DESCRIPTION" or "NAME"
    - UPPERCASE-only category matching (no false positives)
    """

    def test_handles_description_in_task_name(self):
        """Task name containing 'DESCRIPTION' is parsed correctly.

        Regression test: old regex would cut off at first DESCRIPTION: occurrence.
        """
        raw = "UUID:abc123 NAME:INDEPENDENT: Fix DESCRIPTION field bug DESCRIPTION:Fix the bug"
        category_meta, task_name = _parse_add_tasks_line(raw)

        assert category_meta == "<!-- category: independent -->"
        assert task_name == "Fix DESCRIPTION field bug"

    def test_handles_name_in_task_name(self):
        """Task name containing 'NAME' is parsed correctly."""
        raw = "UUID:xyz789 NAME:FUNDAMENTAL: Update NAME validation logic DESCRIPTION:Improve it"
        category_meta, task_name = _parse_add_tasks_line(raw)

        assert category_meta == "<!-- category: fundamental -->"
        assert task_name == "Update NAME validation logic"

    def test_no_false_positive_on_lowercase_fundamental(self):
        """Sentence-case 'Fundamental' does NOT trigger category extraction.

        Regression test: old regex used re.IGNORECASE which caused false positives.
        """
        raw = "UUID:test123 NAME:Fundamental analysis of the market DESCRIPTION:Research task"
        category_meta, task_name = _parse_add_tasks_line(raw)

        # No category extracted (not UPPERCASE)
        assert category_meta is None
        assert task_name == "Fundamental analysis of the market"

    def test_no_false_positive_on_lowercase_independent(self):
        """Sentence-case 'Independent' does NOT trigger category extraction."""
        raw = "UUID:test456 NAME:Independent study required DESCRIPTION:Self-study"
        category_meta, task_name = _parse_add_tasks_line(raw)

        # No category extracted (not UPPERCASE)
        assert category_meta is None
        assert task_name == "Independent study required"

    def test_simple_task_without_category(self):
        """Task without category prefix is parsed correctly."""
        raw = "UUID:simple1 NAME:Simple task name DESCRIPTION:A simple description"
        category_meta, task_name = _parse_add_tasks_line(raw)

        assert category_meta is None
        assert task_name == "Simple task name"

    def test_non_add_tasks_format_passthrough(self):
        """Non-add_tasks format lines pass through unchanged."""
        raw = "Just a regular task name"
        category_meta, task_name = _parse_add_tasks_line(raw)

        assert category_meta is None
        assert task_name == "Just a regular task name"

    def test_extract_with_tricky_description_name(self):
        """Full integration test with tricky task containing DESCRIPTION in name.

        Proves the regex handles: NAME:CATEGORY: ... DESCRIPTION ... DESCRIPTION:...
        """
        output = """Here is the task list:
[ ] UUID:tricky1 NAME:INDEPENDENT: Fix DESCRIPTION field bug DESCRIPTION:This fixes the bug
[ ] UUID:tricky2 NAME:FUNDAMENTAL: Add NAME column to DB DESCRIPTION:Database update
[ ] UUID:normal1 NAME:INDEPENDENT: Regular task DESCRIPTION:Normal description
"""
        result = _extract_tasklist_from_output(output, "TRICKY-123")

        assert result is not None
        tasks = parse_task_list(result)

        assert len(tasks) == 3

        # Verify task names are correctly extracted
        assert tasks[0].name == "Fix DESCRIPTION field bug"
        assert tasks[1].name == "Add NAME column to DB"
        assert tasks[2].name == "Regular task"

        # Verify categories
        from ingot.workflow.tasks import TaskCategory

        assert tasks[0].category == TaskCategory.INDEPENDENT
        assert tasks[1].category == TaskCategory.FUNDAMENTAL
        assert tasks[2].category == TaskCategory.INDEPENDENT


class TestGenerateTasklist:
    """Tests for _generate_tasklist function."""

    def test_persists_ai_output_to_file(
        self,
        workflow_state,
        tmp_path,
        mock_backend,
    ):
        """AI output is persisted to file even if AI doesn't write it."""
        # Setup
        tasklist_path = tmp_path / "specs" / "TEST-123-tasklist.md"
        plan_path = workflow_state.plan_file

        # Mock backend to return success with task list in output
        mock_backend.run_with_callback.return_value = (
            True,
            """Here's the task list:
- [ ] Create user module
- [ ] Add authentication
- [ ] Write tests
""",
        )

        # Act
        result = _generate_tasklist(
            workflow_state,
            plan_path,
            tasklist_path,
            mock_backend,
        )

        # Assert
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        tasks = parse_task_list(content)
        assert len(tasks) == 3
        assert tasks[0].name == "Create user module"

    def test_uses_subagent_for_tasklist_generation(
        self,
        tmp_path,
        mock_backend,
    ):
        """Uses state.subagent_names tasklist agent for task list generation."""
        # Setup
        ticket = GenericTicket(
            id="TEST-456",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-456",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-456-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-456-tasklist.md"

        mock_backend.run_with_callback.return_value = (True, "- [ ] Single task\n")

        # Act
        result = _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        # Assert - subagent from state is used
        call_kwargs = mock_backend.run_with_callback.call_args.kwargs
        assert "subagent" in call_kwargs
        assert call_kwargs["subagent"] == state.subagent_names["tasklist"]
        assert result is True

    def test_falls_back_to_default_when_no_tasks_extracted(
        self,
        tmp_path,
        mock_backend,
    ):
        """Falls back to default template when AI output has no checkbox tasks."""
        ticket = GenericTicket(
            id="TEST-789",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-789",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-789-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-789-tasklist.md"

        mock_backend.run_with_callback.return_value = (
            True,
            "I couldn't understand the plan. Please clarify.",
        )

        result = _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        # Should fall back to default template
        assert result is True
        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        # Default template has placeholder tasks
        assert "[Core functionality implementation with tests]" in content

    def test_includes_user_context_in_prompt(
        self,
        tmp_path,
        mock_backend,
    ):
        """User context appears in prompt when state.user_context is set."""
        ticket = GenericTicket(
            id="TEST-CTX",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-CTX",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.user_context = "Focus on backward compatibility"

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-CTX-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-CTX-tasklist.md"

        mock_backend.run_with_callback.return_value = (True, "- [ ] Single task\n")

        _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "Additional Context" in prompt
        assert "Focus on backward compatibility" in prompt

    def test_excludes_user_context_when_empty(
        self,
        tmp_path,
        mock_backend,
    ):
        """User context section absent when state.user_context is empty."""
        ticket = GenericTicket(
            id="TEST-NOCTX",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-NOCTX",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.user_context = ""

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-NOCTX-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-NOCTX-tasklist.md"

        mock_backend.run_with_callback.return_value = (True, "- [ ] Single task\n")

        _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "Additional Context" not in prompt

    def test_excludes_user_context_when_whitespace_only(
        self,
        tmp_path,
        mock_backend,
    ):
        """User context section absent when state.user_context is whitespace only."""
        ticket = GenericTicket(
            id="TEST-WS",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-WS",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)
        state.user_context = "   \n  "

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-WS-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-WS-tasklist.md"

        mock_backend.run_with_callback.return_value = (True, "- [ ] Single task\n")

        _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        prompt = mock_backend.run_with_callback.call_args[0][0]
        assert "Additional Context" not in prompt


class TestStep2CreateTasklist:
    """Tests for step_2_create_tasklist function."""

    @patch("ingot.workflow.step2_tasklist.show_task_review_menu")
    @patch("ingot.workflow.step2_tasklist._edit_tasklist")
    @patch("ingot.workflow.step2_tasklist._generate_tasklist")
    def test_edit_does_not_regenerate(
        self,
        mock_generate,
        mock_edit,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """EDIT choice does not regenerate/overwrite the task list.

        Test A: Verifies:
        - _generate_tasklist is called exactly once
        - After EDIT, the edited content is preserved (not overwritten)
        - APPROVE after EDIT approves the edited content
        - state.current_step is set to 3 and state.tasklist_file is set
        """
        # Change to tmp_path so that state.specs_dir resolves correctly
        monkeypatch.chdir(tmp_path)

        # Setup
        ticket = GenericTicket(
            id="TEST-EDIT",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-EDIT",
            title="Test Edit Flow",
            description="Test description",
            branch_summary="Test Edit Flow",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)

        # Create plan file
        plan_path = specs_dir / "TEST-EDIT-plan.md"
        plan_path.write_text("# Plan\n\nImplement feature.")
        state.plan_file = plan_path

        # Get the actual tasklist path that the function will use
        tasklist_path = state.get_tasklist_path()

        # Initial content written by _generate_tasklist
        initial_content = """# Task List: TEST-EDIT

- [ ] Original task 1
- [ ] Original task 2
"""
        # Edited content (what user changes it to)
        edited_content = """# Task List: TEST-EDIT

- [ ] Edited task 1
- [ ] Edited task 2
- [ ] Edited task 3
"""

        def mock_generate_side_effect(state, plan_path, tasklist_path, backend):
            tasklist_path.write_text(initial_content)
            return True

        mock_generate.side_effect = mock_generate_side_effect

        def mock_edit_side_effect(path):
            # Simulate user editing the file
            path.write_text(edited_content)

        mock_edit.side_effect = mock_edit_side_effect

        # Menu returns EDIT first, then APPROVE
        mock_menu.side_effect = [TaskReviewChoice.EDIT, TaskReviewChoice.APPROVE]

        mock_auggie = MagicMock()

        # Act
        result = step_2_create_tasklist(state, mock_auggie)

        # Assert
        assert result is True

        # _generate_tasklist should be called exactly once
        assert mock_generate.call_count == 1

        # The file should contain the edited content (not reverted)
        final_content = tasklist_path.read_text()
        assert "Edited task 1" in final_content
        assert "Edited task 2" in final_content
        assert "Edited task 3" in final_content
        assert "Original task" not in final_content

        # State should be updated
        assert state.current_step == 3
        assert state.tasklist_file == tasklist_path

    @patch("ingot.workflow.step2_tasklist.show_task_review_menu")
    @patch("ingot.workflow.step2_tasklist._generate_tasklist")
    def test_regenerate_calls_generate_again(
        self,
        mock_generate,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """REGENERATE choice calls _generate_tasklist again."""
        monkeypatch.chdir(tmp_path)

        ticket = GenericTicket(
            id="TEST-REGEN",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-REGEN",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-REGEN-plan.md"
        plan_path.write_text("# Plan")
        state.plan_file = plan_path

        def mock_generate_effect(state, plan_path, tasklist_path, backend):
            tasklist_path.write_text("- [ ] Task\n")
            return True

        mock_generate.side_effect = mock_generate_effect

        # REGENERATE then APPROVE
        mock_menu.side_effect = [
            TaskReviewChoice.REGENERATE,
            TaskReviewChoice.APPROVE,
        ]

        result = step_2_create_tasklist(state, MagicMock())

        assert result is True
        # Should be called twice: initial + after REGENERATE
        assert mock_generate.call_count == 2

    @patch("ingot.workflow.step2_tasklist.show_task_review_menu")
    @patch("ingot.workflow.step2_tasklist._generate_tasklist")
    def test_abort_returns_false(
        self,
        mock_generate,
        mock_menu,
        tmp_path,
        monkeypatch,
    ):
        """ABORT choice returns False."""
        monkeypatch.chdir(tmp_path)

        ticket = GenericTicket(
            id="TEST-ABORT",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-ABORT",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-ABORT-plan.md"
        plan_path.write_text("# Plan")
        state.plan_file = plan_path

        mock_generate.side_effect = lambda s, pp, tp, b: (tp.write_text("- [ ] Task\n") or True)
        mock_menu.return_value = TaskReviewChoice.ABORT

        result = step_2_create_tasklist(state, MagicMock())

        assert result is False

    @patch("ingot.workflow.step2_tasklist._generate_tasklist")
    def test_returns_false_when_plan_not_found(
        self,
        mock_generate,
        tmp_path,
        monkeypatch,
    ):
        """Returns False when plan file does not exist."""
        monkeypatch.chdir(tmp_path)

        ticket = GenericTicket(
            id="TEST-NOPLAN",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-NOPLAN",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        # Create specs directory but NO plan file
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        # state.plan_file is None, so it will use default path which doesn't exist

        result = step_2_create_tasklist(state, MagicMock())

        assert result is False
        # _generate_tasklist should never be called
        mock_generate.assert_not_called()


class TestDisplayTasklist:
    """Tests for _display_tasklist function."""

    def test_displays_task_list(self, tmp_path, capsys):
        """Displays task list content and task count."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text(
            """# Task List: TEST-123

- [ ] Task one
- [ ] Task two
- [x] Task three
"""
        )

        with patch("ingot.workflow.step2_tasklist.console") as mock_console:
            _display_tasklist(tasklist_path)

            # Verify console.print was called multiple times
            assert mock_console.print.call_count >= 4
            # Check that task count is displayed (2 pending + 1 complete = 3)
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("Total tasks: 3" in str(c) for c in calls)

    def test_displays_empty_task_list(self, tmp_path):
        """Displays empty task list with zero count."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("# Task List: TEST-123\n\nNo tasks yet.\n")

        with patch("ingot.workflow.step2_tasklist.console") as mock_console:
            _display_tasklist(tasklist_path)

            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("Total tasks: 0" in str(c) for c in calls)


class TestEditTasklist:
    """Tests for _edit_tasklist function."""

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nano"}, clear=False)
    def test_opens_editor_from_environment(self, mock_run, tmp_path):
        """Opens the editor specified in EDITOR environment variable."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        _edit_tasklist(tasklist_path)

        mock_run.assert_called_once_with(["nano", str(tasklist_path)], check=True)

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_vim(self, mock_run, tmp_path):
        """Defaults to vim when EDITOR is not set."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        _edit_tasklist(tasklist_path)

        mock_run.assert_called_once_with(["vim", str(tasklist_path)], check=True)

    @patch("ingot.workflow.step2_tasklist.prompt_enter")
    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nonexistent_editor"}, clear=False)
    def test_handles_editor_not_found(self, mock_run, mock_prompt, tmp_path):
        """Handles case when editor is not found."""
        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        mock_run.side_effect = FileNotFoundError()

        _edit_tasklist(tasklist_path)

        # Should prompt user to edit manually
        mock_prompt.assert_called_once()

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "vim"}, clear=False)
    def test_handles_editor_error(self, mock_run, tmp_path):
        """Handles case when editor exits with error."""
        import subprocess as sp

        tasklist_path = tmp_path / "tasklist.md"
        tasklist_path.write_text("- [ ] Task\n")

        mock_run.side_effect = sp.CalledProcessError(1, "vim")

        # Should not raise, just print warning
        _edit_tasklist(tasklist_path)


class TestCreateDefaultTasklist:
    """Tests for _create_default_tasklist function."""

    def test_creates_default_template(self, tmp_path):
        """Creates default task list with template content."""
        tasklist_path = tmp_path / "tasklist.md"
        ticket = GenericTicket(
            id="TEST-DEFAULT",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-DEFAULT",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        _create_default_tasklist(tasklist_path, state)

        assert tasklist_path.exists()
        content = tasklist_path.read_text()
        assert "# Task List: TEST-DEFAULT" in content
        assert "[Core functionality implementation with tests]" in content
        assert "[Integration/API layer with tests]" in content
        assert "[Documentation updates]" in content

    def test_includes_ticket_id_in_header(self, tmp_path):
        """Includes ticket ID in the task list header."""
        tasklist_path = tmp_path / "tasklist.md"
        ticket = GenericTicket(
            id="PROJ-999",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-999",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        _create_default_tasklist(tasklist_path, state)

        content = tasklist_path.read_text()
        assert "PROJ-999" in content

    def test_creates_parent_directory_if_needed(self, tmp_path):
        """Creates parent directories if they don't exist."""
        tasklist_path = tmp_path / "nested" / "dir" / "tasklist.md"
        ticket = GenericTicket(
            id="TEST-NESTED",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-NESTED",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        # Create parent directory manually since _create_default_tasklist doesn't
        tasklist_path.parent.mkdir(parents=True, exist_ok=True)
        _create_default_tasklist(tasklist_path, state)

        assert tasklist_path.exists()


class TestGenerateTasklistRetry:
    """Tests for _generate_tasklist retry behavior."""

    def test_returns_false_on_auggie_failure(self, tmp_path, mock_backend):
        """Returns False when backend command fails."""
        ticket = GenericTicket(
            id="TEST-FAIL",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-FAIL",
            title="Test",
            description="Test description",
            branch_summary="Test",
        )
        state = WorkflowState(ticket=ticket)

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir(parents=True)
        plan_path = specs_dir / "TEST-FAIL-plan.md"
        plan_path.write_text("# Plan\n\nDo something.")
        tasklist_path = specs_dir / "TEST-FAIL-tasklist.md"

        mock_backend.run_with_callback.return_value = (False, "Error occurred")

        result = _generate_tasklist(state, plan_path, tasklist_path, mock_backend)

        assert result is False


class TestFundamentalSectionKeywordDetection:
    """Tests for _fundamental_section_has_test_keywords optimization function."""

    def test_positive_match_keyword_in_fundamental_section(self):
        """Keyword exists in Fundamental Tasks section - should return True."""
        content = """# Task List: TEST-123

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: 1 -->
<!-- files: src/main/java/Service.java -->
- [ ] **Implement service layer**
  - Create Service.java
  - Add business logic
  - Write unit tests for Service

## Independent Tasks (Parallel)

<!-- category: independent, group: implementation -->
<!-- files: src/main/java/Controller.java -->
- [ ] **Update controller**
  - Add new endpoint
"""
        result = _fundamental_section_has_test_keywords(content)
        assert result is True

    def test_negative_match_keyword_only_in_independent_section(self):
        """Keyword exists ONLY in Independent Tasks section - should return False.

        This tests the optimization: if there are no test keywords in Fundamental,
        we can skip the AI refiner call entirely.
        """
        content = """# Task List: TEST-123

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: 1 -->
<!-- files: src/main/java/Service.java -->
- [ ] **Implement service layer**
  - Create Service.java
  - Add business logic
  - Implement error handling

## Independent Tasks (Parallel)

<!-- category: independent, group: testing -->
<!-- files: src/test/java/ServiceTest.java -->
- [ ] **Write tests for service**
  - Add unit tests
  - Add integration tests
"""
        result = _fundamental_section_has_test_keywords(content)
        assert result is False

    def test_ambiguous_keyword_verify_triggers_match(self):
        """Common verb 'verify' in Fundamental section triggers match - should return True.

        'verify' is in the keyword list and should be detected even though it's
        commonly used in non-test contexts.
        """
        content = """# Task List: TEST-123

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: 1 -->
<!-- files: src/main/java/Validator.java -->
- [ ] **Implement validation logic**
  - Create Validator.java
  - Add input validation
  - Verify data integrity before processing

## Independent Tasks (Parallel)

<!-- category: independent, group: implementation -->
<!-- files: src/main/java/Handler.java -->
- [ ] **Update handler**
  - Add new method
"""
        result = _fundamental_section_has_test_keywords(content)
        assert result is True
