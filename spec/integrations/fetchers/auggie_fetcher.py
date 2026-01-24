"""Auggie-mediated ticket fetcher using MCP integrations.

This module provides the AuggieMediatedFetcher class that fetches
ticket data through Auggie's native MCP tool integrations for
Jira, Linear, and GitHub.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.fetchers.exceptions import AgentIntegrationError
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager
    from spec.integrations.auggie import AuggieClient

logger = logging.getLogger(__name__)

# Platforms supported by Auggie MCP integrations
SUPPORTED_PLATFORMS = {Platform.JIRA, Platform.LINEAR, Platform.GITHUB}

# Platform-specific prompt templates for structured JSON responses
PLATFORM_PROMPT_TEMPLATES: dict[Platform, str] = {
    Platform.JIRA: """Use your Jira tool to fetch issue {ticket_id}.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "key": "PROJ-123",
  "summary": "ticket title",
  "description": "full description text",
  "status": "Open|In Progress|Done|etc",
  "issuetype": "Bug|Story|Task|etc",
  "assignee": "username or null",
  "labels": ["label1", "label2"],
  "created": "ISO datetime",
  "updated": "ISO datetime",
  "priority": "High|Medium|Low|etc",
  "project": {{ "key": "PROJ", "name": "Project Name" }}
}}""",
    Platform.LINEAR: """Use your Linear tool to fetch issue {ticket_id}.

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "identifier": "TEAM-123",
  "title": "issue title",
  "description": "full description text",
  "state": {{ "name": "Todo|In Progress|Done|etc" }},
  "assignee": {{ "name": "username" }} or null,
  "labels": {{ "nodes": [{{ "name": "label1" }}] }},
  "createdAt": "ISO datetime",
  "updatedAt": "ISO datetime",
  "priority": 1-4,
  "team": {{ "key": "TEAM" }},
  "url": "https://linear.app/..."
}}""",
    Platform.GITHUB: """Use your GitHub API tool to fetch issue or PR {ticket_id}.

The ticket_id format is "owner/repo#number" (e.g., "microsoft/vscode#12345").

Return ONLY a JSON object with these fields (no markdown, no explanation):
{{
  "number": 123,
  "title": "issue/PR title",
  "body": "full description text",
  "state": "open|closed",
  "user": {{ "login": "username" }},
  "labels": [{{ "name": "label1" }}],
  "created_at": "ISO datetime",
  "updated_at": "ISO datetime",
  "html_url": "https://github.com/...",
  "milestone": {{ "title": "v1.0" }} or null,
  "assignee": {{ "login": "username" }} or null
}}""",
}


class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Auggie's native MCP integrations.

    This fetcher delegates to Auggie's built-in tool calls for platforms
    like Jira, Linear, and GitHub. It's the primary fetch path when
    running in an Auggie-enabled environment.

    Attributes:
        _auggie: AuggieClient for CLI invocations
        _config: Optional ConfigManager for checking agent integrations
    """

    def __init__(
        self,
        auggie_client: AuggieClient,
        config_manager: ConfigManager | None = None,
    ) -> None:
        """Initialize with Auggie client and optional config.

        Args:
            auggie_client: Client for Auggie CLI invocations
            config_manager: Optional ConfigManager for checking integrations
        """
        self._auggie = auggie_client
        self._config = config_manager

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Auggie MCP Fetcher"

    def supports_platform(self, platform: Platform) -> bool:
        """Check if Auggie has integration for this platform.

        First checks if platform is in SUPPORTED_PLATFORMS, then
        consults AgentConfig if ConfigManager is available.

        Args:
            platform: Platform enum value to check

        Returns:
            True if Auggie can fetch from this platform
        """
        if platform not in SUPPORTED_PLATFORMS:
            return False

        if self._config:
            agent_config = self._config.get_agent_config()
            return agent_config.supports_platform(platform.name.lower())

        # Default: assume support if no config to check against
        return True

    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        """Execute fetch prompt via Auggie CLI.

        Uses run_print_quiet() for non-interactive execution that
        captures the response for JSON parsing.

        Args:
            prompt: Structured prompt to send to Auggie
            platform: Target platform (for logging/context)

        Returns:
            Raw response string from Auggie

        Raises:
            AgentIntegrationError: If Auggie invocation fails
        """
        logger.debug("Executing Auggie fetch for %s", platform.name)

        try:
            # run_print_quiet is synchronous - run in executor for async
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._auggie.run_print_quiet(prompt, dont_save_session=True),
            )
        except Exception as e:
            raise AgentIntegrationError(
                message=f"Auggie CLI invocation failed: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

        # run_print_quiet returns a string directly, not CompletedProcess
        # Check if we got an empty response
        if not result:
            raise AgentIntegrationError(
                message="Auggie returned empty response",
                agent_name=self.name,
            )

        return result

    def _get_prompt_template(self, platform: Platform) -> str:
        """Get the prompt template for the given platform.

        Args:
            platform: Platform to get template for

        Returns:
            Prompt template string with {ticket_id} placeholder

        Raises:
            AgentIntegrationError: If platform has no template
        """
        template = PLATFORM_PROMPT_TEMPLATES.get(platform)
        if not template:
            raise AgentIntegrationError(
                message=f"No prompt template for platform: {platform.name}",
                agent_name=self.name,
            )
        return template
