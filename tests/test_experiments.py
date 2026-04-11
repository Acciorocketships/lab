"""Experiment helpers."""

from pathlib import Path

from lab import db, experiments


def test_compare_metrics() -> None:
    """Comparison obeys higher_is_better."""
    assert experiments.compare_metrics({"score": 1.0}, {"score": 2.0}, primary_key="score") is True
    assert experiments.compare_metrics({"score": 2.0}, {"score": 1.0}, primary_key="score", higher_is_better=False) is True


def test_new_experiment_id(tmp_path: Path) -> None:
    """Creates folder and row."""
    dbp = tmp_path / "t.db"
    conn = db.connect_db(dbp)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    eid = experiments.new_experiment_id(conn, project_dir)
    conn.commit()
    conn.close()
    assert eid.startswith("exp_")
    assert (project_dir / "experiments" / eid / "proposal.md").exists()
