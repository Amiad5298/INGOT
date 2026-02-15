"""Tests for ingot.utils.logging module."""

import os
from pathlib import Path
from unittest.mock import patch

import ingot.utils.logging as logging_mod
from ingot.utils.logging import log_once


class TestLogging:
    def test_log_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            # Need to reimport to pick up env changes
            import importlib

            import ingot.utils.logging as logging_module

            # Reset the module state
            logging_module._logger = None
            importlib.reload(logging_module)

            assert logging_module.LOG_ENABLED is False

    def test_log_enabled_with_env_var(self):
        with patch.dict(os.environ, {"INGOT_LOG": "true"}):
            import importlib

            import ingot.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            assert logging_module.LOG_ENABLED is True

    def test_log_file_default_path(self):
        import ingot.utils.logging as logging_module

        expected = Path.home() / ".ingot.log"
        assert logging_module.LOG_FILE == expected

    def test_log_file_custom_path(self):
        custom_path = "/tmp/custom-log.log"
        with patch.dict(os.environ, {"INGOT_LOG_FILE": custom_path}):
            import importlib

            import ingot.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            assert str(logging_module.LOG_FILE) == custom_path

    def test_setup_logging_returns_logger(self):
        import ingot.utils.logging as logging_module

        logging_module._logger = None
        logger = logging_module.setup_logging()

        assert logger is not None
        assert logger.name == "ingot"

    def test_get_logger_returns_same_instance(self):
        import ingot.utils.logging as logging_module

        logging_module._logger = None
        logger1 = logging_module.get_logger()
        logger2 = logging_module.get_logger()

        assert logger1 is logger2

    def test_log_message_when_disabled(self):
        with patch.dict(os.environ, {"INGOT_LOG": "false"}):
            import importlib

            import ingot.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            # Should not raise any errors
            logging_module.log_message("Test message")

    def test_log_message_when_enabled(self, tmp_path):
        log_file = tmp_path / "test.log"

        with patch.dict(
            os.environ,
            {
                "INGOT_LOG": "true",
                "INGOT_LOG_FILE": str(log_file),
            },
        ):
            import importlib

            import ingot.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            logging_module.log_message("Test message")

            # Force flush
            for handler in logging_module._logger.handlers:
                handler.flush()

            content = log_file.read_text()
            assert "Test message" in content

    def test_log_command(self, tmp_path):
        log_file = tmp_path / "test.log"

        with patch.dict(
            os.environ,
            {
                "INGOT_LOG": "true",
                "INGOT_LOG_FILE": str(log_file),
            },
        ):
            import importlib

            import ingot.utils.logging as logging_module

            logging_module._logger = None
            importlib.reload(logging_module)

            logging_module.log_command("git status", exit_code=0)

            for handler in logging_module._logger.handlers:
                handler.flush()

            content = log_file.read_text()
            assert "COMMAND: git status" in content
            assert "EXIT_CODE: 0" in content


class TestLogOnce:
    def setup_method(self):
        """Clear the logged-once state before each test.

        Access via module attribute (not a stale import) because
        TestLogging reloads the module, replacing the set object.
        """
        logging_mod._logged_once_keys.clear()

    def test_logs_first_call(self):
        with patch("ingot.utils.logging.log_message") as mock_log:
            log_once("test_key_a", "hello")

        mock_log.assert_called_once_with("hello")

    def test_suppresses_second_call_same_key(self):
        with patch("ingot.utils.logging.log_message") as mock_log:
            log_once("test_key_b", "first")
            log_once("test_key_b", "second")

        mock_log.assert_called_once_with("first")

    def test_different_keys_both_logged(self):
        with patch("ingot.utils.logging.log_message") as mock_log:
            log_once("test_key_c", "message a")
            log_once("test_key_d", "message b")

        assert mock_log.call_count == 2
