#!/bin/sh
# P4-A/B1: dry run, then the real per-stage profile (and with "shm" as $1, the P4-B1 shared-memory run), one queue job at a time.
set -u
W=$(cd "$(dirname "$0")/../.." && pwd); cd "$W"
SHM=${1:-}
ABOUT="Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, gen weights 8-bit), Variant A, 4 controls at 0.25, 448x256 (closed-loop size, lowered from 832x480), recorded Iris controls for 2 streams"
if [ -z "$SHM" ]; then
  python3 ops/gpu.py run --dry-run --name fable_P4_profile_dry --priority 40 --gb 12 --cwd "$W" \
    --about "$ABOUT; ONE stream ONE frame: checks the P4-A KOKO_PROFILE script" --output out/fable/P4/profile_dry -- \
    env KOKO_PROFILE=1 .venv/bin/python scripts/fable/p4_profile.py --out out/fable/P4/profile_dry || exit $?
  exec python3 ops/gpu.py run --name fable_P4_profile --priority 40 --gb 20 --max-hours 1 --cwd "$W" \
    --about "$ABOUT; KOKO_PROFILE=1 per-stage timers: 1+16 frames per stream then one 160-frame push (P4-A)" \
    --output out/fable/P4/profile -- env KOKO_PROFILE=1 .venv/bin/python scripts/fable/p4_profile.py --out out/fable/P4/profile
fi
exec python3 ops/gpu.py run --name fable_P4_profile_shm --priority 40 --gb 20 --max-hours 1 --cwd "$W" \
  --about "$ABOUT; same as fable_P4_profile but KOKO_WM_SHM shared-memory frame handoff instead of .npy files (P4-B1 test)" \
  --output out/fable/P4/profile_shm -- env KOKO_PROFILE=1 .venv/bin/python scripts/fable/p4_profile.py --out out/fable/P4/profile_shm --shm
