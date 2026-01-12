"""Settings dataclass for AI Workflow configuration.

This module defines the Settings dataclass that holds all configuration
values, matching the original Bash script's configuration options.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    """Configuration settings for AI Workflow.

    All settings have sensible defaults and can be loaded from
    the configuration file (~/.ai-workflow-config).

    Attributes:
        default_model: Legacy default AI model for all phases
        planning_model: AI model for Steps 1-2 (Discovery & Planning)
        implementation_model: AI model for Step 3 (Execution)
        default_jira_project: Default Jira project key for numeric ticket IDs
        jira_integration_status: Cached Jira integration status
        jira_check_timestamp: Unix timestamp of last Jira check
        auto_open_files: Whether to auto-open files in editor
        preferred_editor: Preferred editor command (empty = auto-detect)
        skip_clarification: Skip clarification step by default
        squash_at_end: Squash checkpoint commits at workflow end
    """

    # Model settings
    default_model: str = ""
    planning_model: str = ""
    implementation_model: str = ""

    # Jira settings
    default_jira_project: str = ""
    jira_integration_status: str = ""
    jira_check_timestamp: int = 0

    # UI settings
    auto_open_files: bool = True
    preferred_editor: str = ""

    # Workflow settings
    skip_clarification: bool = False
    squash_at_end: bool = True

    # Config key to attribute mapping
    _key_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "DEFAULT_MODEL": "default_model",
            "PLANNING_MODEL": "planning_model",
            "IMPLEMENTATION_MODEL": "implementation_model",
            "DEFAULT_JIRA_PROJECT": "default_jira_project",
            "JIRA_INTEGRATION_STATUS": "jira_integration_status",
            "JIRA_CHECK_TIMESTAMP": "jira_check_timestamp",
            "AUTO_OPEN_FILES": "auto_open_files",
            "PREFERRED_EDITOR": "preferred_editor",
            "SKIP_CLARIFICATION": "skip_clarification",
            "SQUASH_AT_END": "squash_at_end",
        },
        repr=False,
    )

    def get_attribute_for_key(self, key: str) -> str | None:
        """Get the attribute name for a config key.

        Args:
            key: Configuration key (e.g., "DEFAULT_MODEL")

        Returns:
            Attribute name or None if key is unknown
        """
        return self._key_mapping.get(key)

    def get_key_for_attribute(self, attr: str) -> str | None:
        """Get the config key for an attribute name.

        Args:
            attr: Attribute name (e.g., "default_model")

        Returns:
            Config key or None if attribute is unknown
        """
        for key, value in self._key_mapping.items():
            if value == attr:
                return key
        return None

    @classmethod
    def get_config_keys(cls) -> list[str]:
        """Get list of all valid configuration keys.

        Returns:
            List of configuration key names
        """
        # Create a temporary instance to get the keys
        temp = cls()
        return list(temp._key_mapping.keys())


# Default configuration file path
CONFIG_FILE = Path.home() / ".ai-workflow-config"


__all__ = [
    "Settings",
    "CONFIG_FILE",
]

