"""Textual TUI: status pane + command prompt; writes control events to SQLite."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static

from research_lab import db
from research_lab.ui import events


class ResearchConsole(App[None]):
    """Async command surface; polls DB for scheduler heartbeats."""

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self._conn = db.connect_db(db_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static("Initializing…", id="status")
            yield RichLog(id="log", highlight=True, markup=True)
            with Horizontal():
                yield Input(
                    placeholder="Type instructions as plain text, or /pause /resume /status /help …",
                    id="cmd",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Start polling thread for status refresh."""
        self.title = "research-lab"
        self.sub_title = str(self.db_path)
        self.set_interval(0.4, self._refresh_status)

    def _refresh_status(self) -> None:
        """Poll DB and update status widget."""
        status = self.query_one("#status", Static)
        log = self.query_one("#log", RichLog)
        try:
            block = events.format_status_block(self._conn)
            status.update(block)
        except sqlite3.OperationalError:
            log.write("[yellow]waiting for DB…[/]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle one line: plain text queues an instruction; `/name` runs a control command."""
        line = event.value.strip()
        event.input.value = ""
        log = self.query_one("#log", RichLog)
        if not line:
            return
        if not line.startswith("/"):
            db.enqueue_event(self._conn, "instruction", line)
            self._conn.commit()
            log.write(f"[green]queued instruction[/]: {line[:200]}")
            return
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower().removeprefix("/")
        rest = parts[1] if len(parts) > 1 else ""
        if cmd == "help":
            log.write(
                "[bold]Slash commands:[/] /instruction <text> | /ask <q> | /pause | /resume | "
                "/shutdown | /status | /backlog | /branches | /experiments | /report | /help — "
                "lines without a leading / are queued as instructions."
            )
            return
        if cmd == "instruction":
            db.enqueue_event(self._conn, "instruction", rest)
            self._conn.commit()
            log.write(f"[green]queued instruction[/]: {rest[:200]}")
            return
        if cmd == "ask":
            db.enqueue_event(self._conn, "question", rest)
            self._conn.commit()
            log.write(f"[green]queued question[/]: {rest[:200]}")
            return
        if cmd == "pause":
            db.enqueue_event(self._conn, "pause", None)
            self._conn.commit()
            log.write("[yellow]pause requested[/]")
            return
        if cmd == "resume":
            db.enqueue_event(self._conn, "resume", None)
            self._conn.commit()
            log.write("[green]resume requested[/]")
            return
        if cmd == "shutdown":
            db.enqueue_event(self._conn, "shutdown", None)
            self._conn.commit()
            log.write("[red]shutdown requested — exiting UI shortly[/]")
            threading.Timer(0.8, self.exit).start()
            return
        if cmd == "status":
            st = db.get_system_state(self._conn)
            log.write(str(dict(st)))
            return
        if cmd == "backlog":
            rows = db.list_instructions(self._conn)
            for r in rows[:20]:
                log.write(f"{r['id']}: [{r['status']}] {r['text'][:200]}")
            return
        if cmd == "branches":
            for r in db.list_branches_rows(self._conn)[:30]:
                log.write(f"{r['name']}: {r['status']}")
            return
        if cmd == "experiments":
            for r in db.list_experiments_rows(self._conn)[:30]:
                log.write(f"{r['exp_id']}: {r['status']} ({r['branch']})")
            return
        if cmd == "report":
            log.write("[dim]report: not implemented yet — use Tier A / memory/extended for notes[/]")
            return
        log.write(f"[red]unknown command:[/] {cmd}")


def run_console(db_path: Path) -> None:
    """Entry for the TUI process."""
    app = ResearchConsole(db_path)
    app.run()
