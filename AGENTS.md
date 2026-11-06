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
- **Backups:** snapshots the uncommitted `main` tree to `refs/backup/main-wip` without touching the index or branches.

## Feel-then-decide agent (working tree on `main`, uncommitted)

- **Status:** Replaces the teacher idea, which the user dropped. `mind/feeling.py` wraps any runtime agent to say what changed, update a slowly moving feeling from that, and decide only at decision points, without editing `runtime/`. Open questions are in `mind/OPEN_DECISIONS.md`.
- **Owns:** `mind/`, `tests/test_mind.py`.
- **Runs:** `mind.run` and `mind.check`, writing to `out/mind/`. Real Qwen goes through the GPU queue at priority 45.
- **For viewers:** `out/mind/<run>/feelings.jsonl` is written as a run happens, and `mind.feeling.timeline(path)` turns it into one entry per tick. Row fields are at the top of `mind/feeling.py`.
- **Trained models:** `mind.run --weights <run>/fused`. `mind.check --replay --weights ...` compares it with a base run on identical moments.

## GPU queue view (working tree on `main`, uncommitted)

- **Status:** The dev panel's `/queue` page: a 12-hour timeline, GPU readings, the newest picture from each job's `--out` folder, and controls for waiting jobs (priority, Mac or PACE, cancel) plus where new jobs go. Every change goes through `gpu.py`'s own commands, and only this panel's own page can make one.
- **Owns:** `life/gpu_queue.py`, `life/static/queue.*`, `tests/test_life_gpu_queue.py`. The queue itself stays with overnight coordination.

## Wellness center night and staged jobs (working tree on `main`, uncommitted)

- **Status:** Started 2026-11-05 19:33, writing to `out/scenario/2026-11-05-193212`. The spec's calibration check fails on its own payoff table; reported, not fixed.
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
