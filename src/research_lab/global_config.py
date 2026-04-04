"""Global (~/.airesearcher/) and per-project (.airesearcher/) configuration with TOML persistence."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


GLOBAL_DIR = Path.home() / ".airesearcher"
GLOBAL_CONFIG_PATH = GLOBAL_DIR / "config.toml"
GLOBAL_OAUTH_PATH = GLOBAL_DIR / "oauth_tokens.json"

PROJECT_DIR_NAME = ".airesearcher"


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


@dataclass
class ProjectConfig:
    """Persisted in <project>/.airesearcher/config.toml."""

    research_idea: str = ""
    preferences: str = ""

    def to_toml(self) -> str:
        return (
            "[project]\n"
            f"research_idea = {_format_toml_string_value(self.research_idea)}\n"
            f"preferences = {_format_toml_string_value(self.preferences)}\n"
        )

    @classmethod
    def from_toml(cls, path: Path) -> ProjectConfig:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        proj = data.get("project", {})
        idea = str(proj.get("research_idea", ""))
        return cls(
            research_idea=idea,
            preferences=str(proj.get("preferences", "")),
        )


def _escape_toml(s: str) -> str:
    """Escape special chars for a TOML double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_toml_string_value(s: str) -> str:
    """Emit a TOML string value. Use a multiline ``\"\"\"`` block when *s* contains newlines (readable)."""
    if not s:
        return '""'
    if "\n" in s:
        if '"""' in s:
            return '"' + _escape_toml(s) + '"'
        return '"""\n' + s + '"""'
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


def project_config_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_DIR_NAME / "config.toml"


def project_researcher_root(project_dir: Path) -> Path:
    return project_dir / PROJECT_DIR_NAME


def project_is_initialized(project_dir: Path) -> bool:
    return project_config_path(project_dir).is_file()


def load_project_config(project_dir: Path) -> ProjectConfig:
    path = project_config_path(project_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"Project not initialized (no {path}). Run `lab init` in the project directory."
        )
    return ProjectConfig.from_toml(path)


def save_project_config(project_dir: Path, cfg: ProjectConfig) -> Path:
    path = project_config_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.to_toml(), encoding="utf-8")
    return path
