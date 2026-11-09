# Agents working in this repo

Add a short entry for what you own and what you're touching. Update it when your status changes.

## World model agent loop (`feat/wm-agent-loop`)

- **Status:** Loop, mocks, event log, leak guard, viewer and tests are committed on the branch. SimWorld work is merged and connected, tested on fake servers only. Real Mac runs are on the `ops/gpu.py` queue at priorities 10, 20 and 30.
- **Worktree:** `.claude/worktrees/wm-agent-loop`. It includes a snapshot of `life/` and `homeostatic/`; the originals stay uncommitted in this checkout.
- **Owns:** `runtime/`, apart from the SimWorld files listed below. Anything needed outside them goes in `runtime/HANDOFF.md` rather than being edited directly.
- **Reads only:** `blend.py`, `world_model.py`, `llm_model.py`, `settings.py`, `life/`, `simworld/`, `out/life.db`.
- **Will run in:** its own git worktree, never by switching branches in this shared checkout. Anything it launches is prefixed `wmloop_`.

## Benchmarks (`feat/evals`)

- **Status:** Finished its first pass. 12 local commits on the branch, not pushed. `PREREG.md` is still a draft, waiting on the owner.
- **Owns:** `benchmarks/`, `scripts/pace/evals/`.
- **Runs:** anything it launches is prefixed `evals_`. Real model runs go through the `ops/gpu.py` queue at priority 40, in turns of 30 minutes or less. `benchmarks.run` isn't recognized as a model job by the queue, so never start it outside the queue.

## SimWorld capabilities (`feat/wm-simworld`)

- **Status:** Finished and merged into `feat/wm-agent-loop`. No real server run yet.
- **Owns:** `runtime/physics.py`, `runtime/adapters/simworld*`, `runtime/tests/test_simworld*`, `runtime/SIMWORLD.md`, `scripts/pace/`.
- **Reads only:** `simworld/`. Proposed changes to it go in `runtime/HANDOFF.md`.
- **Runs:** tests against a fake local UnrealCV server only, with no Cosmos, Qwen or real UE. Ports and temp dirs are prefixed `wmloop_`.

## Overnight coordination and morning status (`feat/ops`)

- **Status:** Running overnight in its own git worktree, `.claude/worktrees/ops`. Doesn't change anyone else's code.
- **Owns:** `ops/`, `out/ops/`. The morning report is `out/ops/MORNING.md`.
- **GPU turns:** start every model job with `python3 /Users/jaycewalzer/Desktop/kokopelli/.claude/worktrees/ops/ops/gpu.py run --name NAME --priority N --max-hours H --cwd DIR --about "WHAT IT DOES" --output PATH -- CMD`. Lower numbers go first. **The owner requires every experiment to have `--about` (a sentence or two on what it does and why, at most 400 characters) and at least one `--output` (a file or folder it writes, relative to `--cwd`), so the panel's GPU tab can explain it and show its outputs. A job without them isn't queued.** It waits for its turn and exits with the job's code. `gpu.py status` shows the line. Priorities tonight: 10 for the real demo run, 20-30 for 4-bit conversion and the low-memory run, 40 for benchmarks, 50 for homeostatic training.
- **Running jobs (2026-11-08):** once a job has its turn, a keeper process owns it, so killing `gpu.py run` or closing a terminal does NOT stop the job and it stays counted. To end one: `gpu.py stop --name NAME` (SIGTERM to its whole process group, SIGKILL after 30 s), or Stop job in the panel's drawer. Never kill model processes by hand or with a `pkill` pattern. `--gb N` holds a job until `ram_share.py` says N GB is free; use it for jobs that aren't `Guard`-polite. `status` says why each job waits and how long a running job's log has been quiet. A Python process over 8 GB that no ticket owns blocks the queue as an outside job, whatever it's called. Memory is measured with `phys_footprint`, because `ps` RSS leaves out MLX's Metal buffers. Per-job machine readings (macmon, `brew install macmon`) go in `out/ops/job_logs/*.metrics.jsonl` and the ledger.
- **Backups:** snapshots the uncommitted `main` tree to `refs/backup/main-wip` without touching the index or branches.

## Feel-then-decide agent (working tree on `main`, uncommitted)

- **Status:** Replaces the teacher idea, which the user dropped. `mind/feeling.py` wraps any runtime agent to say what changed, update a slowly moving feeling from that, and decide only at decision points, without editing `runtime/`. Open questions are in `mind/OPEN_DECISIONS.md`.
- **Owns:** `mind/`, `tests/test_mind.py`.
- **Runs:** `mind.run` and `mind.check`, writing to `out/mind/`. Real Qwen goes through the GPU queue at priority 45.
- **For viewers:** `out/mind/<run>/feelings.jsonl` is written as a run happens, and `mind.feeling.timeline(path)` turns it into one entry per tick. Row fields are at the top of `mind/feeling.py`.
- **Trained models:** `mind.run --weights <run>/fused`. `mind.check --replay --weights ...` compares it with a base run on identical moments.

## GPU queue view (working tree on `main`, uncommitted)

- **Status:** The dev panel's `/queue` page is a one-screen board (redone 2026-11-06): the job on the GPU with a running clock, GPU busy and memory as moving 15-minute lines, a 12-hour timeline with a moving now line, the waiting line as cards with growing waits, and recent results. Clicking any job opens a drawer with its details, outputs, log, command and controls (priority, Mac or PACE, cancel). Every change still goes through `gpu.py`'s own commands, and only this panel's own page can make one.
- **Owns:** `life/gpu_queue.py`, `life/static/queue.*`, `tests/test_life_gpu_queue.py`. The queue itself stays with overnight coordination.

## Wellness center night and staged jobs (working tree on `main`, uncommitted)

- **Status:** Started 2026-11-05 19:33, writing to `out/scenario/2026-11-05-193212`. At 01:40 on 11-06 it had finished 4 of 12 mornings and was waiting behind `simworld_mac_server`, after giving way twice. The spec's calibration check fails on its own payoff table; reported, not fixed.
- **Owns:** `life/scenario.py`, `life/scenario_night.py`, `life/staged.py`, `ram_share.py`, `tests/test_life_scenario.py`, `SCENARIO_*` and `STAGED_JOBS` in `settings.py`, `out/scenario/`, `out/staged/`, `out/ram/`, and the Ready to start section of the queue page.
- **Touched:** `Engine._limit` and `_close` take an optional window and extra closing context, and `closing_prompt` shows a fixed outcome when given one. Existing behavior is unchanged.
- **Runs:** through the GPU queue at priority 60, about 6.4 h. It's polite: between model calls it ends its turn (exit 75) if any local ticket with a lower number is waiting, then queues itself again and resumes. The simcity Unreal work (`mac_server`, priority 1) comes first.
- **Memory outside the queue:** heavy work the queue can't see claims memory with `python ram_share.py hold --name NAME --gb N -- CMD` or `claim --pid`. The night won't load a model into claimed room, and it gives Qwen back if memory runs short.

## PACE backend for the queue (working tree on `main`, uncommitted)

- **Status:** Built and tested against a fake Slurm only. Nothing has reached PACE: it needs the user's `cloud/pace.json` and an open SSH connection (`cloud/README.md`), and no job has a CUDA `--pace-command` yet.
- **Owns:** `cloud/`, `tests/test_cloud_pace.py`. `gpu.py` calls `cloud.pace.run_job` for a ticket whose `where` is `pace` (feat/ops `ac89532`).

## Homeostatic post-training and the dev panel (working tree on `main`, uncommitted)

- **Status:** Running overnight. The code is written; training hasn't yet beaten the untrained model. The first-token pilot is queued as `homeostatic_pilot_first_token`.
- **Owns:** `homeostatic/`, the `HOMEOSTATIC_*` settings, `life/static/training.*`, `life/static/architecture.*`, `life/architecture.py`, and `tests/test_homeostatic_*`.
- **Runs:** real Qwen training (about 20 GB), one model job at a time, as `homeostatic.train` and `homeostatic.experiment`, writing to `out/homeostatic/`. It also keeps the dev panel up on port 8765.
- **GPU turns:** training goes through the queue in the overnight coordination entry, at priority 50. `out/world_data_20261104/collect.py` was started before the queue existed, and the queue waits for it.

## World model as a filter over the sim (working tree on `main`, uncommitted)

- **Status:** Testing on the Mac. `world_filter.py` adds edge control to Cosmos3-Nano without editing the runner; not yet connected to `runtime/`.
- **Owns:** `edges.py`, `world_filter.py`, `filter_video` in `world_model.py`, `tests/test_edges.py`, `tests/test_world_filter.py`, `out/edge_filter/`.
- **Runs:** through the GPU queue as `edge_filter_*`.

## Watch the agent view (working tree on `main`, uncommitted)

- **Status:** The dev panel's `/city-live` page: pick a city agent run, see its first-person frame, what it's doing and thinking, a top-down map with the agent, people, things and route, and the decision log. A live run is polled; a finished one is replayed decision by decision. Read-only.
- **Owns:** `life/city_live.py`, `life/static/city-live.*`, `life/static/city-draw.js`, `tests/test_life_city_live.py`.
- **Reads only:** `out/city_agents/` (written by `city/agents/live.py`, which it never changes), `city/world.json` via `/api/city`.
- **Touched:** `life/panel.py` (the `/city-live` page, `/api/city-live/runs`, `/api/city-live/run`, `/api/city-live/frame`); a "Watch the agent" link in every page's sidebar; `life/static/city-plan.js` now imports its drawing from `city-draw.js` instead of holding it, with the moodboard plan unchanged. The live page reuses the `#plan-svg` styles in `moodboard.css` without editing them.

## Sim-to-real filter test, and the model runs page (working tree on `main`, uncommitted)

- **Status:** The test clip is the Moss-Commons sky bridge walk with a moving head (`out/filter_test/test_clip/`; the garden take is `test_clip_garden/`). Weights are downloaded and the controls made. The three runs are queued at p20-22 (`filter_sd15_simdepth`, `filter_sd15_dadepth`, `filter_cosmos_simdepth`), waiting behind the SimWorld hold. Metrics and the comparison video come after.
- **Owns:** `filter_test/`, `out/filter_test/`. The dev panel's runs page is now "Model runs" (still `/worlds`): type tabs from `world_runs.TYPES`, group by source or type, sort, and a Sim-to-real test group. Touched `life/world_runs.py`, `life/static/worlds.*`, `tests/test_life_world_runs.py`, and the sidebar label on every page.
- **Runs:** captures connect to the packaged SimWorld server on 9001 (one client only; ask the simcity session first), with no NPCs and `StopAgent` before closing. Model runs go through the GPU queue.

## World-model text prompts (working tree on `main`, uncommitted)

- **Status:** Prompts for the sky-bridge sim-to-real run are written (item 3 of the realism plan); none have been run yet. Three variants (faithful photoreal, light, phone video), with notes on what each sentence carries.
- **Owns:** `city/wm/prompts/` (`bridge.json`, `bridge_source.py`, `build.py`, `README.md`).
- **Reads only:** `city/world.json`, `city/VIBE.md`, `city/moodboard/`, `out/filter_test/test_clip/`, `models/*/assets`. No GPU and no model runs.

## Cosmos Sim-Transfer control videos (working tree on `main`, uncommitted)

- **Status:** Done for the bridge shot (first 150 frames of `out/filter_test/test_clip/`). No model runs; another agent is porting the model.
- **Owns:** `city/wm/controls.py`, `out/city_wm/bridge/controls/`.
- **Reads only:** `out/filter_test/test_clip/`, `filter_test/scripts/controls.py` (its depth logic is reused, not imported), `models/Cosmos3-Nano-Sim-Transfer/`.
- **Runs:** `.venv/bin/python -I city/wm/controls.py [--frames N --clip DIR --out DIR]`, CPU only, about a minute. Never connects to 9001.

## Sim-Transfer on the Mac (working tree on `main`, uncommitted)

- **Status:** Finished 2026-11-06. It reproduces NVIDIA's example1, and it produced the 5 s bridge run (`out/city_wm/bridge/final/`). The single-control benchmark was cancelled because the user wants 4-control runs only; it's scripted in `out/sim_transfer/bench.py`. `world_transfer.py` runs NVIDIA's Cosmos3-Nano-Sim-Transfer (causal, 4-step, one control) in MLX from `models/Cosmos3-Nano-Sim-Transfer`. Deviations from NVIDIA's reference are in `docs/SIM_TRANSFER_MLX.md`. It doesn't touch `world_filter.py` or `world_model.py`.
- **Owns:** `world_transfer.py`, `docs/SIM_TRANSFER_MLX.md`, `out/sim_transfer/`, `world_stream.py` (one continuous Sim-Transfer rollout fed step by step), `city/agents/live_wm.py` + `run_wm_life.sh` (a life lived inside the world model: the agent sees only painted frames), `out/world_stream/`.
- **Queued 2026-11-07:** `wmstream_smoke` (p30), `wmlife_5min` (p31), and the two-agent `wmlunch_5min` (p32, code from the lunch helper: `city/agents/lunch_wm.py`, `world_stream_multi.py`).
- **Runs:** in the `~/cosmos3/cosmos3-mlx` venv under `ram_share.py hold --name sim_transfer*`. Call it with `world_transfer.transfer_video(prompt, {"depth": path}, output, size=..., frames=...)`. Every output has an `<output>.json` sidecar that names the model.

## Multi-control Cosmos transfer (working tree on `main`, uncommitted)

- **Status:** The user chose Variant A, `world_transfer_multi.py` (Sim-Transfer with weighted controls), for the bridge clip on 2026-11-07; Variant B (`world_multicontrol_base.py`) stays as a reference and isn't run. The full 150-frame A run with all four controls is in `out/wm_multicontrol/a4_full/`. Results: `wm_multicontrol/REPORT.md`.
- **Default (owner's rule, 2026-11-08):** every sim-driven world-model run uses Variant A with all four controls (blur, seg, depth, edge at 0.25 each) unless the owner explicitly says otherwise. Agents must decide from the highest-quality painted image available (closed loop), so a record-then-paint run doesn't count as the quality test. If a run lowers size or precision to fit memory, say so in its report and sidecar.
- **8-bit weights (measured 2026-11-08):** the fastest setting tested for Variant A, and the one to use unless told otherwise. On the 150-frame bridge clip at 832x480 with `--quantize 8`: 1782 s and 19.9 GB peak, against 3518 s and 24.2 GB for bf16 (`a4_full`, which may have shared the Mac), and the owner found the two basically the same by eye (`out/wm_multicontrol/a4_8bit_blind/`). 4-bit hasn't been tried. That's one clip, with recorded controls and one stream; two live streams are still untested.
- **Owns:** `wm_multicontrol/`, `world_transfer_multi.py`, `world_multicontrol_base.py`, `tests/test_wm_multicontrol*.py`, `out/wm_multicontrol/`.
- **Touched:** `life/world_runs.py`: a "Multi-control transfer" group on the Model runs page (`multicontrol_entries`, read from each video's sidecar and `out/wm_multicontrol/notes.json`). Tested in `tests/test_wm_multicontrol_runs.py`; the existing page tests still pass.
- **Reads only:** `world_transfer.py` and `world_filter.py` (imported, never edited; proposed hooks go in `wm_multicontrol/HANDOFF.md`), `out/city_wm/bridge/controls/`, `city/wm/prompts/bridge.json`, `models/Cosmos3-Nano*`.
- **Runs:** everything is prefixed `wmmc_`, queued via `gpu.py` with a `ram_share.py hold`. Outputs go to `out/wm_multicontrol/<run>/` with a JSON sidecar.

## Unreal realism pilot around the bridge shot (working tree on `main`, uncommitted)

- **Status:** Step 0 (2026-11-06): own editor-game instance on port 9003 (minimized, `ram_share` claim `realism_9003`, 10 GB), city built, "before" replay of the bridge walk recording. Brief: `city/realism/BRIEF.md`. Tuning for the world model's blur control at 832x480 (lighting, colour values, silhouettes before fine texture).
- **Owns:** `city/realism/`, `out/city_realism/`, and (once agreed) a pilot-only material/foliage path gated to the bridge area in `mac_server/` (`/Game/Realism/`, flagged actors only; the rest of the city must render unchanged).
- **Reads only:** `out/filter_test/test_clip/` (poses), `city/world.json`, `city/wm/prompts/` (prompt changes go to the world-model session, `jaycewalzer-00`, not edited here).
- **Runs:** only on port 9003, never 9001 or `mac_server/Packaged/`, no `build.sh package`. `city/realism/replay_bridge.py --port 9003 --label X` re-renders the walk from the recorded poses (rgb + depth + seg).

## Varied city: building kinds + re-plan (working tree on `main`, uncommitted, started 2026-11-07)

- **Status:** overnight multi-agent run (user's request): replace the seven cloned courtyard blocks with a mix of moodboard and mid-century modern buildings. Commons civic buildings stay as the quality bar. The realism pilot is paused meanwhile (its material code is in, flag off).
- **Owns:** `city/ue/kinds/` (README.md is the guide, CATALOG.md the shared kind list; one module per author), `city/world_varied.json` + `city/ue/plan_varied/` (planner), `out/city_kinds/`, and `SWCityKit` (`mac_server/.../City/SWCityKit.cpp`: generic Python-authored geometry, so kinds need no C++).
- **Reads only:** `city/world.json` (NOT edited; swapping the varied plan into the life sim is the user's call), `city/moodboard/`, `city/VIBE.md`.
- **Runs:** editor on port 9003 only (`ram_share` claim `city_kinds_9003`); every use goes through the lock `out/city_kinds/.editor.lock` (`python -m city.ue.kinds.preview` / `.locked`); `city.ue.kinds.watchdog` restarts it on the Metal leak. Never 9001 or `mac_server/Packaged/`.
- **Now (2026-11-07 22:10):** idle. The 9003 editor was force-quit by the user and is NOT running; the watchdog is stopped and no claim is held. Final layout r7 is in `city/world_varied.json` (renders `out/city_kinds/planner/r7/`); a 1 s world-model aerial of it is in `out/city_wm/varied_aerial/` (Variant A, done). Relaunching 9003 is only for when the user wants to view or change the city again.

## Experiment 1 homeostatic RL (`feat/exp1-homeostatic-rl`)

- **Status:** Phase 1 (reward wiring, balance, leak and tabular tests) committed on the branch. Phase 2 (Qwen + LoRA sleep loop) and 3 (panel page) not started. Waiting on the owner's call on run_main's need change, which the deficit-only cap makes unbalanceable.
- **Worktree:** `.claude/worktrees/exp1`, branched from `origin/main` (the hourly snapshot, identical to this checkout's `life/` at the time).
- **Owns:** `exp1/`, `tests/test_exp1.py`, `docs/homeostatic_rl_map.md`, and (later) a new panel page. `/training` and `homeostatic/` stay untouched.
- **Reads only:** `life/scenario.py` (imported, never edited; the wellness night still resumes from it), `life/seed.py`.
- **Runs:** CPU only so far. Qwen runs will go through the GPU queue, prefixed `exp1_`.

## Two agents at lunch inside the world model (working tree on `main`, uncommitted, started 2026-11-07)

- **Status:** Built and dry-tested (no GPU, no server, no models); not run or queued yet. Mara and her neighbour Iris (both Qwen3-VL-8B 4-bit, loaded once) meet at The Kettle for lunch and talk, each seeing only its own Cosmos3-Nano-Sim-Transfer film.
- **Owns:** `city/agents/lunch_wm.py`, `city/agents/run_wm_lunch.sh`, `world_stream_multi.py`, `tests/test_city_lunch.py`, `out/city_agents/*_lunch/`.
- **Reads only:** `city/agents/live.py`, `live_wm.py`, `world_stream.py`, `world_transfer*.py`, `city/wm/controls.py`, `npcs.json` (the barista's lunch line is added in memory, not in the file), the wm-agent-loop adapter (subclassed as `TwoBodySim`, never edited), `mac_server/docs`.
- **Runs:** through the GPU queue as `wmlunch_*`, under `ram_share.py hold --name wmlunch_agents --gb 24`, on the packaged server at 9001 (one client). Dry test: `.venv/bin/python -m unittest tests/test_city_lunch.py`.

## Realistic bodies for the city agents (working tree on `main`, uncommitted, started 2026-11-07)

- **Status:** Overnight demo done (2026-11-08 06:3x). Watch `out/bodies/demo/20261108/demo.mp4` (real Cosmos run `wmbodies_demo`; world-model panels to 0:52, then sim renders, because the painted films break into a mosaic after ~52 s; jaycewalzer-00 is diagnosing) and `demo_sim_only.mp4` (fake world model). README `out/bodies/demo/README.md`; "Bodies demo" group on the Model runs page. `mac_server/Packaged` IS NOW the bodies build (old one in `Packaged_prebodies/`). Wrapper `city/bodies/demo_lunch.py` (lunch_wm.py unchanged), cut `city/bodies/demo_cut.py`. Touched outside our area (told the owner): one line in `world_stream.py` (first-push trim) + a test in `tests/test_world_stream.py`; `life/world_runs.py` (additive group) + `tests/test_bodies_demo_runs.py`. Bodies still clay (no MetaHuman Core Data). Log: `city/bodies/LOG.md`.
- **Owns:** `city/bodies/`, `out/bodies/`, `mac_server/Config/Bodies.json`, `mac_server/Content/Characters/`, body code in `SWCharacterBase`/`SWHumanoid`/`SWPedestrian`/`SWSettings`, `mac_server/tests/test_bodies*.py`, `tests/test_city_bodies.py`, `mac_server/Packaged_bodies/`.
- **Touches (additive only):** `city/agents/npcs.json` (`body` fields), `city/agents/live.py` (`--body`, `SetBody` after spawn), the mock server's command list, SimCV's `OnAnnotationCapture` hook and object-mask material choice (`mac_server/Plugins/SimCV`), `mac_server/Content/Characters/TestParts`.
- **Runs:** editor on port 9004 only (`ram_share` claim `bodies_9004`); never 9001, 9003 or `mac_server/Packaged/`. Model runs via the GPU queue as `bodies_*`.
