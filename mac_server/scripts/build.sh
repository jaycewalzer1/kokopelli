#!/usr/bin/env bash
# Build the SimWorld Mac server.
#
#   scripts/build.sh [editor|game|package|xcode|clean] [Development|DebugGame|Shipping]
#
#   editor   compile SimWorldEditor (fastest check; needed for run.sh editor-game)   [default]
#   game     compile the standalone SimWorld game target (no cook)
#   package  RunUAT BuildCookRun -> Build/Mac/SimWorld.app (cooked, pak'd)
#   xcode    generate SimWorld.xcworkspace
#   clean    delete Binaries/ and Intermediate/ (project + plugin)
#
# Engine: $UE_ROOT if set, else the newest "/Users/Shared/Epic Games/UE_5.*".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT/SimWorld.uproject"
MODE="${1:-editor}"
CONFIG="${2:-Development}"

find_engine() {
	if [[ -n "${UE_ROOT:-}" ]]; then
		echo "$UE_ROOT"
		return
	fi
	local dirs=("/Users/Shared/Epic Games"/UE_5.*)
	[[ -d "${dirs[0]}" ]] || return 0
	printf '%s\n' "${dirs[@]}" | sort -V | tail -n 1
}

UE="$(find_engine)"
if [[ -z "$UE" || ! -x "$UE/Engine/Build/BatchFiles/Mac/Build.sh" ]]; then
	echo "error: Unreal Engine not found. Install UE 5.x from the Epic launcher or set UE_ROOT=/path/to/UE_5.x" >&2
	exit 1
fi

if ! xcodebuild -version >/dev/null 2>&1; then
	echo "error: xcodebuild not usable. Point xcode-select at the full Xcode: sudo xcode-select -s /Applications/Xcode.app" >&2
	exit 1
fi

LOG_DIR="$ROOT/Saved/BuildLogs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/build-$MODE-$(date +%Y%m%d-%H%M%S).log"
echo "engine:  $UE"
echo "xcode:   $(xcodebuild -version | head -n 1)"
echo "mode:    $MODE ($CONFIG)"
echo "log:     $LOG"

BUILD_SH="$UE/Engine/Build/BatchFiles/Mac/Build.sh"
RUN_UAT="$UE/Engine/Build/BatchFiles/RunUAT.sh"

run() {
	echo "+ $*"
	"$@" 2>&1 | tee "$LOG"
	return "${PIPESTATUS[0]}"
}

case "$MODE" in
	editor)
		run "$BUILD_SH" SimWorldEditor Mac "$CONFIG" -project="$PROJECT" -waitmutex
		;;
	game)
		run "$BUILD_SH" SimWorld Mac "$CONFIG" -project="$PROJECT" -waitmutex
		;;
	package)
		run "$RUN_UAT" BuildCookRun \
			-project="$PROJECT" \
			-platform=Mac \
			-clientconfig="$CONFIG" \
			-build -cook -stage -pak -archive \
			-archivedirectory="$ROOT/Build" \
			-unattended -utf8output -nop4
		;;
	xcode)
		run "$UE/Engine/Build/BatchFiles/Mac/GenerateProjectFiles.sh" -project="$PROJECT" -game
		;;
	clean)
		rm -rf "$ROOT/Binaries" "$ROOT/Intermediate" "$ROOT/Plugins/SimCV/Binaries" "$ROOT/Plugins/SimCV/Intermediate"
		echo "cleaned"
		;;
	*)
		echo "usage: $0 [editor|game|package|xcode|clean] [Development|DebugGame|Shipping]" >&2
		exit 2
		;;
esac
