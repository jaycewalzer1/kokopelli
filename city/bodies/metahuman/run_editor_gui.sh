#!/usr/bin/env bash
# Run an editor-Python script in the full (windowed) editor against the bodies scratch project; the script
# must call unreal.SystemLibrary.quit_editor() when done (MH_QUIT=1). Claims RAM as bodies_mh_editor. -nosimcv: the editor opens no SimCV port (9004 belongs to agent B's test game).
#   city/bodies/metahuman/run_editor_gui.sh <script.py> [log]
set -uo pipefail
K=~/Desktop/kokopelli
PROJ="${MH_PROJECT:-$K/out/bodies/scratch_project/SimWorld.uproject}"
UE="/Users/Shared/Epic Games/UE_5.8"
SCRIPT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
LOG="$(cd "$(dirname "${2:-$K/out/bodies/editor_gui.log}")" && pwd)/$(basename "${2:-editor_gui.log}")"
export MH_QUIT=1
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$PROJ" -ExecutePythonScript="$SCRIPT" \
  -unattended -nosplash -nop4 -log -ABSLOG="$LOG" -nosimcv -ResX=1280 -ResY=720 -windowed \
  -ini:Engine:[ConsoleVariables]:mh.Character.SuppressContentWarnings=1 ${MH_EXTRA:-} > "${LOG%.log}.stdout" 2>&1 &
PID=$!
cd "$K" && .venv/bin/python ram_share.py claim --name bodies_mh_editor --gb 10 --pid $PID >/dev/null
# minimize the editor window once it exists (Metal present leak)
( sleep 60; osascript -e 'tell application "System Events" to set miniaturized of every window of (every process whose unix id is '$PID') to true' >/dev/null 2>&1 ) &
wait $PID; rc=$?
# UE 5.8 often crashes in Slate teardown after quit_editor (work already saved); don't leave its crash reporter running.
sleep 2; pkill -f "CrashReport-UE-SimWorld-pid-$PID" 2>/dev/null || true
grep -E "\[MH\]|Error:|Critical" "$LOG" | grep -v "LogDerivedDataCache\|LogShader" | head -150 | cut -c1-600
exit $rc
