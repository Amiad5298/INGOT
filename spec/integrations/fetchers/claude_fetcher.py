"""Claude Code CLI-mediated ticket fetcher using MCP integrations.

This module provides the ClaudeMediatedFetcher class that fetches
ticket data through the Claude Code CLI's MCP tool integrations for
Jira, Linear, and GitHub.

This follows the exact same pattern as AuggieMediatedFetcher.
Prompt templates are shared via fetchers.templates module.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendTimeoutError
from spec.integrations.fetchers.base import AgentMediatedFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
    AgentIntegrationError,
    AgentResponseParseError,
    PlatformNotSupportedError,
)
from spec.integrations.fetchers.templates import (
    PLATFORM_PROMPT_TEMPLATES,
    REQUIRED_FIELDS,
    SUPPORTED_PLATFORMS,
)
from spec.integrations.providers.base import Platform

if TYPE_CHECKING:
    from spec.config import ConfigManager

logger = logging.getLogger(__name__)

# Default timeout for agent execution (seconds)
DEFAULT_TIMEOUT_SECONDS: float = 60.0


class ClaudeMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Claude Code CLI's MCP integrations.

    This fetcher delegates to the Claude Code backend's tool calls for platforms
    like Jira, Linear, and GitHub. It follows the same pattern as
    AuggieMediatedFetcher.

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
            backend: AI backend instance (ClaudeBackend)
            config_manager: Optional ConfigManager for checking integrations
            timeout_seconds: Timeout for agent execution (default: 60s)
        """
        self._backend = backend
        self._config = config_manager
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Claude MCP Fetcher"

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

        return True

    async def fetch(
        self,
        ticket_id: str,
        platform: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Fetch raw ticket data using platform string.

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
        return await self.fetch_raw(ticket_id, platform_enum, timeout_seconds=timeout_seconds)

    async def _execute_fetch_prompt(
        self,
        prompt: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute fetch prompt via AI backend with timeout.

        This is the single place that resolves the effective timeout.
        Callers pass timeout_seconds=None to use the instance default.

        Args:
            prompt: Structured prompt to send to the backend
            platform: Target platform (for logging/context)
            timeout_seconds: Timeout for this execution (falls back to instance default)

        Returns:
            Raw response string from the backend

        Raises:
            AgentFetchError: If execution fails or times out
            AgentIntegrationError: If agent integration is misconfigured (passes through)
        """
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        )
        logger.debug(
            "Executing backend fetch for %s (timeout: %.1fs)",
            platform.name,
            effective_timeout,
        )

        # Timeout is enforced at the subprocess level (via backend → client →
        # subprocess.run(timeout=)). asyncio.wait_for acts as a safety net
        # with a generous buffer in case something else blocks.
        safety_timeout = effective_timeout + 10

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._backend.run_print_quiet(
                        prompt,
                        dont_save_session=True,
                        timeout_seconds=effective_timeout,
                    ),
                ),
                timeout=safety_timeout,
            )
        except (TimeoutError, BackendTimeoutError):
            raise AgentFetchError(
                message=(f"Backend execution timed out after {effective_timeout}s"),
                agent_name=self.name,
            ) from None
        except (AgentIntegrationError, AgentFetchError, AgentResponseParseError):
            raise
        except Exception as e:
            raise AgentFetchError(
                message=f"Backend invocation failed: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

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

        Args:
            ticket_id: The ticket identifier
            platform: The platform to fetch from
            timeout_seconds: Timeout for this request

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
        except (AgentIntegrationError, AgentFetchError, AgentResponseParseError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raise AgentFetchError(
                message=f"Unexpected error during agent communication: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e

        data = self._parse_response(response)
        return self._validate_response(data, platform)
