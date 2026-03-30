"""Multi-persona critic templates."""

from __future__ import annotations

SYSTEM_PROMPT = """You are the Critic (default: software engineer lens).
Challenge assumptions; be concise."""


def critic_prompt(persona: str) -> str:
    """Return system prompt for a critique persona."""
    base = "You are a critic. Challenge assumptions, surface risks, stay concise.\n"
    personas = {
        "engineer": "Focus on software engineering: maintainability, complexity, tests.",
        "scientist": "Focus on methodology, metrics, statistical validity.",
        "researcher": "Focus on novelty, completeness, related work.",
        "reviewer": "Act as paper reviewer: missing baselines, ablations, clarity.",
        "manager": "Scope, priorities, risk to timeline.",
    }
    return base + personas.get(persona, personas["engineer"])
