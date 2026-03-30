"""Redesigned Textual TUI: Claude Code-inspired layout with streaming output."""

from __future__ import annotations

import multiprocessing
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from research_lab import db
from research_lab.runner import reset_project_preserving_research_idea
from research_lab.ui import events

if TYPE_CHECKING:
    from research_lab.config import RunConfig

CSS = """
Screen {
    background: $surface;
}

#header {
    height: 1;
    dock: top;
    background: $primary-background;
    color: $text-muted;
    padding: 0 1;
}

#activity {
    min-height: 1;
}

#statusbar {
    height: 1;
    dock: bottom;
    background: $primary-background;
    color: $text-muted;
    padding: 0 1;
}

#prompt {
    dock: bottom;
    height: 1;
    margin: 0;
    border: none;
    background: $surface;
}

#prompt:focus {
    border: none;
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
        self._scheduler: multiprocessing.Process | None = None
        self._last_stream_id = 0
        self._last_run_event_id = 0
        self._last_cycle = 0
        self._last_worker = ""
        self._worker_start: float = 0.0
        self._project_name = cfg.project_dir.name
        self._model = cfg.openai_model

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Vertical():
            yield RichLog(id="activity", highlight=False, markup=True, wrap=True, auto_scroll=True)
        yield Static("", id="statusbar")
        yield Input(placeholder="> ", id="prompt")

    def on_mount(self) -> None:
        self._refresh_header()
        log = self.query_one("#activity", RichLog)
        log.write("")
        log.write("  [bold]Welcome to lab.[/] Type [bold]/start[/] to begin, or type an instruction.")
        log.write("  Type [bold]/help[/] for available commands.\n")
        self.set_interval(0.3, self._poll)

    def _refresh_header(self) -> None:
        try:
            hdr = events.header_line(self._project_name, self._model, self._conn)
        except sqlite3.OperationalError:
            hdr = "[bold]lab[/]"
        self.query_one("#header", Static).update(hdr)

    def _refresh_status(self) -> None:
        try:
            line = events.status_line(self._conn)
        except sqlite3.OperationalError:
            line = "[dim]waiting for DB...[/]"
        self.query_one("#statusbar", Static).update(line)

    def _poll(self) -> None:
        """Periodic poll: update header, status bar, run events, and stream chunks."""
        self._refresh_header()
        self._refresh_status()
        self._poll_run_events()
        self._poll_stream()

    def _poll_run_events(self) -> None:
        """Check for new orchestrator / worker lifecycle events."""
        log = self.query_one("#activity", RichLog)
        try:
            rows = list(
                self._conn.execute(
                    "SELECT id, ts, cycle, kind, worker, roadmap_step, task, summary "
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
                ok = "error" not in (row["summary"] or "").lower()
                log.write(events.format_worker_done(elapsed, ok))

    def _poll_stream(self) -> None:
        """Read new streaming chunks from the worker_stream table."""
        log = self.query_one("#activity", RichLog)
        try:
            rows = db.stream_chunks_since(self._conn, self._last_stream_id)
        except sqlite3.OperationalError:
            return
        for row in rows:
            self._last_stream_id = row["id"]
            line = events.format_stream_chunk(row["chunk"])
            if line:
                log.write(line)

    # --- input handling -------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return

        log = self.query_one("#activity", RichLog)

        if not line.startswith("/"):
            db.enqueue_event(self._conn, "instruction", line)
            self._conn.commit()
            log.write(f"\n  [green]\u276f[/] {line[:200]}")
            return

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""

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
        elif cmd == "instruction" and rest:
            db.enqueue_event(self._conn, "instruction", rest)
            self._conn.commit()
            log.write(f"\n  [green]\u276f[/] {rest[:200]}")
        else:
            log.write(f"  [red]Unknown command:[/] /{cmd}")

    def _cmd_start(self) -> None:
        log = self.query_one("#activity", RichLog)
        if self._scheduler and self._scheduler.is_alive():
            log.write("  [dim]Agent is already running.[/]")
            return

        db.enqueue_event(self._conn, "resume", None)
        self._conn.commit()

        from research_lab.loop import spawn_scheduler
        from research_lab.global_config import project_researcher_root

        researcher_root = project_researcher_root(self.cfg.project_dir)
        self._scheduler = spawn_scheduler(
            self.db_path, researcher_root, self.cfg.project_dir, self.cfg,
        )
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
