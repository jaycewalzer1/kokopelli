# P2-A Worktree path fix

Branch `fable/P2-A`, cut from `integration/fable` at `ba07916`.

## What changed

The queue moved into this checkout under `ops/`, but 11 tracked files still pointed at the old ops worktree's copy of `gpu.py`. A job launched from a shell that still used that path would fail with 127 (command not found), which already happened once in the ledger. Commit `5134284` makes this change:

| File | Change |
|---|---|
| `city/bodies/apply_core_data.sh` | `"$K/<old>"` → `"$K/ops/gpu.py"` (runs code: the queue-idle check) |
| `benchmarks/noise_check_turns.sh` | `GPU=` absolute path → `/Users/jaycewalzer/Desktop/kokopelli/ops/gpu.py` (runs code) |
| `filter_test/scripts/queue_all.sh` | both calls → `python3 ops/gpu.py` (runs code; relative as before, so it still assumes the repo root as cwd) |
| `city/agents/run_wm_life.sh`, `run_wm_lunch.sh` | usage comments only |
| `ops/status.py` | the "Live queue" hint line in the generated report |
| `life/architecture.py` | queue node: `branch_files` with the old paths → `files: ["ops/gpu.py", "ops/status.py"]`; its `why` said "Only on the feat/ops worktree, not merged", now "Merged into this checkout under ops/" |
| `city/bodies/PLAN.md`, `wm_multicontrol/BRIEF.md`, `cloud/README.md`, `benchmarks/HANDOFF.md` | doc command lines |

## Acceptance

- Acceptance grep (the exact command in the plan's P2-A section, plus `--exclude-dir=.venv --exclude-dir=models` because those symlinks point into the owner's data): before, 14 files; after, 3: `docs/FABLE_BRIEF.md` (allowed), `docs/FABLE_PLAN.md` and `docs/fable_log/P1-A.md`. The last two only quote the old path as the thing being fixed. P2-A doesn't own them, so they stay. The plan expected `docs/FABLE_LOG.md`, which became the per-package logs. This log names the path only in pieces, so it doesn't match.
- `bash -n` passes on all 5 edited `.sh` files.
- `tests.test_life_architecture`: 28 tests, OK (memguard peak 0.0 GB). `ops/tests`: OK.
- `make test-all`: exit 0, all suites OK (peak 18.3 GB, 387 s, waited 1313 s for memory). tests 550 OK (skipped 4, expected failures 2); runtime 100 OK; simworld 197 OK; ops 26 OK; benchmarks 198 OK (skipped 1). There was no pre-change run, so this has no before figure to compare against. The change only edits strings and one catalog entry.

## For the owner

- `life/architecture.py` still lists `branch_files` for other old worktrees (`wm-agent-loop`, `agent-a2d4…` benchmarks), and their `why` text still says "not merged". Those modules look merged now (`runtime/`, `benchmarks/` exist here). Fixing them is outside P2-A's goal, so I left them alone. They are a candidate for a later cleanup.
- `out/ops/MORNING.md` (gitignored) still needs the orchestrator's edit in main, as the plan says.
