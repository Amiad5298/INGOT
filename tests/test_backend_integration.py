"""Integration tests for multi-backend system.

All tests are gated behind INGOT_INTEGRATION_TESTS=1 and require the
actual backend CLIs to be installed. These tests verify real backend
instances against the AIBackend protocol contract.

Usage:
    # Skipped by default:
    pytest tests/test_backend_integration.py -v

    # Run when enabled (requires CLIs installed):
    INGOT_INTEGRATION_TESTS=1 pytest tests/test_backend_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.factory import BackendFactory

pytestmark = pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled. Set INGOT_INTEGRATION_TESTS=1 to enable.",
)

_PLATFORMS = [
    AgentPlatform.AUGGIE,
    AgentPlatform.CLAUDE,
    AgentPlatform.CURSOR,
]


@pytest.fixture()
def backend(request: pytest.FixtureRequest) -> AIBackend:
    """Create a backend instance for the parameterized platform."""
    return BackendFactory.create(request.param)


@pytest.mark.parametrize("backend", _PLATFORMS, ids=lambda p: p.value, indirect=True)
class TestBackendProtocolCompliance:
    """Verify real backends satisfy the AIBackend protocol.

    Tests go beyond callable checks — they actually invoke safe methods
    (check_installed, detect_rate_limit, close) and verify return types.
    """

    def test_isinstance_aibackend(self, backend: AIBackend):
        assert isinstance(backend, AIBackend)

    def test_name_is_string(self, backend: AIBackend):
        assert isinstance(backend.name, str)
        assert len(backend.name) > 0

    def test_platform_matches_request(self, backend: AIBackend, request: pytest.FixtureRequest):
        assert isinstance(backend.platform, AgentPlatform)
        assert backend.platform == request.param

    def test_model_is_string(self, backend: AIBackend):
        assert isinstance(backend.model, str)

    def test_supports_parallel_is_bool(self, backend: AIBackend):
        assert isinstance(backend.supports_parallel, bool)

    def test_supports_parallel_execution_returns_bool(self, backend: AIBackend):
        result = backend.supports_parallel_execution()
        assert isinstance(result, bool)
        assert result == backend.supports_parallel

    def test_check_installed_returns_tuple(self, backend: AIBackend):
        result = backend.check_installed()
        assert isinstance(result, tuple)
        assert len(result) == 2
        installed, message = result
        assert isinstance(installed, bool)
        assert isinstance(message, str)

    def test_detect_rate_limit_returns_false_for_normal_output(self, backend: AIBackend):
        result = backend.detect_rate_limit("normal output")
        assert isinstance(result, bool)
        assert result is False

    def test_detect_rate_limit_detects_429(self, backend: AIBackend):
        assert backend.detect_rate_limit("Error 429: rate limit") is True

    def test_close_does_not_raise(self, backend: AIBackend):
        backend.close()  # Should not raise
