"""File-based memory layout, Tier A state, and episodes."""

from __future__ import annotations

import shutil
from pathlib import Path

from research_lab import helpers


TIER_A_FILES = [
    "project_brief.md",
    "extended_memory_index.md",
    "research_idea.md",  # full research brief (goals + success criteria)
    "preferences.md",
    "roadmap.md",
    "immediate_plan.md",
    "status.md",
    "context_summary.md",
    "skills_index.md",
    "lessons.md",
    "user_instructions.md",
]


def state_dir(researcher_root: Path) -> Path:
    """Tier A operating memory directory."""
    return researcher_root / "data" / "runtime" / "state"


def research_idea_body_for_project_config(markdown: str) -> str:
    """Strip a leading Markdown H1 if present; used to sync ``[project].research_idea`` in TOML."""
    text = markdown.strip()
    if not text:
        return ""
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        return "\n".join(lines[1:]).lstrip("\n").rstrip()
    return text


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
    _clear_dir_contents(researcher_root / "data" / "runtime" / "memory" / "branch")
    _clear_dir_contents(episodes_dir(researcher_root), keep=frozenset({"README.md"}))
    _clear_dir_contents(skills_dir(researcher_root))
    if project_dir is not None:
        _clear_dir_contents(experiments_dir(project_dir))

    sd = state_dir(researcher_root)
    helpers.ensure_dir(sd)
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
        else:
            helpers.write_text(p, _default_tier_a_content(name))
    _ensure_episodes_readme(researcher_root)


def extended_dir(researcher_root: Path) -> Path:
    """Long-form supplementary memory: logs, experiments, extra context."""
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


def ensure_memory_layout(researcher_root: Path, *, project_dir: Path | None = None) -> None:
    """Create runtime dirs and empty Tier A files if missing."""
    base = researcher_root / "data" / "runtime"
    for sub in (
        "state",
        "memory/extended",
        "memory/branch",
        "memory/episodes",
        "memory/skills",
    ):
        helpers.ensure_dir(base / sub)
    if project_dir is not None:
        helpers.ensure_dir(experiments_dir(project_dir))
    for name in TIER_A_FILES:
        p = state_dir(researcher_root) / name
        if not p.exists():
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


def _default_extended_memory_index() -> str:
    return """# Extended memory index

Index of long-form files under `memory/extended/`. This file is included **in full** in orchestrator and worker context alongside other Tier A files, so keep it concise and high-signal: path plus a short description, or a few one-line bullets, for what the full file contains. Use it to point from Tier A to longer logs, artifacts, findings, notes, or transcripts that are too large to inline. Layout rules are in the shared prompt (`MEMORY_AND_TIER_A` in `agents/shared_prompt.py`).

## `memory/extended/`

- *(path + what it contains / why it matters)*
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
    from research_lab import memory_extra as mx

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
