"""SQLite schema and queries for control events, run log, and registry tables."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


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

CREATE TABLE IF NOT EXISTS worker_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  worker_type TEXT NOT NULL,
  start_time REAL NOT NULL,
  end_time REAL,
  exit_code INTEGER,
  cost REAL,
  summary TEXT
);

CREATE TABLE IF NOT EXISTS instructions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  answer_path TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exp_id TEXT NOT NULL UNIQUE,
  branch TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  metrics_path TEXT
);

CREATE TABLE IF NOT EXISTS heartbeats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  phase TEXT NOT NULL,
  worker TEXT NOT NULL,
  message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stall_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_type TEXT NOT NULL,
  cycle INTEGER NOT NULL,
  details TEXT,
  resolved INTEGER NOT NULL DEFAULT 0
);
"""


def connect_db(db_path: Path) -> sqlite3.Connection:
    """Open SQLite with WAL; shared across processes for TUI + scheduler."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_db(conn)
    return conn


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Upgrade legacy schemas (phase column, run_events table)."""
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='system_state'").fetchone()
    if row:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(system_state)").fetchall()}
        if "roadmap_step" not in cols:
            conn.execute("ALTER TABLE system_state ADD COLUMN roadmap_step TEXT NOT NULL DEFAULT ''")
        if "task" not in cols:
            conn.execute("ALTER TABLE system_state ADD COLUMN task TEXT NOT NULL DEFAULT ''")
        if "phase" in cols:
            conn.execute(
                "UPDATE system_state SET roadmap_step = phase WHERE id = 1 AND "
                "(roadmap_step IS NULL OR roadmap_step = '')"
            )
            try:
                conn.execute("ALTER TABLE system_state DROP COLUMN phase")
            except sqlite3.OperationalError:
                pass
    conn.commit()


@contextmanager
def db_session(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection and commit/rollback."""
    conn = connect_db(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


def heartbeat(conn: sqlite3.Connection, phase: str, worker: str, message: str) -> None:
    """Legacy no-op: heartbeats table may exist; prefer run_events."""
    del phase, worker, message


def latest_heartbeat(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Deprecated: use recent_run_events."""
    rows = recent_run_events(conn, 1)
    if not rows:
        return None
    r = rows[0]
    return {
        "ts": r["ts"],
        "phase": "",
        "worker": r["worker"],
        "message": r["summary"],
    }


def recent_heartbeats(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Deprecated alias: returns run_events rows."""
    return recent_run_events(conn, limit)


def add_instruction(conn: sqlite3.Connection, text: str, status: str = "new") -> int:
    """Insert user instruction; returns row id."""
    cur = conn.execute(
        "INSERT INTO instructions (text, status, created_at) VALUES (?, ?, ?)",
        (text, status, time.time()),
    )
    return int(cur.lastrowid)


def add_question(conn: sqlite3.Connection, text: str) -> int:
    """Queue a user question."""
    cur = conn.execute(
        "INSERT INTO questions (text, answer_path, status, created_at) VALUES (?, NULL, 'pending', ?)",
        (text, time.time()),
    )
    return int(cur.lastrowid)


def list_instructions(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    """List instructions, optionally filtered."""
    if status:
        return list(conn.execute("SELECT * FROM instructions WHERE status = ? ORDER BY id DESC", (status,)))
    return list(conn.execute("SELECT * FROM instructions ORDER BY id DESC"))


def list_branches_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Branch registry."""
    return list(conn.execute("SELECT * FROM branches ORDER BY id DESC"))


def list_experiments_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Experiment registry."""
    return list(conn.execute("SELECT * FROM experiments ORDER BY id DESC"))
