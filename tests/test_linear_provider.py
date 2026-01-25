"""Tests for LinearProvider in spec.integrations.providers.linear module.

Tests cover:
- Provider registration with ProviderRegistry (with explicit registration)
- can_handle() for URLs and ticket IDs (including alphanumeric teams like G2)
- parse_input() for URL and ID parsing with strict fullmatch
- normalize() for raw Linear GraphQL data conversion
- ID validation (ValueError on empty/missing identifier)
- Defensive field handling for malformed responses
- Status mapping (state.name priority over state.type for "In Review")
- Type mapping (default to FEATURE, not UNKNOWN)
- get_prompt_template() and other methods
- fetch_ticket() and check_connection() deprecation warnings
"""

import warnings

import pytest

from spec.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.linear import (
    LinearProvider,
)
from spec.integrations.providers.registry import ProviderRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before and after each test.

    This fixture ensures proper test isolation by:
    1. Clearing the registry before each test
    2. Clearing after each test for cleanup

    NOTE: Tests that need a registered provider should explicitly call
    ProviderRegistry.register(LinearProvider) to avoid relying on
    import side-effects which can cause flaky tests.
    """
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


@pytest.fixture
def provider():
    """Create a fresh LinearProvider instance."""
    return LinearProvider()


class TestLinearProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    def test_provider_has_platform_attribute(self):
        """LinearProvider has required PLATFORM class attribute."""
        assert hasattr(LinearProvider, "PLATFORM")
        assert LinearProvider.PLATFORM == Platform.LINEAR

    def test_provider_registers_successfully(self):
        """LinearProvider can be registered with ProviderRegistry."""
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(LinearProvider)

        provider = ProviderRegistry.get_provider(Platform.LINEAR)
        assert provider is not None
        assert isinstance(provider, LinearProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(LinearProvider)

        provider1 = ProviderRegistry.get_provider(Platform.LINEAR)
        provider2 = ProviderRegistry.get_provider(Platform.LINEAR)
        assert provider1 is provider2


class TestLinearProviderProperties:
    """Test provider properties."""

    def test_platform_property(self, provider):
        """platform property returns Platform.LINEAR."""
        assert provider.platform == Platform.LINEAR

    def test_name_property(self, provider):
        """name property returns 'Linear'."""
        assert provider.name == "Linear"


class TestLinearProviderCanHandle:
    """Test can_handle() method with strict fullmatch patterns."""

    # Valid URLs (including alphanumeric team keys like G2)
    @pytest.mark.parametrize(
        "url",
        [
            "https://linear.app/myteam/issue/ENG-123",
            "https://linear.app/company/issue/DESIGN-456",
            "https://linear.app/team/issue/ABC-1",
            "https://linear.app/team/issue/ENG-123/implement-feature",
            "https://linear.app/team/issue/ENG-123/some-title-slug",
            "http://linear.app/team/issue/TEST-99",  # http also works
            # Alphanumeric team keys (G2, A1, etc.)
            "https://linear.app/org/issue/G2-42",
            "https://linear.app/org/issue/A1-1",
            "https://linear.app/org/issue/X99-999/with-slug",
        ],
    )
    def test_can_handle_valid_urls(self, provider, url):
        """can_handle returns True for valid Linear URLs."""
        assert provider.can_handle(url) is True

    # Valid IDs (TEAM-123 format with alphanumeric team support)
    @pytest.mark.parametrize(
        "ticket_id",
        [
            "ENG-123",
            "DESIGN-456",
            "ABC-1",
            "XYZ-99999",
            "eng-123",  # lowercase
            "A1-1",  # alphanumeric team
            "G2-42",  # alphanumeric team (common in Linear)
            "X99-999",  # multiple digits in team key
        ],
    )
    def test_can_handle_valid_ids(self, provider, ticket_id):
        """can_handle returns True for valid ticket IDs including alphanumeric teams."""
        assert provider.can_handle(ticket_id) is True

    # Invalid inputs - strict fullmatch rejects partial matches
    @pytest.mark.parametrize(
        "input_str",
        [
            "https://github.com/owner/repo/issues/123",
            "https://company.atlassian.net/browse/PROJ-123",
            "owner/repo#123",
            "AMI-18-implement-feature",  # Not just ticket ID (partial match rejected)
            "ENG-123abc",  # Trailing characters (fullmatch rejects this)
            "PROJECT",  # No number
            "",  # Empty
            "abc",  # Letters only, no dash
            "123",  # Numeric only (not supported for Linear)
            "1ABC-123",  # Team key must start with letter
        ],
    )
    def test_can_handle_invalid_inputs(self, provider, input_str):
        """can_handle returns False for invalid inputs (fullmatch rejects partials)."""
        assert provider.can_handle(input_str) is False


class TestLinearProviderParseInput:
    """Test parse_input() method with strict fullmatch patterns."""

    def test_parse_linear_url(self, provider):
        """parse_input extracts ticket ID from Linear URL."""
        url = "https://linear.app/myteam/issue/ENG-123"
        assert provider.parse_input(url) == "ENG-123"

    def test_parse_linear_url_with_title(self, provider):
        """parse_input extracts ticket ID from URL with title slug."""
        url = "https://linear.app/team/issue/DESIGN-456/implement-new-feature"
        assert provider.parse_input(url) == "DESIGN-456"

    def test_parse_alphanumeric_team_id(self, provider):
        """parse_input handles alphanumeric team keys like G2, A1."""
        assert provider.parse_input("G2-42") == "G2-42"
        assert provider.parse_input("A1-1") == "A1-1"
        assert provider.parse_input("X99-999") == "X99-999"

    def test_parse_alphanumeric_team_url(self, provider):
        """parse_input handles URLs with alphanumeric team keys."""
        url = "https://linear.app/org/issue/G2-42/some-title"
        assert provider.parse_input(url) == "G2-42"

    def test_parse_lowercase_id(self, provider):
        """parse_input normalizes lowercase IDs to uppercase."""
        assert provider.parse_input("eng-123") == "ENG-123"
        assert provider.parse_input("g2-42") == "G2-42"

    def test_parse_with_whitespace(self, provider):
        """parse_input strips whitespace."""
        assert provider.parse_input("  ENG-123  ") == "ENG-123"

    def test_parse_invalid_raises_valueerror(self, provider):
        """parse_input raises ValueError for invalid input."""
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("not-a-ticket")

    def test_parse_numeric_only_raises_valueerror(self, provider):
        """Linear doesn't support numeric-only IDs."""
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("123")

    def test_parse_partial_match_rejected(self, provider):
        """parse_input uses fullmatch to reject partial matches like ENG-123abc."""
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("ENG-123abc")

    def test_parse_ticket_with_suffix_rejected(self, provider):
        """parse_input rejects ticket ID with trailing text."""
        with pytest.raises(ValueError, match="Cannot parse Linear ticket"):
            provider.parse_input("AMI-18-implement-feature")


class TestLinearProviderNormalize:
    """Test normalize() method with ID validation and metadata handling."""

    @pytest.fixture
    def sample_linear_response(self):
        """Sample Linear GraphQL response."""
        return {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "identifier": "ENG-123",
            "title": "Implement user authentication",
            "description": "Add OAuth2 login flow with Google and GitHub providers.",
            "url": "https://linear.app/myteam/issue/ENG-123",
            "state": {
                "name": "In Progress",
                "type": "started",
            },
            "assignee": {
                "name": "Jane Developer",
                "email": "jane@company.com",
            },
            "labels": {
                "nodes": [
                    {"name": "feature"},
                    {"name": "backend"},
                ],
            },
            "createdAt": "2024-01-15T10:30:00.000Z",
            "updatedAt": "2024-01-18T14:20:00.000Z",
            "priority": 2,
            "priorityLabel": "High",
            "team": {
                "key": "ENG",
                "name": "Engineering",
            },
            "cycle": {
                "name": "Sprint 42",
            },
            "parent": None,
        }

    def test_normalize_full_response(self, provider, sample_linear_response):
        """normalize converts full Linear response to GenericTicket."""
        ticket = provider.normalize(sample_linear_response)

        assert ticket.id == "ENG-123"
        assert ticket.platform == Platform.LINEAR
        assert ticket.url == "https://linear.app/myteam/issue/ENG-123"
        assert ticket.title == "Implement user authentication"
        assert ticket.description == "Add OAuth2 login flow with Google and GitHub providers."
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.type == TicketType.FEATURE
        assert ticket.assignee == "Jane Developer"
        assert ticket.labels == ["feature", "backend"]
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_platform_metadata(self, provider, sample_linear_response):
        """normalize populates platform_metadata correctly (without raw_response)."""
        ticket = provider.normalize(sample_linear_response)

        assert ticket.platform_metadata["linear_uuid"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert ticket.platform_metadata["team_key"] == "ENG"
        assert ticket.platform_metadata["team_name"] == "Engineering"
        assert ticket.platform_metadata["priority_label"] == "High"
        assert ticket.platform_metadata["priority_value"] == 2
        assert ticket.platform_metadata["state_type"] == "started"
        assert ticket.platform_metadata["state_name"] == "In Progress"
        assert ticket.platform_metadata["cycle"] == "Sprint 42"
        assert ticket.platform_metadata["parent_id"] is None
        # raw_response should NOT be in metadata (removed to avoid log/cache bloat)
        assert "raw_response" not in ticket.platform_metadata

    def test_normalize_minimal_response(self, provider):
        """normalize handles minimal response - defaults to FEATURE type."""
        minimal = {
            "identifier": "TEST-1",
            "title": "Minimal issue",
            "state": {},
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(minimal)

        assert ticket.id == "TEST-1"
        assert ticket.title == "Minimal issue"
        assert ticket.status == TicketStatus.UNKNOWN
        # Default type is FEATURE (not UNKNOWN) per requirements
        assert ticket.type == TicketType.FEATURE

    def test_normalize_with_parent(self, provider, sample_linear_response):
        """normalize extracts parent_id from parent object."""
        sample_linear_response["parent"] = {"identifier": "ENG-100"}
        ticket = provider.normalize(sample_linear_response)

        assert ticket.platform_metadata["parent_id"] == "ENG-100"


class TestIDValidation:
    """Test ID validation - must raise ValueError for missing/empty identifier."""

    def test_normalize_missing_identifier_raises(self, provider):
        """normalize raises ValueError when identifier field is missing."""
        data = {"title": "Test", "state": {}, "labels": {"nodes": []}}
        with pytest.raises(ValueError, match="identifier.*missing or empty"):
            provider.normalize(data)

    def test_normalize_empty_identifier_raises(self, provider):
        """normalize raises ValueError when identifier is empty string."""
        data = {"identifier": "", "title": "Test", "state": {}, "labels": {"nodes": []}}
        with pytest.raises(ValueError, match="identifier.*missing or empty"):
            provider.normalize(data)

    def test_normalize_whitespace_only_identifier_raises(self, provider):
        """normalize raises ValueError when identifier is whitespace only."""
        data = {"identifier": "   ", "title": "Test", "state": {}, "labels": {"nodes": []}}
        with pytest.raises(ValueError, match="identifier.*missing or empty"):
            provider.normalize(data)

    def test_normalize_none_identifier_raises(self, provider):
        """normalize raises ValueError when identifier is None."""
        data = {"identifier": None, "title": "Test", "state": {}, "labels": {"nodes": []}}
        with pytest.raises(ValueError, match="identifier.*missing or empty"):
            provider.normalize(data)

    def test_normalize_non_string_identifier_raises(self, provider):
        """normalize raises ValueError when identifier is not a string."""
        data = {"identifier": 123, "title": "Test", "state": {}, "labels": {"nodes": []}}
        with pytest.raises(ValueError, match="identifier.*missing or empty"):
            provider.normalize(data)


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    def test_normalize_with_none_state(self, provider):
        """Handle None state gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": None, "labels": {"nodes": []}}
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.UNKNOWN

    def test_normalize_with_non_dict_state(self, provider):
        """Handle non-dict state gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": "invalid",
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.status == TicketStatus.UNKNOWN

    def test_normalize_with_none_assignee(self, provider):
        """Handle None assignee gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "assignee": None,
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_none_labels(self, provider):
        """Handle None labels gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "labels": None}
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_non_dict_labels(self, provider):
        """Handle non-dict labels gracefully."""
        data = {"identifier": "TEST-1", "title": "Test", "state": {}, "labels": "invalid"}
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_malformed_label_nodes(self, provider):
        """Handle malformed label nodes gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "labels": {"nodes": [None, "invalid", {"name": "valid"}, {"name": ""}]},
        }
        ticket = provider.normalize(data)
        assert ticket.labels == ["valid"]

    def test_normalize_with_none_team(self, provider):
        """Handle None team gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "team": None,
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["team_key"] == ""
        assert ticket.platform_metadata["team_name"] == ""

    def test_normalize_with_none_cycle(self, provider):
        """Handle None cycle gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "cycle": None,
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["cycle"] is None

    def test_normalize_with_none_parent(self, provider):
        """Handle None parent gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "parent": None,
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.platform_metadata["parent_id"] is None

    def test_normalize_with_assignee_email_only(self, provider):
        """Assignee with only email (no name) uses email as fallback."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "assignee": {"email": "user@example.com"},
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.assignee == "user@example.com"

    def test_normalize_with_assignee_empty_name(self, provider):
        """Assignee with empty name falls back to email."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "assignee": {"name": "", "email": "user@example.com"},
            "labels": {"nodes": []},
        }
        ticket = provider.normalize(data)
        assert ticket.assignee == "user@example.com"

    def test_normalize_with_malformed_timestamp(self, provider):
        """Handle malformed timestamp strings gracefully."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "labels": {"nodes": []},
            "createdAt": "not-a-date",
            "updatedAt": "12345",
        }
        ticket = provider.normalize(data)
        assert ticket.created_at is None
        assert ticket.updated_at is None

    def test_normalize_with_non_string_timestamp(self, provider):
        """Handle non-string timestamp (e.g., integer) gracefully - triggers TypeError."""
        data = {
            "identifier": "TEST-1",
            "title": "Test",
            "state": {},
            "labels": {"nodes": []},
            "createdAt": 12345,  # Integer instead of string
            "updatedAt": {"invalid": "dict"},  # Dict instead of string
        }
        ticket = provider.normalize(data)
        # Should return None for both due to TypeError in _parse_timestamp
        assert ticket.created_at is None
        assert ticket.updated_at is None


class TestStatusMapping:
    """Test status mapping - state.name takes PRIORITY over state.type."""

    @pytest.mark.parametrize(
        "state_type,expected",
        [
            ("backlog", TicketStatus.OPEN),
            ("unstarted", TicketStatus.OPEN),
            ("started", TicketStatus.IN_PROGRESS),
            ("completed", TicketStatus.DONE),
            ("canceled", TicketStatus.CLOSED),
        ],
    )
    def test_state_type_mapping(self, provider, state_type, expected):
        """Test mapping by state.type when state.name is empty."""
        assert provider._map_status(state_type, "") == expected

    @pytest.mark.parametrize(
        "state_name,expected",
        [
            ("Backlog", TicketStatus.OPEN),
            ("Triage", TicketStatus.OPEN),
            ("Todo", TicketStatus.OPEN),
            ("In Progress", TicketStatus.IN_PROGRESS),
            ("In Review", TicketStatus.REVIEW),
            ("Review", TicketStatus.REVIEW),
            ("Code Review", TicketStatus.REVIEW),
            ("Pending Review", TicketStatus.REVIEW),
            ("Done", TicketStatus.DONE),
            ("Canceled", TicketStatus.CLOSED),
        ],
    )
    def test_state_name_mapping(self, provider, state_name, expected):
        """Test state.name mapping (checked FIRST before state.type)."""
        assert provider._map_status("", state_name) == expected

    def test_state_name_priority_over_type(self, provider):
        """CRITICAL: state.name 'In Review' should map to REVIEW, not IN_PROGRESS.

        Linear's 'In Review' status often has type='started', but it should
        map to TicketStatus.REVIEW, not IN_PROGRESS. This verifies that
        state.name is checked BEFORE state.type.
        """
        # "In Review" with type="started" - should map to REVIEW, not IN_PROGRESS
        assert provider._map_status("started", "In Review") == TicketStatus.REVIEW

        # Verify other review states also take priority
        assert provider._map_status("started", "Code Review") == TicketStatus.REVIEW
        assert provider._map_status("started", "Pending Review") == TicketStatus.REVIEW

    def test_state_type_fallback_when_name_unrecognized(self, provider):
        """When state.name is unrecognized, fall back to state.type."""
        # Custom state name with valid type should use type mapping
        assert provider._map_status("started", "Custom Work State") == TicketStatus.IN_PROGRESS
        assert provider._map_status("completed", "My Done State") == TicketStatus.DONE

    def test_unknown_status(self, provider):
        """Unknown state returns UNKNOWN when neither name nor type match."""
        assert provider._map_status("custom", "Custom State") == TicketStatus.UNKNOWN


class TestTypeMapping:
    """Test type mapping - defaults to FEATURE (not UNKNOWN)."""

    @pytest.mark.parametrize(
        "labels,expected",
        [
            (["bug"], TicketType.BUG),
            (["Bug Report"], TicketType.BUG),
            (["feature"], TicketType.FEATURE),
            (["enhancement"], TicketType.FEATURE),
            (["task"], TicketType.TASK),
            (["chore"], TicketType.TASK),
            (["tech-debt"], TicketType.MAINTENANCE),
            (["Infrastructure"], TicketType.MAINTENANCE),
        ],
    )
    def test_type_mapping_from_labels(self, provider, labels, expected):
        """Test type inference from labels."""
        assert provider._map_type(labels) == expected

    def test_default_type_is_feature(self, provider):
        """CRITICAL: Default type is FEATURE when no type keywords found.

        Per requirements, default ticket type must be TicketType.FEATURE
        (not UNKNOWN) when no type-specific labels are present.
        """
        # Empty labels -> FEATURE
        assert provider._map_type([]) == TicketType.FEATURE

        # Labels without type keywords -> FEATURE
        assert provider._map_type(["priority", "backend"]) == TicketType.FEATURE
        assert provider._map_type(["urgent", "q1"]) == TicketType.FEATURE
        assert provider._map_type(["team-a", "frontend"]) == TicketType.FEATURE

    def test_first_matching_label_wins(self, provider):
        """If multiple labels match, first one in list wins."""
        # "bug" matches before "feature"
        labels = ["bug", "feature"]
        assert provider._map_type(labels) == TicketType.BUG


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    def test_prompt_template_contains_placeholder(self, provider):
        """Prompt template contains required placeholders."""
        template = provider.get_prompt_template()

        assert "{ticket_id}" in template
        assert "identifier" in template
        assert "state" in template
        assert "labels" in template


class TestFetchTicketDeprecation:
    """Test fetch_ticket() deprecation warning."""

    def test_fetch_ticket_raises_deprecation_warning(self, provider):
        """fetch_ticket() should emit DeprecationWarning before raising."""
        with pytest.warns(DeprecationWarning, match="deprecated"):
            with pytest.raises(NotImplementedError):
                provider.fetch_ticket("ENG-123")

    def test_fetch_ticket_raises_not_implemented(self, provider):
        """fetch_ticket() should raise NotImplementedError."""
        # Suppress the warning to test the exception
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with pytest.raises(NotImplementedError, match="hybrid architecture"):
                provider.fetch_ticket("ENG-123")


class TestCheckConnectionDeprecation:
    """Test check_connection() deprecation warning."""

    def test_check_connection_raises_deprecation_warning(self, provider):
        """check_connection() should emit DeprecationWarning."""
        with pytest.warns(DeprecationWarning, match="deprecated"):
            success, message = provider.check_connection()
            assert success is True

    def test_check_connection_returns_ready(self, provider):
        """check_connection returns ready status (with deprecation warning)."""
        # Suppress the warning to test the return value
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            success, message = provider.check_connection()
            assert success is True
            assert "ready" in message.lower() or "LinearProvider" in message
