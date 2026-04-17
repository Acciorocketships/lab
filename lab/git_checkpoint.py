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
_EXCLUDE_PATHSPEC = ":(exclude).lab"


def _git_add_paths(
    project_dir: Path, env: dict[str, str], paths: list[str]
) -> None:
    """Stage *paths* via ``git add -A``.

    Long path lists are piped through ``--pathspec-from-file`` with NUL
    terminators so the argv never exceeds the OS ``ARG_MAX`` limit, which
    previously crashed the scheduler with ``OSError: [Errno 7] Argument list
    too long: 'git'`` on large working trees.
    """
    if not paths:
        subprocess.run(
            ["git", "add", "-A", "--", "."],
            cwd=project_dir, env=env, check=True, capture_output=True,
        )
        return
    stdin_bytes = ("\x00".join(paths) + "\x00").encode("utf-8")
    subprocess.run(
        ["git", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
        cwd=project_dir, env=env, check=True, capture_output=True,
        input=stdin_bytes,
    )


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
    _ensure_lab_excluded(project_dir)
    env = _checkpoint_env()
    # Empty initial commit only: staging the full tree with `git add -A` here
    # made `lab init` minutes-long (or worse) in large/no-.gitignore directories.
    subprocess.run(
        ["git", "commit", "-m", "Initial commit (created by lab)", "--allow-empty"],
        cwd=project_dir, env=env, check=True, capture_output=True,
    )


def _ensure_lab_excluded(project_dir: Path) -> None:
    """Append ``.lab/`` to ``.git/info/exclude`` so runtime data never
    leaks into checkpoint trees (idempotent)."""
    exclude_path = project_dir / ".git" / "info" / "exclude"
    pattern = ".lab/"
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
    env["GIT_AUTHOR_NAME"] = "lab"
    env["GIT_AUTHOR_EMAIL"] = "lab@local"
    env["GIT_COMMITTER_NAME"] = "lab"
    env["GIT_COMMITTER_EMAIL"] = "lab@local"
    if tmp_index is not None:
        env["GIT_INDEX_FILE"] = str(tmp_index)
    return env


def _snapshot_paths(project_dir: Path) -> list[str]:
    """Tracked + untracked non-ignored paths to stage into a snapshot index."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=project_dir, capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    raw = result.stdout.decode("utf-8", errors="ignore")
    return [part for part in raw.split("\x00") if part and part != ".lab"]


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

    _ensure_lab_excluded(project_dir)

    git_dir = project_dir / ".git"
    tmp_index = git_dir / "checkpoint_index_tmp"
    env = _checkpoint_env(tmp_index)
    paths = _snapshot_paths(project_dir)

    try:
        _git_add_paths(project_dir, env, paths)

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

def _restore_working_tree_to_treeish(project_dir: Path, treeish: str) -> bool:
    """Reset index + working tree to match *treeish* (commit or branch name)."""
    try:
        subprocess.run(
            ["git", "read-tree", "--reset", treeish],
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
        return True
    except subprocess.CalledProcessError as exc:
        _log.error("Tree restore failed: %s\nstderr: %s", exc, getattr(exc, "stderr", ""))
        return False


def get_ref_sha(project_dir: Path, ref_name: str) -> str | None:
    """Resolve *ref_name* to a SHA, or None if it doesn't exist."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref_name],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def update_ref(project_dir: Path, ref_name: str, sha: str) -> bool:
    """Point *ref_name* at *sha*."""
    result = subprocess.run(
        ["git", "update-ref", ref_name, sha],
        cwd=project_dir, capture_output=True,
    )
    return result.returncode == 0


def delete_ref(project_dir: Path, ref_name: str) -> bool:
    """Delete *ref_name* if present."""
    result = subprocess.run(
        ["git", "update-ref", "-d", ref_name],
        cwd=project_dir, capture_output=True,
    )
    return result.returncode == 0


def snapshot_ref(
    project_dir: Path,
    ref_name: str,
    message: str,
    *,
    parent: str | None = None,
) -> str | None:
    """Snapshot the current working tree into an arbitrary git ref."""
    if not is_git_repo(project_dir):
        return None

    _ensure_lab_excluded(project_dir)

    git_dir = project_dir / ".git"
    tmp_index = git_dir / "snapshot_index_tmp"
    env = _checkpoint_env(tmp_index)
    paths = _snapshot_paths(project_dir)

    try:
        _git_add_paths(project_dir, env, paths)
        tree_sha = subprocess.run(
            ["git", "write-tree"],
            cwd=project_dir, env=env, check=True, capture_output=True, text=True,
        ).stdout.strip()

        parent_sha = parent if parent else get_ref_sha(project_dir, ref_name)
        commit_cmd = ["git", "commit-tree", tree_sha, "-m", message]
        if parent_sha:
            commit_cmd.extend(["-p", parent_sha])
        commit_sha = subprocess.run(
            commit_cmd,
            cwd=project_dir, env=env, check=True, capture_output=True, text=True,
        ).stdout.strip()
        if not update_ref(project_dir, ref_name, commit_sha):
            return None
        return commit_sha
    except subprocess.CalledProcessError as exc:
        _log.error("Snapshot ref failed: %s\nstderr: %s", exc, getattr(exc, "stderr", ""))
        return None
    finally:
        tmp_index.unlink(missing_ok=True)


def restore_working_tree(project_dir: Path, treeish: str) -> bool:
    """Public wrapper to restore working tree/index to *treeish*."""
    _ensure_lab_excluded(project_dir)
    return _restore_working_tree_to_treeish(project_dir, treeish)


def has_worktree_changes(project_dir: Path) -> bool:
    """True when tracked or untracked files differ from the current tree."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=project_dir, capture_output=True, text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def has_worktree_changes_since(project_dir: Path, treeish: str) -> bool:
    """True when tracked or untracked files differ from *treeish*."""
    tracked = subprocess.run(
        ["git", "diff", "--quiet", treeish, "--"],
        cwd=project_dir, capture_output=True,
    )
    if tracked.returncode == 1:
        return True
    if tracked.returncode not in (0, 1):
        return False
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=project_dir, capture_output=True, text=True,
    )
    return untracked.returncode == 0 and bool(untracked.stdout.strip())


def worktree_matches_checkpoint_tip(project_dir: Path) -> bool:
    """True when the working tree (tracked + untracked) matches tip ``checkpoints``.

    Used to skip ``read-tree`` / ``checkout-index`` / ``clean`` when exiting or
    stopping with no in-flight cycle and no local edits since the last snapshot.
    """
    if not has_checkpoint(project_dir):
        return False
    return not has_worktree_changes_since(
        project_dir, f"refs/heads/{CHECKPOINT_BRANCH}",
    )


def cherry_pick_no_commit(project_dir: Path, commit_sha: str) -> bool:
    """Apply *commit_sha* onto the current working tree without creating a commit."""
    result = subprocess.run(
        ["git", "cherry-pick", "--no-commit", commit_sha],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    _log.warning("git cherry-pick failed: %s", result.stderr.strip())
    return False


def list_unmerged_paths(project_dir: Path) -> list[str]:
    """Return paths with unresolved merge conflicts."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=project_dir, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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

    _ensure_lab_excluded(project_dir)
    cycle = get_checkpoint_cycle(project_dir)

    if not _restore_working_tree_to_treeish(project_dir, CHECKPOINT_BRANCH):
        return None

    _log.info("Reverted working tree to checkpoint cycle %s", cycle)
    return cycle


def restore_pre_checkpoint_state(project_dir: Path) -> bool:
    """Restore the working tree to ``HEAD`` and drop checkpoint history.

    This is used when undoing back to logical cycle 0, meaning "before the
    first completed worker checkpoint".
    """
    if not is_git_repo(project_dir):
        return False

    _ensure_lab_excluded(project_dir)
    if not _restore_working_tree_to_treeish(project_dir, "HEAD"):
        return False

    delete_checkpoint_branch(project_dir)
    _log.info("Restored working tree to HEAD and deleted checkpoints branch")
    return True


def restore_checkpoint_at_or_before_cycle(project_dir: Path, max_cycle: int) -> int | None:
    """Restore the working tree to the newest ``checkpoints`` commit whose message
    cycle is ≤ *max_cycle*, and move the branch ref to that commit.

    Unlike ``checkpoints~1``, this works when the oldest checkpoint is a git root
    (no first parent) and when stepping back by **logical** cycle using the DB.

    Returns the parsed cycle from the chosen commit, or *None* if no matching
    commit exists (e.g. *max_cycle* < 1 and only ``cycle 1`` checkpoints exist).
    """
    if max_cycle < 0 or not has_checkpoint(project_dir):
        return None

    log = subprocess.run(
        ["git", "log", CHECKPOINT_BRANCH, "--format=%H %s"],
        cwd=project_dir, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return None

    best_sha: str | None = None
    best_c = -1
    for line in log.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, subj = parts[0], parts[1]
        m = re.search(r"cycle\s+(\d+)", subj)
        if not m:
            continue
        c = int(m.group(1))
        if c <= max_cycle and c > best_c:
            best_c = c
            best_sha = sha

    if best_sha is None or best_c < 0:
        _log.info("No checkpoint commit with cycle ≤ %s", max_cycle)
        return None

    _ensure_lab_excluded(project_dir)
    if not _restore_working_tree_to_treeish(project_dir, best_sha):
        return None

    try:
        subprocess.run(
            ["git", "update-ref", f"refs/heads/{CHECKPOINT_BRANCH}", best_sha],
            cwd=project_dir, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        _log.error("update-ref checkpoints failed: %s", exc)
        return None

    _log.info("Restored checkpoints to cycle %s (max requested %s)", best_c, max_cycle)
    return best_c


def get_checkpoint_sha_for_cycle(project_dir: Path, cycle: int) -> str | None:
    """Return the commit SHA of the checkpoint for exactly *cycle*, or None."""
    if cycle < 1 or not has_checkpoint(project_dir):
        return None
    log = subprocess.run(
        ["git", "log", CHECKPOINT_BRANCH, "--format=%H %s"],
        cwd=project_dir, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return None
    for line in log.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, subj = parts[0], parts[1]
        m = re.search(r"cycle\s+(\d+)", subj)
        if m and int(m.group(1)) == cycle:
            return sha
    return None


def get_line_diff(
    project_dir: Path,
    from_ref: str,
    to_ref: str | None = None,
    *,
    context_lines: int = 3,
) -> str:
    """Return raw unified diff between *from_ref* and *to_ref* (working tree when None)."""
    if not is_git_repo(project_dir):
        return ""
    cmd = ["git", "diff", f"-U{context_lines}", from_ref]
    if to_ref is not None:
        cmd.append(to_ref)
    try:
        result = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True, timeout=15,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def revert_checkpoints_to_parent(project_dir: Path) -> int | None:
    """Prefer :func:`restore_checkpoint_at_or_before_cycle` with DB max worker.

    Kept for tests and callers that only know the tip message cycle.
    """
    tip = get_checkpoint_cycle(project_dir)
    if tip is None or tip < 1:
        return None
    return restore_checkpoint_at_or_before_cycle(project_dir, tip - 1)
