"""Tests for spec.integrations.cursor module - CursorClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.cursor import (
    CURSOR_STARTUP_DELAY_MAX_MS,
    CURSOR_STARTUP_DELAY_MIN_MS,
    CursorClient,
    check_cursor_installed,
    looks_like_rate_limit,
)


class TestCursorClientDetectCliCommand:
    """Tests for CursorClient._detect_cli_command()."""

    def test_detects_cursor_when_available(self):
        """Detects 'cursor' when it's in PATH."""
        client = CursorClient(enable_startup_jitter=False)

        with patch("spec.integrations.cursor.shutil.which", side_effect=lambda x: x == "cursor"):
            cmd = client._detect_cli_command()

        assert cmd == "cursor"

    def test_falls_back_to_agent(self):
        """Falls back to 'agent' when 'cursor' not found."""
        client = CursorClient(enable_startup_jitter=False)

        def which_side_effect(name):
            if name == "agent":
                return "/usr/local/bin/agent"
            return None

        with patch("spec.integrations.cursor.shutil.which", side_effect=which_side_effect):
            cmd = client._detect_cli_command()

        assert cmd == "agent"

    def test_defaults_to_cursor_when_nothing_found(self):
        """Defaults to 'cursor' when neither command is found."""
        client = CursorClient(enable_startup_jitter=False)

        with patch("spec.integrations.cursor.shutil.which", return_value=None):
            cmd = client._detect_cli_command()

        assert cmd == "cursor"

    def test_caches_result(self):
        """Result is cached after first detection."""
        client = CursorClient(enable_startup_jitter=False)

        with patch(
            "spec.integrations.cursor.shutil.which", return_value="/usr/local/bin/cursor"
        ) as mock_which:
            client._detect_cli_command()
            client._detect_cli_command()

        # which() should only be called once (for "cursor"), then cached
        assert mock_which.call_count == 1


class TestCursorClientSupportsModelFlag:
    """Tests for CursorClient._supports_model_flag()."""

    def test_supports_model_when_in_help(self):
        """Returns True when --model is in --help output."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "Options:\n  --model <model>  Specify model\n  --help"
        mock_result.stderr = ""

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            assert client._supports_model_flag() is True

    def test_no_model_when_not_in_help(self):
        """Returns False when --model is not in --help output."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "Options:\n  --print  Print mode\n  --help"
        mock_result.stderr = ""

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            assert client._supports_model_flag() is False

    def test_caches_result(self):
        """Result is cached per session."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        mock_result = MagicMock()
        mock_result.stdout = "--model"
        mock_result.stderr = ""

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result) as mock_run:
            client._supports_model_flag()
            client._supports_model_flag()

        assert mock_run.call_count == 1

    def test_returns_false_on_exception(self):
        """Returns False if --help check fails."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"

        with patch(
            "spec.integrations.cursor.subprocess.run",
            side_effect=OSError("command not found"),
        ):
            assert client._supports_model_flag() is False


class TestCursorClientBuildCommand:
    """Tests for CursorClient.build_command() method."""

    def _make_client(self, model: str = "") -> CursorClient:
        """Create a CursorClient with predictable CLI detection."""
        client = CursorClient(model=model, enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True
        return client

    def test_basic_structure(self):
        """Basic command: cursor --print <prompt>."""
        client = self._make_client()
        cmd = client.build_command("test prompt", print_mode=True)

        assert cmd[0] == "cursor"
        assert "--print" in cmd
        assert cmd[-1] == "test prompt"

    def test_model_flag_when_model_set(self):
        """--model flag included when model is set on client."""
        client = self._make_client(model="gpt-4")
        cmd = client.build_command("test prompt", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "gpt-4"

    def test_model_flag_when_model_passed(self):
        """--model flag uses per-call model override."""
        client = self._make_client()
        cmd = client.build_command("test prompt", model="claude-3-sonnet", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-3-sonnet"

    def test_no_save_flag(self):
        """--no-save when no_save=True."""
        client = self._make_client()
        cmd = client.build_command("test prompt", no_save=True, print_mode=True)

        assert "--no-save" in cmd

    def test_no_save_flag_absent(self):
        """No --no-save when no_save=False."""
        client = self._make_client()
        cmd = client.build_command("test prompt", no_save=False, print_mode=True)

        assert "--no-save" not in cmd

    def test_all_flags_combined(self):
        """All flags work together correctly."""
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
        """Command without --print flag when print_mode=False."""
        client = self._make_client()
        cmd = client.build_command("test prompt", print_mode=False)

        assert "--print" not in cmd
        assert cmd[-1] == "test prompt"

    def test_prompt_is_last_argument(self):
        """Prompt is always the last positional argument."""
        client = self._make_client(model="gpt-4")
        cmd = client.build_command(
            "my prompt here",
            print_mode=True,
            no_save=True,
        )

        assert cmd[-1] == "my prompt here"

    def test_explicit_model_overrides_instance_default(self):
        """Per-call model takes precedence over instance default."""
        client = self._make_client(model="default-model")
        cmd = client.build_command("test", model="override-model", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"

    def test_model_flag_skipped_when_not_supported(self):
        """--model flag is skipped when CLI doesn't support it."""
        client = CursorClient(model="gpt-4", enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = False

        cmd = client.build_command("test prompt", print_mode=True)

        assert "--model" not in cmd


class TestCursorClientExecution:
    """Tests for CursorClient execution methods with mocked subprocess."""

    def _make_client(self) -> CursorClient:
        """Create a CursorClient with predictable settings."""
        client = CursorClient(enable_startup_jitter=False)
        client._cli_command = "cursor"
        client._model_flag_supported = True
        return client

    def test_run_with_callback_streams_output(self):
        """run_with_callback streams output via Popen."""
        client = self._make_client()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch("spec.integrations.cursor.subprocess.Popen", return_value=mock_process):
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
        """run_with_callback returns False on non-zero exit code."""
        client = self._make_client()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = None

        with patch("spec.integrations.cursor.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is False
        assert "error output" in output

    def test_run_print_with_output_returns_tuple(self):
        """run_print_with_output returns (success, output) tuple."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_does_not_print_to_stdout(self, capsys):
        """run_print_with_output does NOT print to stdout."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            client.run_print_with_output("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_with_output_includes_stderr_on_failure(self):
        """run_print_with_output includes stderr when CLI fails with empty stdout."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: invalid model"
        mock_result.returncode = 1

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: invalid model" in output

    def test_run_print_with_output_prefers_stdout_even_on_failure(self):
        """run_print_with_output returns stdout when present even on failure."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "partial output"
        mock_result.stderr = "some error"
        mock_result.returncode = 1

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert output == "partial output"

    def test_run_print_quiet_returns_output_string(self):
        """run_print_quiet returns output string only."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_quiet_empty_output(self):
        """run_print_quiet returns empty string on None stdout."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == ""

    def test_run_print_quiet_includes_stderr_on_failure(self):
        """run_print_quiet includes stderr when CLI fails with no stdout."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: rate limit exceeded"
        mock_result.returncode = 1

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert "Error: rate limit exceeded" in output

    def test_run_print_quiet_does_not_print_to_stdout(self, capsys):
        """run_print_quiet does NOT print to stdout."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result):
            client.run_print_quiet("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_quiet_passes_timeout_to_subprocess(self):
        """timeout_seconds is forwarded to subprocess.run(timeout=)."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result) as mock_run:
            client.run_print_quiet("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        """subprocess.TimeoutExpired propagates from run_print_quiet."""
        client = self._make_client()

        with (
            patch(
                "spec.integrations.cursor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=5),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_quiet("test", timeout_seconds=5.0)

    def test_run_print_with_output_passes_timeout_to_subprocess(self):
        """timeout_seconds is forwarded to subprocess.run(timeout=)."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result) as mock_run:
            client.run_print_with_output("test", timeout_seconds=45.0)

        assert mock_run.call_args.kwargs.get("timeout") == 45.0

    def test_run_print_with_output_timeout_raises_timeout_expired(self):
        """subprocess.TimeoutExpired propagates from run_print_with_output."""
        client = self._make_client()

        with (
            patch(
                "spec.integrations.cursor.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=10),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_with_output("test", timeout_seconds=10.0)

    def test_run_print_quiet_no_timeout_by_default(self):
        """No timeout passed to subprocess.run when timeout_seconds is None."""
        client = self._make_client()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("spec.integrations.cursor.subprocess.run", return_value=mock_result) as mock_run:
            client.run_print_quiet("test")

        assert mock_run.call_args.kwargs.get("timeout") is None


class TestCheckCursorInstalled:
    """Tests for check_cursor_installed() function."""

    def test_installed_returns_true_and_version(self):
        """Returns (True, version) when CLI is installed."""
        with (
            patch(
                "spec.integrations.cursor.shutil.which",
                side_effect=lambda x: "/usr/local/bin/cursor" if x == "cursor" else None,
            ),
            patch(
                "spec.integrations.cursor.subprocess.run",
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
        """Returns (False, message) when CLI is not in PATH."""
        with patch("spec.integrations.cursor.shutil.which", return_value=None):
            is_installed, message = check_cursor_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message

    def test_agent_fallback_detected(self):
        """Falls back to 'agent' CLI when 'cursor' not found."""

        def which_side_effect(name):
            if name == "agent":
                return "/usr/local/bin/agent"
            return None

        with (
            patch("spec.integrations.cursor.shutil.which", side_effect=which_side_effect),
            patch(
                "spec.integrations.cursor.subprocess.run",
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
        """Returns (False, message) when version check fails for all CLIs."""

        def which_side_effect(name):
            if name == "cursor":
                return "/usr/local/bin/cursor"
            return None

        with (
            patch("spec.integrations.cursor.shutil.which", side_effect=which_side_effect),
            patch(
                "spec.integrations.cursor.subprocess.run",
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
    """Tests for looks_like_rate_limit() function."""

    def test_detects_429(self):
        """Detects HTTP 429 status code."""
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        """Detects 'rate limit' text."""
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_rate_limit_underscore(self):
        """Detects 'rate_limit' text."""
        assert looks_like_rate_limit("rate_limit error") is True

    def test_detects_overloaded(self):
        """Detects 'overloaded'."""
        assert looks_like_rate_limit("API is overloaded") is True

    def test_detects_too_many_requests(self):
        """Detects 'too many requests'."""
        assert looks_like_rate_limit("too many requests") is True

    def test_detects_quota_exceeded(self):
        """Detects 'quota exceeded'."""
        assert looks_like_rate_limit("quota exceeded for this account") is True

    def test_detects_throttling(self):
        """Detects 'throttl' prefix (throttle, throttling, throttled)."""
        assert looks_like_rate_limit("request throttled") is True

    def test_normal_output_returns_false(self):
        """Normal output returns False."""
        assert looks_like_rate_limit("Successfully generated code") is False

    def test_empty_string_returns_false(self):
        """Empty string returns False."""
        assert looks_like_rate_limit("") is False

    def test_none_output_returns_false(self):
        """None output returns False without raising."""
        assert looks_like_rate_limit(None) is False


class TestCursorStabilityMechanism:
    """Tests for CursorClient stability mechanisms."""

    def test_startup_jitter_applied(self):
        """Startup jitter calls time.sleep with appropriate delay."""
        client = CursorClient(enable_startup_jitter=True)

        with patch("spec.integrations.cursor.time.sleep") as mock_sleep:
            client._apply_startup_jitter()

        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert CURSOR_STARTUP_DELAY_MIN_MS / 1000.0 <= delay <= CURSOR_STARTUP_DELAY_MAX_MS / 1000.0

    def test_startup_jitter_disabled(self):
        """No jitter when enable_startup_jitter=False."""
        client = CursorClient(enable_startup_jitter=False)

        with patch("spec.integrations.cursor.time.sleep") as mock_sleep:
            client._apply_startup_jitter()

        mock_sleep.assert_not_called()

    def test_spawn_retry_on_transient_error(self):
        """Retries on transient spawn errors."""
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

        with patch("spec.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is True
        assert output == "success"
        assert call_count == 2

    def test_spawn_retry_max_attempts_exceeded(self):
        """Returns failure after max retry attempts."""
        client = CursorClient(enable_startup_jitter=False)

        def mock_run():
            return False, "Error: socket in use"

        with patch("spec.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is False
        assert "socket in use" in output

    def test_spawn_retry_no_retry_on_non_transient_error(self):
        """Does not retry on non-transient errors."""
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
        """Detects all transient spawn error patterns."""
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
        """Retries on OSError (e.g., too many open files)."""
        client = CursorClient(enable_startup_jitter=False)

        call_count = 0

        def mock_run():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Too many open files")
            return True, "success"

        with patch("spec.integrations.cursor.time.sleep"):
            success, output = client._run_with_spawn_retry(mock_run)

        assert success is True
        assert output == "success"
        assert call_count == 2

    def test_os_error_exhausts_retries(self):
        """OSError that persists raises after exhausting retries."""
        client = CursorClient(enable_startup_jitter=False)

        def mock_run():
            raise OSError("Too many open files")

        with (
            patch("spec.integrations.cursor.time.sleep"),
            pytest.raises(OSError, match="Too many open files"),
        ):
            client._run_with_spawn_retry(mock_run)


class TestCursorClientModuleExports:
    """Tests for __all__ exports."""

    def test_no_private_functions_exported(self):
        """No underscore-prefixed names in __all__."""
        from spec.integrations.cursor import __all__

        for name in __all__:
            assert not name.startswith("_"), f"Private name '{name}' should not be in __all__"

    def test_expected_exports(self):
        """Only expected public names are exported."""
        from spec.integrations.cursor import __all__

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
