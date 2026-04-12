"""Textual TUI: Claude Code-inspired layout with streaming output."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.markup import escape as rich_escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Static, TextArea

from lab import db, helpers, memory
from lab.global_config import project_researcher_root
from lab.runner import reset_project_preserving_research_idea
from lab.ui import events
from lab.ui.prompt_text_area import PromptSubmitted, PromptTextArea

if TYPE_CHECKING:
    from lab.config import RunConfig
    from lab.loop import SchedulerProcessHandle

@dataclass
class _RedoSnapshot:
    token: str
    tree_ref: str
    checkpoint_sha: str | None
    snapshot_dir: Path
    cycle: int


@dataclass
class _LiveDiffState:
    from_ref: str
    to_ref: str | None
    title_text: str
    widget: Static
    last_raw_diff: str = ""


@dataclass
class _LivePlanState:
    widget: Static
    last_text: str = ""

CSS = """
Screen {
    background: $surface;
}

#header {
    height: 1;
    dock: top;
    background: $panel;
    color: $text-muted;
    padding: 0 2;
}

#activity-scroll {
    padding: 0 1;
    scrollbar-size: 1 1;
    /* Avoid stable gutter: it reserves a column even when the scrollbar is not
       mounted (short content), which reads as a phantom track and clashes with
       rounded Rich panels (e.g. live tool-call box) along the right edge. */
    scrollbar-gutter: auto;
}

.activity-line {
    height: auto;
    width: 1fr;
}

.cycle-header {
    margin: 3 0 0 0;
    padding: 1 2;
    border-top: heavy $surface-lighten-2;
}

#prompt-box {
    dock: bottom;
    layout: horizontal;
    width: 100%;
    height: 3;
    max-height: 14;
    min-height: 3;
    margin: 1 0 0 0;
    padding: 0 1;
    border: round $accent;
    background: $surface-darken-1;
}

#prompt-indicator {
    width: 2;
    height: 1;
    color: $success;
    text-style: bold;
    content-align: left top;
}

#prompt {
    width: 1fr;
    min-width: 0;
    max-width: 100%;
    height: 1;
    border: none;
    background: transparent;
    color: $text;
    padding: 0;
}

#prompt:focus {
    border: none;
}

.task-prompt {
    height: auto;
    padding: 1 3;
    margin: 0 2;
    color: rgb(235, 160, 160);
    border-left: tall $surface-lighten-1;
}

.file-changes {
    height: auto;
    width: 1fr;
    margin: 0 3;
    padding: 0 1;
}

.checklist-box {
    height: auto;
    margin: 0 2;
    width: 1fr;
    min-width: 0;
}

#stream-text {
    height: auto;
    margin: 0 2;
    width: 1fr;
    min-width: 0;
}

.result-box {
    height: auto;
    margin: 1 2 0 2;
    width: 1fr;
    min-width: 0;
}
"""


class ResearchConsole(App[None]):
    """Interactive console with on-demand scheduler lifecycle."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    CSS = CSS

    def __init__(self, db_path: Path, cfg: RunConfig) -> None:
        super().__init__()
        self.db_path = db_path
        self.cfg = cfg
        self._conn = db.connect_db(db_path)
        self._scheduler: SchedulerProcessHandle | None = None
        self._last_stream_id = 0
        self._last_run_event_id = 0
        self._last_cycle = 0
        self._last_worker = ""
        self._worker_start_ts: float = 0.0
        self._last_orchestrator_task = ""
        self._cycle_header_widget: Static | None = None
        self._project_name = cfg.project_dir.name
        self._model = cfg.openai_model
        self._auto_restarts = 0
        self._MAX_AUTO_RESTARTS = 3
        self._last_stream_text = ""
        self._stream_tool_markup = ""
        self._stream_text_live = ""
        self._cumulative_stream_text = ""
        self._stream_message_closed = False
        self._stream_last_event_was_tool = False
        self._current_cycle_widgets: list[Static] = []
        self._file_changes_widget: Static | None = None
        self._checklist_widget: Static | None = None
        self._last_checklist_text = ""
        self._last_file_changes_ts: float = 0.0
        self._orchestrating = False
        self._orchestrating_tick = 0
        self._stream_is_running_placeholder = False
        self._running_worker_tick = 0
        self._welcome_widgets: list[Static] = []
        self._redo_stack: list[_RedoSnapshot] = []
        self._checkpoint_notice_widget: Static | None = None
        self._diff_widgets: list[Static] = []
        self._live_diff_state: _LiveDiffState | None = None
        self._live_plan_state: _LivePlanState | None = None

    def _cycle_header_cursor_model(self) -> str | None:
        """Cursor CLI ``--model`` value for cycle headers (only when workers use Cursor)."""
        if self.cfg.default_worker_backend != "cursor":
            return None
        m = (self.cfg.cursor_agent_model or "").strip()
        return m or None

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with VerticalScroll(id="activity-scroll"):
            yield Static("", id="stream-text")
        with Container(id="prompt-box"):
            yield Static("❯", id="prompt-indicator")
            yield PromptTextArea(
                "",
                id="prompt",
                placeholder="Type here · Enter to send · Shift+Enter for new line",
                compact=True,
                show_line_numbers=False,
            )

    def on_mount(self) -> None:
        self._cleanup_orphaned_cycles()
        self._refresh_header()
        self.query_one("#stream-text", Static).display = False
        self._rebuild_activity_from_db()
        self.query_one("#prompt", PromptTextArea).focus()
        self.set_interval(0.3, self._poll)

    # --- activity helpers -----------------------------------------------------

    def _write_welcome_lines(self) -> None:
        self._welcome_widgets = []
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        for markup in (
            "  [bold]Welcome to lab.[/]",
            "  Type [bold]/start[/] to begin, [bold]/help[/] for a list of commands. "
            "Type additional instructions at any time.",
        ):
            w = Static(markup, classes="activity-line")
            scroll.mount(w, before=stream)
            self._welcome_widgets.append(w)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

    def _remove_welcome_intro(self) -> None:
        """Drop the initial welcome lines after the user sends any input."""
        for w in self._welcome_widgets:
            w.remove()
        self._welcome_widgets = []

    def _clear_diff_widgets(self) -> None:
        """Remove any previously-shown /diff output widgets."""
        for w in self._diff_widgets:
            try:
                w.remove()
            except Exception:
                pass
        self._diff_widgets = []
        self._live_diff_state = None

    def _clear_activity_log(self) -> None:
        """Remove all lines from the scroll area except the live stream panel."""
        self._welcome_widgets = []
        self._checkpoint_notice_widget = None
        self._diff_widgets = []
        self._live_diff_state = None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        children = list(getattr(scroll, "children", []))
        for child in children:
            if child is not stream:
                try:
                    child.remove()
                except Exception:
                    pass

    def _clear_below_stream_feedback(self) -> None:
        """Remove ephemeral lines under the stream panel (slash commands, status, etc.)."""
        self._checkpoint_notice_widget = None
        self._diff_widgets = []
        self._live_diff_state = None
        self._live_plan_state = None
        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
            stream = self.query_one("#stream-text", Static)
        except Exception:
            return
        children = list(getattr(scroll, "children", []))
        try:
            idx = children.index(stream)
        except ValueError:
            return
        for w in children[idx + 1 :]:
            try:
                w.remove()
            except Exception:
                pass

    def _rebuild_activity_from_db(self) -> None:
        """Re-render completed cycles from DB so undo/redo immediately refresh the UI."""
        self._clear_activity_log()
        self._current_cycle_widgets = []
        self._cycle_header_widget = None
        self._file_changes_widget = None
        self._checklist_widget = None
        self._last_checklist_text = ""
        self._last_file_changes_ts = 0.0
        self._worker_start_ts = 0.0
        self._last_worker = ""
        self._last_orchestrator_task = ""

        try:
            rows = list(
                self._conn.execute(
                    "SELECT cycle, ts, kind, worker, task, summary, payload_json "
                    "FROM run_events ORDER BY cycle ASC, id ASC"
                )
            )
        except sqlite3.OperationalError:
            rows = []

        by_cycle: dict[int, dict[str, sqlite3.Row]] = {}
        for row in rows:
            bucket = by_cycle.setdefault(int(row["cycle"]), {})
            bucket[str(row["kind"])] = row

        if not by_cycle:
            self._write_welcome_lines()
            return

        for cycle in sorted(by_cycle):
            worker_row = by_cycle[cycle].get("worker")
            if worker_row is None:
                continue
            orch_row = by_cycle[cycle].get("orchestrator")
            payload: dict = {}
            try:
                payload = json.loads(worker_row["payload_json"]) if worker_row["payload_json"] else {}
            except (json.JSONDecodeError, TypeError):
                payload = {}
            ok = payload.get("worker_ok", True)
            start_ts = float(orch_row["ts"]) if orch_row else float(worker_row["ts"])
            elapsed = max(0.0, float(worker_row["ts"]) - start_ts)
            worker = worker_row["worker"]
            task = (worker_row["task"] or "") or (orch_row["task"] if orch_row else "") or ""
            header = self._mount_activity_widget(
                events.format_cycle_header(
                    cycle,
                    worker,
                    task,
                    cursor_model=self._cycle_header_cursor_model(),
                    elapsed_sec=elapsed,
                    status="ok" if ok else "fail",
                ),
                classes="activity-line cycle-header",
            )
            self._current_cycle_widgets.append(header)
            task_w = self._write_task(task)
            if task_w is not None:
                self._current_cycle_widgets.append(task_w)
            checklist = str(payload.get("immediate_plan_checklist", "") or "").strip()
            checklist_w = self._write_checklist_box(checklist)
            if checklist_w is not None:
                self._current_cycle_widgets.append(checklist_w)

            excerpt = events.extract_result_excerpt(self._fetch_last_stream_text(cycle))
            if not excerpt:
                excerpt = events.extract_result_excerpt(worker_row["summary"] or "")
            if excerpt:
                result_w = self._write_result_box(excerpt)
                if result_w is not None:
                    self._current_cycle_widgets.append(result_w)
            elif not ok:
                self._write_activity("  [dim](failed — no excerpt)[/]")

        self._last_cycle = max(by_cycle)
        try:
            row = self._conn.execute("SELECT MAX(id) FROM run_events").fetchone()
            self._last_run_event_id = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            self._last_run_event_id = 0
        try:
            row = self._conn.execute("SELECT MAX(id) FROM worker_stream").fetchone()
            self._last_stream_id = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            self._last_stream_id = 0
        self._scroll_to_bottom()

    def _write_activity(self, markup: str, *, below_stream: bool = False) -> None:
        """Append a permanent line to the activity scroll area.

        Cycle log lines (rebuild, worker summaries) stay *above* the live stream
        panel. Slash-command feedback, status/help text, and similar messages use
        ``below_stream=True`` so they render under the stream box (just above the
        prompt), matching the CLI transcript order users expect.
        """
        if not markup:
            return
        if below_stream:
            self._write_below_stream_box(markup)
            return
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        line = Static(markup, classes="activity-line")
        scroll.mount(line, before=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

    def _write_below_stream_box(self, markup: str, *, title: str = "") -> Static | None:
        """Append boxed slash-command output under the live stream panel."""
        if not markup:
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        widget = Static(
            events.make_markup_panel(markup, title=title),
            classes="result-box",
            expand=True,
        )
        scroll.mount(widget, after=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return widget

    def _write_below_stream_renderable(
        self, renderable: object, *, classes: str = "result-box",
    ) -> Static:
        """Append a renderable widget under the live stream panel."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        widget = Static(renderable, classes=classes, expand=True)
        scroll.mount(widget, after=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return widget

    def _dismiss_checkpoint_notice(self) -> None:
        w = self._checkpoint_notice_widget
        if w is None:
            return
        self._checkpoint_notice_widget = None
        try:
            w.remove()
        except Exception:
            pass

    def _write_checkpoint_notice(self, markup: str) -> None:
        """Ephemeral undo/redo checkpoint line; removed when the prompt buffer changes."""
        if not markup:
            return
        self._dismiss_checkpoint_notice()
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        notice = Static(markup, classes="activity-line")
        self._checkpoint_notice_widget = notice
        scroll.mount(notice, after=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

    def _write_task(self, task: str) -> Static | None:
        """Append a styled task-prompt block to the activity scroll area."""
        if not task.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        w = Static(task, classes="task-prompt")
        scroll.mount(w, before=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return w

    def _mount_activity_widget(
        self, markup: str, classes: str = "activity-line",
    ) -> Static:
        """Append a line and return the widget so it can be updated later."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        w = Static(markup, classes=classes)
        scroll.mount(w, before=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return w

    def _orchestrator_ts_for_cycle(self, cycle: int) -> float | None:
        """Wall time when the orchestrator logged this cycle (for elapsed on reload)."""
        try:
            row = self._conn.execute(
                "SELECT ts FROM run_events WHERE cycle = ? AND kind = 'orchestrator' "
                "ORDER BY id DESC LIMIT 1",
                (cycle,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return float(row["ts"]) if row else None

    def _write_result_box(self, text: str) -> Static | None:
        """Append a styled result box to the activity scroll area."""
        if not text.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        rendered = events.wrap_result_renderable(events.render_markdown(text))
        w = Static(rendered, classes="result-box", expand=True)
        scroll.mount(w, before=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return w

    def _write_checklist_box(self, text: str) -> Static | None:
        """Append a rendered checklist block to the activity scroll area."""
        if not text.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        rendered = events.wrap_result_renderable(events.render_markdown(text))
        w = Static(rendered, classes="checklist-box", expand=True)
        scroll.mount(w, before=stream)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))
        return w

    def _reset_stream_message_buffers(self) -> None:
        self._stream_tool_markup = ""
        self._stream_text_live = ""
        self._cumulative_stream_text = ""
        self._stream_message_closed = False
        self._stream_last_event_was_tool = False

    def _format_stream_tool_row(self, text: str) -> str:
        t = text.strip()
        if not t:
            return ""
        return f"[cyan]{rich_escape(t)}[/]"

    def _format_stream_text_block(self, text: str) -> str:
        cleaned = text.strip("\n")
        if not cleaned.strip():
            return ""
        rows: list[str] = []
        for line in cleaned.splitlines():
            if line.strip():
                rows.append(f"[dim]{rich_escape(line.rstrip())}[/]")
            else:
                rows.append("")
        return "\n".join(rows)

    def _append_stream_text_delta(self, chunk: str) -> None:
        """Accumulate assistant text as one visible message block."""
        if not chunk:
            return
        if self._stream_message_closed or self._stream_last_event_was_tool:
            self._stream_text_live = ""
            self._stream_message_closed = False
        self._stream_text_live += chunk
        self._cumulative_stream_text += chunk
        self._last_stream_text = self._cumulative_stream_text.strip()
        self._stream_last_event_was_tool = False

    def _replace_stream_message(self, text: str) -> None:
        """Replace the visible message with one complete assistant message."""
        self._stream_text_live = text
        if text:
            if self._cumulative_stream_text and not self._cumulative_stream_text.endswith("\n"):
                self._cumulative_stream_text += "\n"
            self._cumulative_stream_text += text
        self._last_stream_text = self._cumulative_stream_text.strip()
        self._stream_message_closed = True
        self._stream_last_event_was_tool = False

    def _rebuild_stream_panel_from_buffers(self) -> None:
        parts: list[str] = []
        if self._stream_tool_markup:
            parts.append(self._stream_tool_markup)
        message_block = self._format_stream_text_block(self._stream_text_live)
        if message_block:
            if parts:
                parts.append("")
            parts.append(message_block)
        inner = "\n".join(parts)
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(inner))
        status.display = bool(inner.strip())

    def _clear_stream_status(self) -> None:
        self._stream_is_running_placeholder = False
        self._reset_stream_message_buffers()
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(""))
        status.display = False

    def _set_stream_placeholder(self, markup: str) -> None:
        """Single-line animated status (Running… / Orchestrating…), not the message log."""
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(markup))
        status.display = True

    def _fetch_last_stream_text(self, cycle: int) -> str:
        """Retrieve the full text output from worker_stream for a completed cycle.

        Prefers the ``result`` event emitted at the end of a stream-json
        session (contains the complete assistant response).  Falls back to the
        last individual text chunk when no result event is available.
        """
        try:
            rows = list(self._conn.execute(
                "SELECT chunk FROM worker_stream WHERE cycle = ? ORDER BY id DESC LIMIT 200",
                (cycle,),
            ))
        except sqlite3.OperationalError:
            return ""

        for row in rows:
            raw = row["chunk"].strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("type") == "result":
                result_text = data.get("result", "")
                if isinstance(result_text, str) and result_text.strip():
                    return result_text.strip()

        for row in rows:
            parsed = events.parse_stream_event(row["chunk"], full_text=True)
            if parsed and parsed[0] == "text" and parsed[1].strip():
                return parsed[1].strip()
        return ""

    def _scroll_to_bottom(self) -> None:
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

    def _activity_viewport_at_bottom(self) -> bool:
        """True when the activity scroller is pinned to the end (same idea as Rich Log auto-scroll)."""
        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
        except Exception:
            return False
        return bool(
            scroll.is_vertical_scroll_end and not scroll.is_vertical_scrollbar_grabbed
        )

    def _scroll_cycle_header_to_top(self) -> None:
        """Scroll so the current cycle-header divider aligns with the viewport top."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        w = self._cycle_header_widget
        if w is None:
            self._scroll_to_bottom()
            return
        self.call_after_refresh(
            lambda: scroll.scroll_to_widget(w, top=True, animate=False, force=True)
        )

    # --- polling --------------------------------------------------------------

    def _refresh_file_changes(self, *, force: bool = False) -> None:
        """Update the file-changes widget with current git diff stats."""
        if self._file_changes_widget is None:
            return
        now = time.time()
        if not force and now - self._last_file_changes_ts < 0.25:
            return
        self._last_file_changes_ts = now
        raw = memory.read_worker_diff_baseline(project_researcher_root(self.cfg.project_dir))
        if not raw or int(raw.get("cycle", -1)) != self._last_cycle:
            self._file_changes_widget.display = False
            return
        diffs = events.compute_file_diffs(self.cfg.project_dir, baseline=raw)
        if diffs:
            self._file_changes_widget.update(events.format_file_changes(diffs))
            self._file_changes_widget.display = True
        else:
            self._file_changes_widget.display = False

    def _read_immediate_plan_checklist(self) -> str:
        body = helpers.read_text(
            memory.state_dir(self.cfg.researcher_root) / "immediate_plan.md",
            default="",
        )
        return memory.extract_immediate_plan_checklist(body)

    def _update_checklist_widget(self, text: str, *, force: bool = False) -> None:
        if self._checklist_widget is None:
            return
        cleaned = (text or "").strip()
        if not force and cleaned == self._last_checklist_text:
            return
        self._last_checklist_text = cleaned
        if not cleaned:
            self._checklist_widget.display = False
            return
        self._checklist_widget.update(
            events.wrap_result_renderable(events.render_markdown(cleaned))
        )
        self._checklist_widget.display = True

    def _refresh_checklist(self, *, force: bool = False) -> None:
        if self._checklist_widget is None:
            return
        self._update_checklist_widget(self._read_immediate_plan_checklist(), force=force)

    def _read_roadmap_checklist(self) -> str:
        body = helpers.read_text(
            memory.state_dir(self.cfg.researcher_root) / "roadmap.md",
            default="",
        )
        return memory.extract_roadmap_checklist(body)

    def _refresh_header(self) -> None:
        try:
            hdr = events.header_line(self._project_name, self._model, self._conn)
        except sqlite3.OperationalError:
            hdr = "[bold]lab[/]"
        self.query_one("#header", Static).update(hdr)

    def _poll(self) -> None:
        """Periodic poll: update header, run events, stream chunks, and health check."""
        self._check_scheduler_health()
        self._refresh_header()
        self._poll_run_events()
        self._poll_stream()
        self._poll_animated_stream_status()
        self._refresh_running_cycle_header()
        self._refresh_file_changes()
        self._refresh_checklist()
        self._refresh_live_plan()
        self._refresh_live_diff()

    def _poll_animated_stream_status(self) -> None:
        """Animate Orchestrating… or Running {worker}… until stream chunks replace the panel."""
        if self._scheduler is None or not self._scheduler.is_alive():
            self._orchestrating = False
            self._stream_is_running_placeholder = False
            if not self._stream_text_live and not self._stream_tool_markup:
                self._clear_stream_status()
            return
        try:
            if db.get_system_state(self._conn).get("control_mode", "paused") != "active":
                self._orchestrating = False
                self._stream_is_running_placeholder = False
                if not self._stream_text_live and not self._stream_tool_markup:
                    self._clear_stream_status()
                return
        except sqlite3.OperationalError:
            self._orchestrating = False
            self._stream_is_running_placeholder = False
            if not self._stream_text_live and not self._stream_tool_markup:
                self._clear_stream_status()
            return
        if self._orchestrating:
            self._orchestrating_tick += 1
            dots = "." * ((self._orchestrating_tick % 3) + 1)
            self._set_stream_placeholder(f"[dim]Orchestrating{dots}[/]")
            return
        if self._stream_is_running_placeholder and self._worker_start_ts > 0:
            self._running_worker_tick += 1
            dots = "." * ((self._running_worker_tick % 3) + 1)
            self._set_stream_placeholder(f"[dim]Running {self._last_worker}{dots}[/]")

    def _check_scheduler_health(self) -> None:
        """Detect a crashed scheduler subprocess and auto-restart when possible."""
        if self._scheduler is None:
            return
        if self._scheduler.is_alive():
            return
        self._scheduler = None
        self._orchestrating = False
        self._stream_is_running_placeholder = False
        try:
            # Revert sets control_mode to paused via rollback_to_cycle; capture intent first.
            should_auto_restart = (
                db.get_system_state(self._conn).get("control_mode", "paused") == "active"
            )
        except sqlite3.OperationalError:
            should_auto_restart = False
        self._revert_to_checkpoint()
        if not should_auto_restart:
            return
        if self._auto_restarts >= self._MAX_AUTO_RESTARTS:
            self._write_activity(
                "\n  [red]⚠ Agent process crashed repeatedly. Use [bold]/start[/] to restart.[/]",
                below_stream=True,
            )
            db.set_control_mode(self._conn, "paused")
            self._conn.commit()
            return
        self._auto_restarts += 1
        self._write_activity(
            f"\n  [red]⚠ Agent process exited unexpectedly. "
            f"Restarting… ({self._auto_restarts}/{self._MAX_AUTO_RESTARTS})[/]",
            below_stream=True,
        )
        self._restart_scheduler()

    def _restart_scheduler(self) -> None:
        from lab.loop import spawn_scheduler

        researcher_root = project_researcher_root(self.cfg.project_dir)
        db.enqueue_event(self._conn, "resume", None)
        self._conn.commit()
        self._scheduler = spawn_scheduler(
            self.db_path, researcher_root, self.cfg.project_dir, self.cfg,
        )
        self._orchestrating = True

    def _refresh_running_cycle_header(self) -> None:
        """Tick the live duration on the open cycle header while the worker runs."""
        if self._cycle_header_widget is None or not self._worker_start_ts:
            return
        if self._scheduler is None or not self._scheduler.is_alive():
            elapsed = max(0.0, time.time() - self._worker_start_ts)
            self._cycle_header_widget.update(
                events.format_cycle_header(
                    self._last_cycle,
                    self._last_worker,
                    self._last_orchestrator_task,
                    cursor_model=self._cycle_header_cursor_model(),
                    elapsed_sec=elapsed,
                    status="fail",
                )
            )
            self._worker_start_ts = 0.0
            return
        elapsed = events.cycle_header_running_elapsed(self._worker_start_ts)
        self._cycle_header_widget.update(
            events.format_cycle_header(
                self._last_cycle,
                self._last_worker,
                self._last_orchestrator_task,
                cursor_model=self._cycle_header_cursor_model(),
                elapsed_sec=elapsed,
                status="running",
            )
        )

    def _refresh_live_diff(self) -> None:
        """Repaint an active working-tree diff view while files continue changing."""
        from lab import git_checkpoint

        state = self._live_diff_state
        if state is None or state.to_ref is not None:
            return
        raw_diff = git_checkpoint.get_line_diff(self.cfg.project_dir, state.from_ref, None)
        if raw_diff == state.last_raw_diff:
            return
        state.last_raw_diff = raw_diff
        if raw_diff.strip():
            body_markup = events.format_diff_as_markup(raw_diff)
        else:
            body_markup = "  [dim]No changes yet[/]"
        state.widget.update(
            events.make_markup_panel(body_markup, title=f"[dim]diff[/] [dim]{state.title_text}[/]")
        )

    def _refresh_live_plan(self) -> None:
        """Repaint an active roadmap checklist view while the file changes."""
        state = self._live_plan_state
        if state is None:
            return
        text = self._read_roadmap_checklist()
        if text == state.last_text:
            return
        state.last_text = text
        if text.strip():
            body = events.wrap_result_renderable(events.render_markdown(text))
        else:
            body = events.make_markup_panel("  [dim]No roadmap checklist found[/]", title="[dim]plan[/]")
        state.widget.update(body)

    def _poll_run_events(self) -> None:
        """Check for new orchestrator / worker lifecycle events."""
        try:
            rows = list(
                self._conn.execute(
                    "SELECT id, ts, cycle, kind, worker, roadmap_step, task, summary, payload_json "
                    "FROM run_events WHERE id > ? ORDER BY id ASC LIMIT 50",
                    (self._last_run_event_id,),
                )
            )
        except sqlite3.OperationalError:
            return

        for row in rows:
            self._last_run_event_id = row["id"]
            kind = row["kind"]
            cycle = row["cycle"]
            worker = row["worker"]
            task = row["task"] or ""

            if kind == "orchestrator":
                self._orchestrating = False
                new_cycle = cycle != self._last_cycle or worker != self._last_worker
                if new_cycle:
                    self._clear_diff_widgets()
                    if self._cycle_header_widget is not None:
                        ps = self._worker_start_ts
                        pe = max(0.0, time.time() - ps) if ps else 0.0
                        self._cycle_header_widget.update(
                            events.format_cycle_header(
                                self._last_cycle,
                                self._last_worker,
                                self._last_orchestrator_task,
                                cursor_model=self._cycle_header_cursor_model(),
                                elapsed_sec=pe,
                                status="fail",
                            )
                        )
                        self._cycle_header_widget = None
                    self._last_cycle = cycle
                    self._last_worker = worker
                    self._worker_start_ts = float(row["ts"])
                    self._last_orchestrator_task = task
                    self._last_stream_text = ""
                    self._reset_stream_message_buffers()
                    self._current_cycle_widgets = []
                    elapsed0 = events.cycle_header_running_elapsed(self._worker_start_ts)
                    self._cycle_header_widget = self._mount_activity_widget(
                        events.format_cycle_header(
                            cycle,
                            worker,
                            task,
                            cursor_model=self._cycle_header_cursor_model(),
                            elapsed_sec=elapsed0,
                            status="running",
                        ),
                        classes="activity-line cycle-header",
                    )
                    self._current_cycle_widgets.append(self._cycle_header_widget)
                    task_w = self._write_task(task)
                    if task_w is not None:
                        self._current_cycle_widgets.append(task_w)
                    self._file_changes_widget = self._mount_activity_widget(
                        "", classes="activity-line file-changes",
                    )
                    self._file_changes_widget.display = False
                    self._current_cycle_widgets.append(self._file_changes_widget)
                    self._last_file_changes_ts = 0.0
                    self._checklist_widget = self._mount_activity_widget(
                        "", classes="activity-line checklist-box",
                    )
                    self._checklist_widget.display = False
                    self._current_cycle_widgets.append(self._checklist_widget)
                    self._last_checklist_text = ""
                    self._refresh_checklist(force=True)
                self._stream_is_running_placeholder = True
                self._running_worker_tick = 0
                wdots = "." * ((self._running_worker_tick % 3) + 1)
                follow = self._activity_viewport_at_bottom()
                self._set_stream_placeholder(f"[dim]Running {worker}{wdots}[/]")
                if new_cycle and self._cycle_header_widget is not None:
                    self._scroll_cycle_header_to_top()
                elif follow:
                    self._scroll_to_bottom()
            elif kind == "worker":
                self._clear_redo_stack()
                start_ts = self._worker_start_ts
                if cycle != self._last_cycle or start_ts <= 0:
                    start_ts = self._orchestrator_ts_for_cycle(cycle) or 0.0
                end_ts = float(row["ts"])
                elapsed = max(0.0, end_ts - start_ts) if start_ts else 0.0
                payload: dict = {}
                try:
                    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                ok = payload.get("worker_ok", True)
                error_excerpt = ""
                if not ok:
                    error_excerpt = events.extract_error_excerpt(
                        row["summary"] or "",
                        str(payload.get("error", "") or ""),
                    )
                stream_excerpt = events.extract_result_excerpt(
                    self._fetch_last_stream_text(cycle)
                )
                if not stream_excerpt:
                    stream_excerpt = events.extract_result_excerpt(self._last_stream_text)
                summary_excerpt = events.extract_result_excerpt(row["summary"] or "")
                excerpt = stream_excerpt or (summary_excerpt if ok else "")
                checklist = str(payload.get("immediate_plan_checklist", "") or "").strip()
                if not checklist:
                    checklist = self._read_immediate_plan_checklist()
                self._clear_stream_status()
                self._refresh_file_changes(force=True)
                self._file_changes_widget = None
                self._update_checklist_widget(checklist, force=True)
                self._checklist_widget = None
                if self._cycle_header_widget is not None and cycle == self._last_cycle:
                    self._cycle_header_widget.update(
                        events.format_cycle_header(
                            cycle,
                            worker,
                            task or self._last_orchestrator_task,
                            cursor_model=self._cycle_header_cursor_model(),
                            elapsed_sec=elapsed,
                            status="ok" if ok else "fail",
                        )
                    )
                    self._cycle_header_widget = None
                self._worker_start_ts = 0.0
                if excerpt:
                    result_w = self._write_result_box(excerpt)
                    if result_w is not None:
                        self._current_cycle_widgets.append(result_w)
                elif not ok:
                    if error_excerpt:
                        self._write_activity(f"  [red]Error:[/] {rich_escape(error_excerpt)}")
                    else:
                        self._write_activity("  [dim](failed — no excerpt)[/]")
                self._last_stream_text = ""
                try:
                    sid_row = self._conn.execute(
                        "SELECT MAX(id) FROM worker_stream WHERE cycle = ?", (cycle,)
                    ).fetchone()
                    if sid_row and sid_row[0] is not None:
                        self._last_stream_id = max(self._last_stream_id, int(sid_row[0]))
                except sqlite3.OperationalError:
                    pass
                # Slash-command / status lines under the stream belong to the open
                # cycle; clear when the worker finishes (including graceful pause with
                # no immediate follow-up orchestrator event).
                self._clear_below_stream_feedback()
                if self._scheduler and self._scheduler.is_alive():
                    self._orchestrating = True

    def _poll_stream(self) -> None:
        """Append stream events to the live panel.

        Tool activity is shown as a short trail above a single active assistant
        message block. Message boundaries rotate the text buffer so we do not
        accumulate the whole transcript in the live panel.
        """
        try:
            rows = db.stream_chunks_since(self._conn, self._last_stream_id)
        except sqlite3.OperationalError:
            return
        had_tool = False
        for row in rows:
            self._last_stream_id = row["id"]
            parsed = events.parse_stream_event(row["chunk"], full_text=True)
            if parsed is None:
                continue
            event_type, text = parsed
            if event_type == "tool" and text.strip():
                had_tool = True
                self._stream_is_running_placeholder = False
                tool_row = self._format_stream_tool_row(text)
                if tool_row:
                    self._stream_tool_markup = tool_row
                self._stream_last_event_was_tool = True
                follow = self._activity_viewport_at_bottom()
                self._rebuild_stream_panel_from_buffers()
                if follow:
                    self._scroll_to_bottom()
            elif event_type == "text" and text.strip():
                self._stream_is_running_placeholder = False
                self._append_stream_text_delta(text)
                follow = self._activity_viewport_at_bottom()
                self._rebuild_stream_panel_from_buffers()
                if follow:
                    self._scroll_to_bottom()
            elif event_type == "message" and text.strip():
                self._stream_is_running_placeholder = False
                self._replace_stream_message(text)
                follow = self._activity_viewport_at_bottom()
                self._rebuild_stream_panel_from_buffers()
                if follow:
                    self._scroll_to_bottom()
            elif event_type == "boundary":
                self._stream_message_closed = bool(self._stream_text_live.strip())
                self._stream_last_event_was_tool = False
        if had_tool:
            self._last_file_changes_ts = 0.0

    # --- input handling -------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        self._dismiss_checkpoint_notice()

    def on_prompt_submitted(self, event: PromptSubmitted) -> None:
        ta = event.sender
        text = ta.text
        ta.text = ""
        ta._adjust_height()
        self._submit_prompt_text(text)

    def _submit_prompt_text(self, raw: str) -> None:
        text = raw.strip()
        if not text:
            return

        self._remove_welcome_intro()
        self._clear_below_stream_feedback()

        lines = text.splitlines()
        first = lines[0].strip()
        instruction_text = ""

        # Support the common flow where the user writes an instruction, then puts
        # `/start` on the final line in the same submission.
        if not first.startswith("/") and len(lines) > 1:
            last_idx = -1
            for idx in range(len(lines) - 1, -1, -1):
                if lines[idx].strip():
                    last_idx = idx
                    break
            if last_idx > 0:
                last = lines[last_idx].strip()
                leading = "\n".join(lines[:last_idx]).strip()
                if last.startswith("/") and leading:
                    instruction_text = leading
                    first = last
                    tail = ""
                else:
                    tail = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            else:
                tail = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        else:
            tail = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if instruction_text:
            db.enqueue_event(self._conn, "instruction", instruction_text)
            preview = instruction_text if len(instruction_text) <= 200 else instruction_text[:200] + "…"
            self._write_activity(f"  [green]❯[/] {rich_escape(preview)}", below_stream=True)

        if not first.startswith("/"):
            db.enqueue_event(self._conn, "instruction", text)
            self._conn.commit()
            preview = text if len(text) <= 200 else text[:200] + "…"
            self._write_activity(f"  [green]❯[/] {rich_escape(preview)}", below_stream=True)
            return

        parts = first.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "instruction":
            body = (rest + "\n" + tail if tail else rest).strip()
            if not body:
                self._write_below_stream_box("  [red]/instruction[/] requires text")
                return
            db.enqueue_event(self._conn, "instruction", body)
            self._conn.commit()
            preview = body if len(body) <= 200 else body[:200] + "…"
            self._write_below_stream_box(f"  [green]❯[/] {rich_escape(preview)}")
            return

        if tail:
            self._write_below_stream_box(
                "  [dim]Note: only the first line is used as a slash command; "
                "omit the leading / for multi-line instructions.[/]"
            )

        if cmd == "diff":
            self._cmd_diff(rest)
            return

        if cmd == "plan":
            self._cmd_plan()
            return

        handler = {
            "start": self._cmd_start,
            "pause": self._cmd_pause,
            "stop": self._cmd_stop,
            "exit": self._cmd_exit,
            "help": self._cmd_help,
            "reset": self._cmd_reset,
            "undo": self._cmd_undo,
            "redo": self._cmd_redo,
        }.get(cmd)

        if handler:
            handler()
        else:
            self._write_below_stream_box(f"  [red]Unknown command:[/] /{cmd}")

    def _cmd_diff(self, rest: str) -> None:
        """Show line-by-line diff for the requested cycle range.

        /diff           – changes in the current (in-progress) cycle
        /diff N         – changes introduced by cycle N
        /diff N M       – changes from the start of cycle N through the end of cycle M
        """
        from lab import git_checkpoint

        parts = rest.strip().split()
        try:
            if len(parts) == 0:
                start_cycle: int | None = None
                end_cycle: int | None = None
            elif len(parts) == 1:
                start_cycle = int(parts[0])
                end_cycle = start_cycle
            elif len(parts) == 2:
                start_cycle = int(parts[0])
                end_cycle = int(parts[1])
            else:
                self._write_below_stream_box("  [red]Usage:[/] /diff [cycle] [end_cycle]")
                return
        except ValueError:
            self._write_below_stream_box("  [red]Usage:[/] /diff [cycle] [end_cycle]")
            return

        if (start_cycle is not None and start_cycle < 1) or (
            end_cycle is not None and end_cycle < 1
        ):
            self._write_below_stream_box("  [red]Cycle number must be >= 1[/]")
            return

        if start_cycle is not None and end_cycle is not None and end_cycle < start_cycle:
            self._write_below_stream_box("  [red]End cycle must be >= start cycle[/]")
            return

        project_dir = self.cfg.project_dir
        current_cycle = int(db.get_system_state(self._conn).get("cycle_count", 0))

        # Resolve "no args" → current in-progress cycle
        if start_cycle is None:
            start_cycle = max(current_cycle, 1)
            end_cycle = start_cycle
            to_ref: str | None = None  # compare against working tree
        else:
            assert end_cycle is not None
            # Resolve to_ref (end of end_cycle)
            to_sha = git_checkpoint.get_checkpoint_sha_for_cycle(project_dir, end_cycle)
            if to_sha is not None:
                to_ref = to_sha
            elif end_cycle == current_cycle:
                to_ref = None  # in-progress – use working tree
            else:
                self._write_below_stream_box(f"  [red]No checkpoint found for cycle {end_cycle}[/]")
                return

        # Resolve from_ref (state just before start_cycle)
        from_sha = git_checkpoint.get_checkpoint_sha_for_cycle(project_dir, start_cycle - 1)
        from_ref: str = from_sha if from_sha is not None else "HEAD"

        # Build the diff
        raw_diff = git_checkpoint.get_line_diff(project_dir, from_ref, to_ref)
        assert end_cycle is not None

        is_live = to_ref is None
        if not raw_diff.strip() and not is_live:
            if start_cycle == end_cycle:
                label = f"cycle {start_cycle}" + (" (in progress)" if to_ref is None else "")
            else:
                label = f"cycles {start_cycle}–{end_cycle}"
            self._write_below_stream_box(f"  [dim]No changes for {label}[/]")
            return

        markup = events.format_diff_as_markup(raw_diff)
        self._clear_diff_widgets()

        if start_cycle == end_cycle:
            title_text = f"cycle {start_cycle}" + (" · in progress" if to_ref is None else "")
        else:
            title_text = f"cycles {start_cycle}–{end_cycle}"

        body_markup = markup if raw_diff.strip() else "  [dim]No changes yet[/]"
        widget = self._write_below_stream_box(
            body_markup,
            title=f"[dim]diff[/] [dim]{title_text}[/]",
        )
        if widget is None:
            return
        self._diff_widgets = [widget]
        self._live_diff_state = _LiveDiffState(
            from_ref=from_ref,
            to_ref=to_ref,
            title_text=title_text,
            widget=widget,
            last_raw_diff=raw_diff,
        )

    def _cmd_undo(self) -> None:
        """Drop in-flight or last finished worker changes; restart only if the agent was running."""
        was_running = bool(self._scheduler and self._scheduler.is_alive())
        snap = self._capture_redo_snapshot()
        if snap is None:
            self._write_activity(
                "  [red]/undo failed:[/] could not snapshot current state for /redo.",
                below_stream=True,
            )
            return
        self._kill_scheduler()
        self._revert_to_checkpoint(undo_last_completed_worker=True)
        self._redo_stack.append(snap)
        self._auto_restarts = 0
        if was_running:
            self._restart_scheduler()

    def _cmd_redo(self) -> None:
        """Restore the most recently undone checkpoint and reapply local changes."""
        if not self._redo_stack:
            self._write_activity("  [dim]Nothing to redo.[/]", below_stream=True)
            return
        was_running = bool(self._scheduler and self._scheduler.is_alive())
        self._kill_scheduler()
        snap = self._redo_stack.pop()
        if not self._restore_redo_snapshot(snap):
            self._write_activity(
                "  [red]/redo failed:[/] could not restore the saved snapshot.",
                below_stream=True,
            )
            self._drop_redo_snapshot(snap)
            return
        self._auto_restarts = 0
        if was_running and not (self._scheduler and self._scheduler.is_alive()):
            self._restart_scheduler()

    def _cmd_start(self) -> None:
        db.set_graceful_pause_pending(self._conn, False)
        mode = db.get_system_state(self._conn).get("control_mode", "active")
        scheduler_alive = bool(self._scheduler and self._scheduler.is_alive())

        if mode != "active" or not scheduler_alive:
            db.set_control_mode(self._conn, "active")
            db.enqueue_event(self._conn, "resume", None)
        self._conn.commit()

        if scheduler_alive:
            if mode == "paused":
                self._orchestrating = True
            else:
                self._write_activity("  [dim]Agent is already running.[/]", below_stream=True)
            return

        self._auto_restarts = 0
        self._restart_scheduler()

    def _cmd_stop(self) -> None:
        """Kill the scheduler immediately and revert any in-flight cycle."""
        db.set_graceful_pause_pending(self._conn, False)
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self._clear_stream_status()
        self._last_stream_text = ""

    def _cmd_pause(self) -> None:
        """Pause after the current worker finishes (no kill, no revert)."""
        alive = bool(self._scheduler and self._scheduler.is_alive())
        mode = db.get_system_state(self._conn).get("control_mode", "paused")
        if not alive:
            db.set_graceful_pause_pending(self._conn, False)
            if mode != "active":
                self._write_activity("  [dim]Already paused.[/]", below_stream=True)
            else:
                db.set_control_mode(self._conn, "paused")
                self._write_activity("  [yellow]Paused.[/]", below_stream=True)
            self._conn.commit()
            return
        db.set_graceful_pause_pending(self._conn, True)
        self._conn.commit()
        self._write_activity(
            "  [yellow]Pausing after the current worker finishes…[/]",
            below_stream=True,
        )

    def _cmd_exit(self) -> None:
        self._write_activity("  [dim]Shutting down...[/]", below_stream=True)
        db.set_graceful_pause_pending(self._conn, False)
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self.set_timer(0.3, self.exit)

    def _cmd_plan(self) -> None:
        self._live_plan_state = None
        checklist = self._read_roadmap_checklist()
        if checklist.strip():
            widget = self._write_below_stream_renderable(
                events.wrap_result_renderable(events.render_markdown(checklist)),
                classes="checklist-box",
            )
        else:
            widget = self._write_below_stream_box(
                "  [dim]No roadmap checklist found[/]",
                title="[dim]plan[/]",
            )
        if widget is None:
            return
        self._live_plan_state = _LivePlanState(widget=widget, last_text=checklist)

    def _cmd_help(self) -> None:
        self._write_below_stream_box(
            "  [bold]Commands[/]\n"
            "  [bold]/start[/]        Start the background agent\n"
            "  [bold]/pause[/]        Pause after the current worker finishes\n"
            "  [bold]/stop[/]         Stop immediately (kill worker, revert in-flight cycle)\n"
            "  [bold]/exit[/]         Stop agent and quit\n"
            "  [bold]/plan[/]         Show the live roadmap checklist\n"
            "  [bold]/diff[/]         Line-by-line diff. If args are given: [bold]/diff n[/] = diff in cycle n; [bold]/diff n m[/] = diff from cycle n to end of cycle m\n"
            "  [bold]/reset[/]        Clear DB and runtime memory; keep research_idea.md + preferences.md; project code unchanged\n"
            "  [bold]/undo[/]         Revert since last worker; restarts orchestrator only if agent was running\n"
            "  [bold]/redo[/]         Restore the last undone checkpoint and replay local edits on top\n"
            "  [bold]/help[/]         This message\n"
            "\n  Plain text is queued as an instruction.\n"
            "  [dim]Enter[/] sends · [dim]Shift+Enter[/] for newline · navigate lines with arrows\n"
        )

    def _cmd_reset(self) -> None:
        self._kill_scheduler()
        self._conn.close()
        try:
            reset_project_preserving_research_idea(self.cfg.project_dir)
        except Exception as e:
            self._conn = db.connect_db(self.db_path)
            self._write_activity(f"  [red]Reset failed:[/] {e}", below_stream=True)
            return
        self._conn = db.connect_db(self.db_path)
        self._last_stream_id = 0
        self._last_run_event_id = 0
        self._last_cycle = 0
        self._last_worker = ""
        self._worker_start_ts = 0.0
        self._last_orchestrator_task = ""
        self._cycle_header_widget = None
        self._file_changes_widget = None
        self._last_file_changes_ts = 0.0
        self._last_stream_text = ""
        self._current_cycle_widgets = []
        self._auto_restarts = 0
        self._orchestrating_tick = 0
        self._running_worker_tick = 0
        self._clear_activity_log()
        self._clear_stream_status()
        self._refresh_header()
        self._clear_redo_stack()
        self._write_activity(
            "  [green]Reset complete.[/] Kept [bold]research_idea.md[/] and [bold]preferences.md[/]. "
            "Cleared DB, other Tier A files, episodes, extended, branches, skills, experiments.",
            below_stream=True,
        )
        self._write_welcome_lines()

    # --- lifecycle ------------------------------------------------------------

    def _redo_snapshot_root(self) -> Path:
        return project_researcher_root(self.cfg.project_dir) / "redo"

    def _clear_redo_stack(self) -> None:
        for snap in self._redo_stack:
            self._drop_redo_snapshot(snap)
        self._redo_stack.clear()

    def _capture_redo_snapshot(self) -> _RedoSnapshot | None:
        """Save enough state to reverse the next /undo via /redo."""
        from lab import git_checkpoint

        token = f"{time.time_ns()}"
        tree_ref = f"refs/lab/redo/{token}"
        tree_sha = git_checkpoint.snapshot_ref(
            self.cfg.project_dir,
            tree_ref,
            f"redo snapshot {token}",
        )
        if tree_sha is None:
            return None

        checkpoint_sha = git_checkpoint.get_ref_sha(
            self.cfg.project_dir, f"refs/heads/{git_checkpoint.CHECKPOINT_BRANCH}"
        )
        snapshot_dir = self._redo_snapshot_root() / token
        runtime_copy = snapshot_dir / "runtime"
        runtime_copy.parent.mkdir(parents=True, exist_ok=True)
        try:
            if runtime_copy.exists():
                shutil.rmtree(runtime_copy)
            live_root = project_researcher_root(self.cfg.project_dir)
            if live_root.is_dir():
                runtime_copy.mkdir(parents=True, exist_ok=True)
                for child in live_root.iterdir():
                    if child.name == "redo":
                        continue
                    dst = runtime_copy / child.name
                    if child.is_dir():
                        shutil.copytree(child, dst)
                    else:
                        shutil.copy2(child, dst)
            else:
                runtime_copy.mkdir(parents=True, exist_ok=True)
        except OSError:
            git_checkpoint.delete_ref(self.cfg.project_dir, tree_ref)
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            return None

        try:
            db_copy = sqlite3.connect(str(snapshot_dir / "runtime.db"))
            try:
                self._conn.backup(db_copy)
                db_copy.commit()
            finally:
                db_copy.close()
        except sqlite3.Error:
            git_checkpoint.delete_ref(self.cfg.project_dir, tree_ref)
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            return None

        return _RedoSnapshot(
            token=token,
            tree_ref=tree_ref,
            checkpoint_sha=checkpoint_sha,
            snapshot_dir=snapshot_dir,
            cycle=self._last_cycle,
        )

    def _drop_redo_snapshot(self, snap: _RedoSnapshot) -> None:
        from lab import git_checkpoint

        git_checkpoint.delete_ref(self.cfg.project_dir, snap.tree_ref)
        shutil.rmtree(snap.snapshot_dir, ignore_errors=True)

    def _restore_runtime_snapshot(self, snap: _RedoSnapshot) -> bool:
        runtime_copy = snap.snapshot_dir / "runtime"
        if not runtime_copy.is_dir():
            return False
        live_root = project_researcher_root(self.cfg.project_dir)
        self._conn.close()
        try:
            live_root.mkdir(parents=True, exist_ok=True)
            for child in list(live_root.iterdir()):
                if child.name == "redo":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            for child in runtime_copy.iterdir():
                dst = live_root / child.name
                if child.is_dir():
                    shutil.copytree(child, dst)
                else:
                    shutil.copy2(child, dst)
        except OSError:
            self._conn = db.connect_db(self.db_path)
            return False

        try:
            for dst in (
                self.db_path,
                Path(str(self.db_path) + "-wal"),
                Path(str(self.db_path) + "-shm"),
            ):
                try:
                    dst.unlink()
                except FileNotFoundError:
                    pass
            shutil.copy2(snap.snapshot_dir / "runtime.db", self.db_path)
        except OSError:
            self._conn = db.connect_db(self.db_path)
            return False

        self._conn = db.connect_db(self.db_path)
        return True

    def _start_implementer_merge_fix(self, conflicts: list[str]) -> None:
        task = (
            "Resolve merge conflicts created while replaying local changes after /redo. "
            "Keep the restored checkpoint intent, preserve compatible local edits, remove conflict markers, "
            "and leave the working tree conflict-free. "
            f"Conflicted paths: {', '.join(conflicts[:20])}"
        )
        self._conn.execute("BEGIN IMMEDIATE")
        db.set_forced_run(self._conn, "implementer", task)
        db.set_control_mode(self._conn, "active")
        db.enqueue_event(self._conn, "resume", None)
        self._conn.commit()
        self._write_activity(
            "  [yellow]/redo hit merge conflicts; starting implementer to resolve them.[/]",
            below_stream=True,
        )
        self._restart_scheduler()

    def _restore_redo_snapshot(self, snap: _RedoSnapshot) -> bool:
        from lab import git_checkpoint

        current_treeish = (
            f"refs/heads/{git_checkpoint.CHECKPOINT_BRANCH}"
            if git_checkpoint.has_checkpoint(self.cfg.project_dir)
            else "HEAD"
        )
        current_base_sha = git_checkpoint.get_ref_sha(self.cfg.project_dir, current_treeish)
        overlay_ref: str | None = None
        overlay_commit: str | None = None
        if current_base_sha and git_checkpoint.has_worktree_changes_since(
            self.cfg.project_dir, current_treeish
        ):
            overlay_ref = f"refs/lab/redo-overlay/{snap.token}"
            overlay_commit = git_checkpoint.snapshot_ref(
                self.cfg.project_dir,
                overlay_ref,
                f"redo overlay {snap.token}",
                parent=current_base_sha,
            )
            if overlay_commit is None:
                if overlay_ref is not None:
                    git_checkpoint.delete_ref(self.cfg.project_dir, overlay_ref)
                return False

        try:
            if not git_checkpoint.restore_working_tree(self.cfg.project_dir, snap.tree_ref):
                return False
            if snap.checkpoint_sha:
                if not git_checkpoint.update_ref(
                    self.cfg.project_dir,
                    f"refs/heads/{git_checkpoint.CHECKPOINT_BRANCH}",
                    snap.checkpoint_sha,
                ):
                    return False
            else:
                git_checkpoint.delete_ref(
                    self.cfg.project_dir, f"refs/heads/{git_checkpoint.CHECKPOINT_BRANCH}"
                )

            if not self._restore_runtime_snapshot(snap):
                return False
            self._rebuild_activity_from_db()
            self._refresh_header()
            self._clear_stream_status()

            if overlay_commit:
                if not git_checkpoint.cherry_pick_no_commit(self.cfg.project_dir, overlay_commit):
                    conflicts = git_checkpoint.list_unmerged_paths(self.cfg.project_dir)
                    if conflicts:
                        self._start_implementer_merge_fix(conflicts)
                    else:
                        self._write_activity(
                            "  [red]/redo failed:[/] could not replay local changes.",
                            below_stream=True,
                        )
                        return False
            self._write_checkpoint_notice(
                f"  [yellow]Redid checkpoint (cycle {db.get_system_state(self._conn).get('cycle_count', 0)}).[/]"
            )
            return True
        finally:
            if overlay_ref is not None:
                git_checkpoint.delete_ref(self.cfg.project_dir, overlay_ref)
            self._drop_redo_snapshot(snap)

    def _kill_scheduler(self) -> None:
        """Immediately kill the scheduler and all child worker processes."""
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.kill_group()
        self._scheduler = None
        self._orchestrating = False
        self._stream_is_running_placeholder = False

    def _cleanup_orphaned_cycles(self) -> None:
        """Delete DB rows for cycles that have an orchestrator event but no worker event."""
        try:
            orphaned = [
                row[0]
                for row in self._conn.execute(
                    "SELECT DISTINCT cycle FROM run_events WHERE kind = 'orchestrator' "
                    "AND cycle NOT IN (SELECT DISTINCT cycle FROM run_events WHERE kind = 'worker')"
                ).fetchall()
            ]
            for c in orphaned:
                self._conn.execute("DELETE FROM run_events WHERE cycle = ?", (c,))
                self._conn.execute("DELETE FROM worker_stream WHERE cycle = ?", (c,))
            if orphaned:
                self._conn.commit()
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _cleanup_incomplete_episodes(researcher_root: Path, last_completed: int) -> None:
        """Delete episode directories for cycles beyond *last_completed*."""
        from lab.memory import episodes_dir
        import re as _re
        ep_root = episodes_dir(researcher_root)
        if not ep_root.is_dir():
            return
        for child in list(ep_root.iterdir()):
            if not child.is_dir():
                continue
            m = _re.match(r"cycle_(\d+)", child.name)
            if m and int(m.group(1)) > last_completed:
                import shutil
                shutil.rmtree(child, ignore_errors=True)

    @staticmethod
    def _reset_context_summary(researcher_root: Path) -> None:
        """Reset context_summary.md to its default when no cycles have completed."""
        from lab import helpers
        from lab.memory import state_dir, _default_tier_a_content

        p = state_dir(researcher_root) / "context_summary.md"
        helpers.ensure_dir(p.parent)
        p.write_text(_default_tier_a_content("context_summary.md"), encoding="utf-8")

    def _revert_to_checkpoint(
        self,
        *,
        undo_last_completed_worker: bool = False,
        emit_activity_message: bool = True,
    ) -> None:
        """Restore the working tree to the last completed-cycle checkpoint and
        roll back the DB to match, removing any UI traces of the interrupted cycle.

        When *undo_last_completed_worker* is true and the latest cycle has
        already finished (orchestrator is not ahead of the last worker row),
        the working tree is restored to the newest checkpoint whose recorded
        cycle is ≤ (max completed worker cycle − 1), using the DB so repeated
        /undo works even when the oldest checkpoint is a git root (no ``~1``).
        Otherwise the tip checkpoint is used (same as pause/crash recovery:
        drops an in-flight worker only).
        """
        from lab import git_checkpoint

        researcher_root = project_researcher_root(self.cfg.project_dir)

        # Remove in-progress cycle widgets unconditionally -- the scheduler is
        # dead at this point so the cycle cannot complete.
        for w in self._current_cycle_widgets:
            try:
                w.remove()
            except Exception:
                pass
        self._current_cycle_widgets.clear()
        self._cycle_header_widget = None
        self._file_changes_widget = None
        self._last_file_changes_ts = 0.0
        self._worker_start_ts = 0.0
        self._last_worker = ""
        self._last_orchestrator_task = ""
        self._last_stream_text = ""

        try:
            row_mx = self._conn.execute("SELECT MAX(cycle) FROM run_events").fetchone()
            max_event_cycle_before = int(row_mx[0]) if row_mx and row_mx[0] is not None else 0
        except Exception:
            max_event_cycle_before = 0

        # Attempt git-level revert to the last completed-cycle checkpoint.
        reverted = False
        tip_ahead = False
        last_completed = 0
        target_cycle = 0
        try:
            tip_ahead = db.orchestrator_ahead_of_worker(self._conn)
            row = self._conn.execute(
                "SELECT MAX(cycle) FROM run_events WHERE kind = 'worker'",
            ).fetchone()
            last_completed = int(row[0]) if row and row[0] is not None else 0
            target_cycle = (
                max(0, last_completed - 1)
                if undo_last_completed_worker and not tip_ahead
                else last_completed
            )
        except Exception:
            tip_ahead = False
            last_completed = 0
            target_cycle = 0

        if git_checkpoint.has_checkpoint(self.cfg.project_dir):
            cycle: int | None = None
            if undo_last_completed_worker and not tip_ahead:
                if target_cycle == 0:
                    if git_checkpoint.restore_pre_checkpoint_state(self.cfg.project_dir):
                        cycle = 0
                else:
                    cycle = git_checkpoint.restore_checkpoint_at_or_before_cycle(
                        self.cfg.project_dir, target_cycle,
                    )
            else:
                cycle = git_checkpoint.revert_to_checkpoint(self.cfg.project_dir)
            if cycle is not None:
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    db.rollback_to_cycle(self._conn, cycle)
                    self._conn.commit()
                    reverted = True
                    self._cleanup_incomplete_episodes(researcher_root, cycle)
                    if cycle == 0:
                        self._reset_context_summary(researcher_root)
                except Exception:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass

        # Purge any remaining orphaned cycles the checkpoint didn't cover.
        self._cleanup_orphaned_cycles()

        # Even without git, ensure system_state is consistent with completed
        # cycles and clean up filesystem artifacts from interrupted runs.
        if not reverted:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                db.rollback_to_cycle(self._conn, target_cycle)
                self._conn.commit()
            except Exception:
                try:
                    self._conn.rollback()
                except Exception:
                    pass

            self._cleanup_incomplete_episodes(researcher_root, target_cycle)
            if target_cycle == 0:
                self._reset_context_summary(researcher_root)

        # Resync event/stream IDs with the DB after deletions.
        try:
            row = self._conn.execute("SELECT MAX(id) FROM run_events").fetchone()
            self._last_run_event_id = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            pass
        try:
            row = self._conn.execute("SELECT MAX(id) FROM worker_stream").fetchone()
            self._last_stream_id = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            pass
        try:
            row = self._conn.execute("SELECT MAX(cycle) FROM run_events").fetchone()
            self._last_cycle = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            pass

        try:
            self._clear_stream_status()
        except Exception:
            pass
        try:
            self._rebuild_activity_from_db()
            self._refresh_header()
        except Exception:
            pass

        if emit_activity_message and max_event_cycle_before > self._last_cycle:
            self._write_checkpoint_notice(
                f"  [yellow]Reverted to checkpoint (cycle {self._last_cycle}).[/]"
            )

    def action_quit(self) -> None:
        db.set_graceful_pause_pending(self._conn, False)
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self.exit()


def run_console(db_path: Path, cfg: RunConfig) -> None:
    """Entry point for the TUI."""
    app = ResearchConsole(db_path, cfg)
    app.run()
