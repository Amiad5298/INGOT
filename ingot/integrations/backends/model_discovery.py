"""Shared model discovery via provider REST APIs.

Each function accepts an explicit API key parameter and returns a list of
BackendModel instances. Functions never raise — they return [] on any error
(network, auth, timeout, invalid JSON).
"""

from __future__ import annotations

import logging

import httpx

from ingot.integrations.backends.base import BackendModel

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0  # seconds


def fetch_anthropic_models(api_key: str) -> list[BackendModel]:
    """Fetch available models from the Anthropic API.

    GET https://api.anthropic.com/v1/models
    Filters to claude-* models.

    Args:
        api_key: Anthropic API key (x-api-key header).

    Returns:
        List of BackendModel instances, or [] on any error.
    """
    try:
        resp = httpx.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        models: list[BackendModel] = []
        for item in data.get("data", []):
            model_id = item.get("id", "")
            if model_id.startswith("claude-"):
                display_name = item.get("display_name", model_id)
                models.append(BackendModel(id=model_id, name=display_name))

        return sorted(models, key=lambda m: m.id)
    except Exception:
        logger.debug("Failed to fetch Anthropic models", exc_info=True)
        return []


def fetch_openai_models(api_key: str) -> list[BackendModel]:
    """Fetch available models from the OpenAI API.

    GET https://api.openai.com/v1/models
    Filters to gpt-4*, o1*, o3*, o4* (excludes embeddings/tts/whisper/dall-e).

    Args:
        api_key: OpenAI API key (Bearer token).

    Returns:
        List of BackendModel instances, or [] on any error.
    """
    _INCLUDE_PREFIXES = ("gpt-4", "o1", "o3", "o4")
    _EXCLUDE_KEYWORDS = ("embedding", "tts", "whisper", "dall-e", "audio", "realtime")

    try:
        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        models: list[BackendModel] = []
        for item in data.get("data", []):
            model_id = item.get("id", "")
            if not any(model_id.startswith(p) for p in _INCLUDE_PREFIXES):
                continue
            if any(kw in model_id.lower() for kw in _EXCLUDE_KEYWORDS):
                continue
            models.append(BackendModel(id=model_id, name=model_id))

        return sorted(models, key=lambda m: m.id)
    except Exception:
        logger.debug("Failed to fetch OpenAI models", exc_info=True)
        return []


def fetch_gemini_models(api_key: str) -> list[BackendModel]:
    """Fetch available models from the Gemini API.

    GET https://generativelanguage.googleapis.com/v1beta/models?key=$KEY
    Filters to models with 'generateContent' in supportedGenerationMethods.

    Args:
        api_key: Google API key (query parameter).

    Returns:
        List of BackendModel instances, or [] on any error.
    """
    try:
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        models: list[BackendModel] = []
        for item in data.get("models", []):
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            # Model name is like "models/gemini-2.5-pro" — strip prefix
            full_name = item.get("name", "")
            model_id = full_name.removeprefix("models/")
            display_name = item.get("displayName", model_id)
            description = item.get("description", "")
            models.append(BackendModel(id=model_id, name=display_name, description=description))

        return sorted(models, key=lambda m: m.id)
    except Exception:
        logger.debug("Failed to fetch Gemini models", exc_info=True)
        return []


__all__ = [
    "fetch_anthropic_models",
    "fetch_openai_models",
    "fetch_gemini_models",
]
