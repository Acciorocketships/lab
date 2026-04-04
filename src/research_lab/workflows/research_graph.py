"""LangGraph research loop: ingest control events, choose worker, run worker, checkpoint."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from research_lab import control, db, memory, orchestrator, packets
from research_lab.agents import (
    base as agents_base,
    critic as critic_mod,
    debugger,
    executer,
    experimenter,
    implementer,
    planner,
    reporter as reporter_mod,
    researcher,
    reviewer,
    shared_prompt,
    skill_writer,
)
from research_lab.config import RunConfig
from research_lab.state import ResearchState

_WORKER_MODULES: dict[str, Any] = {
    "planner": planner,
    "researcher": researcher,
    "executer": executer,
    "implementer": implementer,
    "debugger": debugger,
    "experimenter": experimenter,
    "critic": critic_mod,
    "reviewer": reviewer,
    "reporter": reporter_mod,
    "skill_writer": skill_writer,
    "done": None,
}


def _conn(db_path: Path):
    """Open DB connection for graph nodes."""
    return db.connect_db(db_path)


def ingest_events(state: ResearchState, *, db_path: Path, researcher_root: Path) -> dict[str, Any]:
    """Consume control events; update SQLite and files."""
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        evs = db.fetch_pending_events(conn)
        ids: list[int] = []
        for ev in evs:
            kid = ev["kind"]
            payload = ev["payload"]
            if kid == "pause":
                db.set_control_mode(conn, "paused")
            elif kid == "resume":
                db.set_control_mode(conn, "active")
            elif kid == "shutdown":
                db.set_control_mode(conn, "shutdown")
            elif kid == "instruction":
                control.apply_instruction_event(conn, researcher_root, payload)
            ids.append(int(ev["id"]))
        db.mark_events_consumed(conn, ids)
        conn.commit()
        st = db.get_system_state(conn)
        return {"control_mode": st["control_mode"]}
    finally:
        conn.close()


def choose_action(
    state: ResearchState,
    *,
    cfg: RunConfig,
    researcher_root: Path,
    db_path: Path,
) -> dict[str, Any]:
    """Orchestrator chooses next worker; updates rolling context and logs orchestrator run_event."""
    prev = memory.read_context_summary(researcher_root)
    tier = memory.load_tier_a_bundle(researcher_root)
    ctx = memory.format_orchestrator_context(
        researcher_root,
        tier=tier,
        current_branch=str(state.get("current_branch", "") or ""),
        last_worker_output=str(state.get("last_action_summary", "") or ""),
        previous_context_summary=prev,
        prev_summary_max_chars=cfg.orchestrator_prev_summary_max_chars,
        last_worker_max_chars=cfg.orchestrator_last_worker_max_chars,
        tier_file_max_chars=cfg.orchestrator_tier_file_max_chars,
        branch_memory_max_chars=cfg.orchestrator_branch_memory_max_chars,
    )
    dec = orchestrator.decide_orchestrator(
        ctx,
        model=cfg.openai_model,
        cfg=cfg,
    )
    if memory.user_instructions_new_has_pending(researcher_root) and dec.worker != "planner":
        dec = dec.model_copy(
            update={
                "worker": "planner",
                "task": (
                    "Merge bullets under ## New in user_instructions.md into immediate_plan.md and/or "
                    "roadmap.md, then remove them from ## New (use In progress/Completed if helpful). "
                    "Address the substance immediately."
                ),
                "reason": (
                    "Pending user instructions under ## New in user_instructions.md; planner must integrate and clear."
                ),
            }
        )
    new_cs = (dec.context_summary or "").strip()
    if new_cs:
        memory.write_context_summary(researcher_root, dec.context_summary)
    orch_summary = f"{dec.worker}: {dec.reason}"
    cycle = int(state.get("cycle_count", 0)) + 1
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        db.append_run_event(
            conn,
            cycle=cycle,
            kind="orchestrator",
            worker=dec.worker,
            roadmap_step=dec.roadmap_step,
            task=dec.task,
            summary=orch_summary,
            payload=dec.model_dump(),
            packet_path=None,
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "roadmap_step": dec.roadmap_step,
        "orchestrator_task": dec.task,
        "orchestrator_reason": dec.reason,
        "rolling_context_summary": dec.context_summary,
        "current_worker": dec.worker,
        "current_branch": dec.branch or state.get("current_branch", ""),
        "last_action_summary": orch_summary,
        "current_goal": dec.task,
        "worker_kwargs": dec.worker_kwargs,
    }


def execute_worker(
    state: ResearchState,
    *,
    cfg: RunConfig,
    researcher_root: Path,
    project_dir: Path,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Build packet and call CLI worker (or skip)."""
    worker = state.get("current_worker", "planner")
    cyc = int(state.get("cycle_count", 0)) + 1
    task = state.get("current_goal", "continue")
    if worker in ("done",):
        return {
            "cycle_count": cyc,
            "last_action_summary": "done",
            "last_packet_relpath": "",
            "orchestrator_reason": str(state.get("orchestrator_reason", "") or ""),
            "acceptance_satisfied": True,
        }
    mod = _WORKER_MODULES.get(worker)
    worker_kwargs: dict[str, str] = state.get("worker_kwargs") or {}
    role_hint = (getattr(mod, "SYSTEM_PROMPT", "") if mod else "").strip()
    # Critic: use persona-specific prompt when the orchestrator supplies one.
    if worker == "critic" and mod is not None:
        persona = worker_kwargs.get("persona", "")
        role_hint = critic_mod.critic_prompt(persona).strip()
    extra: dict[str, str] = {}
    shared = shared_prompt.MEMORY_AND_TIER_A.strip()
    if role_hint:
        extra["Role"] = role_hint
    if shared:
        extra["Memory & Tier A"] = shared
    pkt = packets.build_worker_packet(
        worker=worker,
        researcher_root=researcher_root,
        task=task,
        extra_sections=extra if extra else None,
        current_branch=str(state.get("current_branch", "") or ""),
        max_chars=cfg.worker_packet_max_chars,
    )
    packets.write_packet_file(researcher_root, cyc, worker, pkt)
    relpath = memory.episodes_cycle_relpath(cycle=cyc, worker=worker)
    backend = cfg.default_worker_backend
    if backend not in ("claude", "cursor"):
        backend = "cursor"

    on_chunk = None
    if db_path is not None:
        stream_conn = _conn(db_path)
        def on_chunk(chunk: str, _c=stream_conn, _cyc=cyc, _w=worker) -> None:
            try:
                db.append_stream_chunk(_c, _cyc, _w, chunk)
            except Exception:
                pass

    res = agents_base.run_worker(
        pkt,
        backend=backend,
        project_cwd=project_dir,
        cursor_agent_model=cfg.cursor_agent_model,
        on_chunk=on_chunk,
    )
    packets.write_worker_output_file(researcher_root, cyc, worker, res)
    summary = str(res.get("parsed", res))
    return {
        "cycle_count": cyc,
        "last_action_summary": summary,
        "last_packet_relpath": relpath,
        "orchestrator_reason": str(state.get("orchestrator_reason", "") or ""),
    }


def update_state(state: ResearchState, *, db_path: Path, researcher_root: Path) -> dict[str, Any]:
    """Persist run_events worker row and system_state."""
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cyc = int(state.get("cycle_count", 0))
        pkt_rel = str(state.get("last_packet_relpath", "")) or None
        db.append_run_event(
            conn,
            cycle=cyc,
            kind="worker",
            worker=str(state.get("current_worker", "")),
            roadmap_step=str(state.get("roadmap_step", "")),
            task=str(state.get("orchestrator_task", "")),
            summary=str(state.get("last_action_summary", "")),
            payload={"last_action_summary": str(state.get("last_action_summary", ""))},
            packet_path=pkt_rel,
        )
        if pkt_rel:
            memory.append_episode_index_entry(
                researcher_root,
                cycle=cyc,
                worker=str(state.get("current_worker", "")),
                task=str(state.get("orchestrator_task", "")),
                reason=str(state.get("orchestrator_reason", "") or ""),
                episode_relpath=pkt_rel,
            )
        db.set_system_fields(
            conn,
            roadmap_step=str(state.get("roadmap_step", "")),
            task=str(state.get("orchestrator_task", "")),
            current_branch=state.get("current_branch", ""),
            current_worker=state.get("current_worker", ""),
            cycle_count=cyc,
            last_message=state.get("last_action_summary", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return {}


def build_graph(
    cfg: RunConfig,
    *,
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    checkpoint_path: Path | None = None,
):
    """Compile LangGraph; optional checkpoint_path reserved for durable resume."""
    del checkpoint_path  # wired when enabling SqliteSaver for crash recovery
    memory.ensure_memory_layout(researcher_root)

    def n_ingest(s: ResearchState):
        return ingest_events(s, db_path=db_path, researcher_root=researcher_root)

    def n_choose(s: ResearchState):
        return choose_action(s, cfg=cfg, researcher_root=researcher_root, db_path=db_path)

    def n_worker(s: ResearchState):
        return execute_worker(s, cfg=cfg, researcher_root=researcher_root, project_dir=project_dir, db_path=db_path)

    def n_update(s: ResearchState):
        return update_state(s, db_path=db_path, researcher_root=researcher_root)

    g = StateGraph(ResearchState)
    g.add_node("ingest", n_ingest)
    g.add_node("choose", n_choose)
    g.add_node("worker", n_worker)
    g.add_node("update", n_update)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "choose")
    g.add_edge("choose", "worker")
    g.add_edge("worker", "update")
    g.add_edge("update", END)

    return g.compile()


def _state_from_db(db_path: Path) -> ResearchState:
    """Hydrate LangGraph state from operational DB between cycles."""
    conn = _conn(db_path)
    try:
        st = db.get_system_state(conn)
        return {
            "current_goal": st.get("task") or st.get("last_message", "") or "continue",
            "current_branch": st.get("current_branch", ""),
            "current_worker": st.get("current_worker", "") or "planner",
            "cycle_count": int(st.get("cycle_count", 0)),
        "control_mode": st.get("control_mode", "active"),
        "pending_instructions": [],
        "last_action_summary": st.get("last_message", ""),
        "roadmap_step": st.get("roadmap_step", ""),
        "orchestrator_task": st.get("task", ""),
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }
    finally:
        conn.close()


def run_loop(
    cfg: RunConfig,
    *,
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
    checkpoint_path: Path,
) -> None:
    """One graph invoke per outer iteration until shutdown."""
    del checkpoint_path
    app = build_graph(
        cfg,
        db_path=db_path,
        researcher_root=researcher_root,
        project_dir=project_dir,
    )
    while True:
        conn = _conn(db_path)
        try:
            mode = db.get_system_state(conn)["control_mode"]
        finally:
            conn.close()
        if mode == "paused":
            time.sleep(0.5)
            continue
        if mode == "shutdown":
            break
        out = app.invoke(_state_from_db(db_path))
        if out.get("acceptance_satisfied"):
            break
