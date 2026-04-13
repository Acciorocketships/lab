"""Async ``/agent`` runtime independent from the orchestrator scheduler."""

from __future__ import annotations

from pathlib import Path

from lab import db, memory, packets
from lab.agents import base as agents_base
from lab.agents import shared_prompt
from lab.config import RunConfig


def _agent_backend_and_model(cfg: RunConfig) -> tuple[str, str]:
    backend = cfg.default_worker_backend
    if backend not in ("claude", "cursor"):
        backend = "cursor"
    model = (cfg.cursor_agent_model or "").strip() if backend == "cursor" else ""
    return backend, model


def build_agent_packet(
    *,
    researcher_root: Path,
    prompt: str,
    current_branch: str,
    max_chars: int | None,
) -> str:
    """Build a generic agent packet: shared guidance + Tier A, no role prompt."""
    extra: dict[str, str] = {}
    shared_work = shared_prompt.SHARED_WORK_GUIDANCE.strip()
    shared = shared_prompt.MEMORY_AND_TIER_A.strip()
    if shared_work:
        extra["Shared guidance"] = shared_work
    if shared:
        extra["Memory & Tier A"] = shared
    return packets.build_worker_packet(
        worker="agent",
        researcher_root=researcher_root,
        task=prompt,
        extra_sections=extra if extra else None,
        current_branch=current_branch,
        max_chars=max_chars,
    )


def run_agent(
    *,
    agent_id: int,
    db_path: Path,
    cfg: RunConfig,
    researcher_root: Path,
    project_dir: Path,
) -> None:
    """Run one async ``/agent`` task end-to-end, streaming into SQLite."""
    conn = db.connect_db(db_path)
    try:
        row = db.get_agent_run(conn, agent_id)
        if row is None:
            return
        prompt = str(row["prompt"] or "").strip()
        backend, model = _agent_backend_and_model(cfg)
        packet = build_agent_packet(
            researcher_root=researcher_root,
            prompt=prompt,
            current_branch=memory.current_git_branch(project_dir),
            max_chars=cfg.worker_packet_max_chars,
        )
        packet_path = packets.write_agent_packet_file(researcher_root, agent_id, packet)
        packet_rel = memory.episodes_agent_relpath(agent_id=agent_id)
        db.update_agent_run_paths(conn, agent_id, packet_path=packet_rel)
        memory.append_agent_episode_index_entry(
            researcher_root,
            agent_id=agent_id,
            task=prompt,
            episode_relpath=packet_rel,
        )
        memory.refresh_system_tier_from_db(
            researcher_root,
            project_dir,
            db_path,
            limit=cfg.system_recent_run_events_limit,
        )
    finally:
        conn.close()

    stream_conn = db.connect_db(db_path)

    def on_chunk(chunk: str, *, _conn=stream_conn, _agent_id=agent_id) -> None:
        try:
            db.append_agent_stream_chunk(_conn, _agent_id, chunk)
        except Exception:
            pass

    try:
        result = agents_base.run_worker(
            packet,
            backend=backend,
            project_cwd=project_dir,
            cursor_agent_model=cfg.cursor_agent_model,
            on_chunk=on_chunk,
        )
    finally:
        stream_conn.close()

    output_path = packets.write_agent_output_file(researcher_root, agent_id, result)
    output_rel = memory.episodes_agent_relpath(agent_id=agent_id)
    parsed = result.get("parsed")
    agent_ok = result.get("ok", True)
    summary = ""
    if isinstance(parsed, dict):
        summary = str(parsed.get("result", "") or parsed.get("raw", "") or "").strip()
    elif isinstance(parsed, str):
        summary = parsed.strip()
    if not summary:
        summary = str(parsed or result).strip()
    error = str(result.get("error", "") or result.get("stderr", "") or "").strip()

    finish_conn = db.connect_db(db_path)
    try:
        db.update_agent_run_paths(finish_conn, agent_id, output_path=output_rel)
        db.finish_agent_run(
            finish_conn,
            agent_id,
            status="completed" if agent_ok else "failed",
            summary=summary,
            error=error,
            output_path=output_rel,
        )
        memory.refresh_system_tier_from_db(
            researcher_root,
            project_dir,
            db_path,
            limit=cfg.system_recent_run_events_limit,
        )
    finally:
        finish_conn.close()
