"""Tests for the programmatic runner API."""

from pathlib import Path

import pytest

from research_lab.config import RunConfig
from research_lab.global_config import GlobalConfig, ProjectConfig
from research_lab import db, memory
from research_lab.global_config import load_project_config
from research_lab.runner import (
    LabConfigError,
    bootstrap_bench_project,
    ensure_console_ready,
    init_project_at,
    reset_project_preserving_research_idea,
    run_console_session,
)


def test_ensure_console_ready_raises_without_global(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("research_lab.runner.global_config_exists", lambda: False)
    with pytest.raises(LabConfigError, match="Global config"):
        ensure_console_ready(tmp_path)


def test_ensure_console_ready_raises_without_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("research_lab.runner.global_config_exists", lambda: True)
    monkeypatch.setattr("research_lab.runner.project_is_initialized", lambda p: False)
    with pytest.raises(LabConfigError, match="not initialized"):
        ensure_console_ready(tmp_path)


def test_bootstrap_bench_project_writes_and_merges(tmp_path: Path, monkeypatch) -> None:
    gdir = tmp_path / "global"
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", gdir)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", gdir / "config.toml")

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gcfg = GlobalConfig(provider="openrouter", model_name="m", api_key="k")
    pcfg = ProjectConfig(research_idea="idea", preferences="")
    db_path, run_cfg = bootstrap_bench_project(project_dir, gcfg=gcfg, pcfg=pcfg)

    assert db_path == project_dir / ".airesearcher" / "data" / "runtime.db"
    assert run_cfg.research_idea == "idea"
    assert run_cfg.openrouter_api_key == "k"
    assert (gdir / "config.toml").is_file()
    assert (project_dir / ".airesearcher" / "config.toml").is_file()


def test_init_project_at_requires_global(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("research_lab.runner.global_config_exists", lambda: False)
    with pytest.raises(LabConfigError, match="Global config"):
        init_project_at(tmp_path, ProjectConfig(research_idea="a"))


def test_run_console_session_accepts_explicit_config(tmp_path: Path, monkeypatch) -> None:
    """Smoke: run_console_session wires memory + DB pause without starting the TUI."""
    pdir = tmp_path / "p"
    pdir.mkdir()
    rr = pdir / ".airesearcher"
    cfg = RunConfig(
        researcher_root=rr,
        project_dir=pdir,
        research_idea="x",
        preferences="z",
        orchestrator_backend="openrouter",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="m",
        default_worker_backend="cursor",
        cursor_agent_model="composer-2",
        openrouter_api_key="k",
    )
    db_path = rr / "data" / "runtime.db"

    called: list[tuple[Path, RunConfig]] = []

    def fake_run_console(db: Path, c: RunConfig) -> None:
        called.append((db, c))

    monkeypatch.setattr("research_lab.ui.console.run_console", fake_run_console)
    run_console_session(db_path, cfg)

    assert len(called) == 1
    assert called[0][0] == db_path
    assert called[0][1].project_dir == pdir


def test_reset_project_preserving_research_idea(tmp_path: Path, monkeypatch) -> None:
    gdir = tmp_path / "global"
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", gdir)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", gdir / "config.toml")

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    gcfg = GlobalConfig(provider="openrouter", model_name="m", api_key="k")
    pcfg = ProjectConfig(research_idea="original idea", preferences="keep pref")
    db_path, _ = bootstrap_bench_project(project_dir, gcfg=gcfg, pcfg=pcfg)

    conn = db.connect_db(db_path)
    db.add_instruction(conn, "do something")
    conn.commit()
    conn.close()

    rr = project_dir / ".airesearcher"
    (rr / "data" / "runtime" / "memory" / "extended" / "notes.md").write_text("x", encoding="utf-8")
    (memory.state_dir(rr) / "research_idea.md").write_text(
        "# Research brief\n\nMy preserved brief\n", encoding="utf-8"
    )
    (memory.state_dir(rr) / "preferences.md").write_text(
        "# Preferences\n\nCustom prefs line\n", encoding="utf-8"
    )

    reset_project_preserving_research_idea(project_dir)

    loaded = load_project_config(project_dir)
    assert "My preserved brief" in loaded.research_idea
    assert loaded.preferences == "Custom prefs line"

    conn = db.connect_db(db_path)
    assert conn.execute("SELECT COUNT(*) FROM instructions").fetchone()[0] == 0
    conn.close()

    assert not (rr / "data" / "runtime" / "memory" / "extended" / "notes.md").exists()
    assert (
        (memory.state_dir(rr) / "research_idea.md").read_text(encoding="utf-8")
        == "# Research brief\n\nMy preserved brief\n"
    )
    assert (
        (memory.state_dir(rr) / "preferences.md").read_text(encoding="utf-8")
        == "# Preferences\n\nCustom prefs line\n"
    )
