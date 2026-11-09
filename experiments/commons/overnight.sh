#!/bin/bash
# Runs the full experiment through the GPU queue, retrying a killed job (runs resume by season), then analyzes and commits the summaries.
# usage: overnight.sh <deadline ISO, e.g. 2026-11-09T08:30>
DEADLINE="$1"
MAIN=/Users/jaycewalzer/Desktop/kokopelli
HERE="$MAIN/.claude/worktrees/commons/experiments/commons"
RUNS="$MAIN/.claude/worktrees/commons/runs/commons"
cd "$HERE" || exit 1
"$MAIN/simworld/.venv/bin/python" audit.py > /dev/null
for attempt in 1 2 3 4 5 6; do
  now=$(date +%s); end=$(date -j -f "%Y-%m-%dT%H:%M" "$DEADLINE" +%s)
  [ "$now" -ge "$end" ] && break
  hours=$(python3 -c "print(max(0.2, ($end - $now) / 3600 + 0.1))")
  echo "$(date) attempt $attempt, up to $hours h"
  "$MAIN/simworld/.venv/bin/python" "$MAIN/.claude/worktrees/ops/ops/gpu.py" run --name "commons_full_$attempt" --priority 40 --gb 10 --max-hours "$hours" --cwd "$HERE" \
    --about "Lake-governance pilot: 60-season games of clones vs described vs lived upbringings, 7 Qwen3-VL-8B-Instruct-4bit agents plus a scripted defector; no world model, video or LoRA. Resumable by season." \
    --output ../../runs/commons/R3 -- "$MAIN/.venv/bin/python" run.py full --seeds 0-9 --deadline "$DEADLINE" --satiation
  code=$?
  echo "$(date) attempt $attempt exited $code"
  [ "$code" -eq 0 ] && break
  sleep 30
done
"$MAIN/.venv/bin/python" analyze.py
cd "$MAIN/.claude/worktrees/commons" || exit 1
git add -f runs/commons/REPORT.md runs/commons/metrics.json runs/commons/reward_audit.md runs/commons/lint_report.md runs/commons/lint_report.json runs/commons/plots runs/commons/spend.json
git add -A experiments/commons
git commit -qm "Add overnight results, plots and the generated report"
echo "$(date) finished"
