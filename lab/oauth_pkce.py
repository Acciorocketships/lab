"""OAuth 2.0 Authorization Code + PKCE (S256) with browser redirect — not device-code flow.

Primary path: **OpenAI Codex / ChatGPT** OAuth at ``https://auth.openai.com`` (same client id and
authorize parameters as the Codex CLI). For other IdPs (e.g. Google), set ``oauth_issuer`` and
scopes/redirect to match that provider.

Run :func:`run_browser_login_once` (e.g. from scripts/oauth_login.py) to store tokens;
:func:`resolve_openai_bearer` refreshes and returns an access token for ``llm``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from lab.config import RunConfig


def _b64url(data: bytes) -> str:
    """Base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE (Codex-compatible: 64 random bytes, URL-safe base64url no pad)."""
    raw = secrets.token_bytes(64)
    verifier = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = _b64url(digest)
    return verifier, challenge


def oauth_token_file(cfg: RunConfig) -> Path:
    """Where access/refresh tokens are stored (chmod 600 recommended)."""
    if cfg.oauth_token_path is not None:
        return cfg.oauth_token_path
    return cfg.researcher_root / "oauth_openai_tokens.json"


def fetch_oidc_discovery(issuer: str) -> dict[str, Any]:
    """Load OpenID discovery document to read authorization and token endpoints."""
    base = issuer.rstrip("/")
    url = f"{base}/.well-known/openid-configuration"
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    return r.json()


def resolve_oauth_endpoints(cfg: RunConfig) -> tuple[str, str]:
    """Return (authorization_endpoint, token_endpoint) from config or issuer discovery."""
    if cfg.oauth_authorization_endpoint and cfg.oauth_token_endpoint:
        return cfg.oauth_authorization_endpoint, cfg.oauth_token_endpoint
    if not cfg.oauth_issuer:
        raise ValueError("Set oauth_issuer or both oauth_authorization_endpoint and oauth_token_endpoint")
    issuer = cfg.oauth_issuer.rstrip("/")
    # Codex uses https://auth.openai.com/oauth/{authorize,token}. OIDC discovery at the same host
    # points at different paths (e.g. /authorize vs /oauth/authorize), so we never discover here.
    if issuer in ("https://auth.openai.com", "http://auth.openai.com"):
        return "https://auth.openai.com/oauth/authorize", "https://auth.openai.com/oauth/token"
    doc = fetch_oidc_discovery(cfg.oauth_issuer)
    auth_ep = doc.get("authorization_endpoint")
    token_ep = doc.get("token_endpoint")
    if not auth_ep or not token_ep:
        raise ValueError("OIDC discovery missing authorization_endpoint or token_endpoint")
    return str(auth_ep), str(token_ep)


def _token_refresh_uses_json(token_endpoint: str) -> bool:
    """ChatGPT/Codex refresh uses JSON POST (openai/codex login); code exchange stays form-urlencoded."""
    p = urlparse(token_endpoint)
    return p.netloc == "auth.openai.com" and p.path.rstrip("/") == "/oauth/token"


def _token_exchange_uses_openai_api_key(token_endpoint: str) -> bool:
    """Codex performs a token exchange from id_token -> openai-api-key before API calls."""
    p = urlparse(token_endpoint)
    return p.netloc == "auth.openai.com" and p.path.rstrip("/") == "/oauth/token"


def exchange_id_token_for_api_key(
    cfg: RunConfig,
    id_token: str,
    *,
    oauth_access_token: str | None = None,
) -> str:
    """Exchange a ChatGPT/Codex id_token for the bearer accepted by api.openai.com.

    ``auth.openai.com`` expects JSON bodies for some grants (same as refresh). We try JSON first,
    then optional ``Authorization: Bearer`` with the session token from the code exchange, then
    form-urlencoded for other IdPs or legacy behavior.
    """
    _auth_ep, token_ep = resolve_oauth_endpoints(cfg)
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": cfg.oauth_client_id or "",
        "requested_token": "openai-api-key",
        "subject_token": id_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
    }
    p = urlparse(token_ep)
    openai_host = p.netloc == "auth.openai.com" and p.path.rstrip("/") == "/oauth/token"

    def _access_from_response(r: httpx.Response) -> str | None:
        if not r.is_success:
            return None
        data = r.json()
        at = data.get("access_token")
        return str(at) if at else None

    if openai_host:
        r = httpx.post(
            token_ep,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60.0,
        )
        out = _access_from_response(r)
        if out:
            return out
        if oauth_access_token:
            r = httpx.post(
                token_ep,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {oauth_access_token}",
                },
                timeout=60.0,
            )
            out = _access_from_response(r)
            if out:
                return out

    r = httpx.post(
        token_ep,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Token exchange response missing access_token")
    return str(access_token)


def _parse_redirect(redirect_uri: str) -> tuple[str, int, str]:
    """Return host, port, path from redirect URI (http only for local dev)."""
    p = urlparse(redirect_uri)
    if p.scheme not in ("http", "https"):
        raise ValueError("redirect_uri must be http or https")
    if p.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("For local login use 127.0.0.1 or localhost in redirect_uri")
    port = p.port or (443 if p.scheme == "https" else 80)
    path = p.path or "/"
    return p.hostname, port, path


class _OAuthHandler(BaseHTTPRequestHandler):
    """One-shot handler: captures ?code= and ?state= then stops."""

    result: dict[str, str | None] = {"code": None, "state": None, "error": None}
    expected_state: str = ""
    path_needle: str = "/"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        """Handle redirect from IdP."""
        parsed = urlparse(self.path)
        got = parsed.path.rstrip("/") or "/"
        want = _OAuthHandler.path_needle.rstrip("/") or "/"
        if got != want:
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        err = qs.get("error", [None])[0]
        if err:
            _OAuthHandler.result["error"] = err
        else:
            _OAuthHandler.result["code"] = qs.get("code", [None])[0]
            _OAuthHandler.result["state"] = qs.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if _OAuthHandler.result.get("error"):
            self.wfile.write(
                b"<html><body><p>OAuth error. You can close this tab.</p></body></html>"
            )
        else:
            self.wfile.write(
                b"<html><body><p>Sign-in complete. You can close this tab and return to the terminal.</p></body></html>"
            )


def run_browser_login_once(cfg: RunConfig) -> Path:
    """Open browser to IdP, receive authorization code on localhost, exchange for tokens, save file.

    Call once per machine (or when refresh token expires). Uses Authorization Code + PKCE only.
    """
    if not cfg.oauth_client_id:
        raise ValueError("oauth_client_id is required")
    auth_ep, token_ep = resolve_oauth_endpoints(cfg)
    hostname, port, path = _parse_redirect(cfg.oauth_redirect_uri)
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    _OAuthHandler.path_needle = path.rstrip("/") or "/"
    if not _OAuthHandler.path_needle.startswith("/"):
        _OAuthHandler.path_needle = "/" + _OAuthHandler.path_needle
    _OAuthHandler.result = {"code": None, "state": None, "error": None}
    _OAuthHandler.expected_state = state

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": cfg.oauth_client_id,
        "redirect_uri": cfg.oauth_redirect_uri,
        "scope": cfg.oauth_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if cfg.oauth_resource:
        params["resource"] = cfg.oauth_resource
    for k, v in cfg.oauth_extra_authorize_params.items():
        params[k] = v
    auth_url = f"{auth_ep}?{urlencode(params)}"

    bind_host = "127.0.0.1" if hostname in ("localhost", "127.0.0.1") else hostname
    server = HTTPServer((bind_host, port), _OAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print("Opening browser for sign-in…")
        webbrowser.open(auth_url)
        deadline = time.time() + 300.0
        while time.time() < deadline:
            if _OAuthHandler.result.get("error"):
                raise RuntimeError(f"OAuth error: {_OAuthHandler.result['error']}")
            if _OAuthHandler.result.get("code"):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("No OAuth redirect received within 300s")
        if _OAuthHandler.result.get("state") != state:
            raise RuntimeError("OAuth state mismatch")
        code = _OAuthHandler.result.get("code")
        if not code:
            raise RuntimeError("No authorization code")
    finally:
        server.shutdown()
        thread.join(timeout=2.0)

    body: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.oauth_redirect_uri,
        "client_id": cfg.oauth_client_id,
        "code_verifier": code_verifier,
    }
    if cfg.oauth_client_secret:
        body["client_secret"] = cfg.oauth_client_secret
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = httpx.post(token_ep, data=body, headers=headers, timeout=60.0)
    r.raise_for_status()
    tok = r.json()
    path_out = oauth_token_file(cfg)
    path_out.parent.mkdir(parents=True, exist_ok=True)
    expires_in = float(tok.get("expires_in", 3600))
    oauth_at = str(tok["access_token"])
    api_bearer = oauth_at
    if tok.get("id_token") and _token_exchange_uses_openai_api_key(token_ep):
        try:
            api_bearer = exchange_id_token_for_api_key(
                cfg, str(tok["id_token"]), oauth_access_token=oauth_at
            )
        except Exception:
            print(
                "Note: id_token → API key exchange failed; using OAuth access token from "
                "sign-in. If Chat Completions return 401, set OPENAI_API_KEY or open an issue."
            )
    record: dict[str, Any] = {
        "access_token": api_bearer,
        "refresh_token": tok.get("refresh_token"),
        "token_type": tok.get("token_type", "Bearer"),
        "expires_at": time.time() + expires_in - 60.0,
    }
    if tok.get("id_token"):
        record["id_token"] = tok["id_token"]
    if tok.get("access_token"):
        record["oauth_access_token"] = tok["access_token"]
    path_out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        path_out.chmod(0o600)
    except OSError:
        pass
    print(f"Tokens saved to {path_out}")
    return path_out


def refresh_access_token(cfg: RunConfig, refresh_token: str) -> dict[str, Any]:
    """Use refresh_token at token_endpoint (form for most IdPs; JSON for auth.openai.com/Codex)."""
    _auth_ep, token_ep = resolve_oauth_endpoints(cfg)
    if _token_refresh_uses_json(token_ep):
        payload = {
            "client_id": cfg.oauth_client_id or "",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        r = httpx.post(
            token_ep,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60.0,
        )
    else:
        body: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": cfg.oauth_client_id or "",
        }
        if cfg.oauth_client_secret:
            body["client_secret"] = cfg.oauth_client_secret
        r = httpx.post(
            token_ep,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60.0,
        )
    r.raise_for_status()
    return r.json()


def load_and_refresh_token_file(cfg: RunConfig) -> str | None:
    """Return a valid access_token, refreshing on disk when possible."""
    path = oauth_token_file(cfg)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    _auth_ep, token_ep = resolve_oauth_endpoints(cfg)
    access = data.get("access_token")
    expires_at = float(data.get("expires_at", 0))
    if access and time.time() < expires_at:
        if data.get("id_token") and _token_exchange_uses_openai_api_key(token_ep) and not data.get("oauth_access_token"):
            try:
                data["oauth_access_token"] = access
                data["access_token"] = exchange_id_token_for_api_key(
                    cfg, str(data["id_token"]), oauth_access_token=access
                )
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
                return str(data["access_token"])
            except Exception:
                return str(access)
        return str(access)
    refresh = data.get("refresh_token")
    if not refresh or not cfg.oauth_client_id:
        return access
    try:
        tok = refresh_access_token(cfg, str(refresh))
    except Exception:
        return access
    expires_in = float(tok.get("expires_in", 3600))
    if tok.get("access_token"):
        data["oauth_access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        data["refresh_token"] = tok["refresh_token"]
    if tok.get("id_token"):
        data["id_token"] = tok["id_token"]
    if data.get("id_token") and _token_exchange_uses_openai_api_key(token_ep):
        try:
            data["access_token"] = exchange_id_token_for_api_key(
                cfg,
                str(data["id_token"]),
                oauth_access_token=data.get("oauth_access_token"),
            )
        except Exception:
            return access
    elif tok.get("access_token"):
        data["access_token"] = tok["access_token"]
    data["expires_at"] = time.time() + expires_in - 60.0
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return str(data["access_token"])


def resolve_openai_bearer(cfg: RunConfig) -> str | None:
    """Prefer explicit API key, then env var, then OAuth token file (with refresh)."""
    if cfg.openai_api_key:
        return cfg.openai_api_key
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    if not oauth_token_file(cfg).exists():
        return None
    return load_and_refresh_token_file(cfg)
