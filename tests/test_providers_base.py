"""Tests for ingot.integrations.providers.base module.

Tests cover:
- Platform, TicketStatus, TicketType enums
- GenericTicket dataclass properties and methods
- semantic_branch_prefix property
- branch_slug property
- safe_filename_stem property
- IssueTrackerProvider abstract methods
- Default generate_branch_summary implementation
- sanitize_for_branch_component helper function
"""

import re
from abc import ABC
from enum import Enum

import pytest

from ingot.integrations.providers.base import (
    GenericTicket,
    IssueTrackerProvider,
    Platform,
    TicketStatus,
    TicketType,
    sanitize_for_branch_component,
    sanitize_title_for_branch,
)


class TestSanitizeForBranchComponent:
    def test_lowercases_input(self):
        assert sanitize_for_branch_component("UPPERCASE") == "uppercase"

    def test_replaces_spaces_with_hyphens(self):
        assert sanitize_for_branch_component("hello world") == "hello-world"

    def test_replaces_special_chars_with_hyphens(self):
        result = sanitize_for_branch_component("test@#$%^&*()")
        assert "@" not in result
        assert "#" not in result
        # Should collapse to something like "test"
        assert result == "test"

    def test_collapses_multiple_hyphens(self):
        assert sanitize_for_branch_component("a---b") == "a-b"
        assert sanitize_for_branch_component("a - - - b") == "a-b"

    def test_strips_leading_trailing_hyphens(self):
        assert sanitize_for_branch_component("-test-") == "test"
        assert sanitize_for_branch_component("---test---") == "test"

    def test_handles_empty_string(self):
        assert sanitize_for_branch_component("") == ""

    def test_handles_only_special_chars(self):
        assert sanitize_for_branch_component("@#$%^&*()") == ""

    def test_preserves_numbers(self):
        assert sanitize_for_branch_component("test123") == "test123"

    def test_preserves_hyphens(self):
        assert sanitize_for_branch_component("test-value") == "test-value"

    def test_replaces_slashes_with_hyphens(self):
        assert sanitize_for_branch_component("owner/repo") == "owner-repo"

    def test_replaces_hash_with_hyphen(self):
        result = sanitize_for_branch_component("repo#123")
        assert "#" not in result
        assert result == "repo-123"

    def test_complex_github_id(self):
        result = sanitize_for_branch_component("my-org/my-repo#456")
        assert result == "my-org-my-repo-456"

    def test_unicode_replaced(self):
        result = sanitize_for_branch_component("test émoji 🎉")
        # All non-[a-z0-9-] replaced
        assert "é" not in result
        assert "🎉" not in result


class TestSanitizeTitleForBranch:
    def test_truncates_to_max_length(self):
        long_title = "a" * 100
        result = sanitize_title_for_branch(long_title, max_length=50)
        assert len(result) <= 50

    def test_sanitizes_after_truncation(self):
        result = sanitize_title_for_branch("Add New Feature", max_length=50)
        assert result == "add-new-feature"

    def test_default_max_length_is_50(self):
        long_title = "a" * 100
        result = sanitize_title_for_branch(long_title)
        assert len(result) <= 50


class TestPlatformEnum:
    def test_is_enum(self):
        assert issubclass(Platform, Enum)

    def test_has_jira(self):
        assert Platform.JIRA is not None

    def test_has_github(self):
        assert Platform.GITHUB is not None

    def test_has_linear(self):
        assert Platform.LINEAR is not None

    def test_has_azure_devops(self):
        assert Platform.AZURE_DEVOPS is not None

    def test_has_monday(self):
        assert Platform.MONDAY is not None

    def test_has_trello(self):
        assert Platform.TRELLO is not None

    def test_all_platforms(self):
        platforms = list(Platform)
        assert len(platforms) == 6

    def test_platform_values_are_auto(self):
        for platform in Platform:
            assert isinstance(platform.value, int)


class TestTicketStatusEnum:
    def test_is_enum(self):
        assert issubclass(TicketStatus, Enum)

    def test_has_open(self):
        assert TicketStatus.OPEN is not None

    def test_has_in_progress(self):
        assert TicketStatus.IN_PROGRESS is not None

    def test_has_review(self):
        assert TicketStatus.REVIEW is not None

    def test_has_done(self):
        assert TicketStatus.DONE is not None

    def test_has_closed(self):
        assert TicketStatus.CLOSED is not None

    def test_has_blocked(self):
        assert TicketStatus.BLOCKED is not None

    def test_has_unknown(self):
        assert TicketStatus.UNKNOWN is not None


class TestTicketTypeEnum:
    def test_is_enum(self):
        assert issubclass(TicketType, Enum)

    def test_has_feature(self):
        assert TicketType.FEATURE is not None

    def test_has_bug(self):
        assert TicketType.BUG is not None

    def test_has_task(self):
        assert TicketType.TASK is not None

    def test_has_maintenance(self):
        assert TicketType.MAINTENANCE is not None

    def test_has_unknown(self):
        assert TicketType.UNKNOWN is not None


class TestGenericTicketBasic:
    def test_creation_with_required_fields(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
        )
        assert ticket.id == "TEST-123"
        assert ticket.platform == Platform.JIRA
        assert ticket.url == "https://jira.example.com/TEST-123"

    def test_default_values(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.GITHUB,
            url="https://github.com/owner/repo/issues/1",
        )
        assert ticket.title == ""
        assert ticket.description == ""
        assert ticket.status == TicketStatus.UNKNOWN
        assert ticket.type == TicketType.UNKNOWN
        assert ticket.assignee is None
        assert ticket.labels == []
        assert ticket.platform_metadata == {}

    def test_full_ticket(self):
        ticket = GenericTicket(
            id="PROJ-456",
            platform=Platform.LINEAR,
            url="https://linear.app/issue/PROJ-456",
            title="Add feature",
            description="Long description",
            status=TicketStatus.IN_PROGRESS,
            type=TicketType.FEATURE,
            assignee="john.doe",
            labels=["frontend", "priority-high"],
            platform_metadata={"key": "value"},
        )
        assert ticket.description == "Long description"
        assert ticket.assignee == "john.doe"
        assert "frontend" in ticket.labels


class TestGenericTicketSemanticBranchPrefix:
    def test_feature_returns_feat(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.FEATURE,
        )
        assert ticket.semantic_branch_prefix == "feat"

    def test_bug_returns_fix(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.BUG,
        )
        assert ticket.semantic_branch_prefix == "fix"

    def test_task_returns_chore(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.TASK,
        )
        assert ticket.semantic_branch_prefix == "chore"

    def test_maintenance_returns_refactor(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.MAINTENANCE,
        )
        assert ticket.semantic_branch_prefix == "refactor"

    def test_unknown_returns_feature(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.UNKNOWN,
        )
        assert ticket.semantic_branch_prefix == "feature"


class TestGenericTicketBranchSlug:
    def test_basic_slug_with_summary(self):
        ticket = GenericTicket(
            id="PROJ-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-123",
            type=TicketType.FEATURE,
            branch_summary="add-user-login",
        )
        slug = ticket.branch_slug
        assert "proj-123" in slug.lower()
        assert "add-user-login" in slug.lower()
        # branch_slug should NOT contain prefix
        assert "/" not in slug

    def test_slug_is_lowercase(self):
        ticket = GenericTicket(
            id="TEST-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-1",
            type=TicketType.BUG,
            branch_summary="uppercase-fix",
        )
        slug = ticket.branch_slug
        assert "test-1" in slug  # ID is lowercased

    def test_slug_without_summary(self):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            type=TicketType.TASK,
        )
        slug = ticket.branch_slug
        # Should be id only (no prefix)
        assert slug == "t-1"

    def test_slug_includes_ticket_id(self):
        ticket = GenericTicket(
            id="ABC-999",
            platform=Platform.JIRA,
            url="https://jira.example.com/ABC-999",
            type=TicketType.FEATURE,
            branch_summary="feature-work",
        )
        slug = ticket.branch_slug
        assert "abc-999" in slug.lower()

    def test_slug_no_prefix_for_bug(self):
        ticket = GenericTicket(
            id="BUG-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/BUG-1",
            type=TicketType.BUG,
            branch_summary="critical-issue",
        )
        slug = ticket.branch_slug
        # Slug should NOT contain prefix - that's handled by caller
        assert "/" not in slug
        assert "bug-1" in slug

    def test_slug_no_prefix_for_task(self):
        ticket = GenericTicket(
            id="TASK-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/TASK-1",
            type=TicketType.TASK,
            branch_summary="cleanup-code",
        )
        slug = ticket.branch_slug
        assert "/" not in slug
        assert "task-1" in slug

    def test_slug_no_prefix_for_maintenance(self):
        ticket = GenericTicket(
            id="MAINT-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/MAINT-1",
            type=TicketType.MAINTENANCE,
            branch_summary="tech-debt",
        )
        slug = ticket.branch_slug
        assert "/" not in slug
        assert "maint-1" in slug

    def test_slug_no_prefix_for_unknown(self):
        ticket = GenericTicket(
            id="U-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/U-1",
            type=TicketType.UNKNOWN,
            branch_summary="something",
        )
        slug = ticket.branch_slug
        assert "/" not in slug
        assert "u-1" in slug


class TestGenericTicketBranchSlugEdgeCases:
    def test_github_style_id_with_slash(self):
        ticket = GenericTicket(
            id="owner/repo#42",
            platform=Platform.GITHUB,
            url="https://github.com/owner/repo/issues/42",
            type=TicketType.BUG,
            branch_summary="fix-bug",
        )
        slug = ticket.branch_slug
        # branch_slug should NOT contain any slashes
        assert "/" not in slug
        assert "#" not in slug
        assert "owner-repo-42" in slug.lower()

    def test_sanitizes_spaces_in_id(self):
        ticket = GenericTicket(
            id="PROJ 123",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-123",
            type=TicketType.FEATURE,
            branch_summary="test",
        )
        slug = ticket.branch_slug
        assert " " not in slug

    def test_sanitizes_colons_in_id(self):
        ticket = GenericTicket(
            id="PREFIX:123",
            platform=Platform.JIRA,
            url="https://jira.example.com/PREFIX-123",
            type=TicketType.TASK,
            branch_summary="work",
        )
        slug = ticket.branch_slug
        assert ":" not in slug

    def test_removes_double_dot_sequence(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="add..feature",
        )
        slug = ticket.branch_slug
        assert ".." not in slug

    def test_removes_at_brace_sequence(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="ref@{yesterday}",
        )
        slug = ticket.branch_slug
        assert "@{" not in slug

    def test_removes_trailing_slash(self):
        ticket = GenericTicket(
            id="TEST-123/",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
        )
        slug = ticket.branch_slug
        assert not slug.endswith("/")

    def test_removes_lock_suffix(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="config.lock",
        )
        slug = ticket.branch_slug
        assert not slug.endswith(".lock")

    def test_generates_summary_from_title_when_empty(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            title="Add User Authentication Feature",
            branch_summary="",  # Empty
        )
        slug = ticket.branch_slug
        assert "add" in slug.lower()
        assert "user" in slug.lower()
        assert "authentication" in slug.lower()

    def test_handles_empty_title_and_summary(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.TASK,
            title="",
            branch_summary="",
        )
        slug = ticket.branch_slug
        # branch_slug does NOT include prefix
        assert slug == "test-123"

    def test_sanitizes_special_characters_in_summary(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.BUG,
            branch_summary="fix: [critical] issue~1",
        )
        slug = ticket.branch_slug
        assert ":" not in slug
        assert "[" not in slug
        assert "]" not in slug
        assert "~" not in slug

    def test_collapses_consecutive_hyphens(self):
        ticket = GenericTicket(
            id="TEST---123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="some---feature",
        )
        slug = ticket.branch_slug
        assert "---" not in slug

    def test_output_is_entirely_lowercase(self):
        ticket = GenericTicket(
            id="UPPERCASE-ID",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="MixedCase-Summary",
        )
        slug = ticket.branch_slug
        assert slug == slug.lower()

    def test_output_contains_only_safe_characters(self):
        ticket = GenericTicket(
            id="PROJ@123",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-123",
            type=TicketType.FEATURE,
            branch_summary="feature! with [special] chars: test~1",
        )
        slug = ticket.branch_slug
        # Only a-z, 0-9, hyphens (NO forward slash in slug)
        assert re.match(r"^[a-z0-9-]+$", slug), f"Invalid slug: {slug}"

    def test_summary_with_spaces_and_punctuation(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.BUG,
            branch_summary="Fix the API endpoint (urgent)!",
        )
        slug = ticket.branch_slug
        assert " " not in slug
        assert "(" not in slug
        assert ")" not in slug
        assert "!" not in slug
        assert slug == slug.lower()
        # Verify structure (no prefix in slug)
        assert "/" not in slug
        assert "test-123" in slug

    def test_summary_with_unicode_characters(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary="Add émoji 🎉 support",
        )
        slug = ticket.branch_slug
        # Unicode should be replaced, result should be safe (no slash)
        assert re.match(r"^[a-z0-9-]+$", slug), f"Invalid slug: {slug}"

    def test_complex_github_style_id(self):
        ticket = GenericTicket(
            id="my-org/my-repo#456",
            platform=Platform.GITHUB,
            url="https://github.com/my-org/my-repo/issues/456",
            type=TicketType.BUG,
            branch_summary="fix-auth-issue",
        )
        slug = ticket.branch_slug
        # branch_slug should NOT contain any slashes or #
        assert "/" not in slug
        assert "#" not in slug
        # The ID portion should be sanitized to my-org-my-repo-456
        assert "my-org-my-repo-456" in slug.lower()

    def test_deterministic_output(self):
        ticket = GenericTicket(
            id="PROJ-999",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-999",
            type=TicketType.FEATURE,
            branch_summary="New Feature: Add SSO",
        )
        slug1 = ticket.branch_slug
        slug2 = ticket.branch_slug
        slug3 = ticket.branch_slug
        assert slug1 == slug2 == slug3

    def test_empty_branch_summary_uses_title(self):
        long_title = "A" * 60 + " Feature Title"
        ticket = GenericTicket(
            id="TEST-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-1",
            type=TicketType.FEATURE,
            title=long_title,
            branch_summary="",
        )
        slug = ticket.branch_slug
        # Should use title, truncated and sanitized
        assert "a" in slug  # From the A's in title

    def test_id_with_dots_handled(self):
        ticket = GenericTicket(
            id="proj.sub.123",
            platform=Platform.JIRA,
            url="https://jira.example.com/proj.sub.123",
            type=TicketType.TASK,
            branch_summary="task-work",
        )
        slug = ticket.branch_slug
        # Dots should be replaced
        assert ".." not in slug


class TestIssueTrackerProviderABC:
    def test_is_abstract_class(self):
        assert issubclass(IssueTrackerProvider, ABC)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            IssueTrackerProvider()

    def test_requires_platform_property(self):
        class IncompleteProv(IssueTrackerProvider):
            @property
            def name(self):
                return "Test"

            def can_handle(self, input_str):
                return False

            def parse_input(self, input_str):
                return None

            def normalize(self, raw_data, ticket_id=None):
                return None

        with pytest.raises(TypeError):
            IncompleteProv()

    def test_requires_name_property(self):
        class IncompleteProv(IssueTrackerProvider):
            @property
            def platform(self):
                return Platform.JIRA

            def can_handle(self, input_str):
                return False

            def parse_input(self, input_str):
                return None

            def normalize(self, raw_data, ticket_id=None):
                return None

        with pytest.raises(TypeError):
            IncompleteProv()

    def test_complete_implementation_works(self):
        class CompleteProv(IssueTrackerProvider):
            @property
            def platform(self):
                return Platform.JIRA

            @property
            def name(self):
                return "Test Provider"

            def can_handle(self, input_str):
                return input_str.startswith("TEST-")

            def parse_input(self, input_str):
                return input_str.upper()

            def normalize(self, raw_data, ticket_id=None):
                return GenericTicket(
                    id=raw_data.get("key", ticket_id or "TEST-1"),
                    platform=Platform.JIRA,
                    url=f"https://jira.example.com/{raw_data.get('key', ticket_id)}",
                    title=raw_data.get("summary", "Test ticket"),
                )

        provider = CompleteProv()
        assert provider.platform == Platform.JIRA
        assert provider.name == "Test Provider"
        assert provider.can_handle("TEST-123") is True
        assert provider.parse_input("test-1") == "TEST-1"
        # check_connection now returns default from ABC
        success, message = provider.check_connection()
        assert success is True


class TestIssueTrackerProviderGenerateBranchSummary:
    @pytest.fixture
    def provider(self):
        """Create a test provider with default implementation."""

        class TestProvider(IssueTrackerProvider):
            @property
            def platform(self):
                return Platform.JIRA

            @property
            def name(self):
                return "Test"

            def can_handle(self, input_str):
                return True

            def parse_input(self, input_str):
                return input_str

            def fetch_ticket(self, ticket_id):
                return GenericTicket(
                    id=ticket_id,
                    platform=Platform.JIRA,
                    url=f"https://jira.example.com/{ticket_id}",
                    title="Test",
                )

            def check_connection(self):
                return (True, "Connected")

            def normalize(self, raw_data, ticket_id=None):
                return GenericTicket(
                    id=raw_data.get("key", ticket_id or "TEST-1"),
                    platform=Platform.JIRA,
                    url=f"https://jira.example.com/{raw_data.get('key', ticket_id)}",
                    title=raw_data.get("summary", "Test"),
                )

        return TestProvider()

    def test_basic_summary(self, provider):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            title="Add user authentication",
        )
        summary = provider.generate_branch_summary(ticket)
        assert summary is not None
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_lowercase(self, provider):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            title="UPPERCASE Title Here",
        )
        summary = provider.generate_branch_summary(ticket)
        assert summary == summary.lower()

    def test_summary_replaces_spaces(self, provider):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            title="Multiple Words Here",
        )
        summary = provider.generate_branch_summary(ticket)
        assert " " not in summary
        assert "-" in summary

    def test_summary_removes_special_chars(self, provider):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            title="Fix: issue [critical]!",
        )
        summary = provider.generate_branch_summary(ticket)
        assert ":" not in summary
        assert "[" not in summary
        assert "]" not in summary
        assert "!" not in summary

    def test_summary_truncates_long_titles(self, provider):
        ticket = GenericTicket(
            id="T-1",
            platform=Platform.JIRA,
            url="https://jira.example.com/T-1",
            title="This is a very long title " * 10,
        )
        summary = provider.generate_branch_summary(ticket)
        assert len(summary) < 60


class TestIssueTrackerProviderMethodSignatures:
    @pytest.fixture
    def provider_class(self):
        """Return the abstract provider class."""
        return IssueTrackerProvider

    def test_can_handle_takes_string(self, provider_class):
        import inspect

        sig = inspect.signature(provider_class.can_handle)
        params = list(sig.parameters.keys())
        assert "input_str" in params

    def test_parse_input_takes_string(self, provider_class):
        import inspect

        sig = inspect.signature(provider_class.parse_input)
        params = list(sig.parameters.keys())
        assert "input_str" in params


class TestProviderPlatformAttribute:
    """Tests for provider PLATFORM class attribute requirement.

    These tests verify that providers correctly declare the PLATFORM
    class attribute, which is required for ProviderRegistry.register()
    to work without instantiating provider classes.
    """

    def test_provider_with_platform_attribute(self):
        class MockProvider(IssueTrackerProvider):
            PLATFORM = Platform.JIRA  # Class attribute

            @property
            def platform(self):
                return Platform.JIRA

            @property
            def name(self):
                return "Jira"

            def can_handle(self, input_str):
                return False

            def parse_input(self, input_str):
                return input_str

            def fetch_ticket(self, ticket_id):
                return None

            def check_connection(self):
                return (True, "OK")

        # PLATFORM should be accessible on the class without instantiation
        assert hasattr(MockProvider, "PLATFORM")
        assert MockProvider.PLATFORM == Platform.JIRA

    def test_platform_attribute_accessible_without_instantiation(self):
        class MockProvider(IssueTrackerProvider):
            PLATFORM = Platform.GITHUB

            def __init__(self):
                # This should NOT be called during registration
                raise RuntimeError("__init__ should not be called during registration!")

            @property
            def platform(self):
                return Platform.GITHUB

            @property
            def name(self):
                return "GitHub"

            def can_handle(self, input_str):
                return False

            def parse_input(self, input_str):
                return input_str

            def fetch_ticket(self, ticket_id):
                return None

            def check_connection(self):
                return (True, "OK")

        # Accessing PLATFORM should NOT trigger __init__
        platform = MockProvider.PLATFORM
        assert platform == Platform.GITHUB

    def test_registry_compatible_provider_pattern(self):
        init_called = False

        class RegistryCompatibleProvider(IssueTrackerProvider):
            PLATFORM = Platform.LINEAR  # Required class attribute

            def __init__(self):
                nonlocal init_called
                init_called = True
                # Initialization code that should only run when
                # actually using the provider, not during registration
                self._api_token = None

            @property
            def platform(self):
                return self.PLATFORM  # Can reference class attr

            @property
            def name(self):
                return "Linear"

            def can_handle(self, input_str):
                return False

            def parse_input(self, input_str):
                return input_str

            def fetch_ticket(self, ticket_id):
                return None

            def check_connection(self):
                return (True, "OK")

        # Simulating what ProviderRegistry.register() should do:
        # Access PLATFORM without instantiation
        if hasattr(RegistryCompatibleProvider, "PLATFORM"):
            platform = RegistryCompatibleProvider.PLATFORM
        else:
            raise TypeError("Provider must declare PLATFORM class attribute")

        assert platform == Platform.LINEAR
        assert not init_called, "Provider should not be instantiated during registration"


class TestGenericTicketBranchSlugFallback:
    """Tests for GenericTicket.branch_slug empty ID fallback.

    These tests verify that when the ticket ID sanitizes to empty,
    a deterministic fallback ID is used.
    """

    def test_emoji_only_id_uses_fallback(self):
        ticket = GenericTicket(
            id="🎉🎉🎉",
            platform=Platform.JIRA,
            url="https://jira.example.com/emoji",
            type=TicketType.FEATURE,
        )
        slug = ticket.branch_slug

        # branch_slug should NOT have prefix
        assert "/" not in slug
        assert "ticket-" in slug
        # Should be deterministic
        assert ticket.branch_slug == slug
        # Verify fallback ID format (ticket-<6-char-hash>)
        assert slug.startswith("ticket-")
        # Hash should be 6 hex chars
        hash_part = slug.split("-")[1]
        assert len(hash_part) == 6
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_special_chars_only_id_uses_fallback(self):
        ticket = GenericTicket(
            id="@#$%^&*()",
            platform=Platform.JIRA,
            url="https://jira.example.com/special",
            type=TicketType.BUG,
        )
        slug = ticket.branch_slug

        # branch_slug should NOT have prefix
        assert "/" not in slug
        assert "ticket-" in slug
        # Should match allowed pattern (no prefix)
        assert re.match(r"^ticket-[a-f0-9]{6}$", slug)

    def test_fallback_id_is_deterministic(self):
        id_value = "🚀🔥💯"

        ticket1 = GenericTicket(
            id=id_value,
            platform=Platform.JIRA,
            url="https://jira.example.com/1",
            type=TicketType.TASK,
        )
        ticket2 = GenericTicket(
            id=id_value,
            platform=Platform.JIRA,
            url="https://jira.example.com/2",
            type=TicketType.TASK,
        )

        assert ticket1.branch_slug == ticket2.branch_slug

    def test_different_emoji_ids_produce_different_fallbacks(self):
        ticket1 = GenericTicket(
            id="🎉",
            platform=Platform.JIRA,
            url="https://jira.example.com/1",
            type=TicketType.FEATURE,
        )
        ticket2 = GenericTicket(
            id="🚀",
            platform=Platform.JIRA,
            url="https://jira.example.com/2",
            type=TicketType.FEATURE,
        )

        assert ticket1.branch_slug != ticket2.branch_slug

    def test_fallback_with_branch_summary(self):
        ticket = GenericTicket(
            id="🎉🎉",
            platform=Platform.JIRA,
            url="https://jira.example.com/emoji",
            type=TicketType.FEATURE,
            branch_summary="add-feature",
        )
        slug = ticket.branch_slug

        # branch_slug should NOT have prefix
        assert "/" not in slug
        assert "ticket-" in slug
        assert "add-feature" in slug


class TestGenericTicketBranchSlugLongSummary:
    """Tests for GenericTicket.branch_slug with long summaries.

    These tests verify that long branch_summary values are truncated
    and don't produce trailing hyphens.
    """

    def test_long_branch_summary_truncated(self):
        long_summary = "a" * 200  # Way longer than 50 chars
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.FEATURE,
            branch_summary=long_summary,
        )
        slug = ticket.branch_slug

        # Slug should be reasonable length (id (8) + "-" + summary (max 50) = ~59 max)
        assert len(slug) <= 65
        # Should contain truncated summary (no prefix in slug)
        assert slug.startswith("test-123-")

    def test_long_summary_with_special_chars_truncated_cleanly(self):
        # Create a long summary that would have hyphens at truncation point
        long_summary = "fix-bug-" * 30  # Lots of hyphens
        ticket = GenericTicket(
            id="TEST-456",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-456",
            type=TicketType.BUG,
            branch_summary=long_summary,
        )
        slug = ticket.branch_slug

        # Should not end with hyphen
        assert not slug.endswith("-")

    def test_long_summary_500_chars(self):
        # Create 500 char mixed summary
        long_summary = "this-is-a-very-long-summary-" * 20
        ticket = GenericTicket(
            id="PROJ-789",
            platform=Platform.JIRA,
            url="https://jira.example.com/PROJ-789",
            type=TicketType.TASK,
            branch_summary=long_summary,
        )
        slug = ticket.branch_slug

        # Verify reasonable length (no prefix in slug)
        assert len(slug) <= 65
        # Verify no trailing hyphen
        assert not slug.endswith("-")
        # Verify matches allowed pattern (no slash in slug)
        assert re.match(r"^[a-z0-9-]+$", slug)

    def test_long_summary_unicode_truncation(self):
        # Mix of unicode and ASCII
        long_summary = "feature-with-émojis-🎉-" * 20
        ticket = GenericTicket(
            id="TEST-001",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-001",
            type=TicketType.FEATURE,
            branch_summary=long_summary,
        )
        slug = ticket.branch_slug

        # Should be truncated and safe
        assert len(slug) <= 65
        # Should not contain unicode (no slash in slug)
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug)


class TestGenericTicketBranchSlugNoMalformed:
    """Tests ensuring branch_slug never produces malformed slugs.

    These tests verify that the slug always has proper structure:
    - Never empty
    - Always has ticket ID component
    - Proper format: id or id-summary
    """

    def test_never_returns_empty(self):
        # Even with empty everything, should have fallback ID
        ticket = GenericTicket(
            id="🎉",  # Will sanitize to empty
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
            type=TicketType.FEATURE,
            title="",
            branch_summary="",
        )
        slug = ticket.branch_slug

        # Should not be empty
        assert slug != ""
        assert len(slug) > 0
        # Should have fallback ID
        assert "ticket-" in slug

    def test_never_returns_just_hyphen(self):
        # ID that sanitizes to empty, summary that sanitizes to empty
        ticket = GenericTicket(
            id="@#$",
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
            type=TicketType.BUG,
            branch_summary="!@#$%",  # Will sanitize to empty
        )
        slug = ticket.branch_slug

        # Should not have patterns like leading/trailing hyphens
        assert not slug.startswith("-")
        assert not slug.endswith("-")
        # Should have format ticket-hash-unnamed-ticket
        # (because branch_summary had content that sanitized to empty)
        assert re.match(r"^ticket-[a-f0-9]{6}-unnamed-ticket$", slug)

    def test_all_ticket_types_produce_valid_slugs(self):
        for ticket_type in TicketType:
            ticket = GenericTicket(
                id="🔥",  # Will need fallback
                platform=Platform.JIRA,
                url="https://jira.example.com/test",
                type=ticket_type,
            )
            slug = ticket.branch_slug

            # Should have valid format (no slash in slug)
            assert "/" not in slug
            assert len(slug) > 0

            # Should contain only valid chars
            assert re.match(r"^[a-z0-9-]+$", slug)

    def test_empty_id_with_title_fallback(self):
        ticket = GenericTicket(
            id="🎉",  # Will sanitize to empty
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
            type=TicketType.FEATURE,
            title="Add user login feature",
        )
        slug = ticket.branch_slug

        # Should have fallback ID (no prefix in slug)
        assert "/" not in slug
        assert "ticket-" in slug
        # Should include title-derived summary
        assert "add" in slug or "user" in slug or "login" in slug

    def test_whitespace_only_branch_summary_handled(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            type=TicketType.TASK,
            branch_summary="   \t\n   ",  # Whitespace only
        )
        slug = ticket.branch_slug

        # Should work without summary (no prefix in slug)
        assert slug.startswith("test-123")
        # Should not have trailing hyphen
        assert not slug.endswith("-")


class TestGenericTicketSafeFilenameStem:
    """Tests for GenericTicket.safe_filename_stem property.

    These tests verify that the safe_filename_stem property:
    - Handles Windows reserved names by prepending 'ticket_'
    - Strips trailing dots and spaces
    - Truncates to 64 characters max
    - Sanitizes unsafe filesystem characters
    """

    def test_basic_stem(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
        )
        assert ticket.safe_filename_stem == "TEST-123"

    def test_github_style_id(self):
        ticket = GenericTicket(
            id="owner/repo#42",
            platform=Platform.GITHUB,
            url="https://github.com/owner/repo/issues/42",
        )
        stem = ticket.safe_filename_stem
        assert "/" not in stem
        assert "#" not in stem
        assert stem == "owner_repo_42"

    def test_windows_reserved_name_con(self):
        ticket = GenericTicket(
            id="CON",
            platform=Platform.JIRA,
            url="https://jira.example.com/CON",
        )
        assert ticket.safe_filename_stem == "ticket_CON"

    def test_windows_reserved_name_prn(self):
        ticket = GenericTicket(
            id="PRN",
            platform=Platform.JIRA,
            url="https://jira.example.com/PRN",
        )
        assert ticket.safe_filename_stem == "ticket_PRN"

    def test_windows_reserved_name_aux(self):
        ticket = GenericTicket(
            id="AUX",
            platform=Platform.JIRA,
            url="https://jira.example.com/AUX",
        )
        assert ticket.safe_filename_stem == "ticket_AUX"

    def test_windows_reserved_name_nul(self):
        ticket = GenericTicket(
            id="NUL",
            platform=Platform.JIRA,
            url="https://jira.example.com/NUL",
        )
        assert ticket.safe_filename_stem == "ticket_NUL"

    def test_windows_reserved_name_com1(self):
        ticket = GenericTicket(
            id="COM1",
            platform=Platform.JIRA,
            url="https://jira.example.com/COM1",
        )
        assert ticket.safe_filename_stem == "ticket_COM1"

    def test_windows_reserved_name_lpt9(self):
        ticket = GenericTicket(
            id="LPT9",
            platform=Platform.JIRA,
            url="https://jira.example.com/LPT9",
        )
        assert ticket.safe_filename_stem == "ticket_LPT9"

    def test_windows_reserved_name_case_insensitive(self):
        ticket = GenericTicket(
            id="con",
            platform=Platform.JIRA,
            url="https://jira.example.com/con",
        )
        assert ticket.safe_filename_stem == "ticket_con"

    def test_trailing_dot_stripped(self):
        ticket = GenericTicket(
            id="TEST-123...",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
        )
        stem = ticket.safe_filename_stem
        assert not stem.endswith(".")

    def test_trailing_space_stripped(self):
        ticket = GenericTicket(
            id="TEST-123   ",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
        )
        stem = ticket.safe_filename_stem
        assert not stem.endswith(" ")

    def test_long_id_truncated(self):
        long_id = "A" * 100
        ticket = GenericTicket(
            id=long_id,
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        stem = ticket.safe_filename_stem
        assert len(stem) <= 64

    def test_truncation_preserves_content(self):
        long_id = "X" * 64 + "Y" * 36
        ticket = GenericTicket(
            id=long_id,
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        stem = ticket.safe_filename_stem
        assert len(stem) == 64
        assert all(c == "X" for c in stem)

    def test_truncation_cleans_trailing_underscore(self):
        # Create ID that would have underscore at position 64
        id_with_special = "A" * 63 + "/" + "B" * 10
        ticket = GenericTicket(
            id=id_with_special,
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        stem = ticket.safe_filename_stem
        assert len(stem) <= 64
        assert not stem.endswith("_")

    def test_empty_id_returns_fallback(self):
        ticket = GenericTicket(
            id="",
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        assert ticket.safe_filename_stem == "unknown-ticket"

    def test_special_chars_only_returns_fallback(self):
        ticket = GenericTicket(
            id="///###",
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        assert ticket.safe_filename_stem == "unknown-ticket"

    def test_unsafe_chars_replaced(self):
        ticket = GenericTicket(
            id='TEST:*?"<>|123',
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
        )
        stem = ticket.safe_filename_stem
        assert ":" not in stem
        assert "*" not in stem
        assert "?" not in stem
        assert '"' not in stem
        assert "<" not in stem
        assert ">" not in stem
        assert "|" not in stem

    def test_leading_trailing_dots_spaces_underscores_stripped(self):
        ticket = GenericTicket(
            id=".. test__id ..",
            platform=Platform.JIRA,
            url="https://jira.example.com/test",
        )
        # Leading '..' stripped, spaces become underscores then outer ones stripped,
        # '__' collapsed to '_', trailing '..' stripped
        assert ticket.safe_filename_stem == "test_id"


class TestGenericTicketSerialization:
    """Tests for GenericTicket.to_dict() and from_dict() methods.

    P1 Fix Tests: These tests verify that platform_metadata normalization
    handles non-JSON-serializable types correctly.
    """

    def test_to_dict_basic_roundtrip(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            title="Test Ticket",
            status=TicketStatus.IN_PROGRESS,
            type=TicketType.FEATURE,
        )
        data = ticket.to_dict()
        restored = GenericTicket.from_dict(data)

        assert restored.id == ticket.id
        assert restored.platform == ticket.platform
        assert restored.title == ticket.title
        assert restored.status == ticket.status
        assert restored.type == ticket.type

    def test_to_dict_normalizes_datetime_in_metadata(self):
        from datetime import UTC, datetime

        test_dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            platform_metadata={"created": test_dt, "updated": test_dt},
        )
        data = ticket.to_dict()

        # datetime should be converted to ISO string
        assert isinstance(data["platform_metadata"]["created"], str)
        assert "2024-01-15" in data["platform_metadata"]["created"]
        assert "10:30:00" in data["platform_metadata"]["created"]

    def test_to_dict_normalizes_set_in_metadata(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            platform_metadata={"tags": {"beta", "alpha", "gamma"}},
        )
        data = ticket.to_dict()

        # set should be converted to sorted list
        assert isinstance(data["platform_metadata"]["tags"], list)
        assert data["platform_metadata"]["tags"] == ["alpha", "beta", "gamma"]

    def test_to_dict_normalizes_enum_in_metadata(self):
        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            platform_metadata={"status": TicketStatus.IN_PROGRESS},
        )
        data = ticket.to_dict()

        # Enum should be converted to its value
        assert data["platform_metadata"]["status"] == "in_progress"

    def test_to_dict_normalizes_custom_object_in_metadata(self):
        class CustomClass:
            def __repr__(self):
                return "CustomClass()"

        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            platform_metadata={"custom": CustomClass()},
        )
        data = ticket.to_dict()

        # Custom object should be converted to marked dict
        custom_data = data["platform_metadata"]["custom"]
        assert custom_data["__non_serializable__"] is True
        assert custom_data["type"] == "CustomClass"
        assert "CustomClass()" in custom_data["repr"]

    def test_to_dict_normalizes_nested_metadata(self):
        from datetime import UTC, datetime

        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.JIRA,
            url="https://jira.example.com/TEST-123",
            platform_metadata={
                "nested": {
                    "tags": {"a", "b"},
                    "timestamp": datetime(2024, 1, 1, tzinfo=UTC),
                },
                "list_of_sets": [{"x", "y"}, {"z"}],
            },
        )
        data = ticket.to_dict()

        # Check nested dict
        assert data["platform_metadata"]["nested"]["tags"] == ["a", "b"]
        assert "2024-01-01" in data["platform_metadata"]["nested"]["timestamp"]

        # Check list of sets
        assert data["platform_metadata"]["list_of_sets"][0] == ["x", "y"]
        assert data["platform_metadata"]["list_of_sets"][1] == ["z"]


class TestGenericTicketFromDictPlatformCasing:
    """Tests for platform casing normalization in GenericTicket.from_dict().

    P1 Fix Tests: These tests verify case-insensitive platform parsing.
    """

    def test_from_dict_accepts_uppercase_platform(self):
        data = {
            "id": "TEST-123",
            "platform": "JIRA",
            "url": "https://jira.example.com/TEST-123",
        }
        ticket = GenericTicket.from_dict(data)
        assert ticket.platform == Platform.JIRA

    def test_from_dict_accepts_lowercase_platform(self):
        data = {
            "id": "TEST-123",
            "platform": "jira",
            "url": "https://jira.example.com/TEST-123",
        }
        ticket = GenericTicket.from_dict(data)
        assert ticket.platform == Platform.JIRA

    def test_from_dict_accepts_mixed_case_platform(self):
        data = {
            "id": "TEST-123",
            "platform": "Jira",
            "url": "https://jira.example.com/TEST-123",
        }
        ticket = GenericTicket.from_dict(data)
        assert ticket.platform == Platform.JIRA

    def test_from_dict_rejects_unknown_platform(self):
        data = {
            "id": "TEST-123",
            "platform": "unknown_platform",
            "url": "https://example.com/TEST-123",
        }
        with pytest.raises(ValueError) as exc_info:
            GenericTicket.from_dict(data)
        assert "Unknown platform" in str(exc_info.value)

    def test_from_dict_all_platforms_case_insensitive(self):
        platforms = ["GITHUB", "github", "GitHub", "LINEAR", "linear", "Linear"]

        for platform_str in platforms:
            data = {
                "id": "TEST-123",
                "platform": platform_str,
                "url": "https://example.com/TEST-123",
            }
            ticket = GenericTicket.from_dict(data)
            assert ticket.platform.name == platform_str.upper()
