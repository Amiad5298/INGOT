"""Tests for spec.config.manager module.

Tests cover:
- ConfigManager.load method with legacy and cascading hierarchy
- ConfigManager.save method with validation and atomic writes
- ConfigManager.get method
- ConfigManager.show method
- Cascading hierarchy: environment > local > global > defaults
- Local config discovery (_find_local_config)
- Environment variable loading (_load_environment)
"""

from unittest.mock import patch

import pytest

from spec.config.manager import ConfigManager


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
        config_file.write_text(
            """# This is a comment
DEFAULT_MODEL="test"
# Another comment
PLANNING_MODEL="test2"
"""
        )
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "test"
        assert settings.planning_model == "test2"

    def test_load_ignores_empty_lines(self, tmp_path):
        """Skips empty lines."""
        config_file = tmp_path / "config"
        config_file.write_text(
            """DEFAULT_MODEL="test"

PLANNING_MODEL="test2"

"""
        )
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
        config_file.write_text("DEFAULT_MODEL=test-model\n")
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
        config_file.write_text(
            """DEFAULT_MODEL="Claude Opus 4.5 [opus4.5]"
PLANNING_MODEL="Haiku 4.5 [haiku4.5]"
IMPLEMENTATION_MODEL="Sonnet 4.5 [sonnet4.5]"
"""
        )
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "opus4.5"
        assert settings.planning_model == "haiku4.5"
        assert settings.implementation_model == "sonnet4.5"

    def test_load_keeps_model_id_format_unchanged(self, tmp_path):
        """Keeps model ID format unchanged if already in ID-only format."""
        config_file = tmp_path / "config"
        config_file.write_text(
            """DEFAULT_MODEL="opus4.5"
PLANNING_MODEL="haiku4.5"
"""
        )
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

    @patch("spec.utils.console.print_header")
    @patch("spec.utils.console.print_info")
    @patch("spec.utils.console.console")
    def test_show_missing_file(self, mock_console, mock_info, mock_header, tmp_path):
        """Shows message when config file doesn't exist."""
        config_path = tmp_path / "missing"
        manager = ConfigManager(config_path)

        manager.show()

        mock_header.assert_called_once()
        assert mock_info.call_count >= 1

    @patch("spec.utils.console.print_header")
    @patch("spec.utils.console.print_info")
    @patch("spec.utils.console.console")
    def test_show_displays_settings(self, mock_console, mock_info, mock_header, temp_config_file):
        """Shows all settings from config file."""
        manager = ConfigManager(temp_config_file)
        manager.load()

        manager.show()

        mock_header.assert_called_once()
        # Should print multiple setting lines
        assert mock_console.print.call_count >= 5


class TestCascadingConfigHierarchy:
    """Tests for cascading configuration hierarchy."""

    def test_global_config_loaded(self, tmp_path):
        """Global config values are loaded."""
        # Create global config
        global_config = tmp_path / ".spec-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "global-model"

    def test_local_overrides_global(self, tmp_path, monkeypatch):
        """Local config overrides global config."""
        # Create global config
        global_config = tmp_path / ".spec-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        # Create local config in a subdirectory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".spec"
        local_config.write_text('DEFAULT_MODEL="local-model"\n')

        # Create fake .git to mark repo root
        (project_dir / ".git").mkdir()

        # Change to project directory
        monkeypatch.chdir(project_dir)

        # Create manager with explicit global config path
        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "local-model"

    def test_environment_overrides_all(self, tmp_path, monkeypatch):
        """Environment variables override local and global config."""
        # Create global config
        global_config = tmp_path / ".spec-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        # Create local config
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".spec"
        local_config.write_text('DEFAULT_MODEL="local-model"\n')
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        # Set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "env-model"

    def test_multiple_keys_from_different_sources(self, tmp_path, monkeypatch):
        """Different keys can come from different sources."""
        # Global has multiple keys
        global_config = tmp_path / ".spec-config"
        global_config.write_text(
            """DEFAULT_MODEL="global-model"
PLANNING_MODEL="global-planning"
DEFAULT_JIRA_PROJECT="GLOBAL"
"""
        )

        # Local overrides one key
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".spec"
        local_config.write_text('DEFAULT_JIRA_PROJECT="LOCAL"\n')
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        # Environment overrides another
        monkeypatch.setenv("PLANNING_MODEL", "env-planning")

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "global-model"  # from global
        assert settings.planning_model == "env-planning"  # from env
        assert settings.default_jira_project == "LOCAL"  # from local


class TestFindLocalConfig:
    """Tests for _find_local_config method."""

    def test_finds_config_in_cwd(self, tmp_path, monkeypatch):
        """Finds .spec in current directory."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".spec"
        local_config.write_text("TEST_KEY=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found == local_config

    def test_finds_config_in_parent(self, tmp_path, monkeypatch):
        """Finds .spec in parent directory."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sub_dir = project_dir / "src" / "module"
        sub_dir.mkdir(parents=True)
        local_config = project_dir / ".spec"
        local_config.write_text("TEST_KEY=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(sub_dir)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found == local_config

    def test_stops_at_git_root(self, tmp_path, monkeypatch):
        """Stops traversing at .git directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = workspace / "project"
        project.mkdir()
        (project / ".git").mkdir()

        # Config above .git should not be found
        (workspace / ".spec").write_text("TEST_KEY=value\n")
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None

    def test_returns_none_if_not_found(self, tmp_path, monkeypatch):
        """Returns None when no .spec exists."""
        project = tmp_path / "empty-project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None

    def test_ignores_spec_directory(self, tmp_path, monkeypatch):
        """Ignores .spec if it is a directory, not a file."""
        project = tmp_path / "project"
        project.mkdir()
        # Create .spec as a directory instead of a file
        spec_dir = project / ".spec"
        spec_dir.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None


class TestLoadEnvironment:
    """Tests for _load_environment method."""

    def test_loads_known_keys_only(self, tmp_path, monkeypatch):
        """Only loads environment variables for known config keys."""
        config_path = tmp_path / "config"
        config_path.write_text("")
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")
        monkeypatch.setenv("UNKNOWN_RANDOM_VAR", "should-be-ignored")

        manager = ConfigManager(config_path)
        manager.load()

        assert manager._raw_values.get("DEFAULT_MODEL") == "env-model"
        assert "UNKNOWN_RANDOM_VAR" not in manager._raw_values

    def test_empty_env_values_are_loaded(self, tmp_path, monkeypatch):
        """Empty environment values are still loaded."""
        config_path = tmp_path / "config"
        config_path.write_text('DEFAULT_MODEL="file-model"\n')
        monkeypatch.setenv("DEFAULT_MODEL", "")

        manager = ConfigManager(config_path)
        manager.load()

        assert manager._raw_values.get("DEFAULT_MODEL") == ""


class TestConfigManagerPathAccessors:
    """Tests for config path attributes."""

    def test_global_config_path_attribute(self, tmp_path):
        """global_config_path is set from constructor."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        assert manager.global_config_path == config_path

    def test_local_config_path_none_before_load(self, tmp_path):
        """local_config_path is None before load."""
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        assert manager.local_config_path is None

    def test_local_config_path_set_after_load(self, tmp_path, monkeypatch):
        """local_config_path is set after load finds local config."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".spec"
        local_config.write_text("TEST=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        manager = ConfigManager(tmp_path / "nonexistent")
        manager.load()

        assert manager.local_config_path == local_config


class TestConfigManagerIdempotency:
    """Tests for ConfigManager.load() idempotency."""

    def test_load_resets_settings_on_each_call(self, tmp_path):
        """Each load() call starts with fresh defaults."""
        config_path = tmp_path / "config"
        config_path.write_text('DEFAULT_MODEL="first-model"\n')

        manager = ConfigManager(config_path)
        settings1 = manager.load()
        assert settings1.default_model == "first-model"

        # Change the config file
        config_path.write_text('DEFAULT_MODEL="second-model"\n')

        # Load again - should get new values, not stale ones
        settings2 = manager.load()
        assert settings2.default_model == "second-model"

    def test_load_resets_local_config_path(self, tmp_path, monkeypatch):
        """Each load() resets local_config_path."""
        # First load with local config
        project1 = tmp_path / "project1"
        project1.mkdir()
        local1 = project1 / ".spec"
        local1.write_text("TEST=value1\n")
        (project1 / ".git").mkdir()
        monkeypatch.chdir(project1)

        manager = ConfigManager(tmp_path / "global")
        manager.load()
        assert manager.local_config_path == local1

        # Second load in project without local config
        project2 = tmp_path / "project2"
        project2.mkdir()
        (project2 / ".git").mkdir()
        monkeypatch.chdir(project2)

        manager.load()
        assert manager.local_config_path is None

    def test_load_clears_raw_values(self, tmp_path):
        """Each load() clears _raw_values from previous load."""
        config_path = tmp_path / "config"
        config_path.write_text('KEY1="value1"\nKEY2="value2"\n')

        manager = ConfigManager(config_path)
        manager.load()
        assert "KEY1" in manager._raw_values
        assert "KEY2" in manager._raw_values

        # New config with only KEY1
        config_path.write_text('KEY1="new-value1"\n')
        manager.load()
        assert manager._raw_values.get("KEY1") == "new-value1"
        assert "KEY2" not in manager._raw_values


class TestConfigManagerSaveScope:
    """Tests for ConfigManager.save() scope parameter."""

    def test_save_to_global_by_default(self, tmp_path):
        """save() writes to global config by default."""
        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)

        manager.save("TEST_KEY", "test_value")

        assert global_config.exists()
        assert 'TEST_KEY="test_value"' in global_config.read_text()

    def test_save_to_local_scope(self, tmp_path, monkeypatch):
        """save() with scope='local' writes to local config."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager(tmp_path / "global")
        manager.load()  # Establish local config path

        manager.save("LOCAL_KEY", "local_value", scope="local")

        local_config = project / ".spec"
        assert local_config.exists()
        assert 'LOCAL_KEY="local_value"' in local_config.read_text()

    def test_save_invalid_scope_raises(self, tmp_path):
        """Invalid scope raises ValueError."""
        manager = ConfigManager(tmp_path / "config")

        with pytest.raises(ValueError, match="Invalid scope"):
            manager.save("KEY", "value", scope="invalid")

    def test_save_warns_when_local_overrides_global(self, tmp_path, monkeypatch):
        """save() returns warning when local config overrides saved value."""
        project = tmp_path / "project"
        project.mkdir()
        local_config = project / ".spec"
        local_config.write_text('OVERRIDE_KEY="local-value"\n')
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)
        manager.load()

        warning = manager.save("OVERRIDE_KEY", "global-value")

        assert warning is not None
        assert "overridden" in warning.lower()
        assert "local" in warning.lower()

    def test_save_warns_when_env_overrides(self, tmp_path, monkeypatch):
        """save() returns warning when env var overrides saved value."""
        monkeypatch.setenv("ENV_KEY", "env-value")

        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)
        manager.load()

        warning = manager.save("ENV_KEY", "saved-value")

        assert warning is not None
        assert "overridden" in warning.lower()
        assert "environment" in warning.lower()

    def test_save_no_warning_when_not_overridden(self, tmp_path):
        """save() returns None when value is not overridden."""
        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)
        manager.load()

        warning = manager.save("UNIQUE_KEY", "value")

        assert warning is None

    def test_save_to_local_creates_file(self, tmp_path, monkeypatch):
        """save() with scope='local' creates .spec if it doesn't exist."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager(tmp_path / "global")
        # Don't call load() - local_config_path should be None
        assert manager.local_config_path is None

        manager.save("NEW_KEY", "new_value", scope="local")

        local_config = project / ".spec"
        assert local_config.exists()
        assert 'NEW_KEY="new_value"' in local_config.read_text()


class TestConfigManagerSavePrecedence:
    """Tests for ConfigManager.save() precedence correctness.

    These tests verify that after calling save(), the in-memory state
    correctly reflects the effective precedence (env > local > global).
    """

    def test_global_save_when_local_overrides(self, tmp_path, monkeypatch):
        """Global save preserves local override in memory.

        Verifies that when saving to global config while local config
        overrides the same key, the in-memory settings still reflect
        the local (higher priority) value.
        """
        # Setup: global has one value, local has a different value
        global_config = tmp_path / ".spec-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        project = tmp_path / "project"
        project.mkdir()
        local_config = project / ".spec"
        local_config.write_text('DEFAULT_MODEL="local-model"\n')
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager(global_config)
        manager.load()

        # Verify initial state
        assert manager.settings.default_model == "local-model"

        # Act: save a new value to global
        warning = manager.save("DEFAULT_MODEL", "new-global", scope="global")

        # Assert: warning mentions local override
        assert warning is not None
        assert "overridden" in warning.lower()
        assert "local" in warning.lower()

        # Assert: global file was updated
        assert 'DEFAULT_MODEL="new-global"' in global_config.read_text()

        # Assert: in-memory state still reflects local (higher priority)
        assert manager.settings.default_model == "local-model"
        assert manager.get("DEFAULT_MODEL") == "local-model"

    def test_global_save_when_env_overrides(self, tmp_path, monkeypatch):
        """Global save preserves env override in memory.

        Verifies that when saving to global config while an environment
        variable overrides the same key, the in-memory settings still
        reflect the env (highest priority) value.
        """
        # Setup: set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)
        manager.load()

        # Verify initial state
        assert manager.settings.default_model == "env-model"

        # Act: save a new value to global
        warning = manager.save("DEFAULT_MODEL", "new-global", scope="global")

        # Assert: warning mentions env override
        assert warning is not None
        assert "overridden" in warning.lower()
        assert "environment" in warning.lower()

        # Assert: global file was updated
        assert 'DEFAULT_MODEL="new-global"' in global_config.read_text()

        # Assert: in-memory state still reflects env (highest priority)
        assert manager.settings.default_model == "env-model"
        assert manager.get("DEFAULT_MODEL") == "env-model"

    def test_local_save_when_env_overrides(self, tmp_path, monkeypatch):
        """Local save preserves env override in memory.

        Verifies that when saving to local config while an environment
        variable overrides the same key, the in-memory settings still
        reflect the env (highest priority) value.
        """
        # Setup: set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)
        manager.load()

        # Verify initial state
        assert manager.settings.default_model == "env-model"

        # Act: save a new value to local
        warning = manager.save("DEFAULT_MODEL", "new-local", scope="local")

        # Assert: warning mentions env override
        assert warning is not None
        assert "overridden" in warning.lower()
        assert "environment" in warning.lower()

        # Assert: local file was created with new value
        local_config = project / ".spec"
        assert local_config.exists()
        assert 'DEFAULT_MODEL="new-local"' in local_config.read_text()

        # Assert: in-memory state still reflects env (highest priority)
        assert manager.settings.default_model == "env-model"
        assert manager.get("DEFAULT_MODEL") == "env-model"

    def test_global_save_without_override_updates_memory(self, tmp_path):
        """Global save updates memory when no higher priority overrides.

        Verifies that when saving to global config without any local
        or env overrides, the in-memory settings are updated.
        """
        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)
        manager.load()

        # Verify initial state (defaults)
        assert manager.settings.default_model == ""

        # Act: save a new value to global
        warning = manager.save("DEFAULT_MODEL", "new-global", scope="global")

        # Assert: no warning
        assert warning is None

        # Assert: global file was created with new value
        assert 'DEFAULT_MODEL="new-global"' in global_config.read_text()

        # Assert: in-memory state is updated
        assert manager.settings.default_model == "new-global"
        assert manager.get("DEFAULT_MODEL") == "new-global"

    def test_local_save_without_env_updates_memory(self, tmp_path, monkeypatch):
        """Local save updates memory when no env override exists.

        Verifies that when saving to local config without env override,
        the in-memory settings are updated.
        """
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        manager = ConfigManager(global_config)
        manager.load()

        # Verify initial state
        assert manager.settings.default_model == "global-model"

        # Act: save a new value to local
        warning = manager.save("DEFAULT_MODEL", "new-local", scope="local")

        # Assert: no warning (local is higher priority than global)
        assert warning is None

        # Assert: local file was created with new value
        local_config = project / ".spec"
        assert local_config.exists()
        assert 'DEFAULT_MODEL="new-local"' in local_config.read_text()

        # Assert: in-memory state is updated (local > global)
        assert manager.settings.default_model == "new-local"
        assert manager.get("DEFAULT_MODEL") == "new-local"

    def test_local_config_path_correct_after_save(self, tmp_path, monkeypatch):
        """local_config_path is correctly set after save creates local file."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)
        # Don't call load() first to test save creating local config

        # Act: save to local (creates the file)
        manager.save("TEST_KEY", "test_value", scope="local")

        # Assert: local_config_path is set correctly
        expected_path = project / ".spec"
        assert manager.local_config_path == expected_path
        assert manager.local_config_path.exists()


class TestConfigManagerSensitiveValueMasking:
    """Tests for sensitive value masking in logs."""

    def test_is_sensitive_key_detects_token(self):
        """Keys containing TOKEN are detected as sensitive."""
        assert ConfigManager._is_sensitive_key("JIRA_TOKEN") is True
        assert ConfigManager._is_sensitive_key("jira_token") is True
        assert ConfigManager._is_sensitive_key("MY_API_TOKEN") is True

    def test_is_sensitive_key_detects_key(self):
        """Keys containing KEY are detected as sensitive."""
        assert ConfigManager._is_sensitive_key("API_KEY") is True
        assert ConfigManager._is_sensitive_key("api_key") is True
        assert ConfigManager._is_sensitive_key("ENCRYPTION_KEY") is True

    def test_is_sensitive_key_detects_secret(self):
        """Keys containing SECRET are detected as sensitive."""
        assert ConfigManager._is_sensitive_key("CLIENT_SECRET") is True
        assert ConfigManager._is_sensitive_key("secret_value") is True

    def test_is_sensitive_key_detects_password(self):
        """Keys containing PASSWORD are detected as sensitive."""
        assert ConfigManager._is_sensitive_key("DB_PASSWORD") is True
        assert ConfigManager._is_sensitive_key("password") is True

    def test_is_sensitive_key_detects_pat(self):
        """Keys containing PAT are detected as sensitive."""
        assert ConfigManager._is_sensitive_key("GITHUB_PAT") is True
        assert ConfigManager._is_sensitive_key("pat_token") is True

    def test_is_sensitive_key_non_sensitive(self):
        """Non-sensitive keys are not flagged."""
        assert ConfigManager._is_sensitive_key("DEFAULT_MODEL") is False
        assert ConfigManager._is_sensitive_key("AUTO_OPEN_FILES") is False
        assert ConfigManager._is_sensitive_key("JIRA_PROJECT") is False

    def test_save_does_not_log_sensitive_values(self, tmp_path, monkeypatch, caplog):
        """Sensitive values are not logged in plaintext."""
        import logging

        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        # Enable logging
        monkeypatch.setenv("SPEC_LOG", "true")

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Capture logs
        with caplog.at_level(logging.DEBUG):
            manager.save("API_TOKEN", "super-secret-value-12345", scope="global")

        # Assert: secret value is not in logs
        log_text = caplog.text
        assert "super-secret-value-12345" not in log_text
        assert "REDACTED" in log_text or "API_TOKEN" in log_text


class TestConfigManagerQuoteEscaping:
    """Tests for quote and special character escaping in config values."""

    def test_escape_value_for_storage_handles_quotes(self):
        """Double quotes are escaped for storage."""
        result = ConfigManager._escape_value_for_storage('value with "quotes"')
        assert result == 'value with \\"quotes\\"'

    def test_escape_value_for_storage_handles_backslashes(self):
        """Backslashes are escaped for storage."""
        result = ConfigManager._escape_value_for_storage("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_value_for_storage_handles_both(self):
        """Both quotes and backslashes are escaped correctly."""
        result = ConfigManager._escape_value_for_storage('say \\"hello\\"')
        assert result == 'say \\\\\\"hello\\\\\\"'

    def test_unescape_value_reverses_quotes(self):
        """Escaped quotes are unescaped correctly."""
        result = ConfigManager._unescape_value('value with \\"quotes\\"')
        assert result == 'value with "quotes"'

    def test_unescape_value_reverses_backslashes(self):
        """Escaped backslashes are unescaped correctly."""
        result = ConfigManager._unescape_value("path\\\\to\\\\file")
        assert result == "path\\to\\file"

    def test_round_trip_with_quotes(self, tmp_path, monkeypatch):
        """Values with quotes survive save/load round-trip."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Save value with quotes
        original_value = 'model with "special" name'
        manager.save("TEST_VALUE", original_value, scope="global")

        # Create new manager and load
        manager2 = ConfigManager(global_config)
        manager2.load()

        # Assert: value is preserved
        assert manager2.get("TEST_VALUE") == original_value

    def test_round_trip_with_backslashes(self, tmp_path, monkeypatch):
        """Values with backslashes survive save/load round-trip."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Save value with backslashes
        original_value = "C:\\Users\\test\\path"
        manager.save("TEST_PATH", original_value, scope="global")

        # Create new manager and load
        manager2 = ConfigManager(global_config)
        manager2.load()

        # Assert: value is preserved
        assert manager2.get("TEST_PATH") == original_value

    def test_round_trip_with_special_characters(self, tmp_path, monkeypatch):
        """Values with various special characters survive save/load round-trip."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Save value with multiple special characters
        original_value = 'path\\to\\"file" with spaces & symbols!'
        manager.save("COMPLEX_VALUE", original_value, scope="global")

        # Create new manager and load
        manager2 = ConfigManager(global_config)
        manager2.load()

        # Assert: value is preserved
        assert manager2.get("COMPLEX_VALUE") == original_value

    def test_single_quoted_values_not_unescaped(self, tmp_path, monkeypatch):
        """Single-quoted values in config file are not unescaped (literal treatment)."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"

        # Manually write a config file with single-quoted value containing backslashes
        # In bash single quotes, \\ is literal (not an escape sequence)
        global_config.write_text("SINGLE_QUOTED='path\\\\with\\\\backslashes'\n")

        # Load the config
        manager = ConfigManager(global_config)
        manager.load()

        # Assert: backslashes are preserved literally (not unescaped)
        assert manager.get("SINGLE_QUOTED") == "path\\\\with\\\\backslashes"

    def test_double_quoted_values_are_unescaped(self, tmp_path, monkeypatch):
        """Double-quoted values in config file are properly unescaped."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"

        # Manually write a config file with double-quoted escaped value
        # This represents a value that was escaped on save
        global_config.write_text('DOUBLE_QUOTED="path\\\\with\\\\backslashes"\n')

        # Load the config
        manager = ConfigManager(global_config)
        manager.load()

        # Assert: backslashes are unescaped (double backslash -> single)
        assert manager.get("DOUBLE_QUOTED") == "path\\with\\backslashes"


class TestConfigManagerRepoRootDetection:
    """Tests for local config creation at repository root."""

    def test_save_local_creates_at_repo_root_from_nested_dir(self, tmp_path, monkeypatch):
        """Local config is created at repo root when saving from nested directory."""
        # Setup: repo with nested directory structure
        repo_root = tmp_path / "my-repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        nested_dir = repo_root / "src" / "deep" / "nested"
        nested_dir.mkdir(parents=True)

        # Change to nested directory
        monkeypatch.chdir(nested_dir)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Act: save to local scope
        manager.save("PROJECT_SETTING", "value", scope="local")

        # Assert: config created at repo root, not in nested dir
        expected_path = repo_root / ".spec"
        assert expected_path.exists()
        assert not (nested_dir / ".spec").exists()
        assert manager.local_config_path == expected_path

    def test_save_local_falls_back_to_cwd_without_git(self, tmp_path, monkeypatch):
        """Local config is created in cwd when no .git directory exists."""
        # Setup: directory without .git
        project = tmp_path / "no-git-project"
        project.mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".spec-config"
        manager = ConfigManager(global_config)

        # Act: save to local scope
        manager.save("SETTING", "value", scope="local")

        # Assert: config created in cwd
        expected_path = project / ".spec"
        assert expected_path.exists()
        assert manager.local_config_path == expected_path


class TestFetchConfigEnums:
    """Tests for FetchStrategy and AgentPlatform enums."""

    def test_fetch_strategy_values(self):
        """FetchStrategy enum has correct values."""
        from spec.config.fetch_config import FetchStrategy

        assert FetchStrategy.AGENT.value == "agent"
        assert FetchStrategy.DIRECT.value == "direct"
        assert FetchStrategy.AUTO.value == "auto"

    def test_fetch_strategy_from_string(self):
        """FetchStrategy can be created from string value."""
        from spec.config.fetch_config import FetchStrategy

        assert FetchStrategy("agent") == FetchStrategy.AGENT
        assert FetchStrategy("direct") == FetchStrategy.DIRECT
        assert FetchStrategy("auto") == FetchStrategy.AUTO

    def test_fetch_strategy_invalid_value(self):
        """FetchStrategy raises ValueError for invalid value."""
        from spec.config.fetch_config import FetchStrategy

        with pytest.raises(ValueError):
            FetchStrategy("invalid")

    def test_agent_platform_values(self):
        """AgentPlatform enum has correct values."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform.AUGGIE.value == "auggie"
        assert AgentPlatform.CLAUDE_DESKTOP.value == "claude_desktop"
        assert AgentPlatform.CURSOR.value == "cursor"
        assert AgentPlatform.AIDER.value == "aider"
        assert AgentPlatform.MANUAL.value == "manual"

    def test_agent_platform_from_string(self):
        """AgentPlatform can be created from string value."""
        from spec.config.fetch_config import AgentPlatform

        assert AgentPlatform("auggie") == AgentPlatform.AUGGIE
        assert AgentPlatform("cursor") == AgentPlatform.CURSOR

    def test_agent_platform_invalid_value(self):
        """AgentPlatform raises ValueError for invalid value."""
        from spec.config.fetch_config import AgentPlatform

        with pytest.raises(ValueError):
            AgentPlatform("unknown")


class TestFetchConfigDataclasses:
    """Tests for fetch config dataclasses."""

    def test_agent_config_defaults(self):
        """AgentConfig has correct defaults."""
        from spec.config.fetch_config import AgentConfig, AgentPlatform

        config = AgentConfig()
        assert config.platform == AgentPlatform.AUGGIE
        assert config.integrations == {}

    def test_agent_config_supports_platform(self):
        """AgentConfig.supports_platform() works correctly."""
        from spec.config.fetch_config import AgentConfig

        config = AgentConfig(integrations={"jira": True, "linear": True, "github": False})
        assert config.supports_platform("jira") is True
        assert config.supports_platform("JIRA") is True  # Case insensitive
        assert config.supports_platform("linear") is True
        assert config.supports_platform("github") is False
        assert config.supports_platform("unknown") is False

    def test_fetch_strategy_config_defaults(self):
        """FetchStrategyConfig has correct defaults."""
        from spec.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig()
        assert config.default == FetchStrategy.AUTO
        assert config.per_platform == {}

    def test_fetch_strategy_config_get_strategy_default(self):
        """FetchStrategyConfig.get_strategy() returns default for unknown platforms."""
        from spec.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig(default=FetchStrategy.AGENT)
        assert config.get_strategy("jira") == FetchStrategy.AGENT
        assert config.get_strategy("unknown") == FetchStrategy.AGENT

    def test_fetch_strategy_config_get_strategy_override(self):
        """FetchStrategyConfig.get_strategy() returns per-platform override."""
        from spec.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig(
            default=FetchStrategy.AUTO,
            per_platform={"azure_devops": FetchStrategy.DIRECT, "jira": FetchStrategy.AGENT},
        )
        assert config.get_strategy("azure_devops") == FetchStrategy.DIRECT
        assert (
            config.get_strategy("AZURE_DEVOPS") == FetchStrategy.DIRECT
        )  # Case insensitive lookup
        assert config.get_strategy("jira") == FetchStrategy.AGENT
        assert config.get_strategy("linear") == FetchStrategy.AUTO  # Falls back to default

    def test_fetch_performance_config_defaults(self):
        """FetchPerformanceConfig has correct defaults."""
        from spec.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig()
        assert config.cache_duration_hours == 24
        assert config.timeout_seconds == 30
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0

    def test_fetch_performance_config_custom_values(self):
        """FetchPerformanceConfig accepts custom values."""
        from spec.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig(
            cache_duration_hours=48,
            timeout_seconds=60,
            max_retries=5,
            retry_delay_seconds=2.5,
        )
        assert config.cache_duration_hours == 48
        assert config.timeout_seconds == 60
        assert config.max_retries == 5
        assert config.retry_delay_seconds == 2.5


class TestConfigManagerEnvVarExpansion:
    """Tests for _expand_env_vars method."""

    def test_expand_env_vars_string(self, tmp_path, monkeypatch):
        """Expands ${VAR} in strings."""
        monkeypatch.setenv("TEST_VAR", "expanded_value")
        manager = ConfigManager(tmp_path / "config")

        result = manager._expand_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_expanded_value_suffix"

    def test_expand_env_vars_missing_var(self, tmp_path):
        """Preserves ${VAR} when variable not set."""
        manager = ConfigManager(tmp_path / "config")

        result = manager._expand_env_vars("${MISSING_VAR}")
        assert result == "${MISSING_VAR}"

    def test_expand_env_vars_dict(self, tmp_path, monkeypatch):
        """Recursively expands in dicts."""
        monkeypatch.setenv("VAR1", "value1")
        monkeypatch.setenv("VAR2", "value2")
        manager = ConfigManager(tmp_path / "config")

        result = manager._expand_env_vars({"key1": "${VAR1}", "key2": "${VAR2}"})
        assert result == {"key1": "value1", "key2": "value2"}

    def test_expand_env_vars_list(self, tmp_path, monkeypatch):
        """Recursively expands in lists."""
        monkeypatch.setenv("ITEM", "expanded")
        manager = ConfigManager(tmp_path / "config")

        result = manager._expand_env_vars(["${ITEM}", "static"])
        assert result == ["expanded", "static"]

    def test_expand_env_vars_nested(self, tmp_path, monkeypatch):
        """Recursively expands in nested structures."""
        monkeypatch.setenv("NESTED", "deep_value")
        manager = ConfigManager(tmp_path / "config")

        result = manager._expand_env_vars({"outer": {"inner": "${NESTED}"}})
        assert result == {"outer": {"inner": "deep_value"}}

    def test_expand_env_vars_non_string(self, tmp_path):
        """Returns non-string/dict/list values unchanged."""
        manager = ConfigManager(tmp_path / "config")

        assert manager._expand_env_vars(42) == 42
        assert manager._expand_env_vars(True) is True
        assert manager._expand_env_vars(None) is None


class TestConfigManagerGetAgentConfig:
    """Tests for get_agent_config method."""

    def test_get_agent_config_defaults(self, tmp_path):
        """Returns defaults when no config set."""
        from spec.config.fetch_config import AgentPlatform

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.platform == AgentPlatform.AUGGIE
        assert config.integrations == {}

    def test_get_agent_config_custom_platform(self, tmp_path):
        """Parses AGENT_PLATFORM from config."""
        from spec.config.fetch_config import AgentPlatform

        config_path = tmp_path / "config"
        config_path.write_text('AGENT_PLATFORM="cursor"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.platform == AgentPlatform.CURSOR

    def test_get_agent_config_invalid_platform_falls_back(self, tmp_path):
        """Falls back to AUGGIE for invalid platform."""
        from spec.config.fetch_config import AgentPlatform

        config_path = tmp_path / "config"
        config_path.write_text('AGENT_PLATFORM="invalid_platform"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.platform == AgentPlatform.AUGGIE

    def test_get_agent_config_integrations(self, tmp_path):
        """Parses AGENT_INTEGRATION_* keys."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
AGENT_INTEGRATION_GITHUB=false
AGENT_INTEGRATION_AZURE_DEVOPS=1
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.integrations["jira"] is True
        assert config.integrations["linear"] is True
        assert config.integrations["github"] is False
        assert config.integrations["azure_devops"] is True


class TestConfigManagerGetFetchStrategyConfig:
    """Tests for get_fetch_strategy_config method."""

    def test_get_fetch_strategy_config_defaults(self, tmp_path):
        """Returns defaults when no config set."""
        from spec.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AUTO
        assert config.per_platform == {}

    def test_get_fetch_strategy_config_custom_default(self, tmp_path):
        """Parses FETCH_STRATEGY_DEFAULT from config."""
        from spec.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text('FETCH_STRATEGY_DEFAULT="agent"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AGENT

    def test_get_fetch_strategy_config_invalid_default_falls_back(self, tmp_path):
        """Falls back to AUTO for invalid default strategy."""
        from spec.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text('FETCH_STRATEGY_DEFAULT="invalid"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AUTO

    def test_get_fetch_strategy_config_per_platform(self, tmp_path):
        """Parses FETCH_STRATEGY_* keys for per-platform overrides."""
        from spec.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_STRATEGY_DEFAULT=auto
FETCH_STRATEGY_AZURE_DEVOPS=direct
FETCH_STRATEGY_TRELLO=direct
FETCH_STRATEGY_JIRA=agent
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AUTO
        assert config.per_platform["azure_devops"] == FetchStrategy.DIRECT
        assert config.per_platform["trello"] == FetchStrategy.DIRECT
        assert config.per_platform["jira"] == FetchStrategy.AGENT

    def test_get_fetch_strategy_config_skips_invalid_overrides(self, tmp_path):
        """Skips per-platform overrides with invalid strategy values."""
        from spec.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_STRATEGY_VALID=direct
FETCH_STRATEGY_INVALID=not_a_strategy
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.per_platform["valid"] == FetchStrategy.DIRECT
        assert "invalid" not in config.per_platform


class TestConfigManagerGetFetchPerformanceConfig:
    """Tests for get_fetch_performance_config method."""

    def test_get_fetch_performance_config_defaults(self, tmp_path):
        """Returns defaults when no config set."""
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_performance_config()
        assert config.cache_duration_hours == 24
        assert config.timeout_seconds == 30
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0

    def test_get_fetch_performance_config_custom_values(self, tmp_path):
        """Parses performance settings from config."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_CACHE_DURATION_HOURS=48
FETCH_TIMEOUT_SECONDS=60
FETCH_MAX_RETRIES=5
FETCH_RETRY_DELAY_SECONDS=2.5
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_performance_config()
        assert config.cache_duration_hours == 48
        assert config.timeout_seconds == 60
        assert config.max_retries == 5
        assert config.retry_delay_seconds == 2.5

    def test_get_fetch_performance_config_invalid_values_use_defaults(self, tmp_path):
        """Invalid values are ignored, keeping defaults."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_CACHE_DURATION_HOURS=not_a_number
FETCH_TIMEOUT_SECONDS=60
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_performance_config()
        assert config.cache_duration_hours == 24  # Default kept
        assert config.timeout_seconds == 60  # Valid value used

    def test_get_fetch_performance_config_negative_values_use_defaults(self, tmp_path):
        """Negative values are rejected, keeping defaults."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_CACHE_DURATION_HOURS=-1
FETCH_TIMEOUT_SECONDS=-10
FETCH_MAX_RETRIES=-5
FETCH_RETRY_DELAY_SECONDS=-2.5
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_performance_config()
        assert config.cache_duration_hours == 24  # Default kept (negative rejected)
        assert config.timeout_seconds == 30  # Default kept (negative rejected)
        assert config.max_retries == 3  # Default kept (negative rejected)
        assert config.retry_delay_seconds == 1.0  # Default kept (negative rejected)

    def test_get_fetch_performance_config_zero_values(self, tmp_path):
        """Zero is valid for some fields but not timeout."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_CACHE_DURATION_HOURS=0
FETCH_TIMEOUT_SECONDS=0
FETCH_MAX_RETRIES=0
FETCH_RETRY_DELAY_SECONDS=0
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_performance_config()
        assert config.cache_duration_hours == 0  # Zero is valid (no caching)
        assert config.timeout_seconds == 30  # Default kept (zero not valid for timeout)
        assert config.max_retries == 0  # Zero is valid (no retries)
        assert config.retry_delay_seconds == 0.0  # Zero is valid


class TestConfigManagerGetFallbackCredentials:
    """Tests for get_fallback_credentials method."""

    def test_get_fallback_credentials_none_when_missing(self, tmp_path):
        """Returns None when no credentials configured."""
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is None

    def test_get_fallback_credentials_returns_dict(self, tmp_path):
        """Returns dict of credentials for platform."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PROJECT=myproject
FALLBACK_AZURE_DEVOPS_PAT=secret123
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is not None
        assert creds["organization"] == "myorg"
        assert creds["project"] == "myproject"
        assert creds["pat"] == "secret123"

    def test_get_fallback_credentials_case_insensitive_platform(self, tmp_path):
        """Platform name is case insensitive."""
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_JIRA_TOKEN=token123\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("JIRA")
        assert creds is not None
        assert creds["token"] == "token123"

    def test_get_fallback_credentials_expands_env_vars(self, tmp_path, monkeypatch):
        """Expands ${VAR} in credential values."""
        monkeypatch.setenv("SECRET_PAT", "actual_secret_value")
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_AZURE_DEVOPS_PAT=${SECRET_PAT}\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is not None
        assert creds["pat"] == "actual_secret_value"

    def test_get_fallback_credentials_preserves_unset_env_vars(self, tmp_path):
        """Preserves ${VAR} when env var not set."""
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_TEST_TOKEN=${UNSET_VAR}\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("test")
        assert creds is not None
        assert creds["token"] == "${UNSET_VAR}"


class TestFetchConfigEndToEnd:
    """End-to-end tests for fetch configuration loading."""

    def test_full_fetch_config_from_file(self, tmp_path, monkeypatch):
        """Loads complete fetch configuration from file."""
        from spec.config.fetch_config import AgentPlatform, FetchStrategy

        monkeypatch.setenv("MY_PAT", "secret_pat_value")

        config_path = tmp_path / "config"
        config_path.write_text(
            """# Agent configuration
AGENT_PLATFORM=cursor
AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
AGENT_INTEGRATION_GITHUB=false

# Fetch strategy
FETCH_STRATEGY_DEFAULT=auto
FETCH_STRATEGY_AZURE_DEVOPS=direct

# Performance
FETCH_CACHE_DURATION_HOURS=12
FETCH_TIMEOUT_SECONDS=45

# Fallback credentials
FALLBACK_AZURE_DEVOPS_ORG=myorg
FALLBACK_AZURE_DEVOPS_PAT=${MY_PAT}
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        # Check agent config
        agent_config = manager.get_agent_config()
        assert agent_config.platform == AgentPlatform.CURSOR
        assert agent_config.supports_platform("jira") is True
        assert agent_config.supports_platform("github") is False

        # Check fetch strategy config
        strategy_config = manager.get_fetch_strategy_config()
        assert strategy_config.default == FetchStrategy.AUTO
        assert strategy_config.get_strategy("azure_devops") == FetchStrategy.DIRECT
        assert strategy_config.get_strategy("jira") == FetchStrategy.AUTO

        # Check performance config
        perf_config = manager.get_fetch_performance_config()
        assert perf_config.cache_duration_hours == 12
        assert perf_config.timeout_seconds == 45

        # Check fallback credentials with env var expansion
        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is not None
        assert creds["org"] == "myorg"
        assert creds["pat"] == "secret_pat_value"


class TestEnvVarExpansionStrict:
    """Tests for strict mode environment variable expansion."""

    def test_expand_env_vars_strict_mode_raises_on_missing(self, tmp_path, monkeypatch):
        """Strict mode raises EnvVarExpansionError for missing env vars."""
        from spec.config.manager import EnvVarExpansionError

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(EnvVarExpansionError) as exc_info:
            manager.expand_env_vars_strict("${MISSING_VAR}", context="test_key")

        assert "MISSING_VAR" in str(exc_info.value)
        assert "test_key" in str(exc_info.value)

    def test_expand_env_vars_strict_mode_succeeds_when_set(self, tmp_path, monkeypatch):
        """Strict mode expands when env var is set."""
        monkeypatch.setenv("MY_SECRET", "secret_value")

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        result = manager.expand_env_vars_strict("token=${MY_SECRET}", context="test_key")
        assert result == "token=secret_value"

    def test_expand_env_vars_nested_dict(self, tmp_path, monkeypatch):
        """Expands env vars in nested dict structures."""
        monkeypatch.setenv("NESTED_VAR", "nested_value")

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        data = {"level1": {"level2": {"value": "${NESTED_VAR}"}}}
        result = manager._expand_env_vars(data)
        assert result["level1"]["level2"]["value"] == "nested_value"

    def test_expand_env_vars_nested_list(self, tmp_path, monkeypatch):
        """Expands env vars in list structures."""
        monkeypatch.setenv("LIST_VAR", "list_value")

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        data = ["${LIST_VAR}", "plain", "${LIST_VAR}"]
        result = manager._expand_env_vars(data)
        assert result == ["list_value", "plain", "list_value"]


class TestValidationFailures:
    """Tests for configuration validation failures."""

    def test_validate_strategy_agent_without_integration(self, tmp_path):
        """Agent strategy fails validation when agent lacks integration."""
        from spec.config.fetch_config import (
            AgentConfig,
            AgentPlatform,
            ConfigValidationError,
            FetchStrategy,
            validate_strategy_for_platform,
        )

        agent_config = AgentConfig(
            platform=AgentPlatform.AUGGIE,
            integrations={"jira": False},  # No Jira integration
        )

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_strategy_for_platform(
                platform="jira",
                strategy=FetchStrategy.AGENT,
                agent_config=agent_config,
                has_credentials=False,
                strict=True,
            )

        assert "agent" in str(exc_info.value).lower()
        assert "jira" in str(exc_info.value).lower()

    def test_validate_strategy_direct_without_credentials(self, tmp_path):
        """Direct strategy fails validation when no credentials exist."""
        from spec.config.fetch_config import (
            AgentConfig,
            AgentPlatform,
            ConfigValidationError,
            FetchStrategy,
            validate_strategy_for_platform,
        )

        agent_config = AgentConfig(platform=AgentPlatform.AUGGIE, integrations={})

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_strategy_for_platform(
                platform="azure_devops",
                strategy=FetchStrategy.DIRECT,
                agent_config=agent_config,
                has_credentials=False,
                strict=True,
            )

        assert "direct" in str(exc_info.value).lower()
        assert "credentials" in str(exc_info.value).lower()

    def test_validate_strategy_auto_without_either(self, tmp_path):
        """Auto strategy fails validation when neither integration nor creds exist."""
        from spec.config.fetch_config import (
            AgentConfig,
            AgentPlatform,
            ConfigValidationError,
            FetchStrategy,
            validate_strategy_for_platform,
        )

        agent_config = AgentConfig(platform=AgentPlatform.MANUAL, integrations={})

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_strategy_for_platform(
                platform="trello",
                strategy=FetchStrategy.AUTO,
                agent_config=agent_config,
                has_credentials=False,
                strict=True,
            )

        assert "auto" in str(exc_info.value).lower()
        assert "trello" in str(exc_info.value).lower()

    def test_validate_credentials_missing_required_fields(self):
        """Credential validation fails when required fields are missing."""
        from spec.config.fetch_config import ConfigValidationError, validate_credentials

        # Jira requires url, email, token
        incomplete_creds = {"url": "https://example.atlassian.net"}

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_credentials("jira", incomplete_creds, strict=True)

        assert "email" in str(exc_info.value) or "token" in str(exc_info.value)

    def test_validate_credentials_unexpanded_env_var(self):
        """Credential validation warns about unexpanded env vars."""
        from spec.config.fetch_config import validate_credentials

        creds = {
            "url": "https://example.atlassian.net",
            "email": "user@example.com",
            "token": "${UNSET_TOKEN}",  # Not expanded
        }

        errors = validate_credentials("jira", creds, strict=False)
        assert any("unexpanded" in e.lower() for e in errors)


class TestPerformanceGuardrails:
    """Tests for performance config upper bounds."""

    def test_performance_config_clamps_to_max(self):
        """Performance config clamps values to upper bounds."""
        from spec.config.fetch_config import (
            MAX_CACHE_DURATION_HOURS,
            MAX_RETRIES,
            MAX_RETRY_DELAY_SECONDS,
            MAX_TIMEOUT_SECONDS,
            FetchPerformanceConfig,
        )

        config = FetchPerformanceConfig(
            cache_duration_hours=1000,  # Exceeds max
            timeout_seconds=1000,  # Exceeds max
            max_retries=100,  # Exceeds max
            retry_delay_seconds=1000,  # Exceeds max
        )

        assert config.cache_duration_hours == MAX_CACHE_DURATION_HOURS
        assert config.timeout_seconds == MAX_TIMEOUT_SECONDS
        assert config.max_retries == MAX_RETRIES
        assert config.retry_delay_seconds == MAX_RETRY_DELAY_SECONDS

    def test_performance_config_accepts_valid_values(self):
        """Performance config accepts values within bounds."""
        from spec.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig(
            cache_duration_hours=48,
            timeout_seconds=60,
            max_retries=5,
            retry_delay_seconds=2.5,
        )

        assert config.cache_duration_hours == 48
        assert config.timeout_seconds == 60
        assert config.max_retries == 5
        assert config.retry_delay_seconds == 2.5


class TestNoSecretLeakage:
    """Tests to ensure secrets are never logged."""

    def test_sensitive_key_detection(self):
        """Sensitive key patterns are correctly detected."""
        from spec.config.manager import ConfigManager

        assert ConfigManager._is_sensitive_key("JIRA_TOKEN") is True
        assert ConfigManager._is_sensitive_key("AZURE_PAT") is True
        assert ConfigManager._is_sensitive_key("API_KEY") is True
        assert ConfigManager._is_sensitive_key("SECRET_VALUE") is True
        assert ConfigManager._is_sensitive_key("MY_PASSWORD") is True
        assert ConfigManager._is_sensitive_key("CREDENTIAL_DATA") is True
        assert ConfigManager._is_sensitive_key("DEFAULT_MODEL") is False
        assert ConfigManager._is_sensitive_key("AGENT_PLATFORM") is False

    def test_fallback_credentials_not_in_settings(self, tmp_path):
        """Fallback credentials are not exposed in settings attributes."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """FALLBACK_JIRA_TOKEN=super_secret
FALLBACK_AZURE_DEVOPS_PAT=another_secret
"""
        )
        manager = ConfigManager(config_path)
        settings = manager.load()

        # Settings should not have these as attributes
        assert not hasattr(settings, "fallback_jira_token")
        assert not hasattr(settings, "fallback_azure_devops_pat")

        # But they should be retrievable via get_fallback_credentials
        jira_creds = manager.get_fallback_credentials("jira")
        assert jira_creds is not None
        assert jira_creds["token"] == "super_secret"


class TestPlatformOverrideValidation:
    """Tests for per-platform override validation."""

    def test_unknown_platform_warning(self):
        """Unknown platforms in per_platform generate warnings."""
        from spec.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig(
            default=FetchStrategy.AUTO,
            per_platform={
                "jira": FetchStrategy.AGENT,
                "unknown_platform": FetchStrategy.DIRECT,
            },
        )

        warnings = config.validate_platform_overrides(strict=False)
        assert len(warnings) == 1
        assert "unknown_platform" in warnings[0]

    def test_unknown_platform_strict_raises(self):
        """Unknown platforms in strict mode raise ConfigValidationError."""
        from spec.config.fetch_config import (
            ConfigValidationError,
            FetchStrategy,
            FetchStrategyConfig,
        )

        config = FetchStrategyConfig(
            default=FetchStrategy.AUTO,
            per_platform={"not_a_real_platform": FetchStrategy.DIRECT},
        )

        with pytest.raises(ConfigValidationError):
            config.validate_platform_overrides(strict=True)


class TestSchemaValidation:
    """Tests for JSON Schema validation."""

    def test_valid_config_passes_schema(self):
        """Valid configuration passes schema validation."""
        from spec.config.schema import validate_config_dict

        config = {
            "agent": {"platform": "auggie", "integrations": {"jira": True}},
            "fetch_strategy": {"default": "auto", "per_platform": {"azure_devops": "direct"}},
            "performance": {"cache_duration_hours": 24, "timeout_seconds": 30},
        }

        errors = validate_config_dict(config)
        assert len(errors) == 0

    def test_invalid_strategy_fails_schema(self):
        """Invalid strategy value fails schema validation."""
        from spec.config.schema import validate_config_dict

        config = {"fetch_strategy": {"default": "invalid_strategy"}}

        errors = validate_config_dict(config)
        # Should have at least one error about invalid strategy
        assert len(errors) > 0


class TestValidateFetchConfig:
    """Tests for ConfigManager.validate_fetch_config method."""

    def test_validate_fetch_config_with_working_setup(self, tmp_path, monkeypatch):
        """Valid configuration passes full validation."""
        monkeypatch.setenv("JIRA_TOKEN", "test_token")

        config_path = tmp_path / "config"
        config_path.write_text(
            """AGENT_PLATFORM=auggie
AGENT_INTEGRATION_JIRA=true
FETCH_STRATEGY_DEFAULT=auto
FALLBACK_JIRA_URL=https://example.atlassian.net
FALLBACK_JIRA_EMAIL=user@example.com
FALLBACK_JIRA_TOKEN=${JIRA_TOKEN}
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        # Should not raise
        errors = manager.validate_fetch_config(strict=False)
        # May have warnings for platforms without config, but no critical errors
        assert not any("jira" in e.lower() and "missing" in e.lower() for e in errors)

    def test_validate_fetch_config_collects_all_errors(self, tmp_path):
        """Non-strict mode collects all validation errors."""
        config_path = tmp_path / "config"
        config_path.write_text(
            """AGENT_PLATFORM=manual
FETCH_STRATEGY_DEFAULT=agent
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        # Agent strategy with manual platform and no integrations
        errors = manager.validate_fetch_config(strict=False)
        # Should have errors for each platform that can't use agent strategy
        assert len(errors) > 0
