"""One-shot chat completion to verify credentials (API key or OAuth token file). Keep PROJECT_DIR / RESEARCHER_ROOT in sync with scripts/run.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Same session as scripts/run.py / scripts/oauth_login.py -----------------------------------
PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "project_stub"
RESEARCHER_ROOT = PROJECT_DIR / ".airesearcher"
# openai | openrouter | local (override: export AIRESEARCHER_ORCHESTRATOR_BACKEND=openrouter)
ORCHESTRATOR_BACKEND = os.environ.get("AIRESEARCHER_ORCHESTRATOR_BACKEND", "openai")
OPENAI_MODEL = os.environ.get("AIRESEARCHER_OPENAI_MODEL", "gpt-4o-mini")
# ----------------------------------------------------------------------------------------------


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from research_lab.config import RunConfig
    from research_lab.llm import generate, resolve_llm_api_key, resolve_llm_base_url

    cfg = RunConfig(
        researcher_root=RESEARCHER_ROOT,
        project_dir=PROJECT_DIR,
        research_idea="smoke",
        acceptance_criteria="smoke",
        preferences="smoke",
        orchestrator_backend=ORCHESTRATOR_BACKEND,
        openai_api_key=None,
        openai_base_url=None,
        openai_model=OPENAI_MODEL,
        default_worker_backend="cursor",
    )
    api_key = resolve_llm_api_key(cfg)
    base_url = resolve_llm_base_url(cfg)
    if not api_key:
        print(
            "No credential: for openai set OPENAI_API_KEY or run scripts/oauth_login.py; "
            "for openrouter set OPENROUTER_API_KEY; for local set keys per README. "
            f"(OAuth file: {RESEARCHER_ROOT / 'data' / 'oauth_openai_tokens.json'})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    backend = (cfg.orchestrator_backend or "openai").lower()
    if backend == "openai":
        src = "OPENAI_API_KEY env" if os.environ.get("OPENAI_API_KEY") else "OAuth token file"
    elif backend == "openrouter":
        src = "OPENROUTER_API_KEY env or RunConfig.openrouter_api_key"
    else:
        src = "local (openai_api_key / OPENAI_API_KEY / LOCAL_LLM_API_KEY)"
    print(f"Backend={backend} base_url={base_url!r} credential={src}", file=sys.stderr)

    try:
        text = generate(
            [{"role": "user", "content": "Reply with exactly one word: pong"}],
            model=cfg.openai_model,
            base_url=base_url,
            api_key=api_key,
        )
    except Exception as e:
        print(f"API call failed: {e}", file=sys.stderr)
        if backend == "local":
            print(
                "Local hint: start an OpenAI-compatible server (e.g. `ollama serve`), "
                "`ollama pull qwen3.5:0.8b` (or another tag), then re-run. "
                "Override base URL with LOCAL_LLM_BASE_URL or openai_base_url in run config.",
                file=sys.stderr,
            )
        raise SystemExit(2) from e
    print("LLM reply:", text.strip()[:500])


if __name__ == "__main__":
    main()
