"""Second block in worker packets (after **Role**): Tier A / memory rules. See `packets.build_worker_packet`."""

from __future__ import annotations

# Paths: `data/runtime/state/` — full list in memory.TIER_A_FILES; `memory_guide.md` is the long-form spec.
MEMORY_AND_TIER_A = """**Tier A** (`state/*.md`) and `memory/extended/`: keep them current.

**Long text:** keep Tier A short; park detail in `data/runtime/memory/extended/<name>.md` and cite the path here. Packets do not inline extended bodies—read those paths with tools.

**Tier A files** (`state/*.md` — meanings):
- **`project_brief.md`** — project identity, scope, constraints the repo must respect.
- **`memory_guide.md`** — how to use tiers, extended, branch files, episodes (normative reference).
- **`research_idea.md`** — research brief: goals, approach, and implicit success criteria (what “done” means).
- **`preferences.md`** — operator preferences (tone, tools, citation style, etc.).
- **`roadmap.md`** — durable end-to-end plan (phases, milestones); include completed lines; on scope change, retcon the **whole** file into one coherent story.
- **`immediate_plan.md`** — **only** the current chunk (Cursor-style steps); when the chunk finishes, clear/replace—no stale checklists.
- **`status.md`** — live snapshot: blockers, current focus, last meaningful change.
- **`skills_index.md`** — table of `memory/skills/*.md` entries; keep aligned when you add skills.
- **`lessons.md`** — short durable takeaways; also record abandoned approaches/branches.
- **`user_instructions.md`** — console queue under **`## New`**: merge into **`immediate_plan.md`** / **`roadmap.md`**, then remove from **`## New`** (optional **`## In progress`** / **`## Completed`**); never leave merged items in **`## New`**. Act immediately; if you are not planner, still capture intent in Tier A and clear **`## New`** or leave a one-line planner handoff. **Long runs** (multi-step, slow tools, >few min): re-read this file ~every **2–3 min** for new **`## New`** bullets.

**Branch memory** (`data/runtime/memory/branch/<b>.md`): branch name `/`→`__`. Per active branch you touch: diverged-from (SHA/tag), purpose, status/results. Merge to **main** → delete file (optional copy to `extended/`). Abandoned/failed → delete file + note in **`lessons.md`**.

**Experiments:** link experiment dirs/metrics from Tier A or extended so the next run can find them.

Update memory **in the same run** when your work changes truth—do not assume a later pass fixes it."""

# Back-compat alias
SHARED_SUBAGENT_SYSTEM = MEMORY_AND_TIER_A
SUPPLEMENTARY_TIER_A_AND_MEMORY = MEMORY_AND_TIER_A
