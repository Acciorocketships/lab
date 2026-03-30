"""One headless LangGraph cycle (ingest→…→update) to verify orchestrator + worker path. Exits; no TUI.

Patches the worker CLI so this finishes without Cursor/Claude (orchestrator LLM still runs for real).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# Keep in sync with scripts/run.py
PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "bench_rl_project"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"
_RESEARCH_BRIEF = """\
Implement tabular Q-learning on Gymnasium FrozenLake-v1 (4x4), compare to a random policy baseline, and document \
hyperparameters plus trained vs random mean success rate over >=100 eval episodes in SUMMARY.md. See project README \
for phased deliverables.

## Success criteria

- requirements.txt installs; training and eval entrypoints run
- SUMMARY.md reports hyperparameters and a table: trained policy vs random baseline (mean success rate, >=100 eval episodes each)
- trained policy strictly outperforms random on success rate
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from research_lab.config import RunConfig
    from research_lab import memory
    from research_lab.runner import seed_tier_a_from_run_config
    from research_lab.workflows import research_graph

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea=_RESEARCH_BRIEF,
        preferences="gymnasium + numpy only for the learner; reproducible seeds; type hints optional.",
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="z-ai/glm-4.5-air:free",
        default_worker_backend="cursor",
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    memory.ensure_memory_layout(RESEARCHER_ROOT)
    seed_tier_a_from_run_config(RESEARCHER_ROOT, cfg)

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
