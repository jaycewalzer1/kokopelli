# kokopelli.wm: world model and LLM runners

The world-model side of Kokopelli: Cosmos3-Nano runners (text to video, Sim-Transfer, streaming), the Qwen runner, and the
video helpers around them. `__init__.py` imports nothing on purpose: the Cosmos venv imports `kokopelli.wm` to start a worker
and must not pull in anything heavy.

| File | What it holds |
|---|---|
| `world_model.py` | Calls base Cosmos3-Nano (`text_to_video` and friends). Cosmos runs from its own environment |
| `llm_model.py` | Calls Qwen3-VL-8B-Instruct. The first call loads it; `unload()` frees it |
| `world_transfer.py` | Cosmos3-Nano-Sim-Transfer on MLX: repaints one sim control video as RGB. Deviations from NVIDIA's reference: [`docs/SIM_TRANSFER_MLX.md`](../../docs/SIM_TRANSFER_MLX.md) |
| `world_transfer_multi.py` | Variant A: several weighted controls on Sim-Transfer. The default for sim-driven runs (see `AGENTS.md`) |
| `world_multicontrol_base.py` | Variant B: multi-control on the base model. Reference only |
| `world_stream.py`, `world_stream_multi.py` | Sim-Transfer as a causal rollout fed step by step; the multi version shares one set of weights between several rollouts |
| `world_filter.py` | Repaints a control video with base Cosmos3-Nano (the older filter path) |
| `edges.py` | Edge maps of sim frames |
| `blend.py` | Crossfades clips into one video |
| `video_check.py` | Mosaic and drift scores for a painted video, CPU only |
| `manifest.py` | The `manifest` block every output sidecar carries (commit, weights, seed, prompt, controls) |
| `controls/` | Builds the control videos (depth, seg, edge, blur) from SimWorld shots; `controls/prompts/` holds the prompts ([README](controls/prompts/README.md)) |

## Running

Model jobs go through the GPU queue (`kokopelli/ops/gpu.py run`, see `AGENTS.md`). Launch modules with `-m` from the repo root,
for example `python -m kokopelli.wm.world_transfer_multi --help`, or the installed commands `koko-transfer`,
`koko-transfer-multi`, `koko-filter` and `koko-video-check` (`pyproject.toml`). The Sim-Transfer runners use the Cosmos venv
(`~/cosmos3/cosmos3-mlx/.venv`); the environments are described in [`docs/ENVIRONMENTS.md`](../../docs/ENVIRONMENTS.md).

Each model peaks at about 18 GB, so unload the LLM before calling the world model:

```python
from kokopelli.wm.blend import blend
from kokopelli.wm.llm_model import ask, unload
from kokopelli.wm.world_model import text_to_video

prompt = ask("Write a one-sentence video prompt about a lake at dawn.")
unload()
a = text_to_video(prompt, "out/a.mp4")
b = text_to_video(prompt, "out/b.mp4")
blend([a, b], "out/blended.mp4")
```

Measurements behind the current defaults: [`docs/PAINT_PROFILE.md`](../../docs/PAINT_PROFILE.md) (paint time),
[`docs/MOSAIC.md`](../../docs/MOSAIC.md) (stillness and mosaic), and the multi-control report in
[`experiments/wm_multicontrol/`](../../experiments/wm_multicontrol/README.md).

Tests: `tests/test_world_model.py`, `tests/test_llm_model.py` and others under `tests/` (the real-model ones only with
`RUN_MODEL_TESTS=1`, through the queue). Run them with `make test-all`.
