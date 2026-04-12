"""File-based memory layout, Tier A state, and episodes."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lab import helpers

SYSTEM_TIER_A_FILE = "system.md"
LEGACY_PROJECT_BRIEF = "project_brief.md"
# Collapsed one-line excerpt from worker ``packet.md`` in ``system.md`` Recent activity.
_SYSTEM_RECENT_PACKET_SNIPPET_CHARS = 280

TIER_A_FILES = [
    "extended_memory_index.md",
    "research_idea.md",  # full research brief (goals + success criteria)
    "preferences.md",
    SYSTEM_TIER_A_FILE,
    "roadmap.md",
    "immediate_plan.md",
    "status.md",
    "context_summary.md",
    "skills_index.md",
    "lessons.md",
    "user_instructions.md",
]

IMMEDIATE_PLAN_CHECKLIST_HEADER = "## Checklist"


def state_dir(researcher_root: Path) -> Path:
    """Tier A operating memory directory."""
    return researcher_root / "state"


def _project_dir_for_system_tier(researcher_root: Path, project_dir: Path | None) -> Path:
    """Resolve project directory for path lines in ``system.md``."""
    if project_dir is not None:
        return project_dir
    return researcher_root.parent


def format_system_tier_markdown(
    researcher_root: Path,
    project_dir: Path | None,
    *,
    recent_activity: str,
) -> str:
    """Full body for ``system.md`` (paths + recent run tail). Only called from lab code."""
    pd = _project_dir_for_system_tier(researcher_root, project_dir)
    recent = (recent_activity or "").strip() or "*(no run events yet)*"
    return (
        "# System\n\n"
        "The **lab runtime** overwrites this file with workspace paths and a short tail of SQLite "
        "`run_events`. Workers must **not** edit this file.\n\n"
        "## Paths\n\n"
        f"- Implementation directory: `{pd}`\n"
        f"- Tier A directory: `{state_dir(researcher_root)}`\n"
        f"- Reports and demos: prefer `{pd / 'reports'}`\n\n"
        "## Recent activity\n\n"
        "Recent rows from `run_events` (oldest first in this list): orchestrator lines show **task** and "
        "**kwargs** (e.g. critic `persona`); worker lines show **objective** and a truncated **prompt** "
        "from `packet.md` when available. Routing summaries live in `context_summary.md`.\n\n"
        f"{recent}\n"
    )


def write_system_tier_file(
    researcher_root: Path,
    project_dir: Path | None,
    *,
    recent_activity: str,
) -> None:
    """Overwrite ``system.md`` (system-owned Tier A)."""
    p = state_dir(researcher_root) / SYSTEM_TIER_A_FILE
    helpers.ensure_dir(p.parent)
    helpers.write_text(p, format_system_tier_markdown(researcher_root, project_dir, recent_activity=recent_activity))


def _decode_run_event_payload(raw: object) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        out = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def _format_worker_kwargs_compact(kwargs: Any) -> str:
    if not isinstance(kwargs, dict) or not kwargs:
        return ""
    parts: list[str] = []
    for k in sorted(kwargs.keys()):
        v = kwargs[k]
        s = str(v).replace("\n", " ").strip()
        if len(s) > 80:
            s = s[:77] + "..."
        parts.append(f"{k}={s!r}")
    return ", ".join(parts)


def _packet_prompt_snippet(researcher_root: Path, packet_path: str | None, max_chars: int) -> str:
    if not packet_path or not str(packet_path).strip():
        return ""
    rel = str(packet_path).strip().lstrip("/")
    p = researcher_root / rel
    if not p.is_file():
        return ""
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    one_line = " ".join(raw.split())
    if len(one_line) > max_chars:
        return one_line[: max_chars - 3] + "..."
    return one_line


def _format_system_recent_line(
    researcher_root: Path,
    r: Any,
) -> str:
    """One markdown line for ``system.md`` (no run ``summary`` — use task, kwargs, packet excerpt)."""
    kind = str(r["kind"] or "")
    worker = str(r["worker"] or "")
    cycle = int(r["cycle"])
    head = f"- cycle **{cycle}** `{kind}` **`{worker}`**"
    payload = _decode_run_event_payload(r["payload_json"] if "payload_json" in r.keys() else None)

    if kind == "orchestrator":
        bits: list[str] = []
        task = str(r["task"] or "").replace("\n", " ").strip()
        if task:
            if len(task) > 220:
                task = task[:217] + "..."
            bits.append(f"task: {task}")
        wk = payload.get("worker_kwargs")
        kw = _format_worker_kwargs_compact(wk)
        if kw:
            bits.append(f"kwargs: {kw}")
        return head + ((" — " + " — ".join(bits)) if bits else "")

    # worker (or other kinds): objective from DB task + packet head
    bits = []
    task = str(r["task"] or "").replace("\n", " ").strip()
    if task:
        if len(task) > 180:
            task = task[:177] + "..."
        bits.append(f"objective: {task}")
    pkt = r["packet_path"] if "packet_path" in r.keys() else None
    snip = _packet_prompt_snippet(researcher_root, str(pkt) if pkt else None, _SYSTEM_RECENT_PACKET_SNIPPET_CHARS)
    if snip:
        bits.append(f"prompt: {snip}")
    return head + ((" — " + " — ".join(bits)) if bits else "")


def refresh_system_tier_from_db(
    researcher_root: Path,
    project_dir: Path | None,
    db_path: Path,
    *,
    limit: int = 40,
) -> None:
    """Rebuild ``system.md`` from paths + last *limit* ``run_events`` rows (best-effort)."""
    try:
        from lab import db as db_mod

        conn = db_mod.connect_db(db_path)
        try:
            rows = db_mod.recent_run_events(conn, limit=limit)
        finally:
            conn.close()
        lines = [_format_system_recent_line(researcher_root, r) for r in reversed(rows)]
        recent = "\n".join(lines) if lines else "*(no run events yet)*"
        write_system_tier_file(researcher_root, project_dir, recent_activity=recent)
    except Exception:
        pass


def _remove_legacy_project_brief(researcher_root: Path) -> None:
    legacy = state_dir(researcher_root) / LEGACY_PROJECT_BRIEF
    if legacy.is_file():
        try:
            legacy.unlink()
        except OSError:
            pass


def worker_diff_baseline_path(researcher_root: Path) -> Path:
    """JSON snapshot of the project tree at worker start (for live TUI diffs)."""
    return researcher_root / "worker_diff_baseline.json"


def write_worker_diff_baseline(researcher_root: Path, payload: dict[str, Any]) -> None:
    """Persist baseline; overwritten at each worker start."""
    p = worker_diff_baseline_path(researcher_root)
    helpers.ensure_dir(p.parent)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_worker_diff_baseline(researcher_root: Path) -> dict[str, Any] | None:
    """Load baseline dict, or None if missing / invalid."""
    p = worker_diff_baseline_path(researcher_root)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def clear_worker_diff_baseline(researcher_root: Path) -> None:
    """Remove baseline after the worker run completes."""
    p = worker_diff_baseline_path(researcher_root)
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def _snapshot_line_count(project_dir: Path, relpath: str) -> int:
    fpath = project_dir / relpath
    try:
        if fpath.is_file() and fpath.stat().st_size < 500_000:
            return fpath.read_bytes().count(b"\n")
    except OSError:
        pass
    return 0


def _git_repo_ok(project_dir: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_dir, capture_output=True, text=True, timeout=3,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def current_git_branch(project_dir: Path) -> str:
    """Return ``git rev-parse --abbrev-ref HEAD``, or empty if not a git repo / on error."""
    if not _git_repo_ok(project_dir):
        return ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode != 0:
            return ""
        return (r.stdout or "").strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def capture_worker_diff_baseline(project_dir: Path, cycle: int) -> dict[str, Any] | None:
    """Snapshot working tree at worker start for live TUI diffs (see :func:`write_worker_diff_baseline`).

    Prefers a ``git stash create`` tree object so diffs are vs the exact tree at start, not
    vs ``HEAD``. Falls back to ``HEAD`` only when no stash commit is created.
    """
    if not _git_repo_ok(project_dir):
        return None
    try:
        rh = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, timeout=3,
        )
        head = rh.stdout.strip() if rh.returncode == 0 else None

        ru = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard"],
            cwd=project_dir, capture_output=True, text=True, timeout=5,
        )
        untracked_lines: dict[str, int] = {}
        if ru.returncode == 0 and ru.stdout.strip():
            for fname in ru.stdout.strip().splitlines():
                fn = fname.strip().replace("\\", "/")
                if fn:
                    untracked_lines[fn] = _snapshot_line_count(project_dir, fn)

        tracked_lines: dict[str, int] | None = None
        tree: str | None = None
        if head:
            rs = subprocess.run(
                ["git", "stash", "create", "--include-untracked"],
                cwd=project_dir, capture_output=True, text=True, timeout=30,
            )
            if rs.returncode == 0 and rs.stdout.strip():
                stash = rs.stdout.strip().splitlines()[-1].strip()
                rt = subprocess.run(
                    ["git", "rev-parse", f"{stash}^{{tree}}"],
                    cwd=project_dir, capture_output=True, text=True, timeout=3,
                )
                if rt.returncode == 0 and rt.stdout.strip():
                    tree = rt.stdout.strip()
        else:
            rt = subprocess.run(
                ["git", "ls-files"],
                cwd=project_dir, capture_output=True, text=True, timeout=5,
            )
            if rt.returncode == 0 and rt.stdout.strip():
                tracked_lines = {}
                for fname in rt.stdout.strip().splitlines():
                    fn = fname.strip().replace("\\", "/")
                    if fn:
                        tracked_lines[fn] = _snapshot_line_count(project_dir, fn)

        return {
            "cycle": cycle,
            "tree": tree,
            "head": head,
            "untracked_lines": untracked_lines,
            "tracked_lines": tracked_lines,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def experiments_dir(project_dir: Path) -> Path:
    """Experiment artifacts live in the project directory (visible and git-checkpointed)."""
    return project_dir / "experiments"


def _clear_dir_contents(path: Path, *, keep: frozenset[str] = frozenset()) -> None:
    if not path.exists():
        return
    for child in list(path.iterdir()):
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def reset_runtime_artifacts(
    researcher_root: Path,
    *,
    preserved_research_idea_md: str,
    preserved_preferences_md: str,
    project_dir: Path | None = None,
) -> None:
    """Remove episodic memory and Tier A except ``research_idea.md`` and ``preferences.md``."""
    _clear_dir_contents(extended_dir(researcher_root))
    _clear_dir_contents(researcher_root / "memory" / "branch")
    _clear_dir_contents(episodes_dir(researcher_root), keep=frozenset({"README.md"}))
    _clear_dir_contents(skills_dir(researcher_root))
    if project_dir is not None:
        _clear_dir_contents(experiments_dir(project_dir))

    sd = state_dir(researcher_root)
    helpers.ensure_dir(sd)
    _remove_legacy_project_brief(researcher_root)
    for name in TIER_A_FILES:
        p = sd / name
        if name == "research_idea.md":
            c = preserved_research_idea_md
            if not c.endswith("\n"):
                c += "\n"
            helpers.write_text(p, c)
        elif name == "preferences.md":
            c = preserved_preferences_md
            if not c.endswith("\n"):
                c += "\n"
            helpers.write_text(p, c)
        elif name == SYSTEM_TIER_A_FILE:
            write_system_tier_file(
                researcher_root,
                project_dir,
                recent_activity="*(memory reset — run the scheduler to repopulate)*",
            )
        else:
            helpers.write_text(p, _default_tier_a_content(name))
    _ensure_episodes_readme(researcher_root)
    clear_worker_diff_baseline(researcher_root)


def extended_dir(researcher_root: Path) -> Path:
    """Long-form supplementary memory: logs, experiments, extra context."""
    return researcher_root / "memory" / "extended"


def episodes_dir(researcher_root: Path) -> Path:
    """Per-cycle worker artifacts: packet.md + worker_output.json under cycle_*/<worker>/."""
    return researcher_root / "memory" / "episodes"


def episodes_cycle_relpath(*, cycle: int, worker: str) -> str:
    """Path under researcher root to one worker episode directory (POSIX-style for DB / logs)."""
    return f"memory/episodes/cycle_{cycle:06d}/{worker}"


def episode_cycle_dir(researcher_root: Path, cycle: int, worker: str) -> Path:
    """Absolute path to cycle_<n>/<worker>/ (packet.md, worker_output.json)."""
    return episodes_dir(researcher_root) / f"cycle_{cycle:06d}" / worker


def skills_dir(researcher_root: Path) -> Path:
    """Reusable skill writeups (markdown), indexed from Tier A."""
    return researcher_root / "memory" / "skills"


def ensure_memory_layout(researcher_root: Path, *, project_dir: Path | None = None) -> None:
    """Create dirs and empty Tier A files if missing."""
    for sub in (
        "state",
        "memory/extended",
        "memory/branch",
        "memory/episodes",
        "memory/skills",
    ):
        helpers.ensure_dir(researcher_root / sub)
    _remove_legacy_project_brief(researcher_root)
    # experiments/ under project_dir is created on first experiment (see experiments.new_experiment_id).
    for name in TIER_A_FILES:
        p = state_dir(researcher_root) / name
        if not p.exists():
            if name == SYSTEM_TIER_A_FILE:
                write_system_tier_file(
                    researcher_root,
                    project_dir,
                    recent_activity="*(no run events yet — start the scheduler)*",
                )
            else:
                helpers.write_text(p, _default_tier_a_content(name))
    _ensure_episodes_readme(researcher_root)


def _ensure_episodes_readme(researcher_root: Path) -> None:
    """Document what episodes/ stores (not full message transcripts)."""
    p = episodes_dir(researcher_root) / "README.md"
    if not p.exists():
        helpers.write_text(p, _episodes_readme_text())


def _episodes_readme_text() -> str:
    return (
        "# Episodes\n\n"
        "Each **worker run** is stored under `cycle_<n>/<worker_name>/`:\n\n"
        "- `packet.md` — full markdown context passed to the worker CLI\n"
        "- `worker_output.json` — stdout, stderr, parsed result, exit metadata\n\n"
        "The rolling catalog is **`index.md`** (worker type, task, orchestrator reason, links). "
        "The SQLite **`run_events`** table remains the canonical timeline; this folder is the "
        "durable artifact tree for inspection and debugging.\n"
    )


def _default_tier_a_content(name: str) -> str:
    """Seed content for Tier A files."""
    if name == "extended_memory_index.md":
        return _default_extended_memory_index()
    if name == "skills_index.md":
        return _default_skills_index()
    if name == "user_instructions.md":
        return (
            "# User instructions\n\n"
            "## New\n\n"
            "## In progress\n\n"
            "## Completed\n\n"
        )
    if name == "roadmap.md":
        return _default_plan_doc(
            title="Roadmap",
            role=(
                "End-to-end project roadmap from start to finish: phases, milestones, and major deliverables. "
                "One item here should typically match the scope of the current session’s work in immediate_plan.md."
            ),
        )
    if name == "immediate_plan.md":
        return _default_immediate_plan_doc()
    if name == "context_summary.md":
        return (
            "# Rolling context summary\n\n"
            "The **orchestrator** overwrites this each cycle with a compressed history: project facts, "
            "recent worker/tool outcomes, and patterns (e.g. loops). It is passed to the next orchestrator "
            "and worker runs.\n\n"
            "(No content yet.)\n"
        )
    if name == SYSTEM_TIER_A_FILE:
        return (
            "# System\n\n"
            "The **lab runtime** overwrites this file with workspace paths and recent `run_events`. "
            "Workers must **not** edit it.\n\n"
            "(Paths and activity appear after `ensure_memory_layout` with a project directory or once "
            "the scheduler runs.)\n"
        )
    return f"# {name.replace('_', ' ').replace('.md', '')}\n\n"


def _default_extended_memory_index() -> str:
    return """# Extended memory index

Index of long-form files under `.lab/memory/extended/`. This file is included **in full** in orchestrator and worker context alongside other Tier A files, so keep it concise and high-signal: path plus a short description, or a few one-line bullets, for what the full file contains. Use it to point from Tier A to longer logs, artifacts, findings, notes, or transcripts that are too large to inline. Layout rules are in the shared prompt (`MEMORY_AND_TIER_A` in `agents/shared_prompt.py`).

## `.lab/memory/extended/`

- *(path + what it contains / why it matters)*
"""



def _default_skills_index() -> str:
    return (
        "# Skills index\n\n"
        "List each skill file under `.lab/memory/skills/` with its path and purpose. "
        "Keep this table aligned with files on disk; `skill_writer` commonly does this, but any worker that adds or changes skills should update it.\n\n"
        "| Path | Purpose |\n"
        "|------|--------|\n"
        "| *(add rows as you add `.lab/memory/skills/*.md`)* | |\n\n"
    )


def _default_plan_doc(*, title: str, role: str) -> str:
    """Shared plan-shaped scaffold for roadmap.md and immediate_plan.md."""
    return (
        f"# {title}\n\n"
        f"<!-- {role} -->\n\n"
        "## Overview\n\n\n"
        f"{IMMEDIATE_PLAN_CHECKLIST_HEADER}\n\n"
        "- [ ] \n\n"
        "## Notes\n\n\n"
        "## Done when\n\n\n"
    )


def _default_immediate_plan_doc() -> str:
    """Scaffold ``immediate_plan.md`` with an empty ``## Checklist`` until workers fill it."""
    return (
        "# Immediate plan\n\n"
        "<!-- Low-level plan for the active task only—same shape as a Cursor or Claude Code "
        "plan (concrete steps, files, checks). Should map to a single roadmap item in "
        "roadmap.md when possible. -->\n\n"
        "## Overview\n\n\n"
        f"{IMMEDIATE_PLAN_CHECKLIST_HEADER}\n\n\n"
        "## Notes\n\n\n"
        "## Done when\n\n\n"
    )


def extract_checklist_section(text: str) -> str:
    """Return the canonical ``## Checklist`` section from a plan-shaped document."""
    body = (text or "").strip()
    if not body:
        return ""
    match = re.search(
        rf"(?ms)^[ \t]*{re.escape(IMMEDIATE_PLAN_CHECKLIST_HEADER)}(?:[ \t]+[^\n]*)?[ \t]*\n.*?(?=^[ \t]*##[ \t]+|\Z)",
        body,
    )
    return match.group(0).strip() if match else ""


def _normalize_legacy_steps_to_checklist(section: str) -> str:
    """Convert a legacy ``## Steps`` list block into checklist form."""
    lines = (section or "").splitlines()
    out: list[str] = [IMMEDIATE_PLAN_CHECKLIST_HEADER]
    for line in lines[1:]:
        stripped = line.lstrip()
        if not stripped:
            out.append("")
            continue
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith(("- [ ] ", "- [x] ", "- [X] ")):
            out.append(f"{indent}{stripped}")
            continue
        if stripped.startswith("- "):
            out.append(f"{indent}- [ ] {stripped[2:]}")
            continue
        out.append(line)
    normalized = "\n".join(out).strip()
    return normalized if normalized != IMMEDIATE_PLAN_CHECKLIST_HEADER else ""


def extract_immediate_plan_checklist(text: str) -> str:
    """Return the canonical ``## Checklist`` section from ``immediate_plan.md``."""
    return extract_checklist_section(text)


def extract_roadmap_checklist(text: str) -> str:
    """Return the roadmap checklist, with a fallback for legacy ``## Steps`` sections."""
    checklist = extract_checklist_section(text)
    if checklist:
        return checklist
    body = (text or "").strip()
    if not body:
        return ""
    match = re.search(r"(?ms)^[ \t]*##[ \t]+Steps[ \t]*\n.*?(?=^[ \t]*##[ \t]+|\Z)", body)
    if not match:
        return ""
    return _normalize_legacy_steps_to_checklist(match.group(0))


def write_user_instruction_new_section(researcher_root: Path, text: str) -> None:
    """Append a new bullet under ## New in user_instructions.md."""
    path = state_dir(researcher_root) / "user_instructions.md"
    content = helpers.read_text(path)
    if "## New" not in content:
        content = "# User instructions\n\n## New\n\n## In progress\n\n## Completed\n\n"
    # Append bullet immediately after "## New" header block
    lines = content.splitlines()
    out: list[str] = []
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if line.strip() == "## New" and not inserted:
            out.append(f"- {text.strip()}")
            inserted = True
    if not inserted:
        out.append("## New")
        out.append(f"- {text.strip()}")
    helpers.write_text(path, "\n".join(out) + "\n")


def user_instructions_new_has_pending(researcher_root: Path) -> bool:
    """True when ``user_instructions.md`` has non-empty ``- `` bullets under ``## New``."""
    path = state_dir(researcher_root) / "user_instructions.md"
    body = helpers.read_text(path, default="")
    if "## New" not in body:
        return False
    remainder = body.split("## New", 1)[1]
    section_lines: list[str] = []
    for line in remainder.splitlines():
        st = line.strip()
        if st.startswith("## ") and not st.startswith("###"):
            break
        section_lines.append(line)
    section = "\n".join(section_lines)
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("- "):
            rest = line[2:].strip()
            if rest:
                return True
    return False


def append_lesson(researcher_root: Path, text: str) -> None:  # noqa: dead – kept for agent use
    """Append a dated bullet to lessons.md (Tier A)."""
    path = state_dir(researcher_root) / "lessons.md"
    prev = helpers.read_text(path, default="# Lessons\n\n")
    line = text.strip()
    if not line:
        return
    block = f"- {line}\n"
    helpers.write_text(path, prev.rstrip() + "\n" + block)


def _episode_index_header() -> str:
    return (
        "# Episodes index\n\n"
        "Append-only catalog of worker runs: **worker** (subagent), **task**, **reason** (orchestrator routing), "
        "and links to **input** (`packet.md`) and **output** (`worker_output.json`). Paths are relative to this file.\n\n"
        "---\n\n"
    )


def append_episode_index_entry(
    researcher_root: Path,
    *,
    cycle: int,
    worker: str,
    task: str,
    reason: str,
    episode_relpath: str,
) -> None:
    """Append one worker episode block to memory/episodes/index.md."""
    idx = episodes_dir(researcher_root) / "index.md"
    helpers.ensure_dir(idx.parent)
    base = episode_relpath.strip().rstrip("/")
    prefix = "memory/episodes/"
    if base.startswith(prefix):
        rel = base[len(prefix) :]
    else:
        rel = base
    task_s = (task or "").replace("\n", " ").strip()
    reason_s = (reason or "").replace("\n", " ").strip()
    block = (
        f"\n### Cycle {cycle} — `{worker}`\n\n"
        f"- **Task:** {task_s}\n"
        f"- **Reason:** {reason_s}\n"
        f"- **Input:** [`packet.md`]({rel}/packet.md)\n"
        f"- **Output:** [`worker_output.json`]({rel}/worker_output.json)\n"
    )
    if not idx.exists():
        helpers.write_text(idx, _episode_index_header().rstrip() + "\n")
    prev = helpers.read_text(idx, default="")
    helpers.write_text(idx, prev.rstrip() + block + "\n")


def read_context_summary(researcher_root: Path) -> str:
    """Current rolling context file (may be empty before first orchestrator update)."""
    return helpers.read_text(state_dir(researcher_root) / "context_summary.md", default="")


def write_context_summary(researcher_root: Path, body: str) -> None:
    """Persist orchestrator-updated rolling context."""
    p = state_dir(researcher_root) / "context_summary.md"
    helpers.ensure_dir(p.parent)
    helpers.write_text(p, body)


def _clip_block(text: str, max_chars: int | None) -> str:
    """Return full text when ``max_chars`` is None, otherwise clip with notice."""
    if max_chars is None:
        return text + "\n"
    if len(text) <= max_chars:
        return text + "\n"
    return text[:max_chars] + "\n...[truncated]\n"


def _clip_tier_value(text: str, max_chars: int | None) -> str:
    """Tier A file body clip helper; ``None`` means no clipping."""
    if max_chars is None:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]\n"


def format_orchestrator_context(
    researcher_root: Path,
    *,
    tier: dict[str, str],
    current_branch: str,
    last_worker_output: str = "",
    previous_context_summary: str = "",
    prev_summary_max_chars: int | None = None,
    last_worker_max_chars: int | None = None,
    tier_file_max_chars: int | None = None,
    branch_memory_max_chars: int | None = None,
) -> str:
    """Tier A, rolling context, last worker output, branch memory.

    Limits are optional. ``None`` means no clipping in app code.
    """
    from lab import memory_extra as mx

    parts: list[str] = []
    prev = (previous_context_summary or "").strip()
    if prev:
        parts.append("## Previous context summary (merge and replace with updated context_summary in JSON)\n")
        parts.append(_clip_block(prev, prev_summary_max_chars))
    out = (last_worker_output or "").strip()
    if out:
        parts.append("## Last worker output (incorporate into context_summary)\n")
        parts.append(_clip_block(out, last_worker_max_chars))
    for k, v in tier.items():
        if k == "context_summary.md":
            continue
        parts.append(f"{k}:\n{_clip_tier_value(v, tier_file_max_chars)}\n")
    b = (current_branch or "").strip()
    if b:
        bm = mx.read_branch_memory(researcher_root, b)
        if bm.strip():
            parts.append(f"branch_memory[{b}]:\n{_clip_tier_value(bm, branch_memory_max_chars)}\n")
    return "\n".join(parts)


def load_tier_a_bundle(researcher_root: Path) -> dict[str, str]:
    """Load all Tier A files into a dict for packets."""
    out: dict[str, str] = {}
    for name in TIER_A_FILES:
        out[name] = helpers.read_text(state_dir(researcher_root) / name)
    return out
