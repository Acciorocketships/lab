"""Tests for SQLite helpers."""

from pathlib import Path

from research_lab import db


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
