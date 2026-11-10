#!/bin/sh
# Variant A short runs (832x480, 17 frames, seed 2025, bridge "b_light" prompt). Run only inside the GPU queue:
#   gpu.py run --name wmmc_<run> ... -- sh wm_multicontrol/run_a.sh <a1|a2|a3>
# a1 runs core.world_transfer (blur alone, the baseline) and core.world_transfer_multi (blur at weight 1), saves both latents
# and checks they are bit-identical.
set -e
K="$(cd "$(dirname "$0")/.." && pwd)"
R="$HOME/cosmos3/cosmos3-mlx"
PY="$R/.venv/bin/python"
C="$K/out/city_wm/bridge/controls/832x480"
O="$K/out/wm_multicontrol/$1"
P="$(python3 -c 'import json,sys;print(next(v["prompt"] for v in json.load(open(sys.argv[1]))["variants"] if v["id"]=="b_light"))' "$K/city/wm/prompts/bridge.json")"
COMMON="--size 832x480 --frames 17 --seed 2025"
mkdir -p "$O"
export PYTHONPATH="$K:$R"  # $K first, as when the scripts ran by path, so -m finds core/
case "$1" in
  a1)
    python3 "$K/ram_share.py" hold --name wmmc_a1 --gb 20 -- "$PY" -m core.world_transfer "$P" --hint blur --control "$C/blur.mp4" $COMMON \
      --output "$O/blur_world_transfer.mp4" --save-latents "$O/blur_world_transfer.npy"
    python3 "$K/ram_share.py" hold --name wmmc_a1 --gb 20 -- "$PY" -m core.world_transfer_multi "$P" --control blur="$C/blur.mp4" \
      --weight blur=1 $COMMON --output "$O/blur_multi_w1.mp4" --save-latents "$O/blur_multi_w1.npy"
    "$PY" -c "import json,numpy as n,sys;a,b=n.load(sys.argv[1]),n.load(sys.argv[2]);r={'bitwise_equal':bool((a==b).all()),'max_abs_diff':float(abs(a-b).max())};print(r);open(sys.argv[3],'w').write(json.dumps(r))" \
      "$O/blur_world_transfer.npy" "$O/blur_multi_w1.npy" "$O/equivalence.json"
    ;;
  a2)
    python3 "$K/ram_share.py" hold --name wmmc_a2 --gb 20 -- "$PY" -m core.world_transfer_multi "$P" \
      --control blur="$C/blur.mp4" --control seg="$C/seg.mp4" --weight blur=0.5 --weight seg=0.5 $COMMON --output "$O/a2.mp4"
    ;;
  a3)
    python3 "$K/ram_share.py" hold --name wmmc_a3 --gb 20 -- "$PY" -m core.world_transfer_multi "$P" \
      --control blur="$C/blur.mp4" --control seg="$C/seg.mp4" --control depth="$C/depth.mp4" \
      --weight blur=0.4 --weight seg=0.3 --weight depth=0.3 $COMMON --output "$O/a3.mp4"
    ;;
  a4_full)
    # Whole bridge clip. Five K/V histories x 38 latents ~ 11 GB on top of ~14 GB of weights, hence the larger hold.
    python3 "$K/ram_share.py" hold --name wmmc_a4_full --gb 28 -- "$PY" -m core.world_transfer_multi "$P" \
      --control blur="$C/blur.mp4" --control seg="$C/seg.mp4" --control depth="$C/depth.mp4" --control edge="$C/edge.mp4" \
      --weight blur=0.25 --weight seg=0.25 --weight depth=0.25 --weight edge=0.25 \
      --size 832x480 --frames 150 --seed 2025 --output "$O/a4_full.mp4"
    ;;
  *) echo "usage: run_a.sh a1|a2|a3|a4_full" >&2; exit 2 ;;
esac
