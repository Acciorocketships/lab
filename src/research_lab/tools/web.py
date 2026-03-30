"""Web fetch and lightweight search hooks (deterministic HTTP)."""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx


def fetch_url(url: str, timeout: float = 30.0) -> dict[str, Any]:
    """GET url and return status + truncated text for notes pipeline."""
    try:
        r = httpx.get(url, follow_redirects=True, timeout=timeout)
        text = r.text[:200_000]
        return {"ok": True, "status": r.status_code, "url": str(r.url), "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def duckduckgo_html_query(query: str, timeout: float = 20.0) -> dict[str, Any]:
    """Fetch DuckDuckGo HTML results page (no API key). For research notes only."""
    q = urllib.parse.quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={q}"
    return fetch_url(url, timeout=timeout)
