"""Orchestrator routing without API key."""

from pathlib import Path

import pytest

from lab.config import RunConfig
from lab.orchestrator import (
    OrchestratorCredentialsError,
    OrchestratorDecision,
    _ORCH_JSON_SYSTEM,
    decide_orchestrator,
)
from lab.agents import critic, experimenter, planner, reviewer, shared_prompt


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
    assert "Treat `<code-producing worker> → reviewer` as the normal default" in _ORCH_JSON_SYSTEM
    assert "`critic` is best used after" in _ORCH_JSON_SYSTEM
    assert "prefer independent validation" in _ORCH_JSON_SYSTEM


def test_reviewer_and_critic_prompts_require_hands_on_validation() -> None:
    """Reviewer and critic should stress actual interaction, not only inspection."""
    assert "stress test" in reviewer.SYSTEM_PROMPT
    assert "like a real user" in reviewer.SYSTEM_PROMPT
    assert "interact with it like a human" in critic.SYSTEM_PROMPT
    assert "recommend the missing demo surface, harness, or artifact" in critic.critic_prompt("engineer")


def test_orchestrator_and_experimenter_prompts_assign_long_runs_to_experimenter() -> None:
    """Long-running experiments should be launched and monitored by the experimenter."""
    assert "If a training job takes hours, `experimenter` owns the entire lifecycle" in _ORCH_JSON_SYSTEM
    assert "experimenter" in _ORCH_JSON_SYSTEM
    assert "Do not assume a human or another agent will do it" in experimenter.SYSTEM_PROMPT
    assert "Check back periodically" in experimenter.SYSTEM_PROMPT


def test_orchestrator_prompt_requires_live_immediate_plan_and_subagent_diversity() -> None:
    """Routing prompt should use system history and send stale planning back to planner."""
    assert "Use `system.md`'s recent subagent history" in _ORCH_JSON_SYSTEM
    assert "planning, implementation, review/testing, experimentation, debugging, critique, and reporting" in _ORCH_JSON_SYSTEM
    assert (
        "Route to `planner` whenever the current `immediate_plan.md` is missing, stale, finished, "
        "no longer matches the current roadmap phase, or contains human-gated completion criteria"
    ) in _ORCH_JSON_SYSTEM


def test_shared_and_planner_prompts_require_modular_incremental_checklists() -> None:
    """Shared worker and planner prompts should enforce modular, continuously updated plans."""
    assert "Break work into modular components" in shared_prompt.SHARED_WORK_GUIDANCE
    assert "All workers, not just planner, should maintain this file" in shared_prompt.MEMORY_AND_TIER_A
    assert "**`context_summary.md`** — **Orchestrator-owned only.**" in shared_prompt.MEMORY_AND_TIER_A
    assert "The orchestrator overwrites this file" in shared_prompt.MEMORY_AND_TIER_A
    assert "including implementation, testing, experiments, debugging, review, or reporting" in planner.SYSTEM_PROMPT
    assert "Prefer checklists that track modular components and validation points" in planner.SYSTEM_PROMPT
