"""Tests for ingot.workflow.events module."""

import time

from ingot.workflow.events import (
    TaskEvent,
    TaskEventType,
    TaskRunRecord,
    TaskRunStatus,
    create_run_finished_event,
    create_run_started_event,
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
    format_log_filename,
    format_run_directory,
    format_timestamp,
    slugify_task_name,
)


class TestTaskEventType:
    def test_run_started_value(self):
        assert TaskEventType.RUN_STARTED.value == "run_started"

    def test_task_started_value(self):
        assert TaskEventType.TASK_STARTED.value == "task_started"

    def test_task_output_value(self):
        assert TaskEventType.TASK_OUTPUT.value == "task_output"

    def test_task_finished_value(self):
        assert TaskEventType.TASK_FINISHED.value == "task_finished"

    def test_run_finished_value(self):
        assert TaskEventType.RUN_FINISHED.value == "run_finished"


class TestTaskEvent:
    def test_creation_with_required_fields(self):
        event = TaskEvent(
            event_type=TaskEventType.TASK_STARTED,
            task_index=0,
            task_name="Test task",
            timestamp=12345.0,
        )
        assert event.event_type == TaskEventType.TASK_STARTED
        assert event.task_index == 0
        assert event.task_name == "Test task"
        assert event.timestamp == 12345.0
        assert event.data is None

    def test_creation_with_data(self):
        event = TaskEvent(
            event_type=TaskEventType.TASK_OUTPUT,
            task_index=1,
            task_name="Test",
            timestamp=12345.0,
            data={"line": "output line"},
        )
        assert event.data == {"line": "output line"}


class TestTaskRunStatus:
    def test_all_status_values(self):
        assert TaskRunStatus.PENDING.value == "pending"
        assert TaskRunStatus.RUNNING.value == "running"
        assert TaskRunStatus.SUCCESS.value == "success"
        assert TaskRunStatus.FAILED.value == "failed"
        assert TaskRunStatus.SKIPPED.value == "skipped"


class TestTaskRunRecord:
    def test_default_status_is_pending(self):
        record = TaskRunRecord(task_index=0, task_name="Test")
        assert record.status == TaskRunStatus.PENDING

    def test_status_icon_pending(self):
        record = TaskRunRecord(task_index=0, task_name="Test")
        assert record.get_status_icon() == "○"

    def test_status_icon_running(self):
        record = TaskRunRecord(task_index=0, task_name="Test", status=TaskRunStatus.RUNNING)
        assert record.get_status_icon() == "⟳"

    def test_status_icon_success(self):
        record = TaskRunRecord(task_index=0, task_name="Test", status=TaskRunStatus.SUCCESS)
        assert record.get_status_icon() == "✓"

    def test_status_icon_failed(self):
        record = TaskRunRecord(task_index=0, task_name="Test", status=TaskRunStatus.FAILED)
        assert record.get_status_icon() == "✗"

    def test_status_icon_skipped(self):
        record = TaskRunRecord(task_index=0, task_name="Test", status=TaskRunStatus.SKIPPED)
        assert record.get_status_icon() == "⊘"

    def test_status_color_mapping(self):
        record = TaskRunRecord(task_index=0, task_name="Test")
        assert record.get_status_color() == "dim white"

        record.status = TaskRunStatus.RUNNING
        assert record.get_status_color() == "bold cyan"

        record.status = TaskRunStatus.SUCCESS
        assert record.get_status_color() == "bold green"

        record.status = TaskRunStatus.FAILED
        assert record.get_status_color() == "bold red"

        record.status = TaskRunStatus.SKIPPED
        assert record.get_status_color() == "yellow"

    def test_elapsed_time_not_started(self):
        record = TaskRunRecord(task_index=0, task_name="Test")
        assert record.elapsed_time == 0.0

    def test_elapsed_time_running(self):
        record = TaskRunRecord(
            task_index=0,
            task_name="Test",
            status=TaskRunStatus.RUNNING,
            start_time=time.time() - 5.0,
        )
        assert 4.9 <= record.elapsed_time <= 5.5

    def test_elapsed_time_completed(self):
        record = TaskRunRecord(
            task_index=0,
            task_name="Test",
            status=TaskRunStatus.SUCCESS,
            start_time=100.0,
            end_time=110.0,
        )
        assert record.elapsed_time == 10.0

    def test_duration_property(self):
        record = TaskRunRecord(
            task_index=0,
            task_name="Test",
            start_time=100.0,
        )
        assert record.duration is None

        record.end_time = 110.0
        assert record.duration == 10.0

    def test_format_duration_seconds(self):
        record = TaskRunRecord(
            task_index=0,
            task_name="Test",
            start_time=100.0,
            end_time=101.5,
        )
        assert record.format_duration() == "1.5s"

    def test_format_duration_minutes(self):
        record = TaskRunRecord(
            task_index=0,
            task_name="Test",
            start_time=100.0,
            end_time=190.0,  # 90 seconds = 1m 30s
        )
        assert record.format_duration() == "1m 30s"


class TestSlugifyTaskName:
    def test_basic_slugify(self):
        assert slugify_task_name("Implement authentication") == "implement_authentication"

    def test_removes_special_characters(self):
        assert slugify_task_name("Add user auth!") == "add_user_auth"

    def test_collapses_multiple_underscores(self):
        assert slugify_task_name("foo---bar___baz") == "foo_bar_baz"

    def test_strips_leading_trailing_underscores(self):
        assert slugify_task_name("!!!test!!!") == "test"

    def test_respects_max_length(self):
        long_name = "This is a very long task name that exceeds the limit"
        slug = slugify_task_name(long_name, max_length=20)
        assert len(slug) <= 20

    def test_truncates_at_word_boundary(self):
        slug = slugify_task_name("implement user authentication", max_length=20)
        # Should cut at underscore boundary
        assert slug == "implement_user"


class TestFormatLogFilename:
    def test_basic_filename(self):
        filename = format_log_filename(0, "Implement authentication")
        assert filename == "task_001_implement_authentication.log"

    def test_index_padding(self):
        assert format_log_filename(9, "test") == "task_010_test.log"
        assert format_log_filename(99, "test") == "task_100_test.log"

    def test_slugifies_name(self):
        filename = format_log_filename(0, "Add user auth!")
        assert filename == "task_001_add_user_auth.log"


class TestFormatTimestamp:
    def test_returns_bracketed_timestamp(self):
        ts = format_timestamp()
        assert ts.startswith("[")
        assert ts.endswith("]")

    def test_has_correct_format(self):
        ts = format_timestamp()
        # Format: [2026-01-11 12:34:56.123]
        assert len(ts) == 25
        assert ts[5] == "-"
        assert ts[8] == "-"
        assert ts[11] == " "
        assert ts[14] == ":"
        assert ts[17] == ":"
        assert ts[20] == "."


class TestFormatRunDirectory:
    def test_returns_timestamp_format(self):
        dirname = format_run_directory()
        assert len(dirname) == 15
        assert dirname[8] == "_"
        # Should be all digits except underscore
        assert dirname.replace("_", "").isdigit()


class TestEventFactories:
    def test_create_run_started_event(self):
        event = create_run_started_event(total_tasks=5)
        assert event.event_type == TaskEventType.RUN_STARTED
        assert event.task_index == 0
        assert event.task_name == ""
        assert event.data == {"total_tasks": 5}

    def test_create_task_started_event(self):
        event = create_task_started_event(2, "Test task")
        assert event.event_type == TaskEventType.TASK_STARTED
        assert event.task_index == 2
        assert event.task_name == "Test task"

    def test_create_task_output_event(self):
        event = create_task_output_event(1, "Task", "output line")
        assert event.event_type == TaskEventType.TASK_OUTPUT
        assert event.data == {"line": "output line"}

    def test_create_task_finished_event_success(self):
        event = create_task_finished_event(0, "Task", status="success", duration=5.0)
        assert event.event_type == TaskEventType.TASK_FINISHED
        assert event.data["status"] == "success"
        assert event.data["duration"] == 5.0
        assert event.data["error"] is None

    def test_create_task_finished_event_failure(self):
        event = create_task_finished_event(
            0, "Task", status="failed", duration=2.0, error="Something went wrong"
        )
        assert event.data["status"] == "failed"
        assert event.data["error"] == "Something went wrong"

    def test_task_finished_event_tri_state(self):
        # Test success status
        success_event = create_task_finished_event(0, "Task1", "success", 5.0)
        assert success_event.data["status"] == "success"
        assert success_event.data["error"] is None

        # Test failed status
        failed_event = create_task_finished_event(1, "Task2", "failed", 2.0, error="Error msg")
        assert failed_event.data["status"] == "failed"
        assert failed_event.data["error"] == "Error msg"

        # Test skipped status
        skipped_event = create_task_finished_event(2, "Task3", "skipped", 0.0)
        assert skipped_event.data["status"] == "skipped"
        assert skipped_event.data["duration"] == 0.0
        assert skipped_event.data["error"] is None

    def test_create_run_finished_event(self):
        event = create_run_finished_event(
            total_tasks=10, success_count=8, failed_count=1, skipped_count=1
        )
        assert event.event_type == TaskEventType.RUN_FINISHED
        assert event.data == {
            "total_tasks": 10,
            "success_count": 8,
            "failed_count": 1,
            "skipped_count": 1,
        }
