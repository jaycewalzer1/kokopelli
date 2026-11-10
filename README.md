# Kokopelli

An agent living inside a world model: a Qwen agent whose life is written by a life generator, who sees only what Cosmos3-Nano
paints from a SimWorld city, and decides from that. Everything runs locally on Apple silicon, with PACE as the planned route for
NVIDIA-only parts. The plan behind it is [`docs/Kokopelli_Perspectives.pdf`](docs/Kokopelli_Perspectives.pdf).

Working here, human or agent: read [`AGENTS.md`](AGENTS.md) first (the GPU queue, memory rules, ports, who owns what).
[`CLAUDE.md`](CLAUDE.md) is how the owner wants to be taught, and [`DESIGN.md`](DESIGN.md) is the UI system every page follows.

## Layout

| Folder | What it holds |
|---|---|
| `kokopelli/` | The library, one installable package. Each subpackage has a README: [`wm/`](kokopelli/wm/README.md) (world-model and LLM runners, video helpers, control videos), [`loop/`](kokopelli/loop/README.md) (the 30-second agent loop), [`mind/`](kokopelli/mind/README.md) (feel, then decide), [`agents/`](kokopelli/agents/README.md) (the city agents), [`life/`](kokopelli/life/README.md) (life generator and dev panel), [`ops/`](kokopelli/ops/README.md) (GPU queue, memory guard, PACE), and `settings.py` (models, paths, tunables) |
| `experiments/` | Questions asked with the library, one README each: [`benchmarks/`](experiments/benchmarks/README.md), [`commons/`](experiments/commons/README.md), [`exp1/`](experiments/exp1/README.md), [`homeostatic/`](experiments/homeostatic/README.md), [`filter_test/`](experiments/filter_test/README.md), [`wm_multicontrol/`](experiments/wm_multicontrol/README.md) |
| `tools/` | Hand-run scripts: `city_build/` (builds the city in Unreal), `bodies/` (MetaHuman bodies), `realism/`, `moodboard/`, `pace/` (cluster scripts), `fable/` (`test_all.sh` and the fable pass's helpers), `reorg/` (the reorganization's move table), `smoke_entrypoints.sh` |
| `tests/` | The main test tree, mirroring `kokopelli/`. Experiments keep their own `experiments/*/tests`; `mac_server/tests` stays with the Unreal project |
| `data/` | Tracked inputs: the city plan `data/city/world.json`, and the moodboard pictures (untracked) |
| `docs/` | Notes that span packages (below); `docs/log/` is history |
| `simworld/`, `mac_server/`, `vendor/` | SimWorld (Python client and its venv), the Mac Unreal server, vendored upstream code |
| `ops/` | Two-line stand-ins for `kokopelli/ops/gpu.py` and `memguard.py`, for the Bash hook and old habits |
| `out/`, `models/` | Outputs and weights, not tracked |

Launch modules with `python -m kokopelli.<package>.<module>` from the repo root. `pyproject.toml` also installs `koko-gpu`,
`koko-ram`, `koko-memguard`, `koko-panel`, `koko-video-check`, `koko-transfer`, `koko-transfer-multi` and `koko-filter`.

## Setup

Needs `uv`, `ffmpeg`, and the Cosmos3 MLX port installed in `~/cosmos3/cosmos3-mlx`.

Dependencies are pinned in `pyproject.toml` and `uv.lock`. The three Python environments and why each exists are in
[`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md).

```sh
uv sync
.venv/bin/hf download Qwen/Qwen3-VL-8B-Instruct --local-dir models/Qwen3-VL-8B-Instruct
.venv/bin/hf download nvidia/Cosmos3-Nano --local-dir models/Cosmos3-Nano
```

Then `make panel` opens the dev panel ([`kokopelli/life/`](kokopelli/life/README.md)). A first call to the models is in
[`kokopelli/wm/README.md`](kokopelli/wm/README.md). Model jobs go through the GPU queue (`AGENTS.md`).

## Test

```sh
make test-all        # every suite, one line each; it takes a memory claim and waits its turn
```

`tools/fable/test_all.sh <suite>` runs one suite. Never run `unittest` or `pytest` bare (`AGENTS.md`, "Memory rules"). The
real-model tests run only with `RUN_MODEL_TESTS=1`, through the queue. `tests/test_continuous_video.py` is skipped by default:
with `RUN_LONG_TESTS=1` it generates a real 30-second video in `out/continuous_video/`, which takes about two hours and resumes
if stopped. `tools/smoke_entrypoints.sh` checks that every entry point starts, in all three interpreters.

## Documents

Notes that span packages, in `docs/`:

| File | What it holds |
|---|---|
| [`ENVIRONMENTS.md`](docs/ENVIRONMENTS.md) | The three Python environments |
| [`SIM_TRANSFER_MLX.md`](docs/SIM_TRANSFER_MLX.md) | The Sim-Transfer port on MLX and every deviation from NVIDIA's reference |
| [`PAINT_PROFILE.md`](docs/PAINT_PROFILE.md), [`MOSAIC.md`](docs/MOSAIC.md) | Where paint time goes; stillness versus elapsed time |
| [`GPU_FAILURES.md`](docs/GPU_FAILURES.md) | Why GPU queue jobs failed, up to 2026-11-09 |
| [`OUT_LAYOUT.md`](docs/OUT_LAYOUT.md) | How `out/` is organised and the retention rule |
| [`exp1_phase1.md`](docs/exp1_phase1.md), [`exp1_report.md`](docs/exp1_report.md), [`homeostatic_rl_map.md`](docs/homeostatic_rl_map.md) | Experiment 1's write-ups and the code map |
| [`REORG_PLAN.md`](docs/REORG_PLAN.md), [`REORG_EXECUTION.md`](docs/REORG_EXECUTION.md) | The reorganization's plan and brief; progress in [`docs/log/reorg/PROGRESS.md`](docs/log/reorg/PROGRESS.md) |
| `docs/log/` | History: the fable pass (`fable/`), finished briefs and handoffs (`bodies/`, `realism/`, `wm_multicontrol/`), the reorganization (`reorg/`) |

Notes kept beside the code they describe (beyond the READMEs above):

- Agent loop: [`THIRTY_MIN.md`](kokopelli/loop/THIRTY_MIN.md), [`SIMWORLD.md`](kokopelli/loop/SIMWORLD.md), [`HANDOFF.md`](kokopelli/loop/HANDOFF.md). Mind: [`OPEN_DECISIONS.md`](kokopelli/mind/OPEN_DECISIONS.md), [`MEASUREMENTS.md`](kokopelli/mind/MEASUREMENTS.md).
- Ops: [`cloud/README.md`](kokopelli/ops/cloud/README.md), [`plans/COST_AND_LIFE_PLAN.md`](kokopelli/ops/plans/COST_AND_LIFE_PLAN.md). Prompts: [`kokopelli/wm/controls/prompts/README.md`](kokopelli/wm/controls/prompts/README.md).
- Bodies: [`PLAN.md`](tools/bodies/PLAN.md), [`ANIMATION.md`](tools/bodies/ANIMATION.md), [`METAHUMAN.md`](tools/bodies/METAHUMAN.md), [`LOG.md`](tools/bodies/LOG.md).
- City: [`tools/city_build/kinds/README.md`](tools/city_build/kinds/README.md) and its [`CATALOG.md`](tools/city_build/kinds/CATALOG.md); the look of the city, [`tools/moodboard/VIBE.md`](tools/moodboard/VIBE.md); realism pilot assets and licences, [`tools/realism/ASSETS.md`](tools/realism/ASSETS.md).
- Experiments: see each experiment's README for its pre-registration, handoff and report.
- Skills for repeated workflows: [`sim-capture`](.claude/skills/sim-capture/SKILL.md), [`paint-clip`](.claude/skills/paint-clip/SKILL.md), [`closed-loop-run`](.claude/skills/closed-loop-run/SKILL.md).
