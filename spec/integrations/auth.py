"""Authentication management for fallback credentials.

This module provides AuthenticationManager for managing fallback credentials
used by DirectAPIFetcher when agent-mediated fetching is unavailable.

IMPORTANT: This is for FALLBACK credentials only. Primary authentication
is handled by the connected AI agent's MCP integrations.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.config.manager import ConfigManager

from spec.config import ConfigValidationError
from spec.config.fetch_config import PLATFORM_REQUIRED_CREDENTIALS
from spec.integrations.providers.base import Platform
from spec.utils.env_utils import EnvVarExpansionError

logger = logging.getLogger(__name__)


def _freeze_credentials(creds: dict[str, str]) -> Mapping[str, str]:
    """Convert a mutable dict to an immutable MappingProxyType.

    Creates a shallow copy of the dictionary before freezing to prevent
    aliasing issues where modifications to the original dict would affect
    the frozen view.
    """
    return MappingProxyType(dict(creds))


@dataclass(frozen=True)
class PlatformCredentials:
    """Credentials for a specific platform.

    Attributes:
        platform: The platform these credentials are for
        is_configured: Whether valid credentials are available
        credentials: Read-only mapping of credential key-value pairs (empty if not configured)
        error_message: Description of why credentials are unavailable (if not configured)
    """

    platform: Platform
    is_configured: bool
    credentials: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    error_message: str | None = None


class AuthenticationManager:
    """Manage fallback credentials for direct API access.

    Primary auth is handled by the connected AI agent's MCP integrations.
    This class provides credentials only when DirectAPIFetcher is used
    as a fallback for platforms not supported by the agent.

    Credential Key Transformation:
        Config file keys (e.g., FALLBACK_JIRA_URL) are automatically
        transformed to canonical keys (e.g., 'url') by ConfigManager.

        Common aliases are also resolved:
        - 'org' → 'organization' (Azure DevOps)
        - 'base_url' → 'url' (Jira)
        - 'api_token' → 'token' (Trello)

        See CREDENTIAL_ALIASES in spec/config/fetch_config.py for full mapping.

    Canonical Keys Returned per Platform:
        - Jira: url, email, token
        - GitHub: token
        - Linear: api_key
        - Azure DevOps: organization, pat
        - Monday: api_key
        - Trello: api_key, token

    Attributes:
        _config: ConfigManager instance for loading credentials
    """

    # Set of platforms that support fallback credentials.
    # Platform name is derived from enum name (e.g., Platform.AZURE_DEVOPS -> "azure_devops")
    SUPPORTED_FALLBACK_PLATFORMS: frozenset[Platform] = frozenset(
        {
            Platform.JIRA,
            Platform.GITHUB,
            Platform.LINEAR,
            Platform.AZURE_DEVOPS,
            Platform.MONDAY,
            Platform.TRELLO,
        }
    )

    def __init__(self, config: ConfigManager) -> None:
        """Initialize with ConfigManager.

        Args:
            config: ConfigManager instance (should have load() called)
        """
        self._config = config

    @staticmethod
    def _get_platform_name(platform: Platform) -> str:
        """Derive the lowercase platform name from the Platform enum.

        Args:
            platform: Platform enum value

        Returns:
            Lowercase platform name (e.g., "azure_devops" for Platform.AZURE_DEVOPS)
        """
        return platform.name.lower()

    def get_credentials(self, platform: Platform) -> PlatformCredentials:
        """Get fallback credentials for direct API access.

        Retrieves and validates credentials for the specified platform
        from the configuration hierarchy.

        Args:
            platform: Platform enum value to get credentials for

        Returns:
            PlatformCredentials with credentials if available, or error_message if not
        """
        if platform not in self.SUPPORTED_FALLBACK_PLATFORMS:
            return PlatformCredentials(
                platform=platform,
                is_configured=False,
                error_message=f"Platform {platform.name} does not support fallback credentials",
            )

        platform_name = self._get_platform_name(platform)

        try:
            credentials = self._config.get_fallback_credentials(
                platform_name,
                strict=True,  # Fail on missing env vars
                validate=True,  # Validate required fields
            )
        except (EnvVarExpansionError, ConfigValidationError) as e:
            # Known safe exceptions - their messages are designed for user display
            logger.debug(
                "Failed to get credentials for %s: %s",
                platform_name,
                type(e).__name__,
            )
            return PlatformCredentials(
                platform=platform,
                is_configured=False,
                error_message=str(e),
            )
        except Exception as e:
            # SECURITY: Unknown exceptions may contain secrets in their message
            # (e.g., "Invalid token 'sk-123...'"). Return generic message to avoid leaks.
            logger.debug(
                "Failed to get credentials for %s: %s",
                platform_name,
                type(e).__name__,
            )
            return PlatformCredentials(
                platform=platform,
                is_configured=False,
                error_message=f"Failed to load credentials for {platform_name}",
            )

        if credentials is None:
            return PlatformCredentials(
                platform=platform,
                is_configured=False,
                error_message=f"No fallback credentials configured for {platform_name}",
            )

        return PlatformCredentials(
            platform=platform,
            is_configured=True,
            credentials=_freeze_credentials(credentials),
            error_message=None,
        )

    def has_fallback_configured(self, platform: Platform) -> bool:
        """Quick check if fallback credentials exist for a platform.

        This performs a lightweight check that verifies at least one REQUIRED
        credential key exists in the configuration, without strict validation
        (e.g., env var expansion). For full validation, use get_credentials() instead.

        Args:
            platform: Platform to check

        Returns:
            True if at least one required credential key exists for the platform
            (may still fail full validation due to missing env vars or empty values)
        """
        if platform not in self.SUPPORTED_FALLBACK_PLATFORMS:
            return False

        platform_name = self._get_platform_name(platform)

        try:
            # Use non-strict mode for quick check (no env var expansion)
            credentials = self._config.get_fallback_credentials(
                platform_name,
                strict=False,  # Don't fail on unexpanded env vars
                validate=False,  # Don't validate required fields
            )
            if credentials is None or len(credentials) == 0:
                return False

            # Verify at least one REQUIRED key exists to avoid false positives
            # from typos or irrelevant keys (e.g., FALLBACK_JIRA_TOKE vs FALLBACK_JIRA_TOKEN)
            required_keys = PLATFORM_REQUIRED_CREDENTIALS.get(platform_name, frozenset())
            if not required_keys:
                # Unknown platform - fall back to basic check
                return True

            credential_keys = set(credentials.keys())
            return bool(credential_keys & required_keys)
        except Exception:
            return False

    def list_fallback_platforms(self) -> list[Platform]:
        """List platforms with fallback credentials configured.

        Returns:
            List of Platform enum values that have valid fallback credentials
        """
        return [
            platform
            for platform in self.SUPPORTED_FALLBACK_PLATFORMS
            if self.has_fallback_configured(platform)
        ]

    def validate_credentials(self, platform: Platform) -> tuple[bool, str]:
        """Validate that required credential fields are present and non-empty.

        NOTE: This performs FORMAT validation only. It checks that:
        - All required fields for the platform are present
        - No required fields are empty strings

        Validation is delegated to ConfigManager.get_fallback_credentials()
        with strict=True and validate=True. The ConfigManager is responsible
        for checking that all required fields are present and non-empty.

        This method does NOT:
        - Make API calls to verify credentials are valid
        - Test network connectivity to the platform
        - Validate token expiration or permissions

        For API connectivity testing, use DirectAPIFetcher which makes
        actual API calls and will surface authentication errors.

        Args:
            platform: Platform to validate credentials for

        Returns:
            Tuple of (success: bool, message: str)
            - (True, "Credentials configured for {platform}") if valid
            - (False, error_message) if validation fails
        """
        creds = self.get_credentials(platform)

        if not creds.is_configured:
            return False, creds.error_message or "Credentials not configured"

        # Additional explicit check for empty string values
        empty_fields = [key for key, value in creds.credentials.items() if value == ""]
        if empty_fields:
            return False, f"Empty credential values for: {', '.join(empty_fields)}"

        return True, f"Credentials configured for {platform.name}"
