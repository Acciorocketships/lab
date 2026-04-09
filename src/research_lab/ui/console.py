"""Textual TUI: Claude Code-inspired layout with streaming output."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from research_lab import db
from research_lab.runner import reset_project_preserving_research_idea
from research_lab.ui import events
from research_lab.ui.prompt_text_area import PromptSubmitted, PromptTextArea

if TYPE_CHECKING:
    from research_lab.config import RunConfig
    from research_lab.loop import SchedulerProcessHandle

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
    color: $text-muted;
    border-left: tall $surface-lighten-1;
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
        self._current_cycle_widgets: list[Static] = []

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
        self._write_activity("")
        self._write_activity("  [bold]Welcome to lab.[/]")
        self._write_activity("  Type [bold]/start[/] to begin, or type an instruction.")
        self._write_activity(
            "  [dim]Enter[/] sends · [dim]Shift+Enter[/] for newline · "
            "[dim]/help[/] for commands\n"
        )
        self.query_one("#prompt", PromptTextArea).focus()
        self.set_interval(0.3, self._poll)

    # --- activity helpers -----------------------------------------------------

    def _write_activity(self, markup: str) -> None:
        """Append a permanent line to the activity scroll area."""
        if not markup:
            return
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        scroll.mount(Static(markup, classes="activity-line"), before=stream)
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

    def _clear_stream_status(self) -> None:
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(""))
        status.display = False

    def _set_stream_status(self, markup: str) -> None:
        status = self.query_one("#stream-text", Static)
        status.update(events.make_stream_panel(markup))
        status.display = True

    def _fetch_last_stream_text(self, cycle: int) -> str:
        """Retrieve the last text content from worker_stream for a completed cycle."""
        try:
            rows = list(self._conn.execute(
                "SELECT chunk FROM worker_stream WHERE cycle = ? ORDER BY id DESC LIMIT 50",
                (cycle,),
            ))
        except sqlite3.OperationalError:
            return ""
        for row in rows:
            parsed = events.parse_stream_event(row["chunk"], full_text=True)
            if parsed and parsed[0] == "text" and parsed[1].strip():
                return parsed[1].strip()
        return ""

    def _scroll_to_bottom(self) -> None:
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

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
        self._refresh_running_cycle_header()

    def _check_scheduler_health(self) -> None:
        """Detect a crashed scheduler subprocess and auto-restart when possible."""
        if self._scheduler is None:
            return
        if self._scheduler.is_alive():
            return
        self._scheduler = None
        self._revert_to_checkpoint()
        try:
            mode = db.get_system_state(self._conn).get("control_mode", "paused")
        except sqlite3.OperationalError:
            return
        if mode != "active":
            return
        if self._auto_restarts >= self._MAX_AUTO_RESTARTS:
            self._write_activity(
                "\n  [red]⚠ Agent process crashed repeatedly. Use [bold]/start[/] to restart.[/]"
            )
            db.set_control_mode(self._conn, "paused")
            self._conn.commit()
            return
        self._auto_restarts += 1
        self._write_activity(
            f"\n  [red]⚠ Agent process exited unexpectedly. "
            f"Restarting… ({self._auto_restarts}/{self._MAX_AUTO_RESTARTS})[/]"
        )
        self._restart_scheduler()

    def _restart_scheduler(self) -> None:
        from research_lab.loop import spawn_scheduler
        from research_lab.global_config import project_researcher_root

        researcher_root = project_researcher_root(self.cfg.project_dir)
        db.enqueue_event(self._conn, "resume", None)
        self._conn.commit()
        self._scheduler = spawn_scheduler(
            self.db_path, researcher_root, self.cfg.project_dir, self.cfg,
        )

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
                elapsed_sec=elapsed,
                status="running",
            )
        )

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
                new_cycle = cycle != self._last_cycle or worker != self._last_worker
                if new_cycle:
                    if self._cycle_header_widget is not None:
                        ps = self._worker_start_ts
                        pe = max(0.0, time.time() - ps) if ps else 0.0
                        self._cycle_header_widget.update(
                            events.format_cycle_header(
                                self._last_cycle,
                                self._last_worker,
                                self._last_orchestrator_task,
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
                    self._current_cycle_widgets = []
                    elapsed0 = events.cycle_header_running_elapsed(self._worker_start_ts)
                    self._cycle_header_widget = self._mount_activity_widget(
                        events.format_cycle_header(
                            cycle,
                            worker,
                            task,
                            elapsed_sec=elapsed0,
                            status="running",
                        ),
                        classes="activity-line cycle-header",
                    )
                    self._current_cycle_widgets.append(self._cycle_header_widget)
                    task_w = self._write_task(task)
                    if task_w is not None:
                        self._current_cycle_widgets.append(task_w)
                self._set_stream_status(f"[dim]Running {worker}...[/]")
                if new_cycle and self._cycle_header_widget is not None:
                    self._scroll_cycle_header_to_top()
                else:
                    self._scroll_to_bottom()
            elif kind == "worker":
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
                stream_excerpt = events.extract_result_excerpt(self._last_stream_text)
                if not stream_excerpt:
                    stream_excerpt = events.extract_result_excerpt(
                        self._fetch_last_stream_text(cycle)
                    )
                summary_excerpt = events.extract_result_excerpt(row["summary"] or "")
                excerpt = stream_excerpt or summary_excerpt
                self._clear_stream_status()
                if self._cycle_header_widget is not None and cycle == self._last_cycle:
                    self._cycle_header_widget.update(
                        events.format_cycle_header(
                            cycle,
                            worker,
                            task or self._last_orchestrator_task,
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

    def _poll_stream(self) -> None:
        """Show the most recent stream event in the inline status panel.

        Only the latest message is displayed (replaced each poll).  Text events
        are stored so they can be persisted into the activity log when the
        worker finishes.
        """
        try:
            rows = db.stream_chunks_since(self._conn, self._last_stream_id)
        except sqlite3.OperationalError:
            return
        for row in rows:
            self._last_stream_id = row["id"]
            parsed = events.parse_stream_event(row["chunk"], full_text=True)
            if parsed is None:
                continue
            event_type, text = parsed
            if event_type == "tool" and text.strip():
                self._set_stream_status(f"[cyan]{text}[/]")
                self._scroll_to_bottom()
            elif event_type == "text" and text.strip():
                clean = text.strip()
                self._last_stream_text = clean
                self._set_stream_status(f"[dim]{clean}[/]")
                self._scroll_to_bottom()

    # --- input handling -------------------------------------------------------

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

        lines = text.splitlines()
        first = lines[0].strip()
        tail = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if not first.startswith("/"):
            db.enqueue_event(self._conn, "instruction", text)
            self._conn.commit()
            preview = text if len(text) <= 200 else text[:200] + "…"
            self._write_activity(f"\n  [green]❯[/] {preview}")
            return

        parts = first.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "instruction":
            body = (rest + "\n" + tail if tail else rest).strip()
            if not body:
                self._write_activity("  [red]/instruction[/] requires text")
                return
            db.enqueue_event(self._conn, "instruction", body)
            self._conn.commit()
            preview = body if len(body) <= 200 else body[:200] + "…"
            self._write_activity(f"\n  [green]❯[/] {preview}")
            return

        if tail:
            self._write_activity(
                "  [dim]Note: only the first line is used as a slash command; "
                "omit the leading / for multi-line instructions.[/]"
            )

        handler = {
            "start": self._cmd_start,
            "pause": self._cmd_pause,
            "exit": self._cmd_exit,
            "status": self._cmd_status,
            "help": self._cmd_help,
            "backlog": self._cmd_backlog,
            "experiments": self._cmd_experiments,
            "reset": self._cmd_reset,
        }.get(cmd)

        if handler:
            handler()
        else:
            self._write_activity(f"  [red]Unknown command:[/] /{cmd}")

    def _cmd_start(self) -> None:
        mode = db.get_system_state(self._conn).get("control_mode", "active")
        scheduler_alive = bool(self._scheduler and self._scheduler.is_alive())

        if mode != "active" or not scheduler_alive:
            db.enqueue_event(self._conn, "resume", None)
            self._conn.commit()

        if scheduler_alive:
            if mode == "paused":
                self._write_activity("  [green]Agent resumed.[/]\n")
            else:
                self._write_activity("  [dim]Agent is already running.[/]")
            return

        self._auto_restarts = 0
        self._restart_scheduler()
        self._write_activity("  [green]Agent started.[/]\n")

    def _cmd_pause(self) -> None:
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self._clear_stream_status()
        self._last_stream_text = ""
        self._write_activity("  [yellow]Agent paused.[/]")

    def _cmd_exit(self) -> None:
        self._write_activity("  [dim]Shutting down...[/]")
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self.set_timer(0.3, self.exit)

    def _cmd_status(self) -> None:
        try:
            st = db.get_system_state(self._conn)
        except sqlite3.OperationalError:
            self._write_activity("  [red]DB not ready[/]")
            return
        mode = st.get("control_mode", "?")
        cycle = st.get("cycle_count", 0)
        worker = st.get("current_worker", "")
        task = (st.get("task", "") or "")[:120]
        roadmap = (st.get("roadmap_step", "") or "")[:60]
        self._write_activity(
            f"  [bold]Status[/]  mode={mode}  cycle={cycle}  worker={worker}\n"
            f"  roadmap: {roadmap}\n"
            f"  task: {task}"
        )

    def _cmd_help(self) -> None:
        self._write_activity(
            "\n  [bold]Commands[/]\n"
            "  [bold]/start[/]        Start the background agent\n"
            "  [bold]/pause[/]        Pause the agent\n"
            "  [bold]/exit[/]         Pause agent and quit\n"
            "  [bold]/status[/]       Show current agent state\n"
            "  [bold]/backlog[/]      Show recent instructions\n"
            "  [bold]/experiments[/]  Show experiments\n"
            "  [bold]/reset[/]        Clear DB and runtime memory; keep research_idea.md + preferences.md\n"
            "  [bold]/help[/]         This message\n"
            "\n  Plain text is queued as an instruction.\n"
            "  [dim]Enter[/] sends · [dim]Shift+Enter[/] for newline · navigate lines with arrows\n"
        )

    def _cmd_backlog(self) -> None:
        rows = db.list_instructions(self._conn)
        if not rows:
            self._write_activity("  [dim]No instructions.[/]")
            return
        for r in rows[:15]:
            self._write_activity(f"  [dim]{r['id']}[/] [{r['status']}] {r['text'][:160]}")

    def _cmd_experiments(self) -> None:
        rows = db.list_experiments_rows(self._conn)
        if not rows:
            self._write_activity("  [dim]No experiments.[/]")
            return
        for r in rows[:20]:
            self._write_activity(f"  {r['exp_id']}: {r['status']} ({r['branch']})")

    def _cmd_reset(self) -> None:
        self._kill_scheduler()
        self._conn.close()
        try:
            reset_project_preserving_research_idea(self.cfg.project_dir)
        except Exception as e:
            self._conn = db.connect_db(self.db_path)
            self._write_activity(f"  [red]Reset failed:[/] {e}")
            return
        self._conn = db.connect_db(self.db_path)
        self._last_stream_id = 0
        self._last_run_event_id = 0
        self._last_cycle = 0
        self._last_worker = ""
        self._worker_start_ts = 0.0
        self._last_orchestrator_task = ""
        self._cycle_header_widget = None
        self._last_stream_text = ""
        self._current_cycle_widgets = []
        self._clear_stream_status()
        self._write_activity(
            "  [green]Reset complete.[/] Kept [bold]research_idea.md[/] and [bold]preferences.md[/]. "
            "Cleared DB, other Tier A files, episodes, extended, branches, skills, experiments."
        )

    # --- lifecycle ------------------------------------------------------------

    def _kill_scheduler(self) -> None:
        """Immediately kill the scheduler and all child worker processes."""
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.kill_group()
        self._scheduler = None

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

    def _revert_to_checkpoint(self) -> None:
        """Restore the working tree to the last completed-cycle checkpoint and
        roll back the DB to match, removing any UI traces of the interrupted cycle."""
        from research_lab import git_checkpoint

        # Remove in-progress cycle widgets unconditionally -- the scheduler is
        # dead at this point so the cycle cannot complete.
        for w in self._current_cycle_widgets:
            w.remove()
        self._current_cycle_widgets.clear()
        self._cycle_header_widget = None
        self._worker_start_ts = 0.0
        self._last_worker = ""
        self._last_orchestrator_task = ""
        self._last_stream_text = ""

        # Attempt git-level revert to the last completed-cycle checkpoint.
        reverted = False
        if git_checkpoint.has_checkpoint(self.cfg.project_dir):
            cycle = git_checkpoint.revert_to_checkpoint(self.cfg.project_dir)
            if cycle is not None:
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    db.rollback_to_cycle(self._conn, cycle)
                    self._conn.commit()
                    reverted = True
                except Exception:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass

        # Purge any remaining orphaned cycles the checkpoint didn't cover.
        self._cleanup_orphaned_cycles()

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

        if reverted:
            self._write_activity(
                f"  [yellow]Reverted to checkpoint (cycle {self._last_cycle}).[/]"
            )

    def action_quit(self) -> None:
        self._kill_scheduler()
        self._revert_to_checkpoint()
        db.set_control_mode(self._conn, "paused")
        self._conn.commit()
        self.exit()


def run_console(db_path: Path, cfg: RunConfig) -> None:
    """Entry point for the TUI."""
    app = ResearchConsole(db_path, cfg)
    app.run()
