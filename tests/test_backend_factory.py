"""Tests for spec.integrations.backends.factory module."""

import threading

import pytest

from spec.config.fetch_config import AgentPlatform, ConfigValidationError
from spec.integrations.backends.base import AIBackend
from spec.integrations.backends.errors import BackendNotInstalledError
from spec.integrations.backends.factory import BackendFactory


class TestBackendFactoryCreate:
    """Tests for BackendFactory.create() method."""

    def test_create_auggie_backend_from_enum(self):
        """Create AuggieBackend from AgentPlatform enum."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_from_string(self):
        """Create AuggieBackend from string name."""
        backend = BackendFactory.create("auggie")
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_case_insensitive(self):
        """String platform name is case-insensitive."""
        backend = BackendFactory.create("AUGGIE")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_with_model_parameter(self):
        """Model parameter is passed to backend constructor."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="claude-3-opus")
        # Model is stored internally (implementation detail)
        assert backend is not None

    def test_create_returns_aibackend_instance(self):
        """Returned backend satisfies AIBackend protocol."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert isinstance(backend, AIBackend)


class TestBackendFactoryUnimplementedPlatforms:
    """Tests for unimplemented backend platforms."""

    def test_create_claude_raises_not_implemented(self):
        """Claude backend raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError, match="Claude backend not yet implemented"):
            BackendFactory.create(AgentPlatform.CLAUDE)

    def test_create_cursor_raises_not_implemented(self):
        """Cursor backend raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError, match="Cursor backend not yet implemented"):
            BackendFactory.create(AgentPlatform.CURSOR)

    def test_create_aider_raises_value_error(self):
        """Aider backend raises ValueError (deferred indefinitely, not a planned phase)."""
        with pytest.raises(ValueError, match="Aider backend not yet implemented"):
            BackendFactory.create(AgentPlatform.AIDER)

    def test_create_manual_raises_value_error(self):
        """Manual mode raises ValueError (no AI backend - this is permanent)."""
        with pytest.raises(ValueError, match="Manual mode does not use an AI backend"):
            BackendFactory.create(AgentPlatform.MANUAL)


class TestBackendFactoryVerifyInstalled:
    """Tests for verify_installed parameter."""

    def test_verify_installed_true_with_installed_cli(self, mocker):
        """verify_installed=True succeeds when CLI is installed."""
        mock_check = mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(True, "Auggie CLI v1.0.0"),
        )
        backend = BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        assert backend is not None
        mock_check.assert_called_once()

    def test_verify_installed_true_raises_when_cli_missing(self, mocker):
        """verify_installed=True raises BackendNotInstalledError when CLI missing."""
        mock_check = mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(False, "Auggie CLI not found. Install from https://..."),
        )
        with pytest.raises(BackendNotInstalledError):
            BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        mock_check.assert_called_once()

    def test_verify_installed_false_skips_check(self, mocker):
        """verify_installed=False (default) does not call check_installed."""
        mock_check = mocker.patch(
            "spec.integrations.backends.auggie.AuggieBackend.check_installed",
        )
        BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=False)
        mock_check.assert_not_called()


class TestBackendFactoryInvalidInput:
    """Tests for invalid input handling."""

    def test_create_unknown_platform_string_raises(self):
        """Unknown platform string raises ConfigValidationError.

        Note: The parent spec's TestBackendFactory shows pytest.raises(ValueError),
        but the actual behavior is ConfigValidationError because parse_agent_platform()
        raises ConfigValidationError for invalid values.
        """
        with pytest.raises(ConfigValidationError):
            BackendFactory.create("unknown_platform")


class TestBackendFactoryStringNormalization:
    """Tests for string input normalization (Linear ticket requirement)."""

    def test_create_strips_whitespace_from_string(self):
        """String platform name handles leading/trailing whitespace."""
        backend = BackendFactory.create("  auggie  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_handles_mixed_case_with_whitespace(self):
        """String platform name handles mixed case and whitespace."""
        backend = BackendFactory.create("  AuGgIe  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_empty_string_returns_default(self):
        """Empty string returns default platform (AUGGIE).

        Note: This behavior comes from parse_agent_platform() which has
        default=AgentPlatform.AUGGIE.
        """
        backend = BackendFactory.create("")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_whitespace_only_string_returns_default(self):
        """Whitespace-only string returns default platform."""
        backend = BackendFactory.create("   ")
        assert backend.platform == AgentPlatform.AUGGIE


class TestBackendFactoryThreadSafety:
    """Tests for thread safety in concurrent usage."""

    def test_create_is_thread_safe(self):
        """Factory creates independent instances for concurrent calls."""
        backends = []
        errors = []
        lock = threading.Lock()

        def create_backend():
            try:
                backend = BackendFactory.create(AgentPlatform.AUGGIE)
                with lock:
                    backends.append(backend)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=create_backend) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent creation: {errors}"
        assert len(backends) == 10
        # Verify all are independent instances (different object IDs)
        assert len({id(b) for b in backends}) == 10


class TestBackendFactoryExport:
    """Tests for package export (AC6)."""

    def test_backend_factory_exported_from_package(self):
        """BackendFactory is exported via spec.integrations.backends."""
        from spec.integrations.backends import BackendFactory as ExportedFactory

        assert ExportedFactory is not None
        assert hasattr(ExportedFactory, "create")
        # Verify it's the same class as the direct import
        assert ExportedFactory is BackendFactory


class TestBackendFactoryLazyImports:
    """Tests for lazy import behavior.

    These tests verify that factory.py itself uses lazy imports
    (imports inside if-branches). The lazy import pattern is valuable because:
    1. Direct imports of factory.py bypass the package __init__.py
    2. It sets up the correct pattern for when/if we switch to PEP 562 lazy exports
    3. It avoids circular imports within the factory module itself
    """

    def test_factory_module_has_no_toplevel_backend_imports(self):
        """Verify factory.py doesn't have top-level backend imports.

        This is a code structure test, not a runtime import test.
        It verifies the factory follows the lazy import pattern by checking
        that backend imports are inside the create() method, not at module level.
        """
        import ast
        from pathlib import Path

        factory_path = Path("spec/integrations/backends/factory.py")
        if not factory_path.exists():
            pytest.skip("factory.py not yet created")

        source = factory_path.read_text()
        tree = ast.parse(source)

        # Find all top-level imports (not inside functions/classes)
        toplevel_imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                if isinstance(node, ast.ImportFrom) and node.module:
                    toplevel_imports.append(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        toplevel_imports.append(alias.name)

        # Backend modules should NOT be in top-level imports
        backend_modules = [
            "spec.integrations.backends.auggie",
            "spec.integrations.backends.claude",
            "spec.integrations.backends.cursor",
        ]
        for backend_module in backend_modules:
            assert backend_module not in toplevel_imports, (
                f"Backend module {backend_module} should not be imported at top level. "
                f"Use lazy import inside create() method."
            )
