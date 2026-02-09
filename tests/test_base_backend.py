"""Tests for spec.integrations.backends.base module - BaseBackend class."""

from abc import ABC
from collections.abc import Callable

import pytest

from spec.config.fetch_config import AgentPlatform
from spec.integrations.backends.base import (
    AIBackend,
    BaseBackend,
    SubagentMetadata,
)
from spec.integrations.backends.errors import BackendTimeoutError


class ConcreteTestBackend(BaseBackend):
    """Minimal concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "TestBackend"

    @property
    def platform(self) -> AgentPlatform:
        return AgentPlatform.AUGGIE

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        return True, "output"

    def run_print_with_output(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        return True, "output"

    def run_print_quiet(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return "output"

    def run_streaming(
        self,
        prompt: str,
        *,
        subagent: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str]:
        return True, "output"

    def check_installed(self) -> tuple[bool, str]:
        return True, "1.0.0"

    def detect_rate_limit(self, output: str) -> bool:
        return "rate limit" in output.lower()


class TestSubagentMetadata:
    """Tests for SubagentMetadata dataclass."""

    def test_subagent_metadata_defaults(self):
        """SubagentMetadata has None defaults for all fields."""
        metadata = SubagentMetadata()
        assert metadata.model is None
        assert metadata.temperature is None

    def test_subagent_metadata_with_values(self):
        """SubagentMetadata accepts model and temperature."""
        metadata = SubagentMetadata(model="claude-3-opus", temperature=0.7)
        assert metadata.model == "claude-3-opus"
        assert metadata.temperature == 0.7

    def test_subagent_metadata_model_only(self):
        """SubagentMetadata can have model without temperature."""
        metadata = SubagentMetadata(model="gpt-4")
        assert metadata.model == "gpt-4"
        assert metadata.temperature is None

    def test_subagent_metadata_temperature_only(self):
        """SubagentMetadata can have temperature without model."""
        metadata = SubagentMetadata(temperature=0.5)
        assert metadata.model is None
        assert metadata.temperature == 0.5


class TestBaseBackendAbstract:
    """Tests for BaseBackend abstract class enforcement."""

    def test_basebackend_is_abc(self):
        """BaseBackend is an abstract base class."""
        assert issubclass(BaseBackend, ABC)

    def test_basebackend_cannot_be_instantiated(self):
        """BaseBackend raises TypeError on direct instantiation."""
        with pytest.raises(TypeError, match="abstract"):
            BaseBackend()

    def test_concrete_backend_must_implement_abstract_methods(self):
        """Subclass without implementations raises TypeError."""

        class IncompleteBackend(BaseBackend):
            pass

        with pytest.raises(TypeError, match="abstract"):
            IncompleteBackend()

    def test_concrete_backend_can_be_instantiated(self):
        """Properly implemented subclass can be instantiated."""
        backend = ConcreteTestBackend()
        assert backend is not None
        assert backend.name == "TestBackend"


class TestBaseBackendDefaults:
    """Tests for BaseBackend default implementations."""

    def test_supports_parallel_default_true(self):
        """Default supports_parallel is True."""
        backend = ConcreteTestBackend()
        assert backend.supports_parallel is True

    def test_supports_parallel_execution_returns_property(self):
        """supports_parallel_execution() returns supports_parallel value."""
        backend = ConcreteTestBackend()
        assert backend.supports_parallel_execution() is True
        assert backend.supports_parallel_execution() == backend.supports_parallel

    def test_close_is_noop(self):
        """close() is a no-op and doesn't raise."""
        backend = ConcreteTestBackend()
        backend.close()  # Should not raise

    def test_model_stored_as_instance_attribute(self):
        """Model parameter is stored as _model attribute."""
        backend = ConcreteTestBackend(model="test-model")
        assert backend._model == "test-model"

    def test_model_defaults_to_empty_string(self):
        """Model defaults to empty string when not provided."""
        backend = ConcreteTestBackend()
        assert backend._model == ""


class TestParseSubagentPrompt:
    """Tests for _parse_subagent_prompt method."""

    def test_parse_subagent_prompt_with_frontmatter(self, tmp_path, monkeypatch):
        """Parses YAML frontmatter and returns metadata + body."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "test-agent.md"
        subagent_file.write_text(
            "---\nmodel: claude-3-opus\ntemperature: 0.5\n---\nYou are a test agent."
        )
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("test-agent")

        assert metadata.model == "claude-3-opus"
        assert metadata.temperature == 0.5
        assert body == "You are a test agent."

    def test_parse_subagent_prompt_without_frontmatter(self, tmp_path, monkeypatch):
        """Returns empty metadata and full content when no frontmatter."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "plain-agent.md"
        subagent_file.write_text("You are a plain agent without frontmatter.")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("plain-agent")

        assert metadata.model is None
        assert body == "You are a plain agent without frontmatter."

    def test_parse_subagent_prompt_file_not_found(self, tmp_path, monkeypatch):
        """Returns empty metadata and empty body when file not found."""
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("nonexistent")

        assert metadata.model is None
        assert body == ""

    def test_parse_subagent_prompt_invalid_yaml(self, tmp_path, monkeypatch):
        """Returns empty metadata when YAML is invalid."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "invalid-agent.md"
        subagent_file.write_text("---\ninvalid: yaml: content:\n---\nBody text.")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("invalid-agent")

        # Should fall back gracefully
        assert metadata.model is None

    def test_parse_subagent_prompt_model_only(self, tmp_path, monkeypatch):
        """Frontmatter with only model field, no temperature."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "model-only.md"
        subagent_file.write_text("---\nmodel: gpt-4\n---\nPrompt body here.")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("model-only")

        assert metadata.model == "gpt-4"
        assert metadata.temperature is None
        assert body == "Prompt body here."

    def test_parse_subagent_prompt_empty_frontmatter(self, tmp_path, monkeypatch):
        """Handles empty frontmatter `---\\n---\\n` gracefully."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "empty-frontmatter.md"
        subagent_file.write_text("---\n---\nBody after empty frontmatter.")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("empty-frontmatter")

        assert metadata.model is None
        assert metadata.temperature is None
        assert body == "Body after empty frontmatter."

    def test_parse_subagent_prompt_extra_fields_ignored(self, tmp_path, monkeypatch):
        """Unknown frontmatter fields are ignored gracefully."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        subagent_file = agents_dir / "extra-fields.md"
        subagent_file.write_text(
            "---\nmodel: claude-3\ntemperature: 0.5\nunknown_field: value\n---\nBody."
        )
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend()
        metadata, body = backend._parse_subagent_prompt("extra-fields")

        assert metadata.model == "claude-3"
        assert metadata.temperature == 0.5
        assert body == "Body."


class TestResolveModel:
    """Tests for _resolve_model method."""

    def test_resolve_model_explicit_override(self):
        """Explicit model takes highest precedence."""
        backend = ConcreteTestBackend(model="default-model")
        result = backend._resolve_model(explicit_model="override-model", subagent=None)
        assert result == "override-model"

    def test_resolve_model_from_frontmatter(self, tmp_path, monkeypatch):
        """Model from subagent frontmatter used when no explicit override."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "model-agent.md").write_text("---\nmodel: frontmatter-model\n---\n")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend(model="default-model")
        result = backend._resolve_model(explicit_model=None, subagent="model-agent")
        assert result == "frontmatter-model"

    def test_resolve_model_instance_default(self):
        """Falls back to instance default when no override or frontmatter."""
        backend = ConcreteTestBackend(model="default-model")
        result = backend._resolve_model(explicit_model=None, subagent=None)
        assert result == "default-model"

    def test_resolve_model_returns_none_when_empty(self):
        """Returns None when no model specified anywhere."""
        backend = ConcreteTestBackend()
        result = backend._resolve_model(explicit_model=None, subagent=None)
        assert result is None

    def test_resolve_model_explicit_overrides_frontmatter(self, tmp_path, monkeypatch):
        """Explicit model overrides frontmatter model."""
        agents_dir = tmp_path / ".augment" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "model-agent.md").write_text("---\nmodel: frontmatter-model\n---\n")
        monkeypatch.chdir(tmp_path)

        backend = ConcreteTestBackend(model="default-model")
        result = backend._resolve_model(explicit_model="explicit-model", subagent="model-agent")
        assert result == "explicit-model"


class TestRunStreamingWithTimeout:
    """Tests for _run_streaming_with_timeout method."""

    def test_run_streaming_with_timeout_success(self, mocker):
        """Process completes before timeout - returns output and exit code."""
        mock_process = mocker.MagicMock()
        mock_process.stdout = iter(["line1\n", "line2\n"])
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = None

        mocker.patch("subprocess.Popen", return_value=mock_process)

        backend = ConcreteTestBackend()
        output_lines = []
        return_code, output = backend._run_streaming_with_timeout(
            ["echo", "test"],
            output_callback=output_lines.append,
            timeout_seconds=10.0,
        )

        assert return_code == 0
        assert output == "line1\nline2\n"
        assert output_lines == ["line1", "line2"]

    def test_run_streaming_with_timeout_no_timeout(self, mocker):
        """Process runs without timeout when timeout_seconds=None."""
        mock_process = mocker.MagicMock()
        mock_process.stdout = iter(["output\n"])
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = None

        mocker.patch("subprocess.Popen", return_value=mock_process)
        mock_thread = mocker.patch("threading.Thread")

        backend = ConcreteTestBackend()
        return_code, output = backend._run_streaming_with_timeout(
            ["echo", "test"],
            output_callback=lambda x: None,
            timeout_seconds=None,
        )

        # Verify no watchdog thread was created when timeout is None
        mock_thread.assert_not_called()
        assert return_code == 0
        assert output == "output\n"

    def test_run_streaming_with_timeout_callback_receives_stripped_lines(self, mocker):
        """Output callback receives lines with newlines stripped."""
        mock_process = mocker.MagicMock()
        mock_process.stdout = iter(["  line with spaces  \n", "another line\n"])
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = None

        mocker.patch("subprocess.Popen", return_value=mock_process)

        backend = ConcreteTestBackend()
        output_lines = []
        backend._run_streaming_with_timeout(
            ["echo", "test"],
            output_callback=output_lines.append,
            timeout_seconds=10.0,
        )

        # Callback receives stripped lines (no trailing newline)
        assert output_lines == ["  line with spaces  ", "another line"]

    def test_run_streaming_with_timeout_nonzero_exit(self, mocker):
        """Process with non-zero exit code returns that code."""
        mock_process = mocker.MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.poll.return_value = 1
        mock_process.wait.return_value = None

        mocker.patch("subprocess.Popen", return_value=mock_process)

        backend = ConcreteTestBackend()
        return_code, output = backend._run_streaming_with_timeout(
            ["false"],
            output_callback=lambda x: None,
            timeout_seconds=10.0,
        )

        assert return_code == 1
        assert output == "error output\n"

    def test_run_streaming_with_timeout_exceeds(self, mocker):
        """Process killed when timeout exceeded - raises BackendTimeoutError."""
        import threading

        mock_process = mocker.MagicMock()
        hang_event = threading.Event()

        # Create an iterator that blocks until hang_event is set
        def blocking_iterator():
            hang_event.wait()
            return
            yield  # Make this a generator

        mock_process.stdout = blocking_iterator()
        mock_process.returncode = -15  # SIGTERM
        mock_process.poll.return_value = None  # Process still running

        def terminate_side_effect():
            hang_event.set()

        mock_process.terminate.side_effect = terminate_side_effect
        mock_process.wait.return_value = None

        mocker.patch("subprocess.Popen", return_value=mock_process)

        backend = ConcreteTestBackend()
        with pytest.raises(BackendTimeoutError) as exc_info:
            backend._run_streaming_with_timeout(
                ["sleep", "100"],
                output_callback=lambda x: None,
                timeout_seconds=0.1,  # Very short timeout
            )

        assert "timed out" in str(exc_info.value).lower()


class TestBaseBackendImports:
    """Tests for module imports."""

    def test_basebackend_importable_from_package(self):
        """BaseBackend can be imported from backends package."""
        from spec.integrations.backends import BaseBackend

        assert BaseBackend is not None

    def test_subagentmetadata_importable_from_package(self):
        """SubagentMetadata can be imported from backends package."""
        from spec.integrations.backends import SubagentMetadata

        assert SubagentMetadata is not None

    def test_all_exports_available(self):
        """All expected exports are available from backends package."""
        from spec.integrations.backends import (
            AIBackend,
            BackendTimeoutError,
            BaseBackend,
            SubagentMetadata,
        )

        assert AIBackend.__name__ == "AIBackend"
        assert BaseBackend.__name__ == "BaseBackend"
        assert SubagentMetadata.__name__ == "SubagentMetadata"
        assert BackendTimeoutError.__name__ == "BackendTimeoutError"


class TestMatchesCommonRateLimit:
    """Tests for the shared matches_common_rate_limit function."""

    def test_none_output_returns_false(self):
        """None output returns False without raising AttributeError."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert matches_common_rate_limit(None) is False

    def test_empty_string_returns_false(self):
        """Empty string returns False."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert matches_common_rate_limit("") is False

    def test_detects_429(self):
        """Detects HTTP 429 status code."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert matches_common_rate_limit("Error 429: Too Many Requests") is True

    def test_detects_rate_limit_keyword(self):
        """Detects rate limit keywords."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert matches_common_rate_limit("rate limit exceeded") is True

    def test_does_not_detect_502(self):
        """502 is not a rate limit."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert matches_common_rate_limit("502 Bad Gateway") is False

    def test_extra_keywords(self):
        """Extra keywords are checked."""
        from spec.integrations.backends.base import matches_common_rate_limit

        assert (
            matches_common_rate_limit("server overloaded", extra_keywords=("overloaded",)) is True
        )
        assert matches_common_rate_limit("server overloaded") is False

    def test_extra_status_re(self):
        """Extra status code regex is checked."""
        import re

        from spec.integrations.backends.base import matches_common_rate_limit

        assert (
            matches_common_rate_limit("Error 529", extra_status_re=re.compile(r"\b529\b")) is True
        )
        assert matches_common_rate_limit("Error 529") is False


class TestBaseBackendProtocolCompliance:
    """Tests verifying BaseBackend subclasses satisfy AIBackend protocol."""

    def test_concrete_backend_satisfies_aibackend_protocol(self):
        """ConcreteTestBackend satisfies AIBackend protocol."""
        backend = ConcreteTestBackend()
        assert isinstance(backend, AIBackend)
