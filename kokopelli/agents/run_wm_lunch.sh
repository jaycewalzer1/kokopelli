#!/usr/bin/env bash
# Two agents meet for lunch inside the world model: SimWorld server (minimized, port 9001) + lunch_wm.py.
# Starts the packaged server only if nothing is listening on the port, and stops it afterwards only if it started it.
#
#   kokopelli/agents/run_wm_lunch.sh --minutes 5          # extra args go to lunch_wm.py (--fps, --size, --quantize 8, ...)
#
# Queue it, don't run it bare (AGENTS.md):
#   python3 kokopelli/ops/gpu.py run --name wmlunch_... -- kokopelli/agents/run_wm_lunch.sh --minutes 5
# Memory: one world-model worker (weights ~14 GB only while painting, ~2 GB history per agent kept) and Qwen 4-bit
# (~6 GB only while deciding) take turns; SimWorld ~10 GB is claimed separately.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-9001}"
cd "$ROOT" || exit

started=""
if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1; then
	echo "starting SimWorld (minimized) on $PORT"
	MINIMIZED=1 NOMOUSE=1 CVPORT="$PORT" mac_server/scripts/run.sh packaged >"/tmp/wmlunch_server_$PORT.log" 2>&1 &
	started=$!
	for _ in $(seq 1 180); do
		lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 && break
		sleep 2
	done
	lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 || { echo "server never opened $PORT"; kill "$started" 2>/dev/null; exit 3; }
	sleep 20   # let the map finish streaming in
	python3 kokopelli/ops/ram_share.py claim --name "wmlunch_server_$PORT" --gb 10 --pid "$(pgrep -f "SimWorld.*-cvport=$PORT" | head -1)" || true
	echo "building the city on $PORT"
	simworld/.venv/bin/python -I tools/city_build/build_city.py --port "$PORT" || { echo "build_city failed"; pkill -f "SimWorld.*-cvport=$PORT"; exit 4; }
fi

python3 kokopelli/ops/ram_share.py hold --name wmlunch_agents --gb 24 -- .venv/bin/python -m kokopelli.agents.lunch_wm --port "$PORT" "$@"
code=$?

if [[ -n "$started" ]]; then
	echo "stopping the SimWorld server this script started"
	pkill -f "SimWorld.*-cvport=$PORT" || true
fi
exit $code
