"""Shared pytest fixtures for AI Workflow tests."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Create a temporary config file with sample values."""
    config_file = tmp_path / ".ai-workflow-config"
    config_file.write_text('''# AI Workflow Configuration
DEFAULT_MODEL="claude-3"
PLANNING_MODEL="claude-3-opus"
IMPLEMENTATION_MODEL="claude-3-sonnet"
DEFAULT_JIRA_PROJECT="PROJ"
AUTO_OPEN_FILES="true"
SKIP_CLARIFICATION="false"
SQUASH_AT_END="true"
''')
    return config_file


@pytest.fixture
def empty_config_file(tmp_path: Path) -> Path:
    """Create an empty config file."""
    config_file = tmp_path / ".ai-workflow-config"
    config_file.write_text("")
    return config_file


@pytest.fixture
def sample_plan_file(tmp_path: Path) -> Path:
    """Create a sample plan file."""
    plan = tmp_path / "specs" / "TEST-123-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text('''# Implementation Plan: TEST-123

## Summary
Test implementation plan for feature development.

## Implementation Tasks
### Phase 1: Setup
1. Create database schema
2. Add API endpoint

### Phase 2: Frontend
1. Create UI components
2. Add form validation
''')
    return plan


@pytest.fixture
def sample_tasklist_file(tmp_path: Path) -> Path:
    """Create a sample task list file."""
    tasklist = tmp_path / "specs" / "TEST-123-tasklist.md"
    tasklist.parent.mkdir(parents=True)
    tasklist.write_text('''# Task List: TEST-123

## Phase 1: Setup
- [ ] Create database schema
- [ ] Add API endpoint
- [x] Configure environment

## Phase 2: Frontend
- [ ] Create UI components
* [ ] Add form validation
''')
    return tasklist


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for git/auggie commands."""
    with patch('subprocess.run') as mock:
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
    monkeypatch.setattr("ai_workflow.utils.console.console", mock)
    return mock

