#!/usr/bin/env bash
# The hunger video benchmark: the egg scene at full, half and starving, one closed-loop run each (egg_wm.py), then the
# viewer overlay on each and the three side by side (kokopelli/body/overlay.py).
# Starts the packaged server only if nothing is listening on the port, and stops it afterwards only if it started it.
#
#   kokopelli/agents/run_egg_videos.sh                          # cue arm, 3 sim-minutes each, 832x480, 8-bit
#   kokopelli/agents/run_egg_videos.sh --arm label --minutes 2  # extra args go to every egg_wm.py run
#
# Queue it, don't run it bare (AGENTS.md). The mouse rule applies: ask the owner to step away first.
#   K=/Users/jaycewalzer/Desktop/kokopelli
#   python3 kokopelli/ops/gpu.py run --name egg_videos_cue --priority 32 --max-hours 6 --cwd $K \
#     --about "Hunger video benchmark: egg scene at full/half/starving, Qwen3-VL-8B 4-bit deciding from Cosmos3-Nano-Sim-Transfer frames (8-bit, 4 controls at 0.25, 832x480), cue arm, same seeds" \
#     --output out/sensation/videos -- kokopelli/agents/run_egg_videos.sh
#
# Writes out/sensation/videos/<stamp>_<arm>/{full,half,starving} (links to each run folder, with overlay.mp4) and
# hunger_triptych.mp4 with its .json sidecar. OUT=<folder> picks the folder instead.
#
# LEVELS="full" runs only those levels into OUT, so each level can be its own queue job with a pause between them (on
# a charger too small for the GPU, one long job empties the battery). The side-by-side film is made by whichever job
# finds all three overlays in OUT. VOICE=0 skips the inner voice.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-9001}"
cd "$ROOT" || exit
# The packaged server isn't in git, so a worktree has none. Use the main checkout's (the folder that holds .git).
SERVER="$ROOT/mac_server"
[[ -d "$SERVER/Packaged" ]] || SERVER="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)/mac_server"

arm=cue
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
	[[ "${args[$i]}" == "--arm" ]] && arm="${args[$((i + 1))]}"
done
OUT="${OUT:-out/sensation/videos/$(date +%Y%m%d-%H%M%S)_$arm}"
mkdir -p "$OUT"

started=""
if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1; then
	echo "starting SimWorld (minimized) on $PORT"
	[[ -d "$SERVER/Packaged" ]] || { echo "no packaged server at $SERVER/Packaged"; exit 3; }
	MINIMIZED=1 NOMOUSE=1 CVPORT="$PORT" "$SERVER/scripts/run.sh" packaged >"/tmp/egg_server_$PORT.log" 2>&1 &
	started=$!
	for _ in $(seq 1 180); do
		lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 && break
		sleep 2
	done
	lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 || { echo "server never opened $PORT"; kill "$started" 2>/dev/null; exit 3; }
	sleep 20   # let the map finish streaming in
	python3 kokopelli/ops/ram_share.py claim --name "egg_server_$PORT" --gb 10 --pid "$(pgrep -f "SimWorld.*-cvport=$PORT" | head -1)" || true
	echo "building the city on $PORT"
	# --world is named because build_city.py's own default still points at tools/world.json, which the reorg moved.
	simworld/.venv/bin/python -I tools/city_build/build_city.py --port "$PORT" --world data/city/world.json || { echo "build_city failed"; pkill -f "SimWorld.*-cvport=$PORT"; exit 4; }
fi

code=0
# shellcheck disable=SC2086  # LEVELS is a space-separated list, split on purpose
for level in ${LEVELS:-full half starving}; do
	echo "== $level"
	python3 kokopelli/ops/ram_share.py hold --name egg_agent --gb 22 -- \
		.venv/bin/python -m kokopelli.agents.egg_wm --port "$PORT" --level "$level" --out "$OUT/$level" "$@" || { code=$?; echo "$level failed ($code)"; }
	if [[ -e "$OUT/$level/world_model.mp4" ]]; then
		# The inner voice is optional: Kokoro downloads once from Hugging Face; without it the films are still complete.
		if [[ "${VOICE:-1}" == 1 ]]; then
			.venv/bin/python -m kokopelli.body.voice "$OUT/$level" || echo "no inner voice for $level; the film is fine without it"
		fi
		.venv/bin/python -m kokopelli.body.overlay one "$OUT/$level"   # also writes overlay_voice.mp4 when voice.wav exists
	fi
done

if [[ -n "$started" ]]; then
	echo "stopping the SimWorld server this script started"
	pkill -f "SimWorld.*-cvport=$PORT" || true
	# Wait for the port to close. A job queued straight after this one otherwise finds the dying server still
	# listening, starts none of its own, and fails on its first request (the full level did, 2026-11-11 02:20).
	for _ in $(seq 1 60); do
		lsof -iTCP:"$PORT" -sTCP:LISTEN -P >/dev/null 2>&1 || break
		sleep 1
	done
fi

if [[ -e "$OUT/full/overlay.mp4" && -e "$OUT/half/overlay.mp4" && -e "$OUT/starving/overlay.mp4" ]]; then
	.venv/bin/python -m kokopelli.body.overlay triptych "$OUT" || code=$?
else
	echo "no side-by-side film yet: it needs overlay.mp4 for full, half and starving in $OUT"
fi
echo "videos in $OUT"
exit $code
