"""Integration tests for memory write/read fidelity across simulated cycles."""

from __future__ import annotations

import json
from pathlib import Path

from research_lab import helpers, memory, memory_extra, packets


LOG_DIR = Path(__file__).parent / "logs"


def _log(name: str, data: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    p = LOG_DIR / f"{name}.json"
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Tier A round-trip
# ---------------------------------------------------------------------------


def test_tier_a_round_trip_all_files(tmp_path: Path) -> None:
    """Write content to every Tier A file, reload via load_tier_a_bundle, verify nothing lost."""
    memory.ensure_memory_layout(tmp_path)
    written: dict[str, str] = {}
    for i, name in enumerate(memory.TIER_A_FILES):
        body = f"# Content for {name}\n\nPayload line {i}: {'x' * 200}\n"
        helpers.write_text(memory.state_dir(tmp_path) / name, body)
        written[name] = body

    bundle = memory.load_tier_a_bundle(tmp_path)
    sizes: dict[str, dict[str, int]] = {}
    for name in memory.TIER_A_FILES:
        assert name in bundle, f"Missing Tier A key: {name}"
        assert bundle[name] == written[name], f"Content mismatch for {name}"
        sizes[name] = {"written": len(written[name]), "read": len(bundle[name])}

    _log("tier_a_round_trip", {"files": len(memory.TIER_A_FILES), "sizes": sizes})


# ---------------------------------------------------------------------------
# 2. Context summary overwrite cycle
# ---------------------------------------------------------------------------


def test_context_summary_overwrite_cycle(tmp_path: Path) -> None:
    """10 sequential overwrites; each read returns only the latest write."""
    memory.ensure_memory_layout(tmp_path)
    sizes: list[dict[str, int]] = []
    for cycle in range(10):
        body = f"## Cycle {cycle} summary\n\nFact_{cycle:03d} discovered.\n" + ("z" * (500 * (cycle + 1)))
        memory.write_context_summary(tmp_path, body)
        got = memory.read_context_summary(tmp_path)
        assert got == body, f"Cycle {cycle}: read-back mismatch"
        assert f"Fact_{cycle:03d}" in got
        if cycle > 0:
            assert f"Fact_{cycle - 1:03d}" not in got, "Previous cycle content should be fully replaced"
        sizes.append({"cycle": cycle, "written": len(body), "read": len(got)})

    _log("context_summary_overwrite", {"cycles": 10, "sizes": sizes})


# ---------------------------------------------------------------------------
# 3. Episode accumulation
# ---------------------------------------------------------------------------


def test_episode_accumulation(tmp_path: Path) -> None:
    """20 append_episode_index_entry calls; index.md preserves all entries in order."""
    memory.ensure_memory_layout(tmp_path)
    workers = ["planner", "researcher", "executer", "implementer", "debugger"]

    for cycle in range(1, 21):
        w = workers[cycle % len(workers)]
        memory.append_episode_index_entry(
            tmp_path,
            cycle=cycle,
            worker=w,
            task=f"Task_{cycle:03d}",
            reason=f"Reason_{cycle:03d}",
            episode_relpath=memory.episodes_cycle_relpath(cycle=cycle, worker=w),
        )

    idx_path = memory.episodes_dir(tmp_path) / "index.md"
    text = idx_path.read_text(encoding="utf-8")
    for cycle in range(1, 21):
        w = workers[cycle % len(workers)]
        assert f"Cycle {cycle}" in text, f"Missing cycle {cycle}"
        assert f"Task_{cycle:03d}" in text
        assert f"Reason_{cycle:03d}" in text
        assert f"cycle_{cycle:06d}/{w}/packet.md" in text
        assert f"cycle_{cycle:06d}/{w}/worker_output.json" in text

    _log("episode_accumulation", {"entries": 20, "index_chars": len(text)})


# ---------------------------------------------------------------------------
# 4. Extended memory isolation
# ---------------------------------------------------------------------------


def test_extended_memory_isolation(tmp_path: Path) -> None:
    """Bodies in memory/extended/ must never appear in orchestrator context or worker packets."""
    memory.ensure_memory_layout(tmp_path)
    secret = "EXTENDED_SECRET_PAYLOAD_" + "A" * 5000
    (memory.extended_dir(tmp_path) / "big_notes.md").write_text(
        f"# Big notes\n{secret}\n", encoding="utf-8"
    )
    (memory.state_dir(tmp_path) / "extended_memory_index.md").write_text(
        "- `memory/extended/big_notes.md` — big notes file\n", encoding="utf-8"
    )

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(tmp_path, tier=tier, current_branch="")
    pkt = packets.build_worker_packet(
        worker="researcher", researcher_root=tmp_path, task="Continue", max_chars=100_000
    )

    assert secret not in ctx, "Extended body leaked into orchestrator context"
    assert secret not in pkt, "Extended body leaked into worker packet"
    assert "big_notes.md" in ctx, "Index reference should be present in orchestrator context"
    assert "big_notes.md" in pkt, "Index reference should be present in packet"

    _log("extended_memory_isolation", {
        "secret_len": len(secret),
        "ctx_len": len(ctx),
        "pkt_len": len(pkt),
        "secret_in_ctx": secret in ctx,
        "secret_in_pkt": secret in pkt,
    })


# ---------------------------------------------------------------------------
# 5. Branch memory write / read
# ---------------------------------------------------------------------------


def test_branch_memory_write_read(tmp_path: Path) -> None:
    """Branches with slashes and hyphens survive write/read via memory_extra."""
    memory.ensure_memory_layout(tmp_path)
    branches = {
        "feature/new-model": "Notes about the new model branch.",
        "bug/fix-nan-loss": "Debugging NaN in training loop.",
        "main": "Stable baseline results.",
    }
    for branch, content in branches.items():
        p = memory_extra.branch_memory_path(tmp_path, branch)
        helpers.write_text(p, content)

    results: dict[str, dict] = {}
    for branch, expected in branches.items():
        got = memory_extra.read_branch_memory(tmp_path, branch)
        assert got == expected, f"Branch {branch!r}: content mismatch"
        p = memory_extra.branch_memory_path(tmp_path, branch)
        assert "/" not in p.name, f"Slash should be escaped in filename: {p.name}"
        results[branch] = {"filename": p.name, "content_len": len(got)}

    assert memory_extra.read_branch_memory(tmp_path, "nonexistent/branch") == ""
    _log("branch_memory", results)


# ---------------------------------------------------------------------------
# 6. Lesson append ordering
# ---------------------------------------------------------------------------


def test_lesson_append_ordering(tmp_path: Path) -> None:
    """5 lessons appended in order; all present and ordered in lessons.md."""
    memory.ensure_memory_layout(tmp_path)
    lessons = [f"Lesson_{i}: learning rate {0.001 * (i + 1):.4f} works best" for i in range(5)]
    for lesson in lessons:
        memory.append_lesson(tmp_path, lesson)

    text = helpers.read_text(memory.state_dir(tmp_path) / "lessons.md")
    positions = []
    for lesson in lessons:
        pos = text.find(lesson)
        assert pos >= 0, f"Missing lesson: {lesson}"
        positions.append(pos)

    assert positions == sorted(positions), "Lessons are not in append order"
    _log("lesson_ordering", {"count": len(lessons), "file_chars": len(text)})


# ---------------------------------------------------------------------------
# 7. User instruction lifecycle
# ---------------------------------------------------------------------------


def test_user_instruction_lifecycle(tmp_path: Path) -> None:
    """Write instruction -> pending=True -> clear -> pending=False."""
    memory.ensure_memory_layout(tmp_path)
    assert not memory.user_instructions_new_has_pending(tmp_path)

    memory.write_user_instruction_new_section(tmp_path, "Run ablation study on dropout rates")
    assert memory.user_instructions_new_has_pending(tmp_path)

    memory.write_user_instruction_new_section(tmp_path, "Also compare with baseline")
    text = helpers.read_text(memory.state_dir(tmp_path) / "user_instructions.md")
    assert "Run ablation study on dropout rates" in text
    assert "Also compare with baseline" in text

    # Simulate clearing: rewrite the file without bullets under ## New
    cleared = (
        "# User instructions\n\n"
        "## New\n\n"
        "## In progress\n\n"
        "- Run ablation study on dropout rates\n"
        "- Also compare with baseline\n\n"
        "## Completed\n\n"
    )
    helpers.write_text(memory.state_dir(tmp_path) / "user_instructions.md", cleared)
    assert not memory.user_instructions_new_has_pending(tmp_path)

    _log("user_instruction_lifecycle", {
        "instructions_written": 2,
        "pending_after_write": True,
        "pending_after_clear": False,
        "file_chars": len(cleared),
    })


# ---------------------------------------------------------------------------
# 8. Reset preserves research_idea and preferences
# ---------------------------------------------------------------------------


def test_reset_preserves_research_idea(tmp_path: Path) -> None:
    """reset_runtime_artifacts wipes everything except research_idea.md and preferences.md."""
    memory.ensure_memory_layout(tmp_path)

    idea = "# Research idea\n\nTrain a transformer on protein folding data.\n"
    prefs = "# Preferences\n\nUse PyTorch, cite in APA format.\n"
    helpers.write_text(memory.state_dir(tmp_path) / "research_idea.md", idea)
    helpers.write_text(memory.state_dir(tmp_path) / "preferences.md", prefs)

    helpers.write_text(memory.state_dir(tmp_path) / "roadmap.md", "# Roadmap\n\n- Step 1\n- Step 2\n")
    memory.write_context_summary(tmp_path, "Rolling summary from cycle 5")
    (memory.extended_dir(tmp_path) / "notes.md").write_text("Some extended notes", encoding="utf-8")
    memory.append_episode_index_entry(
        tmp_path, cycle=1, worker="planner", task="Plan", reason="Init",
        episode_relpath=memory.episodes_cycle_relpath(cycle=1, worker="planner"),
    )
    ep_dir = memory.episode_cycle_dir(tmp_path, 1, "planner")
    helpers.ensure_dir(ep_dir)
    (ep_dir / "packet.md").write_text("fake packet", encoding="utf-8")

    memory.reset_runtime_artifacts(
        tmp_path, preserved_research_idea_md=idea, preserved_preferences_md=prefs,
    )

    bundle = memory.load_tier_a_bundle(tmp_path)
    assert bundle["research_idea.md"].strip() == idea.strip()
    assert bundle["preferences.md"].strip() == prefs.strip()
    assert "Rolling summary from cycle 5" not in bundle["context_summary.md"]
    assert "Step 1" not in bundle["roadmap.md"]
    assert not list(memory.extended_dir(tmp_path).glob("*.md"))
    assert not (memory.episodes_dir(tmp_path) / "index.md").exists()

    _log("reset_preservation", {
        "idea_preserved": bundle["research_idea.md"].strip() == idea.strip(),
        "prefs_preserved": bundle["preferences.md"].strip() == prefs.strip(),
        "roadmap_reset": "Step 1" not in bundle["roadmap.md"],
        "context_summary_reset": "Rolling summary" not in bundle["context_summary.md"],
        "extended_cleared": len(list(memory.extended_dir(tmp_path).glob("*.md"))) == 0,
    })
