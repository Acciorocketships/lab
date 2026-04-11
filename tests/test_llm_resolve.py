"""resolve_llm_api_key / resolve_llm_base_url by orchestrator_backend."""

from pathlib import Path

from lab.config import RunConfig
from lab.llm import (
    describe_orchestrator_credential_source,
    resolve_llm_api_key,
    resolve_llm_base_url,
)


def _base_cfg(tmp_path: Path, **kwargs: object) -> RunConfig:
    defaults: dict[str, object] = {
        "researcher_root": tmp_path,
        "project_dir": tmp_path,
        "orchestrator_backend": "openai",
        "openai_api_key": None,
        "openai_base_url": None,
        "openai_model": "gpt-4o-mini",
        "default_worker_backend": "cursor",
        "cursor_agent_model": "auto",
    }
    defaults.update(kwargs)
    return RunConfig(**defaults)  # type: ignore[arg-type]


def test_resolve_openrouter_prefers_config_key(tmp_path: Path) -> None:
    cfg = _base_cfg(
        tmp_path,
        orchestrator_backend="openrouter",
        openrouter_api_key="sk-or",
    )
    assert resolve_llm_api_key(cfg) == "sk-or"
    assert resolve_llm_base_url(cfg) == "https://openrouter.ai/api/v1"


def test_resolve_openrouter_env_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env")
    cfg = _base_cfg(tmp_path, orchestrator_backend="openrouter", openrouter_api_key=None)
    assert resolve_llm_api_key(cfg) == "sk-env"


def test_resolve_openrouter_custom_base_url(tmp_path: Path) -> None:
    cfg = _base_cfg(
        tmp_path,
        orchestrator_backend="openrouter",
        openrouter_api_key="k",
        openai_base_url="https://example.com/v1",
    )
    assert resolve_llm_base_url(cfg) == "https://example.com/v1"


def test_resolve_local_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    cfg = _base_cfg(tmp_path, orchestrator_backend="local")
    assert resolve_llm_api_key(cfg) == "ollama"
    assert resolve_llm_base_url(cfg) == "http://127.0.0.1:11434/v1"


def test_resolve_local_env_base_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:8080/v1")
    cfg = _base_cfg(tmp_path, orchestrator_backend="local")
    assert resolve_llm_base_url(cfg) == "http://localhost:8080/v1"


def test_describe_openai_prefers_config_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _base_cfg(tmp_path, openai_api_key="sk-cfg")
    assert "global config" in describe_orchestrator_credential_source(cfg)


def test_describe_openai_env_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = _base_cfg(tmp_path, openai_api_key=None)
    assert "OPENAI_API_KEY" in describe_orchestrator_credential_source(cfg)


def test_describe_openai_oauth_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tok = tmp_path / "oauth_tokens.json"
    tok.write_text("{}", encoding="utf-8")
    cfg = _base_cfg(tmp_path, openai_api_key=None, oauth_token_path=tok)
    label = describe_orchestrator_credential_source(cfg)
    assert "OAuth token file" in label
    assert str(tok) in label


def test_describe_openrouter_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk")
    cfg = _base_cfg(tmp_path, orchestrator_backend="openrouter", openrouter_api_key=None)
    assert "OPENROUTER_API_KEY" in describe_orchestrator_credential_source(cfg)
