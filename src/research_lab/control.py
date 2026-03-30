"""Control event handling: map events to DB + file updates."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from research_lab import db, memory


def apply_instruction_event(conn: sqlite3.Connection, researcher_root: Path, payload: str | None) -> None:
    """Record instruction in SQLite and Tier A user_instructions.md."""
    if not payload:
        return
    db.add_instruction(conn, payload.strip(), status="new")
    memory.write_user_instruction_new_section(researcher_root, payload.strip())
