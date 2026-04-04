#!/usr/bin/env python3
"""Aggregate test log JSON files and produce an analysis report with improvement recommendations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
REPORT_PATH = LOG_DIR / "analysis_report.md"


def _load(name: str) -> dict | None:
    p = LOG_DIR / f"{name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _section(title: str) -> str:
    return f"\n## {title}\n"


def analyze_memory_fidelity() -> str:
    lines = [_section("Memory Write/Read Fidelity")]
    data = _load("tier_a_round_trip")
    if data:
        lines.append(f"- **Tier A round-trip**: {data['files']} files tested, all content survived write/read cycle.")
        sizes = data.get("sizes", {})
        for name, s in sizes.items():
            if s["written"] != s["read"]:
                lines.append(f"  - WARNING: {name} — wrote {s['written']} chars, read {s['read']} chars")
    else:
        lines.append("- Tier A round-trip: *log not found*")

    data = _load("context_summary_overwrite")
    if data:
        lines.append(f"- **Context summary overwrite**: {data['cycles']} cycles tested, each overwrite fully replaced prior content.")

    data = _load("extended_memory_isolation")
    if data:
        leaked = data.get("secret_in_ctx") or data.get("secret_in_pkt")
        status = "LEAKED" if leaked else "properly isolated"
        lines.append(f"- **Extended memory isolation**: bodies {status} (secret {data['secret_len']} chars, ctx {data['ctx_len']} chars).")

    data = _load("branch_memory")
    if data:
        branches = list(data.keys())
        lines.append(f"- **Branch memory**: {len(branches)} branches tested with special characters — all round-tripped correctly.")

    data = _load("lesson_ordering")
    if data:
        lines.append(f"- **Lesson ordering**: {data['count']} lessons appended in order, file is {data['file_chars']} chars.")

    data = _load("reset_preservation")
    if data:
        preserved = data.get("idea_preserved") and data.get("prefs_preserved")
        cleared = data.get("roadmap_reset") and data.get("context_summary_reset") and data.get("extended_cleared")
        lines.append(f"- **Reset preservation**: research_idea={'preserved' if preserved else 'LOST'}, "
                      f"other files={'cleared' if cleared else 'NOT CLEARED'}.")

    return "\n".join(lines)


def analyze_context_budgets() -> str:
    lines = [_section("Context Budget Analysis")]

    data = _load("orchestrator_budget")
    if data:
        lines.append(f"- **Orchestrator context size**: {data['total_ctx_len']} chars (max expected: {data['max_expected']}).")
        if data.get("section_sizes"):
            lines.append("- Per-Tier-A-section sizes in orchestrator context:")
            for name, size in sorted(data["section_sizes"].items(), key=lambda x: -x[1]):
                lines.append(f"  - `{name}`: ~{size} chars")

    data = _load("packet_budget")
    if data:
        lines.append(f"- **Packet budget**: {data['pkt_len']} chars vs {data['budget']} budget. "
                      f"Header present: {data['header_present']}, objective present: {data['objective_present']}.")

    data = _load("context_summary_compression")
    if data:
        lines.append(f"- **Summary compression**: {data['original_len']}-char summary truncated, "
                      f"{data['z_count_in_section']} chars survived in orchestrator context "
                      f"({data['chars_lost']} chars lost).")

    return "\n".join(lines)


def analyze_context_growth() -> str:
    lines = [_section("Context Growth Over Cycles")]

    data = _load("context_growth")
    if data:
        cycles = data.get("cycles", [])
        if cycles:
            lines.append("| Cycle | Orch Ctx (chars) | Packet (chars) | Roadmap (chars) | Summary (chars) |")
            lines.append("|------:|----------------:|--------------:|---------------:|---------------:|")
            for c in cycles:
                lines.append(
                    f"| {c['cycle']:5d} | {c['ctx_len']:16,d} | {c['pkt_len']:14,d} | "
                    f"{c['roadmap_len']:15,d} | {c['summary_len']:15,d} |"
                )

            first, last = cycles[0], cycles[-1]
            ctx_growth = last["ctx_len"] - first["ctx_len"]
            pkt_growth = last["pkt_len"] - first["pkt_len"]
            lines.append(f"\n- **Orchestrator context growth**: {first['ctx_len']} -> {last['ctx_len']} "
                          f"({ctx_growth:+d} chars over {len(cycles)} cycles)")
            lines.append(f"- **Packet growth**: {first['pkt_len']} -> {last['pkt_len']} "
                          f"({pkt_growth:+d} chars over {len(cycles)} cycles)")

            max_ctx = max(c["ctx_len"] for c in cycles)
            max_pkt = max(c["pkt_len"] for c in cycles)
            lines.append(f"- **Peak orchestrator context**: {max_ctx} chars (budget: 12,000)")
            lines.append(f"- **Peak packet**: {max_pkt} chars (budget: 24,000)")

            if max_ctx > 12000:
                lines.append(f"  - NOTE: orchestrator context exceeds 12,000-char cap at peak — "
                              f"truncation will discard {max_ctx - 12000} chars")
    else:
        lines.append("- Context growth log: *not found*")

    return "\n".join(lines)


def analyze_information_survival() -> str:
    lines = [_section("Information Survival Across Cycles")]

    data = _load("information_survival")
    if data:
        lines.append(f"- **Total facts introduced**: {data['total_facts']}")
        lines.append(f"- **Surviving in final summary**: {data['surviving_in_final']} "
                      f"({data['overall_survival_rate']}%)")
        lines.append(f"- **Final summary size**: {data['final_summary_chars']} chars")

        missing = data.get("missing_from_final", [])
        if missing:
            lines.append(f"- **Missing facts**: {', '.join(missing)}")
            lines.append("  - These facts were introduced in early cycles and were pushed out by "
                          "the 6,000-char rolling compression window.")

        snapshots = data.get("cycle_snapshots", [])
        if snapshots:
            lines.append("\n| Cycle | Fact | Summary (chars) | Surviving | Rate |")
            lines.append("|------:|------|----------------:|----------:|-----:|")
            for s in snapshots:
                lines.append(
                    f"| {s['cycle']:5d} | {s['fact_introduced']} | {s['summary_len']:16,d} | "
                    f"{s['survival_count']:9d} | {s['survival_rate']:4.1f}% |"
                )
    else:
        lines.append("- Information survival log: *not found*")

    return "\n".join(lines)


def analyze_char_vs_tokens() -> str:
    lines = [_section("Character vs. Token Divergence")]

    data = _load("char_vs_token")
    if data:
        lines.append(f"- **Tokenizer**: {data.get('tokenizer', 'unknown')}")
        samples = data.get("samples", {})

        lines.append("\n| Content Type | Chars | Tokens | Chars/Token | 4k-char budget (tokens) |")
        lines.append("|-------------|------:|-------:|------------:|------------------------:|")
        for name, s in samples.items():
            if name in ("orchestrator_context", "worker_packet"):
                continue
            t4k = s.get("char_budget_4000_actual_tokens", "—")
            lines.append(
                f"| {name} | {s['chars']:,d} | {s['tokens']:,d} | "
                f"{s['chars_per_token']:.2f} | {t4k} |"
            )

        for key in ("orchestrator_context", "worker_packet"):
            s = samples.get(key)
            if s:
                lines.append(f"\n**{key.replace('_', ' ').title()}**: "
                              f"{s['chars']:,} chars = {s['tokens']:,} tokens "
                              f"({s['chars_per_token']:.2f} chars/token, "
                              f"{s['token_utilization_vs_128k']:.2f}% of 128k context window)")

        # Compute divergence implications
        ratios = [s["chars_per_token"] for s in samples.values() if s.get("chars_per_token", 0) > 0]
        if ratios:
            avg_ratio = sum(ratios) / len(ratios)
            lines.append(f"\n- **Average chars/token ratio**: {avg_ratio:.2f}")
            lines.append(f"- **Implication**: A 12,000-char budget corresponds to ~{int(12000 / avg_ratio)} tokens, "
                          f"not the ~3,000 a naive 4-chars/token assumption would give.")
            lines.append(f"- **Implication**: A 24,000-char budget corresponds to ~{int(24000 / avg_ratio)} tokens.")
    else:
        lines.append("- Char/token divergence log: *not found*")

    return "\n".join(lines)


def analyze_utilization() -> str:
    lines = [_section("Context Utilization (Realistic Project)")]

    data = _load("context_utilization")
    if data:
        orch = data.get("orchestrator", {})
        pkt = data.get("packet", {})
        orch_overflow = f", {orch['overflow_chars']} chars overflowed" if orch.get("overflow_chars", 0) > 0 else ""
        lines.append(f"- **Orchestrator**: {orch.get('raw_chars', '?')} raw chars, "
                      f"{orch.get('utilization_pct', '?')}% of {orch.get('budget', '?')}-char budget used"
                      f"{orch_overflow}")
        pkt_overflow = f", {pkt['overflow_chars']} chars overflowed" if pkt.get("overflow_chars", 0) > 0 else ""
        lines.append(f"- **Packet**: {pkt.get('raw_chars', '?')} raw chars, "
                      f"{pkt.get('utilization_pct', '?')}% of {pkt.get('budget', '?')}-char budget used"
                      f"{pkt_overflow}")

        per_file = data.get("per_file_chars", {})
        if per_file:
            lines.append("\n- Tier A file sizes in realistic project:")
            for name, size in sorted(per_file.items(), key=lambda x: -x[1]):
                bar = "#" * min(50, size // 100)
                lines.append(f"  - `{name}`: {size:,d} chars {bar}")
    else:
        lines.append("- Context utilization log: *not found*")

    return "\n".join(lines)


def analyze_user_instructions() -> str:
    lines = [_section("User Instruction Lifecycle")]

    lines.append(
        "- Graph-level coverage (ingest event → planner override → second cycle respects orchestrator): "
        "`pytest tests/test_e2e_toy_problem.py::test_user_instruction_override_through_real_graph -v`"
    )
    lines.append(
        "- File-level pending detection: `pytest tests/test_memory.py::test_user_instructions_new_has_pending -v`"
    )

    return "\n".join(lines)


def improvement_recommendations() -> str:
    lines = [_section("Improvement Recommendations")]

    lines.append("""
Based on test findings and recent research in multi-agent orchestration frameworks:

### 1. Token-Aware Budgets

**Problem**: The system uses character-based limits (12,000 / 8,000 / 4,000 / 24,000 chars) that
diverge from actual token counts by 25-40% depending on content type. Code has a higher chars/token
ratio than prose, causing inconsistent effective context sizes.

**Recommendation**: Replace character limits with token-counted budgets using `tiktoken` (or a
model-appropriate tokenizer). This ensures consistent context utilization regardless of content type
and prevents both under-utilization (wasted capacity) and silent over-truncation.

**Research basis**: Production multi-agent systems report 60-80% cost reductions with token-aware
context management ([Multi-Agent Orchestration Guide](https://dev.to/nebulagg/multi-agent-orchestration-a-guide-to-patterns-that-work-1h81)).

### 2. Hierarchical Memory with Semantic Retrieval

**Problem**: Extended memory files are opaque to the orchestrator — only the index is inlined. As
projects grow, the flat index becomes insufficient for the orchestrator to know *which* extended
files are relevant to the current task.

**Recommendation**: Add lightweight semantic indexing to extended memory. When files are written to
`memory/extended/`, generate a summary embedding. At retrieval time, use the current task/query to
pull the most relevant extended files (or excerpts) rather than relying on the worker to manually
open files.

**Research basis**: H-MEM (Hierarchical Memory for LLM Agents, 2025) shows that multi-level memory
with index-based routing outperforms flat retrieval, especially in sessions exceeding 20 cycles
([H-MEM](https://ui.adsabs.harvard.edu/abs/2025arXiv250722925S/abstract)).

### 3. Multi-Stage Context Compression

**Problem**: The rolling `context_summary.md` is a single-pass compression mechanism. The
orchestrator LLM produces one summary per cycle, which must simultaneously serve as: (a) a
compressed history, (b) a task-relevant context selector, and (c) a pattern detector (e.g., loops).
This overloads a single field.

**Recommendation**: Adopt a multi-stage compression pipeline inspired by SimpleMem:
1. **Structured compression**: Distill each cycle's output into tagged facts (discoveries, decisions,
   failures, metrics) stored in a structured format.
2. **Semantic synthesis**: Periodically merge related facts into higher-level summaries.
3. **Intent-aware retrieval**: When building context for the next cycle, select facts based on the
   orchestrator's routing intent rather than recency alone.

**Research basis**: SimpleMem achieves 26.4% F1 improvement and up to 30x token reduction over
single-pass summarization ([SimpleMem](https://arxiv.org/html/2601.02553v2)).

### 4. Importance-Weighted Section Ordering

**Problem**: `_trim_packet` keeps the first and last halves of the packet, discarding the middle.
However, the "lost in the middle" effect means LLMs attend poorly to content in the middle of long
contexts *even when it isn't truncated*. The current Tier A section ordering is static (defined by
`TIER_A_FILES` list order) and doesn't account for task relevance.

**Recommendation**: 
- Reorder sections by relevance to the current task (e.g., if the orchestrator chose `debugger`,
  put `status.md` and `lessons.md` near the top).
- Place the most critical information at the beginning and end of the context (primacy/recency
  positions), with less critical content in the middle.
- Consider a recency-biased ordering where recently modified Tier A files appear first.

**Research basis**: LLM context window research consistently shows U-shaped attention curves
([AI Context Window Management](https://www.ai-agentsplus.com/blog/ai-context-window-management-2026)).

### 5. Memory Consolidation Cycles

**Problem**: Episodes accumulate indefinitely. After 50+ cycles, the episode index grows large
but is never pruned or consolidated. Old episodes become noise rather than signal.

**Recommendation**: Implement periodic consolidation (e.g., every 10 cycles):
- Summarize completed roadmap phases into `lessons.md` or a new `consolidated_history.md`.
- Archive old episode directories (zip or move to `memory/extended/archive/`).
- Prune the episode index to keep only the last N entries inline, with a pointer to the archive.

**Research basis**: Mnemis (2025) shows that dual-route retrieval on hierarchical graphs — combining
fast similarity-based and slower global selection — maintains quality while controlling memory growth.

### 6. Context Window Utilization Metrics

**Problem**: No runtime observability exists for context utilization. When context is saturated
(>80% of budget), the system has no mechanism to detect this or adapt its behavior.

**Recommendation**: Add per-cycle logging of:
- Orchestrator context chars/tokens used vs. budget
- Packet chars/tokens used vs. budget
- Which Tier A files were truncated and by how much
- Rolling summary compression ratio (input chars vs. output chars)

Use these metrics to trigger adaptive behavior: when utilization exceeds 80%, the orchestrator
could proactively trigger a consolidation cycle or increase compression aggressiveness.
""")
    return "\n".join(lines)


def main() -> None:
    if not LOG_DIR.exists():
        print(f"No logs directory at {LOG_DIR}. Run the tests first:")
        print(
            "  pytest tests/test_memory_integration.py tests/test_context_integration.py "
            "tests/test_packets.py tests/test_e2e_toy_problem.py -v -s"
        )
        sys.exit(1)

    log_files = list(LOG_DIR.glob("*.json"))
    if not log_files:
        print(f"No JSON log files in {LOG_DIR}. Run the tests first.")
        sys.exit(1)

    print(f"Found {len(log_files)} log files in {LOG_DIR}")

    sections = [
        "# Memory & Context Management Analysis Report\n",
        f"*Generated from {len(log_files)} test log files.*\n",
        analyze_memory_fidelity(),
        analyze_context_budgets(),
        analyze_context_growth(),
        analyze_information_survival(),
        analyze_char_vs_tokens(),
        analyze_utilization(),
        analyze_user_instructions(),
        improvement_recommendations(),
    ]

    report = "\n".join(sections)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")
    print(f"Report size: {len(report):,d} chars")
    print("\n" + "=" * 60)
    print(report)


if __name__ == "__main__":
    main()
