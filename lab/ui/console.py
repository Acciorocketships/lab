"""Textual TUI: Claude Code-inspired layout with streaming output."""

from __future__ import annotations

import json
import os
import signal
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
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

_FORCED_AGENT_KILL_WAIT_TIMEOUT = 0.2
_FORCED_AGENT_DB_TIMEOUT = 0.2
_FORCED_SCHEDULER_KILL_WAIT_TIMEOUT = 0.1
_FAST_POLL_INTERVAL_SEC = 0.1
_ANIMATION_POLL_INTERVAL_SEC = 0.2
_SLOW_POLL_INTERVAL_SEC = 0.75


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


@dataclass
class _PendingPromptEditState:
    target: str
    path: Path
    heading: str


@dataclass
class _AgentSectionState:
    agent_id: int
    prompt: str
    status: str
    started_ts: float
    finished_ts: float | None
    header_widget: Static
    task_widget: Static | None
    stream_widget: Static | None
    result_widget: Static | None = None
    cumulative_stream_text: str = ""
    stream_tool_markup: str = ""
    stream_text_live: str = ""
    stream_message_closed: bool = False
    stream_last_event_was_tool: bool = False
    stream_placeholder_tick: int = 0

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def widgets(self) -> list[Static]:
        out = [self.header_widget]
        if self.task_widget is not None:
            out.append(self.task_widget)
        if self.stream_widget is not None:
            out.append(self.stream_widget)
        if self.result_widget is not None:
            out.append(self.result_widget)
        return out


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
    height: auto;
    max-height: 14;
    min-height: 3;
    align: left top;
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
    min-height: 1;
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


class ActivityScroll(VerticalScroll):
    """Activity log scroller that notifies the app when the user nears the top."""

    _wants_bottom: bool = False
    _prepend_baseline: tuple[int, float] | None = None

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        if self._wants_bottom:
            mx = float(self.max_scroll_y)
            if mx > 0 and new_value < mx:
                self.scroll_target_y = mx
                self.scroll_y = mx
                return
        elif self._prepend_baseline is not None:
            base_height, base_y = self._prepend_baseline
            delta = self.virtual_size.height - base_height
            if delta > 0:
                target_y = base_y + delta
                if abs(new_value - target_y) > 1:
                    self.scroll_target_y = target_y
                    self.scroll_y = target_y
                    self._prepend_baseline = (self.virtual_size.height, target_y)
                    return
        super().watch_scroll_y(old_value, new_value)
        handler = getattr(self.app, "_on_activity_scroll_y", None)
        if handler is not None:
            handler(new_value)

    def watch_virtual_size(self, old_size, new_size) -> None:
        if old_size.height == new_size.height:
            return
        if self._wants_bottom:
            target = float(self.max_scroll_y)
            self.scroll_target_y = target
            self.scroll_y = target
        elif self._prepend_baseline is not None:
            base_height, base_y = self._prepend_baseline
            delta = new_size.height - base_height
            if delta > 0:
                target_y = base_y + delta
                self.scroll_target_y = target_y
                self.scroll_y = target_y
                self._prepend_baseline = (new_size.height, target_y)


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
        self._cycle_stream_widget: Static | None = None
        self._last_checklist_text = ""
        self._last_file_changes_ts: float = 0.0
        self._orchestrating = False
        self._orchestrating_tick = 0
        self._stream_is_running_placeholder = False
        self._running_worker_tick = 0
        self._scheduler_start_pending = False
        # Active while a memory_compactor stream has chunks but no matching
        # completion event yet. Tracked reactively from _poll_stream / _poll_run_events
        # because the equivalent SQL NOT EXISTS query grew to multi-second latency
        # on the main event loop, stalling the animation and keyboard input.
        self._memory_compactor_active = False
        self._memory_compactor_active_seeded = False
        self._welcome_widgets: list[Static] = []
        self._redo_stack: list[_RedoSnapshot] = []
        self._checkpoint_notice_widget: Static | None = None
        self._diff_widgets: list[Static] = []
        self._live_diff_state: _LiveDiffState | None = None
        self._live_plan_state: _LivePlanState | None = None
        self._pending_prompt_edit: _PendingPromptEditState | None = None
        self._agent_processes: dict[int, SchedulerProcessHandle] = {}
        self._agent_sections: dict[int, _AgentSectionState] = {}
        self._last_agent_stream_id = 0
        # Lazy history: prefix timeline items (oldest first) not yet mounted; anchor = insert-before target.
        self._history_lazy_prefix: list[tuple[float, str, object]] | None = None
        self._history_lazy_anchor: Static | None = None
        self._history_lazy_loading = False
        self._history_lazy_ready = False
        self._history_suppress_scroll = False
        self._history_deferred_agent_ids: set[int] = set()

    def _cycle_header_cursor_model(self) -> str | None:
        """Cursor CLI ``--model`` value for cycle headers (only when workers use Cursor)."""
        if self.cfg.default_worker_backend != "cursor":
            return None
        m = (self.cfg.cursor_agent_model or "").strip()
        return m or None

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with ActivityScroll(id="activity-scroll"):
            yield Static("", id="stream-text")
        with Container(id="prompt-box"):
            yield Static("❯", id="prompt-indicator")
            yield PromptTextArea(
                "",
                id="prompt",
                placeholder=(
                    "Type here · Enter to send · Shift+Enter or Ctrl+Enter for new line"
                ),
                compact=True,
                show_line_numbers=False,
            )

    def on_mount(self) -> None:
        self._cleanup_orphaned_cycles()
        self._sync_rebuild_ids_from_db()
        self._seed_memory_compactor_active()
        self._refresh_header()
        stream = self.query_one("#stream-text", Static)
        stream.display = False
        scroll = self.query_one("#activity-scroll", ActivityScroll)
        scroll.mount(
            Static("  [dim]Loading session…[/]", classes="activity-line", id="session-loading"),
            before=stream,
        )
        self.set_timer(0.01, self._complete_initial_activity_rebuild)
        self.set_interval(_FAST_POLL_INTERVAL_SEC, self._poll_fast)
        self.set_interval(_ANIMATION_POLL_INTERVAL_SEC, self._poll_animation)
        self.set_interval(_SLOW_POLL_INTERVAL_SEC, self._poll_slow)

    def _complete_initial_activity_rebuild(self) -> None:
        """Run after first paint so the terminal shows a loading line instead of blocking on_mount.

        ``_rebuild_activity_from_db(load_full_history=False)`` keeps older cycles on disk
        until the user scrolls toward the top of the activity log.
        """
        try:
            self._rebuild_activity_from_db(load_full_history=False)
        finally:
            try:
                self.query_one("#prompt", PromptTextArea).focus()
            except Exception:
                pass

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
        self._agent_sections = {}
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

    # Number of newest timeline entries to mount before yielding to the event loop.
    _REBUILD_FIRST_BATCH = 3

    # Lazy history (``load_full_history=False`` on first paint): last N graph cycles,
    # then load older chunks when the user scrolls toward the top.
    _ACTIVITY_INITIAL_CYCLES = 5
    _ACTIVITY_SCROLL_BATCH_CYCLES = 5
    _ACTIVITY_SCROLL_TOP_THRESHOLD = 4.0

    def _rebuild_activity_from_db(self, *, load_full_history: bool = True) -> None:
        """Re-render completed cycles from DB so undo/redo immediately refresh the UI.

        With ``load_full_history=True`` (undo/redo), the full timeline is rebuilt using
        the existing timer-chained batches.  With ``load_full_history=False`` (initial
        session paint), only the last ``_ACTIVITY_INITIAL_CYCLES`` worker cycles are
        mounted; older entries load when the activity scroller nears the top.
        """
        self._cancel_pending_rebuild_chain()
        self._history_lazy_prefix = None
        self._history_deferred_agent_ids = set()
        self._history_lazy_anchor = None
        self._history_lazy_loading = False
        self._history_lazy_ready = False
        self._history_suppress_scroll = False
        self._clear_activity_log()
        self._current_cycle_widgets = []
        self._cycle_header_widget = None
        self._file_changes_widget = None
        self._checklist_widget = None
        self._cycle_stream_widget = None
        self._last_checklist_text = ""
        self._last_file_changes_ts = 0.0
        self._worker_start_ts = 0.0
        self._last_worker = ""
        self._last_orchestrator_task = ""
        self._agent_sections = {}

        if not load_full_history:
            self._rebuild_activity_lazy_initial()
            return

        timeline, by_cycle, stream_excerpt_by_cycle, active_agents = self._load_rebuild_data()

        if timeline is None:
            self._write_welcome_lines()
            self._scroll_to_bottom()
            return

        # Mount active agents first (always shown, lightweight).
        self._mount_active_agents(active_agents or [])

        # Mount the newest few timeline entries synchronously so the first paint
        # shows recent activity at the bottom of the scroll.  Mount in
        # chronological order (oldest of batch first) so that each successive
        # ``before=stream`` insert puts the newer item closest to stream, yielding
        # correct chronological order with newest at the bottom.
        reversed_tl = list(reversed(timeline))
        first_batch = reversed_tl[: self._REBUILD_FIRST_BATCH]
        remaining = reversed_tl[self._REBUILD_FIRST_BATCH :]

        self._mount_before = None  # insert before stream (default)
        for item in reversed(first_batch):  # chronological: oldest of batch first
            self._mount_timeline_item(item, by_cycle, stream_excerpt_by_cycle)

        self._sync_rebuild_ids_from_db()
        self._scroll_to_bottom()

        # Schedule remaining (older) items in batches via timers so Textual can
        # paint between each batch.  They insert *above* the first-batch items
        # by setting ``_mount_before`` to the topmost widget from the first batch.
        if remaining:
            first_batch_top = self._find_topmost_activity_widget()
            self._schedule_rebuild_chain(
                remaining, by_cycle, stream_excerpt_by_cycle,
                anchor=first_batch_top,
            )

    @staticmethod
    def _by_cycle_from_run_event_rows(rows: list[sqlite3.Row]) -> dict[int, dict[str, sqlite3.Row]]:
        by_cycle: dict[int, dict[str, sqlite3.Row]] = {}
        for row in rows:
            bucket = by_cycle.setdefault(int(row["cycle"]), {})
            bucket[str(row["kind"])] = row
        return by_cycle

    def _normalize_agent_runs(self, agent_rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        normalized: list[sqlite3.Row] = []
        for row in agent_rows:
            if str(row["status"] or "") == "running":
                pid = int(row["pid"]) if row["pid"] is not None else None
                if not self._pid_is_alive(pid):
                    fixed = self._finalize_stale_agent_run(
                        int(row["id"]),
                        "agent was left marked running, but no live process exists",
                    )
                    if fixed is not None:
                        normalized.append(fixed)
                        continue
            normalized.append(row)
        return normalized

    @staticmethod
    def _split_timeline_tail_last_n_cycles(
        timeline: list[tuple[float, str, object]], n_cycles: int,
    ) -> tuple[list[tuple[float, str, object]], list[tuple[float, str, object]]]:
        """Oldest-first *prefix*, chronological *tail* with the last ``n_cycles`` worker cycles."""
        if not timeline:
            return [], []
        if n_cycles <= 0:
            return [], list(timeline)
        collected_rev: list[tuple[float, str, object]] = []
        seen = 0
        for i in range(len(timeline) - 1, -1, -1):
            item = timeline[i]
            collected_rev.append(item)
            if item[1] == "cycle":
                seen += 1
                if seen >= n_cycles:
                    tail = list(reversed(collected_rev))
                    prefix = timeline[:i]
                    return prefix, tail
        return [], list(reversed(collected_rev))

    @staticmethod
    def _newest_prefix_chunk_n_cycles(
        prefix: list[tuple[float, str, object]], n_cycles: int,
    ) -> tuple[list[tuple[float, str, object]], list[tuple[float, str, object]]]:
        """Take the newest ``n_cycles`` worker cycles from the *end* of *prefix*.

        Returns ``(remaining_prefix, chunk)`` where *chunk* is chronological
        (oldest first) and contains the items closest to the already-visible tail.
        """
        if not prefix or n_cycles <= 0:
            return prefix, []
        seen = 0
        for i in range(len(prefix) - 1, -1, -1):
            if prefix[i][1] == "cycle":
                seen += 1
                if seen >= n_cycles:
                    return prefix[:i], prefix[i:]
        return [], list(prefix)

    def _run_events_full_rows_for_cycles(self, cycles: set[int]) -> list[sqlite3.Row]:
        if not cycles:
            return []
        ordered = tuple(sorted(cycles))
        placeholders = ",".join("?" * len(ordered))
        sql = (
            "SELECT cycle, ts, kind, worker, task, summary, payload_json FROM run_events "
            f"WHERE cycle IN ({placeholders}) ORDER BY cycle ASC, id ASC"
        )
        try:
            return list(self._conn.execute(sql, ordered))
        except sqlite3.OperationalError:
            return []

    def _rebuild_activity_lazy_initial(self) -> None:
        """Mount recent history only; leave older timeline rows in ``_history_lazy_prefix``."""
        try:
            index_rows = list(
                self._conn.execute(
                    "SELECT cycle, ts, kind FROM run_events WHERE kind IN ('orchestrator', 'worker') "
                    "ORDER BY cycle ASC, id ASC"
                )
            )
        except sqlite3.OperationalError:
            index_rows = []
        try:
            raw_agents = db.list_agent_runs(self._conn)
        except sqlite3.OperationalError:
            raw_agents = []
        agent_rows = self._normalize_agent_runs(raw_agents)

        by_index = self._by_cycle_from_run_event_rows(index_rows)
        cycle_sections: list[tuple[float, int]] = []
        for cycle in sorted(by_index):
            worker_row = by_index[cycle].get("worker")
            if worker_row is None:
                continue
            orch_row = by_index[cycle].get("orchestrator")
            sort_ts = float(orch_row["ts"]) if orch_row else float(worker_row["ts"])
            cycle_sections.append((sort_ts, cycle))

        completed_agents = [
            row for row in agent_rows
            if str(row["status"] or "") != "running" and row["finished_at"] is not None
        ]
        active_agents = [row for row in agent_rows if str(row["status"] or "") == "running"]

        if not cycle_sections and not completed_agents and not active_agents:
            self._write_welcome_lines()
            self._scroll_to_bottom()
            self._sync_rebuild_ids_from_db()
            return

        timeline: list[tuple[float, str, object]] = []
        for sort_ts, cycle in cycle_sections:
            timeline.append((sort_ts, "cycle", cycle))
        for row in completed_agents:
            timeline.append((float(row["finished_at"]), "agent", row))
        timeline.sort(key=lambda item: (item[0], 0 if item[1] == "cycle" else 1))

        prefix, tail = self._split_timeline_tail_last_n_cycles(timeline, self._ACTIVITY_INITIAL_CYCLES)

        cycles_in_tail = {int(item[2]) for item in tail if item[1] == "cycle"}
        heavy_rows = self._run_events_full_rows_for_cycles(cycles_in_tail)
        by_cycle = self._by_cycle_from_run_event_rows(heavy_rows)
        excerpts = self._bulk_fetch_last_stream_text_by_cycles(sorted(cycles_in_tail))

        self._mount_active_agents(active_agents)
        self._mount_before = None
        widgets_before = len(self._current_cycle_widgets)
        for item in tail:
            self._mount_timeline_item(item, by_cycle, excerpts)
        first_tail_widget = (
            self._current_cycle_widgets[widgets_before]
            if len(self._current_cycle_widgets) > widgets_before
            else None
        )

        self._sync_rebuild_ids_from_db()
        self._scroll_to_bottom()

        self._history_lazy_prefix = prefix if prefix else None
        self._history_deferred_agent_ids = {
            int(item[2]["id"]) for item in prefix if item[1] == "agent"
        } if prefix else set()
        self._history_lazy_anchor = first_tail_widget if prefix and first_tail_widget else None
        if self._history_lazy_prefix:
            self.set_timer(1.0, self._arm_lazy_history)

    def _arm_lazy_history(self) -> None:
        if self._history_lazy_prefix:
            self._history_suppress_scroll = True
            self.call_after_refresh(self._arm_lazy_history_final)

    def _arm_lazy_history_final(self) -> None:
        if self._history_lazy_prefix:
            self._history_lazy_ready = True
        self._history_suppress_scroll = False

    def _on_activity_scroll_y(self, new_value: float) -> None:
        if not self._history_lazy_ready or self._history_suppress_scroll:
            return
        if not self._history_lazy_prefix or self._history_lazy_loading:
            return
        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
        except Exception:
            return
        if scroll.max_scroll_y <= 0:
            return
        if new_value > self._ACTIVITY_SCROLL_TOP_THRESHOLD:
            return
        self._history_lazy_loading = True
        try:
            self._load_older_history_scroll_chunk()
        finally:
            self._history_lazy_loading = False

    def _load_older_history_scroll_chunk(self) -> None:
        pref = self._history_lazy_prefix
        if not pref:
            return
        anchor = self._history_lazy_anchor
        if anchor is not None and getattr(anchor, "parent", None) is None:
            self._history_lazy_prefix = None
            return
        rest, chunk = self._newest_prefix_chunk_n_cycles(pref, self._ACTIVITY_SCROLL_BATCH_CYCLES)
        if not chunk:
            self._history_lazy_prefix = rest or None
            return

        cycles = {int(item[2]) for item in chunk if item[1] == "cycle"}
        heavy_rows = self._run_events_full_rows_for_cycles(cycles)
        by_cycle = self._by_cycle_from_run_event_rows(heavy_rows)
        excerpts = self._bulk_fetch_last_stream_text_by_cycles(sorted(cycles))

        try:
            scroll = self.query_one("#activity-scroll", ActivityScroll)
        except Exception:
            scroll = None

        if scroll is not None:
            self._history_suppress_scroll = True
            scroll._wants_bottom = False
            scroll._prepend_baseline = (scroll.virtual_size.height, float(scroll.scroll_y))

        self._mount_before = self._history_lazy_anchor
        widgets_before = len(self._current_cycle_widgets)
        for item in chunk:
            self._mount_timeline_item(item, by_cycle, excerpts)
        self._mount_before = None

        new_anchor = (
            self._current_cycle_widgets[widgets_before]
            if len(self._current_cycle_widgets) > widgets_before
            else self._history_lazy_anchor
        )
        self._history_lazy_anchor = new_anchor
        self._history_lazy_prefix = rest if rest else None
        for item in chunk:
            if item[1] == "agent":
                self._history_deferred_agent_ids.discard(int(item[2]["id"]))
        if not self._history_lazy_prefix:
            self._history_deferred_agent_ids.clear()

        if scroll is not None:
            try:
                self.set_timer(2.0, self._clear_prepend_baseline)
            except Exception:
                pass

    def _clear_prepend_baseline(self) -> None:
        try:
            scroll = self.query_one("#activity-scroll", ActivityScroll)
            scroll._prepend_baseline = None
        except Exception:
            pass
        self._history_suppress_scroll = False

    def _load_rebuild_data(
        self,
    ) -> tuple[
        list[tuple[float, str, object]] | None,
        dict[int, dict[str, sqlite3.Row]],
        dict[int, str],
        list[sqlite3.Row],
    ]:
        """Query DB once and return (timeline, by_cycle, stream_excerpts, active_agents).

        Returns ``(None, {}, {}, [])`` when there is nothing to show (welcome screen).
        """
        try:
            rows = list(
                self._conn.execute(
                    "SELECT cycle, ts, kind, worker, task, summary, payload_json "
                    "FROM run_events ORDER BY cycle ASC, id ASC"
                )
            )
        except sqlite3.OperationalError:
            rows = []
        try:
            agent_rows = db.list_agent_runs(self._conn)
        except sqlite3.OperationalError:
            agent_rows = []
        agent_rows = self._normalize_agent_runs(agent_rows)

        by_cycle = self._by_cycle_from_run_event_rows(rows)

        cycle_sections: list[tuple[float, int]] = []
        for cycle in sorted(by_cycle):
            worker_row = by_cycle[cycle].get("worker")
            if worker_row is None:
                continue
            orch_row = by_cycle[cycle].get("orchestrator")
            sort_ts = float(orch_row["ts"]) if orch_row else float(worker_row["ts"])
            cycle_sections.append((sort_ts, cycle))

        completed_agents = [
            row for row in agent_rows if str(row["status"] or "") != "running" and row["finished_at"] is not None
        ]
        active_agents = [row for row in agent_rows if str(row["status"] or "") == "running"]

        if not cycle_sections and not completed_agents and not active_agents:
            return None, {}, {}, []

        timeline: list[tuple[float, str, object]] = []
        for sort_ts, cycle in cycle_sections:
            timeline.append((sort_ts, "cycle", cycle))
        for row in completed_agents:
            timeline.append((float(row["finished_at"]), "agent", row))
        timeline.sort(key=lambda item: (item[0], 0 if item[1] == "cycle" else 1))

        cycle_numbers = [int(item[2]) for item in timeline if item[1] == "cycle"]
        stream_excerpt_by_cycle = self._bulk_fetch_last_stream_text_by_cycles(cycle_numbers)

        return timeline, by_cycle, stream_excerpt_by_cycle, active_agents

    def _mount_timeline_item(
        self,
        item: tuple[float, str, object],
        by_cycle: dict[int, dict[str, sqlite3.Row]],
        stream_excerpt_by_cycle: dict[int, str],
    ) -> None:
        """Mount a single timeline entry (cycle or agent) into the activity scroll."""
        _, kind, payload_item = item
        if kind == "agent":
            self._create_agent_section(payload_item)  # type: ignore[arg-type]
            return
        cycle = int(payload_item)
        worker_row = by_cycle[cycle].get("worker")
        if worker_row is None:
            return
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

        excerpt = events.extract_result_excerpt(stream_excerpt_by_cycle.get(cycle, ""))
        if not excerpt:
            excerpt = events.extract_result_excerpt(worker_row["summary"] or "")
        if excerpt:
            result_w = self._write_result_box(
                excerpt,
                title=f"[dim]{worker}[/] [dim]cycle {cycle}[/]",
            )
            if result_w is not None:
                self._current_cycle_widgets.append(result_w)
        elif not ok:
            self._write_activity("  [dim](failed — no excerpt)[/]")

    def _mount_active_agents(self, active_agents: list[sqlite3.Row]) -> None:
        """Mount and replay stream for currently-running agent sections."""
        for row in sorted(active_agents, key=lambda item: (float(item["started_at"]), int(item["id"]))):
            agent = self._create_agent_section(row)
            try:
                chunks = list(
                    self._conn.execute(
                        "SELECT chunk FROM agent_stream WHERE agent_id = ? ORDER BY id ASC",
                        (agent.agent_id,),
                    )
                )
            except sqlite3.OperationalError:
                chunks = []
            for chunk_row in chunks:
                self._agent_apply_stream_chunk(agent, str(chunk_row["chunk"] or ""))
        self._reposition_active_agent_sections()
        if active_agents:
            latest_agent_id = max(int(row["id"]) for row in active_agents)
            latest_agent = self._agent_sections.get(latest_agent_id)
            if latest_agent is not None:
                self._scroll_widget_to_top(latest_agent.header_widget)

    def _sync_rebuild_ids_from_db(self) -> None:
        """After a rebuild, resync the high-water-mark IDs with the DB."""
        try:
            row = self._conn.execute("SELECT MAX(cycle) FROM run_events").fetchone()
            self._last_cycle = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            self._last_cycle = 0
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
        try:
            row = self._conn.execute("SELECT MAX(id) FROM agent_stream").fetchone()
            self._last_agent_stream_id = int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            self._last_agent_stream_id = 0

    # --- chunked rebuild chain -----------------------------------------------

    _REBUILD_BATCH_SIZE = 5

    def _find_topmost_activity_widget(self) -> Static | None:
        """Return the first non-stream child of ``#activity-scroll``, or *None*."""
        try:
            scroll = self.query_one("#activity-scroll", VerticalScroll)
            stream = self.query_one("#stream-text", Static)
            for child in scroll.children:
                if child is not stream:
                    return child  # type: ignore[return-value]
        except Exception:
            pass
        return None

    def _cancel_pending_rebuild_chain(self) -> None:
        """Cancel any in-flight background rebuild timer chain."""
        self._mount_before = None
        timer = getattr(self, "_rebuild_chain_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        self._rebuild_chain_timer = None
        self._rebuild_chain_items = None

    def _schedule_rebuild_chain(
        self,
        items: list[tuple[float, str, object]],
        by_cycle: dict[int, dict[str, sqlite3.Row]],
        stream_excerpt_by_cycle: dict[int, str],
        *,
        anchor: Static | None = None,
    ) -> None:
        """Start a timer chain that mounts *items* (newest→oldest) in batches.

        *items* are still ordered newest-first.  Each batch is reversed internally
        so that within a batch the oldest item is mounted first (``before=anchor``),
        producing correct chronological order.

        *anchor* is the widget that older items should be inserted before (i.e.
        the topmost widget from the first batch).  When *None*, falls back to
        ``#stream-text``.

        Falls back to synchronous mounting when no asyncio event loop is running
        (unit tests, or rebuilds triggered from non-async contexts like ``/undo``).
        """
        import asyncio

        self._mount_before = anchor

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            for item in reversed(items):  # chronological: oldest first
                self._mount_timeline_item(item, by_cycle, stream_excerpt_by_cycle)
            self._mount_before = None
            return

        self._rebuild_chain_items = items
        self._rebuild_chain_by_cycle = by_cycle
        self._rebuild_chain_excerpts = stream_excerpt_by_cycle
        self._rebuild_chain_offset = 0
        self._rebuild_chain_timer = self.set_timer(0, self._rebuild_chain_tick)

    def _rebuild_chain_tick(self) -> None:
        """Mount one batch of older timeline items, then schedule the next tick.

        Items arrive newest-first; each batch is reversed so the oldest item in
        the batch mounts first (``before=anchor``), preserving chronological
        order in the DOM.
        """
        items = getattr(self, "_rebuild_chain_items", None)
        if items is None:
            return
        by_cycle = self._rebuild_chain_by_cycle
        excerpts = self._rebuild_chain_excerpts
        offset = self._rebuild_chain_offset
        batch = items[offset : offset + self._REBUILD_BATCH_SIZE]
        if not batch:
            self._cancel_pending_rebuild_chain()
            return
        for item in reversed(batch):  # chronological within the batch
            self._mount_timeline_item(item, by_cycle, excerpts)
        self._rebuild_chain_offset = offset + len(batch)
        if self._rebuild_chain_offset < len(items):
            self._rebuild_chain_timer = self.set_timer(0, self._rebuild_chain_tick)
        else:
            self._cancel_pending_rebuild_chain()

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
        self._scroll_to_bottom()
        return widget

    def _write_below_stream_renderable(
        self, renderable: object, *, classes: str = "result-box",
    ) -> Static:
        """Append a renderable widget under the live stream panel."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        widget = Static(renderable, classes=classes, expand=True)
        scroll.mount(widget, after=stream)
        self._scroll_to_bottom()
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

    # When set, ``_mount_activity_widget`` and friends insert *before* this
    # widget instead of before ``#stream-text``.  Used by the chunked rebuild
    # chain to prepend older history above the already-visible newest batch.
    _mount_before: Static | None = None

    def _mount_anchor(self) -> Static:
        """Return the widget that new activity lines should be inserted before."""
        if self._mount_before is not None:
            return self._mount_before
        return self.query_one("#stream-text", Static)

    def _write_task(self, task: str) -> Static | None:
        """Append a styled task-prompt block to the activity scroll area."""
        if not task.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        anchor = self._mount_anchor()
        w = Static(task, classes="task-prompt")
        scroll.mount(w, before=anchor)
        return w

    def _mount_activity_widget(
        self, markup: str, classes: str = "activity-line",
    ) -> Static:
        """Append a line and return the widget so it can be updated later."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        anchor = self._mount_anchor()
        w = Static(markup, classes=classes)
        scroll.mount(w, before=anchor)
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

    def _write_result_box(self, text: str, *, title: str = "") -> Static | None:
        """Append a styled result box to the activity scroll area."""
        if not text.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        anchor = self._mount_anchor()
        rendered = events.wrap_result_renderable(events.render_markdown(text), title=title)
        w = Static(rendered, classes="result-box", expand=True)
        scroll.mount(w, before=anchor)
        return w

    def _write_checklist_box(self, text: str) -> Static | None:
        """Append a rendered checklist block to the activity scroll area."""
        if not text.strip():
            return None
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        anchor = self._mount_anchor()
        rendered = events.wrap_result_renderable(events.render_markdown(text))
        w = Static(rendered, classes="checklist-box", expand=True)
        scroll.mount(w, before=anchor)
        return w

    def _render_agent_stream_panel(self, agent: _AgentSectionState) -> None:
        if agent.stream_widget is None:
            return
        parts: list[str] = []
        if agent.stream_tool_markup:
            parts.append(agent.stream_tool_markup)
        message_block = self._format_stream_text_block(agent.stream_text_live)
        if message_block:
            if parts:
                parts.append("")
            parts.append(message_block)
        inner = "\n".join(parts)
        agent.stream_widget.update(events.make_stream_panel(inner))
        agent.stream_widget.display = bool(inner.strip())

    def _render_cycle_stream_panel(self, markup: str) -> None:
        widget = self._cycle_stream_widget
        if widget is not None:
            status = self.query_one("#stream-text", Static)
            status.update(events.make_stream_panel(""))
            status.display = False
            widget.update(events.make_stream_panel(markup))
            widget.display = bool(markup.strip())
            return
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(markup))
        status.display = bool(markup.strip())

    def _agent_append_stream_text_delta(self, agent: _AgentSectionState, chunk: str) -> None:
        if not chunk:
            return
        if agent.stream_message_closed or agent.stream_last_event_was_tool:
            agent.stream_text_live = ""
            agent.stream_message_closed = False
        agent.stream_text_live += chunk
        agent.cumulative_stream_text += chunk
        agent.stream_last_event_was_tool = False

    def _agent_replace_stream_message(self, agent: _AgentSectionState, text: str) -> None:
        agent.stream_text_live = text
        if text:
            if agent.cumulative_stream_text and not agent.cumulative_stream_text.endswith("\n"):
                agent.cumulative_stream_text += "\n"
            agent.cumulative_stream_text += text
        agent.stream_message_closed = True
        agent.stream_last_event_was_tool = False

    def _agent_apply_stream_chunk(self, agent: _AgentSectionState, chunk: str) -> None:
        parsed = events.parse_stream_event(chunk, full_text=True)
        if parsed is None:
            return
        event_type, text = parsed
        if event_type == "tool" and text.strip():
            tool_row = self._format_stream_tool_row(text)
            if tool_row:
                agent.stream_tool_markup = tool_row
            agent.stream_last_event_was_tool = True
        elif event_type == "text" and text.strip():
            self._agent_append_stream_text_delta(agent, text)
        elif event_type == "message" and text.strip():
            self._agent_replace_stream_message(agent, text)
        elif event_type == "boundary":
            agent.stream_message_closed = bool(agent.stream_text_live.strip())
            agent.stream_last_event_was_tool = False
        self._render_agent_stream_panel(agent)

    def _agent_status_for(self, status: str) -> events.CycleHeaderStatus:
        return "running" if status == "running" else ("ok" if status == "completed" else "fail")

    def _agent_elapsed(self, agent: _AgentSectionState) -> float:
        end = time.time() if agent.is_running else float(agent.finished_ts or agent.started_ts)
        return max(0.0, end - agent.started_ts)

    def _create_agent_section(self, row: sqlite3.Row) -> _AgentSectionState:
        agent_id = int(row["id"])
        prompt = str(row["prompt"] or "")
        status = str(row["status"] or "running")
        started_ts = float(row["started_at"] or row["created_at"] or time.time())
        finished_ts = float(row["finished_at"]) if row["finished_at"] is not None else None
        header = self._mount_activity_widget(
            events.format_cycle_header(
                agent_id,
                "agent",
                prompt,
                label="agent",
                elapsed_sec=max(0.0, (finished_ts or time.time()) - started_ts),
                status=self._agent_status_for(status),
            ),
            classes="activity-line cycle-header",
        )
        task_w = self._write_task(prompt)
        agent = _AgentSectionState(
            agent_id=agent_id,
            prompt=prompt,
            status=status,
            started_ts=started_ts,
            finished_ts=finished_ts,
            header_widget=header,
            task_widget=task_w,
            stream_widget=None,
        )
        if status == "running":
            agent.stream_widget = self._mount_activity_widget("", classes="activity-line result-box")
            dots = "." * ((agent.stream_placeholder_tick % 3) + 1)
            agent.stream_widget.update(
                events.make_stream_panel(f"[dim]Running agent{dots}[/]")
            )
            agent.stream_widget.display = True
        else:
            excerpt = events.extract_result_excerpt(str(row["summary"] or ""))
            if not excerpt and status == "failed":
                excerpt = events.extract_error_excerpt(
                    str(row["summary"] or ""),
                    str(row["error"] or ""),
                )
            if excerpt:
                agent.result_widget = self._write_result_box(
                    excerpt,
                    title=f"[dim]agent {agent_id}[/]",
                )
        self._agent_sections[agent_id] = agent
        return agent

    def _move_widgets_before_stream(self, widgets: list[Static]) -> None:
        if not widgets:
            return
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        mounted = [widget for widget in widgets if getattr(widget, "parent", None) is scroll]
        if not mounted:
            return
        for widget in mounted:
            try:
                scroll.move_child(widget, before=stream)
            except Exception:
                pass

    def _reposition_active_agent_sections(self) -> None:
        # Keep the current cycle's widgets together even after the worker has
        # finished, because the header widget is cleared on completion before the
        # final result box is appended.
        if self._current_cycle_widgets:
            self._move_widgets_before_stream(self._current_cycle_widgets)
        running = sorted(
            (agent for agent in self._agent_sections.values() if agent.is_running),
            key=lambda agent: (agent.started_ts, agent.agent_id),
        )
        for agent in running:
            self._move_widgets_before_stream(agent.widgets)

    def _has_active_agent_sections(self) -> bool:
        return any(agent.is_running for agent in self._agent_sections.values())

    def _pid_is_alive(self, pid: int | None) -> bool:
        if pid is None or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _finalize_stale_agent_run(self, agent_id: int, reason: str) -> sqlite3.Row | None:
        db.finish_agent_run(
            self._conn,
            agent_id,
            status="failed",
            summary=reason,
            error=reason,
        )
        memory.refresh_system_tier_from_db(
            self.cfg.researcher_root,
            self.cfg.project_dir,
            self.db_path,
            limit=self.cfg.system_recent_run_events_limit,
        )
        return db.get_agent_run(self._conn, agent_id)

    def _finalize_agent_section(self, row: sqlite3.Row) -> None:
        agent_id = int(row["id"])
        agent = self._agent_sections.get(agent_id)
        if agent is None or not agent.is_running:
            return
        agent.status = str(row["status"] or "completed")
        agent.finished_ts = float(row["finished_at"]) if row["finished_at"] is not None else time.time()
        agent.header_widget.update(
            events.format_cycle_header(
                agent_id,
                "agent",
                agent.prompt,
                label="agent",
                elapsed_sec=self._agent_elapsed(agent),
                status=self._agent_status_for(agent.status),
            )
        )
        excerpt = events.extract_result_excerpt(str(row["summary"] or ""))
        if not excerpt and agent.status == "failed":
            excerpt = events.extract_error_excerpt(str(row["summary"] or ""), str(row["error"] or ""))
        if excerpt:
            rendered = events.wrap_result_renderable(
                events.render_markdown(excerpt),
                title=f"[dim]agent {agent_id}[/]",
            )
            if agent.stream_widget is not None:
                agent.stream_widget.update(rendered)
                agent.stream_widget.display = True
                agent.result_widget = agent.stream_widget
                agent.stream_widget = None
            else:
                agent.result_widget = self._write_result_box(
                    excerpt,
                    title=f"[dim]agent {agent_id}[/]",
                )
        elif agent.stream_widget is not None:
            agent.stream_widget.display = False
            agent.result_widget = agent.stream_widget
            agent.stream_widget = None

    def _kill_agent_processes(self) -> None:
        killed_any = False
        for agent_id, proc in list(self._agent_processes.items()):
            try:
                proc.kill_group(wait_timeout=_FORCED_AGENT_KILL_WAIT_TIMEOUT)
                killed_any = True
            except Exception:
                pass
            try:
                row = db.get_agent_run(self._conn, agent_id)
                if row is not None and str(row["status"] or "") == "running":
                    db.finish_agent_run(
                        self._conn,
                        agent_id,
                        status="failed",
                        summary="agent stopped when lab shut down or reverted",
                        error="agent stopped when lab shut down or reverted",
                    )
                    killed_any = True
            except Exception:
                pass
        self._agent_processes = {}
        if killed_any:
            try:
                memory.refresh_system_tier_from_db(
                    self.cfg.researcher_root,
                    self.cfg.project_dir,
                    self.db_path,
                    limit=self.cfg.system_recent_run_events_limit,
                    db_timeout=_FORCED_AGENT_DB_TIMEOUT,
                )
            except Exception:
                pass

    def _kill_single_agent_process(self, agent_id: int) -> bool:
        """Stop one async ``/agent`` by id; return True if a live process was signaled."""
        row = db.get_agent_run(self._conn, agent_id)
        if row is None:
            return False

        signaled = False
        proc = self._agent_processes.pop(agent_id, None)
        if proc is not None:
            try:
                proc.kill_group(wait_timeout=_FORCED_AGENT_KILL_WAIT_TIMEOUT)
                signaled = True
            except Exception:
                pass
        else:
            pid = int(row["pid"]) if row["pid"] is not None else None
            if pid and pid > 0:
                try:
                    os.killpg(pid, signal.SIGKILL)
                    signaled = True
                except Exception:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        signaled = True
                    except Exception:
                        pass

        if str(row["status"] or "") == "running":
            db.finish_agent_run(
                self._conn,
                agent_id,
                status="failed",
                summary=f"agent {agent_id} stopped by /stop agent {agent_id}",
                error=f"agent {agent_id} stopped by /stop agent {agent_id}",
            )
            memory.refresh_system_tier_from_db(
                self.cfg.researcher_root,
                self.cfg.project_dir,
                self.db_path,
                limit=self.cfg.system_recent_run_events_limit,
                db_timeout=_FORCED_AGENT_DB_TIMEOUT,
            )
            updated = db.get_agent_run(self._conn, agent_id)
            if updated is not None:
                self._finalize_agent_section(updated)
        return signaled

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
        self._render_cycle_stream_panel(inner)

    def _clear_stream_status(self) -> None:
        self._stream_is_running_placeholder = False
        self._reset_stream_message_buffers()
        self._render_cycle_stream_panel("")

    def _set_stream_placeholder(self, markup: str) -> None:
        """Single-line animated status (Running… / Orchestrating… / Compressing Memory…), not the message log."""
        self._render_cycle_stream_panel(markup)

    @staticmethod
    def _chunks_newest_first_to_stream_text(chunks: Sequence[str]) -> str:
        """Decode stream-json chunks (newest first, at most 200) into assistant text."""
        for raw in chunks:
            s = (raw or "").strip()
            if not s:
                continue
            try:
                data = json.loads(s)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("type") == "result":
                result_text = data.get("result", "")
                if isinstance(result_text, str) and result_text.strip():
                    return result_text.strip()
        for raw in chunks:
            parsed = events.parse_stream_event(raw, full_text=True)
            if parsed and parsed[0] == "text" and parsed[1].strip():
                return parsed[1].strip()
        return ""

    def _bulk_fetch_last_stream_text_by_cycles(self, cycles: list[int]) -> dict[int, str]:
        """One pass over ``worker_stream`` for all *cycles* (avoids N per-cycle queries on rebuild)."""
        unique = sorted({int(c) for c in cycles})
        if not unique:
            return {}
        out: dict[int, str] = {}
        chunk_size = 400
        for off in range(0, len(unique), chunk_size):
            batch = unique[off : off + chunk_size]
            ph = ",".join("?" * len(batch))
            sql = (
                "WITH ranked AS ("
                " SELECT cycle, chunk,"
                " ROW_NUMBER() OVER (PARTITION BY cycle ORDER BY id DESC) AS rn"
                " FROM worker_stream WHERE cycle IN ("
                + ph
                + ") AND worker != 'memory_compactor' ) SELECT cycle, chunk FROM ranked WHERE rn <= 200 "
                "ORDER BY cycle ASC, rn ASC"
            )
            try:
                cur = self._conn.execute(sql, batch)
            except sqlite3.OperationalError:
                for c in batch:
                    out[c] = self._fetch_last_stream_text(c)
                continue
            current: int | None = None
            buf: list[str] = []
            for row in cur:
                c = int(row["cycle"])
                ch = str(row["chunk"] or "")
                if current is None:
                    current = c
                    buf = [ch]
                    continue
                if c == current:
                    buf.append(ch)
                else:
                    out[current] = self._chunks_newest_first_to_stream_text(buf)
                    current = c
                    buf = [ch]
            if current is not None:
                out[current] = self._chunks_newest_first_to_stream_text(buf)
        return out

    def _fetch_last_stream_text(self, cycle: int) -> str:
        """Retrieve the full text output from worker_stream for a completed cycle.

        Prefers the ``result`` event emitted at the end of a stream-json
        session (contains the complete assistant response).  Falls back to the
        last individual text chunk when no result event is available.

        Internal ``memory_compactor`` chunks are excluded; they must not appear
        in user-visible excerpts or history.
        """
        try:
            rows = list(
                self._conn.execute(
                    "SELECT chunk FROM worker_stream WHERE cycle = ? "
                    "AND worker != 'memory_compactor' ORDER BY id DESC LIMIT 200",
                    (cycle,),
                )
            )
        except sqlite3.OperationalError:
            return ""
        return self._chunks_newest_first_to_stream_text(
            [str(r["chunk"] or "") for r in rows]
        )

    def _scroll_to_bottom(self) -> None:
        self._history_suppress_scroll = True
        try:
            scroll = self.query_one("#activity-scroll", ActivityScroll)
            scroll._prepend_baseline = None
            scroll._wants_bottom = True
        except Exception:
            self._history_suppress_scroll = False
            return
        try:
            self.set_timer(2.0, self._clear_wants_bottom)
        except Exception:
            pass

    def _clear_wants_bottom(self) -> None:
        try:
            scroll = self.query_one("#activity-scroll", ActivityScroll)
            scroll._wants_bottom = False
        except Exception:
            pass
        self._history_suppress_scroll = False


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

    def _scroll_widget_to_top(self, widget: Static | None) -> None:
        """Scroll so *widget* aligns with the viewport top."""
        if widget is None:
            self._scroll_to_bottom()
            return
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        self.call_after_refresh(
            lambda: scroll.scroll_to_widget(widget, top=True, animate=False, force=True)
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

    def _poll_fast(self) -> None:
        """Fast poll for stream/event handling and lightweight animation updates."""
        self._check_scheduler_health()
        self._poll_run_events()
        self._poll_agent_runs()
        self._poll_stream()
        self._poll_agent_stream()

    def _poll_animation(self) -> None:
        """Dedicated animation loop so placeholder dots don't wait on other refresh work."""
        self._poll_agent_stream_placeholders()
        self._poll_animated_stream_status()
        self._refresh_running_cycle_header()
        self._refresh_running_agent_headers()

    def _poll_slow(self) -> None:
        """Slower poll for heavier repo/file refreshes that need less cadence."""
        self._refresh_header()
        self._refresh_file_changes()
        self._refresh_checklist()
        self._refresh_live_plan()
        self._refresh_live_diff()

    def _memory_compactor_stream_before_worker_event(self) -> bool:
        """True while Tier A compaction is in flight: stream chunks exist but no worker row yet.

        Uses a reactive in-memory flag maintained by ``_poll_stream`` (set True on
        memory_compactor chunks) and ``_poll_run_events`` (set False on memory_compactor
        worker events). The flag is seeded once from the DB on mount because running
        the equivalent ``NOT EXISTS`` query every animation tick can take multiple
        seconds on a large DB and blocks the Textual event loop.
        """
        if not self._memory_compactor_active_seeded:
            self._seed_memory_compactor_active()
        return self._memory_compactor_active

    def _seed_memory_compactor_active(self) -> None:
        """One-time DB read to initialize ``_memory_compactor_active`` at session start."""
        self._memory_compactor_active_seeded = True
        try:
            row = self._conn.execute(
                """
                SELECT 1 FROM worker_stream ws
                WHERE ws.worker = 'memory_compactor'
                  AND NOT EXISTS (
                    SELECT 1 FROM run_events re
                    WHERE re.cycle = ws.cycle
                      AND re.kind = 'worker'
                      AND re.worker = 'memory_compactor'
                  )
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.OperationalError:
            self._memory_compactor_active = False
            return
        self._memory_compactor_active = row is not None

    def _invalidate_memory_compactor_placeholder_cache(self) -> None:
        """No-op retained for compatibility; the flag is updated reactively now."""
        return

    def _poll_animated_stream_status(self) -> None:
        """Animate Orchestrating… / Compressing Memory… or Running {worker}… until stream replaces the panel."""
        if self._scheduler_start_pending:
            self._orchestrating = True
            self._orchestrating_tick += 1
            dots = "." * ((self._orchestrating_tick % 3) + 1)
            self._set_stream_placeholder(f"[dim]Orchestrating{dots}[/]")
            return
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
            if self._memory_compactor_stream_before_worker_event():
                self._set_stream_placeholder(f"[dim]Compressing Memory{dots}[/]")
            else:
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
        if self._scheduler_start_pending:
            return
        self._scheduler_start_pending = True
        self._orchestrating = True
        self._orchestrating_tick = 0
        self._set_stream_placeholder("[dim]Orchestrating.[/]")
        self._scroll_to_bottom()
        self.call_after_refresh(self._start_scheduler_after_refresh)

    def _start_scheduler_after_refresh(self) -> None:
        if not self._scheduler_start_pending:
            return
        from lab.loop import spawn_scheduler

        researcher_root = project_researcher_root(self.cfg.project_dir)
        self._scheduler_start_pending = False
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

    def _refresh_running_agent_headers(self) -> None:
        """Tick live durations for any active async ``/agent`` sections."""
        for agent in self._agent_sections.values():
            if not agent.is_running:
                continue
            agent.header_widget.update(
                events.format_cycle_header(
                    agent.agent_id,
                    "agent",
                    agent.prompt,
                    label="agent",
                    elapsed_sec=self._agent_elapsed(agent),
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

            if worker == "memory_compactor" and kind == "worker":
                self._memory_compactor_active = False

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
                    self._cycle_stream_widget = self._mount_activity_widget(
                        "", classes="activity-line result-box",
                    )
                    self._cycle_stream_widget.display = False
                    self._current_cycle_widgets.append(self._cycle_stream_widget)
                self._stream_is_running_placeholder = True
                self._running_worker_tick = 0
                wdots = "." * ((self._running_worker_tick % 3) + 1)
                follow = self._activity_viewport_at_bottom()
                self._set_stream_placeholder(f"[dim]Running {worker}{wdots}[/]")
                self._reposition_active_agent_sections()
                # Keep the scheduler's newest cycle visible even when standalone
                # /agent sections are also active; otherwise /start can look idle
                # because the new cycle mounts above the currently focused agent UI.
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
                if worker == "memory_compactor" and ok:
                    excerpt = ""
                checklist = str(payload.get("immediate_plan_checklist", "") or "").strip()
                if not checklist:
                    checklist = self._read_immediate_plan_checklist()
                self._clear_stream_status()
                self._cycle_stream_widget = None
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
                    result_w = self._write_result_box(
                        excerpt,
                        title=f"[dim]{worker}[/] [dim]cycle {cycle}[/]",
                    )
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
                self._reposition_active_agent_sections()

    def _poll_agent_runs(self) -> None:
        """Check for new or completed async ``/agent`` runs."""
        try:
            rows = db.list_agent_runs(self._conn)
        except sqlite3.OperationalError:
            return
        seen_ids = {int(row["id"]) for row in rows}
        for stale_id in list(self._agent_processes):
            if stale_id not in seen_ids:
                self._agent_processes.pop(stale_id, None)
        for row in rows:
            agent_id = int(row["id"])
            status = str(row["status"] or "running")
            pid = int(row["pid"]) if row["pid"] is not None else None
            proc = self._agent_processes.get(agent_id)
            if status == "running":
                dead_local = proc is not None and not proc.is_alive()
                dead_pid = proc is None and not self._pid_is_alive(pid)
                if dead_local or dead_pid:
                    reason = "agent process exited unexpectedly" if pid else "agent was left marked running, but no live process exists"
                    row = self._finalize_stale_agent_run(agent_id, reason) or row
                    status = str(row["status"] or "failed")
                    self._agent_processes.pop(agent_id, None)
            if agent_id in self._history_deferred_agent_ids:
                continue
            agent = self._agent_sections.get(agent_id)
            if agent is None:
                agent = self._create_agent_section(row)
                self._reposition_active_agent_sections()
                self._scroll_widget_to_top(agent.header_widget)
                continue
            if agent.status != status and status != "running":
                self._finalize_agent_section(row)
                self._agent_processes.pop(agent_id, None)

    def _poll_agent_stream(self) -> None:
        """Append stream events to each live async agent section."""
        try:
            rows = db.agent_stream_chunks_since(self._conn, self._last_agent_stream_id)
        except sqlite3.OperationalError:
            return
        for row in rows:
            self._last_agent_stream_id = int(row["id"])
            agent = self._agent_sections.get(int(row["agent_id"]))
            if agent is None:
                continue
            follow = self._activity_viewport_at_bottom()
            self._agent_apply_stream_chunk(agent, str(row["chunk"] or ""))
            if follow:
                self._scroll_to_bottom()

    def _poll_agent_stream_placeholders(self) -> None:
        """Animate Running agent… until tool/text stream content replaces the panel."""
        for agent in self._agent_sections.values():
            if not agent.is_running or agent.stream_widget is None:
                continue
            if agent.stream_tool_markup or agent.stream_text_live.strip():
                continue
            agent.stream_placeholder_tick += 1
            dots = "." * ((agent.stream_placeholder_tick % 3) + 1)
            agent.stream_widget.update(
                events.make_stream_panel(f"[dim]Running agent{dots}[/]")
            )
            agent.stream_widget.display = True

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
            if row["worker"] == "memory_compactor":
                self._memory_compactor_active = True
                self._memory_compactor_active_seeded = True
                continue
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
        pending_edit = self._pending_prompt_edit
        first_line = raw.splitlines()[0].strip() if raw.splitlines() else ""
        if pending_edit is not None and not first_line.startswith("/"):
            self._remove_welcome_intro()
            self._clear_below_stream_feedback()
            self._write_pending_edit_body(pending_edit, raw.strip())
            self._pending_prompt_edit = None
            label = "research idea" if pending_edit.target == "idea" else "preferences"
            self._write_below_stream_box(f"  [green]Updated {label}.[/]")
            return

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
            self._write_activity(
                f"  [green]❯[/] {rich_escape(instruction_text)}", below_stream=True
            )

        if not first.startswith("/"):
            db.enqueue_event(self._conn, "instruction", text)
            self._conn.commit()
            self._write_activity(f"  [green]❯[/] {rich_escape(text)}", below_stream=True)
            return

        parts = first.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""

        if self._pending_prompt_edit is not None and cmd != "edit":
            self._pending_prompt_edit = None

        if cmd == "instruction":
            body = (rest + "\n" + tail if tail else rest).strip()
            if not body:
                self._write_below_stream_box("  [red]/instruction[/] requires text")
                return
            db.enqueue_event(self._conn, "instruction", body)
            self._conn.commit()
            self._write_below_stream_box(f"  [green]❯[/] {rich_escape(body)}")
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

        if cmd == "edit":
            self._cmd_edit(rest)
            return

        if cmd == "agent":
            body = (rest + "\n" + tail if tail else rest).strip()
            self._cmd_agent(body)
            return

        handler = {
            "start": self._cmd_start,
            "pause": self._cmd_pause,
            "exit": self._cmd_exit,
            "help": self._cmd_help,
            "reset": self._cmd_reset,
            "undo": self._cmd_undo,
            "redo": self._cmd_redo,
        }.get(cmd)

        if cmd == "stop":
            self._cmd_stop(rest)
        elif handler:
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
        self._kill_agent_processes()
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
        self._kill_agent_processes()
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

        if scheduler_alive and mode != "active":
            db.set_control_mode(self._conn, "active")
            db.enqueue_event(self._conn, "resume", None)
        elif not scheduler_alive and mode != "active":
            db.set_control_mode(self._conn, "active")
        self._conn.commit()

        if scheduler_alive:
            if mode == "paused":
                self._orchestrating = True
            else:
                self._write_activity("  [dim]Agent is already running.[/]", below_stream=True)
            return

        self._auto_restarts = 0
        self._restart_scheduler()

    def _cmd_stop(self, rest: str = "") -> None:
        """Stop everything, or target one standalone async agent via ``/stop agent N``."""
        parts = rest.strip().split()
        if parts:
            if len(parts) == 2 and parts[0].lower() == "agent":
                try:
                    agent_id = int(parts[1])
                except ValueError:
                    self._write_below_stream_box("  [red]Usage:[/] /stop agent [id]")
                    return
                row = db.get_agent_run(self._conn, agent_id)
                if row is None:
                    self._write_below_stream_box(f"  [red]No such agent:[/] {agent_id}")
                    return
                if str(row["status"] or "") != "running":
                    self._write_below_stream_box(f"  [dim]Agent {agent_id} is not running.[/]")
                    return
                self._kill_single_agent_process(agent_id)
                self._write_below_stream_box(f"  [yellow]Stopped agent {agent_id}.[/]")
                return
            self._write_below_stream_box("  [red]Usage:[/] /stop OR /stop agent [id]")
            return

        # No args: keep the original global stop behaviour.
        db.set_graceful_pause_pending(self._conn, False)
        self._kill_scheduler()
        self._kill_agent_processes()
        self._revert_to_checkpoint(skip_git_if_worktree_matches_tip=True)
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
        self._shutdown_and_exit()

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

    def _pending_edit_spec(
        self,
        target: str,
    ) -> _PendingPromptEditState | None:
        normalized = target.strip().lower()
        state_root = memory.state_dir(self.cfg.researcher_root)
        if normalized == "idea":
            return _PendingPromptEditState(
                target="idea",
                path=state_root / "research_idea.md",
                heading="# Research brief",
            )
        if normalized in {"prefs", "preferences"}:
            return _PendingPromptEditState(
                target="prefs",
                path=state_root / "preferences.md",
                heading="# Preferences",
            )
        return None

    def _read_pending_edit_body(self, pending: _PendingPromptEditState) -> str:
        content = helpers.read_text(pending.path, default=f"{pending.heading}\n\n")
        lines = content.splitlines()
        if lines and lines[0].strip() == pending.heading:
            return "\n".join(lines[1:]).lstrip("\n").rstrip("\n")
        return content.strip("\n")

    def _write_pending_edit_body(
        self,
        pending: _PendingPromptEditState,
        body: str,
    ) -> None:
        cleaned = body.strip()
        content = f"{pending.heading}\n\n"
        if cleaned:
            content += f"{cleaned}\n"
        helpers.write_text(pending.path, content)

    def _load_prompt_text(self, text: str) -> None:
        prompt = self.query_one("#prompt", PromptTextArea)
        prompt.text = text
        prompt._adjust_height()
        lines = text.split("\n")
        prompt.move_cursor((len(lines) - 1, len(lines[-1])), record_width=False)
        prompt.focus()
        try:
            prompt.scroll_cursor_visible()
        except Exception:
            pass

    def _cmd_edit(self, rest: str) -> None:
        pending = self._pending_edit_spec(rest)
        if pending is None:
            self._pending_prompt_edit = None
            self._write_below_stream_box(
                f"  [red]Usage:[/] {rich_escape('/edit [idea|prefs]')}"
            )
            return
        self._pending_prompt_edit = pending
        self._load_prompt_text(self._read_pending_edit_body(pending))
        label = "research idea" if pending.target == "idea" else "preferences"
        self._write_below_stream_box(
            f"  [yellow]Editing {label}.[/] The next non-command submission will overwrite [bold]{pending.path.name}[/]."
        )

    def _cmd_help(self) -> None:
        self._write_below_stream_box(
            "  [bold]Commands[/]\n"
            "  [bold]/start[/]        Start the background agent\n"
            "  [bold]/agent[/]        /agent [prompt] runs a standalone subagent, useful for asking questions\n"
            "  [bold]/pause[/]        Pause after the current worker finishes\n"
            "  [bold]/stop[/]         Stop everything immediately (workers + /agent runs). Use [bold]/stop agent n[/] to stop a specific agent\n"
            "  [bold]/exit[/]         Stop agent and quit\n"
            "  [bold]/edit[/]         /edit idea to edit the research idea; /edit prefs to edit the preferences.\n"
            "  [bold]/plan[/]         Show the live roadmap checklist\n"
            "  [bold]/diff[/]         Line-by-line diff on current cycle. [bold]/diff n[/] = diff in cycle n; [bold]/diff n m[/] = diff in cycle range (inclusive)\n"
            "  [bold]/reset[/]        Clear DB and runtime memory; keep research_idea.md + preferences.md; project code unchanged\n"
            "  [bold]/undo[/]         Revert since last worker; restarts orchestrator only if agent was running\n"
            "  [bold]/redo[/]         Restore the last undone checkpoint and replay local edits on top\n"
            "  [bold]/help[/]         This message\n"
            "\n  Plain text is queued as an instruction.\n"
            "  [dim]Enter[/] sends · [dim]Shift+Enter[/] for newline · navigate lines with arrows\n"
        )

    def _cmd_agent(self, body: str) -> None:
        if not body.strip():
            self._write_below_stream_box("  [red]/agent[/] requires a prompt")
            return
        from lab.loop import spawn_agent_run

        backend = self.cfg.default_worker_backend
        if backend not in ("claude", "cursor"):
            backend = "cursor"
        model = self.cfg.cursor_agent_model if backend == "cursor" else ""
        agent_id = db.create_agent_run(self._conn, prompt=body, backend=backend, model=model or "")
        researcher_root = project_researcher_root(self.cfg.project_dir)
        proc = spawn_agent_run(
            self.db_path,
            researcher_root,
            self.cfg.project_dir,
            self.cfg,
            agent_id,
        )
        self._agent_processes[agent_id] = proc
        db.update_agent_run_pid(self._conn, agent_id, proc.pid)
        row = db.get_agent_run(self._conn, agent_id)
        if row is not None and agent_id not in self._agent_sections:
            agent = self._create_agent_section(row)
            self._reposition_active_agent_sections()
            self._scroll_widget_to_top(agent.header_widget)

    def _cmd_reset(self) -> None:
        self._kill_scheduler()
        self._kill_agent_processes()
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
        self._agent_sections = {}
        self._last_agent_stream_id = 0
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
            self._rebuild_activity_from_db(load_full_history=True)
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

    def _kill_scheduler(
        self,
        *,
        wait_timeout: float | None = _FORCED_SCHEDULER_KILL_WAIT_TIMEOUT,
    ) -> None:
        """Immediately kill the scheduler and all child worker processes."""
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.kill_group(wait_timeout=wait_timeout)
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
        skip_git_if_worktree_matches_tip: bool = False,
        skip_ui_rebuild: bool = False,
    ) -> None:
        """Restore the working tree to the last completed-cycle checkpoint and
        roll back the DB to match, removing any UI traces of the interrupted cycle.

        When *skip_git_if_worktree_matches_tip* is true (``/exit``, ``/stop``, quit),
        skip ``read-tree`` / ``checkout-index`` / ``clean`` if there is no in-flight
        cycle (orchestrator not ahead of worker) and the worktree already matches
        the tip ``checkpoints`` commit — otherwise behaviour is unchanged.

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
            skip_git = (
                skip_git_if_worktree_matches_tip
                and not tip_ahead
                and not undo_last_completed_worker
                and git_checkpoint.worktree_matches_checkpoint_tip(self.cfg.project_dir)
            )
            if skip_git:
                cycle = None
            elif undo_last_completed_worker and not tip_ahead:
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

        if not skip_ui_rebuild:
            try:
                self._clear_stream_status()
            except Exception:
                pass
            try:
                self._rebuild_activity_from_db(load_full_history=True)
                self._refresh_header()
            except Exception:
                pass

            if emit_activity_message and max_event_cycle_before > self._last_cycle:
                self._write_checkpoint_notice(
                    f"  [yellow]Reverted to checkpoint (cycle {self._last_cycle}).[/]"
                )

    def action_quit(self) -> None:
        self._shutdown_and_exit()

    def _shutdown_and_exit(self) -> None:
        """Kill workers, revert only if needed (no UI rebuild), then exit."""
        from lab import git_checkpoint

        self._cancel_pending_rebuild_chain()
        db.set_graceful_pause_pending(self._conn, False)
        self._kill_scheduler()
        self._kill_agent_processes()

        tip_ahead = False
        try:
            tip_ahead = db.orchestrator_ahead_of_worker(self._conn)
        except Exception:
            pass

        needs_git_revert = tip_ahead or not git_checkpoint.worktree_matches_checkpoint_tip(
            self.cfg.project_dir
        )

        if needs_git_revert:
            self._revert_to_checkpoint(skip_ui_rebuild=True)
        else:
            self._cleanup_orphaned_cycles()

        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self.exit()


def run_console(db_path: Path, cfg: RunConfig) -> None:
    """Entry point for the TUI."""
    app = ResearchConsole(db_path, cfg)
    app.run()
