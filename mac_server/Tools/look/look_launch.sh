#!/usr/bin/env bash
# Kill only THIS copy's game (path-specific) and relaunch on port 9002.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=9002
pkill -f "MacOS/UnrealEditor $ROOT/SimWorld.uproject" && sleep 3
mkdir -p "$ROOT/Saved"
(cd "$ROOT" && CVPORT=$PORT nohup scripts/run.sh editor-game > "$ROOT/Saved/run.out" 2>&1 &)
sleep 4
PID=$(pgrep -f "MacOS/UnrealEditor $ROOT/SimWorld.uproject" | head -1)
python3 ~/Desktop/kokopelli/ram_share.py claim --name look_game --gb 10 --pid "$PID" >/dev/null 2>&1
for ((i = 0; i < ${1:-900}; i++)); do
	if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then echo "ready pid=$PID after ${i}s"; exit 0; fi
	if ! kill -0 "$PID" 2>/dev/null; then echo "game exited"; exit 1; fi
	sleep 1
done
echo timeout; exit 1
