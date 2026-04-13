"""Tier A file layout."""

from pathlib import Path

from lab import db, memory


def test_default_extended_memory_index_is_minimal_seed(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    text = (memory.state_dir(tmp_path) / "extended_memory_index.md").read_text(encoding="utf-8")
    assert text.strip() == "# Extended Memory Index"
    assert "memory/branch/" not in text
    assert "memory/episodes/" not in text


def test_append_episode_index_entry(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    memory.append_episode_index_entry(
        tmp_path,
        cycle=3,
        worker="researcher",
        task="Find papers",
        reason="Need citations",
        episode_relpath="memory/episodes/cycle_000003/researcher",
    )
    idx = memory.episodes_dir(tmp_path) / "index.md"
    text = idx.read_text(encoding="utf-8")
    assert "researcher" in text
    assert "Find papers" in text
    assert "Need citations" in text
    assert "packet.md" in text
    assert "worker_output.json" in text
    assert "cycle_000003/researcher" in text


def test_format_orchestrator_context_extended_bodies_not_inlined(tmp_path: Path) -> None:
    """Orchestrator context includes the index but not bodies of memory/extended/*.md files."""
    memory.ensure_memory_layout(tmp_path)
    (memory.extended_dir(tmp_path) / "extra.md").write_text("# SECRET\nnot in prompt\n", encoding="utf-8")
    (memory.state_dir(tmp_path) / "extended_memory_index.md").write_text(
        "Pointer: memory/extended/extra.md — details on disk\n", encoding="utf-8"
    )
    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(tmp_path, tier=tier, current_branch="")
    assert "SECRET" not in ctx
    assert "not in prompt" not in ctx
    assert "memory/extended/extra.md" in ctx


def test_format_orchestrator_context_no_limits_by_default(tmp_path: Path) -> None:
    """Default helper behavior keeps full text; no app-level clipping unless requested."""
    memory.ensure_memory_layout(tmp_path)
    long_summary = "S" * 9000
    long_worker = "W" * 13000
    (memory.state_dir(tmp_path) / "roadmap.md").write_text("R" * 5000, encoding="utf-8")
    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path,
        tier=tier,
        current_branch="",
        last_worker_output=long_worker,
        previous_context_summary=long_summary,
    )
    assert "S" * 8500 in ctx
    assert "W" * 12050 in ctx
    assert "R" * 4500 in ctx
    assert "...[truncated]" not in ctx


def test_user_instructions_new_has_pending(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    assert not memory.user_instructions_new_has_pending(tmp_path)
    memory.write_user_instruction_new_section(tmp_path, "Do the thing")
    assert memory.user_instructions_new_has_pending(tmp_path)


def test_extract_immediate_plan_checklist_returns_only_canonical_section() -> None:
    text = (
        "# Immediate plan\n\n"
        "## Overview\n\n"
        "Short summary.\n\n"
        "## Checklist\n\n"
        "- [x] Land parser\n"
        "  - [ ] Wire UI\n"
        "- [ ] Add verification\n\n"
        "## Notes\n\n"
        "Keep this lean.\n"
    )
    got = memory.extract_immediate_plan_checklist(text)
    assert got.startswith("## Checklist")
    assert "Wire UI" in got
    assert "## Notes" not in got


def test_extract_immediate_plan_checklist_allows_annotated_heading() -> None:
    text = (
        "# Immediate plan\n\n"
        "## Checklist (Phase 1.5 - archived)\n\n"
        "- [x] Keep showing archived checklist\n\n"
        "## Notes\n\n"
        "Archived after completion.\n"
    )
    got = memory.extract_immediate_plan_checklist(text)
    assert got.startswith("## Checklist (Phase 1.5 - archived)")
    assert "Keep showing archived checklist" in got
    assert "## Notes" not in got


def test_legacy_project_brief_removed_on_ensure(tmp_path: Path) -> None:
    project_dir = tmp_path.parent / "proj_workspace"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(tmp_path, project_dir=project_dir)
    legacy = memory.state_dir(tmp_path) / memory.LEGACY_PROJECT_BRIEF
    legacy.write_text("# old\n", encoding="utf-8")
    memory.ensure_memory_layout(tmp_path, project_dir=project_dir)
    assert not legacy.is_file()
    assert (memory.state_dir(tmp_path) / memory.SYSTEM_TIER_A_FILE).is_file()


def test_legacy_root_logs_migrated_on_ensure(tmp_path: Path) -> None:
    (tmp_path / "scheduler.log").write_text("scheduler line\n", encoding="utf-8")
    (tmp_path / "agent_2.log").write_text("agent line\n", encoding="utf-8")

    memory.ensure_memory_layout(tmp_path)

    assert not (tmp_path / "scheduler.log").exists()
    assert not (tmp_path / "agent_2.log").exists()
    assert (memory.logs_dir(tmp_path) / "scheduler.log").read_text(encoding="utf-8") == "scheduler line\n"
    assert (memory.logs_dir(tmp_path) / "agent_2.log").read_text(encoding="utf-8") == "agent line\n"


def test_refresh_system_tier_from_db_renders_run_events(tmp_path: Path) -> None:
    project_dir = tmp_path.parent / "proj_workspace"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(tmp_path, project_dir=project_dir)
    pkt_rel = "memory/episodes/cycle_000001/planner/packet.md"
    pkt_path = tmp_path / pkt_rel
    pkt_path.parent.mkdir(parents=True, exist_ok=True)
    long_body = "# Worker: planner\n\n## Objective\n\nDo the thing\n\n" + ("x" * 400)
    pkt_path.write_text(long_body, encoding="utf-8")

    db_path = tmp_path / "runtime.db"
    conn = db.connect_db(db_path)
    try:
        db.append_run_event(
            conn,
            cycle=1,
            kind="orchestrator",
            worker="critic",
            roadmap_step="",
            task="Challenge the latest experiment writeup.",
            summary="critic: need review",
            payload={"worker_kwargs": {"persona": "data_scientist"}, "reason": "x"},
            packet_path=None,
        )
        db.append_run_event(
            conn,
            cycle=1,
            kind="worker",
            worker="planner",
            roadmap_step="",
            task="Plan the next chunk",
            summary="done planning",
            payload=None,
            packet_path=pkt_rel,
        )
        conn.commit()
    finally:
        conn.close()

    memory.refresh_system_tier_from_db(tmp_path, project_dir, db_path, limit=10)
    text = (memory.state_dir(tmp_path) / memory.SYSTEM_TIER_A_FILE).read_text(encoding="utf-8")
    assert "Recent activity" in text
    assert "`orchestrator`" not in text
    assert "`worker`" in text
    assert "Challenge the latest experiment writeup." not in text
    assert "persona='data_scientist'" not in text
    assert "critic: need review" not in text
    assert "done planning" not in text
    assert "objective: Plan the next chunk" in text
    assert "prompt:" in text
    assert "# Worker: planner" in text.replace("\n", " ")
    assert str(project_dir) in text


def test_refresh_system_tier_from_db_respects_subagent_limit(tmp_path: Path) -> None:
    project_dir = tmp_path.parent / "proj_workspace"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(tmp_path, project_dir=project_dir)
    db_path = tmp_path / "runtime.db"
    conn = db.connect_db(db_path)
    try:
        for i in range(1, 6):
            db.append_run_event(
                conn,
                cycle=i,
                kind="worker",
                worker="planner",
                roadmap_step="",
                task=f"task {i}",
                summary="done",
                payload=None,
                packet_path=None,
            )
        conn.commit()
    finally:
        conn.close()

    memory.refresh_system_tier_from_db(tmp_path, project_dir, db_path, limit=3)
    text = (memory.state_dir(tmp_path) / memory.SYSTEM_TIER_A_FILE).read_text(encoding="utf-8")
    assert text.count("objective: task ") == 3
    assert "objective: task 1" not in text
    assert "objective: task 2" not in text
    assert "objective: task 3" in text
    assert "objective: task 4" in text
    assert "objective: task 5" in text
