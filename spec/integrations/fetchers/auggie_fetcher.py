"""AI backend-mediated ticket fetcher using MCP integrations.

This module provides the AuggieMediatedFetcher class that fetches
ticket data through an AI backend's MCP tool integrations for
Jira, Linear, and GitHub (platforms with MCP integrations).

Architecture Note:
    This fetcher uses a prompt-based approach rather than direct tool
    invocation because the AIBackend API does not expose an `invoke_tool()`
    method. The CLI interface requires natural language prompts that instruct
    the agent to use its MCP tools.

    To mitigate LLM variability:
    - Prompts explicitly request JSON-only output
    - Templates use valid JSON examples (no "or null" syntax)
    - Response parsing handles markdown code blocks
    - Validation ensures required fields exist before returning

    If AIBackend adds direct tool invocation in the future, this fetcher
    should be updated to use that approach for more deterministic behavior.

Historical Note:
    This class was originally designed for Auggie (hence the name
    "AuggieMediatedFetcher"). It now works with any AIBackend implementation.
    The class name is preserved for backwards compatibility.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from spec.integrations.backends.base import AIBackend
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
)
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager

logger = logging.getLogger(__name__)

# Default timeout for agent execution (seconds)
DEFAULT_TIMEOUT_SECONDS: float = 60.0

# Platforms supported by AI backend MCP integrations
SUPPORTED_PLATFORMS = {Platform.JIRA, Platform.LINEAR, Platform.GITHUB}

# Required fields per platform for validation
# These are the minimum fields that must be present for normalization
REQUIRED_FIELDS: dict[Platform, set[str]] = {
    Platform.JIRA: {"key", "summary"},
    Platform.LINEAR: {"identifier", "title"},
    Platform.GITHUB: {"number", "title"},
}

# Platform-specific prompt templates for structured JSON responses
# NOTE: Templates use valid JSON examples only - no "or null" syntax that could be
# output literally. Instead, we describe optional fields in comments.
PLATFORM_PROMPT_TEMPLATES: dict[Platform, str] = {
    Platform.JIRA: """Use your Jira tool to fetch issue {ticket_id}.

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields marked (optional) can be null if not available.

{{
  "key": "PROJ-123",
  "summary": "ticket title",
  "description": "full description text",
  "status": "Open",
  "issuetype": "Bug",
  "assignee": null,
  "labels": ["label1", "label2"],
  "created": "2024-01-15T10:30:00Z",
  "updated": "2024-01-16T14:20:00Z",
  "priority": "High",
  "project": {{"key": "PROJ", "name": "Project Name"}}
}}""",
    Platform.LINEAR: """Use your Linear tool to fetch issue {ticket_id}.

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields can be null if not available.

{{
  "identifier": "TEAM-123",
  "title": "issue title",
  "description": "full description text",
  "state": {{"name": "Todo"}},
  "assignee": null,
  "labels": {{"nodes": [{{"name": "label1"}}]}},
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-01-16T14:20:00Z",
  "priority": 2,
  "team": {{"key": "TEAM"}},
  "url": "https://linear.app/team/issue/TEAM-123"
}}""",
    Platform.GITHUB: """Use your GitHub API tool to fetch issue or PR {ticket_id}.

The ticket_id format is "owner/repo#number" (e.g., "microsoft/vscode#12345").

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields can be null if not available.

{{
  "number": 123,
  "title": "issue/PR title",
  "body": "full description text",
  "state": "open",
  "user": {{"login": "username"}},
  "labels": [{{"name": "label1"}}],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-16T14:20:00Z",
  "html_url": "https://github.com/owner/repo/issues/123",
  "milestone": null,
  "assignee": null
}}""",
}


class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through AI backend's MCP integrations.

    This fetcher delegates to the AI backend's tool calls for platforms
    like Jira, Linear, and GitHub. It's the primary fetch path when
    running in an AI agent-enabled environment.

    Note:
        Despite the name "AuggieMediatedFetcher", this fetcher can work
        with any AIBackend implementation. The name is preserved for
        backwards compatibility.

        This fetcher uses prompt-based invocation since the backend API
        does not expose direct tool invocation. See module docstring for details.

    Attributes:
        _backend: AIBackend instance for prompt execution
        _config: Optional ConfigManager for checking agent integrations
        _timeout_seconds: Timeout for agent execution
    """

    def __init__(
        self,
        backend: AIBackend,
        config_manager: ConfigManager | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize with AI backend and optional config.

        Args:
            backend: AI backend instance (AuggieBackend, ClaudeBackend, etc.)
            config_manager: Optional ConfigManager for checking integrations
            timeout_seconds: Timeout for agent execution (default: 60s)
        """
        self._backend = backend
        self._config = config_manager
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Auggie MCP Fetcher"

    def _resolve_platform(self, platform: str) -> Platform:
        """Resolve a platform string to Platform enum and validate support.

        Args:
            platform: Platform name as string (case-insensitive)

        Returns:
            Platform enum value (guaranteed to be in SUPPORTED_PLATFORMS)

        Raises:
            AgentIntegrationError: If platform string is not recognized or not supported
        """
        platform_upper = platform.upper()
        valid_platforms = sorted(p.name for p in SUPPORTED_PLATFORMS)

        try:
            platform_enum = Platform[platform_upper]
        except KeyError:
            raise AgentIntegrationError(
                message=(
                    f"Unknown platform: '{platform}'. "
                    f"Supported platforms: {', '.join(valid_platforms)}"
                ),
                agent_name=self.name,
            ) from None

        # Validate the resolved enum is actually supported
        if platform_enum not in SUPPORTED_PLATFORMS:
            raise AgentIntegrationError(
                message=(
                    f"Platform '{platform_enum.name}' is not supported. "
                    f"Supported platforms: {', '.join(valid_platforms)}"
                ),
                agent_name=self.name,
            )

        return platform_enum

    def supports_platform(self, platform: Platform) -> bool:
        """Check if the backend has integration for this platform.

        First checks if platform is in SUPPORTED_PLATFORMS, then
        consults AgentConfig if ConfigManager is available.

        Args:
            platform: Platform enum value to check

        Returns:
            True if the backend can fetch from this platform
        """
        if platform not in SUPPORTED_PLATFORMS:
            return False

        if self._config:
            agent_config = self._config.get_agent_config()
            return agent_config.supports_platform(platform.name.lower())

        # Default: assume support if no config to check against
        return True

    async def fetch(
        self,
        ticket_id: str,
        platform: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch raw ticket data using platform string.

        This is the primary public interface for TicketService integration.
        Accepts platform as a string and handles internal enum conversion.

        Args:
            ticket_id: The ticket identifier (e.g., 'PROJ-123', 'owner/repo#42')
            platform: Platform name as string (e.g., 'jira', 'github', 'linear')
            timeout_seconds: Optional timeout override for this request

        Returns:
            Raw ticket data as a dictionary

        Raises:
            AgentIntegrationError: If platform is not supported/configured
            AgentFetchError: If tool execution fails
            AgentResponseParseError: If response cannot be parsed or validated
        """
        platform_enum = self._resolve_platform(platform)
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        )
        return await self.fetch_raw(ticket_id, platform_enum, timeout_seconds=effective_timeout)

    async def _execute_fetch_prompt(
        self,
        prompt: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute fetch prompt via AI backend with timeout.

        Uses run_print_quiet() for non-interactive execution that
        captures the response for JSON parsing.

        Note:
            The timeout is implemented at the asyncio level. The underlying
            subprocess may continue running if cancelled, but we won't wait
            for it indefinitely.

        Args:
            prompt: Structured prompt to send to the backend
            platform: Target platform (for logging/context)
            timeout_seconds: Timeout for this execution (defaults to self._timeout_seconds)

        Returns:
            Raw response string from the backend

        Raises:
            AgentFetchError: If execution fails or times out
        """
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        )
        logger.debug(
            "Executing backend fetch for %s (timeout: %.1fs)",
            platform.name,
            effective_timeout,
        )

        try:
            # run_print_quiet is synchronous - run in executor for async
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._backend.run_print_quiet(prompt, dont_save_session=True),
                ),
                timeout=effective_timeout,
            )
        except TimeoutError:
            raise AgentFetchError(
                message=(f"Backend execution timed out after {effective_timeout}s"),
                agent_name=self.name,
            ) from None
        except Exception as e:
            raise AgentFetchError(
                message=f"Backend invocation failed: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

        # run_print_quiet returns a string directly, not CompletedProcess
        if not result:
            raise AgentFetchError(
                message="Backend returned empty response",
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

    def _validate_response(self, data: dict[str, Any], platform: Platform) -> dict[str, Any]:
        """Validate that required fields exist in the response.

        Args:
            data: Parsed JSON data from agent response
            platform: Platform for field requirements

        Returns:
            The validated data (unchanged)

        Raises:
            AgentResponseParseError: If required fields are missing
        """
        required = REQUIRED_FIELDS.get(platform, set())
        missing = required - set(data.keys())

        if missing:
            raise AgentResponseParseError(
                message=(
                    f"Response missing required fields for {platform.name}: "
                    f"{', '.join(sorted(missing))}"
                ),
                agent_name=self.name,
                raw_response=str(data),
            )

        return data

    async def fetch_raw(
        self,
        ticket_id: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch raw ticket data with validation.

        Implements the full fetch logic with platform-specific validation.
        This method does not call super() to allow passing timeout through
        the call chain in a thread-safe manner.

        Args:
            ticket_id: The ticket identifier
            platform: The platform to fetch from
            timeout_seconds: Timeout for this request (defaults to self._timeout_seconds)

        Returns:
            Validated raw ticket data as a dictionary

        Raises:
            PlatformNotSupportedError: If platform is not supported
            AgentFetchError: If agent execution fails
            AgentResponseParseError: If response parsing or validation fails
        """
        if not self.supports_platform(platform):
            raise PlatformNotSupportedError(
                platform=platform.name,
                fetcher_name=self.name,
            )

        prompt = self._build_prompt(ticket_id, platform)
        try:
            response = await self._execute_fetch_prompt(
                prompt, platform, timeout_seconds=timeout_seconds
            )
        except AgentIntegrationError:
            raise
        except Exception as e:
            raise AgentIntegrationError(
                message=f"Unexpected error during agent communication: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

        data = self._parse_response(response)
        return self._validate_response(data, platform)
