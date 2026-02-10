"""Tests for GitHubProvider in ingot.integrations.providers.github module.

Tests cover:
- Provider registration with ProviderRegistry
- can_handle() for URLs and ticket IDs
- parse_input() for URL and ID parsing
- normalize() for raw GitHub data conversion
- Status and type mapping
- get_prompt_template() and other methods
"""

import pytest

from ingot.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
)
from ingot.integrations.providers.github import (
    GitHubProvider,
)
from ingot.integrations.providers.registry import ProviderRegistry


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
    def test_provider_has_platform_attribute(self):
        assert hasattr(GitHubProvider, "PLATFORM")
        assert GitHubProvider.PLATFORM == Platform.GITHUB

    def test_provider_registers_successfully(self):
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(GitHubProvider)

        provider = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider is not None
        assert isinstance(provider, GitHubProvider)

    def test_singleton_pattern(self):
        # Manually register since the decorator ran at import time before clear()
        ProviderRegistry.register(GitHubProvider)

        provider1 = ProviderRegistry.get_provider(Platform.GITHUB)
        provider2 = ProviderRegistry.get_provider(Platform.GITHUB)
        assert provider1 is provider2


class TestGitHubProviderProperties:
    def test_platform_property(self, provider):
        assert provider.platform == Platform.GITHUB

    def test_name_property(self, provider):
        assert provider.name == "GitHub Issues"


class TestGitHubProviderCanHandle:
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
        assert provider.can_handle(url) is True

    # GitHub Enterprise URLs - should NOT be accepted without explicit configuration
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.mycompany.com/owner/repo/issues/99",
            "https://github.enterprise.corp/org/project/pull/42",
        ],
    )
    def test_can_handle_github_enterprise_urls_without_config(self, provider, url):
        assert provider.can_handle(url) is False

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
        assert provider.can_handle(input_str) is False


class TestGitHubEnterpriseWithConfig:
    @pytest.fixture
    def provider_with_ghe(self, monkeypatch):
        """Create a GitHubProvider with mocked GITHUB_BASE_URL."""
        monkeypatch.setenv("GITHUB_BASE_URL", "https://github.mycompany.com")
        return GitHubProvider()

    def test_can_handle_configured_enterprise_url(self, provider_with_ghe):
        url = "https://github.mycompany.com/owner/repo/issues/99"
        assert provider_with_ghe.can_handle(url) is True

    def test_can_handle_configured_enterprise_pr_url(self, provider_with_ghe):
        url = "https://github.mycompany.com/org/project/pull/42"
        assert provider_with_ghe.can_handle(url) is True

    def test_can_handle_github_com_with_enterprise_config(self, provider_with_ghe):
        url = "https://github.com/owner/repo/issues/123"
        assert provider_with_ghe.can_handle(url) is True

    def test_can_handle_wrong_enterprise_url(self, provider_with_ghe):
        url = "https://github.othercompany.com/owner/repo/issues/99"
        assert provider_with_ghe.can_handle(url) is False

    def test_parse_configured_enterprise_url(self, provider_with_ghe):
        url = "https://github.mycompany.com/org/project/issues/99"
        assert provider_with_ghe.parse_input(url) == "org/project#99"

    def test_parse_wrong_enterprise_url_raises(self, provider_with_ghe):
        url = "https://github.othercompany.com/org/project/issues/99"
        with pytest.raises(ValueError, match="not allowed"):
            provider_with_ghe.parse_input(url)

    def test_domain_not_allowed_error_is_reachable(self, provider_with_ghe):
        # URL has valid GitHub-like structure but host is not in allowed list
        url = "https://github.unauthorized.com/owner/repo/issues/42"
        with pytest.raises(ValueError) as exc_info:
            provider_with_ghe.parse_input(url)

        # Verify the error message mentions the specific disallowed domain
        assert "github.unauthorized.com" in str(exc_info.value)
        assert "not allowed" in str(exc_info.value)


class TestGitHubEnterpriseWithoutScheme:
    @pytest.fixture
    def provider_with_ghe_no_scheme(self, monkeypatch):
        """Create a GitHubProvider with GITHUB_BASE_URL set without scheme."""
        monkeypatch.setenv("GITHUB_BASE_URL", "github.mycompany.com")
        return GitHubProvider()

    def test_can_handle_enterprise_url_without_scheme_config(self, provider_with_ghe_no_scheme):
        url = "https://github.mycompany.com/owner/repo/issues/99"
        assert provider_with_ghe_no_scheme.can_handle(url) is True

    def test_parse_enterprise_url_without_scheme_config(self, provider_with_ghe_no_scheme):
        url = "https://github.mycompany.com/org/project/issues/42"
        assert provider_with_ghe_no_scheme.parse_input(url) == "org/project#42"

    def test_github_com_still_works_without_scheme_config(self, provider_with_ghe_no_scheme):
        url = "https://github.com/owner/repo/issues/123"
        assert provider_with_ghe_no_scheme.can_handle(url) is True
        assert provider_with_ghe_no_scheme.parse_input(url) == "owner/repo#123"

    @pytest.fixture
    def provider_with_ghe_trailing_slash(self, monkeypatch):
        """Create a GitHubProvider with GITHUB_BASE_URL with trailing slash."""
        monkeypatch.setenv("GITHUB_BASE_URL", "github.mycompany.com/")
        return GitHubProvider()

    def test_handles_trailing_slash_in_base_url(self, provider_with_ghe_trailing_slash):
        url = "https://github.mycompany.com/owner/repo/issues/99"
        assert provider_with_ghe_trailing_slash.can_handle(url) is True

    @pytest.fixture
    def provider_with_ghe_whitespace(self, monkeypatch):
        """Create a GitHubProvider with GITHUB_BASE_URL with leading/trailing whitespace."""
        monkeypatch.setenv("GITHUB_BASE_URL", "  https://github.mycompany.com  ")
        return GitHubProvider()

    def test_handles_whitespace_in_base_url(self, provider_with_ghe_whitespace):
        url = "https://github.mycompany.com/owner/repo/issues/99"
        assert provider_with_ghe_whitespace.can_handle(url) is True

    def test_parse_with_whitespace_in_base_url(self, provider_with_ghe_whitespace):
        url = "https://github.mycompany.com/org/project/issues/42"
        assert provider_with_ghe_whitespace.parse_input(url) == "org/project#42"

    @pytest.fixture
    def provider_with_ghe_port(self, monkeypatch):
        """Create a GitHubProvider with GITHUB_BASE_URL containing a port."""
        monkeypatch.setenv("GITHUB_BASE_URL", "https://github.company.com:8443")
        return GitHubProvider()

    def test_handles_port_in_base_url_matches_url_without_port(self, provider_with_ghe_port):
        url = "https://github.company.com/owner/repo/issues/99"
        assert provider_with_ghe_port.can_handle(url) is True

    def test_handles_port_in_base_url_matches_url_with_different_port(self, provider_with_ghe_port):
        url = "https://github.company.com:9000/owner/repo/issues/99"
        assert provider_with_ghe_port.can_handle(url) is True

    def test_parse_with_port_in_base_url(self, provider_with_ghe_port):
        url = "https://github.company.com/org/project/issues/42"
        assert provider_with_ghe_port.parse_input(url) == "org/project#42"

    @pytest.fixture
    def provider_with_ghe_no_port(self, monkeypatch):
        """Create a GitHubProvider with GITHUB_BASE_URL without a port."""
        monkeypatch.setenv("GITHUB_BASE_URL", "https://github.company.com")
        return GitHubProvider()

    def test_config_without_port_matches_url_with_port(self, provider_with_ghe_no_port):
        url = "https://github.company.com:8443/owner/repo/issues/99"
        assert provider_with_ghe_no_port.can_handle(url) is True

    def test_parse_url_with_port_when_config_has_no_port(self, provider_with_ghe_no_port):
        url = "https://github.company.com:8443/org/project/issues/42"
        assert provider_with_ghe_no_port.parse_input(url) == "org/project#42"


class TestGitHubProviderParseInput:
    def test_parse_issue_url(self, provider):
        url = "https://github.com/octocat/Hello-World/issues/42"
        assert provider.parse_input(url) == "octocat/Hello-World#42"

    def test_parse_pr_url(self, provider):
        url = "https://github.com/owner/repo/pull/123"
        assert provider.parse_input(url) == "owner/repo#123"

    def test_parse_ghe_url_without_config_raises(self, provider):
        url = "https://github.company.com/org/project/issues/99"
        with pytest.raises(ValueError, match="not allowed"):
            provider.parse_input(url)

    def test_parse_short_ref(self, provider):
        assert provider.parse_input("owner/repo#123") == "owner/repo#123"

    def test_parse_with_whitespace(self, provider):
        assert provider.parse_input("  owner/repo#123  ") == "owner/repo#123"

    def test_parse_bare_number_with_defaults(self, provider_with_defaults):
        assert provider_with_defaults.parse_input("#123") == "myorg/myrepo#123"

    def test_parse_invalid_raises_valueerror(self, provider):
        with pytest.raises(ValueError, match="Cannot parse GitHub issue"):
            provider.parse_input("PROJ-123")  # Jira format

    def test_parse_bare_number_without_defaults_raises(self, provider):
        with pytest.raises(ValueError, match="Cannot parse GitHub issue"):
            provider.parse_input("#123")


class TestGitHubProviderNormalize:
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
        ticket = provider.normalize(sample_github_response)

        assert ticket.platform_metadata["repository"] == "octocat/Hello-World"
        assert ticket.platform_metadata["issue_number"] == 42
        assert ticket.platform_metadata["is_pull_request"] is False
        assert ticket.platform_metadata["milestone"] == "v1.0"
        assert ticket.platform_metadata["author"] == "reporter"

    def test_normalize_minimal_response(self, provider):
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
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "completed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE

    def test_normalize_closed_not_planned(self, provider, sample_github_response):
        sample_github_response["state"] = "closed"
        sample_github_response["state_reason"] = "not_planned"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.CLOSED

    def test_normalize_merged_pr(self, provider, sample_github_response):
        sample_github_response["pull_request"] = {"url": "..."}
        sample_github_response["merged_at"] = "2024-01-20T12:00:00Z"
        sample_github_response["state"] = "closed"
        ticket = provider.normalize(sample_github_response)
        assert ticket.status == TicketStatus.DONE
        assert ticket.platform_metadata["is_pull_request"] is True

    def test_normalize_without_repository_field(self, provider):
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
    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_normalize_with_none_labels(self, provider):
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
    @pytest.fixture
    def provider(self):
        return GitHubProvider()

    def test_prompt_template_contains_placeholder(self, provider):
        template = provider.get_prompt_template()
        assert "{ticket_id}" in template

    def test_prompt_template_is_structured(self, provider):
        template = provider.get_prompt_template()
        assert "JSON" in template or "json" in template.lower()
