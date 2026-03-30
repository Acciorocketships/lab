"""Branch-local memory: one markdown file per active branch."""

from __future__ import annotations

from pathlib import Path

from research_lab import helpers


def branch_memory_path(researcher_root: Path, branch: str) -> Path:
    """Per-branch memory file (slashes in branch name → ``__``)."""
    safe = branch.replace("/", "__")
    return researcher_root / "data" / "runtime" / "memory" / "branch" / f"{safe}.md"


def default_branch_memory_body(branch: str) -> str:
    """Template for a new branch memory file."""
    return (
        f"# Branch: `{branch}`\n\n"
        "## Diverged from\n\n"
        "- Base commit: *(git SHA or tag — `git merge-base main HEAD` / describe)*\n"
        "- Notes: \n\n"
        "## Purpose\n\n"
        "What this branch explores or validates:\n\n"
        "## Status and results\n\n"
        "- Status: \n"
        "- Results so far: \n\n"
        "<!-- Keep this file in sync with git. Delete when merged to main or when the branch is removed. "
        "If the approach fails, delete this file and record learnings in state/lessons.md. -->\n"
    )


def read_branch_memory(researcher_root: Path, branch: str) -> str:
    """Return branch markdown or empty string if missing."""
    p = branch_memory_path(researcher_root, branch)
    return helpers.read_text(p, default="")
