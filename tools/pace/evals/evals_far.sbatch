#!/usr/bin/env bash
# Far-transfer benchmarks with vLLM and LoRA hot-swap, all arms in one job. Submit from the repo root:
#   mkdir -p logs && sbatch tools/pace/evals/evals_far.sbatch
# Print the commands instead of running them:
#   EVALS_DRY_RUN=1 bash tools/pace/evals/evals_far.sbatch
#
# Untested on PACE. The account, partition, GPU type, memory and time are guesses for a first run.
#SBATCH --job-name=evals_far
#SBATCH --account=CHANGE_ME_ACCOUNT
#SBATCH --partition=CHANGE_ME_GPU_PARTITION
#SBATCH --gres=CHANGE_ME_GPU_GRES
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=logs/evals_far_%j.out
set -euo pipefail

REPO="${SLURM_SUBMIT_DIR:-$(pwd)}"
# shellcheck source=tools/pace/evals/env.sh
source "$REPO/tools/pace/evals/env.sh"
RUN_ID="${EVALS_RUN_ID:-far_$(date +%Y%m%d)}"
ARMS="${EVALS_ARMS:-base lived described shuffled flipped_lived}"
SEEDS="${EVALS_SEEDS:-0 1 2}"
SAMPLES="${EVALS_SAMPLES:-50}"

do_it() {
    echo "+ $*"
    if [ -z "${EVALS_DRY_RUN:-}" ]; then "$@"; fi
}

if [ -z "${EVALS_DRY_RUN:-}" ]; then
    # shellcheck disable=SC2086
    module load $EVALS_MODULES
    # shellcheck disable=SC1091
    source "$EVALS_VENV/bin/activate"
else
    echo "+ module load $EVALS_MODULES"
    echo "+ source $EVALS_VENV/bin/activate"
fi

do_it cd "$REPO"
# Refuses if PREREG.md is a draft, unlocked, or edited since the lock. Fails before any GPU time is spent.
do_it python -m experiments.benchmarks.prereg check
# Arm configs look for adapters and their training text under out/adapters in the repo.
do_it mkdir -p out
do_it ln -sfn "$EVALS_ADAPTERS" out/adapters
# shellcheck disable=SC2086
do_it python -m experiments.benchmarks.leakage --arms $ARMS --instruments holt_laury lotteries --seeds $SEEDS
# shellcheck disable=SC2086
do_it python -u -m experiments.benchmarks.run --backend vllm --real --model "$EVALS_MODEL" \
    --arms $ARMS --instruments holt_laury lotteries --samples "$SAMPLES" --seeds $SEEDS \
    --out "$EVALS_OUT/$RUN_ID" --progress 500
do_it python -m experiments.benchmarks.report "$EVALS_OUT/$RUN_ID"
