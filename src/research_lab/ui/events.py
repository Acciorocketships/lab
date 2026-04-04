"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import json
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
        f"  [dim]{task}[/]"
    )


def format_stream_chunk(chunk: str) -> str:
    """A single streaming output line from a worker process (plain text fallback)."""
    text = chunk.rstrip()
    if not text:
        return ""
    return f"  [dim]┊ {text}[/]"


def format_worker_done(elapsed_sec: float, ok: bool = True, result_text: str = "") -> str:
    """Summary line after worker completes, optionally with a result excerpt."""
    t = f"{elapsed_sec:.1f}s"
    if ok:
        line = f"  [green]✓[/] [dim]Done ({t})[/]"
    else:
        line = f"  [red]✗[/] [dim]Failed ({t})[/]"
    if result_text:
        excerpt = " ".join(result_text.strip().split())[:200]
        if excerpt:
            line += f"\n  [dim]  {excerpt}[/]"
    return line


# ---------------------------------------------------------------------------
# Stream-JSON chunk parsing (tool call activity for the live status line)
# ---------------------------------------------------------------------------

_TOOL_LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Read": ("Reading", ("file_path", "path")),
    "View": ("Reading", ("file_path", "path")),
    "Write": ("Writing", ("file_path", "path")),
    "Create": ("Creating", ("file_path", "path")),
    "Edit": ("Editing", ("file_path", "path")),
    "Replace": ("Editing", ("file_path", "path")),
    "StrReplace": ("Editing", ("file_path", "path")),
    "MultiEdit": ("Editing", ("file_path", "path")),
    "Bash": ("Running", ("command",)),
    "Shell": ("Running", ("command",)),
    "Execute": ("Running", ("command",)),
    "Grep": ("Searching", ("pattern", "query")),
    "Search": ("Searching", ("pattern", "query")),
    "RipGrep": ("Searching", ("pattern", "query")),
    "Glob": ("Finding files", ("pattern", "glob_pattern")),
    "ListFiles": ("Listing", ("path", "directory")),
    "TodoWrite": ("Planning", ()),
    "WebSearch": ("Web search", ("search_term", "query")),
    "WebFetch": ("Fetching", ("url",)),
    "Task": ("Dispatching agent", ("description",)),
    "SemanticSearch": ("Semantic search", ("query",)),
}


def _format_tool_use(name: str, input_data: dict) -> str:
    label_info = _TOOL_LABELS.get(name)
    if label_info is None:
        return name
    verb, keys = label_info
    for key in keys:
        val = input_data.get(key, "")
        if val:
            val_str = str(val)
            if len(val_str) > 80:
                val_str = val_str[:77] + "…"
            return f"{verb} {val_str}"
    return verb


def parse_stream_event(chunk: str) -> tuple[str, str] | None:
    """Parse a stream-json chunk and return ``(event_type, display_text)`` or
    *None* to skip.  ``event_type`` is ``"tool"`` or ``"text"``.
    """
    text = chunk.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        clean = text.rstrip()
        return ("text", clean) if clean else None

    if not isinstance(data, dict):
        return ("text", str(data))

    typ = data.get("type", "")

    if typ == "assistant":
        msg = data.get("message", {})
        parts: list[str] = []
        for block in msg.get("content", []):
            if block.get("type") == "tool_use":
                return ("tool", _format_tool_use(block.get("name", ""), block.get("input", {})))
            if block.get("type") == "text":
                t = block.get("text", "").strip()
                if t:
                    parts.append(t)
        if parts:
            return ("text", " ".join(parts).split("\n")[0][:160])
        return None

    if typ in ("tool_use", "tool_call"):
        return (
            "tool",
            _format_tool_use(
                data.get("name", "") or data.get("tool", ""),
                data.get("input", {}) or data.get("arguments", {}),
            ),
        )

    if typ in ("result", "system", "tool_result"):
        return None

    return None


def extract_result_excerpt(summary: str, max_len: int = 200) -> str:
    """Collapse a worker summary into a short single-line excerpt."""
    text = summary.strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text
