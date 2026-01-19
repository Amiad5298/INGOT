"""Tests for spec.config.settings module."""

import pytest
from pathlib import Path

from specflow.config.settings import Settings, CONFIG_FILE


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


class TestParallelSettings:
    """Tests for parallel execution settings."""

    def test_parallel_execution_enabled_default(self):
        """parallel_execution_enabled defaults to True."""
        settings = Settings()
        assert settings.parallel_execution_enabled is True

    def test_max_parallel_tasks_default(self):
        """max_parallel_tasks defaults to 3."""
        settings = Settings()
        assert settings.max_parallel_tasks == 3

    def test_fail_fast_default(self):
        """fail_fast defaults to False."""
        settings = Settings()
        assert settings.fail_fast is False

    def test_loads_from_config_file(self):
        """Parallel settings can be loaded from config keys."""
        settings = Settings()

        # Verify the key mappings exist
        assert settings.get_attribute_for_key("PARALLEL_EXECUTION_ENABLED") == "parallel_execution_enabled"
        assert settings.get_attribute_for_key("MAX_PARALLEL_TASKS") == "max_parallel_tasks"
        assert settings.get_attribute_for_key("FAIL_FAST") == "fail_fast"


class TestSubagentSettings:
    """Tests for subagent settings."""

    def test_subagent_planner_default(self):
        """subagent_planner defaults to spec-planner."""
        settings = Settings()
        assert settings.subagent_planner == "spec-planner"

    def test_subagent_tasklist_default(self):
        """subagent_tasklist defaults to spec-tasklist."""
        settings = Settings()
        assert settings.subagent_tasklist == "spec-tasklist"

    def test_subagent_implementer_default(self):
        """subagent_implementer defaults to spec-implementer."""
        settings = Settings()
        assert settings.subagent_implementer == "spec-implementer"

    def test_subagent_reviewer_default(self):
        """subagent_reviewer defaults to spec-reviewer."""
        settings = Settings()
        assert settings.subagent_reviewer == "spec-reviewer"

    def test_subagent_doc_updater_default(self):
        """subagent_doc_updater defaults to spec-doc-updater."""
        settings = Settings()
        assert settings.subagent_doc_updater == "spec-doc-updater"

    def test_subagent_custom_values(self):
        """Subagent settings accept custom values."""
        settings = Settings(
            subagent_planner="custom-planner",
            subagent_implementer="custom-impl",
        )
        assert settings.subagent_planner == "custom-planner"
        assert settings.subagent_implementer == "custom-impl"

    def test_subagent_config_key_mappings(self):
        """Subagent settings have correct config key mappings."""
        settings = Settings()
        assert settings.get_attribute_for_key("SUBAGENT_PLANNER") == "subagent_planner"
        assert settings.get_attribute_for_key("SUBAGENT_TASKLIST") == "subagent_tasklist"
        assert settings.get_attribute_for_key("SUBAGENT_IMPLEMENTER") == "subagent_implementer"
        assert settings.get_attribute_for_key("SUBAGENT_REVIEWER") == "subagent_reviewer"
        assert settings.get_attribute_for_key("SUBAGENT_DOC_UPDATER") == "subagent_doc_updater"


class TestDocUpdateSettings:
    """Tests for documentation update settings."""

    def test_auto_update_docs_default(self):
        """auto_update_docs defaults to True."""
        settings = Settings()
        assert settings.auto_update_docs is True

    def test_auto_update_docs_can_be_disabled(self):
        """auto_update_docs can be set to False."""
        settings = Settings(auto_update_docs=False)
        assert settings.auto_update_docs is False

    def test_auto_update_docs_config_key_mapping(self):
        """auto_update_docs has correct config key mapping."""
        settings = Settings()
        assert settings.get_attribute_for_key("AUTO_UPDATE_DOCS") == "auto_update_docs"


class TestConfigFile:
    """Tests for CONFIG_FILE constant."""

    def test_config_file_in_home(self):
        """CONFIG_FILE is in home directory."""
        assert CONFIG_FILE.parent == Path.home()

    def test_config_file_name(self):
        """CONFIG_FILE has correct name."""
        assert CONFIG_FILE.name == ".specflow-config"

