# Extended Memory Index

Pointers to `.lab/memory/extended/*.md` (planner ADRs). Closure + evidence: `reports/phase*.md`. Open ADRs hold slice tables; this file stays an index only.

## Bootstrap & sim spine (0–12)

- **`engine_llm_notes.md`** — Headless vs visual CI, OpenRouter/Ollama sketches.
- **`phase5_combat_zone_rt_tb.md`** — RT→TB combat bubble, `World.combat`. Mirror: `reports/phase5_combat_zone.md`.
- **`phase6_overworld_v0.md`** — Chunked overworld, seeds, dumps. Mirror: `reports/phase6_overworld_v0.md`.
- **`phase7_territory_sentiment_v1.md`** — Sentiment kernel, diffusion, `game/territory`. Mirror: `reports/phase7_territory_sentiment_v1.md`.
- **`phase8_orchestrator_tools.md`** — Tool surface v0, audit, idempotency, prompts. Mirror: `reports/phase8_orchestrator_tools.md`.
- **`phase9_npc_agent_loop.md`** — NPC observation, cadence, stub step, prompts, formats. Mirror: `reports/phase9_npc_agent_loop.md`.
- **`phase10_ability_check.md`** — DC pipeline, fingerprints, stub/LLM judge, smoke. Mirror: `reports/phase10_ability_check_dc_agent.md`.
- **`phase11_ursina_client.md`** — Ursina client: assets, snapshot, terrain, actors, input. Mirror: `reports/phase11_ursina_client.md`.
- **`phase12_local_multiplayer.md`** — ≥2 `local_players`, bindings, import fence. Mirror: `reports/phase12_local_multiplayer.md`.

## Phase 13 — Polish / reach

- **`phase13_polish_reach.md`** — Tracks A–D ordering, slice matrix, defer ledger. Closures: `reports/phase13_closure.md`, `reports/phase13_track_d_persistent_rules.md`, `reports/phase13_polish_reach.md`, `reports/phase13_track_c_terrain_hints.md`.
- **`phase13_critic_closure.md`** — Critic verdict vs “game done”; gaps routed to later phases.

## Vertical harness & client parity (14–30)

- **`phase14_vertical_play_stub_harness.md`** — `run_vertical_play_stub.py` + goldens. `reports/phase14_vertical_play_stub_harness.md`.
- **`phase15_client_rules_parity.md`** — Ursina `rules_eval_config` parity. `reports/phase15_client_rules_parity.md`.
- **`phase16_vertical_stub_llm_npc.md`** — Structured LLM NPC on harness. `reports/phase16_vertical_stub_llm_npc.md`.
- **`phase17_vertical_orchestrator_npc_joint.md`** — Joint orchestrator + NPC tick order. `reports/phase17_vertical_orchestrator_npc_joint.md`.
- **`phase18_client_freeform_local_players.md`** — Client `freeform_ability` for locals (HUD → Phase 29). `reports/phase18_client_freeform_local_players.md`.
- **`phase19_npc_freeform_ability_check_parity.md`** — NPC `ability_check_*` kwargs. `reports/phase19_npc_freeform_ability_check_parity.md`.
- **`phase20_vertical_stub_freeform_ability_harness.md`** — Harness freeform + events. `reports/phase20_vertical_stub_freeform_ability_harness.md`.
- **`phase21_vertical_stub_orchestrator_active_rules.md`** — `install_active_rule` harness. `reports/phase21_vertical_stub_orchestrator_active_rules.md`.
- **`phase22_vertical_stub_orchestrator_terrain_hints.md`** — Terrain hints in harness. `reports/phase22_vertical_stub_orchestrator_terrain_hints.md`.
- **`phase23_vertical_stub_orchestrator_remove_active_rule.md`** — `orchestrator_tool_batches` + remove rule. `reports/phase23_vertical_stub_orchestrator_remove_active_rule.md`.
- **`phase24_vertical_stub_orchestrator_spawn_npc.md`** — Harness `spawn_npc`. `reports/phase24_vertical_stub_orchestrator_spawn_npc.md`.
- **`phase25_vertical_stub_orchestrator_narrate_state_patch.md`** — `narrate_world_patch` + `state_patch`. `reports/phase25_vertical_stub_orchestrator_narrate_state_patch.md`.
- **`phase26_vertical_stub_orchestrator_audit_parity.md`** — Audit ↔ `orchestrator_tool` events. `reports/phase26_vertical_stub_orchestrator_audit_parity.md`.
- **`phase27_orchestrator_sliding_window_rate_limit.md`** — Sliding-window cap stub. `reports/phase27_orchestrator_sliding_window_rate_limit.md`.
- **`phase28_vertical_stub_sliding_window_rate_limit.md`** — Harness overlay for rate limits. `reports/phase28_vertical_stub_sliding_window_rate_limit.md`.
- **`phase29_client_freeform_hud_outcome.md`** — Freeform HUD formatter + Ursina wiring. `reports/phase29_client_freeform_hud_outcome.md`.
- **`phase30_orchestrator_smoke_parity.md`** — `orchestrator_smoke.py` parity. `reports/phase30_orchestrator_smoke_parity.md`.

## NPC async & headless helpers (31–40)

- **`phase31_orchestrator_docs_timing_hygiene.md`** — Ops guide / timing tables (Tier A `lessons.md` § orchestrator). `reports/phase31_orchestrator_docs_timing_hygiene.md`.
- **`phase32_npc_planner_observability_v0.md`** — `npc_planner_metrics`. `reports/phase32_npc_planner_observability_v0.md`.
- **`phase33_npc_async_llm_overlap_spike.md`** — Async overlap design (Track B6). `reports/phase33_npc_async_llm_overlap_spike.md`; mirror: `reports/phase13_track_b6_async_llm_design.md`.
- **`phase34_headless_events_capture_helper.md`** — `run_headless_events`. `reports/phase34_headless_events_capture_helper.md`.
- **`phase35_headless_events_helper_adoption.md`** — Test/script adoption. `reports/phase35_headless_events_helper_adoption.md`.
- **`phase36_npc_async_llm_planner_implementation.md`** — Async planner code (opt-in). `reports/phase36_npc_async_llm_planner_implementation.md`.
- **`phase37_vertical_stub_npc_async_planner.md`** — Harness async proof. `reports/phase37_vertical_stub_npc_async_planner.md`.
- **`phase38_vertical_stub_npc_async_combat_cancel.md`** — `combat_cancelled` defer path. `reports/phase38_vertical_stub_npc_async_combat_cancel.md`.
- **`phase39_npc_async_deferred_event_seq_stale.md`** — `stale_event_seq` + baseline refresh. `reports/phase39_npc_async_deferred_event_seq_stale.md`.
- **`phase40_ability_check_llm_dc_pipeline.md`** — Config-gated LLM DC judge. `reports/phase40_ability_check_llm_dc_pipeline.md`.

## Track mitigations & rule DSL (41–48)

- **`phase41_track_d5_exploit_mitigations_v0.md`** — Rule-event volume cap. `reports/phase41_track_d5_exploit_mitigations_v0.md`.
- **`phase42_track_c5_chunk_regen_cache_invalidation.md`** — Chunk cache epoch + snapshot keys. `reports/phase42_track_c5_chunk_regen_cache_invalidation.md`.
- **`phase43_track_c4_overworld_ascii_harness_v0.md`** — ASCII harness + digest. `reports/phase43_track_c4_overworld_ascii_harness_v0.md`.
- **`phase44_track_d6_rule_dsl_design_spike.md`** — Rule DSL design. `reports/phase44_track_d6_rule_dsl_design_spike.md`.
- **`phase45_track_d6_rule_dsl_implementation_v0.md`** — `rule_program_v0` runner. `reports/phase45_track_d6_rule_dsl_implementation_v0.md`.
- **`phase46_vertical_stub_rule_program_v0.md`** — Harness `rule_program_v0`. `reports/phase46_vertical_stub_rule_program_v0.md`.
- **`phase47_rule_program_v0_opcode_mod_emit.md`** — Opcode `emit_trigger_mod`. `reports/phase47_rule_program_v0_opcode_mod_emit.md`.
- **`phase48_vertical_stub_phase43_overlay.md`** — Phase 43 overlay + epoch in harness. `reports/phase48_vertical_stub_phase43_overlay.md`.

## Visual / Ursina (49–53)

- **`phase49_track_a5_visual_client_recovery.md`** — Visual recovery + smoke. `reports/phase49_track_a5_visual_client_recovery.md`.
- **`phase50_rule_program_v0_opcode_emit_trigger_labeled.md`** — Opcode `emit_trigger_labeled`. `reports/phase50_rule_program_v0_opcode_emit_trigger_labeled.md`.
- **`phase51_rule_program_v0_opcode_emit_trigger_mod_labeled.md`** — Opcode `emit_trigger_mod_labeled`. `reports/phase51_rule_program_v0_opcode_emit_trigger_mod_labeled.md`.
- **`phase52_visual_client_scene_rendering.md`** — macOS Core Profile / GLSL 130→150 mitigation. `reports/phase52_visual_client_scene_rendering.md`; triage: `reports/phase52_slice_b_visual_client_triage.md`, `reports/phase52_slice_d_visual_window_experiment.md`.
- **`phase53_visual_client_viewport_truth.md`** — **Paused** Ursina primary path; window-truth + minimal POC notes. `reports/phase53_slice_d_window_truth_experiment.md`, `reports/phase53_minimal_ursina_poc.png` (artifacts dir).

## Vertical harness follow-on (64–70)

Sequence: inventory harness → attack default → `drop_item` → `pick_up` → `give_item` → propose/accept → deny. Each: ADR + `reports/phaseNN_*.md`; harness tests use goldens + subprocess `httpx`/`llm` fences where noted in the report.

- **`phase64_vertical_stub_npc_inventory_actions_harness.md`** — Closed **2026-04-14**. Stub `equip`/`use_item`, `item_equipped`/`item_used`. `reports/phase64_vertical_stub_npc_inventory_actions_harness.md`.
- **`phase65_npc_structured_attack_equipped_item_default.md`** — Closed **2026-04-14**. `attack` default `item_id` from `equipped_item_id`. `reports/phase65_npc_structured_attack_equipped_item_default.md`.
- **`phase66_vertical_stub_npc_drop_item_headless_harness.md`** — Closed **2026-04-14**. `drop_item`, `item_dropped`. `reports/phase66_vertical_stub_npc_drop_item_headless_harness.md`.
- **`phase67_vertical_stub_npc_pick_up_headless_harness.md`** — Closed **2026-04-14**. `ground_items`, `pick_up`, `item_picked_up`. `reports/phase67_vertical_stub_npc_pick_up_headless_harness.md`.
- **`phase68_vertical_stub_npc_give_item_headless_harness.md`** — Closed **2026-04-14**. `give_item`, `item_given`. `reports/phase68_vertical_stub_npc_give_item_headless_harness.md`.
- **`phase69_vertical_stub_npc_propose_accept_trade_headless_harness.md`** — Closed **2026-04-14**. `propose_trade`/`accept_trade`, events. `reports/phase69_vertical_stub_npc_propose_accept_trade_headless_harness.md`.
- **`phase70_vertical_stub_npc_deny_trade_headless_harness.md`** — Closed **2026-04-14**. `deny_trade`, stale cleanup. `reports/phase70_vertical_stub_npc_deny_trade_headless_harness.md`.

## Pyglet client (54–77)

- **`phase54_pyglet_visual_client_v0.md`** — Pyglet v0 POC + extras. Research: **`phase54_pyglet_macos_opengl_research.md`**. `reports/phase54_pyglet_visual_client_v0.md`.
- **`phase55_pyglet_client_snapshot_2d.md`** — Snapshot-driven terrain grid (`terrain_tile_grid`). `reports/phase55_pyglet_client_snapshot_2d.md`.
- **`phase56_pyglet_input_dispatch_hud.md`** — Keys → `dispatch_action` + HUD. `reports/phase56_pyglet_input_dispatch_hud.md`.
- **`phase57_pyglet_entity_markers_combat_ui_perf.md`** — Markers + combat HUD + Slice G perf (metrics-only, **2026-04-14**). `reports/phase57_pyglet_entity_markers_combat_ui_perf.md`, `reports/phase57_slice_g_*`.
- **`phase58_pyglet_target_cooldown_freeform.md`** — Target cycle, cooldown HUD, freeform input. `reports/phase58_pyglet_target_cooldown_freeform.md`.
- **`phase59_pyglet_inventory_hud.md`** — Read-only inventory HUD. `reports/phase59_pyglet_inventory_hud.md`.
- **`phase60_pyglet_mouse_tile_picking.md`** — Mouse ↔ tile hit + optional click-move. `reports/phase60_pyglet_mouse_tile_picking.md`.
- **`phase61_pyglet_mouse_melee_target_integration.md`** — Click tile → melee selection. `reports/phase61_pyglet_mouse_melee_target_integration.md`.
- **`phase62_pyglet_inventory_equip_use_item.md`** — `equip` / `use_item` + `equipped_item_id` + Pyglet keys. `reports/phase62_pyglet_inventory_equip_use_item.md`.
- **`phase63_pyglet_inventory_followthrough_npc_quick_attack.md`** — Closed **2026-04-14**. NPC equip/use + quick-attack default item. `reports/phase63_pyglet_inventory_followthrough_npc_quick_attack.md`.
- **`phase71_pyglet_trade_ux_v0.md`** — Closed **2026-04-14**. Pyglet trade keys + `trade_hud_format`. `reports/phase71_pyglet_trade_ux_v0.md`.
- **`phase72_pending_trade_timeout_v0.md`** — Closed **2026-04-14**. `expires_at_tick`, tick expiry. `reports/phase72_pending_trade_timeout_v0.md`.
- **`phase73_pending_trades_multi_slot_queue_v0.md`** — Closed **2026-04-14**. `pending_trades` FIFO + `trade_id`. `reports/phase73_pending_trades_multi_slot_queue_v0.md`.
- **`phase74_trade_currency_v0.md`** — Closed **2026-04-14**. `gold` + trade gold fields. `reports/phase74_trade_currency_v0.md`.
- **`phase75_trade_counter_offer_design_spike_v0.md`** — Closed **2026-04-15** (doc-only). Design 1 + `trade_revised` name freeze. `reports/phase75_trade_counter_offer_design_spike_v0.md`.
- **`phase76_trade_revised_implementation_v0.md`** — Closed **2026-04-15**. `revise_trade` / `trade_revised`. `reports/phase76_trade_revised_implementation_v0.md`.
- **`phase77_pyglet_full_client_viewport_v0.md`** — Closed **2026-04-15**. Viewport / terrain `Batch`, diagnostics, Slice D evidence (`reports/phase77_slice_d_viewport_evidence.md`). `reports/phase77_pyglet_full_client_viewport_v0.md`.

## NPC planner trade parity (78+)

Closed **2026-04-15** unless noted. Each row: ADR under `.lab/memory/extended/` + mirror `reports/phaseNN_*.md` (pytest counts / slice tables live there, not here).

- **`phase78_npc_observation_trade_revise_parity_v0.md`** — Observation `=== trades ===` + `legality_hint` trade/`revise_trade`. `reports/phase78_npc_observation_trade_revise_parity_v0.md`.
- **`phase79_pyglet_ground_loot_hud_markers_v0.md`** — `ground_tiles`, `pyglet_free_ground_loot_hud`, Pyglet HUD/markers. `reports/phase79_pyglet_ground_loot_hud_markers_v0.md`.
- **`phase80_pyglet_click_pick_up_v0.md`** — CONFIG click → `pick_up`. `reports/phase80_pyglet_click_pick_up_v0.md`.
- **`phase81_vertical_stub_npc_revise_trade_llm_overlay_v0.md`** — Hero `propose_trade` + NPC `llm_agent` `revise_trade` / `trade_revised`; harness + subprocess fence. `reports/phase81_vertical_stub_npc_revise_trade_llm_overlay_v0.md`.
- **`phase82_pyglet_drop_item_v0.md`** — Pyglet `drop_item`. `reports/phase82_pyglet_drop_item_v0.md`.
- **`phase83_pyglet_give_item_v0.md`** — Pyglet `give_item`. `reports/phase83_pyglet_give_item_v0.md`.
- **`phase84_vertical_stub_npc_give_item_llm_overlay_v0.md`** — LLM overlay `give_item` → `item_given`. `reports/phase84_vertical_stub_npc_give_item_llm_overlay_v0.md`.
- **`phase85_pyglet_examine_v0.md`** — Pyglet `examine` + `entity_examined`. `reports/phase85_pyglet_examine_v0.md`.
- **`phase86_vertical_stub_npc_examine_llm_overlay_v0.md`** — LLM overlay `examine`. `reports/phase86_vertical_stub_npc_examine_llm_overlay_v0.md`.
- **`phase87_npc_observation_examine_entity_examined_parity_v0.md`** — Observation `entity_examined` + `examine:` legality. `reports/phase87_npc_observation_examine_entity_examined_parity_v0.md`.
- **`phase88_npc_observation_wait_say_events_legality_parity_v0.md`** — `wait` / `say` tails + legality. `reports/phase88_npc_observation_wait_say_events_legality_parity_v0.md`.
- **`phase89_interact_action_dispatcher_events_observation_parity_v0.md`** — `interact` + `entity_interacted` + observation. `reports/phase89_interact_action_dispatcher_events_observation_parity_v0.md`.
- **`phase90_pyglet_interact_v0.md`** — Pyglet `interact`. `reports/phase90_pyglet_interact_v0.md`.
- **`phase91_vertical_stub_npc_interact_llm_overlay_v0.md`** — LLM overlay `interact`. `reports/phase91_vertical_stub_npc_interact_llm_overlay_v0.md`.
- **`phase92_npc_observation_interact_entity_interacted_parity_v0.md`** — `recent_entity_interacted_as_target:` + `interact:` legality. `reports/phase92_npc_observation_interact_entity_interacted_parity_v0.md`.
- **`phase93_trade_counter_offer_design2_design_spike_v0.md`** — Design 2 doc spike; defer shipping (policy freezes in ADR). `reports/phase93_trade_counter_offer_design2_design_spike_v0.md`.
- **`phase94_pyglet_wait_say_v0.md`** — Pyglet `wait` / `say` + `wait_say_hud_format`. `reports/phase94_pyglet_wait_say_v0.md`.
- **`phase95_vertical_stub_npc_wait_say_llm_overlay_v0.md`** — LLM overlay `wait` / `say`. `reports/phase95_vertical_stub_npc_wait_say_llm_overlay_v0.md`.
- **`phase96_vertical_stub_npc_freeform_ability_llm_overlay_v0.md`** — LLM overlay `freeform_ability`. `reports/phase96_vertical_stub_npc_freeform_ability_llm_overlay_v0.md`.
- **`phase97_npc_observation_freeform_ability_ability_check_parity_v0.md`** — `ability_check_events` + `freeform_ability:` legality. `reports/phase97_npc_observation_freeform_ability_ability_check_parity_v0.md`.
- **`phase98_npc_observation_move_attack_end_turn_parity_v0.md`** — **Closed** **2026-04-15**. `move:` / `attack:` / `end_turn:` legality + **`=== combat_movement_events ===`** tails; **`npc_system.md`** + **`test_npc_prompt_skeleton.py`** anchors; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase98_npc_observation_move_attack_end_turn_parity_v0.md`**.
- **`phase99_npc_observation_inventory_actions_legality_parity_v0.md`** — **Closed** **2026-04-15**. **Slices A–F** **`[x]`**: inventory **`legality_hint`** + **`=== inventory_item_events ===`** tails + prompt anchors; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase99_npc_observation_inventory_actions_legality_parity_v0.md`**. **§ Successor** → **Phase 100** (**frozen** **2026-04-15**).
- **`phase100_equip_use_item_dispatch_observation_parity_v0.md`** — **Closed** **2026-04-15**. **Slices A–G** **`[x]`**: **`dispatch_action`** **`equip` / `use_item`** + observation **`legality_hint`** + **`inventory_item_events`** **`item_equipped` / `item_used`**; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase100_equip_use_item_dispatch_observation_parity_v0.md`**. **§ Successor** → **Phase 101** (**selected** **2026-04-15**).
- **`phase101_vertical_stub_npc_equip_use_item_llm_overlay_v0.md`** — **Closed** **2026-04-15** — Slices **A–D** **`[x]`** — vertical stub **`llm_agent`** **`equip` / `use_item`** + **`item_equipped` / `item_used`** goldens + subprocess fence; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase101_vertical_stub_npc_equip_use_item_llm_overlay_v0.md`**. **§ Successor** → **Phase 102** (**selected** **2026-04-15**).
- **`phase102_vertical_stub_npc_drop_item_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`drop_item`** + **`item_dropped`** goldens + subprocess fence (**`tests/test_vertical_play_stub_npc_drop_item_llm_overlay_phase102.py`**); ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase102_vertical_stub_npc_drop_item_llm_overlay_v0.md`**. **§ Successor** (**frozen**) → **Phase 103** **`pick_up`** **`llm_agent`** overlay.
- **`phase103_vertical_stub_npc_pick_up_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`pick_up`** + **`item_picked_up`**; closure **`reports/phase103_vertical_stub_npc_pick_up_llm_overlay_v0.md`**; ADR **§ Reviewer** + **§ Reporter sign-off**; **§ Successor** → **Phase 104** **`propose_trade`** / **`accept_trade`** overlay ADR **`phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`**.
- **`phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`propose_trade`** / **`accept_trade`** + **`trade_proposed`** / **`trade_accepted`** goldens + subprocess fence (**`tests/test_vertical_play_stub_npc_propose_accept_trade_llm_overlay_phase104.py`**); ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase104_vertical_stub_npc_propose_accept_trade_llm_overlay_v0.md`**. **§ Successor** → **Phase 105** **`deny_trade`** **`llm_agent`** overlay ADR **`phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`** (**planner** **Slice A**).
- **`phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`deny_trade`** after hero **`propose_trade`**; voluntary **`trade_denied`** payload vs **`dispatcher.py`** (**`reason`:** **`"denied"`**); goldens + subprocess fence (**`tests/test_vertical_play_stub_npc_deny_trade_llm_overlay_phase105.py`**); ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase105_vertical_stub_npc_deny_trade_llm_overlay_v0.md`**. **§ Successor** → **Phase 106** ADR **`phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`**.
- **`phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`propose_trade`** / **`accept_trade`** with **Phase 74** **`give_gold`** / **`want_gold`** on events; **Phase 104**-class fence; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase106_vertical_stub_npc_trade_currency_llm_overlay_v0.md`**. **§ Successor** → **Phase 107** ADR **`phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`** (**frozen** **2026-04-15**).
- **`phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`deny_trade`** after hero **`propose_trade`** with **non-zero** gold on **`trade_proposed`**; **`tests/test_vertical_play_stub_npc_deny_trade_currency_llm_overlay_phase107.py`** + **`run_vertical_play_stub.py`** doc; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase107_vertical_stub_npc_deny_trade_currency_llm_overlay_v0.md`**. **§ Successor** → **Phase 108** ADR **`phase108_npc_observation_trade_currency_parity_v0.md`** (**frozen** **2026-04-15** planner Slice **A**).
- **`phase108_npc_observation_trade_currency_parity_v0.md`** — **Closed** **2026-04-15** — **Slices A–F** **`[x]`** — NPC observation **`=== trades ===`** / **`recent_trade_events`** / **`legality_hint`** for **Phase 74** gold vs **Phase 78** band; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase108_npc_observation_trade_currency_parity_v0.md`**. **§ Successor** → **Phase 109** ADR **`phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`** (**frozen** **2026-04-15** reporter Slice **F**).
- **`phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** **`revise_trade`** after hero **`propose_trade`** with **Phase 74** gold; **`tests/test_vertical_play_stub_npc_revise_trade_currency_llm_overlay_phase109.py`** + subprocess fence; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase109_vertical_stub_npc_revise_trade_currency_llm_overlay_v0.md`**. **§ Successor** → **Phase 110** ADR **`phase110_pyglet_revise_trade_currency_v0.md`** (**frozen** **2026-04-15** reporter Slice **D**).
- **`phase110_pyglet_revise_trade_currency_v0.md`** — **Closed** **2026-04-15** — **Slices A–E** **`[x]`** — Pyglet **`revise_trade`** + **Phase 74** gold on default demo path + HUD/tests; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase110_pyglet_revise_trade_currency_v0.md`**. **§ Successor** → **Phase 111** ADR **`phase111_pyglet_accept_trade_after_revise_currency_v0.md`** (**frozen** **2026-04-15** reporter Slice **E**).
- **`phase111_pyglet_accept_trade_after_revise_currency_v0.md`** — **Closed** **2026-04-15** — **Slices A–E** **`[x]`** — Pyglet rising-edge **`accept_trade`** after **`trade_revised`** + **Phase 74** **`trade_accepted`** / HUD; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase111_pyglet_accept_trade_after_revise_currency_v0.md`**. **§ Successor** → **`phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** (**frozen** **2026-04-15** reporter Slice **E**).
- **`phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`** — **Closed** **2026-04-15** — **Slices A–D** **`[x]`** — vertical stub **`llm_agent`** three-tick **`propose_trade`** → **`revise_trade`** → **`accept_trade`** with **Phase 74** gold + **Phase 104**/**106**/**109**-class subprocess fence; **`tests/test_vertical_play_stub_npc_accept_trade_after_revise_llm_overlay_phase112.py`**; ADR **§ Reviewer** + **§ Reporter sign-off**; closure **`reports/phase112_vertical_stub_npc_accept_trade_after_revise_llm_overlay_v0.md`**. **§ Successor** → **`phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**frozen** **2026-04-15** reporter Slice **D**).
- **`phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** — **Open** **2026-04-15** — **Slices A–C** **`[x]`** — vertical stub **`llm_agent`** three-tick **`propose_trade`** → **`revise_trade`** → **`deny_trade`** + **Phase 74** gold on propose/**`trade_revised`**; voluntary **`trade_denied`** per **Phase 105**/**107**; **`tests/test_vertical_play_stub_npc_deny_trade_after_revise_llm_overlay_phase113.py`** + **`run_vertical_play_stub.py`** module-doc; ADR **§ Reviewer sign-off** (**Slice C** **2026-04-15**); standard deselect **`pytest`** **896** passed, **2** skipped (**~3.15** s reviewer, **`e89112f`**, **0** deselected); **§ Successor** pending **reporter** Slice **D** (planner candidate **`phase114_pyglet_deny_trade_after_revise_currency_v0.md`**); target closure **`reports/phase113_vertical_stub_npc_deny_trade_after_revise_llm_overlay_v0.md`** (**pending**).
