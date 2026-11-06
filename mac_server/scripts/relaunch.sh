#!/usr/bin/env bash
# Kill the SimWorld game of THIS project on THIS port (other agents' instances on other ports or
# other project copies are left alone), launch editor-game, wait until SimCV accepts connections.
#   CVPORT=9001 scripts/relaunch.sh [timeout_s]
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CVPORT:-9000}"
# run.sh passes "-cvport=$PORT" after the project path; match both so only our own instance dies.
MATCH="MacOS/UnrealEditor $ROOT/SimWorld.uproject .*-cvport=$PORT( |\$)"
if pkill -f "$MATCH"; then
	for ((k = 0; k < 30; k++)); do pgrep -f "$MATCH" >/dev/null || break; sleep 1; done
fi
mkdir -p "$ROOT/Saved"
(cd "$ROOT" && CVPORT=$PORT nohup scripts/run.sh editor-game > "$ROOT/Saved/run-$PORT.out" 2>&1 &)
sleep 3
PID=$(pgrep -f "$MATCH" | head -1)
for ((i = 0; i < ${1:-600}; i++)); do
	if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then echo "ready pid=$PID after ${i}s"; exit 0; fi
	if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
		echo "game exited"; LOG=$(ls -t "$ROOT"/Saved/Logs/simworld-*.log 2>/dev/null | head -1)
		[[ -n "$LOG" ]] && grep -E "Error|Fatal|Critical|dialog|Assertion" "$LOG" | tail -15; exit 1
	fi
	sleep 1
done
echo "timeout"; exit 1
