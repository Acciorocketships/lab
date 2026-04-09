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

#prompt-box {
    dock: bottom;
    layout: horizontal;
    height: 3;
    max-height: 14;
    min-height: 3;
    margin: 0 1;
    padding: 0 1;
    border: round $accent-darken-2;
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
    padding: 0 3;
    margin: 0 2;
    border-left: tall $accent;
}

#stream-text {
    height: auto;
    max-height: 6;
    padding: 1 3;
    margin: 0 2;
    background: $boost;
    border: round $surface-lighten-2;
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

    def _mount_activity_widget(self, markup: str) -> Static:
        """Append a line and return the widget so it can be updated later."""
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        stream = self.query_one("#stream-text", Static)
        w = Static(markup, classes="activity-line")
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

    def _scroll_to_bottom(self) -> None:
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        self.call_after_refresh(lambda: scroll.scroll_end(animate=False))

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
        status = self.query_one("#stream-text", Static)
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
                if cycle != self._last_cycle or worker != self._last_worker:
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
                        )
                    )
                    self._current_cycle_widgets.append(self._cycle_header_widget)
                    task_w = self._write_task(task)
                    if task_w is not None:
                        self._current_cycle_widgets.append(task_w)
                status.update(f"[dim]Running {worker}…[/]")
                status.display = True
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
                summary_excerpt = events.extract_result_excerpt(row["summary"] or "")
                excerpt = stream_excerpt or summary_excerpt
                status.update("")
                status.display = False
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
                self._write_activity(events.format_worker_result_excerpt(ok, excerpt))
                self._last_stream_text = ""

    def _poll_stream(self) -> None:
        """Show the most recent stream event in the inline status panel.

        Only the latest message is displayed (replaced each poll).  Text events
        are stored so they can be persisted into the activity log when the
        worker finishes.
        """
        status = self.query_one("#stream-text", Static)
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
                status.update(f"[cyan]{text}[/]")
                if not status.display:
                    status.display = True
                self._scroll_to_bottom()
            elif event_type == "text" and text.strip():
                clean = text.strip()
                self._last_stream_text = clean
                status.update(f"[dim]{clean}[/]")
                if not status.display:
                    status.display = True
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
        status = self.query_one("#stream-text", Static)
        status.update("")
        status.display = False
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
        status = self.query_one("#stream-text", Static)
        status.update("")
        status.display = False
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

    def _revert_to_checkpoint(self) -> None:
        """Restore the working tree to the last completed-cycle checkpoint and
        roll back the DB to match, removing any UI traces of the interrupted cycle."""
        from research_lab import git_checkpoint

        if self._cycle_header_widget is not None and self._worker_start_ts:
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

        if not git_checkpoint.has_checkpoint(self.cfg.project_dir):
            return
        cycle = git_checkpoint.revert_to_checkpoint(self.cfg.project_dir)
        if cycle is None:
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            db.rollback_to_cycle(self._conn, cycle)
            self._conn.commit()
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass

        if self._last_cycle > cycle:
            for w in self._current_cycle_widgets:
                w.remove()
            self._current_cycle_widgets.clear()
            self._cycle_header_widget = None
            self._last_cycle = cycle
            self._last_worker = ""
            self._worker_start_ts = 0.0
            self._last_orchestrator_task = ""
            self._last_stream_text = ""

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

        status = self.query_one("#stream-text", Static)
        status.update("")
        status.display = False

        self._write_activity(f"  [yellow]Reverted to checkpoint (cycle {cycle}).[/]")

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
