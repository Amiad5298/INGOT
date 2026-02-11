"""Tests for ingot.integrations.backends.factory module."""

import threading

import pytest

from ingot.config.fetch_config import AgentPlatform, ConfigValidationError
from ingot.integrations.backends.base import AIBackend
from ingot.integrations.backends.errors import BackendNotInstalledError
from ingot.integrations.backends.factory import BackendFactory


class TestBackendFactoryCreate:
    def test_create_auggie_backend_from_enum(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_from_string(self):
        backend = BackendFactory.create("auggie")
        assert backend.name == "Auggie"
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_auggie_backend_case_insensitive(self):
        backend = BackendFactory.create("AUGGIE")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_with_model_parameter(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="claude-3-opus")
        # Model is stored internally (implementation detail)
        assert backend is not None

    def test_create_returns_aibackend_instance(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert isinstance(backend, AIBackend)


class TestBackendFactoryUnimplementedPlatforms:
    def test_create_claude_backend(self):
        backend = BackendFactory.create(AgentPlatform.CLAUDE)
        assert backend.name == "Claude Code"
        assert backend.platform == AgentPlatform.CLAUDE
        assert isinstance(backend, AIBackend)

    def test_create_cursor_backend(self):
        backend = BackendFactory.create(AgentPlatform.CURSOR)
        assert backend.name == "Cursor"
        assert backend.platform == AgentPlatform.CURSOR
        assert isinstance(backend, AIBackend)

    def test_create_aider_backend(self):
        backend = BackendFactory.create(AgentPlatform.AIDER)
        assert backend.name == "Aider"
        assert backend.platform == AgentPlatform.AIDER
        assert isinstance(backend, AIBackend)

    def test_create_gemini_backend(self):
        backend = BackendFactory.create(AgentPlatform.GEMINI)
        assert backend.name == "Gemini CLI"
        assert backend.platform == AgentPlatform.GEMINI
        assert isinstance(backend, AIBackend)

    def test_create_codex_backend(self):
        backend = BackendFactory.create(AgentPlatform.CODEX)
        assert backend.name == "Codex"
        assert backend.platform == AgentPlatform.CODEX
        assert isinstance(backend, AIBackend)

    def test_create_manual_raises_value_error(self):
        with pytest.raises(ValueError, match="Manual mode does not use an AI backend"):
            BackendFactory.create(AgentPlatform.MANUAL)


class TestBackendFactoryVerifyInstalled:
    def test_verify_installed_true_with_installed_cli(self, mocker):
        mock_check = mocker.patch(
            "ingot.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(True, "Auggie CLI v1.0.0"),
        )
        backend = BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        assert backend is not None
        mock_check.assert_called_once()

    def test_verify_installed_true_raises_when_cli_missing(self, mocker):
        mock_check = mocker.patch(
            "ingot.integrations.backends.auggie.AuggieBackend.check_installed",
            return_value=(False, "Auggie CLI not found. Install from https://..."),
        )
        with pytest.raises(BackendNotInstalledError):
            BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=True)
        mock_check.assert_called_once()

    def test_verify_installed_false_skips_check(self, mocker):
        mock_check = mocker.patch(
            "ingot.integrations.backends.auggie.AuggieBackend.check_installed",
        )
        BackendFactory.create(AgentPlatform.AUGGIE, verify_installed=False)
        mock_check.assert_not_called()


class TestBackendFactoryInvalidInput:
    def test_create_unknown_platform_string_raises(self):
        with pytest.raises(ConfigValidationError):
            BackendFactory.create("unknown_platform")


class TestBackendFactoryStringNormalization:
    def test_create_strips_whitespace_from_string(self):
        backend = BackendFactory.create("  auggie  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_handles_mixed_case_with_whitespace(self):
        backend = BackendFactory.create("  AuGgIe  ")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_empty_string_returns_default(self):
        backend = BackendFactory.create("")
        assert backend.platform == AgentPlatform.AUGGIE

    def test_create_whitespace_only_string_returns_default(self):
        backend = BackendFactory.create("   ")
        assert backend.platform == AgentPlatform.AUGGIE


class TestBackendFactoryThreadSafety:
    def test_create_is_thread_safe(self):
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
    def test_backend_factory_exported_from_package(self):
        from ingot.integrations.backends import BackendFactory as ExportedFactory

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
        import ast
        from pathlib import Path

        factory_path = Path("ingot/integrations/backends/factory.py")
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
            "ingot.integrations.backends.auggie",
            "ingot.integrations.backends.claude",
            "ingot.integrations.backends.cursor",
            "ingot.integrations.backends.aider",
            "ingot.integrations.backends.gemini",
            "ingot.integrations.backends.codex",
        ]
        for backend_module in backend_modules:
            assert backend_module not in toplevel_imports, (
                f"Backend module {backend_module} should not be imported at top level. "
                f"Use lazy import inside create() method."
            )
