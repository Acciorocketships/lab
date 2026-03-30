"""Start scheduler + console as separate processes."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import TYPE_CHECKING

from research_lab import memory
from research_lab.workflows import research_graph

if TYPE_CHECKING:
    from research_lab.config import RunConfig


def _run_scheduler(db_path: Path, researcher_root: Path, project_dir: Path, cfg: RunConfig) -> None:
    """Child process entry: LangGraph research loop."""
    ckpt = researcher_root / "data" / "langgraph_checkpoint.db"
    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=researcher_root,
        project_dir=project_dir,
        checkpoint_path=ckpt,
    )


def spawn_scheduler(
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    cfg: RunConfig,
) -> multiprocessing.Process:
    """Spawn the background scheduler process and return the Process handle."""
    memory.ensure_memory_layout(researcher_root)
    proc = multiprocessing.Process(
        target=_run_scheduler,
        args=(db_path, researcher_root, project_dir, cfg),
        daemon=True,
    )
    proc.start()
    return proc


def start_session(
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    cfg: RunConfig,
    src_root: Path | None = None,
) -> None:
    """Spawn background scheduler and run TUI in foreground (scheduler starts immediately).

    Interactive use prefers :func:`research_lab.runner.run_lab_console`, which keeps the agent
    idle until ``/start`` in the console.
    """
    memory.ensure_memory_layout(researcher_root)
    if src_root is not None:
        p = str(src_root)
        os.environ["PYTHONPATH"] = p + os.pathsep + os.environ.get("PYTHONPATH", "")
    proc = spawn_scheduler(db_path, researcher_root, project_dir, cfg)
    try:
        from research_lab.runner import run_console_session

        run_console_session(db_path, cfg, ensure_paused=False)
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=3)
