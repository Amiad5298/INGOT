"""Tests for ingot.config.settings module."""

from pathlib import Path

from ingot.config.settings import CONFIG_FILE, Settings


class TestSettings:
    def test_default_values(self):
        settings = Settings()

        assert settings.default_model == ""
        assert settings.planning_model == ""
        assert settings.implementation_model == ""
        assert settings.jira_integration_status == ""
        assert settings.jira_check_timestamp == 0
        assert settings.auto_open_files is True
        assert settings.preferred_editor == ""
        assert settings.skip_clarification is False
        assert settings.squash_at_end is True

    def test_custom_values(self):
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
        settings = Settings()

        assert settings.get_attribute_for_key("DEFAULT_MODEL") == "default_model"
        assert settings.get_attribute_for_key("PLANNING_MODEL") == "planning_model"
        assert settings.get_attribute_for_key("AUTO_OPEN_FILES") == "auto_open_files"
        assert settings.get_attribute_for_key("UNKNOWN_KEY") is None

    def test_get_key_for_attribute(self):
        settings = Settings()

        assert settings.get_key_for_attribute("default_model") == "DEFAULT_MODEL"
        assert settings.get_key_for_attribute("planning_model") == "PLANNING_MODEL"
        assert settings.get_key_for_attribute("auto_open_files") == "AUTO_OPEN_FILES"
        assert settings.get_key_for_attribute("unknown_attr") is None

    def test_get_config_keys(self):
        keys = Settings.get_config_keys()

        assert "DEFAULT_MODEL" in keys
        assert "PLANNING_MODEL" in keys
        assert "IMPLEMENTATION_MODEL" in keys
        assert "AUTO_OPEN_FILES" in keys
        assert "SKIP_CLARIFICATION" in keys
        assert "SQUASH_AT_END" in keys


class TestParallelSettings:
    def test_parallel_execution_enabled_default(self):
        settings = Settings()
        assert settings.parallel_execution_enabled is True

    def test_max_parallel_tasks_default(self):
        settings = Settings()
        assert settings.max_parallel_tasks == 3

    def test_fail_fast_default(self):
        settings = Settings()
        assert settings.fail_fast is False

    def test_loads_from_config_file(self):
        settings = Settings()

        # Verify the key mappings exist
        assert (
            settings.get_attribute_for_key("PARALLEL_EXECUTION_ENABLED")
            == "parallel_execution_enabled"
        )
        assert settings.get_attribute_for_key("MAX_PARALLEL_TASKS") == "max_parallel_tasks"
        assert settings.get_attribute_for_key("FAIL_FAST") == "fail_fast"


class TestSubagentSettings:
    def test_subagent_planner_default(self):
        settings = Settings()
        assert settings.subagent_planner == "ingot-planner"

    def test_subagent_tasklist_default(self):
        settings = Settings()
        assert settings.subagent_tasklist == "ingot-tasklist"

    def test_subagent_implementer_default(self):
        settings = Settings()
        assert settings.subagent_implementer == "ingot-implementer"

    def test_subagent_reviewer_default(self):
        settings = Settings()
        assert settings.subagent_reviewer == "ingot-reviewer"

    def test_subagent_doc_updater_default(self):
        settings = Settings()
        assert settings.subagent_doc_updater == "ingot-doc-updater"

    def test_subagent_custom_values(self):
        settings = Settings(
            subagent_planner="custom-planner",
            subagent_implementer="custom-impl",
        )
        assert settings.subagent_planner == "custom-planner"
        assert settings.subagent_implementer == "custom-impl"

    def test_subagent_config_key_mappings(self):
        settings = Settings()
        assert settings.get_attribute_for_key("SUBAGENT_PLANNER") == "subagent_planner"
        assert settings.get_attribute_for_key("SUBAGENT_TASKLIST") == "subagent_tasklist"
        assert settings.get_attribute_for_key("SUBAGENT_IMPLEMENTER") == "subagent_implementer"
        assert settings.get_attribute_for_key("SUBAGENT_REVIEWER") == "subagent_reviewer"
        assert settings.get_attribute_for_key("SUBAGENT_DOC_UPDATER") == "subagent_doc_updater"


class TestDocUpdateSettings:
    def test_auto_update_docs_default(self):
        settings = Settings()
        assert settings.auto_update_docs is True

    def test_auto_update_docs_can_be_disabled(self):
        settings = Settings(auto_update_docs=False)
        assert settings.auto_update_docs is False

    def test_auto_update_docs_config_key_mapping(self):
        settings = Settings()
        assert settings.get_attribute_for_key("AUTO_UPDATE_DOCS") == "auto_update_docs"


class TestDefaultPlatformSettings:
    def test_default_platform_default_value(self):
        settings = Settings()
        assert settings.default_platform == ""

    def test_default_platform_custom_value(self):
        settings = Settings(default_platform="jira")
        assert settings.default_platform == "jira"

    def test_default_platform_config_key_mapping(self):
        settings = Settings()
        assert settings.get_attribute_for_key("DEFAULT_PLATFORM") == "default_platform"

    def test_get_default_platform_returns_none_when_empty(self):
        settings = Settings()
        assert settings.get_default_platform() is None

    def test_get_default_platform_returns_jira(self):
        from ingot.integrations.providers import Platform

        settings = Settings(default_platform="jira")
        assert settings.get_default_platform() == Platform.JIRA

    def test_get_default_platform_returns_linear(self):
        from ingot.integrations.providers import Platform

        settings = Settings(default_platform="linear")
        assert settings.get_default_platform() == Platform.LINEAR

    def test_get_default_platform_case_insensitive(self):
        from ingot.integrations.providers import Platform

        assert Settings(default_platform="JIRA").get_default_platform() == Platform.JIRA
        assert Settings(default_platform="Jira").get_default_platform() == Platform.JIRA
        assert Settings(default_platform="LINEAR").get_default_platform() == Platform.LINEAR

    def test_get_default_platform_returns_none_for_invalid(self):
        settings = Settings(default_platform="invalid_platform")
        assert settings.get_default_platform() is None

    def test_get_default_platform_all_valid_platforms(self):
        from ingot.integrations.providers import Platform

        assert Settings(default_platform="github").get_default_platform() == Platform.GITHUB
        assert (
            Settings(default_platform="azure_devops").get_default_platform()
            == Platform.AZURE_DEVOPS
        )
        assert Settings(default_platform="monday").get_default_platform() == Platform.MONDAY
        assert Settings(default_platform="trello").get_default_platform() == Platform.TRELLO


class TestConfigFile:
    def test_config_file_in_home(self):
        assert CONFIG_FILE.parent == Path.home()

    def test_config_file_name(self):
        assert CONFIG_FILE.name == ".ingot-config"
