"""Shared programmatic API for lab: CLI, scripts, and tests use the same entry points."""

from __future__ import annotations

from pathlib import Path

from research_lab import db, memory
from research_lab.config import RunConfig
from research_lab.global_config import (
    GLOBAL_DIR,
    GLOBAL_OAUTH_PATH,
    GlobalConfig,
    ProjectConfig,
    global_config_exists,
    load_global_config,
    load_project_config,
    project_is_initialized,
    project_researcher_root,
    save_global_config,
    save_project_config,
)


class LabConfigError(RuntimeError):
    """Raised when global or project configuration is missing or invalid."""


DEFAULT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


def ensure_console_ready(project_dir: Path) -> tuple[Path, RunConfig]:
    """Load merged config, ensure memory layout, pause active scheduler row, return db path and RunConfig.

    Requires ``~/.airesearcher/config.toml`` and ``<project_dir>/.airesearcher/config.toml``.
    """
    if not global_config_exists():
        raise LabConfigError("Global config not found. Run `lab setup` first (or `runner.run_interactive_global_setup()`).")
    if not project_is_initialized(project_dir):
        raise LabConfigError(
            f"Project not initialized at {project_dir}. Run `lab init` first (or `runner.init_project_at()`)."
        )

    gcfg = load_global_config()
    pcfg = load_project_config(project_dir)
    run_cfg = RunConfig.from_configs(gcfg, pcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    memory.ensure_memory_layout(researcher_root)

    db_path = researcher_root / "data" / "runtime.db"
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
    memory.ensure_memory_layout(cfg.researcher_root)
    if ensure_paused:
        conn = db.connect_db(db_path)
        try:
            st = db.get_system_state(conn)
            if st["control_mode"] == "active":
                db.set_control_mode(conn, "paused")
                conn.commit()
        finally:
            conn.close()

    from research_lab.ui.console import run_console

    run_console(db_path, cfg)


def seed_tier_a_from_run_config(researcher_root: Path, cfg: RunConfig) -> None:
    """Write core Tier A markdown files from *cfg* (overwrites if present)."""
    state = researcher_root / "data" / "runtime" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "research_idea.md").write_text(f"# Research idea\n\n{cfg.research_idea}\n", encoding="utf-8")
    (state / "acceptance_criteria.md").write_text(
        f"# Acceptance criteria\n\n{cfg.acceptance_criteria}\n", encoding="utf-8"
    )
    (state / "preferences.md").write_text(f"# Preferences\n\n{cfg.preferences}\n", encoding="utf-8")
    (state / "project_brief.md").write_text(
        f"# Project\n\nImplementation directory: `{cfg.project_dir}`\n", encoding="utf-8"
    )


def init_project_at(
    project_dir: Path,
    pcfg: ProjectConfig,
    *,
    overwrite: bool = False,
) -> Path:
    """Create ``.airesearcher/``, project ``config.toml``, memory layout, and seed Tier A.

    Requires global config to exist. Returns the researcher root path.
    """
    if not global_config_exists():
        raise LabConfigError("Global config not found. Run `lab setup` first.")

    if project_is_initialized(project_dir) and not overwrite:
        raise LabConfigError(
            f"Project already initialized at {project_dir / '.airesearcher'}; pass overwrite=True to re-seed."
        )

    gcfg = load_global_config()
    save_project_config(project_dir, pcfg)
    run_cfg = RunConfig.from_configs(gcfg, pcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    researcher_root.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(researcher_root)
    seed_tier_a_from_run_config(researcher_root, run_cfg)
    return researcher_root


def run_oauth_browser_for_global(client_id: str | None = None) -> Path:
    """Run browser OAuth and store tokens under ``~/.airesearcher/oauth_tokens.json``."""
    from research_lab.oauth_pkce import run_browser_login_once

    cid = client_id or DEFAULT_OAUTH_CLIENT_ID
    tmp_cfg = RunConfig(
        researcher_root=GLOBAL_DIR,
        project_dir=GLOBAL_DIR,
        research_idea="",
        acceptance_criteria="",
        preferences="",
        orchestrator_backend="openai",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="gpt-4o-mini",
        default_worker_backend="cursor",
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
    """Interactive wizard: prompts and writes ``~/.airesearcher/config.toml`` (and OAuth if chosen)."""
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

    code_style = click.prompt(
        "Code style preferences (free text, or leave blank)",
        default="",
    )

    gcfg = GlobalConfig(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        oauth_client_id=oauth_client_id,
        worker_backend=worker_backend,
        code_style=code_style,
    )
    return save_global_config(gcfg)


def bootstrap_bench_project(
    project_dir: Path,
    *,
    gcfg: GlobalConfig,
    pcfg: ProjectConfig,
) -> tuple[Path, RunConfig]:
    """Write global + project TOML and initialize memory (for scripts/tests without prior ``lab setup``).

    Overwrites global config at ``~/.airesearcher/config.toml`` and project config under *project_dir*.
    Returns ``(db_path, RunConfig)`` suitable for :func:`run_console_session`.
    """
    save_global_config(gcfg)
    save_project_config(project_dir, pcfg)
    run_cfg = RunConfig.from_configs(gcfg, pcfg, project_dir)
    researcher_root = project_researcher_root(project_dir)
    researcher_root.mkdir(parents=True, exist_ok=True)
    memory.ensure_memory_layout(researcher_root)
    seed_tier_a_from_run_config(researcher_root, run_cfg)
    db_path = researcher_root / "data" / "runtime.db"
    return db_path, run_cfg
