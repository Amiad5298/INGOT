"""Tests for ingot.integrations.backends.claude module - ClaudeBackend class."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends import AIBackend, ClaudeBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class TestClaudeBackendProperties:
    def test_name_property(self):
        backend = ClaudeBackend()
        assert backend.name == "Claude Code"

    def test_platform_property(self):
        backend = ClaudeBackend()
        assert backend.platform == AgentPlatform.CLAUDE

    def test_supports_parallel_property(self):
        backend = ClaudeBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_method(self):
        backend = ClaudeBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_model_stored_in_client(self):
        backend = ClaudeBackend(model="test-model")
        assert backend._client.model == "test-model"

    def test_model_property(self):
        backend = ClaudeBackend(model="my-model")
        assert backend.model == "my-model"


class TestClaudeBackendProtocolCompliance:
    def test_isinstance_aibackend(self):
        backend = ClaudeBackend()
        assert isinstance(backend, AIBackend)

    def test_has_all_required_properties(self):
        backend = ClaudeBackend()
        assert hasattr(backend, "name")
        assert hasattr(backend, "platform")
        assert hasattr(backend, "supports_parallel")
        assert isinstance(backend.name, str)
        assert isinstance(backend.platform, AgentPlatform)
        assert isinstance(backend.supports_parallel, bool)

    def test_has_all_required_methods(self):
        backend = ClaudeBackend()
        assert callable(backend.run_with_callback)
        assert callable(backend.run_print_with_output)
        assert callable(backend.run_print_quiet)
        assert callable(backend.run_streaming)
        assert callable(backend.check_installed)
        assert callable(backend.detect_rate_limit)
        assert callable(backend.supports_parallel_execution)
        assert callable(backend.close)


class TestClaudeBackendDelegation:
    def test_run_with_callback_delegates_to_client(self):
        backend = ClaudeBackend()
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

    def test_run_with_callback_passes_resolved_system_prompt(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "ingot-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = ClaudeBackend()
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
        assert call_kwargs.get("system_prompt") == "You are a planner."

    def test_run_print_with_output_delegates(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_print_with_output("test prompt")

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_with_output_passes_timeout(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 30.0

    def test_run_print_quiet_delegates(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            output = backend.run_print_quiet("test prompt")

        mock_run.assert_called_once()
        assert output == "quiet output"

    def test_run_print_quiet_passes_timeout(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            backend.run_print_quiet("test prompt", timeout_seconds=45.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 45.0

    def test_run_print_quiet_passes_system_prompt(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "ingot-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            backend.run_print_quiet("test prompt", subagent="ingot-planner")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("system_prompt") == "You are a planner."

    def test_run_print_with_output_passes_system_prompt(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text("You are an executor.")

        monkeypatch.chdir(tmp_path)

        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", subagent="test-agent")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("system_prompt") == "You are an executor."

    def test_dont_save_session_passed_to_client(self):
        backend = ClaudeBackend()

        # Test run_with_callback
        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                dont_save_session=True,
            )
        assert mock_run.call_args.kwargs.get("dont_save_session") is True

        # Test run_print_with_output
        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("dont_save_session") is True

        # Test run_print_quiet
        with patch.object(backend._client, "run_print_quiet", return_value="output") as mock_run:
            backend.run_print_quiet("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("dont_save_session") is True

    def test_run_streaming_delegates_to_run_print_with_output(self):
        backend = ClaudeBackend()

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
        backend = ClaudeBackend()

        assert backend.detect_rate_limit("Error 429: Too Many Requests") is True
        assert backend.detect_rate_limit("rate limit exceeded") is True
        assert backend.detect_rate_limit("overloaded") is True
        assert backend.detect_rate_limit("quota exceeded") is True
        assert backend.detect_rate_limit("normal output") is False

    def test_check_installed_delegates(self):
        backend = ClaudeBackend()

        with patch(
            "ingot.integrations.backends.claude.check_claude_installed",
            return_value=(True, "claude 1.0.0"),
        ) as mock_check:
            is_installed, message = backend.check_installed()

        mock_check.assert_called_once()
        assert is_installed is True
        assert message == "claude 1.0.0"


class TestClaudeBackendModelResolution:
    """Tests for model resolution in ClaudeBackend.

    Model resolution precedence (per Decision 6 in parent spec):
    1. Explicit per-call model override (highest priority)
    2. Subagent frontmatter model field
    3. Instance default model (lowest priority)

    Model is resolved once in ClaudeBackend._resolve_subagent() and passed
    as a pre-resolved value to ClaudeClient (no double resolution).
    """

    def test_run_with_callback_resolves_model(self):
        backend = ClaudeBackend(model="default-model")

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
        backend = ClaudeBackend(model="default-model")

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

        backend = ClaudeBackend(model="default-model")

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

        backend = ClaudeBackend(model="default-model")

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

    def test_model_precedence_default_when_no_frontmatter(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text("You are a test agent with no frontmatter.")

        monkeypatch.chdir(tmp_path)

        backend = ClaudeBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "default-model"

    def test_no_double_model_resolution(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: frontmatter-model
---
Agent instructions."""
        )

        monkeypatch.chdir(tmp_path)

        backend = ClaudeBackend()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
            )

        call_kwargs = mock_run.call_args.kwargs
        # Client receives model + system_prompt (not subagent name)
        assert call_kwargs.get("model") == "frontmatter-model"
        assert call_kwargs.get("system_prompt") == "Agent instructions."
        assert "subagent" not in call_kwargs


class TestClaudeBackendTimeout:
    def test_run_with_callback_uses_timeout_wrapper(self, mocker):
        backend = ClaudeBackend()
        mock_callback = MagicMock()

        mock_timeout_wrapper = mocker.patch.object(
            backend, "_run_streaming_with_timeout", return_value=(0, "timeout output")
        )
        mocker.patch.object(backend._client, "build_command", return_value=["claude", "test"])

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_timeout_wrapper.assert_called_once()
        assert success is True
        assert output == "timeout output"

    def test_run_with_callback_without_timeout_delegates_directly(self, mocker):
        backend = ClaudeBackend()
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

    def test_timeout_error_propagates(self, mocker):
        backend = ClaudeBackend()
        mock_callback = MagicMock()

        mocker.patch.object(
            backend,
            "_run_streaming_with_timeout",
            side_effect=BackendTimeoutError("Timed out", timeout_seconds=30.0),
        )
        mocker.patch.object(backend._client, "build_command", return_value=["claude", "test"])

        with pytest.raises(BackendTimeoutError) as exc_info:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                timeout_seconds=30.0,
            )

        assert exc_info.value.timeout_seconds == 30.0

    def test_timeout_uses_public_build_command(self, mocker):
        backend = ClaudeBackend()
        mock_callback = MagicMock()

        mocker.patch.object(backend, "_run_streaming_with_timeout", return_value=(0, "output"))
        mock_build = mocker.patch.object(
            backend._client, "build_command", return_value=["claude", "test"]
        )

        backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_build.assert_called_once()

    def test_run_print_quiet_timeout_raises_backend_timeout_error(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client,
            "run_print_quiet",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=30),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_quiet("test", timeout_seconds=30.0)

        assert exc_info.value.timeout_seconds == 30.0

    def test_run_print_with_output_timeout_raises_backend_timeout_error(self):
        backend = ClaudeBackend()

        with patch.object(
            backend._client,
            "run_print_with_output",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=15),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_with_output("test", timeout_seconds=15.0)

        assert exc_info.value.timeout_seconds == 15.0


class TestClaudeBackendClose:
    def test_close_is_noop(self):
        backend = ClaudeBackend()
        backend.close()  # Should not raise


class TestClaudeDetectRateLimit:
    @pytest.fixture
    def backend(self):
        return ClaudeBackend()

    @pytest.mark.parametrize(
        "output",
        [
            "Error 429: Too Many Requests",
            "rate limit exceeded, please wait",
            "rate_limit_error: quota used up",
            "too many requests, slow down",
            "quota exceeded for model",
            "insufficient capacity, try again",
            "request throttled by API",
            "API is overloaded, try later",
            "Error 529: API overloaded",
        ],
        ids=[
            "429",
            "rate_limit",
            "rate_limit_underscore",
            "too_many_requests",
            "quota_exceeded",
            "capacity",
            "throttle",
            "overloaded",
            "529",
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
            "HTTP 502 Bad Gateway",
            "Service Unavailable 503",
            "Gateway Timeout: 504",
        ],
        ids=[
            "normal",
            "success",
            "file_created",
            "file_not_found",
            "empty",
            "502_server_error",
            "503_server_error",
            "504_server_error",
        ],
    )
    def test_negative_detection(self, backend, output):
        assert backend.detect_rate_limit(output) is False

    def test_429_word_boundary_no_false_positive(self, backend):
        assert backend.detect_rate_limit("Working on PROJ-4290") is False

    def test_429_word_boundary_true_positive(self, backend):
        assert backend.detect_rate_limit("HTTP 429 error") is True

    def test_529_word_boundary_no_false_positive(self, backend):
        assert backend.detect_rate_limit("Issue PROJ-5290 resolved") is False

    def test_529_word_boundary_true_positive(self, backend):
        assert backend.detect_rate_limit("Error 529: API overloaded") is True


@pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestClaudeBackendIntegration:
    def test_check_installed_returns_version(self):
        backend = ClaudeBackend()
        is_installed, message = backend.check_installed()
        assert isinstance(is_installed, bool)
        assert isinstance(message, str)
