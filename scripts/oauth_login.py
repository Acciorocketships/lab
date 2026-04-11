"""OAuth login helper — delegates to :func:`lab.runner.run_oauth_browser_for_global`."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    from lab.runner import run_oauth_browser_for_global

    run_oauth_browser_for_global()


if __name__ == "__main__":
    main()
