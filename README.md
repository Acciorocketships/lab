# lab

**lab** is a long-running research assistant for a codebase or project folder. You describe what you want investigated or built; a **supervisor loop** (LangGraph) keeps work moving across specialized **subagents**. An **orchestrator** model (any OpenAI-compatible API: OpenAI, OpenRouter, or a local server) decides which subagent runs next and what task it gets. Each **worker** subagent runs in the real repo via **Claude Code** or **Cursor** agent CLI in headless mode, so it can edit files, run commands, and use tools like a normal coding agent.

The system is built around **markdown memory** under your project’s `.lab/` tree: a small set of always-on “Tier A” files holds the brief, roadmap, status, and rolling summaries, while deeper notes, skills, and per-run artifacts live in structured folders. That layout is what both the orchestrator and the workers read and update, so progress survives across cycles without fitting the whole history into one prompt.

## Quick start

```bash
# 1. Install
pip install .

# 2. One-time global setup (model, credentials, worker backend)
lab setup

# 3. Initialize a project (creates .lab/ under the current directory)
cd my-project
lab init

# 4. Start the console
lab
```

In the console, use `/start` to run the background supervisor, `/pause` to finish the current worker then stop scheduling, `/stop` to halt immediately, or `/exit` to quit. Plain text lines are queued as **instructions** for the agent (merged into Tier A memory for workers to act on).

## CLI commands


| Command     | Description                                                                                                                                                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lab`       | Open the interactive console. Requires `lab setup` and `lab init` in the project directory (or cwd).                                                                                                                                                 |
| `lab setup` | Interactive wizard: model provider, model name, credentials (OAuth or API key), default worker backend. Writes `~/.lab/config.toml`.                                                                                                                 |
| `lab init`  | Initialize the current directory as a lab project. Creates `.lab/` (config, memory layout, seed Tier A files). Seeds an empty **research brief**; starting `lab` runs `/edit idea` automatically when the saved brief is still empty. If `.lab/` already exists, asks before overwriting. |


## Console commands


| Command    | Action                                                                                                                                                   |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/start`   | Start the background supervisor (scheduler + LangGraph cycles).                                                                                          |
| `/pause`   | Pause after the current graph worker finishes (no kill, no revert).                                                                                      |
| `/stop`    | Stop immediately: kill workers and any `/agent` runs. `/stop agent n` stops one standalone async agent by id.                                            |
| `/exit`    | Stop everything and quit the console.                                                                                                                    |
| `/agent …` | Run a **standalone** async worker on the given prompt (same CLI backend as graph workers, but not chosen by the orchestrator).                           |
| `/plan`    | Show the live roadmap checklist from Tier A (`roadmap.md`).                                                                                              |
| `/diff`    | Line diff of captured changes. `/diff n` = cycle `n`; `/diff n m` = from cycle `n` through end of cycle `m`.                                             |
| `/reset`   | Clear runtime database and lab artifacts under `.lab/` except `research_idea.md` and `preferences.md`; project source tree unchanged.                    |
| `/undo`    | Revert project tree and runtime state to before the current or last graph worker (git checkpoints); restarts orchestrator only if the agent was running. |
| `/redo`    | Restore the last undone checkpoint and replay local edits when possible.                                                                                 |
| `/help`    | List commands.                                                                                                                                           |
| Plain text | Queued as user instructions for the research loop.                                                                                                       |


## Subagents

Two kinds of execution show up in the UI:

1. **Graph workers** — the orchestrator picks one per cycle from `lab/workflows/research_graph.py`. Each gets a **packet** (objective, rolling summary, Tier A, branch memory) and runs the configured worker CLI in the **project directory** (the repo under study).
2. **Standalone `/agent` runs** — you type `/agent` with a prompt; the console spawns the same kind of CLI worker **outside** the LangGraph cycle. Use these for one-off tasks without steering the main roadmap loop.

Graph workers:


| Worker           | Role                                                                                                                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **planner**      | Turns goals, user instructions, and acceptance criteria into a concrete sequence of work; maintains roadmap-style structure and handoffs across other roles.                                            |
| **query**        | **Local** investigation: codebase layout, where behavior lives, tests and configs, constraints for the next step. Prefer over **researcher** when uncertainty is about the repo, not the outside world. |
| **researcher**   | **External** context: web and literature, datasets, libraries, comparable projects, baselines—cited, synthesized, written into memory for others to use.                                                |
| **executer**     | One-off operations: shell, environment checks, file moves, temporary scripts, non-product “glue” edits—not feature implementation or experiment **execution**.                                          |
| **implementer**  | Product code and tests: small, reviewable changes, iterative baselines before polish.                                                                                                                   |
| **debugger**     | Root-cause analysis: hypotheses, instrumentation, evidence, localized fixes.                                                                                                                            |
| **experimenter** | Owns **running** experiments end-to-end (launch, monitor, analyze, interpret)—not merely writing experiment code.                                                                                       |
| **critic**       | Broader-picture challenge pass with slight routing priority: judges overall direction, infrastructure, and real outputs by running the product or artifacts and evaluating them like a human, using a persona chosen by the orchestrator (`engineer`, `data_scientist`, `theoretical_scientist`, `researcher`, `reviewer`, `manager`). |
| **reviewer**     | Code-and-logic review: inspects implementation details, runs focused and full-system tests, and suggests refactors or code changes to improve correctness, flexibility, and maintainability. |
| **reporter**     | User-facing reports, plots, demos, and summaries from current memory and artifacts.                                                                                                                     |
| **skill_writer** | Captures reusable procedures under `.lab/memory/skills/` and keeps `skills_index.md` aligned.                                                                                                           |
| **done**         | Not a CLI worker: orchestrator-only signal that the brief and roadmap support stopping the loop.                                                                                                        |


Routing hints live in the orchestrator system prompt in `lab/orchestrator.py` (e.g. when to prefer `query` vs `researcher`, how `reviewer` and `critic` split code-vs-output evaluation, when `critic` gets slight priority after substantive work, when to run `critic` before `done`).

## Memory and context management

### Where memory lives

Everything is under the **researcher root** `<project>/.lab/`. Canonical Tier A filenames and helpers are in `lab/memory.py`.


| Location                         | Purpose                                                                                                                                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.lab/state/*.md`                | **Tier A** — operating memory loaded every orchestrator turn and packed into worker prompts (with the exceptions below).                                                                                            |
| `.lab/memory/extended/`          | Long-form notes, logs, raw synthesis. **Bodies are not inlined** into orchestrator or worker packets—only the **index** in Tier A (`extended_memory_index.md`) is included; workers open files on disk when needed. |
| `.lab/memory/branch/<branch>.md` | Per-git-branch notes (name encoding: `/` → `__`).                                                                                                                                                                   |
| `.lab/memory/episodes/`          | Per-cycle **packet** and **worker output** artifacts for audit and debugging.                                                                                                                                       |
| `.lab/memory/skills/`            | Reusable procedures; indexed from Tier A `skills_index.md`.                                                                                                                                                         |


Shared rules for what each Tier A file means, who may edit it, and how `user_instructions.md` queues work are in `lab/agents/shared_prompt.py` (`MEMORY_AND_TIER_A`). In short: workers keep Tier A truthful in the **same** run as their changes; `**system.md`** (paths + recent activity tail) and `**context_summary.md**` (rolling compressed history) are **runtime-owned** and must not be edited by workers.

### Orchestrator context

Each cycle, **before** the routing LLM runs, `lab/workflows/research_graph.py` performs **pre-orchestrator Tier A management**: if any non-system Tier A file is larger than its saved line (default **20k** characters, or `max(20_000, last_size_after_compact)` from the prior cycle per file), the internal `memory_compactor` worker runs once to shrink files on disk. Then `format_orchestrator_context()` in `lab/memory.py` builds the routing prompt from that state (previous `context_summary`, last worker summary, full Tier A bodies except `context_summary.md`—which is represented by the previous-summary block rather than the raw file—plus optional **branch memory**). There is **no** mechanical middle-truncation of Tier A inside prompts. The orchestrator returns structured JSON (`worker`, `task`, `reason`, `context_summary`, etc.); a fresh `**context_summary`** is written to disk when provided.

### Worker packets

`lab/packets.build_worker_packet()` assembles markdown for the CLI worker: **objective**, **rolling context summary** (from `context_summary.md`), conduct hints for long-running commands, **Tier A** sections (verbatim from disk; again skipping the raw `context_summary.md` file chunk in the Tier A list), optional **branch memory**, then optional role-specific sections from `lab/workflows/research_graph.py`. If `worker_packet_max_chars` is set on `RunConfig`, the **whole** assembled packet is head/tail truncated with a marker.

### Context size and limits

Optional `RunConfig.worker_packet_max_chars` caps the **assembled worker/async-agent packet** with a head/tail trim. `system_recent_run_events_limit` controls how many recent graph-worker events feed the **Recent activity** section in `system.md`. Tier A growth is handled by the **pre-orchestrator** `memory_compactor` pass (20k default trigger; per-file persisted lines in `pre_orchestrator_compact_state.json`) and optional whole-packet caps above—not by silently clipping individual Tier A files inside the routing or worker prompts.

## Layout

- `lab/` — package (orchestration, persistence, memory, tools, agents, UI, workflows).
- `lab/runner.py` — shared entry points for CLI, scripts, and tests.
- `tests/` — pytest.


| Location              | Purpose                                                                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Global config**     | `~/.lab/` — model settings, credentials, OAuth tokens, default preferences (`code_style`) copied into new projects. |
| **Researcher root**   | `<project>/.lab/` — project config, Tier A state and supporting memory folders, runtime database, experiments.      |
| **Project directory** | The repo or tree under study; workers use this as their working directory.                                          |


## Configuration

### Global (`~/.lab/config.toml`)

Created by `lab setup`. Contains model provider/name, API keys or OAuth client id, worker backend. Optional default **preferences** under `[preferences]` as `code_style` — on `lab init`, that value is copied into the project; you can edit `preferences.md` in the project afterward.

### Per-project (`.lab/config.toml`)

Created by `lab init`. Holds machine-oriented fields; the human-facing **brief** and **preferences** live in Tier A (`research_idea.md`, `preferences.md`) and are what workers read.

### Model providers

- **openai**: `OPENAI_API_KEY` or OAuth (Authorization Code + PKCE). `lab setup` with provider `openai` can start the browser flow.
- **openrouter**: OpenRouter API key during `lab setup`. Base URL defaults to `https://openrouter.ai/api/v1`.
- **local**: OpenAI-compatible server (e.g. Ollama at `http://127.0.0.1:11434/v1`).

### Worker backends

Workers use **Claude Code** (`claude -p`) or **Cursor agent** (`cursor agent -p`). Choose during `lab setup`.

- **cursor**: `cursor agent -p "<prompt>" --trust`. Optional `LAB_CURSOR_TIMEOUT_SEC` caps runtime in seconds.
- **claude**: `claude -p --output-format json` (e.g. `npm i -g @anthropic-ai/claude-code`). Optional `LAB_CLAUDE_TIMEOUT_SEC`.

## Pipeline (high level)

1. **Console** (Textual) and **scheduler** coordinate mode (active/paused), cycles, and worker processes.
2. Each **cycle**, the LangGraph in `workflows/research_graph.py` runs: ingest → choose → worker → update.
3. **Choose** calls `orchestrator.decide_orchestrator()` (structured LLM output).
4. **Worker** writes `packet.md` and `worker_output.json` under `memory/episodes/cycle_*/<worker>/` and runs `agents.base.run_worker()` (Claude or Cursor).
5. Worker stdout/stderr streams into the console in real time.
6. **Memory** updates flow from worker edits to Tier A and related trees; the orchestrator refreshes `**context_summary.md`**; `**system.md**` is refreshed from durable run metadata for a short **Recent activity** tail.

## Development

```bash
conda env create -f environment.yml && conda activate lab
pip install -e ".[dev]"
pytest -q
```

## Scripts (`scripts/`)

- `scripts/run.py` — bench-style launcher: builds a `RunConfig` for `data/bench_rl_project` and calls `runner.run_console_session` (same core as `lab`, without relying on TOML for that path).
- `scripts/oauth_login.py` — calls `runner.run_oauth_browser_for_global` (same OAuth path as `lab setup`).

## Recovery

- **Tier A** under `.lab/state/` holds the durable brief, roadmap, and rolling summary.
- `**/undo`** / `**/redo**` use git checkpoints over the project tree plus lab runtime state.
- `**/reset**` clears lab runtime and most memory while preserving `research_idea.md` and `preferences.md`.
