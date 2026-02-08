"""Backend-platform MCP support compatibility matrix.

Maps each AI backend to the set of ticket platforms it supports
via MCP (Model Context Protocol) integrations, and defines which
platforms support direct API access.

TODO: Consumed by Phase 6 (fetch-strategy selection). Not yet wired
into production code paths.
"""

from spec.config.fetch_config import AgentPlatform
from spec.integrations.providers.base import Platform

MCP_SUPPORT: dict[AgentPlatform, frozenset[Platform]] = {
    AgentPlatform.AUGGIE: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.CLAUDE: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.CURSOR: frozenset({Platform.JIRA, Platform.LINEAR, Platform.GITHUB}),
    AgentPlatform.AIDER: frozenset(),
    AgentPlatform.MANUAL: frozenset(),
}

API_SUPPORT: frozenset[Platform] = frozenset(
    {
        Platform.JIRA,
        Platform.LINEAR,
        Platform.GITHUB,
        Platform.AZURE_DEVOPS,
        Platform.TRELLO,
        Platform.MONDAY,
    }
)


def get_platform_support(backend: AgentPlatform, platform: Platform) -> tuple[bool, str]:
    """Check how a backend supports a ticket platform.

    Args:
        backend: The AI backend to check
        platform: The ticket platform to check support for

    Returns:
        Tuple of (is_supported, mechanism) where mechanism is
        'mcp', 'api', or 'unsupported'.
    """
    if platform in MCP_SUPPORT.get(backend, frozenset()):
        return True, "mcp"
    if platform in API_SUPPORT:
        return True, "api"
    return False, "unsupported"


__all__ = ["MCP_SUPPORT", "API_SUPPORT", "get_platform_support"]
