# kokopelli.mind: feel, then decide

Gives an agent an inner life. `FeelingAgent` wraps any agent of the agent loop (`kokopelli/loop/`): each tick it says what
changed, updates how it feels from that, and decides only at a decision point. A feeling shapes only the agent's own later
prompts; it is never a score.

| File | What it holds |
|---|---|
| `feeling.py` | `FeelingAgent`, the change and appraisal prompts, the decision-point rule |
| `run.py` | Runs the agent loop with a `FeelingAgent` (mock or Qwen, `--weights` for a fused training run) |
| `check.py` | Reads a finished run: do feelings follow events, and does a feeling change the next action (`--flip` asks the model again) |
| `change_check.py` | Does real Qwen notice real changes and ignore non-changes |
| `variables.py` | Planned body variables, comments only; nothing reads it |
| [`OPEN_DECISIONS.md`](OPEN_DECISIONS.md) | The defaults chosen so work could continue, and what is still the owner's to decide |
| [`MEASUREMENTS.md`](MEASUREMENTS.md) | What the mind loop costs and what Qwen did, from the first real runs (`out/mind/qwen_8`, `out/mind/qwen_90`) |

## Running

```sh
.venv/bin/python -m kokopelli.mind.run --ticks 60 --out out/mind/mock_60     # mock agent, mock world
python -m kokopelli.mind.check out/mind/qwen_8                                # reads a run, no model
```

A run with `--agent qwen` loads Qwen, so it goes through the GPU queue (`kokopelli/ops/gpu.py run`, queue priority 45). The
docstrings of `run.py` and `change_check.py` still put the old agent-loop worktree on `PYTHONPATH`; the loop is now in this
checkout (`kokopelli/loop/`). Phase 3 of the reorganization moves the mind-and-loop launcher; check `run.py`'s location after it.

Tests: `tests/test_mind.py`, through `make test-all`. Outputs go to `out/mind/`.
