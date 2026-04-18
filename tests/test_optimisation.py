"""Optimisation helpers and judge parsing."""

from __future__ import annotations

from pathlib import Path

from lab.config import RunConfig
from lab.optimisation import (
    LLMAsJudge,
    OptimisationHistory,
    OptimisationIteration,
    _extract_judge_verdict,
    load_optimisation_history,
    optimisation_context_for_orchestrator,
    optimisation_history_json_path,
    saturation_status,
    write_optimisation_history,
)


def _cfg(tmp_path: Path) -> RunConfig:
    return RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "project",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )


def test_saturation_status_detects_flat_recent_iterations() -> None:
    history = OptimisationHistory(
        objective="maximize reward",
        optimisation_active=True,
        best_iteration=4,
        best_value=10.0,
        iterations=[
            OptimisationIteration(iteration=2, status="merged", relative_gain=0.04, improved=True),
            OptimisationIteration(iteration=3, status="merged", relative_gain=0.009, improved=True),
            OptimisationIteration(iteration=4, status="rejected", relative_gain=0.0, improved=False),
            OptimisationIteration(iteration=5, status="merged", relative_gain=0.003, improved=True),
        ],
    )

    status = saturation_status(history)

    assert status.active is True
    assert status.saturated is True
    assert status.best_iteration == 4
    assert "last 3 optimiser iterations" in status.reason


def test_write_and_load_optimisation_history_roundtrip(tmp_path: Path) -> None:
    history = OptimisationHistory(
        objective="lower loss",
        optimisation_active=True,
        iterations=[
            OptimisationIteration(
                iteration=1,
                status="merged",
                primary_metric="loss",
                higher_is_better=False,
                baseline_value=1.0,
                candidate_value=0.8,
                marginal_gain=0.2,
                relative_gain=0.2,
                improved=True,
            )
        ],
    )

    write_optimisation_history(tmp_path, history)
    loaded = load_optimisation_history(tmp_path)

    assert optimisation_history_json_path(tmp_path).is_file()
    assert loaded.objective == "lower loss"
    assert loaded.iterations[0].candidate_value == 0.8


def test_optimisation_context_for_orchestrator_includes_status(tmp_path: Path) -> None:
    write_optimisation_history(
        tmp_path,
        OptimisationHistory(
            objective="improve judged output quality",
            optimisation_active=True,
            best_iteration=2,
            best_value=8.7,
            iterations=[
                OptimisationIteration(iteration=1, status="merged", relative_gain=0.08, improved=True),
                OptimisationIteration(iteration=2, status="merged", relative_gain=0.03, improved=True),
            ],
        ),
    )

    text = optimisation_context_for_orchestrator(tmp_path)

    assert "## Optimisation loop status" in text
    assert "improve judged output quality" in text
    assert "optimisation_history.json" in text


def test_extract_judge_verdict_accepts_nested_result_json() -> None:
    verdict = _extract_judge_verdict(
        {
            "ok": True,
            "parsed": {
                "result": (
                    '{"winner":"candidate","candidate_score":8.5,'
                    '"baseline_score":7.0,"confidence":0.8,"rationale":"Cleaner output."}'
                )
            },
        }
    )

    assert verdict.winner == "candidate"
    assert verdict.improved is True
    assert verdict.baseline_score == 7.0


def test_llm_as_judge_uses_worker_backend(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()
    captured: dict[str, str] = {}

    def _fake_run_worker(packet: str, **kwargs: object) -> dict[str, object]:
        captured["packet"] = packet
        captured["backend"] = str(kwargs["backend"])
        return {
            "ok": True,
            "parsed": {
                "result": (
                    '{"winner":"baseline","candidate_score":4.0,'
                    '"baseline_score":6.0,"confidence":0.9,"rationale":"Regression."}'
                )
            },
        }

    monkeypatch.setattr("lab.optimisation.agents_base.run_worker", _fake_run_worker)

    verdict = LLMAsJudge(cfg).judge(
        objective="Prefer the sample with better factual accuracy and clarity.",
        baseline_label="parent",
        baseline_output="Baseline summary text.",
        candidate_label="candidate",
        candidate_output="Candidate summary text.",
        baseline_artifact_path="reports/baseline.md",
        candidate_artifact_path="reports/candidate.md",
    )

    assert verdict.winner == "baseline"
    assert captured["backend"] == "cursor"
    assert "Baseline artifact path" in captured["packet"]
