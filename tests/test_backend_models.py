"""Tests for BackendModel dataclass and backend list_models() methods."""

from __future__ import annotations

from unittest.mock import patch

from ingot.integrations.backends.base import BackendModel, BaseBackend


class TestBackendModel:
    def test_create_with_defaults(self):
        model = BackendModel(id="claude-3", name="Claude 3")
        assert model.id == "claude-3"
        assert model.name == "Claude 3"
        assert model.description == ""

    def test_create_with_description(self):
        model = BackendModel(id="gpt-4", name="GPT-4", description="Latest GPT model")
        assert model.description == "Latest GPT model"

    def test_equality(self):
        m1 = BackendModel(id="x", name="X")
        m2 = BackendModel(id="x", name="X")
        assert m1 == m2


class TestBaseBackendListModels:
    def test_returns_empty_list(self):
        """BaseBackend.list_models() returns [] by default."""

        class ConcreteBackend(BaseBackend):
            @property
            def name(self):
                return "Test"

            @property
            def platform(self):
                from ingot.config.fetch_config import AgentPlatform

                return AgentPlatform.AUGGIE

            def run_with_callback(self, *a, **kw):
                pass

            def run_print_with_output(self, *a, **kw):
                pass

            def run_print_quiet(self, *a, **kw):
                pass

            def run_streaming(self, *a, **kw):
                pass

            def check_installed(self):
                return True, "ok"

            def detect_rate_limit(self, output):
                return False

        backend = ConcreteBackend()
        assert backend.list_models() == []


class TestClaudeBackendListModels:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_returns_fallback(self):
        from ingot.integrations.backends.claude import ClaudeBackend

        backend = ClaudeBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert all(isinstance(m, BackendModel) for m in models)
        assert any("claude" in m.id for m in models)

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("ingot.integrations.backends.model_discovery.fetch_anthropic_models")
    def test_api_success_returns_dynamic(self, mock_fetch):
        from ingot.integrations.backends.claude import ClaudeBackend

        mock_fetch.return_value = [BackendModel(id="claude-new", name="Claude New")]
        backend = ClaudeBackend()
        models = backend.list_models()
        assert len(models) == 1
        assert models[0].id == "claude-new"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("ingot.integrations.backends.model_discovery.fetch_anthropic_models")
    def test_api_failure_returns_fallback(self, mock_fetch):
        from ingot.integrations.backends.claude import ClaudeBackend

        mock_fetch.return_value = []
        backend = ClaudeBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert any("claude" in m.id for m in models)


class TestCursorBackendListModels:
    def test_returns_hardcoded_models(self):
        from ingot.integrations.backends.cursor import CursorBackend

        backend = CursorBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert all(isinstance(m, BackendModel) for m in models)


class TestAiderBackendListModels:
    def test_returns_hardcoded_models(self):
        from ingot.integrations.backends.aider import AiderBackend

        backend = AiderBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert all(isinstance(m, BackendModel) for m in models)


class TestGeminiBackendListModels:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_returns_fallback(self):
        from ingot.integrations.backends.gemini import GeminiBackend

        backend = GeminiBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert any("gemini" in m.id for m in models)

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    @patch("ingot.integrations.backends.model_discovery.fetch_gemini_models")
    def test_api_success_returns_dynamic(self, mock_fetch):
        from ingot.integrations.backends.gemini import GeminiBackend

        mock_fetch.return_value = [BackendModel(id="gemini-new", name="Gemini New")]
        backend = GeminiBackend()
        models = backend.list_models()
        assert len(models) == 1
        assert models[0].id == "gemini-new"


class TestCodexBackendListModels:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_returns_fallback(self):
        from ingot.integrations.backends.codex import CodexBackend

        backend = CodexBackend()
        models = backend.list_models()
        assert len(models) >= 1
        assert any(m.id in ("o3", "o4-mini", "gpt-4.1") for m in models)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("ingot.integrations.backends.model_discovery.fetch_openai_models")
    def test_api_success_returns_dynamic(self, mock_fetch):
        from ingot.integrations.backends.codex import CodexBackend

        mock_fetch.return_value = [BackendModel(id="o3", name="o3")]
        backend = CodexBackend()
        models = backend.list_models()
        assert len(models) == 1
        assert models[0].id == "o3"


class TestAuggieBackendListModels:
    @patch("ingot.integrations.backends.auggie.auggie_list_models")
    def test_wraps_auggie_models(self, mock_list):
        from ingot.integrations.auggie import AuggieModel
        from ingot.integrations.backends.auggie import AuggieBackend

        mock_list.return_value = [
            AuggieModel(name="Model A", id="model-a", description="Desc A"),
        ]
        backend = AuggieBackend()
        models = backend.list_models()
        assert len(models) == 1
        assert models[0].id == "model-a"
        assert models[0].name == "Model A"
        assert isinstance(models[0], BackendModel)

    @patch("ingot.integrations.backends.auggie.auggie_list_models")
    def test_empty_when_cli_returns_nothing(self, mock_list):
        from ingot.integrations.backends.auggie import AuggieBackend

        mock_list.return_value = []
        backend = AuggieBackend()
        assert backend.list_models() == []
