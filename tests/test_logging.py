"""Tests for spec.utils.logging module."""

import os
from pathlib import Path
from unittest.mock import patch


class TestLogging:
    """Tests for logging functionality."""

    def test_log_disabled_by_default(self):
        """Logging is disabled when SPEC_LOG is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Need to reimport to pick up env changes
            import importlib

            import spec.utils.logging as logging_module

            # Reset the module state
            logging_module._logger = None
            importlib.reload(logging_module)

            assert logging_module.LOG_ENABLED is False

    def test_log_enabled_with_env_var(self):
        """Logging is enabled when SPEC_LOG=true."""
        with patch.dict(os.environ, {"SPEC_LOG": "true"}):
            import importlib

            import spec.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            assert logging_module.LOG_ENABLED is True

    def test_log_file_default_path(self):
        """Default log file is in home directory."""
        import spec.utils.logging as logging_module

        expected = Path.home() / ".spec.log"
        assert logging_module.LOG_FILE == expected

    def test_log_file_custom_path(self):
        """Custom log file path from environment."""
        custom_path = "/tmp/custom-log.log"
        with patch.dict(os.environ, {"SPEC_LOG_FILE": custom_path}):
            import importlib

            import spec.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            assert str(logging_module.LOG_FILE) == custom_path

    def test_setup_logging_returns_logger(self):
        """setup_logging returns a logger instance."""
        import spec.utils.logging as logging_module

        logging_module._logger = None
        logger = logging_module.setup_logging()

        assert logger is not None
        assert logger.name == "spec"

    def test_get_logger_returns_same_instance(self):
        """get_logger returns the same logger instance."""
        import spec.utils.logging as logging_module

        logging_module._logger = None
        logger1 = logging_module.get_logger()
        logger2 = logging_module.get_logger()

        assert logger1 is logger2

    def test_log_message_when_disabled(self):
        """log_message does nothing when logging is disabled."""
        with patch.dict(os.environ, {"SPEC_LOG": "false"}):
            import importlib

            import spec.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            # Should not raise any errors
            logging_module.log_message("Test message")

    def test_log_message_when_enabled(self, tmp_path):
        """log_message writes to file when logging is enabled."""
        log_file = tmp_path / "test.log"

        with patch.dict(os.environ, {
            "SPEC_LOG": "true",
            "SPEC_LOG_FILE": str(log_file),
        }):
            import importlib

            import spec.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            logging_module.log_message("Test message")

            # Force flush
            for handler in logging_module._logger.handlers:
                handler.flush()

            content = log_file.read_text()
            assert "Test message" in content

    def test_log_command(self, tmp_path):
        """log_command logs command with exit code."""
        log_file = tmp_path / "test.log"

        with patch.dict(os.environ, {
            "SPEC_LOG": "true",
            "SPEC_LOG_FILE": str(log_file),
        }):
            import importlib

            import spec.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            logging_module.log_command("git status", exit_code=0)

            for handler in logging_module._logger.handlers:
                handler.flush()

            content = log_file.read_text()
            assert "COMMAND: git status" in content
            assert "EXIT_CODE: 0" in content

