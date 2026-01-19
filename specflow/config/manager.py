"""Configuration manager for SPEC.

This module provides the ConfigManager class for loading, saving, and
managing configuration values with a cascading hierarchy:

    1. Environment Variables (highest priority)
    2. Local Config (.specflow in project/parent directories)
    3. Global Config (~/.specflow-config)
    4. Built-in Defaults (lowest priority)

This enables developers working on multiple projects with different
trackers to have project-specific settings while maintaining global defaults.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Literal, Optional

from specflow.config.settings import CONFIG_FILE, Settings
from specflow.utils.logging import log_message


# Keys containing these substrings are considered sensitive and should not be logged
SENSITIVE_KEY_PATTERNS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PAT")


class ConfigManager:
    """Manages configuration loading and saving with cascading hierarchy.

    Configuration Precedence (highest to lowest):
    1. Environment Variables - CI/CD, temporary overrides
    2. Local Config (.specflow) - Project-specific settings
    3. Global Config (~/.specflow-config) - User defaults
    4. Built-in Defaults - Fallback values

    Security features:
    - Safe line-by-line parsing (no eval/exec)
    - Key name validation
    - Atomic file writes
    - Secure file permissions (600)

    Attributes:
        settings: Current settings instance
        global_config_path: Path to global ~/.specflow-config file
        local_config_path: Path to discovered local .specflow file (after load)
    """

    LOCAL_CONFIG_NAME = ".specflow"
    GLOBAL_CONFIG_NAME = ".specflow-config"

    def __init__(self, global_config_path: Path | None = None) -> None:
        """Initialize the configuration manager.

        Args:
            global_config_path: Optional custom path to global config file.
                                Defaults to ~/.specflow-config.
        """
        self.global_config_path = global_config_path or CONFIG_FILE
        self.local_config_path: Optional[Path] = None
        self.settings = Settings()
        self._raw_values: dict[str, str] = {}
        self._config_sources: dict[str, str] = {}

    def load(self) -> Settings:
        """Load configuration from all sources with cascading precedence.

        Loading order (later sources override earlier ones):
        1. Built-in defaults (from Settings dataclass)
        2. Global config (~/.specflow-config)
        3. Local config (.specflow in project/parent directories)
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

        # Step 2: Load global config (~/.specflow-config) - lowest file-based priority
        if self.global_config_path.exists():
            log_message(f"Loading global configuration from {self.global_config_path}")
            self._load_file(self.global_config_path, source="global")

        # Step 3: Load local config (.specflow) - higher priority
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

    def _find_local_config(self) -> Optional[Path]:
        """Find local .specflow config by traversing up from CWD.

        Starts from current working directory and traverses parent
        directories until:
        - A .specflow file is found
        - A .git directory is found (repository root)
        - The filesystem root is reached

        Returns:
            Path to local config file, or None if not found
        """
        current = Path.cwd()
        while True:
            config_path = current / self.LOCAL_CONFIG_NAME
            if config_path.exists():
                return config_path

            # Stop at repository root
            if (current / ".git").exists():
                break

            parent = current.parent
            if parent == current:  # Reached filesystem root
                break
            current = parent

        return None

    def _find_repo_root(self) -> Optional[Path]:
        """Find the repository root by looking for .git directory.

        Traverses from current working directory upward until:
        - A .git directory is found (returns that directory)
        - The filesystem root is reached (returns None)

        Returns:
            Path to repository root, or None if not in a repository
        """
        current = Path.cwd()
        while True:
            if (current / ".git").exists():
                return current

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
                from specflow.integrations.auggie import extract_model_id
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
            - If scope="local" and no local config exists, creates a .specflow
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
            scope: Target config file - "global" (~/.specflow-config) or
                   "local" (.specflow in project directory)
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
                repo_root = self._find_repo_root()
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
            prefix=".specflow-config-",
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

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        """Check if a configuration key contains sensitive data.

        Args:
            key: The configuration key name

        Returns:
            True if the key is considered sensitive
        """
        key_upper = key.upper()
        return any(pattern in key_upper for pattern in SENSITIVE_KEY_PATTERNS)

    def _log_config_save(self, key: str, scope: str) -> None:
        """Log a configuration save without exposing sensitive values.

        For sensitive keys (containing TOKEN, KEY, SECRET, PASSWORD, PAT),
        the value is not logged. For other keys, only the key and scope
        are logged.

        Args:
            key: The configuration key that was saved
            scope: The scope (global or local) where it was saved
        """
        if self._is_sensitive_key(key):
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

    def get_config_source(self, key: str) -> str:
        """Return the source of a configuration value (for debugging).

        Args:
            key: Configuration key

        Returns:
            Source identifier: "environment", "local (/path)", "global (/path)",
            or "default" if the value comes from built-in defaults.
        """
        if key in self._config_sources:
            return self._config_sources[key]
        return "default"

    def show(self) -> None:
        """Display current configuration using Rich formatting."""
        from specflow.utils.console import console, print_header, print_info

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
]

