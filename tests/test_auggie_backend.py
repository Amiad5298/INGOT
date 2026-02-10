"""Tests for ingot.integrations.backends.auggie module - AuggieBackend class."""

import os
from unittest.mock import MagicMock, patch

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends import AIBackend, AuggieBackend
from ingot.integrations.backends.errors import BackendTimeoutError


class TestAuggieBackendProperties:
    def test_name_property(self):
        backend = AuggieBackend()
        assert backend.name == "Auggie"

    def test_platform_property(self):
        backend = AuggieBackend()
        assert backend.platform == AgentPlatform.AUGGIE

    def test_supports_parallel_property(self):
        backend = AuggieBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_method(self):
        backend = AuggieBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_model_stored_in_client(self):
        backend = AuggieBackend(model="test-model")
        assert backend._client.model == "test-model"


class TestAuggieBackendProtocolCompliance:
    def test_isinstance_aibackend(self):
        backend = AuggieBackend()
        assert isinstance(backend, AIBackend)

    def test_has_all_required_properties(self):
        backend = AuggieBackend()
        # Properties should be accessible without error
        assert hasattr(backend, "name")
        assert hasattr(backend, "platform")
        assert hasattr(backend, "supports_parallel")
        # Verify they return expected types
        assert isinstance(backend.name, str)
        assert isinstance(backend.platform, AgentPlatform)
        assert isinstance(backend.supports_parallel, bool)

    def test_has_all_required_methods(self):
        backend = AuggieBackend()
        # Methods should be callable
        assert callable(backend.run_with_callback)
        assert callable(backend.run_print_with_output)
        assert callable(backend.run_print_quiet)
        assert callable(backend.run_streaming)
        assert callable(backend.check_installed)
        assert callable(backend.detect_rate_limit)
        assert callable(backend.supports_parallel_execution)
        assert callable(backend.close)


class TestAuggieBackendDelegation:
    def test_run_with_callback_delegates_to_client(self):
        backend = AuggieBackend()
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

    def test_run_with_callback_maps_subagent_to_agent(self):
        backend = AuggieBackend()
        mock_callback = MagicMock()

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                subagent="ingot-planner",
            )

        # Verify agent parameter was passed (not subagent)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("agent") == "ingot-planner"
        assert "subagent" not in call_kwargs

    def test_run_print_with_output_delegates(self):
        backend = AuggieBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            success, output = backend.run_print_with_output("test prompt")

        mock_run.assert_called_once()
        assert success is True
        assert output == "output"

    def test_run_print_quiet_delegates(self):
        backend = AuggieBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            output = backend.run_print_quiet("test prompt")

        mock_run.assert_called_once()
        assert output == "quiet output"

    def test_run_print_quiet_maps_subagent_to_agent(self):
        backend = AuggieBackend()

        with patch.object(
            backend._client, "run_print_quiet", return_value="quiet output"
        ) as mock_run:
            backend.run_print_quiet("test prompt", subagent="ingot-planner")

        # Verify agent parameter was passed (not subagent)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("agent") == "ingot-planner"
        assert "subagent" not in call_kwargs

    def test_run_print_with_output_maps_subagent_to_agent(self):
        backend = AuggieBackend()

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt", subagent="test-agent")

        # Verify agent parameter was passed (not subagent)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("agent") == "test-agent"
        assert "subagent" not in call_kwargs

    def test_dont_save_session_passed_to_client(self):
        backend = AuggieBackend()

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
        backend = AuggieBackend()

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
        backend = AuggieBackend()

        # Test positive cases
        assert backend.detect_rate_limit("Error 429: Too Many Requests") is True
        assert backend.detect_rate_limit("rate limit exceeded") is True
        assert backend.detect_rate_limit("quota exceeded") is True

        # Test negative case
        assert backend.detect_rate_limit("normal output") is False

    def test_check_installed_delegates(self):
        backend = AuggieBackend()

        with patch(
            "ingot.integrations.backends.auggie.check_auggie_installed",
            return_value=(True, "1.0.0"),
        ) as mock_check:
            is_installed, message = backend.check_installed()

        mock_check.assert_called_once()
        assert is_installed is True
        assert message == "1.0.0"


class TestAuggieBackendModelResolution:
    """Tests for model resolution in AuggieBackend.

    Model resolution precedence (per Decision 6 in parent spec):
    1. Explicit per-call model override (highest priority)
    2. Subagent frontmatter model field
    3. Instance default model (lowest priority)

    Note: AuggieClient._build_command() now respects explicit model overrides
    even when a subagent is set (explicit > agent definition > default).
    """

    def test_run_with_callback_resolves_model(self):
        backend = AuggieBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                model="explicit-model",
            )

        # Verify explicit model was passed
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "explicit-model"

    def test_run_print_with_output_resolves_model(self):
        backend = AuggieBackend(model="default-model")

        with patch.object(
            backend._client, "run_print_with_output", return_value=(True, "output")
        ) as mock_run:
            backend.run_print_with_output("test prompt")

        # Verify default model was passed
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "default-model"

    def test_model_precedence_explicit_beats_frontmatter(self, tmp_path, monkeypatch):
        # Create a mock subagent file with frontmatter model
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

        # Change to temp directory so agent file is found
        monkeypatch.chdir(tmp_path)

        backend = AuggieBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
                model="explicit-model",  # Should win over frontmatter
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "explicit-model"

    def test_model_precedence_frontmatter_beats_default(self, tmp_path, monkeypatch):
        # Create a mock subagent file with frontmatter model
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

        # Change to temp directory so agent file is found
        monkeypatch.chdir(tmp_path)

        backend = AuggieBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
                # No explicit model - should use frontmatter
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "frontmatter-model"

    def test_model_precedence_default_when_no_frontmatter(self, tmp_path, monkeypatch):
        # Create a mock subagent file WITHOUT frontmatter model
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text("You are a test agent with no frontmatter.")

        # Change to temp directory so agent file is found
        monkeypatch.chdir(tmp_path)

        backend = AuggieBackend(model="default-model")

        with patch.object(
            backend._client, "run_with_callback", return_value=(True, "output")
        ) as mock_run:
            backend.run_with_callback(
                "test prompt",
                output_callback=MagicMock(),
                subagent="test-agent",
                # No explicit model, no frontmatter - should use default
            )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("model") == "default-model"


class TestAuggieBackendTimeout:
    def test_run_with_callback_uses_timeout_wrapper(self, mocker):
        backend = AuggieBackend()
        mock_callback = MagicMock()

        # Mock _run_streaming_with_timeout
        mock_timeout_wrapper = mocker.patch.object(
            backend, "_run_streaming_with_timeout", return_value=(0, "timeout output")
        )
        # Mock _build_command to return a simple command
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=30.0,
        )

        mock_timeout_wrapper.assert_called_once()
        assert success is True
        assert output == "timeout output"

    def test_run_with_callback_without_timeout_delegates_directly(self, mocker):
        backend = AuggieBackend()
        mock_callback = MagicMock()

        # Mock _run_streaming_with_timeout - should NOT be called
        mock_timeout_wrapper = mocker.patch.object(backend, "_run_streaming_with_timeout")
        # Mock client's run_with_callback
        mock_client_run = mocker.patch.object(
            backend._client, "run_with_callback", return_value=(True, "direct output")
        )

        success, output = backend.run_with_callback(
            "test prompt",
            output_callback=mock_callback,
            timeout_seconds=None,  # No timeout
        )

        mock_timeout_wrapper.assert_not_called()
        mock_client_run.assert_called_once()
        assert success is True
        assert output == "direct output"

    def test_timeout_error_propagates(self, mocker):
        backend = AuggieBackend()
        mock_callback = MagicMock()

        # Mock _run_streaming_with_timeout to raise timeout error
        mocker.patch.object(
            backend,
            "_run_streaming_with_timeout",
            side_effect=BackendTimeoutError("Timed out", timeout_seconds=30.0),
        )
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])

        with pytest.raises(BackendTimeoutError) as exc_info:
            backend.run_with_callback(
                "test prompt",
                output_callback=mock_callback,
                timeout_seconds=30.0,
            )

        assert exc_info.value.timeout_seconds == 30.0

    def test_run_print_with_output_enforces_timeout(self, mocker):
        import subprocess

        backend = AuggieBackend()
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])
        mocker.patch(
            "ingot.integrations.backends.auggie.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["auggie"], timeout=10.0),
        )

        with pytest.raises(BackendTimeoutError) as exc_info:
            backend.run_print_with_output("test prompt", timeout_seconds=10.0)

        assert exc_info.value.timeout_seconds == 10.0

    def test_run_print_with_output_timeout_returns_result(self, mocker):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output text"

        backend = AuggieBackend()
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])
        mocker.patch("ingot.integrations.backends.auggie.subprocess.run", return_value=mock_result)

        success, output = backend.run_print_with_output("test prompt", timeout_seconds=30.0)

        assert success is True
        assert output == "output text"

    def test_run_print_with_output_without_timeout_delegates(self, mocker):
        backend = AuggieBackend()
        mock_run = mocker.patch.object(
            backend._client, "run_print_with_output", return_value=(True, "delegated")
        )
        mock_subprocess = mocker.patch("ingot.integrations.backends.auggie.subprocess.run")

        success, output = backend.run_print_with_output("test prompt", timeout_seconds=None)

        mock_run.assert_called_once()
        mock_subprocess.assert_not_called()
        assert success is True
        assert output == "delegated"

    def test_run_print_quiet_enforces_timeout(self, mocker):
        import subprocess

        backend = AuggieBackend()
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])
        mocker.patch(
            "ingot.integrations.backends.auggie.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["auggie"], timeout=15.0),
        )

        with pytest.raises(BackendTimeoutError) as exc_info:
            backend.run_print_quiet("test prompt", timeout_seconds=15.0)

        assert exc_info.value.timeout_seconds == 15.0

    def test_run_print_quiet_timeout_returns_result(self, mocker):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "quiet output"

        backend = AuggieBackend()
        mocker.patch.object(backend._client, "_build_command", return_value=["auggie", "test"])
        mocker.patch("ingot.integrations.backends.auggie.subprocess.run", return_value=mock_result)

        output = backend.run_print_quiet("test prompt", timeout_seconds=30.0)

        assert output == "quiet output"

    def test_run_print_quiet_without_timeout_delegates(self, mocker):
        backend = AuggieBackend()
        mock_run = mocker.patch.object(backend._client, "run_print_quiet", return_value="delegated")
        mock_subprocess = mocker.patch("ingot.integrations.backends.auggie.subprocess.run")

        output = backend.run_print_quiet("test prompt", timeout_seconds=None)

        mock_run.assert_called_once()
        mock_subprocess.assert_not_called()
        assert output == "delegated"


class TestAuggieClientContract:
    """Tests verifying AuggieClient private API contract.

    These tests ensure _build_command() behavior matches AuggieBackend's expectations.
    If these fail, AuggieBackend may need updates.
    """

    def test_build_command_basic_structure(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        cmd = client._build_command("test prompt", print_mode=True)
        assert cmd[0] == "auggie"
        assert "--print" in cmd
        assert cmd[-1] == "test prompt"

    def test_build_command_with_model(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        cmd = client._build_command("test prompt", model="test-model", print_mode=True)
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "test-model"

    def test_build_command_explicit_model_overrides_agent_model(self):
        from unittest.mock import MagicMock, patch

        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()

        # Mock agent definition with its own model
        mock_agent_def = MagicMock()
        mock_agent_def.model = "agent-model"
        mock_agent_def.prompt = "Agent instructions"

        with patch(
            "ingot.integrations.auggie._parse_agent_definition",
            return_value=mock_agent_def,
        ):
            cmd = client._build_command(
                "test prompt",
                agent="test-agent",
                model="explicit-override-model",
            )

        # Explicit model takes precedence over agent definition model
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "explicit-override-model"

    def test_build_command_agent_model_used_when_no_explicit(self):
        from unittest.mock import MagicMock, patch

        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()

        mock_agent_def = MagicMock()
        mock_agent_def.model = "agent-model"
        mock_agent_def.prompt = "Agent instructions"

        with patch(
            "ingot.integrations.auggie._parse_agent_definition",
            return_value=mock_agent_def,
        ):
            cmd = client._build_command(
                "test prompt",
                agent="test-agent",
                # No explicit model - agent model should be used
            )

        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "agent-model"


class TestAuggieBackendClose:
    def test_close_is_noop(self):
        backend = AuggieBackend()
        backend.close()  # Should not raise


class TestAuggieDetectRateLimit:
    @pytest.fixture
    def backend(self):
        return AuggieBackend()

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
        ],
        ids=[
            "429",
            "rate_limit",
            "rate_limit_underscore",
            "too_many_requests",
            "quota_exceeded",
            "capacity",
            "throttle",
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


@pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)
class TestAuggieBackendIntegration:
    def test_check_installed_returns_version(self):
        backend = AuggieBackend()
        is_installed, message = backend.check_installed()
        # If Auggie is installed, should return True
        # Note: This test only runs when INGOT_INTEGRATION_TESTS=1
        assert isinstance(is_installed, bool)
        assert isinstance(message, str)
