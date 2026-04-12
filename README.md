# lab

Long-lived **multi-agent AI researcher** in Python: a **LangGraph** supervisor loop, **SQLite** for control/events, **file-based memory** (Tier A–E), and **worker agents** driven by **Claude Code** or **Cursor** CLI in headless mode. The **orchestrator** uses a normal OpenAI-compatible API (OpenAI, OpenRouter, or a local server).

## Quick start

```bash
# 1. Install
pip install .

# 2. One-time global setup (model, credentials, preferences)
lab setup

# 3. Initialize a project
cd my-project
lab init

# 4. Start the console
lab
```

Once in the console, type `/start` to begin the background agent, `/pause` to pause after the current worker finishes, `/stop` to halt immediately, or `/exit` to quit. Plain text is queued as an instruction to the agent.

## CLI commands

| Command | Description |
|---------|-------------|
| `lab setup` | Interactive wizard: choose model provider, model, credentials (OAuth or API key), worker backend. Writes `~/.lab/config.toml` (add code style in `[preferences]` yourself if you want). |
| `lab init` | Initialize the current directory as a research project. Creates `.lab/` with config, memory layout, and seed files. Accepts `--idea` and `--criteria` flags, or prompts interactively. |
| `lab` | Start the interactive console (requires `lab setup` and `lab init` first). |

## Console commands

| Command | Action |
|---------|--------|
| `/start` | Start the background research agent |
| `/pause` | Pause after the current worker (subagent) finishes — no kill, no revert |
| `/stop` | Stop immediately: kill the worker process and revert any in-flight cycle |
| `/exit` | Stop the agent and quit the console |
| `/branches` | Show branch registry |
| `/reset` | Clear SQLite and runtime memory (Tier A except `research_idea.md` and `preferences.md`, episodes, extended, branches, skills, experiments); syncs `[project]` brief and preferences in `config.toml` from those files; does not change your project code |
| `/undo` | Stop the scheduler if running, restore the project tree and DB to before the current or last worker (git checkpoints); if the agent was running, restart it for a fresh orchestrator step (if paused, stays paused) |
| `/help` | List all commands |
| plain text | Queue as an instruction to the agent |

## Programmatic API (`lab.runner`)

The `lab` CLI is a thin wrapper. Scripts and tests should call the same functions:

| Function | Purpose |
|----------|---------|
| `run_lab_console(project_dir=None)` | Start the console using `~/.lab/` and `<project>/.lab/config.toml` (default project = current working directory). |
| `ensure_console_ready(project_dir)` | Validate config, merge, prepare DB; returns `(db_path, RunConfig)`. |
| `run_console_session(db_path, cfg)` | Start the TUI with an explicit `RunConfig` (no TOML). Used by `scripts/run.py` and unit tests. |
| `init_project_at(project_dir, pcfg, overwrite=False)` | Full project init after global setup. |
| `bootstrap_bench_project(project_dir, gcfg=..., pcfg=...)` | Write global + project TOML and seed memory in one step (e.g. automated tests). |
| `run_interactive_global_setup()` | Interactive wizard (same as `lab setup`). |
| `seed_tier_a_from_run_config(researcher_root, cfg)` | Write system-owned `.lab/state/system.md` (paths; run tail filled once the scheduler runs). |

Example (explicit config, no global TOML — typical for `scripts/run.py`):

```python
from pathlib import Path
from lab.config import RunConfig
from lab.runner import run_console_session, seed_tier_a_from_run_config
from lab import memory

cfg = RunConfig(...)  # researcher_root, project_dir, model, etc.
memory.ensure_memory_layout(cfg.researcher_root)
seed_tier_a_from_run_config(cfg.researcher_root, cfg)
run_console_session(cfg.researcher_root / "runtime.db", cfg)
```

## Layout

- `lab/` — package (orchestration, DB, memory, tools, agents, UI, workflows).
- `lab/runner.py` — shared entry points for CLI, scripts, and tests.
- `tests/` — pytest.

Two directories per project:

| Location | Purpose |
|----------|---------|
| **Global config** | `~/.lab/` — model settings, credentials, OAuth tokens, default preferences (`code_style`) copied into new projects. Shared across all projects. |
| **Researcher root** | `<project_dir>/.lab/` — project-specific config, memory (Tier A–E), SQLite DB, experiments. |
| **Project directory** | The repo or tree under study; workers run CLI tools with this as cwd. |

## Configuration

### Global (`~/.lab/config.toml`)

Created by `lab setup`. Contains model provider/name, API keys or OAuth client id, worker backend. Optional default **preferences** go under `[preferences]` as `code_style` — on `lab init`, that value is copied into the project file; edit the file by hand; multiline values work as TOML literal blocks.

### Per-project (`.lab/config.toml`)

Created by `lab init`. Contains a **research brief** (`research_idea`) and **preferences** (`preferences` under `[project]`). At init, preferences start as a copy of global `code_style`; the running lab uses only this project field (change global defaults for future inits, or edit the project TOML for this repo).

### Model providers

- **openai**: Uses `OPENAI_API_KEY` or OAuth (Authorization Code + PKCE). Run `lab setup` and choose "openai" to trigger the browser OAuth flow.
- **openrouter**: Provide an OpenRouter API key during `lab setup`. Base URL defaults to `https://openrouter.ai/api/v1`.
- **local**: OpenAI-compatible server (e.g. Ollama at `http://127.0.0.1:11434/v1`).

### Worker backends

Workers use **Claude Code** (`claude -p`) or **Cursor agent** (`cursor agent -p`). Choose during `lab setup`.

- **cursor**: Runs `cursor agent -p "<prompt>" --trust`. No subprocess timeout by default; set `LAB_CURSOR_TIMEOUT_SEC` to cap runtime in seconds if needed.
- **claude**: Runs `claude -p --output-format json`. Install with `npm i -g @anthropic-ai/claude-code`. No subprocess timeout by default; set `LAB_CLAUDE_TIMEOUT_SEC` to cap runtime in seconds if needed.

### Context truncation

By default, the app no longer truncates orchestrator context or worker packets in Python. We pass the
full assembled prompt and let the upstream provider/model enforce its own context window. This means
you will get a provider/model error if the prompt is too large, rather than silently losing
instructions or context in app code.

If you want to reintroduce limits, set the optional limit fields on `RunConfig`:

- `orchestrator_input_max_chars`
- `orchestrator_prev_summary_max_chars`
- `orchestrator_last_worker_max_chars`
- `orchestrator_tier_file_max_chars`
- `orchestrator_branch_memory_max_chars`
- `worker_packet_max_chars`
- `system_recent_run_events_limit` — how many recent SQLite `run_events` rows are rendered into `.lab/state/system.md` (default 40).

## Pipeline (high level)

1. **Console (Textual)** and **scheduler** share **SQLite** (`control_events`, `system_state`, `run_events`, `worker_stream`).
2. Each **cycle**, the **LangGraph** in `workflows/research_graph.py` runs: `ingest` → `choose` → `worker` → `update`.
3. **Choose** calls `orchestrator.decide_orchestrator()` (LLM with structured output).
4. **Worker** builds a **packet**, writes `packet.md` and `worker_output.json` under `memory/episodes/cycle_*/<worker>/`, and runs `agents.base.run_worker()` → Claude or Cursor CLI.
5. Worker output is **streamed** line-by-line to the `worker_stream` table; the console displays chunks in real time.
6. **Memory** — Tier A files under `state/` are the default operating context. **`system.md`** is system-only (workspace paths + a short **Recent activity** tail from `run_events`: orchestrator **task** + **kwargs** such as critic `persona`, and per-worker **objective** plus a collapsed excerpt from **`packet.md`**; routing rationale stays in **`context_summary.md`**); agents edit the other Tier A files (notably `research_idea.md` for the research brief).

## Agents

| Agent | Role |
|-------|------|
| Planner | Backlog / plan / branching strategy |
| Researcher | Gather information: web/papers, codebase questions, file exploration |
| Executer | One-off ops: shell, ephemeral scripts, non-code edits |
| Implementer | Code + tests |
| Debugger | Hypotheses, instrumentation |
| Experimenter | Runs, metrics |
| Critic | Multi-persona review |
| Reviewer | Enforces preferences |
| Reporter | Answers and reports |
| Skill writer | `memory/skills/` + `skills_index.md` |
| Done | Orchestrator signals the brief in `research_idea.md` and `roadmap.md` support completion |

## Memory system

File-based memory lives under the **researcher root** (`<project_dir>/.lab/`). See `lab/memory.py` for the canonical list of Tier A filenames.

- **A** — `state/*.md` — operating memory (loaded every cycle).
- **B** — `memory/extended/` — long-form notes; describe them in Tier A `extended_memory_index.md` (included in context with other Tier A files).
- **C** — `memory/branch/<branch>.md` — one file per active branch.
- **D** — `memory/episodes/` — per worker run + `index.md`.
- **E** — `memory/skills/` — reusable procedures; indexed from Tier A `skills_index.md`.

## Development

```bash
conda env create -f environment.yml && conda activate lab
pip install -e ".[dev]"
pytest -q
```

## Scripts (`scripts/`)

- `scripts/run.py` — bench project launcher: builds a `RunConfig` for `data/bench_rl_project` and calls `runner.run_console_session` (same core as `lab`, without TOML).
- `scripts/oauth_login.py` — calls `runner.run_oauth_browser_for_global` (same OAuth path as `lab setup`).

## Recovery

- SQLite and Tier A files under `<project_dir>/.lab/state/` hold durable control and operating memory.
- LangGraph checkpoint wiring is reserved; the default loop re-invokes the graph each cycle.
