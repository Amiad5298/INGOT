"""Tests for spec.integrations.backends.cursor module - CursorBackend class."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends import AIBackend, CursorBackend
from spec.integrations.backends.errors import BackendTimeoutError


class TestCursorBackendProperties:
    """Tests for CursorBackend properties."""

    def test_name_property(self):
        """Backend name is 'Cursor'."""
        backend = CursorBackend()
        assert backend.name == "Cursor"

    def test_platform_property(self):
        """Platform is AgentPlatform.CURSOR."""
        backend = CursorBackend()
        assert backend.platform == AgentPlatform.CURSOR

    def test_supports_parallel_property(self):
        """Backend supports parallel execution."""
        backend = CursorBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_method(self):
        """supports_parallel_execution() returns supports_parallel value."""
        backend = CursorBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_model_stored_in_client(self):
        """Model is passed to underlying CursorClient."""
        backend = CursorBackend(model="test-model")
        assert backend._client.model == "test-model"

    def test_model_property(self):
        """Model property returns instance default."""
        backend = CursorBackend(model="my-model")
        assert backend.model == "my-model"


class TestCursorBackendProtocolCompliance:
    """Tests verifying AIBackend protocol compliance."""

    def test_isinstance_aibackend(self):
        """CursorBackend satisfies AIBackend protocol via isinstance()."""
        backend = CursorBackend()
        assert isinstance(backend, AIBackend)

    def test_has_all_required_properties(self):
        """CursorBackend has all required protocol properties."""
        backend = CursorBackend()
        assert hasattr(backend, "name")
        assert hasattr(backend, "platform")
        assert hasattr(backend, "supports_parallel")
        assert isinstance(backend.name, str)
        assert isinstance(backend.platform, AgentPlatform)
        assert isinstance(backend.supports_parallel, bool)

    def test_has_all_required_methods(self):
        """CursorBackend has all required protocol methods."""
        backend = CursorBackend()
        assert callable(backend.run_with_callback)
        assert callable(backend.run_print_with_output)
        assert callable(backend.run_print_quiet)
        assert callable(backend.run_streaming)
        assert callable(backend.check_installed)
        assert callable(backend.detect_rate_limit)
        assert callable(backend.supports_parallel_execution)
        assert callable(backend.close)


class TestCursorBackendDelegation:
    """Tests for method delegation to CursorClient."""

    def test_run_with_callback_delegates_to_client(self):
        """run_with_callback delegates to CursorClient when no timeout."""
        backend = CursorBackend()
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
        """subagent is composed into the prompt before passing to client."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "spec-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = CursorBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                subagent="spec-planner",
            )

        # The prompt should be composed (not passed as a separate system_prompt)
        call_args = mock_run.call_args
        composed_prompt = call_args[0][0]
        assert "## Agent Instructions" in composed_prompt
        assert "You are a planner." in composed_prompt
        assert "## Task" in composed_prompt
        assert "test prompt" in composed_prompt
        # No system_prompt kwarg (unlike ClaudeBackend)
        assert "system_prompt" not in call_args.kwargs

    def test_run_print_with_output_delegates(self):
        """run_print_with_output delegates to CursorClient."""
        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_print_with_output("test prompt")

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_with_output_passes_timeout(self):
        """timeout_seconds is forwarded to client."""
        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", timeout_seconds=30.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 30.0

    def test_run_print_quiet_delegates(self):
        """run_print_quiet delegates to CursorClient."""
        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            output = backend.run_print_quiet("test prompt")

        mock_run.assert_called_once()
        assert output == "quiet output"

    def test_run_print_quiet_passes_timeout(self):
        """timeout_seconds is forwarded to client."""
        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            backend.run_print_quiet("test prompt", timeout_seconds=45.0)

        assert mock_run.call_args.kwargs.get("timeout_seconds") == 45.0

    def test_run_print_quiet_composes_subagent_prompt(self, tmp_path, monkeypatch):
        """subagent is composed into the prompt in run_print_quiet."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "spec-planner.md"
        agent_file.write_text("You are a planner.")

        monkeypatch.chdir(tmp_path)

        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            backend.run_print_quiet("test prompt", subagent="spec-planner")

        composed_prompt = mock_run.call_args[0][0]
        assert "## Agent Instructions" in composed_prompt
        assert "You are a planner." in composed_prompt
        assert "## Task" in composed_prompt
        assert "test prompt" in composed_prompt

    def test_run_print_with_output_composes_subagent_prompt(self, tmp_path, monkeypatch):
        """subagent is composed into the prompt in run_print_with_output."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "spec-executor.md"
        agent_file.write_text("You are an executor.")

        monkeypatch.chdir(tmp_path)

        backend = CursorBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", subagent="spec-executor")

        composed_prompt = mock_run.call_args[0][0]
        assert "## Agent Instructions" in composed_prompt
        assert "You are an executor." in composed_prompt
        assert "## Task" in composed_prompt
        assert "test prompt" in composed_prompt

    def test_dont_save_session_passed_as_no_save(self):
        """dont_save_session is mapped to no_save for CursorClient methods."""
        backend = CursorBackend()

        # Test run_with_callback
        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                dont_save_session=True,
            )
        assert mock_run.call_args.kwargs.get("no_save") is True

        # Test run_print_with_output
        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("no_save") is True

        # Test run_print_quiet
        with patch.object(backend._client, "run_print_quiet", return_value="output") as mock_run:
            backend.run_print_quiet("test prompt", dont_save_session=True)
        assert mock_run.call_args.kwargs.get("no_save") is True

    def test_run_streaming_delegates_to_run_print_with_output(self):
        """run_streaming calls run_print_with_output internally."""
        backend = CursorBackend()

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
        """detect_rate_limit uses _looks_like_rate_limit."""
        backend = CursorBackend()

        assert backend.detect_rate_limit("Error 429: Too Many Requests") is True
        assert backend.detect_rate_limit("rate limit exceeded") is True
        assert backend.detect_rate_limit("overloaded") is True
        assert backend.detect_rate_limit("quota exceeded") is True
        assert backend.detect_rate_limit("normal output") is False

    def test_check_installed_delegates(self):
        """check_installed uses check_cursor_installed."""
        backend = CursorBackend()

        with patch(
            "spec.integrations.backends.cursor.check_cursor_installed",
            return_value=(True, "cursor 0.1.0"),
        ) as mock_check:
            is_installed, message = backend.check_installed()

        mock_check.assert_called_once()
        assert is_installed is True
        assert message == "cursor 0.1.0"


class TestCursorBackendModelResolution:
    """Tests for model resolution in CursorBackend.

    Model resolution precedence (per Decision 6 in parent spec):
    1. Explicit per-call model override (highest priority)
    2. Subagent frontmatter model field
    3. Instance default model (lowest priority)

    Model is resolved once in CursorBackend._resolve_subagent() and passed
    as a pre-resolved value to CursorClient (no double resolution).
    """

    def test_run_with_callback_resolves_model(self):
        """Explicit model is passed through to client."""
        backend = CursorBackend(model="default-model")

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
        """run_print_with_output passes instance default model."""
        backend = CursorBackend(model="default-model")

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "default-model"

    def test_model_precedence_explicit_beats_frontmatter(self, tmp_path, monkeypatch):
        """Explicit model override takes precedence over frontmatter model."""
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

        backend = CursorBackend(model="default-model")

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
        """Frontmatter model takes precedence over instance default."""
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

        backend = CursorBackend(model="default-model")

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
        """Instance default is used when no explicit or frontmatter model."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text("You are a test agent with no frontmatter.")

        monkeypatch.chdir(tmp_path)

        backend = CursorBackend(model="default-model")

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
        """Model resolution happens once in backend, not again in client.

        The client receives pre-resolved model via keyword argument.
        No subagent file I/O happens in the client.
        """
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

        backend = CursorBackend()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
            )

        call_kwargs = mock_run.call_args.kwargs
        composed_prompt = mock_run.call_args[0][0]
        # Client receives model (not subagent name)
        assert call_kwargs.get("model") == "frontmatter-model"
        # Subagent instructions are embedded in prompt
        assert "Agent instructions." in composed_prompt
        assert "subagent" not in call_kwargs


class TestCursorBackendPromptComposition:
    """Tests for _compose_prompt() method."""

    def test_compose_with_subagent_prompt(self):
        """Composes prompt with agent instructions section."""
        backend = CursorBackend()
        result = backend._compose_prompt("Do the task", "You are a planner.")

        assert result == "## Agent Instructions\n\nYou are a planner.\n\n## Task\n\nDo the task"

    def test_compose_without_subagent_prompt(self):
        """Returns original prompt when no subagent prompt."""
        backend = CursorBackend()
        result = backend._compose_prompt("Do the task", None)

        assert result == "Do the task"

    def test_compose_with_empty_subagent_prompt(self):
        """Returns original prompt when subagent prompt is empty string."""
        backend = CursorBackend()
        result = backend._compose_prompt("Do the task", "")

        assert result == "Do the task"


class TestCursorBackendTimeout:
    """Tests for timeout handling in CursorBackend."""

    def test_run_with_callback_uses_timeout_wrapper(self, mocker):
        """Timeout triggers _run_streaming_with_timeout()."""
        backend = CursorBackend()
        mock_callback = MagicMock()

        mock_timeout_wrapper = mocker.patch.object(
            backend, "_run_streaming_with_timeout", return_value=(0, "timeout output")
        )
        mocker.patch.object(backend._client, "build_command", return_value=["cursor", "test"])

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_timeout_wrapper.assert_called_once()
        assert success is True
        assert output == "timeout output"

    def test_run_with_callback_without_timeout_delegates_directly(self, mocker):
        """Without timeout, delegates directly to CursorClient.run_with_callback()."""
        backend = CursorBackend()
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
        """BackendTimeoutError from _run_streaming_with_timeout bubbles up."""
        backend = CursorBackend()
        mock_callback = MagicMock()

        mocker.patch.object(
            backend,
            "_run_streaming_with_timeout",
            side_effect=BackendTimeoutError("Timed out", timeout_seconds=30.0),
        )
        mocker.patch.object(backend._client, "build_command", return_value=["cursor", "test"])

        with pytest.raises(BackendTimeoutError) as exc_info:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                timeout_seconds=30.0,
            )

        assert exc_info.value.timeout_seconds == 30.0

    def test_timeout_uses_public_build_command(self, mocker):
        """Timeout path uses public build_command (not _build_command)."""
        backend = CursorBackend()
        mock_callback = MagicMock()

        mocker.patch.object(backend, "_run_streaming_with_timeout", return_value=(0, "output"))
        mock_build = mocker.patch.object(
            backend._client, "build_command", return_value=["cursor", "test"]
        )

        backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_build.assert_called_once()

    def test_run_print_quiet_timeout_raises_backend_timeout_error(self):
        """subprocess.TimeoutExpired from client becomes BackendTimeoutError."""
        backend = CursorBackend()

        with patch.object(
            backend._client,
            "run_print_quiet",
            side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=30),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_quiet("test", timeout_seconds=30.0)

        assert exc_info.value.timeout_seconds == 30.0

    def test_run_print_with_output_timeout_raises_backend_timeout_error(self):
        """subprocess.TimeoutExpired from client becomes BackendTimeoutError."""
        backend = CursorBackend()

        with patch.object(
            backend._client,
            "run_print_with_output",
            side_effect=subprocess.TimeoutExpired(cmd=["cursor"], timeout=15),
        ):
            with pytest.raises(BackendTimeoutError) as exc_info:
                backend.run_print_with_output("test", timeout_seconds=15.0)

        assert exc_info.value.timeout_seconds == 15.0


class TestCursorBackendClose:
    """Tests for close() method."""

    def test_close_is_noop(self):
        """close() is inherited from BaseBackend and is a no-op."""
        backend = CursorBackend()
        backend.close()  # Should not raise


@pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests require SPEC_INTEGRATION_TESTS=1",
)
class TestCursorBackendIntegration:
    """Integration tests with real Cursor CLI."""

    def test_check_installed_returns_version(self):
        """check_installed returns True and version string when Cursor is installed."""
        backend = CursorBackend()
        is_installed, message = backend.check_installed()
        assert isinstance(is_installed, bool)
        assert isinstance(message, str)
