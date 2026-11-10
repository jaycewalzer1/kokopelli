#!/bin/sh
# P4-C: paint the bridge clip exactly as wmmc_a4_full_8bit did (Variant A, 4 controls at 0.25, 832x480, 150 frames,
# seed 2025, window 51, sink 1), at gen-weight precision $1 (4 or 8). The prompt is copied verbatim from that job's
# ledger entry. 4-bit is quantized at load from the local bf16 weights (mx.quantize, group 64): nothing downloaded.
#   sh scripts/fable/p4_c_bits.sh 4 [--dry-run]       (queue it with ops/gpu.py; see docs/fable_log/P4.md)
set -eu
BITS=$1; shift
W=$(cd "$(dirname "$0")/../.." && pwd)
C=/Users/jaycewalzer/Desktop/kokopelli/out/city_wm/bridge/controls/832x480
OUT=out/fable/P4/bits/bridge_${BITS}bit.mp4
P=$(python3 -c 'import json,sys
for l in open(sys.argv[1]):
    e = json.loads(l) if l.startswith("{") else {}
    if e.get("event") == "queued" and e.get("name") == "wmmc_a4_full_8bit":
        c = e["command"]
print(c[c.index("world_transfer_multi.py") + 1])' "$W/out/ops/gpu_ledger.jsonl")
if [ "$BITS" = 8 ]; then LABEL="default precision (8-bit), same-session baseline for P4-C"
else LABEL="LOWERED PRECISION: gen weights ${BITS}-bit (default is 8-bit); P4-C test only"; fi
mkdir -p "$W/out/fable/P4/bits"
cd "$W"
exec env PYTHONPATH=$HOME/cosmos3/cosmos3-mlx $HOME/cosmos3/cosmos3-mlx/.venv/bin/python world_transfer_multi.py "$P" \
  --control blur=$C/blur.mp4 --control seg=$C/seg.mp4 --control depth=$C/depth.mp4 --control edge=$C/edge.mp4 \
  --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25 \
  --output "$OUT" --size 832x480 --frames 150 --seed 2025 --window 51 --sink 1 --quantize "$BITS" \
  --extra "{\"precision\": \"$LABEL\", \"compare_with\": \"out/wm_multicontrol/a4_full_8bit (8-bit, 2026-11-08, on battery)\"}" "$@"
