"""Tier A file layout."""

from pathlib import Path

from research_lab import memory


def test_default_extended_memory_index_scopes_to_extended_only(tmp_path: Path) -> None:
    memory.ensure_memory_layout(tmp_path)
    text = (memory.state_dir(tmp_path) / "extended_memory_index.md").read_text(encoding="utf-8")
    assert "## `.airesearcher/memory/extended/`" in text
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
