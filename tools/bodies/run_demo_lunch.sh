#!/usr/bin/env bash
# Bodies demo: kokopelli/agents/run_wm_lunch.sh, but running tools/bodies/demo_lunch.py (lunch_wm.py unchanged + director
# camera, SetSpeaking gestures, captions). Starts the packaged server minimized on $PORT only if nothing listens there,
# and stops it afterwards only if it started it. Queue it through gpu.py (AGENTS.md); see out/bodies/demo/README.md.
#   tools/bodies/run_demo_lunch.sh --minutes 2 --fake-wm --out out/bodies/demo/runs/sim
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-9001}"
HOLD_GB="${HOLD_GB:-24}"
cd "$ROOT" || exit

started=""
if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1; then
	echo "starting SimWorld (minimized) on $PORT"
	MINIMIZED=1 CVPORT="$PORT" mac_server/scripts/run.sh packaged >"$ROOT/out/bodies/demo/server_$PORT.log" 2>&1 &
	started=$!
	for _ in $(seq 1 180); do
		lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 && break
		sleep 2
	done
	lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 || { echo "server never opened $PORT"; kill "$started" 2>/dev/null; exit 3; }
	sleep 20   # let the map finish streaming in
	python3 kokopelli/ops/ram_share.py claim --name "bodies_demo_server_$PORT" --gb 10 --pid "$(pgrep -f "SimWorld.*-cvport=$PORT" | head -1)" || true
fi

# The lunch code never builds the city, so build it every time (re-runnable, ~2 s; data/city/world.json, mac_server/docs/CITY.md).
simworld/.venv/bin/python -I tools/city_build/build_city.py --port "$PORT" || {
	echo "build_city failed"; [[ -n "$started" ]] && pkill -f "SimWorld.*-cvport=$PORT"; exit 4; }
sleep 5

python3 kokopelli/ops/ram_share.py hold --name bodies_demo_agents --gb "$HOLD_GB" -- .venv/bin/python tools/bodies/demo_lunch.py --port "$PORT" "$@"
code=$?

if [[ -n "$started" ]]; then
	echo "stopping the SimWorld server this script started"
	pkill -f "SimWorld.*-cvport=$PORT" || true
fi
exit $code
