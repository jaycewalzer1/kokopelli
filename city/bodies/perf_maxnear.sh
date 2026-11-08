#!/usr/bin/env bash
# Perf + peak memory of MetaHuman bodies for several max_near values (wave 2). Port 9004 only.
# For each N: a fresh server with Bodies.json max_near=N (-bodies=<tmp copy>), RAM claim bodies_9004, city build,
# city/bodies/wave2_renders.py perf, then the server is stopped. Results: out/bodies/renders/wave2/perf_maxnear<N>.json
#
#   city/bodies/perf_maxnear.sh packaged|editor [N ...]      (default N: 3 5 8)
#   packaged = mac_server/Packaged_bodies/SimWorld.app (never mac_server/Packaged/)
set -uo pipefail
K=~/Desktop/kokopelli
MODE="${1:-packaged}"; shift || true
NS=("${@:-3 5 8}"); NS=(${NS[@]})
PORT=9004
OUT="$K/out/bodies/renders/wave2"
PY="$K/simworld/.venv/bin/python"
UE="/Users/Shared/Epic Games/UE_5.8"
mkdir -p "$OUT"
for N in "${NS[@]}"; do
  if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then echo "port $PORT busy; stop the 9004 server first" >&2; exit 1; fi
  J="$OUT/Bodies_maxnear$N.json"
  "$PY" -c "import json,sys;d=json.load(open('$K/mac_server/Config/Bodies.json'));d['max_near']=$N;json.dump(d,open('$J','w'),indent=1)"
  LOG="$OUT/server_maxnear$N.log"
  ARGS=(-windowed -ResX=1280 -ResY=720 -cvport=$PORT -log -ABSLOG="$LOG" -nosplash -swminimized
        "-ini:Engine:[SystemSettings]:r.SceneCulling.Async.Update=0" -bodies="$J")
  if [[ "$MODE" == packaged ]]; then
    EXE="$K/mac_server/Packaged_bodies/SimWorld.app/Contents/MacOS/SimWorld"
    "$EXE" "${ARGS[@]}" > "$OUT/server_maxnear$N.stdout" 2>&1 &
  else
    "$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$K/mac_server/SimWorld.uproject" -game "${ARGS[@]}" \
      > "$OUT/server_maxnear$N.stdout" 2>&1 &
  fi
  PID=$!
  (cd "$K" && .venv/bin/python ram_share.py claim --name bodies_9004 --gb 10 --pid $PID >/dev/null)
  "$PY" - <<PYEOF
import socket, time
t = time.time()
while time.time() - t < 600:
    try:
        socket.create_connection(('127.0.0.1', $PORT), 1).close(); break
    except OSError:
        time.sleep(3)
PYEOF
  sleep 3
  (cd "$K" && "$PY" city/ue/build_city.py --port $PORT > "$OUT/build_city_maxnear$N.log" 2>&1)
  (cd "$K" && "$PY" city/bodies/wave2_renders.py perf --max-near $N --pid $PID --out "$OUT") || echo "perf N=$N failed"
  kill $PID; wait $PID 2>/dev/null
  pkill -f "CrashReport.*pid-$PID" 2>/dev/null || true
done
