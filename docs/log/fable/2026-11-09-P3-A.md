# P3-A: GPU failure causes and a dry run

Branch `fable/P3-A`, cut from `integration/fable` at `6479b67`. Root modules were already in `core/` (with root shims).

## Failure causes

`docs/GPU_FAILURES.md` holds the table. The 15 real failures (21.26 h) come down to 4 causes:

- **A. Command can't start** (2 jobs, 0.0 h): exit 127 (`"env PYTHONPATH=..."` passed as one word) and exit 2 (argparse: missing `--model-dir`). Fix: `gpu.py check`, which `run` now does before queueing. It catches the 127 but not the argparse error, because the check never runs job code.
- **B. Script bug in the first 2 minutes** (5 jobs, 0.07 h): not fixable in the queue. `--dry-run` finds these first for scripts that honor `KOKO_DRY_RUN`.
- **C. SIGTERM from outside the queue** (7 jobs, 18.49 h): all before keepers (`dc985ea`, 2026-11-08 11:22), none since. The ledger now gets `outside_signal` on any such ending.
- **D. SIGKILL, sender unknown** (1 job, 2.71 h): not fixable here. Jetsam or a hand `kill -9`, with no readings from that time.

## What changed

- `ops/gpu.py` (nothing in `status()`):
  - `preflight()` and a new `gpu.py check [--cwd] [--output] [--gb] -- CMD` subcommand. The check unwraps `env K=V` and `ram_share.py`/`memguard.py ... --` wrappers, then checks that the cwd exists, the executable resolves (relative to cwd), a `-m` module can be found by the job's own interpreter (`importlib.util.find_spec`, honoring `-I/-E/-s/-S`, never importing the module itself), a script exists and compiles under that interpreter, and each output's nearest existing folder is writable. Only `check` tests GB free.
  - `run` runs the same pre-flight (memory excluded, since `--gb` waits in line) and refuses with exit 2. `--no-check` skips it.
  - `run --dry-run` sets `KOKO_DRY_RUN=1` in the job's environment (ticket `env`, applied by the keeper), prefixes `--about` with `[dry run]`, defaults `--max-hours` to 0.5, and marks the `queued` and `finished` ledger events `dry_run: true`.
  - The keeper writes `outside_signal: "SIGTERM"` (etc.) when a job ends on a signal the queue didn't send, and adds a line to the job log.
- `core/world_transfer_multi.py`: only a module-top `DRY_RUN` constant, a `--dry-run` argparse flag, `dry_run_args()` and one line in `main()`. A dry run uses `frames=1` (latent 0) and writes `<stem>.dryrun.mp4` beside `--output`, so it never overwrites a real result. The sidecar gets `"dry_run": "dry run, 1 chunk"` through the existing `--extra` merge, so the sidecar function is untouched (P3-E1 owns it).
- `core/world_stream_multi.py`: only a module-top `DRY_RUN` constant, a `dry_run()` entry above `__main__`, and an `elif` in `__main__`. `python -m core.world_stream_multi --dry-run [--fake] [--out D] [--quantize 8] [--size 448x256]` opens one stream (four controls at 0.25), pushes one grey frame, expects one painted frame back, and writes `D/dry_run.json` (`"dry_run": "dry run, 1 chunk"`; `fake: true` for the stand-in). The push loop and the worker are untouched (P3-D owns them).
- Tests: `ops/tests/test_gpu.py` +5 (check: bad cwd/command in < 5 s, module/script/compile/wrapper, unwritable output and memory; a job failing the check is never queued; dry run gets the flag, the limit and the labels). `tests/test_gpu_keeper.py` +5 (outside signal named in the ledger, unwrap, python_target, transfer dry-run args, stream dry run with the fake worker).
- `docs/GPU_FAILURES.md` (new).

## Numbers

- Bad path: the historic `mind_change_check` command waited 150 s for its turn and then exited 127. Now `gpu.py check` refuses it in 0.04 s, and `run` refuses it before queueing (test: under 5 s, no ledger entry).
- Single modules (memguard, peak 0.1 GB): `ops.tests.test_gpu` 14 → 19 OK; `tests.test_gpu_keeper` 12 → 17 OK.
- Fake stream dry run: exit 0, 1 frame in, 1 out, 0.1 s.
- ruff check: clean on all 5 touched .py files.
- `make test-all` (one run, 364 s, peak 1.1 GB, exit 0). Before (P2-D's run) → after: tests 550 OK (10 skipped, 2 xfail) → 555 OK (10 skipped, 2 xfail); runtime 100 → 100; simworld 197 → 197; ops 26 → 31; benchmarks 198 (1 skipped) → 198 (1 skipped). The +5 and +5 are exactly the new tests; nothing that already existed changed.

## GPU dry run (not queued; for the orchestrator after merge)

Variant A, 8-bit, four controls at 0.25, bridge controls, 832x480, one latent. `gpu.py check` on this command passed everything except memory: 6.9 GB was free during my test run, against `--gb 20`.

```
K=/Users/jaycewalzer/Desktop/kokopelli; C=$K/out/city_wm/bridge/controls/832x480; NAME=fable_P3-A_dryrun_a4_8bit
P="$(python3 -c 'import json,sys;print(next(v["prompt"] for v in json.load(open(sys.argv[1]))["variants"] if v["id"]=="b_light"))' $K/city/wm/prompts/bridge.json)"
python3 $K/ops/gpu.py run --dry-run --name $NAME --priority 35 --max-hours 0.5 --cwd $K \
  --about "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, 8-bit), 4 controls at 0.25, 832x480, bridge clip, ONE latent: checks P3-A's dry-run path end to end; sidecar must say dry run, 1 chunk" \
  --output out/wm_multicontrol/$NAME -- \
  python3 ram_share.py hold --name $NAME --gb 20 -- env PYTHONPATH=$HOME/cosmos3/cosmos3-mlx $HOME/cosmos3/cosmos3-mlx/.venv/bin/python \
  world_transfer_multi.py "$P" \
  --control blur=$C/blur.mp4 --control seg=$C/seg.mp4 --control depth=$C/depth.mp4 --control edge=$C/edge.mp4 \
  --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25 \
  --output out/wm_multicontrol/$NAME/$NAME.mp4 --size 832x480 --seed 2025 --window 51 --sink 1 --quantize 8
```
Expected output: `out/wm_multicontrol/$NAME/$NAME.dryrun.mp4` (1 frame) and its `.json` with `"dry_run": "dry run, 1 chunk"` and `"frames": 1`. Pass if exit 0.

## Doubts / owner decisions

- A one-frame paint (latent 0 only) has never run on the real model. If `decode_chunked`/`save_mp4` mishandle a single frame, the GPU dry run will fail for that reason, not because of the job. Then use 5 frames (2 latents) in `dry_run_args`.
- `KOKO_DRY_RUN` passes through `transfer_video_multi()`'s subprocess. A caller that expects the exact `--output` path would then miss it, because the dry run writes `.dryrun.mp4`. No caller runs under a dry run today.
- `city/agents/lunch_wm.py` (closed loop) and `runtime.run` don't read `KOKO_DRY_RUN`, so `gpu.py run --dry-run` on them runs in full, with a 0.5 h limit. Out of my scope. That's the next step if wanted.
- The 7 cause-C SIGTERMs are probably deliberate hand stops from before `gpu.py stop` existed. The ledger can't confirm it.
- `run`'s own exit status for a signal-killed job is the shell's 256-n (241 for -15), which predates this change. The ledger has the real -15.
- The pre-flight could wrongly refuse a valid job (for example a module only reachable through something the check doesn't reproduce). `--no-check` is the escape hatch.
- The world-model dry-run tests live in `tests/test_gpu_keeper.py`, because that is the test file this package owns.
