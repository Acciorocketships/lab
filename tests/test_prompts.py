"""Prompt guardrails for Tier A and internal maintenance workers."""

from lab.agents import memory_compactor, planner, shared_prompt


def test_user_instructions_prompt_forbids_internal_bookkeeping() -> None:
    """Shared guidance should keep internal agent status out of user instructions."""
    text = shared_prompt.MEMORY_AND_TIER_A
    assert "Do not use this file for agent task tracking" in text
    assert "only user instructions" in text


def test_planner_prompt_forbids_internal_completion_logs_in_user_instructions() -> None:
    """Planner-specific guidance should not invite internal task logs into user instructions."""
    text = planner.SYSTEM_PROMPT
    assert "Do not add planner tasks" in text
    assert "actual user instructions" in text


def test_memory_compactor_prompt_protects_system_files() -> None:
    """The internal compactor should avoid system-managed files."""
    text = memory_compactor.SYSTEM_PROMPT
    assert "system.md" in text
    assert "context_summary.md" in text
    assert "Do **not** edit" in text
