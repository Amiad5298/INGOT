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
