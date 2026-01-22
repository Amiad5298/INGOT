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
        """Raises error for numeric without default project."""
        with pytest.raises(ValueError, match="DEFAULT_JIRA_PROJECT"):
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

        with patch("spec.integrations.jira.print_info"), \
             patch("spec.integrations.jira.print_success"), \
             patch("spec.integrations.jira.print_step"):
            check_jira_integration(mock_config, mock_auggie, force=True)

        mock_auggie.run_print_quiet.assert_called_once()

    def test_detects_working_integration(self):
        """Detects working Jira integration."""
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "YES, Jira is available"

        with patch("spec.integrations.jira.print_info"), \
             patch("spec.integrations.jira.print_success"), \
             patch("spec.integrations.jira.print_step"):
            result = check_jira_integration(mock_config, mock_auggie)

        assert result is True
        mock_config.save.assert_any_call("JIRA_INTEGRATION_STATUS", "working")

    def test_detects_not_configured(self):
        """Detects Jira not configured."""
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        mock_auggie = MagicMock()
        mock_auggie.run_print_quiet.return_value = "Jira is not configured"

        with patch("spec.integrations.jira.print_info"), \
             patch("spec.integrations.jira.print_warning"), \
             patch("spec.integrations.jira.print_step"):
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

