"""Configuration manager for SPEC.

This module provides the ConfigManager class for loading, saving, and
managing configuration values with a cascading hierarchy:

    1. Environment Variables (highest priority)
    2. Local Config (.spec in project/parent directories)
    3. Global Config (~/.spec-config)
    4. Built-in Defaults (lowest priority)

This enables developers working on multiple projects with different
trackers to have project-specific settings while maintaining global defaults.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from spec.config.fetch_config import (
    AgentConfig,
    AgentPlatform,
    ConfigValidationError,
    FetchPerformanceConfig,
    FetchStrategy,
    FetchStrategyConfig,
    canonicalize_credentials,
    get_active_platforms,
    parse_agent_platform,
    parse_fetch_strategy,
    validate_credentials,
    validate_strategy_for_platform,
)
from spec.config.settings import CONFIG_FILE, Settings
from spec.integrations.git import find_repo_root
from spec.utils.console import console, print_header, print_info
from spec.utils.env_utils import (
    SENSITIVE_KEY_PATTERNS,
    EnvVarExpansionError,
    expand_env_vars,
    is_sensitive_key,
)
from spec.utils.logging import log_message

# Module-level logger
logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration loading and saving with cascading hierarchy.

    Configuration Precedence (highest to lowest):
    1. Environment Variables - CI/CD, temporary overrides
    2. Local Config (.spec) - Project-specific settings
    3. Global Config (~/.spec-config) - User defaults
    4. Built-in Defaults - Fallback values

    Security features:
    - Safe line-by-line parsing (no eval/exec)
    - Key name validation
    - Atomic file writes
    - Secure file permissions (600)

    Attributes:
        settings: Current settings instance
        global_config_path: Path to global ~/.spec-config file
        local_config_path: Path to discovered local .spec file (after load)
    """

    LOCAL_CONFIG_NAME = ".spec"
    GLOBAL_CONFIG_NAME = ".spec-config"

    def __init__(self, global_config_path: Path | None = None) -> None:
        """Initialize the configuration manager.

        Args:
            global_config_path: Optional custom path to global config file.
                                Defaults to ~/.spec-config.
        """
        self.global_config_path = global_config_path or CONFIG_FILE
        self.local_config_path: Path | None = None
        self.settings = Settings()
        self._raw_values: dict[str, str] = {}
        self._config_sources: dict[str, str] = {}

    def load(self) -> Settings:
        """Load configuration from all sources with cascading precedence.

        Loading order (later sources override earlier ones):
        1. Built-in defaults (from Settings dataclass)
        2. Global config (~/.spec-config)
        3. Local config (.spec in project/parent directories)
        4. Environment variables (highest priority)

        Security: Uses safe line-by-line parsing instead of eval/exec.
        Only reads KEY=VALUE or KEY="VALUE" pairs.

        Note: This method is idempotent - each call starts from clean defaults
        to prevent stale values from persisting across multiple loads.

        Returns:
            Settings instance with loaded values
        """
        # Reset to clean state for idempotency
        self.settings = Settings()
        self.local_config_path = None
        self._raw_values = {}
        self._config_sources = {}

        # Step 1: Start with built-in defaults (from Settings dataclass)
        # The Settings dataclass already has defaults, nothing to do here

        # Step 2: Load global config (~/.spec-config) - lowest file-based priority
        if self.global_config_path.exists():
            log_message(f"Loading global configuration from {self.global_config_path}")
            self._load_file(self.global_config_path, source="global")

        # Step 3: Load local config (.spec) - higher priority
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
        """Find local .spec config by traversing up from CWD.

        Starts from current working directory and traverses parent
        directories until:
        - A .spec file is found
        - A .git directory is found (repository root)
        - The filesystem root is reached

        Returns:
            Path to local config file, or None if not found
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
        """Load key=value pairs from a config file.

        Args:
            path: Path to the config file
            source: Source identifier for debugging
        """
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
        """Apply a raw config value to the settings object.

        Args:
            key: Configuration key
            value: Raw string value from file
        """
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
                pass  # Keep default on parse error
        else:
            # String values - extract model ID for model-related keys
            if key in ("DEFAULT_MODEL", "PLANNING_MODEL", "IMPLEMENTATION_MODEL"):
                from spec.integrations.auggie import extract_model_id

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
            - If scope="local" and no local config exists, creates a .spec
              file at the repository root (detected via .git directory).
              Falls back to the current working directory if no .git is found.
            - After saving, load() is called internally to recompute effective
              values, ensuring manager.settings reflects correct precedence.
            - The value written to the file may not be the effective value if
              a higher-priority source overrides it (env var or local config).
            - Values containing special characters (quotes, backslashes) are
              properly escaped for safe round-trip through save/load.

        Args:
            key: Configuration key (must match pattern: [a-zA-Z_][a-zA-Z0-9_]*)
            value: Configuration value to save
            scope: Target config file - "global" (~/.spec-config) or
                   "local" (.spec in project directory)
            warn_on_override: If True, returns warning message when the saved
                              value is overridden by a higher-priority source

        Returns:
            Warning message describing overrides (if any), None otherwise.
            For global scope: warns if local config or env var overrides.
            For local scope: warns if env var overrides.

        Raises:
            ValueError: If key name is invalid (doesn't match pattern) or
                        scope is not "global" or "local"
        """
        # Validate key name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            raise ValueError(f"Invalid config key: {key}")

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
        """Check if saved value will be overridden by higher-priority source.

        Args:
            key: Configuration key that was saved
            saved_value: Value that was written to file
            scope: Scope of the save operation
            warn_on_override: Whether to generate warnings

        Returns:
            Warning message if overridden, None otherwise
        """
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
        """Read key=value pairs from a config file without modifying state.

        Args:
            path: Path to the config file

        Returns:
            Dictionary of key-value pairs
        """
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
        """Atomically write lines to a specific config file.

        Args:
            lines: Lines to write
            target_path: Path to write to
        """
        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory for atomic move
        fd, temp_path = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=".spec-config-",
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

        Handles:
        - Backslashes (escape with another backslash)
        - Double quotes (escape with backslash)

        Args:
            value: The raw value to escape

        Returns:
            Escaped value safe for storage in double-quoted format
        """
        # Escape backslashes first, then quotes
        result = value.replace("\\", "\\\\")
        result = result.replace('"', '\\"')
        return result

    @staticmethod
    def _unescape_value(value: str) -> str:
        """Unescape a value read from config file.

        Reverses the escaping done by _escape_value_for_storage.

        Args:
            value: The escaped value from the config file

        Returns:
            Original unescaped value
        """
        # Unescape backslashes first, then quotes
        # (reverse order of escaping to handle \\\" correctly)
        result = value.replace("\\\\", "\\")
        result = result.replace('\\"', '"')
        return result

    def _log_config_save(self, key: str, scope: str) -> None:
        """Log a configuration save without exposing sensitive values.

        For sensitive keys (containing TOKEN, KEY, SECRET, PASSWORD, PAT),
        the value is not logged. For other keys, only the key and scope
        are logged.

        Args:
            key: The configuration key that was saved
            scope: The scope (global or local) where it was saved
        """
        if is_sensitive_key(key):
            log_message(f"Configuration saved to {scope}: {key}=<REDACTED>")
        else:
            log_message(f"Configuration saved to {scope}: {key}")

    def get(self, key: str, default: str = "") -> str:
        """Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self._raw_values.get(key, default)

    def get_agent_config(self) -> AgentConfig:
        """Get AI agent configuration.

        Parses AGENT_PLATFORM and AGENT_INTEGRATION_* keys from config.

        Returns:
            AgentConfig instance with platform and integrations

        Raises:
            ConfigValidationError: If AGENT_PLATFORM has an invalid value
        """
        platform_str = self._raw_values.get("AGENT_PLATFORM")
        integrations: dict[str, bool] = {}

        # Parse AGENT_INTEGRATION_* keys
        for key, value in self._raw_values.items():
            if key.startswith("AGENT_INTEGRATION_"):
                platform_name = key.replace("AGENT_INTEGRATION_", "").lower()
                integrations[platform_name] = value.lower() in ("true", "1", "yes")

        # Use safe parser - raises ConfigValidationError for invalid values
        platform = parse_agent_platform(
            platform_str,
            default=AgentPlatform.AUGGIE,
            context="AGENT_PLATFORM",
        )

        return AgentConfig(
            platform=platform,
            integrations=integrations,
        )

    def get_fetch_strategy_config(self) -> FetchStrategyConfig:
        """Get fetch strategy configuration.

        Parses FETCH_STRATEGY_DEFAULT and FETCH_STRATEGY_* keys from config.

        Returns:
            FetchStrategyConfig instance with default and per-platform strategies

        Raises:
            ConfigValidationError: If any strategy value is invalid
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

        Returns:
            FetchPerformanceConfig instance with performance settings
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

        Args:
            platform: Platform name (e.g., 'azure_devops', 'trello')
            strict: If True, raises EnvVarExpansionError for missing env vars
            validate: If True, validates credentials have required fields

        Returns:
            Dictionary of credential key-value pairs with canonical keys,
            or None if no credentials found

        Raises:
            EnvVarExpansionError: If strict=True and env var expansion fails
            ConfigValidationError: If validate=True and required fields missing
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
        """Get the set of 'active' platforms that need validation.

        Active platforms are those explicitly defined in:
        - per_platform strategy overrides
        - agent integrations
        - fallback_credentials

        Returns:
            Set of lowercase platform names that are actively configured
        """
        # Delegate to the extracted helper function
        return get_active_platforms(
            raw_config_keys=set(self._raw_values.keys()),
            strategy_config=self.get_fetch_strategy_config(),
            agent_config=self.get_agent_config(),
        )

    def validate_fetch_config(self, strict: bool = True) -> list[str]:
        """Validate the complete fetch configuration.

        Performs scoped validation only on 'active' platforms that are explicitly
        configured (defined in per_platform, integrations, or fallback_credentials).
        This reduces noise by not checking all KNOWN_PLATFORMS by default.

        Validation includes:
        - Strategy/platform compatibility
        - Credential availability and completeness
        - Per-platform override references
        - Enum parsing (agent platform, fetch strategies)

        Args:
            strict: If True, raises ConfigValidationError on first error.
                    If False, collects and returns all errors without raising.

        Returns:
            List of validation error messages

        Raises:
            ConfigValidationError: If strict=True and validation fails
        """
        errors: list[str] = []

        # Get agent config - may raise ConfigValidationError for invalid enum values
        try:
            agent_config = self.get_agent_config()
        except ConfigValidationError as e:
            if strict:
                raise
            errors.append(str(e))
            # Use default agent config to continue validation
            agent_config = AgentConfig(
                platform=AgentPlatform.AUGGIE,
                integrations={},
            )

        # Get strategy config - may raise ConfigValidationError for invalid enum values
        try:
            strategy_config = self.get_fetch_strategy_config()
        except ConfigValidationError as e:
            if strict:
                raise
            errors.append(str(e))
            # Use default strategy config to continue validation
            strategy_config = FetchStrategyConfig(
                default=FetchStrategy.AUTO,
                per_platform={},
            )

        # Validate per-platform overrides reference known platforms
        override_warnings = strategy_config.validate_platform_overrides(strict=False)
        errors.extend(override_warnings)

        # Get only the active platforms that need validation
        # Use the already-parsed configs to avoid re-calling getters (which could raise)
        active_platforms = get_active_platforms(
            raw_config_keys=set(self._raw_values.keys()),
            strategy_config=strategy_config,
            agent_config=agent_config,
        )

        # Validate only active platforms' strategies
        for platform in active_platforms:
            strategy = strategy_config.get_strategy(platform)
            has_agent_support = agent_config.supports_platform(platform)

            # Determine if credentials are required for this platform
            # - DIRECT strategy: always requires credentials
            # - AUTO strategy: requires credentials if no agent support (direct is only path)
            credentials_required = strategy == FetchStrategy.DIRECT or (
                strategy == FetchStrategy.AUTO and not has_agent_support
            )

            # Use strict mode for env var expansion when credentials are required
            # This fail-fast behavior prevents silent 401/403 errors at runtime
            credentials = None
            try:
                credentials = self.get_fallback_credentials(platform, strict=credentials_required)
            except EnvVarExpansionError as e:
                # Missing env vars in required credentials is a config error
                errors.append(
                    f"Platform '{platform}' requires credentials but has missing "
                    f"environment variable(s): {e}"
                )

            has_credentials = credentials is not None and len(credentials) > 0

            platform_errors = validate_strategy_for_platform(
                platform=platform,
                strategy=strategy,
                agent_config=agent_config,
                has_credentials=has_credentials,
                strict=False,
            )
            errors.extend(platform_errors)

            # If direct or auto strategy with credentials, validate credential fields
            if has_credentials and strategy.value in ("direct", "auto"):
                cred_errors = validate_credentials(platform, credentials, strict=False)
                errors.extend(cred_errors)

        if strict and errors:
            raise ConfigValidationError(
                "Fetch configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        return errors

    def show(self) -> None:
        """Display current configuration using Rich formatting."""
        print_header("Current Configuration")

        # Show config file locations
        print_info(f"Global config: {self.global_config_path}")
        if self.local_config_path:
            print_info(f"Local config:  {self.local_config_path}")
        else:
            print_info("Local config:  (not found)")
        console.print()

        s = self.settings
        console.print(f"  Default Model (Legacy): {s.default_model or '(not set)'}")
        console.print(f"  Planning Model: {s.planning_model or '(not set)'}")
        console.print(f"  Implementation Model: {s.implementation_model or '(not set)'}")
        console.print(f"  Default Jira Project: {s.default_jira_project or '(not set)'}")
        console.print(f"  Auto-open Files: {s.auto_open_files}")
        console.print(f"  Preferred Editor: {s.preferred_editor or '(auto-detect)'}")
        console.print(f"  Skip Clarification: {s.skip_clarification}")
        console.print(f"  Squash Commits at End: {s.squash_at_end}")
        console.print()
        console.print("  [bold]Parallel Execution:[/bold]")
        console.print(f"    Enabled: {s.parallel_execution_enabled}")
        console.print(f"    Max Parallel Tasks: {s.max_parallel_tasks}")
        console.print(f"    Fail Fast: {s.fail_fast}")
        console.print()
        console.print("  [bold]Subagents:[/bold]")
        console.print(f"    Planner: {s.subagent_planner}")
        console.print(f"    Tasklist: {s.subagent_tasklist}")
        console.print(f"    Implementer: {s.subagent_implementer}")
        console.print(f"    Reviewer: {s.subagent_reviewer}")
        console.print()


__all__ = [
    "ConfigManager",
    "EnvVarExpansionError",
    "SENSITIVE_KEY_PATTERNS",
]
