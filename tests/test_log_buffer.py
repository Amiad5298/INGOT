"""Tests for spec.ui.log_buffer module."""

from pathlib import Path

from spec.ui.log_buffer import TaskLogBuffer


class TestTaskLogBufferCreation:
    """Tests for TaskLogBuffer initialization."""

    def test_creates_with_path(self, tmp_path: Path):
        """TaskLogBuffer can be created with a log path."""
        log_path = tmp_path / "test.log"
        buffer = TaskLogBuffer(log_path=log_path)
        assert buffer.log_path == log_path
        assert buffer.tail_lines == 100
        buffer.close()

    def test_creates_with_custom_tail_lines(self, tmp_path: Path):
        """TaskLogBuffer respects custom tail_lines parameter."""
        log_path = tmp_path / "test.log"
        buffer = TaskLogBuffer(log_path=log_path, tail_lines=50)
        assert buffer.tail_lines == 50
        buffer.close()


class TestTaskLogBufferWrite:
    """Tests for TaskLogBuffer write operations."""

    def test_creates_file_on_first_write(self, tmp_path: Path):
        """File is created lazily on first write."""
        log_path = tmp_path / "subdir" / "test.log"
        buffer = TaskLogBuffer(log_path=log_path)

        # File should not exist yet
        assert not log_path.exists()

        buffer.write("First line")

        # Now file should exist
        assert log_path.exists()
        buffer.close()

    def test_writes_lines_to_file(self, tmp_path: Path):
        """Lines are written to the log file."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            buffer.write("Line 1")
            buffer.write("Line 2")
            buffer.write("Line 3")

        content = log_path.read_text()
        assert "Line 1" in content
        assert "Line 2" in content
        assert "Line 3" in content

    def test_writes_with_timestamp_by_default(self, tmp_path: Path):
        """Lines include timestamp by default."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            buffer.write("Test line")

        content = log_path.read_text()
        # Check for timestamp format [YYYY-MM-DD HH:MM:SS.mmm]
        assert "[20" in content  # Year starts with 20
        assert "Test line" in content

    def test_write_raw_skips_timestamp(self, tmp_path: Path):
        """write_raw does not include timestamp."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            buffer.write_raw("Raw line")

        content = log_path.read_text()
        assert content.strip() == "Raw line"

    def test_line_count_tracks_writes(self, tmp_path: Path):
        """line_count property tracks number of writes."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            assert buffer.line_count == 0
            buffer.write("Line 1")
            assert buffer.line_count == 1
            buffer.write("Line 2")
            buffer.write("Line 3")
            assert buffer.line_count == 3


class TestTaskLogBufferGetTail:
    """Tests for TaskLogBuffer get_tail method."""

    def test_get_tail_returns_correct_lines(self, tmp_path: Path):
        """get_tail returns the last n lines."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            for i in range(10):
                buffer.write(f"Line {i}")

            tail = buffer.get_tail(3)
            assert tail == ["Line 7", "Line 8", "Line 9"]

    def test_get_tail_returns_all_if_less_than_n(self, tmp_path: Path):
        """get_tail returns all lines if fewer than n exist."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            buffer.write("Line 1")
            buffer.write("Line 2")

            tail = buffer.get_tail(10)
            assert tail == ["Line 1", "Line 2"]

    def test_get_tail_default_is_15(self, tmp_path: Path):
        """get_tail default n is 15."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            for i in range(20):
                buffer.write(f"Line {i}")

            tail = buffer.get_tail()
            assert len(tail) == 15
            assert tail[0] == "Line 5"
            assert tail[-1] == "Line 19"


class TestTaskLogBufferMaxLines:
    """Tests for TaskLogBuffer memory bounds."""

    def test_respects_max_lines(self, tmp_path: Path):
        """Buffer respects tail_lines limit."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path, tail_lines=5) as buffer:
            for i in range(100):
                buffer.write(f"Line {i}")

            # Buffer should only have last 5 lines
            tail = buffer.get_tail(100)  # Request more than buffer size
            assert len(tail) == 5
            assert tail == ["Line 95", "Line 96", "Line 97", "Line 98", "Line 99"]


class TestTaskLogBufferContextManager:
    """Tests for TaskLogBuffer context manager."""

    def test_context_manager_closes_file(self, tmp_path: Path):
        """Context manager closes file on exit."""
        log_path = tmp_path / "test.log"
        with TaskLogBuffer(log_path=log_path) as buffer:
            buffer.write("Test")
            assert buffer._file_handle is not None

        # After context, file handle should be None
        assert buffer._file_handle is None

    def test_close_is_idempotent(self, tmp_path: Path):
        """close() can be called multiple times safely."""
        log_path = tmp_path / "test.log"
        buffer = TaskLogBuffer(log_path=log_path)
        buffer.write("Test")
        buffer.close()
        buffer.close()  # Should not raise
        buffer.close()  # Should not raise

