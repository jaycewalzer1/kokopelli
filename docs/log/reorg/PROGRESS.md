# Reorg progress

One section per phase, appended when the phase is done (see `docs/REORG_EXECUTION.md` section 4).
Each records the branch or merge commit, test counts, what was skipped or is owed, and anything
surprising. Failures and skips are written down as plainly as successes.

## Phase 0: safety net

Branch `reorg/0-safety-net` from `main` at `e47b5c9` (tag `pre-reorg`, made by the orchestrator).

### Baseline tests

`make test-all` on main (orchestrator's run before the branch):

| suite | result |
|---|---|
| tests | 600 ran, OK (skipped 10, expected failures 2) |
| runtime | 100 ran, OK |
| simworld | 197 ran, OK |
| ops | 35 ran, OK |
| benchmarks | 198 ran, OK (skipped 1) |
| commons | 62 passed |

memguard peak 1.3 of 2.0 GB, 434 s.

`MAC=1 make test-all` on the branch (2026-11-10, before any phase 0 commit, so the same code as main):

| suite | result |
|---|---|
| tests | 600 ran, OK (skipped 10, expected failures 2), 237 s |
| runtime | 100 ran, OK, 100 s |
| simworld | 197 ran, OK, 47 s |
| ops | 35 ran, OK, 15 s |
| benchmarks | 198 ran, OK (skipped 1), 25 s |
| commons | 62 passed, 1 s |
| mac_server | 26 failed, 215 passed, 16 skipped, 148 s (reported "ok": under the 29 known failures) |

memguard peak 1.3 of 2.0 GB, 573 s. The summary line `test_all.sh` prints for mac_server cuts off
the counts, so they come from one extra `VERBOSE=1 scripts/fable/test_all.sh mac_server` run
(same result, 150 s, peak 0.2 GB).

mac_server has **26** failures, not the 29 the brief and `test_all.sh` expect. All 26 are in
`tests/test_conformance.py` against the mock server: collision_counts, enter_exit_vehicle, gestures,
heavy_box_pick_up, humanoid_falls_to_ground, humanoid_move_forward_and_stop, humanoid_rotate (2),
humanoid_set_follow_path, humanoid_step_forward (2), pedestrian_move_rotate_stop,
pedestrian_waypoints, pick_up_and_drop, robot_dog, scooter_cycle, sit_stand_return_string_bools,
sun_intensity_changes_lit_image, traffic_controller_smoke, traffic_signal_states,
ue_manager_reports_humanoid, ue_manager_update_objects_sees_late_spawns,
vehicle_batch_state_via_manager, vehicle_throttle_brake, vehicle_u_turn, weather_roundtrip.
Compare later phases against this list of 26.

### Lint baseline

- `uvx ruff@0.11.4 check .` is clean. 0.11.4 is the version `.pre-commit-config.yaml` pins. Newer
  ruff (0.17) adds 79 UP045 findings; they are not part of the baseline. There is no `.venv/bin/ruff`.
- `uvx pre-commit run --all-files` (through memguard) does **not** pass on main as it stands:
  - `shellcheck` (strict hook) reports `experiments/commons/overnight.sh` (SC2034),
    `scripts/fable/p4_c_bits.sh`, `scripts/fable/p4_queue_all.sh`, `scripts/fable/p4_queue_profile.sh`
    (SC2086, SC2164). These scripts are not in the hook's baseline list.
  - `end-of-file-fixer` rewrites `runs/commons/lint_report.json`, `metrics.json`, `spend.json`
    (no final newline). The rewrite was reverted with `git checkout`; nothing was changed.
  So "pre-commit changes nothing" holds only after these are fixed or baselined (phase 8 at the latest).

### Smoke check

`tools/smoke_entrypoints.sh` runs every entry point found with
`git grep -l '__name__ == "__main__"'` (minus tests, `simworld/`, `mac_server/`,
`wm_multicontrol/upstream/`), the 12 root stand-ins and 26 shell launchers. The table at its top
tags each with its interpreter. Results on the branch:

| interpreter | ok | failed | skipped |
|---|---|---|---|
| `.venv/bin/python` (3.12.5) | 104 | 0 | 1 |
| `simworld/.venv/bin/python` (3.10.22) | 30 | 0 | 1 |
| `~/cosmos3/cosmos3-mlx/.venv/bin/python` (3.12.5) | 17 | 0 | 1 |
| system `python3` (3.15.2, only the stdlib tools tagged `all`) | 4 | 0 | 1 |

Skip list: `filter_test/scripts/run_sd.py` runs in its own `filter_test/.venv` (torch, diffusers),
which is none of the three.

Not loaded: no model and no GPU queue call. `--help` exits in argparse; the import checks only import.

### Import graph

`tools/reorg/import_graph.py` writes `docs/log/imports-before.txt`. It shows the wrong-way edges the
plan names: `life -> homeostatic` (3 files: `architecture.py`, `panel.py`, `pipeline.py`) and the cycle
`mind <-> runtime` (`mind/feeling.py` and `mind/run.py` import runtime; `runtime/run.py` imports mind).

It also shows two cycles and two edges the plan does not name:
- `core <-> runtime`: `core/video_check.py` imports `runtime.drift` inside a function.
- `exp1 <-> life`: `life/panel.py` imports `exp1.panel`.
- `life -> cloud` (`life/gpu_queue.py`) and `ops -> cloud` (`ops/gpu.py`, inside a function).

### Owed / skipped

- Nothing skipped in phase 0 apart from the `run_sd.py` smoke entry above.
