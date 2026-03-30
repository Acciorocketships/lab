"""Start scheduler + console as separate processes."""

from __future__ import annotations

import multiprocessing
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
