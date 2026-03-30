# research-lab

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

Once in the console, type `/start` to begin the background agent, `/pause` to pause it, or `/exit` to quit. Plain text is queued as an instruction to the agent.

## CLI commands

| Command | Description |
|---------|-------------|
| `lab setup` | Interactive wizard: choose model provider, model, credentials (OAuth or API key), worker backend. Writes `~/.airesearcher/config.toml` (add code style in `[preferences]` yourself if you want). |
| `lab init` | Initialize the current directory as a research project. Creates `.airesearcher/` with config, memory layout, and seed files. Accepts `--idea` and `--criteria` flags, or prompts interactively. |
| `lab` | Start the interactive console (requires `lab setup` and `lab init` first). |

## Console commands

| Command | Action |
|---------|--------|
| `/start` | Start the background research agent |
| `/pause` | Pause the agent |
| `/exit` | Pause the agent and quit the console |
| `/status` | Show current agent state |
| `/ask <q>` | Queue a question for the agent |
| `/backlog` | Show recent instructions |
| `/branches` | Show branch registry |
| `/experiments` | Show experiment registry |
| `/reset` | Clear SQLite and runtime memory (Tier A except `research_idea.md` and `preferences.md`, episodes, extended, branches, skills, experiments); syncs `[project]` brief and preferences in `config.toml` from those files |
| `/help` | List all commands |
| plain text | Queue as an instruction to the agent |

## Programmatic API (`research_lab.runner`)

The `lab` CLI is a thin wrapper. Scripts and tests should call the same functions:

| Function | Purpose |
|----------|---------|
| `run_lab_console(project_dir=None)` | Start the console using `~/.airesearcher/` and `<project>/.airesearcher/config.toml` (default project = current working directory). |
| `ensure_console_ready(project_dir)` | Validate config, merge, prepare DB; returns `(db_path, RunConfig)`. |
| `run_console_session(db_path, cfg)` | Start the TUI with an explicit `RunConfig` (no TOML). Used by `scripts/run.py` and unit tests. |
| `init_project_at(project_dir, pcfg, overwrite=False)` | Full project init after global setup. |
| `bootstrap_bench_project(project_dir, gcfg=..., pcfg=...)` | Write global + project TOML and seed memory in one step (e.g. automated tests). |
| `run_interactive_global_setup()` | Interactive wizard (same as `lab setup`). |
| `seed_tier_a_from_run_config(researcher_root, cfg)` | Seed core Tier A markdown from a `RunConfig`. |

Example (explicit config, no global TOML — typical for `scripts/run.py`):

```python
from pathlib import Path
from research_lab.config import RunConfig
from research_lab.runner import run_console_session, seed_tier_a_from_run_config
from research_lab import memory

cfg = RunConfig(...)  # researcher_root, project_dir, model, etc.
memory.ensure_memory_layout(cfg.researcher_root)
seed_tier_a_from_run_config(cfg.researcher_root, cfg)
run_console_session(cfg.researcher_root / "data" / "runtime.db", cfg)
```

## Layout

- `src/research_lab/` — package (orchestration, DB, memory, tools, agents, UI, workflows).
- `src/research_lab/runner.py` — shared entry points for CLI, scripts, and tests.
- `tests/` — pytest.

Two directories per project:

| Location | Purpose |
|----------|---------|
| **Global config** | `~/.airesearcher/` — model settings, credentials, OAuth tokens, code style preferences. Shared across all projects. |
| **Researcher root** | `<project_dir>/.airesearcher/` — project-specific config, memory (Tier A–E), SQLite DB, experiments. |
| **Project directory** | The repo or tree under study; workers run CLI tools with this as cwd. |

## Configuration

### Global (`~/.airesearcher/config.toml`)

Created by `lab setup`. Contains model provider/name, API keys or OAuth client id, worker backend. Optional **code style** goes under `[preferences]` as `code_style` — edit the file by hand; multiline values work as TOML `"""..."""` blocks.

### Per-project (`.airesearcher/config.toml`)

Created by `lab init`. Contains a single **research brief** (`research_idea` in TOML — goals and implicit success criteria in one field) and optional project-specific preference overrides.

### Model providers

- **openai**: Uses `OPENAI_API_KEY` or OAuth (Authorization Code + PKCE). Run `lab setup` and choose "openai" to trigger the browser OAuth flow.
- **openrouter**: Provide an OpenRouter API key during `lab setup`. Base URL defaults to `https://openrouter.ai/api/v1`.
- **local**: OpenAI-compatible server (e.g. Ollama at `http://127.0.0.1:11434/v1`).

### Worker backends

Workers use **Claude Code** (`claude -p`) or **Cursor agent** (`cursor agent -p`). Choose during `lab setup`.

- **cursor**: Runs `cursor agent -p "<prompt>" --trust`. No subprocess timeout by default; set `AIRESEARCHER_CURSOR_TIMEOUT_SEC` to cap runtime in seconds if needed.
- **claude**: Runs `claude -p --output-format json`. Install with `npm i -g @anthropic-ai/claude-code`. No subprocess timeout by default; set `AIRESEARCHER_CLAUDE_TIMEOUT_SEC` to cap runtime in seconds if needed.

## Pipeline (high level)

1. **Console (Textual)** and **scheduler** share **SQLite** (`control_events`, `system_state`, `run_events`, `worker_stream`).
2. Each **cycle**, the **LangGraph** in `workflows/research_graph.py` runs: `ingest` → `sync` → `choose` → `worker` → `update`.
3. **Choose** calls `orchestrator.decide_orchestrator()` (LLM with structured output).
4. **Worker** builds a **packet**, writes `packet.md` and `worker_output.json` under `data/runtime/memory/episodes/cycle_*/<worker>/`, and runs `agents.base.run_worker()` → Claude or Cursor CLI.
5. Worker output is **streamed** line-by-line to the `worker_stream` table; the console displays chunks in real time.
6. **Memory** — Tier A files under `data/runtime/state/` are the default operating context.

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

File-based memory lives under the **researcher root** (`<project_dir>/.airesearcher/`). See `src/research_lab/memory.py` for the canonical list of Tier A filenames.

- **A** — `data/runtime/state/*.md` — operating memory (loaded every cycle).
- **B** — `memory/extended/` — long-form notes; describe them in Tier A `extended_memory_index.md` (included in context with other Tier A files).
- **C** — `memory/branch/<branch>.md` — one file per active branch.
- **D** — `memory/episodes/` — per worker run + `index.md`.
- **E** — `memory/skills/` — reusable procedures; indexed from Tier A `skills_index.md`.

## Development

```bash
conda env create -f environment.yml && conda activate research-lab
pip install -e ".[dev]"
pytest -q
```

## Scripts (`scripts/`)

- `scripts/run.py` — bench project launcher: builds a `RunConfig` for `data/bench_rl_project` and calls `runner.run_console_session` (same core as `lab`, without TOML).
- `scripts/oauth_login.py` — calls `runner.run_oauth_browser_for_global` (same OAuth path as `lab setup`).

## Recovery

- SQLite and Tier A files under `<project_dir>/.airesearcher/data/runtime/state/` hold durable control and operating memory.
- LangGraph checkpoint wiring is reserved; the default loop re-invokes the graph each cycle.
