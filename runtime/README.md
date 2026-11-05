# The agent loop

An agent lives 30 sim-minutes in a world model: 60 ticks of 30 sim-seconds. The sim holds the physical truth, the world model only draws it, and the agent's actions land on the sim.

## Try it

Run these from the repo root (or this worktree's root) with the repo's Python.

```sh
PY=.venv/bin/python
$PY -m runtime.run --ticks 60                       # all mocks, about a minute
$PY -m runtime.viewer runs/<run_id>                 # replay it in the browser
```

Things to try:

```sh
$PY -m runtime.run --ticks 60 --no-drift-control    # same seed, no re-anchoring: watch the drift line climb
$PY -m runtime.run --ticks 8 --context life --life-db out/overnight/latest/life.db --life-run 2   # real life tree text
$PY -m runtime.run --resume <run_id> --ticks 60     # continue a run from its last finished tick
```

Real models on a Mac, with the mock sim. Cosmos and Qwen each need about 18 GB, so stop other model jobs first. The `demo` preset renders 16 frames per tick, roughly 2 minutes, instead of a real 30 seconds, which took about 2 hours.

```sh
$PY -m runtime.run --ticks 3 --wm cosmos --wm-preset demo --agent qwen \
  --context life --life-db out/overnight/latest/life.db --life-run 2
```

## Using less RAM

On a 36 GB Mac the loop unloads Qwen before Cosmos renders, so they take turns. To need less:

```sh
$PY -m mlx_vlm.convert --hf-path models/Qwen3-VL-8B-Instruct --mlx-path models/Qwen3-VL-8B-Instruct-4bit -q --q-bits 4   # once
$PY -m runtime.run --ticks 3 --wm cosmos --agent qwen --low-memory --context life --life-db out/overnight/latest/life.db --life-run 2
```

`--low-memory` means smaller clips, 8-bit Cosmos and 4-bit Qwen. Measured on one short run, it halves the time and takes about 11 GB off Qwen's peak, but barely lowers Cosmos's: the runner loads the full model before shrinking it. The machine still peaked at 28 GB while Cosmos ran, about 15 GB above where it started. Use it for demos, not experiment results, because a quantized model behaves differently from the one being trained. Every tick logs the machine's peak RAM per stage; see the Timing tab in the viewer. SimWorld itself can't run on a Mac.

## On NVIDIA GPUs

`--wm cosmos_server --wm-url <vLLM-Omni server>` follows the model README's rollout, which conditions each chunk on one frame. A re-anchor there replaces that one frame, so it pulls harder than replacing the oldest of five, and may show as a jump. This has only been tested against a fake server.

The whole loop on PACE, after filling in `scripts/pace/env.sh` and the `CHANGE_ME` lines, and after `scripts/pace/wmloop_gate.sbatch` has shown SimWorld works. `runtime/SIMWORLD.md` has the first-run steps.

```sh
mkdir -p logs
WMLOOP_DRY_RUN=1 bash scripts/pace/wmloop_run.sbatch        # prints every command
WMLOOP_TICKS=10 sbatch scripts/pace/wmloop_run.sbatch       # the 5 minute run
```

On SimWorld the null-agent comparison doesn't run yet, because replays drift by an amount only a real run can measure. Asking to do something it can't, like interacting with a person, costs the agent its turn: the action becomes a `wait` and the refusal is in `last_result`.

## What each file does

| File | What it holds |
|---|---|
| `interfaces.py` | `PhysicsSim`, `WorldModel`, `AgentPolicy`, `ContextDB`, `EventLog` |
| `loop.py` | One tick, in order |
| `run.py` | The CLI |
| `prompt_builder.py`, `leak_guard.py` | Both prompts, and what keeps the future out of them |
| `actions.py` | The action schema and how replies get validated |
| `drift.py` | The drift score and the re-anchor rule |
| `event_log.py`, `replay.py` | The append-only log, and rebuilding a run from it |
| `checkpoint.py` | What a resume needs |
| `autonomy.py` | The comparison with an agent that always waits |
| `viewer.py`, `static/` | The replay page |
| `mocks/`, `adapters/` | The stand-ins and the real backends |

## How a tick goes

1. The sim applies the last action and advances 30 seconds, capturing at +15 and +30.
2. The world model prompt is built from the life tree at this moment, the physical state, and the last 5 frames as conditioning.
3. The world model renders chunk by chunk. Every 15 sim-seconds the newest frame is compared with the sim's render. Past the threshold, or after 60 sim-seconds, the oldest conditioning frame is replaced with the sim's.
4. The agent sees frames sampled from the clip, its own notes and its place in life, and returns JSON. One bad reply gets a retry; a second becomes `wait`.
5. Everything goes in `events.jsonl`, and a checkpoint is written.

## What the numbers mean, and what they don't

- **Drift on mocks proves the mechanism, not the method.** The mock world model is built to wander and to respond to re-anchoring, so the improvement shows that the plumbing works. Whether replacing one old frame steers real Cosmos is still untested.
- **Mock sim plus real Cosmos has no re-anchoring.** Its first run showed the mock's grid ghosting into the video, so this pairing now starts from the prompt alone with drift control off. Scores are logged but mean little: they need SimWorld renders.
- **The score is pixels only.** Depth and segmentation agreement and key-object presence are logged as `null`, because a generated frame has neither map. They need an estimator model.
- **"Differs from tree" is a stand-in.** The tree has no default action, so it uses the tree's own choice in the slot, mapped to the nearest action (`VERB_TO_ACTION` in `adapters/life_db.py`), or `wait` if it made none. On the mock context the defaults are a fixed script, so the number there carries no meaning. Ticks where bad replies forced a `wait` aren't counted.
- **The null agent comparison only runs on the mock sim for now.**
- **Cost reads $0** unless `gpu_dollars_per_hour` is set, since local compute has no bill. Seconds per stage are real.

## Tests

```sh
.venv/bin/python -W ignore -m unittest discover -s runtime/tests -t . -p 'test_[!s]*.py'    # everything but SimWorld
simworld/.venv/bin/python -W ignore -m unittest discover -s runtime/tests -t . -p 'test_simworld*.py'   # those need unrealcv
```
