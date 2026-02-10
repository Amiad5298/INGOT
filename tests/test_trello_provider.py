"""Tests for TrelloProvider in ingot.integrations.providers.trello module.

Tests cover:
- Provider registration with ProviderRegistry
- can_handle() for URLs and short links
- parse_input() for URL and short link parsing
- normalize() for raw Trello data conversion
- List-based status mapping
- Label-based type mapping
- Created date extraction from MongoDB ObjectId
- Closed card handling
- get_prompt_template() returns empty string (no Auggie MCP)
"""

from datetime import UTC

import pytest

from ingot.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
)
from ingot.integrations.providers.registry import ProviderRegistry
from ingot.integrations.providers.trello import (
    TrelloProvider,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before and after each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


@pytest.fixture
def provider():
    """Create a fresh TrelloProvider instance."""
    return TrelloProvider()


class TestTrelloProviderRegistration:
    def test_provider_has_platform_attribute(self):
        assert hasattr(TrelloProvider, "PLATFORM")
        assert TrelloProvider.PLATFORM == Platform.TRELLO

    def test_provider_registers_successfully(self):
        ProviderRegistry.register(TrelloProvider)
        provider = ProviderRegistry.get_provider(Platform.TRELLO)
        assert provider is not None
        assert isinstance(provider, TrelloProvider)

    def test_singleton_pattern(self):
        ProviderRegistry.register(TrelloProvider)
        provider1 = ProviderRegistry.get_provider(Platform.TRELLO)
        provider2 = ProviderRegistry.get_provider(Platform.TRELLO)
        assert provider1 is provider2


class TestTrelloProviderProperties:
    def test_platform_property(self, provider):
        assert provider.platform == Platform.TRELLO

    def test_name_property(self, provider):
        assert provider.name == "Trello"


class TestTrelloProviderCanHandle:
    def test_can_handle_trello_card_url(self, provider):
        assert provider.can_handle("https://trello.com/c/abc12345")
        assert provider.can_handle("https://trello.com/c/abc12345/card-title")
        assert provider.can_handle("http://trello.com/c/XyZ12AbC")

    def test_can_handle_short_link(self, provider):
        assert provider.can_handle("abc12345")
        assert provider.can_handle("XyZ12AbC")

    def test_cannot_handle_short_link_wrong_length(self, provider):
        assert not provider.can_handle("abc123")  # too short
        assert not provider.can_handle("abc1234567")  # too long

    def test_cannot_handle_github_url(self, provider):
        assert not provider.can_handle("https://github.com/owner/repo/issues/1")

    def test_cannot_handle_monday_url(self, provider):
        assert not provider.can_handle("https://team.monday.com/boards/123/pulses/456")

    def test_cannot_handle_random_text(self, provider):
        assert not provider.can_handle("not-a-ticket")


class TestTrelloProviderParseInput:
    def test_parse_trello_url(self, provider):
        result = provider.parse_input("https://trello.com/c/abc12345")
        assert result == "abc12345"

    def test_parse_trello_url_with_title(self, provider):
        result = provider.parse_input("https://trello.com/c/abc12345/some-card-title")
        assert result == "abc12345"

    def test_parse_short_link(self, provider):
        assert provider.parse_input("abc12345") == "abc12345"

    def test_parse_with_whitespace(self, provider):
        result = provider.parse_input("  https://trello.com/c/abc12345  ")
        assert result == "abc12345"

    def test_parse_invalid_raises_valueerror(self, provider):
        with pytest.raises(ValueError, match="Cannot parse Trello"):
            provider.parse_input("not-a-ticket")


class TestTrelloProviderNormalize:
    @pytest.fixture
    def sample_trello_response(self):
        """Sample Trello REST API response."""
        return {
            "id": "5f9e8d7c6b5a4321",
            "shortLink": "abc12345",
            "name": "Fix login bug",
            "desc": "Users cannot log in with OAuth",
            "url": "https://trello.com/c/abc12345/1-fix-login-bug",
            "closed": False,
            "idBoard": "board123",
            "idList": "list456",
            "list": {"id": "list456", "name": "In Progress"},
            "board": {"id": "board123", "name": "Development"},
            "labels": [{"name": "bug"}, {"name": "urgent"}],
            "members": [{"id": "user1", "fullName": "John Doe"}],
            "dateLastActivity": "2024-01-18T14:20:00.000Z",
            "due": "2024-01-20T12:00:00.000Z",
            "dueComplete": False,
        }

    def test_normalize_full_response(self, provider, sample_trello_response):
        ticket = provider.normalize(sample_trello_response)

        assert ticket.id == "abc12345"
        assert ticket.platform == Platform.TRELLO
        assert ticket.url == "https://trello.com/c/abc12345/1-fix-login-bug"
        assert ticket.title == "Fix login bug"
        assert ticket.description == "Users cannot log in with OAuth"
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.type == TicketType.BUG
        assert ticket.assignee == "John Doe"
        assert ticket.labels == ["bug", "urgent"]
        assert ticket.updated_at is not None

    def test_normalize_minimal_response(self, provider):
        minimal = {"id": "abc12345", "shortLink": "abc12345", "name": "Minimal"}
        ticket = provider.normalize(minimal)

        assert ticket.id == "abc12345"
        assert ticket.title == "Minimal"
        assert ticket.status == TicketStatus.UNKNOWN
        assert ticket.type == TicketType.UNKNOWN
        assert ticket.assignee is None
        assert ticket.labels == []

    def test_normalize_generates_branch_summary(self, provider, sample_trello_response):
        ticket = provider.normalize(sample_trello_response)
        assert ticket.branch_summary == "fix-login-bug"

    def test_normalize_platform_metadata(self, provider, sample_trello_response):
        ticket = provider.normalize(sample_trello_response)

        assert ticket.platform_metadata["board_id"] == "board123"
        assert ticket.platform_metadata["board_name"] == "Development"
        assert ticket.platform_metadata["list_id"] == "list456"
        assert ticket.platform_metadata["list_name"] == "In Progress"
        assert ticket.platform_metadata["short_link"] == "abc12345"


class TestDefensiveFieldHandling:
    def test_normalize_with_none_members(self, provider):
        data = {"id": "abc12345", "shortLink": "abc12345", "name": "Test", "members": None}
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_empty_members(self, provider):
        data = {"id": "abc12345", "shortLink": "abc12345", "name": "Test", "members": []}
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_non_dict_member(self, provider):
        data = {
            "id": "abc12345",
            "shortLink": "abc12345",
            "name": "Test",
            "members": [None, "string"],
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_missing_shortlink_uses_id(self, provider):
        data = {"id": "5f9e8d7c6b5a4321", "name": "Test"}
        ticket = provider.normalize(data)
        assert ticket.id == "5f9e8d7c6b5a4321"

    def test_normalize_missing_both_id_and_shortlink_raises(self, provider):
        with pytest.raises(ValueError, match="id.*shortLink"):
            provider.normalize({"name": "Test"})


class TestListStatusMapping:
    def test_map_status_open_lists(self, provider):
        assert provider._map_list_to_status("To Do") == TicketStatus.OPEN
        assert provider._map_list_to_status("Backlog") == TicketStatus.OPEN
        assert provider._map_list_to_status("todo") == TicketStatus.OPEN
        assert provider._map_list_to_status("new") == TicketStatus.OPEN
        assert provider._map_list_to_status("inbox") == TicketStatus.OPEN

    def test_map_status_in_progress_lists(self, provider):
        assert provider._map_list_to_status("In Progress") == TicketStatus.IN_PROGRESS
        assert provider._map_list_to_status("Doing") == TicketStatus.IN_PROGRESS
        assert provider._map_list_to_status("Active") == TicketStatus.IN_PROGRESS
        assert provider._map_list_to_status("working") == TicketStatus.IN_PROGRESS

    def test_map_status_review_lists(self, provider):
        assert provider._map_list_to_status("Review") == TicketStatus.REVIEW
        assert provider._map_list_to_status("In Review") == TicketStatus.REVIEW
        assert provider._map_list_to_status("Testing") == TicketStatus.REVIEW
        assert provider._map_list_to_status("QA") == TicketStatus.REVIEW

    def test_map_status_blocked_lists(self, provider):
        assert provider._map_list_to_status("Blocked") == TicketStatus.BLOCKED
        assert provider._map_list_to_status("On Hold") == TicketStatus.BLOCKED
        assert provider._map_list_to_status("Waiting") == TicketStatus.BLOCKED

    def test_map_status_done_lists(self, provider):
        assert provider._map_list_to_status("Done") == TicketStatus.DONE
        assert provider._map_list_to_status("Complete") == TicketStatus.DONE
        assert provider._map_list_to_status("Completed") == TicketStatus.DONE
        assert provider._map_list_to_status("Closed") == TicketStatus.DONE
        assert provider._map_list_to_status("Archived") == TicketStatus.DONE

    def test_map_status_unknown_list(self, provider):
        assert provider._map_list_to_status("CustomList") == TicketStatus.UNKNOWN


class TestTypeKeywords:
    def test_map_type_bug_labels(self, provider):
        assert provider._map_type(["bug"]) == TicketType.BUG
        assert provider._map_type(["defect"]) == TicketType.BUG
        assert provider._map_type(["fix"]) == TicketType.BUG
        assert provider._map_type(["error"]) == TicketType.BUG
        assert provider._map_type(["issue"]) == TicketType.BUG

    def test_map_type_feature_labels(self, provider):
        assert provider._map_type(["feature"]) == TicketType.FEATURE
        assert provider._map_type(["enhancement"]) == TicketType.FEATURE
        assert provider._map_type(["story"]) == TicketType.FEATURE
        assert provider._map_type(["new"]) == TicketType.FEATURE

    def test_map_type_task_labels(self, provider):
        assert provider._map_type(["task"]) == TicketType.TASK
        assert provider._map_type(["chore"]) == TicketType.TASK
        assert provider._map_type(["action"]) == TicketType.TASK

    def test_map_type_maintenance_labels(self, provider):
        assert provider._map_type(["maintenance"]) == TicketType.MAINTENANCE
        assert provider._map_type(["tech debt"]) == TicketType.MAINTENANCE
        assert provider._map_type(["refactor"]) == TicketType.MAINTENANCE
        assert provider._map_type(["cleanup"]) == TicketType.MAINTENANCE
        assert provider._map_type(["infra"]) == TicketType.MAINTENANCE

    def test_map_type_unknown(self, provider):
        assert provider._map_type(["custom"]) == TicketType.UNKNOWN
        assert provider._map_type([]) == TicketType.UNKNOWN


class TestCreatedAtExtraction:
    def test_get_created_at_valid_objectid(self, provider):
        # ObjectId "5f9e8d7c..." has timestamp 5f9e8d7c (hex) = 1604194684 (dec)
        # which is 2020-11-01T03:31:24 UTC
        created_at = provider._get_created_at("5f9e8d7c6b5a4321")
        assert created_at.year == 2020
        assert created_at.month == 11
        assert created_at.tzinfo == UTC

    def test_get_created_at_invalid_objectid(self, provider):
        # Too short ID should return None (not misleading datetime.now())
        created_at = provider._get_created_at("abc")
        assert created_at is None

    def test_get_created_at_non_hex_objectid(self, provider):
        created_at = provider._get_created_at("xxxxxxxx")
        assert created_at is None


class TestClosedCardHandling:
    def test_closed_card_overrides_list_status(self, provider):
        data = {
            "id": "abc12345",
            "shortLink": "abc12345",
            "name": "Test",
            "closed": True,
            "list": {"name": "In Progress"},  # Would normally be IN_PROGRESS
        }
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.CLOSED

    def test_open_card_uses_list_status(self, provider):
        data = {
            "id": "abc12345",
            "shortLink": "abc12345",
            "name": "Test",
            "closed": False,
            "list": {"name": "In Progress"},
        }
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.IN_PROGRESS


class TestPromptTemplate:
    def test_get_prompt_template_returns_empty_string(self, provider):
        assert provider.get_prompt_template() == ""
