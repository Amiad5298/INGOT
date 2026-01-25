"""Pytest configuration for integration tests.

This module provides:
- --live flag for enabling live API tests
- Fixtures for DirectAPIFetcher with real credentials
- Skip markers for missing credentials
"""

import os

import pytest


def pytest_addoption(parser):
    """Add custom command-line options for integration tests."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live integration tests (requires API credentials)",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "live: mark test as requiring live API access (use --live to run)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip live tests unless --live flag is provided."""
    if config.getoption("--live"):
        # --live given in cli: do not skip live tests
        return

    skip_live = pytest.mark.skip(reason="Live tests require --live flag")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


# Environment variable helpers for credential checking
def has_jira_credentials() -> bool:
    """Check if Jira credentials are configured."""
    return bool(os.getenv("FALLBACK_JIRA_URL"))


def has_github_credentials() -> bool:
    """Check if GitHub credentials are configured."""
    return bool(os.getenv("FALLBACK_GITHUB_TOKEN"))


def has_azure_devops_credentials() -> bool:
    """Check if Azure DevOps credentials are configured."""
    return bool(os.getenv("FALLBACK_AZURE_DEVOPS_ORGANIZATION"))


def has_trello_credentials() -> bool:
    """Check if Trello credentials are configured."""
    return bool(os.getenv("FALLBACK_TRELLO_API_KEY"))
