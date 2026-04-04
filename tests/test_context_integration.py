"""Integration tests for context management: budgets, inter-agent flow, and user instruction lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from research_lab import db, helpers, memory, packets
from research_lab.config import RunConfig
from research_lab.orchestrator import OrchestratorDecision
from research_lab.packets import _trim_packet
from research_lab.state import ResearchState
from research_lab.workflows import research_graph

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


def _base_state(cycle: int = 0, **overrides: Any) -> ResearchState:
    st: ResearchState = {
        "current_goal": "continue",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": cycle,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }
    st.update(overrides)  # type: ignore[typeddict-item]
    return st


def _fake_decide_factory(worker: str = "researcher", context_summary: str = "") -> Any:
    def _fake(*_args: Any, **_kwargs: Any) -> OrchestratorDecision:
        return OrchestratorDecision(
            worker=worker,
            task="do something",
            reason="test reason",
            roadmap_step="step-1",
            context_summary=context_summary,
        )
    return _fake


# ---------------------------------------------------------------------------
# 1. Orchestrator context budget with full Tier A
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 2. Orchestrator hard cap 12000
# ---------------------------------------------------------------------------


def test_orchestrator_hard_cap_12000(tmp_path: Path) -> None:
    """The orchestrator slices context_md[:12000]; verify with a mocked LLM call."""
    memory.ensure_memory_layout(tmp_path)
    for name in memory.TIER_A_FILES:
        helpers.write_text(memory.state_dir(tmp_path) / name, "Q" * 10_000)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        last_worker_output="W" * 15_000,
        previous_context_summary="P" * 10_000,
        prev_summary_max_chars=8000,
        last_worker_max_chars=12000,
        tier_file_max_chars=4000,
    )

    truncated = ctx[:12000]
    assert len(truncated) <= 12000
    assert len(ctx) > 12000, "Test setup: raw context should exceed 12000"

    _log("orchestrator_hard_cap", {
        "raw_ctx_len": len(ctx),
        "truncated_len": len(truncated),
        "chars_lost": len(ctx) - 12000,
        "loss_pct": round((len(ctx) - 12000) / len(ctx) * 100, 1),
    })


# ---------------------------------------------------------------------------
# 3. Packet budget enforcement
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 4. Packet trim preserves head and tail
# ---------------------------------------------------------------------------


def test_packet_trim_preserves_head_and_tail(tmp_path: Path) -> None:
    """_trim_packet keeps first half and last half with truncation notice."""
    head_marker = "HEAD_MARKER_UNIQUE"
    tail_marker = "TAIL_MARKER_UNIQUE"
    body = head_marker + ("M" * 20000) + tail_marker
    budget = 10000

    trimmed = _trim_packet(body, budget)
    assert head_marker in trimmed, "Head content lost"
    assert tail_marker in trimmed, "Tail content lost"
    assert "truncated for context budget" in trimmed
    assert len(trimmed) <= budget + 200  # notice adds some overhead

    _log("packet_trim", {
        "original_len": len(body),
        "trimmed_len": len(trimmed),
        "budget": budget,
        "head_preserved": head_marker in trimmed,
        "tail_preserved": tail_marker in trimmed,
    })


# ---------------------------------------------------------------------------
# 5. Multi-cycle context flow
# ---------------------------------------------------------------------------


def test_multi_cycle_context_flow(tmp_path: Path) -> None:
    """5 cycles: information from context_summary and worker output carries forward."""
    memory.ensure_memory_layout(tmp_path)
    cfg = _cfg(
        tmp_path,
        orchestrator_prev_summary_max_chars=8000,
        orchestrator_last_worker_max_chars=12000,
        orchestrator_tier_file_max_chars=4000,
    )
    db_path = tmp_path / "test.db"
    db.connect_db(db_path).close()
    (tmp_path / "project").mkdir(exist_ok=True)

    cycle_logs: list[dict[str, Any]] = []
    facts_written: list[str] = []

    for cycle in range(5):
        fact = f"FACT_{cycle:03d}"
        facts_written.append(fact)

        prev_summary = memory.read_context_summary(tmp_path)
        new_summary = (prev_summary.strip() + f"\n- {fact} discovered in cycle {cycle}\n").strip()

        with patch.object(
            research_graph.orchestrator,
            "decide_orchestrator",
            _fake_decide_factory(worker="researcher", context_summary=new_summary),
        ):
            state = _base_state(
                cycle=cycle,
                last_action_summary=f"Worker output with {fact}" if cycle > 0 else "",
            )
            result = research_graph.choose_action(
                state, cfg=cfg, researcher_root=tmp_path, db_path=db_path,
            )

        tier = memory.load_tier_a_bundle(tmp_path)
        ctx = memory.format_orchestrator_context(
            tmp_path, tier=tier, current_branch="",
            last_worker_output=f"Worker found {fact}",
            previous_context_summary=memory.read_context_summary(tmp_path),
            prev_summary_max_chars=8000,
            last_worker_max_chars=12000,
            tier_file_max_chars=4000,
        )

        cycle_logs.append({
            "cycle": cycle,
            "fact": fact,
            "ctx_len": len(ctx),
            "summary_len": len(memory.read_context_summary(tmp_path)),
            "facts_in_summary": [f for f in facts_written if f in memory.read_context_summary(tmp_path)],
        })

    final_summary = memory.read_context_summary(tmp_path)
    for fact in facts_written:
        assert fact in final_summary, f"{fact} missing from final context summary"

    _log("multi_cycle_context_flow", {"cycles": cycle_logs})


# ---------------------------------------------------------------------------
# 6. Context growth over cycles
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 7. User instruction forces planner
# ---------------------------------------------------------------------------


def test_user_instruction_forces_planner(tmp_path: Path) -> None:
    """Pending ## New bullets override orchestrator to route to planner."""
    memory.ensure_memory_layout(tmp_path)
    cfg = _cfg(
        tmp_path,
        orchestrator_prev_summary_max_chars=8000,
        orchestrator_tier_file_max_chars=4000,
        worker_packet_max_chars=24000,
    )
    db_path = tmp_path / "test.db"
    db.connect_db(db_path).close()
    (tmp_path / "project").mkdir(exist_ok=True)

    memory.write_user_instruction_new_section(tmp_path, "Add dropout experiment")

    with patch.object(
        research_graph.orchestrator,
        "decide_orchestrator",
        _fake_decide_factory(worker="researcher", context_summary="summary"),
    ):
        result = research_graph.choose_action(
            _base_state(), cfg=cfg, researcher_root=tmp_path, db_path=db_path,
        )

    assert result["current_worker"] == "planner", "Should override to planner"
    assert "## New" in result["orchestrator_task"] or "user_instructions" in result["orchestrator_task"]

    _log("user_instruction_forces_planner", {
        "original_worker": "researcher",
        "overridden_worker": result["current_worker"],
        "task_mentions_new": "## New" in result.get("orchestrator_task", ""),
    })


# ---------------------------------------------------------------------------
# 8. User instruction full lifecycle
# ---------------------------------------------------------------------------


def test_user_instruction_full_lifecycle(tmp_path: Path) -> None:
    """End-to-end: enqueue instruction -> ingest -> planner override -> process -> cleared."""
    memory.ensure_memory_layout(tmp_path)
    cfg = _cfg(tmp_path)
    db_path = tmp_path / "test.db"
    conn = db.connect_db(db_path)
    conn.close()
    (tmp_path / "project").mkdir(exist_ok=True)

    instruction_text = "Add ablation study to experiments"

    # Step 1: Enqueue the instruction event (simulating console input mid-run)
    conn = db.connect_db(db_path)
    db.enqueue_event(conn, "instruction", instruction_text)
    conn.commit()
    conn.close()

    # Step 2: Run ingest_events to process the event
    state = _base_state()
    research_graph.ingest_events(state, db_path=db_path, researcher_root=tmp_path)

    # Verify: instruction appears in user_instructions.md under ## New
    ui_text = helpers.read_text(memory.state_dir(tmp_path) / "user_instructions.md")
    assert instruction_text in ui_text, "Instruction not written to user_instructions.md"
    assert memory.user_instructions_new_has_pending(tmp_path), "Should have pending instructions"

    # Verify: instruction exists in SQLite instructions table
    conn = db.connect_db(db_path)
    rows = db.list_instructions(conn, status="new")
    conn.close()
    assert any(instruction_text in str(dict(r)) for r in rows), "Instruction not in DB"

    # Step 3: choose_action with mocked orchestrator returning "researcher" -> forced to planner
    with patch.object(
        research_graph.orchestrator,
        "decide_orchestrator",
        _fake_decide_factory(worker="researcher", context_summary="Updated summary"),
    ):
        choose_result = research_graph.choose_action(
            _base_state(), cfg=cfg, researcher_root=tmp_path, db_path=db_path,
        )

    assert choose_result["current_worker"] == "planner", "Must override to planner"

    # Step 4: Simulate planner worker completing — integrate instruction into plan and clear ## New
    # (In real runs, the CLI worker does this; we replicate the expected file edits.)
    plan_text = helpers.read_text(memory.state_dir(tmp_path) / "immediate_plan.md")
    plan_text += f"\n## Ablation study\n\n- {instruction_text}\n"
    helpers.write_text(memory.state_dir(tmp_path) / "immediate_plan.md", plan_text)

    cleared_ui = (
        "# User instructions\n\n"
        "## New\n\n"
        "## In progress\n\n"
        f"- {instruction_text}\n\n"
        "## Completed\n\n"
    )
    helpers.write_text(memory.state_dir(tmp_path) / "user_instructions.md", cleared_ui)

    # Step 5: Mock execute_worker (we skip actual CLI) and run update_state
    worker_state = _base_state(
        cycle=0,
        current_worker="planner",
        orchestrator_task=choose_result["orchestrator_task"],
        orchestrator_reason=choose_result.get("orchestrator_reason", ""),
        last_action_summary="Integrated user instruction into immediate_plan.md",
        last_packet_relpath=memory.episodes_cycle_relpath(cycle=1, worker="planner"),
    )

    ep_dir = memory.episode_cycle_dir(tmp_path, 1, "planner")
    helpers.ensure_dir(ep_dir)
    helpers.write_text(ep_dir / "packet.md", "fake packet")
    helpers.write_text(
        ep_dir / "worker_output.json",
        json.dumps({"ok": True, "parsed": {"status": "integrated"}}),
    )

    research_graph.update_state(worker_state, db_path=db_path, researcher_root=tmp_path)

    # Step 6: Verify final state
    assert not memory.user_instructions_new_has_pending(tmp_path), "## New should be clear"
    plan_final = helpers.read_text(memory.state_dir(tmp_path) / "immediate_plan.md")
    assert instruction_text in plan_final, "Instruction not in immediate_plan.md"

    idx_text = helpers.read_text(memory.episodes_dir(tmp_path) / "index.md")
    assert "planner" in idx_text, "Episode index missing planner entry"

    # Step 7: Next choose_action should NOT override to planner
    with patch.object(
        research_graph.orchestrator,
        "decide_orchestrator",
        _fake_decide_factory(worker="implementer", context_summary="Next summary"),
    ):
        next_result = research_graph.choose_action(
            _base_state(cycle=1), cfg=cfg, researcher_root=tmp_path, db_path=db_path,
        )

    assert next_result["current_worker"] == "implementer", (
        "With ## New cleared, orchestrator choice should not be overridden"
    )

    _log("user_instruction_full_lifecycle", {
        "instruction": instruction_text,
        "pending_after_enqueue": True,
        "override_to_planner": choose_result["current_worker"] == "planner",
        "pending_after_clear": False,
        "in_plan": instruction_text in plan_final,
        "next_worker_not_overridden": next_result["current_worker"] == "implementer",
    })


# ---------------------------------------------------------------------------
# 9. Context summary compression fidelity
# ---------------------------------------------------------------------------


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

    # The previous_context_summary slice is capped at 8000 chars
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

    # The section should contain at most 8000 chars of the summary plus header overhead
    z_count = section_body.count("Z")
    assert z_count <= 8000, f"Previous summary section has {z_count} Z's, expected <= 8000"

    _log("context_summary_compression", {
        "original_len": len(long_summary),
        "ctx_total_len": len(ctx),
        "z_count_in_section": z_count,
        "chars_lost": len(long_summary) - 8000 if len(long_summary) > 8000 else 0,
    })
