"""Runtime configuration loaded by run scripts (no CLI args)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RunConfig:
    """All knobs for a researcher session; set in scripts/run.py only."""

    researcher_root: Path
    project_dir: Path
    research_idea: str
    acceptance_criteria: str
    preferences: str
    orchestrator_backend: str  # openai | openrouter | local
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    default_worker_backend: str  # claude | cursor
    # OAuth2 Authorization Code + PKCE (browser redirect to localhost). No device-code flow.
    # Public Codex OAuth client id (same as the Codex CLI); override if you use another IdP.
    oauth_client_id: str | None = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_client_secret: str | None = None
    # OpenAI Codex / ChatGPT OAuth uses localhost:1455 and /auth/callback (same as the Codex CLI).
    oauth_redirect_uri: str = "http://localhost:1455/auth/callback"
    oauth_authorization_endpoint: str | None = None
    oauth_token_endpoint: str | None = None
    # Set to https://auth.openai.com for Codex; we resolve /oauth/authorize and /oauth/token (not OIDC discovery).
    oauth_issuer: str | None = "https://auth.openai.com"
    oauth_scopes: str = (
        "openid profile email offline_access api.connectors.read api.connectors.invoke"
    )
    oauth_resource: str | None = None
    oauth_token_path: Path | None = None
    # Merged into the authorize URL (e.g. Google: access_type=offline, prompt=consent).
    oauth_extra_authorize_params: dict[str, str] = field(default_factory=dict)
    # When orchestrator_backend == "openrouter"; else env OPENROUTER_API_KEY.
    openrouter_api_key: str | None = None


def researcher_root_for_project(project_dir: Path) -> Path:
    """Internal researcher state lives next to the project under study (not under the tool repo root)."""
    return project_dir / ".airesearcher"
