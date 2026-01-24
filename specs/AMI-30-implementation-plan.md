# Implementation Plan: AMI-30 - Implement AuggieMediatedFetcher with Structured JSON Prompts

**Ticket:** [AMI-30](https://linear.app/amiadspec/issue/AMI-30/implement-auggiemediatedfetcher-with-structured-json-prompts)
**Status:** Draft
**Date:** 2026-01-24

---

## Summary

This ticket implements the `AuggieMediatedFetcher` class that fetches ticket data through the Auggie agent's native MCP integrations. This is the **primary path** for fetching tickets when running in Auggie-enabled environments.

The fetcher extends `AgentMediatedFetcher` (implemented in AMI-29) and implements:
1. **Platform-specific prompt templates** - Structured JSON prompts for Jira, Linear, and GitHub
2. **Auggie tool execution** - Integration with `AuggieClient` for MCP tool invocations
3. **Platform support checking** - Uses `AgentConfig.supports_platform()` from AMI-33

---

## Technical Approach

### Architecture Fit

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TicketFetcher (ABC)                                │
│                      (spec/integrations/fetchers/base.py)                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                     ▲
                                     │ extends
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AgentMediatedFetcher (base)                            │
│   - _build_prompt(ticket_id, platform) → str                                │
│   - _parse_response(response) → dict  (robust JSON extraction)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                     ▲
                                     │ extends
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AuggieMediatedFetcher ← THIS TICKET                     │
│                                                                             │
│   - _execute_fetch_prompt(prompt, platform) → str                           │
│   - _get_prompt_template(platform) → str                                    │
│   - supports_platform(platform) → bool                                      │
│   - name → "Auggie MCP Fetcher"                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integration with Auggie MCP Tools

The fetcher uses `AuggieClient.run_print_quiet()` to invoke Auggie with structured prompts that instruct it to use its native MCP tools:

| Platform | Auggie MCP Tool | Prompt Strategy |
|----------|-----------------|-----------------|
| Jira | `jira` | Fetch issue by key, return JSON with standard fields |
| Linear | `linear` | Fetch issue by identifier, return JSON |
| GitHub | `github-api` | Fetch issue/PR by number from repo, return JSON |

### Key Design Decisions

1. **AuggieClient Injection** - Client is injected via constructor for testability
2. **ConfigManager Integration** - Uses `AgentConfig.supports_platform()` to check MCP availability
3. **Async Wrapper** - Wraps synchronous `AuggieClient.run_print_quiet()` in async for interface compliance
4. **Structured Prompts** - Prompts instruct Auggie to return **only** JSON for reliable parsing

---

## Components to Create

### New File: `spec/integrations/fetchers/auggie_fetcher.py`

| Component | Purpose |
|-----------|---------|
| `AuggieMediatedFetcher` class | Fetches tickets via Auggie's MCP integrations |
| `PLATFORM_PROMPT_TEMPLATES` dict | Platform-specific prompt templates |
| `SUPPORTED_PLATFORMS` set | Platforms supported by Auggie MCP |

### Modified Files

| File | Changes |
|------|---------|
| `spec/integrations/fetchers/__init__.py` | Export `AuggieMediatedFetcher` |

---

## Implementation Steps

### Step 1: Create Auggie Fetcher Module
**File:** `spec/integrations/fetchers/auggie_fetcher.py`

Implement `AuggieMediatedFetcher` class extending `AgentMediatedFetcher`:

```python
from typing import Any
from spec.config import ConfigManager
from spec.config.fetch_config import AgentConfig
from spec.integrations.auggie import AuggieClient
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.providers.base import Platform

# Platforms that Auggie can access via MCP tools
SUPPORTED_PLATFORMS = {Platform.JIRA, Platform.LINEAR, Platform.GITHUB}

class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie's native MCP integrations."""

    def __init__(
        self,
        auggie_client: AuggieClient,
        config_manager: ConfigManager | None = None,
    ):
        self._auggie = auggie_client
        self._config = config_manager

    @property
    def name(self) -> str:
        return "Auggie MCP Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        # Check if platform is in our supported set
        if platform not in SUPPORTED_PLATFORMS:
            return False
        # If config available, also check agent integration config
        if self._config:
            agent_config = self._config.get_agent_config()
            return agent_config.supports_platform(platform.name.lower())
        return True  # Default: assume support if no config

    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        # AuggieClient is synchronous - wrap for async interface
        result = self._auggie.run_print_quiet(prompt)
        return result.stdout if result.returncode == 0 else ""

    def _get_prompt_template(self, platform: Platform) -> str:
        return PLATFORM_PROMPT_TEMPLATES.get(platform, "")
```

### Step 2: Define Platform-Specific Prompt Templates
**File:** `spec/integrations/fetchers/auggie_fetcher.py`

Design structured prompts that:
1. Tell Auggie to use the appropriate MCP tool
2. Request specific fields in JSON format
3. Instruct Auggie to respond with **only** the JSON (no markdown, no explanation)

```python
PLATFORM_PROMPT_TEMPLATES = {
    Platform.JIRA: """Use your Jira tool to fetch issue {ticket_id}.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "key": "PROJ-123",
  "summary": "ticket title",
  "description": "full description text",
  "status": "Open|In Progress|Done|etc",
  "issuetype": "Bug|Story|Task|etc",
  "assignee": "username or null",
  "labels": ["label1", "label2"],
  "created": "ISO datetime",
  "updated": "ISO datetime",
  "priority": "High|Medium|Low|etc",
  "project": {{ "key": "PROJ", "name": "Project Name" }}
}}""",

    Platform.LINEAR: """Use your Linear tool to fetch issue {ticket_id}.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "identifier": "TEAM-123",
  "title": "issue title",
  "description": "full description text",
  "state": {{ "name": "Todo|In Progress|Done|etc" }},
  "assignee": {{ "name": "username" }} or null,
  "labels": {{ "nodes": [{{ "name": "label1" }}] }},
  "createdAt": "ISO datetime",
  "updatedAt": "ISO datetime",
  "priority": 1-4,
  "team": {{ "key": "TEAM" }},
  "url": "https://linear.app/..."
}}""",

    Platform.GITHUB: """Use your GitHub API tool to fetch issue or PR {ticket_id}.

The ticket_id format is "owner/repo#number" (e.g., "microsoft/vscode#12345").

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "number": 123,
  "title": "issue/PR title",
  "body": "full description text",
  "state": "open|closed",
  "user": {{ "login": "username" }},
  "labels": [{{ "name": "label1" }}],
  "created_at": "ISO datetime",
  "updated_at": "ISO datetime",
  "html_url": "https://github.com/...",
  "milestone": {{ "title": "v1.0" }} or null,
  "assignee": {{ "login": "username" }} or null
}}""",
}


### Step 3: Update Package Exports
**File:** `spec/integrations/fetchers/__init__.py`

Add export for `AuggieMediatedFetcher`:

```python
from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher

__all__ = [
    # ... existing exports ...
    "AuggieMediatedFetcher",
]
```

### Step 4: Add Unit Tests
**File:** `tests/test_auggie_fetcher.py`

Create comprehensive tests with mocked `AuggieClient`.

---

## File Changes Detail

### New: `spec/integrations/fetchers/auggie_fetcher.py`

Complete module structure:

```python
"""Auggie-mediated ticket fetcher using MCP integrations.

This module provides the AuggieMediatedFetcher class that fetches
ticket data through Auggie's native MCP tool integrations for
Jira, Linear, and GitHub.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from spec.config import ConfigManager
from spec.integrations.auggie import AuggieClient
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.fetchers.exceptions import AgentIntegrationError
from spec.integrations.providers.base import Platform

logger = logging.getLogger(__name__)

# Platforms supported by Auggie MCP integrations
SUPPORTED_PLATFORMS = {Platform.JIRA, Platform.LINEAR, Platform.GITHUB}

# Platform-specific prompt templates for structured JSON responses
PLATFORM_PROMPT_TEMPLATES: dict[Platform, str] = {
    Platform.JIRA: """...""",  # See Step 2 for full templates
    Platform.LINEAR: """...""",
    Platform.GITHUB: """...""",
}


class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie's native MCP integrations.

    This fetcher delegates to Auggie's built-in tool calls for platforms
    like Jira, Linear, and GitHub. It's the primary fetch path when
    running in an Auggie-enabled environment.

    Attributes:
        _auggie: AuggieClient for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
    """

    def __init__(
        self,
        auggie_client: AuggieClient,
        config_manager: ConfigManager | None = None,
    ) -> None:
        """Initialize with Auggie client and optional config.

        Args:
            auggie_client: Client for Auggie CLI invocations
            config_manager: Optional ConfigManager for checking integrations
        """
        self._auggie = auggie_client
        self._config = config_manager

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Auggie MCP Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        """Check if Auggie has integration for this platform.

        First checks if platform is in SUPPORTED_PLATFORMS, then
        consults AgentConfig if ConfigManager is available.

        Args:
            platform: Platform enum value to check

        Returns:
            True if Auggie can fetch from this platform
        """
        if platform not in SUPPORTED_PLATFORMS:
            return False

        if self._config:
            agent_config = self._config.get_agent_config()
            return agent_config.supports_platform(platform.name.lower())

        # Default: assume support if no config to check against
        return True

    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        """Execute fetch prompt via Auggie CLI.

        Uses run_print_quiet() for non-interactive execution that
        captures the response for JSON parsing.

        Args:
            prompt: Structured prompt to send to Auggie
            platform: Target platform (for logging/context)

        Returns:
            Raw response string from Auggie

        Raises:
            AgentIntegrationError: If Auggie invocation fails
        """
        logger.debug("Executing Auggie fetch for %s", platform.name)

        try:
            # run_print_quiet is synchronous - run in executor for async
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._auggie.run_print_quiet(prompt),
            )
        except Exception as e:
            raise AgentIntegrationError(
                message=f"Auggie CLI invocation failed: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            raise AgentIntegrationError(
                message=f"Auggie returned non-zero exit code: {error_msg}",
                agent_name=self.name,
            )

        return result.stdout

    def _get_prompt_template(self, platform: Platform) -> str:
        """Get the prompt template for the given platform.

        Args:
            platform: Platform to get template for

        Returns:
            Prompt template string with {ticket_id} placeholder

        Raises:
            AgentIntegrationError: If platform has no template
        """
        template = PLATFORM_PROMPT_TEMPLATES.get(platform)
        if not template:
            raise AgentIntegrationError(
                message=f"No prompt template for platform: {platform.name}",
                agent_name=self.name,
            )
        return template
```

### Modified: `spec/integrations/fetchers/__init__.py`

```python
"""Ticket fetchers package."""

from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher
from spec.integrations.fetchers.base import (
    AgentMediatedFetcher,
    TicketFetcher,
)
from spec.integrations.fetchers.exceptions import (
    AgentIntegrationError,
    PlatformNotSupportedError,
    TicketFetchError,
)

__all__ = [
    "AgentMediatedFetcher",
    "AuggieMediatedFetcher",
    "TicketFetcher",
    "TicketFetchError",
    "PlatformNotSupportedError",
    "AgentIntegrationError",
]
```


---

## Testing Strategy

### Unit Tests (`tests/test_auggie_fetcher.py`)

1. **Instantiation Tests**
   - `test_init_with_auggie_client_only` - Client-only initialization
   - `test_init_with_config_manager` - With ConfigManager
   - `test_name_property` - Returns "Auggie MCP Fetcher"

2. **Platform Support Tests**
   - `test_supports_platform_jira` - Jira is supported
   - `test_supports_platform_linear` - Linear is supported
   - `test_supports_platform_github` - GitHub is supported
   - `test_supports_platform_unsupported` - Azure DevOps, Trello, Monday return False
   - `test_supports_platform_with_config_disabled` - Respects AgentConfig.supports_platform()
   - `test_supports_platform_no_config_defaults_true` - No config = assume supported

3. **Prompt Template Tests**
   - `test_get_prompt_template_jira` - Returns Jira template with {ticket_id}
   - `test_get_prompt_template_linear` - Returns Linear template
   - `test_get_prompt_template_github` - Returns GitHub template
   - `test_get_prompt_template_unsupported_raises` - AgentIntegrationError for unknown platform

4. **Execute Fetch Prompt Tests**
   - `test_execute_fetch_prompt_success` - Returns stdout on success
   - `test_execute_fetch_prompt_nonzero_exit` - Raises AgentIntegrationError
   - `test_execute_fetch_prompt_exception` - Wraps exceptions in AgentIntegrationError
   - `test_execute_fetch_prompt_runs_in_executor` - Async wrapper works

5. **Integration Tests (fetch_raw)**
   - `test_fetch_raw_jira_success` - Full flow with mocked Auggie returning JSON
   - `test_fetch_raw_linear_success` - Linear ticket fetch
   - `test_fetch_raw_github_success` - GitHub issue fetch
   - `test_fetch_raw_unsupported_platform` - Raises PlatformNotSupportedError
   - `test_fetch_raw_parses_json_from_response` - Inherited _parse_response works
   - `test_fetch_raw_handles_markdown_code_blocks` - JSON in ```json blocks

### Mock Strategy

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import subprocess

@pytest.fixture
def mock_auggie_client():
    """Create a mock AuggieClient."""
    client = MagicMock(spec=AuggieClient)
    # Default: successful response with JSON
    client.run_print_quiet.return_value = subprocess.CompletedProcess(
        args=["auggie"],
        returncode=0,
        stdout='{"key": "PROJ-123", "summary": "Test issue"}',
        stderr="",
    )
    return client

@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager with Jira/Linear enabled."""
    config = MagicMock(spec=ConfigManager)
    agent_config = MagicMock()
    agent_config.supports_platform.side_effect = lambda p: p in ["jira", "linear"]
    config.get_agent_config.return_value = agent_config
    return config
```

### Manual Integration Test

A manual integration test should verify end-to-end functionality:

```bash
# Test with real Auggie (requires Jira MCP integration configured)
python -c "
import asyncio
from spec.integrations.auggie import AuggieClient
from spec.integrations.fetchers import AuggieMediatedFetcher
from spec.integrations.providers.base import Platform

async def test():
    client = AuggieClient()
    fetcher = AuggieMediatedFetcher(client)
    result = await fetcher.fetch_raw('PROJ-123', Platform.JIRA)
    print(result)

asyncio.run(test())
"
```

---

## Migration Considerations

### Backward Compatibility

- **No breaking changes** - This is a new module with no existing dependents
- Existing `spec/integrations/jira.py` remains unchanged (legacy path)
- Future tickets (AMI-32: TicketService) will integrate with this fetcher

### Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| `TicketFetcher` ABC | ✅ Implemented (AMI-29) | `spec/integrations/fetchers/base.py` |
| `AgentMediatedFetcher` | ✅ Implemented (AMI-29) | `spec/integrations/fetchers/base.py` |
| `AuggieClient` | ✅ Implemented | `spec/integrations/auggie.py` |
| `ConfigManager.get_agent_config()` | ✅ Implemented (AMI-33) | `spec/config/manager.py` |
| `AgentConfig.supports_platform()` | ✅ Implemented (AMI-33) | `spec/config/fetch_config.py` |
| `Platform` enum | ✅ Implemented | `spec/integrations/providers/base.py` |

### Downstream Dependents (Future)

- **AMI-32:** `TicketService` uses `AuggieMediatedFetcher` as primary fetcher
- **CLI Integration:** `specflow/cli.py` will use TicketService for ticket fetching

### Relationship with ProviderRegistry

Per the architecture note in the ticket comments:

```
1. ProviderRegistry.get_provider_for_input() → returns IssueTrackerProvider
2. Provider uses TicketFetcher (this class) to get raw data
3. Provider normalizes raw data to GenericTicket
```

Fetchers are used **BY providers** via `TicketService`, not directly through `ProviderRegistry`.

---

## Acceptance Criteria Checklist

From the ticket:

- [ ] `AuggieMediatedFetcher` class extending `AgentMediatedFetcher`
- [ ] `supports_platform()` uses `AgentConfig.supports_platform()` from AMI-33
- [ ] `_execute_fetch_prompt()` invokes Auggie CLI via `run_print_quiet()`
- [ ] `_get_prompt_template()` returns platform-specific structured JSON prompts
- [ ] Platform support for Jira, Linear, GitHub
- [ ] Error handling for unsupported platforms (`PlatformNotSupportedError`)
- [ ] Error handling for Auggie CLI failures (`AgentIntegrationError`)
- [ ] Async interface compliance (wraps sync Auggie calls)
- [ ] Unit tests with mocked `AuggieClient`
- [ ] Integration test with real Auggie (manual)
- [ ] Exports added to `fetchers/__init__.py`
- [ ] Type hints and docstrings for all public methods

---

## Example Usage

### Basic Usage (Future TicketService Integration)

```python
from spec.config import ConfigManager
from spec.integrations.auggie import AuggieClient
from spec.integrations.fetchers import AuggieMediatedFetcher
from spec.integrations.providers.base import Platform

# Create fetcher with dependencies
config_manager = ConfigManager()
auggie_client = AuggieClient()
fetcher = AuggieMediatedFetcher(auggie_client, config_manager)

# Check platform support
if fetcher.supports_platform(Platform.JIRA):
    # Fetch raw ticket data
    raw_data = await fetcher.fetch_raw("PROJ-123", Platform.JIRA)
    # Returns: {"key": "PROJ-123", "summary": "...", ...}
```

### With TicketService (AMI-32)

```python
class TicketService:
    def __init__(
        self,
        primary_fetcher: TicketFetcher,
        fallback_fetcher: TicketFetcher | None = None,
    ):
        self._primary = primary_fetcher
        self._fallback = fallback_fetcher

    async def get_ticket(self, input_str: str) -> GenericTicket:
        # 1. Detect platform and get provider
        provider = ProviderRegistry.get_provider_for_input(input_str)
        ticket_id = provider.parse_input(input_str)
        platform = provider.platform

        # 2. Fetch raw data using fetcher
        raw_data = await self._primary.fetch_raw(ticket_id, platform)

        # 3. Provider normalizes to GenericTicket
        return provider.normalize(raw_data)
```
