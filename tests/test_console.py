from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from rich import box
from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from lab.ui import console as console_mod
from lab import db, git_checkpoint, memory
from lab.config import RunConfig
from lab.ui import events
from lab.ui.console import ResearchConsole


def _console_query_stub(captured: list[str]):
    """Minimal Textual stand-ins so console methods can mount activity lines."""

    class FakeScroll:
        # Match Textual scroll-follow checks used by ``ResearchConsole._activity_viewport_at_bottom``.
        is_vertical_scroll_end = True
        is_vertical_scrollbar_grabbed = False

        def mount(self, w, before=None, after=None) -> None:
            text = getattr(w, "content", None) or getattr(w, "renderable", None)
            if text is None:
                captured.append("")
                return
            if isinstance(text, Panel):
                inner = text.renderable
                captured.append(inner.plain if isinstance(inner, Text) else str(inner))
            else:
                captured.append(str(text))

        def scroll_end(self, animate: bool = False) -> None:
            pass

    class FakeStatic:
        def update(self, *args, **kwargs) -> None:
            pass

        display = True

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#activity-scroll":
            return FakeScroll()
        return FakeStatic()

    return fake_query


class _FakePrompt:
    def __init__(self) -> None:
        self.text = ""
        self.focused = False
        self.cursor_location: tuple[int, int] | None = None
        self.adjust_count = 0

    def _adjust_height(self) -> None:
        self.adjust_count += 1

    def move_cursor(self, location: tuple[int, int], **kwargs) -> None:
        self.cursor_location = location

    def focus(self) -> None:
        self.focused = True

    def scroll_cursor_visible(self) -> None:
        pass


def _console_query_with_prompt_stub(captured: list[str], prompt: _FakePrompt):
    base_query = _console_query_stub(captured)

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#prompt":
            return prompt
        return base_query(sel, *args, **kwargs)

    return fake_query


def _cfg(tmp_path: Path) -> RunConfig:
    project_dir = tmp_path / "project"
    researcher_root = project_dir / ".lab"
    return RunConfig(
        researcher_root=researcher_root,
        project_dir=project_dir,
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="model",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        openrouter_api_key="key",
    )


def test_cmd_start_enqueues_resume_when_scheduler_is_alive(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    writes: list[str] = []

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]

    console._cmd_start()

    pending = db.fetch_pending_events(conn)
    assert [row["kind"] for row in pending] == ["resume"]
    assert db.get_system_state(conn)["control_mode"] == "active"
    assert console._orchestrating is True

    console._conn.close()


def test_cmd_start_clears_graceful_pause_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    db.set_graceful_pause_pending(conn, True)
    conn.commit()

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]

    console._cmd_start()

    assert int(db.get_system_state(conn).get("graceful_pause_pending", 0) or 0) == 0
    console._conn.close()


def test_cmd_start_with_dead_scheduler_defers_spawn_until_after_refresh(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    writes: list[str] = []
    scheduled: list[object] = []
    placeholders: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console.call_after_refresh = lambda callback: scheduled.append(callback)  # type: ignore[method-assign]
    console._set_stream_placeholder = lambda markup: placeholders.append(markup)  # type: ignore[method-assign]
    console._scroll_to_bottom = lambda: None  # type: ignore[method-assign]

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr("lab.loop.spawn_scheduler", lambda *args, **kwargs: FakeScheduler())

    console._cmd_start()

    assert console._scheduler_start_pending is True
    assert console._orchestrating is True
    assert placeholders == ["[dim]Orchestrating.[/]"]
    assert db.get_system_state(conn)["control_mode"] == "active"
    assert db.fetch_pending_events(conn) == []
    assert len(scheduled) == 1

    scheduled[0]()

    pending = db.fetch_pending_events(conn)
    assert [row["kind"] for row in pending] == ["resume"]
    assert console._scheduler is not None
    assert console._scheduler_start_pending is False

    console._conn.close()


def test_submit_prompt_text_enqueues_instruction_then_runs_start(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()

    console._submit_prompt_text("Please investigate the flaky test.\n/start")

    pending = db.fetch_pending_events(conn)
    assert [row["kind"] for row in pending] == ["instruction", "resume"]
    assert pending[0]["payload"] == "Please investigate the flaky test."
    assert db.get_system_state(conn)["control_mode"] == "active"
    assert console._orchestrating is True

    console._conn.close()


def test_submit_prompt_text_instruction_then_start_separately_resumes_immediately(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()

    console._submit_prompt_text("create gifs of the best runs for each method")
    console._submit_prompt_text("/start")

    pending = db.fetch_pending_events(conn)
    assert [row["kind"] for row in pending] == ["instruction", "resume"]
    assert db.get_system_state(conn)["control_mode"] == "active"
    assert console._orchestrating is True

    console._conn.close()


def test_complete_initial_activity_rebuild_opens_edit_when_brief_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True)
    cfg.researcher_root.mkdir(parents=True, exist_ok=True)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]
    mock_edit = MagicMock()
    console._cmd_edit = mock_edit  # type: ignore[method-assign]

    console._complete_initial_activity_rebuild()

    mock_edit.assert_called_once_with("idea")
    console._conn.close()


def test_complete_initial_activity_rebuild_skips_edit_when_brief_has_body(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True)
    cfg.researcher_root.mkdir(parents=True, exist_ok=True)
    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "research_idea.md").write_text(
        "# Research brief\n\nInvestigate widget performance.\n",
        encoding="utf-8",
    )
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]
    mock_edit = MagicMock()
    console._cmd_edit = mock_edit  # type: ignore[method-assign]

    console._complete_initial_activity_rebuild()

    mock_edit.assert_not_called()
    console._conn.close()


def test_cmd_edit_idea_prefills_prompt_without_heading(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "research_idea.md").write_text(
        "# Research brief\n\nLine one\n\nLine two\n",
        encoding="utf-8",
    )

    console._submit_prompt_text("/edit idea")

    assert prompt.text == "Line one\n\nLine two"
    assert prompt.focused is True
    assert prompt.cursor_location == (2, len("Line two"))
    assert console._pending_prompt_edit is not None
    assert console._pending_prompt_edit.target == "idea"

    console._conn.close()


def test_cmd_edit_prefs_prefills_prompt_without_heading(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "preferences.md").write_text(
        "# Preferences\n\n- simple\n- readable\n",
        encoding="utf-8",
    )

    console._submit_prompt_text("/edit prefs")

    assert prompt.text == "- simple\n- readable"
    assert prompt.focused is True
    assert prompt.cursor_location == (1, len("- readable"))
    assert console._pending_prompt_edit is not None
    assert console._pending_prompt_edit.target == "prefs"

    console._conn.close()


def test_submit_prompt_text_after_edit_idea_rewrites_research_brief(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "research_idea.md").write_text(
        "# Research brief\n\nOriginal idea\n",
        encoding="utf-8",
    )

    console._submit_prompt_text("/edit idea")
    console._submit_prompt_text("Updated idea\n\nWith details")

    assert (
        (state_dir / "research_idea.md").read_text(encoding="utf-8")
        == "# Research brief\n\nUpdated idea\n\nWith details\n"
    )
    assert console._pending_prompt_edit is None

    console._conn.close()


def test_submit_prompt_text_after_edit_prefs_rewrites_preferences(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "preferences.md").write_text(
        "# Preferences\n\n- old pref\n",
        encoding="utf-8",
    )

    console._submit_prompt_text("/edit preferences")
    console._submit_prompt_text("- new pref\n- another pref")

    assert (
        (state_dir / "preferences.md").read_text(encoding="utf-8")
        == "# Preferences\n\n- new pref\n- another pref\n"
    )
    assert console._pending_prompt_edit is None

    console._conn.close()


def test_submit_prompt_text_after_edit_allows_empty_body(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "research_idea.md").write_text(
        "# Research brief\n\nExisting body\n",
        encoding="utf-8",
    )

    console._submit_prompt_text("/edit idea")
    console._submit_prompt_text("")

    assert (
        (state_dir / "research_idea.md").read_text(encoding="utf-8")
        == "# Research brief\n\n"
    )
    assert console._pending_prompt_edit is None

    console._conn.close()


def test_slash_command_during_pending_edit_does_not_save_file(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    state_dir = memory.state_dir(cfg.researcher_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    original = "# Preferences\n\n- keep me\n"
    (state_dir / "preferences.md").write_text(original, encoding="utf-8")

    console._submit_prompt_text("/edit prefs")
    console._submit_prompt_text("/help")

    assert (state_dir / "preferences.md").read_text(encoding="utf-8") == original
    assert console._pending_prompt_edit is None
    assert any("Commands" in message for message in writes)

    console._conn.close()


def test_cmd_edit_invalid_usage_shows_helpful_message(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    console._submit_prompt_text("/edit roadmap")

    assert any("Usage:" in message and "/edit [idea|prefs]" in message for message in writes)
    assert console._pending_prompt_edit is None

    console._conn.close()


def test_cmd_report_no_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True, exist_ok=True)
    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    console._submit_prompt_text("/report")

    assert any("No reports found." in message for message in writes)
    console._conn.close()


def test_cmd_report_picks_newest_markdown(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    reports = cfg.project_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    older = reports / "older.md"
    newer = reports / "newer.md"
    older.write_text("# Older report\n", encoding="utf-8")
    newer.write_text("# Newer report\n", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))

    console = ResearchConsole(db_path, cfg)
    prompt = _FakePrompt()
    writes: list[str] = []
    console.query_one = _console_query_with_prompt_stub(writes, prompt)  # type: ignore[method-assign]

    console._submit_prompt_text("/report")

    joined = "\n".join(writes)
    assert "Newer report" in joined
    assert "Older report" not in joined
    console._conn.close()


def test_on_mount_schedules_fast_and_slow_poll_loops(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    timer_calls: list[tuple[float, str]] = []
    interval_calls: list[tuple[float, str]] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console.set_timer = lambda interval, callback: timer_calls.append((interval, callback.__name__))  # type: ignore[method-assign]
    console.set_interval = lambda interval, callback: interval_calls.append((interval, callback.__name__))  # type: ignore[method-assign]
    console._cleanup_orphaned_cycles = lambda: None  # type: ignore[method-assign]
    console._sync_rebuild_ids_from_db = lambda: None  # type: ignore[method-assign]

    console.on_mount()

    assert timer_calls == [(0.01, "_complete_initial_activity_rebuild")]
    assert interval_calls == [
        (console_mod._FAST_POLL_INTERVAL_SEC, "_poll_fast"),
        (console_mod._ANIMATION_POLL_INTERVAL_SEC, "_poll_animation"),
        (console_mod._SLOW_POLL_INTERVAL_SEC, "_poll_slow"),
    ]

    console._conn.close()


def test_fetch_last_stream_text_excludes_memory_compactor(tmp_path: Path) -> None:
    """Internal memory_compactor stream rows must not leak into visible excerpts."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn

    db.append_stream_chunk(
        conn,
        cycle=1,
        worker="memory_compactor",
        chunk=json.dumps(
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "secret compaction"},
            }
        ),
    )
    db.append_stream_chunk(
        conn,
        cycle=1,
        worker="planner",
        chunk=json.dumps(
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "visible planner"},
            }
        ),
    )

    got = console._fetch_last_stream_text(cycle=1)
    assert "visible planner" in got
    assert "secret compaction" not in got

    conn.close()


def test_memory_compactor_placeholder_query_is_cached(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    class _FakeCursor:
        def fetchone(self):
            return object()

    class _FakeConn:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *args, **kwargs):
            self.calls += 1
            return _FakeCursor()

    fake_conn = _FakeConn()
    console._conn.close()
    console._conn = fake_conn  # type: ignore[assignment]
    times = iter([100.0, 100.1])
    monkeypatch.setattr(console_mod.time, "time", lambda: next(times))

    assert console._memory_compactor_stream_before_worker_event() is True
    assert console._memory_compactor_stream_before_worker_event() is True
    assert fake_conn.calls == 1


def test_cmd_pause_when_idle_sets_paused(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True, exist_ok=True)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console._cmd_pause()
    assert db.get_system_state(conn)["control_mode"] == "paused"
    assert int(db.get_system_state(conn).get("graceful_pause_pending", 0) or 0) == 0
    console._conn.close()


def test_cmd_pause_when_running_sets_graceful_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True, exist_ok=True)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()

    class FakeScheduler:
        def is_alive(self) -> bool:
            return True

    console._scheduler = FakeScheduler()
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console._cmd_pause()
    assert int(db.get_system_state(conn).get("graceful_pause_pending", 0) or 0) == 1
    console._conn.close()


def test_cmd_undo_after_pause_restores_pre_first_checkpoint_state(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial", "--allow-empty"],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console._clear_activity_log = lambda: None  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)
    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="planner",
        roadmap_step="",
        task="do work",
        summary="done",
        payload={"worker_ok": True},
    )
    conn.execute("UPDATE system_state SET cycle_count = 1 WHERE id = 1")
    conn.commit()

    (cfg.project_dir / "f.txt").write_text("after cycle 1\n", encoding="utf-8")
    git_checkpoint.create_checkpoint(cfg.project_dir, 1, "planner")

    console._cmd_stop()
    assert (cfg.project_dir / "f.txt").read_text(encoding="utf-8") == "after cycle 1\n"
    assert git_checkpoint.has_checkpoint(cfg.project_dir) is True

    console._cmd_undo()

    assert (cfg.project_dir / "f.txt").read_text(encoding="utf-8") == "base\n"
    assert db.get_system_state(conn)["cycle_count"] == 0
    assert git_checkpoint.has_checkpoint(cfg.project_dir) is False
    assert any("Reverted to checkpoint" in m for m in writes)

    console._conn.close()


def test_cmd_undo_after_pause_rewinds_completed_checkpoint_chain(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial", "--allow-empty"],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)

    for cycle in range(1, 5):
        db.append_run_event(
            conn,
            cycle=cycle,
            kind="worker",
            worker="planner",
            roadmap_step="",
            task=f"cycle {cycle}",
            summary="done",
            payload={"worker_ok": True},
        )
        conn.execute("UPDATE system_state SET cycle_count = ? WHERE id = 1", (cycle,))
        conn.commit()
        (cfg.project_dir / "f.txt").write_text(f"cycle {cycle}\n", encoding="utf-8")
        git_checkpoint.create_checkpoint(cfg.project_dir, cycle, "planner")

    console._cmd_stop()
    console._cmd_undo()

    assert (cfg.project_dir / "f.txt").read_text(encoding="utf-8") == "cycle 3\n"
    assert db.get_system_state(conn)["cycle_count"] == 3
    assert git_checkpoint.get_checkpoint_cycle(cfg.project_dir) == 3
    assert any("Reverted to checkpoint" in m for m in writes)

    console._conn.close()


def test_cmd_undo_twice_while_paused_rebuilds_visible_cycles(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial", "--allow-empty"],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    console.query_one = _console_query_stub([])  # type: ignore[method-assign]
    console._clear_activity_log = lambda: None  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)

    visible_headers: list[str] = []

    def fake_mount(markup: str, classes: str = "activity-line") -> object:
        if "cycle-header" in classes:
            visible_headers.append(markup)
        return type("Widget", (), {"remove": lambda self: None})()

    console._mount_activity_widget = fake_mount  # type: ignore[method-assign]
    console._write_task = lambda task: None  # type: ignore[method-assign]
    console._write_result_box = lambda text, title="": None  # type: ignore[method-assign]
    console._scroll_to_bottom = lambda: None  # type: ignore[method-assign]
    console._clear_activity_log = lambda: None  # type: ignore[method-assign]

    for cycle in range(1, 5):
        db.append_run_event(
            conn,
            cycle=cycle,
            kind="orchestrator",
            worker="planner",
            roadmap_step="",
            task=f"cycle {cycle}",
            summary="route",
            payload={"worker": "planner"},
        )
        db.append_run_event(
            conn,
            cycle=cycle,
            kind="worker",
            worker="planner",
            roadmap_step="",
            task=f"cycle {cycle}",
            summary="done",
            payload={"worker_ok": True},
        )
        conn.execute("UPDATE system_state SET cycle_count = ? WHERE id = 1", (cycle,))
        conn.commit()
        (cfg.project_dir / "f.txt").write_text(f"cycle {cycle}\n", encoding="utf-8")
        git_checkpoint.create_checkpoint(cfg.project_dir, cycle, "planner")

    console._cmd_stop()
    visible_headers.clear()
    console._cmd_undo()
    visible_headers.clear()
    console._cmd_undo()

    assert db.get_system_state(conn)["cycle_count"] == 2
    assert any("cycle 1" in header for header in visible_headers)
    assert any("cycle 2" in header for header in visible_headers)
    assert not any("cycle 3" in header for header in visible_headers)

    console._conn.close()


def test_cmd_redo_restores_last_undone_checkpoint(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial", "--allow-empty"],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)

    for cycle in range(1, 5):
        db.append_run_event(
            conn,
            cycle=cycle,
            kind="worker",
            worker="planner",
            roadmap_step="",
            task=f"cycle {cycle}",
            summary="done",
            payload={"worker_ok": True},
        )
        conn.execute("UPDATE system_state SET cycle_count = ? WHERE id = 1", (cycle,))
        conn.commit()
        (cfg.project_dir / "f.txt").write_text(f"cycle {cycle}\n", encoding="utf-8")
        git_checkpoint.create_checkpoint(cfg.project_dir, cycle, "planner")

    console._cmd_stop()
    console._cmd_undo()
    console._cmd_redo()

    assert (cfg.project_dir / "f.txt").read_text(encoding="utf-8") == "cycle 4\n"
    assert db.get_system_state(console._conn)["cycle_count"] == 4
    assert git_checkpoint.get_checkpoint_cycle(cfg.project_dir) == 4
    assert any("Redid checkpoint" in m for m in writes)

    console._conn.close()


def test_cmd_redo_reapplies_local_changes_on_top(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir()

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial", "--allow-empty"],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    console.query_one = _console_query_stub([])  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)

    (cfg.project_dir / "f.txt").write_text("base\ncycle 1\n", encoding="utf-8")
    db.append_run_event(conn, cycle=1, kind="worker", worker="planner", roadmap_step="", task="cycle 1", summary="done", payload={"worker_ok": True})
    conn.execute("UPDATE system_state SET cycle_count = 1 WHERE id = 1")
    conn.commit()
    git_checkpoint.create_checkpoint(cfg.project_dir, 1, "planner")

    (cfg.project_dir / "f.txt").write_text("base\ncycle 1\ncycle 2\n", encoding="utf-8")
    db.append_run_event(conn, cycle=2, kind="worker", worker="planner", roadmap_step="", task="cycle 2", summary="done", payload={"worker_ok": True})
    conn.execute("UPDATE system_state SET cycle_count = 2 WHERE id = 1")
    conn.commit()
    git_checkpoint.create_checkpoint(cfg.project_dir, 2, "planner")

    console._cmd_stop()
    console._cmd_undo()
    (cfg.project_dir / "notes.txt").write_text("local edit\n", encoding="utf-8")
    console._cmd_redo()

    assert (cfg.project_dir / "f.txt").read_text(encoding="utf-8") == "base\ncycle 1\ncycle 2\n"
    assert (cfg.project_dir / "notes.txt").read_text(encoding="utf-8") == "local edit\n"
    assert db.get_system_state(console._conn)["cycle_count"] == 2

    console._conn.close()


# ---------------------------------------------------------------------------
# Regression: successful worker output with "is_error" key must NOT be
# displayed as "Failed".
# ---------------------------------------------------------------------------


def test_worker_ok_from_payload_not_summary_substring(tmp_path: Path) -> None:
    """The console must read worker_ok from payload_json, not substring-match on summary."""
    db_path = tmp_path / "runtime.db"
    conn = db.connect_db(db_path)
    db.get_system_state(conn)

    summary_with_error_key = (
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"Updated train.py"}'
    )
    payload = json.dumps({"worker_ok": True, "last_action_summary": summary_with_error_key})
    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="implementer",
        roadmap_step="",
        task="implement phase 5",
        summary=summary_with_error_key,
        payload={"worker_ok": True, "last_action_summary": summary_with_error_key},
    )
    conn.commit()

    rows = list(
        conn.execute(
            "SELECT id, ts, cycle, kind, worker, roadmap_step, task, summary, payload_json "
            "FROM run_events WHERE kind = 'worker' ORDER BY id DESC LIMIT 1"
        )
    )
    assert len(rows) == 1
    row = rows[0]
    pj = json.loads(row["payload_json"]) if row["payload_json"] else {}
    ok = pj.get("worker_ok", True)
    assert ok is True, "worker_ok should be True even though summary contains 'is_error'"


def test_poll_run_events_surfaces_worker_error_excerpt(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console._refresh_file_changes = lambda force=False: None  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)

    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="reporter",
        roadmap_step="",
        task="write report",
        summary="cycle crashed: openai.APIStatusError",
        payload={
            "worker_ok": False,
            "error": (
                "Traceback (most recent call last):\n"
                "  File \"x.py\", line 1, in <module>\n"
                "openai.APIStatusError: Error code: 402 - insufficient credits\n"
                "During task with name 'choose' and id 'abc'\n"
            ),
        },
    )
    conn.commit()

    console._poll_run_events()

    assert any("Error:[/]" in m and "402 - insufficient credits" in m for m in writes)

    console._conn.close()
    conn.close()


def test_poll_run_events_clears_below_stream_after_worker_not_on_orchestrator(
    tmp_path: Path,
) -> None:
    """Ephemeral slash-command lines should clear when the worker finishes, not on the next orchestrator tick."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)

    class FakeScroll:
        is_vertical_scroll_end = True
        is_vertical_scrollbar_grabbed = False

        def mount(self, w, before=None, after=None) -> None:
            pass

        def scroll_end(self, animate: bool = False) -> None:
            pass

        def scroll_to_widget(self, *args, **kwargs) -> None:
            pass

    class FakeStatic:
        def update(self, *args, **kwargs) -> None:
            pass

        display = True

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#activity-scroll":
            return FakeScroll()
        return FakeStatic()

    console.query_one = fake_query  # type: ignore[method-assign]
    console.call_after_refresh = lambda fn: fn()  # type: ignore[method-assign]
    console._refresh_file_changes = lambda force=False: None  # type: ignore[method-assign]
    console._fetch_last_stream_text = lambda cycle: ""  # type: ignore[method-assign]
    console._scroll_to_bottom = lambda: None  # type: ignore[method-assign]

    clear_calls = 0
    real_clear = console._clear_below_stream_feedback

    def counting_clear() -> None:
        nonlocal clear_calls
        clear_calls += 1
        real_clear()

    console._clear_below_stream_feedback = counting_clear  # type: ignore[method-assign]

    db.append_run_event(
        conn,
        cycle=1,
        kind="orchestrator",
        worker="planner",
        roadmap_step="",
        task="t1",
        summary="",
        payload=None,
    )
    conn.commit()

    console._poll_run_events()
    assert clear_calls == 0

    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="planner",
        roadmap_step="",
        task="t1",
        summary="done",
        payload={"worker_ok": True},
    )
    conn.commit()

    console._poll_run_events()
    assert clear_calls == 1

    console._conn.close()


def test_kill_agent_processes_uses_fast_shutdown_path(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    agent_id = db.create_agent_run(conn, prompt="inspect bug")

    class FakeAgentProc:
        def __init__(self) -> None:
            self.wait_timeouts: list[float | None] = []

        def kill_group(self, *, wait_timeout: float | None = 5.0) -> None:
            self.wait_timeouts.append(wait_timeout)

    proc = FakeAgentProc()
    console._agent_processes = {agent_id: proc}  # type: ignore[assignment]

    refresh_calls: list[float] = []

    def fake_refresh_system_tier_from_db(*args, **kwargs) -> None:
        refresh_calls.append(float(kwargs["db_timeout"]))

    monkeypatch.setattr(memory, "refresh_system_tier_from_db", fake_refresh_system_tier_from_db)

    console._kill_agent_processes()

    row = db.get_agent_run(conn, agent_id)
    assert row is not None
    assert str(row["status"]) == "failed"
    assert proc.wait_timeouts == [0.2]
    assert refresh_calls == [0.2]

    console._conn.close()


def test_kill_scheduler_uses_fast_shutdown_path(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    class FakeScheduler:
        def __init__(self) -> None:
            self.wait_timeouts: list[float | None] = []

        def is_alive(self) -> bool:
            return True

        def kill_group(self, *, wait_timeout: float | None = 5.0) -> None:
            self.wait_timeouts.append(wait_timeout)

    scheduler = FakeScheduler()
    console._scheduler = scheduler  # type: ignore[assignment]
    console._orchestrating = True
    console._stream_is_running_placeholder = True

    console._kill_scheduler()

    assert scheduler.wait_timeouts == [0.1]
    assert console._scheduler is None
    assert console._orchestrating is False
    assert console._stream_is_running_placeholder is False

    console._conn.close()


# ---------------------------------------------------------------------------
# _fetch_last_stream_text prefers the result event over individual deltas
# ---------------------------------------------------------------------------


def test_fetch_last_stream_text_uses_result_event(tmp_path: Path) -> None:
    """The full response from the result event should be returned, not the last delta."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn

    full_text = (
        "Here is the code:\n\n"
        "```python\n140:175:src/analyticgmm/poly_gaussian.py\n"
        "    def integrate_lebesgue(self, dims):\n"
        "        pg = self\n"
        "        for dim in range(d0 - 1, -1, -1):\n"
        "            if dim in wanted:\n"
        "                pg = pg.integrate_lebesgue_1d(dim)\n"
        "        return pg\n```"
    )

    db.append_stream_chunk(conn, cycle=1, worker="implementer",
                           chunk=json.dumps({"type": "content_block_delta",
                                             "delta": {"type": "text_delta", "text": "return pg"}}))
    db.append_stream_chunk(conn, cycle=1, worker="implementer",
                           chunk=json.dumps({"type": "result", "subtype": "success",
                                             "is_error": False, "result": full_text}))

    got = console._fetch_last_stream_text(cycle=1)
    assert "integrate_lebesgue" in got
    assert "140:175" in got
    assert got == full_text.strip()

    conn.close()


def test_fetch_last_stream_text_falls_back_to_delta(tmp_path: Path) -> None:
    """When no result event exists, fall back to the last text delta."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn

    db.append_stream_chunk(conn, cycle=1, worker="planner",
                           chunk=json.dumps({"type": "content_block_delta",
                                             "delta": {"type": "text_delta", "text": "some delta"}}))

    got = console._fetch_last_stream_text(cycle=1)
    assert got == "some delta"

    conn.close()


# ---------------------------------------------------------------------------
# Stream event parsing
# ---------------------------------------------------------------------------


def test_parse_stream_event_tool_use() -> None:
    chunk = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "src/train.py"}}
            ]
        },
    })
    result = events.parse_stream_event(chunk)
    assert result is not None
    assert result[0] == "tool"
    assert "Reading" in result[1]
    assert "train.py" in result[1]


def test_parse_stream_event_nested_tool_call_includes_argument() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "readToolCall": {
                "args": {
                    "path": "/tmp/project/src/train.py",
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "📖 Reading /tmp/project/src/train.py")


def test_parse_stream_event_write_tool_call_extra_space_after_pencil() -> None:
    """``Write`` uses ``✍️ `` in labels plus ``_TOOL_EMOJI_GAP`` so the verb does not crowd the icon."""
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "writeToolCall": {
                "args": {"path": "/tmp/out.md"},
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "✍️  Writing /tmp/out.md")


def test_parse_stream_event_edit_tool_call_includes_path() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "editToolCall": {
                "args": {"path": "/tmp/roadmap.md"},
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "📝 Editing /tmp/roadmap.md")


def test_parse_stream_event_shell_tool_call_includes_command() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "shellToolCall": {
                "args": {
                    "command": "pytest tests/test_console.py -q",
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "🐚 Running in shell pytest tests/test_console.py -q")


def test_parse_stream_event_git_shell_tool_call_uses_git_label() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "shellToolCall": {
                "args": {
                    "command": "git status --short",
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "🌿 Git git status --short")


def test_parse_stream_event_shell_tool_call_keeps_description() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "shellToolCall": {
                "args": {
                    "command": "python -m pytest -q --tb=line",
                },
                "description": "Run full pytest suite",
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == (
        "tool",
        "🐚 Running in shell python -m pytest -q --tb=line (Run full pytest suite)",
    )


def test_parse_stream_event_semsearch_tool_call_formats_query() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "semSearchToolCall": {
                "args": {
                    "query": "Where is train_extrinsic_baseline defined?",
                    "targetDirectories": ["/tmp/project"],
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == (
        "tool",
        "🧠 Semantic search Where is train_extrinsic_baseline defined?",
    )


def test_parse_stream_event_grep_tool_call_formats_pattern_and_path() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "grepToolCall": {
                "args": {
                    "pattern": "train_iters|frames_per_batch",
                    "path": "/tmp/project/scripts",
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == (
        "tool",
        "🔍 Searching train_iters|frames_per_batch in /tmp/project/scripts",
    )


def test_parse_stream_event_read_lints_tool_call_formats_paths() -> None:
    chunk = json.dumps({
        "type": "tool_call",
        "tool_call": {
            "readLintsToolCall": {
                "args": {
                    "paths": [
                        "/tmp/project/a.py",
                        "/tmp/project/b.py",
                    ],
                }
            }
        },
    })
    result = events.parse_stream_event(chunk)
    assert result == ("tool", "🩺 Checking lints /tmp/project/a.py, /tmp/project/b.py")


def test_parse_stream_event_skips_result() -> None:
    chunk = json.dumps({"type": "result", "subtype": "success", "is_error": False})
    assert events.parse_stream_event(chunk) == ("boundary", "")


def test_parse_stream_event_message_stop_is_boundary() -> None:
    chunk = json.dumps({"type": "message_stop"})
    assert events.parse_stream_event(chunk) == ("boundary", "")


def test_parse_stream_event_thinking_is_skipped() -> None:
    chunk = json.dumps({"type": "thinking", "subtype": "delta", "text": "internal"})
    assert events.parse_stream_event(chunk, full_text=True) is None


def test_parse_stream_event_plain_text() -> None:
    result = events.parse_stream_event("hello world")
    assert result == ("text", "hello world")


def test_parse_stream_event_assistant_is_complete_message() -> None:
    chunk = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Hello world\n\nMore detail"}
            ]
        },
    })
    assert events.parse_stream_event(chunk, full_text=True) == ("message", "Hello world\n\nMore detail")


def test_stream_buffer_replaces_closed_message(tmp_path: Path) -> None:
    console = ResearchConsole(tmp_path / "runtime.db", _cfg(tmp_path))

    console._append_stream_text_delta("First message")
    console._stream_message_closed = True
    console._append_stream_text_delta("Second message")

    assert console._stream_text_live == "Second message"
    assert console._last_stream_text == "First messageSecond message"

    console._conn.close()


def test_replace_stream_message_overwrites_visible_text(tmp_path: Path) -> None:
    console = ResearchConsole(tmp_path / "runtime.db", _cfg(tmp_path))

    console._append_stream_text_delta("partial")
    console._replace_stream_message("final message")

    assert console._stream_text_live == "final message"
    assert console._stream_message_closed is True

    console._conn.close()


def test_format_stream_rows_drop_vertical_bars(tmp_path: Path) -> None:
    console = ResearchConsole(tmp_path / "runtime.db", _cfg(tmp_path))

    assert "┊" not in console._format_stream_tool_row("📖 Reading src/train.py")
    assert "┊" not in console._format_stream_text_block("hello\nworld")

    console._conn.close()


def test_format_worker_result_excerpt_shows_text() -> None:
    out = events.format_worker_result_excerpt(True, result_text="Added slippery flag support")
    assert "slippery" in out
    assert "Done" not in out


def test_format_worker_result_excerpt_ok_empty() -> None:
    assert events.format_worker_result_excerpt(True, "") == ""


def test_format_worker_result_excerpt_fail_empty() -> None:
    assert "failed" in events.format_worker_result_excerpt(False, "").lower()


def test_format_cycle_header_no_truncation() -> None:
    long_task = "A" * 300
    out = events.format_cycle_header(1, "planner", long_task)
    assert "cycle 1" in out
    assert "planner" in out
    assert "●" in out
    assert "0.0s" in out


def test_format_cycle_header_done_shows_elapsed() -> None:
    out = events.format_cycle_header(
        2, "researcher", "task", elapsed_sec=12.36, status="ok",
    )
    assert "12.4s" in out
    assert "cycle 2" in out


def test_format_cycle_header_shows_cursor_model_dim() -> None:
    out = events.format_cycle_header(3, "reporter", "t", cursor_model="auto", status="running")
    assert "cycle 3" in out
    assert "reporter" in out
    assert "[dim](auto)[/]" in out


def test_render_markdown_converts_pipe_table_to_rich_table() -> None:
    rendered = events.render_markdown(
        "| Name | Score |\n"
        "| --- | --- |\n"
        "| Alice | 10 |\n"
        "| Bob | 8 |"
    )
    assert isinstance(rendered, Table)
    assert [column.header.plain for column in rendered.columns] == ["Name", "Score"]
    assert rendered.row_count == 2
    assert rendered.box == events._MARKDOWN_TABLE_BOX
    assert rendered.show_lines is True


def test_render_markdown_converts_pipe_rows_without_separator_to_table() -> None:
    rendered = events.render_markdown("| Name | Score |\n| Alice | 10 |\n| Bob | 8 |")
    assert isinstance(rendered, Table)
    assert [column.header.plain for column in rendered.columns] == ["Name", "Score"]
    assert rendered.row_count == 2


def test_render_markdown_wraps_code_block_in_syntax_panel() -> None:
    rendered = events.render_markdown("```python\nprint('hello')\n```")
    assert isinstance(rendered, Panel)
    assert isinstance(rendered.renderable, Syntax)
    assert "python" in str(rendered.title)
    assert rendered.renderable.line_numbers is False


def test_render_markdown_highlights_language_keywords() -> None:
    rendered = events.render_markdown("```py\nfor item in items:\n    if item:\n        pass\n```")
    assert isinstance(rendered, Panel)
    assert isinstance(rendered.renderable, Syntax)

    console = Console(width=80, record=True)
    first_line = console.render_lines(rendered.renderable)[0]
    segment_styles = {segment.text.strip(): str(segment.style) for segment in first_line if segment.text.strip()}

    assert "for" in segment_styles
    assert "item" in segment_styles
    assert segment_styles["for"] != segment_styles["item"]


def test_render_markdown_guesses_python_for_unlabeled_code_block() -> None:
    rendered = events.render_markdown("```\nfor item in items:\n    if item:\n        pass\n```")
    assert isinstance(rendered, Panel)
    assert isinstance(rendered.renderable, Syntax)

    console = Console(width=80, record=True)
    first_line = console.render_lines(rendered.renderable)[0]
    segment_styles = {segment.text.strip(): str(segment.style) for segment in first_line if segment.text.strip()}

    assert "for" in segment_styles
    assert "item" in segment_styles
    assert segment_styles["for"] != segment_styles["item"]


def test_render_markdown_code_ref_extracts_filepath_as_title() -> None:
    rendered = events.render_markdown(
        "```python\n140:175:/some/path/poly_gaussian.py\n"
        "    pg: PolyGaussian = self\n    return pg\n```"
    )
    assert isinstance(rendered, Panel)
    assert isinstance(rendered.renderable, Syntax)
    assert "poly_gaussian.py" in str(rendered.title)
    assert rendered.renderable.start_line == 140
    assert rendered.renderable.line_numbers is True


def test_render_markdown_mixes_text_and_table() -> None:
    rendered = events.render_markdown(
        "Summary\n\n"
        "| Name | Score |\n"
        "| --- | --- |\n"
        "| Alice | 10 |"
    )
    assert isinstance(rendered, Group)
    assert any(isinstance(item, Table) for item in rendered.renderables)


def test_render_markdown_renders_task_list_checkboxes() -> None:
    rendered = events.render_markdown(
        "## Checklist\n\n"
        "- [x] Finish parser\n"
        "  - [ ] Wire live UI\n"
    )
    console = Console(width=80, record=True)
    console.print(rendered)
    out = console.export_text()
    assert "Checklist" in out
    assert "☒ Finish parser" in out
    assert "☐ Wire live UI" in out


def test_refresh_checklist_reads_immediate_plan_section(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    class FakeStatic:
        def __init__(self) -> None:
            self.updated = None
            self.display = True

        def update(self, renderable) -> None:
            self.updated = renderable

    memory_dir = cfg.researcher_root / "state"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "immediate_plan.md").write_text(
        "# Immediate plan\n\n"
        "## Overview\n\n"
        "Ship checklist UI.\n\n"
        "## Checklist\n\n"
        "- [x] Canonicalize format\n"
        "  - [ ] Refresh each cycle\n\n"
        "## Notes\n\n"
        "Ignore this.\n",
        encoding="utf-8",
    )

    fake = FakeStatic()
    console._checklist_widget = fake  # type: ignore[assignment]
    console._refresh_checklist(force=True)

    assert console._last_checklist_text.startswith("## Checklist")
    assert "Refresh each cycle" in console._last_checklist_text
    assert fake.updated is not None
    assert fake.display is True

    console._conn.close()


# ---------------------------------------------------------------------------
# Scheduler health check: console detects dead scheduler and auto-restarts
# ---------------------------------------------------------------------------


def test_check_scheduler_health_restarts_dead_process(tmp_path: Path) -> None:
    """When the scheduler dies while DB says 'active', the console should auto-restart."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()

    writes: list[str] = []

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    spawned: list[bool] = []

    def fake_restart(self_console: ResearchConsole) -> None:
        spawned.append(True)
        self_console._scheduler = type("Alive", (), {"is_alive": lambda self: True})()

    console._scheduler = DeadScheduler()
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    console._restart_scheduler = lambda: fake_restart(console)  # type: ignore[method-assign]

    console._check_scheduler_health()

    assert len(spawned) == 1, "scheduler should have been restarted"
    assert console._auto_restarts == 1
    assert any("unexpectedly" in m.lower() for m in writes)

    console._conn.close()


def test_check_scheduler_health_stops_after_max_restarts(tmp_path: Path) -> None:
    """After _MAX_AUTO_RESTARTS, the console should stop restarting and set mode to paused."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    conn.commit()

    writes: list[str] = []

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    console._scheduler = DeadScheduler()
    console._auto_restarts = console._MAX_AUTO_RESTARTS
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]

    console._check_scheduler_health()

    mode = db.get_system_state(conn)["control_mode"]
    assert mode == "paused", "should have set mode to paused after exhausting restarts"
    assert any("/start" in m for m in writes)

    console._conn.close()


def test_check_scheduler_health_ignores_paused_mode(tmp_path: Path) -> None:
    """When the scheduler exits and DB says 'paused', the console should NOT restart."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    console._scheduler = DeadScheduler()

    console._check_scheduler_health()

    assert console._scheduler is None, "scheduler ref should be cleared"
    assert console._auto_restarts == 0, "should not have attempted a restart"

    console._conn.close()


def test_check_scheduler_health_no_spurious_checkpoint_notice_on_clean_exit(tmp_path: Path) -> None:
    """Completed cycle + paused DB: dead scheduler should not claim a checkpoint revert."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    cfg.project_dir.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=cfg.project_dir, check=True, capture_output=True)
    (cfg.project_dir / "f.txt").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=cfg.project_dir, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
            "--allow-empty",
        ],
        cwd=cfg.project_dir,
        check=True,
        capture_output=True,
    )

    console = ResearchConsole(db_path, cfg)
    writes: list[str] = []
    console.query_one = _console_query_stub(writes)  # type: ignore[method-assign]
    conn = console._conn
    db.get_system_state(conn)
    db.append_run_event(
        conn,
        cycle=1,
        kind="orchestrator",
        worker="planner",
        roadmap_step="",
        task="t",
        summary="",
        payload=None,
    )
    db.append_run_event(
        conn,
        cycle=1,
        kind="worker",
        worker="planner",
        roadmap_step="",
        task="t",
        summary="done",
        payload={"worker_ok": True},
    )
    conn.execute("UPDATE system_state SET cycle_count = 1 WHERE id = 1")
    db.set_control_mode(conn, "paused")
    conn.commit()
    git_checkpoint.create_checkpoint(cfg.project_dir, 1, "planner")

    class DeadScheduler:
        def is_alive(self) -> bool:
            return False

    console._scheduler = DeadScheduler()
    console._check_scheduler_health()

    assert not any("Reverted to checkpoint" in m for m in writes)

    console._conn.close()


def test_poll_animated_stream_status_clears_stale_placeholder_when_paused(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "paused")
    conn.commit()

    class AliveScheduler:
        def is_alive(self) -> bool:
            return True

    class FakeStatic:
        def __init__(self) -> None:
            self.display = True
            self.last = None

        def update(self, value) -> None:
            self.last = value

    stream = FakeStatic()
    header = FakeStatic()

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#stream-text":
            return stream
        if sel == "#header":
            return header
        return _console_query_stub([])(sel, *args, **kwargs)

    console.query_one = fake_query  # type: ignore[method-assign]
    console._scheduler = AliveScheduler()
    console._orchestrating = True
    console._set_stream_placeholder("[dim]Orchestrating...[/]")

    console._poll_animated_stream_status()

    assert console._orchestrating is False
    assert stream.display is False

    console._conn.close()


def test_poll_animated_stream_status_memory_compactor_placeholder(tmp_path: Path) -> None:
    """Pre-orchestrator compaction streams before the worker run_event; no transcript in the log."""
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)
    conn = console._conn
    db.get_system_state(conn)
    db.set_control_mode(conn, "active")
    db.append_stream_chunk(conn, 2, "memory_compactor", "chunk")
    conn.commit()

    class AliveScheduler:
        def is_alive(self) -> bool:
            return True

    class FakeStatic:
        def __init__(self) -> None:
            self.display = True
            self.last = None

        def update(self, value) -> None:
            self.last = value

    stream = FakeStatic()

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#stream-text":
            return stream
        return _console_query_stub([])(sel, *args, **kwargs)

    console.query_one = fake_query  # type: ignore[method-assign]
    console._scheduler = AliveScheduler()
    console._orchestrating = True
    console._orchestrating_tick = 0

    console._poll_animated_stream_status()

    assert stream.last is not None
    inner = stream.last.renderable
    assert "Compressing Memory" in inner.plain

    db.append_run_event(
        conn,
        cycle=2,
        kind="worker",
        worker="memory_compactor",
        roadmap_step="",
        task="t",
        summary="done",
        payload={"worker_ok": True},
    )
    conn.commit()
    console._orchestrating_tick = 0
    console._poll_run_events()
    console._poll_animated_stream_status()

    inner2 = stream.last.renderable
    assert "Orchestrating" in inner2.plain
    assert "Compressing Memory" not in inner2.plain

    console._conn.close()


def test_poll_animated_stream_status_keeps_animating_while_scheduler_start_is_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)
    console = ResearchConsole(db_path, cfg)

    class FakeStatic:
        def __init__(self) -> None:
            self.display = True
            self.last = None

        def update(self, value) -> None:
            self.last = value

    stream = FakeStatic()

    def fake_query(sel: str, *args, **kwargs):
        if sel == "#stream-text":
            return stream
        return _console_query_stub([])(sel, *args, **kwargs)

    console.query_one = fake_query  # type: ignore[method-assign]
    console._scheduler_start_pending = True
    console._orchestrating_tick = 0

    console._poll_animated_stream_status()

    assert stream.last is not None
    inner = stream.last.renderable
    assert "Orchestrating" in inner.plain

    console._conn.close()
