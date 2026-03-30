"""Invoke Claude Code CLI in headless print mode with optional streaming."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

StreamCallback = Callable[[str], None]


def available() -> bool:
    """True if `claude` is on PATH."""
    return shutil.which("claude") is not None


def _build_cmd(
    prompt: str,
    *,
    system_append: str | None = None,
    max_turns: int = 25,
    allowed_tools: str | None = None,
    resume_session: str | None = None,
) -> list[str] | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    cmd: list[str] = [exe, "-p", "--output-format", "json", "--max-turns", str(max_turns)]
    if system_append:
        cmd.extend(["--append-system-prompt", system_append])
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])
    if resume_session:
        cmd.extend(["--resume", resume_session])
    cmd.append(prompt)
    return cmd


def run_print(
    prompt: str,
    *,
    cwd: Path,
    system_append: str | None = None,
    max_turns: int = 25,
    allowed_tools: str | None = None,
    resume_session: str | None = None,
    timeout_sec: int = 600,
    on_chunk: StreamCallback | None = None,
) -> dict[str, Any]:
    """Run `claude -p` and parse JSON output when possible."""
    cmd = _build_cmd(
        prompt,
        system_append=system_append,
        max_turns=max_turns,
        allowed_tools=allowed_tools,
        resume_session=resume_session,
    )
    if cmd is None:
        return {"ok": False, "error": "claude CLI not found", "stdout": "", "stderr": ""}

    if on_chunk is not None:
        return _run_streaming(cmd, cwd=cwd, limit=timeout_sec, on_chunk=on_chunk)
    return _run_blocking(cmd, cwd=cwd, limit=timeout_sec)


def _run_blocking(cmd: list[str], *, cwd: Path, limit: int) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=limit)
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
            "ok": False, "error": f"claude failed to start: {e}",
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
            "ok": False, "error": f"claude timed out after {limit}s",
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
