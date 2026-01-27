"""Tests for AzureDevOpsProvider in spec.integrations.providers.azure_devops module.

Tests cover:
- Provider registration with ProviderRegistry
- can_handle() for URLs and ticket IDs
- parse_input() for URL and ID parsing
- normalize() for raw Azure DevOps data conversion
- Status and type mapping
- HTML stripping for descriptions
- get_prompt_template() returns empty string (no Auggie MCP)
"""

import pytest

from spec.integrations.providers.azure_devops import (
    AzureDevOpsProvider,
    strip_html,
)
from spec.integrations.providers.base import (
    Platform,
    TicketStatus,
    TicketType,
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
    """Create a fresh AzureDevOpsProvider instance."""
    return AzureDevOpsProvider()


class TestAzureDevOpsProviderRegistration:
    """Test provider registration with ProviderRegistry."""

    def test_provider_has_platform_attribute(self):
        """AzureDevOpsProvider has required PLATFORM class attribute."""
        assert hasattr(AzureDevOpsProvider, "PLATFORM")
        assert AzureDevOpsProvider.PLATFORM == Platform.AZURE_DEVOPS

    def test_provider_registers_successfully(self):
        """AzureDevOpsProvider can be registered with ProviderRegistry."""
        ProviderRegistry.register(AzureDevOpsProvider)
        provider = ProviderRegistry.get_provider(Platform.AZURE_DEVOPS)
        assert provider is not None
        assert isinstance(provider, AzureDevOpsProvider)

    def test_singleton_pattern(self):
        """Same instance returned for multiple get_provider calls."""
        ProviderRegistry.register(AzureDevOpsProvider)
        provider1 = ProviderRegistry.get_provider(Platform.AZURE_DEVOPS)
        provider2 = ProviderRegistry.get_provider(Platform.AZURE_DEVOPS)
        assert provider1 is provider2


class TestAzureDevOpsProviderProperties:
    """Test provider properties."""

    def test_platform_property(self, provider):
        """platform property returns Platform.AZURE_DEVOPS."""
        assert provider.platform == Platform.AZURE_DEVOPS

    def test_name_property(self, provider):
        """name property returns 'Azure DevOps'."""
        assert provider.name == "Azure DevOps"


class TestAzureDevOpsProviderCanHandle:
    """Test can_handle() method."""

    def test_can_handle_dev_azure_url(self, provider):
        """Recognizes dev.azure.com URLs."""
        assert provider.can_handle("https://dev.azure.com/myorg/MyProject/_workitems/edit/42")
        assert provider.can_handle("http://dev.azure.com/contoso/Backend/_workitems/edit/123")

    def test_can_handle_visualstudio_url(self, provider):
        """Recognizes visualstudio.com URLs."""
        assert provider.can_handle("https://myorg.visualstudio.com/MyProject/_workitems/edit/42")
        assert provider.can_handle("http://contoso.visualstudio.com/Backend/_workitems/edit/123")

    def test_can_handle_ab_format(self, provider):
        """Recognizes AB#123 format."""
        assert provider.can_handle("AB#42")
        assert provider.can_handle("ab#123")  # case insensitive

    def test_cannot_handle_github_url(self, provider):
        """Does not recognize GitHub URLs."""
        assert not provider.can_handle("https://github.com/owner/repo/issues/1")

    def test_cannot_handle_jira_url(self, provider):
        """Does not recognize Jira URLs."""
        assert not provider.can_handle("https://company.atlassian.net/browse/PROJ-123")

    def test_cannot_handle_random_text(self, provider):
        """Does not recognize random text."""
        assert not provider.can_handle("not-a-ticket")
        assert not provider.can_handle("123")


class TestAzureDevOpsProviderParseInput:
    """Test parse_input() method."""

    def test_parse_dev_azure_url(self, provider):
        """Parses dev.azure.com URL to org/project#id format."""
        result = provider.parse_input("https://dev.azure.com/contoso/Backend/_workitems/edit/42")
        assert result == "contoso/Backend#42"

    def test_parse_visualstudio_url(self, provider):
        """Parses visualstudio.com URL to org/project#id format."""
        result = provider.parse_input(
            "https://myorg.visualstudio.com/MyProject/_workitems/edit/123"
        )
        assert result == "myorg/MyProject#123"

    def test_parse_ab_format_with_defaults(self):
        """Parses AB#123 format when defaults are configured."""
        provider = AzureDevOpsProvider(default_org="contoso", default_project="Backend")
        result = provider.parse_input("AB#42")
        assert result == "contoso/Backend#42"

    def test_parse_ab_format_without_defaults_raises(self, provider):
        """AB#123 format without defaults raises ValueError."""
        with pytest.raises(ValueError, match="AZURE_DEVOPS_ORG"):
            provider.parse_input("AB#42")

    def test_parse_with_whitespace(self, provider):
        """Strips whitespace from input."""
        result = provider.parse_input("  https://dev.azure.com/org/proj/_workitems/edit/1  ")
        assert result == "org/proj#1"

    def test_parse_invalid_raises_valueerror(self, provider):
        """Invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Cannot parse Azure DevOps"):
            provider.parse_input("not-a-ticket")


class TestAzureDevOpsProviderNormalize:
    """Test normalize() method."""

    @pytest.fixture
    def sample_ado_response(self):
        """Sample Azure DevOps API response."""
        return {
            "id": 42,
            "url": "https://dev.azure.com/contoso/Backend/_workitems/edit/42",
            "fields": {
                "System.Title": "Fix login bug",
                "System.Description": "<div>This is the <b>description</b></div>",
                "System.State": "Active",
                "System.WorkItemType": "Bug",
                "System.AssignedTo": {
                    "displayName": "John Doe",
                    "uniqueName": "john@contoso.com",
                },
                "System.Tags": "backend; priority",
                "System.CreatedDate": "2024-01-15T10:30:00.000Z",
                "System.ChangedDate": "2024-01-18T14:20:00.000Z",
                "System.TeamProject": "Backend",
                "System.AreaPath": "Backend\\API",
                "System.IterationPath": "Backend\\Sprint 42",
            },
        }

    def test_normalize_full_response(self, provider, sample_ado_response):
        """Normalizes full Azure DevOps response to GenericTicket."""
        ticket = provider.normalize(sample_ado_response)

        # ID includes org/project when URL matches dev.azure.com pattern
        assert ticket.id == "contoso/Backend#42"
        assert ticket.platform == Platform.AZURE_DEVOPS
        assert ticket.url == "https://dev.azure.com/contoso/Backend/_workitems/edit/42"
        assert ticket.title == "Fix login bug"
        assert "description" in ticket.description.lower()  # HTML stripped
        assert "<div>" not in ticket.description  # HTML removed
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.type == TicketType.BUG
        assert ticket.assignee == "John Doe"
        assert ticket.labels == ["backend", "priority"]
        assert ticket.created_at is not None
        assert ticket.updated_at is not None

    def test_normalize_minimal_response(self, provider):
        """Normalizes minimal Azure DevOps response."""
        minimal = {"id": 1, "fields": {"System.Title": "Minimal"}}
        ticket = provider.normalize(minimal)

        assert ticket.id == "1"
        assert ticket.title == "Minimal"
        assert ticket.status == TicketStatus.UNKNOWN
        assert ticket.type == TicketType.UNKNOWN
        assert ticket.assignee is None
        assert ticket.labels == []

    def test_normalize_generates_branch_summary(self, provider, sample_ado_response):
        """Normalizes and generates branch summary."""
        ticket = provider.normalize(sample_ado_response)
        assert ticket.branch_summary == "fix-login-bug"

    def test_normalize_empty_response_raises_valueerror(self, provider):
        """Empty dict raises ValueError due to missing id."""
        with pytest.raises(ValueError, match="id.*missing"):
            provider.normalize({})

    def test_normalize_platform_metadata(self, provider, sample_ado_response):
        """Normalizes platform-specific metadata."""
        ticket = provider.normalize(sample_ado_response)

        assert ticket.platform_metadata["area_path"] == "Backend\\API"
        assert ticket.platform_metadata["iteration_path"] == "Backend\\Sprint 42"


class TestBrowseUrlExtraction:
    """Test browse URL extraction from _links.html.href."""

    def test_normalize_uses_links_html_href(self, provider):
        """Uses _links.html.href when present for browse URL."""
        data = {
            "id": 42,
            "url": "https://api.dev.azure.com/contoso/Backend/_apis/wit/workItems/42",
            "_links": {
                "html": {"href": "https://dev.azure.com/contoso/Backend/_workitems/edit/42"}
            },
            "fields": {"System.Title": "Test"},
        }
        ticket = provider.normalize(data)
        assert ticket.url == "https://dev.azure.com/contoso/Backend/_workitems/edit/42"

    def test_normalize_falls_back_to_url_field(self, provider):
        """Falls back to url field when _links.html.href is missing."""
        data = {
            "id": 42,
            "url": "https://dev.azure.com/contoso/Backend/_workitems/edit/42",
            "_links": {},
            "fields": {"System.Title": "Test"},
        }
        ticket = provider.normalize(data)
        assert ticket.url == "https://dev.azure.com/contoso/Backend/_workitems/edit/42"


class TestDefensiveFieldHandling:
    """Test defensive handling of malformed API responses."""

    def test_normalize_with_none_assignee(self, provider):
        """Handle None assignee gracefully."""
        data = {
            "id": 1,
            "fields": {
                "System.Title": "Test",
                "System.AssignedTo": None,
            },
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_with_non_dict_assignee(self, provider):
        """Handle non-dict assignee gracefully."""
        data = {
            "id": 1,
            "fields": {
                "System.Title": "Test",
                "System.AssignedTo": "invalid",
            },
        }
        ticket = provider.normalize(data)
        assert ticket.assignee is None

    def test_normalize_missing_id_raises_valueerror(self, provider):
        """Missing ID raises ValueError."""
        data = {"fields": {"System.Title": "Test"}}
        with pytest.raises(ValueError, match="id.*missing"):
            provider.normalize(data)


class TestStatusMapping:
    """Test status mapping from Azure DevOps states."""

    def test_map_status_open_states(self, provider):
        """Map open states to OPEN."""
        assert provider._map_status("New") == TicketStatus.OPEN
        assert provider._map_status("To Do") == TicketStatus.OPEN
        assert provider._map_status("new") == TicketStatus.OPEN  # case insensitive

    def test_map_status_in_progress_states(self, provider):
        """Map in-progress states to IN_PROGRESS."""
        assert provider._map_status("Active") == TicketStatus.IN_PROGRESS
        assert provider._map_status("In Progress") == TicketStatus.IN_PROGRESS
        assert provider._map_status("Committed") == TicketStatus.IN_PROGRESS

    def test_map_status_review_states(self, provider):
        """Map review states to REVIEW."""
        assert provider._map_status("Resolved") == TicketStatus.REVIEW

    def test_map_status_done_states(self, provider):
        """Map done states to DONE."""
        assert provider._map_status("Closed") == TicketStatus.DONE
        assert provider._map_status("Done") == TicketStatus.DONE

    def test_map_status_closed_states(self, provider):
        """Map removed state to CLOSED."""
        assert provider._map_status("Removed") == TicketStatus.CLOSED

    def test_map_status_unknown(self, provider):
        """Unknown state returns UNKNOWN."""
        assert provider._map_status("CustomState") == TicketStatus.UNKNOWN


class TestTypeMapping:
    """Test type mapping from Azure DevOps work item types."""

    def test_map_type_bug_types(self, provider):
        """Map bug types to BUG."""
        assert provider._map_type("Bug") == TicketType.BUG
        assert provider._map_type("Defect") == TicketType.BUG
        assert provider._map_type("Impediment") == TicketType.BUG
        assert provider._map_type("Issue") == TicketType.BUG

    def test_map_type_feature_types(self, provider):
        """Map feature types to FEATURE."""
        assert provider._map_type("User Story") == TicketType.FEATURE
        assert provider._map_type("Feature") == TicketType.FEATURE
        assert provider._map_type("Product Backlog Item") == TicketType.FEATURE
        assert provider._map_type("Epic") == TicketType.FEATURE
        assert provider._map_type("Requirement") == TicketType.FEATURE

    def test_map_type_task_types(self, provider):
        """Map task types to TASK."""
        assert provider._map_type("Task") == TicketType.TASK
        assert provider._map_type("Spike") == TicketType.TASK

    def test_map_type_maintenance_types(self, provider):
        """Map maintenance types to MAINTENANCE."""
        assert provider._map_type("Tech Debt") == TicketType.MAINTENANCE
        assert provider._map_type("Change Request") == TicketType.MAINTENANCE

    def test_map_type_unknown(self, provider):
        """Unknown type returns UNKNOWN."""
        assert provider._map_type("CustomType") == TicketType.UNKNOWN


class TestHTMLStripping:
    """Test HTML stripping for descriptions."""

    def test_strip_html_simple_tags(self):
        """Strips simple HTML tags."""
        assert strip_html("<p>Hello</p>") == "Hello"
        assert strip_html("<div>World</div>") == "World"

    def test_strip_html_nested_tags(self):
        """Strips nested HTML tags."""
        assert strip_html("<div><p>Hello <b>World</b></p></div>") == "Hello World"

    def test_strip_html_empty_string(self):
        """Returns empty string for empty input."""
        assert strip_html("") == ""

    def test_strip_html_none(self):
        """Returns empty string for None input."""
        assert strip_html(None) == ""

    def test_strip_html_plain_text(self):
        """Returns plain text unchanged."""
        assert strip_html("Hello World") == "Hello World"


class TestPromptTemplate:
    """Test get_prompt_template() method."""

    def test_get_prompt_template_returns_empty_string(self, provider):
        """get_prompt_template returns empty string - no Auggie MCP support."""
        assert provider.get_prompt_template() == ""
