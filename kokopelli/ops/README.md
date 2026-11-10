# kokopelli.ops: the GPU queue, memory guard and morning report

What keeps a 36 GB Mac from running two model jobs or too much heavy work at once, and what reports on it. `gpu.py`,
`memguard.py` and `ram_share.py` use only the standard library and run under the system `python3` (the Bash hook, the watchdog
and the Makefile call them without a venv), so `__init__.py` imports nothing. `ops/gpu.py` and `ops/memguard.py` at the repo
root are two-line stand-ins for these files.

| File | What it holds |
|---|---|
| `gpu.py` | The GPU queue: one model job at a time, in priority order, with a ledger of every job (`out/ops/gpu_ledger.jsonl`). `koko-gpu` |
| `memguard.py` | The gate for heavy work that isn't a queue job (tests, builds, linters), and the overnight watchdog (`memguard.py watch`). `koko-memguard` |
| `ram_share.py` | Memory claims shared between queue jobs and heavy work the queue can't see, such as an Unreal server. `koko-ram` |
| `status.py` | Writes `out/ops/MORNING.md` from evidence on disk; `--tests` also reruns the suites |
| `summarize.py` | A short summary and rating for a finished queue job, for the panel's GPU tab |
| `out_report.py` | Read-only report on `out/` against the retention rule in [`docs/OUT_LAYOUT.md`](../../docs/OUT_LAYOUT.md) |
| `cloud/` | Running a queue job on PACE instead of the Mac ([README](cloud/README.md)) |
| [`plans/COST_AND_LIFE_PLAN.md`](plans/COST_AND_LIFE_PLAN.md) | Cost and longer-life test plan (2026-11-05); the morning report links it |
| `tests/` | `test_gpu.py`, `test_memguard.py` (phase 7 of the reorganization moves them under `tests/`) |

## Use

```sh
python3 kokopelli/ops/gpu.py status                                  # who has the GPU and why each job waits
python3 kokopelli/ops/gpu.py run --name NAME --priority N --max-hours H --cwd DIR --about "WHAT AND WHY" --output PATH -- CMD
python3 kokopelli/ops/memguard.py run --name NAME --gb N -- CMD       # heavy work outside the queue
python3 kokopelli/ops/memguard.py status                             # memory, swap, and who holds a claim
python3 kokopelli/ops/ram_share.py hold --name NAME --gb N -- CMD     # claim memory for a command the queue can't see
```

The rules for using them (priorities, stopping jobs, ports) are in [`AGENTS.md`](../../AGENTS.md). Why queue jobs failed
before: [`docs/GPU_FAILURES.md`](../../docs/GPU_FAILURES.md). Backing up `out/`: [`docs/log/fable/2026-11-09-OUT_BACKUP.md`](../../docs/log/fable/2026-11-09-OUT_BACKUP.md)
(a proposal). Tests run in the `ops` suite of `make test-all`.
