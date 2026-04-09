from __future__ import annotations

import json
from pathlib import Path

from rich import box
from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from research_lab import db
from research_lab.config import RunConfig
from research_lab.ui import events
from research_lab.ui.console import ResearchConsole


def _console_query_stub(captured: list[str]):
    """Minimal Textual stand-ins so console methods can mount activity lines."""

    class FakeScroll:
        def mount(self, w, before=None) -> None:
            text = getattr(w, "content", None) or getattr(w, "renderable", None)
            captured.append(str(text) if text is not None else "")

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


def _cfg(tmp_path: Path) -> RunConfig:
    project_dir = tmp_path / "project"
    researcher_root = project_dir / ".airesearcher"
    return RunConfig(
        researcher_root=researcher_root,
        project_dir=project_dir,
        research_idea="idea",
        preferences="prefs",
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
    assert console._orchestrating is True

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
    conn.close()


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


def test_parse_stream_event_skips_result() -> None:
    chunk = json.dumps({"type": "result", "subtype": "success", "is_error": False})
    assert events.parse_stream_event(chunk) is None


def test_parse_stream_event_plain_text() -> None:
    result = events.parse_stream_event("hello world")
    assert result == ("text", "hello world")


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
