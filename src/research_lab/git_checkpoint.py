"""Git-based checkpoint system: snapshot project state after each completed cycle.

Checkpoints live on a dedicated ``checkpoints`` branch that is advanced via
plumbing commands (write-tree / commit-tree / update-ref) so the working branch
and index are never disturbed during normal operation.

On revert the working tree is restored to the last checkpoint state.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)

CHECKPOINT_BRANCH = "checkpoints"
_EXCLUDE_PATHSPEC = ":(exclude).airesearcher"


def is_git_repo(project_dir: Path) -> bool:
    return (project_dir / ".git").is_dir()


def ensure_git_repo(project_dir: Path) -> None:
    """Initialize a git repo with an initial commit if one doesn't exist."""
    if is_git_repo(project_dir):
        return
    _log.info("Initializing git repo at %s", project_dir)
    subprocess.run(
        ["git", "init"], cwd=project_dir, check=True, capture_output=True,
    )
    _ensure_airesearcher_excluded(project_dir)
    env = _checkpoint_env()
    subprocess.run(
        ["git", "add", "-A"],
        cwd=project_dir, env=env, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit (created by lab)", "--allow-empty"],
        cwd=project_dir, env=env, check=True, capture_output=True,
    )


def _ensure_airesearcher_excluded(project_dir: Path) -> None:
    """Append ``.airesearcher/`` to ``.git/info/exclude`` so runtime data never
    leaks into checkpoint trees (idempotent)."""
    exclude_path = project_dir / ".git" / "info" / "exclude"
    pattern = ".airesearcher/"
    if exclude_path.is_file():
        content = exclude_path.read_text(encoding="utf-8")
        if pattern in content:
            return
        with open(exclude_path, "a", encoding="utf-8") as f:
            f.write(f"\n{pattern}\n")
    else:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text(f"{pattern}\n", encoding="utf-8")


def _checkpoint_env(tmp_index: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "airesearcher"
    env["GIT_AUTHOR_EMAIL"] = "airesearcher@local"
    env["GIT_COMMITTER_NAME"] = "airesearcher"
    env["GIT_COMMITTER_EMAIL"] = "airesearcher@local"
    if tmp_index is not None:
        env["GIT_INDEX_FILE"] = str(tmp_index)
    return env


# ---------------------------------------------------------------------------
# Checkpoint creation
# ---------------------------------------------------------------------------

def create_checkpoint(project_dir: Path, cycle: int, worker: str) -> str | None:
    """Snapshot the working tree into a commit on the ``checkpoints`` branch.

    Uses a temporary index so the real index is untouched.  Returns the new
    commit SHA, or *None* on failure.
    """
    if not is_git_repo(project_dir):
        _log.warning("Not a git repo — skipping checkpoint: %s", project_dir)
        return None

    _ensure_airesearcher_excluded(project_dir)

    git_dir = project_dir / ".git"
    tmp_index = git_dir / "checkpoint_index_tmp"
    env = _checkpoint_env(tmp_index)

    try:
        subprocess.run(
            ["git", "add", "-A", "--", ".", _EXCLUDE_PATHSPEC],
            cwd=project_dir, env=env, check=True,
            capture_output=True,
        )

        tree_sha = subprocess.run(
            ["git", "write-tree"],
            cwd=project_dir, env=env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

        parent = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{CHECKPOINT_BRANCH}"],
            cwd=project_dir, capture_output=True, text=True,
        )

        msg = f"checkpoint: cycle {cycle} ({worker})"
        commit_cmd = ["git", "commit-tree", tree_sha, "-m", msg]

        if parent.returncode == 0:
            parent_sha = parent.stdout.strip()
            parent_tree = subprocess.run(
                ["git", "rev-parse", f"{parent_sha}^{{tree}}"],
                cwd=project_dir, capture_output=True, text=True,
            )
            if parent_tree.returncode == 0 and parent_tree.stdout.strip() == tree_sha:
                _log.debug("Checkpoint tree unchanged at cycle %d; skipping.", cycle)
                return parent_sha
            commit_cmd.extend(["-p", parent_sha])

        commit_sha = subprocess.run(
            commit_cmd, cwd=project_dir, env=env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

        subprocess.run(
            ["git", "update-ref", f"refs/heads/{CHECKPOINT_BRANCH}", commit_sha],
            cwd=project_dir, check=True, capture_output=True,
        )

        _log.info("Checkpoint: cycle %d (%s) → %s", cycle, worker, commit_sha[:10])
        return commit_sha

    except subprocess.CalledProcessError as exc:
        _log.error("Checkpoint failed: %s\nstderr: %s", exc, getattr(exc, "stderr", ""))
        return None
    finally:
        tmp_index.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def has_checkpoint(project_dir: Path) -> bool:
    if not is_git_repo(project_dir):
        return False
    return subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{CHECKPOINT_BRANCH}"],
        cwd=project_dir, capture_output=True,
    ).returncode == 0


def delete_checkpoint_branch(project_dir: Path) -> bool:
    """Remove the ``checkpoints`` branch ref so stale checkpoints don't survive a reset."""
    if not has_checkpoint(project_dir):
        return False
    result = subprocess.run(
        ["git", "update-ref", "-d", f"refs/heads/{CHECKPOINT_BRANCH}"],
        cwd=project_dir, capture_output=True,
    )
    if result.returncode == 0:
        _log.info("Deleted checkpoints branch in %s", project_dir)
        return True
    _log.warning("Failed to delete checkpoints branch: %s", result.stderr)
    return False


def get_checkpoint_cycle(project_dir: Path) -> int | None:
    """Parse the cycle number from the latest checkpoint commit message."""
    if not has_checkpoint(project_dir):
        return None
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s", CHECKPOINT_BRANCH],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"cycle\s+(\d+)", result.stdout.strip())
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------

def revert_to_checkpoint(project_dir: Path) -> int | None:
    """Restore the working tree to the latest checkpoint.

    Only the index and working tree are modified — ``HEAD`` and the current
    branch stay where they are.

    Returns the checkpoint cycle number, or *None* when there is nothing to
    revert to.
    """
    if not has_checkpoint(project_dir):
        _log.info("No checkpoints branch — nothing to revert.")
        return None

    _ensure_airesearcher_excluded(project_dir)
    cycle = get_checkpoint_cycle(project_dir)

    try:
        subprocess.run(
            ["git", "read-tree", "--reset", CHECKPOINT_BRANCH],
            cwd=project_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "checkout-index", "-a", "-f"],
            cwd=project_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=project_dir, check=True, capture_output=True,
        )

        _log.info("Reverted working tree to checkpoint cycle %s", cycle)
        return cycle

    except subprocess.CalledProcessError as exc:
        _log.error("Revert failed: %s\nstderr: %s", exc, getattr(exc, "stderr", ""))
        return None
