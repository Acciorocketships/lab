"""Bench / dev launcher — same core as ``lab`` via :func:`research_lab.runner.run_console_session`.

Prefer ``pip install .`` then ``lab setup`` / ``lab init`` / ``lab`` for normal use.
This script builds a :class:`~research_lab.config.RunConfig` explicitly (no TOML) for the bench project.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "bench_rl_project"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"
RESEARCH_BRIEF = """\
Implement tabular Q-learning on Gymnasium FrozenLake-v1 (4x4), compare to a random policy baseline, and document \
hyperparameters plus trained vs random mean success rate over >=100 eval episodes in SUMMARY.md. See project README \
for phased deliverables.

## Success criteria

- requirements.txt installs; training and eval entrypoints run
- SUMMARY.md reports hyperparameters and a table: trained policy vs random baseline (mean success rate, >=100 eval episodes each)
- trained policy strictly outperforms random on success rate
"""
PREFERENCES = "gymnasium + numpy only for the learner; reproducible seeds; type hints optional."


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    from research_lab.config import RunConfig
    from research_lab.runner import run_console_session, seed_tier_a_from_run_config
    from research_lab import memory

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea=RESEARCH_BRIEF,
        preferences=PREFERENCES,
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="google/gemini-2.5-flash-lite",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(RESEARCHER_ROOT)
    seed_tier_a_from_run_config(RESEARCHER_ROOT, cfg)

    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    run_console_session(db_path, cfg)


if __name__ == "__main__":
    main()
