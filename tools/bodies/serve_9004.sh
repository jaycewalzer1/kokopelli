#!/usr/bin/env bash
# Start (or stop) our SimWorld server on port 9004, minimized, RAM-claimed as bodies_9004. Never 9001/9003/Packaged/.
#   tools/bodies/serve_9004.sh editor|packaged [extra args]   -> prints the pid, waits for the port
#   tools/bodies/serve_9004.sh stop
set -uo pipefail
K=~/Desktop/kokopelli
MODE="${1:-editor}"; shift || true
PIDF="$K/out/bodies/wave2b/server.pid"
mkdir -p "$K/out/bodies/wave2b"
if [[ "$MODE" == stop ]]; then
  [[ -f "$PIDF" ]] && { P=$(cat "$PIDF"); kill "$P" 2>/dev/null; sleep 4; kill -9 "$P" 2>/dev/null; pkill -f "CrashReport.*pid-$P" 2>/dev/null; rm -f "$PIDF"; }
  exit 0
fi
if lsof -nP -iTCP:9004 -sTCP:LISTEN >/dev/null 2>&1; then echo "port 9004 busy" >&2; exit 1; fi
UE="/Users/Shared/Epic Games/UE_5.8"
LOG="$K/out/bodies/wave2b/server_$MODE.log"
ARGS=(-windowed -ResX=1280 -ResY=720 -cvport=9004 -log -ABSLOG="$LOG" -nosplash -swminimized "-ini:Engine:[SystemSettings]:r.SceneCulling.Async.Update=0" "$@")
if [[ "$MODE" == packaged ]]; then
  "$K/mac_server/Packaged_bodies/SimWorld.app/Contents/MacOS/SimWorld" "${ARGS[@]}" > "${LOG%.log}.stdout" 2>&1 &
else
  "$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$K/mac_server/SimWorld.uproject" -game "${ARGS[@]}" > "${LOG%.log}.stdout" 2>&1 &
fi
PID=$!
echo $PID > "$PIDF"
(cd "$K" && .venv/bin/python kokopelli/ops/ram_share.py claim --name bodies_9004 --gb 10 --pid $PID >/dev/null)
for _ in $(seq 1 200); do lsof -nP -iTCP:9004 -sTCP:LISTEN >/dev/null 2>&1 && break; kill -0 $PID 2>/dev/null || { echo "server died" >&2; exit 1; }; sleep 3; done
sleep 5
echo $PID
