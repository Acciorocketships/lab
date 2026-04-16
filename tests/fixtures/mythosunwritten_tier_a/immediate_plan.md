# Immediate plan

## Overview

**Phase 113** — **next gating** (**2026-04-15**): vertical stub **`llm_agent`** **`deny_trade`** after **`trade_revised`** + **Phase 74** gold — ADR **`.lab/memory/extended/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**Slices A–C** landed **2026-04-15**). **Predecessor:** **Phase 112** (**closed**).

**Next:** **reporter** — **Phase 113** **Slice D** — closure **`reports/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** freeze.

**Parallel (non-gating):** Phase **50**/**51** Slice **E**; **Arcade** backlog (`roadmap.md`). **User graphics (after Phase 113 harness slice or dedicated branch):** POC → tile atlas or sampled colours from **`screenshots/sproutlands.png`** so terrain is not random RGB grid; then HUD/items/actors — **`research_idea.md`** / **`preferences.md`** asset layout; evidence vs **`screenshots/pyglet1.png`**.

**Branch (suggested):** **`feat/phase113-vertical-stub-npc-deny-trade-after-revise-llm-overlay-v0`** off integration **`feat/phase4-items-attacks-cooldowns`**.

## Checklist

- [x] **planner** — **Phase 113** **Slice A** — ADR **`phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** + Tier A + **Phase 112** **§ Successor** filename respected (**2026-04-15**)
- [x] **implementer** — **Phase 113** **Slice B** — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_deny_trade_after_revise_llm_overlay_phase113.py`** + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
- [x] **reviewer** — **Phase 113** **Slice C** — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **896** passed, **2** skipped, **~3.15** s, **`e89112f`**, **0** deselected)
- [ ] **reporter** — **Phase 113** **Slice D** — **`reports/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** freeze

## Done when

**Phase 113:** ADR **Slices B–D** **`[x]`**; closure report; Tier A Phase **113** parent **`[x]`**; **§ Successor** frozen by **reporter** on close.
