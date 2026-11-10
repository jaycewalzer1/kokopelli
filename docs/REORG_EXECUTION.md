# Reorganization: execution brief for a fresh session

Written 2026-11-10 for a Claude Code session that has none of the earlier conversation. Read this file fully, then `docs/REORG_PLAN.md` (the design and the reasons), then `AGENTS.md`. This file is the how; the plan is the what and why. Where they disagree, this file wins, and you note the disagreement in the log.

To start the session, the owner pastes:

> Read docs/REORG_EXECUTION.md and execute it from the first unfinished phase. Just do it, no teaching mode.

## 1. The job

Reorganize this repo into one installable `kokopelli/` package, an `experiments/` folder, a `tools/` folder, one test tree, and linters that hold the shape. Ten phases, 0 to 9.

**No behavior changes.** Every commit is a move, a rename, an import rewrite or a config change. If you find a bug, write it in the log and leave it, unless it blocks the move. No new features, no new pages, no refactors "while you're here".

The repo's `CLAUDE.md` asks for teaching mode (questions, quizzes). It also exempts mechanical cleanup. This whole job is mechanical cleanup: don't quiz, don't ask for predictions. Report briefly what changed.

## 2. State when this was written

Check each of these before you start. If one is false, stop and find out why before changing anything.

| Fact | Value | How to check |
|---|---|---|
| Repo | `/Users/jaycewalzer/Desktop/kokopelli`, branch `main` | `git rev-parse --abbrev-ref HEAD` |
| Main | at or after `f57f479`, tree clean except three untracked `mac_server/` paths | `git status --short` |
| GitHub | `origin/main` is behind local main by a few doc commits | `git log origin/main..main --oneline` |
| Tests | tests 600 (10 skipped, 2 expected failures), runtime 100, simworld 197, ops 35, benchmarks 198 (1 skipped), commons 62 | `make test-all` |
| Lint | clean, with a 292-finding baseline in `pyproject.toml` per-file ignores | `.venv/bin/ruff check .` or `uvx ruff check .` |
| GPU queue | idle | `python3 ops/gpu.py status` prints `idle` |
| Watchdog | running | `pgrep -fl "memguard.py watch"` |
| No phase started | no `pre-reorg` tag, no `docs/log/reorg/` folder | `git tag -l pre-reorg` |

Progress is recorded in `docs/log/reorg/PROGRESS.md` (you create it in phase 0). On a restart, that file says which phase is next.

## 3. Hard rules

Breaking one of these has crashed this Mac or lost work before.

1. **Memory.** This is a 36 GB Mac that kernel-panicked on 2026-11-09 from parallel test runs. Run tests only with `make test-all` (or `scripts/fable/test_all.sh <suite>`), which takes a memory claim through `ops/memguard.py`. Run any other heavy command as `python3 ops/memguard.py run --name X --gb N -- cmd`. Never run two test runs at once. Don't spawn parallel subagents that run tests.
2. **The Bash hook.** A global hook in `~/.claude/settings.json` refuses a command that contains `pytest` or `-m unittest` inside this repo unless it also contains `memguard`, `test_all.sh` or `test-all`. It matches text, so a `grep` for the word pytest is refused too: rephrase (for example `grep 'pyte[s]t'`).
3. **No GPU.** The owner said not to use the GPU for this work. Don't load Qwen or Cosmos, don't submit queue jobs, don't set `RUN_MODEL_TESTS=1`. Other GPU jobs may be running that aren't yours: never stop or disturb them or the watchdog. Where the plan asks for a real queue dry run (phase 2), use the no-model check in section 6 and list the real run as owed.
4. **Never delete, move or overwrite** anything under `out/`, `models/`, `mac_server/Packaged*`, `mac_server/Content`, `simworld/.venv`, `.venv`, or `~/cosmos3`. These are outputs, weights and builds, mostly outside git, and can't be rebuilt cheaply. `git mv` on tracked source is fine.
5. **Deleting tracked files** is done with `git rm` (git keeps them). Anything untracked that must go is moved to the Trash (`mv X ~/.Trash/`), never `rm`.
6. **Don't push.** Commit locally. Tell the owner what is unpushed at the end.
7. **Don't touch the vendored trees** except where a phase names them: `simworld/`, `mac_server/` (apart from its scripts' paths into the repo), `wm_multicontrol/upstream/`.
8. **Python 3.10.** Anything the SimWorld venv imports (`runtime/adapters/simworld*`, the `test_simworld*` tests and what they import) must stay 3.10-compatible: no `type X = ...`, no PEP 695 generics, no `except*`, no 3.11+ stdlib.
9. **System `python3` runs `ops/gpu.py`, `ops/memguard.py` and `ram_share`** (the hook, the watchdog, the Makefile). They use only the standard library and must keep working without any venv, before and after they move. `kokopelli/__init__.py` and `kokopelli/ops/__init__.py` must therefore import nothing.
10. **UI** is not part of this job. If a move forces a change in a page, follow `DESIGN.md` tokens and change nothing visible.

## 4. How to work

- **One phase, one branch.** `git switch -c reorg/N-short-name main`. Small commits inside it. When its acceptance checks pass: `git switch main && git merge --no-ff reorg/N-short-name -m "Reorg phase N: ..."`, run `make test-all` once more on main, then delete the branch. A phase can then be undone with `git revert -m 1 <merge>`.
- Work in the main checkout, not a worktree. The venvs, `out/` and `models/` live here and jobs read the working folder. Phases run one at a time.
- **Commit messages:** a plain sentence, ending with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **After every commit that moves a file,** run the suite it belongs to (`scripts/fable/test_all.sh ops`, for example). Run the full `make test-all` at the end of each phase. The whole run takes about two minutes and peaks near 1.3 GB.
- **Use `git mv`** so history follows the file. Rewrite imports with a script you keep in `tools/reorg/` (created in phase 0), not by hand, so the rewrite can be rerun and reviewed.
- **Subagents:** fine for read-only searches. Don't hand a phase to a subagent, and never let one run tests.
- **Log.** After each phase append to `docs/log/reorg/PROGRESS.md`: phase, merge commit, test counts, what was skipped or owed, anything surprising. Plainly: failures and skips as clearly as successes.
- **Stop and ask the owner** only when: test counts change and you can't explain it within an hour; a rule in section 3 would have to be broken; something under `out/` would need rewriting beyond `out/staged`; or a phase's acceptance can't be met. Otherwise keep going through the phases without asking.
- **A sensible early finish.** After phase 2 the root is clean and nothing depends on the working folder. After phase 4 the namespace is done. If the session is running long, finish the current phase, merge, log, and stop there.

## 5. Things that will bite

- **Three interpreters.** `.venv/bin/python` (3.12, main, no pytest until phase 7), `simworld/.venv/bin/python` (3.10, has pytest), `~/cosmos3/cosmos3-mlx/.venv/bin/python` (3.12, Cosmos; finds repo code through `PYTHONPATH` or the working folder). Package manager is `uv` (0.13). Don't `uv sync` the SimWorld or Cosmos venvs: install into them only with `uv pip install --python <that python> --no-deps -e .`.
- **Root stand-ins.** The 12 root `.py` files (`world_transfer.py`, `settings.py`, `ram_share.py`, ...) are aliases: `sys.modules[__name__] = core.x`, or `runpy` when launched. The same module object is shared on purpose, so `mock.patch("world_transfer.X")` reaches the real code. When you add aliases in phase 4, use the same trick, never `from x import *`.
- **The architecture table.** `life/architecture.py` lists file paths per node; `tests/test_life_architecture.py` fails if one doesn't exist. Update the table in the same commit as each move.
- **The panel watch list.** `life/panel.py` restarts when listed files change (it includes `core/settings.py`). Update it with each move. The dev panel may be running on port 8765: leave it; it only reads.
- **`core/settings.py`** has `ROOT`, `GPU_QUEUE_SCRIPT = ROOT / "ops" / "gpu.py"` and a `WORKTREES` table. `ROOT` is computed from the file's own location, so moving the file one level deeper changes it. Fix `ROOT` in the move commit and assert it still equals the repo folder.
- **Old worktrees.** `.claude/worktrees/` holds five worktrees (`agent-a2d4c0a770bb9b339`, `agent-aa5f839d86d587545`, `commons`, `exp1`, `wm-agent-loop`). Their branches are all merged into main. `WORKTREES` in settings, `life/architecture.py` and `ops/status.py` still name three of them. Leave them until phase 9. Don't run tests inside them.
- **Jobs on disk.** `out/staged/` holds queue commands with paths (one entry, `started`, at the time of writing). Read what is there before a path-changing merge; regenerate, don't hand-edit.
- **Cluster copy.** `scripts/pace/` runs on the PACE cluster from its own checkout. You can't reach it. When paths it uses change, write the exact follow-up for the owner in the log under "Owed: PACE".
- **`benchmarks/core.py`** shadows the `core` package when a file in `benchmarks/` is launched by path. Launch with `-m` from the root.
- **Piping long commands into `tail` hides waits.** `memguard run` prints why it is waiting; if a command seems hung, look at `python3 ops/memguard.py status`.
- **`mac_server` tests** (`MAC=1 make test-all`) have 29 known baseline failures and start a mock server on port 9000. Run them once in phase 0 and once in phases 4 and 5, not every time.
- **Commons tests** are pytest-style and run in the SimWorld venv until phase 7.

## 6. Checks used by every phase

**Full tests:** `make test-all`. Expected lines until phase 7: `tests ok ... Ran 600 tests`, `runtime ... 100`, `simworld ... 197`, `ops ... 35`, `benchmarks ... 198`, `commons ... 62 passed`. After phase 7 the total stays 1,192 collected.

**Lint:** `ruff check .` clean. `pre-commit run --all-files` changes nothing.

**Smoke (from phase 0):** `tools/smoke_entrypoints.sh` passes in all three interpreters.

**Queue without a model:** `python3 ops/gpu.py check`, then send a help call through the queue: `python3 ops/gpu.py run --name reorg-smoke --priority 90 --gb 1 --max-hours 0.1 --about "reorg smoke, no model" -- <cosmos python> -m <transfer module> --help`. This exercises the queue, the working folder and the launch path, and loads nothing. Do **not** use `--dry-run` with a real transfer command: a dry run sets `KOKO_DRY_RUN=1` and paints one latent, which loads Cosmos onto the GPU. That real dry run is the one owed to the owner. Only run the help call when `gpu.py status` prints `idle`, and read `python3 ops/gpu.py run --help` first; don't guess flags.

## 7. Phases

Each phase lists steps, acceptance, and what to record. Detail and reasoning are in `docs/REORG_PLAN.md` under the same phase number.

### Phase 0: safety net

1. Run the checks in section 2. Run `MAC=1 make test-all` once and record all counts.
2. `git tag pre-reorg`.
3. Create `docs/log/reorg/PROGRESS.md` with the baseline counts, and `tools/reorg/` for the scripts you write.
4. Write `tools/smoke_entrypoints.sh`. It takes an interpreter path (default: all three in turn), runs each entry point with `--help`, and prints one `ok`/`FAIL` line each, exit 1 on any failure. Build the list with `git grep -l '__name__ == "__main__"' -- '*.py'` minus tests, `simworld/`, `mac_server/` and `wm_multicontrol/upstream/`; at the time of writing that is about 35 files in `core/`, `ops/`, `life/`, `runtime/`, `mind/`, `city/agents/`, plus the root stand-ins and the shell launchers (`bash -n` for `.sh`). Some scripts don't take `--help` or load a model on import: for those, check `python -c "import importlib; importlib.import_module('pkg.mod')"` instead, and keep a short skip list with a reason per line. Each entry is tagged with the interpreter it belongs to; don't expect MLX imports to work in the 3.10 venv.
5. Write `tools/reorg/import_graph.py` (standard library `ast`; package-to-package edges with counts) and save its output as `docs/log/imports-before.txt`. Confirm it shows the wrong-way edges the plan names (`life` → `homeostatic`, `mind` → `runtime` → `mind`).

Acceptance: tag exists; smoke passes or every failure is explained in the skip list; baseline recorded; tests unchanged.

### Phase 1: installable

1. In `pyproject.toml` add `[build-system]` (hatchling or setuptools, whichever needs less config) and `[project.scripts]`: `koko-gpu`, `koko-ram`, `koko-memguard`, `koko-transfer`, `koko-transfer-multi`, `koko-stream`, `koko-stream-multi`, `koko-filter`, `koko-panel`, each pointing at the existing module's `main`. Where a module has no `main()` function, wrap its `if __name__` body in one, changing nothing else.
2. Declare today's packages explicitly (`core`, `ops`, `life`, `runtime`, `mind`, `cloud`, ...) so the build doesn't sweep in `out/`, `models/`, `simworld/` or `mac_server/`.
3. `uv pip install -e .` in `.venv`; `--no-deps -e .` in the SimWorld and Cosmos venvs, each with `--python`. Run `uv lock` and commit `uv.lock` if it changes.
4. Add the commands to the smoke script.

Acceptance: every `koko-*` prints help from the venv that uses it; old path launches still work; tests unchanged. Nothing moved or deleted.

### Phase 2: no path launches, no root stand-ins

1. List the launchers: `git grep -nE "(ram_share|world_transfer|world_stream|world_filter|world_model|world_multicontrol_base|blend|edges|llm_model|settings)(_multi)?\.py" -- ':!docs' ':!simworld' ':!mac_server'`. Change each to the `koko-*` command or `python -m core.<module>`. In shell scripts that run under the Cosmos venv, prefer `python -m` with the repo as working folder: it doesn't depend on the install being fresh.
2. Remove `sys.path.insert` calls one package at a time (`git grep -n "sys.path.insert"`: 73 in 57 files), running that package's suite after each. Leave the ones in `simworld/`, `mac_server/` and vendored code. A script in a subfolder that was run by path must now be run with `-m` from the root: update whatever launches it.
3. Before deleting the root files: `grep -rlE "(world_transfer|world_stream|world_filter|ram_share)(_multi)?\.py" out/staged out/ops 2>/dev/null` and record the hits. Regenerate staged jobs with the tool that wrote them; if you can't find the generator, leave the entry, don't edit it, and log it as owed.
4. Update tests that import the root names (`import world_transfer`) to `core.world_transfer`, including `mock.patch` target strings.
5. `git rm` the 12 root `.py` files. `git mv "Kokopelli_Perspectives (2).pdf" docs/`. Trash the root `__pycache__`.
6. Update the Makefile, `AGENTS.md`, the architecture table and the panel watch list.

Acceptance: no `.py` at the root; smoke passes in all three venvs; remaining `sys.path.insert` hits are only in excluded trees; the no-model queue check passes; tests unchanged. Owed to the owner: one real queue dry run (about a minute of GPU).

### Phase 3: layering, then the wall

1. `git mv homeostatic/watch.py life/watch.py` (or `core/` if both `life` and `homeostatic` need it), with an alias left at the old path for now; fix the three importers in `life`.
2. Break `mind` ↔ `runtime`: `mind/run.py` wires the two together, so it becomes a launcher outside `mind` (for now `runtime/run_mind.py` or the existing `runtime/run.py`, whichever already plays that part; read both first). `mind` must not import `runtime` afterwards.
3. Add `import-linter` to the dev dependencies and a `[tool.importlinter]` section with three contracts: the library packages never import `experiments`, `benchmarks`, `exp1`, `homeostatic`, `filter_test`, `wm_multicontrol`, `tools`, `scripts` or `tests`; layers `core` → `mind` → `runtime` → `city.agents` (lower never imports higher); `ops` imports none of the others. `runtime.adapters.life_db` → `life` is an allowed edge: put it in the allow-list with a one-line reason.
4. The wall is hard (owner's decision). Any other violation is fixed by moving code, not by an allow-list line, unless moving it would change behavior. Then allow-list it with the reason and log it.
5. Add `lint-imports` to `.pre-commit-config.yaml`.

Acceptance: `lint-imports` passes; regenerated import graph shows no wrong-way edge outside the allow-list; tests unchanged.

### Phase 4: one namespace (the largest phase)

Preconditions: GPU queue idle, no other branch ahead of main, `out/staged` read.

Order, one commit each, suite after each: `ops` + `cloud` → `kokopelli/ops`; `core` → `kokopelli/wm` (with `core/settings.py` → `kokopelli/settings.py`); `mind` → `kokopelli/mind`; `runtime` → `kokopelli/loop`; `life` → `kokopelli/life`.

For each package:

1. `git mv` the folder. Tests stay where they are until phase 7, except that `runtime/tests` and `ops/tests` must remain discoverable: leave them at their old paths for now (a `runtime/tests/` folder beside the alias is fine) and keep `test_all.sh` pointing at them.
2. Rewrite imports across the repo with `tools/reorg/rewrite_imports.py` (handle `import a.b`, `from a import b`, `from a.b import c`, strings in `mock.patch(...)`, `python -m a.b` in shell, Makefile and docs, and `[project.scripts]`). Review the diff; a name like `core` also appears as an ordinary word.
3. Leave an alias package at the old name: an `__init__.py` that maps the old package and each submodule onto the new module objects in `sys.modules`. Add a test, `tests/test_reorg_aliases.py`, asserting identity for a few modules (`core.settings is kokopelli.settings`), and delete it with the aliases in phase 9.
4. Fix `ROOT` in settings, `GPU_QUEUE_SCRIPT`, the architecture table, the panel watch list, `AGENTS.md`, the Makefile and `scripts/fable/test_all.sh`.

Then, once `ops` has moved, three things outside the repo's Python:

- **The hook.** Back up `~/.claude/settings.json` (`cp` to `settings.json.bak-<date>`), then change the PreToolUse Bash hook's file list so `kokopelli/ops/memguard.py` comes first and the old `ops/memguard.py` path stays as a fallback. Test it: a command containing the phrase `memguard-hook-selftest` should produce the hook's self-test response; then confirm a bare unittest command in the repo is still refused.
- **The watchdog.** It was started from the old path. After the merge to main: find it with `pgrep -f "memguard.py watch"`, stop that one process, and start `nohup python3 -m kokopelli.ops.memguard watch >/dev/null 2>&1 &` from the repo root. This is the one process in this job you may restart, and only this way. Check `python3 -m kokopelli.ops.memguard status`.
- **State paths.** Memory claims live in `out/ram/claims` and `~/.kokopelli/memguard/`; they are found through the git common dir, not the file's location. Confirm `status` still shows a running `test_all` claim during a test run.

Keep `python3 ops/memguard.py` and `python3 ops/gpu.py` working through the phase (a two-line stand-in script at the old path), because the Makefile, the hook fallback, `mac_server/scripts/package_nomouse.sh`, `city/agents/run_wm_*.sh` and the owner's habits all use them. They go in phase 9.

Acceptance: `kokopelli/{wm,loop,mind,life,ops}` and `kokopelli/settings.py` exist; alias identity test passes; smoke passes in all three venvs; `lint-imports` passes with contracts rewritten to the new names; `MAC=1 make test-all` matches the phase 0 counts; hook and watchdog verified.

### Phase 5: split `city/`

Before moving `city/ue`: capture a dry-run dump of the planned actor list (read `city/ue` for its plan or dry-run mode; it must not need a running Unreal server) into the scratch folder. After the move, the dump must be byte-identical.

| From | To |
|---|---|
| `city/agents/` | `kokopelli/agents/` (library; add to the layer contract above `loop`) |
| `city/wm/` code | `kokopelli/wm/controls/`; prompt text files to `data/prompts/` |
| `city/ue/` | `tools/city_build/` |
| `city/bodies/` | `tools/bodies/` |
| `city/realism/`, `city/source_*.py`, `city/moodboard/` | `tools/realism/`, `tools/moodboard/` |
| `city/world.json` | `data/city/world.json` |

- `city/world.json` and `city/world_varied.json` are byte-identical (`cmp` them first; if they differ, stop and ask). Keep `world.json`, `git rm` the other, point its five readers at the kept file. The current file is the owner's updated, varied city: keep its content exactly.
- 17 files name `city/world`; update all (`git grep -n "city/world"`).
- `city/bodies/*.sh` hold absolute paths: `bash -n` each and fix paths into the repo. `city/agents/run_wm_life.sh` and `run_wm_lunch.sh` pass `NOMOUSE=1` to `mac_server/scripts/run.sh`: keep that.
- The moodboard is served by the panel at `/moodboard`: check the page still loads its data after the move (request it with `curl` against a panel you start on a spare port, then stop that one).

Acceptance: `city/` is gone; actor dump identical; tests and `MAC=1` counts unchanged; smoke and `lint-imports` pass.

### Phase 6: experiments and tools

1. `git mv` `benchmarks/`, `exp1/`, `homeostatic/`, `filter_test/`, `wm_multicontrol/` into `experiments/`. `wm_multicontrol/upstream/` goes to `vendor/wm_multicontrol_upstream/`.
2. `benchmarks` imports become `experiments.benchmarks.*`; update `python -m benchmarks...` in its docs and scripts and in `scripts/pace/evals` (log under "Owed: PACE"). `benchmarks/tests` moves with it; update `test_all.sh`.
3. `git mv runs/commons experiments/commons/results` and fix the paths the commons report cites.
4. `git mv scripts/fable tools/fable`, `git mv scripts/pace tools/pace`. Update the Makefile (`test-all`), the hook's `GUARDED` pattern if the script name it matches changes (`test_all.sh` and `test-all` must still match), `AGENTS.md`, and `~/.kokopelli/fable/worker.sh` is not yours to fix: note it as stale in the log.
5. One `README.md` per experiment: what it asked, how to rerun, where results are. Build each from the documents already in that folder; don't invent results.
6. Rewrite the import contracts to the final names.

Acceptance: top level holds only `kokopelli/ experiments/ tools/ data/ tests/ docs/ vendor/ mac_server/ simworld/ out/ models/` plus config files and the temporary alias folders; tests unchanged.

### Phase 7: one test tree

1. Add `pytest` to the main environment's dev dependencies (`uv add --dev pytest`), so `.venv` has it.
2. Before moving anything, save the collected test IDs from the old runner (unittest discovery per suite, via `test_all.sh` with `VERBOSE=1`) into `docs/log/reorg/tests-before.txt`.
3. `git mv` `runtime/tests` → `tests/loop/`, `ops/tests` → `tests/ops/`, and sort the existing `tests/*.py` into folders mirroring `kokopelli/`. Experiments keep their own `tests/`; `mac_server/tests` stays.
4. Register markers in `pyproject.toml`: `model` (replaces `RUN_MODEL_TESTS=1`; skipped unless that variable is set, so the default stays safe), `py310`, `unreal`, `slow`.
5. `make test-all` becomes two guarded pytest runs under one memory claim: `.venv` with `-m "not py310"`, the SimWorld venv with `-m py310`, plus the commons tests wherever they pass. Keep the output to one summary line per run and keep `MAC=1`.
6. Compare collected IDs with step 2. Same 1,192 tests, same skips, same two expected failures. Measure peak memory of the new run with `memguard` before trusting it; it must stay under 2 GB. If the count differs, fix collection (class names, `load_tests`, module-level skips), not the tests.
7. Update the hook's patterns only if needed, then re-run its self-test.

Acceptance: counts match; old runner removed; `AGENTS.md` memory rules updated to the new command.

### Phase 8: linters

Do in this order, each its own commit, tests after each:

1. `ruff format .` plus import sorting (rule `I`) as one commit; put its hash in `.git-blame-ignore-revs` and run `git config blame.ignoreRevsFile .git-blame-ignore-revs`. Exclude `simworld/`, `mac_server/`, `vendor/`.
2. Burn down the per-file ignores one rule at a time, `B023` first (loop-variable capture: each may be a real bug; where fixing it would change behavior, leave the ignore on that line with `# noqa: B023` and a reason, and log it). Look at the four `F821` findings in `exp1/diagnose_pilot.py` line 54: report what they are; fix only if it's a plain missing import.
3. Pyright to zero on `kokopelli/` (67 errors at the start; 12 are `cosmos3_mlx` imports, solved with a stub under `typings/`). Fix with annotations and narrowing, not by changing logic. Experiments and tools stay unchecked.
4. Fix the 23 shellcheck and 22 biome findings; drop their baselines.
5. Add a `pre-push` hook stage running `make test-all`, and `.github/workflows/ci.yml` for ruff, import-linter, pyright and the tests that need neither MLX nor Unreal. The workflow can't be verified until the owner pushes: say so.

Acceptance: no per-file ignore list (or a short one where every line has a reason); `pyright kokopelli` reports 0; `pre-commit run --all-files` changes nothing.

### Phase 9: documents and leftovers

1. One `README.md` per package under `kokopelli/`. Dated `HANDOFF.md`, `PLAN.md`, `BRIEF.md` files and `docs/fable_log/` move to `docs/log/<area>/` with the date in the name. Files that hold results stay where code or reports cite them (`git grep` the filename first).
2. Rewrite `AGENTS.md` and the top `README.md` for the new layout. Keep the memory rules section. Don't change `CLAUDE.md` or `DESIGN.md`.
3. Remove aliases and stand-ins: only after `git grep -nE "^(from|import) (core|runtime|mind|life|ops|cloud|city|benchmarks)\b"` is empty outside the alias folders, and the hook and Makefile use the new paths. Then drop the old `ops/memguard.py` fallback from the hook.
4. Fix `WORKTREES` in settings and the references in the architecture table and status tool, then retire the five merged worktrees: confirm each branch is merged (`git branch --merged main`) and each worktree is clean (`git -C <path> status --short`); `git worktree remove` the clean ones; list any dirty one for the owner instead of forcing it.
5. Final `docs/log/reorg/PROGRESS.md` summary: what moved, final counts, everything owed.

Acceptance: fewer than 60 Markdown files outside `docs/log/`, `simworld/`, `mac_server/`, `vendor/`; every one linked from a README; full checks pass.

## 8. Final report to the owner

Short and plain: phases finished and merged, test counts before and after, what was skipped or failed and why, and the owed list. Expect at least: the real queue dry run (GPU), PACE checkout updates, the unverified GitHub Action, any staged job left alone, commits not pushed. Name any model that ran (none should have).
