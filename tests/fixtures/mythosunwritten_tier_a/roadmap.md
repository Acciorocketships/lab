# Roadmap

## Overview

**Mythos Unwritten:** multi-agent world sim — shared action API for player and NPCs, LLMs behind a strict tool contract, procedural overworld, **territory** from sentiment, RT exploration → localized turn-based **combat**.

**Stack:** Python under `src/`; Ursina optional (`[visual]`); **Pyglet** optional (`[pyglet_visual]` in `pyproject.toml`). OpenRouter or Ollama. **Policy:** `OPENROUTER_API_KEY`; default model **`google/gemma-4-26b-a4b-it`** (override in script `CONFIG` only).

**Architecture:** core sim + orchestration engine-agnostic; `game/` and `client/` swappable per `preferences.md`.

**Extended memory:** `.lab/memory/extended/` ADRs + `reports/phase*.md` hold specs, sign-offs, and evidence. Tier A checklist is navigational — slice tables live in ADRs.

## Checklist

- [x] **Phase 0–12** — Repo layout, headless spine + events, LLM stubs/providers, character sheet + memory + dispatcher, items/attacks/cooldowns, combat bubble RT→TB, overworld v0, territory v1, orchestrator tools + audit + prompts, NPC observation/cadence/stub + headless wiring, ability-check pipeline + smoke, Ursina client + snapshot + input, local multiplayer + import fences. Reports: `phase5` … `phase12`, `phase11_ursina_client`.
- [x] **Phase 13 — Polish / reach (Tracks A–D)** — Required slices; encounter `rules_eval_config` parity. ADR `phase13_polish_reach.md`. Closures: `reports/phase13_closure.md`, `reports/phase13_track_d_persistent_rules.md`, etc.
  - [x] **Track A** — `freeform_ability` + ability check (A1–A3). **A4** → Phase 18.
  - [x] **A5** — Optional visual smoke → **Phase 49**.
  - [x] **Track B** — Distance gate, stub lookahead, throttle (B1–B4). **B5** → 32. **B6** design 33, code 36.
  - [x] **Track C** — `chunk_gen_hints`, merge order, orchestrator terrain hint (C1–C3). **C4** → 43. **C5** → 42.
  - [x] **Track D** — `active_rules`, `evaluate_rules_tick`, install/remove (D1–D4). **D5** → 41. **D6** design 44, code 45–51 + stub 46; **Phase 51** closed **2026-04-14** — `reports/phase51_rule_program_v0_opcode_emit_trigger_mod_labeled.md`.
- [x] **Phase 14** — Vertical stub + harness goldens + sentiment delta. `reports/phase14_vertical_play_stub_harness.md`. Slice D → Phase 34 helper.
- [x] **Phase 15** — Ursina `rules_eval_config` parity vs headless. `reports/phase15_client_rules_parity.md`.
- [x] **Phase 16** — Structured LLM NPC on harness; `scripts/npc_planner_llm_smoke.py`. `reports/phase16_vertical_stub_llm_npc.md`.
- [x] **Phase 17** — Joint orchestrator + NPC tick. `reports/phase17_vertical_orchestrator_npc_joint.md`.
- [x] **Phase 18** — Client `freeform_ability` for `local_players`. `reports/phase18_client_freeform_local_players.md`. Slice F HUD → Phase 29.
- [x] **Phase 19** — NPC `ability_check_*` kwargs. `reports/phase19_npc_freeform_ability_check_parity.md`.
- [x] **Phase 20** — Harness stub `freeform_ability` + ability-check events. `reports/phase20_vertical_stub_freeform_ability_harness.md`.
- [x] **Phase 21** — Harness `install_active_rule` + `rule_*` events. `reports/phase21_vertical_stub_orchestrator_active_rules.md`.
- [x] **Phase 22** — Harness terrain hint + snapshot delta. `reports/phase22_vertical_stub_orchestrator_terrain_hints.md`.
- [x] **Phase 23** — `run_headless` `orchestrator_tool_batches` + harness `remove_active_rule`. `reports/phase23_vertical_stub_orchestrator_remove_active_rule.md`.
- [x] **Phase 24** — Harness `spawn_npc`. `reports/phase24_vertical_stub_orchestrator_spawn_npc.md`.
- [x] **Phase 25** — Harness `narrate_world_patch` + non-empty `state_patch`. `reports/phase25_vertical_stub_orchestrator_narrate_state_patch.md`.
- [x] **Phase 26** — `orchestrator_audit` ↔ `orchestrator_tool` parity. `reports/phase26_vertical_stub_orchestrator_audit_parity.md`.
- [x] **Phase 27** — Minimal sliding-window rate limit proof. `reports/phase27_orchestrator_sliding_window_rate_limit.md`.
- [x] **Phase 28** — Vertical stub sliding-window overlay. `reports/phase28_vertical_stub_sliding_window_rate_limit.md`.
- [x] **Phase 29** — Freeform outcome HUD. `reports/phase29_client_freeform_hud_outcome.md`.
- [x] **Phase 30** — `orchestrator_smoke.py` batch/sliding parity. `reports/phase30_orchestrator_smoke_parity.md`.
- [x] **Phase 31** — Orchestrator ops guide in `lessons.md` + timing tables. `reports/phase31_orchestrator_docs_timing_hygiene.md`.
- [x] **Phase 32** — `npc_planner_metrics` v0. `reports/phase32_npc_planner_observability_v0.md`.
- [x] **Phase 33** — Async LLM overlap **design** spike. `reports/phase33_npc_async_llm_overlap_spike.md`, `reports/phase13_track_b6_async_llm_design.md`.
- [x] **Phase 34** — `run_headless_events` helper. `reports/phase34_headless_events_capture_helper.md`.
- [x] **Phase 35** — Adoption sweep to `run_headless_events`. `reports/phase35_headless_events_helper_adoption.md`.
- [x] **Phase 36** — NPC async planner **code** (opt-in). `reports/phase36_npc_async_llm_planner_implementation.md`.
- [x] **Phase 37** — Vertical stub async harness. `reports/phase37_vertical_stub_npc_async_planner.md`.
- [x] **Phase 38** — Vertical stub `combat_cancelled`. `reports/phase38_vertical_stub_npc_async_combat_cancel.md`.
- [x] **Phase 39** — Deferred `stale_event_seq`. `reports/phase39_npc_async_deferred_event_seq_stale.md`.
- [x] **Phase 40** — Config-gated LLM DC judge. `reports/phase40_ability_check_llm_dc_pipeline.md`.
- [x] **Phase 41** — Track D5 rule-event volume cap. `reports/phase41_track_d5_exploit_mitigations_v0.md`.
- [x] **Phase 42** — Track C5 chunk cache epoch + snapshot keys. `reports/phase42_track_c5_chunk_regen_cache_invalidation.md`.
- [x] **Phase 43** — Track C4 ASCII harness. `reports/phase43_track_c4_overworld_ascii_harness_v0.md`.
- [x] **Phase 44** — Track D6 DSL design spike (doc-only). `reports/phase44_track_d6_rule_dsl_design_spike.md`.
- [x] **Phase 45** — `rule_program_v0` implementation. `reports/phase45_track_d6_rule_dsl_implementation_v0.md`.
- [x] **Phase 46** — Vertical stub `rule_program_v0`. `reports/phase46_vertical_stub_rule_program_v0.md`.
- [x] **Phase 47** — Opcode `emit_trigger_mod`. `reports/phase47_rule_program_v0_opcode_mod_emit.md`.
- [x] **Phase 48** — Vertical stub Phase 43 overlay + epoch. `reports/phase48_vertical_stub_phase43_overlay.md`.
- [x] **Phase 49** — Track A5 visual recovery. ADR `phase49_track_a5_visual_client_recovery.md`; `reports/phase49_track_a5_visual_client_recovery.md`. **2026-04-14**.
- [x] **Phase 50** — Opcode `emit_trigger_labeled`. ADR `phase50_rule_program_v0_opcode_emit_trigger_labeled.md`; `reports/phase50_rule_program_v0_opcode_emit_trigger_labeled.md`.
  - [ ] **Slice E** (optional) — harness overlay in `tests/test_vertical_play_stub_rule_program_v0.py`.
- [x] **Phase 51** — Opcode `emit_trigger_mod_labeled`. ADR `phase51_rule_program_v0_opcode_emit_trigger_mod_labeled.md`; `reports/phase51_rule_program_v0_opcode_emit_trigger_mod_labeled.md`.
  - [ ] **Slice E** (optional) — same harness overlay (bars Phase 47 / 50 Slice E).
- [x] **Phase 52** — Ursina macOS GLSL 130/140 → 150 (`ursina_glsl_compatibility`). ADR `phase52_visual_client_scene_rendering.md`; triage `reports/phase52_slice_b_*`, `phase52_slice_d_*`.
- [ ] **Phase 53** — Ursina viewport truth — **paused** as primary visual path. ADR `phase53_visual_client_viewport_truth.md`; `reports/phase53_slice_d_window_truth_experiment.md`. Active path: Pyglet (54+).
  - [x] Slices A–D, E (implementer), G (user → Pyglet) — **2026-04-14**
  - [ ] Slice E (reviewer) / Slice F (reporter) — optional
- [x] **Phase 54** — Pyglet v0 POC + `[pyglet_visual]` + import fences. ADR `phase54_pyglet_visual_client_v0.md`; `reports/phase54_pyglet_visual_client_v0.md`.
- [x] **Phase 55** — Snapshot-driven 2D terrain (`terrain_tile_grid`, `run_pyglet_visual_client.py`). ADR `phase55_pyglet_client_snapshot_2d.md`; `reports/phase55_pyglet_client_snapshot_2d.md`.
- [x] **Phase 56** — Keys → `dispatch_action` + compact HUD. ADR `phase56_pyglet_input_dispatch_hud.md`; `reports/phase56_pyglet_input_dispatch_hud.md`.
- [x] **Phase 57** — Entity markers + combat HUD + Slice **G** perf baseline (**2026-04-14**). ADR `phase57_pyglet_entity_markers_combat_ui_perf.md`; `reports/phase57_pyglet_entity_markers_combat_ui_perf.md`, `reports/phase57_slice_g_*`.
- [x] **Phase 58** — Target cycle, cooldown rows, freeform typing. ADR `phase58_pyglet_target_cooldown_freeform.md`; `reports/phase58_pyglet_target_cooldown_freeform.md`.
- [x] **Phase 59** — Read-only inventory HUD. ADR `phase59_pyglet_inventory_hud.md`; `reports/phase59_pyglet_inventory_hud.md`.
- [x] **Phase 60** — Mouse ↔ tile hit + optional click-move. ADR `phase60_pyglet_mouse_tile_picking.md`; `reports/phase60_pyglet_mouse_tile_picking.md`.
- [x] **Phase 61** — Mouse → melee target integration. ADR `phase61_pyglet_mouse_melee_target_integration.md`; `reports/phase61_pyglet_mouse_melee_target_integration.md`.
- [x] **Phase 62** — `equip` / `use_item` + `equipped_item_id` + Pyglet slot keys. ADR `phase62_pyglet_inventory_equip_use_item.md`; `reports/phase62_pyglet_inventory_equip_use_item.md`.
- [x] **Phase 63** — Pyglet NPC equip/use parity + quick-attack default `item_id`; optional modifier click-to-slot. ADR `phase63_pyglet_inventory_followthrough_npc_quick_attack.md`; `reports/phase63_pyglet_inventory_followthrough_npc_quick_attack.md`.
- [x] **Phase 64** — Vertical stub NPC inventory harness (`item_equipped` / `item_used`). ADR `phase64_vertical_stub_npc_inventory_actions_harness.md`; `reports/phase64_vertical_stub_npc_inventory_actions_harness.md`.
- [x] **Phase 65** — NPC structured `attack`: default `item_id` from `equipped_item_id`. ADR `phase65_npc_structured_attack_equipped_item_default.md`; `reports/phase65_npc_structured_attack_equipped_item_default.md`.
- [x] **Phase 66** — Vertical stub `drop_item` + `item_dropped`. ADR `phase66_vertical_stub_npc_drop_item_headless_harness.md`; `reports/phase66_vertical_stub_npc_drop_item_headless_harness.md`.
- [x] **Phase 67** — `pick_up` + `item_picked_up` + harness. ADR `phase67_vertical_stub_npc_pick_up_headless_harness.md`; `reports/phase67_vertical_stub_npc_pick_up_headless_harness.md`.
- [x] **Phase 68** — `give_item` + `item_given` + harness. ADR `phase68_vertical_stub_npc_give_item_headless_harness.md`; `reports/phase68_vertical_stub_npc_give_item_headless_harness.md`.
- [x] **Phase 69** — `propose_trade` / `accept_trade` + harness. ADR `phase69_vertical_stub_npc_propose_accept_trade_headless_harness.md`; `reports/phase69_vertical_stub_npc_propose_accept_trade_headless_harness.md`.
- [x] **Phase 70** — `deny_trade` + `trade_denied` + stale-accept cleanup + harness. ADR `phase70_vertical_stub_npc_deny_trade_headless_harness.md`; `reports/phase70_vertical_stub_npc_deny_trade_headless_harness.md`.
- [x] **Phase 71** — Pyglet trade UX (`propose_trade` / accept / deny + HUD). ADR `phase71_pyglet_trade_ux_v0.md`; `reports/phase71_pyglet_trade_ux_v0.md`.
- [x] **Phase 72** — `pending_trade` tick expiry + events + harness/HUD hooks. ADR `phase72_pending_trade_timeout_v0.md`; `reports/phase72_pending_trade_timeout_v0.md`.
- [x] **Phase 73** — Multi-slot `pending_trades` FIFO + snapshot/HUD. ADR `phase73_pending_trades_multi_slot_queue_v0.md`; `reports/phase73_pending_trades_multi_slot_queue_v0.md`.
- [x] **Phase 74** — Trade currency (`gold` on sheet + optional trade gold). ADR `phase74_trade_currency_v0.md`; `reports/phase74_trade_currency_v0.md`.
- [x] **Phase 75** — Counter-offer **design spike** (doc-only, Design 1 + `trade_revised` frozen). ADR `phase75_trade_counter_offer_design_spike_v0.md`; `reports/phase75_trade_counter_offer_design_spike_v0.md`.
- [x] **Phase 76** — `revise_trade` / `trade_revised` implementation. ADR `phase76_trade_revised_implementation_v0.md`; `reports/phase76_trade_revised_implementation_v0.md`.
- [x] **Phase 77** — Pyglet full-client viewport / terrain `Batch` + diagnostics + Slice D evidence. ADR `phase77_pyglet_full_client_viewport_v0.md`; `reports/phase77_pyglet_full_client_viewport_v0.md`.
- [x] **Phase 78** — NPC observation: trades band + `legality_hint` trade/`revise_trade`. ADR `phase78_npc_observation_trade_revise_parity_v0.md`; `reports/phase78_npc_observation_trade_revise_parity_v0.md`.
- [x] **Phase 79** — Pyglet ground loot HUD + markers (`ground_tiles`, formatter, CONFIG). **2026-04-15**. ADR `phase79_pyglet_ground_loot_hud_markers_v0.md`; `reports/phase79_pyglet_ground_loot_hud_markers_v0.md`.
- [x] **Phase 80** — Pyglet click `pick_up`. **2026-04-15**. ADR `phase80_pyglet_click_pick_up_v0.md`; `reports/phase80_pyglet_click_pick_up_v0.md`.
- [x] **Phase 81** — Vertical stub NPC `revise_trade` LLM overlay + subprocess fence. **2026-04-15**. ADR `phase81_vertical_stub_npc_revise_trade_llm_overlay_v0.md`; `reports/phase81_vertical_stub_npc_revise_trade_llm_overlay_v0.md`.
- [x] **Phase 82** — Pyglet `drop_item` v0. **2026-04-15**. ADR `phase82_pyglet_drop_item_v0.md`; `reports/phase82_pyglet_drop_item_v0.md`.
- [x] **Phase 83** — Pyglet `give_item` v0. **2026-04-15**. ADR `phase83_pyglet_give_item_v0.md`; `reports/phase83_pyglet_give_item_v0.md`.
- [x] **Phase 84** — Vertical stub NPC `give_item` LLM overlay. **2026-04-15**. ADR `phase84_vertical_stub_npc_give_item_llm_overlay_v0.md`; `reports/phase84_vertical_stub_npc_give_item_llm_overlay_v0.md`.
- [x] **Phase 85** — Pyglet `examine` v0. **2026-04-15**. ADR `phase85_pyglet_examine_v0.md`; `reports/phase85_pyglet_examine_v0.md`.
- [x] **Phase 86** — Vertical stub NPC `examine` LLM overlay. **2026-04-15**. ADR `phase86_vertical_stub_npc_examine_llm_overlay_v0.md`; `reports/phase86_vertical_stub_npc_examine_llm_overlay_v0.md`.
- [x] **Phase 87** — NPC observation `examine` / `entity_examined` parity. **2026-04-15**. ADR `phase87_npc_observation_examine_entity_examined_parity_v0.md`; `reports/phase87_npc_observation_examine_entity_examined_parity_v0.md`.
- [x] **Phase 88** — NPC observation `wait` / `say` events + legality parity. **2026-04-15**. ADR `phase88_npc_observation_wait_say_events_legality_parity_v0.md`; `reports/phase88_npc_observation_wait_say_events_legality_parity_v0.md`.
- [x] **Phase 89** — `interact` dispatcher + `entity_interacted` + observation parity (no Pyglet in v0). **2026-04-15**. ADR `phase89_interact_action_dispatcher_events_observation_parity_v0.md`; `reports/phase89_interact_action_dispatcher_events_observation_parity_v0.md`.
- [x] **Phase 90** — Pyglet `interact` v0. **2026-04-15**. ADR `phase90_pyglet_interact_v0.md`; `reports/phase90_pyglet_interact_v0.md`.
- [x] **Phase 91** — Vertical stub NPC `interact` LLM overlay. **2026-04-15**. ADR `phase91_vertical_stub_npc_interact_llm_overlay_v0.md`; `reports/phase91_vertical_stub_npc_interact_llm_overlay_v0.md`.
- [x] **Phase 92** — NPC observation `interact` / `entity_interacted` parity. **2026-04-15**. ADR `phase92_npc_observation_interact_entity_interacted_parity_v0.md`; `reports/phase92_npc_observation_interact_entity_interacted_parity_v0.md`.
- [x] **Phase 93** — Trade Phase 75 **Design 2** doc-only spike (defer shipping). **2026-04-15**. ADR `phase93_trade_counter_offer_design2_design_spike_v0.md`; `reports/phase93_trade_counter_offer_design2_design_spike_v0.md`.
- [x] **Phase 94** — Pyglet `wait` / `say` v0. **2026-04-15**. ADR `phase94_pyglet_wait_say_v0.md`; `reports/phase94_pyglet_wait_say_v0.md`.
- [x] **Phase 95** — Vertical stub NPC `wait` / `say` LLM overlay. **2026-04-15**. ADR `phase95_vertical_stub_npc_wait_say_llm_overlay_v0.md`; `reports/phase95_vertical_stub_npc_wait_say_llm_overlay_v0.md`.
- [x] **Phase 96** — Vertical stub NPC `freeform_ability` LLM overlay. **2026-04-15**. ADR `phase96_vertical_stub_npc_freeform_ability_llm_overlay_v0.md`; `reports/phase96_vertical_stub_npc_freeform_ability_llm_overlay_v0.md`.
- [x] **Phase 97** — NPC observation `freeform_ability` + ability-check parity. **2026-04-15**. ADR `phase97_npc_observation_freeform_ability_ability_check_parity_v0.md`; `reports/phase97_npc_observation_freeform_ability_ability_check_parity_v0.md`.
- [x] **Phase 98** — NPC observation `move:` / `attack:` / `end_turn:` legality + bounded combat/movement `World.events` tails; `npc_system.md` + prompt skeleton anchors. **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase98_npc_observation_move_attack_end_turn_parity_v0.md`; `reports/phase98_npc_observation_move_attack_end_turn_parity_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + Phase 97 § Successor → Phase 98
  - [x] **Slice B** — implementer — `legality_hint` `move:` / `attack:` / `end_turn:` vs `sim/dispatcher.py` / `resolve_attack` (**2026-04-15**)
  - [x] **Slice C** — implementer — bounded event tails + `ObservationLimits` + `tests/test_npc_observation*.py` (**2026-04-15**)
  - [x] **Slice D** — implementer — `npc_system.md` + `tests/test_npc_prompt_skeleton.py` Phase 98 anchors (**2026-04-15**)
  - [x] **Slice E** — reviewer — ADR § Reviewer sign-off + standard deselect `pytest` line (**2026-04-15**)
  - [x] **Slice F** — reporter — closure report + Tier A parent `[x]` + ADR § Reporter sign-off (**2026-04-15**)
- [x] **Phase 99** — NPC observation inventory actions (`pick_up` / `drop_item` / `give_item` + conditional `equip` / `use_item`) `legality_hint` + bounded `item_*` event tails v0. **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase99_npc_observation_inventory_actions_legality_parity_v0.md`; closure `reports/phase99_npc_observation_inventory_actions_legality_parity_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + Phase 98 § Successor freeze → Phase 99 (**2026-04-15**)
  - [x] **Slice B** — implementer — `legality_hint` inventory paragraphs + dispatcher roster reconciliation (**2026-04-15**)
  - [x] **Slice C** — implementer — bounded `item_*` tails + `ObservationLimits` (**2026-04-15**)
  - [x] **Slice D** — implementer — `npc_system.md` + `tests/test_npc_prompt_skeleton.py` Phase 99 anchors (**2026-04-15**)
  - [x] **Slice E** — reviewer — ADR § Reviewer sign-off + standard deselect `pytest` (**2026-04-15**)
  - [x] **Slice F** — reporter — closure report + Tier A parent `[x]` + ADR § Reporter sign-off (**2026-04-15**)
- [x] **Phase 100** — **`equip` / `use_item`** in **`dispatch_action`** + structured NPC JSON + observation **`legality_hint`** + **`=== inventory_item_events ===`** (`item_equipped` / `item_used`). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase100_equip_use_item_dispatch_observation_parity_v0.md`; closure `reports/phase100_equip_use_item_dispatch_observation_parity_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + Phase 99 § Successor freeze → Phase 100 (**2026-04-15**)
  - [x] **Slice B** — implementer — `dispatch_action` + `World.events` + `tests/test_dispatcher.py` (**2026-04-15**)
  - [x] **Slice C** — implementer — `structured_action_json` + `npc_step` + agent tests (**2026-04-15**)
  - [x] **Slice D** — implementer — `observation.py` + `tests/test_npc_observation*.py` (**2026-04-15**)
  - [x] **Slice E** — implementer — `npc_system.md` + `tests/test_npc_prompt_skeleton.py` (**2026-04-15**)
  - [x] **Slice F** — reviewer — ADR § Reviewer sign-off + standard deselect `pytest` (**2026-04-15**; **852** passed, **2** skipped; **`e89112f`**)
  - [x] **Slice G** — reporter — closure report + Tier A parent `[x]` + ADR § Reporter sign-off (**2026-04-15**)
- [x] **Phase 101** — Vertical stub NPC **`equip` / `use_item`** **`llm_agent`** overlay v0 (`item_equipped` / `item_used` goldens + subprocess fence; mirrors **Phase 84** / **Phase 96**). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase101_vertical_stub_npc_equip_use_item_llm_overlay_v0.md`; closure `reports/phase101_vertical_stub_npc_equip_use_item_llm_overlay_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 100** ADR **§ Successor** selection freeze → **Phase 101** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_equip_use_item_llm_overlay_phase101.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **855** passed, **2** skipped; **`e89112f`**)
  - [x] **Slice D** — reporter — **`reports/phase101_vertical_stub_npc_equip_use_item_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** (**Phase 102** queue) (**2026-04-15**)
- [x] **Phase 102** — Vertical stub NPC **`drop_item`** **`llm_agent`** overlay v0 (`item_dropped` goldens + subprocess fence; mirrors **Phase 66** / **Phase 84** / **Phase 101**). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase102_vertical_stub_npc_drop_item_llm_overlay_v0.md`; closure `reports/phase102_vertical_stub_npc_drop_item_llm_overlay_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 101** ADR **§ Successor** selection freeze → **Phase 102** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_drop_item_llm_overlay_phase102.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **857** passed, **2** skipped; **`e89112f`**)
  - [x] **Slice D** — reporter — **`reports/phase102_vertical_stub_npc_drop_item_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** (**Phase 103** queue) (**2026-04-15**)
- [x] **Phase 103** — Vertical stub NPC **`pick_up`** **`llm_agent`** overlay v0 (`item_picked_up` goldens + subprocess fence; mirrors **Phase 67** + **Phase 101**/**102**). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase103_vertical_stub_npc_pick_up_llm_overlay_v0.md`; closure `reports/phase103_vertical_stub_npc_pick_up_llm_overlay_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 102** ADR **§ Successor** path confirmed → **Phase 103** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + additive **`run_headless`** ground seed (if required) + **`tests/test_vertical_play_stub_npc_pick_up_llm_overlay_phase103.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **859** passed, **2** skipped, **~2.17** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase103_vertical_stub_npc_pick_up_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** (**Phase 104** queue) (**2026-04-15**)
- [x] **Phase 104** — Vertical stub NPC **`propose_trade`** / **`accept_trade`** **`llm_agent`** overlay v0 (`trade_proposed` / `trade_accepted` goldens + subprocess fence; mirrors **Phase 69** + **Phase 81**/**84**). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`; closure `reports/phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 103** ADR **§ Successor** path → **Phase 104** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_propose_accept_trade_llm_overlay_phase104.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **862** passed, **2** skipped, **~2.21** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** (**Phase 105** ADR **`phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`** frozen) (**2026-04-15**)
- [x] **Phase 105** — Vertical stub NPC **`deny_trade`** **`llm_agent`** overlay v0 (`trade_denied` voluntary deny payload + **`trade_proposed`** goldens + subprocess fence; mirrors **`dispatcher.py`** **`deny_trade`** + **Phase 104** fence class). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`; closure `reports/phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 104** **§ Successor** path acknowledged → **Phase 105** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_deny_trade_llm_overlay_phase105.py`** + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **865** passed, **2** skipped, **~2.28** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 106** ADR **`phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`** (**2026-04-15**)
- [x] **Phase 106** — Vertical stub NPC **trade currency (gold)** **`llm_agent`** overlay v0 (**`trade_proposed`** / **`trade_accepted`** with **non-zero** **`give_gold`** / **`want_gold`** per **Phase 74**; mirrors **Phase 104** fence + **`run_loop`** gold seeds). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`; closure **`reports/phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`**.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 105** **§ Successor** filename freeze → **Phase 106** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_trade_currency_llm_overlay_phase106.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **868** passed, **2** skipped, **~2.36** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 107** ADR **`phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 107** — Vertical stub NPC **`deny_trade`** **`llm_agent`** overlay with **Phase 74** **non-zero** **`give_gold`** / **`want_gold`** on **`trade_proposed`** (NPC denies; voluntary **`trade_denied`** four-key **`payload`** per **Phase 105** / **`dispatcher.py`**). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`; closure **`reports/phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`**.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 106** **§ Successor** filename freeze → **Phase 107** (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_deny_trade_currency_llm_overlay_phase107.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **871** passed, **2** skipped, **~2.46** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 108** ADR **`phase108_npc_observation_trade_currency_parity_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 108** — NPC observation trade currency (**Phase 74** **`give_gold`** / **`want_gold`**) parity v0 — **`=== trades ===`** pending + **`recent_trade_events`** + exploration **`=== legality_hint ===`** vs **Phase 78** band; **`npc_system.md`** + **`test_npc_prompt_skeleton.py`** anchors. **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase108_npc_observation_trade_currency_parity_v0.md`; closure **`reports/phase108_npc_observation_trade_currency_parity_v0.md`**.
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 107** **§ Successor** filename freeze → **Phase 108** (**2026-04-15**)
  - [x] **Slice B** — implementer — **`=== trades ===`** pending + recent tails show non-zero gold **iff** present (**Phase 74** **`+Ng`** omit-zero parity) (**2026-04-15**)
  - [x] **Slice C** — implementer — **`=== legality_hint ===`** exploration **`trade_gold_afford:`** + trade paragraph **`+Ng`** cross-ref (**2026-04-15**)
  - [x] **Slice D** — implementer — **`npc_system.md`** + **`tests/test_npc_prompt_skeleton.py`** Phase **108** anchors (**2026-04-15**)
  - [x] **Slice E** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line (**2026-04-15**; **873** passed, **2** skipped, **~2.75** s, **`e89112f`**, **0** deselected)
  - [x] **Slice F** — reporter — **`reports/phase108_npc_observation_trade_currency_parity_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 109** ADR **`phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 109** — Vertical stub NPC **`revise_trade`** **`llm_agent`** overlay with **Phase 74** **`give_gold`** / **`want_gold`** (extends **Phase 81** revise fence + **Phase 106** gold seeds). **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`; closure **`reports/phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`**.
  - [x] **Slice A** — planner — ADR body + Tier A + **Phase 108** **§ Successor** filename respected (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_revise_trade_currency_llm_overlay_phase109.py`** (suggested) + goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **876** passed, **2** skipped, **~2.94** s; **`e89112f`** — **`--deselect`** no matching node on this tip → **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 110** ADR **`phase110_pyglet_revise_trade_currency_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 110** — Pyglet **`revise_trade`** + **Phase 74** trade gold v0 — default demo path + HUD/tests prove **currency-bearing** **`trade_proposed`** → **`revise_trade`** → **`trade_revised`** (**`+Ng`**, omit-zero) without new **`dispatcher`** rules. **Closed** **2026-04-15**. ADR `.lab/memory/extended/phase110_pyglet_revise_trade_currency_v0.md`; closure **`reports/phase110_pyglet_revise_trade_currency_v0.md`**.
  - [x] **Slice A** — planner — ADR body + Tier A + **Phase 109** **§ Successor** filename respected (**2026-04-15**)
  - [x] **Slice B** — implementer — **`run_pyglet_visual_client.py`** / demo **`CONFIG`**: NPC **`propose_trade`** + **Phase 74** gold toward hero; hero **`revise_trade`** + **`pyglet_trade_revise_*_gold`** → **`trade_revised`**; HUD currency (**2026-04-15**)
  - [x] **Slice C** — implementer — additive **`pytest`** + source guards; **`pytest`** **881** passed, **2** skipped (**2026-04-15**)
  - [x] **Slice D** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **881** passed, **2** skipped, **~3.06** s, **`e89112f`**, **0** deselected)
  - [x] **Slice E** — reporter — **`reports/phase110_pyglet_revise_trade_currency_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **Phase 111** ADR **`phase111_pyglet_accept_trade_after_revise_currency_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 111** — Pyglet **`accept_trade`** after **`trade_revised`** + **Phase 74** gold v0 — **Closed** **2026-04-15**. ADR **`.lab/memory/extended/phase111_pyglet_accept_trade_after_revise_currency_v0.md`**; closure **`reports/phase111_pyglet_accept_trade_after_revise_currency_v0.md`**. **§ Successor** → **Phase 112** ADR **`phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** (**frozen** **2026-04-15** reporter Slice **E**).
  - [x] **Slice A** — planner — ADR body + Tier A + **Phase 110** **§ Successor** filename respected (**2026-04-15**)
  - [x] **Slice B** — implementer — **`run_pyglet_visual_client.py`**: rising-edge **`accept_trade`** (CONFIG **`pyglet_trade_accept_*`**, default **`y`**) after **`trade_revised`** on **Phase 110** demo path; **`on_draw`** order vs revise + snapshot (**`lessons.md`**) (**2026-04-15**)
  - [x] **Slice C** — implementer — additive **`tests/test_run_pyglet_visual_client_config.py`** + module-doc / source guards (**`trade_accepted`** + **Phase 74** gold **iff** non-zero) + **`trade_hud_format`** **`trade_accepted`** tail (**2026-04-15**; implementer **`pytest`** **888** passed, **2** skipped, standard deselect, **~2.92** s)
  - [x] **Slice D** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **888** passed, **2** skipped, **~2.96** s, **`e89112f`**, **0** deselected)
  - [x] **Slice E** — reporter — **`reports/phase111_pyglet_accept_trade_after_revise_currency_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** → **`phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** (**frozen** **2026-04-15**)
- [x] **Phase 112** — Vertical stub NPC **`llm_agent`** **`accept_trade`** after **`trade_revised`** + **Phase 74** gold v0 — **Closed** **2026-04-15**. ADR **`.lab/memory/extended/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** (**filename frozen** by **Phase 111** **§ Successor**). Closure **`reports/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`**. **§ Successor** → **`phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**frozen** **2026-04-15** reporter Slice **D**).
  - [x] **Slice A** — planner — ADR body + Tier A + **Phase 111** **§ Successor** filename respected (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_accept_trade_after_revise_llm_overlay_phase112.py`** (suggested) + **`trade_proposed`** / **`trade_revised`** / **`trade_accepted`** goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **892** passed, **2** skipped, **~2.95** s, **`e89112f`**, **0** deselected)
  - [x] **Slice D** — reporter — **`reports/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** (**2026-04-15**; reporter re-verify **892** passed, **2** skipped, **~2.98** s, **`e89112f`**, **0** deselected)
- [ ] **Phase 113** — Vertical stub NPC **`deny_trade`** after **`trade_revised`** + **Phase 74** gold **`llm_agent`** overlay v0 — **Open** **2026-04-15**. ADR **`.lab/memory/extended/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**filename frozen** by **Phase 112** **§ Successor**). **Predecessor:** **Phase 112** (**closed**). **Next:** **reporter** **Slice D** (closure report + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** freeze).
  - [x] **Slice A** — planner — ADR + Tier A + **Phase 112** **§ Successor** filename respected (**2026-04-15**)
  - [x] **Slice B** — implementer — harness **`CONFIG`** + **`tests/test_vertical_play_stub_npc_deny_trade_after_revise_llm_overlay_phase113.py`** + **`trade_proposed`** / **`trade_revised`** / **`trade_denied`** goldens + subprocess fence; **`scripts/run_vertical_play_stub.py`** module-doc pointer (**2026-04-15**; standard deselect **`pytest`** **896** passed, **2** skipped, **~3.12** s)
  - [x] **Slice C** — reviewer — ADR **§ Reviewer sign-off** + standard deselect **`pytest`** line recorded (**2026-04-15**; **896** passed, **2** skipped, **~3.15** s, **`e89112f`**, **0** deselected)
  - [ ] **Slice D** — reporter — **`reports/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** freeze
- [ ] **Optional / non-gating backlog** — Phase **50**/**51** Slice **E** harness overlays; Ursina `equipped_item_id` quick-attack mirror notes; Phase 77 framebuffer variance (`lessons.md`). **Arcade (user contingency):** bounded `scripts/` spike if Pyglet stays window-unverified — primary path Pyglet until an ADR promotes a switch.
- [ ] **Pyglet Sproutlands-style art pass (user priority, non-gating vs numbered harness phases)** — Replace flat **`terrain_tile_grid`** / snapshot RGB grid (**`screenshots/pyglet1.png`**) with terrain that reads like user reference **`screenshots/sproutlands.png`** (tile atlas, texture sampling, or tuned biome palette); follow with HUD typography/contrast, item icons, character markers or sprites + minimal animation hook. **Assets:** `data/assets/` only; do not commit paid tile packs (document paths in README). **Sequencing:** land behind **Phase 113** unless a planner ADR promotes it; use POC + `reports/` stills like Phase **54**/**55** experiments.

## Notes

**Branches:** short-lived `feat/phase-*`; merge locally after reviewer sign-off when non-trivial.

**Workflow:** rotate implementer / experimenter / reviewer / debugger / researcher / reporter / critic.

**Assets:** configurable under `data/assets/`; do not commit paid packs (document in README).

**macOS Ursina:** `CocoaGraphicsPipe`, window position, `iCCP` without traceback → usually benign startup (`lessons.md`, `reports/phase11_visual_smoke_experiment.md`).

**Phase 13 + defer narrative:** `reports/phase13_closure.md`.

**Visual direction:** Ursina viewport **paused** as primary (Phase 53 ADR). **Pyglet** is the active interactive client (54+). Prefer **window-scoped** framebuffer evidence over full-desktop grabs (Phase 52 caveat).

**Pyglet triage:** If the window clears but geometry is missing, bisect `scripts/run_pyglet_visual_poc.py` vs `run_pyglet_visual_client.py` before concluding a Pyglet failure (`lessons.md`, `reports/phase54_*`).

**CI pytest (standard recipe):** `uv run pytest -q --deselect=tests/test_client_imports.py::test_pyglet_extra_subprocess_import_does_not_pull_ursina` — expect **2** skipped; **1** deselected only when that test id exists in the suite (on **`e89112f`** **2026-04-15** the id is absent → **0** deselected). **Tip `e89112f` (2026-04-15):** Phase **113** Slice **C** (reviewer) — **896** passed, **2** skipped (**~3.15** s, **0** deselected). Phase **113** Slice **B** (implementer) — **896** passed, **2** skipped (**~3.12** s, **0** deselected). Phase **113** Slice **A** (planner) — ADR body + Tier A sync (**no** new **`pytest`** delta). Phase **112** Slice **D** (reporter) — **892** passed, **2** skipped (**~2.98** s, **0** deselected). Phase **112** Slice **C** (reviewer) — **892** passed, **2** skipped (**~2.95** s, **0** deselected). Phase **112** Slice **B** (implementer) — **892** passed, **2** skipped (**~3.02** s, **0** deselected). Phase **111** Slice **E** (reporter) — **888** passed, **2** skipped (**~3.13** s, **0** deselected). Phase **111** Slice **D** (reviewer) — **888** passed, **2** skipped (**~2.96** s, **0** deselected). Phase **110** Slice **E** (reporter) — **881** passed, **2** skipped (**~2.95** s, **0** deselected). Phase **110** Slice **D** (reviewer) — **881** passed, **2** skipped (**~3.06** s, **0** deselected). Phase **109** Slice **D** (reporter) — **876** passed (**~2.89** s). Phase **109** Slice **C** (reviewer) — **876** passed, **2** skipped (**~2.94** s). Phase **108** Slice **F** (reporter) — **873** passed (**~2.78** s). Phase **108** Slice **E** (reviewer) — **873** passed (**~2.75** s). Phase **107** Slice **D** (reporter) — **871** passed (**~2.41** s). Phase **107** Slice **C** (reviewer) — **871** passed (**~2.46** s). Phase **107** Slice **B** (implementer) — **871** passed (**~2.48** s). Phase **106** Slice **D** (reporter) — **868** passed (**~2.40** s). Phase **106** Slice **C** (reviewer) — **868** passed (**~2.36** s). Phase **105** Slice **D** (reporter) — **865** passed (**~2.38** s). Phase **105** Slice **C** (reviewer) — **865** passed (**~2.28** s). Phase **105** Slice **B** (implementer) — **865** passed (**~2.33** s). Phase **104** Slice **D** (reporter) — **862** passed (**~2.23** s). Phase **104** Slice **C** (reviewer) — **862** passed (**~2.21** s). Phase **103** Slice **D** (reporter) — **859** passed (**~2.21** s). Phase **103** Slice **C** (reviewer) — **859** passed (**~2.17** s). Phase **102** Slice **D** — **857** passed (**2.11** s). Phase **101** close was **855** passed (**~2.13** s). Older per-phase counts live in each `reports/phaseNN_*.md` (not duplicated here).

**External Ursina triage (background):** [Stack Overflow — Ursina black screen](https://stackoverflow.com/questions/69963253/black-screen-when-i-try-to-use-ursina-on-python), [r/Ursina](https://www.reddit.com/r/Ursina/comments/1r2gcbw/issue_with_ursina/).

**Playable stub (research):** `scripts/run_vertical_play_stub.py` + `tests/test_vertical_play_stub_harness.py` (Phase 14).

## Done when

**Phases 0–62:** Fresh clone runs headless + stub tests; parent `[x]` matches code + `reports/phase*.md` (ADR sign-offs in `.lab/memory/extended/` where used). Slice acceptance lives in ADRs.

**Phases 51–62 / 63–98:** Closure reports + ADR sign-offs; numeric pytest lines belong in those reports / ADRs (not Tier A duplication).

**Phase 53:** Paused Ursina primary milestone — optional reviewer/reporter doc tails are non-gating vs Pyglet path.

**Closed band 63–112:** Each phase closed when its ADR + `reports/phaseNN_*.md` show reviewer/reporter sign-off as applicable. **Latest closed flagship:** Phase **112** — **892** passed, standard deselect, **`e89112f`**, **2026-04-15** — ADR **`.lab/memory/extended/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`**; closure **`reports/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`**. **Next gating flagship:** **Phase 113** — ADR **`.lab/memory/extended/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**open**; **Slices A–C** **2026-04-15**); **next:** **reporter** **Slice D** (closure **`reports/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** + Tier A parent **`[x]`** + ADR **§ Reporter sign-off** + **§ Successor** freeze).

**Phase 102 (closed):** Frozen successor from Phase **101** **§ Successor** — vertical stub **`llm_agent`** **`drop_item`** + **`item_dropped`** goldens + subprocess **`httpx`** / package **`llm`** fence; ADR slices **A–D** **`[x]`**.

**Phase 101 (closed):** Frozen successor from Phase **100** **§ Successor** — vertical stub **`llm_agent`** **`equip` / `use_item`** overlay + **`item_equipped` / `item_used`** goldens + subprocess **`httpx`** / package **`llm`** fence; ADR slices **A–D** **`[x]`**.

**Phase 100 (closed):** Frozen successor from Phase **99** **§ Successor** — restored **`equip` / `use_item`** on **`dispatch_action`**, structured NPC JSON, **`legality_hint`** + **`inventory_item_events`** **`item_equipped` / `item_used`** tails; ADR slices **A–G** **`[x]`**.
