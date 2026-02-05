"""Settings dataclass for SPECFLOW configuration.

This module defines the Settings dataclass that holds all configuration
values, matching the original Bash script's configuration options.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.integrations.providers import Platform

# Subagent constants - must be defined here to avoid circular imports.
# These are the canonical values; spec/workflow/constants.py re-exports them.
# DO NOT import from spec.workflow.constants here - it causes circular imports
# because spec/workflow/__init__.py imports from runner.py which imports from
# spec/config/manager.py.
_SPECFLOW_AGENT_PLANNER = "spec-planner"
_SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
_SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
_SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
_SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
_SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"


@dataclass
class Settings:
    """Configuration settings for SPEC.

    All settings have sensible defaults and can be loaded from
    the configuration file (~/.spec-config).

    Attributes:
        default_model: Legacy default AI model for all phases
        planning_model: AI model for Steps 1-2 (Discovery & Planning)
        implementation_model: AI model for Step 3 (Execution)
        jira_integration_status: Cached Jira integration status
        jira_check_timestamp: Unix timestamp of last Jira check
        default_jira_project: Default project key for numeric-only Jira ticket IDs
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
        default_platform: Default platform for ambiguous ticket IDs (jira, linear, etc.)
        ai_backend: AI backend selection (auggie, claude, cursor) - must be explicitly configured
    """

    # Model settings
    default_model: str = ""
    planning_model: str = ""
    implementation_model: str = ""

    # Jira settings
    jira_integration_status: str = ""
    jira_check_timestamp: int = 0
    default_jira_project: str = ""  # Default project key for numeric-only Jira ticket IDs

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
    # Defaults use local constants to avoid circular imports
    subagent_planner: str = _SPECFLOW_AGENT_PLANNER
    subagent_tasklist: str = _SPECFLOW_AGENT_TASKLIST
    subagent_tasklist_refiner: str = _SPECFLOW_AGENT_TASKLIST_REFINER
    subagent_implementer: str = _SPECFLOW_AGENT_IMPLEMENTER
    subagent_reviewer: str = _SPECFLOW_AGENT_REVIEWER
    subagent_doc_updater: str = _SPECFLOW_AGENT_DOC_UPDATER

    # Documentation update settings
    auto_update_docs: bool = True  # Enable automatic documentation updates

    # Platform settings
    default_platform: str = ""  # Default platform for ambiguous ticket IDs (jira, linear, etc.)

    # Backend settings
    ai_backend: str = (
        ""  # AI backend selection (auggie, claude, cursor) - no default, must be configured
    )

    # Fetch strategy settings
    fetch_strategy_default: str = "auto"
    fetch_cache_duration_hours: int = 24
    fetch_timeout_seconds: int = 30
    fetch_max_retries: int = 3
    fetch_retry_delay_seconds: float = 1.0

    # Config key to attribute mapping
    _key_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "DEFAULT_MODEL": "default_model",
            "PLANNING_MODEL": "planning_model",
            "IMPLEMENTATION_MODEL": "implementation_model",
            "JIRA_INTEGRATION_STATUS": "jira_integration_status",
            "JIRA_CHECK_TIMESTAMP": "jira_check_timestamp",
            "DEFAULT_JIRA_PROJECT": "default_jira_project",
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
            # Platform settings
            "DEFAULT_PLATFORM": "default_platform",
            # Backend settings
            "AI_BACKEND": "ai_backend",
            # Fetch strategy settings
            "FETCH_STRATEGY_DEFAULT": "fetch_strategy_default",
            "FETCH_CACHE_DURATION_HOURS": "fetch_cache_duration_hours",
            "FETCH_TIMEOUT_SECONDS": "fetch_timeout_seconds",
            "FETCH_MAX_RETRIES": "fetch_max_retries",
            "FETCH_RETRY_DELAY_SECONDS": "fetch_retry_delay_seconds",
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

    def get_default_platform(self) -> Platform | None:
        """Get default platform as Platform enum, or None if not configured.

        Logs a warning if the configured value is invalid (non-empty but not
        a valid platform name).

        Returns:
            Platform enum value if default_platform is set and valid, None otherwise
        """
        import logging

        from spec.integrations.providers import Platform

        if not self.default_platform:
            return None
        try:
            return Platform[self.default_platform.upper()]
        except KeyError:
            # Log warning for invalid configuration value
            logger = logging.getLogger(__name__)
            valid_platforms = ", ".join(p.name.lower() for p in Platform)
            logger.warning(
                f"Invalid DEFAULT_PLATFORM value '{self.default_platform}', ignoring. "
                f"Valid options: {valid_platforms}"
            )
            return None


# Default configuration file path
CONFIG_FILE = Path.home() / ".spec-config"


__all__ = [
    "Settings",
    "CONFIG_FILE",
]
