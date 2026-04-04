"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import sqlite3

from research_lab import db


def header_line(project_name: str, model: str, conn: sqlite3.Connection) -> str:
    """Single-line header combining project info and live status."""
    st = db.get_system_state(conn)
    mode = st.get("control_mode", "paused")
    cycle = int(st.get("cycle_count", 0))
    worker = st.get("current_worker", "") or ""

    dot = {"active": "[green]●[/]", "paused": "[yellow]●[/]"}.get(mode, "[red]●[/]")

    left = f"[bold]lab[/] [dim]──[/] {project_name} [dim]──[/] [dim]{model}[/]"

    right_parts = [f"{dot} {mode}"]
    if cycle:
        right_parts.append(f"cycle {cycle}")
    if worker:
        right_parts.append(worker)
    right = " [dim]·[/] ".join(right_parts)

    return f"{left}    {right}"


def format_cycle_header(cycle: int, worker: str, task: str) -> str:
    """Heading line when a new cycle starts."""
    pad = "─" * max(1, 50 - len(worker) - len(str(cycle)))
    return (
        f"\n  [bold]── cycle {cycle} · {worker} {pad}[/]\n"
        f"  [dim]{task[:140]}[/]"
    )


def format_stream_chunk(chunk: str) -> str:
    """A single streaming output line from a worker process."""
    text = chunk.rstrip()[:200]
    if not text:
        return ""
    return f"  [dim]┊ {text}[/]"


def format_worker_done(elapsed_sec: float, ok: bool = True) -> str:
    """Summary line after worker completes."""
    t = f"{elapsed_sec:.1f}s"
    if ok:
        return f"  [green]✓[/] [dim]Done ({t})[/]"
    return f"  [red]✗[/] [dim]Failed ({t})[/]"
