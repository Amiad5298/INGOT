"""Tests for ingot.ui.tui module - parallel execution support."""

import threading
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from ingot.ui.keyboard import _CHAR_MAPPINGS, _ESCAPE_SEQUENCES, Key, KeyboardReader
from ingot.ui.tui import (
    TaskRunnerUI,
    TaskRunRecord,
    TaskRunStatus,
    render_status_bar,
    render_task_list,
)
from ingot.workflow.events import (
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
)


def render_to_string(renderable) -> str:
    """Render a Rich renderable to a plain string."""
    console = Console(file=StringIO(), force_terminal=True, width=120)
    console.print(renderable)
    return console.file.getvalue()


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


class TestTuiParallelMode:
    def test_parallel_mode_defaults_to_false(self, tui):
        assert tui.parallel_mode is False

    def test_set_parallel_mode_enables(self, tui):
        tui.set_parallel_mode(True)
        assert tui.parallel_mode is True

    def test_set_parallel_mode_disables(self, tui):
        tui.set_parallel_mode(True)
        tui.set_parallel_mode(False)
        assert tui.parallel_mode is False

    def test_running_task_indices_tracked(self, tui):
        tui.set_parallel_mode(True)
        # Simulate adding running tasks
        tui._running_task_indices.add(0)
        tui._running_task_indices.add(2)

        assert 0 in tui._running_task_indices
        assert 2 in tui._running_task_indices
        assert len(tui._running_task_indices) == 2

    def test_get_running_count_returns_correct_count(self, tui):
        tui.set_parallel_mode(True)
        tui._running_task_indices.add(0)
        tui._running_task_indices.add(1)

        assert tui._get_running_count() == 2


class TestRenderTaskListParallel:
    def test_shows_parallel_indicator_for_running_tasks(self, records):
        panel = render_task_list(records, parallel_mode=True)
        # The panel should contain the parallel indicator
        panel_str = render_to_string(panel)
        assert "⚡" in panel_str

    def test_no_indicator_in_sequential_mode(self, records):
        panel = render_task_list(records, parallel_mode=False)
        panel_str = render_to_string(panel)
        # Should show "Running" text, not parallel indicator
        assert "Running" in panel_str

    def test_multiple_running_tasks_shown(self):
        records = [
            TaskRunRecord(task_index=0, task_name="Task 1", status=TaskRunStatus.RUNNING),
            TaskRunRecord(task_index=1, task_name="Task 2", status=TaskRunStatus.RUNNING),
            TaskRunRecord(task_index=2, task_name="Task 3", status=TaskRunStatus.PENDING),
        ]
        panel = render_task_list(records, parallel_mode=True)
        panel_str = render_to_string(panel)
        # Should show parallel count in header
        assert "parallel" in panel_str


class TestRenderStatusBarParallel:
    def test_shows_parallel_task_count(self):
        text = render_status_bar(
            running=True,
            parallel_mode=True,
            running_count=3,
        )
        text_str = str(text)
        assert "3 tasks running" in text_str

    def test_singular_task_count(self):
        text = render_status_bar(
            running=True,
            parallel_mode=True,
            running_count=1,
        )
        text_str = str(text)
        # Should still show "1 tasks running" (current implementation)
        assert "1 tasks running" in text_str


class TestTuiEventQueue:
    def test_tui_post_event_thread_safe(self, tui):
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
        event = create_task_started_event(1, "Task 2")
        tui._apply_event(event)

        record = tui.get_record(1)
        assert record.status == TaskRunStatus.RUNNING
        assert record.start_time == event.timestamp

    def test_apply_event_processes_task_finished_success(self, tui):
        # First start the task
        tui._apply_event(create_task_started_event(0, "Task 1"))

        # Then finish it
        finish_event = create_task_finished_event(0, "Task 1", "success", 2.0)
        tui._apply_event(finish_event)

        record = tui.get_record(0)
        assert record.status == TaskRunStatus.SUCCESS
        assert record.end_time == finish_event.timestamp

    def test_apply_event_processes_task_finished_failed(self, tui):
        tui._apply_event(create_task_started_event(1, "Task 2"))
        finish_event = create_task_finished_event(1, "Task 2", "failed", 1.0, error="Error!")
        tui._apply_event(finish_event)

        record = tui.get_record(1)
        assert record.status == TaskRunStatus.FAILED
        assert record.error == "Error!"

    def test_apply_event_processes_task_finished_skipped(self, tui):
        finish_event = create_task_finished_event(2, "Task 3", "skipped", 0.0)
        tui._apply_event(finish_event)

        record = tui.get_record(2)
        assert record.status == TaskRunStatus.SKIPPED
        assert record.error is None


class TestLogBufferCleanup:
    def test_log_buffer_closed_on_success(self, tui):
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
        class FailingLogBuffer:
            def close(self):
                raise RuntimeError("Close failed!")

        record = tui.get_record(0)
        record.log_buffer = FailingLogBuffer()

        # Should not raise
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Buffer reference should be cleared even on error
        assert record.log_buffer is None


class TestAutoSwitchOnTaskFinish:
    def test_auto_switch_to_running_task_when_selected_finishes(self, tui):
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
        tui.set_parallel_mode(False)  # Sequential mode
        tui.follow_mode = True

        # Start a task (sequential mode)
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui.selected_index = 0

        # Task 1 finishes
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))

        # Selection stays unchanged (sequential mode doesn't use auto-switch)
        assert tui.selected_index == 0


class TestSpinnerCaching:
    """Tests for spinner caching to maintain animation state.

    Spinners are now managed via events:
    - Created in _handle_task_started
    - Removed in _handle_task_finished
    - render_task_list is read-only (retrieves from cache, doesn't create/remove)
    """

    def test_spinner_reuse_for_running_task(self, tui):
        # Start task via event - this creates the spinner
        tui._apply_event(create_task_started_event(1, "Task 2"))
        assert 1 in tui._spinners
        first_spinner = tui._spinners[1]

        # Render multiple times - spinner should be the same object
        tui._render_layout()
        tui._render_layout()
        assert 1 in tui._spinners
        second_spinner = tui._spinners[1]

        # Verify it's the EXACT same object (identity check)
        assert first_spinner is second_spinner

    def test_spinner_cleanup_when_task_finishes(self, tui):
        # Start task - creates spinner
        tui._apply_event(create_task_started_event(1, "Task 2"))
        assert 1 in tui._spinners

        # Finish task via event - removes spinner
        tui._apply_event(create_task_finished_event(1, "Task 2", status="success", duration=1.0))
        assert 1 not in tui._spinners

    def test_spinner_cleanup_on_failed_task(self, tui):
        # Start task - creates spinner
        tui._apply_event(create_task_started_event(0, "Task 1"))
        assert 0 in tui._spinners

        # Task fails via event - removes spinner
        tui._apply_event(create_task_finished_event(0, "Task 1", status="failed", duration=1.0))
        assert 0 not in tui._spinners

    def test_spinner_cleanup_on_skipped_task(self, tui):
        # Start task - creates spinner
        tui._apply_event(create_task_started_event(0, "Task 1"))
        assert 0 in tui._spinners

        # Task is skipped via event - removes spinner
        tui._apply_event(create_task_finished_event(0, "Task 1", status="skipped", duration=0.0))
        assert 0 not in tui._spinners

    def test_multiple_spinners_tracked_in_parallel_mode(self, tui):
        tui.set_parallel_mode(True)

        # Start all three tasks via events
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))

        # All three should have spinners
        assert 0 in tui._spinners
        assert 1 in tui._spinners
        assert 2 in tui._spinners
        assert len(tui._spinners) == 3

        # Verify they're different objects
        assert tui._spinners[0] is not tui._spinners[1]
        assert tui._spinners[1] is not tui._spinners[2]

    def test_spinner_cache_partial_cleanup(self, tui):
        tui.set_parallel_mode(True)

        # Start all three tasks via events
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))
        tui._apply_event(create_task_started_event(2, "Task 3"))
        assert len(tui._spinners) == 3
        spinner_1 = tui._spinners[1]

        # Task 0 finishes via event
        tui._apply_event(create_task_finished_event(0, "Task 1", status="success", duration=1.0))

        # Task 0 removed, but 1 and 2 still cached
        assert 0 not in tui._spinners
        assert 1 in tui._spinners
        assert 2 in tui._spinners
        assert len(tui._spinners) == 2

        # Spinner for task 1 should be the same object
        assert tui._spinners[1] is spinner_1

    def test_spinner_cache_none_uses_static_fallback(self, records):
        from io import StringIO

        from rich.console import Console

        # Render with spinners=None - should use static Text fallback for running task
        panel = render_task_list(records, spinners=None)
        assert panel is not None

        # Capture rendered output to verify the running task shows static icon
        console = Console(file=StringIO(), force_terminal=True, width=100)
        console.print(panel)
        output = console.file.getvalue()

        # The running task (Task 2) should show the ⟳ icon (static fallback)
        # not an animated spinner frame. This confirms Text is used, not Spinner.
        assert "⟳" in output, (
            f"Expected running icon '⟳' in rendered output for running task "
            f"without cached spinner. Got output:\n{output}"
        )

    def test_spinner_cache_empty_uses_static_fallback(self, records):
        from io import StringIO

        from rich.console import Console

        # Render with empty spinner cache
        panel = render_task_list(records, spinners={})
        assert panel is not None

        # Capture rendered output
        console = Console(file=StringIO(), force_terminal=True, width=100)
        console.print(panel)
        output = console.file.getvalue()

        # Running task should show ⟳ icon (static fallback)
        assert "⟳" in output, f"Expected running icon '⟳' in rendered output. Got:\n{output}"

    def test_spinner_cache_hit_uses_cached_spinner(self, records):
        from unittest.mock import patch

        from rich.spinner import Spinner
        from rich.table import Table

        # Create a spinner and put it in cache for the running task (index 1)
        cached_spinner = Spinner("dots", style="bold cyan")
        spinners_cache = {1: cached_spinner}

        # Track what gets added to the table by patching Table.add_row
        added_rows = []
        original_add_row = Table.add_row

        def tracking_add_row(self, *args, **kwargs):
            added_rows.append(args)
            return original_add_row(self, *args, **kwargs)

        with patch.object(Table, "add_row", tracking_add_row):
            panel = render_task_list(records, spinners=spinners_cache)

        assert panel is not None

        # Find the row for the running task (index 1, which is the second row)
        # Each row is (status_cell, task_name, duration)
        assert len(added_rows) >= 2, f"Expected at least 2 rows, got {len(added_rows)}"

        # The running task is at index 1 in records, so it's the second add_row call
        running_task_row = added_rows[1]
        status_cell = running_task_row[0]  # First column is status

        # Verify the cached spinner instance is used
        assert isinstance(status_cell, Spinner), (
            f"Expected Spinner for running task with cached spinner, "
            f"got {type(status_cell).__name__}"
        )
        assert (
            status_cell is cached_spinner
        ), "Expected the exact cached Spinner instance to be used"

        # Verify non-running tasks use Text (first row is pending task)
        pending_task_row = added_rows[0]
        pending_status_cell = pending_task_row[0]
        assert not isinstance(pending_status_cell, Spinner), "Pending task should not use Spinner"

    def test_tui_uses_spinner_cache(self, tui):
        tui.set_parallel_mode(True)

        # Start two tasks via events - this creates the spinners
        tui._apply_event(create_task_started_event(0, "Task 1"))
        tui._apply_event(create_task_started_event(1, "Task 2"))

        # Spinners should be cached after events
        assert 0 in tui._spinners
        assert 1 in tui._spinners
        spinner_0 = tui._spinners[0]
        spinner_1 = tui._spinners[1]

        # Render (via _render_layout) - spinners should still be same objects
        tui._render_layout()

        # Second render
        tui._render_layout()

        # Same spinner objects should be reused
        assert tui._spinners[0] is spinner_0
        assert tui._spinners[1] is spinner_1

        # Finish task 0
        tui._apply_event(create_task_finished_event(0, "Task 1", "success", 1.0))
        tui._render_layout()

        # Task 0 spinner removed, task 1 still cached
        assert 0 not in tui._spinners
        assert 1 in tui._spinners
        assert tui._spinners[1] is spinner_1


class TestThreadSafetyEnhancements:
    def test_check_quit_requested_thread_safe(self, tui):
        assert tui.check_quit_requested() is False

        # Set quit flag
        tui._handle_quit()

        assert tui.check_quit_requested() is True

    def test_clear_quit_request_thread_safe(self, tui):
        # Set quit flag
        tui._handle_quit()
        assert tui.check_quit_requested() is True

        # Clear it
        tui.clear_quit_request()
        assert tui.check_quit_requested() is False

    def test_toggle_follow_mode_thread_safe(self, tui):
        initial = tui.follow_mode
        tui._toggle_follow_mode()
        assert tui.follow_mode != initial

    def test_toggle_verbose_mode_thread_safe(self, tui):
        initial = tui.verbose_mode
        tui._toggle_verbose_mode()
        assert tui.verbose_mode != initial

    def test_concurrent_quit_requests(self, tui):
        num_threads = 10
        barrier = threading.Barrier(num_threads)

        def request_quit():
            barrier.wait()
            tui._handle_quit()

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=request_quit)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Quit should be requested
        assert tui.check_quit_requested() is True


class TestKeyEnum:
    def test_key_values(self):
        assert Key.UP.value == "up"
        assert Key.DOWN.value == "down"
        assert Key.ENTER.value == "enter"
        assert Key.ESCAPE.value == "escape"
        assert Key.Q.value == "q"
        assert Key.F.value == "f"
        assert Key.V.value == "v"
        assert Key.J.value == "j"
        assert Key.K.value == "k"
        assert Key.L.value == "l"
        assert Key.UNKNOWN.value == "unknown"


class TestCharMappings:
    def test_enter_mappings(self):
        assert _CHAR_MAPPINGS["\r"] == Key.ENTER
        assert _CHAR_MAPPINGS["\n"] == Key.ENTER

    def test_escape_mapping(self):
        assert _CHAR_MAPPINGS["\x1b"] == Key.ESCAPE

    def test_letter_mappings_case_insensitive(self):
        assert _CHAR_MAPPINGS["q"] == Key.Q
        assert _CHAR_MAPPINGS["Q"] == Key.Q
        assert _CHAR_MAPPINGS["f"] == Key.F
        assert _CHAR_MAPPINGS["F"] == Key.F
        assert _CHAR_MAPPINGS["v"] == Key.V
        assert _CHAR_MAPPINGS["V"] == Key.V
        assert _CHAR_MAPPINGS["j"] == Key.J
        assert _CHAR_MAPPINGS["J"] == Key.J
        assert _CHAR_MAPPINGS["k"] == Key.K
        assert _CHAR_MAPPINGS["K"] == Key.K
        assert _CHAR_MAPPINGS["l"] == Key.L
        assert _CHAR_MAPPINGS["L"] == Key.L


class TestEscapeSequences:
    def test_arrow_up_sequences(self):
        assert _ESCAPE_SEQUENCES["[A"] == Key.UP
        assert _ESCAPE_SEQUENCES["OA"] == Key.UP

    def test_arrow_down_sequences(self):
        assert _ESCAPE_SEQUENCES["[B"] == Key.DOWN
        assert _ESCAPE_SEQUENCES["OB"] == Key.DOWN


class TestKeyboardReader:
    def test_init_state(self):
        reader = KeyboardReader()
        assert reader._old_settings is None
        assert reader._is_started is False

    def test_context_manager_protocol(self):
        reader = KeyboardReader()
        with patch.object(reader, "start") as mock_start:
            with patch.object(reader, "stop") as mock_stop:
                with reader as r:
                    mock_start.assert_called_once()
                    assert r is reader
                mock_stop.assert_called_once()

    def test_start_on_non_unix_does_nothing(self):
        reader = KeyboardReader()
        with patch("ingot.ui.keyboard._IS_UNIX", False):
            reader.start()
            assert reader._is_started is False

    def test_stop_on_non_unix_does_nothing(self):
        reader = KeyboardReader()
        with patch("ingot.ui.keyboard._IS_UNIX", False):
            reader.stop()
            assert reader._is_started is False

    def test_read_key_returns_none_when_not_started(self):
        reader = KeyboardReader()
        assert reader.read_key() is None

    def test_read_key_returns_none_on_non_unix(self):
        reader = KeyboardReader()
        reader._is_started = True
        with patch("ingot.ui.keyboard._IS_UNIX", False):
            assert reader.read_key() is None

    def test_start_already_started_does_nothing(self):
        reader = KeyboardReader()
        reader._is_started = True
        with patch("ingot.ui.keyboard._IS_UNIX", True):
            reader.start()  # Should not raise or change state
            assert reader._is_started is True

    def test_stop_clears_state(self):
        reader = KeyboardReader()
        reader._is_started = True
        reader._old_settings = None
        with patch("ingot.ui.keyboard._IS_UNIX", True):
            reader.stop()
            assert reader._is_started is False

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_returns_mapped_key(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        # Mock select to indicate input is ready
        mock_select.select.return_value = ([mock_sys.stdin], [], [])
        # Mock stdin.read to return 'q'
        mock_sys.stdin.read.return_value = "q"

        result = reader.read_key()

        assert result == Key.Q

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_returns_unknown_for_unmapped(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        mock_select.select.return_value = ([mock_sys.stdin], [], [])
        mock_sys.stdin.read.return_value = "x"  # Not in mappings

        result = reader.read_key()

        assert result == Key.UNKNOWN

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_returns_none_when_no_input(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        # Mock select to indicate no input ready
        mock_select.select.return_value = ([], [], [])

        result = reader.read_key()

        assert result is None

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_returns_none_on_empty_read(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        mock_select.select.return_value = ([mock_sys.stdin], [], [])
        mock_sys.stdin.read.return_value = ""

        result = reader.read_key()

        assert result is None

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_handles_escape_sequence(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        # First call returns escape char, subsequent calls return sequence
        mock_select.select.side_effect = [
            ([mock_sys.stdin], [], []),  # Initial select
            ([mock_sys.stdin], [], []),  # Escape sequence check
            ([mock_sys.stdin], [], []),  # Read sequence char 1
            ([mock_sys.stdin], [], []),  # Read sequence char 2
            ([], [], []),  # No more chars
        ]
        mock_sys.stdin.read.side_effect = ["\x1b", "[", "A"]  # Escape + [A = UP

        result = reader.read_key()

        assert result == Key.UP

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    @patch("ingot.ui.keyboard.select")
    @patch("ingot.ui.keyboard.sys")
    def test_read_key_returns_escape_when_alone(self, mock_sys, mock_select):
        reader = KeyboardReader()
        reader._is_started = True

        mock_select.select.side_effect = [
            ([mock_sys.stdin], [], []),  # Initial select
            ([], [], []),  # No more chars after escape
        ]
        mock_sys.stdin.read.return_value = "\x1b"

        result = reader.read_key()

        assert result == Key.ESCAPE

    @patch("ingot.ui.keyboard._IS_UNIX", True)
    def test_read_key_handles_os_error(self):
        import select as real_select

        reader = KeyboardReader()
        reader._is_started = True

        with patch("ingot.ui.keyboard.select") as mock_select:
            # Keep the real error class
            mock_select.error = real_select.error
            mock_select.select.side_effect = OSError("Terminal error")

            result = reader.read_key()

            assert result is None
