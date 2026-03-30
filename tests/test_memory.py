"""Tier A file layout and migration."""

from pathlib import Path

from research_lab import memory


def test_append_episode_index_entry(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    memory.append_episode_index_entry(
        tmp_path,
        cycle=3,
        worker="researcher",
        task="Find papers",
        reason="Need citations",
        episode_relpath="data/runtime/memory/episodes/cycle_000003/researcher",
    )
    idx = memory.episodes_dir(tmp_path) / "index.md"
    text = idx.read_text(encoding="utf-8")
    assert "researcher" in text
    assert "Find papers" in text
    assert "Need citations" in text
    assert "packet.md" in text
    assert "worker_output.json" in text
    assert "cycle_000003/researcher" in text


def test_migrate_legacy_tier_a_filenames(tmp_path: Path) -> None:
    """backlog.md / current_goal.md rename to roadmap.md / immediate_plan.md."""
    sd = memory.state_dir(tmp_path)
    sd.mkdir(parents=True)
    (sd / "backlog.md").write_text("# legacy backlog\n", encoding="utf-8")
    (sd / "current_goal.md").write_text("# legacy goal\n", encoding="utf-8")
    memory.ensure_memory_layout(tmp_path)
    assert not (sd / "backlog.md").exists()
    assert not (sd / "current_goal.md").exists()
    assert (sd / "roadmap.md").read_text(encoding="utf-8") == "# legacy backlog\n"
    assert (sd / "immediate_plan.md").read_text(encoding="utf-8") == "# legacy goal\n"


def test_migrate_acceptance_criteria_into_research_idea(tmp_path: Path) -> None:
    """Legacy acceptance_criteria.md merges into research_idea.md and is removed."""
    sd = memory.state_dir(tmp_path)
    sd.mkdir(parents=True)
    (sd / "research_idea.md").write_text("# Research brief\n\nGoal text.\n", encoding="utf-8")
    (sd / "acceptance_criteria.md").write_text("# Acceptance criteria\n\nMust win.\n", encoding="utf-8")
    memory.ensure_memory_layout(tmp_path)
    assert not (sd / "acceptance_criteria.md").exists()
    merged = (sd / "research_idea.md").read_text(encoding="utf-8")
    assert "Goal text" in merged
    assert "Must win" in merged
    assert "## Success criteria" in merged


def test_discover_extended_refs(tmp_path: Path) -> None:
    """Tier A text can reference memory/extended/*.md paths."""
    names = memory.discover_extended_filenames_from_text(
        "See memory/extended/run_log.md and data/runtime/memory/extended/other_notes.md"
    )
    assert names == ["run_log.md", "other_notes.md"]


def test_load_referenced_extended_bundle(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    p = memory.extended_dir(tmp_path) / "extra.md"
    p.write_text("# Extra\n\nbody\n", encoding="utf-8")
    tier = memory.load_tier_a_bundle(tmp_path)
    tier["status.md"] = "Link: memory/extended/extra.md\n"
    got = memory.load_referenced_extended_bundle(tmp_path, tier)
    assert got["extra.md"].strip().startswith("# Extra")


def test_format_orchestrator_context_extended_not_inlined(tmp_path: Path) -> None:
    """Orchestrator prompt lists extended paths but does not embed file bodies."""
    memory.ensure_memory_layout(tmp_path)
    (memory.extended_dir(tmp_path) / "extra.md").write_text("# SECRET\nnot in prompt\n", encoding="utf-8")
    tier = memory.load_tier_a_bundle(tmp_path)
    tier["status.md"] = "Pointer: memory/extended/extra.md\n"
    ctx = memory.format_orchestrator_context(tmp_path, tier=tier, current_branch="")
    assert "SECRET" not in ctx
    assert "not in prompt" not in ctx
    assert "referenced_extended_files" in ctx
    assert "extra.md" in ctx


def test_format_worker_packet_extended_section_lists_paths(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    (memory.extended_dir(tmp_path) / "note.md").write_text("# Hidden\n", encoding="utf-8")
    sd = memory.state_dir(tmp_path)
    (sd / "status.md").write_text("See memory/extended/note.md\n", encoding="utf-8")
    text = memory.format_extended_refs_for_worker_packet(tmp_path, memory.load_tier_a_bundle(tmp_path))
    assert "Hidden" not in text
    assert str((memory.extended_dir(tmp_path) / "note.md").resolve()) in text


def test_user_instructions_new_has_pending(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    assert not memory.user_instructions_new_has_pending(tmp_path)
    memory.write_user_instruction_new_section(tmp_path, "Do the thing")
    assert memory.user_instructions_new_has_pending(tmp_path)


def test_migrate_hot_to_extended(tmp_path: Path) -> None:
    base = tmp_path / "data" / "runtime" / "memory"
    hot = base / "hot"
    hot.mkdir(parents=True)
    (hot / "old.md").write_text("moved\n", encoding="utf-8")
    memory.ensure_memory_layout(tmp_path)
    ext = base / "extended" / "old.md"
    assert ext.exists()
    assert ext.read_text(encoding="utf-8") == "moved\n"
