"""Tests for GitHubProvider in spec.integrations.providers.github module.

Tests cover:
- Provider registration with ProviderRegistry
- can_handle() for URLs and ticket IDs
- parse_input() for URL and ID parsing
- normalize() for raw GitHub data conversion
- Status and type mapping
- get_prompt_template() and other methods
"""

import pytest

from spec.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.github import (
    GitHubProvider,
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
    """Create a fresh GitHubProvider instance."""
    return GitHubProvider()


@pytest.fixture
def provider_with_defaults():
    """Create a GitHubProvider with default owner/repo configured."""
    return GitHubProvider(default_owner="myorg", default_repo="myrepo")


class TestGitHubProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    def test_provider_has_platform_attribute(self):
        """GitHubProvider has required PLATFORM class attribute."""
        assert hasattr(GitHubProvider, "PLATFORM")
        assert GitHubProvider.PLATFORM == Platform.GITHUB

    def test_provider_registers_successfully(self):
        """GitHubProvider can be registered with ProviderRegistry."""
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(GitHubProvider)

        provider = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider is not None
        assert isinstance(provider, GitHubProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(GitHubProvider)

        provider1 = ProviderRegistry.get_provider(Platform.GITHUB)
        provider2 = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider1 is provider2


class TestGitHubProviderProperties:
    """Test provider properties."""

    def test_platform_property(self, provider):
        """platform property returns Platform.GITHUB."""
        assert provider.platform == Platform.GITHUB

    def test_name_property(self, provider):
        """name property returns 'GitHub Issues'."""
        assert provider.name == "GitHub Issues"


class TestGitHubProviderCanHandle:
    """Test can_handle() method."""

    # Valid GitHub.com URLs
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo/issues/123",
            "https://github.com/owner/repo/pull/456",
            "https://github.com/octocat/Hello-World/issues/42",
            "https://github.com/myorg/backend/pull/1234",
            "http://github.com/owner/repo/issues/1",
        ],
    )
    def test_can_handle_valid_github_urls(self, provider, url):
        """Provider recognizes valid GitHub.com URLs."""
        assert provider.can_handle(url) is True

    # GitHub Enterprise URLs
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.mycompany.com/owner/repo/issues/99",
            "https://github.enterprise.corp/org/project/pull/42",
        ],
    )
    def test_can_handle_github_enterprise_urls(self, provider, url):
        """Provider recognizes GitHub Enterprise URLs."""
        assert provider.can_handle(url) is True

    # Valid short references
    @pytest.mark.parametrize(
        "ref",
        [
            "owner/repo#123",
            "octocat/Hello-World#42",
            "myorg/backend#1",
            "OWNER/REPO#999",
            "o/r#1",
        ],
    )
    def test_can_handle_valid_short_refs(self, provider, ref):
        """Provider recognizes owner/repo#123 format."""
        assert provider.can_handle(ref) is True

    # Invalid inputs (should not be handled)
    @pytest.mark.parametrize(
        "input_str",
        [
            "https://company.atlassian.net/browse/PROJ-123",  # Jira
            "https://linear.app/team/issue/ENG-123",  # Linear
            "PROJ-123",  # Jira ID
            "ENG-123",  # Linear ID
            "#123",  # Bare number (no defaults configured)
            "123",  # Numeric only
            "",  # Empty
            "owner/repo/subdir#123",  # Invalid - extra path segment
        ],
    )
    def test_can_handle_invalid_inputs(self, provider, input_str):
        """Provider rejects non-GitHub inputs."""
        assert provider.can_handle(input_str) is False


class TestGitHubProviderParseInput:
    """Test parse_input() method."""

    def test_parse_issue_url(self, provider):
        """Parse GitHub issue URL."""
        url = "https://github.com/octocat/Hello-World/issues/42"
        assert provider.parse_input(url) == "octocat/Hello-World#42"

    def test_parse_pr_url(self, provider):
        """Parse GitHub PR URL."""
        url = "https://github.com/owner/repo/pull/123"
        assert provider.parse_input(url) == "owner/repo#123"

    def test_parse_ghe_url(self, provider):
        """Parse GitHub Enterprise URL."""
        url = "https://github.company.com/org/project/issues/99"
        assert provider.parse_input(url) == "org/project#99"

    def test_parse_short_ref(self, provider):
        """Parse short reference format."""
        assert provider.parse_input("owner/repo#123") == "owner/repo#123"

    def test_parse_with_whitespace(self, provider):
        """Parse input with leading/trailing whitespace."""
        assert provider.parse_input("  owner/repo#123  ") == "owner/repo#123"

    def test_parse_bare_number_with_defaults(self, provider_with_defaults):
        """Parse bare issue number when defaults configured."""
        assert provider_with_defaults.parse_input("#123") == "myorg/myrepo#123"

    def test_parse_invalid_raises_valueerror(self, provider):
        """Invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse GitHub issue"):
            provider.parse_input("PROJ-123")  # Jira format

    def test_parse_bare_number_without_defaults_raises(self, provider):
        """Bare number without defaults raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse GitHub issue"):
            provider.parse_input("#123")


class TestGitHubProviderNormalize:
    """Test normalize() method."""

    @pytest.fixture
    def sample_github_response(self):
        """Sample GitHub API response for testing."""
        return {
            "number": 42,
            "title": "Found a bug in login",
            "body": "When clicking login, nothing happens.",
            "state": "open",
            "state_reason": None,
            "html_url": "https://github.com/octocat/Hello-World/issues/42",
            "labels": [{"name": "bug"}, {"name": "priority: high"}],
            "assignee": {"login": "developer"},
            "assignees": [{"login": "developer"}, {"login": "reviewer"}],
            "user": {"login": "reporter"},
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-18T14:20:00Z",
            "closed_at": None,
            "repository": {"full_name": "octocat/Hello-World"},
            "pull_request": None,
            "milestone": {"title": "v1.0"},
            "merged_at": None,
        }

    def test_normalize_full_response(self, provider, sample_github_response):
        """Normalize complete GitHub response."""
        ticket = provider.normalize(sample_github_response)

        assert ticket.id == "octocat/Hello-World#42"
        assert ticket.platform == Platform.GITHUB
        assert ticket.url == "https://github.com/octocat/Hello-World/issues/42"
        assert ticket.title == "Found a bug in login"
        assert ticket.description == "When clicking login, nothing happens."
        assert ticket.status == TicketStatus.OPEN
        assert ticket.type == TicketType.BUG
        assert ticket.assignee == "developer"
        assert "bug" in ticket.labels
        assert "priority: high" in ticket.labels
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_platform_metadata(self, provider, sample_github_response):
        """Normalize populates platform_metadata correctly."""
        ticket = provider.normalize(sample_github_response)

        assert ticket.platform_metadata["repository"] == "octocat/Hello-World"
        assert ticket.platform_metadata["issue_number"] == 42
        assert ticket.platform_metadata["is_pull_request"] is False
        assert ticket.platform_metadata["milestone"] == "v1.0"
        assert ticket.platform_metadata["author"] == "reporter"

    def test_normalize_minimal_response(self, provider):
        """Normalize minimal GitHub response."""
        minimal = {
            "number": 1,
            "title": "Minimal issue",
            "html_url": "https://github.com/owner/repo/issues/1",
            "state": "open",
            "labels": [],
        }
        ticket = provider.normalize(minimal)

        assert ticket.id == "owner/repo#1"
        assert ticket.title == "Minimal issue"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.type == TicketType.UNKNOWN

    def test_normalize_closed_completed(self, provider, sample_github_response):
        """Closed issue with 'completed' reason maps to DONE."""
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "completed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE

    def test_normalize_closed_not_planned(self, provider, sample_github_response):
        """Closed issue with 'not_planned' reason maps to CLOSED."""
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "not_planned"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.CLOSED

    def test_normalize_merged_pr(self, provider, sample_github_response):
        """Merged PR maps to DONE status."""
        sample_github_response["pull_request"] = {"url": "..."}
        sample_github_response["merged_at"] = "2024-01-20T12:00:00Z"
        sample_github_response["state"] = "closed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE
        assert ticket.platform_metadata["is_pull_request"] is True

    def test_normalize_without_repository_field(self, provider):
        """Falls back to parsing html_url for repo info."""
        data = {
            "number": 42,
            "title": "Test",
            "html_url": "https://github.com/owner/repo/issues/42",
            "state": "open",
            "labels": [],
        }
        ticket = provider.normalize(data)
        assert ticket.id == "owner/repo#42"
        assert ticket.platform_metadata["repository"] == "owner/repo"


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_normalize_with_none_labels(self, provider):
        """Handle None labels gracefully."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": None,
        }
        ticket = provider.normalize(data)
        assert ticket.labels == []

    def test_normalize_with_none_assignee(self, provider):
        """Handle None assignee gracefully."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [],
            "assignee": None,
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_malformed_labels(self, provider):
        """Handle malformed labels gracefully."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [None, "invalid", {"name": "valid"}, {"name": ""}],
        }
        ticket = provider.normalize(data)
        assert ticket.labels == ["valid"]

    def test_normalize_with_none_body(self, provider):
        """Handle None body gracefully."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [],
            "body": None,
        }
        ticket = provider.normalize(data)
        assert ticket.description == ""

    def test_normalize_with_assignees_fallback(self, provider):
        """Use assignees array when assignee is None."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [],
            "assignee": None,
            "assignees": [{"login": "fallback_user"}],
        }
        ticket = provider.normalize(data)
        assert ticket.assignee == "fallback_user"


class TestStatusMapping:
    """Test status mapping coverage."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    @pytest.mark.parametrize(
        "state,state_reason,expected_status",
        [
            ("open", None, TicketStatus.OPEN),
            ("closed", "completed", TicketStatus.DONE),
            ("closed", "not_planned", TicketStatus.CLOSED),
            ("closed", None, TicketStatus.CLOSED),
        ],
    )
    def test_status_mapping_combinations(self, provider, state, state_reason, expected_status):
        """Test state and state_reason combinations."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": state,
            "state_reason": state_reason,
            "labels": [],
        }
        ticket = provider.normalize(data)
        assert ticket.status == expected_status

    @pytest.mark.parametrize(
        "label,expected_status",
        [
            ("in progress", TicketStatus.IN_PROGRESS),
            ("wip", TicketStatus.IN_PROGRESS),
            ("review", TicketStatus.REVIEW),
            ("needs review", TicketStatus.REVIEW),
            ("blocked", TicketStatus.BLOCKED),
        ],
    )
    def test_label_based_status_enhancement(self, provider, label, expected_status):
        """Test label-based status enhancement for open issues."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [{"name": label}],
        }
        ticket = provider.normalize(data)
        assert ticket.status == expected_status


class TestTypeMapping:
    """Test type mapping from labels."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    @pytest.mark.parametrize(
        "label,expected_type",
        [
            ("bug", TicketType.BUG),
            ("defect", TicketType.BUG),
            ("feature", TicketType.FEATURE),
            ("enhancement", TicketType.FEATURE),
            ("task", TicketType.TASK),
            ("chore", TicketType.TASK),
            ("maintenance", TicketType.MAINTENANCE),
            ("tech-debt", TicketType.MAINTENANCE),
            ("refactor", TicketType.MAINTENANCE),
        ],
    )
    def test_type_inference_from_labels(self, provider, label, expected_type):
        """Test type inference from labels."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [{"name": label}],
        }
        ticket = provider.normalize(data)
        assert ticket.type == expected_type

    def test_type_unknown_when_no_matching_labels(self, provider):
        """Type is UNKNOWN when no matching labels found."""
        data = {
            "number": 1,
            "title": "Test",
            "html_url": "https://github.com/o/r/issues/1",
            "state": "open",
            "labels": [{"name": "priority: high"}],
        }
        ticket = provider.normalize(data)
        assert ticket.type == TicketType.UNKNOWN


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_prompt_template_contains_placeholder(self, provider):
        """Prompt template contains {ticket_id} placeholder."""
        template = provider.get_prompt_template()
        assert "{ticket_id}" in template

    def test_prompt_template_is_structured(self, provider):
        """Prompt template includes structured output format."""
        template = provider.get_prompt_template()
        assert "JSON" in template or "json" in template.lower()


class TestFetchTicketDeprecation:
    """Test fetch_ticket() deprecation behavior."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_fetch_ticket_raises_not_implemented_error(self, provider):
        """fetch_ticket() raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            provider.fetch_ticket("owner/repo#123")
        assert "hybrid architecture" in str(exc_info.value).lower()

    def test_fetch_ticket_raises_deprecation_warning(self, provider):
        """fetch_ticket() raises DeprecationWarning."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                provider.fetch_ticket("owner/repo#123")
            except NotImplementedError:
                pass
            assert len(w) >= 1
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)


class TestCheckConnection:
    """Test check_connection() method."""

    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_check_connection_returns_tuple(self, provider):
        """check_connection() returns (bool, str) tuple."""
        result = provider.check_connection()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_check_connection_returns_ready(self, provider):
        """check_connection() returns success status."""
        success, message = provider.check_connection()
        assert success is True
        assert "ready" in message.lower()
