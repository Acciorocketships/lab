"""One headless LangGraph cycle for the active bench project (orchestrator real; worker mocked).

PROJECT_DIR must match scripts/run.py. Exits after one cycle; no TUI, no Cursor/Claude CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

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
    from research_lab.config import RunConfig
    from research_lab import memory
    from research_lab.runner import seed_tier_a_from_run_config
    from research_lab.workflows import research_graph

    project_dir = _REPO_ROOT / "data" / "bench_rl_project"
    researcher_root = project_dir / ".airesearcher"
    cfg = RunConfig(
        researcher_root=researcher_root,
        project_dir=project_dir,
        research_idea=_RESEARCH_BRIEF,
        preferences=(
            "gymnasium + numpy only for the learner; reproducible seeds; type hints optional."
        ),
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="google/gemini-2.5-flash-lite",
        default_worker_backend="cursor",
    )
    researcher_root.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = researcher_root / "data" / "runtime.db"
    memory.ensure_memory_layout(researcher_root)
    seed_tier_a_from_run_config(researcher_root, cfg)

    app = research_graph.build_graph(
        cfg,
        db_path=db_path,
        researcher_root=researcher_root,
        project_dir=project_dir,
    )
    st = research_graph._state_from_db(db_path)

    def _fake_worker(packet: str, *, backend: str, project_cwd: Path, **kwargs):  # type: ignore[no-untyped-def]
        return {"ok": True, "parsed": "run_bench_smoke: worker skipped (mock); packet received."}

    with patch("research_lab.agents.base.run_worker", side_effect=_fake_worker):
        out = app.invoke(st)
    print("run_bench_smoke: one cycle OK")
    print(
        json.dumps(
            {k: out.get(k) for k in ("cycle_count", "current_worker", "roadmap_step", "last_action_summary")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
