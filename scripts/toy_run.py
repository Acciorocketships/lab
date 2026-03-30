"""One headless LangGraph cycle (ingest→…→update) to verify orchestrator + worker path. Exits; no TUI.

Patches the worker CLI so this finishes without Cursor/Claude (orchestrator LLM still runs for real).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# Keep in sync with scripts/run.py
PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "project_stub"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from research_lab.config import RunConfig
    from research_lab import memory
    from research_lab.workflows import research_graph

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea="Toy: confirm the lab loop runs end-to-end on a trivial task.",
        acceptance_criteria="One cycle completes; orchestrator returns a valid worker; heartbeat updates.",
        preferences="Keep code simple and documented.",
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="z-ai/glm-4.5-air:free",
        default_worker_backend="cursor",
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    state = RESEARCHER_ROOT / "data" / "runtime" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "research_idea.md").write_text(f"# Research idea\n\n{cfg.research_idea}\n", encoding="utf-8")
    (state / "acceptance_criteria.md").write_text(f"# Acceptance criteria\n\n{cfg.acceptance_criteria}\n", encoding="utf-8")
    (state / "preferences.md").write_text(f"# Preferences\n\n{cfg.preferences}\n", encoding="utf-8")
    (state / "project_brief.md").write_text(
        f"# Project\n\nImplementation directory: `{cfg.project_dir}`\n", encoding="utf-8"
    )
    memory.ensure_memory_layout(RESEARCHER_ROOT)

    app = research_graph.build_graph(
        cfg,
        db_path=db_path,
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
    )
    st = research_graph._state_from_db(db_path)

    def _fake_worker(packet: str, *, backend: str, project_cwd: Path, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "parsed": "toy_run: worker skipped (mock)"}

    with patch("research_lab.agents.base.run_worker", side_effect=_fake_worker):
        out = app.invoke(st)
    print("toy_run: one cycle OK")
    print(json.dumps({k: out.get(k) for k in ("cycle_count", "current_worker", "roadmap_step", "last_action_summary")}, indent=2))


if __name__ == "__main__":
    main()
