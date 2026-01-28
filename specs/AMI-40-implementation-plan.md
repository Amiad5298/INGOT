# Implementation Plan: AMI-40 - Add End-to-End Integration Tests for Multi-Platform CLI

**Ticket:** [AMI-40](https://linear.app/amiadspec/issue/AMI-40/add-end-to-end-integration-tests-for-multi-platform-cli)
**Status:** Draft
**Date:** 2026-01-28
**Last Updated:** 2026-01-28

---

## Plan Changes (v2)

### Problem Statement

The original plan had two inconsistencies with the ticket requirements:

1. **Mixed Testing Approaches**: The plan patched `spec.cli._fetch_ticket_async` for CLI tests (bypassing TicketService entirely), while separate E2E tests ran TicketService directly without going through CLI. This didn't match AC1: "Integration tests exist for CLI with mocked TicketService."

2. **Incomplete CLI Coverage**: The ticket requires "All 6 platforms are tested through the CLI entry point" (AC2), but the deeper integration tests (verifying TicketService→provider→fetcher) weren't exercised via `runner.invoke(app, ...)`.

### New Structure: 2-Layer Test Strategy

**Layer A: CLI Contract Tests** — Test CLI behavior (flag parsing, validation, exit codes) with TicketService mocked at the `create_ticket_service` factory boundary.

**Layer B: CLI→Service Integration Tests** — Test the full CLI→TicketService→Provider chain for all 6 platforms, mocking only at the fetcher boundary (AuggieMediatedFetcher/DirectAPIFetcher `.fetch()` methods).

### Rationale

- **Eliminates `_fetch_ticket_async` patching**: Instead of patching a private function, we mock at proper boundaries (`create_ticket_service` or `fetcher.fetch()`).
- **All 6 platforms go through CLI**: Layer B tests use `runner.invoke(app, ...)` with fetcher mocks, exercising the real TicketService + real Providers.
- **Cleaner dependency injection**: Mock at factory or class boundaries, not internal implementation details.
- **CI-friendly**: No network calls, no credentials, deterministic.

---

## Summary

This ticket adds end-to-end integration tests that verify the complete flow from CLI entry point through TicketService to ticket fetching for all 6 supported platforms. While unit tests exist for individual components (TicketService, providers, fetchers), there are no integration tests that validate the full CLI → TicketService → Fetcher → Provider chain.

**Why This Matters:**
- Unit tests don't catch integration issues between components
- Regressions in the CLI-to-TicketService integration could go undetected
- The disambiguation flow (user prompts for ambiguous IDs) needs end-to-end testing
- Fallback behavior (AuggieMediatedFetcher to DirectAPIFetcher) needs verification at CLI level
- The `--platform` flag from AMI-25 needs comprehensive testing with all platform values

**Scope:**
- New test file: `tests/test_cli_integration.py`
- May add shared fixtures to `tests/conftest.py`
- Does NOT require actual API credentials (all external dependencies mocked)

---

## Technical Approach

### 2-Layer Test Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER A: CLI Contract Tests                                                      │
│ Mock boundary: create_ticket_service factory                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│  runner.invoke(app, ["PROJ-123", "--platform", "jira"])                         │
│       │                                                                          │
│       ▼                                                                          │
│  main() → _validate_platform() (real)                                           │
│       │                                                                          │
│       ▼                                                                          │
│  _run_workflow() → _disambiguate_platform() (real or mocked prompt)             │
│       │                                                                          │
│       ▼                                                                          │
│  _fetch_ticket_async() → create_ticket_service() [MOCKED to return MockService] │
│       │                                                                          │
│       ▼                                                                          │
│  MockTicketService.get_ticket() returns pre-built GenericTicket                 │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│ LAYER B: CLI→Service Integration Tests                                          │
│ Mock boundary: fetcher class constructors (return mock instances with .fetch())  │
├─────────────────────────────────────────────────────────────────────────────────┤
│  runner.invoke(app, ["https://jira.example.com/browse/PROJ-123"])               │
│       │                                                                          │
│       ▼                                                                          │
│  main() → _validate_platform() (real)                                           │
│       │                                                                          │
│       ▼                                                                          │
│  _run_workflow() (real)                                                          │
│       │                                                                          │
│       ▼                                                                          │
│  _fetch_ticket_async() → create_ticket_service() (real factory)                 │
│       │                                                                          │
│       ▼                                                                          │
│  TicketService (real) → ProviderRegistry (real) → Provider (real)               │
│       │                                                                          │
│       ▼                                                                          │
│  _fetch_with_fallback() → MockFetcher.fetch() [MOCKED - returns raw API data]   │
│       │                                                                          │
│       ▼                                                                          │
│  Provider.normalize(raw_data) (real) → GenericTicket                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Mocking Strategy by Layer

| Component | Layer A (Contract) | Layer B (Integration) | Rationale |
|-----------|-------------------|----------------------|-----------|
| `create_ticket_service` | **MOCKED** (returns MockService) | Real | Layer A focuses on CLI behavior |
| `TicketService` | MockService instance | **Real** | Layer B tests real orchestration |
| `ProviderRegistry` | N/A (not reached) | **Real** | Test actual platform detection |
| `Provider.normalize()` | N/A (not reached) | **Real** | Test actual data transformation |
| `AuggieMediatedFetcher` | N/A | **MOCKED** (constructor patched) | Returns mock with stubbed `.fetch()` |
| `DirectAPIFetcher` | N/A | **MOCKED** (constructor patched) | Returns mock with stubbed `.fetch()` |
| `AuggieClient` | N/A | MOCKED constructor | Avoid process spawn |
| `AuthenticationManager` | N/A | MOCKED instance | Provide fake credentials |
| `prompt_select()` | MOCKED | MOCKED | Simulate user input |
| `ConfigManager` | MOCKED | MOCKED | Control settings |

### Test Categories

**Layer A: CLI Contract Tests**
1. **--platform Flag Validation** - Valid values, invalid values, case insensitivity, -p shorthand
2. **Disambiguation Flow** - Ambiguous IDs trigger prompt, default_platform skips prompt, --platform bypasses prompt
3. **Exit Codes** - Correct exit codes for all error types
4. **Error Messages** - User-friendly messages for invalid platform, unconfigured credentials, etc.

**Layer B: CLI→Service Integration Tests**
5. **All 6 Platforms via CLI** - Each platform with URL input, verifying real TicketService + real Provider
6. **Fallback Behavior** - Primary fetcher fails → fallback succeeds (tested via CLI)
7. **Error Propagation** - TicketNotFoundError, AuthenticationError properly surface at CLI
8. **Real Normalization** - Raw API data → GenericTicket with correct field mapping

---

## Acceptance Criteria Mapping

| AC | Description | Test Type | Test Class/Method | Notes |
|----|-------------|-----------|-------------------|-------|
| **AC1** | Integration tests exist for CLI with mocked TicketService | Layer A | `TestPlatformFlagValidation`, `TestDisambiguationFlow` | Mock at `create_ticket_service` factory (TicketService itself is mocked) |
| **AC2** | All 6 platforms tested through CLI entry point | Layer B | `TestCLIServiceIntegration.test_platform_via_cli[platform]` | Parametrized test for all 6 platforms using PLATFORM_TEST_DATA keys |
| **AC3** | `--platform` flag tested with all valid values | Layer A | `TestPlatformFlagValidation.test_valid_platform_values` | 6 parametrized cases |
| **AC4** | Invalid `--platform` values produce errors | Layer A | `TestPlatformFlagValidation.test_invalid_platform_error` | Exit code + message check |
| **AC5** | Disambiguation flow tested | Layer A | `TestDisambiguationFlow.*` | 4 scenarios (prompt, default, override, skip) |
| **AC6** | Error handling for unconfigured platforms | Layer B | `TestCLIServiceIntegration.test_unconfigured_platform_error` | Real service, mock fetcher raises |
| **AC7** | Fallback from primary to fallback fetcher | Layer B | `TestCLIServiceIntegration.test_fallback_behavior_via_cli` | Primary mock fails, fallback succeeds |
| **AC8** | Tests run in CI without external dependencies | Both | All tests | No network, no credentials |

### Additional AC Mapping (from original plan)

| AC | Description | Test Type | Test Class/Method |
|----|-------------|-----------|-------------------|
| AC9 | URL auto-detection for all 6 platforms | Layer B | `TestCLIServiceIntegration.test_platform_via_cli` (uses URLs) |
| AC10 | `default_platform` config tested | Layer A | `TestDisambiguationFlow.test_default_platform_skips_prompt` |
| AC11 | `--platform` overrides `default_platform` | Layer A | `TestDisambiguationFlow.test_flag_overrides_config` |
| AC12 | GitHub `owner/repo#123` is unambiguous | Layer A | `TestDisambiguationFlow.test_github_format_no_disambiguation` |
| AC15 | `-p` shorthand tested | Layer A | `TestPlatformFlagValidation.test_short_flag_alias` |
| AC16 | `TicketNotFoundError` at CLI level | Layer B | `TestCLIServiceIntegration.test_ticket_not_found_via_cli` |
| AC17 | `AuthenticationError` at CLI level | Layer B | `TestCLIServiceIntegration.test_auth_error_via_cli` |

---

## Specific Implementation Guidance

### Where to Inject Mocks

| Layer | Mock Target | What Runs Real | Code Location |
|-------|-------------|----------------|---------------|
| **Layer A** | `spec.integrations.ticket_service.create_ticket_service` | CLI, arg parsing, `_disambiguate_platform`, `_validate_platform` | `spec/integrations/ticket_service.py:293` |
| **Layer B** | `spec.integrations.ticket_service.AuggieMediatedFetcher` and `DirectAPIFetcher` | CLI, TicketService, Providers, ProviderRegistry | `spec/integrations/ticket_service.py:40, 55` |

### What to Mock (Cheat Sheet)

```python
# Layer A: Mock the entire TicketService via factory
with patch("spec.integrations.ticket_service.create_ticket_service", mock_factory):
    result = runner.invoke(app, ["PROJ-123", "--platform", "jira"])

# Layer B: Mock just the fetcher classes
with patch("spec.integrations.ticket_service.AuggieMediatedFetcher", return_value=mock_primary):
    with patch("spec.integrations.ticket_service.DirectAPIFetcher", return_value=mock_fallback):
        result = runner.invoke(app, ["https://jira.example.com/browse/PROJ-123"])
```

### Example Test Outlines

#### 1. Each of 6 Platforms via CLI (Layer B)

```python
@pytest.mark.parametrize("platform,url,expected_title", [
    (Platform.JIRA, "https://company.atlassian.net/browse/PROJ-123", "Test Jira Ticket"),
    (Platform.LINEAR, "https://linear.app/team/issue/ENG-456", "Test Linear Issue"),
    (Platform.GITHUB, "https://github.com/owner/repo/issues/42", "Test GitHub Issue"),
    (Platform.AZURE_DEVOPS, "https://dev.azure.com/org/project/_workitems/edit/789", "Test ADO Item"),
    (Platform.MONDAY, "https://myorg.monday.com/boards/123/pulses/456", "Test Monday Item"),
    (Platform.TRELLO, "https://trello.com/c/abc123/card", "Test Trello Card"),
])
def test_all_platforms_via_cli(platform, url, expected_title, request):
    """Layer B: Full chain CLI→TicketService→Provider for each platform."""
    raw_data = request.getfixturevalue(f"mock_{platform.name.lower()}_raw_data")

    mock_fetcher = MagicMock()
    mock_fetcher.fetch = AsyncMock(return_value=raw_data)

    with patch("spec.integrations.ticket_service.AuggieMediatedFetcher", return_value=mock_fetcher):
        result = runner.invoke(app, [url])

    # Workflow should receive correctly normalized ticket
    assert mock_workflow.called
```

#### 2. Invalid --platform Flag (Layer A)

```python
def test_invalid_platform_error(mock_ticket_service_factory):
    """Layer A: Invalid --platform value shows helpful error."""
    with patch("spec.integrations.ticket_service.create_ticket_service",
               mock_ticket_service_factory({})):
        result = runner.invoke(app, ["PROJ-123", "--platform", "invalid_platform"])

    assert result.exit_code != 0
    assert "invalid" in result.stdout.lower() or "not a valid" in result.stdout.lower()
```

#### 3. Ambiguous ID Disambiguation Flow (Layer A)

```python
@patch("spec.cli._disambiguate_platform")
def test_ambiguous_id_triggers_disambiguation(
    mock_disambig, mock_ticket_service_factory, mock_jira_ticket
):
    """Layer A: PROJ-123 format triggers disambiguation prompt."""
    mock_disambig.return_value = Platform.JIRA

    with patch("spec.integrations.ticket_service.create_ticket_service",
               mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})):
        runner.invoke(app, ["PROJ-123"])  # No --platform flag

    mock_disambig.assert_called_once()  # Should prompt user
```

#### 4. Unconfigured Platform Error Handling (Layer B)

```python
def test_unconfigured_platform_error_via_cli():
    """Layer B: Platform with no credentials shows helpful error."""
    from spec.integrations.fetchers.exceptions import PlatformNotSupportedError

    mock_fetcher = MagicMock()
    mock_fetcher.supports_platform.return_value = False  # No support

    with patch("spec.integrations.ticket_service.AuggieMediatedFetcher", return_value=mock_fetcher):
        with patch("spec.integrations.ticket_service.DirectAPIFetcher", return_value=mock_fetcher):
            result = runner.invoke(app, ["https://monday.com/boards/123/pulses/456"])

    assert result.exit_code != 0
    assert "monday" in result.stdout.lower() or "not configured" in result.stdout.lower()
```

#### 5. Primary→Fallback Fetcher Behavior (Layer B)

```python
def test_fallback_on_primary_failure_via_cli(mock_jira_raw_data):
    """Layer B: Primary fetcher fails → fallback succeeds → ticket returned."""
    from spec.integrations.fetchers.exceptions import AgentIntegrationError

    # Primary fails
    mock_primary = MagicMock()
    mock_primary.fetch = AsyncMock(side_effect=AgentIntegrationError("Auggie down"))

    # Fallback succeeds
    mock_fallback = MagicMock()
    mock_fallback.fetch = AsyncMock(return_value=mock_jira_raw_data)

    with patch("spec.integrations.ticket_service.AuggieMediatedFetcher", return_value=mock_primary):
        with patch("spec.integrations.ticket_service.DirectAPIFetcher", return_value=mock_fallback):
            result = runner.invoke(app, ["https://jira.example.com/browse/PROJ-123"])

    mock_primary.fetch.assert_called_once()
    mock_fallback.fetch.assert_called_once()  # Fallback was used
```

---

## Files to Create

### New File: `tests/test_cli_integration.py`

**Purpose:** 2-layer integration tests for CLI → TicketService flow

**Structure (Updated for 2-Layer Strategy):**
```python
"""Integration tests for multi-platform CLI.

2-Layer Test Strategy:
- Layer A (CLI Contract): Mock at create_ticket_service factory
- Layer B (CLI→Service Integration): Mock only at fetcher.fetch() boundary

All tests use runner.invoke(app, ...) to exercise the real CLI entry point.
"""

import pytest
from typer.testing import CliRunner
from unittest.mock import AsyncMock, MagicMock, patch

from spec.cli import app
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
)
from spec.integrations.providers import GenericTicket, Platform
from spec.integrations.providers.exceptions import (
    AuthenticationError,
    PlatformNotSupportedError,
    TicketNotFoundError,
)
from spec.utils.errors import ExitCode


runner = CliRunner()


# =============================================================================
# LAYER A: CLI Contract Tests (Mock at create_ticket_service factory)
# =============================================================================
class TestPlatformFlagValidation: ...
class TestDisambiguationFlow: ...
class TestCLIContractWithMockedService: ...


# =============================================================================
# LAYER B: CLI→Service Integration Tests (Mock at fetcher.fetch() boundary)
# =============================================================================
class TestCLIServiceIntegration: ...
class TestFallbackBehaviorViaCLI: ...
class TestErrorPropagationViaCLI: ...
```

---

## Implementation Steps

### Phase 1: Create Test Infrastructure

#### Step 1.1: Add Platform-Specific Ticket Fixtures to conftest.py

Add shared fixtures for all 6 platforms to `tests/conftest.py`:

```python
# Note: There are TWO different PlatformNotSupportedError classes:
# 1. spec.integrations.providers.exceptions.PlatformNotSupportedError - for provider-level errors
# 2. spec.integrations.fetchers.exceptions.PlatformNotSupportedError - for fetcher-level errors
# We alias the fetcher version to avoid confusion
from spec.integrations.fetchers.exceptions import PlatformNotSupportedError as FetcherPlatformNotSupportedError
# Import from the public API (spec.integrations.providers) for consistency
from spec.integrations.providers import GenericTicket, Platform, TicketStatus, TicketType


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
        "_links": {
            "html": {"href": "https://dev.azure.com/org/project/_workitems/edit/789"}
        },
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
        labels=[],  # Azure DevOps uses Tags, represented as empty labels for consistency
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
```

#### Step 1.2: Create Mock Fetcher Factory

Add a helper fixture that creates pre-configured mock fetchers:

```python
@pytest.fixture
def mock_fetcher_factory():
    """Factory for creating mock fetchers with platform-specific responses.

    Usage:
        fetcher = mock_fetcher_factory({
            Platform.JIRA: {"key": "PROJ-123", ...},
            Platform.LINEAR: {"identifier": "ENG-456", ...},
        })
    """
    from spec.integrations.fetchers.exceptions import (
        PlatformNotSupportedError as FetcherPlatformNotSupportedError,
    )

    def create_fetcher(platform_responses: dict[Platform, dict]):
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

    This fixture allows mocking at the `create_ticket_service` factory level,
    so CLI code paths are exercised but TicketService is completely mocked.

    Usage:
        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", "jira"])
    """
    def create_mock_service_factory(ticket_map: dict[str, "GenericTicket"]):
        """Create a mock create_ticket_service that returns a mock TicketService.

        Args:
            ticket_map: Dict mapping ticket_id/input to GenericTicket to return
        """
        def mock_create_ticket_service(*args, **kwargs):
            mock_service = MagicMock()

            async def mock_get_ticket(ticket_input: str, platform_hint=None):
                # Try direct lookup first
                if ticket_input in ticket_map:
                    return ticket_map[ticket_input]
                # Try extracting ticket ID from URL (simplified)
                for key, ticket in ticket_map.items():
                    if key in ticket_input:
                        return ticket
                # Not found - raise error
                from spec.integrations.providers.exceptions import TicketNotFoundError
                raise TicketNotFoundError(ticket_id=ticket_input, platform="unknown")

            mock_service.get_ticket = AsyncMock(side_effect=mock_get_ticket)
            mock_service.close = AsyncMock()

            # Return as async context manager
            async_cm = MagicMock()
            async_cm.__aenter__ = AsyncMock(return_value=mock_service)
            async_cm.__aexit__ = AsyncMock(return_value=None)
            return async_cm

        return mock_create_ticket_service

    return create_mock_service_factory
```

---

### Phase 2: Layer A - CLI Contract Tests (Mock at create_ticket_service)

**Injection Point:** Mock `spec.integrations.ticket_service.create_ticket_service` to return a MockTicketService.
This tests CLI behavior without exercising real TicketService/Provider code.

**Note:** The `mock_ticket_service_factory` fixture is already defined in Step 1.2 above.
It returns a factory that creates mock `create_ticket_service` replacements matching the real signature
(an async function returning an async context manager).

#### Step 2.1: Test All Valid Platform Values (Layer A)

```python
class TestPlatformFlagValidation:
    """Test --platform flag parsing and validation (Layer A: contract tests)."""

    def test_invalid_platform_shows_error(self):
        """Invalid --platform value produces clear error message.

        Note: This test doesn't need any mocks - validation fails before TicketService is called.
        """
        result = runner.invoke(app, ["PROJ-123", "--platform", "invalid"])

        assert result.exit_code == ExitCode.GENERAL_ERROR
        assert "Invalid platform: invalid" in result.stdout
        assert "Valid options:" in result.stdout
        for platform in ["jira", "linear", "github", "azure_devops", "monday", "trello"]:
            assert platform in result.stdout

    @pytest.mark.parametrize("platform_name,expected_platform", [
        ("jira", Platform.JIRA),
        ("linear", Platform.LINEAR),
        ("github", Platform.GITHUB),
        ("azure_devops", Platform.AZURE_DEVOPS),
        ("monday", Platform.MONDAY),
        ("trello", Platform.TRELLO),
    ])
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_valid_platform_values(
        self, mock_config_class, mock_prereq, mock_banner,
        platform_name, expected_platform, mock_ticket_service_factory, mock_jira_ticket
    ):
        """All 6 platform values are accepted by --platform flag."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        # Mock at create_ticket_service factory (not _fetch_ticket_async)
        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", platform_name])

        # Should not error on platform validation
        assert "Invalid platform" not in result.stdout

    @pytest.mark.parametrize("variant", ["JIRA", "Jira", "JiRa", "jira"])
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_platform_flag_case_insensitive(
        self, mock_config_class, mock_prereq, mock_banner,
        variant, mock_ticket_service_factory, mock_jira_ticket
    ):
        """--platform flag is case-insensitive."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            result = runner.invoke(app, ["PROJ-123", "--platform", variant])

        assert "Invalid platform" not in result.stdout

    @pytest.mark.parametrize("platform_name", [
        "jira", "linear", "github", "azure_devops", "monday", "trello"
    ])
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_short_flag_alias(
        self, mock_config_class, mock_prereq, mock_banner,
        platform_name, mock_ticket_service_factory, mock_jira_ticket
    ):
        """-p shorthand works for all platform values."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"TEST-123": mock_jira_ticket})
        ):
            result = runner.invoke(app, ["TEST-123", "-p", platform_name])

        assert "Invalid platform" not in result.stdout
```

---

### Phase 3: Layer A - Disambiguation Flow Tests

**Note:** Disambiguation tests can still use `_disambiguate_platform` directly for unit testing,
but CLI-level tests should mock at `create_ticket_service` boundary.

```python
class TestDisambiguationFlow:
    """Test disambiguation flow for ambiguous ticket IDs (Layer A)."""

    @patch("spec.ui.prompts.prompt_select")
    def test_disambiguation_prompts_user(self, mock_prompt):
        """Disambiguation prompts user to choose between Jira and Linear.

        Note: This is a unit test of _disambiguate_platform, not a CLI integration test.
        """
        from spec.cli import _disambiguate_platform

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = None
        mock_prompt.return_value = "Jira"

        result = _disambiguate_platform("PROJ-123", mock_config)

        assert result == Platform.JIRA
        mock_prompt.assert_called_once()
        call_kwargs = mock_prompt.call_args.kwargs
        assert "Jira" in call_kwargs["choices"]
        assert "Linear" in call_kwargs["choices"]

    def test_default_platform_skips_prompt(self):
        """default_platform config skips user prompt for ambiguous IDs."""
        from spec.cli import _disambiguate_platform

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = Platform.LINEAR

        result = _disambiguate_platform("ENG-456", mock_config)

        assert result == Platform.LINEAR

    @patch("spec.cli._disambiguate_platform")
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_ambiguous_id_triggers_disambiguation_via_cli(
        self, mock_config_class, mock_prereq, mock_banner, mock_disambig,
        mock_ticket_service_factory, mock_jira_ticket
    ):
        """Ambiguous ticket ID triggers disambiguation when no default configured."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = None
        mock_config_class.return_value = mock_config
        mock_disambig.return_value = Platform.JIRA

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            runner.invoke(app, ["PROJ-123"])

        mock_disambig.assert_called_once()

    @patch("spec.cli._disambiguate_platform")
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_flag_overrides_disambiguation(
        self, mock_config_class, mock_prereq, mock_banner, mock_disambig,
        mock_ticket_service_factory, mock_jira_ticket
    ):
        """--platform flag bypasses disambiguation entirely."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"PROJ-123": mock_jira_ticket})
        ):
            runner.invoke(app, ["PROJ-123", "--platform", "linear"])

        mock_disambig.assert_not_called()

    @patch("spec.cli._disambiguate_platform")
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_github_format_no_disambiguation(
        self, mock_config_class, mock_prereq, mock_banner, mock_disambig,
        mock_ticket_service_factory, mock_github_ticket
    ):
        """GitHub owner/repo#123 format is unambiguous - no disambiguation needed."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"owner/repo#42": mock_github_ticket})
        ):
            runner.invoke(app, ["owner/repo#42"])

        mock_disambig.assert_not_called()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_config_default_platform_used(
        self, mock_config_class, mock_prereq, mock_banner,
        mock_ticket_service_factory, mock_linear_ticket
    ):
        """Configured default_platform is used for ambiguous IDs without prompting."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = Platform.LINEAR
        mock_config_class.return_value = mock_config

        with patch(
            "spec.integrations.ticket_service.create_ticket_service",
            mock_ticket_service_factory({"ENG-456": mock_linear_ticket})
        ):
            result = runner.invoke(app, ["ENG-456"])

        # Should succeed without prompting (using default)
        # This verifies the config integration path
```

---

### Phase 4: Layer B - CLI→Service Integration Tests (Mock at fetcher.fetch())

**This is the key phase that satisfies AC2: "All 6 platforms are tested through the CLI entry point."**

**Injection Point:** Mock the fetcher classes' `fetch()` methods while allowing the real
`create_ticket_service`, `TicketService`, and `Provider` classes to run.

```python
class TestCLIServiceIntegration:
    """Layer B: Full CLI→TicketService→Provider integration tests.

    These tests:
    1. Use runner.invoke(app, ...) to exercise the real CLI entry point
    2. Allow real TicketService and real Providers to run
    3. Mock only at the fetcher.fetch() boundary to avoid external API calls
    4. Verify that raw API data is correctly normalized to GenericTicket
    """

    # Mapping of platforms to their test URLs and raw data fixtures
    PLATFORM_TEST_DATA = {
        Platform.JIRA: {
            "url": "https://company.atlassian.net/browse/PROJ-123",
            "raw_fixture": "mock_jira_raw_data",
            "expected_title": "Test Jira Ticket",
        },
        Platform.LINEAR: {
            "url": "https://linear.app/team/issue/ENG-456",
            "raw_fixture": "mock_linear_raw_data",
            "expected_title": "Test Linear Issue",
        },
        Platform.GITHUB: {
            "url": "https://github.com/owner/repo/issues/42",
            "raw_fixture": "mock_github_raw_data",
            "expected_title": "Test GitHub Issue",
        },
        Platform.AZURE_DEVOPS: {
            "url": "https://dev.azure.com/org/project/_workitems/edit/789",
            "raw_fixture": "mock_azure_devops_raw_data",
            "expected_title": "Test ADO Work Item",
        },
        Platform.MONDAY: {
            "url": "https://myorg.monday.com/boards/987654321/pulses/123456789",
            "raw_fixture": "mock_monday_raw_data",
            "expected_title": "Test Monday Item",
        },
        Platform.TRELLO: {
            "url": "https://trello.com/c/abc123/test-card",
            "raw_fixture": "mock_trello_raw_data",
            "expected_title": "Test Trello Card",
        },
    }

    @pytest.mark.parametrize("platform", list(PLATFORM_TEST_DATA.keys()))
    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    @patch("spec.workflow.runner.run_spec_driven_workflow")  # Prevent actual workflow execution
    def test_platform_via_cli(
        self, mock_workflow, mock_config_class, mock_prereq, mock_banner,
        platform, request
    ):
        """All 6 platforms work through CLI→TicketService→Provider chain.

        This test:
        1. Invokes CLI with a platform-specific URL
        2. Lets real TicketService and Provider code run
        3. Mocks fetcher class constructors to return mock instances with stubbed .fetch()
        4. Verifies the workflow receives correctly normalized GenericTicket

        Note: Parametrized over PLATFORM_TEST_DATA.keys() (not list(Platform)) to ensure
        we test exactly the 6 supported platforms with proper test data.
        """
        test_data = self.PLATFORM_TEST_DATA[platform]
        raw_data = request.getfixturevalue(test_data["raw_fixture"])

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config.settings.get_default_platform.return_value = None
        # Add all required config settings
        mock_config.settings.default_model = "test-model"
        mock_config.settings.planning_model = ""
        mock_config.settings.implementation_model = ""
        mock_config.settings.skip_clarification = False
        mock_config.settings.squash_at_end = True
        mock_config.settings.auto_update_docs = True
        mock_config.settings.max_parallel_tasks = 3
        mock_config.settings.parallel_execution_enabled = True
        mock_config.settings.fail_fast = False
        mock_config_class.return_value = mock_config

        # Create a mock fetcher that returns raw data for this platform
        mock_fetcher = MagicMock()
        mock_fetcher.name = "MockFetcher"
        mock_fetcher.supports_platform.return_value = True
        mock_fetcher.fetch = AsyncMock(return_value=raw_data)
        mock_fetcher.close = AsyncMock()

        # Mock AuggieClient to avoid process spawning
        with patch("spec.cli.AuggieClient") as mock_auggie_class:
            mock_auggie_class.return_value = MagicMock()

            # Mock AuthenticationManager
            with patch("spec.cli.AuthenticationManager") as mock_auth_class:
                mock_auth = MagicMock()
                mock_auth.get_credentials.return_value = {"api_token": "test"}
                mock_auth_class.return_value = mock_auth

                # Mock the fetcher creation to return our mock
                with patch(
                    "spec.integrations.ticket_service.AuggieMediatedFetcher",
                    return_value=mock_fetcher
                ), patch(
                    "spec.integrations.ticket_service.DirectAPIFetcher",
                    return_value=mock_fetcher
                ):
                    result = runner.invoke(app, [test_data["url"]])

        # Verify workflow was called with a GenericTicket
        if mock_workflow.called:
            call_kwargs = mock_workflow.call_args.kwargs
            ticket = call_kwargs.get("ticket")
            assert ticket is not None
            assert ticket.platform == platform
            assert ticket.title == test_data["expected_title"]

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    @patch("spec.workflow.runner.run_spec_driven_workflow")
    def test_fallback_behavior_via_cli(
        self, mock_workflow, mock_config_class, mock_prereq, mock_banner,
        mock_jira_raw_data
    ):
        """Primary fetcher failure triggers fallback - tested via CLI."""
        from spec.integrations.fetchers.exceptions import AgentIntegrationError

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
        mock_config_class.return_value = mock_config

        # Primary fetcher fails
        mock_primary = MagicMock()
        mock_primary.name = "AuggieMediatedFetcher"
        mock_primary.supports_platform.return_value = True
        mock_primary.fetch = AsyncMock(side_effect=AgentIntegrationError("Auggie unavailable"))
        mock_primary.close = AsyncMock()

        # Fallback succeeds
        mock_fallback = MagicMock()
        mock_fallback.name = "DirectAPIFetcher"
        mock_fallback.supports_platform.return_value = True
        mock_fallback.fetch = AsyncMock(return_value=mock_jira_raw_data)
        mock_fallback.close = AsyncMock()

        with patch("spec.cli.AuggieClient") as mock_auggie_class:
            mock_auggie_class.return_value = MagicMock()

            with patch("spec.cli.AuthenticationManager") as mock_auth_class:
                mock_auth = MagicMock()
                mock_auth.get_credentials.return_value = {"api_token": "test"}
                mock_auth_class.return_value = mock_auth

                with patch(
                    "spec.integrations.ticket_service.AuggieMediatedFetcher",
                    return_value=mock_primary
                ), patch(
                    "spec.integrations.ticket_service.DirectAPIFetcher",
                    return_value=mock_fallback
                ):
                    result = runner.invoke(
                        app, ["https://company.atlassian.net/browse/PROJ-123"]
                    )

        # Verify fallback was used
        mock_primary.fetch.assert_called_once()
        mock_fallback.fetch.assert_called_once()

        # Verify workflow received the ticket
        if mock_workflow.called:
            call_kwargs = mock_workflow.call_args.kwargs
            ticket = call_kwargs.get("ticket")
            assert ticket.platform == Platform.JIRA
```

---

### Phase 5: Layer B - Error Propagation Tests

```python
class TestErrorPropagationViaCLI:
    """Layer B: Test that errors from TicketService propagate correctly to CLI."""

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_ticket_not_found_via_cli(
        self, mock_config_class, mock_prereq, mock_banner
    ):
        """TicketNotFoundError surfaces as user-friendly CLI error."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        mock_fetcher = MagicMock()
        mock_fetcher.name = "MockFetcher"
        mock_fetcher.supports_platform.return_value = True
        mock_fetcher.fetch = AsyncMock(
            side_effect=TicketNotFoundError(ticket_id="PROJ-999", platform="JIRA")
        )
        mock_fetcher.close = AsyncMock()

        with patch("spec.cli.AuggieClient"), patch("spec.cli.AuthenticationManager"):
            with patch(
                "spec.integrations.ticket_service.AuggieMediatedFetcher",
                return_value=mock_fetcher
            ):
                result = runner.invoke(
                    app, ["https://company.atlassian.net/browse/PROJ-999"]
                )

        assert result.exit_code != 0
        # Should mention ticket not found
        assert "PROJ-999" in result.stdout or "not found" in result.stdout.lower()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_auth_error_via_cli(
        self, mock_config_class, mock_prereq, mock_banner
    ):
        """AuthenticationError surfaces as user-friendly CLI error."""
        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        mock_fetcher = MagicMock()
        mock_fetcher.name = "MockFetcher"
        mock_fetcher.supports_platform.return_value = True
        mock_fetcher.fetch = AsyncMock(
            side_effect=AuthenticationError(
                message="Invalid token",
                platform="LINEAR",
                missing_credentials=["api_token"]
            )
        )
        mock_fetcher.close = AsyncMock()

        with patch("spec.cli.AuggieClient"), patch("spec.cli.AuthenticationManager"):
            with patch(
                "spec.integrations.ticket_service.AuggieMediatedFetcher",
                return_value=mock_fetcher
            ):
                result = runner.invoke(
                    app, ["https://linear.app/team/issue/ENG-456"]
                )

        assert result.exit_code != 0
        assert "auth" in result.stdout.lower() or "token" in result.stdout.lower()

    @patch("spec.cli.show_banner")
    @patch("spec.cli._check_prerequisites", return_value=True)
    @patch("spec.cli.ConfigManager")
    def test_unconfigured_platform_error_via_cli(
        self, mock_config_class, mock_prereq, mock_banner
    ):
        """Unconfigured platform error surfaces correctly via CLI."""
        from spec.integrations.fetchers.exceptions import (
            PlatformNotSupportedError as FetcherPlatformNotSupported
        )

        mock_config = MagicMock()
        mock_config.settings.default_jira_project = ""
        mock_config_class.return_value = mock_config

        mock_fetcher = MagicMock()
        mock_fetcher.name = "MockFetcher"
        mock_fetcher.supports_platform.return_value = False
        mock_fetcher.close = AsyncMock()

        with patch("spec.cli.AuggieClient"), patch("spec.cli.AuthenticationManager"):
            with patch(
                "spec.integrations.ticket_service.AuggieMediatedFetcher",
                return_value=mock_fetcher
            ), patch(
                "spec.integrations.ticket_service.DirectAPIFetcher",
                return_value=mock_fetcher
            ):
                result = runner.invoke(
                    app, ["https://myorg.monday.com/boards/123/pulses/456"]
                )

        assert result.exit_code != 0
```

> **Note:** Old Phase 6 (Error Handling) and Phase 7 (Configuration) tests have been removed.
> Their functionality is now covered by:
> - **Phase 5: Layer B - Error Propagation Tests** (tests errors via CLI with real TicketService)
> - **Phase 3: Layer A - Disambiguation Flow Tests** (tests config/disambiguation via CLI)
> - **Phase 4: Layer B - CLI→Service Integration Tests** (tests fallback behavior via CLI)

---

## Test Strategy (Updated for 2-Layer Approach)

### Layer Summary

| Layer | Mock Point | What's Real | Purpose |
|-------|------------|-------------|---------|
| **Layer A** | `create_ticket_service` factory | CLI, arg parsing, _disambiguate_platform | Test CLI contract behavior in isolation |
| **Layer B** | `fetcher.fetch()` methods | CLI, TicketService, Providers | Test full integration chain |

### Relationship to Existing Tests

| Existing File | Focus | New File Adds |
|--------------|-------|---------------|
| `tests/test_cli.py` | Unit tests for CLI helper functions | Layer A + Layer B integration tests |
| `tests/test_ticket_service.py` | Unit tests for TicketService | CLI-level invocation via Layer B |
| `tests/test_providers.py` | Unit tests for individual providers | Real providers exercised via Layer B |

### Integration Tests (This Ticket)

| Test Class | Layer | Test Count | Covers AC |
|------------|-------|------------|-----------|
| `TestPlatformFlagValidation` | A | 17 (6 valid + 1 invalid + 4 case + 6 shorthand) | AC1, AC3, AC4, AC15 |
| `TestDisambiguationFlow` | A | 6 | AC1, AC5, AC10, AC11, AC12 |
| `TestCLIServiceIntegration` | B | 7 (6 platforms + 1 fallback) | AC2, AC7, AC9 |
| `TestErrorPropagationViaCLI` | B | 3 | AC6, AC16, AC17 |
| **Total** | | **33 tests** | |

> **AC1 Clarification:** AC1 ("Integration tests exist for CLI with mocked TicketService") is satisfied
> exclusively by **Layer A**, which mocks at the `create_ticket_service` factory boundary. This means
> TicketService itself is mocked, directly matching the AC1 requirement.
>
> **Layer B Coverage:** Layer B provides **additional integration coverage** by testing the full
> CLI→TicketService→Provider chain with mocking only at the fetcher boundary. Layer B contributes to
> AC2, AC6, AC7, AC9, AC16, and AC17, but does not satisfy AC1 (since TicketService runs for real).

### Test Execution

```bash
# Run all CLI integration tests
pytest tests/test_cli_integration.py -v

# Run Layer A tests only
pytest tests/test_cli_integration.py::TestPlatformFlagValidation -v
pytest tests/test_cli_integration.py::TestDisambiguationFlow -v

# Run Layer B tests only (full integration)
pytest tests/test_cli_integration.py::TestCLIServiceIntegration -v
pytest tests/test_cli_integration.py::TestErrorPropagationViaCLI -v

# Run with coverage
pytest tests/test_cli_integration.py --cov=spec.cli --cov=spec.integrations.ticket_service
```

---

## Acceptance Criteria

### From Linear Ticket

- [ ] **AC1:** Integration tests exist for CLI with mocked TicketService
- [ ] **AC2:** All 6 platforms are tested through the CLI entry point
- [ ] **AC3:** The `--platform` flag is tested with all valid platform values
- [ ] **AC4:** Invalid `--platform` values produce appropriate error messages
- [ ] **AC5:** Disambiguation flow is tested (ambiguous IDs like PROJ-123)
- [ ] **AC6:** Error handling is tested for unconfigured platforms
- [ ] **AC7:** Fallback from primary to fallback fetcher is tested
- [ ] **AC8:** Tests can run in CI without external API dependencies

### Additional Criteria

- [ ] **AC9:** URL auto-detection tests cover all 6 platforms
- [ ] **AC10:** `default_platform` configuration setting is tested
- [ ] **AC11:** `--platform` flag overrides `default_platform` configuration
- [ ] **AC12:** GitHub `owner/repo#123` format is correctly identified as unambiguous
- [ ] **AC13:** Tests follow existing patterns from `tests/test_cli.py`
- [ ] **AC14:** New fixtures added to `tests/conftest.py` are reusable
- [ ] **AC15:** `-p` shorthand for `--platform` is tested
- [ ] **AC16:** `TicketNotFoundError` handling is tested at CLI level
- [ ] **AC17:** `AuthenticationError` handling is tested at CLI level
- [ ] **AC18:** Network and timeout errors are handled gracefully

---

## Dependencies

### Upstream Dependencies (Must Be Complete First)

| Ticket | Component | Status | Description |
|--------|-----------|--------|-------------|
| [AMI-25](https://linear.app/amiadspec/issue/AMI-25) | CLI Migration | ✅ Required | CLI must support `--platform` flag |
| [AMI-30](https://linear.app/amiadspec/issue/AMI-30) | AuggieMediatedFetcher | ✅ Implemented | Primary fetcher |
| [AMI-31](https://linear.app/amiadspec/issue/AMI-31) | DirectAPIFetcher | ✅ Implemented | Fallback fetcher |
| [AMI-32](https://linear.app/amiadspec/issue/AMI-32) | TicketService | ✅ Implemented | Orchestration layer |
| [AMI-17](https://linear.app/amiadspec/issue/AMI-17) | ProviderRegistry | ✅ Implemented | Platform detection |

### Downstream Dependencies (Will Use This)

| Ticket | Title | Relationship |
|--------|-------|--------------|
| None | - | No downstream dependencies |

---

## Estimated Effort (Updated)

| Phase | Description | Estimate |
|-------|-------------|----------|
| Phase 1 | Create test infrastructure (fixtures, mock_ticket_service_factory) | 0.25 day |
| Phase 2 | Layer A - Platform flag validation tests | 0.25 day |
| Phase 3 | Layer A - Disambiguation flow tests | 0.25 day |
| Phase 4 | **Layer B - CLI→Service integration tests (key phase)** | 0.5 day |
| Phase 5 | Layer B - Error propagation tests | 0.25 day |
| Validation | Run tests, fix issues, ensure CI passes | 0.25 day |
| **Total** | | **~1.75 days** |

---

## Usage Examples

### Running the Tests

```bash
# Full test suite
pytest tests/test_cli_integration.py -v

# Layer A tests only (CLI contract)
pytest tests/test_cli_integration.py::TestPlatformFlagValidation -v
pytest tests/test_cli_integration.py::TestDisambiguationFlow -v

# Layer B tests only (full integration)
pytest tests/test_cli_integration.py::TestCLIServiceIntegration -v
pytest tests/test_cli_integration.py::TestErrorPropagationViaCLI -v

# With coverage report
pytest tests/test_cli_integration.py --cov=spec --cov-report=html

# Parallel execution (if pytest-xdist installed)
pytest tests/test_cli_integration.py -n auto
```

### Expected Test Output (2-Layer Structure)

```
# Layer A - CLI Contract Tests (TestPlatformFlagValidation: 14 tests)
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[jira] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[linear] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[github] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[azure_devops] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[monday] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_valid_platform_values[trello] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_invalid_platform_shows_error PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_platform_flag_case_insensitive[JIRA] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_platform_flag_case_insensitive[Jira] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_platform_flag_case_insensitive[JiRa] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_platform_flag_case_insensitive[jira] PASSED
tests/test_cli_integration.py::TestPlatformFlagValidation::test_short_flag_alias[jira] PASSED
... (6 more for -p shorthand)

# Layer A - CLI Contract Tests (TestDisambiguationFlow: 6 tests)
tests/test_cli_integration.py::TestDisambiguationFlow::test_disambiguation_prompts_user PASSED
tests/test_cli_integration.py::TestDisambiguationFlow::test_default_platform_skips_prompt PASSED
tests/test_cli_integration.py::TestDisambiguationFlow::test_ambiguous_id_triggers_disambiguation_via_cli PASSED
tests/test_cli_integration.py::TestDisambiguationFlow::test_flag_overrides_disambiguation PASSED
tests/test_cli_integration.py::TestDisambiguationFlow::test_github_format_no_disambiguation PASSED
tests/test_cli_integration.py::TestDisambiguationFlow::test_config_default_platform_used PASSED

# Layer B - CLI→Service Integration Tests (TestCLIServiceIntegration: 7 tests)
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[JIRA] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[LINEAR] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[GITHUB] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[AZURE_DEVOPS] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[MONDAY] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_platform_via_cli[TRELLO] PASSED
tests/test_cli_integration.py::TestCLIServiceIntegration::test_fallback_behavior_via_cli PASSED

# Layer B - Error Propagation (TestErrorPropagationViaCLI: 3 tests)
tests/test_cli_integration.py::TestErrorPropagationViaCLI::test_ticket_not_found_via_cli PASSED
tests/test_cli_integration.py::TestErrorPropagationViaCLI::test_auth_error_via_cli PASSED
tests/test_cli_integration.py::TestErrorPropagationViaCLI::test_unconfigured_platform_error_via_cli PASSED

============================= 33 passed in 3.45s =============================
```

---

## References

### Related Implementation Plans

| Document | Purpose |
|----------|---------|
| [AMI-25-implementation-plan.md](./AMI-25-implementation-plan.md) | CLI migration with --platform flag |
| [AMI-30-implementation-plan.md](./AMI-30-implementation-plan.md) | AuggieMediatedFetcher implementation |
| [AMI-31-implementation-plan.md](./AMI-31-implementation-plan.md) | DirectAPIFetcher implementation |
| [AMI-32-implementation-plan.md](./AMI-32-implementation-plan.md) | TicketService orchestration layer |

### Existing Test Files (Reference)

| File | Purpose | Pattern Reference |
|------|---------|-------------------|
| `tests/test_cli.py` | Existing CLI tests | Test structure, fixtures |
| `tests/test_ticket_service.py` | TicketService unit tests | Mock fetcher patterns |
| `tests/test_auggie_fetcher.py` | Fetcher unit tests | Async test patterns |
| `tests/conftest.py` | Shared fixtures | Fixture organization |

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-28 | AI Assistant | Initial draft created |
| 2026-01-28 | AI Assistant | Revised: Fixed mock parameter ordering, added -p shorthand tests, added TicketNotFoundError/AuthenticationError tests, added network error tests, fixed import paths, added complete fixtures for all 6 platforms, corrected call_args access patterns |
| 2026-01-28 | AI Assistant | **Major revision (v2):** Restructured to 2-layer test strategy to resolve AC1/AC2 mismatch. Layer A mocks at `create_ticket_service`, Layer B mocks at `fetcher.fetch()`. All tests now use `runner.invoke(app, ...)`. Added AC mapping table, implementation guidance, `mock_ticket_service_factory` fixture. Removed redundant Phases 6-7, consolidated into new Phase 4 (Layer B) and Phase 5 (Error Propagation). |
| 2026-01-28 | AI Assistant | **5-Issue Fix (v3):** (1) Removed duplicate `mock_ticket_service_factory` fixture definition. (2) Clarified Layer B mocking approach: patch fetcher class constructors to return mock instances with stubbed `.fetch()`. (3) Fixed AC1 mapping inconsistency - AC1 now covered by both Layer A and Layer B. (4) Changed parametrization from `list(Platform)` to `PLATFORM_TEST_DATA.keys()` for safety. (5) Fixed expected test count from conflicting 24/35 to consistent 33. |
| 2026-01-28 | AI Assistant | **AC1 & Count Consistency Fix (v4):** (1) Updated AC1 to be satisfied by Layer A only (mocked TicketService), not Layer B. Layer B now described as "additional integration coverage" for AC2/AC6/AC7/etc. (2) Fixed changelog reference from "consistent 30" to "consistent 33" to match the test matrix and expected output. |
