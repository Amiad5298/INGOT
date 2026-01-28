"""Shared pytest fixtures for SPEC tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Enable pytest-asyncio for async test support
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Create a temporary config file with sample values."""
    config_file = tmp_path / ".spec-config"
    config_file.write_text(
        """# SPEC Configuration
DEFAULT_MODEL="claude-3"
PLANNING_MODEL="claude-3-opus"
IMPLEMENTATION_MODEL="claude-3-sonnet"
DEFAULT_JIRA_PROJECT="PROJ"
AUTO_OPEN_FILES="true"
SKIP_CLARIFICATION="false"
SQUASH_AT_END="true"
"""
    )
    return config_file


@pytest.fixture
def empty_config_file(tmp_path: Path) -> Path:
    """Create an empty config file."""
    config_file = tmp_path / ".spec-config"
    config_file.write_text("")
    return config_file


@pytest.fixture
def sample_plan_file(tmp_path: Path) -> Path:
    """Create a sample plan file."""
    plan = tmp_path / "specs" / "TEST-123-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        """# Implementation Plan: TEST-123

## Summary
Test implementation plan for feature development.

## Implementation Tasks
### Phase 1: Setup
1. Create database schema
2. Add API endpoint

### Phase 2: Frontend
1. Create UI components
2. Add form validation
"""
    )
    return plan


@pytest.fixture
def sample_tasklist_file(tmp_path: Path) -> Path:
    """Create a sample task list file."""
    tasklist = tmp_path / "specs" / "TEST-123-tasklist.md"
    tasklist.parent.mkdir(parents=True)
    tasklist.write_text(
        """# Task List: TEST-123

## Phase 1: Setup
- [ ] Create database schema
- [ ] Add API endpoint
- [x] Configure environment

## Phase 2: Frontend
- [ ] Create UI components
* [ ] Add form validation
"""
    )
    return tasklist


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for git/auggie commands."""
    with patch("subprocess.run") as mock:
        mock.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        yield mock


@pytest.fixture
def mock_auggie_client():
    """Mock AuggieClient for testing."""
    client = MagicMock()
    client.run_print.return_value = True
    client.run_print_quiet.return_value = "BRANCH_SUMMARY: test-feature\nTITLE: Test\n"
    return client


@pytest.fixture
def mock_console(monkeypatch):
    """Mock console output for testing."""
    mock = MagicMock()
    monkeypatch.setattr("spec.utils.console.console", mock)
    return mock


@pytest.fixture
def sample_tasks_with_categories():
    """Create sample tasks with category metadata for parallel execution tests."""
    from spec.workflow.tasks import Task, TaskCategory, TaskStatus

    return [
        Task(
            name="Setup database schema",
            status=TaskStatus.PENDING,
            line_number=1,
            category=TaskCategory.FUNDAMENTAL,
            dependency_order=1,
        ),
        Task(
            name="Configure environment",
            status=TaskStatus.PENDING,
            line_number=2,
            category=TaskCategory.FUNDAMENTAL,
            dependency_order=2,
        ),
        Task(
            name="Create UI components",
            status=TaskStatus.PENDING,
            line_number=3,
            category=TaskCategory.INDEPENDENT,
            group_id="frontend",
        ),
        Task(
            name="Add form validation",
            status=TaskStatus.PENDING,
            line_number=4,
            category=TaskCategory.INDEPENDENT,
            group_id="frontend",
        ),
        Task(
            name="Write unit tests",
            status=TaskStatus.PENDING,
            line_number=5,
            category=TaskCategory.INDEPENDENT,
            group_id="testing",
        ),
    ]


@pytest.fixture
def rate_limit_config():
    """Create a RateLimitConfig for testing."""
    from spec.workflow.state import RateLimitConfig

    return RateLimitConfig(
        max_retries=3,
        base_delay_seconds=1.0,
        max_delay_seconds=30.0,
        jitter_factor=0.25,
    )


@pytest.fixture
def generic_ticket():
    """Create a standard test ticket using GenericTicket.

    This is the platform-agnostic ticket fixture that should be used
    for all workflow tests after the JiraTicket to GenericTicket migration.
    """
    from spec.integrations.providers import GenericTicket, Platform

    return GenericTicket(
        id="TEST-123",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-123",
        title="Test Feature",
        description="Test description for the feature implementation.",
        branch_summary="test-feature",
    )


@pytest.fixture
def generic_ticket_no_summary():
    """Create a test ticket without branch summary."""
    from spec.integrations.providers import GenericTicket, Platform

    return GenericTicket(
        id="TEST-456",
        platform=Platform.JIRA,
        url="https://jira.example.com/TEST-456",
        title="Test Feature No Summary",
        description="Test description.",
        branch_summary="",
    )


# =============================================================================
# Platform-specific raw data fixtures for CLI integration tests (AMI-40)
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
# Pre-built GenericTicket fixtures for CLI integration tests (AMI-40)
# =============================================================================


@pytest.fixture
def mock_jira_ticket():
    """Pre-built GenericTicket for Jira platform."""
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
    from spec.integrations.providers import (
        GenericTicket,
        Platform,
        TicketStatus,
        TicketType,
    )

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
# Mock factory fixtures for CLI integration tests (AMI-40)
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
    from unittest.mock import AsyncMock, MagicMock

    from spec.integrations.fetchers.exceptions import (
        PlatformNotSupportedError as FetcherPlatformNotSupportedError,
    )
    from spec.integrations.providers import Platform

    def create_fetcher(platform_responses: dict):
        fetcher = MagicMock()
        fetcher.name = "MockFetcher"
        fetcher.supports_platform.side_effect = lambda p: p in platform_responses

        async def mock_fetch(ticket_id: str, platform_str: str) -> dict:
            platform = Platform[platform_str.upper()]
            if platform in platform_responses:
                return platform_responses[platform]
            raise FetcherPlatformNotSupportedError(
                platform=platform.name, fetcher_name="MockFetcher"
            )

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
    from unittest.mock import AsyncMock, MagicMock

    from spec.integrations.providers import GenericTicket
    from spec.integrations.providers.exceptions import TicketNotFoundError

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

            # Set up async context manager protocol on the service itself
            mock_service.__aenter__ = AsyncMock(return_value=mock_service)
            mock_service.__aexit__ = AsyncMock(return_value=None)
            return mock_service

        return mock_create_ticket_service

    return create_mock_service_factory
