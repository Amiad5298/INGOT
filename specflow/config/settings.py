"""Settings dataclass for SPECFLOW configuration.

This module defines the Settings dataclass that holds all configuration
values, matching the original Bash script's configuration options.
"""

from dataclasses import dataclass, field
from pathlib import Path

# Import subagent constants as single source of truth
from specflow.integrations.auggie import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)


@dataclass
class Settings:
    """Configuration settings for SPEC.

    All settings have sensible defaults and can be loaded from
    the configuration file (~/.specflow-config).

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
        parallel_execution_enabled: Enable parallel execution of independent tasks
        max_parallel_tasks: Maximum number of parallel tasks (1-5)
        fail_fast: Stop on first task failure
        subagent_planner: Agent name for planning step
        subagent_tasklist: Agent name for task list generation
        subagent_implementer: Agent name for task execution
        subagent_reviewer: Agent name for task validation
        subagent_doc_updater: Agent name for documentation update step
        auto_update_docs: Enable automatic documentation updates after code changes
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

    # Parallel execution settings
    parallel_execution_enabled: bool = True
    max_parallel_tasks: int = 3
    fail_fast: bool = False

    # Subagent settings (customizable agent names)
    # Defaults from auggie.py constants - the single source of truth
    subagent_planner: str = SPECFLOW_AGENT_PLANNER
    subagent_tasklist: str = SPECFLOW_AGENT_TASKLIST
    subagent_tasklist_refiner: str = SPECFLOW_AGENT_TASKLIST_REFINER
    subagent_implementer: str = SPECFLOW_AGENT_IMPLEMENTER
    subagent_reviewer: str = SPECFLOW_AGENT_REVIEWER
    subagent_doc_updater: str = SPECFLOW_AGENT_DOC_UPDATER

    # Documentation update settings
    auto_update_docs: bool = True  # Enable automatic documentation updates

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
            "PARALLEL_EXECUTION_ENABLED": "parallel_execution_enabled",
            "MAX_PARALLEL_TASKS": "max_parallel_tasks",
            "FAIL_FAST": "fail_fast",
            "SUBAGENT_PLANNER": "subagent_planner",
            "SUBAGENT_TASKLIST": "subagent_tasklist",
            "SUBAGENT_TASKLIST_REFINER": "subagent_tasklist_refiner",
            "SUBAGENT_IMPLEMENTER": "subagent_implementer",
            "SUBAGENT_REVIEWER": "subagent_reviewer",
            "SUBAGENT_DOC_UPDATER": "subagent_doc_updater",
            "AUTO_UPDATE_DOCS": "auto_update_docs",
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
CONFIG_FILE = Path.home() / ".specflow-config"


__all__ = [
    "Settings",
    "CONFIG_FILE",
]

