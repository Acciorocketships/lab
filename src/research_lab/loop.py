"""Launch and run the background scheduler loop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from research_lab import memory
from research_lab.workflows import research_graph

if TYPE_CHECKING:
    from research_lab.config import RunConfig


class SchedulerProcessHandle:
    """Small adapter so the console can manage a subprocess like a process."""

    def __init__(self, proc: subprocess.Popen[object]) -> None:
        self._proc = proc

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def terminate(self) -> None:
        if self.is_alive():
            self._proc.terminate()

    def join(self, timeout: float | None = None) -> None:
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return


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


def _jsonable(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _serialize_run_config(cfg: RunConfig) -> str:
    return json.dumps({key: _jsonable(value) for key, value in asdict(cfg).items()})


def _deserialize_run_config(payload: str) -> RunConfig:
    from research_lab.config import RunConfig

    data = json.loads(payload)
    for key in ("researcher_root", "project_dir", "oauth_token_path"):
        if data.get(key):
            data[key] = Path(data[key])
    return RunConfig(**data)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_root = str(Path(__file__).resolve().parents[1])
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_root if not current else f"{src_root}{os.pathsep}{current}"
    return env


def spawn_scheduler(
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    cfg: RunConfig,
) -> SchedulerProcessHandle:
    """Spawn the background scheduler subprocess and return a lightweight handle.

    stdout/stderr are redirected to a log file under the runtime directory so
    that subprocess output (logging warnings, tracebacks) never bleeds through
    the Textual TUI.
    """
    memory.ensure_memory_layout(researcher_root)
    log_path = researcher_root / "data" / "scheduler.log"
    log_fh = open(log_path, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "research_lab.loop",
            "run-scheduler",
            str(db_path),
            _serialize_run_config(cfg),
        ],
        cwd=str(project_dir),
        env=_subprocess_env(),
        stdout=log_fh,
        stderr=log_fh,
    )
    return SchedulerProcessHandle(proc)


def _run_scheduler_from_cli(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: python -m research_lab.loop run-scheduler <db_path> <run_config_json>")
    db_path = Path(argv[0])
    cfg = _deserialize_run_config(argv[1])
    _run_scheduler(db_path, cfg.researcher_root, cfg.project_dir, cfg)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: python -m research_lab.loop run-scheduler <db_path> <run_config_json>")
    command = args.pop(0)
    if command == "run-scheduler":
        return _run_scheduler_from_cli(args)
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
