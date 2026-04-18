"""Shared programmatic API for lab: CLI, scripts, and tests use the same entry points."""

from __future__ import annotations

import json
import os
import sys
import tomllib
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
_SETUP_DIALOG_WIDTH = 96

_SETUP_STYLE_OVERRIDES = {
    "dialog": "bg:#0b0e11",
    "dialog.body": "bg:#11161b #e5eaef",
    "dialog shadow": "bg:#06080a",
    "dialog.body shadow": "bg:#0a0d10",
    "frame.border": "#33404c",
    "dialog frame.label": "bold #c8dcff",
    "frame.border shadow": "#06080a",
    "setup-badge": "bg:#202b36 #a9bed6 bold",
    "setup-section": "bold #f5f7fa",
    "setup-copy": "#9fb0bf",
    "setup-hint": "#738596",
    "setup-radio-list": "bg:#11161b",
    "setup-radio": "#d6dee6",
    "setup-radio-selected": "bg:#1c2630 #f5f7fa",
    "setup-radio-checked": "bold #8fb9ff",
    "setup-input-shell": "bg:#0f1419",
    "setup-input": "bg:#0f1419 #f5f7fa",
    "setup-input.cursor-line": "bg:#16202a",
    "setup-input.selection": "bg:#24415f",
    "dialog.body text-area": "bg:#0f1419 #f5f7fa",
    "dialog.body text-area cursor-line": "bg:#16202a",
    "dialog.body text-area last-line": "nounderline",
    "validation-toolbar": "bg:#3a2020 #ffd7d7",
    "button": "bg:#151b21 #98a9b8",
    "button.focused": "bg:#b7d3ff #091019 bold",
    "button.arrow": "bold",
}


def _global_oauth_looks_logged_in() -> bool:
    """True if ``~/.lab/oauth_tokens.json`` exists and appears to hold OAuth material."""
    if not GLOBAL_OAUTH_PATH.is_file():
        return False
    try:
        data = json.loads(GLOBAL_OAUTH_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(
        data.get("access_token")
        or data.get("oauth_access_token")
        or data.get("refresh_token")
        or data.get("id_token")
    )


def _setup_dialog_intro(title: str, text: str, hint: str) -> list[tuple[str, str]]:
    """Shared formatted header copy for setup dialogs."""
    return [
        ("class:setup-section", f"{title.upper()}\n"),
        ("class:setup-copy", f"{text.strip()}\n"),
        ("class:setup-hint", hint),
    ]


def _setup_dialog_style():
    """Shared prompt_toolkit style for setup screens."""
    from prompt_toolkit.styles import Style, merge_styles
    from prompt_toolkit.styles.defaults import default_ui_style

    return merge_styles(
        [
            default_ui_style(),
            Style.from_dict(_SETUP_STYLE_OVERRIDES),
        ]
    )


def _prompt_text_dialog(
    title: str,
    text: str,
    *,
    default: str = "",
    password: bool = False,
) -> str:
    """Read a single-line text value in the styled setup dialog when possible."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit.application import Application, get_app
            from prompt_toolkit.filters import has_focus
            from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
            from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
            from prompt_toolkit.key_binding.defaults import load_key_bindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.containers import HSplit, Window
            from prompt_toolkit.widgets import Button, Dialog, Label, TextArea
        except ImportError:
            Application = None  # type: ignore[misc, assignment]
        else:
            def ok_handler() -> None:
                get_app().exit(result=textfield.text)

            def cancel_handler() -> None:
                get_app().exit(result=None)

            ok_button = Button(
                text="OK",
                handler=ok_handler,
                width=10,
                left_symbol="[",
                right_symbol="]",
            )
            cancel_button = Button(
                text="CANCEL",
                handler=cancel_handler,
                width=14,
                left_symbol="[",
                right_symbol="]",
            )

            def accept(_) -> bool:
                get_app().layout.focus(ok_button)
                return True

            textfield = TextArea(
                text=default,
                multiline=False,
                password=password,
                accept_handler=accept,
                wrap_lines=False,
                style="class:setup-input",
                dont_extend_height=True,
                height=1,
                name="setup-input",
            )

            dialog = Dialog(
                title="LAB SETUP",
                body=HSplit(
                    [
                        Label(
                            text=_setup_dialog_intro(
                                title,
                                text,
                                "TYPE TO EDIT    DOWN for OK and CANCEL",
                            ),
                            dont_extend_height=True,
                        ),
                        Window(height=1, style="class:setup-input-shell"),
                        textfield,
                    ],
                    padding=1,
                ),
                buttons=[ok_button, cancel_button],
                with_background=True,
                width=_SETUP_DIALOG_WIDTH,
            )

            bindings = KeyBindings()
            bindings.add("tab")(focus_next)
            bindings.add("s-tab")(focus_previous)

            @bindings.add("down", filter=has_focus(textfield))
            def _focus_ok(event) -> None:
                event.app.layout.focus(ok_button)

            @bindings.add("up", filter=has_focus(ok_button))
            @bindings.add("up", filter=has_focus(cancel_button))
            def _focus_text(event) -> None:
                event.app.layout.focus(textfield)

            @bindings.add("escape")
            def _cancel_dialog(event) -> None:
                cancel_handler()

            result = Application(
                layout=Layout(dialog, focused_element=textfield),
                key_bindings=merge_key_bindings([load_key_bindings(), bindings]),
                mouse_support=True,
                style=_setup_dialog_style(),
                full_screen=True,
            ).run()
            if result is None:
                raise KeyboardInterrupt
            return str(result)

    import click

    return click.prompt(text or title, default=default, hide_input=password, show_default=not password)


def _prompt_choice_radiolist(
    title: str,
    text: str,
    choices: list[tuple[str, str]],
    *,
    default: str,
) -> str:
    """Pick one of *choices* as ``(value, label)`` using arrow keys + Enter when possible."""
    values = [v for v, _ in choices]
    if default not in values:
        default = values[0]
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit.application import Application, get_app
            from prompt_toolkit.filters import has_focus
            from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
            from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
            from prompt_toolkit.key_binding.defaults import load_key_bindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.containers import HSplit
            from prompt_toolkit.widgets import Button, Dialog, Label, RadioList
        except ImportError:
            Application = None  # type: ignore[misc, assignment]
        else:
            class SetupRadioList(RadioList[str]):
                open_character = "["
                close_character = "]"
                container_style = "class:setup-radio-list"
                default_style = "class:setup-radio"
                selected_style = "class:setup-radio-selected"
                checked_style = "class:setup-radio-checked"
                show_scrollbar = False

            def ok_handler() -> None:
                get_app().exit(result=radio_list.current_value)

            def cancel_handler() -> None:
                get_app().exit(result=None)

            radio_list = SetupRadioList(
                values=[(v, lab) for v, lab in choices],
                default=default,
            )
            ok_button = Button(
                text="OK",
                handler=ok_handler,
                width=10,
                left_symbol="[",
                right_symbol="]",
            )
            cancel_button = Button(
                text="CANCEL",
                handler=cancel_handler,
                width=14,
                left_symbol="[",
                right_symbol="]",
            )

            dialog = Dialog(
                title="LAB SETUP",
                body=HSplit(
                    [
                        Label(
                            text=_setup_dialog_intro(
                                title,
                                text,
                                "UP / DOWN choose option    ENTER select option    LEFT / RIGHT for OK and CANCEL",
                            ),
                            dont_extend_height=True,
                        ),
                        radio_list,
                    ],
                    padding=1,
                ),
                buttons=[ok_button, cancel_button],
                with_background=True,
                width=_SETUP_DIALOG_WIDTH,
            )

            bindings = KeyBindings()
            bindings.add("tab")(focus_next)
            bindings.add("s-tab")(focus_previous)

            @bindings.add("right", filter=has_focus(radio_list))
            def _focus_ok(event) -> None:
                radio_list._handle_enter()
                event.app.layout.focus(ok_button)

            @bindings.add("left", filter=has_focus(radio_list))
            def _focus_cancel(event) -> None:
                radio_list._handle_enter()
                event.app.layout.focus(cancel_button)

            @bindings.add("left", filter=has_focus(ok_button))
            @bindings.add("up", filter=has_focus(ok_button))
            def _focus_list_from_ok(event) -> None:
                event.app.layout.focus(radio_list)

            @bindings.add("up", filter=has_focus(cancel_button))
            def _focus_list_from_cancel(event) -> None:
                event.app.layout.focus(radio_list)

            @bindings.add("escape")
            def _cancel_dialog(event) -> None:
                cancel_handler()

            result = Application(
                layout=Layout(dialog),
                key_bindings=merge_key_bindings([load_key_bindings(), bindings]),
                mouse_support=True,
                style=_setup_dialog_style(),
                full_screen=True,
            ).run()
            if result is None:
                raise KeyboardInterrupt
            return str(result)
    import click

    return click.prompt(
        text or title,
        type=click.Choice(values, case_sensitive=False),
        default=default,
    )


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
    """Write system-owned ``system.md`` in Tier A (paths + placeholder activity until DB refresh)."""
    memory.write_system_tier_file(
        researcher_root,
        cfg.project_dir,
        recent_activity="",
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

    previous: GlobalConfig | None = None
    if global_config_exists():
        try:
            previous = load_global_config()
        except (OSError, ValueError, KeyError, TypeError, tomllib.TOMLDecodeError):
            previous = None

    default_provider = (previous.provider if previous else "openrouter") or "openrouter"
    provider = _prompt_choice_radiolist(
        "Model provider",
        "Choose which backend should power orchestration.",
        [
            ("openai", "OpenAI"),
            ("openrouter", "OpenRouter"),
            ("local", "Local (OpenAI-compatible, e.g. Ollama)"),
        ],
        default=default_provider,
    )

    defaults: dict[str, str] = {
        "openai": "gpt-4o-mini",
        "openrouter": "google/gemini-2.5-flash-lite",
        "local": "llama3",
    }
    model_default = defaults.get(provider, "")
    if previous and previous.provider == provider and (previous.model_name or "").strip():
        model_default = previous.model_name
    model_name = _prompt_text_dialog(
        "Model name",
        "Enter the model identifier lab should use for orchestration.",
        default=model_default,
    )
    base_url = ""
    if provider == "local":
        bu_default = (
            previous.base_url
            if previous and previous.provider == "local" and (previous.base_url or "").strip()
            else "http://127.0.0.1:11434/v1"
        )
        base_url = _prompt_text_dialog(
            "Base URL",
            "Enter the OpenAI-compatible endpoint for your local or self-hosted model.",
            default=bu_default,
        )

    api_key = ""
    oauth_client_id = (
        (previous.oauth_client_id or "").strip() or DEFAULT_OAUTH_CLIENT_ID
        if previous
        else DEFAULT_OAUTH_CLIENT_ID
    )

    if provider == "openai":
        if _global_oauth_looks_logged_in():
            click.echo("Using existing OAuth tokens from ~/.lab/oauth_tokens.json.")
        else:
            auth_how = _prompt_choice_radiolist(
                "OpenAI authentication",
                "Choose how lab should authenticate with OpenAI.",
                [
                    ("oauth", "OAuth (sign in with browser)"),
                    ("api_key", "API key (paste manually)"),
                ],
                default="oauth",
            )
            if auth_how == "oauth":
                run_oauth_browser_for_global(oauth_client_id)
            else:
                prev_ai = (
                    (previous.api_key or "").strip()
                    if previous and previous.provider == "openai"
                    else ""
                )
                if prev_ai:
                    api_key = prev_ai
                    click.echo("Keeping OpenAI API key from ~/.lab/config.toml.")
                else:
                    api_key = _prompt_text_dialog(
                        "OpenAI API key",
                        "Paste the API key lab should store for OpenAI requests.",
                        default="",
                        password=True,
                    )
    elif provider == "openrouter":
        prev_or = (
            (previous.api_key or "").strip()
            if previous and previous.provider == "openrouter"
            else ""
        )
        env_or = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if prev_or:
            api_key = prev_or
            click.echo("Keeping OpenRouter API key from ~/.lab/config.toml.")
        elif env_or:
            api_key = ""
            click.echo(
                "Using OPENROUTER_API_KEY from the environment (not written to config.toml)."
            )
        else:
            api_key = _prompt_text_dialog(
                "OpenRouter API key",
                "Paste the API key lab should store for OpenRouter requests.",
                default="",
                password=True,
            )
    elif provider == "local":
        loc_default = (
            previous.api_key
            if previous and previous.provider == "local" and (previous.api_key or "").strip()
            else "ollama"
        )
        api_key = _prompt_text_dialog(
            "Local API key",
            "Enter the API key for your local endpoint, or keep the default for Ollama.",
            default=loc_default,
        )

    wb_default = (previous.worker_backend if previous else "cursor") or "cursor"
    worker_backend = _prompt_choice_radiolist(
        "Default worker backend",
        "Choose which backend to use for the worker agents.",
        [
            ("cursor", "Cursor agent CLI"),
            ("claude", "Claude Code"),
        ],
        default=wb_default,
    )
    cursor_agent_model = "auto"
    if worker_backend == "cursor":
        cm_default = (
            previous.cursor_agent_model
            if previous and (previous.cursor_agent_model or "").strip()
            else "auto"
        )
        cursor_agent_model = _prompt_text_dialog(
            "Cursor agent CLI model",
            "Enter the LLM model used by cursor (run `agent models` to see available models).",
            default=cm_default,
        )

    click.echo("")
    click.echo(
        f"Optional: set default preferences under [preferences] code_style in {GLOBAL_CONFIG_PATH}; "
        "they are copied into new projects when you run `lab init`."
    )

    code_style_preserve = (previous.code_style if previous else "") or ""
    gcfg = GlobalConfig(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        oauth_client_id=oauth_client_id,
        worker_backend=worker_backend,
        cursor_agent_model=cursor_agent_model,
        code_style=code_style_preserve,
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
    memory.reset_runtime_artifacts(
        researcher_root,
        preserved_research_idea_md=preserved,
        preserved_preferences_md=preserved_prefs,
        project_dir=project_dir,
    )
    memory.ensure_memory_layout(researcher_root, project_dir=project_dir)
