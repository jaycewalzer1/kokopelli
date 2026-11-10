---
name: sim-capture
description: Record a SimWorld walk clip (rgb, depth, segmentation at 30 fps) from the packaged server on port 9001 and turn it into Cosmos Sim-Transfer control videos (blur, seg, depth, edge). Use when a new sim shot or new controls are needed before painting. No model runs.
---

# Sim capture and control videos

Distilled from `filter_test/scripts/capture.py` and `city/wm/controls.py`. Nothing new: run those scripts as they are.

**Model and weights:** none. No Cosmos, no Qwen. The packaged SimWorld server renders; both steps are CPU-side.

## Before you start

- Port 9001 is the packaged server (`mac_server/Packaged/`), **one client at a time**. Check `lsof -iTCP:9001 -sTCP:LISTEN -P` and ask the session that owns it before connecting.
- **Mouse:** moving the mouse during a packaged-server run turns camera 0. Ask the owner to step away first.
- `capture.py` **deletes and rewrites** `out/filter_test/test_clip/` (its output path is fixed). That clip feeds `out/city_wm/bridge/controls/` and every bridge paint. Copy it aside first if it must survive.
- If no server is listening, start it the way `city/agents/run_wm_lunch.sh` does, from the repo root:
  ```
  MINIMIZED=1 CVPORT=9001 mac_server/scripts/run.sh packaged > /tmp/capture_server_9001.log 2>&1 &
  # wait until 9001 listens, then ~20 s for the map to stream in
  python3 ram_share.py claim --name capture_server_9001 --gb 10 --pid "$(pgrep -f 'SimWorld.*-cvport=9001' | head -1)"
  simworld/.venv/bin/python -I city/ue/build_city.py --port 9001
  ```
  Stop only a server you started: `pkill -f "SimWorld.*-cvport=9001"` (a server, not a model process).

## 1. Capture (300 frames, 10 s, no NPCs, fixed clock)

```
.venv/bin/python filter_test/scripts/capture.py                 # bridge walk with head motion, 1280x720, 14:00
.venv/bin/python filter_test/scripts/capture.py --place garden  # replays Qwen's first route from a city run
.venv/bin/python filter_test/scripts/capture.py --still         # SimWorld's own camera, locked to the body
```
Flags: `--port 9001 --size 1280x720 --clock 14:00 --speed 1.6`. It sends `StopAgent` before closing. Output: `out/filter_test/test_clip/{rgb,depth,segmentation}/NNNN.*`, `poses.jsonl`, `head.jsonl`, `capture.json`.

## 2. Control videos (CPU, about a minute, never connects to 9001)

```
.venv/bin/python -I city/wm/controls.py                           # first 150 frames of the bridge clip
.venv/bin/python -I city/wm/controls.py --frames 300 --clip out/filter_test/test_clip --out out/city_wm/bridge/controls
```
Writes `<out>/832x480/` and `<out>/448x256/` with `{depth,depth_inverse,seg,seg_actor,edge,blur}.mp4`, plus `controls.json` and `sheet.png`. 832x480 is the model's trained canvas.

## Check

Open `sheet.png` and confirm the frame count in `capture.json` and `controls.json`. Next step: the `paint-clip` skill.
