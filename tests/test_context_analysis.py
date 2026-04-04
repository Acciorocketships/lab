"""Diagnostic tests that measure context utilization and log structured data for analysis."""

from __future__ import annotations

import json
from pathlib import Path

from research_lab import helpers, memory, packets

LOG_DIR = Path(__file__).parent / "logs"


def _log(name: str, data: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Measure Tier A overhead
# ---------------------------------------------------------------------------


def test_measure_tier_a_overhead(tmp_path: Path) -> None:
    """With default seed content, how much of orchestrator/packet context is structural overhead?"""
    memory.ensure_memory_layout(tmp_path)

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(tmp_path, tier=tier, current_branch="")
    pkt = packets.build_worker_packet(
        worker="planner", researcher_root=tmp_path, task="Plan next steps",
    )

    total_tier_content = sum(len(v) for v in tier.values())
    user_content_chars = 0  # seed files are all boilerplate
    overhead_chars_ctx = len(ctx) - user_content_chars
    overhead_chars_pkt = len(pkt) - user_content_chars

    _log("tier_a_overhead", {
        "tier_a_file_count": len(memory.TIER_A_FILES),
        "total_tier_content_chars": total_tier_content,
        "orchestrator_ctx_chars": len(ctx),
        "packet_chars": len(pkt),
        "overhead_ctx_chars": overhead_chars_ctx,
        "overhead_pkt_chars": overhead_chars_pkt,
        "overhead_pct_of_orch_budget": round(overhead_chars_ctx / 12000 * 100, 1),
        "overhead_pct_of_pkt_budget": round(overhead_chars_pkt / 24000 * 100, 1),
        "per_file_sizes": {name: len(tier[name]) for name in memory.TIER_A_FILES},
    })

    assert len(ctx) > 0
    assert len(pkt) > 0


# ---------------------------------------------------------------------------
# 2. Measure context utilization for a realistic project
# ---------------------------------------------------------------------------


def test_measure_context_utilization(tmp_path: Path) -> None:
    """Simulate a realistic project state and measure budget utilization."""
    memory.ensure_memory_layout(tmp_path)

    helpers.write_text(
        memory.state_dir(tmp_path) / "research_idea.md",
        "# Research idea\n\nTrain a transformer on protein folding prediction using AlphaFold datasets. "
        "Compare attention mechanisms. " * 40 + "\n",
    )
    helpers.write_text(
        memory.state_dir(tmp_path) / "roadmap.md",
        "# Roadmap\n\n" + "".join(f"- Phase {i}: {'task description ' * 10}\n" for i in range(20)),
    )
    helpers.write_text(
        memory.state_dir(tmp_path) / "immediate_plan.md",
        "# Immediate plan\n\n" + "".join(f"- [ ] Step {i}: implement {'detail ' * 8}\n" for i in range(10)),
    )
    helpers.write_text(
        memory.state_dir(tmp_path) / "status.md",
        "# Status\n\nCurrently training model v3. Loss at 0.42, target 0.35.\n",
    )
    memory.write_context_summary(
        tmp_path,
        "# Rolling context\n\n" + "Previous cycles established baseline. " * 80,
    )

    for i in range(5):
        memory.append_episode_index_entry(
            tmp_path, cycle=i + 1, worker="researcher",
            task=f"Search for papers on topic {i}",
            reason=f"Need more literature on aspect {i}",
            episode_relpath=memory.episodes_cycle_relpath(cycle=i + 1, worker="researcher"),
        )

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        last_worker_output="Found 3 relevant papers. Key insight: attention heads specialize by amino acid type. " * 20,
        previous_context_summary=memory.read_context_summary(tmp_path),
    )
    pkt = packets.build_worker_packet(
        worker="researcher", researcher_root=tmp_path, task="Continue literature review",
    )

    orch_budget = 12000
    pkt_budget = 24000
    orch_util = min(len(ctx), orch_budget) / orch_budget * 100
    pkt_util = min(len(pkt), pkt_budget) / pkt_budget * 100

    _log("context_utilization", {
        "orchestrator": {
            "raw_chars": len(ctx),
            "budget": orch_budget,
            "used_after_cap": min(len(ctx), orch_budget),
            "utilization_pct": round(orch_util, 1),
            "overflow_chars": max(0, len(ctx) - orch_budget),
        },
        "packet": {
            "raw_chars": len(pkt),
            "budget": pkt_budget,
            "used_after_trim": min(len(pkt), pkt_budget),
            "utilization_pct": round(pkt_util, 1),
            "overflow_chars": max(0, len(pkt) - pkt_budget),
        },
        "per_file_chars": {name: len(tier[name]) for name in memory.TIER_A_FILES},
    })

    assert orch_util > 0
    assert pkt_util > 0


# ---------------------------------------------------------------------------
# 3. Information survival over 10 cycles
# ---------------------------------------------------------------------------


def test_information_survival_over_10_cycles(tmp_path: Path) -> None:
    """Simulate 10 cycles with unique facts; measure how many survive in the context summary."""
    memory.ensure_memory_layout(tmp_path)

    facts: list[str] = [f"FACT_{i:03d}" for i in range(10)]
    cycle_snapshots: list[dict] = []

    current_summary = ""
    for cycle, fact in enumerate(facts):
        worker_output = f"In cycle {cycle}, we discovered {fact}: the learning rate should be {0.001 * (cycle + 1):.4f}."

        # Simulate orchestrator merging prior summary + worker output into new summary.
        # Use a simple concatenation strategy (real LLM would compress more aggressively).
        new_summary_parts = []
        if current_summary:
            # Keep only last 6000 chars of prior summary (simulating compression)
            new_summary_parts.append(current_summary[-6000:])
        new_summary_parts.append(f"\n- Cycle {cycle}: {fact} — {worker_output}\n")
        current_summary = "".join(new_summary_parts)
        memory.write_context_summary(tmp_path, current_summary)

        surviving = [f for f in facts[:cycle + 1] if f in current_summary]
        cycle_snapshots.append({
            "cycle": cycle,
            "fact_introduced": fact,
            "summary_len": len(current_summary),
            "surviving_facts": surviving,
            "survival_count": len(surviving),
            "total_introduced": cycle + 1,
            "survival_rate": round(len(surviving) / (cycle + 1) * 100, 1),
        })

    final_summary = memory.read_context_summary(tmp_path)
    final_surviving = [f for f in facts if f in final_summary]
    final_missing = [f for f in facts if f not in final_summary]

    _log("information_survival", {
        "total_facts": len(facts),
        "surviving_in_final": len(final_surviving),
        "missing_from_final": final_missing,
        "final_summary_chars": len(final_summary),
        "cycle_snapshots": cycle_snapshots,
        "overall_survival_rate": round(len(final_surviving) / len(facts) * 100, 1),
    })

    assert len(final_surviving) > 0, "At least some facts should survive"


# ---------------------------------------------------------------------------
# 4. Character vs. token divergence
# ---------------------------------------------------------------------------


def test_char_vs_token_divergence(tmp_path: Path) -> None:
    """Measure how character budgets diverge from estimated token counts."""
    memory.ensure_memory_layout(tmp_path)

    samples = {
        "english_prose": (
            "The transformer architecture has revolutionized natural language processing. "
            "Self-attention mechanisms allow the model to weigh the importance of different "
            "parts of the input sequence when producing each output element. "
        ) * 50,
        "code_python": (
            "def train_model(config: dict, data: DataLoader) -> nn.Module:\n"
            "    model = TransformerModel(**config)\n"
            "    optimizer = torch.optim.AdamW(model.parameters(), lr=config['lr'])\n"
            "    for epoch in range(config['epochs']):\n"
            "        for batch in data:\n"
            "            loss = model(batch)\n"
            "            loss.backward()\n"
            "            optimizer.step()\n"
        ) * 30,
        "markdown_structured": (
            "# Section\n\n## Subsection\n\n- Item 1: description\n- Item 2: description\n"
            "| Col A | Col B |\n|-------|-------|\n| val1 | val2 |\n\n"
            "```python\nprint('hello')\n```\n\n"
        ) * 40,
        "mixed_technical": (
            "Learning rate: 3e-4, batch size: 32, epochs: 100. "
            "F1-score: 0.847 (+/- 0.023). Parameters: 125M. "
            "GPU: A100 80GB, training time: 4.5 hours. "
        ) * 60,
    }

    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        count_tokens = lambda text: len(enc.encode(text))
        tokenizer = "tiktoken/gpt-4o"
    except ImportError:
        count_tokens = lambda text: len(text.split())
        tokenizer = "whitespace-split (tiktoken not installed)"

    results: dict[str, dict] = {}
    for name, text in samples.items():
        chars = len(text)
        tokens = count_tokens(text)
        ratio = chars / tokens if tokens > 0 else 0

        results[name] = {
            "chars": chars,
            "tokens": tokens,
            "chars_per_token": round(ratio, 2),
            "char_budget_4000_actual_tokens": count_tokens(text[:4000]),
            "char_budget_12000_actual_tokens": count_tokens(text[:12000]) if chars >= 12000 else count_tokens(text),
        }

    # Measure divergence for actual Tier A content
    helpers.write_text(
        memory.state_dir(tmp_path) / "research_idea.md",
        samples["english_prose"][:3000],
    )
    helpers.write_text(memory.state_dir(tmp_path) / "roadmap.md", samples["markdown_structured"][:3000])
    memory.write_context_summary(tmp_path, samples["mixed_technical"][:4000])

    tier = memory.load_tier_a_bundle(tmp_path)
    ctx = memory.format_orchestrator_context(
        tmp_path, tier=tier, current_branch="",
        last_worker_output=samples["code_python"][:2000],
        previous_context_summary=memory.read_context_summary(tmp_path),
    )
    pkt = packets.build_worker_packet(
        worker="researcher", researcher_root=tmp_path, task="Review code",
    )

    ctx_tokens = count_tokens(ctx)
    pkt_tokens = count_tokens(pkt)

    results["orchestrator_context"] = {
        "chars": len(ctx),
        "tokens": ctx_tokens,
        "chars_per_token": round(len(ctx) / ctx_tokens, 2) if ctx_tokens > 0 else 0,
        "token_utilization_vs_128k": round(ctx_tokens / 128000 * 100, 2),
    }
    results["worker_packet"] = {
        "chars": len(pkt),
        "tokens": pkt_tokens,
        "chars_per_token": round(len(pkt) / pkt_tokens, 2) if pkt_tokens > 0 else 0,
        "token_utilization_vs_128k": round(pkt_tokens / 128000 * 100, 2),
    }

    _log("char_vs_token", {"tokenizer": tokenizer, "samples": results})

    for name, data in results.items():
        if data["chars_per_token"] > 0:
            assert 2.0 <= data["chars_per_token"] <= 8.0, (
                f"Unexpected chars/token ratio for {name}: {data['chars_per_token']}"
            )
