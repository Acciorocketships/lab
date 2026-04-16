"""Launch and run the background scheduler loop."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING

from lab import agent_runtime, memory
from lab.workflows import research_graph

if TYPE_CHECKING:
    from lab.config import RunConfig


class SchedulerProcessHandle:
    """Small adapter so the console can manage a subprocess like a process.

    The subprocess is started in its own session / process group so that
    ``kill_group()`` can tear down the scheduler **and** any child worker
    processes (cursor / claude CLI) in one shot.
    """

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

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def kill_group(self, *, wait_timeout: float | None = 5.0) -> None:
        """SIGKILL the entire process group (scheduler + child workers)."""
        if self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                self._proc.kill()
            except OSError:
                pass
        if wait_timeout is None or wait_timeout <= 0:
            return
        try:
            self._proc.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            pass


def _run_scheduler(db_path: Path, researcher_root: Path, project_dir: Path, cfg: RunConfig) -> None:
    """Child process entry: LangGraph research loop."""
    ckpt = researcher_root / "langgraph_checkpoint.db"
    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=researcher_root,
        project_dir=project_dir,
        checkpoint_path=ckpt,
    )


def _run_agent(db_path: Path, researcher_root: Path, project_dir: Path, cfg: RunConfig, agent_id: int) -> None:
    """Child process entry: standalone async ``/agent`` worker."""
    agent_runtime.run_agent(
        agent_id=agent_id,
        db_path=db_path,
        cfg=cfg,
        researcher_root=researcher_root,
        project_dir=project_dir,
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
    from lab.config import RunConfig

    data = json.loads(payload)
    for key in ("researcher_root", "project_dir", "oauth_token_path"):
        if data.get(key):
            data[key] = Path(data[key])
    allowed = {f.name for f in fields(RunConfig)}
    data = {k: v for k, v in data.items() if k in allowed}
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
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
    log_path = memory.scheduler_log_path(researcher_root)
    log_fh = open(log_path, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lab.loop",
            "run-scheduler",
            str(db_path),
            _serialize_run_config(cfg),
        ],
        cwd=str(project_dir),
        env=_subprocess_env(),
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    return SchedulerProcessHandle(proc)


def spawn_agent_run(
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    cfg: RunConfig,
    agent_id: int,
) -> SchedulerProcessHandle:
    """Spawn one standalone async ``/agent`` subprocess."""
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
    log_path = memory.agent_log_path(researcher_root, agent_id)
    log_fh = open(log_path, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lab.loop",
            "run-agent",
            str(db_path),
            str(agent_id),
            _serialize_run_config(cfg),
        ],
        cwd=str(project_dir),
        env=_subprocess_env(),
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    return SchedulerProcessHandle(proc)


def _run_scheduler_from_cli(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: python -m lab.loop run-scheduler <db_path> <run_config_json>")
    db_path = Path(argv[0])
    cfg = _deserialize_run_config(argv[1])
    _run_scheduler(db_path, cfg.researcher_root, cfg.project_dir, cfg)
    return 0


def _run_agent_from_cli(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit("usage: python -m lab.loop run-agent <db_path> <agent_id> <run_config_json>")
    db_path = Path(argv[0])
    agent_id = int(argv[1])
    cfg = _deserialize_run_config(argv[2])
    _run_agent(db_path, cfg.researcher_root, cfg.project_dir, cfg, agent_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: python -m lab.loop run-scheduler <db_path> <run_config_json>")
    command = args.pop(0)
    if command == "run-scheduler":
        return _run_scheduler_from_cli(args)
    if command == "run-agent":
        return _run_agent_from_cli(args)
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
