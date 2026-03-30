"""Hooks for domain-specific metrics, objectives, and experiment runners.

Core orchestration imports only this module's protocols when extended.
"""

from __future__ import annotations

from typing import Any, Protocol


class DomainHooks(Protocol):
    """Optional domain plugin: metrics keys, baseline paths, run commands."""

    def primary_metric_key(self) -> str:
        """Metric name used for keep/revert."""
        ...

    def run_baseline(self, project_dir: str) -> dict[str, Any]:
        """Return metrics dict for baseline run."""
        ...
