# Why GPU queue jobs failed (ledger up to 2026-11-09)

Source: `out/ops/gpu_ledger.jsonl` (93 finished jobs) and the tails of `out/ops/job_logs/*.log`. Of 24 non-zero exits,
4 were exit 75 (a polite yield) and 5 were stops the owner asked for (`stopped: true`). That leaves 15 real failures,
21.3 hours of queue time. They come down to 4 causes.

| Cause | Jobs | Hours | Fix |
|---|---|---|---|
| A. The command couldn't start as written | 2 | 0.0 | `gpu.py check`, which `run` now does before queueing (exit 127 only; see below) |
| B. A bug in the job's script, hit in the first 2 minutes | 5 | 0.07 | Not fixable in the queue. `gpu.py run --dry-run` finds it first for scripts that honor `KOKO_DRY_RUN` |
| C. SIGTERM from outside the queue | 7 | 18.49 | Fixed on 2026-11-08 by keepers and `gpu.py stop` (`dc985ea`). The ledger now names such a signal |
| D. SIGKILL, sender unknown | 1 | 2.71 | Not fixable here. The keeper's swap readings and `outside_signal` make the next one diagnosable |

## The 15 jobs

| Job | Exit | Ran | Cause | What the log says |
|---|---|---|---|---|
| `mind_change_check` | 127 | 0 s (after a 150 s wait) | A | `env PYTHONPATH=...` was passed as one word, so no such program existed |
| `edge_filter_long` | 2 | 0 s (after a 195 s wait) | A | `world_filter.py: error: the following arguments are required: --model-dir` |
| `wmloop_demo_lowmem` | 1 | 1.5 min | B | `condition_video needs 1 + 4n frames, got 3` |
| `bridge_simtransfer_5s` | 1 | 0 min | B | `city/wm/prompts/bridge.json` had become a list; the script indexed it by name |
| `wmbodies_demo` (1st) | 1 | 1.0 min | B | relative `--out` doubled into `out/bodies/demo/runs/wm/wm/in_mara_00001_blur.npy` |
| `wmbodies_demo` (2nd) | 1 | 1.1 min | B | Qwen got image path `None` (`Failed to load image from None`) |
| `commons_bench` | 1 | 0.6 min | B | `BatchGenerator.__init__() got an unexpected keyword argument 'temperature'` (mlx_vlm API changed) |
| `sim_transfer_bench` | -15 | 0.4 min | C | log empty; a scratchpad script |
| `wmmc_b4_full` | -15 | 8.8 h | C | ended cleanly at step 39 of 50, about 760 s per step |
| `exp1_lived_s0_lr2e-5_resume` | -15 | 8.7 h | C | ended cleanly after "morning 31" |
| `wmbodies_demo` (3rd to 6th) | -15 | 15.7, 15.9, 11.8, 12.1 min | C | each re-queued within 12 s with changed flags: a session stopping and restarting its own job |
| `exp1_lived_s0_lr2e-5` | -9 | 2.7 h | D | ended cleanly after "morning 19"; no machine readings then |

## Notes per cause

**A.** `gpu.py check` refuses `mind_change_check`'s command in 0.04 s ("command not found"). Before, it waited 150 s for
its turn and then failed. `edge_filter_long`'s missing argument isn't caught: the check never runs the job's code
(that would load a model), so argument errors still need a dry run, and `world_filter.py` doesn't honor `KOKO_DRY_RUN`.

**B.** These are bugs in each job's own script, and each cost about a minute of queue time. The queue can't find them
without running the job. `--dry-run` runs the job cut to one latent: `core/world_transfer_multi.py` and
`python -m core.world_stream_multi --dry-run` honor it. Other scripts run in full under `--dry-run` until they read
`KOKO_DRY_RUN` too (`city/agents/lunch_wm.py` and `runtime.run` are the obvious next ones).

**C.** All 7 ended before 2026-11-08 11:22, when keepers arrived. Before that, the only way to end a job was to kill
its process by hand, and the ledger couldn't tell that from a crash. The long ones (8.8 h and 8.7 h) were probably
deliberate stops of runs going too slowly. This can't be confirmed now. None has happened since keepers arrived.
The `pkill -f "SimWorld.*-cvport=$PORT"` lines in the run scripts don't match a job's own command line, so they aren't
the sender. Now a job that ends on a signal the queue didn't send gets `outside_signal` in its `finished` ledger
event and a line at the end of its log.

**D.** The log ends mid-run with no error, so it wasn't a crash in Python. Either the system's out-of-memory killer
(jetsam) or a hand `kill -9` sent the SIGKILL. This was before the keeper took machine readings, so swap at the time is
unknown. Since then each job's `.metrics.jsonl` records swap and job memory every 15 s.
