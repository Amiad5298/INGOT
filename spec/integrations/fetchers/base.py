"""Base classes for ticket fetching strategies.

This module defines:
- TicketFetcher: Abstract base class for all ticket fetchers
- AgentMediatedFetcher: Base class for fetchers that use AI agent integrations

The fetcher abstraction separates HOW to fetch data (fetching strategy) from
HOW to normalize data (provider responsibility), enabling flexible ticket
retrieval from multiple sources.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from ..providers.base import Platform
from .exceptions import AgentIntegrationError, PlatformNotSupportedError

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

    This class provides common functionality for fetching tickets through
    AI agents that have MCP (Model Context Protocol) integrations with
    issue tracking platforms.

    Subclasses must implement:
    - _execute_fetch_prompt(): Send prompt to agent and get response
    - _get_prompt_template(): Return platform-specific prompt template
    - supports_platform(): Check if platform is supported
    - name: Human-readable fetcher name
    """

    @abstractmethod
    async def _execute_fetch_prompt(self, prompt: str, platform: Platform) -> str:
        """Execute the fetch prompt through the agent.

        Subclasses implement this to send the prompt to their specific
        agent integration and return the raw response.

        Args:
            prompt: The structured prompt to send to the agent
            platform: The target platform (for context/tool selection)

        Returns:
            Raw string response from the agent

        Raises:
            AgentIntegrationError: If agent communication fails
        """
        pass

    @abstractmethod
    def _get_prompt_template(self, platform: Platform) -> str:
        """Get the prompt template for the given platform.

        Returns a format string with {ticket_id} placeholder.

        Args:
            platform: The platform to get template for

        Returns:
            Prompt template string with {ticket_id} placeholder
        """
        pass

    async def fetch_raw(self, ticket_id: str, platform: Platform) -> dict[str, Any]:
        """Fetch raw ticket data using agent-mediated approach.

        Builds a structured prompt, sends it to the agent, and parses
        the JSON response.

        Args:
            ticket_id: The ticket identifier
            platform: The platform to fetch from

        Returns:
            Raw ticket data as a dictionary

        Raises:
            PlatformNotSupportedError: If platform is not supported
            AgentIntegrationError: If agent communication or parsing fails
        """
        if not self.supports_platform(platform):
            raise PlatformNotSupportedError(
                platform=platform.name,
                fetcher_name=self.name,
            )

        prompt = self._build_prompt(ticket_id, platform)
        try:
            response = await self._execute_fetch_prompt(prompt, platform)
        except AgentIntegrationError:
            raise
        except Exception as e:
            raise AgentIntegrationError(
                message=f"Unexpected error during agent communication: {e}",
                agent_name=self.name,
                original_error=e,
            ) from e
        return self._parse_response(response)

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
            AgentIntegrationError: If response cannot be parsed as JSON
        """
        if not response or not response.strip():
            raise AgentIntegrationError(
                message="Empty response received from agent",
                agent_name=self.name,
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

        raise AgentIntegrationError(
            message="Failed to parse JSON from agent response: no valid JSON object found",
            agent_name=self.name,
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
