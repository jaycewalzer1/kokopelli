# Agents working in this repo

Standing rules first, then one line per live area. Status, results and dates go in each area's own notes or `out/ops/MORNING.md`, not here. Add or update your area's line when you take one.

## Layout (since the 2026-11-10 reorganization)

- `kokopelli/` is the library, one package: `wm/` (world-model runners, video helpers, `controls/`), `loop/` (the agent loop, was `runtime/`), `mind/`, `agents/` (was `city/agents/`), `life/` (generator, store, panel), `ops/` (queue, memory guard, `ram_share`, `cloud/`), `settings.py`.
- `experiments/` holds `commons/`, `benchmarks/`, `exp1/`, `homeostatic/`, `filter_test/`, `wm_multicontrol/`. `tools/` holds hand-run scripts (`city_build/`, `bodies/`, `realism/`, `moodboard/`, `fable/`, `pace/`, `reorg/`). `data/` holds tracked inputs (`city/world.json`) and the moodboard pictures. `vendor/` is third-party code.
- Launch with `python -m kokopelli.<package>.<module>` from the repo root. `ops/gpu.py` and `ops/memguard.py` at the root are stand-ins for `kokopelli/ops/`. What moved where: `tools/reorg/migrate.py`; log: `docs/log/reorg/PROGRESS.md`.

## Rules

- **One task per session.** Keep sessions and workers short; hand off in a file instead of keeping a long session open.
- **Work in your own git worktree,** never by switching branches in the shared checkout. Name everything you launch with your area's prefix.
- **GPU queue for every model job:** `python3 kokopelli/ops/gpu.py run --name NAME --priority N --max-hours H --cwd DIR --about "WHAT AND WHY" --output PATH -- CMD` (absolute `/Users/jaycewalzer/Desktop/kokopelli/kokopelli/ops/gpu.py` from elsewhere). `--about` (at most 400 characters) and at least one `--output` (relative to `--cwd`) are required, or the job isn't queued. Lower priority numbers go first. `--gb N` holds a job until `ram_share.py` says N GB is free (use it for jobs that aren't `Guard`-polite). `gpu.py status` shows the line and why each job waits.
- **Stopping jobs:** a started job belongs to a keeper process, so killing `gpu.py run` doesn't stop it. Use `gpu.py stop --name NAME` or Stop job in the panel's drawer. Never kill model processes by hand or with a `pkill` pattern. A Python process over 8 GB that no ticket owns blocks the queue as an outside job.
- **Memory outside the queue:** heavy work the queue can't see claims memory with `python3 kokopelli/ops/ram_share.py hold --name NAME --gb N -- CMD`, or `kokopelli/ops/ram_share.py claim --name NAME --gb N --pid PID` for a running process.
- **World-model default (owner's rule):** every sim-driven world-model run uses Variant A (`kokopelli/wm/world_transfer_multi.py`, Cosmos3-Nano-Sim-Transfer) with all four controls (blur, seg, depth, edge at 0.25 each) and 8-bit weights (`--quantize 8`), unless the owner says otherwise. If a run lowers size or precision, say so in its report and sidecar. Every output has a JSON sidecar naming the model and weights.
- **Quality tests are closed-loop:** agents decide from the highest-quality painted image available. A record-then-paint run doesn't count, and the fake world model (`--fake-wm`) is never presented as the real one.
- **Ports:** 9001 is the packaged server (`mac_server/Packaged/`, one client at a time; ask before connecting). 9003 and 9004 are editor instances (city kinds/realism and bodies). 8765 is the dev panel (`kokopelli/life/panel.py`). Don't use another area's port.
- **Mouse:** moving the mouse during a packaged-server run turns camera 0. Ask the owner to step away first.
- **Re-planning the city:** `data/city/world.json` is the varied plan; the identical `world_varied.json` was removed. `tools/city_build/plan_varied/plan.py` still reads `world.json` as the pre-varied base and writes `data/city/world_varied.json` beside it, so put the pre-varied version (git `4cc0311`, then at `city/world.json`) in place before re-planning, and never let a plan overwrite `world.json` unasked.
- **Benchmarks:** `experiments.benchmarks.run` isn't recognized as a model job by the queue; never start it outside the queue.
- **Skills:** `.claude/skills/` holds the repeated workflows (`sim-capture`, `closed-loop-run`, `paint-clip`).

## Areas (owns / runs as / port)

| Area | Owns | Prefix, port, notes |
|---|---|---|
| World-model agent loop | `kokopelli/loop/` (not the SimWorld files) | `wmloop_`; asks go in `kokopelli/loop/HANDOFF.md` |
| SimWorld adapter | `kokopelli/loop/physics.py`, `kokopelli/loop/adapters/simworld*`, `kokopelli/loop/tests/test_simworld*`, `kokopelli/loop/SIMWORLD.md` | fake UnrealCV server in tests; reads `simworld/` only |
| Benchmarks | `experiments/benchmarks/`, `tools/pace/evals/` | `evals_`, queue p40, turns of 30 min or less; `experiments/benchmarks/PREREG.md` |
| Queue, ops, morning report | `kokopelli/ops/`, `out/ops/` | report `out/ops/MORNING.md`; job logs `out/ops/job_logs/` |
| GPU queue page | `kokopelli/life/gpu_queue.py`, `kokopelli/life/static/queue.*` | panel `/queue`; changes go through `gpu.py` commands |
| Feel-then-decide mind | `kokopelli/mind/`, `tests/test_mind.py` | queue p45; `kokopelli/mind/OPEN_DECISIONS.md` |
| Scenario night, staged jobs, memory sharing | `kokopelli/life/scenario*.py`, `kokopelli/life/staged.py`, `kokopelli/ops/ram_share.py`, `SCENARIO_*`/`STAGED_JOBS` settings | queue p60, polite (yields with exit 75) |
| PACE backend | `kokopelli/ops/cloud/` | needs `kokopelli/ops/cloud/pace.json` and SSH (`kokopelli/ops/cloud/README.md`); `gpu.py` imports it |
| Homeostatic training, dev panel | `experiments/homeostatic/`, `HOMEOSTATIC_*` settings, `kokopelli/life/architecture.py`, `kokopelli/life/static/{training,architecture}.*` | queue p50; panel on 8765 |
| Edge filter | `kokopelli/wm/edges.py`, `kokopelli/wm/world_filter.py`, `filter_video` in `kokopelli/wm/world_model.py` | `edge_filter_*` |
| Agent view page | `kokopelli/life/city_live.py`, `kokopelli/life/static/city-live.*`, `kokopelli/life/static/city-draw.js` | panel `/city-live`; read-only on `out/city_agents/` |
| Sim-to-real filter test, Model runs page | `experiments/filter_test/`, `kokopelli/life/world_runs.py`, `kokopelli/life/static/worlds.*` | captures on 9001 with no NPCs, `StopAgent` before closing |
| World-model prompts | `kokopelli/wm/controls/prompts/` | no GPU |
| Control videos | `kokopelli/wm/controls/controls.py`, `out/city_wm/bridge/controls/` | CPU only, never 9001 |
| Sim-Transfer on the Mac | `kokopelli/wm/world_transfer.py`, `kokopelli/wm/world_stream.py`, `kokopelli/agents/live_wm.py`, `run_wm_life.sh`, `docs/SIM_TRANSFER_MLX.md` | `~/cosmos3/cosmos3-mlx` venv under `ram_share.py hold` |
| Multi-control transfer | `experiments/wm_multicontrol/`, `kokopelli/wm/world_transfer_multi.py`, `kokopelli/wm/world_multicontrol_base.py` (Variant B, reference only) | `wmmc_`; results `experiments/wm_multicontrol/REPORT.md` |
| Unreal realism pilot | `tools/realism/` | 9003 only, claim `realism_9003`; `tools/realism/BRIEF.md` |
| Varied city, building kinds | `tools/city_build/kinds/`, `tools/city_build/plan_varied/`, `data/city/world.json`, `SWCityKit` | 9003 only, claim `city_kinds_9003`, lock `out/city_kinds/.editor.lock` via `python -m tools.city_build.kinds.preview`/`.locked`; `city.ue.kinds.watchdog` |
| Experiment 1 homeostatic RL | `experiments/exp1/`, `tests/test_exp1.py`, `docs/homeostatic_rl_map.md` | `exp1_` |
| Two agents at lunch | `kokopelli/agents/lunch_wm.py`, `run_wm_lunch.sh`, `kokopelli/wm/world_stream_multi.py` | `wmlunch_`, 9001, `ram_share.py hold --name wmlunch_agents --gb 24` |
| Realistic bodies | `tools/bodies/`, `mac_server/Config/Bodies.json`, body code in `SWCharacterBase`/`SWHumanoid`/`SWPedestrian`/`SWSettings` | `bodies_`, 9004 only, claim `bodies_9004`; log `tools/bodies/LOG.md` |

## Memory rules (36 GB Mac)

Five full test runs at once (18 GB each) ran the Mac out of memory and swap on 2026-11-09 and it panicked. Since then:

- Run tests with `make test-all` (it claims its memory and waits its turn). It runs the tree with pytest: `.venv` with `-m "not py310"` (`main`, then `experiments` for benchmarks and commons in their own process), `simworld/.venv` with `-m py310`, one summary line each; `MAC=1` adds mac_server. For some files or tests, pass them to the same script: `tools/fable/test_all.sh tests/ops` or `tools/fable/test_all.sh tests/life/test_life_store.py`. Never run `unittest` or `pytest` bare.
- Markers (`conftest.py`): `model` tests load Qwen or Cosmos and are skipped unless `RUN_MODEL_TESTS` is set; `slow` ones unless `RUN_LONG_TESTS` is set. Only set either for a job queued through `kokopelli/ops/gpu.py`.
- Anything else heavy (whole-repo linters, `uv`, `npx`, builds) also goes through `kokopelli/ops/memguard.py run` with its peak in `--gb`. Model jobs go through `kokopelli/ops/gpu.py run --gb`.
- Exit 75 from the guard means memory ran short. Wait and run it again later; don't retry in a loop and don't start a second copy.
- Don't put a heavy command in the background and then start another. At most two guarded commands run at once.
- `python3 kokopelli/ops/memguard.py status` prints memory, swap and who holds a claim. The overnight watchdog is `kokopelli/ops/memguard.py watch`.
- Measured peaks: the whole `make test-all` 1.5 GB (2026-11-10; the `main` run is the largest; the real-model tests behind `RUN_MODEL_TESTS=1` peak at 17.3), `experiments` alone 0.7.
