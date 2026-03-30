"""Runtime configuration loaded by run scripts or the `lab` CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research_lab.global_config import GlobalConfig, ProjectConfig


@dataclass(frozen=True)
class RunConfig:
    """All knobs for a researcher session."""

    researcher_root: Path
    project_dir: Path
    research_idea: str
    preferences: str
    orchestrator_backend: str  # openai | openrouter | local
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    default_worker_backend: str  # claude | cursor
    oauth_client_id: str | None = "app_EMoamEEZ73f0CkXaXp7hrann"
    oauth_client_secret: str | None = None
    oauth_redirect_uri: str = "http://localhost:1455/auth/callback"
    oauth_authorization_endpoint: str | None = None
    oauth_token_endpoint: str | None = None
    oauth_issuer: str | None = "https://auth.openai.com"
    oauth_scopes: str = (
        "openid profile email offline_access api.connectors.read api.connectors.invoke"
    )
    oauth_resource: str | None = None
    oauth_token_path: Path | None = None
    oauth_extra_authorize_params: dict[str, str] = field(default_factory=dict)
    openrouter_api_key: str | None = None

    @classmethod
    def from_configs(
        cls,
        gcfg: GlobalConfig,
        pcfg: ProjectConfig,
        project_dir: Path,
    ) -> RunConfig:
        """Build a RunConfig by merging global and project-level settings."""
        from research_lab.global_config import GLOBAL_OAUTH_PATH, project_researcher_root

        researcher_root = project_researcher_root(project_dir)
        api_key: str | None = gcfg.api_key or None
        openrouter_key: str | None = None
        if gcfg.provider == "openrouter" and api_key:
            openrouter_key = api_key
            api_key = None

        return cls(
            researcher_root=researcher_root,
            project_dir=project_dir,
            research_idea=pcfg.research_idea,
            preferences=pcfg.preferences or gcfg.code_style,
            orchestrator_backend=gcfg.provider,
            openai_api_key=api_key if gcfg.provider != "openrouter" else None,
            openai_base_url=gcfg.base_url or None,
            openai_model=gcfg.model_name,
            default_worker_backend=gcfg.worker_backend,
            oauth_client_id=gcfg.oauth_client_id or None,
            oauth_token_path=GLOBAL_OAUTH_PATH,
            openrouter_api_key=openrouter_key,
        )


def researcher_root_for_project(project_dir: Path) -> Path:
    """Kept for import compatibility; prefer ``global_config.project_researcher_root``."""
    return project_dir / ".airesearcher"
