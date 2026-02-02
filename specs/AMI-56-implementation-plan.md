# Implementation Plan: AMI-56 - Phase 1.5.1: Update AuggieMediatedFetcher

**Ticket:** [AMI-56](https://linear.app/amiadspec/issue/AMI-56/phase-151-update-auggiemediatedfetcher)
**Status:** Draft
**Date:** 2026-02-02
**Labels:** MultiAgent
**Parent:** [AMI-55: Phase 1.5 - Fetcher Refactoring](https://linear.app/amiadspec/issue/AMI-55)

---

## Summary

This ticket updates the `AuggieMediatedFetcher` class to accept an `AIBackend` instance instead of the concrete `AuggieClient`. This is a key step in the Phase 1.5 Fetcher Refactoring effort, enabling the fetcher to work with any AI backend that implements the `AIBackend` protocol.

**Why This Matters:**
- Decouples the fetcher from the concrete `AuggieClient` implementation
- Enables future support for other backends (Claude, Cursor) without fetcher changes
- Aligns with the pluggable multi-agent architecture from Phase 1 (AMI-47 through AMI-53)
- Parameter names are standardized to match the `AIBackend` protocol (`dont_save_session` instead of `no_session`)

**Scope:**
- Update `spec/integrations/fetchers/auggie_fetcher.py`:
  - Change constructor signature: `AuggieClient` → `AIBackend`
  - Update internal attribute: `self._auggie` → `self._backend`
  - Update `_execute_fetch_prompt()` to use `self._backend.run_print_quiet()`
  - Update error messages to be backend-agnostic
  - Update module docstring for backend-agnostic language
  - Preserve async execution pattern and timeout handling
- Update existing tests to use `AIBackend` mock

**Reference:** `specs/Pluggable Multi-Agent Support.md` - Phase 1.5.1 (lines 2067-2109)

> **⚠️ Parent Spec Discrepancy:** The parent specification shows `run_print_quiet()` returning `tuple[bool, str]`, but the actual `AIBackend` protocol returns `str` only. This implementation plan follows the **actual protocol definition** in `spec/integrations/backends/base.py`.

---

## Context

This is **Phase 1.5.1** of the Fetcher Refactoring work (AMI-55), which is part of the broader Backend Infrastructure effort (AMI-45).

### Related Phase Ordering

| Phase | Ticket | Description | Status |
|-------|--------|-------------|--------|
| 1.1 | AMI-47 | Backend Error Types | ✅ Done |
| 1.2 | AMI-48 | AIBackend Protocol | ✅ Done |
| 1.3 | AMI-49 | BaseBackend Abstract Class | ✅ Done |
| 1.4 | AMI-50 | Move Subagent Constants | ✅ Done |
| 1.5 | AMI-51 | Create AuggieBackend | ✅ Done |
| 1.6 | AMI-52 | Create Backend Factory | ✅ Done |
| 1.7 | AMI-53 | Create Backend Platform Resolver | ✅ Done |
| **1.5.1** | **AMI-56** | **Update AuggieMediatedFetcher** | **← This Ticket** |
| 1.5.2 | AMI-57 | Update ticket_service.py | ⏳ Pending |

> **⚠️ Pre-Implementation Verification Required:** Before starting this ticket, verify that `AIBackend` protocol and `AuggieBackend` exist. Run:
> ```bash
> python -c "from spec.integrations.backends import AIBackend, AuggieBackend; print('Dependencies available')"
> ```

### Position in Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AuggieMediatedFetcher (BEFORE)                         │
│   spec/integrations/fetchers/auggie_fetcher.py                               │
│                                                                              │
│   def __init__(self, auggie_client: AuggieClient, ...):                     │
│       self._auggie = auggie_client                                           │
│                                                                              │
│   async def _execute_fetch_prompt(self, prompt, platform, timeout):         │
│       result = self._auggie.run_print_quiet(prompt, dont_save_session=True) │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ refactors to
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AuggieMediatedFetcher (AFTER)                          │
│   spec/integrations/fetchers/auggie_fetcher.py                               │
│                                                                              │
│   def __init__(self, backend: AIBackend, ...):                              │
│       self._backend = backend                                                │
│                                                                              │
│   async def _execute_fetch_prompt(self, prompt, platform, timeout):         │
│       result = self._backend.run_print_quiet(prompt, dont_save_session=True)│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key API Differences

| Aspect | AuggieClient | AIBackend Protocol |
|--------|--------------|-------------------|
| Session parameter | `dont_save_session=True` | `dont_save_session=True` ✅ (same) |
| Method signature | `run_print_quiet(prompt, dont_save_session=...)` | `run_print_quiet(prompt, *, subagent=None, model=None, dont_save_session=False, timeout_seconds=None)` |
| Return type | `str` | `str` |
| Timeout | Not built-in (asyncio wrapper) | `timeout_seconds` parameter available |

The `AIBackend.run_print_quiet()` signature is a **superset** of the current usage, so existing calls are compatible.

---

## Current State Analysis

### Existing Implementation (`spec/integrations/fetchers/auggie_fetcher.py`)

**Constructor (lines 138-153):**
```python
def __init__(
    self,
    auggie_client: AuggieClient,
    config_manager: ConfigManager | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    self._auggie = auggie_client
    self._config = config_manager
    self._timeout_seconds = timeout_seconds
```

**Execution method (lines 250-316):**
```python
async def _execute_fetch_prompt(
    self,
    prompt: str,
    platform: Platform,
    timeout_seconds: float | None = None,
) -> str:
    # ...
    result = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: self._auggie.run_print_quiet(prompt, dont_save_session=True),
        ),
        timeout=effective_timeout,
    )
    # ...
    return result
```

**TYPE_CHECKING imports (lines 38-40):**
```python
if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auggie import AuggieClient
```

> **✅ Important Note:** The current implementation already uses `dont_save_session=True` (line 292), **not** `no_session=True` as shown in some parent spec snippets (lines 4012). This means **no parameter name change is needed** - only the variable name changes from `self._auggie` to `self._backend`. The Linear ticket description mentioning `no_session` → `dont_save_session` is outdated.

---

## Technical Approach

### Changes Overview

1. **Update imports**: Add `AIBackend` import, remove `AuggieClient` from TYPE_CHECKING
2. **Update constructor signature**: `auggie_client: AuggieClient` → `backend: AIBackend`
3. **Update internal attribute**: `self._auggie` → `self._backend`
4. **Update `_execute_fetch_prompt()`**: Use `self._backend.run_print_quiet()`
5. **Preserve async pattern**: Keep the `asyncio.wait_for()` wrapper for timeout enforcement

### Design Decisions

1. **Keep asyncio timeout wrapper**: Although `AIBackend.run_print_quiet()` has a `timeout_seconds` parameter, we keep the asyncio-level timeout for consistency with the current behavior and to avoid breaking changes.

2. **Remove AuggieClient import**: Since we now accept `AIBackend`, there's no need to import `AuggieClient` at all.

3. **Preserve ConfigManager**: The `ConfigManager` parameter remains for checking agent platform support.

4. **Backend-agnostic naming**: Despite the class name `AuggieMediatedFetcher`, it can now work with any `AIBackend`. The class name is preserved for backwards compatibility.

5. **Preserve `name` property**: The `name` property returns `"Auggie MCP Fetcher"` (hardcoded). This is preserved for backwards compatibility. Future work could make this dynamic (e.g., `f"{self._backend.name} MCP Fetcher"`), but that is out of scope for this ticket.

6. **Preserve `_build_prompt()` method**: This method is inherited from `AgentMediatedFetcher` base class and does not require changes. It uses `_get_prompt_template()` which is platform-specific, not backend-specific.

7. **Update error messages**: Error messages in `_execute_fetch_prompt()` are updated from "Auggie CLI" to "Backend" for consistency with the backend-agnostic design.

---

## Implementation Phases

### Phase 1: Update Imports (~5 minutes)

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

Update the TYPE_CHECKING block and add runtime import for AIBackend:

```python
# BEFORE (lines 38-40):
if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auggie import AuggieClient

# AFTER:
from spec.integrations.backends.base import AIBackend

if TYPE_CHECKING:
    from spec.config import ConfigManager
```

**Note:** The `AuggieClient` import is completely removed since we now accept `AIBackend`.

### Phase 2: Update Constructor (~5 minutes)

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

Update constructor signature and attribute:

```python
# BEFORE:
def __init__(
    self,
    auggie_client: AuggieClient,
    config_manager: ConfigManager | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Initialize with Auggie client and optional config.

    Args:
        auggie_client: Client for Auggie CLI invocations
        config_manager: Optional ConfigManager for checking integrations
        timeout_seconds: Timeout for agent execution (default: 60s)
    """
    self._auggie = auggie_client
    self._config = config_manager
    self._timeout_seconds = timeout_seconds

# AFTER:
def __init__(
    self,
    backend: AIBackend,
    config_manager: ConfigManager | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Initialize with AI backend and optional config.

    Args:
        backend: AI backend instance (AuggieBackend, ClaudeBackend, etc.)
        config_manager: Optional ConfigManager for checking integrations
        timeout_seconds: Timeout for agent execution (default: 60s)
    """
    self._backend = backend
    self._config = config_manager
    self._timeout_seconds = timeout_seconds
```

### Phase 3: Update _execute_fetch_prompt (~10 minutes)

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

#### 3a. Update the method to use `self._backend`:

```python
# BEFORE (line 292):
lambda: self._auggie.run_print_quiet(prompt, dont_save_session=True),

# AFTER:
lambda: self._backend.run_print_quiet(prompt, dont_save_session=True),
```

#### 3b. Update debug log message (line 281):

```python
# BEFORE:
logger.debug(
    "Executing Auggie fetch for %s (timeout: %.1fs)",
    platform.name,
    effective_timeout,
)

# AFTER:
logger.debug(
    "Executing backend fetch for %s (timeout: %.1fs)",
    platform.name,
    effective_timeout,
)
```

#### 3c. Update error messages to be backend-agnostic (lines 297-314):

```python
# BEFORE:
except TimeoutError:
    raise AgentFetchError(
        message=(f"Auggie CLI execution timed out after {effective_timeout}s"),
        agent_name=self.name,
    ) from None
except Exception as e:
    raise AgentFetchError(
        message=f"Auggie CLI invocation failed: {e}",
        agent_name=self.name,
        original_error=e,
    ) from e

# ...
if not result:
    raise AgentFetchError(
        message="Auggie returned empty response",
        agent_name=self.name,
    )

# AFTER:
except TimeoutError:
    raise AgentFetchError(
        message=(f"Backend execution timed out after {effective_timeout}s"),
        agent_name=self.name,
    ) from None
except Exception as e:
    raise AgentFetchError(
        message=f"Backend invocation failed: {e}",
        agent_name=self.name,
        original_error=e,
    ) from e

# ...
if not result:
    raise AgentFetchError(
        message="Backend returned empty response",
        agent_name=self.name,
    )
```

#### 3d. Update method docstring (lines 256-276):

```python
# BEFORE:
async def _execute_fetch_prompt(
    self,
    prompt: str,
    platform: Platform,
    timeout_seconds: float | None = None,
) -> str:
    """Execute fetch prompt via Auggie CLI with timeout.

    Uses run_print_quiet() for non-interactive execution that
    captures the response for JSON parsing.

    Note:
        The timeout is implemented at the asyncio level. The underlying
        subprocess may continue running if cancelled, but we won't wait
        for it indefinitely.
    ...

# AFTER:
async def _execute_fetch_prompt(
    self,
    prompt: str,
    platform: Platform,
    timeout_seconds: float | None = None,
) -> str:
    """Execute fetch prompt via AI backend with timeout.

    Uses run_print_quiet() for non-interactive execution that
    captures the response for JSON parsing.

    Note:
        The timeout is implemented at the asyncio level. The underlying
        subprocess may continue running if cancelled, but we won't wait
        for it indefinitely.
    ...
```

### Phase 4: Update Docstrings (~10 minutes)

**File:** `spec/integrations/fetchers/auggie_fetcher.py`

#### 4a. Update module docstring (lines 1-21):

```python
# BEFORE:
"""Auggie-mediated ticket fetcher using MCP integrations.

This module provides the AuggieMediatedFetcher class that fetches
ticket data through Auggie's native MCP tool integrations for
Jira, Linear, and GitHub (platforms with MCP integrations).

Architecture Note:
    This fetcher uses a prompt-based approach rather than direct tool
    invocation because the AuggieClient API does not expose an `invoke_tool()`
    method. The CLI interface requires natural language prompts that instruct
    the agent to use its MCP tools.
    ...
    If AuggieClient adds direct tool invocation in the future, this fetcher
    should be updated to use that approach for more deterministic behavior.
"""

# AFTER:
"""AI backend-mediated ticket fetcher using MCP integrations.

This module provides the AuggieMediatedFetcher class that fetches
ticket data through an AI backend's MCP tool integrations for
Jira, Linear, and GitHub (platforms with MCP integrations).

Architecture Note:
    This fetcher uses a prompt-based approach rather than direct tool
    invocation because the AIBackend API does not expose an `invoke_tool()`
    method. The CLI interface requires natural language prompts that instruct
    the agent to use its MCP tools.
    ...
    If AIBackend adds direct tool invocation in the future, this fetcher
    should be updated to use that approach for more deterministic behavior.

Historical Note:
    This class was originally designed for Auggie (hence the name
    "AuggieMediatedFetcher"). It now works with any AIBackend implementation.
    The class name is preserved for backwards compatibility.
"""
```

#### 4b. Update class docstring (lines 121-136):

```python
# BEFORE:
class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie's native MCP integrations.

    This fetcher delegates to Auggie's built-in tool calls for platforms
    like Jira, Linear, and GitHub. It's the primary fetch path when
    running in an Auggie-enabled environment.

    Note:
        This fetcher uses prompt-based invocation since AuggieClient does
        not expose direct tool invocation. See module docstring for details.

    Attributes:
        _auggie: AuggieClient for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
        _timeout_seconds: Timeout for agent execution
    """

# AFTER:
class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through AI backend's MCP integrations.

    This fetcher delegates to the AI backend's tool calls for platforms
    like Jira, Linear, and GitHub. It's the primary fetch path when
    running in an AI agent-enabled environment.

    Note:
        Despite the name "AuggieMediatedFetcher", this fetcher can work
        with any AIBackend implementation. The name is preserved for
        backwards compatibility.

        This fetcher uses prompt-based invocation since the backend API
        does not expose direct tool invocation. See module docstring for details.

    Attributes:
        _backend: AIBackend for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
        _timeout_seconds: Timeout for agent execution
    """
```

### Phase 5: Update Tests (~30 minutes)

**File:** `tests/test_auggie_fetcher.py`

#### 5a. Update imports (lines 22):

```python
# BEFORE:
from spec.integrations.auggie import AuggieClient

# AFTER:
from spec.integrations.backends.base import AIBackend
```

**Note:** Remove the `AuggieClient` import entirely - it is no longer needed.

#### 5b. Update fixture (lines 39-45):

```python
# BEFORE:
@pytest.fixture
def mock_auggie_client():
    """Create a mock AuggieClient with proper spec for type safety."""
    client = MagicMock(spec=AuggieClient)
    # Default: successful response with JSON
    client.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return client

# AFTER:
@pytest.fixture
def mock_backend():
    """Create a mock AIBackend with proper spec for type safety."""
    backend = MagicMock(spec=AIBackend)
    # Default: successful response with JSON
    backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return backend
```

#### 5c. Update module docstring (lines 1-12):

```python
# BEFORE:
"""Tests for spec.integrations.fetchers.auggie_fetcher module.

Tests cover:
- AuggieMediatedFetcher instantiation
- Platform support checking (with and without ConfigManager)
- Prompt template retrieval
- Execute fetch prompt via AuggieClient
- Full fetch_raw integration with mocked AuggieClient
- New fetch() method with string platform parameter
- Timeout functionality
- Response validation
"""

# AFTER:
"""Tests for spec.integrations.fetchers.auggie_fetcher module.

Tests cover:
- AuggieMediatedFetcher instantiation
- Platform support checking (with and without ConfigManager)
- Prompt template retrieval
- Execute fetch prompt via AIBackend
- Full fetch_raw integration with mocked AIBackend
- New fetch() method with string platform parameter
- Timeout functionality
- Response validation
"""
```

#### 5d. Update TestAuggieMediatedFetcherInstantiation (lines 72-94):

```python
# BEFORE:
class TestAuggieMediatedFetcherInstantiation:
    """Tests for AuggieMediatedFetcher initialization."""

    def test_init_with_auggie_client_only(self, mock_auggie_client):
        """Can initialize with just AuggieClient."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client)

        assert fetcher._auggie is mock_auggie_client
        assert fetcher._config is None

    def test_init_with_config_manager(self, mock_auggie_client, mock_config_manager):
        """Can initialize with AuggieClient and ConfigManager."""
        fetcher = AuggieMediatedFetcher(mock_auggie_client, mock_config_manager)

        assert fetcher._auggie is mock_auggie_client
        assert fetcher._config is mock_config_manager

# AFTER:
class TestAuggieMediatedFetcherInstantiation:
    """Tests for AuggieMediatedFetcher initialization."""

    def test_init_with_backend_only(self, mock_backend):
        """Can initialize with just AIBackend."""
        fetcher = AuggieMediatedFetcher(mock_backend)

        assert fetcher._backend is mock_backend
        assert fetcher._config is None

    def test_init_with_config_manager(self, mock_backend, mock_config_manager):
        """Can initialize with AIBackend and ConfigManager."""
        fetcher = AuggieMediatedFetcher(mock_backend, mock_config_manager)

        assert fetcher._backend is mock_backend
        assert fetcher._config is mock_config_manager
```

#### 5e. Update all other test classes - fixture parameter changes:

All test methods using `mock_auggie_client` must be updated to use `mock_backend`. Here is the complete list:

| Test Class | Methods to Update | Change |
|------------|-------------------|--------|
| `TestAuggieMediatedFetcherInstantiation` | `test_init_with_auggie_client_only`, `test_init_with_config_manager`, `test_name_property` | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherPlatformSupport` | All 10 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherPromptTemplates` | All 5 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherExecuteFetchPrompt` | All 3 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherFetchRaw` | All 6 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherFetchMethod` | All 8 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherTimeout` | All 3 methods | `mock_auggie_client` → `mock_backend` |
| `TestAuggieMediatedFetcherValidation` | All 8 methods | `mock_auggie_client` → `mock_backend` |

**Total: ~46 test methods require fixture parameter updates.**

#### 5f. Update test method names and docstrings (optional but recommended):

```python
# BEFORE:
def test_init_with_auggie_client_only(self, mock_auggie_client):
    """Can initialize with just AuggieClient."""

# AFTER:
def test_init_with_backend_only(self, mock_backend):
    """Can initialize with just AIBackend."""
```

**Note:** Only the instantiation tests need method name changes. Other tests can keep their names since they test the fetcher behavior, not the backend type.

#### 5g. Update error message assertions (line 251):

The test `test_execute_fetch_prompt_exception_wrapped` asserts on the error message text. This must be updated to match the new backend-agnostic error messages:

```python
# BEFORE (line 251):
assert "CLI invocation failed" in str(exc_info.value)

# AFTER:
assert "Backend invocation failed" in str(exc_info.value)
```

**Note:** This is a **critical update** - if not changed, the test will fail because the error message now says "Backend invocation failed" instead of "Auggie CLI invocation failed".

---

## File Changes Detail

### File: `spec/integrations/fetchers/auggie_fetcher.py`

#### Change 1: Imports (lines 38-40)

**Before:**
```python
if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auggie import AuggieClient
```

**After:**
```python
from spec.integrations.backends.base import AIBackend

if TYPE_CHECKING:
    from spec.config import ConfigManager
```

#### Change 2: Class Docstring (lines 121-136)

**Before:**
```python
class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie's native MCP integrations.
    ...
    Attributes:
        _auggie: AuggieClient for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
        _timeout_seconds: Timeout for agent execution
    """
```

**After:**
```python
class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through AI backend's MCP integrations.
    ...
    Attributes:
        _backend: AIBackend for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
        _timeout_seconds: Timeout for agent execution
    """
```

#### Change 3: Constructor (lines 138-153)

**Before:**
```python
def __init__(
    self,
    auggie_client: AuggieClient,
    config_manager: ConfigManager | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Initialize with Auggie client and optional config.

    Args:
        auggie_client: Client for Auggie CLI invocations
        ...
    """
    self._auggie = auggie_client
    self._config = config_manager
    self._timeout_seconds = timeout_seconds
```

**After:**
```python
def __init__(
    self,
    backend: AIBackend,
    config_manager: ConfigManager | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Initialize with AI backend and optional config.

    Args:
        backend: AI backend instance (AuggieBackend, ClaudeBackend, etc.)
        ...
    """
    self._backend = backend
    self._config = config_manager
    self._timeout_seconds = timeout_seconds
```

#### Change 4: Module Docstring (lines 1-21)

**Before:**
```python
"""Auggie-mediated ticket fetcher using MCP integrations.
...
    invocation because the AuggieClient API does not expose an `invoke_tool()`
...
    If AuggieClient adds direct tool invocation in the future, this fetcher
"""
```

**After:**
```python
"""AI backend-mediated ticket fetcher using MCP integrations.
...
    invocation because the AIBackend API does not expose an `invoke_tool()`
...
    If AIBackend adds direct tool invocation in the future, this fetcher

Historical Note:
    This class was originally designed for Auggie (hence the name
    "AuggieMediatedFetcher"). It now works with any AIBackend implementation.
"""
```

#### Change 5: _execute_fetch_prompt method call (line 292)

**Before:**
```python
lambda: self._auggie.run_print_quiet(prompt, dont_save_session=True),
```

**After:**
```python
lambda: self._backend.run_print_quiet(prompt, dont_save_session=True),
```

#### Change 6: _execute_fetch_prompt error messages (lines 297-314)

**Before:**
```python
raise AgentFetchError(
    message=(f"Auggie CLI execution timed out after {effective_timeout}s"),
    ...
raise AgentFetchError(
    message=f"Auggie CLI invocation failed: {e}",
    ...
raise AgentFetchError(
    message="Auggie returned empty response",
```

**After:**
```python
raise AgentFetchError(
    message=(f"Backend execution timed out after {effective_timeout}s"),
    ...
raise AgentFetchError(
    message=f"Backend invocation failed: {e}",
    ...
raise AgentFetchError(
    message="Backend returned empty response",
```

#### Change 7: _execute_fetch_prompt docstring (line 256)

**Before:**
```python
"""Execute fetch prompt via Auggie CLI with timeout.
```

**After:**
```python
"""Execute fetch prompt via AI backend with timeout.
```

---

## Dependencies

### Upstream Dependencies (Required Before Starting)

| Ticket | Description | Status |
|--------|-------------|--------|
| AMI-48 | AIBackend Protocol | ✅ Done |
| AMI-49 | BaseBackend Abstract Class | ✅ Done |
| AMI-51 | Create AuggieBackend | ✅ Done |

### Downstream Dependencies (Blocked By This)

| Ticket | Description | How This Ticket Affects It |
|--------|-------------|---------------------------|
| AMI-57 | Update ticket_service.py | Needs updated fetcher to accept `AIBackend` |
| AMI-57 | Update `spec/cli.py` (line 240) | Uses `AuggieClient()` directly; will be updated in Phase 1.5.3 |
| AMI-58+ | Additional fetcher updates | Pattern established by this ticket |

### Breaking Change Coordination

> **⚠️ IMPORTANT:** This ticket changes the constructor signature of `AuggieMediatedFetcher`, which will **break existing callers** until they are updated.

**Affected Callers:**

1. **`spec/integrations/ticket_service.py` (lines 356-359):**
   ```python
   # CURRENT (will break after AMI-56):
   primary = AuggieMediatedFetcher(
       auggie_client=auggie_client,
       config_manager=config_manager,
   )
   ```

2. **`spec/cli.py` (line 240):**
   ```python
   # CURRENT (uses AuggieClient directly):
   auggie_client = AuggieClient()
   ```

**Migration Strategy Options:**

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A. Same PR** | Update AMI-56 and AMI-57 in the same PR | No broken intermediate state | Larger PR, more review complexity |
| **B. Sequential with Deprecation** | Add backwards-compatible shim in AMI-56, remove in AMI-57 | Smaller PRs, gradual migration | More code churn, temporary complexity |
| **C. Sequential (Recommended)** | Merge AMI-56 first, immediately follow with AMI-57 | Clean separation, clear ownership | Brief window where callers are broken |

**Recommended Approach:** Option C (Sequential) - Merge AMI-56 and AMI-57 in quick succession. The `ticket_service.py` update is straightforward and can be completed immediately after AMI-56.

---

## Testing Strategy

### Unit Test Updates

**File:** `tests/test_auggie_fetcher.py`

All existing tests should be updated to use `AIBackend` mock instead of `AuggieClient` mock:

| Test Class | Changes Required |
|------------|------------------|
| `TestAuggieMediatedFetcherInstantiation` | Replace `mock_auggie_client` with `mock_backend`, update assertions to check `_backend`, rename test methods |
| `TestAuggieMediatedFetcherPlatformSupport` | Update fixture usage (10 methods) |
| `TestAuggieMediatedFetcherPromptTemplates` | Update fixture usage (5 methods) |
| `TestAuggieMediatedFetcherExecuteFetchPrompt` | Update fixture usage (3 methods) |
| `TestAuggieMediatedFetcherFetchRaw` | Update fixture usage (6 methods) |
| `TestAuggieMediatedFetcherFetchMethod` | Update fixture usage (8 methods) |
| `TestAuggieMediatedFetcherTimeout` | Update fixture usage (3 methods) |
| `TestAuggieMediatedFetcherValidation` | Update fixture usage (8 methods) |

**Total: ~46 test methods require fixture parameter updates.**

### Detailed Test Changes

#### Import Changes (line 22)
```python
# BEFORE:
from spec.integrations.auggie import AuggieClient

# AFTER:
from spec.integrations.backends.base import AIBackend
```

#### Fixture Changes (lines 39-45)
```python
# BEFORE:
@pytest.fixture
def mock_auggie_client():
    """Create a mock AuggieClient with proper spec for type safety."""
    client = MagicMock(spec=AuggieClient)
    client.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return client

# AFTER:
@pytest.fixture
def mock_backend():
    """Create a mock AIBackend with proper spec for type safety."""
    backend = MagicMock(spec=AIBackend)
    backend.run_print_quiet.return_value = '{"key": "PROJ-123", "summary": "Test issue"}'
    return backend
```

#### Assertion Changes (lines 75-87)
```python
# BEFORE:
assert fetcher._auggie is mock_auggie_client

# AFTER:
assert fetcher._backend is mock_backend
```

### Key Test Cases to Verify

1. **Protocol compliance**: Verify `AIBackend` mock is correctly called with expected parameters
2. **Backwards compatibility**: Verify `run_print_quiet(prompt, dont_save_session=True)` call pattern works
3. **Timeout handling**: Verify asyncio timeout wrapper still functions correctly
4. **Error handling**: Verify exceptions are still raised appropriately
5. **Error message updates**: Verify new backend-agnostic error messages appear in test assertions

### Verification Commands

```bash
# Pre-implementation: Verify dependencies are available
python -c "from spec.integrations.backends import AIBackend, AuggieBackend; print('Dependencies available')"

# Verify imports work without cycles
python -c "from spec.integrations.fetchers.auggie_fetcher import AuggieMediatedFetcher; print('Import OK')"

# Verify AIBackend is properly type-checked
python -c "
from spec.integrations.backends import AuggieBackend
from spec.integrations.fetchers import AuggieMediatedFetcher
backend = AuggieBackend()
fetcher = AuggieMediatedFetcher(backend)
print('Integration OK')
"

# Run unit tests for fetcher
pytest tests/test_auggie_fetcher.py -v

# Run mypy type checking on source file
mypy spec/integrations/fetchers/auggie_fetcher.py

# Run mypy type checking on test file
mypy tests/test_auggie_fetcher.py

# Run all tests to check for regressions
pytest tests/ -v

# Verify no import cycles with full integration
python -c "
from spec.integrations.backends import AIBackend, AuggieBackend
from spec.integrations.fetchers import AuggieMediatedFetcher
from spec.integrations.providers.base import Platform
print('Full integration OK')
"

# Verify all "Auggie" references in error messages have been updated
# (Should find 0 occurrences of "Auggie CLI" or "Auggie returned" in source)
grep -c "Auggie CLI\|Auggie returned" spec/integrations/fetchers/auggie_fetcher.py || echo "✅ No Auggie-specific error messages found"

# Verify test assertions have been updated to match new error messages
# (Should find 0 occurrences of "CLI invocation failed" in tests)
grep -c "CLI invocation failed" tests/test_auggie_fetcher.py || echo "✅ Test assertions updated"
```

---

## Acceptance Criteria

### Implementation Checklist

#### Source File (`spec/integrations/fetchers/auggie_fetcher.py`)

- [ ] Constructor accepts `backend: AIBackend` instead of `auggie_client: AuggieClient`
- [ ] Internal attribute changed from `self._auggie` to `self._backend`
- [ ] `_execute_fetch_prompt()` uses `self._backend.run_print_quiet()`
- [ ] `AIBackend` import added (runtime import, not TYPE_CHECKING)
- [ ] `AuggieClient` import removed from TYPE_CHECKING block
- [ ] Module docstring updated for backend-agnostic language
- [ ] Class docstring updated to reflect AIBackend usage
- [ ] Constructor docstring updated with new parameter name
- [ ] `_execute_fetch_prompt()` docstring updated (Auggie CLI → AI backend)
- [ ] Error messages updated to be backend-agnostic (3 locations)
- [ ] Parameter name `dont_save_session` matches AIBackend protocol ✅ (already correct)

#### Test File (`tests/test_auggie_fetcher.py`)

- [ ] `AuggieClient` import removed
- [ ] `AIBackend` import added
- [ ] `mock_auggie_client` fixture renamed to `mock_backend`
- [ ] Fixture uses `MagicMock(spec=AIBackend)` instead of `MagicMock(spec=AuggieClient)`
- [ ] All ~46 test methods updated to use `mock_backend` parameter
- [ ] Assertions updated: `fetcher._auggie` → `fetcher._backend`
- [ ] Test method names updated in `TestAuggieMediatedFetcherInstantiation`
- [ ] Module docstring updated (AuggieClient → AIBackend)
- [ ] Error message assertion updated: `"CLI invocation failed"` → `"Backend invocation failed"` (line 251)

### Quality Checklist

- [ ] `mypy spec/integrations/fetchers/auggie_fetcher.py` reports no type errors
- [ ] `mypy tests/test_auggie_fetcher.py` reports no type errors
- [ ] No import cycles introduced
- [ ] Unit tests updated and passing
- [ ] No regressions in existing tests
- [ ] Async execution pattern preserved
- [ ] No "Auggie CLI" or "Auggie returned" strings remain in source error messages
- [ ] No "CLI invocation failed" strings remain in test assertions

### Acceptance Criteria from Linear Ticket

| AC | Description | Verification Method | Status | Notes |
|----|-------------|---------------------|--------|-------|
| **AC1** | Constructor accepts `backend: AIBackend` | Unit test | [ ] | |
| **AC2** | All internal calls use `self._backend` | Code review | [ ] | |
| **AC3** | Parameter names match AIBackend protocol | Code review | ✅ | **Already satisfied** - current code uses `dont_save_session=True` |
| **AC4** | Async execution preserved | Unit test | [ ] | |
| **AC5** | Type hints updated | mypy check | [ ] | |
| **AC6** | Existing fetcher tests pass | pytest | [ ] | |

> **Note on AC3:** The Linear ticket description mentions changing `no_session=True` to `dont_save_session=True`, but the **current implementation already uses `dont_save_session=True`** (line 292). This acceptance criterion is already satisfied - no parameter name change is needed.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking existing callers | Low | High | Update all callers in same PR or coordinate with AMI-57 |
| Type checking failures | Low | Low | Run mypy before and after on both source and test files |
| Test failures | Medium | Low | Update all test fixtures systematically |
| Error message assertion failures | Low | Low | Update any tests that assert on specific error message text |

---

## References

### Specification References

| Document | Section | Description |
|----------|---------|-------------|
| `specs/Pluggable Multi-Agent Support.md` | Lines 2067-2109 | Phase 1.5.1: Update AuggieMediatedFetcher |
| `specs/Pluggable Multi-Agent Support.md` | Lines 3976-4007 | Before/After code snippets |

### Codebase References

| File | Description |
|------|-------------|
| `spec/integrations/fetchers/auggie_fetcher.py` | Current AuggieMediatedFetcher implementation |
| `spec/integrations/backends/base.py` | AIBackend protocol definition |
| `spec/integrations/backends/auggie.py` | AuggieBackend implementation |
| `tests/test_auggie_fetcher.py` | Existing tests to update |

### Related Implementation Plans

| Document | Description |
|----------|-------------|
| `specs/AMI-30-implementation-plan.md` | Original AuggieMediatedFetcher implementation |
| `specs/AMI-48-implementation-plan.md` | AIBackend Protocol creation |
| `specs/AMI-51-implementation-plan.md` | AuggieBackend implementation |

---

## Estimated Effort

~0.5 days (3-4 hours)

| Phase | Description | Estimate |
|-------|-------------|----------|
| Phase 1 | Update imports | ~5 minutes |
| Phase 2 | Update constructor | ~5 minutes |
| Phase 3 | Update `_execute_fetch_prompt()` (method call, log message, error messages, docstring) | ~15 minutes |
| Phase 4 | Update docstrings (module + class) | ~10 minutes |
| Phase 5 | Update tests (~46 methods + error message assertion) | ~45 minutes |
| Verification | Run all verification commands | ~30 minutes |
| Review | Code review and cleanup | ~30 minutes |
| **Total** | | **~2.5 hours** |

**Notes:**
- Phase 3 includes updating the debug log message (line 281) from "Executing Auggie fetch" to "Executing backend fetch"
- Phase 5 (Tests) estimate increased from original 15 minutes to 45 minutes due to the comprehensive test updates required (~46 test methods + error message assertion update)

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2026-02-02 | AI Assistant | Initial draft created following AMI-53 template |
| 2026-02-02 | AI Assistant | Updated after review: added error message updates, module docstring updates, comprehensive test changes, mypy verification for test file |
| 2026-02-02 | AI Assistant | Review updates: (1) Added Phase 5g for test error message assertion update (line 251); (2) Expanded Dependencies section with breaking change coordination and migration strategy; (3) Added `spec/cli.py` to downstream dependencies; (4) Added Phase 3b for debug log message update; (5) Added note in Current State Analysis that `dont_save_session` is already used (no parameter name change needed); (6) Updated Acceptance Criteria with explicit AC3 verification note; (7) Added verification commands to check for remaining Auggie-specific strings |
