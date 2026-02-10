"""Tests for ingot.config.backend_resolver module."""

from unittest.mock import MagicMock

import pytest

from ingot.config.backend_resolver import resolve_backend_platform
from ingot.config.fetch_config import AgentPlatform, ConfigValidationError
from ingot.integrations.backends.errors import BackendNotConfiguredError


class TestResolveBackendPlatformPrecedence:
    def test_cli_override_takes_precedence_over_config(self) -> None:
        config = MagicMock()
        config.get.return_value = "auggie"  # Config says auggie

        # CLI says claude - should win
        result = resolve_backend_platform(config, cli_backend_override="claude")

        assert result == AgentPlatform.CLAUDE  # CLI wins

    def test_cli_override_with_empty_config(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="auggie")

        assert result == AgentPlatform.AUGGIE

    def test_config_used_when_no_cli_override(self) -> None:
        config = MagicMock()
        config.get.return_value = "cursor"

        result = resolve_backend_platform(config, cli_backend_override=None)

        assert result == AgentPlatform.CURSOR

    def test_empty_string_cli_override_uses_config(self) -> None:
        config = MagicMock()
        config.get.return_value = "cursor"

        # Empty string is falsy, so config should be used
        result = resolve_backend_platform(config, cli_backend_override="")

        assert result == AgentPlatform.CURSOR

    def test_whitespace_only_cli_override_uses_config(self) -> None:
        config = MagicMock()
        config.get.return_value = "auggie"

        # Whitespace-only is stripped and treated as empty
        result = resolve_backend_platform(config, cli_backend_override="   ")

        assert result == AgentPlatform.AUGGIE


class TestResolveBackendPlatformNoBackend:
    def test_raises_when_no_cli_and_empty_config(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError) as exc_info:
            resolve_backend_platform(config, cli_backend_override=None)

        assert "No AI backend configured" in str(exc_info.value)
        assert "ingot init" in str(exc_info.value)

    def test_raises_when_config_is_whitespace_only(self) -> None:
        config = MagicMock()
        config.get.return_value = "   "

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(config, cli_backend_override=None)

    def test_whitespace_cli_and_empty_config_raises_error(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(BackendNotConfiguredError):
            resolve_backend_platform(config, cli_backend_override="   ")


class TestResolveBackendPlatformInvalidInput:
    """Tests for invalid platform string handling.

    Note: The Linear ticket states that invalid platforms raise ValueError,
    but the actual behavior is ConfigValidationError because parse_ai_backend()
    raises ConfigValidationError for invalid values. This test reflects the
    actual implementation behavior per the parent specification.
    """

    def test_invalid_cli_override_raises_config_validation_error(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        with pytest.raises(ConfigValidationError) as exc_info:
            resolve_backend_platform(config, cli_backend_override="chatgpt")

        # Check error message indicates invalid platform (avoid asserting full list
        # of allowed values to prevent test brittleness when enum changes)
        assert "Invalid AI backend" in str(exc_info.value)
        assert "chatgpt" in str(exc_info.value)

    def test_invalid_config_value_raises_config_validation_error(self) -> None:
        config = MagicMock()
        config.get.return_value = "openai"  # Not a valid platform

        with pytest.raises(ConfigValidationError):
            resolve_backend_platform(config, cli_backend_override=None)


class TestResolveBackendPlatformStringNormalization:
    def test_cli_override_is_case_insensitive(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="AUGGIE")

        assert result == AgentPlatform.AUGGIE

    def test_config_value_is_case_insensitive(self) -> None:
        config = MagicMock()
        config.get.return_value = "AuGgIe"

        result = resolve_backend_platform(config, cli_backend_override=None)

        assert result == AgentPlatform.AUGGIE

    def test_cli_override_strips_whitespace(self) -> None:
        config = MagicMock()
        config.get.return_value = ""

        result = resolve_backend_platform(config, cli_backend_override="  auggie  ")

        assert result == AgentPlatform.AUGGIE

    def test_config_value_strips_whitespace(self) -> None:
        config = MagicMock()
        config.get.return_value = "  auggie  "

        result = resolve_backend_platform(config, cli_backend_override=None)

        assert result == AgentPlatform.AUGGIE


class TestResolveBackendPlatformEnvironmentVariable:
    """Tests for AI_BACKEND environment variable support.

    These tests verify that AI_BACKEND can be set via environment variable
    and is properly loaded by ConfigManager.
    """

    def test_ai_backend_env_var_is_loaded_by_config_manager(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from ingot.config.manager import ConfigManager
        from ingot.config.settings import Settings

        # Verify AI_BACKEND is in the key mapping
        settings = Settings()
        assert (
            "AI_BACKEND" in settings._key_mapping
        ), "AI_BACKEND must be in Settings._key_mapping for env var support"

        # Set environment variable
        monkeypatch.setenv("AI_BACKEND", "cursor")

        # Create ConfigManager and load config
        config_manager = ConfigManager(global_config_path=tmp_path / "nonexistent-config")
        config_manager.load()

        # Verify the value is accessible via get()
        assert config_manager.get("AI_BACKEND") == "cursor"

    def test_ai_backend_env_var_works_with_resolver(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from ingot.config.manager import ConfigManager

        # Set environment variable
        monkeypatch.setenv("AI_BACKEND", "auggie")

        # Create ConfigManager and load config
        config_manager = ConfigManager(global_config_path=tmp_path / "nonexistent-config")
        config_manager.load()

        # Resolve backend platform
        result = resolve_backend_platform(config_manager, cli_backend_override=None)

        assert result == AgentPlatform.AUGGIE

    def test_cli_override_takes_precedence_over_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        from ingot.config.manager import ConfigManager

        # Set environment variable to auggie
        monkeypatch.setenv("AI_BACKEND", "auggie")

        # Create ConfigManager and load config
        config_manager = ConfigManager(global_config_path=tmp_path / "nonexistent-config")
        config_manager.load()

        # CLI override should win
        result = resolve_backend_platform(config_manager, cli_backend_override="cursor")

        assert result == AgentPlatform.CURSOR
