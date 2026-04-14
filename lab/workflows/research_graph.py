"""LangGraph research loop: ingest control events, choose worker, run worker, checkpoint."""

from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from lab import control, db, git_checkpoint, helpers, memory, orchestrator, packets
from lab.agents import (
    base as agents_base,
    critic as critic_mod,
    debugger,
    executer,
    experimenter,
    implementer,
    memory_compactor,
    planner,
    query,
    reporter as reporter_mod,
    researcher,
    reviewer,
    shared_prompt,
    skill_writer,
)
from lab.config import RunConfig
from lab.state import ResearchState

_WORKER_MODULES: dict[str, Any] = {
    "planner": planner,
    "query": query,
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
                db.set_graceful_pause_pending(conn, False)
                db.set_control_mode(conn, "paused")
            elif kid == "resume":
                db.set_graceful_pause_pending(conn, False)
                db.set_control_mode(conn, "active")
            elif kid == "shutdown":
                db.set_graceful_pause_pending(conn, False)
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
    project_dir: Path,
    db_path: Path,
) -> dict[str, Any]:
    """Orchestrator chooses next worker; updates rolling context and logs orchestrator run_event."""
    forced_worker = ""
    forced_task = ""
    conn = _conn(db_path)
    try:
        forced = db.get_forced_run(conn)
    finally:
        conn.close()

    if forced is not None:
        forced_worker = forced["worker"]
        forced_task = forced["task"]

    prev = memory.read_context_summary(researcher_root)
    tier = memory.load_tier_a_bundle(researcher_root)
    git_branch = memory.current_git_branch(project_dir)
    branch_for_ctx = (git_branch or str(state.get("current_branch", "") or "")).strip()
    ctx = memory.format_orchestrator_context(
        researcher_root,
        tier=tier,
        current_branch=branch_for_ctx,
        last_worker_output=str(state.get("last_action_summary", "") or ""),
        previous_context_summary=prev,
        prev_summary_max_chars=cfg.orchestrator_prev_summary_max_chars,
        last_worker_max_chars=cfg.orchestrator_last_worker_max_chars,
        tier_file_max_chars=cfg.orchestrator_tier_file_max_chars,
        branch_memory_max_chars=cfg.orchestrator_branch_memory_max_chars,
    )
    if forced_worker:
        dec = orchestrator.OrchestratorDecision(
            worker=forced_worker,
            task=forced_task,
            reason="Forced by console to resolve /redo merge conflicts immediately.",
            roadmap_step="",
            context_summary=prev,
            worker_kwargs={},
        )
    else:
        dec = orchestrator.decide_orchestrator(
            ctx,
            model=cfg.openai_model,
            cfg=cfg,
        )
    if (
        not forced_worker
        and memory.user_instructions_new_has_pending(researcher_root)
        and dec.worker != "planner"
    ):
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
    branch = branch_for_ctx
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if forced_worker:
            db.clear_forced_run(conn)
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
        # Align system_state with the new cycle immediately so the
        # header matches the orchestrator run_event (previously only updated after
        # the worker finished, so it lagged by one cycle during execution).
        db.set_system_fields(
            conn,
            roadmap_step=dec.roadmap_step,
            task=dec.task,
            current_branch=branch,
            current_worker=dec.worker,
            cycle_count=cycle,
        )
        conn.commit()
    finally:
        conn.close()
    memory.refresh_system_tier_from_db(
        researcher_root,
        project_dir,
        db_path,
        limit=cfg.system_recent_run_events_limit,
    )
    return {
        "roadmap_step": dec.roadmap_step,
        "orchestrator_task": dec.task,
        "orchestrator_reason": dec.reason,
        "rolling_context_summary": dec.context_summary,
        "current_worker": dec.worker,
        "current_branch": branch,
        "last_action_summary": orch_summary,
        "current_goal": dec.task,
        "worker_kwargs": dec.worker_kwargs,
    }


def _worker_extra_sections(worker: str, mod: Any, worker_kwargs: dict[str, str]) -> dict[str, str]:
    """Shared packet sections for normal workers and internal maintenance workers."""
    role_hint = (getattr(mod, "SYSTEM_PROMPT", "") if mod else "").strip()
    if worker == "critic" and mod is not None:
        persona = worker_kwargs.get("persona", "")
        role_hint = critic_mod.critic_prompt(persona).strip()
    extra: dict[str, str] = {}
    shared_work = shared_prompt.SHARED_WORK_GUIDANCE.strip()
    shared = shared_prompt.MEMORY_AND_TIER_A.strip()
    if role_hint:
        extra["Role"] = role_hint
    if shared_work:
        extra["Shared guidance"] = shared_work
    if shared:
        extra["Memory & Tier A"] = shared
    return extra


def _worker_summary(result: dict[str, Any]) -> str:
    """Compact textual summary derived from a worker result payload."""
    parsed = result.get("parsed")
    result_text = ""
    if isinstance(parsed, dict):
        result_text = parsed.get("result", "") or ""
        if not result_text and parsed.get("raw"):
            result_text = str(parsed["raw"])
        if not result_text and parsed.get("error"):
            result_text = str(parsed["error"])
    elif isinstance(parsed, str):
        result_text = parsed
    return result_text or str(parsed or result)


def _tier_size_snapshot(researcher_root: Path) -> dict[str, int]:
    """Current non-system Tier A file sizes."""
    return memory.tier_a_file_sizes(researcher_root)


def _auto_compactor_effective_thresholds(
    researcher_root: Path,
    current_sizes: dict[str, int],
) -> dict[str, int]:
    """Per-file thresholds: base soft-clip threshold, optionally raised by prior compaction."""
    base = packets.WORKER_TIER_A_SOFT_CLIP_THRESHOLD_CHARS
    thresholds = {name: base for name in current_sizes}
    state = memory.read_auto_compactor_state(researcher_root)
    if not isinstance(state, dict):
        return thresholds
    file_thresholds = state.get("file_thresholds")
    if not isinstance(file_thresholds, dict):
        return thresholds
    for name, value in file_thresholds.items():
        if name not in thresholds:
            continue
        try:
            thresholds[name] = max(base, int(value))
        except (TypeError, ValueError):
            continue
    return thresholds


def _oversized_tier_files_for_auto_compactor(researcher_root: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Return current sizes and files exceeding their current effective compaction thresholds."""
    sizes = _tier_size_snapshot(researcher_root)
    thresholds = _auto_compactor_effective_thresholds(researcher_root, sizes)
    oversized = {
        name: size
        for name, size in sizes.items()
        if size > thresholds.get(name, packets.WORKER_TIER_A_SOFT_CLIP_THRESHOLD_CHARS)
    }
    return sizes, oversized


def _record_auto_compactor_outcome(
    researcher_root: Path,
    result: dict[str, Any],
) -> None:
    """Persist per-file retry thresholds after a compactor run."""
    del result
    _, post_oversized = _oversized_tier_files_for_auto_compactor(researcher_root)
    if not post_oversized:
        memory.clear_auto_compactor_state(researcher_root)
        return
    memory.write_auto_compactor_state(
        researcher_root,
        {
            "file_thresholds": {
                name: max(packets.WORKER_TIER_A_SOFT_CLIP_THRESHOLD_CHARS, size)
                for name, size in post_oversized.items()
            },
        },
    )


def _run_internal_memory_compactor(
    *,
    cyc: int,
    state: ResearchState,
    cfg: RunConfig,
    researcher_root: Path,
    project_dir: Path,
    db_path: Path | None,
    reason: str,
) -> dict[str, Any]:
    """Run the internal Tier A compactor once and persist its artifacts."""
    task = (
        f"Automatically compact Tier A because {reason}. Reduce verbosity aggressively while "
        "preserving important project truth, canonical formatting, and real user instructions only."
    )
    packet = packets.build_worker_packet(
        worker="memory_compactor",
        researcher_root=researcher_root,
        task=task,
        extra_sections=_worker_extra_sections("memory_compactor", memory_compactor, {}),
        current_branch=str(state.get("current_branch", "") or ""),
        max_chars=_AUTO_COMPACTOR_PACKET_MAX_CHARS,
    )
    packets.write_packet_file(researcher_root, cyc, "memory_compactor", packet)
    packet_rel = memory.episodes_cycle_relpath(cycle=cyc, worker="memory_compactor")

    on_chunk = None
    stream_conn = None
    if db_path is not None:
        stream_conn = _conn(db_path)

        def on_chunk(chunk: str, _c=stream_conn, _cyc=cyc) -> None:
            try:
                db.append_stream_chunk(_c, _cyc, "memory_compactor", chunk)
            except Exception:
                pass

    try:
        result = agents_base.run_worker(
            packet,
            backend=cfg.default_worker_backend if cfg.default_worker_backend in ("claude", "cursor") else "cursor",
            project_cwd=project_dir,
            cursor_agent_model=cfg.cursor_agent_model,
            on_chunk=on_chunk,
        )
    finally:
        if stream_conn is not None:
            stream_conn.close()

    packets.write_worker_output_file(researcher_root, cyc, "memory_compactor", result)
    summary = _worker_summary(result)

    if db_path is not None:
        conn = _conn(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            db.append_run_event(
                conn,
                cycle=cyc,
                kind="worker",
                worker="memory_compactor",
                roadmap_step=str(state.get("roadmap_step", "")),
                task=task,
                summary=summary,
                payload={
                    "worker_ok": result.get("ok", True),
                    "auto_trigger_reason": reason,
                },
                packet_path=packet_rel,
            )
            conn.commit()
        finally:
            conn.close()
        memory.append_episode_index_entry(
            researcher_root,
            cycle=cyc,
            worker="memory_compactor",
            task=task,
            reason=f"automatic maintenance: {reason}",
            episode_relpath=packet_rel,
        )
        memory.refresh_system_tier_from_db(
            researcher_root,
            project_dir,
            db_path,
            limit=cfg.system_recent_run_events_limit,
        )
    return result


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
    _, oversized_tier_files = _oversized_tier_files_for_auto_compactor(researcher_root)
    auto_compacted = False
    if oversized_tier_files:
        details = ", ".join(
            f"{name}={size}"
            for name, size in sorted(oversized_tier_files.items())
        )
        compactor_result = _run_internal_memory_compactor(
            cyc=cyc,
            state=state,
            cfg=cfg,
            researcher_root=researcher_root,
            project_dir=project_dir,
            db_path=db_path,
            reason=(
                "these Tier A files exceeded the soft-clip threshold "
                f"({packets.WORKER_TIER_A_SOFT_CLIP_THRESHOLD_CHARS} chars): {details}"
            ),
        )
        _record_auto_compactor_outcome(researcher_root, compactor_result)
        auto_compacted = True
    extra = _worker_extra_sections(str(worker), mod, worker_kwargs)
    packet_kwargs = {
        "worker": worker,
        "researcher_root": researcher_root,
        "task": task,
        "extra_sections": extra if extra else None,
        "current_branch": str(state.get("current_branch", "") or ""),
    }

    def _build_packet(max_chars: int | None) -> str:
        return packets.build_worker_packet(max_chars=max_chars, **packet_kwargs)

    pkt = _build_packet(cfg.worker_packet_max_chars)
    packets.write_packet_file(researcher_root, cyc, worker, pkt)
    relpath = memory.episodes_cycle_relpath(cycle=cyc, worker=worker)
    backend = cfg.default_worker_backend
    if backend not in ("claude", "cursor"):
        backend = "cursor"

    snap = memory.capture_worker_diff_baseline(project_dir, cyc)
    if snap is not None:
        memory.write_worker_diff_baseline(researcher_root, snap)

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
    parsed = res.get("parsed")
    retry_max_chars = cfg.worker_packet_max_chars
    if retry_max_chars is None or retry_max_chars > _EMPTY_OUTPUT_RETRY_PACKET_MAX_CHARS:
        retry_max_chars = _EMPTY_OUTPUT_RETRY_PACKET_MAX_CHARS
    if (
        isinstance(parsed, dict)
        and parsed.get("error") == "empty_output"
    ):
        if not auto_compacted:
            _, oversized_tier_files = _oversized_tier_files_for_auto_compactor(researcher_root)
            if oversized_tier_files:
                compactor_result = _run_internal_memory_compactor(
                    cyc=cyc,
                    state=state,
                    cfg=cfg,
                    researcher_root=researcher_root,
                    project_dir=project_dir,
                    db_path=db_path,
                    reason="the previous worker run returned empty_output",
                )
                _record_auto_compactor_outcome(researcher_root, compactor_result)
                auto_compacted = True
        pkt = _build_packet(retry_max_chars)
        packets.write_packet_file(researcher_root, cyc, worker, pkt)
        res = agents_base.run_worker(
            pkt,
            backend=backend,
            project_cwd=project_dir,
            cursor_agent_model=cfg.cursor_agent_model,
            on_chunk=on_chunk,
        )
    packets.write_worker_output_file(researcher_root, cyc, worker, res)
    parsed = res.get("parsed")
    worker_ok = res.get("ok", True)
    result_text = ""
    if isinstance(parsed, dict):
        result_text = parsed.get("result", "") or ""
        if not result_text and parsed.get("raw"):
            result_text = str(parsed["raw"])
    elif isinstance(parsed, str):
        result_text = parsed
    summary = result_text or str(parsed or res)
    return {
        "cycle_count": cyc,
        "last_action_summary": summary,
        "last_packet_relpath": relpath,
        "orchestrator_reason": str(state.get("orchestrator_reason", "") or ""),
        "worker_ok": worker_ok,
    }


def update_state(
    state: ResearchState,
    *,
    cfg: RunConfig,
    db_path: Path,
    researcher_root: Path,
    project_dir: Path,
) -> dict[str, Any]:
    """Persist run_events worker row and system_state."""
    conn = _conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cyc = int(state.get("cycle_count", 0))
        pkt_rel = str(state.get("last_packet_relpath", "")) or None
        checklist_snapshot = memory.extract_immediate_plan_checklist(
            helpers.read_text(memory.state_dir(researcher_root) / "immediate_plan.md", default="")
        )
        db.append_run_event(
            conn,
            cycle=cyc,
            kind="worker",
            worker=str(state.get("current_worker", "")),
            roadmap_step=str(state.get("roadmap_step", "")),
            task=str(state.get("orchestrator_task", "")),
            summary=str(state.get("last_action_summary", "")),
            payload={
                "last_action_summary": str(state.get("last_action_summary", "")),
                "worker_ok": state.get("worker_ok", True),
                "immediate_plan_checklist": checklist_snapshot,
            },
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
    memory.refresh_system_tier_from_db(
        researcher_root,
        project_dir,
        db_path,
        limit=cfg.system_recent_run_events_limit,
    )
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
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)

    def n_ingest(s: ResearchState):
        return ingest_events(s, db_path=db_path, researcher_root=researcher_root)

    def n_choose(s: ResearchState):
        return choose_action(
            s, cfg=cfg, researcher_root=researcher_root, project_dir=project_dir, db_path=db_path
        )

    def n_worker(s: ResearchState):
        return execute_worker(s, cfg=cfg, researcher_root=researcher_root, project_dir=project_dir, db_path=db_path)

    def n_update(s: ResearchState):
        return update_state(
            s, cfg=cfg, db_path=db_path, researcher_root=researcher_root, project_dir=project_dir
        )

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
        conn.commit()
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


_log = logging.getLogger(__name__)

_MAX_CONSECUTIVE_ERRORS = 5
_EMPTY_OUTPUT_RETRY_PACKET_MAX_CHARS = 120_000
_AUTO_COMPACTOR_PACKET_MAX_CHARS = 90_000


def _root_cause(exc: BaseException) -> BaseException:
    """Walk __cause__ / __context__ chain to find the original exception."""
    root = exc
    seen: set[int] = {id(root)}
    while True:
        nxt = root.__cause__ if root.__cause__ is not None else root.__context__
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        root = nxt
    return root


def _record_cycle_error(
    db_path: Path,
    state: ResearchState,
    tb: str,
    exc: BaseException | None = None,
    *,
    researcher_root: Path | None = None,
    project_dir: Path | None = None,
    cfg: RunConfig | None = None,
) -> None:
    """Write a run_event so the console can display the cycle failure."""
    try:
        if exc is not None:
            root = _root_cause(exc)
            short = f"{type(root).__qualname__}: {root}"
        else:
            short = tb.splitlines()[-1] if tb.strip() else "unknown error"
        conn = _conn(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cycle = int(state.get("cycle_count", 0)) + 1
            worker = state.get("current_worker", "unknown")
            db.append_run_event(
                conn,
                cycle=cycle,
                kind="worker",
                worker=worker,
                roadmap_step=str(state.get("roadmap_step", "")),
                task=str(state.get("orchestrator_task", "")),
                summary=f"cycle crashed: {short[:200]}",
                payload={"worker_ok": False, "error": tb[-2000:]},
                packet_path=None,
            )
            conn.commit()
        finally:
            conn.close()
        if researcher_root is not None and project_dir is not None and cfg is not None:
            memory.refresh_system_tier_from_db(
                researcher_root,
                project_dir,
                db_path,
                limit=cfg.system_recent_run_events_limit,
            )
    except Exception:
        pass


def _revert_to_last_checkpoint(project_dir: Path, db_path: Path) -> None:
    """Revert working tree and DB to the last checkpoint (best-effort)."""
    try:
        cycle = git_checkpoint.revert_to_checkpoint(project_dir)
        if cycle is not None:
            conn = _conn(db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                db.rollback_to_cycle(conn, cycle)
                conn.commit()
            finally:
                conn.close()
    except Exception:
        _log.warning("Revert to checkpoint failed", exc_info=True)


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
    consecutive_errors = 0
    while True:
        state = _state_from_db(db_path)
        mode = state.get("control_mode", "active")
        if mode == "paused":
            event_updates = ingest_events(state, db_path=db_path, researcher_root=researcher_root)
            mode = str(event_updates.get("control_mode", mode))
            if mode == "paused":
                time.sleep(0.5)
                continue
            if mode == "shutdown":
                break
            state = _state_from_db(db_path)
        if mode == "shutdown":
            break
        try:
            out = app.invoke(state)
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            tb = traceback.format_exc()
            _log.error("Cycle %d failed:\n%s", state.get("cycle_count", 0) + 1, tb)
            _record_cycle_error(
                db_path,
                state,
                tb,
                exc,
                researcher_root=researcher_root,
                project_dir=project_dir,
                cfg=cfg,
            )
            _revert_to_last_checkpoint(project_dir, db_path)
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                _log.error(
                    "Hit %d consecutive cycle errors — pausing scheduler.",
                    _MAX_CONSECUTIVE_ERRORS,
                )
                conn = _conn(db_path)
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    db.set_graceful_pause_pending(conn, False)
                    db.set_control_mode(conn, "paused")
                    conn.commit()
                finally:
                    conn.close()
                break
            time.sleep(min(2 ** consecutive_errors, 30))
            continue

        cycle = int(out.get("cycle_count", state.get("cycle_count", 0)))
        worker = str(out.get("current_worker", ""))
        git_checkpoint.create_checkpoint(project_dir, cycle, worker)

        if out.get("acceptance_satisfied"):
            conn = _conn(db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                db.set_graceful_pause_pending(conn, False)
                db.set_control_mode(conn, "paused")
                conn.commit()
            finally:
                conn.close()
            break

        conn = _conn(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            st = db.get_system_state(conn)
            if int(st.get("graceful_pause_pending", 0) or 0):
                db.set_graceful_pause_pending(conn, False)
                db.set_control_mode(conn, "paused")
            conn.commit()
        finally:
            conn.close()
