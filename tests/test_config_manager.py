"""Tests for ai_workflow.config.manager module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config.manager import ConfigManager
from ai_workflow.config.settings import Settings


class TestConfigManagerLoad:
    """Tests for ConfigManager.load method."""

    def test_load_missing_file(self, tmp_path):
        """Returns defaults when config file doesn't exist."""
        config_path = tmp_path / "missing-config"
        manager = ConfigManager(config_path)
        
        settings = manager.load()
        
        assert settings.default_model == ""
        assert settings.auto_open_files is True

    def test_load_valid_file(self, temp_config_file):
        """Parses KEY=VALUE and KEY="VALUE" formats."""
        manager = ConfigManager(temp_config_file)
        
        settings = manager.load()
        
        assert settings.default_model == "claude-3"
        assert settings.planning_model == "claude-3-opus"
        assert settings.implementation_model == "claude-3-sonnet"
        assert settings.default_jira_project == "PROJ"

    def test_load_ignores_comments(self, tmp_path):
        """Skips lines starting with #."""
        config_file = tmp_path / "config"
        config_file.write_text('''# This is a comment
DEFAULT_MODEL="test"
# Another comment
PLANNING_MODEL="test2"
''')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.default_model == "test"
        assert settings.planning_model == "test2"

    def test_load_ignores_empty_lines(self, tmp_path):
        """Skips empty lines."""
        config_file = tmp_path / "config"
        config_file.write_text('''DEFAULT_MODEL="test"

PLANNING_MODEL="test2"

''')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.default_model == "test"
        assert settings.planning_model == "test2"

    def test_load_parses_boolean_true(self, tmp_path):
        """Parses boolean true values."""
        config_file = tmp_path / "config"
        config_file.write_text('AUTO_OPEN_FILES="true"\n')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.auto_open_files is True

    def test_load_parses_boolean_false(self, tmp_path):
        """Parses boolean false values."""
        config_file = tmp_path / "config"
        config_file.write_text('AUTO_OPEN_FILES="false"\n')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.auto_open_files is False

    def test_load_parses_integer(self, tmp_path):
        """Parses integer values."""
        config_file = tmp_path / "config"
        config_file.write_text('JIRA_CHECK_TIMESTAMP="1234567890"\n')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.jira_check_timestamp == 1234567890

    def test_load_handles_unquoted_values(self, tmp_path):
        """Handles values without quotes."""
        config_file = tmp_path / "config"
        config_file.write_text('DEFAULT_MODEL=test-model\n')
        manager = ConfigManager(config_file)
        
        settings = manager.load()
        
        assert settings.default_model == "test-model"

    def test_load_handles_single_quotes(self, tmp_path):
        """Handles single-quoted values."""
        config_file = tmp_path / "config"
        config_file.write_text("DEFAULT_MODEL='test-model'\n")
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "test-model"

    def test_load_extracts_model_id_from_full_format(self, tmp_path):
        """Extracts model ID from 'Name [id]' format for model keys."""
        config_file = tmp_path / "config"
        config_file.write_text('''DEFAULT_MODEL="Claude Opus 4.5 [opus4.5]"
PLANNING_MODEL="Haiku 4.5 [haiku4.5]"
IMPLEMENTATION_MODEL="Sonnet 4.5 [sonnet4.5]"
''')
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "opus4.5"
        assert settings.planning_model == "haiku4.5"
        assert settings.implementation_model == "sonnet4.5"

    def test_load_keeps_model_id_format_unchanged(self, tmp_path):
        """Keeps model ID format unchanged if already in ID-only format."""
        config_file = tmp_path / "config"
        config_file.write_text('''DEFAULT_MODEL="opus4.5"
PLANNING_MODEL="haiku4.5"
''')
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "opus4.5"
        assert settings.planning_model == "haiku4.5"


class TestConfigManagerSave:
    """Tests for ConfigManager.save method."""

    def test_save_validates_key(self, tmp_path):
        """Raises ValueError for invalid key names."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)
        
        with pytest.raises(ValueError, match="Invalid config key"):
            manager.save("invalid-key", "value")

    def test_save_validates_key_starting_with_number(self, tmp_path):
        """Raises ValueError for keys starting with number."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)
        
        with pytest.raises(ValueError, match="Invalid config key"):
            manager.save("123KEY", "value")

    def test_save_creates_file(self, tmp_path):
        """Creates config file if it doesn't exist."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)
        
        manager.save("TEST_KEY", "test_value")
        
        assert config_path.exists()
        assert 'TEST_KEY="test_value"' in config_path.read_text()

    def test_save_updates_existing_key(self, tmp_path):
        """Updates existing key in file."""
        config_path = tmp_path / "config"
        config_path.write_text('TEST_KEY="old_value"\n')
        manager = ConfigManager(config_path)
        manager.load()
        
        manager.save("TEST_KEY", "new_value")
        
        content = config_path.read_text()
        assert 'TEST_KEY="new_value"' in content
        assert "old_value" not in content

    def test_save_preserves_comments(self, tmp_path):
        """Keeps comments when saving."""
        config_path = tmp_path / "config"
        config_path.write_text('# Comment\nTEST_KEY="value"\n')
        manager = ConfigManager(config_path)
        manager.load()
        
        manager.save("TEST_KEY", "new_value")
        
        content = config_path.read_text()
        assert "# Comment" in content

    def test_save_file_permissions(self, tmp_path):
        """Config file has mode 600."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        manager.save("TEST_KEY", "value")

        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestConfigManagerGet:
    """Tests for ConfigManager.get method."""

    def test_get_returns_value(self, temp_config_file):
        """Returns value for existing key."""
        manager = ConfigManager(temp_config_file)
        manager.load()

        value = manager.get("DEFAULT_MODEL")

        assert value == "claude-3"

    def test_get_returns_default(self, tmp_path):
        """Returns default when key not found."""
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        value = manager.get("NONEXISTENT", "default_value")

        assert value == "default_value"

    def test_get_returns_empty_string_default(self, tmp_path):
        """Returns empty string when no default provided."""
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        value = manager.get("NONEXISTENT")

        assert value == ""


class TestConfigManagerShow:
    """Tests for ConfigManager.show method."""

    @patch("ai_workflow.utils.console.print_header")
    @patch("ai_workflow.utils.console.print_info")
    @patch("ai_workflow.utils.console.console")
    def test_show_missing_file(self, mock_console, mock_info, mock_header, tmp_path):
        """Shows message when config file doesn't exist."""
        config_path = tmp_path / "missing"
        manager = ConfigManager(config_path)

        manager.show()

        mock_header.assert_called_once()
        assert mock_info.call_count >= 1

    @patch("ai_workflow.utils.console.print_header")
    @patch("ai_workflow.utils.console.print_info")
    @patch("ai_workflow.utils.console.console")
    def test_show_displays_settings(self, mock_console, mock_info, mock_header, temp_config_file):
        """Shows all settings from config file."""
        manager = ConfigManager(temp_config_file)
        manager.load()

        manager.show()

        mock_header.assert_called_once()
        # Should print multiple setting lines
        assert mock_console.print.call_count >= 5

