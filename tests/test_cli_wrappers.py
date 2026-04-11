"""CLI wrappers return structured dicts when binaries missing."""

from pathlib import Path

from lab.tools import claude_code, cursor_cli


def test_claude_missing(tmp_path: Path) -> None:
    """run_print returns a structured dict; when failing, includes error signal."""
    r = claude_code.run_print("hi", cwd=tmp_path)
    if r.get("ok") is False:
        err = (r.get("error") or "").lower()
        blob = (str(r) + (r.get("stderr") or "")).lower()
        assert (
            "claude" in err
            or "not found" in blob
            or r.get("parsed") is not None
            or r.get("exit_code", 0) != 0
        )


def test_cursor_available_flag() -> None:
    """Module exposes availability check."""
    assert isinstance(cursor_cli.available(), bool)
