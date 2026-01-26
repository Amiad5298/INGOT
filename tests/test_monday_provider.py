"""Tests for MondayProvider in spec.integrations.providers.monday module.

Tests cover:
- Provider registration with ProviderRegistry
- can_handle() for URLs
- parse_input() for URL and ID parsing
- normalize() for raw Monday.com data conversion
- Status keyword mapping
- Type keyword mapping
- Description extraction with cascading fallback
- get_prompt_template() returns empty string (no Auggie MCP)
- fetch_ticket() deprecation warning
"""

import warnings

import pytest

from spec.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.monday import (
    MondayProvider,
)
from spec.integrations.providers.registry import ProviderRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before and after each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


@pytest.fixture
def provider():
    """Create a fresh MondayProvider instance."""
    return MondayProvider()


class TestMondayProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    def test_provider_has_platform_attribute(self):
        """MondayProvider has required PLATFORM class attribute."""
        assert hasattr(MondayProvider, "PLATFORM")
        assert MondayProvider.PLATFORM == Platform.MONDAY

    def test_provider_registers_successfully(self):
        """MondayProvider can be registered with ProviderRegistry."""
        ProviderRegistry.register(MondayProvider)
        provider = ProviderRegistry.get_provider(Platform.MONDAY)
        assert provider is not None
        assert isinstance(provider, MondayProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        ProviderRegistry.register(MondayProvider)
        provider1 = ProviderRegistry.get_provider(Platform.MONDAY)
        provider2 = ProviderRegistry.get_provider(Platform.MONDAY)
        assert provider1 is provider2


class TestMondayProviderProperties:
    """Test provider properties."""

    def test_platform_property(self, provider):
        """platform property returns Platform.MONDAY."""
        assert provider.platform == Platform.MONDAY

    def test_name_property(self, provider):
        """name property returns 'Monday.com'."""
        assert provider.name == "Monday.com"


class TestMondayProviderCanHandle:
    """Test can_handle() method."""

    def test_can_handle_monday_board_url(self, provider):
        """Recognizes monday.com board URLs."""
        assert provider.can_handle("https://myworkspace.monday.com/boards/123456/pulses/789")
        assert provider.can_handle("http://company.monday.com/boards/1/pulses/2")

    def test_can_handle_monday_board_url_with_view(self, provider):
        """Recognizes monday.com board URLs with view segment."""
        assert provider.can_handle(
            "https://myworkspace.monday.com/boards/123456/views/789/pulses/456"
        )

    def test_cannot_handle_github_url(self, provider):
        """Does not recognize GitHub URLs."""
        assert not provider.can_handle("https://github.com/owner/repo/issues/1")

    def test_cannot_handle_trello_url(self, provider):
        """Does not recognize Trello URLs."""
        assert not provider.can_handle("https://trello.com/c/abc123")

    def test_cannot_handle_random_text(self, provider):
        """Does not recognize random text."""
        assert not provider.can_handle("not-a-ticket")
        assert not provider.can_handle("123")


class TestMondayProviderParseInput:
    """Test parse_input() method."""

    def test_parse_monday_url(self, provider):
        """Parses monday.com URL to slug:board:item format."""
        result = provider.parse_input("https://myworkspace.monday.com/boards/123456/pulses/789")
        assert result == "myworkspace:123456:789"

    def test_parse_monday_url_with_view(self, provider):
        """Parses monday.com URL with view segment to slug:board:item format."""
        result = provider.parse_input(
            "https://myworkspace.monday.com/boards/123456/views/789/pulses/456"
        )
        assert result == "myworkspace:123456:456"

    def test_parse_with_whitespace(self, provider):
        """Strips whitespace from input."""
        result = provider.parse_input("  https://team.monday.com/boards/1/pulses/2  ")
        assert result == "team:1:2"

    def test_parse_bare_monday_url(self, provider):
        """Parses bare monday.com URL (no subdomain) to :board:item format."""
        result = provider.parse_input("https://monday.com/boards/123456/pulses/789")
        assert result == ":123456:789"

    def test_parse_invalid_raises_valueerror(self, provider):
        """Invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse Monday.com"):
            provider.parse_input("not-a-ticket")


class TestMondayProviderNormalize:
    """Test normalize() method."""

    @pytest.fixture
    def sample_monday_response(self):
        """Sample Monday.com GraphQL response."""
        return {
            "id": "789",
            "name": "Implement new feature",
            "board": {
                "id": "123456",
                "name": "Development",
            },
            "column_values": [
                {"type": "status", "text": "Working on it", "title": "Status"},
                {"type": "text", "text": "Feature description", "title": "Description"},
            ],
            "group": {"id": "group1", "title": "Sprint 42"},
            "subscribers": [
                {"id": "user1", "name": "John Doe", "email": "john@example.com"},
            ],
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-18T14:20:00Z",
        }

    def test_normalize_full_response(self, provider, sample_monday_response):
        """Normalizes full Monday.com response to GenericTicket."""
        ticket = provider.normalize(sample_monday_response)

        assert ticket.id == "123456:789"
        assert ticket.platform == Platform.MONDAY
        assert ticket.title == "Implement new feature"
        # Status is from "column_values" status column, but fixture has "Working on it"
        # which maps to IN_PROGRESS
        assert ticket.status == TicketStatus.IN_PROGRESS
        # Assignee comes from "people" column, not "subscribers"
        assert ticket.assignee is None  # No "people" column in fixture
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_minimal_response(self, provider):
        """Normalizes minimal Monday.com response."""
        minimal = {"id": "1", "name": "Minimal", "board": {"id": "100"}}
        ticket = provider.normalize(minimal)

        assert ticket.id == "100:1"
        assert ticket.title == "Minimal"
        # Empty status label ("") maps to OPEN in STATUS_KEYWORDS
        assert ticket.status == TicketStatus.OPEN
        assert ticket.type == TicketType.UNKNOWN
        assert ticket.assignee is None

    def test_normalize_generates_branch_summary(self, provider, sample_monday_response):
        """Normalizes and generates branch summary."""
        ticket = provider.normalize(sample_monday_response)
        assert ticket.branch_summary == "implement-new-feature"

    def test_normalize_empty_response_raises_valueerror(self, provider):
        """Empty dict raises ValueError due to missing id."""
        with pytest.raises(ValueError, match="id.*missing"):
            provider.normalize({})

    def test_normalize_platform_metadata(self, provider, sample_monday_response):
        """Normalizes platform-specific metadata."""
        ticket = provider.normalize(sample_monday_response)

        assert ticket.platform_metadata["board_id"] == "123456"
        assert ticket.platform_metadata["board_name"] == "Development"
        assert ticket.platform_metadata["group_title"] == "Sprint 42"


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    def test_normalize_with_none_subscribers(self, provider):
        """Handle None subscribers gracefully."""
        data = {"id": "1", "name": "Test", "board": {"id": "100"}, "subscribers": None}
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_empty_subscribers(self, provider):
        """Handle empty subscribers list gracefully."""
        data = {"id": "1", "name": "Test", "board": {"id": "100"}, "subscribers": []}
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_empty_columns(self, provider):
        """Handle empty column_values - empty status maps to OPEN."""
        data = {
            "id": "1",
            "name": "Test",
            "board": {"id": "100"},
            "column_values": [],  # Empty list - no status column
        }
        ticket = provider.normalize(data)
        # Empty status label ("") maps to OPEN in STATUS_KEYWORDS
        assert ticket.status == TicketStatus.OPEN


class TestStatusKeywords:
    """Test status keyword mapping."""

    def test_map_status_open_keywords(self, provider):
        """Map open keywords to OPEN."""
        assert provider._map_status("new") == TicketStatus.OPEN
        assert provider._map_status("to do") == TicketStatus.OPEN
        assert provider._map_status("backlog") == TicketStatus.OPEN
        assert provider._map_status("Not Started") == TicketStatus.OPEN  # case insensitive

    def test_map_status_in_progress_keywords(self, provider):
        """Map in-progress keywords to IN_PROGRESS."""
        assert provider._map_status("working on it") == TicketStatus.IN_PROGRESS
        assert provider._map_status("in progress") == TicketStatus.IN_PROGRESS
        assert provider._map_status("active") == TicketStatus.IN_PROGRESS

    def test_map_status_review_keywords(self, provider):
        """Map review keywords to REVIEW."""
        assert provider._map_status("review") == TicketStatus.REVIEW
        assert provider._map_status("waiting for review") == TicketStatus.REVIEW
        assert provider._map_status("pending") == TicketStatus.REVIEW
        assert provider._map_status("awaiting") == TicketStatus.REVIEW

    def test_map_status_done_keywords(self, provider):
        """Map done keywords to DONE."""
        assert provider._map_status("done") == TicketStatus.DONE
        assert provider._map_status("complete") == TicketStatus.DONE
        assert provider._map_status("completed") == TicketStatus.DONE
        assert provider._map_status("closed") == TicketStatus.DONE  # In DONE, not CLOSED
        assert provider._map_status("finished") == TicketStatus.DONE

    def test_map_status_blocked_keywords(self, provider):
        """Map blocked keywords to BLOCKED."""
        assert provider._map_status("stuck") == TicketStatus.BLOCKED
        assert provider._map_status("blocked") == TicketStatus.BLOCKED

    def test_map_status_unknown(self, provider):
        """Unknown status returns UNKNOWN."""
        assert provider._map_status("CustomStatus") == TicketStatus.UNKNOWN


class TestTypeKeywords:
    """Test type keyword mapping."""

    def test_map_type_bug_keywords(self, provider):
        """Map bug keywords to BUG."""
        assert provider._map_type(["bug"]) == TicketType.BUG
        assert provider._map_type(["defect"]) == TicketType.BUG
        assert provider._map_type(["fix"]) == TicketType.BUG

    def test_map_type_feature_keywords(self, provider):
        """Map feature keywords to FEATURE."""
        assert provider._map_type(["feature"]) == TicketType.FEATURE
        assert provider._map_type(["enhancement"]) == TicketType.FEATURE
        assert provider._map_type(["story"]) == TicketType.FEATURE

    def test_map_type_task_keywords(self, provider):
        """Map task keywords to TASK."""
        assert provider._map_type(["task"]) == TicketType.TASK
        assert provider._map_type(["chore"]) == TicketType.TASK

    def test_map_type_maintenance_keywords(self, provider):
        """Map maintenance keywords to MAINTENANCE."""
        assert provider._map_type(["maintenance"]) == TicketType.MAINTENANCE
        assert provider._map_type(["tech debt"]) == TicketType.MAINTENANCE

    def test_map_type_unknown(self, provider):
        """Unknown type returns UNKNOWN."""
        assert provider._map_type(["custom"]) == TicketType.UNKNOWN
        assert provider._map_type([]) == TicketType.UNKNOWN


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    def test_get_prompt_template_returns_empty_string(self, provider):
        """get_prompt_template returns empty string - no Auggie MCP support."""
        assert provider.get_prompt_template() == ""


class TestFetchTicketDeprecation:
    """Test fetch_ticket() deprecation."""

    def test_fetch_ticket_raises_deprecation_warning(self, provider):
        """fetch_ticket raises DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(NotImplementedError):
                provider.fetch_ticket("123456:789")
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_fetch_ticket_raises_not_implemented_error(self, provider):
        """fetch_ticket raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="deprecated"):
            provider.fetch_ticket("123456:789")
