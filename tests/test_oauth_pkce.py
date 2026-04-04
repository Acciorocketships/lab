"""OAuth PKCE helpers (offline)."""

import base64
import hashlib
from pathlib import Path

from research_lab.config import RunConfig
from research_lab.oauth_pkce import (
    generate_pkce_pair,
    load_and_refresh_token_file,
    oauth_token_file,
    resolve_oauth_endpoints,
    resolve_openai_bearer,
)


def test_pkce_s256_roundtrip() -> None:
    """code_challenge matches SHA256(code_verifier) per PKCE."""
    v, c = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode("utf-8")).digest()).rstrip(b"=").decode("ascii")
    assert c == expected


def test_resolve_prefers_explicit_api_key(tmp_path: Path) -> None:
    """Explicit key in config wins over env."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path,
        research_idea="x",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key="sk-test",
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    assert resolve_openai_bearer(cfg) == "sk-test"
    assert oauth_token_file(cfg) == tmp_path / "data" / "oauth_openai_tokens.json"


def test_auth_openai_issuer_uses_codex_endpoints_not_oidc_discovery(tmp_path: Path) -> None:
    """auth.openai.com must use /oauth/authorize and /oauth/token (Codex), not OIDC discovery paths."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path,
        research_idea="x",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        oauth_issuer="https://auth.openai.com",
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
    )
    auth_ep, token_ep = resolve_oauth_endpoints(cfg)
    assert auth_ep == "https://auth.openai.com/oauth/authorize"
    assert token_ep == "https://auth.openai.com/oauth/token"


def test_existing_codex_token_file_is_upgraded_to_api_bearer(tmp_path: Path, monkeypatch) -> None:
    """Old token files that stored the raw OAuth access token should be upgraded in place."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path,
        research_idea="x",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        oauth_issuer="https://auth.openai.com",
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
    )
    token_path = oauth_token_file(cfg)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        """{
  "access_token": "oauth-access-token",
  "refresh_token": "refresh-token",
  "id_token": "id-token",
  "expires_at": 9999999999
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "research_lab.oauth_pkce.exchange_id_token_for_api_key",
        lambda cfg, id_token: "exchanged-api-bearer",
    )

    assert load_and_refresh_token_file(cfg) == "exchanged-api-bearer"
    saved = token_path.read_text(encoding="utf-8")
    assert "exchanged-api-bearer" in saved
    assert "oauth-access-token" in saved
