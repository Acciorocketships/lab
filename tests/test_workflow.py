"""LangGraph workflow smoke."""

from pathlib import Path

import pytest

from research_lab import memory
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
        research_idea="x",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
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
        research_idea="x",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
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
