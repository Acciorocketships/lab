"""Async ``/agent`` runtime independent from the orchestrator scheduler."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lab import db, memory, packets
from lab.agents import base as agents_base
from lab.agents import shared_prompt
from lab.config import RunConfig

# How many previous completed ``/agent`` exchanges to fold into the packet as
# follow-up context (newest-first). Only the most recent one is needed to
# support a follow-up; earlier runs stay on disk under ``memory/episodes``.
_AGENT_HISTORY_LIMIT = 1
# Per-exchange cap so one verbose prior answer can't blow the packet budget;
# whole-packet ``max_chars`` still applies on top.
_AGENT_HISTORY_ENTRY_MAX_CHARS = 4000


def _agent_backend_and_model(cfg: RunConfig) -> tuple[str, str]:
    backend = cfg.default_worker_backend
    if backend not in ("claude", "cursor"):
        backend = "cursor"
    model = (cfg.cursor_agent_model or "").strip() if backend == "cursor" else ""
    return backend, model


def _clip_for_history(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "\n...[truncated]..."


def _collect_previous_exchanges(
    conn: sqlite3.Connection,
    *,
    current_agent_id: int,
    limit: int = _AGENT_HISTORY_LIMIT,
) -> list[tuple[int, str, str]]:
    """Return up to ``limit`` prior ``/agent`` runs (id, prompt, summary), oldest-first.

    Only includes runs with a non-empty summary (i.e. finished runs) so the
    context actually helps a follow-up. The current run is excluded.
    """
    rows = db.list_agent_runs(conn)
    finished: list[tuple[int, str, str]] = []
    for row in rows:
        aid = int(row["id"])
        if aid >= current_agent_id:
            continue
        summary = str(row["summary"] or "").strip()
        if not summary:
            continue
        prompt = str(row["prompt"] or "").strip()
        finished.append((aid, prompt, summary))
    if limit > 0:
        finished = finished[-limit:]
    return finished


def _format_previous_exchanges(exchanges: list[tuple[int, str, str]]) -> str:
    if not exchanges:
        return ""
    parts: list[str] = [
        "Most recent ``/agent`` run in this session. Use it as context "
        "for any follow-up in the current task.\n"
    ]
    for aid, prompt, summary in exchanges:
        p = _clip_for_history(prompt, _AGENT_HISTORY_ENTRY_MAX_CHARS)
        s = _clip_for_history(summary, _AGENT_HISTORY_ENTRY_MAX_CHARS)
        parts.append(f"### /agent #{aid}\n**Prompt:**\n{p}\n\n**Response:**\n{s}\n")
    return "\n".join(parts)


def build_agent_packet(
    *,
    researcher_root: Path,
    prompt: str,
    current_branch: str,
    max_chars: int | None,
    previous_exchanges: list[tuple[int, str, str]] | None = None,
) -> str:
    """Build a generic agent packet: shared guidance + Tier A, no role prompt."""
    extra: dict[str, str] = {}
    shared_work = shared_prompt.SHARED_WORK_GUIDANCE.strip()
    shared = shared_prompt.MEMORY_AND_TIER_A.strip()
    if shared_work:
        extra["Shared guidance"] = shared_work
    if shared:
        extra["Memory & Tier A"] = shared
    history = _format_previous_exchanges(previous_exchanges or [])
    if history:
        extra["Previous /agent exchanges"] = history
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
        previous_exchanges = _collect_previous_exchanges(conn, current_agent_id=agent_id)
        packet = build_agent_packet(
            researcher_root=researcher_root,
            prompt=prompt,
            current_branch=memory.current_git_branch(project_dir),
            max_chars=cfg.worker_packet_max_chars,
            previous_exchanges=previous_exchanges,
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
