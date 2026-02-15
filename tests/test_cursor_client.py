"""Tests for ingot.integrations.cursor module - CursorClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.cursor import (
    CURSOR_STARTUP_DELAY_MAX_MS,
    CURSOR_STARTUP_DELAY_MIN_MS,
    CursorClient,
    check_cursor_installed,
    looks_like_rate_limit,
)


class TestCursorClientDetectCliCommand:
    def test_detects_cursor_when_available(self):
        client = CursorClient(enable_startup_jitter=False)

        with patch("ingot.integrations.cursor.shutil.which", side_effect=lambda x: x == "cursor"):
            cmd = client._detect_cli_command()

        assert cmd == "cursor"

    def test_falls_back_to_agent(self):
        client = CursorClient(enable_startup_jitter=False)

        def which_side_effect(name):
            if name == "agent":
                return "/usr/local/bin/agent"
            return None

        with patch("ingot.integrations.cursor.shutil.which", side_effect=which_side_effect):
            cmd = client._detect_cli_command()

        assert cmd == "agent"

    def test_defaults_to_cursor_when_nothing_found(self):
        client = CursorClient(enable_startup_jitter=False)

        with patch("ingot.integrations.cursor.shutil.which", return_value=None):
            cmd = client._detect_cli_command()

        assert cmd == "cursor"

    def test_caches_result(self):
        client = CursorClient(enable_startup_jitter=False)

        with patch(
            "ingot.integrations.cursor.shutil.which", return_value="/usr/local/bin/cursor"
        ) as mock_which:
            client._detect_cli_command()
            client._detect_cli_command()

        # which() should only be called once (for "cursor"), then cached
        assert mock_which.call_count == 1


class TestCursorClientSupportsModelFlag:
    def test_supports_model_when_in_help(self):
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "Options:\n  --model <model>  Specify model\n  --help"
        mock_result.stderr = ""

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            assert client._supports_model_flag() is True

    def test_no_model_when_not_in_help(self):
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "Options:\n  --print  Print mode\n  --help"
        mock_result.stderr = ""

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            assert client._supports_model_flag() is False

    def test_caches_result(self):
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "--model"
        mock_result.stderr = ""

        with patch(
            "ingot.integrations.cursor.subprocess.run", return_value=mock_result
        ) as mock_run:
            client._supports_model_flag()
            client._supports_model_flag()

        assert mock_run.call_count == 1

    def test_returns_false_on_exception(self):
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        with patch(
            "ingot.integrations.cursor.subprocess.run",
            side_effect=OSError("command not found"),
        ):
            assert client._supports_model_flag() is False


class TestCursorClientBuildCommand:
    def _make_client(self, model: str = "") -> CursorClient:
        """Create a CursorClient with predictable CLI detection."""
        client = CursorClient(model=model, enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True
        return client

    def test_basic_structure(self):
        client = self._make_client()
        cmd = client.build_command("test prompt", print_mode=True)

        assert cmd[0] == "cursor"
        assert "--print" in cmd
        assert cmd[-1] == "test prompt"

    def test_model_flag_when_model_set(self):
        client = self._make_client(model="gpt-4")
        cmd = client.build_command("test prompt", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "gpt-4"

    def test_model_flag_when_model_passed(self):
        client = self._make_client()
        cmd = client.build_command("test prompt", model="claude-3-sonnet", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-3-sonnet"

    def test_no_save_flag(self):
        client = self._make_client()
        cmd = client.build_command("test prompt", no_save=True, print_mode=True)

        assert "--no-save" in cmd

    def test_no_save_flag_absent(self):
        client = self._make_client()
        cmd = client.build_command("test prompt", no_save=False, print_mode=True)

        assert "--no-save" not in cmd

    def test_all_flags_combined(self):
        client = self._make_client()
        cmd = client.build_command(
            "do the work",
            model="gpt-4",
            print_mode=True,
            no_save=True,
        )

        assert cmd[0] == "cursor"
        assert "--print" in cmd
        assert "--model" in cmd
        assert "--no-save" in cmd
        assert cmd[-1] == "do the work"

    def test_no_print_mode(self):
        client = self._make_client()
        cmd = client.build_command("test prompt", print_mode=False)

        assert "--print" not in cmd
        assert cmd[-1] == "test prompt"

    def test_prompt_is_last_argument(self):
        client = self._make_client(model="gpt-4")
        cmd = client.build_command(
            "my prompt here",
            print_mode=True,
            no_save=True,
        )

        assert cmd[-1] == "my prompt here"

    def test_explicit_model_overrides_instance_default(self):
        client = self._make_client(model="default-model")
        cmd = client.build_command("test", model="override-model", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"

    def test_model_flag_skipped_when_not_supported(self):
        client = CursorClient(model="gpt-4", enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = False

        cmd = client.build_command("test prompt", print_mode=True)

        assert "--model" not in cmd


class TestCursorClientExecution:
    def _make_client(self) -> CursorClient:
        """Create a CursorClient with predictable settings."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True
        return client

    def test_run_with_callback_streams_output(self):
        client = self._make_client()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch("ingot.integrations.cursor.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is True
        assert "line 1" in output
        assert "line 2" in output
        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("line 1")
        mock_callback.assert_any_call("line 2")

    def test_run_with_callback_failure(self):
        client = self._make_client()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = None

        with patch("ingot.integrations.cursor.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is False
        assert "error output" in output

    def test_run_print_with_output_returns_tuple(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_does_not_print_to_stdout(self, capsys):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            client.run_print_with_output("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_with_output_includes_stderr_on_failure(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: invalid model"
        mock_result.returncode = 1

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: invalid model" in output

    def test_run_print_with_output_prefers_stdout_even_on_failure(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "partial output"
        mock_result.stderr = "some error"
        mock_result.returncode = 1

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert output == "partial output"

    def test_run_print_quiet_returns_output_string(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_quiet_empty_output(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == ""

    def test_run_print_quiet_includes_stderr_on_failure(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: rate limit exceeded"
        mock_result.returncode = 1

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert "Error: rate limit exceeded" in output

    def test_run_print_quiet_does_not_print_to_stdout(self, capsys):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.cursor.subprocess.run", return_value=mock_result):
            client.run_print_quiet("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_quiet_passes_timeout_to_subprocess(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.cursor.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_quiet("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        client = self._make_client()

        with (
            patch(
                "ingot.integrations.cursor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=5),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_quiet("test", timeout_seconds=5.0)

    def test_run_print_with_output_passes_timeout_to_subprocess(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.cursor.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_with_output("test", timeout_seconds=45.0)

        assert mock_run.call_args.kwargs.get("timeout") == 45.0

    def test_run_print_with_output_timeout_raises_timeout_expired(self):
        client = self._make_client()

        with (
            patch(
                "ingot.integrations.cursor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=10),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_with_output("test", timeout_seconds=10.0)

    def test_run_print_quiet_no_timeout_by_default(self):
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.cursor.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_quiet("test")

        assert mock_run.call_args.kwargs.get("timeout") is None


class TestCheckCursorInstalled:
    def test_installed_returns_true_and_version(self):
        with (
            patch(
                "ingot.integrations.cursor.shutil.which",
                side_effect=lambda x: "/usr/local/bin/cursor" if x == "cursor" else None,
            ),
            patch(
                "ingot.integrations.cursor.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="cursor 0.1.0",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_cursor_installed()

        assert is_installed is True
        assert "0.1.0" in message

    def test_not_installed_returns_false(self):
        with patch("ingot.integrations.cursor.shutil.which", return_value=None):
            is_installed, message = check_cursor_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message

    def test_agent_fallback_detected(self):
        def which_side_effect(name):
            if name == "agent":
                return "/usr/local/bin/agent"
            return None

        with (
            patch("ingot.integrations.cursor.shutil.which", side_effect=which_side_effect),
            patch(
                "ingot.integrations.cursor.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="agent 1.2.3",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_cursor_installed()

        assert is_installed is True
        assert "1.2.3" in message

    def test_version_check_failure(self):
        def which_side_effect(name):
            if name == "cursor":
                return "/usr/local/bin/cursor"
            return None

        with (
            patch("ingot.integrations.cursor.shutil.which", side_effect=which_side_effect),
            patch(
                "ingot.integrations.cursor.subprocess.run",
                return_value=MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="error",
                ),
            ),
        ):
            is_installed, message = check_cursor_installed()

        assert is_installed is False


class TestLooksLikeRateLimit:
    def test_detects_429(self):
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_rate_limit_underscore(self):
        assert looks_like_rate_limit("rate_limit error") is True

    def test_detects_overloaded(self):
        assert looks_like_rate_limit("API is overloaded") is True

    def test_detects_too_many_requests(self):
        assert looks_like_rate_limit("too many requests") is True

    def test_detects_quota_exceeded(self):
        assert looks_like_rate_limit("quota exceeded for this account") is True

    def test_detects_throttling(self):
        assert looks_like_rate_limit("request throttled") is True

    def test_normal_output_returns_false(self):
        assert looks_like_rate_limit("Successfully generated code") is False

    def test_empty_string_returns_false(self):
        assert looks_like_rate_limit("") is False

    def test_none_output_returns_false(self):
        assert looks_like_rate_limit("") is False


class TestCursorStabilityMechanism:
    def test_startup_jitter_applied(self):
        client = CursorClient(enable_startup_jitter=True)

        with patch("ingot.integrations.cursor.time.sleep") as mock_sleep:
            client._apply_startup_jitter()

        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert CURSOR_STARTUP_DELAY_MIN_MS / 1000.0 <= delay <= CURSOR_STARTUP_DELAY_MAX_MS / 1000.0

    def test_startup_jitter_disabled(self):
        client = CursorClient(enable_startup_jitter=False)

        with patch("ingot.integrations.cursor.time.sleep") as mock_sleep:
            client._apply_startup_jitter()

        mock_sleep.assert_not_called()

    def test_spawn_retry_on_transient_error(self):
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True

        call_count = 0

        def mock_run():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False, "Error: socket in use"
            return True, "success"

        with patch("ingot.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is True
        assert output == "success"
        assert call_count == 2

    def test_spawn_retry_max_attempts_exceeded(self):
        client = CursorClient(enable_startup_jitter=False)

        def mock_run():
            return False, "Error: socket in use"

        with patch("ingot.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is False
        assert "socket in use" in output

    def test_spawn_retry_no_retry_on_non_transient_error(self):
        client = CursorClient(enable_startup_jitter=False)
        call_count = 0

        def mock_run():
            nonlocal call_count
            call_count += 1
            return False, "Error: invalid syntax in prompt"

        success, output = client._run_with_spawn_retry(mock_run)

        assert success is False
        assert call_count == 1

    def test_is_transient_spawn_error_patterns(self):
        client = CursorClient(enable_startup_jitter=False)

        assert client._is_transient_spawn_error("socket in use") is True
        assert client._is_transient_spawn_error("server busy") is True
        assert client._is_transient_spawn_error("EADDRINUSE") is True
        assert client._is_transient_spawn_error("connection refused") is True
        assert client._is_transient_spawn_error("spawn error occurred") is True
        assert client._is_transient_spawn_error("failed to start server") is True

        assert client._is_transient_spawn_error("normal error") is False
        assert client._is_transient_spawn_error("") is False

    def test_os_error_retry(self):
        client = CursorClient(enable_startup_jitter=False)

        call_count = 0

        def mock_run():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Too many open files")
            return True, "success"

        with patch("ingot.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is True
        assert output == "success"
        assert call_count == 2

    def test_os_error_exhausts_retries(self):
        client = CursorClient(enable_startup_jitter=False)

        def mock_run():
            raise OSError("Too many open files")

        with (
            patch("ingot.integrations.cursor.time.sleep"),
            pytest.raises(OSError, match="Too many open files"),
        ):
            client._run_with_spawn_retry(mock_run)


class TestCursorClientModeFlag:
    def _make_client(self) -> CursorClient:
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True
        return client

    def test_mode_added_when_supported(self):
        client = self._make_client()
        client._mode_flag_supported = True
        cmd = client.build_command("test", mode="plan")

        assert "--mode" in cmd
        mode_idx = cmd.index("--mode")
        assert cmd[mode_idx + 1] == "plan"

    def test_mode_omitted_when_not_supported(self):
        client = self._make_client()
        client._mode_flag_supported = False
        cmd = client.build_command("test", mode="plan")

        assert "--mode" not in cmd

    def test_degradation_logs_warning(self):
        import ingot.utils.logging as logging_mod

        logging_mod._logged_once_keys.discard("cursor_mode_unsupported")

        client = self._make_client()
        client._mode_flag_supported = False

        with patch("ingot.integrations.cursor.log_once") as mock_log_once:
            client.build_command("test", mode="plan")

        mock_log_once.assert_called_once()
        key_arg = mock_log_once.call_args[0][0]
        msg_arg = mock_log_once.call_args[0][1]
        assert key_arg == "cursor_mode_unsupported"
        assert "Warning" in msg_arg
        assert "--mode plan" in msg_arg
        assert "not supported" in msg_arg

    def test_no_warning_when_mode_none(self):
        client = self._make_client()
        client._mode_flag_supported = False

        with patch("ingot.integrations.cursor.log_once") as mock_log_once:
            client.build_command("test", mode=None)

        mock_log_once.assert_not_called()


class TestCursorClientModuleExports:
    def test_no_private_functions_exported(self):
        from ingot.integrations.cursor import __all__

        for name in __all__:
            assert not name.startswith("_"), f"Private name '{name}' should not be in __all__"

    def test_expected_exports(self):
        from ingot.integrations.cursor import __all__

        assert set(__all__) == {
            "CURSOR_CLI_NAME",
            "CURSOR_SPAWN_MAX_RETRIES",
            "CURSOR_SPAWN_RETRY_DELAY_S",
            "CURSOR_STARTUP_DELAY_MAX_MS",
            "CURSOR_STARTUP_DELAY_MIN_MS",
            "CursorClient",
            "check_cursor_installed",
            "looks_like_rate_limit",
        }
