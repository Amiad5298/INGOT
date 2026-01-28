"""Async context manager utilities for tests.

This module provides helper functions for creating and configuring
async context managers in test scenarios.
"""

from unittest.mock import AsyncMock, MagicMock


def make_async_context_manager(mock_service: MagicMock) -> MagicMock:
    """Configure a MagicMock to work as an async context manager.

    This is the STANDARD pattern for mocking create_ticket_service_from_config.
    The factory returns a service that supports `async with service: ...`.

    Pattern:
        mock_service.__aenter__ returns mock_service (the same object)
        mock_service.__aexit__ returns None (no exception suppression)

    Args:
        mock_service: The MagicMock to configure

    Returns:
        The same mock_service, now configured as an async CM
    """
    mock_service.__aenter__ = AsyncMock(return_value=mock_service)
    mock_service.__aexit__ = AsyncMock(return_value=None)
    return mock_service
