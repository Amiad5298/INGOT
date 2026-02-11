"""Tests for ingot.integrations.gemini module - GeminiClient class."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.gemini import (
    GeminiClient,
    check_gemini_installed,
    looks_like_rate_limit,
)


class TestGeminiClientBuildCommand:
    def test_basic_structure(self):
        client = GeminiClient()
        cmd = client.build_command("test prompt")

        assert cmd[0] == "gemini"
        assert "--approval-mode=yolo" in cmd
        assert "-p" in cmd
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "test prompt"

    def test_model_flag_when_model_set(self):
        client = GeminiClient(model="gemini-2.5-pro")
        cmd = client.build_command("test prompt")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "gemini-2.5-pro"

    def test_model_flag_when_model_passed(self):
        client = GeminiClient()
        cmd = client.build_command("test prompt", model="gemini-2.5-flash")

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "gemini-2.5-flash"

    def test_explicit_model_overrides_instance_default(self):
        client = GeminiClient(model="default-model")
        cmd = client.build_command("test", model="override-model")

        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "override-model"

    def test_no_model_when_empty(self):
        client = GeminiClient()
        cmd = client.build_command("test prompt")

        assert "--model" not in cmd


class TestGeminiClientEnvHandling:
    def test_build_env_with_overrides(self):
        client = GeminiClient()
        env = client._build_env({"GEMINI_SYSTEM_MD": "/tmp/system.md"})

        assert env is not None
        assert "GEMINI_SYSTEM_MD" in env
        assert env["GEMINI_SYSTEM_MD"] == "/tmp/system.md"

    def test_build_env_without_overrides(self):
        client = GeminiClient()
        env = client._build_env(None)

        assert env is None

    def test_build_env_empty_dict(self):
        client = GeminiClient()
        env = client._build_env({})

        assert env is None


class TestGeminiClientExecution:
    def test_run_with_callback_streams_output(self):
        client = GeminiClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch("ingot.integrations.gemini.subprocess.Popen", return_value=mock_process):
            success, output = client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        assert success is True
        assert "line 1" in output
        assert "line 2" in output
        assert mock_callback.call_count == 2

    def test_run_with_callback_passes_env(self):
        client = GeminiClient()
        mock_callback = MagicMock()

        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.returncode = 0
        mock_process.wait.return_value = None

        with patch(
            "ingot.integrations.gemini.subprocess.Popen", return_value=mock_process
        ) as mock_popen:
            client.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                env={"GEMINI_SYSTEM_MD": "/tmp/system.md"},
            )

        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs.get("env") is not None
        assert "GEMINI_SYSTEM_MD" in call_kwargs["env"]

    def test_run_print_with_output_returns_tuple(self):
        client = GeminiClient()

        mock_result = MagicMock()
        mock_result.stdout = "response line\n"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.gemini.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is True
        assert "response line" in output

    def test_run_print_with_output_includes_stderr_on_failure(self):
        client = GeminiClient()

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Error: invalid model"
        mock_result.returncode = 1

        with patch("ingot.integrations.gemini.subprocess.run", return_value=mock_result):
            success, output = client.run_print_with_output("test prompt")

        assert success is False
        assert "Error: invalid model" in output

    def test_run_print_with_output_passes_env(self):
        client = GeminiClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.gemini.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_with_output(
                "test",
                env={"GEMINI_SYSTEM_MD": "/tmp/system.md"},
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") is not None
        assert "GEMINI_SYSTEM_MD" in call_kwargs["env"]

    def test_run_print_quiet_returns_output_string(self):
        client = GeminiClient()

        mock_result = MagicMock()
        mock_result.stdout = "quiet output content"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("ingot.integrations.gemini.subprocess.run", return_value=mock_result):
            output = client.run_print_quiet("test prompt")

        assert output == "quiet output content"

    def test_run_print_with_output_passes_timeout(self):
        client = GeminiClient()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch(
            "ingot.integrations.gemini.subprocess.run", return_value=mock_result
        ) as mock_run:
            client.run_print_with_output("test", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout") == 30.0

    def test_run_print_quiet_timeout_raises_timeout_expired(self):
        client = GeminiClient()

        with (
            patch(
                "ingot.integrations.gemini.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=5),
            ),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            client.run_print_quiet("test", timeout_seconds=5.0)


class TestCheckGeminiInstalled:
    def test_installed_returns_true_and_version(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/gemini",
            ),
            patch(
                "ingot.utils.logging.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout="gemini 1.0.0",
                    stderr="",
                ),
            ),
        ):
            is_installed, message = check_gemini_installed()

        assert is_installed is True
        assert "1.0.0" in message

    def test_not_installed_returns_false(self):
        with patch("ingot.utils.logging.shutil.which", return_value=None):
            is_installed, message = check_gemini_installed()

        assert is_installed is False
        assert "not installed" in message.lower() or "not in PATH" in message

    def test_version_check_failure(self):
        with (
            patch(
                "ingot.utils.logging.shutil.which",
                return_value="/usr/local/bin/gemini",
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
            is_installed, message = check_gemini_installed()

        assert is_installed is False


class TestGeminiLooksLikeRateLimit:
    def test_detects_429(self):
        assert looks_like_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit(self):
        assert looks_like_rate_limit("rate limit exceeded") is True

    def test_detects_resource_exhausted(self):
        assert looks_like_rate_limit("RESOURCE_EXHAUSTED: quota exceeded") is True

    def test_detects_overloaded(self):
        assert looks_like_rate_limit("API is overloaded") is True

    def test_detects_403_quota(self):
        assert looks_like_rate_limit("HTTP 403 Quota exceeded") is True

    def test_normal_output_returns_false(self):
        assert looks_like_rate_limit("Successfully generated code") is False

    def test_empty_string_returns_false(self):
        assert looks_like_rate_limit("") is False

    def test_none_output_returns_false(self):
        assert looks_like_rate_limit("") is False


class TestGeminiClientModuleExports:
    def test_expected_exports(self):
        from ingot.integrations.gemini import __all__

        assert set(__all__) == {
            "GEMINI_CLI_NAME",
            "GeminiClient",
            "check_gemini_installed",
            "looks_like_rate_limit",
        }
