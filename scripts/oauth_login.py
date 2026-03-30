"""One-time browser OAuth (Authorization Code + PKCE). Edit the block below; no CLI args."""

from __future__ import annotations

import sys
from pathlib import Path

# --- Session paths (keep in sync with scripts/run.py) -----------------------------------------
PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "project_stub"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"
RESEARCH_IDEA = "OAuth login for orchestrator."
ACCEPTANCE_CRITERIA = "n/a"
PREFERENCES = "n/a"

# =============================================================================
# OpenAI Codex / ChatGPT OAuth (same flow as the `codex` CLI)
# -----------------------------------------------------------------------------
# Uses the public Codex OAuth client id and authorization parameters from
# openai/codex (login callback on localhost:1455, path /auth/callback).
# Tokens are ChatGPT subscription OAuth tokens; use them with OpenAI-compatible
# endpoints that accept that Bearer (see your OpenAI / Codex product docs).
#
# Redirect URI must match exactly what you use below (Codex default: localhost, not 127.0.0.1).
# =============================================================================

# Public client id (same as Codex CLI); no secret required for this flow.
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_CLIENT_SECRET: str | None = None

OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"

# Resolved automatically for https://auth.openai.com (see oauth_pkce.resolve_oauth_endpoints).
OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_AUTHORIZATION_ENDPOINT: str | None = None
OAUTH_TOKEN_ENDPOINT: str | None = None

OAUTH_SCOPES = (
    "openid profile email offline_access api.connectors.read api.connectors.invoke"
)
OAUTH_RESOURCE: str | None = None

# Same query flags as the Codex CLI authorize URL (openai/codex codex-rs/login/src/server.rs).
OAUTH_EXTRA_AUTHORIZE_PARAMS = {
    "id_token_add_organizations": "true",
    "codex_cli_simplified_flow": "true",
    "originator": "codex_cli_rs",
}
# -------------------------------------------------------------------------------


def main() -> None:
    """Run PKCE browser login and write token file under researcher_root/data/."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from research_lab.config import RunConfig
    from research_lab.oauth_pkce import run_browser_login_once

    if not OAUTH_CLIENT_ID:
        print("Set OAUTH_CLIENT_ID in scripts/oauth_login.py (see comments at top).")
        raise SystemExit(1)
    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea=RESEARCH_IDEA,
        acceptance_criteria=ACCEPTANCE_CRITERIA,
        preferences=PREFERENCES,
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        oauth_client_id=OAUTH_CLIENT_ID,
        oauth_client_secret=OAUTH_CLIENT_SECRET or None,
        oauth_redirect_uri=OAUTH_REDIRECT_URI,
        oauth_authorization_endpoint=OAUTH_AUTHORIZATION_ENDPOINT,
        oauth_token_endpoint=OAUTH_TOKEN_ENDPOINT,
        oauth_issuer=OAUTH_ISSUER,
        oauth_scopes=OAUTH_SCOPES,
        oauth_resource=OAUTH_RESOURCE,
        oauth_extra_authorize_params=dict(OAUTH_EXTRA_AUTHORIZE_PARAMS),
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    run_browser_login_once(cfg)


if __name__ == "__main__":
    main()
