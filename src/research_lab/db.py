"""SQLite schema and queries for control events, run log, and registry tables."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS control_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at REAL NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  current_branch TEXT NOT NULL DEFAULT '',
  current_worker TEXT NOT NULL DEFAULT '',
  cycle_count INTEGER NOT NULL DEFAULT 0,
  control_mode TEXT NOT NULL DEFAULT 'active',
  last_message TEXT NOT NULL DEFAULT '',
  roadmap_step TEXT NOT NULL DEFAULT '',
  task TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  cycle INTEGER NOT NULL,
  kind TEXT NOT NULL,
  worker TEXT NOT NULL,
  roadmap_step TEXT NOT NULL DEFAULT '',
  task TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  payload_json TEXT,
  packet_path TEXT
);

CREATE TABLE IF NOT EXISTS instructions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exp_id TEXT NOT NULL UNIQUE,
  branch TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  metrics_path TEXT
);

CREATE TABLE IF NOT EXISTS worker_stream (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle INTEGER NOT NULL,
  worker TEXT NOT NULL,
  chunk TEXT NOT NULL,
  ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS forced_run (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  worker TEXT NOT NULL DEFAULT '',
  task TEXT NOT NULL DEFAULT ''
);
"""


def obliterate_runtime_db(db_path: Path) -> None:
    """Remove the SQLite database file and WAL sidecars so the next :func:`connect_db` creates a fresh DB."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for p in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def connect_db(db_path: Path) -> sqlite3.Connection:
    """Open SQLite with WAL; shared across processes for TUI + scheduler."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO forced_run (id, worker, task) VALUES (1, '', '')"
    )
    conn.commit()
    return conn


def enqueue_event(conn: sqlite3.Connection, kind: str, payload: str | None = None) -> None:
    """Append a control event for the scheduler to consume."""
    conn.execute(
        "INSERT INTO control_events (kind, payload, created_at, consumed) VALUES (?, ?, ?, 0)",
        (kind, payload, time.time()),
    )


def fetch_pending_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Return unconsumed control events oldest-first."""
    cur = conn.execute(
        "SELECT id, kind, payload, created_at FROM control_events WHERE consumed = 0 ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    return list(cur.fetchall())


def mark_events_consumed(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Mark events as consumed."""
    if not ids:
        return
    conn.executemany("UPDATE control_events SET consumed = 1 WHERE id = ?", [(i,) for i in ids])


def get_system_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Single-row operational state."""
    row = conn.execute("SELECT * FROM system_state WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO system_state (id, current_branch, current_worker, cycle_count, control_mode, last_message, roadmap_step, task) "
            "VALUES (1, '', '', 0, 'active', '', '', '')"
        )
        row = conn.execute("SELECT * FROM system_state WHERE id = 1").fetchone()
    return dict(row)  # type: ignore[arg-type]


def set_control_mode(conn: sqlite3.Connection, mode: str) -> None:
    """Update control_mode (active, paused, shutdown, watch)."""
    conn.execute("UPDATE system_state SET control_mode = ? WHERE id = 1", (mode,))


def set_system_fields(
    conn: sqlite3.Connection,
    *,
    roadmap_step: str | None = None,
    task: str | None = None,
    current_branch: str | None = None,
    current_worker: str | None = None,
    cycle_count: int | None = None,
    last_message: str | None = None,
) -> None:
    """Patch system_state fields."""
    state = get_system_state(conn)
    if roadmap_step is not None:
        state["roadmap_step"] = roadmap_step
    if task is not None:
        state["task"] = task
    if current_branch is not None:
        state["current_branch"] = current_branch
    if current_worker is not None:
        state["current_worker"] = current_worker
    if cycle_count is not None:
        state["cycle_count"] = cycle_count
    if last_message is not None:
        state["last_message"] = last_message
    conn.execute(
        "UPDATE system_state SET current_branch=?, current_worker=?, cycle_count=?, last_message=?, roadmap_step=?, task=? WHERE id=1",
        (
            state["current_branch"],
            state["current_worker"],
            state["cycle_count"],
            state["last_message"],
            state.get("roadmap_step", ""),
            state.get("task", ""),
        ),
    )


def append_run_event(
    conn: sqlite3.Connection,
    *,
    cycle: int,
    kind: str,
    worker: str,
    roadmap_step: str,
    task: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    packet_path: str | None = None,
) -> int:
    """Append one row to run_events; returns new id."""
    payload_json = json.dumps(payload, ensure_ascii=False, default=str) if payload is not None else None
    cur = conn.execute(
        """INSERT INTO run_events (ts, cycle, kind, worker, roadmap_step, task, summary, payload_json, packet_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(),
            cycle,
            kind,
            worker,
            roadmap_step,
            task,
            summary,
            payload_json,
            packet_path,
        ),
    )
    return int(cur.lastrowid)


def recent_run_events(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Recent run log rows, newest first."""
    return list(
        conn.execute(
            "SELECT id, ts, cycle, kind, worker, roadmap_step, task, summary, packet_path "
            "FROM run_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    )


def add_instruction(conn: sqlite3.Connection, text: str, status: str = "new") -> int:
    """Insert user instruction; returns row id."""
    cur = conn.execute(
        "INSERT INTO instructions (text, status, created_at) VALUES (?, ?, ?)",
        (text, status, time.time()),
    )
    return int(cur.lastrowid)


def list_instructions(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    """List instructions, optionally filtered."""
    if status:
        return list(conn.execute("SELECT * FROM instructions WHERE status = ? ORDER BY id DESC", (status,)))
    return list(conn.execute("SELECT * FROM instructions ORDER BY id DESC"))


def list_experiments_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Experiment registry."""
    return list(conn.execute("SELECT * FROM experiments ORDER BY id DESC"))


# --- worker stream -----------------------------------------------------------

def append_stream_chunk(conn: sqlite3.Connection, cycle: int, worker: str, chunk: str) -> None:
    """Write one streaming output chunk from a running worker."""
    conn.execute(
        "INSERT INTO worker_stream (cycle, worker, chunk, ts) VALUES (?, ?, ?, ?)",
        (cycle, worker, chunk, time.time()),
    )
    conn.commit()


def stream_chunks_since(conn: sqlite3.Connection, after_id: int = 0) -> list[sqlite3.Row]:
    """Return stream chunks with id > after_id, oldest first."""
    return list(
        conn.execute(
            "SELECT id, cycle, worker, chunk, ts FROM worker_stream WHERE id > ? ORDER BY id ASC LIMIT 200",
            (after_id,),
        )
    )


def orchestrator_ahead_of_worker(conn: sqlite3.Connection) -> bool:
    """True when the latest orchestrator event is for a cycle with no worker row yet."""
    row_o = conn.execute(
        "SELECT MAX(cycle) FROM run_events WHERE kind = 'orchestrator'",
    ).fetchone()
    row_w = conn.execute(
        "SELECT MAX(cycle) FROM run_events WHERE kind = 'worker'",
    ).fetchone()
    orch = row_o[0] if row_o else None
    if orch is None:
        return False
    worker_max = int(row_w[0]) if row_w and row_w[0] is not None else 0
    return int(orch) > worker_max


def rollback_to_cycle(conn: sqlite3.Connection, cycle: int) -> None:
    """Reset system_state to *cycle* and purge run_events / stream rows beyond it."""
    conn.execute(
        "UPDATE system_state SET cycle_count = ?, control_mode = 'paused', "
        "current_worker = '', last_message = '' WHERE id = 1",
        (cycle,),
    )
    conn.execute("DELETE FROM run_events WHERE cycle > ?", (cycle,))
    conn.execute("DELETE FROM worker_stream WHERE cycle > ?", (cycle,))


def set_forced_run(conn: sqlite3.Connection, worker: str, task: str) -> None:
    """Set a one-shot forced worker/task for the next cycle."""
    conn.execute(
        "UPDATE forced_run SET worker = ?, task = ? WHERE id = 1",
        (worker.strip(), task.strip()),
    )


def get_forced_run(conn: sqlite3.Connection) -> dict[str, str] | None:
    """Return the pending forced worker/task, if any."""
    row = conn.execute(
        "SELECT worker, task FROM forced_run WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    worker = (row["worker"] or "").strip()
    task = (row["task"] or "").strip()
    if not worker:
        return None
    return {"worker": worker, "task": task}


def clear_forced_run(conn: sqlite3.Connection) -> None:
    """Clear any pending forced worker/task."""
    conn.execute("UPDATE forced_run SET worker = '', task = '' WHERE id = 1")


def clear_stream(conn: sqlite3.Connection, cycle: int | None = None) -> None:
    """Delete stream rows, optionally only for a given cycle."""
    if cycle is not None:
        conn.execute("DELETE FROM worker_stream WHERE cycle = ?", (cycle,))
    else:
        conn.execute("DELETE FROM worker_stream")
    conn.commit()
