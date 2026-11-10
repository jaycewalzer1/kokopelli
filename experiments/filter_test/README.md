# Sim-to-real filter test

**What it asks:** which model best repaints one 10-second SimWorld clip (a first-person walk along the sky bridge,
`prompt.txt`) as photoreal video, guided by the sim? Three runs on this Mac, all on the same clip:

1. Cosmos3-Nano (MLX, base model) repainting from the sim's depth, through `kokopelli/wm/world_filter.py` (`scripts/run_cosmos.py`).
2. SD1.5 + DMD (one step) + depth ControlNet from the sim's own depth (`scripts/run_sd.py --depth sim`).
3. The same SD1.5 setup on DepthAnythingV2's depth guessed from the sim's RGB (`scripts/run_sd.py --depth da`), to show whether
   real sim depth helps.

| File | What it holds |
|---|---|
| `scripts/capture.py`, `scripts/head.py` | Record the clip (RGB, depth, segmentation at 30 fps) from the packaged server on 9001, with a walking-head camera |
| `scripts/controls.py`, `scripts/preview_videos.py` | Each model's control video from the raw sim depth; watchable previews |
| `scripts/download.py` | Fetches the weights the test uses into the Hugging Face cache |
| `scripts/run_cosmos.py`, `scripts/run_sd.py` | The three runs |
| `scripts/queue_all.sh` | Puts the three runs on the GPU queue |

## Rerun

`bash experiments/filter_test/scripts/queue_all.sh` queues all three. The SD runs use their own venv,
`experiments/filter_test/.venv` (torch, diffusers; not tracked), the Cosmos run the repo's `.venv`. Capturing needs the packaged
server on port 9001 with nobody else connected, and `StopAgent` before closing (`AGENTS.md`). Note: `queue_all.sh` changes to
its folder's grandparent, which since the move to `experiments/` is `experiments/`, not the repo root; that needs fixing before
it is rerun.

## Results

`out/filter_test/` (not tracked): the clip in `test_clip/`, controls in `controls/`, one folder per run, logs in `logs/`. The
panel's Model runs page lists the runs.
