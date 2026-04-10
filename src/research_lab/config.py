"""Runtime configuration loaded by run scripts or the `lab` CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research_lab.global_config import GlobalConfig


@dataclass(frozen=True)
class RunConfig:
    """All knobs for a researcher session.

    Research brief and preferences are stored in Tier A markdown files
    (``.airesearcher/state/research_idea.md`` and ``preferences.md``) rather than here.
    Agents read those files directly; ``RunConfig`` carries only infrastructure settings.
    """

    researcher_root: Path
    project_dir: Path
    orchestrator_backend: str  # openai | openrouter | local
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    default_worker_backend: str  # claude | cursor
    cursor_agent_model: str
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
    # Context limits are optional. ``None`` means "do not truncate in app code";
    # the upstream model/provider is then responsible for enforcing its own limit.
    orchestrator_input_max_chars: int | None = None
    orchestrator_prev_summary_max_chars: int | None = None
    orchestrator_last_worker_max_chars: int | None = None
    orchestrator_tier_file_max_chars: int | None = None
    orchestrator_branch_memory_max_chars: int | None = None
    worker_packet_max_chars: int | None = None

    @classmethod
    def from_configs(
        cls,
        gcfg: GlobalConfig,
        project_dir: Path,
    ) -> RunConfig:
        """Build a RunConfig from global config.

        Model/auth/worker fields come from global config.  Research brief and preferences
        live in Tier A markdown (``state/research_idea.md``, ``state/preferences.md``) and
        are not stored here — agents read those files directly.
        """
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
            orchestrator_backend=gcfg.provider,
            openai_api_key=api_key if gcfg.provider != "openrouter" else None,
            openai_base_url=gcfg.base_url or None,
            openai_model=gcfg.model_name,
            default_worker_backend=gcfg.worker_backend,
            cursor_agent_model=gcfg.cursor_agent_model,
            oauth_client_id=gcfg.oauth_client_id or None,
            oauth_token_path=GLOBAL_OAUTH_PATH,
            openrouter_api_key=openrouter_key,
        )


def researcher_root_for_project(project_dir: Path) -> Path:
    """Kept for import compatibility; prefer ``global_config.project_researcher_root``."""
    return project_dir / ".airesearcher"
