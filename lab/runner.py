"""Shared programmatic API for lab: CLI, scripts, and tests use the same entry points."""

from __future__ import annotations

from pathlib import Path

from lab import db, memory
from lab.config import RunConfig
from lab.global_config import (
    GLOBAL_CONFIG_PATH,
    GLOBAL_DIR,
    GLOBAL_OAUTH_PATH,
    GlobalConfig,
    global_config_exists,
    load_global_config,
    mark_project_initialized,
    project_is_initialized,
    project_researcher_root,
    save_global_config,
)


class LabConfigError(RuntimeError):
    """Raised when global or project configuration is missing or invalid."""


DEFAULT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


def read_multiline_terminal(click_mod: object | None = None) -> str:
    """Read multiline text with full line-editing via prompt_toolkit.

    Arrow keys navigate freely between lines; Esc then Enter submits.
    Falls back to raw stdin if prompt_toolkit is unavailable or the
    session is non-interactive.
    """
    import sys

    try:
        from prompt_toolkit import PromptSession

        if not sys.stdin.isatty():
            raise RuntimeError("non-interactive")

        hint = "  Type below (arrow keys to navigate). Press [Esc] then [Enter] to submit.\n"
        if click_mod is not None:
            click_mod.echo(hint)
        else:
            print(hint, file=sys.stderr)

        session = PromptSession()
        result = session.prompt(
            "❯ ",
            multiline=True,
            prompt_continuation="  ",
        )
        return (result or "").strip()
    except (ImportError, RuntimeError):
        pass
    except (KeyboardInterrupt, EOFError):
        return ""

    if click_mod is not None:
        click_mod.echo(
            "Enter or paste text below, then end input with "
            "Ctrl+D (macOS/Linux) or Ctrl+Z then Enter (Windows)."
        )
    else:
        print(
            "Enter or paste text below, then end input with "
            "Ctrl+D (macOS/Linux) or Ctrl+Z then Enter (Windows).",
            file=sys.stderr,
        )
    try:
        data = sys.stdin.read()
    except (KeyboardInterrupt, EOFError):
        return ""
    return (data or "").strip()


def run_auth_test(project_dir: Path) -> None:
    """Print orchestrator credential source and run one minimal routing LLM call."""
    from lab import llm
    from lab.orchestrator import (
        decide_orchestrator,
        missing_orchestrator_credentials_hint,
    )

    if not global_config_exists():
        raise LabConfigError("Global config not found. Run `lab setup` first.")
    if not project_is_initialized(project_dir):
        raise LabConfigError(
            f"Project not initialized at {project_dir}. Run `lab init` first."
        )

    gcfg = load_global_config()
    cfg = RunConfig.from_configs(gcfg, project_dir)

    base = llm.resolve_llm_base_url(cfg)
    print(f"Project: {project_dir.resolve()}")
    print(f"Orchestrator backend: {cfg.orchestrator_backend}")
    print(f"Model: {cfg.openai_model}")
    print(f"Base URL: {base or '(default — OpenAI official API)'}")
    print(f"Credential source: {llm.describe_orchestrator_credential_source(cfg)}")

    api_key = llm.resolve_llm_api_key(cfg)
    if not api_key:
        raise LabConfigError(missing_orchestrator_credentials_hint(cfg))

    ctx = (
        "# Auth test\n"
        "Minimal orchestrator check. Pick worker=planner with a one-sentence reason."
    )
    decision = decide_orchestrator(ctx, model=cfg.openai_model, cfg=cfg)
    print("")
    print("Orchestrator call succeeded.")
    print(f"  worker: {decision.worker}")
    if decision.reason:
        print(f"  reason: {decision.reason}")


def ensure_console_ready(project_dir: Path) -> tuple[Path, RunConfig]:
    """Load global config, ensure memory layout, pause active scheduler row, return db path and RunConfig.

    Requires ``~/.lab/config.toml`` and an initialized project (see ``lab init``).
    """
    if not global_config_exists():
        raise LabConfigError("Global config not found. Run `lab setup` first (or `runner.run_interactive_global_setup()`).")
    if not project_is_initialized(project_dir):
        raise LabConfigError(
            f"Project not initialized at {project_dir}. Run `lab init` first (or `runner.init_project_at()`)."
        )

    from lab.git_checkpoint import ensure_git_repo

    gcfg = load_global_config()
    run_cfg = RunConfig.from_configs(gcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    ensure_git_repo(project_dir)
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)

    db_path = researcher_root / "runtime.db"
    conn = db.connect_db(db_path)
    try:
        st = db.get_system_state(conn)
        if st["control_mode"] == "active":
            db.set_control_mode(conn, "paused")
            conn.commit()
    finally:
        conn.close()

    return db_path, run_cfg


def run_lab_console(project_dir: Path | None = None) -> None:
    """Start the Textual console using on-disk global + project config (default *project_dir* = cwd)."""
    if project_dir is None:
        project_dir = Path.cwd()
    db_path, run_cfg = ensure_console_ready(project_dir)
    run_console_session(db_path, run_cfg, ensure_paused=False)


def run_console_session(
    db_path: Path,
    cfg: RunConfig,
    *,
    ensure_paused: bool = True,
) -> None:
    """Start the TUI with an explicit *RunConfig* and *db_path* (no TOML required).

    Use this from tests and scripts that build :class:`RunConfig` directly. Ensures memory layout
    and optionally forces ``control_mode`` to ``paused`` before opening the console.
    """
    memory.ensure_memory_layout(cfg.researcher_root, project_dir=cfg.project_dir)
    if ensure_paused:
        conn = db.connect_db(db_path)
        try:
            st = db.get_system_state(conn)
            if st["control_mode"] == "active":
                db.set_control_mode(conn, "paused")
                conn.commit()
        finally:
            conn.close()

    from lab.ui.console import run_console

    run_console(db_path, cfg)


def write_tier_a_brief(
    researcher_root: Path,
    *,
    research_idea: str,
    preferences: str,
) -> None:
    """Write ``research_idea.md`` and ``preferences.md`` in Tier A state.

    Called at ``lab init`` (and ``scripts/run.py``) to seed the project brief.
    Overwrites existing files.
    """
    state = researcher_root / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "research_idea.md").write_text(
        f"# Research brief\n\n{research_idea}\n", encoding="utf-8"
    )
    (state / "preferences.md").write_text(
        f"# Preferences\n\n{preferences}\n", encoding="utf-8"
    )


def seed_tier_a_from_run_config(researcher_root: Path, cfg: RunConfig) -> None:
    """Write system-owned ``system.md`` in Tier A (paths only until DB refresh)."""
    memory.write_system_tier_file(
        researcher_root,
        cfg.project_dir,
        recent_activity="*(no run events yet — start the scheduler)*",
    )


def init_project_at(
    project_dir: Path,
    *,
    research_idea: str,
    preferences: str = "",
    overwrite: bool = False,
) -> Path:
    """Create ``.lab/``, memory layout, and seed Tier A.

    Requires global config to exist. Returns the researcher root path.
    """
    if not global_config_exists():
        raise LabConfigError("Global config not found. Run `lab setup` first.")

    if project_is_initialized(project_dir) and not overwrite:
        raise LabConfigError(
            f"Project already initialized at {project_dir / '.lab'}; pass overwrite=True to re-seed."
        )

    from lab.git_checkpoint import ensure_git_repo

    gcfg = load_global_config()
    run_cfg = RunConfig.from_configs(gcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    researcher_root.mkdir(parents=True, exist_ok=True)
    ensure_git_repo(project_dir)
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
    write_tier_a_brief(researcher_root, research_idea=research_idea, preferences=preferences)
    seed_tier_a_from_run_config(researcher_root, run_cfg)
    mark_project_initialized(project_dir)
    return researcher_root


def run_oauth_browser_for_global(client_id: str | None = None) -> Path:
    """Run browser OAuth and store tokens under ``~/.lab/oauth_tokens.json``."""
    from lab.oauth_pkce import run_browser_login_once

    cid = client_id or DEFAULT_OAUTH_CLIENT_ID
    tmp_cfg = RunConfig(
        researcher_root=GLOBAL_DIR,
        project_dir=GLOBAL_DIR,
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
        cursor_agent_model="auto",
        oauth_client_id=cid,
        oauth_token_path=GLOBAL_OAUTH_PATH,
        oauth_extra_authorize_params={
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "codex_cli_rs",
        },
    )
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    return run_browser_login_once(tmp_cfg)


def run_interactive_global_setup() -> Path:
    """Interactive wizard: prompts and writes ``~/.lab/config.toml`` (and OAuth if chosen)."""
    import click

    click.echo("lab setup\n")

    provider = click.prompt(
        "Model provider",
        type=click.Choice(["openai", "openrouter", "local"], case_sensitive=False),
        default="openrouter",
    )

    defaults: dict[str, str] = {
        "openai": "gpt-4o-mini",
        "openrouter": "google/gemini-2.5-flash-lite",
        "local": "llama3",
    }
    model_name = click.prompt("Model name", default=defaults.get(provider, ""))
    base_url = ""
    if provider == "local":
        base_url = click.prompt("Base URL", default="http://127.0.0.1:11434/v1")

    api_key = ""
    oauth_client_id = DEFAULT_OAUTH_CLIENT_ID

    if provider == "openai":
        use_oauth = click.confirm("Authenticate via OAuth (browser)?", default=True)
        if use_oauth:
            run_oauth_browser_for_global(oauth_client_id)
        else:
            api_key = click.prompt("OpenAI API key", hide_input=True, default="")
    elif provider == "openrouter":
        api_key = click.prompt("OpenRouter API key", hide_input=True, default="")
    elif provider == "local":
        api_key = click.prompt("API key (blank for Ollama default)", default="ollama")

    worker_backend = click.prompt(
        "Default worker backend",
        type=click.Choice(["cursor", "claude"], case_sensitive=False),
        default="cursor",
    )
    cursor_agent_model = "auto"
    if worker_backend == "cursor":
        cursor_agent_model = click.prompt(
            "Cursor agent CLI model (--model)",
            default="auto",
        )

    click.echo("")
    click.echo(
        f"Optional: set default preferences under [preferences] code_style in {GLOBAL_CONFIG_PATH}; "
        "they are copied into new projects when you run `lab init`."
    )

    gcfg = GlobalConfig(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        oauth_client_id=oauth_client_id,
        worker_backend=worker_backend,
        cursor_agent_model=cursor_agent_model,
        code_style="",
    )
    return save_global_config(gcfg)


def bootstrap_bench_project(
    project_dir: Path,
    *,
    gcfg: GlobalConfig,
    research_idea: str = "",
    preferences: str = "",
) -> tuple[Path, RunConfig]:
    """Write global config and initialize memory (for scripts/tests without prior ``lab setup``).

    Overwrites global config at ``~/.lab/config.toml`` and initializes the project
    under *project_dir*.  Returns ``(db_path, RunConfig)`` suitable for :func:`run_console_session`.
    """
    save_global_config(gcfg)
    run_cfg = RunConfig.from_configs(gcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    researcher_root.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
    write_tier_a_brief(researcher_root, research_idea=research_idea, preferences=preferences)
    seed_tier_a_from_run_config(researcher_root, run_cfg)
    mark_project_initialized(project_dir)
    db_path = researcher_root / "runtime.db"
    return db_path, run_cfg


def reset_project_preserving_research_idea(project_dir: Path) -> None:
    """Clear SQLite runtime data and on-disk memory except Tier A ``research_idea.md`` and ``preferences.md``
    under ``.lab/state/``.
    """
    if not project_is_initialized(project_dir):
        raise LabConfigError(
            f"Project not initialized at {project_dir}. Run `lab init` first."
        )
    researcher_root = project_researcher_root(project_dir)
    sd = memory.state_dir(researcher_root)
    idea_path = sd / "research_idea.md"
    preserved = idea_path.read_text(encoding="utf-8") if idea_path.is_file() else "# Research brief\n\n"

    prefs_path = sd / "preferences.md"
    preserved_prefs = prefs_path.read_text(encoding="utf-8") if prefs_path.is_file() else "# Preferences\n\n"

    from lab.git_checkpoint import delete_checkpoint_branch

    db_path = researcher_root / "runtime.db"
    db.obliterate_runtime_db(db_path)
    delete_checkpoint_branch(project_dir)
    log_path = researcher_root / "scheduler.log"
    if log_path.is_file():
        log_path.unlink()
    memory.reset_runtime_artifacts(
        researcher_root,
        preserved_research_idea_md=preserved,
        preserved_preferences_md=preserved_prefs,
        project_dir=project_dir,
    )
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
