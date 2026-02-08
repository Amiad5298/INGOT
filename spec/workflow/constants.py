"""Workflow constants.

This module contains constants used across the workflow that are
not specific to any particular AI backend.

These constants define the canonical names for SPECFLOW subagents
used across all workflow steps, plus default timeout values.
"""

# Subagent names for SPEC workflow
# These are the canonical identifiers used by workflow steps
SPECFLOW_AGENT_PLANNER = "spec-planner"
SPECFLOW_AGENT_TASKLIST = "spec-tasklist"
SPECFLOW_AGENT_TASKLIST_REFINER = "spec-tasklist-refiner"
SPECFLOW_AGENT_IMPLEMENTER = "spec-implementer"
SPECFLOW_AGENT_REVIEWER = "spec-reviewer"
SPECFLOW_AGENT_FIXER = "spec-implementer"  # Autofix reuses the implementer agent
SPECFLOW_AGENT_DOC_UPDATER = "spec-doc-updater"

# Default timeout values (seconds)
DEFAULT_EXECUTION_TIMEOUT = 60
FIRST_RUN_TIMEOUT = 120
ONBOARDING_SMOKE_TEST_TIMEOUT = 60

__all__ = [
    # Subagent constants
    "SPECFLOW_AGENT_PLANNER",
    "SPECFLOW_AGENT_TASKLIST",
    "SPECFLOW_AGENT_TASKLIST_REFINER",
    "SPECFLOW_AGENT_IMPLEMENTER",
    "SPECFLOW_AGENT_REVIEWER",
    "SPECFLOW_AGENT_FIXER",
    "SPECFLOW_AGENT_DOC_UPDATER",
    # Timeout constants
    "DEFAULT_EXECUTION_TIMEOUT",
    "FIRST_RUN_TIMEOUT",
    "ONBOARDING_SMOKE_TEST_TIMEOUT",
]
