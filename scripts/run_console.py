"""Run only the Textual console (expects scheduler elsewhere or manual DB)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "project_stub"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"


def main() -> None:
    """Start TUI against existing DB."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    db_path = RESEARCHER_ROOT / "data" / "runtime.db"
    from research_lab.ui.console import run_console

    run_console(db_path)


if __name__ == "__main__":
    main()
