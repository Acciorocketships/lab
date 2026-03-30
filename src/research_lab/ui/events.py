"""Format DB state for the redesigned TUI."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from research_lab import db


def status_line(conn: sqlite3.Connection) -> str:
    """Single-line status bar text: dot + mode + cycle + worker + roadmap step."""
    st = db.get_system_state(conn)
    mode = st.get("control_mode", "paused")
    cycle = int(st.get("cycle_count", 0))
    worker = st.get("current_worker", "") or ""
    roadmap = (st.get("roadmap_step", "") or "")[:60]

    dot = {"active": "[green]\u25cf[/]", "paused": "[yellow]\u25cf[/]"}.get(
        mode, "[red]\u25cf[/]"
    )
    parts = [f"{dot} {mode}"]
    if cycle:
        parts.append(f"cycle {cycle}")
    if worker:
        parts.append(worker)
    if roadmap:
        parts.append(roadmap)
    return "  ".join(parts)


def header_line(project_name: str, model: str, conn: sqlite3.Connection) -> str:
    """Compact header: lab -- project -- model -- mode."""
    st = db.get_system_state(conn)
    mode = st.get("control_mode", "paused")
    return f"[bold]lab[/] \u2500\u2500 {project_name} \u2500\u2500 {model} \u2500\u2500 {mode}"


def format_run_event_line(row: sqlite3.Row) -> str:
    """Format a single run_event row for the activity log."""
    kind = row["kind"]
    worker = row["worker"]
    summary = (row["summary"] or "")[:160]
    task = (row["task"] or "")[:120]

    if kind == "orchestrator":
        return f"[bold dim]\u2500\u2500 {worker}[/] [dim]{_short_reason(summary)}[/]"
    return f"[dim]\u2502[/] {summary[:160]}"


def _short_reason(summary: str) -> str:
    """Extract the reason part from orchestrator summary like 'worker: reason'."""
    if ": " in summary:
        return summary.split(": ", 1)[1]
    return summary


def format_cycle_header(cycle: int, worker: str, task: str) -> str:
    """Heading line when a new cycle starts."""
    pad = "\u2500" * max(1, 50 - len(worker) - len(str(cycle)))
    return f"\n[bold]\u2500\u2500 cycle {cycle} \u00b7 {worker} {pad}[/]\n[dim]Task: {task[:140]}[/]"


def format_stream_chunk(chunk: str) -> str:
    """A single streaming output line from a worker process."""
    text = chunk.rstrip()[:200]
    if not text:
        return ""
    return f"[dim]\u250a {text}[/]"


def format_worker_done(elapsed_sec: float, ok: bool = True) -> str:
    """Summary line after worker completes."""
    t = f"{elapsed_sec:.1f}s"
    if ok:
        return f"[green]\u2713[/] [dim]Done ({t})[/]"
    return f"[red]\u2717[/] [dim]Failed ({t})[/]"
