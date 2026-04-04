# Memory & Context Management Analysis Report

*Generated from 21 test log files.*


## Memory Write/Read Fidelity

- **Tier A round-trip**: 11 files tested, all content survived write/read cycle.
- **Context summary overwrite**: 10 cycles tested, each overwrite fully replaced prior content.
- **Episode accumulation**: 20 entries, index grew to 4516 chars.
- **Extended memory isolation**: bodies properly isolated (secret 5024 chars, ctx 1230 chars).
- **Branch memory**: 3 branches tested with special characters — all round-tripped correctly.
- **Lesson ordering**: 5 lessons appended in order, file is 230 chars.
- **Reset preservation**: research_idea=preserved, other files=cleared.

## Context Budget Analysis

- **Orchestrator context size**: 60368 chars (max expected: 62000).
- Per-Tier-A-section sizes in orchestrator context:
  - `project_brief.md`: ~4003 chars
  - `extended_memory_index.md`: ~4003 chars
  - `research_idea.md`: ~4003 chars
  - `preferences.md`: ~4003 chars
  - `roadmap.md`: ~4003 chars
  - `immediate_plan.md`: ~4003 chars
  - `status.md`: ~4003 chars
  - `skills_index.md`: ~4003 chars
  - `lessons.md`: ~4003 chars
  - `user_instructions.md`: ~4002 chars
- **Hard cap truncation**: raw context was 60368 chars, truncated to 12000. **80.1%** of content lost to the 12,000-char cap.
- **Packet budget**: 24040 chars vs 24000 budget. Header present: True, objective present: True.
- **Packet trimming**: 20036 chars -> 10040 chars. Head preserved: True, tail preserved: True.
- **Summary compression**: 10019-char summary truncated, 7981 chars survived in orchestrator context (2019 chars lost).

## Context Growth Over Cycles

| Cycle | Orch Ctx (chars) | Packet (chars) | Roadmap (chars) | Summary (chars) |
|------:|----------------:|--------------:|---------------:|---------------:|
|     0 |            4,438 |          3,894 |             278 |           1,150 |
|     1 |            4,460 |          3,916 |             300 |           1,150 |
|     2 |            4,482 |          3,938 |             322 |           1,150 |
|     3 |            4,504 |          3,960 |             344 |           1,150 |
|     4 |            4,526 |          3,982 |             366 |           1,150 |
|     5 |            4,548 |          4,004 |             388 |           1,150 |
|     6 |            4,570 |          4,026 |             410 |           1,150 |
|     7 |            4,592 |          4,048 |             432 |           1,150 |
|     8 |            4,614 |          4,070 |             454 |           1,150 |
|     9 |            4,636 |          4,092 |             476 |           1,150 |
|    10 |            4,810 |          4,166 |             500 |           1,200 |
|    11 |            4,834 |          4,190 |             524 |           1,200 |
|    12 |            4,858 |          4,214 |             548 |           1,200 |
|    13 |            4,882 |          4,238 |             572 |           1,200 |
|    14 |            4,906 |          4,262 |             596 |           1,200 |
|    15 |            4,930 |          4,286 |             620 |           1,200 |
|    16 |            4,954 |          4,310 |             644 |           1,200 |
|    17 |            4,978 |          4,334 |             668 |           1,200 |
|    18 |            5,002 |          4,358 |             692 |           1,200 |
|    19 |            5,026 |          4,382 |             716 |           1,200 |

- **Orchestrator context growth**: 4438 -> 5026 (+588 chars over 20 cycles)
- **Packet growth**: 3894 -> 4382 (+488 chars over 20 cycles)
- **Peak orchestrator context**: 5026 chars (budget: 12,000)
- **Peak packet**: 4382 chars (budget: 24,000)

## Information Survival Across Cycles

- **Total facts introduced**: 10
- **Surviving in final summary**: 10 (100.0%)
- **Final summary size**: 950 chars

| Cycle | Fact | Summary (chars) | Surviving | Rate |
|------:|------|----------------:|----------:|-----:|
|     0 | FACT_000 |               95 |         1 | 100.0% |
|     1 | FACT_001 |              190 |         2 | 100.0% |
|     2 | FACT_002 |              285 |         3 | 100.0% |
|     3 | FACT_003 |              380 |         4 | 100.0% |
|     4 | FACT_004 |              475 |         5 | 100.0% |
|     5 | FACT_005 |              570 |         6 | 100.0% |
|     6 | FACT_006 |              665 |         7 | 100.0% |
|     7 | FACT_007 |              760 |         8 | 100.0% |
|     8 | FACT_008 |              855 |         9 | 100.0% |
|     9 | FACT_009 |              950 |        10 | 100.0% |

## Character vs. Token Divergence

- **Tokenizer**: tiktoken/gpt-4o

| Content Type | Chars | Tokens | Chars/Token | 4k-char budget (tokens) |
|-------------|------:|-------:|------------:|------------------------:|
| english_prose | 11,000 | 1,701 | 6.47 | 618 |
| code_python | 9,900 | 2,040 | 4.85 | 826 |
| markdown_structured | 6,120 | 1,960 | 3.12 | 1281 |
| mixed_technical | 8,340 | 3,481 | 2.40 | 1671 |

**Orchestrator Context**: 14,095 chars = 4,003 tokens (3.52 chars/token, 3.13% of 128k context window)

**Worker Packet**: 12,453 chars = 3,675 tokens (3.39 chars/token, 2.87% of 128k context window)

- **Average chars/token ratio**: 3.96
- **Implication**: A 12,000-char budget corresponds to ~3031 tokens, not the ~3,000 a naive 4-chars/token assumption would give.
- **Implication**: A 24,000-char budget corresponds to ~6063 tokens.

## Context Utilization (Realistic Project)

- **Orchestrator**: 15141 raw chars, 100.0% of 12000-char budget used, 3141 chars overflowed
- **Packet**: 14736 raw chars, 61.4% of 24000-char budget used

- Tier A file sizes in realistic project:
  - `research_idea.md`: 4,921 chars #################################################
  - `roadmap.md`: 3,661 chars ####################################
  - `context_summary.md`: 3,059 chars ##############################
  - `extended_memory_index.md`: 1,040 chars ##########
  - `immediate_plan.md`: 828 chars ########
  - `skills_index.md`: 246 chars ##
  - `user_instructions.md`: 162 chars #
  - `status.md`: 66 chars 
  - `project_brief.md`: 17 chars 
  - `preferences.md`: 15 chars 
  - `lessons.md`: 11 chars 

## User Instruction Lifecycle

- **Instructions written**: 2
- **Pending after write**: True
- **Pending after clear**: False
- **Planner override**: orchestrator chose `researcher`, system overrode to `planner`
- **Full lifecycle test**: instruction "Add ablation study to experiments"
  - Pending after enqueue: True
  - Overridden to planner: True
  - Pending after clear: False
  - Integrated into plan: True
  - Next cycle not overridden: True

## Improvement Recommendations


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
