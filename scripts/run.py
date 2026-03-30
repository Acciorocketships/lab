"""Launch the researcher: config lives here (no CLI args). Edit paths and strings below."""

from __future__ import annotations

import sys
from pathlib import Path

# --- config overrides ---------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "project_stub"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"
RESEARCH_IDEA = "Toy: confirm the lab loop runs end-to-end on a trivial task."
ACCEPTANCE_CRITERIA = "One cycle completes; orchestrator returns a valid worker; heartbeat updates."
PREFERENCES = "Keep code simple and documented."
# Orchestrator LLM: orchestrator_backend = "openai" | "openrouter" | "local"
# - openai: OPENAI_API_KEY and/or Codex OAuth (scripts/oauth_login.py); keep PROJECT_DIR / RESEARCHER_ROOT in sync across scripts.
# - openrouter: OPENROUTER_API_KEY or pass openrouter_api_key=...; optional openai_base_url override.
# - local: e.g. Ollama — set openai_base_url or rely on LOCAL_LLM_BASE_URL; key via OPENAI_API_KEY / LOCAL_LLM_API_KEY or default "ollama".
# ------------------------------------------------------------------------------


def main() -> None:
    """Add src to path, init layout, start loop."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from research_lab.config import RunConfig
    from research_lab.loop import start_session

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea=RESEARCH_IDEA,
        acceptance_criteria=ACCEPTANCE_CRITERIA,
        preferences=PREFERENCES,
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="z-ai/glm-4.5-air:free",
        default_worker_backend="cursor",
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    # Seed Tier A from config
    state = RESEARCHER_ROOT / "data" / "runtime" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "research_idea.md").write_text(f"# Research idea\n\n{cfg.research_idea}\n", encoding="utf-8")
    (state / "acceptance_criteria.md").write_text(f"# Acceptance criteria\n\n{cfg.acceptance_criteria}\n", encoding="utf-8")
    (state / "preferences.md").write_text(f"# Preferences\n\n{cfg.preferences}\n", encoding="utf-8")
    (state / "project_brief.md").write_text(
        f"# Project\n\nImplementation directory: `{cfg.project_dir}`\n", encoding="utf-8"
    )
    start_session(db_path, cfg.researcher_root, cfg.project_dir, cfg, src_root=repo_root / "src")


if __name__ == "__main__":
    main()
