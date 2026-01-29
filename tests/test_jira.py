"""Tests for spec.integrations.jira module."""

from unittest.mock import MagicMock, patch

import pytest

from spec.integrations.jira import (
    JiraTicket,
    check_jira_integration,
    fetch_ticket_info,
    parse_jira_ticket,
)


class TestParseJiraTicket:
    """Tests for parse_jira_ticket function."""

    def test_parse_url(self):
        """Extracts ticket ID from URL."""
        result = parse_jira_ticket("https://jira.example.com/browse/PROJECT-123")

        assert result.ticket_id == "PROJECT-123"
        assert result.ticket_url == "https://jira.example.com/browse/PROJECT-123"

    def test_parse_url_with_path(self):
        """Extracts ticket ID from URL with additional path."""
        result = parse_jira_ticket("https://jira.example.com/browse/PROJ-456/details")

        assert result.ticket_id == "PROJ-456"

    def test_parse_ticket_id_uppercase(self):
        """Parses uppercase ticket ID."""
        result = parse_jira_ticket("PROJECT-123")

        assert result.ticket_id == "PROJECT-123"

    def test_parse_ticket_id_lowercase(self):
        """Normalizes lowercase ticket ID to uppercase."""
        result = parse_jira_ticket("project-456")

        assert result.ticket_id == "PROJECT-456"

    def test_parse_ticket_id_mixed_case(self):
        """Normalizes mixed case ticket ID."""
        result = parse_jira_ticket("Project-789")

        assert result.ticket_id == "PROJECT-789"

    def test_parse_numeric_with_default(self):
        """Parses numeric ID with default project."""
        result = parse_jira_ticket("789", default_project="MYPROJ")

        assert result.ticket_id == "MYPROJ-789"

    def test_parse_numeric_without_default(self):
        """Raises error for numeric-only IDs without default project."""
        with pytest.raises(ValueError, match="default project"):
            parse_jira_ticket("789")

    def test_parse_invalid_format(self):
        """Raises error for invalid format."""
        with pytest.raises(ValueError, match="Invalid ticket format"):
            parse_jira_ticket("not-a-ticket!")

    def test_parse_invalid_url(self):
        """Raises error for URL without ticket ID."""
        with pytest.raises(ValueError, match="Could not extract"):
            parse_jira_ticket("https://jira.example.com/browse/")

    def test_parse_strips_whitespace(self):
        """Strips whitespace from input."""
        result = parse_jira_ticket("  PROJECT-123  ")

        assert result.ticket_id == "PROJECT-123"


class TestCheckJiraIntegration:
    """Tests for check_jira_integration function."""

    def test_uses_cached_result(self):
        """Uses cached result within 24 hours."""
        import time

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default="": {
            "JIRA_CHECK_TIMESTAMP": str(int(time.time()) - 3600),  # 1 hour ago
            "JIRA_INTEGRATION_STATUS": "working",
        }.get(key, default)

        mock_auggie = MagicMock()

        with patch("spec.integrations.jira.print_success"):
            result = check_jira_integration(mock_config, mock_auggie, force=False)

        assert result is True
        mock_auggie.run_print_quiet.assert_not_called()

    def test_force_bypasses_cache(self):
        """Force flag bypasses cache."""
        import time

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default="": {
            "JIRA_CHECK_TIMESTAMP": str(int(time.time()) - 3600),
            "JIRA_INTEGRATION_STATUS": "working",
        }.get(key, default)

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "YES, Jira is available"

        with patch("spec.integrations.jira.print_info"), patch(
            "spec.integrations.jira.print_success"
        ), patch("spec.integrations.jira.print_step"):
            check_jira_integration(mock_config, mock_auggie, force=True)

        mock_auggie.run_print_quiet.assert_called_once()

    def test_detects_working_integration(self):
        """Detects working Jira integration."""
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "YES, Jira is available"

        with patch("spec.integrations.jira.print_info"), patch(
            "spec.integrations.jira.print_success"
        ), patch("spec.integrations.jira.print_step"):
            result = check_jira_integration(mock_config, mock_auggie)

        assert result is True
        mock_config.save.assert_any_call("JIRA_INTEGRATION_STATUS", "working")

    def test_detects_not_configured(self):
        """Detects Jira not configured."""
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "Jira is not configured"

        with patch("spec.integrations.jira.print_info"), patch(
            "spec.integrations.jira.print_warning"
        ), patch("spec.integrations.jira.print_step"):
            result = check_jira_integration(mock_config, mock_auggie)

        assert result is False
        mock_config.save.assert_any_call("JIRA_INTEGRATION_STATUS", "not_configured")


class TestFetchTicketInfo:
    """Tests for fetch_ticket_info function."""

    def test_parses_branch_summary(self):
        """Parses branch summary from response."""
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
        """Sanitizes branch summary for git."""
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
        """Numeric ID works when default_project is explicitly passed.

        This is the core regression test: verify that parse_jira_ticket
        correctly handles numeric IDs when given a default_project.
        """
        result = parse_jira_ticket("456", default_project="CONFIGURED")

        assert result.ticket_id == "CONFIGURED-456"
        assert result.ticket_url == "CONFIGURED-456"

    def test_parse_numeric_id_normalizes_project_to_uppercase(self):
        """Default project is normalized to uppercase."""
        result = parse_jira_ticket("789", default_project="lowercase")

        assert result.ticket_id == "LOWERCASE-789"

    def test_parse_numeric_id_without_default_raises_helpful_error(self):
        """Numeric ID without default_project raises a helpful error message."""
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
        from spec.integrations.providers.jira import JiraProvider
        from spec.integrations.providers.registry import ProviderRegistry

        ProviderRegistry.clear()
        # Re-register JiraProvider after clear (decorator ran at import time)
        ProviderRegistry.register(JiraProvider)
        yield
        # Use reset_instances for cleanup (preserves registration for other tests)
        ProviderRegistry.reset_instances()

    def test_set_config_injects_default_project_to_jira_provider(self):
        """ProviderRegistry.set_config passes default_jira_project to JiraProvider.

        This is the core wiring test: verify that calling set_config with
        default_jira_project causes the JiraProvider instance to use that
        value for numeric ID parsing.

        Tests public behavior: parse_input() and can_handle() for numeric IDs.
        """
        from spec.integrations.providers.base import Platform
        from spec.integrations.providers.registry import ProviderRegistry

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
        """JiraProvider.can_handle returns True for numeric IDs when config is set.

        When default_jira_project is configured, JiraProvider should be able
        to handle numeric-only ticket IDs.
        """
        from spec.integrations.providers.base import Platform
        from spec.integrations.providers.registry import ProviderRegistry

        # Set config before getting provider
        ProviderRegistry.set_config({"default_jira_project": "MYPROJ"})

        provider = ProviderRegistry.get_provider(Platform.JIRA)

        # Should be able to handle numeric IDs when configured
        assert provider.can_handle("123") is True
        assert provider.can_handle("999") is True

        # And parse_input should use the configured project
        assert provider.parse_input("123") == "MYPROJ-123"

    def test_no_config_numeric_ids_not_handled(self):
        """Without set_config, JiraProvider cannot handle numeric-only IDs.

        When no config is provided and no env var is set, numeric-only IDs
        are rejected by can_handle() to prevent ambiguous platform detection.

        Tests public behavior: can_handle() returns False for numeric IDs.
        """
        import os

        from spec.integrations.providers.base import Platform
        from spec.integrations.providers.jira import DEFAULT_PROJECT
        from spec.integrations.providers.registry import ProviderRegistry

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
        """reset_instances() allows changing config without re-registering providers.

        After reset_instances(), setting new config should create a new provider
        instance with the new config values, without needing to re-register.
        """
        from spec.integrations.providers.base import Platform
        from spec.integrations.providers.registry import ProviderRegistry

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
