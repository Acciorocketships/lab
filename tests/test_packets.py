"""Tests for context packets."""

from pathlib import Path

from lab import memory, packets


def test_write_worker_output_file(tmp_path: Path) -> None:
    """Worker CLI result is stored next to packet.md."""
    memory.ensure_memory_layout(tmp_path)
    fake = {"ok": True, "exit_code": 0, "stdout": "hi", "stderr": "", "parsed": {"x": 1}}
    p = packets.write_worker_output_file(tmp_path, 7, "planner", fake)
    assert p.name == "worker_output.json"
    assert p.parent.name == "planner"
    assert "memory/episodes" in str(p).replace("\\", "/")
    assert "cycle_000007" in str(p)
    text = p.read_text(encoding="utf-8")
    assert '"stdout": "hi"' in text
    assert '"x": 1' in text


def test_build_packet_budget(tmp_path: Path) -> None:
    """Packet respects rough character budget."""
    memory.ensure_memory_layout(tmp_path)
    (memory.state_dir(tmp_path) / "research_idea.md").write_text("x" * 5000, encoding="utf-8")
    text = packets.build_worker_packet(
        worker="planner",
        researcher_root=tmp_path,
        task="Plan next steps",
        extra_sections={"Evidence": "short"},
        max_chars=2000,
    )
    assert len(text) <= 2100


def test_build_worker_packet_trim_keeps_head_and_tail(tmp_path: Path) -> None:
    """When over budget, trimming keeps start and end of the packet (public API)."""
    memory.ensure_memory_layout(tmp_path)
    head = "HEAD_MARKER_TRIM_TEST"
    tail = "TAIL_MARKER_TRIM_TEST"
    (memory.state_dir(tmp_path) / "research_idea.md").write_text(
        head + ("m" * 25_000) + tail, encoding="utf-8"
    )
    text = packets.build_worker_packet(
        worker="planner",
        researcher_root=tmp_path,
        task="Plan",
        max_chars=8000,
    )
    assert head in text
    assert tail in text
    assert "truncated for context budget" in text


def test_build_packet_no_limits_by_default(tmp_path: Path) -> None:
    """Default packet builder does not trim; providers enforce context limits instead."""
    memory.ensure_memory_layout(tmp_path)
    (memory.state_dir(tmp_path) / "research_idea.md").write_text("x" * 30_000, encoding="utf-8")
    text = packets.build_worker_packet(
        worker="planner",
        researcher_root=tmp_path,
        task="Plan next steps",
    )
    assert len(text) > 24_000
    assert "truncated for context budget" not in text


def test_build_worker_packet_extended_not_inlined(tmp_path: Path) -> None:
    """Worker packet includes extended_memory_index in Tier A; extended file bodies stay on disk."""
    memory.ensure_memory_layout(tmp_path)
    (memory.extended_dir(tmp_path) / "log.md").write_text("# BIG\n" + "y" * 8000, encoding="utf-8")
    (memory.state_dir(tmp_path) / "extended_memory_index.md").write_text(
        "Training log: `memory/extended/log.md`\n", encoding="utf-8"
    )
    text = packets.build_worker_packet(
        worker="researcher",
        researcher_root=tmp_path,
        task="Continue",
        max_chars=100_000,
    )
    assert "yyyy" not in text  # body not pasted
    assert "### extended_memory_index.md" in text
    assert "memory/extended/log.md" in text


def test_build_worker_packet_soft_clips_oversized_tier_a_files(tmp_path: Path) -> None:
    """Huge Tier A files are clipped per-file even without a global packet budget."""
    memory.ensure_memory_layout(tmp_path)
    roadmap_head = "ROADMAP_HEAD_MARKER"
    roadmap_tail = "ROADMAP_TAIL_MARKER"
    user_head = "USER_HEAD_MARKER"
    user_tail = "USER_TAIL_MARKER"
    (memory.state_dir(tmp_path) / "roadmap.md").write_text(
        roadmap_head + ("R" * 60_000) + roadmap_tail, encoding="utf-8"
    )
    (memory.state_dir(tmp_path) / "user_instructions.md").write_text(
        user_head + ("U" * 60_000) + user_tail, encoding="utf-8"
    )

    text = packets.build_worker_packet(
        worker="planner",
        researcher_root=tmp_path,
        task="Plan next steps",
    )

    assert roadmap_head in text
    assert roadmap_tail in text
    assert user_head in text
    assert user_tail in text
    assert "oversized Tier A file" in text
    assert len(text) < 80_000
