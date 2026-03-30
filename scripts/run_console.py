"""Console-only bench runner — uses :func:`research_lab.runner.run_console_session` like ``scripts/run.py``."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "bench_rl_project"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    from research_lab.config import RunConfig
    from research_lab.runner import run_console_session
    from research_lab import memory

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea="",
        acceptance_criteria="",
        preferences="",
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="google/gemini-2.5-flash-lite",
        default_worker_backend="cursor",
    )
    RESEARCHER_ROOT.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(RESEARCHER_ROOT)
    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    run_console_session(db_path, cfg)


if __name__ == "__main__":
    main()
