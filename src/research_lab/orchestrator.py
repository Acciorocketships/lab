"""Orchestrator structured routing decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from research_lab import llm
from research_lab.config import RunConfig


class OrchestratorDecision(BaseModel):
    """Next worker routing decision from the orchestrator LLM."""

    worker: Literal[
        "planner",
        "researcher",
        "executer",
        "implementer",
        "debugger",
        "experimenter",
        "critic",
        "reviewer",
        "reporter",
        "skill_writer",
        "noop",
    ] = Field(description="Which worker to run next")
    task: str = ""
    branch: str = ""
    reason: str = ""
    roadmap_step: str = ""
    context_summary: str = ""


_ORCH_JSON_SYSTEM = (
    "You route research tasks to one worker. Prefer planner early, noop only if blocked.\n"
    "If `user_instructions.md` has any **actionable bullets under `## New`** (user input from the console), you must "
    "route to **planner** at the **next** decision—do not defer across noop or unrelated workers until those items are "
    "merged into `immediate_plan.md` / `roadmap.md` and cleared from `## New` (see shared worker instructions). "
    "Choose another worker first only when truly blocked (e.g. missing credentials); otherwise planner handles user "
    "instructions as soon as they appear.\n"
    "Context includes Tier A summaries, rolling context, last worker output, and paths to memory/extended/*.md; "
    "extended file bodies are not inlined—workers read them on disk when needed.\n"
    "You must output an updated **context_summary**: merge prior summary with the last worker output—keep "
    "project facts, recent tool outcomes, and patterns (e.g. loops); drop stale detail. Use markdown, stay concise.\n"
    "Routing hints: use **researcher** whenever you need more information—web or papers, questions about the "
    "codebase or files, or exploring the repo to answer a question. Use **executer** for one-off tasks: shell commands, "
    "temporary scripts, operational edits to non-code files—not product code changes (that is **implementer**).\n"
    "Respond with JSON only (no markdown fences). One JSON object with exactly these keys: "
    '"worker", "task", "branch", "reason", "roadmap_step", "context_summary". '
    "roadmap_step: short label for the active high-level item in roadmap.md. "
    "worker must be one of: planner, researcher, executer, implementer, debugger, "
    "experimenter, critic, reviewer, reporter, skill_writer, noop. "
    'Use strings for all values; use empty string for branch if unknown. '
    "Do not wrap the answer in a parent key or nested objects."
)


def _no_credentials_reason(cfg: RunConfig) -> str:
    b = (cfg.orchestrator_backend or "openai").lower()
    if b == "openai":
        return "set OPENAI_API_KEY or run OAuth login (PKCE)"
    if b == "openrouter":
        return "set OPENROUTER_API_KEY or RunConfig.openrouter_api_key"
    if b == "local":
        return "set LOCAL_LLM_BASE_URL / openai_base_url; key via openai_api_key, OPENAI_API_KEY, or LOCAL_LLM_API_KEY"
    return "configure LLM credentials"


def decide_orchestrator(
    context_md: str,
    *,
    model: str,
    cfg: RunConfig,
) -> OrchestratorDecision:
    """Call LLM with structured output, or deterministic noop if no credentials."""
    api_key = llm.resolve_llm_api_key(cfg)
    base_url = llm.resolve_llm_base_url(cfg)
    if not api_key:
        return OrchestratorDecision(
            worker="noop",
            task="no credentials",
            reason=_no_credentials_reason(cfg),
            roadmap_step="",
            context_summary="",
        )
    messages = [
        {"role": "system", "content": _ORCH_JSON_SYSTEM},
        {"role": "user", "content": context_md[:12000]},
    ]
    out = llm.generate(
        messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        response_format=OrchestratorDecision,
    )
    assert isinstance(out, OrchestratorDecision)
    return out
