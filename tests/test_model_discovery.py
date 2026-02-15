"""Tests for ingot.integrations.backends.model_discovery module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from ingot.integrations.backends.model_discovery import (
    fetch_anthropic_models,
    fetch_gemini_models,
    fetch_openai_models,
)

# ---------------------------------------------------------------------------
# fetch_anthropic_models
# ---------------------------------------------------------------------------


class TestFetchAnthropicModels:
    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "claude-sonnet-4", "display_name": "Claude Sonnet 4"},
                {"id": "claude-opus-4", "display_name": "Claude Opus 4"},
                {"id": "not-claude", "display_name": "Other Model"},
            ]
        }
        mock_get.return_value = mock_resp

        models = fetch_anthropic_models("test-key")

        assert len(models) == 2
        assert models[0].id == "claude-opus-4"
        assert models[1].id == "claude-sonnet-4"

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_timeout_returns_empty(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timeout")

        models = fetch_anthropic_models("test-key")

        assert models == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_http_401_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_resp

        models = fetch_anthropic_models("bad-key")

        assert models == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_invalid_json_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_resp

        models = fetch_anthropic_models("test-key")

        assert models == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_uses_correct_headers(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp

        fetch_anthropic_models("my-api-key")

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["x-api-key"] == "my-api-key"
        assert headers["anthropic-version"] == "2023-06-01"


# ---------------------------------------------------------------------------
# fetch_openai_models
# ---------------------------------------------------------------------------


class TestFetchOpenAIModels:
    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_success_filters_correctly(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "gpt-4.1"},
                {"id": "o3"},
                {"id": "o4-mini"},
                {"id": "gpt-4o-audio-preview"},  # excluded: audio
                {"id": "text-embedding-3-large"},  # excluded: not matching prefix
                {"id": "dall-e-3"},  # excluded: not matching prefix
                {"id": "gpt-4-turbo"},
            ]
        }
        mock_get.return_value = mock_resp

        models = fetch_openai_models("test-key")

        model_ids = [m.id for m in models]
        assert "gpt-4.1" in model_ids
        assert "o3" in model_ids
        assert "o4-mini" in model_ids
        assert "gpt-4-turbo" in model_ids
        assert "gpt-4o-audio-preview" not in model_ids
        assert "text-embedding-3-large" not in model_ids

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_timeout_returns_empty(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timeout")

        assert fetch_openai_models("test-key") == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_http_403_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_resp

        assert fetch_openai_models("bad-key") == []


# ---------------------------------------------------------------------------
# fetch_gemini_models
# ---------------------------------------------------------------------------


class TestFetchGeminiModels:
    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_success_filters_by_generate_content(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {
                    "name": "models/gemini-2.5-pro",
                    "displayName": "Gemini 2.5 Pro",
                    "description": "Latest pro model",
                    "supportedGenerationMethods": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/embedding-001",
                    "displayName": "Embedding",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }
        mock_get.return_value = mock_resp

        models = fetch_gemini_models("test-key")

        assert len(models) == 1
        assert models[0].id == "gemini-2.5-pro"
        assert models[0].name == "Gemini 2.5 Pro"
        assert models[0].description == "Latest pro model"

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_strips_models_prefix(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {
                    "name": "models/gemini-2.0-flash",
                    "displayName": "Gemini 2.0 Flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }
        mock_get.return_value = mock_resp

        models = fetch_gemini_models("test-key")

        assert models[0].id == "gemini-2.0-flash"

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_timeout_returns_empty(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timeout")

        assert fetch_gemini_models("test-key") == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_invalid_json_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_resp

        assert fetch_gemini_models("test-key") == []

    @patch("ingot.integrations.backends.model_discovery.httpx.get")
    def test_passes_key_as_query_param(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_get.return_value = mock_resp

        fetch_gemini_models("my-gem-key")

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["key"] == "my-gem-key"
