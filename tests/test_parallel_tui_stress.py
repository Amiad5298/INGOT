"""Stress tests for parallel TUI event handling and thread safety.

Tests that concurrent worker threads posting events to TaskRunnerUI
via post_event() while the main thread calls refresh() does not
cause race conditions, data corruption, or event ordering violations.
"""

import threading
import time

import pytest

from ingot.ui.log_buffer import TaskLogBuffer
from ingot.ui.tui import TaskRunnerUI
from ingot.workflow.events import (
    TaskEventType,
    TaskRunStatus,
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
)


@pytest.fixture
def parallel_tui():
    """Create a TaskRunnerUI configured for parallel mode without Live display."""
    tui = TaskRunnerUI(
        ticket_id="STRESS-TEST",
        parallel_mode=True,
        verbose_mode=False,
    )
    return tui


class TestParallelTuiStress:
    def test_concurrent_post_event_with_drain(self, parallel_tui, tmp_path):
        num_workers = 8
        lines_per_worker = 50
        task_names = [f"Task {i}" for i in range(num_workers)]

        parallel_tui.initialize_records(task_names)

        # Attach log buffers to each record
        for i, record in enumerate(parallel_tui.records):
            log_path = tmp_path / f"task_{i}.log"
            record.log_buffer = TaskLogBuffer(log_path=log_path)

        barrier = threading.Barrier(num_workers)

        def worker(idx: int) -> None:
            """Worker thread that posts TASK_STARTED, multiple TASK_OUTPUT, then signals."""
            barrier.wait()  # Synchronize all workers to start at once
            parallel_tui.post_event(create_task_started_event(idx, task_names[idx]))
            for line_num in range(lines_per_worker):
                parallel_tui.post_event(
                    create_task_output_event(idx, task_names[idx], f"Worker {idx} line {line_num}")
                )

        # Launch worker threads
        threads = []
        for i in range(num_workers):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Main thread: periodically drain events while workers are running
        for _ in range(20):
            parallel_tui._drain_event_queue()
            time.sleep(0.01)

        # Wait for all workers
        for t in threads:
            t.join(timeout=5)

        # Final drain to catch remaining events
        parallel_tui._drain_event_queue()

        # Verify: all tasks should be RUNNING
        for i in range(num_workers):
            record = parallel_tui.get_record(i)
            assert record is not None
            assert record.status == TaskRunStatus.RUNNING

        # Verify: all log buffers received output
        for i in range(num_workers):
            record = parallel_tui.get_record(i)
            assert record is not None
            assert record.log_buffer is not None
            assert record.log_buffer.line_count == lines_per_worker

        # Cleanup
        for record in parallel_tui.records:
            if record.log_buffer:
                record.log_buffer.close()

    def test_event_ordering_invariants(self, parallel_tui, tmp_path):
        num_workers = 6
        task_names = [f"Task {i}" for i in range(num_workers)]
        parallel_tui.initialize_records(task_names)

        # Attach log buffers
        for i, record in enumerate(parallel_tui.records):
            log_path = tmp_path / f"task_{i}.log"
            record.log_buffer = TaskLogBuffer(log_path=log_path)

        # Track event application order
        applied_events: list[tuple[int, TaskEventType]] = []
        original_apply = parallel_tui._apply_event

        def tracking_apply(event):
            applied_events.append((event.task_index, event.event_type))
            original_apply(event)

        parallel_tui._apply_event = tracking_apply

        # Workers post events in correct order (STARTED -> OUTPUT -> FINISHED)
        barrier = threading.Barrier(num_workers)

        def worker(idx: int) -> None:
            barrier.wait()
            parallel_tui.post_event(create_task_started_event(idx, task_names[idx]))
            for line_num in range(10):
                parallel_tui.post_event(
                    create_task_output_event(idx, task_names[idx], f"output {line_num}")
                )
            parallel_tui.post_event(
                create_task_finished_event(idx, task_names[idx], "success", 1.0)
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Drain all events on main thread
        parallel_tui._drain_event_queue()

        # Verify per-task ordering invariants
        for task_idx in range(num_workers):
            task_events = [et for idx, et in applied_events if idx == task_idx]
            assert (
                task_events[0] == TaskEventType.TASK_STARTED
            ), f"Task {task_idx}: first event should be TASK_STARTED, got {task_events[0]}"
            assert (
                task_events[-1] == TaskEventType.TASK_FINISHED
            ), f"Task {task_idx}: last event should be TASK_FINISHED, got {task_events[-1]}"
            # All middle events should be TASK_OUTPUT
            for et in task_events[1:-1]:
                assert et == TaskEventType.TASK_OUTPUT

        # Verify all tasks ended in SUCCESS
        for i in range(num_workers):
            record = parallel_tui.get_record(i)
            assert record is not None
            assert record.status == TaskRunStatus.SUCCESS

    def test_log_buffer_integrity_under_high_concurrency(self, parallel_tui, tmp_path):
        num_workers = 8
        lines_per_worker = 100
        task_names = [f"Task {i}" for i in range(num_workers)]

        parallel_tui.initialize_records(task_names)

        for i, record in enumerate(parallel_tui.records):
            log_path = tmp_path / f"task_{i}.log"
            record.log_buffer = TaskLogBuffer(log_path=log_path)

        barrier = threading.Barrier(num_workers)

        def worker(idx: int) -> None:
            barrier.wait()
            parallel_tui.post_event(create_task_started_event(idx, task_names[idx]))
            for line_num in range(lines_per_worker):
                parallel_tui.post_event(
                    create_task_output_event(
                        idx, task_names[idx], f"TASK{idx:03d}-LINE{line_num:04d}"
                    )
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()

        # Simulate main thread refresh loop
        for _ in range(50):
            parallel_tui._drain_event_queue()
            time.sleep(0.005)

        for t in threads:
            t.join(timeout=5)

        # Final drain
        parallel_tui._drain_event_queue()

        # Verify each log file has the correct lines
        for i in range(num_workers):
            record = parallel_tui.get_record(i)
            assert record is not None
            assert record.log_buffer is not None

            # Read back the log file
            log_content = record.log_buffer.log_path.read_text()
            record.log_buffer.close()

            # Verify all expected lines are present (log file includes timestamps)
            for line_num in range(lines_per_worker):
                expected_marker = f"TASK{i:03d}-LINE{line_num:04d}"
                assert (
                    expected_marker in log_content
                ), f"Missing {expected_marker} in task {i} log file"

    def test_parallel_task_completion_tracking(self, parallel_tui, tmp_path):
        num_workers = 10
        task_names = [f"Task {i}" for i in range(num_workers)]
        parallel_tui.initialize_records(task_names)

        for i, record in enumerate(parallel_tui.records):
            log_path = tmp_path / f"task_{i}.log"
            record.log_buffer = TaskLogBuffer(log_path=log_path)

        # Post all start events
        for i in range(num_workers):
            parallel_tui.post_event(create_task_started_event(i, task_names[i]))

        parallel_tui._drain_event_queue()

        # All tasks should be running
        assert len(parallel_tui._running_task_indices) == num_workers

        # Complete tasks from multiple threads simultaneously
        barrier = threading.Barrier(num_workers)

        def finish_worker(idx: int) -> None:
            barrier.wait()
            status = "success" if idx % 2 == 0 else "failed"
            parallel_tui.post_event(create_task_finished_event(idx, task_names[idx], status, 0.5))

        threads = [threading.Thread(target=finish_worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        parallel_tui._drain_event_queue()

        # All tasks should be finished, none running
        assert len(parallel_tui._running_task_indices) == 0

        # Verify correct statuses
        for i in range(num_workers):
            record = parallel_tui.get_record(i)
            assert record is not None
            if i % 2 == 0:
                assert record.status == TaskRunStatus.SUCCESS
            else:
                assert record.status == TaskRunStatus.FAILED

    def test_no_events_lost_under_contention(self, parallel_tui, tmp_path):
        num_workers = 5
        events_per_worker = 200
        task_names = [f"Task {i}" for i in range(num_workers)]
        parallel_tui.initialize_records(task_names)

        for i, record in enumerate(parallel_tui.records):
            log_path = tmp_path / f"task_{i}.log"
            record.log_buffer = TaskLogBuffer(log_path=log_path)

        # Track total events applied
        event_count = 0
        count_lock = threading.Lock()
        original_apply = parallel_tui._apply_event

        def counting_apply(event):
            nonlocal event_count
            with count_lock:
                event_count += 1
            original_apply(event)

        parallel_tui._apply_event = counting_apply

        barrier = threading.Barrier(num_workers)

        def worker(idx: int) -> None:
            barrier.wait()
            # Post TASK_STARTED + N output events = 1 + events_per_worker events
            parallel_tui.post_event(create_task_started_event(idx, task_names[idx]))
            for j in range(events_per_worker):
                parallel_tui.post_event(create_task_output_event(idx, task_names[idx], f"line {j}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()

        # Interleave draining with posting
        for _ in range(30):
            parallel_tui._drain_event_queue()
            time.sleep(0.005)

        for t in threads:
            t.join(timeout=5)

        # Final drain
        parallel_tui._drain_event_queue()

        expected_events = num_workers * (1 + events_per_worker)  # STARTED + OUTPUT lines
        assert (
            event_count == expected_events
        ), f"Expected {expected_events} events, got {event_count}"

        # Cleanup
        for record in parallel_tui.records:
            if record.log_buffer:
                record.log_buffer.close()
