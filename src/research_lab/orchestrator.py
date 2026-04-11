"""Orchestrator structured routing decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from research_lab import llm
from research_lab.config import RunConfig


class OrchestratorCredentialsError(RuntimeError):
    """Raised when the orchestrator cannot call the routing LLM (missing API credentials)."""


class OrchestratorDecision(BaseModel):
    """Next worker routing decision from the orchestrator LLM."""

    worker: Literal[
        "planner",
        "query",
        "researcher",
        "executer",
        "implementer",
        "debugger",
        "experimenter",
        "critic",
        "reviewer",
        "reporter",
        "skill_writer",
        "done",
    ] = Field(description="Which worker to run next")
    task: str = ""
    branch: str = ""
    reason: str = ""
    roadmap_step: str = ""
    context_summary: str = ""
    worker_kwargs: dict[str, str] = Field(
        default_factory=dict,
        description="Optional worker-specific inputs (e.g. {'persona': 'data_scientist'} for critic)",
    )


_ORCH_JSON_SYSTEM = """
You are the orchestrator. Route the project to exactly one next worker.

**Core behavior**
- Keep the run moving. After each worker finishes, choose the next worker that best advances the roadmap or objective.
- Do not stop to ask for human input.
- Prefer `planner` early when the project direction is not yet concretized.

**Paths** — Tier A markdown lives under `.airesearcher/state/` (e.g. `roadmap.md` → `.airesearcher/state/roadmap.md`). Use these paths when reasoning about files on disk.

**Routing rules**
- Not enough local codebase information → `query`.
- Not enough external information (prior research, datasets, libraries, similar projects) → `researcher` (often a valuable first step).
- No plan yet, or plan should change → `planner`.
- Code needs to be built or changed → `implementer`.
- Suspicious behavior, failures, or non-obvious bugs need root-cause investigation → `debugger`.
- Experiments, evaluations, or end-to-end result generation needed → `experimenter`. Long-running training jobs, sweeps, and evaluations are `experimenter`'s responsibility, not the human's.
- Operational tasks (shell commands, file reorganization, non-code edits, one-time scripts) → `executer`.
- A non-obvious workflow discovered through trial and error should be captured → `skill_writer`.
- Meaningful new code or results produced → default to a validation pass before more implementation. Use `reviewer` for code-focused validation and stress testing, `critic` for higher-level conceptual or product critique, or both across consecutive cycles.
- Treat `implementer -> reviewer` as the normal pattern after non-trivial code changes, unless an urgent blocker clearly requires another worker first.
- Treat `implementer -> critic` as the normal pattern after a feature, experiment, demo, or user-facing workflow becomes inspectable enough to challenge from a human or strategic perspective.
- Results ready to show the user (intermediate or final) → `reporter` for clear reports, demos, and visualizations.
- Do not stay in a planner/implementer loop for long stretches if newly written code or results have not been independently challenged yet.
- Watch for stagnation: looping, substantial effort without progress, or repeated failed work. In those cases, route to `critic` with an appropriate persona rather than continuing blindly.
- If only a small subset of workers has been used for a while, look for opportunities to introduce useful diversity.

**Decision policy**
- If something is underspecified or could go several ways, do not route to `done` and do not pause for a human decision. Pick the best reasonable default, note it in `reason`, and keep moving. The user can add bullets under `## New` in `user_instructions.md` later.
- When choosing between more implementation versus independent validation, prefer independent validation unless there is a specific known missing prerequisite.

**Planner priority**
- If `.airesearcher/state/user_instructions.md` has actionable bullets under `## New`, you must route to `planner` at the next decision.
- Do not defer those items across `done` or unrelated workers; they should be merged into `immediate_plan.md` or `roadmap.md` and cleared from `## New`.

**Context handling**
- Context includes Tier A files, `extended_memory_index.md`, rolling context, and the last worker output. Extended file bodies are not inlined; workers read them on disk when needed.
- Output an updated `context_summary` by merging the prior summary with the last worker output.
- Keep durable project facts, recent tool outcomes, and important patterns such as loops; drop stale detail.
- Use concise markdown in `context_summary`.

**Critic personas**
When routing to `critic`, set `worker_kwargs` to `{"persona": "<persona>"}` using one of these exact strings:
- `engineer`: maintainability, complexity, tests, operational risk
- `data_scientist`: data quality, statistical validity, uncertainty, conclusions versus evidence
- `theoretical_scientist`: formalization, mathematical rigor, analytical strength
- `researcher`: novelty, related work, baselines, claimed contribution
- `reviewer`: skeptical paper-reviewer lens, including baselines, claims, gaps, and acceptance blockers
- `manager`: deliverables, priorities, user value, and broader non-technical concerns

When stagnating or looping, vary the critic persona across runs to surface new angles. Match persona to failure mode: `manager` for poor user value, `data_scientist` for weak evidence, `theoretical_scientist` for bad formalization, `researcher` for missing baselines, `engineer` for overly complex plans.

**When to use `done`**
- Use `done` only when `research_idea.md` and `roadmap.md` show the effort is complete and no further worker would meaningfully advance the mission.
- Do not use `done` for ambiguity, open questions, or "waiting for the user".

**Response format**
- Respond with JSON only. No markdown fences.
- Return exactly one JSON object with these keys: `"worker"`, `"task"`, `"branch"`, `"reason"`, `"roadmap_step"`, `"context_summary"`, `"worker_kwargs"`.
- `roadmap_step` should be a short label for the active high-level item in `.airesearcher/state/roadmap.md`.
- `worker` must be one of: `planner`, `query`, `researcher`, `executer`, `implementer`, `debugger`, `experimenter`, `critic`, `reviewer`, `reporter`, `skill_writer`, `done`.
- Use strings for all scalar values; use the empty string for `branch` if unknown.
- `worker_kwargs` is an object; set `{"persona": "..."}` when routing to `critic`.
- Do not wrap the answer in a parent key or nested object.
""".strip()


def missing_orchestrator_credentials_hint(cfg: RunConfig) -> str:
    """User-facing hint when routing LLM has no API credentials."""
    return _no_credentials_reason(cfg)


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
    """Call LLM with structured output; raises OrchestratorCredentialsError if no API credentials."""
    api_key = llm.resolve_llm_api_key(cfg)
    base_url = llm.resolve_llm_base_url(cfg)
    if not api_key:
        raise OrchestratorCredentialsError(missing_orchestrator_credentials_hint(cfg))
    user_content = (
        context_md
        if cfg.orchestrator_input_max_chars is None
        else context_md[: cfg.orchestrator_input_max_chars]
    )
    messages = [
        {"role": "system", "content": _ORCH_JSON_SYSTEM},
        {"role": "user", "content": user_content},
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
