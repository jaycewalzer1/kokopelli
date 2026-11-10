---
name: paint-clip
description: Paint a recorded SimWorld clip into realistic video with Cosmos3-Nano-Sim-Transfer (Variant A, world_transfer_multi.py) using the owner's default of four controls at 0.25 each and 8-bit weights, queued through kokopelli/ops/gpu.py. Use for open-loop paints of existing control videos.
---

# Paint a clip (Variant A, four controls, 8-bit)

Distilled from `experiments/wm_multicontrol/run_a.sh` and the queued `wmmc_a4_full_8bit` job (ledger, 2026-11-08). Nothing new.

**Model and weights:** NVIDIA Cosmos3-Nano-Sim-Transfer, MLX port, weights `models/Cosmos3-Nano-Sim-Transfer` (`kokopelli.wm.world_transfer.MODEL_DIR`), quantized to 8-bit at load (`--quantize 8`). Runner venv `~/cosmos3/cosmos3-mlx/.venv/bin/python` with the repo and `~/cosmos3/cosmos3-mlx` on `PYTHONPATH`. Name the model and weights in `--about`; the script writes `<output>.json` naming them too.

**Default (owner's rule):** all four controls (blur, seg, depth, edge at 0.25 each), 8-bit, 832x480. Change only if the owner says so; if size or precision is lowered, say so in `--about`, the report and the sidecar (`--extra`). A paint of recorded controls is open-loop: it is not a closed-loop quality test (see `closed-loop-run`).

## Inputs

- Controls: `out/city_wm/bridge/controls/832x480/{blur,seg,depth,edge}.mp4` (from the `sim-capture` skill).
- Prompt: a variant from `kokopelli/wm/controls/prompts/bridge.json`. The a4 runs use `b_light`:
  ```
  P="$(python3 -c 'import json,sys;print(next(v["prompt"] for v in json.load(open(sys.argv[1]))["variants"] if v["id"]=="b_light"))' kokopelli/wm/controls/prompts/bridge.json)"
  ```

## Queue it (from the repo root; never run bare)

```
K=/Users/jaycewalzer/Desktop/kokopelli; C=$K/out/city_wm/bridge/controls/832x480; NAME=wmmc_<run>
python3 kokopelli/ops/gpu.py run --name $NAME --priority 25 --max-hours 1 --cwd $K \
  --about "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, 8-bit), 4 controls at 0.25, 832x480, 150 frames of the bridge clip: <why>" \
  --output out/wm_multicontrol/$NAME -- \
  python3 kokopelli/ops/ram_share.py hold --name $NAME --gb 20 -- env PYTHONPATH=$K:$HOME/cosmos3/cosmos3-mlx $HOME/cosmos3/cosmos3-mlx/.venv/bin/python \
  -m kokopelli.wm.world_transfer_multi "$P" \
  --control blur=$C/blur.mp4 --control seg=$C/seg.mp4 --control depth=$C/depth.mp4 --control edge=$C/edge.mp4 \
  --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25 \
  --output out/wm_multicontrol/$NAME/$NAME.mp4 --size 832x480 --frames 150 --seed 2025 --window 51 --sink 1 --quantize 8
```
Use `/Users/jaycewalzer/Desktop/kokopelli/kokopelli/ops/gpu.py` when the shell is elsewhere. `gpu.py status` shows the line; `gpu.py stop --name $NAME` ends it. Never `pkill` the model process.

Reference measurement (one clip, one stream, recorded controls): 150 frames at 832x480, 8-bit took 1782 s and peaked at 19.9 GB (`out/wm_multicontrol/a4_full_8bit/`).

## Short variants

`sh experiments/wm_multicontrol/run_a.sh a1|a2|a3|a4_full` (17-frame tests and the bf16 full run) also go through `gpu.py run`. They predate the 8-bit default and pass no `--quantize`, so they run bf16. Since the move to `experiments/` the script takes `experiments/` for the repo root; see `experiments/wm_multicontrol/README.md` before using it.
