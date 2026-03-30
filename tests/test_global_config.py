"""Tests for global and project config TOML persistence."""

from pathlib import Path

from research_lab.config import RunConfig
from research_lab.global_config import (
    GlobalConfig,
    ProjectConfig,
    load_global_config,
    load_project_config,
    project_is_initialized,
    save_global_config,
    save_project_config,
)


def test_global_config_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", tmp_path)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

    cfg = GlobalConfig(
        provider="openrouter",
        model_name="google/gemini-2.5-flash-lite",
        base_url="",
        api_key="sk-test-key",
        worker_backend="cursor",
        code_style="Clean Python",
    )
    save_global_config(cfg)
    loaded = load_global_config()
    assert loaded.provider == "openrouter"
    assert loaded.model_name == "google/gemini-2.5-flash-lite"
    assert loaded.api_key == "sk-test-key"
    assert loaded.worker_backend == "cursor"
    assert loaded.code_style == "Clean Python"


def test_project_config_roundtrip(tmp_path: Path) -> None:
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    cfg = ProjectConfig(
        research_idea="Train Q-learning on FrozenLake\n\n## Success criteria\n\nSuccess rate > 90%",
        preferences="numpy only",
    )
    save_project_config(project_dir, cfg)
    assert project_is_initialized(project_dir)

    loaded = load_project_config(project_dir)
    assert loaded.research_idea == "Train Q-learning on FrozenLake\n\n## Success criteria\n\nSuccess rate > 90%"
    assert loaded.preferences == "numpy only"


def test_legacy_acceptance_criteria_merged_into_research_idea(tmp_path: Path) -> None:
    """Old configs with [project].acceptance_criteria merge into research_idea on load."""
    project_dir = tmp_path / "legacy_proj"
    project_dir.mkdir()
    cfg_path = project_dir / ".airesearcher" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(
        '[project]\n'
        'research_idea = "Goal A"\n'
        'acceptance_criteria = "Must pass tests"\n'
        'preferences = ""\n',
        encoding="utf-8",
    )
    loaded = load_project_config(project_dir)
    assert "Goal A" in loaded.research_idea
    assert "Must pass tests" in loaded.research_idea
    assert "## Success criteria" in loaded.research_idea


def test_project_not_initialized(tmp_path: Path) -> None:
    assert not project_is_initialized(tmp_path)


def test_from_configs_merges_correctly(tmp_path: Path) -> None:
    gcfg = GlobalConfig(
        provider="openrouter",
        model_name="gemini-2.5-flash-lite",
        api_key="sk-or",
        worker_backend="cursor",
        code_style="type hints",
    )
    pcfg = ProjectConfig(
        research_idea="Do X\n\n## Success criteria\n\nY works",
        preferences="",
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    run_cfg = RunConfig.from_configs(gcfg, pcfg, project_dir)

    assert run_cfg.orchestrator_backend == "openrouter"
    assert run_cfg.openai_model == "gemini-2.5-flash-lite"
    assert run_cfg.openrouter_api_key == "sk-or"
    assert run_cfg.default_worker_backend == "cursor"
    assert run_cfg.research_idea == "Do X\n\n## Success criteria\n\nY works"
    assert run_cfg.preferences == "type hints"
    assert run_cfg.researcher_root == project_dir / ".airesearcher"


def test_from_configs_project_prefs_override_global(tmp_path: Path) -> None:
    gcfg = GlobalConfig(code_style="global style")
    pcfg = ProjectConfig(
        research_idea="x",
        preferences="project style",
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    run_cfg = RunConfig.from_configs(gcfg, pcfg, project_dir)
    assert run_cfg.preferences == "project style"


def test_toml_escaping_roundtrip(tmp_path: Path) -> None:
    """Values with quotes and newlines survive TOML round-trip."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    cfg = ProjectConfig(
        research_idea='Test "quoted" idea\n\n## Success criteria\n\nline1\nline2',
        preferences="",
    )
    save_project_config(project_dir, cfg)
    loaded = load_project_config(project_dir)
    assert loaded.research_idea == 'Test "quoted" idea\n\n## Success criteria\n\nline1\nline2'


def test_global_code_style_multiline_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", tmp_path)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

    cfg = GlobalConfig(
        code_style="Rule A\nRule B\n- use types",
    )
    save_global_config(cfg)
    loaded = load_global_config()
    assert loaded.code_style == "Rule A\nRule B\n- use types"
