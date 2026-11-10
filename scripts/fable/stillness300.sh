#!/usr/bin/env bash
# P3-C follow-up: the 150-frame stillness test was inconclusive, and earlier still-camera breaks came near frame 224.
# Same test at 300 frames. Sets, built from the 150-frame bridge controls:
#   A300  moving all the way: frames 0..149, then back 149..0
#   B300  still from frame 0: frame 60 repeated
#   C300  moving 60, then frame 60 held
# Painted like set A (a4_full_8bit): Variant A, four controls at 0.25, 8-bit, 832x480, A's caption, seed 2025, window 51.
# Usage: scripts/fable/stillness300.sh [build|run] [A300 B300 C300]
set -euo pipefail
K=/Users/jaycewalzer/Desktop/kokopelli
CM=$HOME/cosmos3/cosmos3-mlx
SRC=$K/out/city_wm/bridge/controls/832x480
GB=${GB:-24}
mode=${1:-build}; shift || true
sets=${*:-A300 B300 C300}
P="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["prompt"])' "$K/out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4.json")"
ENC=(-an -c:v libx264 -pix_fmt yuv420p -crf 10 -r 30 -frames:v 300 -loglevel error -y)

for S in $sets; do
  D=$K/out/wm_multicontrol/fable_still_$S
  case $S in
    A300) F="split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1"; WHAT="moving 300 (bridge controls forward then backward)" ;;
    B300) F="select='eq(n\,60)',loop=loop=299:size=1:start=0,setpts=N/30/TB"; WHAT="still from frame 0 (bridge controls frame 60 repeated 300x)" ;;
    C300) F="trim=end_frame=61,tpad=stop_mode=clone:stop=239,setpts=N/30/TB"; WHAT="moving 60 frames then still 240 (frame 60 held)" ;;
    *) echo "unknown set $S" >&2; exit 2 ;;
  esac
  if [ "$mode" = build ]; then
    mkdir -p "$D/controls"
    for c in blur seg depth edge; do ffmpeg -i "$SRC/$c.mp4" -vf "$F" "${ENC[@]}" "$D/controls/$c.mp4"; done
    echo "$S: $(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames,width,height -of csv=p=0 "$D/controls/blur.mp4")"
  else
    NAME=fable_p3c_still_$S
    OUT=out/wm_multicontrol/fable_still_$S/fable_still_$S.mp4
    python3 "$K/ops/gpu.py" run --name "$NAME" --priority 35 --max-hours 1.5 --gb "$GB" --cwd "$K" \
      --about "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, 8-bit), Variant A, 4 controls at 0.25, 832x480, 300 frames, A's caption and seed. Stillness test at 300 frames, set $S: $WHAT." \
      --output "$OUT" -- \
      python3 "$K/ram_share.py" hold --name "$NAME" --gb "$GB" -- env "PYTHONPATH=$CM" "$CM/.venv/bin/python" \
      "$K/world_transfer_multi.py" "$P" \
      --control "blur=$D/controls/blur.mp4" --control "seg=$D/controls/seg.mp4" \
      --control "depth=$D/controls/depth.mp4" --control "edge=$D/controls/edge.mp4" \
      --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25 \
      --output "$K/$OUT" --size 832x480 --frames 300 --seed 2025 --window 51 --sink 1 --quantize 8 \
      --extra "{\"fable_p3c_set\": \"$S\", \"stillness\": \"$WHAT\"}"
  fi
done
