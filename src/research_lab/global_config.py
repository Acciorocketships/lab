"""Global (~/.airesearcher/) configuration with TOML persistence."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


GLOBAL_DIR = Path.home() / ".airesearcher"
GLOBAL_CONFIG_PATH = GLOBAL_DIR / "config.toml"
GLOBAL_OAUTH_PATH = GLOBAL_DIR / "oauth_tokens.json"

PROJECT_DIR_NAME = ".airesearcher"
# Sentinel written by `init_project_at`; presence means the project is initialized.
_PROJECT_INITIALIZED_SENTINEL = ".initialized"


@dataclass
class GlobalConfig:
    """Persisted in ~/.airesearcher/config.toml."""

    provider: str = "openrouter"
    model_name: str = "google/gemini-2.5-flash-lite"
    base_url: str = ""
    api_key: str = ""
    oauth_client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann"
    worker_backend: str = "cursor"
    cursor_agent_model: str = "composer-2"
    code_style: str = ""

    def to_toml(self) -> str:
        return (
            "[model]\n"
            f'provider = "{self.provider}"\n'
            f'name = "{self.model_name}"\n'
            f'base_url = "{self.base_url}"\n'
            "\n"
            "[auth]\n"
            f'api_key = "{self.api_key}"\n'
            f'oauth_client_id = "{self.oauth_client_id}"\n'
            "\n"
            "[worker]\n"
            f'backend = "{self.worker_backend}"\n'
            f'cursor_model = "{self.cursor_agent_model}"\n'
            "\n"
            "[preferences]\n"
            f"code_style = {_format_toml_string_value(self.code_style)}\n"
        )

    @classmethod
    def from_toml(cls, path: Path) -> GlobalConfig:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        model = data.get("model", {})
        auth = data.get("auth", {})
        worker = data.get("worker", {})
        prefs = data.get("preferences", {})
        return cls(
            provider=str(model.get("provider", "openrouter")),
            model_name=str(model.get("name", "google/gemini-2.5-flash-lite")),
            base_url=str(model.get("base_url", "")),
            api_key=str(auth.get("api_key", "")),
            oauth_client_id=str(auth.get("oauth_client_id", "app_EMoamEEZ73f0CkXaXp7hrann")),
            worker_backend=str(worker.get("backend", "cursor")),
            cursor_agent_model=str(worker.get("cursor_model", "composer-2")),
            code_style=str(prefs.get("code_style", "")),
        )


def _escape_toml(s: str) -> str:
    """Escape special chars for a TOML double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_toml_string_value(s: str) -> str:
    """Emit a TOML string value.

    Multiline values use a multiline **literal** string (``'''``) so backslashes stay literal.
    Basic multiline ``\"\"\"`` would treat ``\\`` as escapes and break on Windows paths, LaTeX, etc.
    """
    if not s:
        return '""'
    if "\n" in s:
        if "'''" in s:
            return '"' + _escape_toml(s) + '"'
        return "'''\n" + s + "'''"
    return '"' + _escape_toml(s) + '"'


def global_config_exists() -> bool:
    return GLOBAL_CONFIG_PATH.is_file()


def load_global_config() -> GlobalConfig:
    if not GLOBAL_CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Global config not found at {GLOBAL_CONFIG_PATH}. Run `lab setup` first."
        )
    return GlobalConfig.from_toml(GLOBAL_CONFIG_PATH)


def save_global_config(cfg: GlobalConfig) -> Path:
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(cfg.to_toml(), encoding="utf-8")
    return GLOBAL_CONFIG_PATH


def project_researcher_root(project_dir: Path) -> Path:
    return project_dir / PROJECT_DIR_NAME


def project_is_initialized(project_dir: Path) -> bool:
    """True if this project directory has been initialized with ``lab init``.

    Checks for the new ``.initialized`` sentinel first (written by the current
    ``init_project_at``), then falls back to the legacy per-project ``config.toml``
    for projects initialized before this refactor.
    """
    airesearcher = project_dir / PROJECT_DIR_NAME
    if (airesearcher / _PROJECT_INITIALIZED_SENTINEL).is_file():
        return True
    # Legacy compatibility: pre-refactor projects used a per-project config.toml.
    if (airesearcher / "config.toml").is_file():
        return True
    return False


def mark_project_initialized(project_dir: Path) -> None:
    """Write the ``.initialized`` sentinel under ``.airesearcher/``."""
    sentinel = project_dir / PROJECT_DIR_NAME / _PROJECT_INITIALIZED_SENTINEL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("", encoding="utf-8")
