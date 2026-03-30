"""Start scheduler + console as separate processes."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

from research_lab import memory
from research_lab.config import RunConfig
from research_lab.ui.console import run_console
from research_lab.workflows import research_graph


def _run_scheduler(db_path: Path, researcher_root: Path, project_dir: Path, cfg: RunConfig) -> None:
    """Child process entry: LangGraph research loop."""
    ckpt = researcher_root / "data" / "langgraph_checkpoint.db"
    research_graph.run_loop(cfg, db_path=db_path, researcher_root=researcher_root, project_dir=project_dir, checkpoint_path=ckpt)


def start_session(
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    cfg: RunConfig,
    src_root: Path | None = None,
) -> None:
    """Spawn background scheduler and run TUI in foreground."""
    memory.ensure_memory_layout(researcher_root)
    if src_root is not None:
        p = str(src_root)
        os.environ["PYTHONPATH"] = p + os.pathsep + os.environ.get("PYTHONPATH", "")
    proc = multiprocessing.Process(
        target=_run_scheduler,
        args=(db_path, researcher_root, project_dir, cfg),
        daemon=True,
    )
    proc.start()
    try:
        run_console(db_path)
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=3)
