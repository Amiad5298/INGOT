"""Tests for ingot.integrations.backends.codex module - CodexBackend class."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends import AIBackend, CodexBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class TestCodexBackendProperties:
    def test_name_property(self):
        backend = CodexBackend()
        assert backend.name == "Codex"

    def test_platform_property(self):
        backend = CodexBackend()
        assert backend.platform == AgentPlatform.CODEX

    def test_supports_parallel_property(self):
        backend = CodexBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_method(self):
        backend = CodexBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_model_stored_in_client(self):
        backend = CodexBackend(model="test-model")
        assert backend._client.model == "test-model"

    def test_model_property(self):
        backend = CodexBackend(model="my-model")
        assert backend.model == "my-model"


class TestCodexBackendProtocolCompliance:
    def test_isinstance_aibackend(self):
        backend = CodexBackend()
        assert isinstance(backend, AIBackend)

    def test_has_all_required_properties(self):
        backend = CodexBackend()
        assert hasattr(backend, "name")
        assert hasattr(backend, "platform")
        assert hasattr(backend, "supports_parallel")
        assert isinstance(backend.name, str)
        assert isinstance(backend.platform, AgentPlatform)
        assert isinstance(backend.supports_parallel, bool)

    def test_has_all_required_methods(self):
        backend = CodexBackend()
        assert callable(backend.run_with_callback)
        assert callable(backend.run_print_with_output)
        assert callable(backend.run_print_quiet)
        assert callable(backend.run_streaming)
        assert callable(backend.check_installed)
        assert callable(backend.detect_rate_limit)
        assert callable(backend.supports_parallel_execution)
        assert callable(backend.close)


class TestCodexBackendDelegation:
    def test_run_with_callback_delegates_to_client(self):
        backend = CodexBackend()
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

    def test_run_with_callback_composes_subagent_prompt(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "ingot-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = CodexBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                subagent="ingot-planner",
            )

        call_args = mock_run.call_args
        composed_prompt = call_args[0][0]
        assert "## Agent Instructions" in composed_prompt
        assert "You are a planner." in composed_prompt
        assert "## Task" in composed_prompt
        assert "test prompt" in composed_prompt

    def test_run_print_with_output_delegates(self):
        backend = CodexBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_print_with_output("test prompt")

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_with_output_passes_timeout(self):
        backend = CodexBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 30.0

    def test_run_print_quiet_delegates(self):
        backend = CodexBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            output = backend.run_print_quiet("test prompt")

        mock_run.assert_called_once()
        assert output == "quiet output"

    def test_dont_save_session_passed_as_ephemeral(self):
        backend = CodexBackend()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                dont_save_session=True,
            )
        assert mock_run.call_args.kwargs.get("ephemeral") is True

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("ephemeral") is True

        with patch.object(backend._client, "run_print_quiet", return_value="output") as mock_run:
            backend.run_print_quiet("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("ephemeral") is True

    def test_run_streaming_delegates_to_run_print_with_output(self):
        backend = CodexBackend()

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
        backend = CodexBackend()

        assert backend.detect_rate_limit("Error 429: Too Many Requests") is True
        assert backend.detect_rate_limit("rate limit exceeded") is True
        assert backend.detect_rate_limit("overloaded") is True
        assert backend.detect_rate_limit("capacity") is True
        assert backend.detect_rate_limit("server_error") is True
        assert backend.detect_rate_limit("normal output") is False

    def test_check_installed_delegates(self):
        backend = CodexBackend()

        with patch(
            "ingot.integrations.backends.codex.check_codex_installed",
            return_value=(True, "codex 1.0.0"),
        ) as mock_check:
            is_installed, message = backend.check_installed()

        mock_check.assert_called_once()
        assert is_installed is True
        assert message == "codex 1.0.0"


class TestCodexBackendModelResolution:
    def test_run_with_callback_resolves_model(self):
        backend = CodexBackend(model="default-model")

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
        backend = CodexBackend(model="default-model")

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

        backend = CodexBackend(model="default-model")

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

    def test_model_precedence_frontmatter_beats_default(self, tmp_path, monkeypatch):
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

        backend = CodexBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "frontmatter-model"


class TestCodexBackendPromptComposition:
    def test_compose_with_subagent_prompt(self):
        backend = CodexBackend()
        result = backend._compose_prompt("Do the task", "You are a planner.")

        assert result == "## Agent Instructions\n\nYou are a planner.\n\n## Task\n\nDo the task"

    def test_compose_without_subagent_prompt(self):
        backend = CodexBackend()
        result = backend._compose_prompt("Do the task", None)

        assert result == "Do the task"

    def test_compose_with_empty_subagent_prompt(self):
        backend = CodexBackend()
        result = backend._compose_prompt("Do the task", "")

        assert result == "Do the task"


class TestCodexBackendTimeout:
    def test_run_with_callback_uses_timeout_wrapper(self, mocker):
        backend = CodexBackend()
        mock_callback = MagicMock()

        mock_timeout_wrapper = mocker.patch.object(
            backend, "_run_streaming_with_timeout", return_value=(0, "timeout output")
        )
        mocker.patch.object(backend._client, "build_command", return_value=["codex", "test"])

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_timeout_wrapper.assert_called_once()
        assert success is True
        assert output == "timeout output"

    def test_run_with_callback_without_timeout_delegates_directly(self, mocker):
        backend = CodexBackend()
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
        backend = CodexBackend()

        with patch.object(
            backend._client,
            "run_print_quiet",
            side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=30),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_quiet("test", timeout_seconds=30.0)

        assert exc_info.value.timeout_seconds == 30.0

    def test_run_print_with_output_timeout_raises_backend_timeout_error(self):
        backend = CodexBackend()

        with patch.object(
            backend._client,
            "run_print_with_output",
            side_effect=subprocess.TimeoutExpired(cmd=["codex"], timeout=15),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_with_output("test", timeout_seconds=15.0)

        assert exc_info.value.timeout_seconds == 15.0


class TestCodexBackendClose:
    def test_close_is_noop(self):
        backend = CodexBackend()
        backend.close()  # Should not raise


class TestCodexDetectRateLimit:
    @pytest.fixture
    def backend(self):
        return CodexBackend()

    @pytest.mark.parametrize(
        "output",
        [
            "Error 429: Too Many Requests",
            "rate limit exceeded, please wait",
            "rate_limit_error: quota used up",
            "too many requests, slow down",
            "quota exceeded for model",
            "request throttled by API",
            "API is overloaded, try later",
            "server at capacity",
            "server_error: internal failure",
        ],
        ids=[
            "429",
            "rate_limit",
            "rate_limit_underscore",
            "too_many_requests",
            "quota_exceeded",
            "throttle",
            "overloaded",
            "capacity",
            "server_error",
        ],
    )
    def test_positive_detection(self, backend, output):
        assert backend.detect_rate_limit(output) is True

    @pytest.mark.parametrize(
        "output",
        [
            "normal output",
            "Task completed successfully",
            "Created file utils.py",
            "Error: file not found",
            "",
        ],
        ids=[
            "normal",
            "success",
            "file_created",
            "file_not_found",
            "empty",
        ],
    )
    def test_negative_detection(self, backend, output):
        assert backend.detect_rate_limit(output) is False


@pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestCodexBackendIntegration:
    def test_check_installed_returns_version(self):
        backend = CodexBackend()
        is_installed, message = backend.check_installed()
        assert isinstance(is_installed, bool)
        assert isinstance(message, str)
