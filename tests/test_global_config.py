"""Tests for global config TOML persistence and project initialization detection."""

from pathlib import Path

from research_lab.config import RunConfig
from research_lab.global_config import (
    GlobalConfig,
    global_config_exists,
    load_global_config,
    mark_project_initialized,
    project_is_initialized,
    save_global_config,
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
        cursor_agent_model="auto",
        code_style="Clean Python",
    )
    save_global_config(cfg)
    loaded = load_global_config()
    assert loaded.provider == "openrouter"
    assert loaded.model_name == "google/gemini-2.5-flash-lite"
    assert loaded.api_key == "sk-test-key"
    assert loaded.worker_backend == "cursor"
    assert loaded.cursor_agent_model == "auto"
    assert loaded.code_style == "Clean Python"


def test_project_not_initialized(tmp_path: Path) -> None:
    assert not project_is_initialized(tmp_path)


def test_project_is_initialized_new_sentinel(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    assert not project_is_initialized(project_dir)
    mark_project_initialized(project_dir)
    assert project_is_initialized(project_dir)


def test_project_is_initialized_legacy_config_toml(tmp_path: Path) -> None:
    """Projects with a legacy per-project config.toml are still recognized as initialized."""
    project_dir = tmp_path / "proj"
    (project_dir / ".airesearcher").mkdir(parents=True)
    (project_dir / ".airesearcher" / "config.toml").write_text(
        '[project]\nresearch_idea = "old"\n', encoding="utf-8"
    )
    assert project_is_initialized(project_dir)


def test_from_configs_builds_run_config(tmp_path: Path) -> None:
    gcfg = GlobalConfig(
        provider="openrouter",
        model_name="gemini-2.5-flash-lite",
        api_key="sk-or",
        worker_backend="cursor",
        code_style="type hints",
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    run_cfg = RunConfig.from_configs(gcfg, project_dir)

    assert run_cfg.orchestrator_backend == "openrouter"
    assert run_cfg.openai_model == "gemini-2.5-flash-lite"
    assert run_cfg.openrouter_api_key == "sk-or"
    assert run_cfg.default_worker_backend == "cursor"
    assert run_cfg.cursor_agent_model == "auto"
    assert run_cfg.researcher_root == project_dir / ".airesearcher"
    assert run_cfg.orchestrator_input_max_chars is None
    assert run_cfg.orchestrator_prev_summary_max_chars is None
    assert run_cfg.orchestrator_last_worker_max_chars is None
    assert run_cfg.orchestrator_tier_file_max_chars is None
    assert run_cfg.orchestrator_branch_memory_max_chars is None
    assert run_cfg.worker_packet_max_chars is None


def test_global_code_style_multiline_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", tmp_path)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

    cfg = GlobalConfig(
        code_style="Rule A\nRule B\n- use types",
    )
    save_global_config(cfg)
    loaded = load_global_config()
    assert loaded.code_style == "Rule A\nRule B\n- use types"


def test_global_config_backslashes_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """Backslashes in multiline values must not break TOML."""
    monkeypatch.setattr("research_lab.global_config.GLOBAL_DIR", tmp_path)
    monkeypatch.setattr("research_lab.global_config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

    gcfg = GlobalConfig(code_style="See C:\\tools\\bin\nOr \\n is fine")
    save_global_config(gcfg)
    assert load_global_config().code_style == gcfg.code_style

