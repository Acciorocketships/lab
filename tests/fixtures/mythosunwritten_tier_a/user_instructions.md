# User instructions

## New

## In progress

- **Pyglet graphics toward Sproutlands look (user):** Current window looks like a flat colour grid (**`screenshots/pyglet1.png`**); target look is the user reference **`screenshots/sproutlands.png`**. Prioritise terrain readability first, then UI polish, item presentation, and character sprites or animation hooks (see **`roadmap.md`** backlog row + **`immediate_plan.md`** parallel). Assets stay under **`data/assets/`** per repo policy (no paid packs in git).
- **Pyglet first, Arcade if stuck:** Keep working until **Pyglet** shows what you expect in **`run_pyglet_visual_client.py`** (use POC vs full-client bisect). If you **cannot verify** correct rendering after that, **try the Arcade library** as the next experiment (see **`roadmap.md`** optional backlog + **`immediate_plan.md`** parallel).
- Pause Ursina-first black-viewport remediation; move the **primary** interactive visual client path to **Pyglet** (see **`.lab/state/roadmap.md`** Phase **54**).

## Completed

- **Pyglet viewport / full client (Phase 77):** Tier A tracks **restored** **`run_pyglet_visual_client.main()`** terrain **`Batch`**, viewport diagnostics, and optional Slice **D** evidence — see **`reports/phase77_pyglet_full_client_viewport_v0.md`**. Residual framebuffer readback vs shapes can still be **host-dependent**; use POC vs full-client checks from **`lessons.md`** when triaging.
- **Pyglet viewport triage (pre–Phase 77):** solid-blue / clear-only vs real draws — POC **`scripts/run_pyglet_visual_poc.py`** vs full client bisect; **`reports/phase54_pyglet_visual_poc*.md`** for minimal-shape evidence notes.
- The Phase **52** window “after” screenshot in **`reports/`** was full-screen desktop capture, not proof of the game window. When I run the game the viewport is still **black**. I want a **minimal Ursina** sanity check (any simple scene that proves pixels) before we blame Mythos-only shaders, plus **research** into similar black-screen reports, and **window-only** framebuffer evidence next—not a full-desktop grab.
- When I run the game and the window opens, I still do not see a normal scene—often it looks like a black screen, and I want the visuals to actually work.
- Visual client minimal loop: Phase **49** closed — **`app.run()`** fix + bounded smoke (**`reports/phase49_track_a5_visual_client_recovery.md`**).

<!-- Agent/planner/reporter completion logs belong in `reports/` and Tier A `status.md` / `immediate_plan.md`, not here. -->
