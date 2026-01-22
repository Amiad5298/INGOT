"""Tests for spec.integrations.providers.detector module.

Tests cover:
- PlatformPattern dataclass
- PLATFORM_PATTERNS configuration
- PlatformDetector.detect() for all platforms
- PlatformDetector.is_url() helper
- Edge cases and error handling
- Ambiguous inputs (e.g., PROJ-123 could be Jira or Linear)
"""

import pytest

from spec.integrations.providers.base import Platform
from spec.integrations.providers.detector import (
    PLATFORM_PATTERNS,
    PlatformDetector,
    PlatformPattern,
)
from spec.integrations.providers.exceptions import PlatformNotSupportedError


class TestPlatformPattern:
    """Tests for PlatformPattern dataclass."""

    def test_creation_with_platform_only(self):
        """Can create pattern with just platform."""
        pattern = PlatformPattern(platform=Platform.JIRA)
        assert pattern.platform == Platform.JIRA
        assert pattern.url_patterns == []
        assert pattern.id_patterns == []

    def test_creation_with_all_fields(self):
        """Can create pattern with all fields."""
        import re

        url_pattern = re.compile(r"https?://example\.com/(\d+)")
        id_pattern = re.compile(r"^TEST-(\d+)$")

        pattern = PlatformPattern(
            platform=Platform.GITHUB,
            url_patterns=[url_pattern],
            id_patterns=[id_pattern],
        )
        assert pattern.platform == Platform.GITHUB
        assert len(pattern.url_patterns) == 1
        assert len(pattern.id_patterns) == 1


class TestPlatformPatterns:
    """Tests for PLATFORM_PATTERNS configuration."""

    def test_contains_all_platforms(self):
        """PLATFORM_PATTERNS includes entries for all platforms."""
        platforms_in_patterns = {p.platform for p in PLATFORM_PATTERNS}
        expected_platforms = {
            Platform.JIRA,
            Platform.GITHUB,
            Platform.LINEAR,
            Platform.AZURE_DEVOPS,
            Platform.MONDAY,
            Platform.TRELLO,
        }
        assert platforms_in_patterns == expected_platforms

    def test_jira_has_url_patterns(self):
        """Jira pattern has URL patterns."""
        jira_pattern = next(p for p in PLATFORM_PATTERNS if p.platform == Platform.JIRA)
        assert len(jira_pattern.url_patterns) > 0

    def test_jira_has_id_patterns(self):
        """Jira pattern has ID patterns."""
        jira_pattern = next(p for p in PLATFORM_PATTERNS if p.platform == Platform.JIRA)
        assert len(jira_pattern.id_patterns) > 0

    def test_github_has_url_patterns(self):
        """GitHub pattern has URL patterns."""
        gh_pattern = next(p for p in PLATFORM_PATTERNS if p.platform == Platform.GITHUB)
        assert len(gh_pattern.url_patterns) >= 2  # issues and pull

    def test_monday_has_no_id_patterns(self):
        """Monday pattern has no ID patterns (requires URL context)."""
        monday_pattern = next(p for p in PLATFORM_PATTERNS if p.platform == Platform.MONDAY)
        assert len(monday_pattern.id_patterns) == 0


class TestPlatformDetectorIsUrl:
    """Tests for PlatformDetector.is_url()."""

    def test_http_url(self):
        """Recognizes http:// URLs."""
        assert PlatformDetector.is_url("http://example.com") is True

    def test_https_url(self):
        """Recognizes https:// URLs."""
        assert PlatformDetector.is_url("https://example.com") is True

    def test_non_url_id(self):
        """Returns False for non-URL inputs."""
        assert PlatformDetector.is_url("PROJ-123") is False

    def test_whitespace_stripped(self):
        """Strips whitespace before checking."""
        assert PlatformDetector.is_url("  https://example.com  ") is True

    def test_uppercase_scheme(self):
        """Case-insensitive scheme check (but input is unlikely uppercase)."""
        # Note: URLs are typically lowercase, but we strip and check prefix
        assert (
            PlatformDetector.is_url("HTTPS://example.com") is False
        )  # startswith is case-sensitive


class TestPlatformDetectorJira:
    """Tests for Jira URL and ID detection."""

    def test_atlassian_cloud_url(self):
        """Detects Atlassian Cloud Jira URLs."""
        platform, groups = PlatformDetector.detect("https://company.atlassian.net/browse/PROJ-123")
        assert platform == Platform.JIRA
        assert groups["ticket_id"] == "PROJ-123"

    def test_self_hosted_jira_url(self):
        """Detects self-hosted Jira URLs."""
        platform, groups = PlatformDetector.detect("https://jira.company.com/browse/ABC-456")
        assert platform == Platform.JIRA

    def test_generic_browse_url(self):
        """Detects generic /browse/ URLs."""
        platform, groups = PlatformDetector.detect("https://issues.example.org/browse/XYZ-789")
        assert platform == Platform.JIRA

    def test_jira_id_uppercase(self):
        """Detects uppercase Jira ticket IDs."""
        platform, groups = PlatformDetector.detect("PROJ-123")
        assert platform == Platform.JIRA

    def test_jira_id_lowercase(self):
        """Detects lowercase Jira ticket IDs (case insensitive)."""
        platform, groups = PlatformDetector.detect("proj-456")
        assert platform == Platform.JIRA

    def test_jira_id_mixed_case(self):
        """Detects mixed case Jira ticket IDs."""
        platform, groups = PlatformDetector.detect("PrOj-789")
        assert platform == Platform.JIRA

    def test_jira_id_long_project_key(self):
        """Detects Jira IDs with long project keys."""
        platform, groups = PlatformDetector.detect("MYPROJECT123-999")
        assert platform == Platform.JIRA

    def test_jira_id_single_letter_project(self):
        """Detects Jira IDs with single letter project key."""
        platform, groups = PlatformDetector.detect("A-1")
        assert platform == Platform.JIRA


class TestPlatformDetectorGitHub:
    """Tests for GitHub URL and ID detection."""

    def test_github_issue_url(self):
        """Detects GitHub issue URLs."""
        platform, groups = PlatformDetector.detect("https://github.com/owner/repo/issues/123")
        assert platform == Platform.GITHUB
        assert groups["owner"] == "owner"
        assert groups["repo"] == "repo"
        assert groups["number"] == "123"

    def test_github_pull_request_url(self):
        """Detects GitHub pull request URLs."""
        platform, groups = PlatformDetector.detect("https://github.com/myorg/myrepo/pull/456")
        assert platform == Platform.GITHUB
        assert groups["owner"] == "myorg"
        assert groups["repo"] == "myrepo"
        assert groups["number"] == "456"

    def test_github_short_reference(self):
        """Detects GitHub short references like owner/repo#123."""
        platform, groups = PlatformDetector.detect("octocat/Hello-World#42")
        assert platform == Platform.GITHUB
        assert groups["repo_ref"] == "octocat/Hello-World"
        assert groups["number"] == "42"

    def test_github_complex_repo_name(self):
        """Detects GitHub with complex repo names."""
        platform, groups = PlatformDetector.detect("my-org/my-repo-name#1234")
        assert platform == Platform.GITHUB


class TestPlatformDetectorLinear:
    """Tests for Linear URL detection."""

    def test_linear_issue_url(self):
        """Detects Linear issue URLs."""
        platform, groups = PlatformDetector.detect("https://linear.app/myteam/issue/TEAM-123")
        assert platform == Platform.LINEAR
        assert groups["team"] == "myteam"
        assert groups["ticket_id"] == "TEAM-123"

    def test_linear_url_lowercase_team(self):
        """Detects Linear URLs with lowercase team ID."""
        platform, groups = PlatformDetector.detect("https://linear.app/company/issue/ABC-456")
        assert platform == Platform.LINEAR

    def test_linear_id_falls_back_to_jira(self):
        """Linear ID format (TEAM-123) matches Jira first due to pattern order."""
        # This is expected behavior - TEAM-123 is ambiguous
        # URL detection should be used for Linear
        platform, groups = PlatformDetector.detect("TEAM-123")
        assert platform == Platform.JIRA  # Jira comes first in patterns


class TestPlatformDetectorAzureDevOps:
    """Tests for Azure DevOps URL and ID detection."""

    def test_azure_devops_url(self):
        """Detects Azure DevOps URLs."""
        platform, groups = PlatformDetector.detect(
            "https://dev.azure.com/myorg/myproject/_workitems/edit/12345"
        )
        assert platform == Platform.AZURE_DEVOPS
        assert groups["org"] == "myorg"
        assert groups["project"] == "myproject"
        assert groups["work_item_id"] == "12345"

    def test_visualstudio_url(self):
        """Detects Visual Studio online URLs."""
        platform, groups = PlatformDetector.detect(
            "https://myorg.visualstudio.com/myproject/_workitems/edit/67890"
        )
        assert platform == Platform.AZURE_DEVOPS

    def test_azure_boards_id(self):
        """Detects Azure Boards AB# format."""
        platform, groups = PlatformDetector.detect("AB#12345")
        assert platform == Platform.AZURE_DEVOPS
        assert groups["work_item_id"] == "12345"

    def test_azure_boards_id_lowercase(self):
        """Detects Azure Boards AB# format (case insensitive)."""
        platform, groups = PlatformDetector.detect("ab#99999")
        assert platform == Platform.AZURE_DEVOPS


class TestPlatformDetectorMonday:
    """Tests for Monday.com URL detection."""

    def test_monday_board_pulse_url(self):
        """Detects Monday.com board/pulse URLs."""
        platform, groups = PlatformDetector.detect(
            "https://view.monday.com/boards/123456/pulses/789012"
        )
        assert platform == Platform.MONDAY

    def test_monday_subdomain_url(self):
        """Detects Monday.com with company subdomain."""
        platform, groups = PlatformDetector.detect(
            "https://company.monday.com/boards/111/pulses/222"
        )
        assert platform == Platform.MONDAY


class TestPlatformDetectorTrello:
    """Tests for Trello URL and ID detection."""

    def test_trello_card_url(self):
        """Detects Trello card URLs."""
        platform, groups = PlatformDetector.detect("https://trello.com/c/abc12345")
        assert platform == Platform.TRELLO
        assert groups["card_id"] == "abc12345"

    def test_trello_card_url_with_name(self):
        """Detects Trello card URLs with card name."""
        platform, groups = PlatformDetector.detect("https://trello.com/c/xyz98765/card-title-here")
        assert platform == Platform.TRELLO
        assert groups["card_id"] == "xyz98765"

    def test_trello_short_id(self):
        """Detects Trello 8-character short IDs."""
        platform, groups = PlatformDetector.detect("abcd1234")
        assert platform == Platform.TRELLO
        assert groups["card_id"] == "abcd1234"

    def test_trello_short_id_uppercase(self):
        """Detects Trello short IDs (mixed case)."""
        platform, groups = PlatformDetector.detect("AbCd1234")
        assert platform == Platform.TRELLO


class TestPlatformDetectorEdgeCases:
    """Tests for edge cases and special inputs."""

    def test_whitespace_stripped(self):
        """Input whitespace is stripped before detection."""
        platform, groups = PlatformDetector.detect("  PROJ-123  ")
        assert platform == Platform.JIRA

    def test_newline_stripped(self):
        """Newlines are stripped from input."""
        platform, groups = PlatformDetector.detect("\nPROJ-123\n")
        assert platform == Platform.JIRA

    def test_tab_stripped(self):
        """Tabs are stripped from input."""
        platform, groups = PlatformDetector.detect("\tPROJ-123\t")
        assert platform == Platform.JIRA

    def test_http_url(self):
        """Detects http:// URLs (not just https)."""
        platform, groups = PlatformDetector.detect("http://company.atlassian.net/browse/PROJ-123")
        assert platform == Platform.JIRA

    def test_url_with_trailing_slash(self):
        """URLs with content after card ID still match."""
        platform, groups = PlatformDetector.detect("https://trello.com/c/abc12345/1-card-title")
        assert platform == Platform.TRELLO

    def test_github_url_with_query_params_not_matched(self):
        """GitHub URLs with query params may not match (pattern limitation)."""
        # This tests current behavior - patterns don't handle query params
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("https://github.com/owner/repo/issues?q=is:open")


class TestPlatformDetectorErrors:
    """Tests for error handling."""

    def test_unknown_url_raises_error(self):
        """Unknown URLs raise PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            PlatformDetector.detect("https://unknown-platform.com/ticket/123")
        assert "unknown-platform.com" in str(exc_info.value)

    def test_random_string_raises_error(self):
        """Random strings raise PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("not-a-valid-ticket-id")

    def test_empty_string_raises_error(self):
        """Empty strings raise PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("")

    def test_whitespace_only_raises_error(self):
        """Whitespace-only strings raise PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("   ")

    def test_error_includes_supported_platforms(self):
        """Error message includes list of supported platforms."""
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            PlatformDetector.detect("invalid-input")
        error = exc_info.value
        assert error.supported_platforms is not None
        assert len(error.supported_platforms) == 6  # All 6 platforms

    def test_error_includes_input_string(self):
        """Error includes the original input string."""
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            PlatformDetector.detect("my-invalid-input")
        error = exc_info.value
        assert error.input_str == "my-invalid-input"


class TestPlatformDetectorAmbiguousInputs:
    """Tests for ambiguous inputs that could match multiple platforms."""

    def test_project_id_format_matches_jira_first(self):
        """PROJECT-123 format matches Jira (first in pattern order)."""
        # This is an intentional design decision - Jira is more common
        platform, groups = PlatformDetector.detect("ABC-123")
        assert platform == Platform.JIRA

    def test_linear_url_preferred_over_id(self):
        """Linear URLs are unambiguous - use URLs for Linear."""
        platform, groups = PlatformDetector.detect("https://linear.app/team/issue/ABC-123")
        assert platform == Platform.LINEAR

    def test_eight_char_alphanumeric_matches_trello(self):
        """8-char alphanumeric strings match Trello."""
        # "ABCD1234" - 8 chars, could theoretically be something else
        platform, groups = PlatformDetector.detect("ABCD1234")
        assert platform == Platform.TRELLO

    def test_nine_char_alphanumeric_no_match(self):
        """9-char alphanumeric strings don't match Trello pattern."""
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("ABCDE1234")  # 9 chars

    def test_seven_char_alphanumeric_no_match(self):
        """7-char alphanumeric strings don't match Trello pattern."""
        with pytest.raises(PlatformNotSupportedError):
            PlatformDetector.detect("ABC1234")  # 7 chars


class TestPlatformDetectorImport:
    """Tests for module imports."""

    def test_import_from_providers(self):
        """Can import PlatformDetector from providers package."""
        from spec.integrations.providers import PlatformDetector as PD

        assert PD is PlatformDetector

    def test_import_platform_pattern_from_providers(self):
        """Can import PlatformPattern from providers package."""
        from spec.integrations.providers import PlatformPattern as PP

        assert PP is PlatformPattern

    def test_import_platform_patterns_from_providers(self):
        """Can import PLATFORM_PATTERNS from providers package."""
        from spec.integrations.providers import PLATFORM_PATTERNS as PP

        assert PP is PLATFORM_PATTERNS
