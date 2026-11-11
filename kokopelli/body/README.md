# kokopelli.body: a body the world sets and the agent feels

Body state (food, energy, warmth), the world's rules that move it, and the words an agent gets for it. Everything here is
a pure function: numbers in, text out, no model. The agent never sees a number and can't change its own state by saying
so. Spec: [`docs/M1_HUNGER_BENCHMARK.md`](../../docs/M1_HUNGER_BENCHMARK.md).

| File | What it holds |
|---|---|
| `state.py` | `Body`, drift over time, what cook, eat, give, rest and tea do, what the world refuses, and the drive |
| `cues.py` | The three delivery arms: `cue` (felt text), `label` ("You are very hungry.") and `none`; bands and three wordings each |
| `components.py` | The components a prompt's body section is built from: `Situation`, `Interoception`, `Contact`, and `Senses` to join them. Each has `pre_act(state)` and `update(event)` |
| `master.py` | `resolve(body, action)`: what the world makes of an attempt: done, refused with a reason, or not a body action |
| `egg.py` | The egg scene: who, where, the ask, the actions, and scoring a reply (gave, promised, declined, other) |
| `overlay.py` | For viewers: the true numbers next to the felt cue on a painted film, and three levels side by side |
| `voice.py` | For viewers: the agent's thoughts read aloud over its film (Kokoro-82M through mlx-audio). Never fed back |
| `_hash.py` | `stable_int`, a copy of the benchmarks' seed hash, held equal by `tests/body/test_hash.py` |

Imports: `kokopelli.settings`, the standard library, numpy and pillow only (a contract in `pyproject.toml`). The text
sweep that uses this is [`experiments/sensation/`](../../experiments/sensation/README.md); the closed-loop video run is
`kokopelli/agents/egg_wm.py`. Both build the body section from `components.py`. The component and game-master designs come
from Concordia; what was borrowed is in [`vendor/concordia_patterns/SOURCE.md`](../../vendor/concordia_patterns/SOURCE.md).

## Running

```sh
.venv/bin/python -m kokopelli.body.overlay one out/sensation/videos/<run>/starving   # CPU, needs ffmpeg
.venv/bin/python -m kokopelli.body.overlay triptych out/sensation/videos/<run>
```

`voice.py` loads a model, so it runs inside the queued video job (`kokopelli/agents/run_egg_videos.sh`), not on its own.
Tests: `tests/body/`, and `tests/agents/test_egg_wm.py` for the overlay and voice, through `make test-all`.
