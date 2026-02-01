"""External integrations for SPECFLOW.

This package contains:
- git: Git operations (branch management, commits, etc.)
- jira: Jira-specific ticket parsing (legacy, use TicketService for new code)
- auggie: Auggie CLI wrapper and model management
- auth: Authentication management for fallback credentials
"""

from spec.integrations.auggie import (
    AuggieClient,
    AuggieModel,
    check_auggie_installed,
    get_auggie_version,
    install_auggie,
    list_models,
    version_gte,
)
from spec.integrations.auth import (
    AuthenticationManager,
    PlatformCredentials,
)
from spec.integrations.cache import (
    CacheConfigurationError,
    CachedTicket,
    CacheKey,
    FileBasedTicketCache,
    InMemoryTicketCache,
    TicketCache,
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
)
from spec.integrations.ticket_service import (
    TicketService,
    create_ticket_service,
)

# Note: SPECFLOW_AGENT_* constants are NOT re-exported here to avoid
# circular imports. Import them directly from spec.workflow.constants.

__all__ = [
    # Authentication
    "AuthenticationManager",
    "PlatformCredentials",
    # Cache
    "CacheKey",
    "CachedTicket",
    "CacheConfigurationError",
    "TicketCache",
    "InMemoryTicketCache",
    "FileBasedTicketCache",
    # Note: _get_global_cache, _set_global_cache, _clear_global_cache are
    # internal APIs imported above for testing/legacy support only.
    # They are intentionally NOT exported in __all__ per AMI-32 spec.
    # Production code should use dependency injection via TicketService.
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
    # Jira (legacy - use TicketService for new code)
    "JiraTicket",
    "parse_jira_ticket",
    "check_jira_integration",
    "fetch_ticket_info",
    # Auggie
    "AuggieModel",
    "AuggieClient",
    "version_gte",
    "get_auggie_version",
    "check_auggie_installed",
    "install_auggie",
    "list_models",
    # Note: SPECFLOW_AGENT_* constants removed - import from spec.workflow.constants
    # TicketService
    "TicketService",
    "create_ticket_service",
]
