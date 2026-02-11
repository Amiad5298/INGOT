"""Tests for ingot.integrations.codex module - CodexClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.codex import (
    CodexClient,
    check_codex_installed,
    looks_like_rate_limit,
)


class TestCodexClientBuildCommand:
    def test_basic_structure(self):
        client = CodexClient()
        cmd = client.build_command("test prompt")

        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--full-auto" in cmd
        assert cmd[-1] == "test prompt"

    def test_model_flag_when_model_set(self):
        client = CodexClient(model="o3")
        cmd = client.build_command("test prompt")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "o3"

    def test_model_flag_when_model_passed(self):
        client = CodexClient()
        cmd = client.build_command("test prompt", model="o4-mini")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "o4-mini"

    def test_explicit_model_overrides_instance_default(self):
        client = CodexClient(model="default-model")
        cmd = client.build_command("test", model="override-model")

        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"

    def test_ephemeral_flag(self):
        client = CodexClient()
        cmd = client.build_command("test prompt", ephemeral=True)

        assert "--ephemeral" in cmd

    def test_no_ephemeral_by_default(self):
        client = CodexClient()
        cmd = client.build_command("test prompt")

        assert "--ephemeral" not in cmd

    def test_full_auto_flag(self):
        client = CodexClient()
        cmd = client.build_command("test prompt", full_auto=True)

        assert "--full-auto" in cmd

    def test_no_full_auto(self):
        client = CodexClient()
        cmd = client.build_command("test prompt", full_auto=False)

        assert "--full-auto" not in cmd

    def test_no_model_when_empty(self):
        client = CodexClient()
        cmd = client.build_command("test prompt")

        assert "--model" not in cmd

    def test_prompt_is_last_argument(self):
        client = CodexClient(model="o3")
        cmd = client.build_command(
            "my prompt here",
            ephemeral=True,
        )

        assert cmd[-1] == "my prompt here"


class TestCodexClientExecution:
    def test_run_with_callback_streams_output(self):
        client = CodexClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch("ingot.integrations.codex.subprocess.Popen", return_value=mock_process):
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
        client = CodexClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = None

        with patch("ingot.integrations.codex.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is False
        assert "error output" in output

    def test_run_print_with_output_returns_tuple(self):
        client = CodexClient()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.returncode = 0

        with patch("ingot.integrations.codex.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_uses_stdout_for_stderr(self):
        """Codex merges stderr into stdout, so output includes both."""
        client = CodexClient()

        mock_result = MagicMock()
        mock_result.stdout = "Error: something failed\n"
        mock_result.returncode = 1

        with patch("ingot.integrations.codex.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: something failed" in output

    def test_run_print_quiet_returns_output_string(self):
        client = CodexClient()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.returncode = 0

        with patch("ingot.integrations.codex.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_with_output_passes_timeout(self):
        client = CodexClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.returncode = 0

        with patch("ingot.integrations.codex.subprocess.run", return_value=mock_result) as mock_run:
            client.run_print_with_output("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        client = CodexClient()

        with (
            patch(
                "ingot.integrations.codex.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=5),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_quiet("test", timeout_seconds=5.0)

    def test_run_with_callback_merges_stderr(self):
        """Verify that Popen is called with stderr=subprocess.STDOUT."""
        client = CodexClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch(
            "ingot.integrations.codex.subprocess.Popen", return_value=mock_process
        ) as mock_popen:
            client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs.get("stderr") == subprocess.STDOUT


class TestCheckCodexInstalled:
    def test_installed_returns_true_and_version(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/codex",
            ),
            patch(
                "ingot.utils.logging.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="codex 1.0.0",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_codex_installed()

        assert is_installed is True
        assert "1.0.0" in message

    def test_not_installed_returns_false(self):
        with patch("ingot.utils.logging.shutil.which", return_value=None):
            is_installed, message = check_codex_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message

    def test_version_check_failure(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/codex",
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
            is_installed, message = check_codex_installed()

        assert is_installed is False


class TestCodexLooksLikeRateLimit:
    def test_detects_429(self):
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_overloaded(self):
        assert looks_like_rate_limit("API is overloaded") is True

    def test_detects_capacity(self):
        assert looks_like_rate_limit("server at capacity") is True

    def test_detects_server_error(self):
        assert looks_like_rate_limit("server_error: internal failure") is True

    def test_normal_output_returns_false(self):
        assert looks_like_rate_limit("Successfully generated code") is False

    def test_empty_string_returns_false(self):
        assert looks_like_rate_limit("") is False

    def test_none_output_returns_false(self):
        assert looks_like_rate_limit("") is False


class TestCodexClientModuleExports:
    def test_expected_exports(self):
        from ingot.integrations.codex import __all__

        assert set(__all__) == {
            "CODEX_CLI_NAME",
            "CodexClient",
            "check_codex_installed",
            "looks_like_rate_limit",
        }
