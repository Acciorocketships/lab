"""Second block in worker packets (after **Role**): Tier A / memory rules. See `packets.build_worker_packet`."""

from __future__ import annotations

# Paths: `data/runtime/state/` — full list in memory.TIER_A_FILES.
MEMORY_AND_TIER_A = """**Tier A** (`state/*.md`) and `memory/extended/`: keep them current.

**Tier A files** (`state/*.md` — meanings):
- **`project_brief.md`** — project identity, scope, constraints the repo must respect.
- **`extended_memory_index.md`** — **you maintain this:** index of `memory/extended/` only. Each entry should point to one long-form file and give a brief description or a few high-level bullets about what the full file contains, so future workers can decide whether to open it.
- **`research_idea.md`** — research brief: goals, approach, and implicit success criteria (what “done” means).
- **`preferences.md`** — user preferences to guide the project; generally not updated by the agents.
- **`roadmap.md`** — durable end-to-end plan (phases, milestones); include completed lines; on scope change, retcon the **whole** file into one coherent story.
- **`immediate_plan.md`** — a more granular plan for the current step in the roadmap. when using planning for implementation/other actions, the plan should go here. this is **only** the current chunk; when the chunk finishes, clear/replace. Prefer iterative chunks that establish a simple working baseline or proof of concept first, then add detail or components in later cycles.
- **`status.md`** — live snapshot: blockers, current focus, last meaningful change.
- **`skills_index.md`** — table of `memory/skills/*.md` entries; keep aligned when you add skills.
- **`lessons.md`** — short durable takeaways; also record abandoned approaches/branches.
- **`user_instructions.md`** — console queue under **`## New`**: merge into **`immediate_plan.md`** / **`roadmap.md`**, then remove from **`## New`** (optional **`## In progress`** / **`## Completed`**); never leave merged items in **`## New`**. Act immediately; if you are not planner, still capture intent in Tier A and clear **`## New`** or leave a one-line planner handoff. **Long runs** (multi-step, slow tools, >few min): re-read this file ~every **2–3 min** for new **`## New`** bullets.

**Branch memory** (`data/runtime/memory/branch/<b>.md`): branch name `/`→`__`. Per active branch you touch: diverged-from (SHA/tag), purpose, status/results. Merge to **main** → delete file (optional copy to `extended/`). Abandoned/failed → delete file + note in **`lessons.md`**.

**Episodes** (`data/runtime/memory/episodes/`): run-by-run packets and worker outputs are auto-populated here. Do not write to this; it is only for looking up context on past subagents actions, if needed.

**Experiments:** link experiment dirs/metrics from Tier A or extended so the next run can find them.

Update memory **in the same run** when your work changes truth—do not assume a later pass fixes it.

**Extended files / catalog:** Tier A should stay short: usually just a few lines per concept. Use `data/runtime/memory/extended/<name>.md` for long logs, raw artifacts, detailed findings, expanded notes, transcripts, or other material that is too long to fit cleanly in Tier A. When you add or update an extended file, put the short pointer in Tier A where it matters and add an entry to **`extended_memory_index.md`** describing what is in the file. The more important the material is, the longer the Tier A excerpt can be, but keep Tier A distilled and high-signal. Extended file bodies are **not** inlined into packets—if someone needs the unabridged version later, they should open that file explicitly with tools (or have a subagent do it)."""
