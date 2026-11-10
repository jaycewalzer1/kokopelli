#!/usr/bin/env bash
# P3-C: queue the two stillness paints (sets B and C from tools/fable/stillness.py). Owner's default setup:
# Variant A (world_transfer_multi.py, Cosmos3-Nano-Sim-Transfer), four controls at 0.25, 8-bit weights, 832x480,
# and everything else exactly as set A (a4_full_8bit): same caption (read from A's sidecar), seed 2025, window 51,
# sink 1, 150 frames. Only the controls differ.
# --gb 28: a4_full_8bit's job log (ledger peak_job_gb) peaked at 28.08 GB for the process tree; its sidecar's
# peak_gb said 19.94 and its ram_share claim of 20 let swap grow 9 GB, so the larger figure is used.
# Usage: tools/fable/stillness_queue.sh [check|run] [B C]   check (default) only runs kokopelli/ops/gpu.py check; run queues.
# Score afterwards: tools/fable/stillness_score.py (see its docstring).
set -euo pipefail
K=/Users/jaycewalzer/Desktop/kokopelli
CM=$HOME/cosmos3/cosmos3-mlx
GB=${GB:-28}
mode=${1:-check}; shift || true
sets=${*:-B C}
P="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["prompt"])' "$K/out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4.json")"

for S in $sets; do
  NAME=fable_p3c_still_$S
  D=$K/out/wm_multicontrol/fable_still_$S
  OUT=out/wm_multicontrol/fable_still_$S/fable_still_$S.mp4
  case $S in
    B) WHAT="still from frame 0 (bridge controls frame 60 repeated 150x)" ;;
    C) WHAT="moving 60 frames then still 90 (bridge controls frame i = min(i, 60))" ;;
    *) echo "unknown set $S" >&2; exit 2 ;;
  esac
  JOB=(python3 "$K/kokopelli/ops/ram_share.py" hold --name "$NAME" --gb "$GB" -- env "PYTHONPATH=$CM" "$CM/.venv/bin/python"
       "$K/world_transfer_multi.py" "$P"
       --control "blur=$D/controls/blur.mp4" --control "seg=$D/controls/seg.mp4"
       --control "depth=$D/controls/depth.mp4" --control "edge=$D/controls/edge.mp4"
       --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25
       --output "$K/$OUT" --size 832x480 --frames 150 --seed 2025 --window 51 --sink 1 --quantize 8
       --extra "{\"fable_p3c_set\": \"$S\", \"stillness\": \"$WHAT\", \"compare_with\": \"out/wm_multicontrol/a4_full_8bit (set A, moving 150)\"}")
  if [ "$mode" = run ]; then
    python3 "$K/kokopelli/ops/gpu.py" run --name "$NAME" --priority 35 --max-hours 1.5 --gb "$GB" --cwd "$K" \
      --about "Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, 8-bit), Variant A, 4 controls at 0.25, 832x480, 150 frames, A's caption and seed. P3-C set $S: $WHAT. Tests whether mosaic follows stillness or elapsed time against a4_full_8bit." \
      --output "$OUT" -- "${JOB[@]}"
  else
    echo "== $NAME"
    python3 "$K/kokopelli/ops/gpu.py" check --cwd "$K" --output "$OUT" --gb "${CHECK_GB:-$GB}" -- "${JOB[@]}" || rc=1
  fi
done
exit "${rc:-0}"
