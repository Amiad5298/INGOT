"""Configuration manager for INGOT.

This module provides the ConfigManager class for loading, saving, and
managing configuration values with a cascading hierarchy:

    1. Environment Variables (highest priority)
    2. Local Config (.ingot in project/parent directories)
    3. Global Config (~/.ingot-config)
    4. Built-in Defaults (lowest priority)

This enables developers working on multiple projects with different
trackers to have project-specific settings while maintaining global defaults.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from ingot.config.fetch_config import (
    AgentConfig,
    AgentPlatform,
    FetchPerformanceConfig,
    FetchStrategy,
    FetchStrategyConfig,
    canonicalize_credentials,
    parse_ai_backend,
    parse_fetch_strategy,
    validate_credentials,
)
from ingot.config.settings import CONFIG_FILE, Settings
from ingot.integrations.git import find_repo_root
from ingot.utils.env_utils import (
    SENSITIVE_KEY_PATTERNS,
    EnvVarExpansionError,
    expand_env_vars,
    is_sensitive_key,
)
from ingot.utils.logging import log_message

# Module-level logger
logger = logging.getLogger(__name__)

# Platform display names - maps internal names to user-friendly display names
PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    "jira": "Jira",
    "linear": "Linear",
    "github": "GitHub",
    "azure_devops": "Azure DevOps",
    "monday": "Monday",
    "trello": "Trello",
}


@functools.lru_cache(maxsize=1)
def _get_known_platforms() -> frozenset[str]:
    """Get KNOWN_PLATFORMS with lazy import to avoid circular dependencies.

    Uses lru_cache instead of a global mutable variable for thread-safety
    and simpler code.
    """
    from ingot.config.fetch_config import KNOWN_PLATFORMS

    # Return a frozenset to ensure immutability matches the type hint
    return frozenset(KNOWN_PLATFORMS)


class ConfigManager:
    """Manages configuration loading and saving with cascading hierarchy.

    Configuration Precedence (highest to lowest):
    1. Environment Variables - CI/CD, temporary overrides
    2. Local Config (.ingot) - Project-specific settings
    3. Global Config (~/.ingot-config) - User defaults
    4. Built-in Defaults - Fallback values

    Security features:
    - Safe line-by-line parsing (no eval/exec)
    - Key name validation
    - Atomic file writes
    - Secure file permissions (600)

    """

    LOCAL_CONFIG_NAME = ".ingot"
    GLOBAL_CONFIG_NAME = ".ingot-config"

    def __init__(self, global_config_path: Path | None = None) -> None:
        """Initialize the configuration manager."""
        self.global_config_path = global_config_path or CONFIG_FILE
        self.local_config_path: Path | None = None
        self.settings = Settings()
        self._raw_values: dict[str, str] = {}
        self._config_sources: dict[str, str] = {}

    def load(self) -> Settings:
        """Load configuration from all sources with cascading precedence.

        Loading order (later sources override earlier ones):
        1. Built-in defaults (from Settings dataclass)
        2. Global config (~/.ingot-config)
        3. Local config (.spec in project/parent directories)
        4. Environment variables (highest priority)

        Security: Uses safe line-by-line parsing instead of eval/exec.
        Only reads KEY=VALUE or KEY="VALUE" pairs.

        Note: This method is idempotent - each call starts from clean defaults
        to prevent stale values from persisting across multiple loads.
        """
        # Reset to clean state for idempotency
        self.settings = Settings()
        self.local_config_path = None
        self._raw_values = {}
        self._config_sources = {}

        # Step 1: Start with built-in defaults (from Settings dataclass)
        # The Settings dataclass already has defaults, nothing to do here

        # Step 2: Load global config (~/.ingot-config) - lowest file-based priority
        if self.global_config_path.exists():
            log_message(f"Loading global configuration from {self.global_config_path}")
            self._load_file(self.global_config_path, source="global")

        # Step 3: Load local config (.ingot) - higher priority
        local_path = self._find_local_config()
        if local_path:
            self.local_config_path = local_path
            log_message(f"Loading local configuration from {local_path}")
            self._load_file(local_path, source=f"local ({local_path})")

        # Step 4: Environment variables override everything
        self._load_environment()

        # Apply all values to settings
        for key, value in self._raw_values.items():
            self._apply_value_to_settings(key, value)

        log_message(f"Configuration loaded successfully ({len(self._raw_values)} keys)")
        return self.settings

    def _find_local_config(self) -> Path | None:
        """Find local .ingot config by traversing up from CWD.

        Starts from current working directory and traverses parent
        directories until a .ingot file is found, a .git directory is
        found (repository root), or the filesystem root is reached.
        """
        current = Path.cwd()
        while True:
            config_path = current / self.LOCAL_CONFIG_NAME
            if config_path.exists() and config_path.is_file():
                return config_path

            # Stop at repository root
            if (current / ".git").exists():
                break

            parent = current.parent
            if parent == current:  # Reached filesystem root
                break
            current = parent

        return None

    def _load_file(self, path: Path, source: str = "file") -> None:
        """Load key=value pairs from a config file."""
        pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$")

        with path.open() as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                match = pattern.match(line)
                if match:
                    key, value = match.groups()

                    # Remove surrounding quotes
                    # Only unescape for double-quoted values (single quotes are literal)
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                        # Unescape escaped characters for double-quoted strings
                        value = self._unescape_value(value)
                    elif value.startswith("'") and value.endswith("'"):
                        # Single quotes: no escaping, just remove quotes
                        value = value[1:-1]

                    self._raw_values[key] = value
                    self._config_sources[key] = source

    def _load_environment(self) -> None:
        """Override config with environment variables.

        Only loads environment variables for known config keys
        to avoid polluting the configuration with unrelated env vars.
        """
        known_keys = Settings.get_config_keys()
        for key in known_keys:
            env_value = os.environ.get(key)
            if env_value is not None:
                self._raw_values[key] = env_value
                self._config_sources[key] = "environment"

    def _apply_value_to_settings(self, key: str, value: str) -> None:
        """Apply a raw config value to the settings object."""
        attr = self.settings.get_attribute_for_key(key)
        if attr is None:
            return  # Unknown key, ignore

        # Get the expected type from the settings dataclass
        current_value = getattr(self.settings, attr)

        if isinstance(current_value, bool):
            # Parse boolean values
            setattr(self.settings, attr, value.lower() in ("true", "1", "yes"))
        elif isinstance(current_value, int):
            # Parse integer values
            try:
                setattr(self.settings, attr, int(value))
            except ValueError:
                logger.warning(
                    "Cannot parse %r as int for config key %r, keeping default", value, key
                )
        elif isinstance(current_value, float):
            # Parse float values
            try:
                setattr(self.settings, attr, float(value))
            except ValueError:
                logger.warning(
                    "Cannot parse %r as float for config key %r, keeping default", value, key
                )
        else:
            # String values - extract model ID for model-related keys
            if key in ("DEFAULT_MODEL", "PLANNING_MODEL", "IMPLEMENTATION_MODEL"):
                from ingot.integrations.auggie import extract_model_id

                value = extract_model_id(value)
            setattr(self.settings, attr, value)

    def save(
        self,
        key: str,
        value: str,
        scope: Literal["global", "local"] = "global",
        warn_on_override: bool = True,
    ) -> str | None:
        """Save a configuration value to a config file.

        Writes the value to the specified config file (global or local) and then
        reloads all configuration to maintain correct precedence. The in-memory
        state always reflects the *effective* value after applying the full
        precedence hierarchy (env > local > global > defaults).

        Security: Validates key name, uses atomic file replacement, masks
        sensitive values in logs.

        Behavior notes:
            - If scope="local" and no local config exists, creates a .ingot
              file at the repository root (detected via .git directory).
              Falls back to the current working directory if no .git is found.
            - After saving, load() is called internally to recompute effective
              values, ensuring manager.settings reflects correct precedence.
            - The value written to the file may not be the effective value if
              a higher-priority source overrides it (env var or local config).
            - Values containing special characters (quotes, backslashes) are
              properly escaped for safe round-trip through save/load.

        Raises:
            ValueError: If key name is invalid or scope is not "global"/"local".
        """
        # Validate key name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            raise ValueError(f"Invalid config key: {key}")

        if not re.match(r"^[A-Z][A-Z0-9_]*$", key):
            logger.warning("Config key %r is not in UPPER_SNAKE_CASE format", key)

        if scope not in ("global", "local"):
            raise ValueError(f"Invalid scope: {scope}. Must be 'global' or 'local'")

        # Determine target file
        if scope == "local":
            if self.local_config_path is None:
                # Try to find repo root first, fall back to cwd
                repo_root = find_repo_root()
                if repo_root:
                    self.local_config_path = repo_root / self.LOCAL_CONFIG_NAME
                else:
                    self.local_config_path = Path.cwd() / self.LOCAL_CONFIG_NAME
            target_path = self.local_config_path
        else:
            target_path = self.global_config_path

        # Read existing file content
        existing_lines: list[str] = []
        if target_path.exists():
            existing_lines = target_path.read_text().splitlines()

        # Build new file content
        new_lines: list[str] = []
        written_keys: set[str] = set()
        key_pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)=")

        # Escape value for safe storage (handle quotes and backslashes)
        escaped_value = self._escape_value_for_storage(value)

        for line in existing_lines:
            # Preserve comments and empty lines
            if not line.strip() or line.strip().startswith("#"):
                new_lines.append(line)
                continue

            match = key_pattern.match(line)
            if match:
                existing_key = match.group(1)
                if existing_key == key:
                    # Write updated value for the key we're saving
                    new_lines.append(f'{key}="{escaped_value}"')
                    written_keys.add(key)
                else:
                    # Preserve other keys
                    new_lines.append(line)
            else:
                # Preserve malformed lines
                new_lines.append(line)

        # Add new key if not already in file
        if key not in written_keys:
            new_lines.append(f'{key}="{escaped_value}"')

        # Atomic write using temp file
        self._atomic_write_to_path(new_lines, target_path)

        # Log without exposing sensitive values
        self._log_config_save(key, scope)

        # Build override warning BEFORE reload (need to check current state)
        warning = self._check_override_warning(key, value, scope, warn_on_override)

        # Reload configuration to maintain correct precedence
        # This ensures in-memory state reflects effective values after save
        self.load()

        return warning

    def _check_override_warning(
        self,
        key: str,
        saved_value: str,
        scope: Literal["global", "local"],
        warn_on_override: bool,
    ) -> str | None:
        """Check if saved value will be overridden by higher-priority source."""
        if not warn_on_override:
            return None

        warning = None

        # Environment variables always override both global and local
        if os.environ.get(key) is not None:
            warning = (
                f"Warning: '{key}' saved to {scope} config but is overridden "
                f"by environment variable (effective value: '{os.environ.get(key)}')"
            )
            return warning  # Env is highest priority, no need to check local

        # For global scope, check if local config overrides
        if scope == "global":
            if self.local_config_path and self.local_config_path.exists():
                local_values = self._read_file_values(self.local_config_path)
                if key in local_values:
                    warning = (
                        f"Warning: '{key}' saved to global config but is overridden "
                        f"by local config at {self.local_config_path} "
                        f"(effective value: '{local_values[key]}')"
                    )

        return warning

    def _read_file_values(self, path: Path) -> dict[str, str]:
        """Read key=value pairs from a config file without modifying state."""
        values: dict[str, str] = {}
        pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$")

        if not path.exists():
            return values

        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = pattern.match(line)
                if match:
                    key, value = match.groups()
                    # Only unescape for double-quoted values (single quotes are literal)
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                        # Unescape escaped characters for double-quoted strings
                        value = self._unescape_value(value)
                    elif value.startswith("'") and value.endswith("'"):
                        # Single quotes: no escaping, just remove quotes
                        value = value[1:-1]
                    values[key] = value
        return values

    def _atomic_write_to_path(self, lines: list[str], target_path: Path) -> None:
        """Atomically write lines to a specific config file."""
        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory for atomic move
        fd, temp_path = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=".ingot-config-",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(lines))
                if lines:
                    f.write("\n")

            # Set secure permissions before moving
            os.chmod(temp_path, 0o600)

            # Atomic replace
            Path(temp_path).replace(target_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _escape_value_for_storage(value: str) -> str:
        """Escape a value for safe storage in config file.

        Handles backslashes (escape with another backslash) and
        double quotes (escape with backslash).
        """
        # Escape backslashes first, then quotes
        result = value.replace("\\", "\\\\")
        result = result.replace('"', '\\"')
        return result

    @staticmethod
    def _unescape_value(value: str) -> str:
        """Unescape a value read from config file.

        Reverses the escaping done by _escape_value_for_storage.
        """
        # Unescape backslashes first, then quotes
        # (reverse order of escaping to handle \\\" correctly)
        result = value.replace("\\\\", "\\")
        result = result.replace('\\"', '"')
        return result

    def _log_config_save(self, key: str, scope: str) -> None:
        """Log a configuration save without exposing sensitive values.

        For sensitive keys (containing TOKEN, KEY, SECRET, PASSWORD, PAT),
        the value is not logged.
        """
        if is_sensitive_key(key):
            log_message(f"Configuration saved to {scope}: {key}=<REDACTED>")
        else:
            log_message(f"Configuration saved to {scope}: {key}")

    def get(self, key: str, default: str = "") -> str:
        """Get a configuration value."""
        return self._raw_values.get(key, default)

    def get_agent_config(self) -> AgentConfig:
        """Get AI agent configuration.

        Parses AI_BACKEND and AGENT_INTEGRATION_* keys from config.

        Raises:
            ConfigValidationError: If AI_BACKEND has an invalid value.
        """
        platform_str = self._raw_values.get("AI_BACKEND")
        integrations: dict[str, bool] | None = None

        # Parse AGENT_INTEGRATION_* keys
        # Only create dict if at least one key is found
        for key, value in self._raw_values.items():
            if key.startswith("AGENT_INTEGRATION_"):
                if integrations is None:
                    integrations = {}
                platform_name = key.replace("AGENT_INTEGRATION_", "").lower()
                integrations[platform_name] = value.lower() in ("true", "1", "yes")

        # Use safe parser - raises ConfigValidationError for invalid values
        platform = parse_ai_backend(
            platform_str,
            default=AgentPlatform.AUGGIE,
            context="AI_BACKEND",
        )

        return AgentConfig(
            platform=platform,
            integrations=integrations,
        )

    def get_fetch_strategy_config(self) -> FetchStrategyConfig:
        """Get fetch strategy configuration.

        Parses FETCH_STRATEGY_DEFAULT and FETCH_STRATEGY_* keys from config.

        Raises:
            ConfigValidationError: If any strategy value is invalid.
        """
        default_str = self._raw_values.get("FETCH_STRATEGY_DEFAULT")
        per_platform: dict[str, FetchStrategy] = {}

        # Parse FETCH_STRATEGY_* keys (excluding DEFAULT)
        # Use safe parser - raises ConfigValidationError for invalid values
        for key, value in self._raw_values.items():
            if key.startswith("FETCH_STRATEGY_") and key != "FETCH_STRATEGY_DEFAULT":
                platform_name = key.replace("FETCH_STRATEGY_", "").lower()
                per_platform[platform_name] = parse_fetch_strategy(
                    value,
                    default=FetchStrategy.AUTO,
                    context=key,
                )

        # Use safe parser - raises ConfigValidationError for invalid values
        default = parse_fetch_strategy(
            default_str,
            default=FetchStrategy.AUTO,
            context="FETCH_STRATEGY_DEFAULT",
        )

        return FetchStrategyConfig(
            default=default,
            per_platform=per_platform,
        )

    def get_fetch_performance_config(self) -> FetchPerformanceConfig:
        """Get fetch performance configuration.

        Parses FETCH_CACHE_DURATION_HOURS, FETCH_TIMEOUT_SECONDS,
        FETCH_MAX_RETRIES, and FETCH_RETRY_DELAY_SECONDS from config.

        Values are validated to ensure they are within reasonable bounds:
        - cache_duration_hours: >= 0
        - timeout_seconds: > 0
        - max_retries: >= 0
        - retry_delay_seconds: >= 0
        """
        # Default values
        cache_duration_hours = 24
        timeout_seconds = 30
        max_retries = 3
        retry_delay_seconds = 1.0

        # Parse each performance setting with type conversion and validation
        if "FETCH_CACHE_DURATION_HOURS" in self._raw_values:
            try:
                cache_value = int(self._raw_values["FETCH_CACHE_DURATION_HOURS"])
                if cache_value >= 0:
                    cache_duration_hours = cache_value
                else:
                    logger.warning(
                        f"FETCH_CACHE_DURATION_HOURS must be >= 0, got {cache_value}, "
                        f"using default {cache_duration_hours}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid FETCH_CACHE_DURATION_HOURS value "
                    f"'{self._raw_values['FETCH_CACHE_DURATION_HOURS']}', "
                    f"using default {cache_duration_hours}"
                )

        if "FETCH_TIMEOUT_SECONDS" in self._raw_values:
            try:
                timeout_value = int(self._raw_values["FETCH_TIMEOUT_SECONDS"])
                if timeout_value > 0:
                    timeout_seconds = timeout_value
                else:
                    logger.warning(
                        f"FETCH_TIMEOUT_SECONDS must be > 0, got {timeout_value}, "
                        f"using default {timeout_seconds}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid FETCH_TIMEOUT_SECONDS value "
                    f"'{self._raw_values['FETCH_TIMEOUT_SECONDS']}', "
                    f"using default {timeout_seconds}"
                )

        if "FETCH_MAX_RETRIES" in self._raw_values:
            try:
                retries_value = int(self._raw_values["FETCH_MAX_RETRIES"])
                if retries_value >= 0:
                    max_retries = retries_value
                else:
                    logger.warning(
                        f"FETCH_MAX_RETRIES must be >= 0, got {retries_value}, "
                        f"using default {max_retries}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid FETCH_MAX_RETRIES value "
                    f"'{self._raw_values['FETCH_MAX_RETRIES']}', "
                    f"using default {max_retries}"
                )

        if "FETCH_RETRY_DELAY_SECONDS" in self._raw_values:
            try:
                delay_value = float(self._raw_values["FETCH_RETRY_DELAY_SECONDS"])
                if delay_value >= 0:
                    retry_delay_seconds = delay_value
                else:
                    logger.warning(
                        f"FETCH_RETRY_DELAY_SECONDS must be >= 0, got {delay_value}, "
                        f"using default {retry_delay_seconds}"
                    )
            except ValueError:
                logger.warning(
                    f"Invalid FETCH_RETRY_DELAY_SECONDS value "
                    f"'{self._raw_values['FETCH_RETRY_DELAY_SECONDS']}', "
                    f"using default {retry_delay_seconds}"
                )

        return FetchPerformanceConfig(
            cache_duration_hours=cache_duration_hours,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )

    def get_fallback_credentials(
        self,
        platform: str,
        strict: bool = False,
        validate: bool = False,
    ) -> dict[str, str] | None:
        """Get fallback credentials for a platform.

        Parses FALLBACK_{PLATFORM}_* keys and expands environment variables.
        Applies credential key aliasing for backward compatibility (e.g., 'org'
        is treated as 'organization' for Azure DevOps, 'base_url' as 'url' for
        Jira, 'api_token' as 'token' for Trello).

        Canonicalization is applied before validation, ensuring required fields
        are checked against canonical keys defined in PLATFORM_REQUIRED_CREDENTIALS.

        Raises:
            EnvVarExpansionError: If strict=True and env var expansion fails.
            ConfigValidationError: If validate=True and required fields missing.
        """
        prefix = f"FALLBACK_{platform.upper()}_"
        raw_credentials: dict[str, str] = {}

        for key, value in self._raw_values.items():
            if key.startswith(prefix):
                cred_name = key.replace(prefix, "").lower()
                context = f"credential {key}"
                raw_credentials[cred_name] = expand_env_vars(value, strict=strict, context=context)

        if not raw_credentials:
            return None

        # Canonicalize credential keys using platform-specific aliases
        credentials = canonicalize_credentials(platform, raw_credentials)

        if validate:
            validate_credentials(platform, credentials, strict=True)

        return credentials

    def _get_active_platforms(self) -> set[str]:
        """Get the set of 'active' platforms that need validation."""
        from ingot.config.validation import get_active_platforms_from_config

        return get_active_platforms_from_config(self)

    def validate_fetch_config(self, strict: bool = True) -> list[str]:
        """Validate the complete fetch configuration.

        Raises:
            ConfigValidationError: If strict=True and validation fails.
        """
        from ingot.config.validation import validate_fetch_config as _validate_fetch_config

        return _validate_fetch_config(self, strict=strict)

    def _get_agent_integrations(self) -> dict[str, bool]:
        """Get agent integration status for all platforms."""
        from ingot.config.display import get_agent_integrations

        return get_agent_integrations(self)

    def _get_fallback_status(self) -> dict[str, bool]:
        """Get fallback credential status for all platforms."""
        from ingot.config.display import get_fallback_status

        return get_fallback_status(self)

    def _get_platform_ready_status(
        self,
        agent_integrations: dict[str, bool],
        fallback_status: dict[str, bool],
    ) -> dict[str, bool]:
        """Determine if each platform is ready to use."""
        from ingot.config.display import get_platform_ready_status

        return get_platform_ready_status(agent_integrations, fallback_status)

    def _show_platform_status(self) -> None:
        """Display platform configuration status as a Rich table."""
        from ingot.config.display import show_platform_status

        show_platform_status(self)

    def _show_platform_status_plain_text(
        self,
        agent_integrations: dict[str, bool],
        fallback_status: dict[str, bool],
        ready_status: dict[str, bool],
    ) -> None:
        """Display platform status as plain text (fallback when Rich fails)."""
        from ingot.config.display import show_platform_status_plain_text

        show_platform_status_plain_text(agent_integrations, fallback_status, ready_status)

    def show(self) -> None:
        """Display current configuration using Rich formatting."""
        from ingot.config.display import show_config

        show_config(self)


__all__ = [
    "ConfigManager",
    "EnvVarExpansionError",
    "SENSITIVE_KEY_PATTERNS",
]
