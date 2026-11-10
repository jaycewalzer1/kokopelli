# P2-D Linters, pre-commit, uv lockfile, venv docs (2026-11-09)

Branch `fable/P2-D`, base `612c096`. No autoformat, no autofix: every existing finding is baselined, none fixed. Nothing was installed into `.venv` or `simworld/.venv`; tools ran through `uvx`/`npx` under `ops/memguard.py`.

## What changed

- `pyproject.toml` (new): project metadata, `mlx-vlm==0.7.11` and `opencv-python==5.0.0.93`, `[tool.uv]` (`package = false`, resolution limited to macOS arm64), ruff and pyright settings.
- `uv.lock` (new): 73 packages. A plain `uv lock` picked newer versions than the main `.venv` for 17 transitive packages (e.g. transformers 5.22.1 → 5.22.2, typer 0.27.3 → 0.29.0), so those 17 are held at the `.venv` versions with `constraint-dependencies`. After that the lock matches `uv pip freeze` of `.venv` exactly: 73/73 packages, 0 version differences. This was a judgment call (reproduce the tested env instead of floating); remove lines from `constraint-dependencies` to undo.
- `.pre-commit-config.yaml` (new): ruff (v0.11.4, same as the system ruff), shellcheck-py v0.11.0.1 (strict hook, plus a baseline hook for 12 scripts with their 9 existing codes), biome 2.6.6 via `npx` on `life/static/*.js`, `check-yaml`, `end-of-file-fixer` (4 files without a final newline excluded so it doesn't rewrite them). Not installed as a git hook: the owner runs `uvx pre-commit install` if wanted.
- `biome.json` (new): recommended lint rules, formatter and assist off, per-file `overrides` turning off only the rules each file already breaks.
- `docs/ENVIRONMENTS.md` (new): the three venvs, what each holds, why they stay separate, how to rebuild `.venv`.
- `README.md` Setup: `uv sync` replaces `uv venv` + `uv pip install -r requirements.txt`; points to ENVIRONMENTS.md.
- `requirements.txt` deleted (its two pins now live in `pyproject.toml`).

## Baselined findings (counts on 2026-11-09)

- ruff `E9,F,B,UP`: 292 findings in 96 files, ignored per file. UP007 84, B905 75, B007 35, F401 28, F841 15, B023 12, UP038 9, B904 8, UP017 7, UP031 7, B027 3, F821 3, UP035 3, UP037 2, B008 1. The 3 F821 (undefined name) were checked by hand and are false positives: `city/ue/kinds/tropical_modern.py:302` (`a` bound on the loop's first pass), `core/world_transfer.py:425` (lambda over `text_kv`, which is `del`'d later), `exp1/diagnose_d2.py:148` (closure over `denom`). The 12 B023 (closure over loop variable) were not checked one by one: worth a look, as some may be real late-binding bugs.
- `runtime/adapters/simworld*.py`, `runtime/tests/test_simworld*.py`, `city/ue/build_city.py` are linted as Python 3.10 (`per-file-target-version`).
- shellcheck: 23 findings in 12 files: SC2086 11, SC2164 3, SC2206 2, SC1091 2, SC2153 1, SC2102 1, SC2034 1, SC2012 1, SC2329 1. 20 are in `*.sh`; 3 are in `scripts/pace/*.sbatch`, which the hook picks up by shebang. One may be a real bug: `scripts/pace/simworld_server.sh:86` uses `WMLOOP_OUT`, which shellcheck says is never assigned in that file (SC2153; it may come from the environment).
- biome: 22 findings in 8 files: useIterableCallbackReturn 9, noUnusedFunctionParameters 7, useTemplate 3, noUnusedVariables 2, noAssignInExpressions 1.
- end-of-file: 4 files excluded (`city/bodies/standins/import_standins.json`, `life/static/inspector.js`, `mac_server/SimWorld.uproject`, `mac_server/Tools/look/realism_means.json`).

## Acceptance

- `ruff check .`: exit 0 (292 before the baseline).
- `uvx pre-commit==4.3.0 run --all-files`: exit 0, all 6 hooks pass, no files modified.
- `uv lock --check`: exit 0.
- `pyright core ops` (1.1.414 via npx, basic mode): **67 errors, not 0**: core 38, ops 29. Core: 12 `reportMissingImports`, all `cosmos3_mlx.*` (that package lives in the Cosmos venv, see ENVIRONMENTS.md); 11 `reportOptionalMemberAccess` (mostly `proc.stdin/stdout` possibly None in `world_stream*.py`); 7 `reportArgumentType` (4 in `llm_model.py` from mlx-vlm's types); 2 `reportPrivateImportUsage` (`mlx_vlm.load/generate`); 2 `reportOptionalSubscript`, 2 `reportCallIssue`, 1 `reportOperatorIssue`, 1 `reportAttributeAccessIssue` (`mx.fast.silu`). Ops: 15 attribute access, 11 argument type, 3 optional member access. Fixing these means editing `core/` and `ops/` code, which this package doesn't own. Whole configured include (`core ops runtime`): 312 errors (runtime 245). pyright isn't a pre-commit hook (plan didn't ask for it).
- `make test-all` (one run, 357 s, peak 1.1 GB, exit 0): tests 550 OK (10 skipped, 2 expected failures); runtime 100 OK; simworld 197 OK; ops 26 OK; benchmarks 198 OK (1 skipped). Before (P2-C's run, base `e1f0d62`): 550 OK (12 skipped, 2 xfail), 100, 197, 26, 198 (1 skipped). The 2 fewer skips are most likely the 2 gpu_queue tests that skipped on the old worktree path, which `612c096` (in this base, after P2-C's run) fixed. This package changes no Python code. No test was run on this base without P2-D, to stay within the two-run limit.

## For the owner

- Decide on pyright `cosmos3_mlx` imports: adding `extraPaths = ["/Users/jaycewalzer/cosmos3/cosmos3-mlx"]` would clear 12 core errors but hard-codes a home path. Left out.
- Decide whether to keep `constraint-dependencies` (reproducible) or let transitive packages float.
- `runtime/HANDOFF.md:70` still has a "Proposed: `requirements.txt`" section; that file is now gone (not owned here; P2-F1's to retire).
- Why `simworld/.venv` is 3.10 isn't written down anywhere; ENVIRONMENTS.md says so.
- Network was used (PyPI, GitHub for hook repos, npm); pre-commit caches in `~/.cache/pre-commit`.
