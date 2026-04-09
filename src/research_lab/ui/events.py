"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from rich import box
from rich.console import Group, RenderableType
from rich.markup import escape as _rich_escape
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from research_lab import db

_SURFACE_BORDER = "#3a3a3a"
_SURFACE_BG = "#1c1c1c"
_CODE_BG = "#141414"
_MARKDOWN_TABLE_BOX = box.Box(
    """
    
    
 ━━ 
    
 ── 
 ── 
    
    
""".strip("\n")
)
_CODE_LANGUAGE_ALIASES = {
    "py": "python",
    "pyi": "python",
    "js": "javascript",
    "jsx": "jsx",
    "ts": "typescript",
    "tsx": "tsx",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "yml": "yaml",
    "md": "markdown",
    "rs": "rust",
}


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


def _markup_text(text: str) -> Text:
    return Text.from_markup(_inline_md_to_rich(_rich_escape(text)))


def _append_paragraph(renderables: list[RenderableType], lines: list[str]) -> None:
    if not lines:
        return
    renderables.append(_markup_text("\n".join(lines)))
    lines.clear()


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\|[\s\-:]+(\|[\s\-:]+)*\|$", stripped))


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _make_markdown_table(block_lines: list[str]) -> Table | None:
    if len(block_lines) < 2:
        return None
    if not _is_table_row(block_lines[0]):
        return None

    headers = _split_table_row(block_lines[0])
    row_start = 2 if _is_table_separator(block_lines[1]) else 1
    rows = [_split_table_row(line) for line in block_lines[row_start:] if _is_table_row(line)]
    if not headers:
        return None

    column_count = max([len(headers), *[len(row) for row in rows]] if rows else [len(headers)])
    while len(headers) < column_count:
        headers.append("")
    for row in rows:
        while len(row) < column_count:
            row.append("")

    table = Table(
        box=_MARKDOWN_TABLE_BOX,
        show_header=True,
        show_lines=True,
        header_style="bold cyan",
        border_style=_SURFACE_BORDER,
        expand=True,
        pad_edge=False,
        padding=(0, 3),
    )
    for header in headers:
        table.add_column(Text.from_markup(_inline_md_to_rich(header)), overflow="fold")
    for row in rows:
        table.add_row(*[Text.from_markup(_inline_md_to_rich(cell)) for cell in row])
    return table


_CODE_REF_RE = re.compile(r"^(\d+):(\d+):(.+)$")


def _resolve_code_lexer(language: str, title_file: str, code: str) -> str:
    normalized = _CODE_LANGUAGE_ALIASES.get(language.strip().lower(), language.strip().lower())
    if normalized:
        return normalized
    first_line = code.lstrip().splitlines()[0].strip() if code.strip() else ""
    if first_line.startswith("#!"):
        if "python" in first_line:
            return "python"
        if any(shell in first_line for shell in ("bash", "sh", "zsh")):
            return "bash"
    if title_file:
        guessed = Syntax.guess_lexer(title_file, code)
        if guessed:
            return guessed
    lowered = code.lower()
    stripped_lines = [line.strip() for line in code.splitlines() if line.strip()]
    if any(
        token in lowered
        for token in (
            "def ",
            "import ",
            "from ",
            "class ",
            "elif ",
            "except",
            "lambda ",
            "pass",
            "none",
            "self",
        )
    ) or any(
        line.startswith(("for ", "if ", "while ", "with ", "try:", "return "))
        and line.endswith(":")
        for line in stripped_lines
    ):
        return "python"
    if any(
        token in lowered
        for token in ("const ", "let ", "function ", "=>", "console.log", "export ")
    ):
        return "javascript"
    if any(
        token in lowered
        for token in ("#!/bin/bash", "#!/usr/bin/env bash", "#!/bin/sh", "fi", "then", "echo ")
    ):
        return "bash"
    if stripped_lines and all(":" in line for line in stripped_lines[: min(3, len(stripped_lines))]):
        return "yaml"
    return "text"


def _make_code_block(code: str, language: str) -> Panel:
    lines = code.split("\n")
    start_line = 1
    title_file = ""

    if lines:
        m = _CODE_REF_RE.match(lines[0].strip())
        if m:
            start_line = int(m.group(1))
            title_file = m.group(3).strip()
            lines = lines[1:]
            code = "\n".join(lines)

    lexer = _resolve_code_lexer(language, title_file, code)
    show_nums = start_line > 1
    syntax = Syntax(
        code,
        lexer,
        theme="monokai",
        code_width=None,
        word_wrap=True,
        line_numbers=show_nums,
        start_line=start_line,
        indent_guides=False,
        background_color=_CODE_BG,
        padding=0,
    )

    if title_file:
        short = Path(title_file).name
        title = f"[dim]{short}[/dim] [dim italic]L{start_line}[/dim italic]"
    elif language:
        title = f"[dim]{language}[/dim]"
    else:
        title = ""

    return Panel(
        syntax,
        box=box.ROUNDED,
        border_style=_SURFACE_BORDER,
        style=f"on {_CODE_BG}",
        title=title,
        title_align="left",
        subtitle=f"[dim italic]{Path(title_file).parent}[/dim italic]" if title_file else "",
        subtitle_align="left",
        padding=0,
        expand=True,
    )


def make_stream_panel(markup: str) -> Panel:
    content = Text.from_markup(markup) if markup else Text("")
    return Panel(
        content,
        box=box.ROUNDED,
        border_style=_SURFACE_BORDER,
        style=f"on {_SURFACE_BG}",
        padding=(0, 2),
        expand=True,
    )


def wrap_result_renderable(renderable: RenderableType) -> RenderableType:
    if isinstance(renderable, Panel):
        return renderable
    return Panel(
        renderable,
        box=box.ROUNDED,
        border_style=_SURFACE_BORDER,
        style=f"on {_SURFACE_BG}",
        padding=(0, 2),
        expand=True,
    )


def render_markdown(text: str) -> RenderableType:
    """Convert common Markdown to Rich renderables for terminal display."""
    lines = text.split("\n")
    renderables: list[RenderableType] = []
    paragraph_lines: list[str] = []
    table_lines: list[str] = []
    code_lines: list[str] = []
    in_code_block = False
    code_language = ""

    for line in lines:
        stripped = line.strip()

        if in_code_block:
            if stripped.startswith("```"):
                renderables.append(_make_code_block("\n".join(code_lines), code_language))
                code_lines.clear()
                code_language = ""
                in_code_block = False
            else:
                code_lines.append(line)
            continue

        if stripped.startswith("```"):
            _append_paragraph(renderables, paragraph_lines)
            if table_lines:
                table = _make_markdown_table(table_lines)
                if table is not None:
                    renderables.append(table)
                table_lines.clear()
            in_code_block = True
            code_language = stripped[3:].strip()
            continue

        if _is_table_row(line):
            _append_paragraph(renderables, paragraph_lines)
            table_lines.append(line)
            continue

        if table_lines:
            if _is_table_separator(line):
                table_lines.append(line)
                continue
            table = _make_markdown_table(table_lines)
            if table is not None:
                renderables.append(table)
            table_lines.clear()

        if not stripped:
            _append_paragraph(renderables, paragraph_lines)
            continue

        if stripped.startswith("### "):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(Text.from_markup(f"[bold]{_inline_md_to_rich(_rich_escape(stripped[4:]))}[/bold]"))
            continue
        if stripped.startswith("## "):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(Text.from_markup(f"[bold]{_inline_md_to_rich(_rich_escape(stripped[3:]))}[/bold]"))
            continue
        if stripped.startswith("# "):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(
                Text.from_markup(
                    f"[bold underline]{_inline_md_to_rich(_rich_escape(stripped[2:]))}[/bold underline]"
                )
            )
            continue

        if re.match(r"^[-*_]{3,}$", stripped):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(Rule(style="dim"))
            continue

        m = re.match(r"^(\s*)([-*+])\s", line)
        if m:
            _append_paragraph(renderables, paragraph_lines)
            depth = len(m.group(1)) // 2
            indent = "  " * depth
            item_text = _inline_md_to_rich(_rich_escape(line[m.end() :]))
            renderables.append(Text.from_markup(f"{indent}[dim]•[/dim] {item_text}"))
            continue

        m = re.match(r"^(\s*)(\d+)\.\s", line)
        if m:
            _append_paragraph(renderables, paragraph_lines)
            depth = len(m.group(1)) // 2
            indent = "  " * depth
            item_text = _inline_md_to_rich(_rich_escape(line[m.end() :]))
            renderables.append(Text.from_markup(f"{indent}{m.group(2)}. {item_text}"))
            continue

        paragraph_lines.append(line)

    if in_code_block:
        renderables.append(_make_code_block("\n".join(code_lines), code_language))
    if table_lines:
        table = _make_markdown_table(table_lines)
        if table is not None:
            renderables.append(table)
    _append_paragraph(renderables, paragraph_lines)

    if not renderables:
        return Text("")
    if len(renderables) == 1:
        return renderables[0]
    return Group(*renderables)


def markdown_to_rich(text: str) -> RenderableType:
    """Backward-compatible alias for the richer markdown renderer."""
    return render_markdown(text)


def extract_result_excerpt(summary: str) -> str:
    """Clean a worker summary for display (preserves multi-line content)."""
    return summary.strip()
