from __future__ import annotations

import json
import signal
from pathlib import Path

from lab.config import RunConfig
from lab.loop import SchedulerProcessHandle, spawn_agent_run, spawn_scheduler


def _cfg(tmp_path: Path) -> RunConfig:
    project_dir = tmp_path / "project"
    researcher_root = project_dir / ".lab"
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

    monkeypatch.setattr("lab.loop.subprocess.Popen", FakePopen)

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
    assert cmd[1:3] == ["-m", "lab.loop"]
    assert cmd[3] == "run-scheduler"
    assert cmd[4] == str(db_path)
    payload = json.loads(cmd[5])
    assert payload["project_dir"] == str(cfg.project_dir)
    stdout_fh = calls[0]["kwargs"]["stdout"]
    assert Path(stdout_fh.name) == cfg.researcher_root / "logs" / "scheduler.log"
    handle.terminate()
    handle.join(timeout=1)
    assert not handle.is_alive()


def test_spawn_agent_run_writes_logs_under_logs_subdir(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.setattr("lab.loop.subprocess.Popen", FakePopen)

    handle = spawn_agent_run(
        db_path,
        cfg.researcher_root,
        cfg.project_dir,
        cfg,
        7,
    )

    assert isinstance(handle, SchedulerProcessHandle)
    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert cmd[3] == "run-agent"
    assert cmd[4] == str(db_path)
    assert cmd[5] == "7"
    stdout_fh = calls[0]["kwargs"]["stdout"]
    assert Path(stdout_fh.name) == cfg.researcher_root / "logs" / "agent_7.log"
    handle.terminate()
    handle.join(timeout=1)


def test_kill_group_can_skip_wait(monkeypatch) -> None:
    waits: list[float | None] = []
    kills: list[object] = []

    class FakePopen:
        pid = 4321

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            kills.append("kill")

        def wait(self, timeout: float | None = None) -> int:
            waits.append(timeout)
            return 0

    def fake_killpg(pid: int, sig: int) -> None:
        kills.append((pid, sig))

    monkeypatch.setattr("lab.loop.os.killpg", fake_killpg)

    handle = SchedulerProcessHandle(FakePopen())
    handle.kill_group(wait_timeout=0)

    assert kills == [(4321, signal.SIGKILL)]
    assert waits == []
