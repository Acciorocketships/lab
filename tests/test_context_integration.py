"""Integration tests for context budgets and formatter behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab import helpers, memory, packets
from lab.config import RunConfig

LOG_DIR = Path(__file__).parent / "logs"


def _log(name: str, data: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _cfg(tmp_path: Path, **overrides: Any) -> RunConfig:
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "project",
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


def test_orchestrator_context_includes_full_oversized_tier_without_mechanical_clip(tmp_path: Path) -> None:
    """Large Tier A on disk is passed through verbatim in orchestrator context (compactor shrinks it earlier)."""
    memory.ensure_memory_layout(tmp_path)
    huge = "X" * 50_000
    helpers.write_text(memory.state_dir(tmp_path) / "roadmap.md", huge)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(tmp_path, tier=tier, current_branch="")
    pkt = packets.build_worker_packet(
        worker="planner",
        researcher_root=tmp_path,
        task="Plan",
    )

    assert "truncated from oversized Tier A file" not in ctx
    assert "truncated from oversized Tier A file" not in pkt
    assert ctx.count("X") == 50_000
    assert pkt.count("X") == 50_000

    _log("orchestrator_budget", {
        "ctx_len": len(ctx),
        "pkt_len": len(pkt),
        "roadmap_len": len(huge),
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


def test_context_growth_worker_packet_stays_capped(tmp_path: Path) -> None:
    """Tier A and summary grow over cycles; optional worker_packet_max_chars still bounds packets."""
    memory.ensure_memory_layout(tmp_path)
    cfg = _cfg(tmp_path, worker_packet_max_chars=24000)
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

        assert len(pkt) <= 24000 + 100  # small overhead from trim notice

    _log("context_growth", {"cycles": growth_log})


def test_orchestrator_preserves_full_context_summary_when_small(tmp_path: Path) -> None:
    """Previous context summary is not truncated for normal sizes."""
    memory.ensure_memory_layout(tmp_path)
    long_summary = "Important finding: " + "Z" * 10_000
    memory.write_context_summary(tmp_path, long_summary)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        previous_context_summary=long_summary,
    )

    prev_section_header = "## Previous context summary"
    assert prev_section_header in ctx
    assert ctx.count("Z") == 10_000
    assert "...[truncated]" not in ctx

    _log("context_summary_compression", {
        "original_len": len(long_summary),
        "ctx_total_len": len(ctx),
        "z_count": ctx.count("Z"),
    })
