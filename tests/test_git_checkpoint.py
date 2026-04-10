"""Tests for git checkpoint helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_lab import git_checkpoint


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def test_revert_checkpoints_to_parent(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    _git(p, "init")
    (p / "f.txt").write_text("one", encoding="utf-8")
    _git(p, "add", "f.txt")
    _git(p, "commit", "-m", "initial", "--allow-empty")

    git_checkpoint.create_checkpoint(p, 1, "planner")
    (p / "f.txt").write_text("two", encoding="utf-8")
    git_checkpoint.create_checkpoint(p, 2, "researcher")

    assert (p / "f.txt").read_text() == "two"
    cyc = git_checkpoint.revert_checkpoints_to_parent(p)
    assert cyc == 1
    assert (p / "f.txt").read_text() == "one"


def test_restore_checkpoint_chain_matches_db_undo_steps(tmp_path: Path) -> None:
    """Repeated undo uses max_cycle = wmax-1; works when oldest checkpoint is a git root."""
    p = tmp_path / "proj"
    p.mkdir()
    _git(p, "init")
    (p / "f.txt").write_text("a", encoding="utf-8")
    _git(p, "add", "f.txt")
    _git(p, "commit", "-m", "initial", "--allow-empty")

    (p / "f.txt").write_text("one", encoding="utf-8")
    git_checkpoint.create_checkpoint(p, 1, "w")
    (p / "f.txt").write_text("two", encoding="utf-8")
    git_checkpoint.create_checkpoint(p, 2, "w")
    (p / "f.txt").write_text("three", encoding="utf-8")
    git_checkpoint.create_checkpoint(p, 3, "w")

    assert (p / "f.txt").read_text() == "three"
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 2) == 2
    assert (p / "f.txt").read_text() == "two"
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 1) == 1
    assert (p / "f.txt").read_text() == "one"
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 0) is None


def test_restore_checkpoint_at_or_before_max_cycle_zero_no_match(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    _git(p, "init")
    (p / "f.txt").write_text("one", encoding="utf-8")
    _git(p, "add", "f.txt")
    _git(p, "commit", "-m", "initial", "--allow-empty")
    git_checkpoint.create_checkpoint(p, 1, "planner")
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 0) is None


def test_restore_checkpoint_chain_keeps_logical_cycles_when_tree_is_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    _git(p, "init")
    (p / "f.txt").write_text("stable", encoding="utf-8")
    _git(p, "add", "f.txt")
    _git(p, "commit", "-m", "initial", "--allow-empty")

    git_checkpoint.create_checkpoint(p, 1, "planner")
    git_checkpoint.create_checkpoint(p, 2, "researcher")
    git_checkpoint.create_checkpoint(p, 3, "implementer")

    result = subprocess.run(
        ["git", "log", "checkpoints", "--format=%s"],
        cwd=p,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip().splitlines()[:3] == [
        "checkpoint: cycle 3 (implementer)",
        "checkpoint: cycle 2 (researcher)",
        "checkpoint: cycle 1 (planner)",
    ]

    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 2) == 2
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 1) == 1
    assert git_checkpoint.restore_checkpoint_at_or_before_cycle(p, 0) is None
