"""Context packet assembly for worker CLIs; ranks and trims text to a budget."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab import helpers, memory
from lab import memory_extra

# Shared for all CLI workers (long-running commands, hangs).
_WORKER_RUNTIME_CONDUCT = """## Commands and long-running work

When you run shell commands, builds, tests, servers, or training: **watch the output**. If the process seems stuck (no
meaningful progress for a long time, or a clear hang), **stop it** (terminate the process), note what you saw, and
continue with a shorter or safer approach. Prefer timeouts or bounded runs where the tool supports them."""

_PACKET_TRUNCATION_NOTICE = "\n\n...[truncated for context budget]...\n\n"


def _trim_middle(text: str, max_chars: int, *, notice: str) -> str:
    """Trim from the middle so prompts keep both framing and recent state."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    notice_text = notice if len(notice) < max_chars else "\n...[truncated]...\n"
    keep = max_chars - len(notice_text)
    if keep <= 0:
        return text[:max_chars]
    head_chars = keep // 2
    tail_chars = keep - head_chars
    if tail_chars <= 0:
        return text[:head_chars] + notice_text
    return text[:head_chars] + notice_text + text[-tail_chars:]


def build_worker_packet(
    *,
    worker: str,
    researcher_root: Path,
    task: str,
    extra_sections: dict[str, str] | None = None,
    max_chars: int | None = None,
    current_branch: str = "",
) -> str:
    """Assemble markdown packet: role header, Tier A, extended path pointers, branch memory, task."""
    tier = memory.load_tier_a_bundle(researcher_root)
    roll = memory.read_context_summary(researcher_root).strip()
    parts: list[str] = [
        f"# Worker: {worker}\n",
        "## Objective\n",
        task.strip() + "\n",
    ]
    if roll:
        parts.append("## Rolling context summary\n")
        parts.append(roll + "\n")
    parts.append(_WORKER_RUNTIME_CONDUCT + "\n")
    parts.append("## Operating context\n")
    for name in memory.TIER_A_FILES:
        if name == "context_summary.md":
            continue
        parts.append(f"### {name}\n{tier.get(name, '')}\n")
    b = (current_branch or "").strip()
    if b:
        bm = memory_extra.read_branch_memory(researcher_root, b)
        if bm.strip():
            parts.append(f"### Branch memory (`{b}`)\n{bm}\n")
    if extra_sections:
        for title, body in extra_sections.items():
            if body:
                parts.append(f"## {title}\n{body}\n")
    text = "\n".join(parts)
    if max_chars is None:
        return text
    if len(text) <= max_chars:
        return text
    return _trim_middle(text, max_chars, notice=_PACKET_TRUNCATION_NOTICE)


def _packet_dir(researcher_root: Path, cycle: int, worker: str) -> Path:
    return memory.episode_cycle_dir(researcher_root, cycle, worker)


def write_packet_file(researcher_root: Path, cycle: int, worker: str, content: str) -> Path:
    """Persist packet under memory/episodes/cycle_xxx/worker/packet.md."""
    d = _packet_dir(researcher_root, cycle, worker)
    helpers.ensure_dir(d)
    p = d / "packet.md"
    helpers.write_text(p, content)
    return p


def write_worker_output_file(
    researcher_root: Path,
    cycle: int,
    worker: str,
    result: dict[str, Any],
) -> Path:
    """Persist CLI worker result next to packet.md (stdout, stderr, parsed JSON, exit metadata)."""
    d = _packet_dir(researcher_root, cycle, worker)
    helpers.ensure_dir(d)
    p = d / "worker_output.json"
    p.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return p


def write_agent_packet_file(researcher_root: Path, agent_id: int, content: str) -> Path:
    """Persist packet under memory/episodes/agent_xxx/agent/packet.md."""
    d = memory.episode_agent_dir(researcher_root, agent_id)
    helpers.ensure_dir(d)
    p = d / "packet.md"
    helpers.write_text(p, content)
    return p


def write_agent_output_file(
    researcher_root: Path,
    agent_id: int,
    result: dict[str, Any],
) -> Path:
    """Persist async ``/agent`` result next to its packet."""
    d = memory.episode_agent_dir(researcher_root, agent_id)
    helpers.ensure_dir(d)
    p = d / "worker_output.json"
    p.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return p
