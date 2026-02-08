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

Timeout Note:
    Unlike ClaudeMediatedFetcher and CursorMediatedFetcher which pass
    timeout_seconds to the backend subprocess, AuggieMediatedFetcher
    uses asyncio-only timeout (the backend does not receive a timeout
    parameter). This is the original Auggie behaviour preserved for
    backwards compatibility.
"""

from __future__ import annotations

import asyncio
import logging

from spec.integrations.fetchers.base import DEFAULT_TIMEOUT_SECONDS, AgentMediatedFetcher
from spec.integrations.fetchers.exceptions import (
    AgentFetchError,
)
from spec.integrations.providers.base import Platform

logger = logging.getLogger(__name__)


class AuggieMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through AI backend's MCP integrations.

    Inherits most behaviour from AgentMediatedFetcher. This subclass
    overrides `_execute_fetch_prompt` to use asyncio-only timeout
    (without passing timeout_seconds to the backend subprocess).

    Note:
        Despite the name "AuggieMediatedFetcher", this fetcher can work
        with any AIBackend implementation. The name is preserved for
        backwards compatibility.
    """

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Auggie MCP Fetcher"

    async def _execute_fetch_prompt(
        self,
        prompt: str,
        platform: Platform,
        timeout_seconds: float | None = None,
    ) -> str:
        """Execute fetch prompt via AI backend with asyncio-only timeout.

        Unlike the base class implementation, this does NOT pass
        timeout_seconds to the backend subprocess. The timeout is
        implemented purely at the asyncio level.

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

        if not result:
            raise AgentFetchError(
                message="Backend returned empty response",
                agent_name=self.name,
            )

        return result


__all__ = [
    "AuggieMediatedFetcher",
    "DEFAULT_TIMEOUT_SECONDS",
]
