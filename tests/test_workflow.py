"""LangGraph workflow smoke."""

import json

from pathlib import Path

import pytest

from lab import db, memory
from lab.config import RunConfig
from lab.orchestrator import OrchestratorCredentialsError, OrchestratorDecision
from lab.state import ResearchState
from lab.workflows import research_graph


def test_graph_invoke_raises_without_credentials(tmp_path: Path, monkeypatch) -> None:
    """Choose step raises when no API key (orchestrator cannot route)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    (tmp_path / "p").mkdir()
    app = research_graph.build_graph(cfg, db_path=tmp_path / "db.sqlite", researcher_root=tmp_path, project_dir=tmp_path / "p")
    st: ResearchState = {
        "current_goal": "t",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
    }
    with pytest.raises(OrchestratorCredentialsError):
        app.invoke(st)


def test_graph_invoke_done_sets_acceptance(tmp_path: Path, monkeypatch) -> None:
    """Orchestrator routing to done skips worker CLI and sets acceptance_satisfied."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def _fake_decide(*args, **kwargs) -> OrchestratorDecision:
        return OrchestratorDecision(
            worker="done",
            task="finished",
            reason="acceptance criteria met",
            roadmap_step="",
            context_summary="",
        )

    monkeypatch.setattr(research_graph.orchestrator, "decide_orchestrator", _fake_decide)

    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    (tmp_path / "p").mkdir()
    app = research_graph.build_graph(cfg, db_path=tmp_path / "db.sqlite", researcher_root=tmp_path, project_dir=tmp_path / "p")
    st: ResearchState = {
        "current_goal": "t",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
    }
    out = app.invoke(st)
    assert out.get("acceptance_satisfied") is True
    assert out["current_worker"] == "done"


def test_execute_worker_query_uses_query_prompt(tmp_path: Path, monkeypatch) -> None:
    """Routing to query should build a packet with the query worker prompt."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    captured: dict[str, str] = {}

    def _fake_run_worker(pkt: str, **kwargs) -> dict[str, object]:
        captured["packet"] = pkt
        return {"ok": True, "parsed": {"result": "Mapped the relevant files"}}

    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "Find where routing decisions are defined",
        "current_branch": "",
        "current_worker": "query",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "Find where routing decisions are defined",
        "orchestrator_reason": "Need codebase facts before planning",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    out = research_graph.execute_worker(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
    )

    assert out["worker_ok"] is True
    packet = captured["packet"]
    assert "# Worker: query" in packet
    assert "You are the Query agent." in packet
    assert "Search the local codebase and researcher files" in packet


def test_execute_worker_retries_after_empty_output_with_smaller_packet(tmp_path: Path, monkeypatch) -> None:
    """An empty worker response should trigger one retry with a bounded packet."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    original_build_packet = research_graph.packets.build_worker_packet

    def _fake_build_worker_packet(*args, max_chars=None, **kwargs) -> str:
        if max_chars is None:
            return "A" * 150_000
        return original_build_packet(*args, max_chars=max_chars, **kwargs)

    monkeypatch.setattr(research_graph.packets, "build_worker_packet", _fake_build_worker_packet)

    seen_packets: list[str] = []

    def _fake_run_worker(pkt: str, **kwargs) -> dict[str, object]:
        seen_packets.append(pkt)
        if len(seen_packets) == 1:
            return {
                "ok": False,
                "error": "cursor agent returned no output",
                "stdout": "",
                "stderr": "",
                "parsed": {"error": "empty_output"},
            }
        return {"ok": True, "parsed": {"result": "Recovered on retry"}}

    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "Plan the next phase",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "Plan the next phase",
        "orchestrator_reason": "Planning is stale",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    out = research_graph.execute_worker(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=tmp_path / "runtime.db",
    )

    assert out["worker_ok"] is True
    assert out["last_action_summary"] == "Recovered on retry"
    assert len(seen_packets) == 2
    assert len(seen_packets[0]) > len(seen_packets[1])
    assert len(seen_packets[1]) <= 120_100


def test_choose_action_pre_orchestrator_runs_memory_compactor_when_tier_file_large(
    tmp_path: Path, monkeypatch,
) -> None:
    """Oversized Tier A on disk is compacted before ``decide_orchestrator`` reads it."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()
    (memory.state_dir(tmp_path) / "roadmap.md").write_text("H" * 75_000, encoding="utf-8")

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    def _fake_decide(_ctx: str, **_kw: object) -> OrchestratorDecision:
        return OrchestratorDecision(
            worker="planner",
            task="next",
            reason="test",
            roadmap_step="",
            context_summary="",
            worker_kwargs={},
        )

    packets_seen: list[str] = []

    def _fake_run_worker(pkt: str, **_kw: object) -> dict[str, object]:
        packets_seen.append(pkt)
        if "# Worker: memory_compactor" in pkt:
            (memory.state_dir(tmp_path) / "roadmap.md").write_text("compacted\n", encoding="utf-8")
            return {"ok": True, "parsed": {"result": "compacted"}}
        raise AssertionError(f"unexpected worker packet: {pkt[:120]!r}")

    monkeypatch.setattr(research_graph.orchestrator, "decide_orchestrator", _fake_decide)
    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "Plan the next phase",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "Plan the next phase",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )

    assert len(packets_seen) == 1
    assert "# Worker: memory_compactor" in packets_seen[0]
    st = memory.read_pre_orchestrator_compact_state(tmp_path)
    assert st is not None
    th = st.get("file_thresholds", {})
    assert th.get("roadmap.md") == max(
        research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS,
        len("compacted\n"),
    )


def test_choose_action_pre_orchestrator_persists_post_compact_size_when_above_floor(
    tmp_path: Path, monkeypatch,
) -> None:
    """If compaction still leaves a file above the default floor, the saved line is that size (not the floor)."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()
    (memory.state_dir(tmp_path) / "roadmap.md").write_text("H" * 75_000, encoding="utf-8")

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    post_compact = "x" * 25_123

    monkeypatch.setattr(
        research_graph.orchestrator,
        "decide_orchestrator",
        lambda *_a, **_k: OrchestratorDecision(
            worker="planner",
            task="next",
            reason="test",
            roadmap_step="",
            context_summary="",
            worker_kwargs={},
        ),
    )

    def _fake_run_worker(pkt: str, **_kw: object) -> dict[str, object]:
        if "# Worker: memory_compactor" in pkt:
            (memory.state_dir(tmp_path) / "roadmap.md").write_text(post_compact, encoding="utf-8")
            return {"ok": True, "parsed": {"result": "still big"}}
        raise AssertionError(f"unexpected worker packet: {pkt[:120]!r}")

    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "Plan the next phase",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "Plan the next phase",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )

    st = memory.read_pre_orchestrator_compact_state(tmp_path)
    assert st is not None
    th = st.get("file_thresholds", {})
    assert th.get("roadmap.md") == len(post_compact)
    assert len(post_compact) > research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS


def test_choose_action_pre_orchestrator_skips_compactor_under_saved_line(tmp_path: Path, monkeypatch) -> None:
    """No compaction when every file is at or below its persisted per-file line."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()
    (memory.state_dir(tmp_path) / "roadmap.md").write_text("a" * 30_000, encoding="utf-8")
    memory.write_pre_orchestrator_compact_state(
        tmp_path,
        {"file_thresholds": {"roadmap.md": 35_000}},
    )

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        research_graph.orchestrator,
        "decide_orchestrator",
        lambda *_a, **_k: OrchestratorDecision(
            worker="planner",
            task="t",
            reason="r",
            roadmap_step="",
            context_summary="",
            worker_kwargs={},
        ),
    )

    def _reject_run_worker(_pkt: str, **_kw: object) -> dict[str, object]:
        raise AssertionError("memory_compactor should not run when sizes are under saved lines")

    monkeypatch.setattr(research_graph.agents_base, "run_worker", _reject_run_worker)

    state: ResearchState = {
        "current_goal": "g",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
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

    research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )


def test_choose_action_pre_orchestrator_runs_when_file_grows_past_saved_line(
    tmp_path: Path, monkeypatch,
) -> None:
    """Compaction runs again when a file exceeds the line persisted from the prior cycle."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()
    (memory.state_dir(tmp_path) / "roadmap.md").write_text("b" * 36_000, encoding="utf-8")
    memory.write_pre_orchestrator_compact_state(
        tmp_path,
        {"file_thresholds": {"roadmap.md": 30_000}},
    )

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        research_graph.orchestrator,
        "decide_orchestrator",
        lambda *_a, **_k: OrchestratorDecision(
            worker="planner",
            task="t",
            reason="r",
            roadmap_step="",
            context_summary="",
            worker_kwargs={},
        ),
    )

    packets_seen: list[str] = []

    def _fake_run_worker(pkt: str, **_kw: object) -> dict[str, object]:
        packets_seen.append(pkt)
        if "# Worker: memory_compactor" in pkt:
            (memory.state_dir(tmp_path) / "roadmap.md").write_text("ok\n", encoding="utf-8")
            return {"ok": True, "parsed": {"result": "shrunk"}}
        raise AssertionError("expected memory_compactor only")

    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "g",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
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

    research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )

    assert len(packets_seen) == 1
    assert "# Worker: memory_compactor" in packets_seen[0]


def test_memory_compactor_is_internal_only() -> None:
    """The orchestrator cannot choose the internal compactor worker directly."""
    assert "memory_compactor" not in research_graph._WORKER_MODULES


def test_update_state_snapshots_immediate_plan_checklist(tmp_path: Path) -> None:
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    (memory.state_dir(tmp_path) / "immediate_plan.md").write_text(
        "# Immediate plan\n\n"
        "## Checklist\n\n"
        "- [x] Canonicalize immediate plan checklist\n"
        "  - [ ] Show it in the UI\n\n"
        "## Notes\n\n"
        "Extra context.\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "db.sqlite"
    state: ResearchState = {
        "current_goal": "t",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 1,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "updated the plan",
        "roadmap_step": "",
        "orchestrator_task": "update plan",
        "orchestrator_reason": "need a stable checklist",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_ok": True,
        "last_packet_relpath": "",
    }

    research_graph.update_state(
        state,
        cfg=cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
    )

    conn = db.connect_db(db_path)
    row = conn.execute(
        "SELECT payload_json FROM run_events WHERE kind = 'worker' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["immediate_plan_checklist"].startswith("## Checklist")
    assert "Show it in the UI" in payload["immediate_plan_checklist"]
    assert "## Notes" not in payload["immediate_plan_checklist"]


def test_run_loop_consumes_resume_while_paused(tmp_path: Path, monkeypatch) -> None:
    """Paused loop should process a queued resume before sleeping again."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    db.enqueue_event(conn, "resume", None)
    conn.commit()
    conn.close()

    invoked: list[ResearchState] = []

    class FakeApp:
        def invoke(self, state: ResearchState) -> dict[str, object]:
            invoked.append(state)
            return {"acceptance_satisfied": True}

    monkeypatch.setattr(research_graph, "build_graph", lambda *args, **kwargs: FakeApp())

    def _unexpected_sleep(_: float) -> None:
        raise AssertionError("run_loop slept despite a pending resume event")

    monkeypatch.setattr(research_graph.time, "sleep", _unexpected_sleep)

    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        checkpoint_path=tmp_path / "checkpoint.db",
    )

    assert len(invoked) == 1

    conn = db.connect_db(db_path)
    assert db.get_system_state(conn)["control_mode"] == "paused"
    assert db.fetch_pending_events(conn) == []
    conn.close()


def test_run_loop_survives_cycle_error(tmp_path: Path, monkeypatch) -> None:
    """A single cycle exception should not kill the loop — it retries and continues."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    call_count = 0

    class FlakyApp:
        def invoke(self, state: ResearchState) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated worker crash")
            return {"acceptance_satisfied": True}

    monkeypatch.setattr(research_graph, "build_graph", lambda *args, **kwargs: FlakyApp())
    monkeypatch.setattr(research_graph.time, "sleep", lambda _: None)

    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        checkpoint_path=tmp_path / "checkpoint.db",
    )

    assert call_count == 2, "loop should have retried after first error"

    conn = db.connect_db(db_path)
    rows = list(conn.execute(
        "SELECT summary, payload_json FROM run_events WHERE kind = 'worker' ORDER BY id"
    ))
    conn.close()
    assert len(rows) >= 1
    assert "cycle crashed" in rows[0]["summary"]


def test_run_loop_pauses_after_max_consecutive_errors(tmp_path: Path, monkeypatch) -> None:
    """After _MAX_CONSECUTIVE_ERRORS failures the loop should set mode to paused and exit."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    call_count = 0

    class AlwaysFailApp:
        def invoke(self, state: ResearchState) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent failure")

    monkeypatch.setattr(research_graph, "build_graph", lambda *args, **kwargs: AlwaysFailApp())
    monkeypatch.setattr(research_graph.time, "sleep", lambda _: None)

    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        checkpoint_path=tmp_path / "checkpoint.db",
    )

    assert call_count == research_graph._MAX_CONSECUTIVE_ERRORS

    conn = db.connect_db(db_path)
    assert db.get_system_state(conn)["control_mode"] == "paused"
    conn.close()


def test_run_loop_pauses_after_acceptance_satisfied(tmp_path: Path, monkeypatch) -> None:
    """A clean 'done' exit should pause the runtime so the console does not auto-restart it."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    class DoneApp:
        def invoke(self, state: ResearchState) -> dict[str, object]:
            return {"acceptance_satisfied": True}

    monkeypatch.setattr(research_graph, "build_graph", lambda *args, **kwargs: DoneApp())

    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        checkpoint_path=tmp_path / "checkpoint.db",
    )

    conn = db.connect_db(db_path)
    assert db.get_system_state(conn)["control_mode"] == "paused"
    conn.close()


def test_run_loop_graceful_pause_after_cycle(tmp_path: Path, monkeypatch) -> None:
    """When graceful_pause_pending is set, one successful cycle should leave mode paused."""
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    db.set_graceful_pause_pending(conn, True)
    conn.commit()
    conn.close()

    class CycleApp:
        def invoke(self, state: ResearchState) -> dict[str, object]:
            return {"cycle_count": 1, "current_worker": "planner"}

    monkeypatch.setattr(research_graph, "build_graph", lambda *a, **k: CycleApp())
    monkeypatch.setattr(research_graph.git_checkpoint, "create_checkpoint", lambda *a, **k: None)

    sleeps = 0

    def sleep_side_effect(_: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            c = db.connect_db(db_path)
            db.enqueue_event(c, "shutdown", None)
            c.commit()
            c.close()

    monkeypatch.setattr(research_graph.time, "sleep", sleep_side_effect)

    research_graph.run_loop(
        cfg,
        db_path=db_path,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        checkpoint_path=tmp_path / "checkpoint.db",
    )

    conn = db.connect_db(db_path)
    st = db.get_system_state(conn)
    assert st["control_mode"] == "shutdown"
    assert int(st.get("graceful_pause_pending", 0) or 0) == 0
    conn.close()


def test_choose_action_uses_forced_run_before_orchestrator(tmp_path: Path, monkeypatch) -> None:
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    db.set_forced_run(conn, "implementer", "Resolve merge conflicts")
    conn.commit()
    conn.close()

    def _unexpected_decide(*args, **kwargs):
        raise AssertionError("orchestrator should not run when a forced worker is pending")

    monkeypatch.setattr(research_graph.orchestrator, "decide_orchestrator", _unexpected_decide)

    state: ResearchState = {
        "current_goal": "t",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    out = research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )

    assert out["current_worker"] == "implementer"
    assert out["current_goal"] == "Resolve merge conflicts"

    conn = db.connect_db(db_path)
    assert db.get_forced_run(conn) is None
    rows = list(conn.execute("SELECT worker, task FROM run_events WHERE kind = 'orchestrator'"))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["worker"] == "implementer"
