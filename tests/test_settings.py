"""Tests for ai_workflow.config.settings module."""

import pytest
from pathlib import Path

from ai_workflow.config.settings import Settings, CONFIG_FILE


class TestSettings:
    """Tests for Settings dataclass."""

    def test_default_values(self):
        """Settings has correct default values."""
        settings = Settings()
        
        assert settings.default_model == ""
        assert settings.planning_model == ""
        assert settings.implementation_model == ""
        assert settings.default_jira_project == ""
        assert settings.jira_integration_status == ""
        assert settings.jira_check_timestamp == 0
        assert settings.auto_open_files is True
        assert settings.preferred_editor == ""
        assert settings.skip_clarification is False
        assert settings.squash_at_end is True

    def test_custom_values(self):
        """Settings accepts custom values."""
        settings = Settings(
            default_model="claude-3",
            planning_model="claude-3-opus",
            auto_open_files=False,
            skip_clarification=True,
        )
        
        assert settings.default_model == "claude-3"
        assert settings.planning_model == "claude-3-opus"
        assert settings.auto_open_files is False
        assert settings.skip_clarification is True

    def test_get_attribute_for_key(self):
        """get_attribute_for_key returns correct attribute name."""
        settings = Settings()
        
        assert settings.get_attribute_for_key("DEFAULT_MODEL") == "default_model"
        assert settings.get_attribute_for_key("PLANNING_MODEL") == "planning_model"
        assert settings.get_attribute_for_key("AUTO_OPEN_FILES") == "auto_open_files"
        assert settings.get_attribute_for_key("UNKNOWN_KEY") is None

    def test_get_key_for_attribute(self):
        """get_key_for_attribute returns correct config key."""
        settings = Settings()
        
        assert settings.get_key_for_attribute("default_model") == "DEFAULT_MODEL"
        assert settings.get_key_for_attribute("planning_model") == "PLANNING_MODEL"
        assert settings.get_key_for_attribute("auto_open_files") == "AUTO_OPEN_FILES"
        assert settings.get_key_for_attribute("unknown_attr") is None

    def test_get_config_keys(self):
        """get_config_keys returns all valid keys."""
        keys = Settings.get_config_keys()
        
        assert "DEFAULT_MODEL" in keys
        assert "PLANNING_MODEL" in keys
        assert "IMPLEMENTATION_MODEL" in keys
        assert "DEFAULT_JIRA_PROJECT" in keys
        assert "AUTO_OPEN_FILES" in keys
        assert "SKIP_CLARIFICATION" in keys
        assert "SQUASH_AT_END" in keys


class TestConfigFile:
    """Tests for CONFIG_FILE constant."""

    def test_config_file_in_home(self):
        """CONFIG_FILE is in home directory."""
        assert CONFIG_FILE.parent == Path.home()

    def test_config_file_name(self):
        """CONFIG_FILE has correct name."""
        assert CONFIG_FILE.name == ".ai-workflow-config"

