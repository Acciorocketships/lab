"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Literal

from rich.markup import escape as _rich_escape

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


def _format_duration(seconds: float) -> str:
    s = max(0.0, seconds)
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    s_rem = s - m * 60
    if m < 60:
        return f"{m}m {s_rem:.1f}s"
    h = m // 60
    m_rem = m % 60
    return f"{h}h {m_rem}m {s_rem:.0f}s"


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
    t = _format_duration(elapsed_sec)
    return f"[bold]cycle {cycle} · {worker}[/] {dot} [dim]{t}[/]"


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
    """Optional result block after worker completes (status and time are on the cycle header)."""
    excerpt = result_text.strip() if result_text else ""
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


def _inline_md_to_rich(text: str) -> str:
    """Convert inline Markdown (bold, code) to Rich markup.

    Input must already be escaped via ``rich.markup.escape``.
    """
    text = re.sub(r"\*\*`([^`]+)`\*\*", r"[bold cyan]\1[/bold cyan]", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", text)
    text = re.sub(r"`([^`]+)`", r"[cyan]\1[/cyan]", text)
    return text


def markdown_to_rich(text: str) -> str:
    """Convert common Markdown to Rich console markup for terminal display."""
    text = _rich_escape(text)
    lines = text.split("\n")
    result: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                lang = stripped[3:].strip()
                label = f" {lang} " if lang else ""
                result.append(f"  [dim]{'─' * 3}{label}{'─' * max(1, 37 - len(label))}[/dim]")
            else:
                result.append(f"  [dim]{'─' * 40}[/dim]")
            continue

        if in_code_block:
            result.append(f"  [dim]{line}[/dim]")
            continue

        if not stripped:
            result.append("")
            continue

        if stripped.startswith("### "):
            result.append(f"[bold]{_inline_md_to_rich(stripped[4:])}[/bold]")
            continue
        if stripped.startswith("## "):
            result.append(f"\n[bold]{_inline_md_to_rich(stripped[3:])}[/bold]")
            continue
        if stripped.startswith("# "):
            result.append(
                f"\n[bold underline]{_inline_md_to_rich(stripped[2:])}[/bold underline]"
            )
            continue

        if re.match(r"^[-*_]{3,}$", stripped):
            result.append(f"[dim]{'─' * 40}[/dim]")
            continue

        if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)*\|$", stripped):
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            styled = [_inline_md_to_rich(c) for c in cells]
            result.append("  " + "  [dim]│[/dim]  ".join(styled))
            continue

        m = re.match(r"^(\s*)([-*+])\s", line)
        if m:
            depth = len(m.group(1)) // 2
            indent = "  " * (depth + 1)
            item_text = _inline_md_to_rich(line[m.end() :])
            result.append(f"{indent}[dim]•[/dim] {item_text}")
            continue

        m = re.match(r"^(\s*)(\d+)\.\s", line)
        if m:
            depth = len(m.group(1)) // 2
            indent = "  " * (depth + 1)
            item_text = _inline_md_to_rich(line[m.end() :])
            result.append(f"{indent}{m.group(2)}. {item_text}")
            continue

        result.append(_inline_md_to_rich(line))

    return "\n".join(result)


def extract_result_excerpt(summary: str) -> str:
    """Clean a worker summary for display (preserves multi-line content)."""
    return summary.strip()
