"""Configuration manager for AI Workflow.

This module provides the ConfigManager class for loading, saving, and
managing configuration values, matching the original Bash script's
configuration handling with security improvements.
"""

import os
import re
import tempfile
from pathlib import Path

from ai_workflow.config.settings import CONFIG_FILE, Settings
from ai_workflow.utils.logging import log_message


class ConfigManager:
    """Manages configuration loading and saving.

    Security features:
    - Safe line-by-line parsing (no eval/exec)
    - Key name validation
    - Atomic file writes
    - Secure file permissions (600)

    Attributes:
        config_path: Path to the configuration file
        settings: Current settings instance
        _raw_values: Raw key-value pairs from file
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the configuration manager.

        Args:
            config_path: Optional custom path to config file
        """
        self.config_path = config_path or CONFIG_FILE
        self.settings = Settings()
        self._raw_values: dict[str, str] = {}

    def load(self) -> Settings:
        """Load configuration from file.

        Security: Uses safe line-by-line parsing instead of eval/exec.
        Only reads KEY=VALUE or KEY="VALUE" pairs.

        Returns:
            Settings instance with loaded values
        """
        self._raw_values = {}

        if not self.config_path.exists():
            log_message(f"No configuration file found at {self.config_path}")
            return self.settings

        log_message(f"Loading configuration from {self.config_path}")

        # Pattern for KEY=VALUE or KEY="VALUE" or KEY='VALUE'
        pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$")

        with self.config_path.open() as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                match = pattern.match(line)
                if match:
                    key, value = match.groups()

                    # Remove surrounding quotes
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]

                    self._raw_values[key] = value
                    self._apply_value_to_settings(key, value)

        log_message(f"Configuration loaded successfully ({len(self._raw_values)} keys)")
        return self.settings

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
                from ai_workflow.integrations.auggie import extract_model_id
                value = extract_model_id(value)
            setattr(self.settings, attr, value)

    def save(self, key: str, value: str) -> None:
        """Save a configuration value to file.

        Security: Validates key name, uses atomic file replacement.

        Args:
            key: Configuration key (alphanumeric + underscore)
            value: Configuration value

        Raises:
            ValueError: If key name is invalid
        """
        # Validate key name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            raise ValueError(f"Invalid config key: {key}")

        # Update in-memory values
        self._raw_values[key] = value
        self._apply_value_to_settings(key, value)

        # Read existing file content
        existing_lines: list[str] = []
        if self.config_path.exists():
            existing_lines = self.config_path.read_text().splitlines()

        # Build new file content
        new_lines: list[str] = []
        written_keys: set[str] = set()
        key_pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)=")

        for line in existing_lines:
            # Preserve comments and empty lines
            if not line.strip() or line.strip().startswith("#"):
                new_lines.append(line)
                continue

            match = key_pattern.match(line)
            if match:
                existing_key = match.group(1)
                if existing_key in self._raw_values:
                    # Write updated value
                    new_lines.append(f'{existing_key}="{self._raw_values[existing_key]}"')
                    written_keys.add(existing_key)
                else:
                    # Preserve unknown keys
                    new_lines.append(line)
            else:
                # Preserve malformed lines
                new_lines.append(line)

        # Add new keys not in file
        for k, v in self._raw_values.items():
            if k not in written_keys:
                new_lines.append(f'{k}="{v}"')

        # Atomic write using temp file
        self._atomic_write(new_lines)
        log_message(f"Configuration saved: {key}={value}")

    def _atomic_write(self, lines: list[str]) -> None:
        """Atomically write lines to config file.

        Args:
            lines: Lines to write
        """
        # Create temp file in same directory for atomic move
        fd, temp_path = tempfile.mkstemp(
            dir=self.config_path.parent,
            prefix=".ai-workflow-config-",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(lines))
                if lines:
                    f.write("\n")

            # Set secure permissions before moving
            os.chmod(temp_path, 0o600)

            # Atomic replace
            Path(temp_path).replace(self.config_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def get(self, key: str, default: str = "") -> str:
        """Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self._raw_values.get(key, default)

    def show(self) -> None:
        """Display current configuration using Rich formatting."""
        from ai_workflow.utils.console import console, print_header, print_info

        print_header("Current Configuration")

        if not self.config_path.exists():
            print_info(f"No configuration file found at: {self.config_path}")
            print_info("Configuration will be created when you save settings.")
            return

        print_info(f"Configuration file: {self.config_path}")
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


__all__ = [
    "ConfigManager",
]

