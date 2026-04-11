"""Long-running process monitor: poll PID, tail logs, emit wake signals via callback."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path


def poll_process(pid: int) -> bool:
    """Return True if process exists."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def watch_until(
    pid: int,
    log_path: Path | None,
    *,
    on_line: Callable[[str], None] | None = None,
    stall_seconds: float = 600.0,
    poll_interval: float = 2.0,
) -> str:
    """Poll pid until exit or stall (no log growth). Returns 'finished' or 'stalled'."""
    last_size = log_path.stat().st_size if log_path and log_path.exists() else 0
    last_growth = time.time()
    while poll_process(pid):
        if log_path and log_path.exists():
            sz = log_path.stat().st_size
            if sz > last_size:
                last_size = sz
                last_growth = time.time()
                if on_line and sz < 2_000_000:
                    tail = log_path.read_text(encoding="utf-8", errors="ignore")[-4000:]
                    on_line(tail)
            elif time.time() - last_growth > stall_seconds:
                return "stalled"
        time.sleep(poll_interval)
    return "finished"
