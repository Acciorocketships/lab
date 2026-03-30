"""Thin OpenAI-compatible chat wrapper for orchestrator (OpenAI / OpenRouter / local)."""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from research_lab.config import RunConfig
from research_lab.oauth_pkce import resolve_openai_bearer

T = TypeVar("T", bound=BaseModel)


def _client(base_url: str | None, api_key: str | None) -> OpenAI:
    """Build OpenAI client; api_key may be env OPENAI_API_KEY."""
    key = api_key or os.environ.get("OPENAI_API_KEY") or ""
    # Avoid hanging forever on slow providers; OpenRouter + many models ignore `parse` / stall on it.
    return OpenAI(api_key=key, base_url=base_url or None, timeout=120.0)


def _use_openai_parse_api(base_url: str | None) -> bool:
    """`beta.chat.completions.parse` is for OpenAI-native APIs; OpenRouter often hangs or errors."""
    if not base_url:
        return True
    return "openrouter.ai" not in base_url.lower()


def resolve_llm_api_key(cfg: RunConfig) -> str | None:
    """API key / bearer for the active orchestrator backend."""
    backend = (cfg.orchestrator_backend or "openai").lower()
    if backend == "openai":
        return resolve_openai_bearer(cfg)
    if backend == "openrouter":
        if cfg.openrouter_api_key:
            return cfg.openrouter_api_key
        return os.environ.get("OPENROUTER_API_KEY")
    if backend == "local":
        if cfg.openai_api_key:
            return cfg.openai_api_key
        if os.environ.get("OPENAI_API_KEY"):
            return os.environ["OPENAI_API_KEY"]
        return os.environ.get("LOCAL_LLM_API_KEY") or "ollama"
    return resolve_openai_bearer(cfg)


def resolve_llm_base_url(cfg: RunConfig) -> str | None:
    """OpenAI-compatible base URL (e.g. api.openai.com, OpenRouter, Ollama /v1)."""
    backend = (cfg.orchestrator_backend or "openai").lower()
    if backend == "openai":
        return cfg.openai_base_url
    if backend == "openrouter":
        return cfg.openai_base_url or "https://openrouter.ai/api/v1"
    if backend == "local":
        if cfg.openai_base_url:
            return cfg.openai_base_url
        return (
            os.environ.get("LOCAL_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "http://127.0.0.1:11434/v1"
        )
    return cfg.openai_base_url


def generate(
    messages: list[dict[str, str]],
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    response_format: type[T] | None = None,
) -> T | str:
    """Call chat completions; if response_format set, parse JSON into model."""
    client = _client(base_url, api_key)
    if response_format is not None:
        if _use_openai_parse_api(base_url):
            try:
                completion = client.beta.chat.completions.parse(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    response_format=response_format,
                )
                msg = completion.choices[0].message
                parsed = msg.parsed
                if parsed is not None:
                    return parsed
            except Exception:
                pass
        raw = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
        )
        text = raw.choices[0].message.content or "{}"
        return response_format.model_validate_json(text)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
    )
    return completion.choices[0].message.content or ""


def generate_json_dict(
    messages: list[dict[str, str]],
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Request JSON object response (no pydantic parse)."""
    client = _client(base_url, api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content or "{}"
    return json.loads(raw)
