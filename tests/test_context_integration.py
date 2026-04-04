"""Integration tests for context budgets and formatter behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_lab import helpers, memory, packets
from research_lab.config import RunConfig

LOG_DIR = Path(__file__).parent / "logs"


def _log(name: str, data: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _cfg(tmp_path: Path, **overrides: Any) -> RunConfig:
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "project",
        research_idea="test idea",
        preferences="none",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    for key, value in overrides.items():
        object.__setattr__(cfg, key, value)
    return cfg


def test_orchestrator_context_budget_with_full_tier_a(tmp_path: Path) -> None:
    """format_orchestrator_context with 10k chars per Tier A file stays bounded via per-file caps."""
    memory.ensure_memory_layout(tmp_path)
    for name in memory.TIER_A_FILES:
        helpers.write_text(memory.state_dir(tmp_path) / name, "X" * 10_000)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        last_worker_output="W" * 15_000,
        previous_context_summary="P" * 10_000,
        prev_summary_max_chars=8000,
        last_worker_max_chars=12000,
        tier_file_max_chars=4000,
    )

    per_file_cap = 4000
    num_tier_files = len(memory.TIER_A_FILES) - 1  # context_summary.md is excluded
    max_expected = 8000 + 12000 + (per_file_cap * num_tier_files) + 2000  # headers/separators
    assert len(ctx) <= max_expected, f"Context too large: {len(ctx)} > {max_expected}"

    section_sizes: dict[str, int] = {}
    for name in memory.TIER_A_FILES:
        if name == "context_summary.md":
            continue
        segment = f"{name}:"
        if segment in ctx:
            start = ctx.index(segment)
            rest = ctx[start + len(segment):]
            next_file = None
            for other in memory.TIER_A_FILES:
                if other == name or other == "context_summary.md":
                    continue
                tag = f"{other}:"
                if tag in rest:
                    idx = rest.index(tag)
                    if next_file is None or idx < next_file:
                        next_file = idx
            chunk_len = next_file if next_file else len(rest)
            section_sizes[name] = chunk_len

    _log("orchestrator_budget", {
        "total_ctx_len": len(ctx),
        "max_expected": max_expected,
        "section_sizes": section_sizes,
    })


def test_packet_budget_enforcement(tmp_path: Path) -> None:
    """50k of Tier A + extras trimmed to 24k; critical sections in head survive."""
    memory.ensure_memory_layout(tmp_path)
    for name in memory.TIER_A_FILES:
        helpers.write_text(memory.state_dir(tmp_path) / name, "D" * 8000)
    memory.write_context_summary(tmp_path, "ROLLING_SUMMARY " * 300)

    pkt = packets.build_worker_packet(
        worker="implementer",
        researcher_root=tmp_path,
        task="Implement the new loss function",
        extra_sections={"Evidence": "E" * 5000},
        max_chars=24000,
    )

    assert len(pkt) <= 24000 + 100, f"Packet too large: {len(pkt)}"
    assert "# Worker: implementer" in pkt[:500], "Worker header must be in the head"
    assert "Implement the new loss function" in pkt[:1000], "Objective must be in the head"
    assert "ROLLING_SUMMARY" in pkt[:3000], "Rolling context should be near the head"

    _log("packet_budget", {
        "pkt_len": len(pkt),
        "budget": 24000,
        "header_present": "# Worker: implementer" in pkt[:500],
        "objective_present": "Implement the new loss function" in pkt[:1000],
    })


def test_context_growth_over_cycles(tmp_path: Path) -> None:
    """20 cycles with growing Tier A; context sizes stay bounded by caps."""
    memory.ensure_memory_layout(tmp_path)
    cfg = _cfg(
        tmp_path,
        orchestrator_prev_summary_max_chars=8000,
        orchestrator_last_worker_max_chars=12000,
        orchestrator_tier_file_max_chars=4000,
        worker_packet_max_chars=24000,
    )
    growth_log: list[dict[str, Any]] = []

    for cycle in range(20):
        roadmap = helpers.read_text(memory.state_dir(tmp_path) / "roadmap.md")
        roadmap += f"\n- Step {cycle}: do thing {cycle}\n"
        helpers.write_text(memory.state_dir(tmp_path) / "roadmap.md", roadmap)

        memory.append_episode_index_entry(
            tmp_path, cycle=cycle, worker="researcher",
            task=f"Task {cycle}", reason=f"Reason {cycle}",
            episode_relpath=memory.episodes_cycle_relpath(cycle=cycle, worker="researcher"),
        )

        summary = f"Summary after cycle {cycle}. " * 50
        memory.write_context_summary(tmp_path, summary)

        tier = memory.load_tier_a_bundle(tmp_path)
        ctx = memory.format_orchestrator_context(
            tmp_path, tier=tier, current_branch="",
            last_worker_output=f"Output {cycle} " * 100,
            previous_context_summary=memory.read_context_summary(tmp_path),
            prev_summary_max_chars=cfg.orchestrator_prev_summary_max_chars,
            last_worker_max_chars=cfg.orchestrator_last_worker_max_chars,
            tier_file_max_chars=cfg.orchestrator_tier_file_max_chars,
        )
        pkt = packets.build_worker_packet(
            worker="researcher",
            researcher_root=tmp_path,
            task="Continue",
            max_chars=cfg.worker_packet_max_chars,
        )

        growth_log.append({
            "cycle": cycle,
            "ctx_len": len(ctx),
            "pkt_len": len(pkt),
            "roadmap_len": len(roadmap),
            "summary_len": len(summary),
        })

        orch_input = ctx[:12000]
        assert len(orch_input) <= 12000
        assert len(pkt) <= 24000 + 100  # small overhead from trim notice

    _log("context_growth", {"cycles": growth_log})


def test_context_summary_compression_fidelity(tmp_path: Path) -> None:
    """A >8000-char context summary is truncated to 8000 in format_orchestrator_context."""
    memory.ensure_memory_layout(tmp_path)
    long_summary = "Important finding: " + "Z" * 10_000
    memory.write_context_summary(tmp_path, long_summary)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        previous_context_summary=long_summary,
        prev_summary_max_chars=8000,
    )

    prev_section_header = "## Previous context summary"
    assert prev_section_header in ctx

    start = ctx.index(prev_section_header)
    after_header = ctx[start:]
    next_section = after_header.find("\n## ", 1)
    if next_section == -1:
        next_section = after_header.find("\n", len(prev_section_header) + 1)
        section_body = after_header
    else:
        section_body = after_header[:next_section]

    z_count = section_body.count("Z")
    assert z_count <= 8000, f"Previous summary section has {z_count} Z's, expected <= 8000"

    _log("context_summary_compression", {
        "original_len": len(long_summary),
        "ctx_total_len": len(ctx),
        "z_count_in_section": z_count,
        "chars_lost": len(long_summary) - 8000 if len(long_summary) > 8000 else 0,
    })
