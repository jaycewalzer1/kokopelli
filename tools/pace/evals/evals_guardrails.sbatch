#!/usr/bin/env bash
# Guardrails: start a vLLM server with every adapter loaded, then point lm-eval at it through the api backend.
#   mkdir -p logs && sbatch tools/pace/evals/evals_guardrails.sbatch
# Print the commands instead of running them:
#   EVALS_DRY_RUN=1 bash tools/pace/evals/evals_guardrails.sbatch
#
# Untested on PACE. The names passed to --lora-modules match api_model in each arm's config: <arm>_seed<N>.
#SBATCH --job-name=evals_guardrails
#SBATCH --account=CHANGE_ME_ACCOUNT
#SBATCH --partition=CHANGE_ME_GPU_PARTITION
#SBATCH --gres=CHANGE_ME_GPU_GRES
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/evals_guardrails_%j.out
set -euo pipefail

REPO="${SLURM_SUBMIT_DIR:-$(pwd)}"
# shellcheck source=tools/pace/evals/env.sh
source "$REPO/tools/pace/evals/env.sh"
RUN_ID="${EVALS_RUN_ID:-guardrails_$(date +%Y%m%d)}"
ARMS="${EVALS_ARMS:-base lived described shuffled flipped_lived}"
SEEDS="${EVALS_SEEDS:-0 1 2}"
API="http://127.0.0.1:$EVALS_PORT/v1"

MODULES_ARG=()
for arm in $ARMS; do
    [ "$arm" = "base" ] && continue
    for seed in $SEEDS; do
        MODULES_ARG+=("${arm}_seed${seed}=$EVALS_ADAPTERS/$arm/seed$seed")
    done
done

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
do_it python -m experiments.benchmarks.prereg check
# Arm configs look for adapters under out/adapters in the repo.
do_it mkdir -p out
do_it ln -sfn "$EVALS_ADAPTERS" out/adapters

SERVER=(vllm serve "$EVALS_MODEL" --port "$EVALS_PORT" --enable-lora --max-loras "${#MODULES_ARG[@]}" --lora-modules "${MODULES_ARG[@]}")
echo "+ ${SERVER[*]} &"
if [ -z "${EVALS_DRY_RUN:-}" ]; then
    "${SERVER[@]}" &
    SERVER_PID=$!
    trap 'kill "$SERVER_PID"' EXIT
    until curl -sf "http://127.0.0.1:$EVALS_PORT/v1/models" >/dev/null; do sleep 10; done
else
    echo "+ wait until $API/models answers"
fi

export EVALS_LM_EVAL
# shellcheck disable=SC2086
do_it python -u -m experiments.benchmarks.run --backend api --real --base-url "$API" \
    --arms $ARMS --instruments ifeval mmlu --samples 1 --seeds $SEEDS --out "$EVALS_OUT/$RUN_ID"
do_it python -m experiments.benchmarks.report "$EVALS_OUT/$RUN_ID"
