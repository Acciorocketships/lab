"""Tests for the programmatic runner API."""

from pathlib import Path

import pytest

from lab.config import RunConfig
from lab.global_config import GlobalConfig
from lab import db, memory
from lab.runner import (
    LabConfigError,
    _prompt_choice_radiolist,
    _prompt_text_dialog,
    bootstrap_bench_project,
    ensure_console_ready,
    init_project_at,
    reset_project_preserving_research_idea,
    run_console_session,
)


def test_ensure_console_ready_raises_without_global(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("lab.runner.global_config_exists", lambda: False)
    with pytest.raises(LabConfigError, match="Global config"):
        ensure_console_ready(tmp_path)


def test_ensure_console_ready_raises_without_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("lab.runner.global_config_exists", lambda: True)
    monkeypatch.setattr("lab.runner.project_is_initialized", lambda p: False)
    with pytest.raises(LabConfigError, match="not initialized"):
        ensure_console_ready(tmp_path)


def test_bootstrap_bench_project_writes_configs(tmp_path: Path, monkeypatch) -> None:
    gdir = tmp_path / "global"
    monkeypatch.setattr("lab.global_config.GLOBAL_DIR", gdir)
    monkeypatch.setattr("lab.global_config.GLOBAL_CONFIG_PATH", gdir / "config.toml")

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gcfg = GlobalConfig(provider="openrouter", model_name="m", api_key="k")
    db_path, run_cfg = bootstrap_bench_project(
        project_dir, gcfg=gcfg, research_idea="idea", preferences=""
    )

    assert db_path == project_dir / ".lab" / "runtime.db"
    assert run_cfg.openrouter_api_key == "k"
    assert (gdir / "config.toml").is_file()
    # Research idea lives in Tier A, not config.toml
    idea_md = (memory.state_dir(project_dir / ".lab") / "research_idea.md").read_text(encoding="utf-8")
    assert "idea" in idea_md


def test_init_project_at_requires_global(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("lab.runner.global_config_exists", lambda: False)
    with pytest.raises(LabConfigError, match="Global config"):
        init_project_at(tmp_path, research_idea="a")


def test_run_console_session_accepts_explicit_config(tmp_path: Path, monkeypatch) -> None:
    """Smoke: run_console_session wires memory + DB pause without starting the TUI."""
    pdir = tmp_path / "p"
    pdir.mkdir()
    rr = pdir / ".lab"
    cfg = RunConfig(
        researcher_root=rr,
        project_dir=pdir,
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="m",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        openrouter_api_key="k",
    )
    db_path = rr / "runtime.db"

    called: list[tuple[Path, RunConfig]] = []

    def fake_run_console(db: Path, c: RunConfig) -> None:
        called.append((db, c))

    monkeypatch.setattr("lab.ui.console.run_console", fake_run_console)
    run_console_session(db_path, cfg)

    assert len(called) == 1
    assert called[0][0] == db_path
    assert called[0][1].project_dir == pdir


def test_reset_project_preserving_research_idea(tmp_path: Path, monkeypatch) -> None:
    gdir = tmp_path / "global"
    monkeypatch.setattr("lab.global_config.GLOBAL_DIR", gdir)
    monkeypatch.setattr("lab.global_config.GLOBAL_CONFIG_PATH", gdir / "config.toml")

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gcfg = GlobalConfig(provider="openrouter", model_name="m", api_key="k")
    db_path, _ = bootstrap_bench_project(
        project_dir, gcfg=gcfg, research_idea="original idea", preferences="keep pref"
    )

    conn = db.connect_db(db_path)
    db.add_instruction(conn, "do something")
    conn.commit()
    conn.close()

    rr = project_dir / ".lab"
    (rr / "memory" / "extended" / "notes.md").write_text("x", encoding="utf-8")
    (rr / "logs" / "scheduler.log").write_text("scheduler output", encoding="utf-8")
    (rr / "logs" / "agent_3.log").write_text("agent output", encoding="utf-8")
    (rr / "legacy.log").write_text("legacy output", encoding="utf-8")
    (memory.state_dir(rr) / "research_idea.md").write_text(
        "# Research brief\n\nMy preserved brief\n", encoding="utf-8"
    )
    (memory.state_dir(rr) / "preferences.md").write_text(
        "# Preferences\n\nCustom prefs line\n", encoding="utf-8"
    )

    reset_project_preserving_research_idea(project_dir)

    # Tier A files are preserved directly
    assert (
        (memory.state_dir(rr) / "research_idea.md").read_text(encoding="utf-8")
        == "# Research brief\n\nMy preserved brief\n"
    )
    assert (
        (memory.state_dir(rr) / "preferences.md").read_text(encoding="utf-8")
        == "# Preferences\n\nCustom prefs line\n"
    )

    conn = db.connect_db(db_path)
    assert conn.execute("SELECT COUNT(*) FROM instructions").fetchone()[0] == 0
    conn.close()

    assert not (rr / "memory" / "extended" / "notes.md").exists()
    assert (rr / "logs").is_dir()
    assert not any((rr / "logs").glob("*.log"))
    assert not (rr / "legacy.log").exists()


def test_prompt_choice_radiolist_accepts_selection_via_arrow_keys(monkeypatch) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("lab.runner.sys.stdin", _TTY())
    monkeypatch.setattr("lab.runner.sys.stdout", _TTY())

    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            pipe_input.send_text("\x1b[B\x1b[C\r")
            result = _prompt_choice_radiolist(
                "Model provider",
                "Choose the backend that should power planning and routing.",
                [("openai", "OpenAI"), ("openrouter", "OpenRouter")],
                default="openai",
            )

    assert result == "openrouter"


def test_prompt_choice_radiolist_can_reach_cancel_via_arrow_keys(monkeypatch) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("lab.runner.sys.stdin", _TTY())
    monkeypatch.setattr("lab.runner.sys.stdout", _TTY())

    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            pipe_input.send_text("\x1b[D\r")
            with pytest.raises(KeyboardInterrupt):
                _prompt_choice_radiolist(
                    "Default worker backend",
                    "Choose which coding agent lab should launch by default.",
                    [("cursor", "Cursor agent CLI"), ("claude", "Claude Code")],
                    default="cursor",
                )


def test_prompt_text_dialog_accepts_typed_value(monkeypatch) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("lab.runner.sys.stdin", _TTY())
    monkeypatch.setattr("lab.runner.sys.stdout", _TTY())

    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            pipe_input.send_text("gpt-5-mini\r\r")
            result = _prompt_text_dialog(
                "Model name",
                "Enter the model identifier lab should use for orchestration.",
            )

    assert result == "gpt-5-mini"


def test_prompt_text_dialog_can_cancel(monkeypatch) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    class _TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("lab.runner.sys.stdin", _TTY())
    monkeypatch.setattr("lab.runner.sys.stdout", _TTY())

    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            pipe_input.send_text("\x1b")
            with pytest.raises(KeyboardInterrupt):
                _prompt_text_dialog(
                    "Base URL",
                    "Enter the OpenAI-compatible endpoint for your local or self-hosted model.",
                    default="http://127.0.0.1:11434/v1",
                )
