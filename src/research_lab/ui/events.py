"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Literal

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


CycleHeaderStatus = Literal["running", "ok", "fail"]


def format_cycle_header(
    cycle: int,
    worker: str,
    task: str,
    *,
    elapsed_sec: float = 0.0,
    status: CycleHeaderStatus = "running",
) -> str:
    """Cycle heading with status dot, duration (like the top header dot), and task line."""
    dot = {"running": "[yellow]●[/]", "ok": "[green]●[/]", "fail": "[red]●[/]"}[status]
    es = max(0.0, float(elapsed_sec))
    t = f"{es:.1f}s"
    return (
        f"\n  [bold]── cycle {cycle} · {worker}[/] {dot} [dim]{t}[/]\n"
        f"  [dim]{task}[/]"
    )


def cycle_header_running_elapsed(orchestrator_ts: float) -> float:
    """Elapsed seconds for a running cycle (for live header updates)."""
    return max(0.0, time.time() - orchestrator_ts)


def format_stream_chunk(chunk: str) -> str:
    """A single streaming output line from a worker process (plain text fallback)."""
    text = chunk.rstrip()
    if not text:
        return ""
    return f"  [dim]┊ {text}[/]"


def format_worker_result_excerpt(ok: bool, result_text: str = "") -> str:
    """Optional result line after worker completes (status and time are on the cycle header)."""
    excerpt = " ".join(result_text.strip().split())[:200] if result_text else ""
    if excerpt:
        return f"  [dim]{excerpt}[/]"
    if not ok:
        return "  [dim](failed — no excerpt)[/]"
    return ""


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


def parse_stream_event(chunk: str, *, full_text: bool = False) -> tuple[str, str] | None:
    """Parse a stream-json chunk and return ``(event_type, display_text)`` or
    *None* to skip.  ``event_type`` is ``"tool"`` or ``"text"``.

    When *full_text* is True the complete text content is returned (multi-line,
    no truncation).  When False (default) a single-line ≤160-char excerpt is
    returned for compact status display.
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
            combined = "\n".join(parts) if full_text else " ".join(parts).split("\n")[0][:160]
            return ("text", combined) if combined.strip() else None
        return None

    if typ == "content_block_delta":
        delta = data.get("delta", {})
        if delta.get("type") == "text_delta":
            t = delta.get("text", "")
            if t.strip():
                return ("text", t if full_text else t.split("\n")[0][:160])
        return None

    if typ == "content_block_start":
        block = data.get("content_block", {})
        if block.get("type") == "tool_use":
            return ("tool", _format_tool_use(block.get("name", ""), block.get("input", {})))
        if block.get("type") == "text":
            t = block.get("text", "")
            if t.strip():
                return ("text", t if full_text else t.split("\n")[0][:160])
        return None

    if typ in ("tool_use", "tool_call"):
        return (
            "tool",
            _format_tool_use(
                data.get("name", "") or data.get("tool", ""),
                data.get("input", {}) or data.get("arguments", {}),
            ),
        )

    if typ in ("result", "system", "tool_result", "message_start", "message_stop",
               "content_block_stop", "ping", "message_delta"):
        return None

    # Fallback: try to extract text from any unrecognized JSON event.
    for key in ("text", "content", "message", "output", "data"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            t = val.strip()
            return ("text", t if full_text else t.split("\n")[0][:160])
        if isinstance(val, dict):
            for sub in ("text", "content"):
                sv = val.get(sub)
                if isinstance(sv, str) and sv.strip():
                    t = sv.strip()
                    return ("text", t if full_text else t.split("\n")[0][:160])

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
