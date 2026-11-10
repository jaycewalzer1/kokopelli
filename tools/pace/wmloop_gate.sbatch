#!/usr/bin/env bash
# The first real test: start a headless SimWorld and run the gate script on the same node.
# Edit the CHANGE_ME lines below and tools/pace/env.sh, then, from the repo root:
#   mkdir -p logs && sbatch tools/pace/wmloop_gate.sbatch
#
# A dry run prints what it would do without a cluster:
#   WMLOOP_DRY_RUN=1 bash tools/pace/wmloop_gate.sbatch
#
#SBATCH --job-name=wmloop_gate
#SBATCH --account=CHANGE_ME_ACCOUNT
#SBATCH --partition=CHANGE_ME_GPU_PARTITION
#SBATCH --gres=CHANGE_ME_GPU_GRES
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/wmloop_gate_%j.out
# --mem is the README's stated minimum. --time and --cpus-per-task are guesses for a first run.
# The GPU needs 6 GB of VRAM or more (README). One node on purpose: client and server talk over 127.0.0.1.
set -uo pipefail

# Slurm runs a copy of this file from its spool folder, so find the repo from where you submitted.
WMLOOP_REPO="${WMLOOP_REPO:-${SLURM_SUBMIT_DIR:-$(pwd)}}"
export WMLOOP_REPO
if [ ! -f "$WMLOOP_REPO/tools/pace/env.sh" ]; then
    echo "ERROR: run this from the repo root. No tools/pace/env.sh under $WMLOOP_REPO" >&2
    exit 2
fi
# shellcheck source=tools/pace/env.sh
source "$WMLOOP_REPO/tools/pace/env.sh"
# shellcheck source=tools/pace/simworld_server.sh
source "$WMLOOP_REPO/tools/pace/simworld_server.sh"

wmloop_require WMLOOP_MODULES WMLOOP_SIMWORLD_DIR WMLOOP_VENV WMLOOP_OUT
wmloop_load_modules || { echo "ERROR: module load failed" >&2; exit 2; }

JOB="${SLURM_JOB_ID:-local}"
export WMLOOP_OUT="$WMLOOP_OUT/job_$JOB"

if [ "${WMLOOP_DRY_RUN:-0}" = "1" ]; then
    WMLOOP_PORT=9000
    wmloop_start_server
    echo "DRY RUN: would wait up to ${WMLOOP_READY_TIMEOUT_S}s for the hello on the chosen port"
    echo "DRY RUN: would run wmloop_one_tick.py, then wmloop_one_tick.py --checklist, against $WMLOOP_OUT"
    exit 0
fi

mkdir -p "$WMLOOP_OUT"
if [ -z "$(wmloop_find_launcher)" ]; then
    echo "ERROR: no SimWorld.sh under $WMLOOP_SIMWORLD_DIR. Run tools/pace/download_simworld.sh --yes first." >&2
    exit 2
fi

# Stop UE however this script ends, including when Slurm cancels the job.
trap wmloop_stop_server EXIT
trap 'exit 143' TERM INT

{
    echo "job=$JOB node=$(hostname) date=$(date +%FT%T%z)"
    echo "git=$(git -C "$WMLOOP_REPO" rev-parse HEAD 2>/dev/null)"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv 2>&1
    command -v vulkaninfo >/dev/null && vulkaninfo --summary 2>&1 | head -n 30
} | tee "$WMLOOP_OUT/environment.txt"

if ! wmloop_start_server; then
    echo "ERROR: the server never became ready. Send back $WMLOOP_OUT and logs/wmloop_gate_$JOB.out" >&2
    exit 1
fi

GATE=("$WMLOOP_VENV/bin/python" "$WMLOOP_REPO/tools/pace/wmloop_one_tick.py" --port "$WMLOOP_PORT"
      --tick-interval "$WMLOOP_TICK_INTERVAL" --resolution "$WMLOOP_RESOLUTION" --out "$WMLOOP_OUT")

echo; echo "=== One real tick ==="
"${GATE[@]}" 2>&1 | tee "$WMLOOP_OUT/one_tick.txt"
ONE_TICK=${PIPESTATUS[0]}

# The checklist starts from a fresh connection. Give UnrealCV a moment to free its single client slot.
sleep 5
echo; echo "=== Checklist ==="
"${GATE[@]}" --checklist 2>&1 | tee "$WMLOOP_OUT/checklist.txt"
CHECKLIST=${PIPESTATUS[0]}

nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv 2>&1 | tee -a "$WMLOOP_OUT/environment.txt"

# Small bundle to send back. Reports, logs, and one sample of each render.
BUNDLE="$WMLOOP_OUT/send_back_$JOB.tar.gz"
(cd "$WMLOOP_OUT" && {
    find . -maxdepth 1 -type f ! -name '*.tar.gz'
    find renders/checklist -path '*branch_0/step_0001/*' -type f 2>/dev/null
} | tar -czf "$BUNDLE" -T -)
echo; echo "one_tick exit=$ONE_TICK checklist exit=$CHECKLIST"
echo "Send back: $BUNDLE and logs/wmloop_gate_$JOB.out"
exit $((ONE_TICK + CHECKLIST > 0))
