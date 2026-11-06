#!/usr/bin/env bash
# Kill any running SimWorld game, launch editor-game, wait until SimCV accepts connections.
#   scripts/relaunch.sh [timeout_s]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CVPORT:-9000}"
pkill -f "MacOS/UnrealEditor .*SimWorld.uproject" && sleep 2
mkdir -p "$ROOT/Saved"
(cd "$ROOT" && CVPORT=$PORT nohup scripts/run.sh editor-game > "$ROOT/Saved/run.out" 2>&1 &)
sleep 3
PID=$(pgrep -f "MacOS/UnrealEditor $ROOT/SimWorld.uproject" | head -1)
for ((i = 0; i < ${1:-600}; i++)); do
	if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then echo "ready pid=$PID after ${i}s"; exit 0; fi
	if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
		echo "game exited"; LOG=$(ls -t "$ROOT"/Saved/Logs/simworld-*.log 2>/dev/null | head -1)
		[[ -n "$LOG" ]] && grep -E "Error|Fatal|Critical|dialog|Assertion" "$LOG" | tail -15; exit 1
	fi
	sleep 1
done
echo "timeout"; exit 1
