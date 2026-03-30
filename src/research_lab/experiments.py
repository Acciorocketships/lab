"""Experiment registry and metric comparison helpers."""

from __future__ import annotations

import time
from pathlib import Path

import sqlite3

from research_lab import helpers


def new_experiment_id(conn: sqlite3.Connection, researcher_root: Path) -> str:
    """Allocate exp_000001 style id and insert row."""
    exp_dir = researcher_root / "data" / "runtime" / "experiments"
    helpers.ensure_dir(exp_dir)
    n = len(list(exp_dir.glob("exp_*"))) + 1
    eid = f"exp_{n:06d}"
    conn.execute(
        "INSERT INTO experiments (exp_id, branch, status, metrics_path) VALUES (?, ?, ?, ?)",
        (eid, "", "proposed", None),
    )
    d = exp_dir / eid
    helpers.ensure_dir(d / "artifacts")
    helpers.write_text(d / "proposal.md", f"# Proposal\n\nCreated {time.time()}\n")
    helpers.write_json(d / "config.json", {})
    helpers.write_json(d / "metrics.json", {})
    return eid


def compare_metrics(
    baseline: dict,
    candidate: dict,
    *,
    primary_key: str = "score",
    higher_is_better: bool = True,
) -> bool:
    """Return True if candidate improves on baseline for primary_key."""
    if primary_key not in baseline or primary_key not in candidate:
        return False
    b = float(baseline[primary_key])
    c = float(candidate[primary_key])
    return c > b if higher_is_better else c < b
