# kokopelli.mind: feel, then decide

Gives an agent an inner life. `FeelingAgent` wraps any agent of the agent loop (`kokopelli/loop/`): each tick it says what
changed, updates how it feels from that, and decides only at a decision point. A feeling shapes only the agent's own later
prompts; it is never a score.

| File | What it holds |
|---|---|
| `feeling.py` | `FeelingAgent`, the change and appraisal prompts, the decision-point rule |
| `actions.py` | The action schema and how replies get validated (used by the loop too) |
| `variables.py` | Planned body variables, comments only; nothing reads it |
| [`OPEN_DECISIONS.md`](OPEN_DECISIONS.md) | The defaults chosen so work could continue, and what is still the owner's to decide |
| [`MEASUREMENTS.md`](MEASUREMENTS.md) | What the mind loop costs and what Qwen did, from the first real runs (`out/mind/qwen_8`, `out/mind/qwen_90`) |

## Running

```sh
.venv/bin/python -m kokopelli.loop.run_mind --ticks 60 --out out/mind/mock_60   # mock agent, mock world
python -m kokopelli.loop.mind_check out/mind/qwen_8                            # reads a run, no model
```

A run with `--agent qwen` loads Qwen, so it goes through the GPU queue (`kokopelli/ops/gpu.py run`, queue priority 45). The
launchers that wire the mind into the loop live in the loop, so `mind` never imports `loop`: `kokopelli/loop/run_mind.py`
(runs the loop with a `FeelingAgent`, mock or Qwen, `--weights` for a fused training run), `kokopelli/loop/mind_check.py`
(do feelings follow events, does a feeling change the next action; `--flip` asks the model again) and
`kokopelli/loop/mind_change_check.py` (does real Qwen notice real changes and ignore non-changes).

Tests: `tests/test_mind.py`, through `make test-all`. Outputs go to `out/mind/`.
