"""End-to-end tests: run the real graph on a toy Fibonacci problem with deterministic stubs.

Unlike test_context_integration.py (which exercises subsystems with mocked boundaries),
these tests drive the full LangGraph pipeline (ingest → choose → worker → update)
through multiple cycles.  The LLM and worker CLI are replaced with deterministic stubs
that simulate realistic behaviour (including file edits); everything else — memory layout,
packet assembly, episode persistence, DB state transitions — runs for real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from research_lab import db, helpers, memory
from research_lab.config import RunConfig
from research_lab.orchestrator import OrchestratorDecision
from research_lab.state import ResearchState
from research_lab.workflows import research_graph


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path) -> RunConfig:
    return RunConfig(
        researcher_root=tmp_path,
        project_dir=tmp_path / "project",
        research_idea="Compute the 10th Fibonacci number and verify the result is 55",
        preferences="Use Python, keep it simple",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
    )


def _initial_state(cycle: int = 0) -> ResearchState:
    return {
        "current_goal": "continue",
        "current_branch": "",
        "current_worker": "planner",
        "cycle_count": cycle,
        "control_mode": "active",
        "pending_instructions": [],
        "last_action_summary": "",
        "roadmap_step": "",
        "orchestrator_task": "",
        "orchestrator_reason": "",
        "acceptance_satisfied": False,
        "shutdown_requested": False,
        "worker_kwargs": {},
    }


# Pre-scripted orchestrator decisions.  Each context_summary intentionally
# accumulates facts so we can verify information carries forward.
_FIBONACCI_DECISIONS = [
    OrchestratorDecision(
        worker="planner",
        task="Create a roadmap to compute the 10th Fibonacci number",
        reason="New project, need a plan first",
        roadmap_step="planning",
        context_summary=(
            "Project goal: compute 10th Fibonacci number (expected 55). "
            "Phase: planning. No work done yet."
        ),
    ),
    OrchestratorDecision(
        worker="implementer",
        task="Implement fibonacci.py with an iterative fib() function",
        reason="Plan complete, moving to implementation",
        roadmap_step="implementation",
        context_summary=(
            "Project goal: compute 10th Fibonacci (expected 55). "
            "Planner created 3-phase roadmap (plan, implement, verify). "
            "Phase: implementation."
        ),
    ),
    OrchestratorDecision(
        worker="experimenter",
        task="Run fibonacci.py and verify fib(10) == 55",
        reason="Implementation done, need to verify result",
        roadmap_step="verification",
        context_summary=(
            "Project goal: compute 10th Fibonacci (expected 55). "
            "Planner created 3-phase roadmap. "
            "Implementer wrote fibonacci.py (iterative approach). "
            "Phase: verification."
        ),
    ),
    OrchestratorDecision(
        worker="done",
        task="Project complete",
        reason="Fibonacci computed and verified: fib(10)=55",
        roadmap_step="complete",
        context_summary=(
            "COMPLETE. 10th Fibonacci is 55. Computed via fibonacci.py, "
            "verified experimentally. All 3 roadmap phases finished."
        ),
    ),
]


class ScriptedOrchestrator:
    """Returns pre-scripted decisions and captures the context string at each call."""

    def __init__(self, decisions: list[OrchestratorDecision]):
        self.decisions = decisions
        self.call_count = 0
        self.contexts_received: list[str] = []

    def __call__(self, context_md: str, *, model: str, cfg: RunConfig) -> OrchestratorDecision:
        self.contexts_received.append(context_md)
        dec = self.decisions[self.call_count]
        self.call_count += 1
        return dec


class ScriptedWorker:
    """Writes side-effect files (simulating a real CLI agent) and returns deterministic results."""

    def __init__(self, researcher_root: Path, project_dir: Path):
        self.researcher_root = researcher_root
        self.project_dir = project_dir
        self.call_count = 0
        self.packets_received: list[str] = []

    def __call__(
        self,
        pkt: str,
        *,
        backend: str,
        project_cwd: Path,
        cursor_agent_model: str,
        on_chunk: Any = None,
        **kw: Any,
    ) -> dict[str, Any]:
        self.packets_received.append(pkt)
        result = [self._planner, self._implementer, self._experimenter][self.call_count]()
        self.call_count += 1
        return result

    def _planner(self) -> dict[str, Any]:
        sd = memory.state_dir(self.researcher_root)
        helpers.write_text(
            sd / "roadmap.md",
            "# Roadmap\n\n"
            "## Phases\n\n"
            "1. **Planning** — define approach\n"
            "2. **Implementation** — write fibonacci.py\n"
            "3. **Verification** — run and check fib(10)==55\n\n"
            "## Done when\n\nfib(10) verified to equal 55.\n",
        )
        helpers.write_text(
            sd / "immediate_plan.md",
            "# Immediate plan\n\n"
            "1. Create fibonacci.py with iterative fib() function\n"
            "2. Run fib(10) and assert result == 55\n",
        )
        helpers.write_text(sd / "status.md", "# Status\n\nPlanning complete. Ready for implementation.\n")
        return {"ok": True, "parsed": {"result": "Created 3-phase roadmap: plan, implement, verify"}}

    def _implementer(self) -> dict[str, Any]:
        helpers.write_text(
            self.project_dir / "fibonacci.py",
            "def fib(n: int) -> int:\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n):\n"
            "        a, b = b, a + b\n"
            "    return a\n",
        )
        helpers.write_text(
            memory.state_dir(self.researcher_root) / "status.md",
            "# Status\n\nImplementation complete. fibonacci.py written.\n",
        )
        return {"ok": True, "parsed": {"result": "Implemented fibonacci.py with iterative fib() function"}}

    def _experimenter(self) -> dict[str, Any]:
        helpers.write_text(
            memory.state_dir(self.researcher_root) / "status.md",
            "# Status\n\nVerification complete. fib(10) = 55 confirmed.\n",
        )
        return {"ok": True, "parsed": {"result": "Ran fib(10) = 55, matches expected value"}}


# ---------------------------------------------------------------------------
# 1. Full run_loop on the Fibonacci toy problem
# ---------------------------------------------------------------------------


def test_toy_fibonacci_full_loop(tmp_path: Path) -> None:
    """4-cycle run: planner → implementer → experimenter → done.

    Verifies context carryforward, memory file edits, episode artifacts,
    and DB state across a complete autonomous run on a concrete problem.
    """
    researcher_root = tmp_path
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)

    memory.ensure_memory_layout(researcher_root)
    helpers.write_text(
        memory.state_dir(researcher_root) / "research_idea.md",
        "# Research idea\n\nCompute the 10th Fibonacci number and verify the result is 55.\n",
    )

    orch = ScriptedOrchestrator(list(_FIBONACCI_DECISIONS))
    worker = ScriptedWorker(researcher_root, project_dir)

    with (
        patch.object(research_graph.orchestrator, "decide_orchestrator", orch),
        patch.object(research_graph.agents_base, "run_worker", worker),
        patch.object(research_graph.time, "sleep", lambda _: None),
    ):
        research_graph.run_loop(
            cfg,
            db_path=db_path,
            researcher_root=researcher_root,
            project_dir=project_dir,
            checkpoint_path=tmp_path / "checkpoint.db",
        )

    # ---- Call counts ----
    assert orch.call_count == 4, "Orchestrator should be called once per cycle"
    assert worker.call_count == 3, "Worker CLI is called for cycles 1-3 (done skips)"

    # ---- Context carryforward (orchestrator sees prior summaries) ----
    # Cycle 2: should contain planning info from cycle 1
    ctx2 = orch.contexts_received[1]
    assert "planning" in ctx2.lower(), "Cycle-2 context must include planning phase info"

    # Cycle 3: should mention the roadmap + implementation phase
    ctx3 = orch.contexts_received[2]
    assert "3-phase" in ctx3 or "roadmap" in ctx3.lower(), "Cycle-3 context must mention roadmap"
    assert "implementation" in ctx3.lower()

    # Cycle 4: should reference fibonacci.py or iterative approach
    ctx4 = orch.contexts_received[3]
    assert "fibonacci" in ctx4.lower(), "Cycle-4 context must mention fibonacci.py"

    # ---- Worker packets carry rolling summary ----
    pkt2 = worker.packets_received[1]  # implementer
    assert "## Rolling context summary" in pkt2, "Implementer packet needs rolling summary section"
    assert "planning" in pkt2.lower(), "Implementer packet should carry planning summary"

    pkt3 = worker.packets_received[2]  # experimenter
    assert "## Rolling context summary" in pkt3
    assert "implementation" in pkt3.lower(), "Experimenter packet should carry implementation info"

    # Packets also contain Tier A state (e.g. roadmap updated by planner)
    assert "fibonacci.py" in pkt2 or "Implementation" in pkt2
    assert "fibonacci" in pkt3.lower()

    # ---- Tier A files reflect worker edits ----
    roadmap = helpers.read_text(memory.state_dir(researcher_root) / "roadmap.md")
    assert "Implementation" in roadmap and "Verification" in roadmap

    plan = helpers.read_text(memory.state_dir(researcher_root) / "immediate_plan.md")
    assert "fibonacci.py" in plan

    status = helpers.read_text(memory.state_dir(researcher_root) / "status.md")
    assert "fib(10) = 55" in status

    # ---- Context summary has final accumulated knowledge ----
    cs = memory.read_context_summary(researcher_root)
    assert "55" in cs and "COMPLETE" in cs

    # ---- Project file was created by implementer ----
    assert (project_dir / "fibonacci.py").exists()
    assert "def fib" in helpers.read_text(project_dir / "fibonacci.py")

    # ---- Episode artifacts (packet.md + worker_output.json per cycle) ----
    for cycle, w in [(1, "planner"), (2, "implementer"), (3, "experimenter")]:
        ep = memory.episode_cycle_dir(researcher_root, cycle, w)
        assert (ep / "packet.md").exists(), f"cycle {cycle} missing packet.md"
        assert (ep / "worker_output.json").exists(), f"cycle {cycle} missing worker_output.json"
        out = json.loads((ep / "worker_output.json").read_text(encoding="utf-8"))
        assert out["ok"] is True

    # On-disk packet should match what was passed to the worker
    ondisk_pkt2 = helpers.read_text(
        memory.episode_cycle_dir(researcher_root, 2, "implementer") / "packet.md"
    )
    assert ondisk_pkt2 == pkt2, "Persisted packet must equal what run_worker received"

    # done (cycle 4) must NOT create episode files
    assert not memory.episode_cycle_dir(researcher_root, 4, "done").exists()

    # Episode index lists cycles 1-3
    idx = helpers.read_text(memory.episodes_dir(researcher_root) / "index.md")
    for cycle in (1, 2, 3):
        assert f"Cycle {cycle}" in idx
    assert "planner" in idx and "implementer" in idx and "experimenter" in idx

    # ---- DB: system_state ----
    conn = db.connect_db(db_path)
    st = db.get_system_state(conn)
    assert st["cycle_count"] == 4
    assert st["control_mode"] == "paused"
    assert st["current_worker"] == "done"

    # ---- DB: run_events ----
    rows = list(conn.execute(
        "SELECT cycle, kind, worker, summary FROM run_events ORDER BY id"
    ))
    conn.close()

    assert len(rows) == 8, f"Expected 8 run_events (4 orch + 4 worker), got {len(rows)}"

    orch_rows = [r for r in rows if r["kind"] == "orchestrator"]
    worker_rows = [r for r in rows if r["kind"] == "worker"]
    assert [r["worker"] for r in orch_rows] == ["planner", "implementer", "experimenter", "done"]
    assert [r["worker"] for r in worker_rows] == ["planner", "implementer", "experimenter", "done"]
    assert [r["cycle"] for r in orch_rows] == [1, 2, 3, 4]
    assert [r["cycle"] for r in worker_rows] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# 2. User instruction mid-run forces planner override
# ---------------------------------------------------------------------------


def test_user_instruction_override_through_real_graph(tmp_path: Path) -> None:
    """Enqueue a user instruction, run two graph cycles, and verify:
    - Cycle 1: orchestrator's "implementer" choice is overridden to planner
    - Cycle 2: with ## New cleared, orchestrator's choice is respected
    Also checks that the instruction text propagates into the orchestrator context
    and the worker packet, and that DB state is consistent throughout.
    """
    researcher_root = tmp_path
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    db_path = tmp_path / "runtime.db"
    cfg = _cfg(tmp_path)

    memory.ensure_memory_layout(researcher_root)
    helpers.write_text(
        memory.state_dir(researcher_root) / "research_idea.md",
        "# Research idea\n\nCompute Fibonacci numbers.\n",
    )

    conn = db.connect_db(db_path)
    db.get_system_state(conn)
    db.enqueue_event(conn, "instruction", "Also try a memoized approach")
    conn.commit()
    conn.close()

    override_decisions = [
        OrchestratorDecision(
            worker="implementer",  # will be overridden to planner
            task="Implement something",
            reason="test reason",
            roadmap_step="step-1",
            context_summary="Summary after override cycle.",
        ),
        OrchestratorDecision(
            worker="researcher",
            task="Research memoization techniques",
            reason="following up on memoized approach",
            roadmap_step="step-2",
            context_summary="Summary after second cycle. Memoized approach noted.",
        ),
    ]
    orch = ScriptedOrchestrator(override_decisions)

    worker_packets: list[str] = []
    worker_call = [0]

    def fake_worker(pkt, *, backend, project_cwd, cursor_agent_model, on_chunk=None, **kw):
        worker_packets.append(pkt)
        idx = worker_call[0]
        worker_call[0] += 1
        if idx == 0:
            # Planner clears ## New and integrates instruction into plan
            helpers.write_text(
                memory.state_dir(researcher_root) / "user_instructions.md",
                "# User instructions\n\n## New\n\n## In progress\n\n"
                "- Also try a memoized approach\n\n## Completed\n\n",
            )
            helpers.write_text(
                memory.state_dir(researcher_root) / "immediate_plan.md",
                helpers.read_text(memory.state_dir(researcher_root) / "immediate_plan.md")
                + "\n## Memoized approach\n\n- Explore memoized Fibonacci\n",
            )
            return {"ok": True, "parsed": {"result": "Integrated user instruction into plan"}}
        return {"ok": True, "parsed": {"result": "Researched memoization"}}

    with (
        patch.object(research_graph.orchestrator, "decide_orchestrator", orch),
        patch.object(research_graph.agents_base, "run_worker", fake_worker),
    ):
        app = research_graph.build_graph(
            cfg, db_path=db_path, researcher_root=researcher_root, project_dir=project_dir,
        )

        # ---- Cycle 1: instruction pending → planner override ----
        out1 = app.invoke(_initial_state())

        assert out1["current_worker"] == "planner", (
            f"Expected planner override, got {out1['current_worker']}"
        )

        # Instruction event was consumed
        conn = db.connect_db(db_path)
        assert db.fetch_pending_events(conn) == []
        # Instruction recorded in instructions table
        inst_rows = db.list_instructions(conn, status="new")
        assert any("memoized" in str(dict(r)).lower() for r in inst_rows)
        conn.close()

        # ## New is cleared (planner did its job)
        assert not memory.user_instructions_new_has_pending(researcher_root)

        # Instruction merged into the plan
        plan = helpers.read_text(memory.state_dir(researcher_root) / "immediate_plan.md")
        assert "memoized" in plan.lower()

        # Orchestrator context contained the instruction text (user_instructions.md is Tier A)
        assert "memoized" in orch.contexts_received[0].lower()

        # The planner packet included the instruction
        assert "memoized" in worker_packets[0].lower()

        # DB run_event records the overridden worker (planner, not implementer)
        conn = db.connect_db(db_path)
        orch_row = conn.execute(
            "SELECT worker FROM run_events WHERE kind='orchestrator' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.close()
        assert orch_row["worker"] == "planner", "DB must record the overridden worker"

        # ---- Cycle 2: ## New is clear → orchestrator choice is respected ----
        state2 = research_graph._state_from_db(db_path)
        out2 = app.invoke(state2)

    assert out2["current_worker"] == "researcher", (
        f"With ## New cleared, orchestrator choice should be respected, got {out2['current_worker']}"
    )

    # Cycle-2 context carries forward the summary from cycle 1
    assert "Summary after override cycle" in orch.contexts_received[1]

    # Both cycles have run_events in the DB
    conn = db.connect_db(db_path)
    all_events = list(conn.execute("SELECT kind, worker, cycle FROM run_events ORDER BY id"))
    conn.close()
    assert len(all_events) == 4  # 2 orchestrator + 2 worker
    assert [r["worker"] for r in all_events if r["kind"] == "orchestrator"] == ["planner", "researcher"]
