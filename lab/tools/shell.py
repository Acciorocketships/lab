"""Sandboxed subprocess helper for tests and experiments."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_cmd(argv: list[str], cwd: Path, timeout: int = 3600) -> tuple[int, str, str]:
    """Run argv under cwd; return code, stdout, stderr."""
    proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr
