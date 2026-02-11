"""Tests for ingot.integrations.backends.gemini module - GeminiBackend class."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends import AIBackend, GeminiBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class TestGeminiBackendProperties:
    def test_name_property(self):
        backend = GeminiBackend()
        assert backend.name == "Gemini CLI"

    def test_platform_property(self):
        backend = GeminiBackend()
        assert backend.platform == AgentPlatform.GEMINI

    def test_supports_parallel_property(self):
        backend = GeminiBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_method(self):
        backend = GeminiBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_model_stored_in_client(self):
        backend = GeminiBackend(model="test-model")
        assert backend._client.model == "test-model"

    def test_model_property(self):
        backend = GeminiBackend(model="my-model")
        assert backend.model == "my-model"


class TestGeminiBackendProtocolCompliance:
    def test_isinstance_aibackend(self):
        backend = GeminiBackend()
        assert isinstance(backend, AIBackend)

    def test_has_all_required_properties(self):
        backend = GeminiBackend()
        assert hasattr(backend, "name")
        assert hasattr(backend, "platform")
        assert hasattr(backend, "supports_parallel")
        assert isinstance(backend.name, str)
        assert isinstance(backend.platform, AgentPlatform)
        assert isinstance(backend.supports_parallel, bool)

    def test_has_all_required_methods(self):
        backend = GeminiBackend()
        assert callable(backend.run_with_callback)
        assert callable(backend.run_print_with_output)
        assert callable(backend.run_print_quiet)
        assert callable(backend.run_streaming)
        assert callable(backend.check_installed)
        assert callable(backend.detect_rate_limit)
        assert callable(backend.supports_parallel_execution)
        assert callable(backend.close)


class TestGeminiBackendDelegation:
    def test_run_with_callback_delegates_to_client(self):
        backend = GeminiBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_with_output_delegates(self):
        backend = GeminiBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_print_with_output("test prompt")

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_with_output_passes_timeout(self):
        backend = GeminiBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 30.0

    def test_run_print_quiet_delegates(self):
        backend = GeminiBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            output = backend.run_print_quiet("test prompt")

        mock_run.assert_called_once()
        assert output == "quiet output"

    def test_run_streaming_delegates_to_run_print_with_output(self):
        backend = GeminiBackend()

        with patch.object(
            backend, "run_print_with_output", return_value=(True, "streaming output")
        ) as mock_run:
            success, output = backend.run_streaming("test prompt")

        mock_run.assert_called_once_with(
            "test prompt",
            subagent=None,
            model=None,
            timeout_seconds=None,
        )
        assert success is True
        assert output == "streaming output"

    def test_detect_rate_limit_delegates(self):
        backend = GeminiBackend()

        assert backend.detect_rate_limit("Error 429: Too Many Requests") is True
        assert backend.detect_rate_limit("rate limit exceeded") is True
        assert backend.detect_rate_limit("resource exhausted") is True
        assert backend.detect_rate_limit("overloaded") is True
        assert backend.detect_rate_limit("HTTP 403 Quota exceeded") is True
        assert backend.detect_rate_limit("normal output") is False

    def test_check_installed_delegates(self):
        backend = GeminiBackend()

        with patch(
            "ingot.integrations.backends.gemini.check_gemini_installed",
            return_value=(True, "gemini 1.0.0"),
        ) as mock_check:
            is_installed, message = backend.check_installed()

        mock_check.assert_called_once()
        assert is_installed is True
        assert message == "gemini 1.0.0"


class TestGeminiBackendSystemPromptEnvVar:
    def test_build_system_prompt_env_with_subagent(self):
        backend = GeminiBackend()
        env, temp_path = backend._build_system_prompt_env("You are a planner.")

        try:
            assert env is not None
            assert "GEMINI_SYSTEM_MD" in env
            assert temp_path is not None
            # Verify file contents
            with open(temp_path) as f:
                content = f.read()
            assert content == "You are a planner."
        finally:
            if temp_path:
                os.unlink(temp_path)

    def test_build_system_prompt_env_without_subagent(self):
        backend = GeminiBackend()
        env, temp_path = backend._build_system_prompt_env(None)

        assert env is None
        assert temp_path is None

    def test_run_with_callback_passes_env_with_subagent(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "ingot-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = GeminiBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                subagent="ingot-planner",
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") is not None
        assert "GEMINI_SYSTEM_MD" in call_kwargs["env"]

    def test_run_with_callback_no_env_without_subagent(self):
        backend = GeminiBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") is None

    def test_run_print_with_output_passes_env_with_subagent(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text("You are an executor.")

        monkeypatch.chdir(tmp_path)

        backend = GeminiBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", subagent="test-agent")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") is not None
        assert "GEMINI_SYSTEM_MD" in call_kwargs["env"]


class TestGeminiBackendModelResolution:
    def test_run_with_callback_resolves_model(self):
        backend = GeminiBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                model="explicit-model",
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "explicit-model"

    def test_run_print_with_output_resolves_model(self):
        backend = GeminiBackend(model="default-model")

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "default-model"

    def test_model_precedence_explicit_beats_frontmatter(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: frontmatter-model
---
You are a test agent.
"""
        )
        monkeypatch.chdir(tmp_path)

        backend = GeminiBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
                model="explicit-model",
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "explicit-model"


class TestGeminiBackendTimeout:
    def test_run_with_callback_uses_timeout_wrapper(self, mocker):
        backend = GeminiBackend()
        mock_callback = MagicMock()

        mock_timeout_wrapper = mocker.patch.object(
            backend, "_run_streaming_with_timeout", return_value=(0, "timeout output")
        )
        mocker.patch.object(backend._client, "build_command", return_value=["gemini", "test"])

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_timeout_wrapper.assert_called_once()
        assert success is True
        assert output == "timeout output"

    def test_run_with_callback_without_timeout_delegates_directly(self, mocker):
        backend = GeminiBackend()
        mock_callback = MagicMock()

        mock_timeout_wrapper = mocker.patch.object(backend, "_run_streaming_with_timeout")
        mock_client_run = mocker.patch.object(
            backend._client, "run_with_callback", return_value=(True, "direct output")
        )

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=None,
        )

        mock_timeout_wrapper.assert_not_called()
        mock_client_run.assert_called_once()
        assert success is True
        assert output == "direct output"

    def test_run_print_quiet_timeout_raises_backend_timeout_error(self):
        backend = GeminiBackend()

        with patch.object(
            backend._client,
            "run_print_quiet",
            side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=30),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_quiet("test", timeout_seconds=30.0)

        assert exc_info.value.timeout_seconds == 30.0

    def test_run_print_with_output_timeout_raises_backend_timeout_error(self):
        backend = GeminiBackend()

        with patch.object(
            backend._client,
            "run_print_with_output",
            side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=15),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_with_output("test", timeout_seconds=15.0)

        assert exc_info.value.timeout_seconds == 15.0


class TestGeminiBackendClose:
    def test_close_is_noop(self):
        backend = GeminiBackend()
        backend.close()  # Should not raise


@pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestGeminiBackendIntegration:
    def test_check_installed_returns_version(self):
        backend = GeminiBackend()
        is_installed, message = backend.check_installed()
        assert isinstance(is_installed, bool)
        assert isinstance(message, str)
