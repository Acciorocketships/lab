"""Second block in worker packets (after **Role**): Tier A / memory rules. See `packets.build_worker_packet`."""

from __future__ import annotations

# Paths: `data/runtime/state/` — full list in memory.TIER_A_FILES.
MEMORY_AND_TIER_A = """**Tier A** means `.airesearcher/data/runtime/state/*.md`, not a project-root `state/` folder. Keep those files current, along with `.airesearcher/data/runtime/memory/extended/`.

All workers share responsibility for maintaining Tier A. If your run changes project truth, plans, status, durable lessons, or creates long-form memory elsewhere, update the relevant Tier A files in the same run. Do not assume planner or a later worker will clean this up for you. If a file's truth did not change, leave it alone.

**Tier A files** (`.airesearcher/data/runtime/state/*.md` — meanings):
- **`project_brief.md`** — project identity, scope, and constraints the repo must respect. Update when the project framing, boundaries, non-goals, or hard constraints change.
- **`extended_memory_index.md`** — index of `memory/extended/` only. Keep this current alongside the rest of Tier A. When you add or materially update a file under `memory/extended/`, add or refresh the matching index entry. Each entry should point to one long-form file and give a brief description or a few high-level bullets about what the full file contains, so future workers can decide whether to open it.
- **`research_idea.md`** — research brief: goals, approach, and implicit success criteria (what “done” means). Update when the core problem statement, hypothesis, evaluation target, or success criteria change.
- **`preferences.md`** — user preferences to guide the project. Usually user-maintained; agents should only edit it when explicitly asked or when the workflow clearly treats a new durable preference as established project policy.
- **`roadmap.md`** — durable end-to-end plan (phases, milestones). Update when scope, sequencing, or completion status changes; include completed lines; on scope change, retcon the **whole** file into one coherent story.
- **`immediate_plan.md`** — a more granular plan for the current step in the roadmap. When using planning for implementation or other actions, the current chunk should go here. This is **only** the current chunk; while work is in progress, keep it current; when the chunk finishes, clear or replace it. Prefer iterative chunks that establish a simple working baseline or proof of concept first, then add detail or components in later cycles.
- **`status.md`** — live snapshot: blockers, current focus, last meaningful change. Update whenever your run changes the active focus, progress state, blocker picture, or latest significant result.
- **`skills_index.md`** — table of `memory/skills/*.md` entries. Keep aligned when you add, rename, remove, or substantially revise skills.
- **`lessons.md`** — short durable takeaways. Add concise lessons when you discover reusable guidance, hit an important pitfall, abandon an approach, or close out a failed branch.
- **`user_instructions.md`** — user-maintained queue under **`## New`**. The user or control layer may append items there. Agents should treat those bullets as actionable input: merge them into **`immediate_plan.md`** and/or **`roadmap.md`**, then remove them from **`## New`** (optional **`## In progress`** / **`## Completed`**); never leave merged items in **`## New`**. Act immediately; if you are not planner, still capture intent in Tier A and clear **`## New`** or leave a one-line planner handoff. **Long runs** (multi-step, slow tools, >few min): re-read this file ~every **2–3 min** for new **`## New`** bullets.

**Branch memory** (`data/runtime/memory/branch/<b>.md`): branch name `/`→`__`. Per active branch you touch: diverged-from (SHA/tag), purpose, status/results. Merge to **main** → delete file (optional copy to `extended/`). Abandoned/failed → delete file + note in **`lessons.md`**.

**Episodes** (`data/runtime/memory/episodes/`): run-by-run packets and worker outputs are auto-populated here. Do not write to this; it is only for looking up context on past subagents actions, if needed.

**Experiments:** link experiment dirs, outputs, and metrics from Tier A or extended so the next run can find them.

Update memory **in the same run** when your work changes truth—do not assume a later pass fixes it.

**Extended files / catalog:** Tier A should stay short: usually just a few lines per concept. Use `data/runtime/memory/extended/<name>.md` for long logs, raw artifacts, detailed findings, expanded notes, transcripts, or other material that is too long to fit cleanly in Tier A. When you add or update an extended file, do two things in the same run: put a short pointer in the Tier A file where that information matters, and add or refresh an entry in **`extended_memory_index.md`** describing what is in the file. The more important the material is, the longer the Tier A excerpt can be, but keep Tier A distilled and high-signal. Extended file bodies are **not** inlined into packets—if someone needs the unabridged version later, they should open that file explicitly with tools (or have a subagent do it)."""
