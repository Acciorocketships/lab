"""Invoke Claude Code CLI in headless print mode with optional streaming."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

StreamCallback = Callable[[str], None]


def available() -> bool:
    """True if `claude` is on PATH."""
    return shutil.which("claude") is not None


def _resolve_timeout_sec(explicit: int | None) -> int | None:
    """Seconds cap for subprocess, or None for no limit (default)."""
    if explicit is not None:
        return None if explicit <= 0 else explicit
    raw = os.environ.get("LAB_CLAUDE_TIMEOUT_SEC")
    if raw is None or raw.strip() == "":
        return None
    try:
        n = int(raw.strip(), 10)
    except ValueError:
        return None
    return None if n <= 0 else n


def _build_cmd(
    prompt: str,
    *,
    system_append: str | None = None,
    max_turns: int = 25,
    allowed_tools: str | None = None,
    resume_session: str | None = None,
    output_format: str = "json",
) -> list[str] | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    cmd: list[str] = [exe, "-p", "--output-format", output_format, "--max-turns", str(max_turns)]
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
    timeout_sec: int | None = None,
    on_chunk: StreamCallback | None = None,
) -> dict[str, Any]:
    """Run `claude -p` and parse JSON output when possible.

    *timeout_sec*: cap in seconds, or ``None`` / ``<= 0`` for no cap (default). Env
    ``LAB_CLAUDE_TIMEOUT_SEC`` applies when *timeout_sec* is omitted.
    """
    effective_format = "stream-json" if on_chunk is not None else "json"
    cmd = _build_cmd(
        prompt,
        system_append=system_append,
        max_turns=max_turns,
        allowed_tools=allowed_tools,
        resume_session=resume_session,
        output_format=effective_format,
    )
    if cmd is None:
        return {"ok": False, "error": "claude CLI not found", "stdout": "", "stderr": ""}

    limit = _resolve_timeout_sec(timeout_sec)
    if on_chunk is not None:
        return _run_streaming(cmd, cwd=cwd, limit=limit, on_chunk=on_chunk)
    return _run_blocking(cmd, cwd=cwd, limit=limit)


def _run_blocking(cmd: list[str], *, cwd: Path, limit: int | None) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": f"claude timed out after {limit}s",
            "exit_code": -1,
            "stdout": (e.stdout or "").strip() if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "").strip() if isinstance(e.stderr, str) else "",
            "parsed": {"error": "timeout", "timeout_sec": limit},
        }
    except OSError as e:
        return {
            "ok": False, "error": f"claude failed to start: {e}",
            "exit_code": -1, "stdout": "", "stderr": str(e), "parsed": {"error": "os_error"},
        }
    return _parse_result(proc.returncode, proc.stdout, proc.stderr)


def _run_streaming(
    cmd: list[str], *, cwd: Path, limit: int | None, on_chunk: StreamCallback,
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

    # stream-json / JSONL: look for the last {"type":"result",...} line
    for line in reversed(out.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("type") == "result":
                return {
                    "ok": not obj.get("is_error", False),
                    "exit_code": returncode or 0,
                    "stdout": out,
                    "stderr": err,
                    "parsed": obj,
                }
        except (json.JSONDecodeError, TypeError):
            continue

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
