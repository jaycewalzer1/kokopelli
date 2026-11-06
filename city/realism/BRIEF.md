# Brief: make the area around the bridge shot look as real as possible in Unreal (item 5)

You are a separate Claude Code instance. The user asked for this work. Another session (the "main" SimWorld session)
is working in parallel on the world-model side (Cosmos Sim-Transfer, controls, prompts, resolution).

## Goal
Make the Unreal render of ONE area photoreal-leaning, as a pilot. Do NOT extend it to the whole city yet.

**The area:** the shot in `out/filter_test/test_clip/` (read its `capture.json`, `README.md`, `poses.jsonl`, and look at
`rgb.mp4` / a few `rgb/*.png`). It walks the Moss–Commons sky bridge at 17.5 m, from x=356 to 380 m, y=115 m, looking east
toward the Commons dome. In world.json terms (x east, y south, metres; Unreal = same axes ×100 cm), work on everything
visible from that walk: the bridge itself, the Moss east bar and Commons west buildings' facades and roofs around
x≈330–420, y≈80–150, the plaza and street below, and the trees in view. The rest of the city stays as it is.

## What "real" means here
Keep the solarpunk design (city/VIBE.md, city/world.json, the moodboard's kept images in city/moodboard/board.json) —
same buildings, layout, palette. Change how it is rendered: real-world materials (PBR textures with roughness/normal
detail: timber grain, weathered render, stone paving, metal), believable foliage (real leaf cards / dense crowns
instead of smooth cushions), glass with reflections, small imperfections (dirt, wear, moss at bases), and lighting
(Lumen GI/reflections, soft shadows) — within what runs on this Mac.

## How the project works (read first)
- `mac_server/docs/CITY.md`, `docs/LOOK_PATCH.md`, `docs/PACKAGING.md`, `city/VIBE.md`, and `CLAUDE.md` (the user is learning:
  explain why, ask before design decisions, point at file:line).
- City code: `mac_server/Source/SimWorld/{Public,Private}/City/*`, `Private/SWEnvironment.cpp`; materials via
  `mac_server/Tools/look/` (Python commandlet authoring); planner `city/ue/build_city.py`; views `city/ue/render_views.py`.
- Compile: `cd mac_server && scripts/build.sh editor`. Run YOUR OWN editor instance on port **9003** only:
  `CVPORT=9003 scripts/relaunch.sh`. Build the city on it: `simworld/.venv/bin/python -I city/ue/build_city.py --port 9003`.
  Claim RAM: `python3 ram_share.py claim --name realism_9003 --gb 10 --pid <pid>`.
- **Never touch port 9001** (the user's live packaged server) or `mac_server/Packaged/`, and don't run `build.sh package`.
- The server accepts one client at a time.

## Two hazards found today (read mac_server/Source/SimWorld/Public/SWPlayerController.h)
1. UE 5.8 on Mac leaks one Metal shared event per *presented frame* while the window is visible (~60/s). After
   ~20–25 min visible, every other Metal app on the Mac (Qwen/Cosmos via MLX) fails. Launch with `MINIMIZED=1` /
   `-swminimized`, or press M; check with `lsmp -p <pid> | grep -c IOSurfaceSharedEventReference`. Restart your
   instance if it climbs past ~50k.
2. Residents left walking after an agent run walk off the map; not your concern unless you run agents.

## Rules
- Pilot area only. Gate any new look behind a region/flag so the rest of the city is unchanged
  (render a far view to prove it).
- Before/after renders of the bridge walk from the same poses (`poses.jsonl`) into `out/city_realism/`.
- Report frame time (`render_views.py --perf`) before/after; it must stay usable (< ~25 ms GPU in the pilot view).
- The 234 conformance tests must still pass on your instance (`SIMCV_PORT=9003 ... pytest tests`).
- Content you download: only free/CC0 sources (e.g. Poly Haven, ambientCG), no purchases, no account sign-ups; note
  each asset's licence in `city/realism/ASSETS.md`.
- No system-wide installs, no git commits. Stop an approach after two failures.
- Add an entry to `AGENTS.md` for what you own.
- When done, re-record the bridge walk's rgb (same poses, 1280×720, 30 fps) to `out/city_realism/bridge_rgb/` so the
  main session can feed it to the world model, and write a short `city/realism/REPORT.md`.
