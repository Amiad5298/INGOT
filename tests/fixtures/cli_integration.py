"""CLI Integration Test Fixtures (AMI-40).

This module contains fixtures specific to CLI integration tests:
- Platform-specific raw API response data
- Pre-built GenericTicket fixtures for each platform
- Mock fetcher and service factories

These fixtures are imported explicitly by tests/test_cli_integration.py
to reduce global conftest bloat.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from spec.integrations.fetchers.exceptions import (
    PlatformNotSupportedError as FetcherPlatformNotSupportedError,
)
from spec.integrations.providers import (
    GenericTicket,
    Platform,
    TicketStatus,
    TicketType,
)
from spec.integrations.providers.exceptions import TicketNotFoundError
from tests.helpers.async_cm import make_async_context_manager

# =============================================================================
# Platform-specific raw data fixtures
# =============================================================================


@pytest.fixture
def mock_jira_raw_data():
    """Raw Jira API response data."""
    return {
        "key": "PROJ-123",
        "fields": {
            "summary": "Test Jira Ticket",
            "description": "Test description",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "assignee": {"displayName": "Test User"},
            "labels": ["test", "integration"],
        },
    }


@pytest.fixture
def mock_linear_raw_data():
    """Raw Linear API response data."""
    return {
        "identifier": "ENG-456",
        "title": "Test Linear Issue",
        "description": "Linear description",
        "state": {"name": "In Progress"},
        "assignee": {"name": "Test User"},
        "labels": {"nodes": [{"name": "feature"}]},
    }


@pytest.fixture
def mock_github_raw_data():
    """Raw GitHub API response data."""
    return {
        "number": 42,
        "title": "Test GitHub Issue",
        "body": "GitHub issue description",
        "state": "open",
        "user": {"login": "testuser"},
        "labels": [{"name": "bug"}, {"name": "priority-high"}],
        "html_url": "https://github.com/owner/repo/issues/42",
    }


@pytest.fixture
def mock_azure_devops_raw_data():
    """Raw Azure DevOps API response data."""
    return {
        "id": 789,
        "fields": {
            "System.Title": "Test ADO Work Item",
            "System.Description": "Azure DevOps description",
            "System.State": "Active",
            "System.WorkItemType": "User Story",
            "System.AssignedTo": {"displayName": "Test User"},
        },
        "_links": {"html": {"href": "https://dev.azure.com/org/project/_workitems/edit/789"}},
    }


@pytest.fixture
def mock_monday_raw_data():
    """Raw Monday.com API response data."""
    return {
        "id": "123456789",
        "name": "Test Monday Item",
        "column_values": [
            {"id": "status", "text": "Working on it"},
            {"id": "person", "text": "Test User"},
        ],
        "board": {"id": "987654321", "name": "Test Board"},
    }


@pytest.fixture
def mock_trello_raw_data():
    """Raw Trello API response data."""
    return {
        "id": "abc123def456",
        "name": "Test Trello Card",
        "desc": "Trello card description",
        "idList": "list123",
        "labels": [{"name": "Feature", "color": "green"}],
        "members": [{"fullName": "Test User"}],
        "url": "https://trello.com/c/abc123/test-card",
    }


# =============================================================================
# Pre-built GenericTicket fixtures
# =============================================================================


@pytest.fixture
def mock_jira_ticket():
    """Pre-built GenericTicket for Jira platform."""
    return GenericTicket(
        id="PROJ-123",
        platform=Platform.JIRA,
        url="https://company.atlassian.net/browse/PROJ-123",
        title="Test Jira Ticket",
        description="Test description",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.FEATURE,
        assignee="Test User",
        labels=["test", "integration"],
    )


@pytest.fixture
def mock_linear_ticket():
    """Pre-built GenericTicket for Linear platform."""
    return GenericTicket(
        id="ENG-456",
        platform=Platform.LINEAR,
        url="https://linear.app/team/issue/ENG-456",
        title="Test Linear Issue",
        description="Linear description",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.FEATURE,
        assignee="Test User",
        labels=["feature"],
    )


@pytest.fixture
def mock_github_ticket():
    """Pre-built GenericTicket for GitHub platform."""
    return GenericTicket(
        id="owner/repo#42",
        platform=Platform.GITHUB,
        url="https://github.com/owner/repo/issues/42",
        title="Test GitHub Issue",
        description="GitHub issue description",
        status=TicketStatus.OPEN,
        type=TicketType.BUG,
        assignee="testuser",
        labels=["bug", "priority-high"],
    )


@pytest.fixture
def mock_azure_devops_ticket():
    """Pre-built GenericTicket for Azure DevOps platform."""
    return GenericTicket(
        id="789",
        platform=Platform.AZURE_DEVOPS,
        url="https://dev.azure.com/org/project/_workitems/edit/789",
        title="Test ADO Work Item",
        description="Azure DevOps description",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.FEATURE,
        assignee="Test User",
        labels=[],
    )


@pytest.fixture
def mock_monday_ticket():
    """Pre-built GenericTicket for Monday.com platform."""
    return GenericTicket(
        id="123456789",
        platform=Platform.MONDAY,
        url="https://myorg.monday.com/boards/987654321/pulses/123456789",
        title="Test Monday Item",
        description="",
        status=TicketStatus.IN_PROGRESS,
        type=TicketType.TASK,
        assignee="Test User",
    )


@pytest.fixture
def mock_trello_ticket():
    """Pre-built GenericTicket for Trello platform."""
    return GenericTicket(
        id="abc123def456",
        platform=Platform.TRELLO,
        url="https://trello.com/c/abc123/test-card",
        title="Test Trello Card",
        description="Trello card description",
        status=TicketStatus.OPEN,
        type=TicketType.TASK,
        assignee="Test User",
        labels=["Feature"],
    )


# =============================================================================
# Mock factory fixtures
# =============================================================================


@pytest.fixture
def mock_fetcher_factory():
    """Factory for creating mock fetchers with platform-specific responses.

    Usage:
        fetcher = mock_fetcher_factory({
            Platform.JIRA: {"key": "PROJ-123", ...},
            Platform.LINEAR: {"identifier": "ENG-456", ...},
        })
    """

    def create_fetcher(platform_responses: dict, name: str = "MockFetcher"):
        fetcher = MagicMock()
        fetcher.name = name
        fetcher.supports_platform.side_effect = lambda p: p in platform_responses

        async def mock_fetch(ticket_id: str, platform_str: str) -> dict:
            platform = Platform[platform_str.upper()]
            if platform in platform_responses:
                return platform_responses[platform]
            raise FetcherPlatformNotSupportedError(platform=platform.name, fetcher_name=name)

        fetcher.fetch = AsyncMock(side_effect=mock_fetch)
        fetcher.close = AsyncMock()
        return fetcher

    return create_fetcher


@pytest.fixture
def mock_config_for_cli():
    """Standard mock ConfigManager for CLI tests.

    Provides all commonly accessed settings to avoid MagicMock surprises.
    """
    mock_config = MagicMock()
    mock_config.settings.default_jira_project = ""
    mock_config.settings.get_default_platform.return_value = None
    mock_config.settings.default_model = "test-model"
    mock_config.settings.planning_model = ""
    mock_config.settings.implementation_model = ""
    mock_config.settings.skip_clarification = False
    mock_config.settings.squash_at_end = True
    mock_config.settings.auto_update_docs = True
    mock_config.settings.max_parallel_tasks = 3
    mock_config.settings.parallel_execution_enabled = True
    mock_config.settings.fail_fast = False
    return mock_config


@pytest.fixture
def mock_ticket_service_factory():
    """Factory for creating mock TicketService for Layer A tests.

    This fixture allows mocking at the `create_ticket_service_from_config` factory level,
    so CLI code paths are exercised but TicketService is completely mocked.

    Usage:
        with patch(
            "spec.cli.create_ticket_service_from_config",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", "jira"])
    """

    def create_mock_service_factory(ticket_map: dict[str, GenericTicket]):
        """Create a mock create_ticket_service_from_config that returns a mock TicketService.

        Args:
            ticket_map: Dict mapping ticket_id/input to GenericTicket to return
        """

        async def mock_create_ticket_service(*args, **kwargs):
            """Async mock that returns a TicketService-like object."""
            mock_service = MagicMock()

            async def mock_get_ticket(ticket_input: str, **kwargs):
                # Try direct lookup first
                if ticket_input in ticket_map:
                    return ticket_map[ticket_input]
                # Try extracting ticket ID from URL (simplified)
                for key, ticket in ticket_map.items():
                    if key in ticket_input:
                        return ticket
                # Not found - raise error
                raise TicketNotFoundError(ticket_id=ticket_input, platform="unknown")

            mock_service.get_ticket = AsyncMock(side_effect=mock_get_ticket)
            mock_service.close = AsyncMock()

            # Use standard async CM pattern helper
            return make_async_context_manager(mock_service)

        return mock_create_ticket_service

    return create_mock_service_factory
