"""Shared pytest fixtures for SPEC tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Enable pytest-asyncio for async test support
# Also include CLI integration fixtures (moved from tests/cli/conftest.py per pytest 9.x requirement)
pytest_plugins = ("pytest_asyncio", "tests.fixtures.cli_integration")


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
# CLI Integration Test Fixtures (AMI-40)
# =============================================================================
# NOTE: Platform-specific fixtures for CLI integration tests are in
# tests/fixtures/cli_integration.py and loaded via pytest_plugins above.
# This is required since pytest 9.x no longer supports pytest_plugins
# in non-top-level conftest files.
# =============================================================================
