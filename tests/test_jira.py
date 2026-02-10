"""Tests for ingot.integrations.jira module."""

from unittest.mock import MagicMock, patch

import pytest

from ingot.integrations.jira import (
    JiraTicket,
    check_jira_integration,
    fetch_ticket_info,
    parse_jira_ticket,
)


class TestParseJiraTicket:
    def test_parse_url(self):
        result = parse_jira_ticket("https://jira.example.com/browse/PROJECT-123")

        assert result.ticket_id == "PROJECT-123"
        assert result.ticket_url == "https://jira.example.com/browse/PROJECT-123"

    def test_parse_url_with_path(self):
        result = parse_jira_ticket("https://jira.example.com/browse/PROJ-456/details")

        assert result.ticket_id == "PROJ-456"

    def test_parse_ticket_id_uppercase(self):
        result = parse_jira_ticket("PROJECT-123")

        assert result.ticket_id == "PROJECT-123"

    def test_parse_ticket_id_lowercase(self):
        result = parse_jira_ticket("project-456")

        assert result.ticket_id == "PROJECT-456"

    def test_parse_ticket_id_mixed_case(self):
        result = parse_jira_ticket("Project-789")

        assert result.ticket_id == "PROJECT-789"

    def test_parse_numeric_with_default(self):
        result = parse_jira_ticket("789", default_project="MYPROJ")

        assert result.ticket_id == "MYPROJ-789"

    def test_parse_numeric_without_default(self):
        with pytest.raises(ValueError, match="default project"):
            parse_jira_ticket("789")

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid ticket format"):
            parse_jira_ticket("not-a-ticket!")

    def test_parse_invalid_url(self):
        with pytest.raises(ValueError, match="Could not extract"):
            parse_jira_ticket("https://jira.example.com/browse/")

    def test_parse_strips_whitespace(self):
        result = parse_jira_ticket("  PROJECT-123  ")

        assert result.ticket_id == "PROJECT-123"


class TestCheckJiraIntegration:
    def test_uses_cached_result(self):
        import time

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default="": {
            "JIRA_CHECK_TIMESTAMP": str(int(time.time()) - 3600),  # 1 hour ago
            "JIRA_INTEGRATION_STATUS": "working",
        }.get(key, default)

        mock_auggie = MagicMock()

        with patch("ingot.integrations.jira.print_success"):
            result = check_jira_integration(mock_config, mock_auggie, force=False)

        assert result is True
        mock_auggie.run_print_quiet.assert_not_called()

    def test_force_bypasses_cache(self):
        import time

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default="": {
            "JIRA_CHECK_TIMESTAMP": str(int(time.time()) - 3600),
            "JIRA_INTEGRATION_STATUS": "working",
        }.get(key, default)

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "YES, Jira is available"

        with (
            patch("ingot.integrations.jira.print_info"),
            patch("ingot.integrations.jira.print_success"),
            patch("ingot.integrations.jira.print_step"),
        ):
            check_jira_integration(mock_config, mock_auggie, force=True)

        mock_auggie.run_print_quiet.assert_called_once()

    def test_detects_working_integration(self):
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "YES, Jira is available"

        with (
            patch("ingot.integrations.jira.print_info"),
            patch("ingot.integrations.jira.print_success"),
            patch("ingot.integrations.jira.print_step"),
        ):
            result = check_jira_integration(mock_config, mock_auggie)

        assert result is True
        mock_config.save.assert_any_call("JIRA_INTEGRATION_STATUS", "working")

    def test_detects_not_configured(self):
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "Jira is not configured"

        with (
            patch("ingot.integrations.jira.print_info"),
            patch("ingot.integrations.jira.print_warning"),
            patch("ingot.integrations.jira.print_step"),
        ):
            result = check_jira_integration(mock_config, mock_auggie)

        assert result is False
        mock_config.save.assert_any_call("JIRA_INTEGRATION_STATUS", "not_configured")


class TestFetchTicketInfo:
    def test_parses_branch_summary(self):
        ticket = JiraTicket(ticket_id="TEST-123", ticket_url="TEST-123")
        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = """
BRANCH_SUMMARY: add-user-authentication
TITLE: Add User Authentication
DESCRIPTION: Implement user login and registration.
"""

        result = fetch_ticket_info(ticket, mock_auggie)

        assert result.summary == "add-user-authentication"
        assert result.title == "Add User Authentication"

    def test_sanitizes_branch_summary(self):
        ticket = JiraTicket(ticket_id="TEST-123", ticket_url="TEST-123")
        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = """
BRANCH_SUMMARY: Add User's Authentication!
TITLE: Test
DESCRIPTION: Test
"""

        result = fetch_ticket_info(ticket, mock_auggie)

        # Should be lowercase, no special chars
        assert result.summary == "add-user-s-authentication"


class TestNumericIdWithConfiguredDefaultProject:
    """Regression tests for numeric ID parsing with DEFAULT_JIRA_PROJECT configured.

    These tests verify that numeric-only ticket IDs (e.g., "123") work correctly
    when the default_jira_project setting is configured, addressing the
    regression from AMI-43.
    """

    def test_parse_numeric_id_with_configured_default_project(self):
        result = parse_jira_ticket("456", default_project="CONFIGURED")

        assert result.ticket_id == "CONFIGURED-456"
        assert result.ticket_url == "CONFIGURED-456"

    def test_parse_numeric_id_normalizes_project_to_uppercase(self):
        result = parse_jira_ticket("789", default_project="lowercase")

        assert result.ticket_id == "LOWERCASE-789"

    def test_parse_numeric_id_without_default_raises_helpful_error(self):
        with pytest.raises(ValueError) as exc_info:
            parse_jira_ticket("123")

        error_message = str(exc_info.value)
        assert "default project" in error_message.lower()
        # The error should guide users to provide a project key
        assert "PROJECT-123" in error_message or "default_project" in error_message


class TestProviderRegistryConfigWiring:
    """Integration tests for ConfigManager → ProviderRegistry → JiraProvider wiring.

    These tests verify that the default_jira_project configuration flows correctly
    from ProviderRegistry.set_config() to JiraProvider, without relying on
    environment variables.

    This is the "wiring test" to ensure dependency injection works end-to-end.
    """

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset ProviderRegistry before and after each test.

        Uses clear() once at start to register JiraProvider, then reset_instances()
        between tests to preserve registration but clear instances/config.
        """
        from ingot.integrations.providers.jira import JiraProvider
        from ingot.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.clear()
        # Re-register JiraProvider after clear (decorator ran at import time)
        ProviderRegistry.register(JiraProvider)
        yield
        # Use reset_instances for cleanup (preserves registration for other tests)
        ProviderRegistry.reset_instances()

    def test_set_config_injects_default_project_to_jira_provider(self):
        from ingot.integrations.providers.base import Platform
        from ingot.integrations.providers.registry import ProviderRegistry

        # Set config BEFORE getting provider (provider is lazy-instantiated)
        ProviderRegistry.set_config({"default_jira_project": "TESTPROJ"})

        # Get provider instance (will be created with injected config)
        provider = ProviderRegistry.get_provider(Platform.JIRA)

        # Verify public behavior: can_handle numeric IDs when configured
        assert provider.can_handle("456") is True

        # Verify public behavior: parse_input uses the configured project
        ticket_id = provider.parse_input("456")
        assert ticket_id == "TESTPROJ-456"

    def test_numeric_id_can_handle_with_config(self):
        from ingot.integrations.providers.base import Platform
        from ingot.integrations.providers.registry import ProviderRegistry

        # Set config before getting provider
        ProviderRegistry.set_config({"default_jira_project": "MYPROJ"})

        provider = ProviderRegistry.get_provider(Platform.JIRA)

        # Should be able to handle numeric IDs when configured
        assert provider.can_handle("123") is True
        assert provider.can_handle("999") is True

        # And parse_input should use the configured project
        assert provider.parse_input("123") == "MYPROJ-123"

    def test_no_config_numeric_ids_not_handled(self):
        import os

        from ingot.integrations.providers.base import Platform
        from ingot.integrations.providers.jira import DEFAULT_PROJECT
        from ingot.integrations.providers.registry import ProviderRegistry

        # Clear any env vars that might interfere
        old_env = os.environ.pop("JIRA_DEFAULT_PROJECT", None)
        try:
            # Get provider without setting config
            provider = ProviderRegistry.get_provider(Platform.JIRA)

            # Public behavior: cannot handle numeric-only IDs without explicit config
            assert provider.can_handle("123") is False

            # But parse_input still works (uses fallback default) for direct calls
            # This is expected behavior - parse_input doesn't validate, just parses
            assert provider.parse_input("123") == f"{DEFAULT_PROJECT}-123"
        finally:
            # Restore env var if it was set
            if old_env is not None:
                os.environ["JIRA_DEFAULT_PROJECT"] = old_env

    def test_reset_instances_allows_config_change(self):
        from ingot.integrations.providers.base import Platform
        from ingot.integrations.providers.registry import ProviderRegistry

        # Set initial config
        ProviderRegistry.set_config({"default_jira_project": "FIRST"})
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)

        # Verify first config via public behavior
        assert provider1.parse_input("123") == "FIRST-123"
        assert provider1.can_handle("123") is True

        # Reset instances (no re-registration needed!) and set new config
        ProviderRegistry.reset_instances()
        ProviderRegistry.set_config({"default_jira_project": "SECOND"})
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        # Verify second config via public behavior
        assert provider2.parse_input("123") == "SECOND-123"
        assert provider1 is not provider2  # Different instances
