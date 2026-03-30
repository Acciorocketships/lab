"""LangGraph workflow smoke."""

from pathlib import Path

from research_lab import memory
from research_lab.config import RunConfig
from research_lab.state import ResearchState
from research_lab.workflows import research_graph


def test_graph_invoke_noop(tmp_path: Path, monkeypatch) -> None:
    """One cycle runs with noop worker when no API key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        research_idea="x",
        acceptance_criteria="y",
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
        "current_worker": "noop",
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
    assert out["current_worker"] in ("noop", "planner")
