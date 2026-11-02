# World Model: Synthetic Life

Base infrastructure for calling a local world model and LLM on Apple silicon.

| File | What it holds |
|---|---|
| `settings.py` | Which world model and LLM to use, and where they live |
| `world_model.py` | Calls NVIDIA Cosmos3-Nano |
| `llm_model.py` | Calls Qwen3-VL-8B-Instruct |
| `blend.py` | Crossfades world model clips into one video |
| `tests/` | One test file for each of the three above |

## Setup

Needs `uv`, `ffmpeg`, and the Cosmos3 MLX port installed in `~/cosmos3/cosmos3-mlx`.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/hf download Qwen/Qwen3-VL-8B-Instruct --local-dir models/Qwen3-VL-8B-Instruct
.venv/bin/hf download nvidia/Cosmos3-Nano --local-dir models/Cosmos3-Nano
```

## Use

```python
from blend import blend
from llm_model import ask, unload
from world_model import text_to_video

prompt = ask("Write a one-sentence video prompt about a lake at dawn.")
unload()
a = text_to_video(prompt, "out/a.mp4")
b = text_to_video(prompt, "out/b.mp4")
blend([a, b], "out/blended.mp4")
```

Each model peaks at about 18 GB, so unload the LLM before calling the world model.

## Test

The model tests call the real models and take a few minutes.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

`tests/test_continuous_video.py` is skipped by default. It generates a real 30 second video in `out/continuous_video/`, which takes about two hours and resumes if stopped.

```sh
RUN_LONG_TESTS=1 .venv/bin/python -u -m unittest tests.test_continuous_video -v
```
