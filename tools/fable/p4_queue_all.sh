#!/bin/sh
# $G and $P hold command lines that must split into words where they are used, so they stay unquoted.
# shellcheck disable=SC2086
# All P4 GPU jobs, one at a time, detached from any shell limit:
#   nohup sh tools/fable/p4_queue_all.sh > out/fable/P4/queue_all.txt 2>&1 &
# Order: profile dry run, profile (P4-A), 8-bit bridge baseline and 4-bit bridge (P4-C), shared-memory profile (P4-B1).
set -u
W=$(cd "$(dirname "$0")/../.." && pwd); cd "$W" || exit
say() { echo "$(date '+%F %T') $*"; }
G="python3 kokopelli/ops/gpu.py run --priority 40 --cwd $W"
A="Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer, gen weights 8-bit), Variant A, 4 controls at 0.25, 448x256 (closed-loop size, lowered from 832x480), recorded Iris controls for 2 streams"
B="Cosmos3-Nano-Sim-Transfer (models/Cosmos3-Nano-Sim-Transfer), Variant A, 4 controls at 0.25, 832x480, 150-frame bridge clip, seed 2025, same command as wmmc_a4_full_8bit"
P="env KOKO_PROFILE=1 .venv/bin/python tools/fable/p4_profile.py"

say "profile dry run"
if $G --dry-run --name fable_P4_profile_dry --gb 12 --about "$A; ONE stream ONE frame: checks the P4-A profile script" \
     --output out/fable/P4/profile_dry -- $P --out out/fable/P4/profile_dry; then
  say "profile"
  $G --name fable_P4_profile --gb 20 --max-hours 1 --about "$A; KOKO_PROFILE=1 per-stage timers: 1+16 frames per stream, then one 160-frame push (P4-A)" \
     --output out/fable/P4/profile -- $P --out out/fable/P4/profile; say "profile exit $?"
else say "profile dry run FAILED, profile skipped"; fi

say "bridge 8-bit"
$G --name fable_P4_bridge_8bit --gb 24 --max-hours 1 --about "$B, gen weights 8-bit (default): same-session time/memory baseline for the P4-C 4-bit test" \
   --output out/fable/P4/bits -- sh tools/fable/p4_c_bits.sh 8; say "bridge 8-bit exit $?"

say "bridge 4-bit dry run"
if $G --dry-run --name fable_P4_bridge_4bit_dry --gb 24 --about "$B, LOWERED PRECISION gen weights 4-bit; one latent: checks the 4-bit path" \
     --output out/fable/P4/bits -- sh tools/fable/p4_c_bits.sh 4; then
  say "bridge 4-bit"
  $G --name fable_P4_bridge_4bit --gb 24 --max-hours 1 --about "$B, LOWERED PRECISION: gen weights 4-bit (default 8-bit). P4-C test of time, memory and video_check scores; default untouched" \
     --output out/fable/P4/bits -- sh tools/fable/p4_c_bits.sh 4; say "bridge 4-bit exit $?"
else say "bridge 4-bit dry run FAILED, 4-bit skipped"; fi

say "profile shm"
$G --name fable_P4_profile_shm --gb 20 --max-hours 1 --about "$A; as fable_P4_profile but frames handed over in shared memory (KOKO_WM_SHM), not .npy files (P4-B1 test)" \
   --output out/fable/P4/profile_shm -- $P --out out/fable/P4/profile_shm --shm; say "profile shm exit $?"
say "all done"
