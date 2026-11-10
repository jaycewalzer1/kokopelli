#!/bin/bash
# shellcheck disable=SC2086  # $GPU holds several arguments and must split into words, so it stays unquoted
# Put the three Mac filter runs on the GPU queue. Each waits for its turn; the SD runs are minutes, Cosmos about an hour.
#   bash experiments/filter_test/scripts/queue_all.sh
cd "$(dirname "$0")/../.." || exit 1
GPU="python3 kokopelli/ops/gpu.py run --cwd $PWD --give-up-hours 48"
LOGS=out/filter_test/logs
mkdir -p "$LOGS"
nohup $GPU --name filter_sd15_simdepth --priority 20 --max-hours 1 --output out/filter_test/sd15_simdepth \
  --about "Sim-to-real test 2 of 3: SD1.5 + DMD one-step + depth ControlNet repaints the 10 s SimWorld bridge clip from the sim's own depth, frame by frame on MPS." \
  -- experiments/filter_test/.venv/bin/python experiments/filter_test/scripts/run_sd.py --depth sim > $LOGS/sd15_simdepth.log 2>&1 &
nohup $GPU --name filter_sd15_dadepth --priority 21 --max-hours 1 --output out/filter_test/sd15_dadepth \
  --about "Sim-to-real test 3 of 3: the same SD1.5 setup, but on DepthAnythingV2's depth guessed from the sim's rgb, the repo's own way. Shows whether real sim depth helps." \
  -- experiments/filter_test/.venv/bin/python experiments/filter_test/scripts/run_sd.py --depth da > $LOGS/sd15_dadepth.log 2>&1 &
nohup $GPU --name filter_cosmos_simdepth --priority 22 --max-hours 3 --output out/filter_test/cosmos_simdepth \
  --about "Sim-to-real test 1 of 3: Cosmos3-Nano (MLX) repaints the 10 s SimWorld bridge clip from the sim's depth through world_filter.py, 26 chunks of 16 frames." \
  -- .venv/bin/python experiments/filter_test/scripts/run_cosmos.py > $LOGS/cosmos_simdepth.log 2>&1 &
sleep 2
python3 kokopelli/ops/gpu.py status
