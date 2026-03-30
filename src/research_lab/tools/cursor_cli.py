"""Invoke Cursor agent CLI in print mode."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def available() -> bool:
    """True if `cursor` is on PATH."""
    return shutil.which("cursor") is not None


def run_agent_print(
    prompt: str,
    *,
    cwd: Path,
    output_format: str = "json",
    trust: bool = True,
    force: bool = False,
    resume: str | None = None,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run `cursor agent -p` (headless)."""
    exe = shutil.which("cursor")
    if not exe:
        return {"ok": False, "error": "cursor CLI not found", "stdout": "", "stderr": ""}
    cmd: list[str] = [exe, "agent", "-p", "--output-format", output_format]
    if trust:
        cmd.append("--trust")
    if force:
        cmd.append("--force")
    if resume:
        cmd.extend(["--resume", resume])
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
