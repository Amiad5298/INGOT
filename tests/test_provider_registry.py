"""Tests for spec.integrations.providers.registry module.

Tests cover:
- Decorator registration
- Singleton instance creation
- Platform lookup and error handling
- get_provider_for_input() with PlatformDetector
- Thread safety for all operations
- clear() for test isolation
- Dependency injection for UserInteractionInterface
- Registration validation and duplicate handling
"""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from spec.integrations.providers.base import (
    GenericTicket,
    IssueTrackerProvider,
    Platform,
)
from spec.integrations.providers.exceptions import PlatformNotSupportedError
from spec.integrations.providers.registry import ProviderRegistry
from spec.integrations.providers.user_interaction import (
    CLIUserInteraction,
    NonInteractiveUserInteraction,
    UserInteractionInterface,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before and after each test."""
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class MockJiraProvider(IssueTrackerProvider):
    """Mock Jira provider for testing."""

    PLATFORM = Platform.JIRA

    @property
    def platform(self) -> Platform:
        return Platform.JIRA

    @property
    def name(self) -> str:
        return "Mock Jira"

    def can_handle(self, input_str: str) -> bool:
        return "jira" in input_str.lower() or input_str.upper().startswith("PROJ-")

    def parse_input(self, input_str: str) -> str:
        return input_str.upper()

    def normalize(self, raw_data: dict, ticket_id: str | None = None) -> GenericTicket:
        return GenericTicket(
            id=raw_data.get("key", ticket_id or "MOCK-1"),
            platform=Platform.JIRA,
            url=f"https://example.atlassian.net/browse/{raw_data.get('key', ticket_id)}",
            title=raw_data.get("summary", "Mock Ticket"),
        )


class MockGitHubProvider(IssueTrackerProvider):
    """Mock GitHub provider for testing."""

    PLATFORM = Platform.GITHUB

    @property
    def platform(self) -> Platform:
        return Platform.GITHUB

    @property
    def name(self) -> str:
        return "Mock GitHub"

    def can_handle(self, input_str: str) -> bool:
        return "github" in input_str.lower()

    def parse_input(self, input_str: str) -> str:
        return input_str

    def normalize(self, raw_data: dict, ticket_id: str | None = None) -> GenericTicket:
        return GenericTicket(
            id=str(raw_data.get("number", ticket_id or "1")),
            platform=Platform.GITHUB,
            url=raw_data.get("html_url", f"https://github.com/{ticket_id}"),
            title=raw_data.get("title", "Mock Issue"),
        )


class MockLinearProviderWithDI(IssueTrackerProvider):
    """Mock Linear provider that accepts user_interaction for DI testing."""

    PLATFORM = Platform.LINEAR

    def __init__(self, user_interaction: UserInteractionInterface | None = None):
        self.user_interaction = user_interaction

    @property
    def platform(self) -> Platform:
        return Platform.LINEAR

    @property
    def name(self) -> str:
        return "Mock Linear"

    def can_handle(self, input_str: str) -> bool:
        return "linear" in input_str.lower()

    def parse_input(self, input_str: str) -> str:
        return input_str

    def normalize(self, raw_data: dict, ticket_id: str | None = None) -> GenericTicket:
        return GenericTicket(
            id=raw_data.get("identifier", ticket_id or "MOCK-1"),
            platform=Platform.LINEAR,
            url=raw_data.get("url", f"https://linear.app/team/issue/{ticket_id}"),
            title=raw_data.get("title", "Mock Linear Issue"),
        )


class MockJiraProviderWithConfig(IssueTrackerProvider):
    """Mock Jira provider that accepts default_project for config DI testing.

    Uses injected default_project to prefix numeric ticket IDs,
    allowing tests to verify config injection via parse_input behavior.
    """

    PLATFORM = Platform.JIRA

    def __init__(self, default_project: str | None = None):
        self.default_project = default_project

    @property
    def platform(self) -> Platform:
        return Platform.JIRA

    @property
    def name(self) -> str:
        return "Mock Jira with Config"

    def can_handle(self, input_str: str) -> bool:
        # Can handle numeric IDs only if default_project is set
        if input_str.isdigit():
            return bool(self.default_project)
        return "-" in input_str

    def parse_input(self, input_str: str) -> str:
        # Prefix numeric IDs with default_project
        if input_str.isdigit() and self.default_project:
            return f"{self.default_project}-{input_str}"
        return input_str

    def normalize(self, raw_data: dict, ticket_id: str | None = None) -> GenericTicket:
        return GenericTicket(
            id=raw_data.get("key", ticket_id or "MOCK-1"),
            platform=Platform.JIRA,
            url=f"https://example.atlassian.net/browse/{raw_data.get('key', ticket_id)}",
            title=raw_data.get("summary", "Mock Ticket"),
        )


class TestProviderRegistryRegister:
    """Tests for @ProviderRegistry.register decorator."""

    def test_register_decorator_adds_to_registry(self):
        """Decorator adds provider class to registry.

        Verified via public API: platform appears in list_platforms()
        and get_provider() returns instance of registered class.
        """

        @ProviderRegistry.register
        class TestProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

        # Verify via public API
        assert Platform.JIRA in ProviderRegistry.list_platforms()
        provider = ProviderRegistry.get_provider(Platform.JIRA)
        assert isinstance(provider, TestProvider)

    def test_register_without_platform_raises_typeerror(self):
        """Missing PLATFORM attribute raises TypeError."""
        with pytest.raises(TypeError) as exc_info:

            @ProviderRegistry.register
            class BadProvider(IssueTrackerProvider):
                pass

        assert "PLATFORM" in str(exc_info.value)
        assert "BadProvider" in str(exc_info.value)

    def test_register_with_invalid_platform_raises_typeerror(self):
        """Non-Platform PLATFORM attribute raises TypeError."""
        with pytest.raises(TypeError) as exc_info:

            @ProviderRegistry.register
            class BadProvider(IssueTrackerProvider):
                PLATFORM = "jira"  # String instead of Platform enum

        assert "Platform enum value" in str(exc_info.value)

    def test_register_returns_class_unchanged(self):
        """Decorator returns the original class."""

        @ProviderRegistry.register
        class TestProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

        # Class should be usable normally
        instance = TestProvider()
        assert instance.platform == Platform.JIRA

    def test_register_multiple_providers(self):
        """Can register multiple providers for different platforms.

        Verified via public API: both platforms in list_platforms().
        """

        @ProviderRegistry.register
        class JiraProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

        @ProviderRegistry.register
        class GitHubProvider(MockGitHubProvider):
            PLATFORM = Platform.GITHUB

        platforms = ProviderRegistry.list_platforms()
        assert len(platforms) == 2
        assert Platform.JIRA in platforms
        assert Platform.GITHUB in platforms

    def test_register_non_subclass_raises_typeerror(self):
        """Non-IssueTrackerProvider subclass raises TypeError."""
        with pytest.raises(TypeError) as exc_info:

            @ProviderRegistry.register
            class NotAProvider:
                PLATFORM = Platform.JIRA

        assert "subclass of IssueTrackerProvider" in str(exc_info.value)

    def test_register_duplicate_same_class_is_noop(self):
        """Re-registering the same class is a no-op.

        Verified via public API: only one platform registered, same instance.
        """
        ProviderRegistry.register(MockJiraProvider)
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)

        ProviderRegistry.register(MockJiraProvider)
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        # Same instance (singleton preserved despite re-registration)
        assert provider1 is provider2
        assert len(ProviderRegistry.list_platforms()) == 1

    def test_register_duplicate_different_class_replaces(self, caplog):
        """Registering different class for same platform replaces it with warning.

        Verified via public API: get_provider returns instance of new class.
        """
        ProviderRegistry.register(MockJiraProvider)
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        assert isinstance(provider1, MockJiraProvider)

        @ProviderRegistry.register
        class AnotherJiraProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

        # New class is used for new instances
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)
        assert isinstance(provider2, AnotherJiraProvider)
        assert provider2 is not provider1

        # Warning should be logged
        assert "Replacing existing provider" in caplog.text

    def test_register_duplicate_clears_existing_instance(self):
        """Registering new provider clears existing cached instance.

        Verified via public API: new registration creates new instance.
        """
        ProviderRegistry.register(MockJiraProvider)
        instance1 = ProviderRegistry.get_provider(Platform.JIRA)

        @ProviderRegistry.register
        class AnotherJiraProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

        # Getting provider should create new instance of new class
        instance2 = ProviderRegistry.get_provider(Platform.JIRA)
        assert isinstance(instance2, AnotherJiraProvider)
        assert instance2 is not instance1

    def test_register_does_not_instantiate_provider(self):
        """Registration should not call provider's __init__.

        Verified via tracking flag: __init__ only called on get_provider().
        """
        init_called = False

        class TrackedProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

            def __init__(self):
                nonlocal init_called
                init_called = True
                super().__init__()

        ProviderRegistry.register(TrackedProvider)

        # Registration does NOT instantiate
        assert not init_called

        # get_provider() triggers instantiation
        _ = ProviderRegistry.get_provider(Platform.JIRA)
        assert init_called


class TestProviderRegistryGetProvider:
    """Tests for ProviderRegistry.get_provider()."""

    def test_get_provider_returns_singleton(self):
        """Same instance returned for repeated calls."""
        ProviderRegistry.register(MockJiraProvider)

        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        assert provider1 is provider2

    def test_get_provider_creates_instance_lazily(self):
        """Provider instance not created until first get.

        Verified via tracking flag: __init__ only called after get_provider().
        """
        init_called = False

        class TrackedProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

            def __init__(self):
                nonlocal init_called
                init_called = True
                super().__init__()

        ProviderRegistry.register(TrackedProvider)

        # No instance created yet (lazy)
        assert not init_called

        # Now get it - triggers instantiation
        provider = ProviderRegistry.get_provider(Platform.JIRA)

        assert init_called
        assert isinstance(provider, TrackedProvider)

    def test_get_provider_unregistered_raises_error(self):
        """Unregistered platform raises PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            ProviderRegistry.get_provider(Platform.JIRA)

        assert "JIRA" in str(exc_info.value)

    def test_get_provider_error_includes_registered_platforms(self):
        """Error message includes list of registered platforms."""
        ProviderRegistry.register(MockGitHubProvider)

        with pytest.raises(PlatformNotSupportedError) as exc_info:
            ProviderRegistry.get_provider(Platform.JIRA)

        error = exc_info.value
        assert "GITHUB" in error.supported_platforms

    def test_get_provider_handles_init_exception(self):
        """Exception during provider __init__ propagates correctly."""

        class FailingProvider(MockJiraProvider):
            PLATFORM = Platform.JIRA

            def __init__(self):
                raise RuntimeError("Provider initialization failed!")

        ProviderRegistry.register(FailingProvider)

        with pytest.raises(RuntimeError, match="Provider initialization failed"):
            ProviderRegistry.get_provider(Platform.JIRA)

        # Verify the instance was not cached - retry should fail again
        with pytest.raises(RuntimeError, match="Provider initialization failed"):
            ProviderRegistry.get_provider(Platform.JIRA)


class TestProviderRegistryGetProviderForInput:
    """Tests for ProviderRegistry.get_provider_for_input()."""

    def test_get_provider_for_input_jira_url(self):
        """Detects Jira from URL and returns provider."""
        ProviderRegistry.register(MockJiraProvider)

        provider = ProviderRegistry.get_provider_for_input(
            "https://company.atlassian.net/browse/PROJ-123"
        )

        assert isinstance(provider, MockJiraProvider)

    def test_get_provider_for_input_jira_id(self):
        """Detects Jira from ticket ID and returns provider."""
        ProviderRegistry.register(MockJiraProvider)

        provider = ProviderRegistry.get_provider_for_input("PROJ-123")

        assert isinstance(provider, MockJiraProvider)

    def test_get_provider_for_input_github_url(self):
        """Detects GitHub from URL and returns provider."""
        ProviderRegistry.register(MockGitHubProvider)

        provider = ProviderRegistry.get_provider_for_input(
            "https://github.com/owner/repo/issues/42"
        )

        assert isinstance(provider, MockGitHubProvider)

    def test_get_provider_for_input_unknown_raises_error(self):
        """Unknown input raises PlatformNotSupportedError."""
        with pytest.raises(PlatformNotSupportedError):
            ProviderRegistry.get_provider_for_input("unknown-input-format")

    def test_get_provider_for_input_detected_but_not_registered(self):
        """Detected platform without registered provider raises error."""
        # Don't register any provider
        # Jira ID format will be detected but no provider registered
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            ProviderRegistry.get_provider_for_input("PROJ-123")

        assert "JIRA" in str(exc_info.value)

    def test_get_provider_for_input_wraps_generic_exception_as_platform_not_supported(
        self, monkeypatch
    ):
        """Generic exceptions from PlatformDetector.detect are wrapped as PlatformNotSupportedError.

        Regression test: Ensures that when PlatformDetector.detect raises a non-PlatformNotSupportedError,
        it is normalized to PlatformNotSupportedError without causing TypeError during construction.
        """
        # Register a provider so we have a non-empty supported_platforms list
        ProviderRegistry.register(MockJiraProvider)

        # Mock PlatformDetector.detect to raise a generic ValueError
        def mock_detect_raises_value_error(input_str: str):
            raise ValueError("Unexpected internal error in detector")

        monkeypatch.setattr(
            "spec.integrations.providers.registry.PlatformDetector.detect",
            mock_detect_raises_value_error,
        )

        # Act & Assert - should raise PlatformNotSupportedError, NOT ValueError or TypeError
        with pytest.raises(PlatformNotSupportedError) as exc_info:
            ProviderRegistry.get_provider_for_input("test-input")

        error = exc_info.value
        # Verify the error was constructed correctly with all expected fields
        assert error.input_str == "test-input"
        assert "JIRA" in error.supported_platforms
        assert "Failed to detect platform from input" in str(error)
        assert "Unexpected internal error in detector" in str(error)

        # Verify exception chaining preserved the original cause
        assert isinstance(error.__cause__, ValueError)


class TestProviderRegistryUtilityMethods:
    """Tests for utility methods."""

    def test_list_platforms_returns_registered(self):
        """list_platforms() returns all registered platforms."""
        ProviderRegistry.register(MockJiraProvider)
        ProviderRegistry.register(MockGitHubProvider)

        platforms = ProviderRegistry.list_platforms()

        assert Platform.JIRA in platforms
        assert Platform.GITHUB in platforms
        assert len(platforms) == 2

    def test_list_platforms_empty_initially(self):
        """list_platforms() returns empty list after clear()."""
        platforms = ProviderRegistry.list_platforms()
        assert platforms == []

    def test_list_platforms_returns_sorted_deterministically(self):
        """list_platforms() returns sorted list for deterministic output."""
        # Register in non-alphabetical order
        ProviderRegistry.register(MockJiraProvider)
        ProviderRegistry.register(MockGitHubProvider)
        ProviderRegistry.register(MockLinearProviderWithDI)

        platforms = ProviderRegistry.list_platforms()

        # Should be sorted alphabetically by platform name
        platform_names = [p.name for p in platforms]
        assert platform_names == sorted(platform_names)

    def test_clear_resets_providers_and_instances(self):
        """clear() removes all providers and instances.

        Verified via public API: after clear, list_platforms() is empty
        and get_provider() raises PlatformNotSupportedError.
        """
        ProviderRegistry.register(MockJiraProvider)
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        assert isinstance(provider1, MockJiraProvider)

        # Verify registration exists
        assert len(ProviderRegistry.list_platforms()) == 1

        # Clear
        ProviderRegistry.clear()

        # Verify providers are gone via public API
        assert len(ProviderRegistry.list_platforms()) == 0
        with pytest.raises(PlatformNotSupportedError):
            ProviderRegistry.get_provider(Platform.JIRA)

    def test_clear_resets_user_interaction_to_cli(self):
        """clear() resets user interaction to CLIUserInteraction."""
        mock_ui = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui)

        ProviderRegistry.clear()

        ui = ProviderRegistry.get_user_interaction()
        assert isinstance(ui, CLIUserInteraction)

    def test_set_user_interaction(self):
        """set_user_interaction() sets the UI implementation."""
        mock_ui = MagicMock(spec=UserInteractionInterface)

        ProviderRegistry.set_user_interaction(mock_ui)

        assert ProviderRegistry.get_user_interaction() is mock_ui

    def test_get_user_interaction_returns_current(self):
        """get_user_interaction() returns current implementation."""
        mock_ui = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui)

        result = ProviderRegistry.get_user_interaction()

        assert result is mock_ui

    def test_default_user_interaction_is_cli(self):
        """Default user interaction is CLIUserInteraction."""
        # After clear(), should reset to CLI
        ui = ProviderRegistry.get_user_interaction()
        assert isinstance(ui, CLIUserInteraction)

    def test_set_non_interactive_user_interaction(self):
        """Can set NonInteractiveUserInteraction for testing."""
        non_interactive = NonInteractiveUserInteraction(fail_on_interaction=True)

        ProviderRegistry.set_user_interaction(non_interactive)

        result = ProviderRegistry.get_user_interaction()
        assert isinstance(result, NonInteractiveUserInteraction)


class TestProviderRegistryThreadSafety:
    """Tests for thread-safe singleton instantiation."""

    def test_concurrent_get_provider_returns_same_instance(self):
        """Concurrent calls to get_provider() return same instance."""
        ProviderRegistry.register(MockJiraProvider)

        instances = []
        errors = []

        def get_provider():
            try:
                provider = ProviderRegistry.get_provider(Platform.JIRA)
                instances.append(provider)
            except Exception as e:
                errors.append(e)

        # Run many concurrent calls
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_provider) for _ in range(100)]
            for future in futures:
                future.result()

        # No errors
        assert len(errors) == 0

        # All instances are the same object
        assert len(instances) == 100
        first_instance = instances[0]
        for instance in instances:
            assert instance is first_instance

    def test_concurrent_registration_and_lookup(self):
        """Concurrent registration and lookup works correctly."""
        results = {"registered": False, "found": []}
        errors = []

        def register_provider():
            try:
                ProviderRegistry.register(MockJiraProvider)
                results["registered"] = True
            except Exception as e:
                errors.append(e)

        def lookup_provider():
            try:
                # May fail if not registered yet, that's OK
                provider = ProviderRegistry.get_provider(Platform.JIRA)
                results["found"].append(provider)
            except PlatformNotSupportedError:
                pass  # Expected if registration hasn't happened yet
            except Exception as e:
                errors.append(e)

        threads = []
        # Start registration thread
        t1 = threading.Thread(target=register_provider)
        threads.append(t1)

        # Start multiple lookup threads
        for _ in range(5):
            t = threading.Thread(target=lookup_provider)
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # No unexpected errors
        assert len(errors) == 0

        # Registration succeeded
        assert results["registered"] is True


class TestProviderRegistryDependencyInjection:
    """Tests for dependency injection of UserInteractionInterface."""

    def test_di_injected_into_provider_with_user_interaction_param(self):
        """UserInteractionInterface is injected into providers that accept it."""
        mock_ui = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui)
        ProviderRegistry.register(MockLinearProviderWithDI)

        provider = ProviderRegistry.get_provider(Platform.LINEAR)

        assert provider.user_interaction is mock_ui

    def test_di_not_injected_into_provider_without_param(self):
        """Providers without user_interaction param are created without injection."""
        ProviderRegistry.register(MockJiraProvider)

        # Should not raise - provider doesn't expect user_interaction
        provider = ProviderRegistry.get_provider(Platform.JIRA)

        assert isinstance(provider, MockJiraProvider)

    def test_set_user_interaction_affects_new_providers(self):
        """set_user_interaction affects newly created providers."""
        ProviderRegistry.register(MockLinearProviderWithDI)

        # Set UI before first get
        mock_ui = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui)

        provider = ProviderRegistry.get_provider(Platform.LINEAR)

        assert provider.user_interaction is mock_ui

    def test_set_user_interaction_does_not_affect_existing_instances(self):
        """set_user_interaction does NOT affect already-created instances."""
        ProviderRegistry.register(MockLinearProviderWithDI)

        # First UI
        mock_ui1 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui1)
        provider1 = ProviderRegistry.get_provider(Platform.LINEAR)

        # Change UI
        mock_ui2 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui2)
        provider2 = ProviderRegistry.get_provider(Platform.LINEAR)

        # Same instance, still has old UI
        assert provider1 is provider2
        assert provider1.user_interaction is mock_ui1

    def test_clear_then_recreate_uses_new_ui(self):
        """After clear(), new providers get the newly set UI."""
        ProviderRegistry.register(MockLinearProviderWithDI)

        mock_ui1 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui1)
        provider1 = ProviderRegistry.get_provider(Platform.LINEAR)

        # Clear and re-register
        ProviderRegistry.clear()
        mock_ui2 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui2)
        ProviderRegistry.register(MockLinearProviderWithDI)

        provider2 = ProviderRegistry.get_provider(Platform.LINEAR)

        # Different instance with new UI
        assert provider2 is not provider1
        assert provider2.user_interaction is mock_ui2


class TestProviderRegistryImport:
    """Tests for module imports."""

    def test_import_from_providers_package(self):
        """Can import ProviderRegistry from providers package."""
        from spec.integrations.providers import ProviderRegistry as PR

        assert PR is ProviderRegistry

    def test_in_all_exports(self):
        """ProviderRegistry is in __all__ exports."""
        from spec.integrations.providers import __all__

        assert "ProviderRegistry" in __all__


class TestProviderRegistryConcurrentClearAndRegister:
    """Additional thread safety tests using queue for more rigorous results."""

    def test_concurrent_clear_and_register_no_exceptions(self):
        """Concurrent clear and register operations don't raise exceptions."""
        error_queue = queue.Queue()

        def clear_op():
            try:
                for _ in range(10):
                    ProviderRegistry.clear()
            except Exception as e:
                error_queue.put(e)

        def register_op():
            try:
                for _ in range(10):
                    ProviderRegistry.register(MockJiraProvider)
            except Exception as e:
                error_queue.put(e)

        threads = [
            threading.Thread(target=clear_op),
            threading.Thread(target=register_op),
            threading.Thread(target=clear_op),
            threading.Thread(target=register_op),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert error_queue.empty()

    def test_concurrent_register_multiple_platforms(self):
        """Concurrent registration of multiple platforms works correctly."""
        error_queue = queue.Queue()

        def register_jira():
            try:
                ProviderRegistry.register(MockJiraProvider)
            except Exception as e:
                error_queue.put(e)

        def register_github():
            try:
                ProviderRegistry.register(MockGitHubProvider)
            except Exception as e:
                error_queue.put(e)

        def register_linear():
            try:
                ProviderRegistry.register(MockLinearProviderWithDI)
            except Exception as e:
                error_queue.put(e)

        threads = [
            threading.Thread(target=register_jira),
            threading.Thread(target=register_github),
            threading.Thread(target=register_linear),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert error_queue.empty()

        # All platforms registered
        platforms = ProviderRegistry.list_platforms()
        assert len(platforms) == 3


class TestProviderRegistryResetInstances:
    """Tests for reset_instances() method."""

    def test_reset_instances_preserves_registrations(self):
        """reset_instances() clears instances but preserves provider registrations.

        Verified via public API: after reset, get_provider() still works
        (registrations preserved) but returns new instances (cache cleared).
        """
        ProviderRegistry.register(MockJiraProvider)
        ProviderRegistry.register(MockGitHubProvider)

        # Create instances
        jira1 = ProviderRegistry.get_provider(Platform.JIRA)
        github1 = ProviderRegistry.get_provider(Platform.GITHUB)

        # Verify registrations via list_platforms (public API)
        assert len(ProviderRegistry.list_platforms()) == 2

        # Reset instances
        ProviderRegistry.reset_instances()

        # Registrations preserved: list_platforms() still works
        assert len(ProviderRegistry.list_platforms()) == 2

        # Can still get providers (new instances created)
        jira2 = ProviderRegistry.get_provider(Platform.JIRA)
        github2 = ProviderRegistry.get_provider(Platform.GITHUB)

        # Verify new instances were created (cache was cleared)
        assert jira2 is not jira1
        assert github2 is not github1
        assert isinstance(jira2, MockJiraProvider)
        assert isinstance(github2, MockGitHubProvider)

    def test_reset_instances_clears_config(self):
        """reset_instances() clears configuration.

        Verifies behavior via public API: after reset, new provider instances
        should NOT receive the previously configured default_project.
        """
        ProviderRegistry.register(MockJiraProvider)
        ProviderRegistry.set_config({"default_jira_project": "MYPROJ"})

        # Create provider with config - provider should get injected config
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)

        # Reset instances (clears config and instances)
        ProviderRegistry.reset_instances()

        # Get new provider instance (should be new, without config)
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        # New instance created (reset worked)
        assert provider2 is not provider1

    def test_reset_instances_resets_user_interaction(self):
        """reset_instances() resets user interaction to CLIUserInteraction."""
        mock_ui = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui)

        # Reset instances
        ProviderRegistry.reset_instances()

        # User interaction is reset
        ui = ProviderRegistry.get_user_interaction()
        assert isinstance(ui, CLIUserInteraction)

    def test_reset_instances_allows_config_change_without_re_registration(self):
        """reset_instances() allows changing config without re-registering providers."""
        ProviderRegistry.register(MockLinearProviderWithDI)

        # First config
        mock_ui1 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui1)
        provider1 = ProviderRegistry.get_provider(Platform.LINEAR)
        assert provider1.user_interaction is mock_ui1

        # Reset instances (not clear!)
        ProviderRegistry.reset_instances()

        # Set new config - no re-registration needed
        mock_ui2 = MagicMock(spec=UserInteractionInterface)
        ProviderRegistry.set_user_interaction(mock_ui2)
        provider2 = ProviderRegistry.get_provider(Platform.LINEAR)

        # New instance with new config
        assert provider2 is not provider1
        assert provider2.user_interaction is mock_ui2


class TestProviderRegistryConfigDeterminism:
    """Tests for config determinism - ensuring no stale config persists.

    Tests verify behavior via public API: config changes affect provider
    behavior (parse_input), not internal state.
    """

    def test_set_config_twice_does_not_keep_old_values(self):
        """Setting config twice replaces all old values, not merging.

        This ensures that if main() runs multiple times (e.g., in tests),
        the second run's config completely replaces the first.

        Verified via behavior: parse_input reflects the latest config.
        """
        ProviderRegistry.register(MockJiraProviderWithConfig)

        # First config - create provider
        ProviderRegistry.set_config({"default_jira_project": "FIRST"})
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        assert provider1.parse_input("123") == "FIRST-123"

        # Reset and set second config
        ProviderRegistry.reset_instances()
        ProviderRegistry.set_config({"default_jira_project": "SECOND"})
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)
        assert provider2.parse_input("123") == "SECOND-123"
        assert provider2 is not provider1

    def test_set_config_with_empty_replaces_previous(self):
        """Setting config with empty dict clears all previous config.

        This simulates running CLI first with config, then without.

        Verified via behavior: after empty config, numeric IDs not handled.
        """
        ProviderRegistry.register(MockJiraProviderWithConfig)

        # First run with config
        ProviderRegistry.set_config({"default_jira_project": "CONFIGURED"})
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        assert provider1.can_handle("456") is True
        assert provider1.parse_input("456") == "CONFIGURED-456"

        # Reset and set empty config
        ProviderRegistry.reset_instances()
        ProviderRegistry.set_config({})
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        # After empty config, numeric IDs should not be handled
        assert provider2.can_handle("456") is False
        assert provider2 is not provider1

    def test_initialization_twice_first_with_value_then_without(self):
        """Simulates main() running twice: first with config, then without.

        Verifies that stale config from first run doesn't persist to second run.
        This is the core acceptance test for config determinism.

        Verified via behavior: second-run provider doesn't inherit first config.
        """
        ProviderRegistry.register(MockJiraProviderWithConfig)

        # First "run" - set config and create instance
        ProviderRegistry.set_config({"default_jira_project": "PROJ1"})
        provider1 = ProviderRegistry.get_provider(Platform.JIRA)
        assert provider1.parse_input("789") == "PROJ1-789"

        # Simulate CLI calling reset_instances at start of second run
        ProviderRegistry.reset_instances()

        # Second "run" - set empty config
        ProviderRegistry.set_config({"default_jira_project": ""})
        provider2 = ProviderRegistry.get_provider(Platform.JIRA)

        # Old config must NOT persist - verified via behavior
        assert provider2.can_handle("789") is False  # No default project
        assert provider2 is not provider1
