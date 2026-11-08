#!/usr/bin/env bash
# One life inside the world model, start to finish: SimWorld server (minimized, port 9001) + live_wm.py.
# Starts the packaged server only if nothing is listening on the port, and stops it afterwards only if it started it.
#
#   city/agents/run_wm_life.sh --minutes 5            # extra args go to live_wm.py
#
# Queue it, don't run it bare (AGENTS.md): python3 .claude/worktrees/ops/ops/gpu.py run --name wmlife_... -- city/agents/run_wm_life.sh ...
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-9001}"
cd "$ROOT"

started=""
if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1; then
	echo "starting SimWorld (minimized) on $PORT"
	MINIMIZED=1 CVPORT="$PORT" mac_server/scripts/run.sh packaged >/tmp/wmlife_server_$PORT.log 2>&1 &
	started=$!
	for _ in $(seq 1 180); do
		lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 && break
		sleep 2
	done
	lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 || { echo "server never opened $PORT"; kill "$started" 2>/dev/null; exit 3; }
	sleep 20   # let the map finish streaming in
	python3 ram_share.py claim --name "wmlife_server_$PORT" --gb 10 --pid "$(pgrep -f "SimWorld.*-cvport=$PORT" | head -1)" || true
	echo "building the city on $PORT"
	simworld/.venv/bin/python -I city/ue/build_city.py --port "$PORT" || { echo "build_city failed"; pkill -f "SimWorld.*-cvport=$PORT"; exit 4; }
fi

python3 ram_share.py hold --name wmlife_agent --gb 22 -- .venv/bin/python city/agents/live_wm.py --port "$PORT" "$@"
code=$?

if [[ -n "$started" ]]; then
	echo "stopping the SimWorld server this script started"
	pkill -f "SimWorld.*-cvport=$PORT" || true
fi
exit $code
