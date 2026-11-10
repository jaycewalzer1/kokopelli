# Reorganization plan

Written 2026-11-10, updated the same day with the owner's decisions. No phase is started; the one precondition (merging the open branches) is done. It continues from the cleanup pass logged in `docs/fable_log/`.

## Goal

Make the repo say what each part is: one installable library, experiments that use it, the Unreal project, hand-run tools, vendored code. Then hold that shape with linters, so it doesn't drift back.

No behavior changes. Every phase is a move, a rename or a config change, and ends with `make test-all` at the same pass counts as it started.

## Measured starting point (main at 2026-11-10)

| Fact | Number |
|---|---|
| Root stand-in files left from the `core/` move | 12 files, 93 lines |
| Files that launch a root file by path (`python world_transfer_multi.py ...`) | 30 |
| `sys.path.insert` calls | 73, in 57 files |
| `city/` | 58 Python files, 19,427 lines. `city/ue` alone is 12,025 |
| Test locations | `tests` 42 files, `runtime/tests` 19, `benchmarks/tests` 6, `ops/tests` 2, `experiments/commons/tests` 2, `mac_server/tests` 2 |
| Interpreters | `.venv` (3.12), `simworld/.venv` (3.10), `~/cosmos3/cosmos3-mlx/.venv` |
| Ruff findings ignored as a baseline | 292, in 96 files |
| Pyright errors on `core` and `ops` | 67 |
| Markdown files tracked | 170 |
| Files outside them that name `mac_server` / `simworld/` | 44 / 46 |

Imports that cross the wrong way today:

- `life` imports `homeostatic.watch` in three files (`architecture.py`, `panel.py`, `pipeline.py`). The library depends on an experiment.
- `runtime/adapters/life_db.py` imports `life`, and `mind/run.py` imports `runtime`, while `runtime` imports `mind`. A cycle.

## Target layout

```
kokopelli/              the library, one importable package, installed editable in all three venvs
  wm/                   today's core/world_*, video_check, manifest, blend, edges, llm_model
  loop/                 today's runtime/ (the agent loop, adapters, mocks)
  mind/                 today's mind/
  agents/               today's city/agents/
  life/                 today's life/ (generator, store, panel)
  ops/                  today's ops/ and cloud/ (queue, memguard, ram_share, status)
  settings.py
experiments/            commons/ (already here), benchmarks/, exp1/, homeostatic/, filter_test/, wm_multicontrol/ (without upstream/)
tools/                  hand-run scripts: moodboard sourcing, body asset generators, capture tools, scripts/fable, scripts/pace
data/                   city/world.json and other tracked inputs
tests/                  one tree, mirroring kokopelli/
docs/                   plus docs/log/ for dated notes
mac_server/             unchanged name
simworld/               unchanged name
out/  models/           ignored by git, unchanged
```

Two things from my first sketch that I'd now leave alone:

- **No `src/` folder.** With three venvs and queue jobs that run with the repo as their working folder, a flat `kokopelli/` package keeps working when an install is stale. A `src/` layout would be stricter and would fail in ways that are hard to see from a queue log.
- **No rename of `mac_server/` or `simworld/`.** 44 and 46 files name them, plus Unreal's own project paths and a venv inside `simworld/`. The rename buys a tidier top level and nothing else. They get a line in the README and stay excluded from linting.

## Constraints that apply to every phase

1. **Three interpreters.** Anything the SimWorld venv imports must run on Python 3.10. Every phase runs the entry-point smoke check (phase 0) in all three.
2. **The architecture page checks file paths.** `life/architecture.py` holds a table of files per node and `tests.test_life_architecture` fails when one is missing. Every move updates that table in the same commit.
3. **The panel watches files.** `life/panel.py` restarts on changes to a list of paths. Moves update the list.
4. **Jobs written to disk.** `out/staged/` and run scripts under `out/` hold commands with paths. Do path-changing phases with the GPU queue idle, and regenerate staged jobs afterwards.
5. **Open branches.** Done on 2026-11-10: `exp/commons-homeostasis` (16 commits), `feat/exp1-homeostatic-rl` (1) and `feat/wm-agent-loop` (1) are merged into main, so no branch is ahead of it. Keep it that way: no other branch stays open across a renaming phase.
6. **The cluster copy.** `scripts/pace/` runs on PACE from its own checkout. Path changes there need the cluster checkout updated at the same time.
7. **Memory rules** from `AGENTS.md`: tests through `make test-all`, heavy commands through `ops/memguard.py`.
8. **One phase per branch**, merged with `--no-ff`, so a phase can be undone by reverting one merge commit.

## Phases

Effort figures are my estimates, not measurements.

### Phase 0: safety net (half a day)

- Tag main as `pre-reorg`.
- Write `tools/smoke_entrypoints.sh`: runs every script and module that has a `main()` with `--help`, in the interpreter it belongs to, and prints one line each. This is the check that catches a broken launch path, which the unit tests don't.
- Save the import graph (the table above, generated by a script) as `docs/log/imports-before.txt`.
- Acceptance: smoke script lists every entry point and all pass; `make test-all` baseline recorded.

### Phase 1: make it installable (half a day)

- Add `[build-system]` and `[project.scripts]` to `pyproject.toml`: `koko-gpu`, `koko-ram`, `koko-memguard`, `koko-transfer`, `koko-transfer-multi`, `koko-stream`, `koko-stream-multi`, `koko-filter`, `koko-panel`.
- `uv pip install -e .` into `.venv` and the Cosmos venv. For the 3.10 SimWorld venv, install with `--no-deps` so it doesn't pull MLX.
- Nothing is moved or deleted. Old paths and new commands both work.
- Acceptance: each command prints its help in the venv that uses it; tests unchanged.
- Risk: the Cosmos venv's dependencies. `--no-deps` there too, since it only needs the code on its path.

### Phase 2: stop launching by path, delete the root stand-ins (1 day)

- Change the 30 launching files to the commands or to `python -m`. The list comes from `git grep -E "(ram_share|world_transfer|world_stream|world_filter|world_model)\.py"`. The heaviest: `life/architecture.py`, `wm_multicontrol/run_a.sh`, `filter_test/scripts/run_cosmos.py`, `core/world_transfer*.py`, `ops/gpu.py`.
- Remove the 73 `sys.path.insert` calls, one package at a time, running that package's tests after each.
- Delete the 12 root files. Move the PDF to `docs/`. `runs/commons/` holds the commons experiment's tracked results and moves with it in phase 6.
- Regenerate `out/staged/` jobs.
- Acceptance: `ls *.py` at the root is empty; smoke script passes in all three venvs; `git grep sys.path.insert` returns only `simworld/`, `mac_server/` and vendored code; one real queue dry run passes (about a minute of GPU).
- Risk: a script on disk outside git that still calls a root file. Mitigation: `grep -rl` over `out/staged` and `out/ops` before deleting, and keep the tag.

### Phase 3: fix the layering, then enforce it (1 day)

- Move `homeostatic/watch.py` into the library (it's a file watcher, not experiment logic), so `life` stops importing an experiment.
- Break the `runtime` ↔ `mind` cycle: `mind/run.py` is a launcher that wires both together, so it moves to a top-level entry point and `mind` stops importing `runtime`.
- `runtime/adapters/life_db.py` importing `life` is a legitimate adapter. Record it as an allowed edge.
- Add `import-linter` with three contracts: the library never imports `experiments`, `benchmarks`, `tools` or `tests`; the layer order `wm` → `mind` → `loop` → `agents`; `ops` imports nothing from the rest.
- Acceptance: `lint-imports` passes in `pre-commit`; tests unchanged.
- Decided: the wall is hard. An exception needs a line in the contract's allow-list with its reason.

### Phase 4: one namespace (2 days, the largest change)

- Move `core`, `runtime`, `mind`, `life`, `ops`, `cloud` under `kokopelli/` with the names in the target layout. One package per commit, in this order: `ops`, `core`→`wm`, `mind`, `runtime`→`loop`, `life`.
- Leave an alias for each old name using the trick from the `core/` move (`sys.modules[__name__] = kokopelli.wm`), so unmerged branches and old scripts keep working. Delete the aliases in phase 9.
- Update `life/architecture.py`'s table, the panel's watch list, `AGENTS.md`, the hook command in `~/.claude/settings.json` (it names `ops/memguard.py`), and the watchdog's launch path.
- Why bother: `core`, `runtime`, `ops` and `life` are generic names that collide. `benchmarks/core.py` already shadows `core` when a file in that folder is run by path.
- Acceptance: tests unchanged; smoke script passes; `import kokopelli.wm.settings is core.settings` style identity checks hold while aliases exist.
- Risk: this touches almost every Python file. Do it alone, with no other branch open, and the queue idle.

### Phase 5: split `city/` (2 days)

| Today | Goes to | Why |
|---|---|---|
| `city/agents/` (10 files, 2,800 lines) | `kokopelli/agents/` | Library code: the lunch and live agents |
| `city/wm/` (6 files) | `kokopelli/wm/controls/`, prompts to `data/prompts/` | Control-video code is world-model code |
| `city/ue/` (22 files, 12,025 lines) | `tools/city_build/` | Scripts that build the city in Unreal; run by hand |
| `city/bodies/` (16 py, 8 sh) | `tools/bodies/` | Asset pipeline and packaging scripts |
| `city/realism/`, `city/source_*.py`, `city/moodboard/` | `tools/realism/`, `tools/moodboard/` | Hand-run tools |
| `city/world.json`, `world_varied.json` | `data/city/` | Tracked input data. The two files are identical: keep one, point the five readers at it |

- Acceptance: `city/` is gone; tests unchanged; `tools/city_build` plans the same city (a dry-run dump of the planned actor list is byte-identical before and after); the 17 files that name `city/world` are updated.
- Risk: `city/bodies` shell scripts contain absolute paths. Check each with `bash -n` and a `--help` or dry run.

### Phase 6: experiments and tools (half a day)

- Move `benchmarks/`, `exp1/`, `homeostatic/` (minus `watch.py`), `filter_test/` and `wm_multicontrol/` into `experiments/`, beside `commons/`. `benchmarks/` is the largest (35 Python files, 65 tracked files): its imports become `experiments.benchmarks.*`, and `python -m benchmarks...` commands in its docs, scripts and `scripts/pace/evals` change with it. Move `runs/commons/` to `experiments/commons/results/` and update the paths its report cites. Move `wm_multicontrol/upstream/` to `vendor/`.
- Move `scripts/fable/` and `scripts/pace/` into `tools/`. `test_all.sh` goes away in phase 7.
- Each experiment keeps one `README.md`: what it asked, how to rerun it, where the results are.
- Acceptance: tests unchanged; the import contracts from phase 3 pass with the new paths.

### Phase 7: one test tree (1 day)

- Move `runtime/tests` and `ops/tests` under `tests/`, mirroring the package layout. `benchmarks/tests` moves with `benchmarks/` in phase 6. `mac_server/tests` stays with the Unreal project, and each experiment keeps its own `tests/` folder.
- Add `pytest` to the main environment. Today only the SimWorld venv has it, which is why the commons tests run there.
- Switch the runner to `pytest` with markers: `model` (loads Qwen or Cosmos, replaces `RUN_MODEL_TESTS`), `py310` (must run in the SimWorld venv), `unreal` (needs a server), `slow`.
- `make test-all` becomes two guarded `pytest` runs, one per interpreter. It can't be one process: the SimWorld tests need Python 3.10.
- Acceptance: the same 1,192 tests are collected as today (600 + 100 + 197 + 35 + 198 + 62 commons); the same ones are skipped; the run still peaks under 2 GB.
- Risk: `unittest` discovery and `pytest` collection differ on a few patterns (test classes without the `Test` prefix, module-level skips). Compare collected test IDs before deleting the old runner.

### Phase 8: tighten the linters (2 to 3 days, can be spread out)

1. **Format once.** `ruff format .` in a single commit, listed in `.git-blame-ignore-revs` so blame skips it. Do it right after phase 6, when no branch is open.
2. **Burn down the 292 ignored findings**, one rule at a time, starting with the 12 loop-variable warnings (`B023`), which can be real bugs. Each rule: fix, remove its ignores, test.
3. **Pyright to zero on the library.** 67 errors now; 12 are imports of `cosmos3_mlx`, fixed with a stub file instead of putting a home path in the config. Experiments and tools stay unchecked.
4. **Shell and JavaScript:** fix the 23 `shellcheck` and 22 `biome` findings and drop their baselines.
5. **Import sorting** (`ruff` rule `I`), added with the format commit.
6. **Run it without relying on memory:** `pre-commit` already exists. Add a `pre-push` hook that runs `make test-all`, and a GitHub Action for lint and the tests that don't need MLX. The Action only helps once main is pushed, which is 80-plus commits behind today.

- Acceptance: `pyproject.toml` has no per-file ignore list; `pyright kokopelli` reports 0; `pre-commit run --all-files` changes nothing.

### Phase 9: documents and leftovers (1 day)

- One `README.md` per package. Dated `HANDOFF.md`, `PLAN.md` and `BRIEF.md` files move to `docs/log/<area>/` with their date in the name. Files holding results stay where the code cites them.
- Rewrite `AGENTS.md` and the top-level `README.md` for the new layout.
- Delete the phase 4 aliases once `git grep` shows no importer and the unmerged worktrees are gone.
- Fix the two `WORKTREES` entries in settings that point at `.claude/worktrees/agent-…`, then retire those worktrees.
- Acceptance: `git ls-files '*.md' | wc -l` drops from 170 to under 60 outside `docs/log/`, `simworld/` and `mac_server/`; every remaining Markdown file is linked from a README.

## Order and size

| Phase | Depends on | Estimate | Can run in parallel with |
|---|---|---|---|
| 0 Safety net | nothing | 0.5 day | nothing |
| 1 Installable | 0 | 0.5 day | nothing |
| 2 No path launches | 1 | 1 day | nothing |
| 3 Layering | 2 | 1 day | nothing |
| 4 One namespace | 3 | 2 days | nothing |
| 5 Split `city/` | 4 | 2 days | 6 |
| 6 Experiments, tools | 4 | 0.5 day | 5 |
| 7 One test tree | 5, 6 | 1 day | nothing |
| 8 Linters | 6 for the format commit | 2 to 3 days | 9 |
| 9 Documents | 7 | 1 day | 8 |

About 11 to 12 working days end to end. Phases 0 to 2 are the cheap, high-value part: after them the root is clean and nothing depends on the working folder. That is a sensible place to stop if priorities change.

## How to run it

- Same pattern as the cleanup pass: one Opus worker per phase in its own worktree, started with `~/.kokopelli/fable/worker.sh`, merged by an orchestrator after `make test-all` and the smoke script pass.
- Phases 0 to 4 and 7 run one at a time. They rename things everything else depends on.
- Only phase 2's dry run needs the GPU, for about a minute.
- A rough token guess from the cleanup pass, where 12 packages ran overnight: phases 4, 5 and 8 are each as large as two or three of those packages. Check `/usage` after phase 2 and scale from there.

## Decisions (owner, 2026-11-10)

1. **Hard wall** between library and experiments, enforced by `import-linter` with an allow-list.
2. **Phase 4 is in.** Everything moves under one `kokopelli/` package.
3. **Open branches merged before starting.** Done; see constraint 5.
4. **Pushed to GitHub** on 2026-11-10, so there is an off-machine copy before any renaming and CI can be added in phase 8.
5. **`benchmarks/` goes under `experiments/`** (phase 6). Under the hard wall the library may not import it; today nothing in the library does.
6. **World file:** keep the current city. `city/world.json` and `city/world_varied.json` are byte-identical on main and both hold the updated, varied city (the original was replaced on 2026-11-09). Phase 5 keeps `world.json`, removes the duplicate and points its five readers at the kept file.

Still open:

- **`exp1/diagnose_pilot.py`** has four undefined-name lint findings (line 54) that came in with the merge and are baselined, not checked. Look at them in phase 8 before trusting that script.
