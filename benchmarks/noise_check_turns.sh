#!/usr/bin/env bash
# The Phase 5 noise check, one GPU turn at a time. Run this in the background from the worktree root.
#
# Each round asks the queue for a turn of at most 30 minutes, at priority 40, and stops when the run reports it's done.
# Exit code 75 means the time budget ran out and more remains, so it rejoins the line and higher priorities go first.
# A kill or a hang loses at most the sample in progress, because results are appended per sample and resume skips them.
# EVALS_TEMPERATURE picks the temperature. Each temperature needs its own <out dir>, because a run's sampling is fixed.
#
#   benchmarks/noise_check_turns.sh <out dir> <samples> <instruments...> -- <arms...>
#   benchmarks/noise_check_turns.sh benchmarks/results/noise_t07 50 holt_laury lotteries -- base
set -u

GPU=/Users/jaycewalzer/Desktop/kokopelli/.claude/worktrees/ops/ops/gpu.py
PY=/Users/jaycewalzer/Desktop/kokopelli/.venv/bin/python
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$1"; SAMPLES="$2"; shift 2
INSTRUMENTS=()
while [ "$1" != "--" ]; do INSTRUMENTS+=("$1"); shift; done
shift
ARMS=("$@")
TEMPERATURE="${EVALS_TEMPERATURE:-0.7}"
MAX_ROUNDS="${EVALS_MAX_ROUNDS:-12}"

for round in $(seq 1 "$MAX_ROUNDS"); do
    python3 "$GPU" run --name "evals_$(basename "$OUT")" --priority 40 --max-hours 0.75 --cwd "$ROOT" -- \
        nice -n 10 "$PY" -u -m benchmarks.run --backend llm_model --real --exploratory \
        --arms "${ARMS[@]}" --instruments "${INSTRUMENTS[@]}" --samples "$SAMPLES" \
        --temperature "$TEMPERATURE" --out "$OUT" --minutes 30 --progress 25
    code=$?
    echo "round $round finished with exit code $code"
    # 124 is the queue's --max-hours kill. Resume makes it safe to try again, as with a used-up budget.
    if [ "$code" -ne 75 ] && [ "$code" -ne 124 ]; then
        exit "$code"
    fi
done
echo "Gave up after $MAX_ROUNDS rounds. Rerun this script to continue."
exit 75
