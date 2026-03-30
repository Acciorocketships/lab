"""Structured log lines for the TUI activity stream (backed by run_events)."""

from __future__ import annotations

import sqlite3

from research_lab import db


def format_status_block(conn: sqlite3.Connection) -> str:
    """Build multi-line status text for the top pane."""
    st = db.get_system_state(conn)
    lines = [
        f"roadmap={st.get('roadmap_step', '')!r} task={(st.get('task', '') or '')[:120]!r}",
        f"mode={st['control_mode']} branch={st['current_branch']}",
        f"worker={st['current_worker']} cycle={st['cycle_count']}",
        f"last: {st['last_message']}",
    ]
    lines.append("--- recent (run_events) ---")
    for row in reversed(db.recent_run_events(conn, 8)):
        snip = (row["summary"] or "")[:120]
        lines.append(f"  {row['kind']}/{row['worker']}: {snip}")
    return "\n".join(lines)
