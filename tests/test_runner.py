"""Tests for the programmatic runner API."""

from pathlib import Path

import pytest

from research_lab.config import RunConfig
from research_lab.global_config import GlobalConfig, ProjectConfig
from research_lab.runner import (
    LabConfigError,
    bootstrap_bench_project,
    ensure_console_ready,
    init_project_at,
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
