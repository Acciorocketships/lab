"""Invoke Cursor agent CLI in print mode with optional streaming."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

_DEFAULT_TIMEOUT = 180

StreamCallback = Callable[[str], None]


def available() -> bool:
    """True if `cursor` is on PATH."""
    return shutil.which("cursor") is not None


def _resolve_timeout_sec(explicit: int | None) -> int:
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get("AIRESEARCHER_CURSOR_TIMEOUT_SEC", str(_DEFAULT_TIMEOUT))
    try:
        return max(1, int(raw.strip(), 10))
    except ValueError:
        return _DEFAULT_TIMEOUT


def _build_cmd(
    prompt: str,
    *,
    output_format: str = "json",
    trust: bool = True,
    force: bool = False,
    resume: str | None = None,
) -> list[str] | None:
    exe = shutil.which("cursor")
    if not exe:
        return None
    cmd: list[str] = [exe, "agent", "-p", prompt]
    if trust:
        cmd.append("--trust")
    if force:
        cmd.append("--force")
    cmd.extend(["--output-format", output_format])
    if resume:
        cmd.extend(["--resume", resume])
    return cmd


def run_agent_print(
    prompt: str,
    *,
    cwd: Path,
    output_format: str = "json",
    trust: bool = True,
    force: bool = False,
    resume: str | None = None,
    timeout_sec: int | None = None,
    on_chunk: StreamCallback | None = None,
) -> dict[str, Any]:
    """Run `cursor agent -p` (headless) with optional line-by-line streaming via *on_chunk*."""
    cmd = _build_cmd(prompt, output_format=output_format, trust=trust, force=force, resume=resume)
    if cmd is None:
        return {"ok": False, "error": "cursor CLI not found", "stdout": "", "stderr": ""}
    limit = _resolve_timeout_sec(timeout_sec)

    if on_chunk is not None:
        return _run_streaming(cmd, cwd=cwd, limit=limit, on_chunk=on_chunk)
    return _run_blocking(cmd, cwd=cwd, limit=limit)


def _run_blocking(cmd: list[str], *, cwd: Path, limit: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": f"cursor agent timed out after {limit}s",
            "exit_code": -1,
            "stdout": (e.stdout or "").strip() if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "").strip() if isinstance(e.stderr, str) else "",
            "parsed": {"error": "timeout", "timeout_sec": limit},
        }
    except OSError as e:
        return {
            "ok": False, "error": f"cursor agent failed to start: {e}",
            "exit_code": -1, "stdout": "", "stderr": str(e), "parsed": {"error": "os_error"},
        }
    return _parse_result(proc.returncode, proc.stdout, proc.stderr)


def _run_streaming(
    cmd: list[str], *, cwd: Path, limit: int, on_chunk: StreamCallback,
) -> dict[str, Any]:
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except OSError as e:
        return {
            "ok": False, "error": f"cursor agent failed to start: {e}",
            "exit_code": -1, "stdout": "", "stderr": str(e), "parsed": {"error": "os_error"},
        }

    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    stdout_parts: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_parts.append(line)
        stripped = line.rstrip("\n\r")
        if stripped:
            on_chunk(stripped)

    try:
        proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        return {
            "ok": False, "error": f"cursor agent timed out after {limit}s",
            "exit_code": -1,
            "stdout": "".join(stdout_parts).strip(),
            "stderr": "".join(stderr_lines).strip(),
            "parsed": {"error": "timeout", "timeout_sec": limit},
        }
    t.join(timeout=5)
    return _parse_result(proc.returncode, "".join(stdout_parts), "".join(stderr_lines))


def _parse_result(returncode: int | None, stdout: str, stderr: str) -> dict[str, Any]:
    out = stdout.strip()
    err = stderr.strip()
    parsed: Any = None
    if out:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}
    return {
        "ok": (returncode or 0) == 0,
        "exit_code": returncode or 0,
        "stdout": out,
        "stderr": err,
        "parsed": parsed,
    }
