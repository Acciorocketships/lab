"""Small reusable helpers used across the package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    """Create directory if missing; used when writing runtime artifacts."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path, default: str = "") -> str:
    """Read UTF-8 text or return default if missing."""
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent dirs."""
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    """Load JSON or return default if missing/invalid."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    """Write pretty JSON."""
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
