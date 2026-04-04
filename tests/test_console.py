from __future__ import annotations

import json
from pathlib import Path

from research_lab import db
from research_lab.config import RunConfig
from research_lab.ui import events
from research_lab.ui.console import ResearchConsole


def _cfg(tmp_path: Path) -> RunConfig:
    project_dir = tmp_path / "project"
    researcher_root = project_dir / ".airesearcher"
    return RunConfig(
        researcher_root=researcher_root,
        project_dir=project_dir,
        research_idea="idea",
        preferences="prefs",
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="model",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        openrouter_api_key="key",
    )


def test_cmd_start_enqueues_resume_when_scheduler_is_alive(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    writes: list[str] = []

    class FakeLog:
        def write(self, message: str) -> None:
            writes.append(message)

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()
    console.query_one = lambda *args, **kwargs: FakeLog()  # type: ignore[method-assign]

    console._cmd_start()

    pending = db.fetch_pending_events(conn)
    assert [row["kind"] for row in pending] == ["resume"]
    assert any("resumed" in message.lower() for message in writes)

    console._conn.close()


# ---------------------------------------------------------------------------
# Regression: successful worker output with "is_error" key must NOT be
# displayed as "Failed".
# ---------------------------------------------------------------------------


def test_worker_ok_from_payload_not_summary_substring(tmp_path: Path) -> None:
    """The console must read worker_ok from payload_json, not substring-match on summary."""
    db_path = tmp_path / "runtime.db"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)

    summary_with_error_key = (
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"Updated train.py"}'
    )
    payload = json.dumps({"worker_ok": True, "last_action_summary": summary_with_error_key})
    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="implementer",
        roadmap_step="",
        task="implement phase 5",
        summary=summary_with_error_key,
        payload={"worker_ok": True, "last_action_summary": summary_with_error_key},
    )
    conn.commit()

    rows = list(
        conn.execute(
            "SELECT id, ts, cycle, kind, worker, roadmap_step, task, summary, payload_json "
            "FROM run_events WHERE kind = 'worker' ORDER BY id DESC LIMIT 1"
        )
    )
    assert len(rows) == 1
    row = rows[0]
    pj = json.loads(row["payload_json"]) if row["payload_json"] else {}
    ok = pj.get("worker_ok", True)
    assert ok is True, "worker_ok should be True even though summary contains 'is_error'"
    conn.close()


# ---------------------------------------------------------------------------
# Stream event parsing
# ---------------------------------------------------------------------------


def test_parse_stream_event_tool_use() -> None:
    chunk = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "src/train.py"}}
            ]
        },
    })
    result = events.parse_stream_event(chunk)
    assert result is not None
    assert result[0] == "tool"
    assert "Reading" in result[1]
    assert "train.py" in result[1]


def test_parse_stream_event_skips_result() -> None:
    chunk = json.dumps({"type": "result", "subtype": "success", "is_error": False})
    assert events.parse_stream_event(chunk) is None


def test_parse_stream_event_plain_text() -> None:
    result = events.parse_stream_event("hello world")
    assert result == ("text", "hello world")


def test_format_worker_done_shows_excerpt() -> None:
    out = events.format_worker_done(42.5, ok=True, result_text="Added slippery flag support")
    assert "Done" in out
    assert "42.5s" in out
    assert "slippery" in out


def test_format_cycle_header_no_truncation() -> None:
    long_task = "A" * 300
    out = events.format_cycle_header(1, "planner", long_task)
    assert long_task in out


# ---------------------------------------------------------------------------
# Scheduler health check: console detects dead scheduler and auto-restarts
# ---------------------------------------------------------------------------


def test_check_scheduler_health_restarts_dead_process(tmp_path: Path) -> None:
    """When the scheduler dies while DB says 'active', the console should auto-restart."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()

    writes: list[str] = []

    class FakeLog:
        def write(self, message: str) -> None:
            writes.append(message)

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    spawned: list[bool] = []

    def fake_restart(self_console: ResearchConsole) -> None:
        spawned.append(True)
        self_console._scheduler = type("Alive", (), {"is_alive": lambda self: True})()

    console._scheduler = DeadScheduler()
    console.query_one = lambda *args, **kwargs: FakeLog()  # type: ignore[method-assign]
    console._restart_scheduler = lambda: fake_restart(console)  # type: ignore[method-assign]

    console._check_scheduler_health()

    assert len(spawned) == 1, "scheduler should have been restarted"
    assert console._auto_restarts == 1
    assert any("unexpectedly" in m.lower() for m in writes)

    console._conn.close()


def test_check_scheduler_health_stops_after_max_restarts(tmp_path: Path) -> None:
    """After _MAX_AUTO_RESTARTS, the console should stop restarting and set mode to paused."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()

    writes: list[str] = []

    class FakeLog:
        def write(self, message: str) -> None:
            writes.append(message)

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    console._scheduler = DeadScheduler()
    console._auto_restarts = console._MAX_AUTO_RESTARTS
    console.query_one = lambda *args, **kwargs: FakeLog()  # type: ignore[method-assign]

    console._check_scheduler_health()

    mode = db.get_system_state(conn)["control_mode"]
    assert mode == "paused", "should have set mode to paused after exhausting restarts"
    assert any("/start" in m for m in writes)

    console._conn.close()


def test_check_scheduler_health_ignores_paused_mode(tmp_path: Path) -> None:
    """When the scheduler exits and DB says 'paused', the console should NOT restart."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    console._scheduler = DeadScheduler()

    console._check_scheduler_health()

    assert console._scheduler is None, "scheduler ref should be cleared"
    assert console._auto_restarts == 0, "should not have attempted a restart"

    console._conn.close()
