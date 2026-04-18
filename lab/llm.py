"""Thin OpenAI-compatible chat wrapper for orchestrator (OpenAI / OpenRouter / local)."""

from __future__ import annotations

import logging
import os
import re
import string
import sys
import time
from typing import Any, TypeVar

from openai import APIStatusError, OpenAI
from pydantic import BaseModel, ValidationError

from lab.config import RunConfig
from lab.oauth_pkce import oauth_token_file, resolve_openai_bearer

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)

_JSON_RETRIES = 3
_RETRY_BACKOFF_SEC = 1.0
_JSON_STRING_ESCAPE_CHARS = set('"\\/bfnrt')
_HEX_DIGITS = set(string.hexdigits)

_WEB_ERR_BODY_MAX = 6000


def _format_llm_failure_for_terminal(exc: BaseException) -> str:
    """Human-readable, provider-agnostic summary for stderr (no secrets)."""
    lines: list[str] = [f"{type(exc).__name__}: {exc}"]
    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int):
        lines.append(f"HTTP status: {sc}")
    resp = getattr(exc, "response", None)
    if resp is not None:
        rsc = getattr(resp, "status_code", None)
        if isinstance(rsc, int) and rsc != sc:
            lines.append(f"Response HTTP status: {rsc}")
    body = getattr(exc, "body", None)
    if body is not None:
        b = body if isinstance(body, str) else repr(body)
        b = b.strip()
        if b:
            if len(b) > _WEB_ERR_BODY_MAX:
                b = b[:_WEB_ERR_BODY_MAX] + "… [truncated]"
            lines.append(f"Response body: {b}")
    cause = exc.__cause__
    if cause is not None:
        lines.append(f"Caused by: {type(cause).__name__}: {cause}")
    if isinstance(sc, int) and sc == 402 and "openrouter.ai" in str(exc).lower():
        lines.append(
            "Hint: OpenRouter 402 can reflect per-key limits or credit reservation; "
            "balances shown on the website may update more slowly than the API quota."
        )
    return "\n".join(lines)


def _print_llm_failure_to_terminal(exc: BaseException) -> None:
    """Emit failure details to stderr (foreground CLI: terminal; scheduler child: log file via loop redirect)."""
    text = _format_llm_failure_for_terminal(exc)
    print("\n[lab] LLM request failed:\n" + text + "\n", file=sys.stderr, flush=True)
    _log.error("LLM request failed:\n%s", text)


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


_OPENROUTER_DEFAULT_MAX_TOKENS = 4096
_OPENROUTER_402_MARGIN = 128
_OPENROUTER_BUDGET_RETRIES = 6


def _openrouter_max_tokens_setting() -> int:
    """Upper bound for completion tokens on OpenRouter (provider reserves against this)."""
    raw = (os.environ.get("OPENROUTER_MAX_TOKENS") or "").strip()
    if raw.isdigit():
        return max(256, min(int(raw), 128_000))
    return _OPENROUTER_DEFAULT_MAX_TOKENS


def _openrouter_completion_kwargs(base_url: str | None) -> dict[str, int]:
    """OpenRouter reserves against max output; omitting max_tokens can default very high (e.g. 65535) and return 402 when credits cannot cover that reservation."""
    if base_url and "openrouter.ai" in base_url.lower():
        return {"max_tokens": _openrouter_max_tokens_setting()}
    return {}


def _openrouter_affordable_max_from_402(exc: BaseException) -> int | None:
    """Parse OpenRouter 402 for completion reservation ``can only afford N`` (not prompt-length limits)."""
    if not isinstance(exc, APIStatusError) or getattr(exc, "status_code", None) != 402:
        return None
    s = str(exc)
    if re.search(r"prompt\s+tokens?\s+", s, re.I):
        return None
    m = re.search(r"can only afford (\d+)", s)
    if not m:
        return None
    return max(256, int(m.group(1)) - _OPENROUTER_402_MARGIN)


def _is_openrouter_base_url(base_url: str | None) -> bool:
    return bool(base_url and "openrouter.ai" in base_url.lower())


def _chat_completions_create_resilient(
    client: OpenAI,
    base_url: str | None,
    *,
    model: str,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> Any:
    """``chat.completions.create`` with OpenRouter 402 → lower ``max_tokens`` and retry."""
    or_kw: dict[str, int] = dict(_openrouter_completion_kwargs(base_url))
    merged: dict[str, Any] = {**kwargs, **or_kw}
    last_exc: APIStatusError | None = None
    for attempt in range(_OPENROUTER_BUDGET_RETRIES):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **merged,
            )
        except APIStatusError as exc:
            last_exc = exc
            cap = _openrouter_affordable_max_from_402(exc)
            if not _is_openrouter_base_url(base_url) or cap is None or "max_tokens" not in merged:
                raise exc
            cur = int(merged["max_tokens"])
            if cap >= cur:
                raise exc
            merged["max_tokens"] = cap
            _log.warning(
                "OpenRouter 402 (credits vs max_tokens); retrying with max_tokens=%s (attempt %d/%d)",
                cap,
                attempt + 1,
                _OPENROUTER_BUDGET_RETRIES,
            )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OpenRouter budget retries exhausted")  # pragma: no cover


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
    try:
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
                raw = _chat_completions_create_resilient(
                    client,
                    base_url,
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
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
        completion = _chat_completions_create_resilient(
            client,
            base_url,
            model=model,
            messages=messages,
        )
        return completion.choices[0].message.content or ""
    except Exception as exc:
        _print_llm_failure_to_terminal(exc)
        raise
