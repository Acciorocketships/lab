"""Orchestrator routing without API key."""

from pathlib import Path

from research_lab.config import RunConfig
from research_lab.orchestrator import decide_orchestrator


def test_no_api_key_is_noop(tmp_path: Path, monkeypatch) -> None:
    """Without OPENAI_API_KEY or token file, orchestrator returns noop."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path,
        research_idea="x",
        acceptance_criteria="y",
        preferences="z",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
    )
    d = decide_orchestrator("context", model="gpt-4o-mini", cfg=cfg)
    assert d.worker == "noop"
