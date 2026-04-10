"""Orchestrator routing without API key."""

from pathlib import Path

import pytest

from research_lab.config import RunConfig
from research_lab.orchestrator import (
    OrchestratorCredentialsError,
    OrchestratorDecision,
    _ORCH_JSON_SYSTEM,
    decide_orchestrator,
)
from research_lab.agents import critic, experimenter, reviewer


def test_no_api_key_raises(tmp_path: Path, monkeypatch) -> None:
    """Without OPENAI_API_KEY or token file, orchestrator raises OrchestratorCredentialsError."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path,
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    with pytest.raises(OrchestratorCredentialsError):
        decide_orchestrator("context", model="gpt-4o-mini", cfg=cfg)


def test_query_worker_is_valid_route() -> None:
    """The orchestrator schema accepts the codebase investigation worker."""
    dec = OrchestratorDecision(worker="query", task="Inspect workflow wiring")
    assert dec.worker == "query"


def test_orchestrator_prompt_biases_toward_post_implementation_review() -> None:
    """Routing prompt should encourage reviewer/critic after implementation."""
    assert "Treat `implementer -> reviewer` as the normal pattern" in _ORCH_JSON_SYSTEM
    assert "Treat `implementer -> critic` as the normal pattern" in _ORCH_JSON_SYSTEM
    assert "prefer independent validation" in _ORCH_JSON_SYSTEM


def test_reviewer_and_critic_prompts_require_hands_on_validation() -> None:
    """Reviewer and critic should stress actual interaction, not only inspection."""
    assert "stress test" in reviewer.SYSTEM_PROMPT
    assert "acting as a user" in reviewer.SYSTEM_PROMPT
    assert "interact with it the way a human would want to" in critic.SYSTEM_PROMPT
    assert "request the missing harness, demo, or artifact" in critic.critic_prompt("engineer")


def test_orchestrator_and_experimenter_prompts_assign_long_runs_to_experimenter() -> None:
    """Long-running experiments should be launched and monitored by the experimenter."""
    assert "Long-running training jobs, evaluations, sweeps" in _ORCH_JSON_SYSTEM
    assert "actually launching runs, training jobs, sweeps, and evaluations" in _ORCH_JSON_SYSTEM
    assert "Do not assume a human will kick off training runs" in experimenter.SYSTEM_PROMPT
    assert "check back periodically" in experimenter.SYSTEM_PROMPT
