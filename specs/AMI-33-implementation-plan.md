# Implementation Plan: AMI-33 - Add Fetch Strategy Configuration to Config Schema

**Ticket:** [AMI-33](https://linear.app/amiadspec/issue/AMI-33/add-fetch-strategy-configuration-to-config-schema)
**Status:** ✅ IMPLEMENTED (PR #20)
**Date:** 2026-01-23
**Updated:** 2026-01-24

---

## Summary

This ticket extends the SPECFLOW configuration schema to support the hybrid ticket fetching architecture. The implementation adds:

1. **AgentConfig** - AI backend and integration settings (which platforms the agent has MCP integrations for)
2. **FetchStrategyConfig** - Default strategy (agent/direct/auto) with per-platform overrides
3. **FetchPerformanceConfig** - Timeout, retry, and cache settings
4. **Fallback credentials** - Direct API credentials for platforms without agent integration
5. **Environment variable expansion** - Support for `${VAR}` syntax in config values

This enables the TicketService (AMI-29) to determine the optimal fetching strategy per platform.

---

## Technical Approach

### Architecture Fit

The configuration extends the existing cascading hierarchy in `spec/config/`:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONFIGURATION PRECEDENCE                              │
│                         (Highest to Lowest)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. Environment Variables    ─── Highest priority (CI/CD, temporary overrides)│
│  2. Local Config (.spec)     ─── Project-specific settings                    │
│  3. Global Config (~/.spec-config) ─── User defaults                          │
│  4. Built-in Defaults        ─── Fallback values                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Current Config Architecture

The existing implementation uses:
- **Settings dataclass** (`spec/config/settings.py`) - Flat key-value pairs with `_key_mapping`
- **ConfigManager** (`spec/config/manager.py`) - Loads from files/env, applies to Settings
- **Simple KEY=VALUE format** - Both `.spec` and `~/.spec-config` use shell-like format

### Design Decision: New Fetch Config Module

Rather than overloading the existing `Settings` dataclass with complex nested structures, we create a **separate configuration module** for fetch-related settings:

```
spec/config/
├── __init__.py           # Updated exports
├── settings.py           # Existing flat settings (unchanged)
├── manager.py            # Updated with new getters
└── fetch_config.py       # NEW: FetchStrategy, AgentConfig, etc.
```

**Rationale:**
1. **Separation of concerns** - Fetch config is a cohesive domain
2. **Type safety** - Dataclasses with enums provide validation
3. **Backward compatibility** - Existing Settings unchanged
4. **Cleaner API** - `config_manager.get_fetch_strategy_config()` vs overloaded Settings

---

## Components to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `spec/config/fetch_config.py` | Dataclasses: `FetchStrategy`, `AgentPlatform`, `AgentConfig`, `FetchStrategyConfig`, `FetchPerformanceConfig`; Validation: `ConfigValidationError`, `validate_credentials()`, `validate_strategy_for_platform()`, `get_active_platforms()`, `canonicalize_credentials()`; Parser helpers: `parse_fetch_strategy()`, `parse_ai_backend()` |
| `spec/utils/env_utils.py` | Environment variable utilities: `expand_env_vars()`, `expand_env_vars_strict()`, `is_sensitive_key()`, `EnvVarExpansionError`, `SENSITIVE_KEY_PATTERNS` |
| `tests/test_fetch_config.py` | 39 comprehensive unit tests |

### Modified Files

| File | Changes |
|------|---------|
| `spec/config/manager.py` | Add `get_agent_config()`, `get_fetch_strategy_config()`, `get_fetch_performance_config()`, `get_fallback_credentials()`, `validate_fetch_config()`, `_get_active_platforms()` |
| `spec/config/__init__.py` | Export new config classes and validation utilities |
| `spec/config/settings.py` | Add new config keys to `_key_mapping` for flat settings |

---

## Implementation Steps

### Step 1: Create Fetch Config Module
**File:** `spec/config/fetch_config.py`

Create dataclasses and enums:
- `FetchStrategy` enum: `AGENT`, `DIRECT`, `AUTO`
- `AgentPlatform` enum: `AUGGIE`, `CLAUDE_DESKTOP`, `CURSOR`, `AIDER`, `MANUAL`
- `AgentConfig` dataclass with `platform` and `integrations` dict
- `FetchStrategyConfig` dataclass with `default` and `per_platform` dict
- `FetchPerformanceConfig` dataclass with `cache_duration_hours`, `timeout_seconds`, `max_retries`, `retry_delay_seconds`

### Step 2: Add Environment Variable Expansion
**File:** `spec/config/manager.py`

Add `_expand_env_vars()` method that:
- Recursively processes dicts, lists, and strings
- Replaces `${VAR_NAME}` with `os.environ.get(VAR_NAME, '')`
- Preserves unmatched patterns as-is (for debugging)

### Step 3: Add ConfigManager Getters
**File:** `spec/config/manager.py`

Add methods:
- `get_agent_config() -> AgentConfig`
- `get_fetch_strategy_config() -> FetchStrategyConfig`
- `get_fetch_performance_config() -> FetchPerformanceConfig`
- `get_fallback_credentials(platform: str) -> dict[str, str] | None`

### Step 4: Update Settings Key Mapping
**File:** `spec/config/settings.py`

Add new flat config keys for simple settings:
- `AI_BACKEND` → AI backend
- `FETCH_STRATEGY_DEFAULT` → default fetch strategy
- `FETCH_CACHE_DURATION_HOURS` → cache TTL
- `FETCH_TIMEOUT_SECONDS` → HTTP timeout
- `FETCH_MAX_RETRIES` → retry count
- `FETCH_RETRY_DELAY_SECONDS` → delay between retries

### Step 5: Update Package Exports
**File:** `spec/config/__init__.py`

Export new classes from `fetch_config.py`.

### Step 6: Add Unit Tests
**File:** `tests/test_fetch_config.py`

Test coverage for:
- Enum parsing and validation
- Dataclass instantiation with defaults
- Environment variable expansion
- ConfigManager integration
- Per-platform strategy overrides

---

## File Changes Detail

### New: `spec/config/fetch_config.py`

```python
"""Fetch strategy configuration for SPECFLOW."""

from dataclasses import dataclass, field
from enum import Enum


class FetchStrategy(Enum):
    """Ticket fetching strategy."""
    AGENT = "agent"    # Use agent-mediated fetch (fail if not supported)
    DIRECT = "direct"  # Use direct API (requires credentials)
    AUTO = "auto"      # Try agent first, fall back to direct


class AgentPlatform(Enum):
    """Supported AI backends."""
    AUGGIE = "auggie"
    CLAUDE_DESKTOP = "claude_desktop"
    CURSOR = "cursor"
    AIDER = "aider"
    MANUAL = "manual"


@dataclass
class AgentConfig:
    """Configuration for the connected AI agent."""
    platform: AgentPlatform = AgentPlatform.AUGGIE
    integrations: dict[str, bool] = field(default_factory=dict)

    def supports_platform(self, platform: str) -> bool:
        """Check if agent has integration for platform."""
        return self.integrations.get(platform.lower(), False)


@dataclass
class FetchStrategyConfig:
    """Configuration for ticket fetching strategy."""
    default: FetchStrategy = FetchStrategy.AUTO
    per_platform: dict[str, FetchStrategy] = field(default_factory=dict)

    def get_strategy(self, platform: str) -> FetchStrategy:
        """Get strategy for a specific platform."""
        return self.per_platform.get(platform.lower(), self.default)


@dataclass
class FetchPerformanceConfig:
    """Performance settings for ticket fetching."""
    cache_duration_hours: int = 24
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
```

### Modified: `spec/config/manager.py`

Add these methods to `ConfigManager`:

```python
def _expand_env_vars(self, value: Any) -> Any:
    """Recursively expand ${VAR} references to environment variables."""
    if isinstance(value, str):
        import re
        pattern = r'\$\{([^}]+)\}'
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(pattern, replace, value)
    elif isinstance(value, dict):
        return {k: self._expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [self._expand_env_vars(v) for v in value]
    return value

def get_agent_config(self) -> AgentConfig:
    """Get AI agent configuration."""
    from spec.config.fetch_config import AgentConfig, AgentPlatform
    platform_str = self._raw_values.get("AI_BACKEND", "auggie")
    integrations = {}
    # Parse AGENT_INTEGRATIONS_* keys
    for key, value in self._raw_values.items():
        if key.startswith("AGENT_INTEGRATION_"):
            platform_name = key.replace("AGENT_INTEGRATION_", "").lower()
            integrations[platform_name] = value.lower() in ("true", "1", "yes")
    return AgentConfig(
        platform=AgentPlatform(platform_str),
        integrations=integrations,
    )

def get_fetch_strategy_config(self) -> FetchStrategyConfig:
    """Get fetch strategy configuration."""
    from spec.config.fetch_config import FetchStrategy, FetchStrategyConfig
    default_str = self._raw_values.get("FETCH_STRATEGY_DEFAULT", "auto")
    per_platform = {}
    # Parse FETCH_STRATEGY_* keys
    for key, value in self._raw_values.items():
        if key.startswith("FETCH_STRATEGY_") and key != "FETCH_STRATEGY_DEFAULT":
            platform_name = key.replace("FETCH_STRATEGY_", "").lower()
            per_platform[platform_name] = FetchStrategy(value.lower())
    return FetchStrategyConfig(
        default=FetchStrategy(default_str),
        per_platform=per_platform,
    )

def get_fallback_credentials(self, platform: str) -> dict[str, str] | None:
    """Get fallback credentials for a platform."""
    prefix = f"FALLBACK_{platform.upper()}_"
    credentials = {}
    for key, value in self._raw_values.items():
        if key.startswith(prefix):
            cred_name = key.replace(prefix, "").lower()
            credentials[cred_name] = self._expand_env_vars(value)
    return credentials if credentials else None
```

### Modified: `spec/config/settings.py`

Add to `_key_mapping`:

```python
# Fetch strategy settings
"AI_BACKEND": "ai_backend",
"FETCH_STRATEGY_DEFAULT": "fetch_strategy_default",
"FETCH_CACHE_DURATION_HOURS": "fetch_cache_duration_hours",
"FETCH_TIMEOUT_SECONDS": "fetch_timeout_seconds",
"FETCH_MAX_RETRIES": "fetch_max_retries",
"FETCH_RETRY_DELAY_SECONDS": "fetch_retry_delay_seconds",
```

Add new attributes to `Settings` dataclass:

```python
# Fetch strategy settings
ai_backend: str = "auggie"
fetch_strategy_default: str = "auto"
fetch_cache_duration_hours: int = 24
fetch_timeout_seconds: int = 30
fetch_max_retries: int = 3
fetch_retry_delay_seconds: float = 1.0
```

---

## Configuration Format

### Flat Config (.spec / ~/.spec-config)

```bash
# Agent configuration
AI_BACKEND=auggie
AGENT_INTEGRATION_JIRA=true
AGENT_INTEGRATION_LINEAR=true
AGENT_INTEGRATION_GITHUB=true
AGENT_INTEGRATION_AZURE_DEVOPS=false

# Fetch strategy
FETCH_STRATEGY_DEFAULT=auto
FETCH_STRATEGY_AZURE_DEVOPS=direct
FETCH_STRATEGY_TRELLO=direct

# Performance settings
FETCH_CACHE_DURATION_HOURS=24
FETCH_TIMEOUT_SECONDS=30
FETCH_MAX_RETRIES=3
FETCH_RETRY_DELAY_SECONDS=1

# Fallback credentials (for direct API access)
FALLBACK_AZURE_DEVOPS_ORGANIZATION=myorg
FALLBACK_AZURE_DEVOPS_PROJECT=myproject
FALLBACK_AZURE_DEVOPS_PAT=${AZURE_DEVOPS_PAT}
```

---

## Testing Strategy

### Unit Tests (`tests/test_fetch_config.py`)

1. **Enum Tests**
   - `FetchStrategy` values parse correctly
   - `AgentPlatform` values parse correctly
   - Invalid values raise `ValueError`

2. **Dataclass Tests**
   - Default values are sensible
   - `AgentConfig.supports_platform()` works correctly
   - `FetchStrategyConfig.get_strategy()` returns correct overrides

3. **ConfigManager Integration Tests**
   - `get_agent_config()` parses flat config correctly
   - `get_fetch_strategy_config()` parses per-platform overrides
   - `get_fallback_credentials()` returns correct dict or None
   - `_expand_env_vars()` expands `${VAR}` correctly
   - Nested expansion works (dicts, lists)
   - Unmatched `${VAR}` preserved

4. **End-to-End Tests**
   - Load from file with all settings
   - Environment variable override works
   - Cascading hierarchy respected

---

## Migration Considerations

### Backward Compatibility

- **No breaking changes** - All new settings have sensible defaults
- Existing `.spec` and `~/.spec-config` files continue to work
- New keys are optional and ignored by older versions

### Default Behavior

Without any configuration:
- `FetchStrategy.AUTO` - Try agent first, fall back to direct
- `AgentPlatform.AUGGIE` - Assume Auggie agent
- Empty `integrations` - No platforms assumed to have agent integration
- 24-hour cache, 30s timeout, 3 retries

### Dependencies

- **None** - This is a foundation component
- Uses only stdlib (`dataclasses`, `enum`, `os`, `re`)

### Downstream Dependents

- **AMI-29:** `TicketService` uses config to select fetch strategy
- **AMI-27:** `AuggieMediatedFetcher` uses `agent.integrations`
- **AMI-28:** `DirectAPIFetcher` uses `fallback_credentials`

---

## Acceptance Criteria Checklist

From the ticket:
- [x] `AgentConfig` dataclass with platform and integrations
- [x] `FetchStrategyConfig` dataclass with default and per-platform overrides
- [x] `FetchPerformanceConfig` for timeout/retry/cache settings
- [x] Environment variable expansion (`${VAR}` syntax)
- [x] ConfigManager methods for new config sections
- [x] Config file template with comments (documented above)
- [x] Unit tests for config parsing (39 tests)
- [x] Documentation for config options (in docstrings and example config)

Additional from implementation:
- [x] Flat KEY=VALUE format compatible with existing config files
- [x] Sensible defaults for all settings
- [x] Type hints and docstrings for all public methods
- [x] Package exports in `__init__.py`

---

## Additional Features Implemented (Beyond Original Plan)

The implementation exceeded the original plan with these additional features:

### 1. Validation Framework

**File:** `spec/config/fetch_config.py`

- **`ConfigValidationError`** - Exception for fail-fast validation failures
- **`validate_credentials(platform, credentials, strict)`** - Validates required credential fields per platform
- **`validate_strategy_for_platform(platform, strategy, agent_config, has_credentials, strict)`** - Validates strategy is viable
- **`get_active_platforms(raw_config_keys, strategy_config, agent_config)`** - Discovers explicitly configured platforms

```python
# Validation example
from spec.config.fetch_config import validate_credentials, ConfigValidationError

try:
    validate_credentials("jira", {"url": "...", "email": "..."}, strict=True)
except ConfigValidationError as e:
    print(f"Missing fields: {e}")  # Missing token
```

### 2. Performance Bounds with Clamping

**File:** `spec/config/fetch_config.py`

Upper bounds prevent system hangs:

| Setting | Max Value | Notes |
|---------|-----------|-------|
| `cache_duration_hours` | 168 (1 week) | Clamped to max |
| `timeout_seconds` | 300 (5 min) | Clamped to max |
| `max_retries` | 10 | Clamped to max |
| `retry_delay_seconds` | 60 | Clamped to max |

Values are clamped in `FetchPerformanceConfig.__post_init__()` with logged warnings.

### 3. Credential Aliasing

**File:** `spec/config/fetch_config.py`

Platform-specific key normalization via `CREDENTIAL_ALIASES` and `canonicalize_credentials()`:

```python
CREDENTIAL_ALIASES = {
    "azure_devops": {"org": "organization", "token": "pat"},
    "jira": {"base_url": "url"},
    "trello": {"api_token": "token"},
}
```

This allows users to use common synonyms that get normalized to canonical keys.

### 4. Scoped Validation

**File:** `spec/config/manager.py`

`ConfigManager.validate_fetch_config()` only validates "active" platforms that are explicitly configured:
- Platforms in `per_platform` strategy overrides
- Platforms in `agent.integrations`
- Platforms with `FALLBACK_{PLATFORM}_*` credentials

This reduces noise by not checking all `KNOWN_PLATFORMS` by default.

### 5. Extracted Environment Utilities

**File:** `spec/utils/env_utils.py`

Environment variable expansion was extracted to a separate utility module:

- **`expand_env_vars(value, strict, context)`** - Recursive expansion with strict mode
- **`expand_env_vars_strict(value, context)`** - Convenience wrapper for strict mode
- **`is_sensitive_key(key)`** - Checks if key contains sensitive patterns
- **`EnvVarExpansionError`** - Exception for missing env vars in strict mode
- **`SENSITIVE_KEY_PATTERNS`** - Patterns like `TOKEN`, `SECRET`, `PASSWORD`

Sensitive key detection prevents logging secrets:

```python
if is_sensitive_key("FALLBACK_JIRA_TOKEN"):
    logger.warning("Missing env var")  # Context omitted
```

### 6. Safe Enum Parsers

**File:** `spec/config/fetch_config.py`

- **`parse_fetch_strategy(value, default, context)`** - Returns `FetchStrategy` with proper error messages
- **`parse_ai_backend(value, default, context)`** - Returns `AgentPlatform` with proper error messages

```python
strategy = parse_fetch_strategy("invalid", context="FETCH_STRATEGY_DEFAULT")
# Raises: ConfigValidationError("Invalid fetch strategy 'invalid' in FETCH_STRATEGY_DEFAULT...")
```

### 7. Strict/Non-Strict Modes

All validation supports both modes:
- **`strict=True`**: Raises `ConfigValidationError` immediately (fail-fast)
- **`strict=False`**: Returns list of errors/warnings (for debugging/reporting)

---

## Test Coverage

**File:** `tests/test_fetch_config.py` - 39 unit tests

| Category | Tests |
|----------|-------|
| Enum parsing | `parse_fetch_strategy()`, `parse_ai_backend()` with valid/invalid/empty values |
| Dataclass defaults | All fields have sensible defaults |
| `AgentConfig.supports_platform()` | Case-insensitive platform matching |
| `FetchStrategyConfig.get_strategy()` | Per-platform overrides and default fallback |
| `FetchPerformanceConfig` bounds | Upper/lower bound clamping with warnings |
| Credential validation | Missing fields, empty values, unexpanded env vars |
| Strategy validation | `AGENT`/`DIRECT`/`AUTO` viability checks |
| `get_active_platforms()` | Platform discovery from config keys |
| `canonicalize_credentials()` | Alias normalization |
| Environment expansion | `expand_env_vars()`, `expand_env_vars_strict()`, nested structures |
| Sensitive key detection | `is_sensitive_key()` patterns |

All tests pass: `pytest tests/test_fetch_config.py -v`
