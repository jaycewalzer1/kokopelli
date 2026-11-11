#!/bin/sh
# shellcheck disable=SC2086  # $LABEL holds several arguments and must split into words, so it stays unquoted
# The ambiguous-circle label test: paint the clip from circle_clip.py with no label, then with each of two labels,
# caption only (tier a) and with the attention mask (tier b). Seg control alone, 832x480, 93 frames, seed 2025, 8-bit.
# Run only inside the GPU queue:
#   gpu.py run --name labels_circle ... -- sh experiments/labels/run_circle.sh <none|ball_a|ball_b|pumpkin_a|pumpkin_b|all>
set -e
K="$(cd "$(dirname "$0")/../.." && pwd)"
R="$HOME/cosmos3/cosmos3-mlx"
C="$K/out/labels/circle/clip"
L="$K/experiments/labels/circle"
P="$(cat "$L/caption.json")"
export PYTHONPATH="$K:$R"  # $K first, so -m finds this checkout's kokopelli/wm/
paint() {
  case "$1" in
    none) LABEL="" ;;
    ball_a) LABEL="--labels $L/ball.json --label-frames $C/labels --label-steps 0" ;;
    ball_b) LABEL="--labels $L/ball.json --label-frames $C/labels --label-steps 2" ;;
    pumpkin_a) LABEL="--labels $L/pumpkin.json --label-frames $C/labels --label-steps 0" ;;
    pumpkin_b) LABEL="--labels $L/pumpkin.json --label-frames $C/labels --label-steps 2" ;;
    *) echo "unknown run $1" >&2; exit 2 ;;
  esac
  mkdir -p "$K/out/labels/circle/$1"
  python3 "$K/kokopelli/ops/ram_share.py" hold --name labels_circle --gb 20 -- "$R/.venv/bin/python" -m kokopelli.wm.world_transfer "$P" \
    --hint seg --control "$C/controls/832x480/seg.mp4" --output "$K/out/labels/circle/$1/$1.mp4" \
    --size 832x480 --frames 93 --seed 2025 --quantize 8 \
    --extra '{"controls_note": "seg only (not the 4-control default): ambiguous-circle label test", "run": "'"$1"'"}' $LABEL
}
if [ "$1" = all ]; then
  for run in none ball_a ball_b pumpkin_a pumpkin_b; do paint $run; done
else
  paint "$1"
fi
