"""Optimisation-loop helpers: history ledger summaries, saturation checks, and LLM judging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lab import helpers
from lab.agents import base as agents_base
from lab.config import RunConfig

OPTIMISATION_HISTORY_MD = "optimisation_history.md"
OPTIMISATION_HISTORY_JSON = "optimisation_history.json"
SATURATION_LOOKBACK = 3
SATURATION_RELATIVE_GAIN_THRESHOLD = 0.01
_EPSILON = 1e-12


class OptimisationIteration(BaseModel):
    """One completed optimiser iteration."""

    model_config = ConfigDict(extra="ignore")

    iteration: int | None = None
    timestamp: str = ""
    experiment_id: str = ""
    parent_branch: str = ""
    candidate_branch: str = ""
    status: Literal["baseline_only", "merged", "rejected", "error"] = "baseline_only"
    summary: str = ""
    primary_metric: str = ""
    higher_is_better: bool = True
    baseline_value: float | None = None
    candidate_value: float | None = None
    marginal_gain: float | None = None
    relative_gain: float | None = None
    improved: bool | None = None
    qualitative: bool = False
    judgement_mode: str = ""
    parent_report: str = ""
    candidate_report: str = ""


class OptimisationHistory(BaseModel):
    """Machine-readable optimisation ledger kept in extended memory."""

    model_config = ConfigDict(extra="ignore")

    objective: str = ""
    optimisation_active: bool = False
    saturation_detected: bool = False
    saturation_reason: str = ""
    primary_metric: str = ""
    higher_is_better: bool = True
    best_iteration: int | None = None
    best_value: float | None = None
    iterations: list[OptimisationIteration] = Field(default_factory=list)


class OptimisationSaturationStatus(BaseModel):
    """Compact orchestration signal derived from the optimisation ledger."""

    active: bool = False
    saturated: bool = False
    reason: str = ""
    lookback: int = SATURATION_LOOKBACK
    recent_relative_gains: list[float] = Field(default_factory=list)
    best_iteration: int | None = None
    best_value: float | None = None


class LLMJudgeVerdict(BaseModel):
    """Relative judgement between baseline and candidate qualitative outputs."""

    model_config = ConfigDict(extra="ignore")

    winner: Literal["candidate", "baseline", "tie"]
    candidate_score: float = Field(description="Relative score for the candidate output.")
    baseline_score: float = Field(description="Relative score for the baseline output.")
    confidence: float = Field(ge=0.0, le=1.0, description="Judge confidence from 0 to 1.")
    rationale: str = ""

    @property
    def improved(self) -> bool:
        return self.winner == "candidate"


def optimisation_history_md_path(researcher_root: Path) -> Path:
    """Human-readable optimisation log in extended memory."""
    return researcher_root / "memory" / "extended" / OPTIMISATION_HISTORY_MD


def optimisation_history_json_path(researcher_root: Path) -> Path:
    """Machine-readable optimisation ledger in extended memory."""
    return researcher_root / "memory" / "extended" / OPTIMISATION_HISTORY_JSON


def default_optimisation_history_markdown() -> str:
    """Starter body for the human-readable optimisation log."""
    return (
        "# Optimisation History\n\n"
        "Track each optimiser iteration here and keep it in sync with `optimisation_history.json`.\n\n"
        "## Latest summary\n\n"
        "- Objective: \n"
        "- Best result so far: \n"
        "- Saturation status: \n\n"
        "## Iterations\n\n"
        "- Iteration 0: baseline not recorded yet.\n"
    )


def default_optimisation_history() -> OptimisationHistory:
    """Empty machine-readable optimisation ledger."""
    return OptimisationHistory()


def load_optimisation_history(researcher_root: Path) -> OptimisationHistory:
    """Read the optimisation JSON ledger, falling back to an empty history."""
    raw = helpers.read_json(optimisation_history_json_path(researcher_root), default={})
    if not isinstance(raw, dict):
        return default_optimisation_history()
    try:
        return OptimisationHistory.model_validate(raw)
    except Exception:
        return default_optimisation_history()


def write_optimisation_history(researcher_root: Path, history: OptimisationHistory) -> None:
    """Persist the machine-readable optimisation ledger."""
    helpers.write_json(
        optimisation_history_json_path(researcher_root),
        history.model_dump(mode="json"),
    )


def _normalised_relative_gain(entry: OptimisationIteration) -> float:
    if entry.relative_gain is not None:
        return float(entry.relative_gain)
    if entry.marginal_gain is not None and entry.baseline_value not in (None, 0):
        return float(entry.marginal_gain) / max(abs(float(entry.baseline_value)), _EPSILON)
    if entry.baseline_value is None or entry.candidate_value is None:
        return 0.0
    baseline = float(entry.baseline_value)
    candidate = float(entry.candidate_value)
    delta = candidate - baseline if entry.higher_is_better else baseline - candidate
    if abs(baseline) <= _EPSILON:
        return delta
    return delta / abs(baseline)


def saturation_status(
    history: OptimisationHistory,
    *,
    lookback: int = SATURATION_LOOKBACK,
    relative_gain_threshold: float = SATURATION_RELATIVE_GAIN_THRESHOLD,
) -> OptimisationSaturationStatus:
    """Estimate whether recent optimiser iterations have meaningfully saturated."""
    active = bool(history.optimisation_active or history.iterations)
    recent = [
        entry
        for entry in history.iterations
        if entry.status in {"merged", "rejected", "error"}
    ][-lookback:]
    gains = [_normalised_relative_gain(entry) for entry in recent]

    if not active:
        return OptimisationSaturationStatus(
            active=False,
            saturated=False,
            reason="No optimisation loop is active.",
            lookback=lookback,
            best_iteration=history.best_iteration,
            best_value=history.best_value,
        )

    if history.saturation_detected:
        return OptimisationSaturationStatus(
            active=True,
            saturated=True,
            reason=history.saturation_reason or "Optimisation history explicitly marks the loop as saturated.",
            lookback=lookback,
            recent_relative_gains=gains,
            best_iteration=history.best_iteration,
            best_value=history.best_value,
        )

    if len(recent) < lookback:
        return OptimisationSaturationStatus(
            active=True,
            saturated=False,
            reason=(
                f"Only {len(recent)} completed optimiser iteration(s) are recorded; "
                f"need {lookback} to judge saturation."
            ),
            lookback=lookback,
            recent_relative_gains=gains,
            best_iteration=history.best_iteration,
            best_value=history.best_value,
        )

    if all(gain <= relative_gain_threshold for gain in gains):
        pct = relative_gain_threshold * 100.0
        return OptimisationSaturationStatus(
            active=True,
            saturated=True,
            reason=(
                f"The last {lookback} optimiser iterations each delivered <= {pct:.1f}% "
                "relative improvement."
            ),
            lookback=lookback,
            recent_relative_gains=gains,
            best_iteration=history.best_iteration,
            best_value=history.best_value,
        )

    return OptimisationSaturationStatus(
        active=True,
        saturated=False,
        reason="Recent optimiser iterations still show meaningful headroom.",
        lookback=lookback,
        recent_relative_gains=gains,
        best_iteration=history.best_iteration,
        best_value=history.best_value,
    )


def optimisation_context_for_orchestrator(researcher_root: Path) -> str:
    """Short optimisation summary appended to orchestrator context when present."""
    history = load_optimisation_history(researcher_root)
    status = saturation_status(history)
    if not status.active:
        return ""

    gains = ", ".join(f"{gain * 100:.2f}%" for gain in status.recent_relative_gains) or "n/a"
    best = (
        f"iteration {status.best_iteration} ({status.best_value})"
        if status.best_iteration is not None and status.best_value is not None
        else "n/a"
    )
    human_path = optimisation_history_md_path(researcher_root)
    machine_path = optimisation_history_json_path(researcher_root)
    return (
        "## Optimisation loop status\n\n"
        f"- Objective: {history.objective or 'n/a'}\n"
        f"- Active: {'yes' if status.active else 'no'}\n"
        f"- Saturated: {'yes' if status.saturated else 'no'}\n"
        f"- Reason: {status.reason}\n"
        f"- Best result: {best}\n"
        f"- Recent relative gains: {gains}\n"
        f"- History files: `{human_path}` and `{machine_path}`\n"
    )


def _judge_prompt(
    *,
    objective: str,
    baseline_label: str,
    baseline_output: str,
    candidate_label: str,
    candidate_output: str,
    baseline_artifact_path: str,
    candidate_artifact_path: str,
    extra_context: str,
) -> str:
    return (
        "You are an LLM-as-judge for optimisation experiments.\n\n"
        "Compare the baseline and candidate outputs relative to the stated objective. "
        "Use both inputs. Prefer the candidate only if it is clearly better overall; if the "
        "outputs are comparable or the evidence is weak, return a tie.\n\n"
        "Return JSON only with keys: "
        "`winner`, `candidate_score`, `baseline_score`, `confidence`, `rationale`.\n"
        "- `winner` must be one of `candidate`, `baseline`, or `tie`.\n"
        "- Scores should be on a shared relative scale where higher is better.\n"
        "- `confidence` must be between 0 and 1.\n\n"
        f"Objective:\n{objective.strip()}\n\n"
        f"Baseline label: {baseline_label}\n"
        f"Candidate label: {candidate_label}\n\n"
        f"Baseline artifact path (inspect if useful): {baseline_artifact_path or 'n/a'}\n"
        f"Candidate artifact path (inspect if useful): {candidate_artifact_path or 'n/a'}\n\n"
        f"Extra context:\n{extra_context.strip() or 'n/a'}\n\n"
        f"Baseline output:\n{baseline_output.strip()}\n\n"
        f"Candidate output:\n{candidate_output.strip()}\n"
    )


def _candidate_json_objects(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stripped = (text or "").strip()
    if not stripped:
        return out
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        out.append(parsed)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _extract_judge_verdict(result: dict[str, Any]) -> LLMJudgeVerdict:
    parsed = result.get("parsed")
    candidates: list[dict[str, Any]] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
        for key in ("result", "raw"):
            value = parsed.get(key)
            if isinstance(value, str):
                candidates.extend(_candidate_json_objects(value))
    elif isinstance(parsed, str):
        candidates.extend(_candidate_json_objects(parsed))

    stdout = result.get("stdout")
    if isinstance(stdout, str):
        candidates.extend(_candidate_json_objects(stdout))

    for candidate in candidates:
        try:
            return LLMJudgeVerdict.model_validate(candidate)
        except Exception:
            continue

    raise ValueError(f"Could not parse LLM judge verdict from result: {result!r}")


class LLMAsJudge:
    """Run a qualitative relative judgement with the same backend as subagents."""

    def __init__(self, cfg: RunConfig, *, project_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.project_dir = project_dir or cfg.project_dir

    def judge(
        self,
        *,
        objective: str,
        baseline_label: str,
        baseline_output: str,
        candidate_label: str,
        candidate_output: str,
        baseline_artifact_path: str = "",
        candidate_artifact_path: str = "",
        extra_context: str = "",
    ) -> LLMJudgeVerdict:
        """Judge baseline vs candidate using the configured worker backend."""
        backend = self.cfg.default_worker_backend
        if backend not in ("claude", "cursor"):
            backend = "cursor"
        prompt = _judge_prompt(
            objective=objective,
            baseline_label=baseline_label,
            baseline_output=baseline_output,
            candidate_label=candidate_label,
            candidate_output=candidate_output,
            baseline_artifact_path=baseline_artifact_path,
            candidate_artifact_path=candidate_artifact_path,
            extra_context=extra_context,
        )
        result = agents_base.run_worker(
            prompt,
            backend=backend,
            project_cwd=self.project_dir,
            cursor_agent_model=self.cfg.cursor_agent_model,
        )
        return _extract_judge_verdict(result)
