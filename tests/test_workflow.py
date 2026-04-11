"""LangGraph workflow smoke."""

from pathlib import Path

import pytest

from research_lab import db, memory
from research_lab.config import RunConfig
from research_lab.orchestrator import OrchestratorCredentialsError, OrchestratorDecision
from research_lab.state import ResearchState
from research_lab.workflows import research_graph


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
