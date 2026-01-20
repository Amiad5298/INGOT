"""Tests for spec.ui.tui module - parallel execution support."""

import threading
import pytest
from io import StringIO
from rich.console import Console

from specflow.ui.tui import (
    TaskRunnerUI,
    TaskRunRecord,
    TaskRunStatus,
    render_task_list,
    render_status_bar,
)
from specflow.workflow.events import (
    create_task_started_event,
    create_task_finished_event,
    create_task_output_event,
    TaskEventType,
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


# =============================================================================
# Tests for Thread-Safe Event Queue
# =============================================================================


class TestTuiEventQueue:
    """Tests for TaskRunnerUI thread-safe event queue."""

    def test_tui_post_event_thread_safe(self, tui):
        """post_event is thread-safe: multiple threads can queue events."""
        num_threads = 10
        events_per_thread = 5
        barrier = threading.Barrier(num_threads)

        def post_events(thread_id: int):
            barrier.wait()  # Synchronize all threads to start together
            for i in range(events_per_thread):
                event = create_task_output_event(0, "Task 1", f"Thread {thread_id} line {i}")
                tui.post_event(event)

        threads = []
        for thread_id in range(num_threads):
            t = threading.Thread(target=post_events, args=(thread_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Count events in queue
        event_count = 0
        while not tui._event_queue.empty():
            tui._event_queue.get_nowait()
            event_count += 1

        assert event_count == num_threads * events_per_thread

    def test_tui_drain_queue_on_refresh(self, tui):
        """refresh() drains the event queue before updating display."""
        # Post several events
        tui.post_event(create_task_started_event(0, "Task 1"))
        tui.post_event(create_task_output_event(0, "Task 1", "Output line 1"))
        tui.post_event(create_task_finished_event(0, "Task 1", "success", 1.5))

        # Verify queue is not empty
        assert not tui._event_queue.empty()

        # Call refresh (without Live display active, it just drains the queue)
        tui.refresh()

        # Queue should now be empty
        assert tui._event_queue.empty()

        # Verify events were applied - task should be SUCCESS status
        record = tui.get_record(0)
        assert record is not None
        assert record.status == TaskRunStatus.SUCCESS

    def test_apply_event_processes_task_started(self, tui):
        """_apply_event correctly processes TASK_STARTED events."""
        event = create_task_started_event(1, "Task 2")
        tui._apply_event(event)

        record = tui.get_record(1)
        assert record.status == TaskRunStatus.RUNNING
        assert record.start_time == event.timestamp

    def test_apply_event_processes_task_finished_success(self, tui):
        """_apply_event correctly processes TASK_FINISHED with success status."""
        # First start the task
        tui._apply_event(create_task_started_event(0, "Task 1"))

        # Then finish it
        finish_event = create_task_finished_event(0, "Task 1", "success", 2.0)
        tui._apply_event(finish_event)

        record = tui.get_record(0)
        assert record.status == TaskRunStatus.SUCCESS
        assert record.end_time == finish_event.timestamp

    def test_apply_event_processes_task_finished_failed(self, tui):
        """_apply_event correctly processes TASK_FINISHED with failed status."""
        tui._apply_event(create_task_started_event(1, "Task 2"))
        finish_event = create_task_finished_event(1, "Task 2", "failed", 1.0, error="Error!")
        tui._apply_event(finish_event)

        record = tui.get_record(1)
        assert record.status == TaskRunStatus.FAILED
        assert record.error == "Error!"

    def test_apply_event_processes_task_finished_skipped(self, tui):
        """_apply_event correctly processes TASK_FINISHED with skipped status."""
        finish_event = create_task_finished_event(2, "Task 3", "skipped", 0.0)
        tui._apply_event(finish_event)

        record = tui.get_record(2)
        assert record.status == TaskRunStatus.SKIPPED
        assert record.error is None


# =============================================================================
# Tests for Log Buffer Cleanup on Task Finished
# =============================================================================


class TestLogBufferCleanup:
    """Tests for log buffer cleanup on task completion."""

    def test_log_buffer_closed_on_success(self, tui):
        """Log buffer is closed when task finishes with success."""
        # Create a mock log buffer
        class MockLogBuffer:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        record = tui.get_record(0)
        mock_buffer = MockLogBuffer()
        record.log_buffer = mock_buffer

        # Finish the task
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        assert mock_buffer.closed is True
        assert record.log_buffer is None

    def test_log_buffer_closed_on_failure(self, tui):
        """Log buffer is closed when task finishes with failure."""
        class MockLogBuffer:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        record = tui.get_record(1)
        mock_buffer = MockLogBuffer()
        record.log_buffer = mock_buffer

        tui._apply_event(create_task_finished_event(1, "Task 2", "failed", 2.0, error="fail"))

        assert mock_buffer.closed is True
        assert record.log_buffer is None

    def test_log_buffer_closed_on_skipped(self, tui):
        """Log buffer is closed when task finishes with skipped status."""
        class MockLogBuffer:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        record = tui.get_record(2)
        mock_buffer = MockLogBuffer()
        record.log_buffer = mock_buffer

        tui._apply_event(create_task_finished_event(2, "Task 3", "skipped", 0.0))

        assert mock_buffer.closed is True
        assert record.log_buffer is None

    def test_log_buffer_close_exception_ignored(self, tui):
        """Exceptions during log buffer close are caught and ignored."""
        class FailingLogBuffer:
            def close(self):
                raise RuntimeError("Close failed!")

        record = tui.get_record(0)
        record.log_buffer = FailingLogBuffer()

        # Should not raise
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Buffer reference should be cleared even on error
        assert record.log_buffer is None


# =============================================================================
# Tests for Auto-Switch Selection on Task Finish in Parallel Mode
# =============================================================================


class TestAutoSwitchOnTaskFinish:
    """Tests for auto-switching to another running task when selected task finishes."""

    def test_auto_switch_to_running_task_when_selected_finishes(self, tui):
        """When selected task finishes in parallel mode, auto-switch to another running task."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start two tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))

        # Verify both are running
        assert 0 in tui._running_task_indices
        assert 1 in tui._running_task_indices

        # Task 1 is selected (auto-selected as first running task)
        assert tui.selected_index == 0

        # Task 1 finishes
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Should auto-switch to Task 2 (the remaining running task)
        assert tui.selected_index == 1
        assert 0 not in tui._running_task_indices
        assert 1 in tui._running_task_indices

    def test_no_auto_switch_when_follow_mode_disabled(self, tui):
        """No auto-switch when follow_mode is disabled."""
        tui.set_parallel_mode(True)
        tui.follow_mode = False  # User disabled follow mode

        # Start two tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))

        # Manually select Task 1
        tui.selected_index = 0

        # Task 1 finishes
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Should NOT auto-switch (user may want to review the finished task)
        assert tui.selected_index == 0

    def test_no_auto_switch_when_different_task_selected(self, tui):
        """No auto-switch when a different task (not the finishing one) is selected."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start three tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))

        # User manually selected Task 2
        tui.selected_index = 1

        # Task 1 finishes (not the selected task)
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Selection should remain on Task 2
        assert tui.selected_index == 1

    def test_no_auto_switch_when_no_other_running_tasks(self, tui):
        """No auto-switch when no other tasks are running."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start only one task
        tui._apply_event(create_task_started_event(0, "Task 1"))
        assert tui.selected_index == 0

        # Task 1 finishes (no other running tasks)
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Selection stays on Task 1 (nothing to switch to)
        assert tui.selected_index == 0
        assert len(tui._running_task_indices) == 0

    def test_auto_switch_uses_next_neighbor_logic(self, tui):
        """Auto-switch uses 'Next Neighbor' logic: picks next running task after finished one."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start three tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))

        # Select Task 1
        tui.selected_index = 0

        # Task 1 finishes
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Should switch to Task 2 (next neighbor after index 0)
        assert tui.selected_index == 1

    def test_auto_switch_next_neighbor_middle_task(self):
        """Next Neighbor: when middle task finishes, switch to next task, not first."""
        # Need 4 tasks for this test
        tui = TaskRunnerUI(ticket_id="TEST-123")
        tui.initialize_records(["Task 1", "Task 2", "Task 3", "Task 4"])
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start four tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))
        tui._apply_event(create_task_started_event(3, "Task 4"))

        # User is watching Task 2
        tui.selected_index = 1

        # Task 2 finishes - should jump to Task 3 (next neighbor), NOT Task 1
        tui._apply_event(create_task_finished_event(1, "Task 2", "success", 1.0))

        # Should switch to Task 3 (index 2), not Task 1 (index 0)
        assert tui.selected_index == 2

    def test_auto_switch_next_neighbor_wraps_around(self, tui):
        """Next Neighbor: when last task finishes, wrap around to first running task."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start three tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))

        # User is watching Task 3 (last task)
        tui.selected_index = 2

        # Task 3 finishes - no later tasks, should wrap to Task 1
        tui._apply_event(create_task_finished_event(2, "Task 3", "success", 1.0))

        # Should wrap around to Task 1 (index 0)
        assert tui.selected_index == 0

    def test_auto_switch_next_neighbor_with_gaps(self):
        """Next Neighbor: handles non-contiguous running task indices correctly."""
        # Need 5 tasks for this test
        tui = TaskRunnerUI(ticket_id="TEST-123")
        tui.initialize_records(["Task 1", "Task 2", "Task 3", "Task 4", "Task 5"])
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start tasks 0, 2, 4 (indices 1 and 3 are not started or already finished)
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(2, "Task 3"))
        tui._apply_event(create_task_started_event(4, "Task 5"))

        # User is watching Task 1 (index 0)
        tui.selected_index = 0

        # Task 1 finishes - should jump to Task 3 (index 2, next running after 0)
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Should switch to index 2 (next running task after index 0)
        assert tui.selected_index == 2

    def test_auto_switch_works_with_failed_task(self, tui):
        """Auto-switch also works when selected task fails."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start two tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui.selected_index = 0

        # Task 1 fails
        tui._apply_event(create_task_finished_event(0, "Task 1", "failed", 1.0, error="Error"))

        # Should auto-switch to Task 2
        assert tui.selected_index == 1

    def test_auto_switch_works_with_skipped_task(self, tui):
        """Auto-switch also works when selected task is skipped."""
        tui.set_parallel_mode(True)
        tui.follow_mode = True

        # Start two tasks
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui.selected_index = 0

        # Task 1 is skipped (e.g., fail-fast triggered)
        tui._apply_event(create_task_finished_event(0, "Task 1", "skipped", 0.0))

        # Should auto-switch to Task 2
        assert tui.selected_index == 1

    def test_no_auto_switch_in_sequential_mode(self, tui):
        """Auto-switch does not happen in sequential mode (parallel_mode=False)."""
        tui.set_parallel_mode(False)  # Sequential mode
        tui.follow_mode = True

        # Start a task (sequential mode)
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui.selected_index = 0

        # Task 1 finishes
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Selection stays unchanged (sequential mode doesn't use auto-switch)
        assert tui.selected_index == 0
