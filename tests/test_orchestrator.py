"""Orchestrator routing without API key."""

from pathlib import Path

import pytest

from research_lab.config import RunConfig
from research_lab.orchestrator import OrchestratorCredentialsError, decide_orchestrator


def test_no_api_key_raises(tmp_path: Path, monkeypatch) -> None:
    """Without OPENAI_API_KEY or token file, orchestrator raises OrchestratorCredentialsError."""
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
    with pytest.raises(OrchestratorCredentialsError):
        decide_orchestrator("context", model="gpt-4o-mini", cfg=cfg)
