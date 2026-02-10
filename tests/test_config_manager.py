"""Tests for ingot.config.manager module.

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

from ingot.config.manager import ConfigManager


class TestConfigManagerLoad:
    def test_load_missing_file(self, tmp_path):
        config_path = tmp_path / "missing-config"
        manager = ConfigManager(config_path)

        settings = manager.load()

        assert settings.default_model == ""
        assert settings.auto_open_files is True

    def test_load_valid_file(self, temp_config_file):
        manager = ConfigManager(temp_config_file)

        settings = manager.load()

        assert settings.default_model == "claude-3"
        assert settings.planning_model == "claude-3-opus"
        assert settings.implementation_model == "claude-3-sonnet"

    def test_load_ignores_comments(self, tmp_path):
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
        config_file = tmp_path / "config"
        config_file.write_text('AUTO_OPEN_FILES="true"\n')
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.auto_open_files is True

    def test_load_parses_boolean_false(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text('AUTO_OPEN_FILES="false"\n')
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.auto_open_files is False

    def test_load_parses_integer(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text('JIRA_CHECK_TIMESTAMP="1234567890"\n')
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.jira_check_timestamp == 1234567890

    def test_load_handles_unquoted_values(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("DEFAULT_MODEL=test-model\n")
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "test-model"

    def test_load_handles_single_quotes(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("DEFAULT_MODEL='test-model'\n")
        manager = ConfigManager(config_file)

        settings = manager.load()

        assert settings.default_model == "test-model"

    def test_load_extracts_model_id_from_full_format(self, tmp_path):
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
    def test_save_validates_key(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        with pytest.raises(ValueError, match="Invalid config key"):
            manager.save("invalid-key", "value")

    def test_save_validates_key_starting_with_number(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        with pytest.raises(ValueError, match="Invalid config key"):
            manager.save("123KEY", "value")

    def test_save_creates_file(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        manager.save("TEST_KEY", "test_value")

        assert config_path.exists()
        assert 'TEST_KEY="test_value"' in config_path.read_text()

    def test_save_updates_existing_key(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text('TEST_KEY="old_value"\n')
        manager = ConfigManager(config_path)
        manager.load()

        manager.save("TEST_KEY", "new_value")

        content = config_path.read_text()
        assert 'TEST_KEY="new_value"' in content
        assert "old_value" not in content

    def test_save_preserves_comments(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text('# Comment\nTEST_KEY="value"\n')
        manager = ConfigManager(config_path)
        manager.load()

        manager.save("TEST_KEY", "new_value")

        content = config_path.read_text()
        assert "# Comment" in content

    def test_save_file_permissions(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        manager.save("TEST_KEY", "value")

        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestConfigManagerGet:
    def test_get_returns_value(self, temp_config_file):
        manager = ConfigManager(temp_config_file)
        manager.load()

        value = manager.get("DEFAULT_MODEL")

        assert value == "claude-3"

    def test_get_returns_default(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        value = manager.get("NONEXISTENT", "default_value")

        assert value == "default_value"

    def test_get_returns_empty_string_default(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        value = manager.get("NONEXISTENT")

        assert value == ""


class TestConfigManagerShow:
    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    @patch("ingot.config.manager.console")
    def test_show_missing_file(self, mock_console, mock_info, mock_header, tmp_path):
        config_path = tmp_path / "missing"
        manager = ConfigManager(config_path)

        manager.show()

        mock_header.assert_called_once()
        assert mock_info.call_count >= 1

    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    @patch("ingot.config.manager.console")
    def test_show_displays_settings(self, mock_console, mock_info, mock_header, temp_config_file):
        manager = ConfigManager(temp_config_file)
        manager.load()

        manager.show()

        mock_header.assert_called_once()
        # Should print platform settings, platform status table, and other sections
        assert mock_console.print.call_count >= 10  # Increased from 5

        # Verify platform settings are displayed
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Platform Settings" in str(call) for call in print_calls)
        assert any("Default Platform" in str(call) for call in print_calls)

    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    @patch("ingot.config.manager.console")
    def test_show_displays_platform_status_table(
        self, mock_console, mock_info, mock_header, temp_config_file
    ):
        # Skip if Rich is not installed
        Table = pytest.importorskip("rich.table").Table

        manager = ConfigManager(temp_config_file)
        manager.load()

        manager.show()

        # Verify Rich Table was printed (for platform status)
        table_printed = any(
            isinstance(call.args[0], Table)
            for call in mock_console.print.call_args_list
            if call.args
        )
        assert table_printed, "Platform status table should be displayed"


class TestPlatformStatusHelpers:
    def test_get_agent_integrations_uses_agent_config(self, temp_config_file):
        manager = ConfigManager(temp_config_file)
        manager.load()

        integrations = manager._get_agent_integrations()

        # Should return dict with all known platforms
        from ingot.config.fetch_config import KNOWN_PLATFORMS

        assert set(integrations.keys()) == KNOWN_PLATFORMS

        # Default Auggie integrations: jira, linear, github are True
        assert integrations["jira"] is True
        assert integrations["linear"] is True
        assert integrations["github"] is True
        assert integrations["azure_devops"] is False

    def test_get_agent_integrations_respects_explicit_config(self, tmp_path):
        config_file = tmp_path / ".ingot-config"
        config_file.write_text('AGENT_INTEGRATION_JIRA="false"\nAGENT_INTEGRATION_MONDAY="true"\n')
        manager = ConfigManager(config_file)
        manager.load()

        integrations = manager._get_agent_integrations()

        # Explicit config should override defaults
        assert integrations["jira"] is False
        assert integrations["monday"] is True

    def test_get_agent_integrations_no_defaults_for_non_auggie(self, tmp_path):
        config_file = tmp_path / ".ingot-config"
        config_file.write_text('AI_BACKEND="manual"\n')
        manager = ConfigManager(config_file)
        manager.load()

        integrations = manager._get_agent_integrations()

        # All platforms should be False for non-Auggie without explicit config
        from ingot.config.fetch_config import KNOWN_PLATFORMS

        assert set(integrations.keys()) == KNOWN_PLATFORMS
        assert all(v is False for v in integrations.values())

    def test_get_agent_integrations_non_auggie_with_explicit_config(self, tmp_path):
        config_file = tmp_path / ".ingot-config"
        config_file.write_text('AI_BACKEND="cursor"\nAGENT_INTEGRATION_JIRA="true"\n')
        manager = ConfigManager(config_file)
        manager.load()

        integrations = manager._get_agent_integrations()

        # Only explicitly configured integrations should be True
        assert integrations["jira"] is True
        assert integrations["linear"] is False
        assert integrations["github"] is False

    @patch("ingot.integrations.auth.AuthenticationManager")
    def test_get_fallback_status_checks_all_platforms(self, mock_auth_class, temp_config_file):
        # Configure mock to return False for all platforms
        mock_auth = mock_auth_class.return_value
        mock_auth.has_fallback_configured.return_value = False

        manager = ConfigManager(temp_config_file)
        manager.load()

        status = manager._get_fallback_status()

        # Should check all platforms
        from ingot.config.fetch_config import KNOWN_PLATFORMS

        assert set(status.keys()) == KNOWN_PLATFORMS
        # All should be False since mock returns False
        assert all(v is False for v in status.values())
        # Verify has_fallback_configured was called for each platform
        assert mock_auth.has_fallback_configured.call_count == len(KNOWN_PLATFORMS)

    @patch("ingot.integrations.auth.AuthenticationManager")
    def test_get_fallback_status_with_configured_credentials(
        self, mock_auth_class, temp_config_file
    ):
        from ingot.integrations.providers import Platform

        # Configure mock to return True only for Jira
        mock_auth = mock_auth_class.return_value

        def mock_has_fallback(platform):
            return platform == Platform.JIRA

        mock_auth.has_fallback_configured.side_effect = mock_has_fallback

        manager = ConfigManager(temp_config_file)
        manager.load()

        status = manager._get_fallback_status()

        assert status["jira"] is True
        assert status["linear"] is False
        assert status["github"] is False

    def test_get_platform_ready_status_logic(self, temp_config_file):
        manager = ConfigManager(temp_config_file)
        manager.load()

        agent = {"jira": True, "linear": False, "github": False}
        fallback = {"jira": False, "linear": True, "github": False}

        ready = manager._get_platform_ready_status(agent, fallback)

        assert ready["jira"] is True  # agent=True
        assert ready["linear"] is True  # fallback=True
        assert ready["github"] is False  # neither

    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    @patch("ingot.config.manager.console")
    def test_show_platform_status_error_handling(
        self, mock_console, mock_info, mock_header, temp_config_file
    ):
        manager = ConfigManager(temp_config_file)
        manager.load()

        # Mock _get_agent_integrations to raise an exception
        with patch.object(
            manager, "_get_agent_integrations", side_effect=RuntimeError("Test error")
        ):
            # Should not raise, should display error message
            manager._show_platform_status()

        # Verify error message was printed
        print_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Platform Status" in str(call) for call in print_calls)
        assert any("Unable to determine platform status" in str(call) for call in print_calls)
        assert any("Test error" in str(call) for call in print_calls)

    def test_platform_display_order_is_consistent(self, temp_config_file):
        manager = ConfigManager(temp_config_file)
        manager.load()

        # Get platforms multiple times and verify order is consistent
        from ingot.config.manager import _get_known_platforms

        platforms1 = sorted(_get_known_platforms())
        platforms2 = sorted(_get_known_platforms())

        assert platforms1 == platforms2

        # Verify the list is sorted (alphabetical stability)
        assert platforms1 == sorted(platforms1)

        # Verify it contains known essential platforms (not an exact match to avoid brittleness)
        essential_platforms = {"jira", "linear", "github"}
        assert essential_platforms.issubset(set(platforms1))

    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    @patch("ingot.config.manager.console")
    def test_show_platform_status_plain_text_fallback(
        self, mock_console, mock_info, mock_header, temp_config_file, capsys
    ):
        manager = ConfigManager(temp_config_file)
        manager.load()

        # Simulate Rich Table failure during table creation/printing
        with patch("rich.table.Table", side_effect=RuntimeError("Rich failed")):
            manager._show_platform_status()

        # Should have used plain-text fallback (prints to stdout)
        captured = capsys.readouterr()
        assert "Platform Status:" in captured.out
        # Should show platform rows in plain text
        assert "Jira" in captured.out or "jira" in captured.out.lower()
        # Should show status columns
        assert "Agent" in captured.out or "Yes" in captured.out or "No" in captured.out

    @patch("ingot.config.manager.print_header")
    @patch("ingot.config.manager.print_info")
    def test_show_platform_status_fallback_when_rich_import_fails(
        self, mock_info, mock_header, temp_config_file, capsys
    ):
        import sys
        from types import ModuleType

        manager = ConfigManager(temp_config_file)
        manager.load()

        # Create a fake module that raises ImportError when accessing Table
        class FakeRichTableModule(ModuleType):
            def __getattr__(self, name):
                if name == "Table":
                    raise ImportError("No module named 'rich.table'")
                raise AttributeError(name)

        fake_module = FakeRichTableModule("rich.table")

        # Temporarily replace rich.table in sys.modules with our fake module.
        # This approach is more localized than patching builtins.__import__.
        with patch.dict(sys.modules, {"rich.table": fake_module}):
            manager._show_platform_status()

        # Should have used plain-text fallback (prints to stdout)
        captured = capsys.readouterr()
        assert "Platform Status:" in captured.out
        # Verify platform data is displayed in plain text
        assert "Jira" in captured.out or "jira" in captured.out.lower()


class TestCascadingConfigHierarchy:
    def test_global_config_loaded(self, tmp_path):
        # Create global config
        global_config = tmp_path / ".ingot-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "global-model"

    def test_local_overrides_global(self, tmp_path, monkeypatch):
        # Create global config
        global_config = tmp_path / ".ingot-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        # Create local config in a subdirectory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".ingot"
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
        # Create global config
        global_config = tmp_path / ".ingot-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        # Create local config
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".ingot"
        local_config.write_text('DEFAULT_MODEL="local-model"\n')
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        # Set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "env-model"

    def test_multiple_keys_from_different_sources(self, tmp_path, monkeypatch):
        # Global has multiple keys
        global_config = tmp_path / ".ingot-config"
        global_config.write_text(
            """DEFAULT_MODEL="global-model"
PLANNING_MODEL="global-planning"
DEFAULT_PLATFORM="jira"
"""
        )

        # Local overrides one key
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".ingot"
        local_config.write_text('DEFAULT_PLATFORM="linear"\n')
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        # Environment overrides another
        monkeypatch.setenv("PLANNING_MODEL", "env-planning")

        manager = ConfigManager(global_config)
        settings = manager.load()

        assert settings.default_model == "global-model"  # from global
        assert settings.planning_model == "env-planning"  # from env
        assert settings.default_platform == "linear"  # from local


class TestFindLocalConfig:
    def test_finds_config_in_cwd(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".ingot"
        local_config.write_text("TEST_KEY=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found == local_config

    def test_finds_config_in_parent(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sub_dir = project_dir / "src" / "module"
        sub_dir.mkdir(parents=True)
        local_config = project_dir / ".ingot"
        local_config.write_text("TEST_KEY=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(sub_dir)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found == local_config

    def test_stops_at_git_root(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = workspace / "project"
        project.mkdir()
        (project / ".git").mkdir()

        # Config above .git should not be found
        (workspace / ".ingot").write_text("TEST_KEY=value\n")
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None

    def test_returns_none_if_not_found(self, tmp_path, monkeypatch):
        project = tmp_path / "empty-project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None

    def test_ignores_spec_directory(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        # Create .ingot as a directory instead of a file
        spec_dir = project / ".ingot"
        spec_dir.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager()
        found = manager._find_local_config()

        assert found is None


class TestLoadEnvironment:
    def test_loads_known_keys_only(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config"
        config_path.write_text("")
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")
        monkeypatch.setenv("UNKNOWN_RANDOM_VAR", "should-be-ignored")

        manager = ConfigManager(config_path)
        manager.load()

        assert manager._raw_values.get("DEFAULT_MODEL") == "env-model"
        assert "UNKNOWN_RANDOM_VAR" not in manager._raw_values

    def test_empty_env_values_are_loaded(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config"
        config_path.write_text('DEFAULT_MODEL="file-model"\n')
        monkeypatch.setenv("DEFAULT_MODEL", "")

        manager = ConfigManager(config_path)
        manager.load()

        assert manager._raw_values.get("DEFAULT_MODEL") == ""


class TestConfigManagerPathAccessors:
    def test_global_config_path_attribute(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        assert manager.global_config_path == config_path

    def test_local_config_path_none_before_load(self, tmp_path):
        config_path = tmp_path / "config"
        manager = ConfigManager(config_path)

        assert manager.local_config_path is None

    def test_local_config_path_set_after_load(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        local_config = project_dir / ".ingot"
        local_config.write_text("TEST=value\n")
        (project_dir / ".git").mkdir()
        monkeypatch.chdir(project_dir)

        manager = ConfigManager(tmp_path / "nonexistent")
        manager.load()

        assert manager.local_config_path == local_config


class TestConfigManagerIdempotency:
    def test_load_resets_settings_on_each_call(self, tmp_path):
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
        # First load with local config
        project1 = tmp_path / "project1"
        project1.mkdir()
        local1 = project1 / ".ingot"
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
    def test_save_to_global_by_default(self, tmp_path):
        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)

        manager.save("TEST_KEY", "test_value")

        assert global_config.exists()
        assert 'TEST_KEY="test_value"' in global_config.read_text()

    def test_save_to_local_scope(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager(tmp_path / "global")
        manager.load()  # Establish local config path

        manager.save("LOCAL_KEY", "local_value", scope="local")

        local_config = project / ".ingot"
        assert local_config.exists()
        assert 'LOCAL_KEY="local_value"' in local_config.read_text()

    def test_save_invalid_scope_raises(self, tmp_path):
        manager = ConfigManager(tmp_path / "config")

        with pytest.raises(ValueError, match="Invalid scope"):
            manager.save("KEY", "value", scope="invalid")

    def test_save_warns_when_local_overrides_global(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        local_config = project / ".ingot"
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
        monkeypatch.setenv("ENV_KEY", "env-value")

        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)
        manager.load()

        warning = manager.save("ENV_KEY", "saved-value")

        assert warning is not None
        assert "overridden" in warning.lower()
        assert "environment" in warning.lower()

    def test_save_no_warning_when_not_overridden(self, tmp_path):
        global_config = tmp_path / "global-config"
        manager = ConfigManager(global_config)
        manager.load()

        warning = manager.save("UNIQUE_KEY", "value")

        assert warning is None

    def test_save_to_local_creates_file(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        manager = ConfigManager(tmp_path / "global")
        # Don't call load() - local_config_path should be None
        assert manager.local_config_path is None

        manager.save("NEW_KEY", "new_value", scope="local")

        local_config = project / ".ingot"
        assert local_config.exists()
        assert 'NEW_KEY="new_value"' in local_config.read_text()


class TestConfigManagerSavePrecedence:
    """Tests for ConfigManager.save() precedence correctness.

    These tests verify that after calling save(), the in-memory state
    correctly reflects the effective precedence (env > local > global).
    """

    def test_global_save_when_local_overrides(self, tmp_path, monkeypatch):
        # Setup: global has one value, local has a different value
        global_config = tmp_path / ".ingot-config"
        global_config.write_text('DEFAULT_MODEL="global-model"\n')

        project = tmp_path / "project"
        project.mkdir()
        local_config = project / ".ingot"
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
        # Setup: set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        global_config = tmp_path / ".ingot-config"
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
        # Setup: set environment variable
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")

        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
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
        local_config = project / ".ingot"
        assert local_config.exists()
        assert 'DEFAULT_MODEL="new-local"' in local_config.read_text()

        # Assert: in-memory state still reflects env (highest priority)
        assert manager.settings.default_model == "env-model"
        assert manager.get("DEFAULT_MODEL") == "env-model"

    def test_global_save_without_override_updates_memory(self, tmp_path):
        global_config = tmp_path / ".ingot-config"
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
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
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
        local_config = project / ".ingot"
        assert local_config.exists()
        assert 'DEFAULT_MODEL="new-local"' in local_config.read_text()

        # Assert: in-memory state is updated (local > global)
        assert manager.settings.default_model == "new-local"
        assert manager.get("DEFAULT_MODEL") == "new-local"

    def test_local_config_path_correct_after_save(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
        manager = ConfigManager(global_config)
        # Don't call load() first to test save creating local config

        # Act: save to local (creates the file)
        manager.save("TEST_KEY", "test_value", scope="local")

        # Assert: local_config_path is set correctly
        expected_path = project / ".ingot"
        assert manager.local_config_path == expected_path
        assert manager.local_config_path.exists()


class TestConfigManagerSensitiveValueMasking:
    def test_is_sensitive_key_detects_token(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("JIRA_TOKEN") is True
        assert is_sensitive_key("jira_token") is True
        assert is_sensitive_key("MY_API_TOKEN") is True

    def test_is_sensitive_key_detects_key(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("API_KEY") is True
        assert is_sensitive_key("api_key") is True
        assert is_sensitive_key("ENCRYPTION_KEY") is True

    def test_is_sensitive_key_detects_secret(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("CLIENT_SECRET") is True
        assert is_sensitive_key("secret_value") is True

    def test_is_sensitive_key_detects_password(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("DB_PASSWORD") is True
        assert is_sensitive_key("password") is True

    def test_is_sensitive_key_detects_pat(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("GITHUB_PAT") is True
        assert is_sensitive_key("pat_token") is True

    def test_is_sensitive_key_non_sensitive(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("DEFAULT_MODEL") is False
        assert is_sensitive_key("AUTO_OPEN_FILES") is False
        assert is_sensitive_key("JIRA_PROJECT") is False

    def test_save_does_not_log_sensitive_values(self, tmp_path, monkeypatch, caplog):
        import logging

        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        # Enable logging
        monkeypatch.setenv("INGOT_LOG", "true")

        global_config = tmp_path / ".ingot-config"
        manager = ConfigManager(global_config)

        # Capture logs
        with caplog.at_level(logging.DEBUG):
            manager.save("API_TOKEN", "super-secret-value-12345", scope="global")

        # Assert: secret value is not in logs
        log_text = caplog.text
        assert "super-secret-value-12345" not in log_text
        assert "REDACTED" in log_text or "API_TOKEN" in log_text


class TestConfigManagerQuoteEscaping:
    def test_escape_value_for_storage_handles_quotes(self):
        result = ConfigManager._escape_value_for_storage('value with "quotes"')
        assert result == 'value with \\"quotes\\"'

    def test_escape_value_for_storage_handles_backslashes(self):
        result = ConfigManager._escape_value_for_storage("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_value_for_storage_handles_both(self):
        result = ConfigManager._escape_value_for_storage('say \\"hello\\"')
        assert result == 'say \\\\\\"hello\\\\\\"'

    def test_unescape_value_reverses_quotes(self):
        result = ConfigManager._unescape_value('value with \\"quotes\\"')
        assert result == 'value with "quotes"'

    def test_unescape_value_reverses_backslashes(self):
        result = ConfigManager._unescape_value("path\\\\to\\\\file")
        assert result == "path\\to\\file"

    def test_round_trip_with_quotes(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
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
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
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
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
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
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"

        # Manually write a config file with single-quoted value containing backslashes
        # In bash single quotes, \\ is literal (not an escape sequence)
        global_config.write_text("SINGLE_QUOTED='path\\\\with\\\\backslashes'\n")

        # Load the config
        manager = ConfigManager(global_config)
        manager.load()

        # Assert: backslashes are preserved literally (not unescaped)
        assert manager.get("SINGLE_QUOTED") == "path\\\\with\\\\backslashes"

    def test_double_quoted_values_are_unescaped(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"

        # Manually write a config file with double-quoted escaped value
        # This represents a value that was escaped on save
        global_config.write_text('DOUBLE_QUOTED="path\\\\with\\\\backslashes"\n')

        # Load the config
        manager = ConfigManager(global_config)
        manager.load()

        # Assert: backslashes are unescaped (double backslash -> single)
        assert manager.get("DOUBLE_QUOTED") == "path\\with\\backslashes"


class TestConfigManagerRepoRootDetection:
    def test_save_local_creates_at_repo_root_from_nested_dir(self, tmp_path, monkeypatch):
        # Setup: repo with nested directory structure
        repo_root = tmp_path / "my-repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        nested_dir = repo_root / "src" / "deep" / "nested"
        nested_dir.mkdir(parents=True)

        # Change to nested directory
        monkeypatch.chdir(nested_dir)

        global_config = tmp_path / ".ingot-config"
        manager = ConfigManager(global_config)

        # Act: save to local scope
        manager.save("PROJECT_SETTING", "value", scope="local")

        # Assert: config created at repo root, not in nested dir
        expected_path = repo_root / ".ingot"
        assert expected_path.exists()
        assert not (nested_dir / ".ingot").exists()
        assert manager.local_config_path == expected_path

    def test_save_local_falls_back_to_cwd_without_git(self, tmp_path, monkeypatch):
        # Setup: directory without .git
        project = tmp_path / "no-git-project"
        project.mkdir()
        monkeypatch.chdir(project)

        global_config = tmp_path / ".ingot-config"
        manager = ConfigManager(global_config)

        # Act: save to local scope
        manager.save("SETTING", "value", scope="local")

        # Assert: config created in cwd
        expected_path = project / ".ingot"
        assert expected_path.exists()
        assert manager.local_config_path == expected_path


class TestFetchConfigEnums:
    def test_fetch_strategy_values(self):
        from ingot.config.fetch_config import FetchStrategy

        assert FetchStrategy.AGENT.value == "agent"
        assert FetchStrategy.DIRECT.value == "direct"
        assert FetchStrategy.AUTO.value == "auto"

    def test_fetch_strategy_from_string(self):
        from ingot.config.fetch_config import FetchStrategy

        assert FetchStrategy("agent") == FetchStrategy.AGENT
        assert FetchStrategy("direct") == FetchStrategy.DIRECT
        assert FetchStrategy("auto") == FetchStrategy.AUTO

    def test_fetch_strategy_invalid_value(self):
        from ingot.config.fetch_config import FetchStrategy

        with pytest.raises(ValueError):
            FetchStrategy("invalid")

    def test_ai_backend_values(self):
        from ingot.config.fetch_config import AgentPlatform

        assert AgentPlatform.AUGGIE.value == "auggie"
        assert AgentPlatform.CLAUDE.value == "claude"
        assert AgentPlatform.CURSOR.value == "cursor"
        assert AgentPlatform.AIDER.value == "aider"
        assert AgentPlatform.MANUAL.value == "manual"

    def test_ai_backend_from_string(self):
        from ingot.config.fetch_config import AgentPlatform

        assert AgentPlatform("auggie") == AgentPlatform.AUGGIE
        assert AgentPlatform("claude") == AgentPlatform.CLAUDE
        assert AgentPlatform("cursor") == AgentPlatform.CURSOR

    def test_ai_backend_invalid_value(self):
        from ingot.config.fetch_config import AgentPlatform

        with pytest.raises(ValueError):
            AgentPlatform("unknown")


class TestFetchConfigDataclasses:
    def test_agent_config_defaults(self):
        from ingot.config.fetch_config import AgentConfig, AgentPlatform

        config = AgentConfig()
        assert config.platform == AgentPlatform.AUGGIE
        assert config.integrations is None  # None means no explicit config

    def test_agent_config_supports_platform(self):
        from ingot.config.fetch_config import AgentConfig

        config = AgentConfig(integrations={"jira": True, "linear": True, "github": False})
        assert config.supports_platform("jira") is True
        assert config.supports_platform("JIRA") is True  # Case insensitive
        assert config.supports_platform("linear") is True
        assert config.supports_platform("github") is False
        assert config.supports_platform("unknown") is False

    def test_fetch_strategy_config_defaults(self):
        from ingot.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig()
        assert config.default == FetchStrategy.AUTO
        assert config.per_platform == {}

    def test_fetch_strategy_config_get_strategy_default(self):
        from ingot.config.fetch_config import FetchStrategy, FetchStrategyConfig

        config = FetchStrategyConfig(default=FetchStrategy.AGENT)
        assert config.get_strategy("jira") == FetchStrategy.AGENT
        assert config.get_strategy("unknown") == FetchStrategy.AGENT

    def test_fetch_strategy_config_get_strategy_override(self):
        from ingot.config.fetch_config import FetchStrategy, FetchStrategyConfig

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
        from ingot.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig()
        assert config.cache_duration_hours == 24
        assert config.timeout_seconds == 30
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 1.0

    def test_fetch_performance_config_custom_values(self):
        from ingot.config.fetch_config import FetchPerformanceConfig

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


class TestEnvVarExpansion:
    def test_expand_env_vars_string(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("TEST_VAR", "expanded_value")

        result = expand_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_expanded_value_suffix"

    def test_expand_env_vars_missing_var(self):
        from ingot.utils.env_utils import expand_env_vars

        result = expand_env_vars("${MISSING_VAR}", strict=False)
        assert result == "${MISSING_VAR}"

    def test_expand_env_vars_dict(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("VAR1", "value1")
        monkeypatch.setenv("VAR2", "value2")

        result = expand_env_vars({"key1": "${VAR1}", "key2": "${VAR2}"})
        assert result == {"key1": "value1", "key2": "value2"}

    def test_expand_env_vars_list(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("ITEM", "expanded")

        result = expand_env_vars(["${ITEM}", "static"])
        assert result == ["expanded", "static"]

    def test_expand_env_vars_nested(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("NESTED", "deep_value")

        result = expand_env_vars({"outer": {"inner": "${NESTED}"}})
        assert result == {"outer": {"inner": "deep_value"}}

    def test_expand_env_vars_non_string(self):
        from ingot.utils.env_utils import expand_env_vars

        assert expand_env_vars(42) == 42
        assert expand_env_vars(True) is True
        assert expand_env_vars(None) is None


class TestConfigManagerGetAgentConfig:
    def test_get_agent_config_defaults(self, tmp_path):
        from ingot.config.fetch_config import AgentPlatform

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.platform == AgentPlatform.AUGGIE
        assert config.integrations is None  # None means no explicit config

    def test_get_agent_config_custom_platform(self, tmp_path):
        from ingot.config.fetch_config import AgentPlatform

        config_path = tmp_path / "config"
        config_path.write_text('AI_BACKEND="cursor"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_agent_config()
        assert config.platform == AgentPlatform.CURSOR

    def test_get_agent_config_invalid_platform_raises(self, tmp_path):
        from ingot.config.fetch_config import ConfigValidationError

        config_path = tmp_path / "config"
        config_path.write_text('AI_BACKEND="invalid_platform"\n')
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(ConfigValidationError) as exc_info:
            manager.get_agent_config()

        # Error should include the invalid value and allowed values
        assert "invalid_platform" in str(exc_info.value)
        assert "auggie" in str(exc_info.value).lower()
        assert "cursor" in str(exc_info.value).lower()

    def test_get_agent_config_integrations(self, tmp_path):
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
    def test_get_fetch_strategy_config_defaults(self, tmp_path):
        from ingot.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AUTO
        assert config.per_platform == {}

    def test_get_fetch_strategy_config_custom_default(self, tmp_path):
        from ingot.config.fetch_config import FetchStrategy

        config_path = tmp_path / "config"
        config_path.write_text('FETCH_STRATEGY_DEFAULT="agent"\n')
        manager = ConfigManager(config_path)
        manager.load()

        config = manager.get_fetch_strategy_config()
        assert config.default == FetchStrategy.AGENT

    def test_get_fetch_strategy_config_per_platform(self, tmp_path):
        from ingot.config.fetch_config import FetchStrategy

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

    def test_get_fetch_strategy_config_invalid_override_raises(self, tmp_path):
        from ingot.config.fetch_config import ConfigValidationError

        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_STRATEGY_VALID=direct
FETCH_STRATEGY_INVALID=not_a_strategy
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(ConfigValidationError) as exc_info:
            manager.get_fetch_strategy_config()

        # Error should include the invalid value and allowed values
        assert "not_a_strategy" in str(exc_info.value)
        assert "auto" in str(exc_info.value).lower()
        assert "direct" in str(exc_info.value).lower()
        assert "FETCH_STRATEGY_INVALID" in str(exc_info.value)

    def test_get_fetch_strategy_config_invalid_default_raises(self, tmp_path):
        from ingot.config.fetch_config import ConfigValidationError

        config_path = tmp_path / "config"
        config_path.write_text(
            """FETCH_STRATEGY_DEFAULT=bad_default
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(ConfigValidationError) as exc_info:
            manager.get_fetch_strategy_config()

        # Error should include the invalid value and allowed values
        assert "bad_default" in str(exc_info.value)
        assert "FETCH_STRATEGY_DEFAULT" in str(exc_info.value)


class TestConfigManagerGetFetchPerformanceConfig:
    def test_get_fetch_performance_config_defaults(self, tmp_path):
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
    def test_get_fallback_credentials_none_when_missing(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is None

    def test_get_fallback_credentials_returns_dict(self, tmp_path):
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
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_JIRA_TOKEN=token123\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("JIRA")
        assert creds is not None
        assert creds["token"] == "token123"

    def test_get_fallback_credentials_expands_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_PAT", "actual_secret_value")
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_AZURE_DEVOPS_PAT=${SECRET_PAT}\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is not None
        assert creds["pat"] == "actual_secret_value"

    def test_get_fallback_credentials_preserves_unset_env_vars(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("FALLBACK_TEST_TOKEN=${UNSET_VAR}\n")
        manager = ConfigManager(config_path)
        manager.load()

        creds = manager.get_fallback_credentials("test")
        assert creds is not None
        assert creds["token"] == "${UNSET_VAR}"


class TestFetchConfigEndToEnd:
    def test_full_fetch_config_from_file(self, tmp_path, monkeypatch):
        from ingot.config.fetch_config import AgentPlatform, FetchStrategy

        monkeypatch.setenv("MY_PAT", "secret_pat_value")

        config_path = tmp_path / "config"
        config_path.write_text(
            """# Agent configuration
AI_BACKEND=cursor
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
        # Note: 'org' is aliased to 'organization' for Azure DevOps
        creds = manager.get_fallback_credentials("azure_devops")
        assert creds is not None
        assert creds["organization"] == "myorg"
        assert creds["pat"] == "secret_pat_value"


class TestEnvVarExpansionStrict:
    def test_expand_env_vars_strict_mode_raises_on_missing(self, monkeypatch):
        from ingot.utils.env_utils import EnvVarExpansionError, expand_env_vars_strict

        with pytest.raises(EnvVarExpansionError) as exc_info:
            expand_env_vars_strict("${MISSING_VAR}", context="test_field")

        assert "MISSING_VAR" in str(exc_info.value)
        # Context is included in error message for non-sensitive contexts
        assert "test_field" in str(exc_info.value)

    def test_expand_env_vars_strict_mode_succeeds_when_set(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars_strict

        monkeypatch.setenv("MY_SECRET", "secret_value")

        result = expand_env_vars_strict("token=${MY_SECRET}", context="test_key")
        assert result == "token=secret_value"

    def test_expand_env_vars_nested_dict(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("NESTED_VAR", "nested_value")

        data = {"level1": {"level2": {"value": "${NESTED_VAR}"}}}
        result = expand_env_vars(data)
        assert result["level1"]["level2"]["value"] == "nested_value"

    def test_expand_env_vars_nested_list(self, monkeypatch):
        from ingot.utils.env_utils import expand_env_vars

        monkeypatch.setenv("LIST_VAR", "list_value")

        data = ["${LIST_VAR}", "plain", "${LIST_VAR}"]
        result = expand_env_vars(data)
        assert result == ["list_value", "plain", "list_value"]


class TestValidationFailures:
    def test_validate_strategy_agent_without_integration(self, tmp_path):
        from ingot.config.fetch_config import (
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
        from ingot.config.fetch_config import (
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
        from ingot.config.fetch_config import (
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
        from ingot.config.fetch_config import ConfigValidationError, validate_credentials

        # Jira requires url, email, token
        incomplete_creds = {"url": "https://example.atlassian.net"}

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_credentials("jira", incomplete_creds, strict=True)

        assert "email" in str(exc_info.value) or "token" in str(exc_info.value)

    def test_validate_credentials_unexpanded_env_var(self):
        from ingot.config.fetch_config import validate_credentials

        creds = {
            "url": "https://example.atlassian.net",
            "email": "user@example.com",
            "token": "${UNSET_TOKEN}",  # Not expanded
        }

        errors = validate_credentials("jira", creds, strict=False)
        assert any("unexpanded" in e.lower() for e in errors)


class TestPerformanceGuardrails:
    def test_performance_config_clamps_to_max(self):
        from ingot.config.fetch_config import (
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
        from ingot.config.fetch_config import FetchPerformanceConfig

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

    def test_performance_config_clamps_to_lower_bounds(self):
        from ingot.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig(
            cache_duration_hours=-10,  # Negative - clamp to 0
            timeout_seconds=0,  # Zero - clamp to 1 (must be positive)
            max_retries=-5,  # Negative - clamp to 0
            retry_delay_seconds=-1.0,  # Negative - clamp to 0
        )

        assert config.cache_duration_hours == 0
        assert config.timeout_seconds == 1  # Clamped to 1, not 0
        assert config.max_retries == 0
        assert config.retry_delay_seconds == 0.0

    def test_performance_config_zero_timeout_clamps_to_one(self):
        from ingot.config.fetch_config import FetchPerformanceConfig

        config = FetchPerformanceConfig(timeout_seconds=-100)
        assert config.timeout_seconds == 1


class TestNoSecretLeakage:
    """Tests to ensure secrets are never logged."""

    def test_sensitive_key_detection(self):
        from ingot.utils.env_utils import is_sensitive_key

        assert is_sensitive_key("JIRA_TOKEN") is True
        assert is_sensitive_key("AZURE_PAT") is True
        assert is_sensitive_key("API_KEY") is True
        assert is_sensitive_key("SECRET_VALUE") is True
        assert is_sensitive_key("MY_PASSWORD") is True
        assert is_sensitive_key("CREDENTIAL_DATA") is True
        assert is_sensitive_key("DEFAULT_MODEL") is False
        assert is_sensitive_key("AI_BACKEND") is False

    def test_fallback_credentials_not_in_settings(self, tmp_path):
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
    def test_unknown_platform_warning(self):
        from ingot.config.fetch_config import FetchStrategy, FetchStrategyConfig

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
        from ingot.config.fetch_config import (
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


class TestValidateFetchConfig:
    def test_validate_fetch_config_with_working_setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "test_token")

        config_path = tmp_path / "config"
        config_path.write_text(
            """AI_BACKEND=auggie
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
        config_path = tmp_path / "config"
        # Configure active platforms with agent strategy but no integrations
        # This triggers validation errors for those platforms
        config_path.write_text(
            """AI_BACKEND=manual
FETCH_STRATEGY_JIRA=agent
FETCH_STRATEGY_LINEAR=agent
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        # Agent strategy for Jira/Linear with manual platform and no integrations
        errors = manager.validate_fetch_config(strict=False)
        # Should have errors for active platforms that can't use agent strategy
        assert len(errors) > 0

    def test_validate_fetch_config_strict_raises_on_invalid_ai_backend(self, tmp_path):
        from ingot.config.fetch_config import ConfigValidationError

        config_path = tmp_path / "config"
        config_path.write_text("AI_BACKEND=invalid_platform\n")
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(ConfigValidationError, match="Invalid AI backend"):
            manager.validate_fetch_config(strict=True)

    def test_validate_fetch_config_nonstrict_collects_invalid_ai_backend(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("AI_BACKEND=invalid_platform\n")
        manager = ConfigManager(config_path)
        manager.load()

        # Should NOT raise
        errors = manager.validate_fetch_config(strict=False)

        # Should have collected the error
        assert len(errors) >= 1
        assert any("invalid ai backend" in e.lower() for e in errors)

    def test_validate_fetch_config_strict_raises_on_invalid_strategy(self, tmp_path):
        from ingot.config.fetch_config import ConfigValidationError

        config_path = tmp_path / "config"
        config_path.write_text("FETCH_STRATEGY_DEFAULT=invalid_strategy\n")
        manager = ConfigManager(config_path)
        manager.load()

        with pytest.raises(ConfigValidationError, match="Invalid fetch strategy"):
            manager.validate_fetch_config(strict=True)

    def test_validate_fetch_config_nonstrict_collects_invalid_strategy(self, tmp_path):
        config_path = tmp_path / "config"
        config_path.write_text("FETCH_STRATEGY_DEFAULT=invalid_strategy\n")
        manager = ConfigManager(config_path)
        manager.load()

        # Should NOT raise
        errors = manager.validate_fetch_config(strict=False)

        # Should have collected the error
        assert len(errors) >= 1
        assert any("invalid fetch strategy" in e.lower() for e in errors)

    def test_validate_fetch_config_nonstrict_collects_multiple_errors(self, tmp_path):
        config_path = tmp_path / "config"
        # Multiple invalid values
        config_path.write_text(
            """AI_BACKEND=bad_platform
FETCH_STRATEGY_DEFAULT=bad_strategy
FETCH_STRATEGY_JIRA=also_invalid
"""
        )
        manager = ConfigManager(config_path)
        manager.load()

        # Should NOT raise
        errors = manager.validate_fetch_config(strict=False)

        # Should have collected multiple errors
        assert len(errors) >= 2
        error_text = " ".join(errors).lower()
        assert "invalid ai backend" in error_text
        assert "invalid fetch strategy" in error_text


class TestAzureDevOpsCredentialAlias:
    def test_org_alias_mapped_to_organization(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_AZURE_DEVOPS_ORG=my-org
FALLBACK_AZURE_DEVOPS_PROJECT=my-project
FALLBACK_AZURE_DEVOPS_PAT=secret
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops", validate=False)
        # 'org' should be mapped to 'organization'
        assert "organization" in creds
        assert creds["organization"] == "my-org"
        # 'org' should not be present as a separate key
        assert "org" not in creds
        # 'pat' should be present
        assert creds["pat"] == "secret"

    def test_token_alias_mapped_to_pat(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_AZURE_DEVOPS_ORGANIZATION=my-org
FALLBACK_AZURE_DEVOPS_PROJECT=my-project
FALLBACK_AZURE_DEVOPS_TOKEN=secret-token
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops", validate=False)
        # 'token' should be mapped to 'pat'
        assert "pat" in creds
        assert creds["pat"] == "secret-token"
        # 'token' should not be present as a separate key
        assert "token" not in creds

    def test_organization_key_works_directly(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_AZURE_DEVOPS_ORGANIZATION=direct-org
FALLBACK_AZURE_DEVOPS_PROJECT=my-project
FALLBACK_AZURE_DEVOPS_PAT=secret
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("azure_devops", validate=False)
        assert creds["organization"] == "direct-org"
        assert creds["pat"] == "secret"

    def test_jira_base_url_alias_mapped_to_url(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_JIRA_BASE_URL=https://jira.example.com
FALLBACK_JIRA_EMAIL=user@example.com
FALLBACK_JIRA_TOKEN=secret
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("jira", validate=False)
        # 'base_url' should be mapped to 'url'
        assert "url" in creds
        assert creds["url"] == "https://jira.example.com"
        # 'base_url' should not be present as a separate key
        assert "base_url" not in creds
        assert creds["token"] == "secret"

    def test_jira_url_key_works_directly(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_JIRA_URL=https://jira.example.com
FALLBACK_JIRA_TOKEN=secret
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("jira", validate=False)
        assert creds["url"] == "https://jira.example.com"
        assert creds["token"] == "secret"

    def test_trello_api_token_alias_mapped_to_token(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_TRELLO_API_KEY=my-api-key
FALLBACK_TRELLO_API_TOKEN=my-token
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("trello", validate=False)
        # 'api_token' should be mapped to 'token'
        assert "token" in creds
        assert creds["token"] == "my-token"
        # 'api_token' should not be present as a separate key
        assert "api_token" not in creds
        assert creds["api_key"] == "my-api-key"

    def test_trello_token_key_works_directly(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_TRELLO_API_KEY=my-api-key
FALLBACK_TRELLO_TOKEN=my-token
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        creds = manager.get_fallback_credentials("trello", validate=False)
        assert creds["api_key"] == "my-api-key"
        assert creds["token"] == "my-token"


class TestScopedPlatformValidation:
    def test_get_active_platforms_from_per_platform(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text('FETCH_STRATEGY_AZURE_DEVOPS="direct"\n')
        manager = ConfigManager(config_file)
        manager.load()

        active = manager._get_active_platforms()
        assert "azure_devops" in active

    def test_get_active_platforms_from_integrations(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        active = manager._get_active_platforms()
        assert "jira" in active
        assert "linear" in active

    def test_get_active_platforms_from_fallback_credentials(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            """FALLBACK_GITHUB_TOKEN=secret
FALLBACK_AZURE_DEVOPS_ORG=my-org
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        active = manager._get_active_platforms()
        assert "github" in active
        assert "azure_devops" in active

    def test_validate_only_active_platforms(self, tmp_path):
        config_file = tmp_path / "config"
        # Configure only Jira with agent strategy (requires integration)
        config_file.write_text(
            """AI_BACKEND=auggie
AGENT_INTEGRATION_JIRA=true
FETCH_STRATEGY_JIRA=agent
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should NOT have errors about Linear, GitHub, etc. (not active)
        # Jira is properly configured with agent integration
        error_text = " ".join(errors)
        assert "linear" not in error_text.lower()
        assert "github" not in error_text.lower()

    def test_validate_unconfigured_platforms_not_checked(self, tmp_path):
        config_file = tmp_path / "config"
        # Empty config - no platforms active
        config_file.write_text("")
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should have no platform-specific errors (nothing is active)
        assert len(errors) == 0


class TestFailFastMissingEnvVars:
    def test_direct_strategy_strict_env_expansion(self, tmp_path, monkeypatch):
        # Ensure the env var is NOT set
        monkeypatch.delenv("MISSING_TOKEN", raising=False)

        config_file = tmp_path / "config"
        config_file.write_text(
            """FETCH_STRATEGY_AZURE_DEVOPS=direct
FALLBACK_AZURE_DEVOPS_ORG=myorg
FALLBACK_AZURE_DEVOPS_PAT=${MISSING_TOKEN}
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should have error about missing env var
        error_text = " ".join(errors).lower()
        assert "missing" in error_text or "environment variable" in error_text

    def test_direct_strategy_with_valid_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AZURE_PAT", "valid_token")

        config_file = tmp_path / "config"
        config_file.write_text(
            """FETCH_STRATEGY_AZURE_DEVOPS=direct
FALLBACK_AZURE_DEVOPS_ORG=myorg
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_PAT}
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should NOT have errors about missing env vars
        error_text = " ".join(errors).lower()
        assert "missing_token" not in error_text
        assert "environment variable" not in error_text

    def test_auto_strategy_without_agent_strict_env_expansion(self, tmp_path, monkeypatch):
        # Ensure the env var is NOT set
        monkeypatch.delenv("TRELLO_KEY", raising=False)

        config_file = tmp_path / "config"
        config_file.write_text(
            """AI_BACKEND=auggie
AGENT_INTEGRATION_TRELLO=false
FETCH_STRATEGY_TRELLO=auto
FALLBACK_TRELLO_API_KEY=${TRELLO_KEY}
FALLBACK_TRELLO_TOKEN=some_token
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should have error about missing env var (since no agent support, direct is only path)
        error_text = " ".join(errors).lower()
        assert "missing" in error_text or "trello_key" in error_text

    def test_auto_strategy_with_agent_non_strict_env_expansion(self, tmp_path, monkeypatch):
        # Ensure the env var is NOT set
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        config_file = tmp_path / "config"
        config_file.write_text(
            """AI_BACKEND=auggie
AGENT_INTEGRATION_JIRA=true
FETCH_STRATEGY_JIRA=auto
FALLBACK_JIRA_URL=https://example.atlassian.net
FALLBACK_JIRA_EMAIL=user@example.com
FALLBACK_JIRA_TOKEN=${JIRA_TOKEN}
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should NOT have errors about missing env vars (agent is available)
        # But may have warnings about unexpanded vars in credential validation
        error_text = " ".join(errors).lower()
        # No EnvVarExpansionError should occur for AUTO with agent support
        assert "environment variable" not in error_text or "unexpanded" in error_text

    def test_agent_strategy_ignores_credential_env_vars(self, tmp_path, monkeypatch):
        # Ensure the env var is NOT set
        monkeypatch.delenv("MISSING_TOKEN", raising=False)

        config_file = tmp_path / "config"
        config_file.write_text(
            """AI_BACKEND=auggie
AGENT_INTEGRATION_LINEAR=true
FETCH_STRATEGY_LINEAR=agent
FALLBACK_LINEAR_API_KEY=${MISSING_TOKEN}
"""
        )
        manager = ConfigManager(config_file)
        manager.load()

        errors = manager.validate_fetch_config(strict=False)
        # Should NOT have errors about missing env vars (using agent, not direct)
        error_text = " ".join(errors).lower()
        assert "missing_token" not in error_text
