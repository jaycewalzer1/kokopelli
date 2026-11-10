## P2-C Update importers to `core.*` (2026-11-09)

**What changed.** 67 Python files outside root switched from root-module imports to `core.*` (88 import lines; 70 files changed in all), one directory per commit with tests run after each:
- `from X import ...` became `from core.X import ...`; `import X` / `import X as Y` became `from core import X` / `from core import X as Y`, so every local name (`llm_model`, `wt`, `ram_share`...) stays the same and the code below the import is untouched.
- life/ (16 files, 3e4c6bf): architecture, city, city_live, engine, gpu_queue, llm_generator, memory, moodboard, overnight, panel, pipeline, resolver, scenario_night, staged, windows, world_runs.
- homeostatic/ (9), mind/run.py, exp1/run.py, exp1/diagnose_d2.py, benchmarks/backends/llm_model_backend.py, benchmarks/tests/test_before_after.py, filter_test/scripts/run_cosmos.py (26ef8e5).
- runtime/ (8: adapters/cosmos, adapters/qwen, check_video, frames, probe_decisions, run, stitch, tests/test_full_run_tools) and city/ (6: agents/live, live_wm, lunch_parts, lunch_wm, bodies/demo_lunch, wm/run_bridge_final) (9cdf873).
- tests/ (22 files, dc62978).
- `wm_multicontrol/run_a.sh` runs `"$PY" -m core.world_transfer` / `-m core.world_transfer_multi` with `PYTHONPATH="$K:$R"`; README Use section imports `core.*` (ad8edf0).

**Patching kept on the real module.**
- `runtime/tests/test_full_run_tools.py` stubbed `sys.modules["world_model"]`; the cosmos adapter now imports `core.world_model`, so the stub key is now `"core.world_model"`. Left as it was, the test would have called the real `_generate`.
- `tests/test_life_engine.py` mock-mode check asserted `'llm_model'` is never loaded; code now loads `core.llm_model`, so the set also names `'core.llm_model'` (otherwise the check would pass vacuously).
- All other patches are `mock.patch.object(<module object>, ...)`; because P2-B's root files alias `sys.modules`, the object is `core.X` either way. No `mock.patch("settings.X")`-style string targets exist outside `core/`.

**Panel reload.** `life/panel.py:497` watches `ROOT / "core" / "settings.py"` instead of the root `settings.py` (now a shim that never changes), so editing settings restarts the panel again. `life/architecture.py` node `files` lists name `core/{settings,world_model,blend,llm_model}.py` so they stay valid when shims go; `tests/test_life_architecture.py` stale-claims scan now also reads `core/*.py` (the code moved there, so the scan had silently stopped covering it).

**Checks.**
- Acceptance grep (settings/world_*/llm_model/blend/edges): no hits outside `core/`. Two remaining hits are docstring usage examples at `core/world_stream.py:10` and `core/world_stream_multi.py:9` (`from world_stream import WorldStream`); `core/` is not this package's to edit. P2-F2 or the core owner should update them.
- `bash -n` and `sh -n` on `run_a.sh`: OK. `--help` from the Cosmos venv, byte-identical before (`$PY $K/world_transfer.py --help`, PYTHONPATH=$R) and after (`$PY -m core.world_transfer --help`, PYTHONPATH=$K:$R): md5 0890d670... both; world_transfer_multi e328c0f1... both. Not run on GPU (no model loads allowed).
- Import smoke of the script entry points `city/agents/live_wm.py`, `live.py`, `city/wm/run_bridge_final.py`, `city/bodies/demo_lunch.py`: all import. `py_compile` on all 70 changed files: OK.
- Single-module runs while working: tests.test_life_* 252 OK (2 skipped); exp1/homeostatic/mind tests 137 OK (2 expected failures); benchmarks 198 OK (1 skipped); runtime 100 OK; simworld 197 OK; city/bodies/wm_multicontrol/world_stream tests 107 OK (1 skipped); all 22 changed tests/ modules 357 OK (12 skipped).
- `ruff check --select F,E9` per directory: no findings on changed lines (existing unrelated F401/F841/F821 left alone, e.g. `exp1/diagnose_d2.py:148` undefined `denom`, `city/ue/kinds/tropical_modern.py:302` undefined `a`; worth a look by their owners).
- `make test-all` (run once, 332 s, peak 1.3 GB, exit 0), P2-B's figures → after: tests 550 OK (4 skipped, 2 expected failures) → 550 OK (12 skipped, 2 expected failures); runtime 100 OK → 100 OK; simworld 197 OK → 197 OK; ops 26 OK → 26 OK; benchmarks 198 OK (1 skipped) → 198 OK (1 skipped). The 8 extra skips are not from this package: P1-M (c42ef5f) put 4 Qwen tests (`test_llm_model`) and 4 Cosmos tests (`test_world_model`) behind `RUN_MODEL_TESTS`. That commit is in this branch's base (8fa93af) but not in P2-B's branch (dad5e31), whose run still loaded the models (peak 18.4 GB). A `-v` listing shows exactly those 8 plus the 4 old skips: RUN_LONG_TESTS, 2× gpu_queue "feat/ops worktree isn't here", 1× cosmos3_mlx not on PYTHONPATH. No test of this base without P2-C was run, to stay within the two-run limit.
- Side finding (not mine to fix, `core/`): `core/settings.py:109` `GPU_QUEUE_SCRIPT` still points at `.claude/worktrees/ops/ops/gpu.py`, which P2-A's grep missed because it's built with `/` path joins, not one string. That's why the 2 gpu_queue tests skip, and the panel's queue page and `life/scenario_night.py`/`life/staged.py` use that path. Should become `ROOT / "ops" / "gpu.py"`.

**Left as they are, on purpose.**
- `ram_share`: Python imports in owned dirs were switched (`from core import ram_share`), but `ops/gpu.py:186` and `ops/memguard.py:29` still `import ram_share`: `ops/` is the queue area, runs from main with system python3, isn't listed in this package, and memguard is what keeps the Mac alive tonight. Works through the alias. All `python3 ram_share.py ...` shell calls unchanged (plan).
- Root shims stay, and stay needed as entry points: `core/world_transfer.py:48`, `core/world_transfer_multi.py:64,80` and `filter_test/scripts/run_cosmos.py:36` launch `ROOT/"world_transfer*.py"`, `ROOT/"ram_share.py"`, `ROOT/"world_filter.py"` by path; `.claude/skills/paint-clip/SKILL.md` runs `world_transfer_multi.py` (not tracked by this package).
- Before P2-F2 deletes shims, also fix: `runtime/preflight.py:109` checks `REPO / "blend.py"` exists; README lines 7-10 and 40 name root `settings.py` etc. (outside the owned Use section); `life/world_runs.py:113` looks for `world_filter.py` in process lines (still right while the entry point is the shim).
- No other shell script in `city/agents/run_wm_life.sh` or `city/bodies/*.sh` runs a root module except `ram_share.py`, so they're unchanged.

**Doubts for the owner.**
- `benchmarks/core.py` exists. Every user imports it as `benchmarks.core`, so it doesn't clash with `core/` as long as the repo root is first on `sys.path` (true for `-m` runs and every script that inserts ROOT). Running a file from inside `benchmarks/` by path would make `import core` find `benchmarks/core.py`; this was already true after P2-B's shims. Renaming one of them is an owner call.
- `run_a.sh` under `-m` puts the job's cwd in front of `$K` on `sys.path`; with the documented `gpu.py ... -- sh wm_multicontrol/run_a.sh` (cwd = repo root) the order is the same as before.
