# Agents working in this repo

Standing rules first, then one line per live area. Status, results and dates go in each area's own notes or `out/ops/MORNING.md`, not here. Add or update your area's line when you take one.

## Rules

- **One task per session.** Keep sessions and workers short; hand off in a file instead of keeping a long session open.
- **Work in your own git worktree,** never by switching branches in the shared checkout. Name everything you launch with your area's prefix.
- **GPU queue for every model job:** `python3 ops/gpu.py run --name NAME --priority N --max-hours H --cwd DIR --about "WHAT AND WHY" --output PATH -- CMD` (absolute `/Users/jaycewalzer/Desktop/kokopelli/ops/gpu.py` from elsewhere). `--about` (at most 400 characters) and at least one `--output` (relative to `--cwd`) are required, or the job isn't queued. Lower priority numbers go first. `--gb N` holds a job until `ram_share.py` says N GB is free (use it for jobs that aren't `Guard`-polite). `gpu.py status` shows the line and why each job waits.
- **Stopping jobs:** a started job belongs to a keeper process, so killing `gpu.py run` doesn't stop it. Use `gpu.py stop --name NAME` or Stop job in the panel's drawer. Never kill model processes by hand or with a `pkill` pattern. A Python process over 8 GB that no ticket owns blocks the queue as an outside job.
- **Memory outside the queue:** heavy work the queue can't see claims memory with `python3 ram_share.py hold --name NAME --gb N -- CMD`, or `ram_share.py claim --name NAME --gb N --pid PID` for a running process.
- **World-model default (owner's rule):** every sim-driven world-model run uses Variant A (`world_transfer_multi.py`, Cosmos3-Nano-Sim-Transfer) with all four controls (blur, seg, depth, edge at 0.25 each) and 8-bit weights (`--quantize 8`), unless the owner says otherwise. If a run lowers size or precision, say so in its report and sidecar. Every output has a JSON sidecar naming the model and weights.
- **Quality tests are closed-loop:** agents decide from the highest-quality painted image available. A record-then-paint run doesn't count, and the fake world model (`--fake-wm`) is never presented as the real one.
- **Ports:** 9001 is the packaged server (`mac_server/Packaged/`, one client at a time; ask before connecting). 9003 and 9004 are editor instances (city kinds/realism and bodies). 8765 is the dev panel (`life/panel.py`). Don't use another area's port.
- **Mouse:** moving the mouse during a packaged-server run turns camera 0. Ask the owner to step away first.
- **Re-planning the city:** `city/world.json` IS the varied plan (identical to `city/world_varied.json`). `city/ue/plan_varied/plan.py` and `check.py` still treat `city/world.json` as the pre-varied base, so restore that version (git `4cc0311`) before re-planning.
- **Benchmarks:** `benchmarks.run` isn't recognized as a model job by the queue; never start it outside the queue.
- **Skills:** `.claude/skills/` holds the repeated workflows (`sim-capture`, `closed-loop-run`, `paint-clip`).

## Areas (owns / runs as / port)

| Area | Owns | Prefix, port, notes |
|---|---|---|
| World-model agent loop | `runtime/` (not the SimWorld files) | `wmloop_`; asks go in `runtime/HANDOFF.md` |
| SimWorld adapter | `runtime/physics.py`, `runtime/adapters/simworld*`, `runtime/tests/test_simworld*`, `runtime/SIMWORLD.md` | fake UnrealCV server in tests; reads `simworld/` only |
| Benchmarks | `benchmarks/`, `scripts/pace/evals/` | `evals_`, queue p40, turns of 30 min or less; `benchmarks/PREREG.md` |
| Queue, ops, morning report | `ops/`, `out/ops/` | report `out/ops/MORNING.md`; job logs `out/ops/job_logs/` |
| GPU queue page | `life/gpu_queue.py`, `life/static/queue.*` | panel `/queue`; changes go through `gpu.py` commands |
| Feel-then-decide mind | `mind/`, `tests/test_mind.py` | queue p45; `mind/OPEN_DECISIONS.md` |
| Scenario night, staged jobs, `ram_share.py` | `life/scenario*.py`, `life/staged.py`, `ram_share.py`, `SCENARIO_*`/`STAGED_JOBS` settings | queue p60, polite (yields with exit 75) |
| PACE backend | `cloud/` | needs `cloud/pace.json` and SSH (`cloud/README.md`); `gpu.py` imports it |
| Homeostatic training, dev panel | `homeostatic/`, `HOMEOSTATIC_*` settings, `life/architecture.py`, `life/static/{training,architecture}.*` | queue p50; panel on 8765 |
| Edge filter | `edges.py`, `world_filter.py`, `filter_video` in `world_model.py` | `edge_filter_*` |
| Agent view page | `life/city_live.py`, `life/static/city-live.*`, `life/static/city-draw.js` | panel `/city-live`; read-only on `out/city_agents/` |
| Sim-to-real filter test, Model runs page | `filter_test/`, `life/world_runs.py`, `life/static/worlds.*` | captures on 9001 with no NPCs, `StopAgent` before closing |
| World-model prompts | `city/wm/prompts/` | no GPU |
| Control videos | `city/wm/controls.py`, `out/city_wm/bridge/controls/` | CPU only, never 9001 |
| Sim-Transfer on the Mac | `world_transfer.py`, `world_stream.py`, `city/agents/live_wm.py`, `run_wm_life.sh`, `docs/SIM_TRANSFER_MLX.md` | `~/cosmos3/cosmos3-mlx` venv under `ram_share.py hold` |
| Multi-control transfer | `wm_multicontrol/`, `world_transfer_multi.py`, `world_multicontrol_base.py` (Variant B, reference only) | `wmmc_`; results `wm_multicontrol/REPORT.md` |
| Unreal realism pilot | `city/realism/` | 9003 only, claim `realism_9003`; `city/realism/BRIEF.md` |
| Varied city, building kinds | `city/ue/kinds/`, `city/ue/plan_varied/`, `city/world_varied.json`, `SWCityKit` | 9003 only, claim `city_kinds_9003`, lock `out/city_kinds/.editor.lock` via `python -m city.ue.kinds.preview`/`.locked`; `city.ue.kinds.watchdog` |
| Experiment 1 homeostatic RL | `exp1/`, `tests/test_exp1.py`, `docs/homeostatic_rl_map.md` | `exp1_` |
| Two agents at lunch | `city/agents/lunch_wm.py`, `run_wm_lunch.sh`, `world_stream_multi.py` | `wmlunch_`, 9001, `ram_share.py hold --name wmlunch_agents --gb 24` |
| Realistic bodies | `city/bodies/`, `mac_server/Config/Bodies.json`, body code in `SWCharacterBase`/`SWHumanoid`/`SWPedestrian`/`SWSettings` | `bodies_`, 9004 only, claim `bodies_9004`; log `city/bodies/LOG.md` |

## Memory rules (36 GB Mac)

Five full test runs at once (18 GB each) ran the Mac out of memory and swap on 2026-11-09 and it panicked. Since then:

- Run tests with `make test-all` (it claims 20 GB and waits its turn), or one module with `python3 ops/memguard.py run --name <what> --gb 2 -- .venv/bin/python -m unittest tests.test_x`. Never run `unittest` or `pytest` bare.
- Anything else heavy (whole-repo linters, `uv`, `npx`, builds) also goes through `ops/memguard.py run` with its peak in `--gb`. Model jobs go through `ops/gpu.py run --gb`.
- Exit 75 from the guard means memory ran short. Wait and run it again later; don't retry in a loop and don't start a second copy.
- Don't put a heavy command in the background and then start another. At most two guarded commands run at once.
- `python3 ops/memguard.py status` prints memory, swap and who holds a claim. The overnight watchdog is `ops/memguard.py watch`.
- Measured peaks: `tests` 1.3 GB (18.3 before P1-M; the real-model tests behind `RUN_MODEL_TESTS=1` peak at 17.3), `runtime` 0.7, `simworld` 0.3, `ops` 0.1, `benchmarks` 0.7.
