"""Base classes for ticket fetching strategies.

This module defines:
- TicketFetcher: Abstract base class for all ticket fetchers
- AgentMediatedFetcher: Base class for fetchers that use AI agent integrations

The fetcher abstraction separates HOW to fetch data (fetching strategy) from
HOW to normalize data (provider responsibility), enabling flexible ticket
retrieval from multiple sources.

AgentMediatedFetcher provides the complete implementation for agent-mediated
fetching. Concrete subclasses only need to override the `name` property
(and optionally `_execute_fetch_prompt` for different timeout behaviour).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendTimeoutError
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

# Regex pattern to extract JSON-tagged markdown code blocks (```json ... ```)
_JSON_CODE_BLOCK_PATTERN = re.compile(
    r"```json\s*\n?(.*?)\n?```",
    re.DOTALL | re.IGNORECASE,
)

# Regex pattern to extract any markdown code blocks (``` ... ```)
# More permissive to catch blocks like ```jsonc, ```text, etc.
_ANY_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:[^\n]*)?\s*\n?(.*?)\n?```",
    re.DOTALL,
)

# Default timeout for agent execution (seconds)
DEFAULT_TIMEOUT_SECONDS: float = 60.0


class TicketFetcher(ABC):
    """Abstract base class for ticket fetching strategies.

    Defines the contract for all ticket fetchers. Implementations can use
    different strategies such as agent-mediated fetching (via MCP) or
    direct API calls.

    All fetchers return raw dict data - normalization to GenericTicket
    is handled by IssueTrackerProvider implementations.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable fetcher name.

        Returns:
            Display name like 'Auggie MCP Fetcher', 'Direct API Fetcher', etc.
        """
        pass

    @abstractmethod
    def supports_platform(self, platform: Platform) -> bool:
        """Check if this fetcher supports the given platform.

        Args:
            platform: The platform to check support for

        Returns:
            True if this fetcher can fetch tickets from the platform
        """
        pass

    @abstractmethod
    async def fetch_raw(self, ticket_id: str, platform: Platform) -> dict[str, Any]:
        """Fetch raw ticket data from the platform.

        This is the primary method for retrieving ticket information.
        Returns raw platform API response data as a dictionary.

        Args:
            ticket_id: The ticket identifier (e.g., 'PROJ-123', 'owner/repo#42')
            platform: The platform to fetch from

        Returns:
            Raw ticket data as returned by the platform API

        Raises:
            PlatformNotSupportedError: If this fetcher doesn't support the platform
            TicketFetchError: If fetching fails for any reason
        """
        pass


class AgentMediatedFetcher(TicketFetcher):
    """Base class for fetchers that use AI agent integrations.

    Provides the complete implementation for agent-mediated ticket fetching
    through AI backends with MCP tool integrations. Concrete subclasses
    only need to override:

    - name: Human-readable fetcher name (required)
    - _execute_fetch_prompt(): Override for different timeout behaviour (optional)

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
        return await self.fetch_raw(ticket_id, platform_enum, timeout_seconds=timeout_seconds)

    async def _execute_fetch_prompt(
        self,
        prompt: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute fetch prompt via AI backend with timeout.

        Timeout is enforced at the subprocess level (via backend -> client ->
        subprocess.run(timeout=)). asyncio.wait_for acts as a safety net
        with a generous buffer in case something else blocks.

        Subclasses may override this for different timeout behaviour (e.g.
        AuggieMediatedFetcher uses asyncio-only timeout without passing
        timeout_seconds to the backend).

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

    def _build_prompt(self, ticket_id: str, platform: Platform) -> str:
        """Build the fetch prompt for the given ticket.

        Uses the platform-specific template and formats it with
        the ticket ID.

        Args:
            ticket_id: The ticket identifier
            platform: The target platform

        Returns:
            Formatted prompt string ready to send to agent
        """
        template = self._get_prompt_template(platform)
        return template.format(ticket_id=ticket_id)

    def _parse_response(self, response: str) -> dict[str, Any]:
        """Parse agent response and extract JSON data.

        Uses a prioritized extraction strategy:
        1. First, try all ```json tagged code blocks
        2. Then, try any code blocks without json tag
        3. Finally, attempt to extract the first valid JSON object from raw text

        Args:
            response: Raw string response from agent

        Returns:
            Parsed JSON as a dictionary

        Raises:
            AgentResponseParseError: If response cannot be parsed as JSON
        """
        if not response or not response.strip():
            raise AgentResponseParseError(
                message="Empty response received from agent",
                agent_name=self.name,
                raw_response=response,
            )

        # Priority 1: Try all JSON-tagged code blocks (```json ... ```)
        json_blocks = _JSON_CODE_BLOCK_PATTERN.findall(response)
        for block in json_blocks:
            result = self._try_parse_json(block.strip())
            if result is not None:
                logger.debug("Extracted JSON from json-tagged code block")
                return result

        # Priority 2: Try any code blocks (``` ... ```)
        any_blocks = _ANY_CODE_BLOCK_PATTERN.findall(response)
        for block in any_blocks:
            result = self._try_parse_json(block.strip())
            if result is not None:
                logger.debug("Extracted JSON from untagged code block")
                return result

        # Priority 3: Try to extract the first valid JSON object from raw text
        result = self._extract_first_json_object(response)
        if result is not None:
            logger.debug("Extracted JSON from raw text")
            return result

        # Truncate response for error message if too long
        response_preview = response[:500] + "..." if len(response) > 500 else response
        raise AgentResponseParseError(
            message="Failed to parse JSON from agent response: no valid JSON object found",
            agent_name=self.name,
            raw_response=response_preview,
        )

    def _try_parse_json(self, text: str) -> dict[str, Any] | None:
        """Attempt to parse text as a JSON object.

        Args:
            text: String to parse as JSON

        Returns:
            Parsed dict if successful and result is a dict, None otherwise
        """
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            else:
                logger.warning(
                    "Parsed valid JSON but expected dict, got %s",
                    type(result).__name__,
                )
        except json.JSONDecodeError:
            pass
        return None

    def _extract_first_json_object(self, text: str) -> dict[str, Any] | None:
        """Extract the first valid JSON object from text.

        Uses a while loop to search for '{' characters and attempts to parse
        balanced brace sequences as JSON objects. If parsing fails, continues
        searching from the next '{'.

        Args:
            text: Raw text that may contain JSON

        Returns:
            Parsed dict if a valid JSON object is found, None otherwise
        """
        search_start_idx = 0

        while True:
            start_idx = text.find("{", search_start_idx)
            if start_idx == -1:
                return None

            # Try to find matching closing brace by tracking nesting depth
            depth = 0
            for i in range(start_idx, len(text)):
                char = text[i]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        # Found a potential complete JSON object
                        candidate = text[start_idx : i + 1]
                        result = self._try_parse_json(candidate)
                        if result is not None:
                            return result
                        # Parsing failed, search for next '{' after current start
                        break

            # Move search position forward to find the next '{'
            search_start_idx = start_idx + 1
