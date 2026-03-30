"""File-based memory layout, Tier A state, extended refs, and episodes."""

from __future__ import annotations

import re
from pathlib import Path

from research_lab import helpers


TIER_A_FILES = [
    "project_brief.md",
    "memory_guide.md",
    "research_idea.md",
    "preferences.md",
    "acceptance_criteria.md",
    "roadmap.md",
    "immediate_plan.md",
    "status.md",
    "context_summary.md",
    "skills_index.md",
    "lessons.md",
    "user_instructions.md",
]

# Paths in Tier A text that point at memory/extended/*.md (for discovery only — not auto-inlined).
_EXTENDED_REF = re.compile(
    r"(?:data/runtime/)?memory/extended/([A-Za-z0-9][A-Za-z0-9_.-]*\.md)",
)


def state_dir(researcher_root: Path) -> Path:
    """Tier A operating memory directory."""
    return researcher_root / "data" / "runtime" / "state"


def extended_dir(researcher_root: Path) -> Path:
    """Long-form supplementary memory (formerly hot/): logs, experiments, extra context."""
    return researcher_root / "data" / "runtime" / "memory" / "extended"


def episodes_dir(researcher_root: Path) -> Path:
    """Per-cycle worker artifacts: packet.md + worker_output.json under cycle_*/<worker>/."""
    return researcher_root / "data" / "runtime" / "memory" / "episodes"


def episodes_cycle_relpath(*, cycle: int, worker: str) -> str:
    """Path under researcher root to one worker episode directory (POSIX-style for DB / logs)."""
    return f"data/runtime/memory/episodes/cycle_{cycle:06d}/{worker}"


def episode_cycle_dir(researcher_root: Path, cycle: int, worker: str) -> Path:
    """Absolute path to cycle_<n>/<worker>/ (packet.md, worker_output.json)."""
    return episodes_dir(researcher_root) / f"cycle_{cycle:06d}" / worker


def skills_dir(researcher_root: Path) -> Path:
    """Reusable skill writeups (markdown), indexed from Tier A."""
    return researcher_root / "data" / "runtime" / "memory" / "skills"


def ensure_memory_layout(researcher_root: Path) -> None:
    """Create runtime dirs and empty Tier A files if missing."""
    base = researcher_root / "data" / "runtime"
    for sub in (
        "state",
        "memory/extended",
        "memory/branch",
        "memory/episodes",
        "memory/skills",
        "experiments",
    ):
        helpers.ensure_dir(base / sub)
    _migrate_hot_to_extended(researcher_root)
    _migrate_tier_a_legacy_filenames(researcher_root)
    for name in TIER_A_FILES:
        p = state_dir(researcher_root) / name
        if not p.exists():
            helpers.write_text(p, _default_tier_a_content(name))
    _ensure_episodes_readme(researcher_root)


def _migrate_hot_to_extended(researcher_root: Path) -> None:
    """Rename legacy memory/hot/ to memory/extended/ and move files."""
    base = researcher_root / "data" / "runtime" / "memory"
    hot = base / "hot"
    ext = base / "extended"
    if not hot.exists():
        return
    helpers.ensure_dir(ext)
    for p in hot.iterdir():
        if p.is_file():
            dest = ext / p.name
            if not dest.exists():
                p.rename(dest)
    try:
        hot.rmdir()
    except OSError:
        pass


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
    if name == "memory_guide.md":
        return _default_memory_guide()
    if name == "skills_index.md":
        return _default_skills_index()
    if name == "user_instructions.md":
        return (
            "# User instructions\n\n"
            "## New\n\n"
            "(Instructions appended here by the console; they may be merged into the roadmap or handled as tasks.)\n\n"
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
        return _default_plan_doc(
            title="Immediate plan",
            role=(
                "Low-level plan for the active task only—same shape as a Cursor or Claude Code **plan** "
                "(concrete steps, files, checks). Should map to a single roadmap item in roadmap.md when possible."
            ),
        )
    if name == "context_summary.md":
        return (
            "# Rolling context summary\n\n"
            "The **orchestrator** overwrites this each cycle with a compressed history: project facts, "
            "recent worker/tool outcomes, and patterns (e.g. loops). It is passed to the next orchestrator "
            "and worker runs.\n\n"
            "(No content yet.)\n"
        )
    return f"# {name.replace('_', ' ').replace('.md', '')}\n\n"


def _default_memory_guide() -> str:
    return """# Memory conventions

## Tier A (`state/*.md`)

Keep every file **short and information-dense**. Prefer bullets and pointers over prose. If something is long but still useful (extra analysis, experiment logs, stack traces), put it under `memory/extended/<name>.md` and **link the path here** (e.g. `See details in memory/extended/run_2025_notes.md`). Workers see the link in Tier A and **read that file with their tools** when they need the full text — it is **not** pasted into every packet.

## Branch files (`memory/branch/<branch>.md`)

One file per **active** git branch name (slashes → `__`). It is **not** a second git — it is researcher state about that branch.

Maintain each file with:

- **Diverged from**: base commit SHA (or tag) this branch started from.
- **Purpose**: what this branch tests or explores.
- **Status and results**: current state and outcomes so far.

**When the branch merges to `main`:** delete its file (so the folder mirrors live branches). Workers may copy notes to `memory/extended/` first if they want a durable log.

**When a branch is abandoned or the approach failed:** delete the file and append the takeaway to `lessons.md` (not a separate “negative” store). Lifecycle is maintained by **workers** (see `agents/shared_prompt.py`), not by the Python orchestrator.

## Skills (`memory/skills/*.md`)

Reusable procedures and checklists. Maintain `skills_index.md` in Tier A with each skill’s path and a one-line description. The **skill_writer** worker creates/updates skill files and the index.

## Episodes (`memory/episodes/`)

Per worker run: **`index.md`** lists worker (subagent), orchestrator **task**, routing **reason**, and links to each run's **`packet.md`** (input) and **`worker_output.json`** (output). Cycle folders hold the files. See `episodes/README.md`.

## User instructions (`user_instructions.md`)

The console appends bullets under **`## New`**. Workers must **merge** that content into **`immediate_plan.md`** / **`roadmap.md`**, then **remove** it from **`## New`** (optional **`## In progress`** / **`## Completed`**). Do not leave **`## New`** populated once items are incorporated. The orchestrator prioritizes **planner** when **`## New`** has pending bullets. See `agents/shared_prompt.py`.

## `context_summary.md`

Orchestrator-maintained **rolling summary** for bounded LLM context (see also SQLite `run_events` for the full append-only log).
"""


def _default_skills_index() -> str:
    return (
        "# Skills index\n\n"
        "List each skill file under `memory/skills/` with its path and purpose. "
        "The skill_writer worker keeps this table aligned with files on disk.\n\n"
        "| Path | Purpose |\n"
        "|------|--------|\n"
        "| *(add rows as you add `memory/skills/*.md`)* | |\n\n"
    )


def _migrate_tier_a_legacy_filenames(researcher_root: Path) -> None:
    """Rename backlog.md / current_goal.md to roadmap.md / immediate_plan.md if present."""
    sd = state_dir(researcher_root)
    for old_name, new_name in (
        ("backlog.md", "roadmap.md"),
        ("current_goal.md", "immediate_plan.md"),
    ):
        old, new = sd / old_name, sd / new_name
        if old.exists() and not new.exists():
            old.rename(new)


def _default_plan_doc(*, title: str, role: str) -> str:
    """Shared plan-shaped scaffold for roadmap.md and immediate_plan.md."""
    return (
        f"# {title}\n\n"
        f"<!-- {role} -->\n\n"
        "## Overview\n\n\n"
        "## Steps\n\n"
        "- \n\n"
        "## Done when\n\n\n"
    )


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
    """True when ``user_instructions.md`` has actionable ``- `` bullets under ``## New`` (not the seed placeholder)."""
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
    placeholder = (
        "(Instructions appended here by the console; they may be merged into the roadmap or handled as tasks.)"
    )
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("- "):
            rest = line[2:].strip()
            if rest and rest != placeholder:
                return True
    return False


def append_lesson(researcher_root: Path, text: str) -> None:
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
    prefix = "data/runtime/memory/episodes/"
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


def discover_extended_filenames_from_text(*texts: str) -> list[str]:
    """Return unique extended/*.md basenames referenced in Tier A (or other) markdown."""
    seen: list[str] = []
    found: set[str] = set()
    for blob in texts:
        for m in _EXTENDED_REF.finditer(blob or ""):
            name = m.group(1)
            if name not in found:
                found.add(name)
                seen.append(name)
    return seen


def load_referenced_extended_bundle(researcher_root: Path, tier_bundle: dict[str, str]) -> dict[str, str]:
    """Load extended markdown files referenced from Tier A text (e.g. for tests or explicit bulk load)."""
    combined = "\n".join(tier_bundle.values())
    out: dict[str, str] = {}
    for name in discover_extended_filenames_from_text(combined):
        p = extended_dir(researcher_root) / name
        body = helpers.read_text(p, default="")
        if body.strip():
            out[name] = body
    return out


def referenced_extended_absolute_paths(researcher_root: Path, tier_bundle: dict[str, str]) -> list[Path]:
    """Sorted unique absolute paths to extended files linked from Tier A (file may be missing)."""
    combined = "\n".join(tier_bundle.values())
    seen: set[str] = set()
    out: list[Path] = []
    for name in discover_extended_filenames_from_text(combined):
        if name in seen:
            continue
        seen.add(name)
        out.append((extended_dir(researcher_root) / name).resolve())
    return sorted(out)


def format_extended_refs_for_orchestrator(researcher_root: Path, tier_bundle: dict[str, str]) -> str:
    """Short note for the orchestrator: which extended files Tier A links to (bodies not loaded)."""
    paths = referenced_extended_absolute_paths(researcher_root, tier_bundle)
    if not paths:
        return "referenced_extended_files: (none linked from Tier A)\n"
    lines = ["referenced_extended_files (paths only; not loaded into this prompt):"]
    for p in paths:
        lines.append(f"- {p}")
    return "\n".join(lines) + "\n"


def format_extended_refs_for_worker_packet(researcher_root: Path, tier_bundle: dict[str, str]) -> str:
    """Markdown for worker packets: researcher root + absolute paths; extended bodies are not inlined."""
    paths = referenced_extended_absolute_paths(researcher_root, tier_bundle)
    root = researcher_root.resolve()
    lines = [
        "## Extended memory (on demand)",
        "",
        "Tier A may reference `memory/extended/*.md`. Those files are **not** copied into this packet. "
        "When you need the full text, read the paths below with your tools (from the researcher tree).",
        "",
        f"**Researcher root:** `{root}`",
        "",
    ]
    if not paths:
        lines.append("*No `memory/extended/*.md` paths linked from Tier A.*")
        return "\n".join(lines) + "\n"
    lines.append("**Referenced files (absolute paths):**")
    lines.append("")
    for p in paths:
        lines.append(f"- `{p}`")
    return "\n".join(lines) + "\n"


def read_context_summary(researcher_root: Path) -> str:
    """Current rolling context file (may be empty before first orchestrator update)."""
    return helpers.read_text(state_dir(researcher_root) / "context_summary.md", default="")


def write_context_summary(researcher_root: Path, body: str) -> None:
    """Persist orchestrator-updated rolling context."""
    p = state_dir(researcher_root) / "context_summary.md"
    helpers.ensure_dir(p.parent)
    helpers.write_text(p, body)


def format_orchestrator_context(
    researcher_root: Path,
    *,
    tier: dict[str, str],
    current_branch: str,
    last_worker_output: str = "",
    previous_context_summary: str = "",
) -> str:
    """Tier A (truncated), rolling context, last worker output, extended pointers, branch memory."""
    from research_lab import memory_extra as mx

    parts: list[str] = []
    prev = (previous_context_summary or "").strip()
    if prev:
        parts.append("## Previous context summary (merge and replace with updated context_summary in JSON)\n")
        parts.append(prev[:8000] + ("\n" if len(prev) <= 8000 else "\n...[truncated]\n"))
    out = (last_worker_output or "").strip()
    if out:
        parts.append("## Last worker output (incorporate into context_summary)\n")
        parts.append(out[:12000] + ("\n" if len(out) <= 12000 else "\n...[truncated]\n"))
    for k, v in tier.items():
        if k == "context_summary.md":
            continue
        parts.append(f"{k}:\n{v[:4000]}\n")
    parts.append(format_extended_refs_for_orchestrator(researcher_root, tier))
    b = (current_branch or "").strip()
    if b:
        bm = mx.read_branch_memory(researcher_root, b)
        if bm.strip():
            parts.append(f"branch_memory[{b}]:\n{bm[:4000]}\n")
    return "\n".join(parts)


def load_tier_a_bundle(researcher_root: Path) -> dict[str, str]:
    """Load all Tier A files into a dict for packets."""
    out: dict[str, str] = {}
    for name in TIER_A_FILES:
        out[name] = helpers.read_text(state_dir(researcher_root) / name)
    return out
