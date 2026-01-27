# Implementation Plan: AMI-29 - TicketFetcher Abstraction & AgentMediatedFetcher

**Ticket:** [AMI-29](https://linear.app/amiadspec/issue/AMI-29/implement-ticketfetcher-abstraction-and-agentmediatedfetcher-base)
**Status:** Draft
**Date:** 2026-01-23

---

## Summary

This ticket implements the foundational `TicketFetcher` abstract base class and `AgentMediatedFetcher` base implementation, which together form the core of the hybrid ticket fetching architecture. This abstraction separates **how to fetch data** (fetching strategy) from **how to normalize data** (provider responsibility), enabling flexible ticket retrieval from multiple sources:

1. **Agent-mediated fetching** - Leverages AI agent's MCP integrations (e.g., Auggie with Jira MCP)
2. **Direct API fetching** - Falls back to direct HTTP calls (future AMI-28)

---

## Technical Approach

### Architecture Fit

The new `TicketFetcher` abstraction **complements** the existing `IssueTrackerProvider` interface:

```
┌─────────────────────────────────────┐
│         IssueTrackerProvider        │  ← Handles platform-specific normalization
│   (existing in providers/base.py)   │     and data mapping to GenericTicket
└─────────────────────────────────────┘
                  │
                  │ uses
                  ▼
┌─────────────────────────────────────┐
│           TicketFetcher ABC         │  ← NEW: Handles HOW to fetch raw data
│       (fetchers/base.py)            │     Independent of platform normalization
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │   AgentMediatedFetcher (base)   │ │  ← NEW: Base for agent-mediated fetching
│ │   - Prompt building             │ │     Uses AI agent's tool integrations
│ │   - JSON parsing                │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
┌───────────────┐   ┌───────────────┐
│ AuggieFetcher │   │DirectAPIFetcher│
│   (AMI-27)    │   │   (AMI-28)    │
└───────────────┘   └───────────────┘
```

### Key Design Decisions

1. **Async Interface** - Uses `async def` for future HTTP client compatibility
2. **Platform Enum Reuse** - Leverages existing `Platform` enum from `providers/base.py`
3. **Separation of Concerns** - Fetchers only return raw `dict`, normalization stays in providers
4. **Robust JSON Parsing** - Handles markdown code blocks, bare JSON, and edge cases

---

## Components to Create

### New Directory: `spec/integrations/fetchers/`

| File | Purpose |
|------|---------|
| `__init__.py` | Package exports |
| `base.py` | `TicketFetcher` ABC + `AgentMediatedFetcher` base class |
| `exceptions.py` | Custom exceptions: `TicketFetchError`, `PlatformNotSupportedError`, `AgentIntegrationError` |

---

## Implementation Steps

### Step 1: Create Exceptions Module
**File:** `spec/integrations/fetchers/exceptions.py`

Create custom exception hierarchy:
- `TicketFetchError` - Base exception
- `PlatformNotSupportedError` - Fetcher doesn't support requested platform
- `AgentIntegrationError` - Agent integration failure

### Step 2: Create Base Module
**File:** `spec/integrations/fetchers/base.py`

Implement:
1. `TicketFetcher` ABC with:
   - `fetch_raw(ticket_id, platform) -> dict` - Abstract async method
   - `supports_platform(platform) -> bool` - Abstract method
   - `name` property - Human-readable fetcher name

2. `AgentMediatedFetcher` base class with:
   - `_execute_fetch_prompt(prompt, platform) -> str` - Abstract method (subclass implements agent call)
   - `fetch_raw()` - Concrete implementation using prompt-based fetching
   - `_build_prompt(ticket_id, platform) -> str` - Construct structured prompt
   - `_get_prompt_template(platform) -> str` - Abstract method for platform-specific templates
   - `_parse_response(response) -> dict` - Robust JSON extraction from agent response

### Step 3: Create Package Init
**File:** `spec/integrations/fetchers/__init__.py`

Export all public classes and exceptions.

### Step 4: Add Unit Tests
**File:** `tests/test_fetchers_base.py`

Test coverage for:
- JSON parsing edge cases (bare JSON, markdown blocks, nested structures)
- Platform support checking
- Error handling
- Abstract method contracts

---

## File Changes Detail

### New: `spec/integrations/fetchers/exceptions.py`
```python
class TicketFetchError(Exception):
    """Base exception for ticket fetch failures."""
    pass

class PlatformNotSupportedError(TicketFetchError):
    """Raised when fetcher doesn't support the requested platform."""
    pass

class AgentIntegrationError(TicketFetchError):
    """Raised when agent integration fails."""
    pass
```

### New: `spec/integrations/fetchers/base.py`
- Import `Platform` from `spec.integrations.providers.base`
- Define `TicketFetcher` ABC with async `fetch_raw()` method
- Define `AgentMediatedFetcher` with prompt building and JSON parsing logic

### New: `spec/integrations/fetchers/__init__.py`
```python
from spec.integrations.fetchers.base import (
    TicketFetcher,
    AgentMediatedFetcher,
)
from spec.integrations.fetchers.exceptions import (
    TicketFetchError,
    PlatformNotSupportedError,
    AgentIntegrationError,
)

__all__ = [
    "TicketFetcher",
    "AgentMediatedFetcher",
    "TicketFetchError",
    "PlatformNotSupportedError",
    "AgentIntegrationError",
]
```

---

## Testing Strategy

### Unit Tests (`tests/test_fetchers_base.py`)

1. **JSON Parsing Tests**
   - Bare JSON object: `{"key": "value"}`
   - Markdown code block: ` ```json\n{...}\n``` `
   - Markdown without language hint: ` ```\n{...}\n``` `
   - Nested JSON with code blocks
   - Invalid JSON handling

2. **AgentMediatedFetcher Contract Tests**
   - Mock subclass implementation
   - Verify `_execute_fetch_prompt` is called with correct prompt
   - Verify `PlatformNotSupportedError` raised when platform not supported

3. **TicketFetcher ABC Tests**
   - Cannot instantiate directly
   - Subclass must implement abstract methods

---

## Acceptance Criteria Checklist

- [ ] `TicketFetcher` ABC with `fetch_raw()` and `supports_platform()` methods
- [ ] `AgentMediatedFetcher` base class with prompt building and JSON parsing
- [ ] Robust JSON extraction from agent responses (handles code blocks)
- [ ] Custom exceptions for fetch errors
- [ ] Async interface (for future HTTP client compatibility)
- [ ] Type hints and docstrings for all public methods
- [ ] Unit tests for JSON parsing edge cases
- [ ] Package exports in `__init__.py`
