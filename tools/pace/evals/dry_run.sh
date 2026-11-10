#!/usr/bin/env bash
# The phase 4 gate: print the exact commands each job would run, without a cluster, a GPU or vLLM.
#   bash tools/pace/evals/dry_run.sh
set -euo pipefail
cd "$(dirname "$0")/../../.."
export EVALS_DRY_RUN=1
for job in evals_far evals_guardrails; do
    echo "=== sbatch tools/pace/evals/$job.sbatch ==="
    bash "tools/pace/evals/$job.sbatch"
    echo
done
