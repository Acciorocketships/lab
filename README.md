# research-lab

Long-lived **multi-agent AI researcher** in Python: a **LangGraph** supervisor loop, **SQLite** for control/events, **file-based memory** (Tier A–E), and **worker agents** driven by **Claude Code** or **Cursor** CLI in headless mode. The **orchestrator** uses a normal OpenAI-compatible API (OpenAI, OpenRouter, or a local server).

## Layout

- `src/research_lab/` — package (orchestration, DB, memory, tools, agents, UI, workflows).
- `scripts/run.py` — **only** entry configuration (no CLI args); edit variables at top.
- `tests/` — pytest.
- `data/` — includes the default **project stub** for `scripts/run.py` (gitignored). Researcher state is **not** here by default: it lives under **`<project_dir>/.airesearcher/`** (see table).

Two directories:

| Location | Purpose |
|----------|---------|
| **Researcher root** | `<project_dir>/.airesearcher/` — internal memory (Tier A–E), SQLite DB, OAuth token file, LangGraph checkpoint path, experiments tree. Project-specific. |
| **Project directory** | The repo or tree under study; workers run CLI tools with this as cwd. Set **`PROJECT_DIR`** in `scripts/run.py`. |

## Pipeline (high level)

1. **Console (Textual)** and **scheduler** share **SQLite** (`control_events`, `system_state`, `run_events`, …).
2. Each **cycle**, the **LangGraph** in `workflows/research_graph.py` runs: `ingest` → `sync` → `choose` → `worker` → `review` → `update`.
3. **Choose** calls `orchestrator.decide_orchestrator()` (LLM with structured output, or `noop` if no credentials for the selected backend).
4. **Worker** builds a **packet** (`packets.py`), writes `packet.md` and **`worker_output.json`** (CLI stdout/stderr/parsed result) under `data/runtime/memory/episodes/cycle_*/<worker>/`, appends a row to **`memory/episodes/index.md`** (worker, task, orchestrator reason, links), and runs `agents.base.run_worker()` → Claude or Cursor CLI in the **project** directory.
5. **Memory** — Tier A files under `data/runtime/state/` are the default operating context for the orchestrator and workers (see [Memory system](#memory-system)). Tier A may **link** `memory/extended/*.md` paths; those files are **listed** (absolute paths) in prompts but **not** inlined. The current git branch’s **`memory/branch/<branch>.md`** is appended when set. The orchestrator overwrites **`context_summary.md`** each cycle; worker packets surface it as a separate **Rolling context summary** section (see below).
6. **Experiments** (`experiments.py`) create `exp_######` folders, metrics JSON, and keep/revert helpers.
7. **Run log** — each orchestrator and worker step appends a row to SQLite **`run_events`** (cycle, kind, worker, roadmap step, task, summary, optional payload path). The TUI reads recent rows from `run_events`. The orchestrator also updates **`context_summary.md`** (rolling compressed history for the next LLM calls).

## Agents

| Agent | Role |
|-------|------|
| Planner | Backlog / plan / branching strategy |
| Researcher | Gather information: web/papers, codebase questions, file exploration |
| Executer | One-off ops: shell, ephemeral scripts, non-code edits (not product implementation) |
| Implementer | Code + tests |
| Debugger | Hypotheses, instrumentation |
| Experimenter | Runs, metrics |
| Critic | Multi-persona (`agents/critic.py`) |
| Reviewer | Enforces preferences |
| Reporter | Answers and reports |
| Skill writer | `memory/skills/` + `skills_index.md` |

## Memory system

File-based memory lives under the **researcher root** — by convention **`researcher_root_for_project(project_dir)`** in `src/research_lab/config.py` (`<project_dir>/.airesearcher/`). The canonical list of Tier A filenames is **`TIER_A_FILES`** in `src/research_lab/memory.py`. Helpers for paths, extended-reference discovery, episodes, and orchestrator/worker formatting live in the same module; **per-branch** read/write helpers are in `src/research_lab/memory_extra.py` (used when building orchestrator context and worker packets).

### Tier A — `data/runtime/state/*.md`

These markdown files are **loaded every cycle** into the orchestrator (`memory.load_tier_a_bundle` + `memory.format_orchestrator_context`) and into worker packets (`packets.build_worker_packet`), except where noted.

| File | Description |
|------|-------------|
| **`project_brief.md`** | Short project scope and background—what this researcher session is about. |
| **`memory_guide.md`** | Conventions for all tiers (seeded by the app): how to keep Tier A dense, how to link extended/branch/episodes/skills, and lifecycle rules. |
| **`research_idea.md`** | The core research question or hypothesis driving the run. |
| **`preferences.md`** | Stable user or team preferences (tone, tools, constraints) for workers and orchestrator. |
| **`acceptance_criteria.md`** | What “done” means for the current effort—testable or checkable criteria. |
| **`roadmap.md`** | End-to-end **project roadmap** (phases, milestones, major deliverables). Should stay one coherent story; one item here often matches the scope of the active chunk in `immediate_plan.md`. |
| **`immediate_plan.md`** | **Immediate, low-level plan** for the active task only—same shape as a Cursor/Claude **plan** (concrete steps, files, checks). Disposable: refresh when the chunk changes. This is the single scratch for “what we’re doing right now” (there is no separate `current_plan.md`). |
| **`status.md`** | What is true *right now*: focus, blockers, last meaningful change. |
| **`context_summary.md`** | **Orchestrator-maintained** rolling summary (compressed history, facts, recent outcomes). The orchestrator **merges prior summary + last worker output** into a new `context_summary.md` each cycle. It is **not** duplicated inside the Tier A block in orchestrator prompts (`format_orchestrator_context` skips this key in the tier loop). In **worker packets**, it is **not** inlined under `### context_summary.md`; instead, `packets.build_worker_packet` injects the same content once as **Rolling context summary** at the top of the packet (after the objective). |
| **`skills_index.md`** | Table of paths under `memory/skills/` with one-line descriptions; entry point for Tier E. Maintained by humans or the **skill_writer** worker. |
| **`lessons.md`** | Dated or bulleted takeaways—especially when a branch is abandoned or an approach fails. |
| **`user_instructions.md`** | Instructions from the console (`## New` / `## In progress` / `## Completed`); `control.apply_instruction_event` can append to the **New** section. |

**Linking long content:** anywhere in Tier A (or combined tier text), put paths like `memory/extended/<name>.md` or `data/runtime/memory/extended/<name>.md`. `memory.discover_extended_filenames_from_text` finds those references; bodies are **never** auto-inlined—only absolute paths appear in orchestrator and worker prompts (`format_extended_refs_for_orchestrator`, `format_extended_refs_for_worker_packet`).

### Tier B — `data/runtime/memory/extended/`

Long-form notes (analysis, traces, experiment logs, exports). **Referenced from Tier A** only by path strings as above—not a second index file. Optional bulk load for tests: `memory.load_referenced_extended_bundle`. Legacy layout `memory/hot/` is migrated to `extended/` on startup.

### Tier C — `data/runtime/memory/branch/<branch>.md`

**Not** discovered via Tier A hyperlinks. When `current_branch` is set, `memory_extra.read_branch_memory` loads `memory/branch/<sanitized>.md` (branch `/` → `__`) and appends it to orchestrator context and worker packets. Lifecycle: workers keep files in sync with git; delete on merge to `main`, record abandonments in `lessons.md` (see `agents/shared_prompt.py` and the default `memory_guide.md`).

### Tier D — `data/runtime/memory/episodes/`

Per-cycle worker artifacts: `cycle_<n>/<worker>/packet.md` and `worker_output.json`, plus append-only **`index.md`** (task, reason, links). Documented in-folder by `episodes/README.md`. Canonical timeline remains SQLite **`run_events`**; episodes are the durable tree for inspection. Tier A does not “include” episodes as files—**`memory_guide.md`** points agents at the index; the graph appends to `index.md` after each worker run.

### Tier E — `data/runtime/memory/skills/`

Reusable procedures (`*.md`). **Referenced from Tier A** via **`skills_index.md`** (paths and descriptions), not by scanning arbitrary text. The **skill_writer** worker creates or updates files and the index.

### Experiments — `data/runtime/experiments/`

Created by `memory.ensure_memory_layout`; each run uses `exp_######` folders (see `experiments.py`) with SQLite metadata in the `experiments` table. Link paths from Tier A or extended when relevant.

### Memory tiers (summary)

- **A** — `data/runtime/state/*.md` — operating memory (table above).
- **B** — `memory/extended/` — long-form supplementary notes; **path-linked from Tier A**; on-demand reads.
- **C** — `memory/branch/<branch>.md` — one file per active branch; selected by **current git branch**, not Tier A links (`memory_extra.py`).
- **D** — `memory/episodes/` — per worker run + **`index.md`**; timeline of record in SQLite **`run_events`**.
- **E** — `memory/skills/` — reusable procedures; **indexed from Tier A** `skills_index.md`.

## Console commands

Type **plain text** to queue an instruction (SQLite instruction queue, not `roadmap.md`). **Slash commands:** `/instruction …`, `/ask …`, `/pause`, `/resume`, `/shutdown`, `/status`, `/backlog`, `/branches`, `/experiments`, `/report`, `/help`

## Run

1. `conda env create -f environment.yml && conda activate research-lab`
2. `pip install -e ".[dev]"` (if not using conda pip step)
3. Edit **`scripts/run.py`** (paths, idea, acceptance criteria, `default_worker_backend`).
4. `python scripts/run.py`

Set **`orchestrator_backend`** in **`RunConfig`** (`scripts/run.py`) to **`openai`**, **`openrouter`**, or **`local`**. The orchestrator uses **`llm.resolve_llm_api_key()`** and **`llm.resolve_llm_base_url()`** (OpenAI-compatible client).

**`openai`** (default): **`OPENAI_API_KEY`**, or **OpenAI Codex / ChatGPT OAuth** (Authorization Code + PKCE — **not** device-code flow):

1. Defaults in **`RunConfig`** match the **`codex` CLI** (`https://auth.openai.com`, public client id, redirect **`http://localhost:1455/auth/callback`**). Adjust **`scripts/oauth_login.py`** if you use another IdP; for Google or other providers set **`oauth_issuer`** and scopes/redirect, and we use OIDC discovery (except **`auth.openai.com`**, where we use fixed **`/oauth/authorize`** and **`/oauth/token`** like Codex).
2. Run **`python scripts/oauth_login.py`** once: your browser opens, you sign in, the app receives the redirect on **localhost:1455**, exchanges the code for tokens, and saves **`data/oauth_openai_tokens.json`** under **`<project_dir>/.airesearcher/data/`** (mode `600` where supported).
3. Credentials resolve as: explicit **`openai_api_key`** → **`OPENAI_API_KEY`** env → OAuth token file (with id_token → API-key exchange for Codex-style tokens).

**`openrouter`**: set **`OPENROUTER_API_KEY`** or **`RunConfig.openrouter_api_key`**. Base URL defaults to **`https://openrouter.ai/api/v1`**; override with **`openai_base_url`** if needed. Pick a model id OpenRouter supports (e.g. in **`openai_model`**).

**`local`**: OpenAI-compatible server (e.g. **Ollama** at **`http://127.0.0.1:11434/v1`**). Set **`openai_base_url`** or **`LOCAL_LLM_BASE_URL`** / **`OPENAI_BASE_URL`**. API key: **`openai_api_key`**, **`OPENAI_API_KEY`**, **`LOCAL_LLM_API_KEY`**, or default **`ollama`**. Example small model: **`qwen3.5:0.8b`** (`ollama pull` then set **`openai_model`** / **`AIRESEARCHER_OPENAI_MODEL`**).

Use **`python scripts/smoke_llm.py`** to verify the LLM path; optional env **`AIRESEARCHER_ORCHESTRATOR_BACKEND`** matches **`orchestrator_backend`**.

Without any credential for the chosen backend, the orchestrator selects **`noop`** (smoke/testing).

Install **Claude Code** (`npm i -g @anthropic-ai/claude-code`) or use **Cursor** agent CLI on `PATH`.

## Tests

```bash
pytest -q
```

## Recovery

- **SQLite** and Tier A files under **`<project_dir>/.airesearcher/data/runtime/state/`** hold durable control and operating memory.
- LangGraph **checkpoint** wiring is reserved (`checkpoint_path` in `run_loop`); the default loop re-invokes the graph each cycle without a checkpointer for simplicity—enable `SqliteSaver` in `build_graph` when you need process-crash replay.

## Domain code

Put domain-specific metrics/runners under `src/research_lab/domains/` implementing `domains/base.py` hooks; keep core orchestration generic.
