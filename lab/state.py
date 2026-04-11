"""LangGraph shared state schema (minimal routing signals; rich context lives in files)."""

from __future__ import annotations

from typing import Annotated, TypedDict

import operator


class ResearchState(TypedDict, total=False):
    """Checkpointed orchestration state; keep small — details live on disk."""

    current_goal: str
    current_branch: str
    current_worker: str
    cycle_count: int
    control_mode: str
    pending_instructions: Annotated[list[str], operator.add]
    last_action_summary: str
    roadmap_step: str
    orchestrator_task: str
    orchestrator_reason: str
    rolling_context_summary: str
    last_packet_relpath: str
    worker_ok: bool
    acceptance_satisfied: bool
    shutdown_requested: bool
    worker_kwargs: dict[str, str]
