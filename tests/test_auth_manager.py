"""Tests for spec.integrations.auth module.

Tests cover:
- AuthenticationManager initialization
- get_credentials() for various scenarios
- has_fallback_configured() convenience method
- list_fallback_platforms() enumeration
- validate_credentials() format validation
"""

from unittest.mock import MagicMock

import pytest

from spec.config.manager import ConfigManager
from spec.integrations.auth import AuthenticationManager, PlatformCredentials
from spec.integrations.providers.base import Platform

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config_manager():
    """Create a mock ConfigManager."""
    config = MagicMock(spec=ConfigManager)
    # Default: no credentials configured
    config.get_fallback_credentials.return_value = None
    return config


@pytest.fixture
def config_with_jira_creds(mock_config_manager):
    """ConfigManager with Jira credentials configured."""

    def get_creds(platform, **kwargs):
        if platform == "jira":
            return {
                "url": "https://company.atlassian.net",
                "email": "user@example.com",
                "token": "abc123",
            }
        return None

    mock_config_manager.get_fallback_credentials.side_effect = get_creds
    return mock_config_manager


@pytest.fixture
def config_with_multiple_creds(mock_config_manager):
    """ConfigManager with multiple platform credentials configured."""

    def get_creds(platform, **kwargs):
        creds_map = {
            "jira": {
                "url": "https://company.atlassian.net",
                "email": "user@example.com",
                "token": "jira-token",
            },
            "github": {"token": "github-token"},
            "linear": {"api_key": "linear-api-key"},
        }
        return creds_map.get(platform)

    mock_config_manager.get_fallback_credentials.side_effect = get_creds
    return mock_config_manager


# =============================================================================
# Initialization Tests
# =============================================================================


class TestAuthenticationManagerInit:
    """Tests for AuthenticationManager initialization."""

    def test_init_with_config_manager(self, mock_config_manager):
        """Accepts ConfigManager instance."""
        auth_manager = AuthenticationManager(mock_config_manager)

        assert auth_manager._config is mock_config_manager

    def test_supported_fallback_platforms_is_frozenset(self):
        """SUPPORTED_FALLBACK_PLATFORMS is a frozenset for immutability."""
        assert isinstance(AuthenticationManager.SUPPORTED_FALLBACK_PLATFORMS, frozenset)

    def test_supported_fallback_platforms_contains_expected_platforms(self):
        """SUPPORTED_FALLBACK_PLATFORMS contains the known fallback platforms."""
        expected_platforms = {
            Platform.JIRA,
            Platform.GITHUB,
            Platform.LINEAR,
            Platform.AZURE_DEVOPS,
            Platform.MONDAY,
            Platform.TRELLO,
        }
        assert AuthenticationManager.SUPPORTED_FALLBACK_PLATFORMS == expected_platforms

    def test_platform_names_are_lowercase(self):
        """Platform names derived from enum are lowercase."""
        for platform in AuthenticationManager.SUPPORTED_FALLBACK_PLATFORMS:
            name = AuthenticationManager._get_platform_name(platform)
            assert name == name.lower()
            assert "_" in name or name.isalpha()  # snake_case or single word


# =============================================================================
# get_credentials() Tests
# =============================================================================


class TestGetCredentials:
    """Tests for AuthenticationManager.get_credentials()."""

    def test_get_credentials_success(self, config_with_jira_creds):
        """Returns configured credentials."""
        auth_manager = AuthenticationManager(config_with_jira_creds)

        creds = auth_manager.get_credentials(Platform.JIRA)

        assert creds.platform == Platform.JIRA
        assert creds.is_configured is True
        assert creds.credentials == {
            "url": "https://company.atlassian.net",
            "email": "user@example.com",
            "token": "abc123",
        }
        assert creds.error_message is None

    def test_get_credentials_not_configured(self, mock_config_manager):
        """Returns error when no credentials configured."""
        auth_manager = AuthenticationManager(mock_config_manager)

        creds = auth_manager.get_credentials(Platform.GITHUB)

        assert creds.platform == Platform.GITHUB
        assert creds.is_configured is False
        assert creds.credentials == {}
        assert "No fallback credentials configured" in creds.error_message

    def test_get_credentials_missing_env_var(self, mock_config_manager):
        """Returns error for unexpanded environment variable."""
        from spec.utils.env_utils import EnvVarExpansionError

        mock_config_manager.get_fallback_credentials.side_effect = EnvVarExpansionError(
            "GITHUB_TOKEN", "Environment variable not set"
        )
        auth_manager = AuthenticationManager(mock_config_manager)

        creds = auth_manager.get_credentials(Platform.GITHUB)

        assert creds.is_configured is False
        assert creds.credentials == {}
        assert creds.error_message is not None

    def test_get_credentials_missing_required_fields(self, mock_config_manager):
        """Returns error for incomplete config."""
        from spec.config import ConfigValidationError

        mock_config_manager.get_fallback_credentials.side_effect = ConfigValidationError(
            "Missing required field: token"
        )
        auth_manager = AuthenticationManager(mock_config_manager)

        creds = auth_manager.get_credentials(Platform.JIRA)

        assert creds.is_configured is False
        assert creds.credentials == {}
        assert "token" in creds.error_message.lower()

    def test_get_credentials_unknown_exception_returns_generic_message(self, mock_config_manager):
        """Unknown exceptions return generic message to avoid leaking secrets.

        SECURITY: If ConfigManager raises an error containing raw secrets
        (e.g., "Invalid token 'sk-123...'"), we must NOT expose that in error_message.
        """
        # Simulate an unknown exception that might contain a secret in the message
        mock_config_manager.get_fallback_credentials.side_effect = RuntimeError(
            "Invalid token 'sk-secret-token-12345'"
        )
        auth_manager = AuthenticationManager(mock_config_manager)

        creds = auth_manager.get_credentials(Platform.GITHUB)

        assert creds.is_configured is False
        assert creds.credentials == {}
        # Should return generic message, NOT the exception message with the secret
        assert "sk-secret-token" not in creds.error_message
        assert "Failed to load credentials" in creds.error_message

    def test_get_credentials_all_platforms(self, mock_config_manager):
        """Can request credentials for all supported platforms."""
        auth_manager = AuthenticationManager(mock_config_manager)

        for platform in Platform:
            creds = auth_manager.get_credentials(platform)
            assert isinstance(creds, PlatformCredentials)
            assert creds.platform == platform

    def test_get_credentials_returns_frozen_dataclass(self, config_with_jira_creds):
        """PlatformCredentials is immutable."""
        auth_manager = AuthenticationManager(config_with_jira_creds)

        creds = auth_manager.get_credentials(Platform.JIRA)

        with pytest.raises(AttributeError):
            creds.is_configured = False  # type: ignore

    def test_get_credentials_unsupported_platform(self, mock_config_manager, monkeypatch):
        """Handles unsupported platform gracefully when not in SUPPORTED_FALLBACK_PLATFORMS."""
        # Use monkeypatch to safely mock the supported platforms set
        limited_platforms = frozenset({Platform.JIRA, Platform.GITHUB})
        monkeypatch.setattr(
            AuthenticationManager,
            "SUPPORTED_FALLBACK_PLATFORMS",
            limited_platforms,
        )

        auth_manager = AuthenticationManager(mock_config_manager)

        # TRELLO is now unsupported since we limited the set
        creds = auth_manager.get_credentials(Platform.TRELLO)

        assert creds.platform == Platform.TRELLO
        assert creds.is_configured is False
        assert creds.credentials == {}
        assert "does not support fallback credentials" in creds.error_message

    def test_get_credentials_with_aliases(self, mock_config_manager):
        """Credential aliases are normalized by ConfigManager.

        This test verifies that aliased keys (e.g., 'org' -> 'organization')
        are properly resolved when returned from get_credentials().
        The aliasing is handled by ConfigManager.get_fallback_credentials().
        """

        def get_creds_with_aliases(platform, **kwargs):
            if platform == "azure_devops":
                # ConfigManager returns canonical keys after alias resolution
                # 'org' -> 'organization' is resolved by canonicalize_credentials()
                return {
                    "organization": "myorg",  # Canonical key (was 'org' in config)
                    "pat": "secret-pat",
                }
            return None

        mock_config_manager.get_fallback_credentials.side_effect = get_creds_with_aliases
        auth_manager = AuthenticationManager(mock_config_manager)

        creds = auth_manager.get_credentials(Platform.AZURE_DEVOPS)

        assert creds.is_configured is True
        # Verify canonical keys are returned (not aliases)
        assert "organization" in creds.credentials
        assert "pat" in creds.credentials
        assert creds.credentials["organization"] == "myorg"
        assert creds.credentials["pat"] == "secret-pat"
        # Verify alias keys are NOT present
        assert "org" not in creds.credentials

    def test_get_credentials_calls_config_with_correct_keys(self, mock_config_manager):
        """Verify platform.name.lower() produces correct config keys.

        This test ensures that the Platform enum names map to the exact string
        keys expected by ConfigManager. If the Enum name ever changes (e.g.,
        AZURE_DEVOPS -> AZUREDEVOPS), this test will fail, preventing a
        regression in credential loading.

        NOTE: We verify only critical arguments (platform_name, strict=True)
        using call_args to avoid brittleness if ConfigManager adds optional parameters.
        """
        mock_config_manager.get_fallback_credentials.return_value = {"token": "test"}
        auth_manager = AuthenticationManager(mock_config_manager)

        # Test AZURE_DEVOPS specifically - its underscore is critical
        auth_manager.get_credentials(Platform.AZURE_DEVOPS)
        call_args = mock_config_manager.get_fallback_credentials.call_args
        assert call_args.args[0] == "azure_devops"
        assert call_args.kwargs.get("strict") is True

        # Test other platforms to ensure consistent naming contract
        mock_config_manager.reset_mock()
        mock_config_manager.get_fallback_credentials.return_value = {"token": "test"}

        auth_manager.get_credentials(Platform.JIRA)
        call_args = mock_config_manager.get_fallback_credentials.call_args
        assert call_args.args[0] == "jira"
        assert call_args.kwargs.get("strict") is True

        mock_config_manager.reset_mock()
        mock_config_manager.get_fallback_credentials.return_value = {"token": "test"}

        auth_manager.get_credentials(Platform.GITHUB)
        call_args = mock_config_manager.get_fallback_credentials.call_args
        assert call_args.args[0] == "github"
        assert call_args.kwargs.get("strict") is True


# =============================================================================
# has_fallback_configured() Tests
# =============================================================================


class TestHasFallbackConfigured:
    """Tests for AuthenticationManager.has_fallback_configured()."""

    def test_has_fallback_configured_true(self, config_with_jira_creds):
        """Returns True when credentials are configured."""
        auth_manager = AuthenticationManager(config_with_jira_creds)

        assert auth_manager.has_fallback_configured(Platform.JIRA) is True

    def test_has_fallback_configured_false(self, mock_config_manager):
        """Returns False when credentials are not configured."""
        auth_manager = AuthenticationManager(mock_config_manager)

        assert auth_manager.has_fallback_configured(Platform.GITHUB) is False

    def test_has_fallback_configured_partial(self, config_with_multiple_creds):
        """Returns correct status for mixed configuration."""
        auth_manager = AuthenticationManager(config_with_multiple_creds)

        assert auth_manager.has_fallback_configured(Platform.JIRA) is True
        assert auth_manager.has_fallback_configured(Platform.GITHUB) is True
        assert auth_manager.has_fallback_configured(Platform.LINEAR) is True
        assert auth_manager.has_fallback_configured(Platform.AZURE_DEVOPS) is False
        assert auth_manager.has_fallback_configured(Platform.MONDAY) is False
        assert auth_manager.has_fallback_configured(Platform.TRELLO) is False

    def test_has_fallback_configured_false_positive_prevention(self, mock_config_manager):
        """Returns False when credentials exist but no required key is present.

        This tests the fix for false positives where a user has a typo
        (e.g., FALLBACK_JIRA_TOKE instead of FALLBACK_JIRA_TOKEN).
        """

        def get_creds_with_typo(platform, **kwargs):
            if platform == "jira":
                # Simulates typo: FALLBACK_JIRA_TOKE instead of FALLBACK_JIRA_TOKEN
                return {
                    "toke": "abc123",  # typo - not a required key
                    "emal": "user@example.com",  # typo - not a required key
                }
            return None

        mock_config_manager.get_fallback_credentials.side_effect = get_creds_with_typo
        auth_manager = AuthenticationManager(mock_config_manager)

        # Should return False because no required keys (url, email, token) are present
        assert auth_manager.has_fallback_configured(Platform.JIRA) is False

    def test_has_fallback_configured_with_at_least_one_required_key(self, mock_config_manager):
        """Returns True when at least one required key exists."""

        def get_creds_partial(platform, **kwargs):
            if platform == "jira":
                # Has one required key (token), missing others
                return {"token": "abc123"}
            return None

        mock_config_manager.get_fallback_credentials.side_effect = get_creds_partial
        auth_manager = AuthenticationManager(mock_config_manager)

        # Should return True because at least one required key (token) is present
        assert auth_manager.has_fallback_configured(Platform.JIRA) is True


# =============================================================================
# list_fallback_platforms() Tests
# =============================================================================


class TestListFallbackPlatforms:
    """Tests for AuthenticationManager.list_fallback_platforms()."""

    def test_list_fallback_platforms_empty(self, mock_config_manager):
        """Returns empty list when no credentials configured."""
        auth_manager = AuthenticationManager(mock_config_manager)

        platforms = auth_manager.list_fallback_platforms()

        assert platforms == []

    def test_list_fallback_platforms_multiple(self, config_with_multiple_creds):
        """Returns all configured platforms."""
        auth_manager = AuthenticationManager(config_with_multiple_creds)

        platforms = auth_manager.list_fallback_platforms()

        assert len(platforms) == 3
        assert Platform.JIRA in platforms
        assert Platform.GITHUB in platforms
        assert Platform.LINEAR in platforms

    def test_list_fallback_platforms_single(self, config_with_jira_creds):
        """Returns single configured platform."""
        auth_manager = AuthenticationManager(config_with_jira_creds)

        platforms = auth_manager.list_fallback_platforms()

        assert platforms == [Platform.JIRA]

    def test_list_fallback_platforms_returns_platform_enums(self, config_with_multiple_creds):
        """Returns Platform enum values, not strings."""
        auth_manager = AuthenticationManager(config_with_multiple_creds)

        platforms = auth_manager.list_fallback_platforms()

        for platform in platforms:
            assert isinstance(platform, Platform)


# =============================================================================
# validate_credentials() Tests
# =============================================================================


class TestValidateCredentials:
    """Tests for AuthenticationManager.validate_credentials()."""

    def test_validate_credentials_success(self, config_with_jira_creds):
        """Returns (True, message) for valid credentials."""
        auth_manager = AuthenticationManager(config_with_jira_creds)

        success, message = auth_manager.validate_credentials(Platform.JIRA)

        assert success is True
        assert "JIRA" in message
        assert "configured" in message.lower()

    def test_validate_credentials_failure_not_configured(self, mock_config_manager):
        """Returns (False, error) when not configured."""
        auth_manager = AuthenticationManager(mock_config_manager)

        success, message = auth_manager.validate_credentials(Platform.GITHUB)

        assert success is False
        assert message is not None
        assert len(message) > 0

    def test_validate_credentials_failure_missing_env_var(self, mock_config_manager):
        """Returns (False, error) for missing environment variable."""
        from spec.utils.env_utils import EnvVarExpansionError

        mock_config_manager.get_fallback_credentials.side_effect = EnvVarExpansionError(
            "LINEAR_API_KEY", "Not set"
        )
        auth_manager = AuthenticationManager(mock_config_manager)

        success, message = auth_manager.validate_credentials(Platform.LINEAR)

        assert success is False
        assert message is not None

    def test_validate_credentials_all_platforms(self, mock_config_manager):
        """Can validate all supported platforms."""
        auth_manager = AuthenticationManager(mock_config_manager)

        for platform in Platform:
            success, message = auth_manager.validate_credentials(platform)
            assert isinstance(success, bool)
            assert isinstance(message, str)


# =============================================================================
# PlatformCredentials Dataclass Tests
# =============================================================================


class TestPlatformCredentials:
    """Tests for PlatformCredentials dataclass."""

    def test_platform_credentials_creation(self):
        """Can create PlatformCredentials with all fields."""
        from types import MappingProxyType

        creds = PlatformCredentials(
            platform=Platform.JIRA,
            is_configured=True,
            credentials=MappingProxyType({"url": "https://example.com", "token": "abc"}),
            error_message=None,
        )

        assert creds.platform == Platform.JIRA
        assert creds.is_configured is True
        assert creds.credentials == {"url": "https://example.com", "token": "abc"}
        assert creds.error_message is None

    def test_platform_credentials_with_error(self):
        """Can create PlatformCredentials with error message."""
        creds = PlatformCredentials(
            platform=Platform.GITHUB,
            is_configured=False,
            error_message="Token not configured",
        )

        assert creds.platform == Platform.GITHUB
        assert creds.is_configured is False
        assert creds.credentials == {}
        assert creds.error_message == "Token not configured"

    def test_platform_credentials_default_error_message(self):
        """error_message defaults to None."""
        from types import MappingProxyType

        creds = PlatformCredentials(
            platform=Platform.LINEAR,
            is_configured=True,
            credentials=MappingProxyType({"api_key": "key123"}),
        )

        assert creds.error_message is None

    def test_platform_credentials_is_frozen(self):
        """PlatformCredentials is immutable (frozen)."""
        from types import MappingProxyType

        creds = PlatformCredentials(
            platform=Platform.JIRA,
            is_configured=True,
            credentials=MappingProxyType({"token": "abc"}),
        )

        with pytest.raises(AttributeError):
            creds.is_configured = False  # type: ignore

        with pytest.raises(AttributeError):
            creds.platform = Platform.GITHUB  # type: ignore

    def test_platform_credentials_dict_is_immutable(self, config_with_jira_creds):
        """Credentials mapping is truly read-only (MappingProxyType)."""
        from types import MappingProxyType

        auth_manager = AuthenticationManager(config_with_jira_creds)
        creds = auth_manager.get_credentials(Platform.JIRA)

        # Verify it's a MappingProxyType
        assert isinstance(creds.credentials, MappingProxyType)

        # Attempting to modify should raise TypeError
        with pytest.raises(TypeError):
            creds.credentials["new_key"] = "value"  # type: ignore
