from __future__ import annotations

import json
from pathlib import Path

from research_lab.config import RunConfig
from research_lab.loop import SchedulerProcessHandle, spawn_scheduler


def _cfg(tmp_path: Path) -> RunConfig:
    project_dir = tmp_path / "project"
    researcher_root = project_dir / ".airesearcher"
    return RunConfig(
        researcher_root=researcher_root,
        project_dir=project_dir,
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="model",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        openrouter_api_key="key",
    )


def test_spawn_scheduler_launches_subprocess(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    calls: list[dict[str, object]] = []

    class FakePopen:
        def __init__(self, cmd: list[str], **kwargs) -> None:
            calls.append({"cmd": cmd, "kwargs": kwargs})
            self.returncode = None

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode or 0

    monkeypatch.setattr("research_lab.loop.subprocess.Popen", FakePopen)

    handle = spawn_scheduler(
        db_path,
        cfg.researcher_root,
        cfg.project_dir,
        cfg,
    )

    assert isinstance(handle, SchedulerProcessHandle)
    assert handle.is_alive()
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert Path(cmd[0]).name.startswith("python")
    assert cmd[1:3] == ["-m", "research_lab.loop"]
    assert cmd[3] == "run-scheduler"
    assert cmd[4] == str(db_path)
    payload = json.loads(cmd[5])
    assert payload["project_dir"] == str(cfg.project_dir)
    handle.terminate()
    handle.join(timeout=1)
    assert not handle.is_alive()
