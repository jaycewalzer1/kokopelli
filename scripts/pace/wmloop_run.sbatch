#!/usr/bin/env bash
# The whole loop on one node: SimWorld, Cosmos and Qwen servers, then runtime.run. Run wmloop_gate.sbatch first.
# Edit the CHANGE_ME lines below and scripts/pace/env.sh, then, from the repo root:
#   mkdir -p logs && WMLOOP_TICKS=10 sbatch scripts/pace/wmloop_run.sbatch
#
# A dry run prints every command without a cluster:
#   WMLOOP_DRY_RUN=1 bash scripts/pace/wmloop_run.sbatch
#
#SBATCH --job-name=wmloop_run
#SBATCH --account=CHANGE_ME_ACCOUNT
#SBATCH --partition=CHANGE_ME_GPU_PARTITION
#SBATCH --gres=CHANGE_ME_GPU_GRES
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=logs/wmloop_run_%j.out
# Asks for 3 GPUs' worth of work on one node. --mem and --time are guesses until a run measures them.
set -uo pipefail

WMLOOP_REPO="${WMLOOP_REPO:-${SLURM_SUBMIT_DIR:-$(pwd)}}"
export WMLOOP_REPO
if [ ! -f "$WMLOOP_REPO/scripts/pace/env.sh" ]; then
    echo "ERROR: run this from the repo root. No scripts/pace/env.sh under $WMLOOP_REPO" >&2
    exit 2
fi
# shellcheck source=scripts/pace/env.sh
source "$WMLOOP_REPO/scripts/pace/env.sh"
# shellcheck source=scripts/pace/simworld_server.sh
source "$WMLOOP_REPO/scripts/pace/simworld_server.sh"

wmloop_require WMLOOP_MODULES WMLOOP_SIMWORLD_DIR WMLOOP_VENV WMLOOP_OUT WMLOOP_VLLM_VENV WMLOOP_LIFE_DB
wmloop_load_modules || { echo "ERROR: module load failed" >&2; exit 2; }

JOB="${SLURM_JOB_ID:-local}"
TICKS="${WMLOOP_TICKS:-10}"
SEED="${WMLOOP_SEED:-7}"
PRESET="${WMLOOP_WM_PRESET:-gpu_full}"
# Per job and node, so a second job can't collide on the same ports.
COSMOS_PORT=$((20000 + ${SLURM_JOB_ID:-0} % 10000))
QWEN_PORT=$((COSMOS_PORT + 10000))
RUN_OUT="$WMLOOP_OUT/run_$JOB"
export WMLOOP_OUT="$RUN_OUT"
# Cosmos and Qwen take GPUs 0 and 1 by default (env.sh), so SimWorld gets the third.
export WMLOOP_GPU_INDEX="${WMLOOP_SIM_GPU:-2}"

COSMOS_SERVER=("$WMLOOP_VLLM_VENV/bin/vllm" serve "$WMLOOP_COSMOS_MODEL" --omni --host 127.0.0.1 --port "$COSMOS_PORT" --init-timeout "$WMLOOP_MODEL_READY_TIMEOUT_S")
QWEN_SERVER=("$WMLOOP_VLLM_VENV/bin/vllm" serve "$WMLOOP_QWEN_MODEL" --host 127.0.0.1 --port "$QWEN_PORT")
loop_command() {
    SIM_JSON="{\"port\": $WMLOOP_PORT, \"tick_interval_s\": $WMLOOP_TICK_INTERVAL}"
    LOOP=("$WMLOOP_VENV/bin/python" -u -m runtime.run --backend real --ticks "$TICKS" --seed "$SEED" --wm-preset "$PRESET"
          --sim-settings "$SIM_JSON" --wm-url "http://127.0.0.1:$COSMOS_PORT" --agent-url "http://127.0.0.1:$QWEN_PORT"
          --life-db "$WMLOOP_LIFE_DB" --life-run "$WMLOOP_LIFE_RUN" --out "$RUN_OUT/loop")
}

if [ "${WMLOOP_DRY_RUN:-0}" = "1" ]; then
    WMLOOP_PORT=9000
    wmloop_start_server
    loop_command
    echo "DRY RUN: CUDA_VISIBLE_DEVICES=$WMLOOP_COSMOS_GPU ${COSMOS_SERVER[*]}"
    echo "DRY RUN: CUDA_VISIBLE_DEVICES=$WMLOOP_QWEN_GPU ${QWEN_SERVER[*]}"
    echo "DRY RUN: would wait up to ${WMLOOP_MODEL_READY_TIMEOUT_S}s for http://127.0.0.1:$COSMOS_PORT and :$QWEN_PORT/v1/models"
    echo "DRY RUN: cd $WMLOOP_REPO && ${LOOP[*]}"
    exit 0
fi

mkdir -p "$RUN_OUT"
if [ -z "$(wmloop_find_launcher)" ]; then
    echo "ERROR: no SimWorld.sh under $WMLOOP_SIMWORLD_DIR. Run scripts/pace/download_simworld.sh --yes first." >&2
    exit 2
fi

COSMOS_PID=""; QWEN_PID=""
stop_everything() {
    [ -n "$COSMOS_PID" ] && kill "$COSMOS_PID" 2>/dev/null
    [ -n "$QWEN_PID" ] && kill "$QWEN_PID" 2>/dev/null
    wmloop_stop_server
}
trap stop_everything EXIT
trap 'exit 143' TERM INT

{
    echo "job=$JOB node=$(hostname) date=$(date +%FT%T%z) git=$(git -C "$WMLOOP_REPO" rev-parse HEAD 2>/dev/null)"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv 2>&1
} | tee "$RUN_OUT/environment.txt"

CUDA_VISIBLE_DEVICES="$WMLOOP_COSMOS_GPU" "${COSMOS_SERVER[@]}" > "$RUN_OUT/cosmos_server.log" 2>&1 &
COSMOS_PID=$!
CUDA_VISIBLE_DEVICES="$WMLOOP_QWEN_GPU" "${QWEN_SERVER[@]}" > "$RUN_OUT/qwen_server.log" 2>&1 &
QWEN_PID=$!

wait_for_model() {  # url name pid
    local waited=0
    until curl -sf "$1/v1/models" > /dev/null; do
        kill -0 "$3" 2>/dev/null || { echo "ERROR: the $2 server died. See $RUN_OUT/$2_server.log" >&2; return 1; }
        [ "$waited" -ge "$WMLOOP_MODEL_READY_TIMEOUT_S" ] && { echo "ERROR: the $2 server wasn't ready in time" >&2; return 1; }
        sleep 10; waited=$((waited + 10))
    done
}
wait_for_model "http://127.0.0.1:$COSMOS_PORT" cosmos "$COSMOS_PID" || exit 1
wait_for_model "http://127.0.0.1:$QWEN_PORT" qwen "$QWEN_PID" || exit 1
wmloop_start_server || { echo "ERROR: SimWorld never became ready. Send back $RUN_OUT" >&2; exit 1; }

loop_command
cd "$WMLOOP_REPO" && "${LOOP[@]}" 2>&1 | tee "$RUN_OUT/loop.txt"
CODE=${PIPESTATUS[0]}

nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv 2>&1 | tee -a "$RUN_OUT/environment.txt"
echo "loop exit=$CODE. Copy $RUN_OUT/loop back and view it with: python -m runtime.viewer <that folder>"
echo "To continue a stopped run, start the servers and run: python -m runtime.run --resume $RUN_OUT/loop --ticks $TICKS"
exit "$CODE"
