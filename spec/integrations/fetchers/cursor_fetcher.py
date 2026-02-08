"""Cursor IDE CLI-mediated ticket fetcher using MCP integrations.

This module provides the CursorMediatedFetcher class that fetches
ticket data through the Cursor CLI's MCP tool integrations for
Jira, Linear, and GitHub.

CursorMediatedFetcher inherits all behaviour from AgentMediatedFetcher.
Only the `name` property is overridden; everything else (platform support,
prompt building, timeout handling, response parsing) lives in the base class.
"""

from __future__ import annotations

from spec.integrations.fetchers.base import DEFAULT_TIMEOUT_SECONDS, AgentMediatedFetcher


class CursorMediatedFetcher(AgentMediatedFetcher):
    """Fetches tickets through Cursor CLI's MCP integrations.

    Inherits all behaviour from AgentMediatedFetcher. This subclass
    exists only to provide the fetcher name.
    """

    @property
    def name(self) -> str:
        """Human-readable fetcher name."""
        return "Cursor MCP Fetcher"


__all__ = [
    "CursorMediatedFetcher",
    "DEFAULT_TIMEOUT_SECONDS",
]
