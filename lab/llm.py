"""Thin OpenAI-compatible chat wrapper for orchestrator (OpenAI / OpenRouter / local)."""

from __future__ import annotations

import logging
import os
import string
import time
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from lab.config import RunConfig
from lab.oauth_pkce import oauth_token_file, resolve_openai_bearer

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)

_JSON_RETRIES = 3
_RETRY_BACKOFF_SEC = 1.0
_JSON_STRING_ESCAPE_CHARS = set('"\\/bfnrt')
_HEX_DIGITS = set(string.hexdigits)


def _agent_debug_log(*_args: object, **_kwargs: object) -> None:
    """No-op compatibility shim.

    Debug-mode instrumentation used this name during development; a partially
    reverted or cached ``lab.llm`` module can still reference it. Keeping the
    symbol defined avoids ``NameError`` without changing runtime behavior.
    """
    return None


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


def _openrouter_completion_kwargs(base_url: str | None) -> dict[str, int]:
    """OpenRouter reserves against max output; omitting max_tokens can default very high (e.g. 65535) and return 402 when credits cannot cover that reservation."""
    if base_url and "openrouter.ai" in base_url.lower():
        return {"max_tokens": 8192}
    return {}


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


def describe_orchestrator_credential_source(cfg: RunConfig) -> str:
    """Human-readable label for where :func:`resolve_llm_api_key` will take credentials (no secrets)."""
    backend = (cfg.orchestrator_backend or "openai").lower()
    if backend == "openai":
        if cfg.openai_api_key:
            return "OpenAI API key from global config ([auth] api_key)"
        if os.environ.get("OPENAI_API_KEY"):
            return "OpenAI API key from OPENAI_API_KEY"
        token_path = oauth_token_file(cfg)
        if token_path.is_file():
            return f"OpenAI OAuth token file ({token_path})"
        return (
            "No OpenAI credentials (set [auth] api_key, OPENAI_API_KEY, or run OAuth login)"
        )
    if backend == "openrouter":
        if cfg.openrouter_api_key:
            return "OpenRouter API key from global config ([auth] api_key)"
        if os.environ.get("OPENROUTER_API_KEY"):
            return "OpenRouter API key from OPENROUTER_API_KEY"
        return "No OpenRouter API key (set [auth] api_key or OPENROUTER_API_KEY)"
    if backend == "local":
        if cfg.openai_api_key:
            return "API key from global config ([auth] api_key)"
        if os.environ.get("OPENAI_API_KEY"):
            return "OPENAI_API_KEY"
        if os.environ.get("LOCAL_LLM_API_KEY"):
            return "LOCAL_LLM_API_KEY"
        return 'Default local placeholder key ("ollama")'
    if cfg.openai_api_key:
        return "OpenAI API key from global config ([auth] api_key)"
    if os.environ.get("OPENAI_API_KEY"):
        return "OpenAI API key from OPENAI_API_KEY"
    token_path = oauth_token_file(cfg)
    if token_path.is_file():
        return f"OpenAI OAuth token file ({token_path})"
    return "No credentials matched for orchestrator backend"


def _repair_invalid_json_string_escapes(text: str) -> str:
    r"""Best-effort fix for invalid backslashes inside JSON string values.

    Some providers return JSON objects whose string fields contain raw LaTeX or
    Windows-like paths such as ``\tilde`` or ``\Users``. Those are invalid JSON
    escapes and make strict parsing fail even when the rest of the object is
    well-formed. This pass only modifies backslashes that appear *inside* JSON
    strings and are not part of a valid JSON escape sequence.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        if ch == '"':
            out.append(ch)
            in_string = False
            i += 1
            continue

        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        if i + 1 >= n:
            out.append("\\\\")
            i += 1
            continue

        nxt = text[i + 1]
        if nxt in _JSON_STRING_ESCAPE_CHARS:
            out.append("\\")
            out.append(nxt)
            i += 2
            continue
        if nxt == "u":
            hex_seq = text[i + 2 : i + 6]
            if len(hex_seq) == 4 and all(c in _HEX_DIGITS for c in hex_seq):
                out.append("\\")
                out.append("u")
                out.extend(hex_seq)
                i += 6
                continue

        out.append("\\\\")
        i += 1

    return "".join(out)


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
                    **_openrouter_completion_kwargs(base_url),
                )
                msg = completion.choices[0].message
                parsed = msg.parsed
                if parsed is not None:
                    return parsed
            except Exception:
                pass
        last_err: Exception | None = None
        for attempt in range(_JSON_RETRIES):
            raw = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                **_openrouter_completion_kwargs(base_url),
            )
            text = raw.choices[0].message.content or "{}"
            try:
                return response_format.model_validate_json(text)
            except (ValidationError, ValueError) as exc:
                repaired = _repair_invalid_json_string_escapes(text)
                if repaired != text:
                    try:
                        parsed = response_format.model_validate_json(repaired)
                        _log.warning(
                            "LLM returned JSON with invalid string escapes; repaired and accepted on attempt %d/%d",
                            attempt + 1,
                            _JSON_RETRIES,
                        )
                        return parsed
                    except (ValidationError, ValueError):
                        pass
                last_err = exc
                _log.warning(
                    "LLM returned invalid JSON (attempt %d/%d, %d chars): %s",
                    attempt + 1, _JSON_RETRIES, len(text), exc,
                )
                if attempt < _JSON_RETRIES - 1:
                    time.sleep(_RETRY_BACKOFF_SEC * (attempt + 1))
        raise last_err  # type: ignore[misc]
    completion = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        **_openrouter_completion_kwargs(base_url),
    )
    return completion.choices[0].message.content or ""
