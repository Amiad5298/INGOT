"""Scoped conftest for CLI integration tests.

Note: CLI-specific fixtures have been moved to tests/fixtures/cli_integration.py
and are now loaded via the root conftest.py (pytest_plugins).
This is required since pytest 9.x no longer supports pytest_plugins in non-top-level conftest.
"""

# All CLI fixtures are now registered globally via tests/conftest.py
