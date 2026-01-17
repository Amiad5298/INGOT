"""External integrations for SPEC.

This package contains:
- git: Git operations (branch management, commits, etc.)
- jira: Jira ticket parsing and integration checking
- auggie: Auggie CLI wrapper and model management
"""

from spec.integrations.auggie import (
    AuggieClient,
    AuggieModel,
    SPEC_AGENT_IMPLEMENTER,
    SPEC_AGENT_PLANNER,
    SPEC_AGENT_REVIEWER,
    SPEC_AGENT_TASKLIST,
    check_auggie_installed,
    get_auggie_version,
    install_auggie,
    list_models,
    version_gte,
)
from spec.integrations.git import (
    DirtyStateAction,
    add_to_gitignore,
    branch_exists,
    checkout_branch,
    create_branch,
    create_checkpoint_commit,
    get_current_branch,
    get_current_commit,
    get_status_short,
    handle_dirty_state,
    is_dirty,
    is_git_repo,
    squash_commits,
)
from spec.integrations.jira import (
    JiraTicket,
    check_jira_integration,
    fetch_ticket_info,
    parse_jira_ticket,
    show_jira_setup_instructions,
)

__all__ = [
    # Git
    "DirtyStateAction",
    "is_git_repo",
    "is_dirty",
    "get_current_branch",
    "get_current_commit",
    "get_status_short",
    "handle_dirty_state",
    "create_branch",
    "branch_exists",
    "checkout_branch",
    "add_to_gitignore",
    "create_checkpoint_commit",
    "squash_commits",
    # Jira
    "JiraTicket",
    "parse_jira_ticket",
    "check_jira_integration",
    "fetch_ticket_info",
    "show_jira_setup_instructions",
    # Auggie
    "AuggieModel",
    "AuggieClient",
    "version_gte",
    "get_auggie_version",
    "check_auggie_installed",
    "install_auggie",
    "list_models",
    # Subagent constants
    "SPEC_AGENT_PLANNER",
    "SPEC_AGENT_TASKLIST",
    "SPEC_AGENT_IMPLEMENTER",
    "SPEC_AGENT_REVIEWER",
]

