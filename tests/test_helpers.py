"""Tests for helpers."""

import json
from pathlib import Path

from lab import helpers


def test_write_read_json(tmp_path: Path) -> None:
    """JSON round-trip."""
    p = tmp_path / "x.json"
    helpers.write_json(p, {"a": 1})
    assert helpers.read_json(p, {}) == {"a": 1}
