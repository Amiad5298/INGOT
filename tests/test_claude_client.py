"""Tests for ingot.integrations.claude module - ClaudeClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.claude import (
    CLAUDE_CLI_NAME,
    ClaudeClient,
    check_claude_installed,
    looks_like_rate_limit,
)


class TestClaudeClientBuildCommand:
    def test_basic_structure(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", print_mode=True)

        assert cmd[0] == CLAUDE_CLI_NAME
        assert "-p" in cmd
        assert cmd[-1] == "test prompt"

    def test_model_flag_when_model_set(self):
        client = ClaudeClient(model="claude-3-opus")
        cmd = client.build_command("test prompt", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-3-opus"

    def test_model_flag_when_model_passed(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", model="claude-3-sonnet", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "claude-3-sonnet"

    def test_no_session_persistence_flag(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", dont_save_session=True, print_mode=True)

        assert "--no-session-persistence" in cmd

    def test_no_session_persistence_flag_absent(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", dont_save_session=False, print_mode=True)

        assert "--no-session-persistence" not in cmd

    def test_system_prompt_file_flag(self):
        client = ClaudeClient()
        cmd = client.build_command(
            "test prompt",
            system_prompt_file="/tmp/prompt.md",
            print_mode=True,
        )

        assert "--append-system-prompt-file" in cmd
        idx = cmd.index("--append-system-prompt-file")
        assert cmd[idx + 1] == "/tmp/prompt.md"

    def test_no_system_prompt_file_when_none(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", print_mode=True)

        assert "--append-system-prompt-file" not in cmd

    def test_no_system_prompt_file_when_empty(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", system_prompt_file="", print_mode=True)

        assert "--append-system-prompt-file" not in cmd

    def test_all_flags_combined(self):
        client = ClaudeClient()
        cmd = client.build_command(
            "do the work",
            system_prompt_file="/tmp/prompt.md",
            model="claude-3-opus",
            print_mode=True,
            dont_save_session=True,
        )

        assert cmd[0] == CLAUDE_CLI_NAME
        assert "-p" in cmd
        assert "--model" in cmd
        assert "--no-session-persistence" in cmd
        assert "--append-system-prompt-file" in cmd
        assert cmd[-1] == "do the work"

    def test_no_print_mode(self):
        client = ClaudeClient()
        cmd = client.build_command("test prompt", print_mode=False)

        assert "-p" not in cmd
        assert cmd[-1] == "test prompt"

    def test_prompt_is_last_argument(self):
        client = ClaudeClient(model="claude-3-opus")
        cmd = client.build_command(
            "my prompt here",
            print_mode=True,
            dont_save_session=True,
        )

        assert cmd[-1] == "my prompt here"

    def test_explicit_model_overrides_instance_default(self):
        client = ClaudeClient(model="default-model")
        cmd = client.build_command("test", model="override-model", print_mode=True)

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"


class TestClaudeClientExecution:
    def test_run_with_callback_streams_output(self):
        client = ClaudeClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch("ingot.integrations.claude.subprocess.Popen", return_value=mock_process):
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
        client = ClaudeClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = None

        with patch("ingot.integrations.claude.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is False
        assert "error output" in output

    def test_run_print_with_output_returns_tuple(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_does_not_print_to_stdout(self, capsys):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            client.run_print_with_output("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_with_output_includes_stderr_on_failure(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: invalid model"
        mock_result.returncode = 1

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: invalid model" in output

    def test_run_print_with_output_prefers_stdout_even_on_failure(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "partial output"
        mock_result.stderr = "some error"
        mock_result.returncode = 1

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert output == "partial output"

    def test_run_print_quiet_returns_output_string(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_quiet_empty_output(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == ""

    def test_run_print_quiet_includes_stderr_on_failure(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: rate limit exceeded"
        mock_result.returncode = 1

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert "Error: rate limit exceeded" in output

    def test_run_print_quiet_does_not_print_to_stdout(self, capsys):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "some output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.claude.subprocess.run", return_value=mock_result):
            client.run_print_quiet("test prompt")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_run_print_quiet_passes_timeout_to_subprocess(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.claude.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_quiet("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        client = ClaudeClient()

        with (
            patch(
                "ingot.integrations.claude.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=5),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_quiet("test", timeout_seconds=5.0)

    def test_run_print_with_output_passes_timeout_to_subprocess(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.claude.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_with_output("test", timeout_seconds=45.0)

        assert mock_run.call_args.kwargs.get("timeout") == 45.0

    def test_run_print_with_output_timeout_raises_timeout_expired(self):
        client = ClaudeClient()

        with (
            patch(
                "ingot.integrations.claude.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=10),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_with_output("test", timeout_seconds=10.0)

    def test_run_print_quiet_uses_system_prompt_file(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.claude.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_quiet("test", system_prompt="You are a planner.")

        cmd = mock_run.call_args[0][0]
        assert "--append-system-prompt-file" in cmd
        # Inline --append-system-prompt should NOT be used
        assert "--append-system-prompt" not in [
            c for i, c in enumerate(cmd) if c == "--append-system-prompt"
        ]

    def test_run_print_with_output_uses_system_prompt_file(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.claude.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_with_output("test", system_prompt="You are a planner.")

        cmd = mock_run.call_args[0][0]
        assert "--append-system-prompt-file" in cmd

    def test_run_print_quiet_no_timeout_by_default(self):
        client = ClaudeClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.claude.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_quiet("test")

        assert mock_run.call_args.kwargs.get("timeout") is None


class TestCheckClaudeInstalled:
    def test_installed_returns_true_and_version(self):
        with (
            patch("ingot.integrations.claude.shutil.which", return_value="/usr/local/bin/claude"),
            patch(
                "ingot.integrations.claude.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="claude 1.0.0",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_claude_installed()

        assert is_installed is True
        assert "1.0.0" in message

    def test_not_installed_returns_false(self):
        with patch("ingot.integrations.claude.shutil.which", return_value=None):
            is_installed, message = check_claude_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message


class TestLooksLikeRateLimit:
    def test_detects_429(self):
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_overloaded(self):
        assert looks_like_rate_limit("API is overloaded") is True

    def test_detects_529(self):
        assert looks_like_rate_limit("Error 529") is True

    def test_detects_quota_exceeded(self):
        assert looks_like_rate_limit("quota exceeded for this account") is True

    def test_detects_throttling(self):
        assert looks_like_rate_limit("request throttled") is True

    def test_detects_capacity(self):
        assert looks_like_rate_limit("insufficient capacity") is True

    def test_does_not_detect_502(self):
        assert looks_like_rate_limit("502 Bad Gateway") is False

    def test_does_not_detect_503(self):
        assert looks_like_rate_limit("503 Service Unavailable") is False

    def test_does_not_detect_504(self):
        assert looks_like_rate_limit("504 Gateway Timeout") is False

    def test_normal_output_returns_false(self):
        assert looks_like_rate_limit("Successfully generated code") is False

    def test_none_output_returns_false(self):
        assert looks_like_rate_limit("") is False

    def test_empty_string_returns_false(self):
        assert looks_like_rate_limit("") is False


class TestClaudeClientModuleExports:
    def test_no_private_functions_exported(self):
        from ingot.integrations.claude import __all__

        for name in __all__:
            assert not name.startswith("_"), f"Private name '{name}' should not be in __all__"

    def test_expected_exports(self):
        from ingot.integrations.claude import __all__

        assert set(__all__) == {
            "CLAUDE_CLI_NAME",
            "ClaudeClient",
            "check_claude_installed",
            "looks_like_rate_limit",
        }
