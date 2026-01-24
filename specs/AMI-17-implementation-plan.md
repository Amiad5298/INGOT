# Implementation Plan: AMI-17 - Implement ProviderRegistry Factory Pattern

**Ticket:** [AMI-17](https://linear.app/amiadspec/issue/AMI-17/implement-providerregistry-factory-pattern)
**Status:** Draft
**Date:** 2026-01-24

---

## Summary

This ticket implements the `ProviderRegistry` class as defined in **Section 6: Provider Registry & Factory Pattern** of `specs/00_Architecture_Refactor_Spec.md`. The registry provides a centralized factory for issue tracker provider instantiation using:

1. **Factory Pattern** - Provider classes register themselves; core workflow code never needs modification
2. **Singleton Pattern** - One provider instance per platform for memory efficiency and connection reuse
3. **Decorator-based Registration** - Providers declare `PLATFORM` class attribute and use `@ProviderRegistry.register`
4. **PlatformDetector Integration** - Convenience method to auto-select provider based on input URL/ID

---

## Technical Approach

### Architecture Fit

The `ProviderRegistry` acts as the central factory connecting user input to provider instances:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SPECFLOW CLI                                    │
│  spec <ticket_url_or_id>                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ProviderRegistry.get_provider_for_input()           │
│                         (Uses PlatformDetector internally)                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
          ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
          │ JiraProvider│   │GitHubProvider│  │LinearProvider│
          │  (AMI-18)   │   │   (future)  │   │   (future)  │
          └─────────────┘   └─────────────┘   └─────────────┘
```

### Key Design Decisions

1. **Class Methods Only** - Registry uses class methods (no instance needed) for simplicity
2. **PLATFORM Class Attribute** - Providers declare their platform statically to avoid instantiation side-effects during registration
3. **Thread-Safe Singleton** - Uses `threading.Lock` for concurrent provider instantiation
4. **Dependency Injection** - `UserInteractionInterface` is injectable for testing
5. **Test Isolation** - `clear()` method resets state between tests

### Existing Dependencies

| Component | Location | Purpose |
|-----------|----------|---------|
| `Platform` enum | `spec/integrations/providers/base.py` | Platform identification |
| `IssueTrackerProvider` ABC | `spec/integrations/providers/base.py` | Provider interface |
| `PlatformDetector` | `spec/integrations/providers/detector.py` | URL/ID → Platform mapping |
| `PlatformNotSupportedError` | `spec/integrations/providers/exceptions.py` | Error for unregistered platforms |
| `UserInteractionInterface` | `spec/integrations/providers/user_interaction.py` | User prompt abstraction |
| `CLIUserInteraction` | `spec/integrations/providers/user_interaction.py` | Default CLI implementation |

---

## Components to Create

### New File: `spec/integrations/providers/registry.py`

| Component | Purpose |
|-----------|---------|
| `ProviderRegistry` class | Central factory with registration and lookup methods |

---

## Implementation Steps

### Step 1: Create Registry Module

**File:** `spec/integrations/providers/registry.py`

Implement `ProviderRegistry` class with:

```python
class ProviderRegistry:
    """Registry for issue tracker providers."""

    _providers: dict[Platform, Type[IssueTrackerProvider]] = {}
    _instances: dict[Platform, IssueTrackerProvider] = {}
    _user_interaction: UserInteractionInterface = CLIUserInteraction()
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def register(cls, provider_class: Type[IssueTrackerProvider]) -> Type[IssueTrackerProvider]:
        """Decorator to register a provider class."""

    @classmethod
    def get_provider(cls, platform: Platform) -> IssueTrackerProvider:
        """Get singleton provider instance for a platform."""

    @classmethod
    def get_provider_for_input(cls, input_str: str) -> IssueTrackerProvider:
        """Convenience method combining detection and lookup."""

    @classmethod
    def list_platforms(cls) -> list[Platform]:
        """List all registered platforms."""

    @classmethod
    def set_user_interaction(cls, ui: UserInteractionInterface) -> None:
        """Set the user interaction implementation."""

    @classmethod
    def get_user_interaction(cls) -> UserInteractionInterface:
        """Get the current user interaction implementation."""

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
```

### Step 2: Update Package Exports

**File:** `spec/integrations/providers/__init__.py`

Add `ProviderRegistry` to exports:
- Import from `registry.py`
- Add to `__all__` list

### Step 3: Add Unit Tests

**File:** `tests/test_provider_registry.py`

Test coverage for:
- Decorator registration
- Singleton instance creation
- Platform lookup and error handling
- `get_provider_for_input()` with PlatformDetector
- Thread safety
- `clear()` for test isolation
- Dependency injection for UserInteractionInterface

---

## File Changes Detail

### New: `spec/integrations/providers/registry.py`

Key implementation details:

1. **Registration Decorator:**
   - Validates `PLATFORM` class attribute exists
   - Stores class reference (not instance) in `_providers` dict
   - Returns class unchanged for decorator chaining

2. **Singleton Provider Lookup:**
   - Thread-safe instantiation using `threading.Lock`
   - Lazy instantiation (only when first requested)
   - Raises `PlatformNotSupportedError` for unregistered platforms

3. **Input-based Provider Selection:**
   - Delegates to `PlatformDetector.detect()` for platform detection
   - Returns provider instance for detected platform
   - Propagates `PlatformNotSupportedError` from detector

4. **Test Support:**
   - `clear()` resets both `_providers` and `_instances`
   - `set_user_interaction()` enables mock injection

### Modified: `spec/integrations/providers/__init__.py`

Add imports and exports:

```python
from spec.integrations.providers.registry import ProviderRegistry

__all__ = [
    # ... existing exports ...
    # Registry
    "ProviderRegistry",
]
```

---

## Testing Strategy

### Unit Tests (`tests/test_provider_registry.py`)

1. **Registration Tests**
   - `test_register_decorator_adds_to_registry` - Verify provider class is stored
   - `test_register_without_platform_raises_typeerror` - Missing PLATFORM attribute
   - `test_register_returns_class_unchanged` - Decorator returns original class
   - `test_register_multiple_providers` - Multiple platforms registered

2. **Singleton Tests**
   - `test_get_provider_returns_singleton` - Same instance for repeated calls
   - `test_get_provider_creates_instance_lazily` - Not created until first get
   - `test_get_provider_unregistered_raises_error` - PlatformNotSupportedError

3. **Input Detection Tests**
   - `test_get_provider_for_input_jira_url` - Jira URL detection
   - `test_get_provider_for_input_github_url` - GitHub URL detection
   - `test_get_provider_for_input_ticket_id` - Short ID format
   - `test_get_provider_for_input_unknown_raises_error` - Unknown input

4. **Utility Method Tests**
   - `test_list_platforms_returns_registered` - All registered platforms
   - `test_list_platforms_empty_initially` - Empty after clear()
   - `test_clear_resets_providers_and_instances` - Full reset
   - `test_set_user_interaction` - DI works correctly
   - `test_get_user_interaction_returns_current` - Getter works

5. **Thread Safety Tests**
   - `test_concurrent_get_provider_returns_same_instance` - Thread safety

### Mock Provider for Testing

```python
@ProviderRegistry.register
class MockJiraProvider(IssueTrackerProvider):
    """Mock provider for testing."""

    PLATFORM = Platform.JIRA

    @property
    def platform(self) -> Platform:
        return Platform.JIRA

    @property
    def name(self) -> str:
        return "Mock Jira"

    # ... other required methods with minimal implementations
```

---

## Migration Considerations

### Backward Compatibility

- **No breaking changes** - This is a new module with no existing dependents
- Existing `PlatformDetector` and `IssueTrackerProvider` remain unchanged
- Future provider implementations (AMI-18: JiraProvider) will use the registry

### Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| `Platform` enum | ✅ Implemented | `spec/integrations/providers/base.py` |
| `IssueTrackerProvider` ABC | ✅ Implemented | `spec/integrations/providers/base.py` |
| `PlatformDetector` | ✅ Implemented | `spec/integrations/providers/detector.py` |
| `PlatformNotSupportedError` | ✅ Implemented | `spec/integrations/providers/exceptions.py` |
| `UserInteractionInterface` | ✅ Implemented | `spec/integrations/providers/user_interaction.py` |
| `CLIUserInteraction` | ✅ Implemented | `spec/integrations/providers/user_interaction.py` |

### Downstream Dependents (Future)

- **AMI-18:** `JiraProvider` uses `@ProviderRegistry.register` decorator
- **AMI-27:** `AuggieMediatedFetcher` may use registry for provider lookup
- **CLI Integration:** `specflow/cli.py` will use `get_provider_for_input()`

---

## Acceptance Criteria Checklist

From the ticket:

- [ ] `@ProviderRegistry.register` decorator works without instantiating provider
- [ ] `get_provider()` returns singleton instance
- [ ] `get_provider_for_input()` integrates with `PlatformDetector`
- [ ] `PlatformNotSupportedError` raised for unregistered platforms
- [ ] `clear()` method works for test isolation
- [ ] `set_user_interaction()` enables DI for testing
- [ ] Exports added to `providers/__init__.py`
- [ ] Unit tests with mock providers

Additional implementation requirements:

- [ ] Thread-safe singleton instantiation
- [ ] `list_platforms()` method implemented
- [ ] `get_user_interaction()` getter method implemented
- [ ] Type hints and docstrings for all public methods
- [ ] Follows existing code style and patterns

---

## Example Usage

### Provider Registration (Future AMI-18)

```python
# In spec/integrations/providers/jira_provider.py

from spec.integrations.providers import IssueTrackerProvider, Platform, ProviderRegistry

@ProviderRegistry.register
class JiraProvider(IssueTrackerProvider):
    """Jira issue tracker provider."""

    PLATFORM = Platform.JIRA

    @property
    def platform(self) -> Platform:
        return Platform.JIRA

    @property
    def name(self) -> str:
        return "Jira"

    # ... implementation
```

### Provider Lookup (Future CLI Integration)

```python
# In spec/cli.py

from spec.integrations.providers import ProviderRegistry, PlatformNotSupportedError

def fetch_ticket(input_str: str) -> GenericTicket:
    try:
        provider = ProviderRegistry.get_provider_for_input(input_str)
        ticket_id = provider.parse_input(input_str)
        return provider.fetch_ticket(ticket_id)
    except PlatformNotSupportedError as e:
        print(f"Error: {e}")
        raise
```

### Test Isolation

```python
# In tests/test_some_feature.py

import pytest
from spec.integrations.providers import ProviderRegistry

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()
```
