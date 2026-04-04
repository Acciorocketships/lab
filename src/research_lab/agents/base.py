"""Dispatch a worker packet to Claude Code or Cursor CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from research_lab.tools import claude_code, cursor_cli

Backend = Literal["claude", "cursor"]
StreamCallback = Callable[[str], None]


def run_worker(
    packet: str,
    *,
    backend: Backend,
    project_cwd: Path,
    cursor_agent_model: str,
    allowed_tools: str | None = None,
    resume: str | None = None,
    on_chunk: StreamCallback | None = None,
) -> dict[str, Any]:
    """Run headless CLI with the assembled packet as system context + prompt."""
    if backend == "claude" and claude_code.available():
        return claude_code.run_print(
            "Follow the system instructions and write requested artifacts.",
            cwd=project_cwd,
            system_append=packet,
            allowed_tools=allowed_tools or "Read,Write,Edit,Bash",
            resume_session=resume,
            on_chunk=on_chunk,
        )
    if backend == "cursor" and cursor_cli.available():
        return cursor_cli.run_agent_print(
            packet,
            model=cursor_agent_model,
            cwd=project_cwd,
            trust=True,
            force=True,
            resume=resume,
            on_chunk=on_chunk,
        )
    return {
        "ok": False,
        "error": "no CLI backend available",
        "parsed": {"note": "Install claude or use cursor agent CLI"},
    }
