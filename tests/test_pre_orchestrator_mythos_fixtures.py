"""Pre-orchestrator compaction using Tier A snapshots from the mythosunwritten project.

Fixtures live under ``tests/fixtures/mythosunwritten_tier_a/`` (copied from that repo's
``.lab/state/*.md``). At capture time ``roadmap.md`` was >40k chars so the pre-orchestrator
pass must schedule ``memory_compactor`` before the routing LLM runs.

**Real CLI integration** (optional): set ``LAB_RUN_REAL_MEMORY_COMPACTOR=1`` and ensure
``cursor`` or ``claude`` is on ``PATH``. Use ``LAB_REAL_WORKER_BACKEND=cursor`` (default) or
``claude``. For Cursor, set ``LAB_REAL_CURSOR_MODEL`` if needed. Set ``LAB_CURSOR_TIMEOUT_SEC`` /
``LAB_CLAUDE_TIMEOUT_SEC`` to cap subprocess duration (defaults to 900s in the test if neither
is set when you opt in).

**Artifacts:** successful real runs write ``tests/artifacts/real_memory_compactor/<UTC>/`` (see
``tests/REAL_MEMORY_COMPACTOR_ARTIFACTS.md``; directory is gitignored).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab import db, memory
from lab.config import RunConfig
from lab.orchestrator import OrchestratorDecision
from lab.state import ResearchState
from lab.agents import memory_compactor as memory_compactor_mod
from lab.tools import claude_code, cursor_cli
from lab.workflows import research_graph

FIXTURE_TIER_A_DIR = Path(__file__).parent / "fixtures" / "mythosunwritten_tier_a"
_ARTIFACTS_ROOT = Path(__file__).parent / "artifacts" / "real_memory_compactor"

_RUN_REAL_ENV = "LAB_RUN_REAL_MEMORY_COMPACTOR"

# Substrings that should survive a good compaction of the mythos fixture (high-signal / recent).
_RETENTION_MARKERS = (
    "Phase 113",
    "deny_trade",
    "## Checklist",
    "Pyglet",
    "Sproutlands",
    "google/gemma-4-26b-a4b-it",
    "## New",
    "## In progress",
    "## Completed",
)


def _write_retention_checks(out: Path, after_dir: Path) -> None:
    combined = ""
    for p in sorted(after_dir.glob("*.md")):
        combined += p.read_text(encoding="utf-8", errors="replace")
    lines = ["# Substring checks (tier_a_after vs markers)\n"]
    for marker in _RETENTION_MARKERS:
        ok = marker in combined
        lines.append(f"- {'OK' if ok else 'MISSING'}: `{marker}`\n")
    (out / "retention_checks.txt").write_text("".join(lines), encoding="utf-8")


def save_real_memory_compactor_artifacts(
    *,
    tmp_path: Path,
    result: dict,
    sizes_before: dict[str, int],
    sizes_after: dict[str, int],
) -> Path:
    """Persist compactor inputs/outputs under ``tests/artifacts/real_memory_compactor/<UTC>/``."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = _ARTIFACTS_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    before_dir = out / "tier_a_before_fixture"
    before_dir.mkdir(parents=True, exist_ok=True)
    for src in FIXTURE_TIER_A_DIR.glob("*.md"):
        shutil.copy(src, before_dir / src.name)

    after_dir = out / "tier_a_after"
    after_dir.mkdir(parents=True, exist_ok=True)
    sd = memory.state_dir(tmp_path)
    for p in sd.glob("*.md"):
        shutil.copy(p, after_dir / p.name)

    (out / "worker_result.json").write_text(
        json.dumps(result, indent=2, default=str, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / "tier_a_sizes.json").write_text(
        json.dumps({"before": sizes_before, "after": sizes_after}, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "stdout.txt").write_text(str(result.get("stdout") or ""), encoding="utf-8")
    (out / "stderr.txt").write_text(str(result.get("stderr") or ""), encoding="utf-8")

    ep = tmp_path / "memory" / "episodes" / "cycle_000001" / "memory_compactor"
    wo = ep / "worker_output.json"
    if wo.is_file():
        shutil.copy(wo, out / "worker_output.json")
    pkt = ep / "packet.md"
    if pkt.is_file():
        shutil.copy(pkt, out / "compactor_packet.md")

    (out / "memory_compactor_system_prompt.txt").write_text(
        memory_compactor_mod.SYSTEM_PROMPT.strip() + "\n",
        encoding="utf-8",
    )
    _write_retention_checks(out, after_dir)
    (out / "RUN_PATH.txt").write_text(str(out.resolve()) + "\n", encoding="utf-8")
    return out


def _worker_cli_ready(backend: str) -> bool:
    if backend == "claude":
        return claude_code.available()
    return cursor_cli.available()


@pytest.mark.real_memory_compactor
def test_real_memory_compactor_shrinks_mythos_tier_a(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoke the real memory compactor worker (Cursor or Claude CLI) on mythos Tier A fixtures.

    Skips unless ``LAB_RUN_REAL_MEMORY_COMPACTOR=1`` and the chosen backend CLI is available.
    """
    if os.environ.get(_RUN_REAL_ENV, "").strip() != "1":
        pytest.skip(f"Set {_RUN_REAL_ENV}=1 to run this integration test (real worker CLI)")

    backend = os.environ.get("LAB_REAL_WORKER_BACKEND", "cursor").strip().lower()
    if backend not in ("claude", "cursor"):
        pytest.fail("LAB_REAL_WORKER_BACKEND must be 'claude' or 'cursor'")

    if not _worker_cli_ready(backend):
        pytest.skip(f"{backend} CLI not available on PATH")

    if backend == "cursor" and not os.environ.get("LAB_CURSOR_TIMEOUT_SEC"):
        monkeypatch.setenv("LAB_CURSOR_TIMEOUT_SEC", "900")
    if backend == "claude" and not os.environ.get("LAB_CLAUDE_TIMEOUT_SEC"):
        monkeypatch.setenv("LAB_CLAUDE_TIMEOUT_SEC", "900")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    cursor_model = os.environ.get("LAB_REAL_CURSOR_MODEL", "composer-2").strip() or "composer-2"

    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=project_dir,
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend=backend,
        cursor_agent_model=cursor_model,
    )
    memory.ensure_memory_layout(tmp_path)
    _install_mythos_tier_a(tmp_path)

    sizes_before = memory.tier_a_file_sizes(tmp_path)
    total_before = sum(sizes_before.values())
    assert sizes_before["roadmap.md"] > research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS

    db_path = tmp_path / "runtime.db"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    state: ResearchState = {
        "current_goal": "compact Tier A",
        "current_branch": "",
        "current_worker": "memory_compactor",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    result = research_graph._run_internal_memory_compactor(
        cyc=1,
        state=state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=project_dir,
        db_path=db_path,
        reason="integration test: mythosunwritten Tier A fixture snapshot",
    )

    assert result.get("ok") is True, (
        f"memory_compactor worker failed: {result!r}"
    )

    sizes_after = memory.tier_a_file_sizes(tmp_path)
    total_after = sum(sizes_after.values())
    assert total_after < total_before, (
        "expected the real compactor to reduce total Tier A size tracked by tier_a_file_sizes; "
        f"before={total_before} after={total_after}. "
        f"stdout={result.get('stdout', '')!r} stderr={result.get('stderr', '')!r}"
    )

    artifact_dir = save_real_memory_compactor_artifacts(
        tmp_path=tmp_path,
        result=result,
        sizes_before=sizes_before,
        sizes_after=sizes_after,
    )
    # Surface path when running with ``pytest -s`` (artifacts dir is gitignored).
    print(f"\n[real_memory_compactor] artifacts -> {artifact_dir}\n")


def test_save_real_memory_compactor_artifacts_writes_expected_files(tmp_path: Path) -> None:
    """``save_real_memory_compactor_artifacts`` writes the expected tree (no real CLI)."""
    memory.ensure_memory_layout(tmp_path)
    (tmp_path / "project").mkdir()
    _install_mythos_tier_a(tmp_path)
    before = memory.tier_a_file_sizes(tmp_path)
    (memory.state_dir(tmp_path) / "skills_index.md").write_text("# skills\nminimal\n", encoding="utf-8")
    after = memory.tier_a_file_sizes(tmp_path)
    result: dict = {"ok": True, "stdout": "demo-out", "stderr": "", "parsed": {"result": "stub run"}}
    out = save_real_memory_compactor_artifacts(
        tmp_path=tmp_path,
        result=result,
        sizes_before=before,
        sizes_after=after,
    )
    assert (out / "tier_a_before_fixture" / "roadmap.md").is_file()
    assert (out / "tier_a_after" / "skills_index.md").read_text(encoding="utf-8") == "# skills\nminimal\n"
    assert "demo-out" in (out / "worker_result.json").read_text(encoding="utf-8")
    assert (out / "retention_checks.txt").is_file()


def _install_mythos_tier_a(researcher_root: Path) -> None:
    assert FIXTURE_TIER_A_DIR.is_dir(), f"Missing fixture dir: {FIXTURE_TIER_A_DIR}"
    sd = memory.state_dir(researcher_root)
    for src in FIXTURE_TIER_A_DIR.glob("*.md"):
        shutil.copy(src, sd / src.name)


def test_mythos_fixtures_roadmap_exceeds_pre_orchestrator_default() -> None:
    """Sanity: bundled mythos snapshot still has at least one Tier A file over 40k."""
    roadmap = (FIXTURE_TIER_A_DIR / "roadmap.md").read_text(encoding="utf-8")
    assert len(roadmap) > research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS


def test_pre_orchestrator_invokes_memory_compactor_with_mythos_tier_a(
    tmp_path: Path, monkeypatch,
) -> None:
    cfg = RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "p",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )
    memory.ensure_memory_layout(tmp_path)
    cfg.project_dir.mkdir()
    _install_mythos_tier_a(tmp_path)

    sizes_before = memory.tier_a_file_sizes(tmp_path)
    assert sizes_before["roadmap.md"] > research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS

    db_path = tmp_path / "db.sqlite"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    conn.commit()
    conn.close()

    def _fake_decide(_ctx: str, **_kw: object) -> OrchestratorDecision:
        return OrchestratorDecision(
            worker="planner",
            task="noop",
            reason="fixture test",
            roadmap_step="",
            context_summary="",
            worker_kwargs={},
        )

    packets: list[str] = []

    def _fake_run_worker(pkt: str, **_kw: object) -> dict[str, object]:
        packets.append(pkt)
        if "# Worker: memory_compactor" not in pkt:
            raise AssertionError("expected only memory_compactor in this test")
        # Simulate successful compaction so Tier A drops below the default line.
        body = (memory.state_dir(tmp_path) / "roadmap.md").read_text(encoding="utf-8")
        (memory.state_dir(tmp_path) / "roadmap.md").write_text(
            body[:8000].rstrip() + "\n\n# compacted for test harness\n",
            encoding="utf-8",
        )
        return {"ok": True, "parsed": {"result": "compacted roadmap for test"}}

    monkeypatch.setattr(research_graph.orchestrator, "decide_orchestrator", _fake_decide)
    monkeypatch.setattr(research_graph.agents_base, "run_worker", _fake_run_worker)

    state: ResearchState = {
        "current_goal": "g",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": 0,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }

    research_graph.choose_action(
        state,
        cfg=cfg,
        researcher_root=tmp_path,
        project_dir=cfg.project_dir,
        db_path=db_path,
    )

    assert len(packets) == 1
    assert "# Worker: memory_compactor" in packets[0]
    assert len((memory.state_dir(tmp_path) / "roadmap.md").read_text(encoding="utf-8")) <= (
        research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS + 500
    )

    st = memory.read_pre_orchestrator_compact_state(tmp_path)
    assert st is not None
    ft = st.get("file_thresholds")
    assert isinstance(ft, dict)
    assert "roadmap.md" in ft
    assert ft["roadmap.md"] == min(
        research_graph.PRE_ORCHESTRATOR_COMPACT_THRESHOLD_CHARS,
        len((memory.state_dir(tmp_path) / "roadmap.md").read_text(encoding="utf-8")),
    )
