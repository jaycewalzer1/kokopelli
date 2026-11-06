#!/usr/bin/env bash
# Launch the SimWorld server, windowed, with the SimCV (UnrealCV-compatible) port open.
#
#   scripts/run.sh [auto|editor-game|packaged] [extra engine args...]
#
#   editor-game  UnrealEditor <project> -game  (uncooked; needs `build.sh editor`)
#   packaged     Packaged/SimWorld.app          (needs `build.sh package`)
#   auto         packaged if it exists, else editor-game   [default]
#
# Env: CVPORT (9000)  RES (1280x720)  MAP (e.g. /Game/Maps/demo_1; default from DefaultEngine.ini)
#      UE_ROOT (engine dir)  CVBIND (e.g. 0.0.0.0 to accept remote clients; default loopback)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT/SimWorld.uproject"
MODE="${1:-auto}"
[[ $# -gt 0 ]] && shift

PORT="${CVPORT:-9000}"
RES="${RES:-1280x720}"
RES_X="${RES%x*}"
RES_Y="${RES#*x}"

find_engine() {
	if [[ -n "${UE_ROOT:-}" ]]; then
		echo "$UE_ROOT"
		return
	fi
	local dirs=("/Users/Shared/Epic Games"/UE_5.*)
	[[ -d "${dirs[0]}" ]] || return 0
	printf '%s\n' "${dirs[@]}" | sort -V | tail -n 1
}

find_packaged() {
	[[ -d "$ROOT/Packaged" ]] || return 0
	find "$ROOT/Packaged" -maxdepth 3 -type d -name "SimWorld*.app" | head -n 1
}

if [[ "$MODE" == "auto" ]]; then
	if [[ -n "$(find_packaged)" ]]; then MODE=packaged; else MODE=editor-game; fi
fi

LOG_DIR="$ROOT/Saved/Logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/simworld-$MODE-$(date +%Y%m%d-%H%M%S).log"

ARGS=(-windowed -ResX="$RES_X" -ResY="$RES_Y" -cvport="$PORT" -log -ABSLOG="$LOG" -nosplash)
# UE 5.8 crash workaround (see [SystemSettings] in Config/DefaultEngine.ini); repeated here so builds
# packaged before that setting existed get it too.
ARGS+=("-ini:Engine:[SystemSettings]:r.SceneCulling.Async.Update=0")
[[ -n "${CVBIND:-}" ]] && ARGS+=(-cvbind="$CVBIND")

case "$MODE" in
	editor-game)
		UE="$(find_engine)"
		EDITOR="$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
		if [[ -z "$UE" || ! -x "$EDITOR" ]]; then
			echo "error: UnrealEditor not found (set UE_ROOT)" >&2
			exit 1
		fi
		CMD=("$EDITOR" "$PROJECT")
		[[ -n "${MAP:-}" ]] && CMD+=("$MAP")
		CMD+=(-game "${ARGS[@]}")
		;;
	packaged)
		APP="$(find_packaged)"
		if [[ -z "$APP" ]]; then
			echo "error: no packaged app under $ROOT/Build (run scripts/build.sh package)" >&2
			exit 1
		fi
		EXE="$(find "$APP/Contents/MacOS" -maxdepth 1 -type f -perm -u+x | head -n 1)"
		CMD=("$EXE")
		[[ -n "${MAP:-}" ]] && CMD+=("$MAP")
		CMD+=("${ARGS[@]}")
		;;
	*)
		echo "usage: $0 [auto|editor-game|packaged] [extra engine args...]" >&2
		exit 2
		;;
esac

CMD+=("$@")
echo "log:   $LOG"
echo "port:  $PORT   (python: unrealcv.Client(('127.0.0.1', $PORT)))"
echo "+ ${CMD[*]}"
exec "${CMD[@]}"
