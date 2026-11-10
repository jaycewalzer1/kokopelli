---
name: closed-loop-run
description: Run the two-agent lunch closed loop (Mara and Iris on Qwen3-VL-8B 4-bit, each seeing only her own Cosmos3-Nano-Sim-Transfer film painted live from SimWorld on port 9001) through the GPU queue. Use for real quality tests of agents inside the world model.
---

# Closed-loop run (two agents at lunch)

Distilled from `kokopelli/agents/run_wm_lunch.sh`, `kokopelli/agents/lunch_wm.py` and the queued `wmbodies_demo` job (`tools/bodies/run_demo_lunch.sh`). Nothing new.

**Models and weights:**
- Agents: Qwen3-VL-8B-Instruct 4-bit MLX, `models/Qwen3-VL-8B-Instruct-4bit` (`lunch_wm.py --weights`, the default), loaded once for both agents.
- World model: NVIDIA Cosmos3-Nano-Sim-Transfer, `models/Cosmos3-Nano-Sim-Transfer`, via `world_stream_multi.py` (Variant A, four controls blur/seg/depth/edge at 0.25 each by default). Weights are bf16 unless `--quantize 8` is passed, and the owner's default is 8-bit, so pass it.
- Sim: the packaged SimWorld server on 9001 (`mac_server/Packaged/`).

## Rules that apply

- This is the quality test: agents decide from the painted frame. `--fake-wm` (a blend of the controls, no world model) is a dry run only and must never be reported as the real one.
- **Mouse:** moving the mouse during a packaged-server run turns camera 0. Ask the owner to step away first.
- 9001 takes one client. If something already listens, the script reuses it, so check who owns it first.
- `lunch_wm.py` defaults to `--size 448x256`; 832x480 is the trained canvas (about 3x slower). A run below 832x480 or below 8-bit has lowered size or precision: say so in `--about`, the report and the sidecar.

## Queue it (from the repo root; never run bare)

```
K=/Users/jaycewalzer/Desktop/kokopelli; NAME=wmlunch_<run>
python3 kokopelli/ops/gpu.py run --name $NAME --priority 32 --max-hours 4 --cwd $K \
  --about "Closed loop: Mara and Iris (Qwen3-VL-8B 4-bit) meet for lunch at The Kettle, each seeing only her own Cosmos3-Nano-Sim-Transfer film (8-bit, 4 controls at 0.25, <size>): <why>" \
  --output out/city_agents/$NAME -- \
  kokopelli/agents/run_wm_lunch.sh --minutes 5 --quantize 8 --size 832x480 --out $K/out/city_agents/$NAME
```
The script starts the server minimized only if 9001 is free (and stops only a server it started), claims 10 GB for it with `ram_share.py claim`, builds the city with `simworld/.venv/bin/python -I tools/city_build/build_city.py`, then runs `ram_share.py hold --name wmlunch_agents --gb 24 -- .venv/bin/python kokopelli/agents/lunch_wm.py --port 9001 ...`.

Other `lunch_wm.py` flags: `--fps 24 --step-s 10 --window 24 --sink 1 --seed 2025 --clock 12:20 --meet kettle_cafe --first-start fern_common --second-start fern_bakery --no-npcs`. The bodies demo wrapper is `tools/bodies/run_demo_lunch.sh` with the same flags plus `--deadline HH:MM`.

Stop with `gpu.py stop --name $NAME`, never `pkill` a model process. Dry test without GPU or server: `python3 kokopelli/ops/memguard.py run --name lunch-test --gb 2 -- .venv/bin/python -m unittest tests.test_city_lunch`.

## Outputs

`out/city_agents/<run>/` (default `<stamp>_lunch`): `run.json` (both models and weight paths, `fake_world_model`, control weights, `quantize`, size, seeds) and `film/{side_by_side,<agent>}.mp4`, each with a `.json` copy of it. Known issue: painted films have broken into a mosaic about 52 s in (see `out/bodies/demo/README.md`), so watch the whole film before calling a run good.
