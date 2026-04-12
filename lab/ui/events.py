"""Format DB state for the TUI header, activity log, and stream output."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from rich import box
from rich.console import Group, RenderableType
from rich.markup import escape as _rich_escape
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.syntax import ANSISyntaxTheme, Syntax
from rich.table import Table
from rich.text import Text
from pygments.token import Comment, Error, Keyword, Name, Number, Operator, String, Text as TokenText

from lab import db

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
_CODE_THEME = ANSISyntaxTheme(
    {
        TokenText: Style.parse("white"),
        Comment: Style.parse("italic bright_black"),
        Keyword: Style.parse("bold bright_cyan"),
        Keyword.Namespace: Style.parse("bold bright_magenta"),
        Name.Builtin: Style.parse("bright_blue"),
        Name.Class: Style.parse("bold bright_blue"),
        Name.Decorator: Style.parse("bright_magenta"),
        Name.Exception: Style.parse("bold bright_red"),
        Name.Function: Style.parse("bold bright_blue"),
        Name.Namespace: Style.parse("bright_blue"),
        Name.Tag: Style.parse("bold bright_cyan"),
        Number: Style.parse("bright_yellow"),
        Operator: Style.parse("bright_magenta"),
        String: Style.parse("bright_green"),
        Error: Style.parse("bold bright_red"),
    }
)


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
    cursor_model: str | None = None,
    elapsed_sec: float = 0.0,
    status: CycleHeaderStatus = "running",
) -> str:
    """Cycle heading with status dot, duration (like the top header dot), and task line."""
    dot = {"running": "[yellow]●[/]", "ok": "[green]●[/]", "fail": "[red]●[/]"}[status]
    t = _format_duration(elapsed_sec)
    model_bit = (
        f' [dim]({cursor_model})[/]' if (cursor_model is not None and cursor_model != "") else ""
    )
    return f"[bold]cycle {cycle} · {worker}[/]{model_bit} {dot} [dim]{t}[/]"


def cycle_header_running_elapsed(orchestrator_ts: float) -> float:
    """Elapsed seconds for a running cycle (for live header updates)."""
    return max(0.0, time.time() - orchestrator_ts)


# ---------------------------------------------------------------------------
# Real-time file change tracking (git diff per cycle)
# ---------------------------------------------------------------------------

def _git_line_count(project_dir: Path, relpath: str) -> int:
    fpath = project_dir / relpath
    try:
        if fpath.is_file() and fpath.stat().st_size < 500_000:
            return fpath.read_bytes().count(b"\n")
    except OSError:
        pass
    return 0


def compute_file_diffs(
    project_dir: Path,
    baseline: dict[str, Any] | None = None,
) -> list[tuple[str, int, int]]:
    """Return ``(relative_path, additions, deletions)`` for changed or new files.

    With *baseline* (from :func:`lab.memory.capture_worker_diff_baseline`), compare
    to the tree at worker start. Without it, compare tracked files to ``HEAD`` and list
    untracked paths with total line counts (legacy behaviour).
    """
    diffs_map: dict[str, tuple[int, int]] = {}
    try:
        if baseline and isinstance(baseline.get("cycle"), int):
            tree = baseline.get("tree")
            head = (baseline.get("head") or "").strip()
            ref = tree if isinstance(tree, str) and tree.strip() else head
            untracked_lines: dict[str, int] = dict(baseline.get("untracked_lines") or {})

            if ref:
                r = subprocess.run(
                    ["git", "diff", "--numstat", "--no-renames", ref],
                    cwd=project_dir, capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and r.stdout.strip():
                    for line in r.stdout.strip().splitlines():
                        parts = line.split("\t")
                        if len(parts) < 3:
                            continue
                        try:
                            a, d = int(parts[0]), int(parts[1])
                        except ValueError:
                            a, d = 0, 0
                        path = parts[2].replace("\\", "/")
                        diffs_map[path] = (a, d)
            else:
                tracked_lines: dict[str, int] = dict(baseline.get("tracked_lines") or {})
                if tracked_lines:
                    r_staged = subprocess.run(
                        ["git", "ls-files"],
                        cwd=project_dir, capture_output=True, text=True, timeout=5,
                    )
                    if r_staged.returncode == 0 and r_staged.stdout.strip():
                        for fname in r_staged.stdout.strip().splitlines():
                            fn = fname.strip().replace("\\", "/")
                            if not fn:
                                continue
                            prev = tracked_lines.get(fn)
                            now = _git_line_count(project_dir, fn)
                            if prev is None:
                                if now:
                                    diffs_map[fn] = (now, 0)
                            elif now != prev:
                                if now > prev:
                                    diffs_map[fn] = (now - prev, 0)
                                else:
                                    diffs_map[fn] = (0, prev - now)

            baseline_tree_paths: set[str] = set()
            if tree:
                rt = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", tree],
                    cwd=project_dir, capture_output=True, text=True, timeout=5,
                )
                if rt.returncode == 0 and rt.stdout.strip():
                    baseline_tree_paths = {p.replace("\\", "/") for p in rt.stdout.splitlines() if p.strip()}

            r2 = subprocess.run(
                ["git", "ls-files", "-o", "--exclude-standard"],
                cwd=project_dir, capture_output=True, text=True, timeout=5,
            )
            if r2.returncode == 0 and r2.stdout.strip():
                for fname in r2.stdout.strip().splitlines():
                    fn = fname.strip().replace("\\", "/")
                    if not fn or fn in diffs_map:
                        continue
                    if tree and fn in baseline_tree_paths:
                        continue
                    prev = untracked_lines.get(fn)
                    now = _git_line_count(project_dir, fn)
                    if prev is None:
                        if now:
                            diffs_map[fn] = (now, 0)
                    elif now != prev:
                        if now > prev:
                            diffs_map[fn] = (now - prev, 0)
                        else:
                            diffs_map[fn] = (0, prev - now)
            return sorted(
                ((p, a, d) for p, (a, d) in diffs_map.items()),
                key=lambda t: t[0],
            )

        r = subprocess.run(
            ["git", "diff", "--numstat", "--no-renames", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                try:
                    a, d = int(parts[0]), int(parts[1])
                except ValueError:
                    a, d = 0, 0
                path = parts[2].replace("\\", "/")
                diffs_map[path] = (a, d)

        r2 = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard"],
            cwd=project_dir, capture_output=True, text=True, timeout=5,
        )
        if r2.returncode == 0 and r2.stdout.strip():
            for fname in r2.stdout.strip().splitlines():
                fn = fname.strip().replace("\\", "/")
                if not fn:
                    continue
                if fn in diffs_map:
                    continue
                now = _git_line_count(project_dir, fn)
                if now:
                    diffs_map[fn] = (now, 0)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return sorted(
        ((p, a, d) for p, (a, d) in diffs_map.items()),
        key=lambda t: t[0],
    )


_NB = "\u00a0"  # non-breaking space keeps each entry on one line


def format_file_changes(diffs: list[tuple[str, int, int]]) -> Text:
    """Format diffs as a wrapping line of ``file\u00a0+N\u00a0-M`` entries.

    Non-breaking spaces glue each entry together so word-wrap only splits
    between files, never inside a single entry.
    """
    text = Text()
    for i, (filename, adds, dels) in enumerate(diffs):
        if i > 0:
            text.append("  ")
        text.append(f"{filename}{_NB}", style="dim")
        text.append(f"+{adds}", style="green")
        text.append(_NB)
        text.append(f"-{dels}", style="red")
    return text


def format_diff_as_markup(raw_diff: str) -> str:
    """Convert raw ``git diff`` output into Rich markup for display in the TUI.

    Added lines are green, removed lines are red, hunk headers are dim cyan,
    and context lines are dim.  File headers are bold white.  Special characters
    in each line's content are escaped so they are not interpreted as markup.
    """
    from rich.markup import escape as _escape

    lines: list[str] = []
    for raw_line in raw_diff.splitlines():
        if raw_line.startswith("diff --git "):
            # Extract the b/ path as the display filename
            parts = raw_line.split(" ")
            filename = parts[-1].removeprefix("b/") if len(parts) >= 4 else raw_line
            if lines:
                lines.append("")
            lines.append(f"  [bold white]{_escape(filename)}[/]")
        elif raw_line.startswith(("index ", "--- ", "+++ ")):
            continue
        elif raw_line.startswith("@@ "):
            # Keep only the @@ ... @@ part, drop optional trailing context
            hunk = raw_line.split("@@", 2)
            hunk_header = f"@@{hunk[1]}@@" if len(hunk) >= 3 else raw_line
            lines.append(f"  [dim cyan]{_escape(hunk_header)}[/]")
        elif raw_line.startswith("+"):
            lines.append(f"  [green]{_escape(raw_line)}[/]")
        elif raw_line.startswith("-"):
            lines.append(f"  [red]{_escape(raw_line)}[/]")
        elif raw_line.startswith("\\ "):
            lines.append(f"  [dim]{_escape(raw_line)}[/]")
        else:
            lines.append(f"  [dim]{_escape(raw_line)}[/]")
    return "\n".join(lines)


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

# ASCII space between icon and verb. ``Write`` also keeps a trailing space on
# ``✍️`` in ``_TOOL_LABELS`` so tight monospace layouts still separate pencil from “Writing”.
_TOOL_EMOJI_GAP = " "


def _tool_line(emoji: str, rest: str) -> str:
    """``emoji`` + ``_TOOL_EMOJI_GAP`` + *rest* (trimmed). *emoji* may end with a space."""
    r = rest.strip()
    return f"{emoji}{_TOOL_EMOJI_GAP}{r}" if r else f"{emoji}{_TOOL_EMOJI_GAP}"


_TOOL_LABELS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "Read": ("📖", "Reading", ("file_path", "path")),
    "View": ("👁️", "Viewing", ("file_path", "path")),
    "Write": ("✍️ ", "Writing", ("file_path", "path")),
    "Create": ("🆕", "Creating", ("file_path", "path")),
    "Edit": ("📝", "Editing", ("file_path", "path")),
    "Replace": ("🔄", "Replacing", ("file_path", "path")),
    "StrReplace": ("🔤", "String replacing", ("file_path", "path")),
    "MultiEdit": ("🧩", "Multiple edits", ("file_path", "path")),
    "Bash": ("💻", "Running", ("command",)),
    "Shell": ("🐚", "Running in shell", ("command",)),
    "Execute": ("🚀", "Executing", ("command",)),
    "Grep": ("🔍", "Searching", ("pattern", "query")),
    "Search": ("🕵️", "Searching", ("pattern", "query")),
    "RipGrep": ("⚡", "Fast searching", ("pattern", "query")),
    "Glob": ("📂", "Finding files", ("pattern", "glob_pattern")),
    "ListFiles": ("🗂️", "Listing", ("path", "directory")),
    "TodoWrite": ("🧭", "Planning", ()),
    "WebSearch": ("🌐", "Web search", ("search_term", "query")),
    "WebFetch": ("📡", "Fetching", ("url",)),
    "Task": ("🤖", "Dispatching agent", ("description",)),
    "SemanticSearch": ("🧠", "Semantic search", ("query",)),
    "Git": ("🌿", "Git", ("command",)),
    "ReadLints": ("🩺", "Checking lints", ("paths", "path")),
}


def _normalize_tool_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    if raw.endswith("ToolCall"):
        raw = raw.removesuffix("ToolCall")
    mapping = {
        "edit": "Edit",
        "read": "Read",
        "view": "View",
        "write": "Write",
        "create": "Create",
        "shell": "Shell",
        "bash": "Bash",
        "grep": "Grep",
        "search": "Search",
        "glob": "Glob",
        "listfiles": "ListFiles",
        "todolistwrite": "TodoWrite",
        "todowrite": "TodoWrite",
        "websearch": "WebSearch",
        "webfetch": "WebFetch",
        "task": "Task",
        "semsearch": "SemanticSearch",
        "semanticsearch": "SemanticSearch",
        "readlints": "ReadLints",
        "git": "Git",
    }
    key = raw.lower()
    if key in mapping:
        return mapping[key]
    return raw[:1].upper() + raw[1:]


def _format_tool_arg(name: str, value: object) -> str:
    if isinstance(value, list):
        joined = ", ".join(str(v) for v in value[:3] if v)
        if len(value) > 3:
            joined += ", …"
        value_str = joined
    else:
        value_str = str(value)
    if name in {"Read", "View", "Write", "Create", "Edit", "Replace", "StrReplace", "MultiEdit", "ListFiles"}:
        try:
            path = Path(value_str)
            if path.name:
                value_str = str(path)
        except Exception:
            pass
    if len(value_str) > 100:
        value_str = value_str[:97] + "…"
    return value_str


def _format_tool_use(name: str, input_data: dict) -> str:
    normalized = _normalize_tool_name(name)
    if normalized in {"Shell", "Bash", "Execute"}:
        command = str(input_data.get("command", "")).strip()
        if command:
            lowered = command.lower()
            if " git " in f" {lowered} " or lowered.startswith("git "):
                normalized = "Git"
    label_info = _TOOL_LABELS.get(normalized)
    if label_info is None:
        return normalized or name
    emoji, verb, keys = label_info
    if normalized == "Grep":
        pattern = input_data.get("pattern") or input_data.get("query")
        path = input_data.get("path") or input_data.get("directory")
        if pattern and path:
            return _tool_line(
                emoji,
                f"{verb} {_format_tool_arg(normalized, pattern)} in {_format_tool_arg('Read', path)}",
            )
    if normalized == "Glob":
        pattern = input_data.get("pattern") or input_data.get("glob_pattern") or input_data.get("globPattern")
        target = input_data.get("path") or input_data.get("directory") or input_data.get("targetDirectory")
        if pattern and target:
            return _tool_line(
                emoji,
                f"{verb} {_format_tool_arg(normalized, pattern)} in {_format_tool_arg('Read', target)}",
            )
    if normalized == "SemanticSearch":
        query = input_data.get("query")
        targets = input_data.get("targetDirectories")
        if query and targets:
            return _tool_line(emoji, f"{verb} {_format_tool_arg(normalized, query)}")
    for key in keys:
        val = input_data.get(key, "")
        if val:
            return _tool_line(emoji, f"{verb} {_format_tool_arg(normalized, val)}")
    return _tool_line(emoji, verb)


def _format_tool_use_with_description(name: str, input_data: dict, description: str | None = None) -> str:
    formatted = _format_tool_use(name, input_data)
    desc = (description or "").strip()
    if not desc:
        return formatted
    normalized = _normalize_tool_name(name)
    if normalized in {"Shell", "Bash", "Execute", "Git"}:
        return f"{formatted} ({desc})"
    return formatted


def parse_stream_event(chunk: str, *, full_text: bool = False) -> tuple[str, str] | None:
    """Parse a stream-json chunk and return ``(event_type, display_text)`` or
    *None* to skip. ``event_type`` is ``"tool"``, ``"text"``, ``"message"``,
    or ``"boundary"``.

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
                raw_text = block.get("text", "")
                if isinstance(raw_text, str) and raw_text.strip():
                    t = raw_text if full_text else raw_text.strip()
                    parts.append(t)
        if parts:
            combined = "\n".join(parts) if full_text else " ".join(parts).split("\n")[0][:160]
            return ("message", combined) if combined.strip() else None
        return None

    if typ == "thinking":
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
        raw_name = data.get("name", "") or data.get("tool", "")
        raw_input = data.get("input", {}) or data.get("arguments", {})
        raw_description = data.get("description", "")
        tool_payload = data.get("tool_call", {})
        if isinstance(tool_payload, dict) and tool_payload:
            nested_name, nested_value = next(iter(tool_payload.items()))
            if isinstance(nested_value, dict):
                raw_name = raw_name or _normalize_tool_name(nested_name)
                raw_input = nested_value.get("args", raw_input)
                raw_description = nested_value.get("description", raw_description)
        return (
            "tool",
            _format_tool_use_with_description(
                raw_name,
                raw_input if isinstance(raw_input, dict) else {},
                raw_description if isinstance(raw_description, str) else None,
            ),
        )

    if typ in ("message_start", "message_stop", "content_block_stop", "result"):
        return ("boundary", "")

    if typ in ("system", "tool_result", "ping", "message_delta"):
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


_LATEX_SYMBOLS: dict[str, str] = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ",
    r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ",
    r"\sigma": "σ", r"\tau": "τ", r"\phi": "φ", r"\varphi": "φ",
    r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
    r"\Psi": "Ψ", r"\Omega": "Ω",
    r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇",
    r"\sum": "Σ", r"\prod": "Π", r"\int": "∫",
    r"\cdot": "·", r"\odot": "⊙", r"\otimes": "⊗", r"\oplus": "⊕",
    r"\times": "×", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈",
    r"\equiv": "≡", r"\sim": "∼", r"\propto": "∝",
    r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
    r"\subseteq": "⊆", r"\supseteq": "⊇",
    r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
    r"\forall": "∀", r"\exists": "∃", r"\neg": "¬",
    r"\wedge": "∧", r"\vee": "∨",
    r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐", r"\leftrightarrow": "↔", r"\mapsto": "↦",
    r"\to": "→",
    r"\ldots": "…", r"\cdots": "⋯", r"\dots": "…",
    r"\langle": "⟨", r"\rangle": "⟩",
    r"\ell": "ℓ", r"\hbar": "ℏ",
}
_LATEX_SORTED = sorted(_LATEX_SYMBOLS.items(), key=lambda x: -len(x[0]))

_SUPERSCRIPTS = str.maketrans(
    "0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ",
)
_SUBSCRIPTS = str.maketrans(
    "0123456789+-=()aehijklmnoprstuvx",
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
)


def _translate_script(content: str, table: dict[int, int]) -> str | None:
    """Translate *content* using *table*, returning None if any char has no mapping."""
    converted = content.translate(table)
    if converted == content:
        return None
    if any(ord(c) not in table for c in content):
        return None
    return converted


def _apply_scripts(text: str) -> str:
    """Convert ^{...}, _{...}, ^X, _X to Unicode super/subscripts (math context)."""
    def _braced(m: re.Match, table: dict[int, int]) -> str:
        return _translate_script(m.group(1), table) or m.group(0)

    def _single(m: re.Match, table: dict[int, int]) -> str:
        return _translate_script(m.group(1), table) or m.group(0)

    text = re.sub(r"\^\{([^}]+)\}", lambda m: _braced(m, _SUPERSCRIPTS), text)
    text = re.sub(r"_\{([^}]+)\}", lambda m: _braced(m, _SUBSCRIPTS), text)
    text = re.sub(r"\^([0-9a-zA-Z])", lambda m: _single(m, _SUPERSCRIPTS), text)
    text = re.sub(r"_([0-9a-zA-Z])", lambda m: _single(m, _SUBSCRIPTS), text)
    return text


def _apply_scripts_safe(text: str) -> str:
    """Convert scripts outside math delimiters using conservative heuristics.

    Only converts single-letter-variable subscripts/superscripts (``x_j``,
    ``A'^2``) and braced forms (``x_{ij}``).  Multi-letter identifiers like
    ``merge_like_terms`` are left untouched.
    """
    def _braced(m: re.Match, table: dict[int, int]) -> str:
        return _translate_script(m.group(1), table) or m.group(0)

    text = re.sub(r"\^\{([^}]+)\}", lambda m: _braced(m, _SUPERSCRIPTS), text)
    text = re.sub(r"_\{([^}]+)\}", lambda m: _braced(m, _SUBSCRIPTS), text)

    def _safe_sub(m: re.Match) -> str:
        base, ch = m.group(1), m.group(2)
        return base + (_translate_script(ch, _SUBSCRIPTS) or f"_{ch}")

    def _safe_sup(m: re.Match) -> str:
        base, ch = m.group(1), m.group(2)
        return base + (_translate_script(ch, _SUPERSCRIPTS) or f"^{ch}")

    text = re.sub(r"(?<![a-zA-Z])([a-zA-Z]'?)_([0-9a-zA-Z])(?![a-zA-Z_])", _safe_sub, text)
    text = re.sub(r"(?<![a-zA-Z])([a-zA-Z]'?)\^([0-9a-zA-Z])(?![a-zA-Z])", _safe_sup, text)
    return text


def _process_math_content(content: str) -> str:
    """Apply all LaTeX-to-Unicode conversions to text inside math delimiters."""
    content = re.sub(r"\\t?frac\{([^}]*)\}\{([^}]*)\}", r"\1/\2", content)
    content = re.sub(r"\\t?frac(\d)(\d)", r"\1/\2", content)
    for cmd, sym in _LATEX_SORTED:
        content = content.replace(cmd, sym)
    content = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathcal|mathbb|operatorname)\{([^}]*)\}",
        r"\1", content,
    )
    content = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b\s*", "", content)
    content = _apply_scripts(content)
    return content


def _strip_latex(text: str) -> str:
    """Convert LaTeX math notation to readable Unicode for terminal display."""
    text = re.sub(r"\\\((.+?)\\\)", lambda m: _process_math_content(m.group(1)), text)
    text = re.sub(r"\\\[(.+?)\\\]", lambda m: _process_math_content(m.group(1)), text)
    for cmd, sym in _LATEX_SORTED:
        text = text.replace(cmd, sym)
    text = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathcal|mathbb|operatorname)\{([^}]*)\}",
        r"\1", text,
    )
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b\s*", "", text)
    parts = re.split(r"(`[^`]+`)", text)
    text = "".join(
        _apply_scripts_safe(part) if not part.startswith("`")
        else "`" + _apply_scripts_safe(part[1:-1]) + "`"
        for part in parts
    )
    return text


def _inline_md_to_rich(text: str) -> str:
    """Convert inline Markdown (bold, code) to Rich markup.

    Input must already be escaped via ``rich.markup.escape``.
    """
    text = re.sub(r"\*\*`([^`]+)`\*\*", r"[bold cyan]\1[/bold cyan]", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", text)
    text = re.sub(r"`([^`]+)`", r"[cyan]\1[/cyan]", text)
    return text


def _markup_text(text: str) -> Text:
    return Text.from_markup(_inline_md_to_rich(_rich_escape(_strip_latex(text))))


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
        table.add_column(Text.from_markup(_inline_md_to_rich(_rich_escape(_strip_latex(header)))), overflow="fold")
    for row in rows:
        table.add_row(*[Text.from_markup(_inline_md_to_rich(_rich_escape(_strip_latex(cell)))) for cell in row])
    return table


_CODE_REF_RE = re.compile(r"^(\d+):(\d+):(.+)$")


def _resolve_code_lexer(language: str, title_file: str, code: str) -> str:
    lang = language.strip().lower()
    normalized = _CODE_LANGUAGE_ALIASES.get(lang, lang)
    if normalized and not _CODE_REF_RE.match(normalized):
        return normalized
    first_line = code.lstrip().splitlines()[0].strip() if code.strip() else ""
    if first_line.startswith("#!"):
        if "python" in first_line:
            return "python"
        if any(shell in first_line for shell in ("bash", "sh", "zsh")):
            return "bash"
    if title_file:
        ext = Path(title_file).suffix.lstrip(".")
        if ext in _CODE_LANGUAGE_ALIASES:
            return _CODE_LANGUAGE_ALIASES[ext]
        guessed = Syntax.guess_lexer(title_file, code)
        if guessed and guessed.lower() != "text":
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

    m = _CODE_REF_RE.match(language.strip())
    if m:
        start_line = int(m.group(1))
        title_file = m.group(3).strip()
        language = ""
    elif lines:
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
        theme=_CODE_THEME,
        code_width=None,
        word_wrap=True,
        line_numbers=show_nums,
        start_line=start_line,
        indent_guides=True,
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
        # expand=False: when True, Rich sizes to the scroll region width; Textual's
        # scrollbar occupies the right gutter and the panel border can draw into it,
        # producing a broken border/scrollbar seam on the first wrapped row.
        expand=False,
    )


def make_markup_panel(markup: str, *, title: str = "", expand: bool = True) -> Panel:
    content = Text.from_markup(markup) if markup else Text("")
    return Panel(
        content,
        box=box.ROUNDED,
        border_style=_SURFACE_BORDER,
        style=f"on {_SURFACE_BG}",
        title=title,
        title_align="left",
        padding=(0, 2),
        expand=expand,
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
            renderables.append(Text.from_markup(f"[bold]{_inline_md_to_rich(_rich_escape(_strip_latex(stripped[4:])))}[/bold]"))
            continue
        if stripped.startswith("## "):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(Text.from_markup(f"[bold]{_inline_md_to_rich(_rich_escape(_strip_latex(stripped[3:])))}[/bold]"))
            continue
        if stripped.startswith("# "):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(
                Text.from_markup(
                    f"[bold underline]{_inline_md_to_rich(_rich_escape(_strip_latex(stripped[2:])))}[/bold underline]"
                )
            )
            continue

        if re.match(r"^[-*_]{3,}$", stripped):
            _append_paragraph(renderables, paragraph_lines)
            renderables.append(Rule(style="dim"))
            continue

        m = re.match(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$", line)
        if m:
            _append_paragraph(renderables, paragraph_lines)
            depth = len(m.group(1)) // 2
            indent = "  " * depth
            checked = m.group(2).lower() == "x"
            item_text = _inline_md_to_rich(_rich_escape(_strip_latex(m.group(3))))
            marker = "[green]☒[/green]" if checked else "[dim]☐[/dim]"
            if checked:
                item_text = f"[dim strike]{item_text}[/dim strike]"
            renderables.append(Text.from_markup(f"{indent}{marker} {item_text}"))
            continue

        m = re.match(r"^(\s*)([-*+])\s", line)
        if m:
            _append_paragraph(renderables, paragraph_lines)
            depth = len(m.group(1)) // 2
            indent = "  " * depth
            item_text = _inline_md_to_rich(_rich_escape(_strip_latex(line[m.end() :])))
            renderables.append(Text.from_markup(f"{indent}[dim]•[/dim] {item_text}"))
            continue

        m = re.match(r"^(\s*)(\d+)\.\s", line)
        if m:
            _append_paragraph(renderables, paragraph_lines)
            depth = len(m.group(1)) // 2
            indent = "  " * depth
            item_text = _inline_md_to_rich(_rich_escape(_strip_latex(line[m.end() :])))
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


def extract_error_excerpt(summary: str, error_text: str = "") -> str:
    """Return a short, user-facing error line from a traceback or crash summary."""
    for raw in reversed(error_text.splitlines()):
        line = raw.strip()
        if not line or line.startswith("During task with name"):
            continue
        return line
    cleaned = summary.strip()
    if cleaned.lower().startswith("cycle crashed:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    return cleaned
