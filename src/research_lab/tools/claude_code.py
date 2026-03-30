"""Invoke Claude Code CLI in headless print mode."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def available() -> bool:
    """True if `claude` is on PATH."""
    return shutil.which("claude") is not None


def run_print(
    prompt: str,
    *,
    cwd: Path,
    system_append: str | None = None,
    max_turns: int = 25,
    allowed_tools: str | None = None,
    resume_session: str | None = None,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run `claude -p` and parse JSON output when possible."""
    exe = shutil.which("claude")
    if not exe:
        return {"ok": False, "error": "claude CLI not found", "stdout": "", "stderr": ""}
    cmd: list[str] = [exe, "-p", "--output-format", "json", "--max-turns", str(max_turns)]
    if system_append:
        cmd.extend(["--append-system-prompt", system_append])
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])
    if resume_session:
        cmd.extend(["--resume", resume_session])
    cmd.append(prompt)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    parsed: Any = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": out,
        "stderr": err,
        "parsed": parsed,
    }
