"""Backend unit tests: factory, rate-limit detection, and compatibility matrix.

Tests:
- BackendFactory.create() for all platforms
- Per-backend rate limit detection (Auggie, Claude, Cursor)
- Compatibility matrix: get_platform_support()
"""

from __future__ import annotations

import pytest

from ingot.config.compatibility import get_platform_support
from ingot.config.fetch_config import AgentPlatform, ConfigValidationError
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.factory import BackendFactory
from ingot.integrations.providers.base import Platform


class TestBackendFactory:
    def test_create_auggie_backend(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.platform == AgentPlatform.AUGGIE
        assert backend.name == "Auggie"
        assert isinstance(backend, AIBackend)

    def test_create_claude_backend(self):
        backend = BackendFactory.create(AgentPlatform.CLAUDE)
        assert backend.platform == AgentPlatform.CLAUDE
        assert backend.name == "Claude Code"
        assert isinstance(backend, AIBackend)

    def test_create_cursor_backend(self):
        backend = BackendFactory.create(AgentPlatform.CURSOR)
        assert backend.platform == AgentPlatform.CURSOR
        assert backend.name == "Cursor"
        assert isinstance(backend, AIBackend)

    def test_create_from_string(self):
        backend = BackendFactory.create("auggie")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_from_string_claude(self):
        backend = BackendFactory.create("claude")
        assert backend.platform == AgentPlatform.CLAUDE

    def test_create_from_string_cursor(self):
        backend = BackendFactory.create("cursor")
        assert backend.platform == AgentPlatform.CURSOR

    def test_create_unknown_backend_raises(self):
        with pytest.raises(ConfigValidationError, match="Invalid AI backend"):
            BackendFactory.create("unknown")

    def test_manual_backend_raises(self):
        with pytest.raises(ValueError, match="Manual mode"):
            BackendFactory.create(AgentPlatform.MANUAL)

    def test_aider_backend_creates(self):
        backend = BackendFactory.create(AgentPlatform.AIDER)
        assert backend.name == "Aider"
        assert backend.platform == AgentPlatform.AIDER

    def test_create_with_model(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="gpt-4")
        assert isinstance(backend, AIBackend)

    def test_create_returns_independent_instances(self):
        b1 = BackendFactory.create(AgentPlatform.AUGGIE)
        b2 = BackendFactory.create(AgentPlatform.AUGGIE)
        assert b1 is not b2


_RATE_LIMIT_PLATFORMS = [
    AgentPlatform.AUGGIE,
    AgentPlatform.CLAUDE,
    AgentPlatform.CURSOR,
]


@pytest.mark.parametrize("platform", _RATE_LIMIT_PLATFORMS, ids=lambda p: p.value)
class TestRateLimitDetection:
    """Tests for per-backend rate limit detection.

    All backends share matches_common_rate_limit() so 429 and keyword
    detection should be consistent. Backend-specific keywords (e.g.
    Cursor's 'quota exceeded') are tested in the specific methods below.
    """

    def test_detects_429(self, platform: AgentPlatform):
        backend = BackendFactory.create(platform)
        assert backend.detect_rate_limit("Error 429: Too many requests") is True

    def test_detects_rate_limit_keyword(self, platform: AgentPlatform):
        backend = BackendFactory.create(platform)
        assert backend.detect_rate_limit("rate limit exceeded") is True

    def test_normal_output_not_rate_limited(self, platform: AgentPlatform):
        backend = BackendFactory.create(platform)
        assert backend.detect_rate_limit("Task completed successfully") is False


class TestRateLimitDetectionBackendSpecific:
    def test_cursor_detects_quota_exceeded(self):
        backend = BackendFactory.create(AgentPlatform.CURSOR)
        assert backend.detect_rate_limit("quota exceeded") is True


class TestCompatibilityMatrix:
    """Tests for the backend-platform MCP support compatibility matrix.

    These tests mirror the current state of MCP_SUPPORT and API_SUPPORT
    in spec/config/compatibility.py. If those dicts change, update these
    tests accordingly.
    """

    def test_auggie_supports_jira_mcp(self):
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.JIRA)
        assert supported is True
        assert mechanism == "mcp"

    def test_auggie_supports_linear_mcp(self):
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.LINEAR)
        assert supported is True
        assert mechanism == "mcp"

    def test_auggie_supports_github_mcp(self):
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.GITHUB)
        assert supported is True
        assert mechanism == "mcp"

    def test_auggie_supports_trello_api(self):
        supported, mechanism = get_platform_support(AgentPlatform.AUGGIE, Platform.TRELLO)
        assert supported is True
        assert mechanism == "api"

    def test_claude_supports_jira_mcp(self):
        supported, mechanism = get_platform_support(AgentPlatform.CLAUDE, Platform.JIRA)
        assert supported is True
        assert mechanism == "mcp"

    def test_cursor_supports_linear_mcp(self):
        supported, mechanism = get_platform_support(AgentPlatform.CURSOR, Platform.LINEAR)
        assert supported is True
        assert mechanism == "mcp"

    def test_manual_no_mcp_support(self):
        supported, mechanism = get_platform_support(AgentPlatform.MANUAL, Platform.JIRA)
        assert supported is True
        assert mechanism == "api"

    def test_aider_no_mcp_support(self):
        supported, mechanism = get_platform_support(AgentPlatform.AIDER, Platform.LINEAR)
        assert supported is True
        assert mechanism == "api"

    def test_aider_trello_api_fallback(self):
        supported, mechanism = get_platform_support(AgentPlatform.AIDER, Platform.TRELLO)
        assert supported is True
        assert mechanism == "api"

    def test_azure_devops_api_for_all_backends(self):
        for backend in AgentPlatform:
            supported, mechanism = get_platform_support(backend, Platform.AZURE_DEVOPS)
            assert supported is True
            assert mechanism == "api"

    def test_monday_api_for_all_backends(self):
        for backend in AgentPlatform:
            supported, mechanism = get_platform_support(backend, Platform.MONDAY)
            assert supported is True
            assert mechanism == "api"
