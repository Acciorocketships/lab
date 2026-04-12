"""Tests for SQLite helpers."""

import json
from pathlib import Path

from lab import db


def test_enqueue_and_consume(tmp_path: Path) -> None:
    """Events round-trip and can be marked consumed."""
    p = tmp_path / "t.db"
    conn = db.connect_db(p)
    db.enqueue_event(conn, "pause", None)
    db.enqueue_event(conn, "instruction", "do X")
    evs = db.fetch_pending_events(conn)
    assert len(evs) == 2
    db.mark_events_consumed(conn, [int(evs[0]["id"])])
    evs2 = db.fetch_pending_events(conn)
    assert len(evs2) == 1


def test_system_state_row(tmp_path: Path) -> None:
    """system_state initializes."""
    p = tmp_path / "t.db"
    conn = db.connect_db(p)
    st = db.get_system_state(conn)
    assert st["control_mode"] == "active"
    assert "roadmap_step" in st
    assert "task" in st
    db.set_control_mode(conn, "paused")
    st2 = db.get_system_state(conn)
    assert st2["control_mode"] == "paused"


def test_append_run_event(tmp_path: Path) -> None:
    """run_events append and recent list."""
    p = tmp_path / "t.db"
    conn = db.connect_db(p)
    db.append_run_event(
        conn,
        cycle=1,
        kind="orchestrator",
        worker="planner",
        roadmap_step="M1",
        task="plan",
        summary="planner: ok",
        payload={"x": 1},
        packet_path=None,
    )
    conn.commit()
    rows = db.recent_run_events(conn, 5)
    assert len(rows) == 1
    assert rows[0]["worker"] == "planner"
    assert rows[0]["summary"] == "planner: ok"
    assert rows[0]["payload_json"] is not None
    assert json.loads(rows[0]["payload_json"]) == {"x": 1}


def test_worker_stream_roundtrip(tmp_path: Path) -> None:
    """Stream chunks write and read back in order."""
    p = tmp_path / "t.db"
    conn = db.connect_db(p)
    db.append_stream_chunk(conn, cycle=1, worker="planner", chunk="line 1")
    db.append_stream_chunk(conn, cycle=1, worker="planner", chunk="line 2")

    rows = db.stream_chunks_since(conn, 0)
    assert len(rows) == 2
    assert rows[0]["chunk"] == "line 1"
    assert rows[1]["chunk"] == "line 2"

    rows2 = db.stream_chunks_since(conn, rows[0]["id"])
    assert len(rows2) == 1
    assert rows2[0]["chunk"] == "line 2"


def test_clear_stream(tmp_path: Path) -> None:
    p = tmp_path / "t.db"
    conn = db.connect_db(p)
    db.append_stream_chunk(conn, cycle=1, worker="a", chunk="x")
    db.append_stream_chunk(conn, cycle=2, worker="b", chunk="y")
    db.clear_stream(conn, cycle=1)
    rows = db.stream_chunks_since(conn, 0)
    assert len(rows) == 1
    assert rows[0]["cycle"] == 2


def test_orchestrator_ahead_of_worker(tmp_path: Path) -> None:
    conn = db.connect_db(tmp_path / "t.db")
    assert db.orchestrator_ahead_of_worker(conn) is False
    db.append_run_event(
        conn,
        cycle=1,
        kind="orchestrator",
        worker="planner",
        roadmap_step="",
        task="t",
        summary="s",
        payload=None,
        packet_path=None,
    )
    conn.commit()
    assert db.orchestrator_ahead_of_worker(conn) is True
    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="planner",
        roadmap_step="",
        task="t",
        summary="done",
        payload=None,
        packet_path=None,
    )
    conn.commit()
    assert db.orchestrator_ahead_of_worker(conn) is False
    db.append_run_event(
        conn,
        cycle=2,
        kind="orchestrator",
        worker="researcher",
        roadmap_step="",
        task="t2",
        summary="s2",
        payload=None,
        packet_path=None,
    )
    conn.commit()
    assert db.orchestrator_ahead_of_worker(conn) is True
