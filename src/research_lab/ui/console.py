"""Textual TUI: Claude Code-inspired layout with streaming output."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import RichLog, Static

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

#activity {
    min-height: 1;
    padding: 0 1;
    scrollbar-size: 1 1;
}

#prompt-box {
    dock: bottom;
    layout: horizontal;
    height: 3;
    max-height: 14;
    min-height: 3;
    margin: 0 1;
    padding: 0 1;
    border: round $primary;
    background: $boost;
}

#prompt-indicator {
    width: 2;
    height: 1;
    color: $accent;
    content-align: left top;
}

#prompt {
    width: 1fr;
    height: 1;
    border: none;
    background: transparent;
    padding: 0;
}

#prompt:focus {
    border: none;
}

#activity-status {
    dock: bottom;
    height: auto;
    max-height: 2;
    padding: 0 2;
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
        self._worker_start: float = 0.0
        self._project_name = cfg.project_dir.name
        self._model = cfg.openai_model
        self._auto_restarts = 0
        self._MAX_AUTO_RESTARTS = 3

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Vertical():
            yield RichLog(
                id="activity",
                highlight=False,
                markup=True,
                wrap=True,
                auto_scroll=True,
            )
        yield Static("", id="activity-status")
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
        log = self.query_one("#activity", RichLog)
        log.write("")
        log.write("  [bold]Welcome to lab.[/]")
        log.write("  Type [bold]/start[/] to begin, or type an instruction.")
        log.write(
            "  [dim]Enter[/] sends · [dim]Shift+Enter[/] for newline · "
            "[dim]/help[/] for commands\n"
        )
        self.query_one("#prompt", PromptTextArea).focus()
        self.set_interval(0.3, self._poll)

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

    def _check_scheduler_health(self) -> None:
        """Detect a crashed scheduler subprocess and auto-restart when possible."""
        if self._scheduler is None:
            return
        if self._scheduler.is_alive():
            return
        self._scheduler = None
        try:
            mode = db.get_system_state(self._conn).get("control_mode", "paused")
        except sqlite3.OperationalError:
            return
        if mode != "active":
            return
        log = self.query_one("#activity", RichLog)
        if self._auto_restarts >= self._MAX_AUTO_RESTARTS:
            log.write(
                "\n  [red]⚠ Agent process crashed repeatedly. Use [bold]/start[/] to restart.[/]"
            )
            db.set_control_mode(self._conn, "paused")
            self._conn.commit()
            return
        self._auto_restarts += 1
        log.write(
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

    def _poll_run_events(self) -> None:
        """Check for new orchestrator / worker lifecycle events."""
        log = self.query_one("#activity", RichLog)
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
                    self._last_cycle = cycle
                    self._last_worker = worker
                    self._worker_start = time.time()
                    log.write(events.format_cycle_header(cycle, worker, task))
            elif kind == "worker":
                elapsed = time.time() - self._worker_start if self._worker_start else 0
                payload: dict = {}
                try:
                    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                ok = payload.get("worker_ok", True)
                excerpt = events.extract_result_excerpt(row["summary"] or "")
                log.write(events.format_worker_done(elapsed, ok, excerpt))
                self.query_one("#activity-status", Static).update("")

    def _poll_stream(self) -> None:
        """Read new streaming chunks from the worker_stream table.

        All stream content updates the live status widget in place rather than
        appending to the scrollback log, so the UI shows a single continuously-
        refreshed line instead of an ever-growing list of ``┊`` rows.
        """
        status = self.query_one("#activity-status", Static)
        try:
            rows = db.stream_chunks_since(self._conn, self._last_stream_id)
        except sqlite3.OperationalError:
            return
        for row in rows:
            self._last_stream_id = row["id"]
            parsed = events.parse_stream_event(row["chunk"])
            if parsed is None:
                continue
            event_type, text = parsed
            if event_type == "tool":
                status.update(f"  [dim]┊[/] [cyan]{text}[/]")
            elif event_type == "text" and text.strip():
                status.update(f"  [dim]┊ {text.strip()}[/]")

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

        log = self.query_one("#activity", RichLog)

        if not first.startswith("/"):
            db.enqueue_event(self._conn, "instruction", text)
            self._conn.commit()
            preview = text if len(text) <= 200 else text[:200] + "…"
            log.write(f"\n  [green]❯[/] {preview}")
            return

        parts = first.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "instruction":
            body = (rest + "\n" + tail if tail else rest).strip()
            if not body:
                log.write("  [red]/instruction[/] requires text")
                return
            db.enqueue_event(self._conn, "instruction", body)
            self._conn.commit()
            preview = body if len(body) <= 200 else body[:200] + "…"
            log.write(f"\n  [green]❯[/] {preview}")
            return

        if tail:
            log.write(
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
            log.write(f"  [red]Unknown command:[/] /{cmd}")

    def _cmd_start(self) -> None:
        log = self.query_one("#activity", RichLog)
        mode = db.get_system_state(self._conn).get("control_mode", "active")
        scheduler_alive = bool(self._scheduler and self._scheduler.is_alive())

        if mode != "active" or not scheduler_alive:
            db.enqueue_event(self._conn, "resume", None)
            self._conn.commit()

        if scheduler_alive:
            if mode == "paused":
                log.write("  [green]Agent resumed.[/]\n")
            else:
                log.write("  [dim]Agent is already running.[/]")
            return

        self._auto_restarts = 0
        self._restart_scheduler()
        log.write("  [green]Agent started.[/]\n")

    def _cmd_pause(self) -> None:
        log = self.query_one("#activity", RichLog)
        db.enqueue_event(self._conn, "pause", None)
        self._conn.commit()
        log.write("  [yellow]Agent paused.[/]")

    def _cmd_exit(self) -> None:
        log = self.query_one("#activity", RichLog)
        db.enqueue_event(self._conn, "pause", None)
        self._conn.commit()
        log.write("  [dim]Shutting down...[/]")
        self._kill_scheduler()
        self.set_timer(0.3, self.exit)

    def _cmd_status(self) -> None:
        log = self.query_one("#activity", RichLog)
        try:
            st = db.get_system_state(self._conn)
        except sqlite3.OperationalError:
            log.write("  [red]DB not ready[/]")
            return
        mode = st.get("control_mode", "?")
        cycle = st.get("cycle_count", 0)
        worker = st.get("current_worker", "")
        task = (st.get("task", "") or "")[:120]
        roadmap = (st.get("roadmap_step", "") or "")[:60]
        log.write(
            f"  [bold]Status[/]  mode={mode}  cycle={cycle}  worker={worker}\n"
            f"  roadmap: {roadmap}\n"
            f"  task: {task}"
        )

    def _cmd_help(self) -> None:
        log = self.query_one("#activity", RichLog)
        log.write(
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
        log = self.query_one("#activity", RichLog)
        rows = db.list_instructions(self._conn)
        if not rows:
            log.write("  [dim]No instructions.[/]")
            return
        for r in rows[:15]:
            log.write(f"  [dim]{r['id']}[/] [{r['status']}] {r['text'][:160]}")

    def _cmd_experiments(self) -> None:
        log = self.query_one("#activity", RichLog)
        rows = db.list_experiments_rows(self._conn)
        if not rows:
            log.write("  [dim]No experiments.[/]")
            return
        for r in rows[:20]:
            log.write(f"  {r['exp_id']}: {r['status']} ({r['branch']})")

    def _cmd_reset(self) -> None:
        log = self.query_one("#activity", RichLog)
        self._kill_scheduler()
        self._conn.close()
        try:
            reset_project_preserving_research_idea(self.cfg.project_dir)
        except Exception as e:
            self._conn = db.connect_db(self.db_path)
            log.write(f"  [red]Reset failed:[/] {e}")
            return
        self._conn = db.connect_db(self.db_path)
        self._last_stream_id = 0
        self._last_run_event_id = 0
        self._last_cycle = 0
        self._last_worker = ""
        self._worker_start = 0.0
        log.write(
            "  [green]Reset complete.[/] Kept [bold]research_idea.md[/] and [bold]preferences.md[/]. "
            "Cleared DB, other Tier A files, episodes, extended, branches, skills, experiments."
        )

    # --- lifecycle ------------------------------------------------------------

    def _kill_scheduler(self) -> None:
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.terminate()
            self._scheduler.join(timeout=3)
        self._scheduler = None

    def action_quit(self) -> None:
        db.enqueue_event(self._conn, "pause", None)
        self._conn.commit()
        self._kill_scheduler()
        self.exit()


def run_console(db_path: Path, cfg: RunConfig) -> None:
    """Entry point for the TUI."""
    app = ResearchConsole(db_path, cfg)
    app.run()
