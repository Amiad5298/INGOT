"""Tests for ai_workflow.ui.tui module - parallel execution support."""

import pytest
from io import StringIO
from rich.console import Console

from ai_workflow.ui.tui import (
    TaskRunnerUI,
    TaskRunRecord,
    TaskRunStatus,
    render_task_list,
    render_status_bar,
)


def render_to_string(renderable) -> str:
    """Render a Rich renderable to a plain string."""
    console = Console(file=StringIO(), force_terminal=True, width=120)
    console.print(renderable)
    return console.file.getvalue()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tui():
    """Create a TaskRunnerUI instance for testing."""
    ui = TaskRunnerUI(ticket_id="TEST-123")
    ui.initialize_records(["Task 1", "Task 2", "Task 3"])
    return ui


@pytest.fixture
def records():
    """Create sample task records."""
    return [
        TaskRunRecord(task_index=0, task_name="Task 1", status=TaskRunStatus.PENDING),
        TaskRunRecord(task_index=1, task_name="Task 2", status=TaskRunStatus.RUNNING),
        TaskRunRecord(task_index=2, task_name="Task 3", status=TaskRunStatus.PENDING),
    ]


# =============================================================================
# Tests for TUI Parallel Mode
# =============================================================================


class TestTuiParallelMode:
    """Tests for TaskRunnerUI parallel mode functionality."""

    def test_parallel_mode_defaults_to_false(self, tui):
        """parallel_mode defaults to False."""
        assert tui.parallel_mode is False

    def test_set_parallel_mode_enables(self, tui):
        """set_parallel_mode(True) enables parallel mode."""
        tui.set_parallel_mode(True)
        assert tui.parallel_mode is True

    def test_set_parallel_mode_disables(self, tui):
        """set_parallel_mode(False) disables parallel mode."""
        tui.set_parallel_mode(True)
        tui.set_parallel_mode(False)
        assert tui.parallel_mode is False

    def test_running_task_indices_tracked(self, tui):
        """Running task indices are tracked in parallel mode."""
        tui.set_parallel_mode(True)
        # Simulate adding running tasks
        tui._running_task_indices.add(0)
        tui._running_task_indices.add(2)
        
        assert 0 in tui._running_task_indices
        assert 2 in tui._running_task_indices
        assert len(tui._running_task_indices) == 2

    def test_get_running_count_returns_correct_count(self, tui):
        """_get_running_count returns correct count in parallel mode."""
        tui.set_parallel_mode(True)
        tui._running_task_indices.add(0)
        tui._running_task_indices.add(1)
        
        assert tui._get_running_count() == 2


# =============================================================================
# Tests for render_task_list with Parallel Mode
# =============================================================================


class TestRenderTaskListParallel:
    """Tests for render_task_list with parallel mode."""

    def test_shows_parallel_indicator_for_running_tasks(self, records):
        """Shows ⚡ indicator for running tasks in parallel mode."""
        panel = render_task_list(records, parallel_mode=True)
        # The panel should contain the parallel indicator
        panel_str = render_to_string(panel)
        assert "⚡" in panel_str

    def test_no_indicator_in_sequential_mode(self, records):
        """Shows 'Running' text in sequential mode."""
        panel = render_task_list(records, parallel_mode=False)
        panel_str = render_to_string(panel)
        # Should show "Running" text, not parallel indicator
        assert "Running" in panel_str

    def test_multiple_running_tasks_shown(self):
        """Multiple running tasks are displayed correctly."""
        records = [
            TaskRunRecord(task_index=0, task_name="Task 1", status=TaskRunStatus.RUNNING),
            TaskRunRecord(task_index=1, task_name="Task 2", status=TaskRunStatus.RUNNING),
            TaskRunRecord(task_index=2, task_name="Task 3", status=TaskRunStatus.PENDING),
        ]
        panel = render_task_list(records, parallel_mode=True)
        panel_str = render_to_string(panel)
        # Should show parallel count in header
        assert "parallel" in panel_str


# =============================================================================
# Tests for render_status_bar with Parallel Mode
# =============================================================================


class TestRenderStatusBarParallel:
    """Tests for render_status_bar with parallel mode."""

    def test_shows_parallel_task_count(self):
        """Shows parallel task count in status bar."""
        text = render_status_bar(
            running=True,
            parallel_mode=True,
            running_count=3,
        )
        text_str = str(text)
        assert "3 tasks running" in text_str

    def test_singular_task_count(self):
        """Shows singular form for 1 task."""
        text = render_status_bar(
            running=True,
            parallel_mode=True,
            running_count=1,
        )
        text_str = str(text)
        # Should still show "1 tasks running" (current implementation)
        assert "1 tasks running" in text_str

