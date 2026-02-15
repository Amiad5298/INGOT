"""Tests for ingot.integrations.aider module - AiderClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.aider import (
    AiderClient,
    check_aider_installed,
    looks_like_rate_limit,
)


class TestAiderClientBuildCommand:
    def test_basic_structure(self):
        client = AiderClient()
        cmd = client.build_command("test prompt")

        assert cmd[0] == "aider"
        assert "--yes-always" in cmd
        assert "--no-auto-commits" in cmd
        assert "--no-detect-urls" in cmd
        assert "--message" in cmd
        assert cmd[-1] == "test prompt"

    def test_model_flag_when_model_set(self):
        client = AiderClient(model="gpt-4")
        cmd = client.build_command("test prompt")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "gpt-4"

    def test_model_flag_when_model_passed(self):
        client = AiderClient()
        cmd = client.build_command("test prompt", model="claude-3-sonnet")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-3-sonnet"

    def test_explicit_model_overrides_instance_default(self):
        client = AiderClient(model="default-model")
        cmd = client.build_command("test", model="override-model")

        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"

    def test_message_file_flag(self):
        client = AiderClient()
        cmd = client.build_command("test prompt", message_file="/tmp/prompt.md")

        assert "--message-file" in cmd
        file_idx = cmd.index("--message-file")
        assert cmd[file_idx + 1] == "/tmp/prompt.md"
        assert "--message" not in cmd

    def test_no_model_when_empty(self):
        client = AiderClient()
        cmd = client.build_command("test prompt")

        assert "--model" not in cmd

    def test_prompt_as_message_when_no_file(self):
        client = AiderClient()
        cmd = client.build_command("my prompt here")

        msg_idx = cmd.index("--message")
        assert cmd[msg_idx + 1] == "my prompt here"


class TestAiderClientExecution:
    def test_run_with_callback_streams_output(self):
        client = AiderClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with (
            patch("ingot.integrations.aider.subprocess.Popen", return_value=mock_process),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_tmp.return_value.__enter__ = MagicMock(return_value=MagicMock(name="/tmp/test.md"))
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

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
        client = AiderClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = None

        with (
            patch("ingot.integrations.aider.subprocess.Popen", return_value=mock_process),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is False
        assert "error output" in output

    def test_run_print_with_output_returns_tuple(self):
        client = AiderClient()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with (
            patch("ingot.integrations.aider.subprocess.run", return_value=mock_result),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_includes_stderr_on_failure(self):
        client = AiderClient()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: invalid model"
        mock_result.returncode = 1

        with (
            patch("ingot.integrations.aider.subprocess.run", return_value=mock_result),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: invalid model" in output

    def test_run_print_quiet_returns_output_string(self):
        client = AiderClient()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with (
            patch("ingot.integrations.aider.subprocess.run", return_value=mock_result),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_quiet_includes_stderr_on_failure(self):
        client = AiderClient()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: rate limit exceeded"
        mock_result.returncode = 1

        with (
            patch("ingot.integrations.aider.subprocess.run", return_value=mock_result),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            output = client.run_print_quiet("test prompt")

        assert "Error: rate limit exceeded" in output

    def test_run_print_with_output_passes_timeout(self):
        client = AiderClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with (
            patch("ingot.integrations.aider.subprocess.run", return_value=mock_result) as mock_run,
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            client.run_print_with_output("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        client = AiderClient()

        with (
            patch(
                "ingot.integrations.aider.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["aider"], timeout=5),
            ),
            patch("ingot.integrations.aider.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("ingot.integrations.aider.Path") as mock_path,
            pytest.raises(subprocess.TimeoutExpired),
        ):
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.md"
            mock_tmp.return_value = mock_file
            mock_path.return_value.unlink = MagicMock()

            client.run_print_quiet("test", timeout_seconds=5.0)


class TestCheckAiderInstalled:
    def test_installed_returns_true_and_version(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/aider",
            ),
            patch(
                "ingot.utils.logging.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="aider 0.50.0",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_aider_installed()

        assert is_installed is True
        assert "0.50.0" in message

    def test_not_installed_returns_false(self):
        with patch("ingot.utils.logging.shutil.which", return_value=None):
            is_installed, message = check_aider_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message

    def test_version_check_failure(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/aider",
            ),
            patch(
                "ingot.utils.logging.subprocess.run",
                return_value=MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="error",
                ),
            ),
        ):
            is_installed, message = check_aider_installed()

        assert is_installed is False


class TestLooksLikeRateLimit:
    def test_detects_429(self):
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_rate_limit_underscore(self):
        assert looks_like_rate_limit("rate_limit error") is True

    def test_detects_capacity(self):
        assert looks_like_rate_limit("API at capacity") is True

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


class TestAiderClientChatMode:
    def test_chat_mode_ask_adds_flag(self):
        client = AiderClient()
        cmd = client.build_command("test prompt", chat_mode="ask")

        assert "--chat-mode" in cmd
        mode_idx = cmd.index("--chat-mode")
        assert cmd[mode_idx + 1] == "ask"

    def test_chat_mode_none_omits_flag(self):
        client = AiderClient()
        cmd = client.build_command("test prompt", chat_mode=None)

        assert "--chat-mode" not in cmd

    def test_architect_flag_never_generated(self):
        client = AiderClient()

        # With chat_mode
        cmd_ask = client.build_command("test", chat_mode="ask")
        assert "--architect" not in cmd_ask

        # Without chat_mode
        cmd_none = client.build_command("test")
        assert "--architect" not in cmd_none

    def test_chat_mode_with_model_and_message_file(self):
        client = AiderClient()
        cmd = client.build_command(
            "test prompt",
            model="gpt-4",
            message_file="/tmp/prompt.md",
            chat_mode="ask",
        )

        assert "--chat-mode" in cmd
        mode_idx = cmd.index("--chat-mode")
        assert cmd[mode_idx + 1] == "ask"
        assert "--model" in cmd
        assert "--message-file" in cmd


class TestAiderClientModuleExports:
    def test_no_private_functions_exported(self):
        from ingot.integrations.aider import __all__

        for name in __all__:
            assert not name.startswith("_"), f"Private name '{name}' should not be in __all__"

    def test_expected_exports(self):
        from ingot.integrations.aider import __all__

        assert set(__all__) == {
            "AIDER_CLI_NAME",
            "AiderChatMode",
            "AiderClient",
            "check_aider_installed",
            "looks_like_rate_limit",
        }
