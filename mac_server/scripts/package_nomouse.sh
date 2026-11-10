#!/usr/bin/env bash
# Cook + package the current server source (with the -nomouse fix) into mac_server/Packaged_nomouse/. Never touches
# Packaged/ or Packaged_bodies/. Same UAT call as city/bodies/package_bodies.sh, under a ram_share hold of 16 GB.
#   mac_server/scripts/package_nomouse.sh [Development]
set -euo pipefail
K=~/Desktop/kokopelli
ROOT="$K/mac_server"
CONFIG="${1:-Development}"
UE="/Users/Shared/Epic Games/UE_5.8"
LOG="$ROOT/Saved/BuildLogs/package-nomouse-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
cd "$K"
# The build's 16 GB claim leaves no room for a 24 GB paint, so it would stall every queued GPU job for hours. Let the
# queue drain first: start at the first moment nothing is running or waiting. NOWAIT=1 skips this.
if [[ "${NOWAIT:-0}" != 1 ]]; then
  until python3 ops/gpu.py status | grep -qx idle; do sleep 120; done
fi
.venv/bin/python ram_share.py hold --name nomouse_build --gb 16 -- \
  "$UE/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun -project="$ROOT/SimWorld.uproject" -platform=Mac \
  -clientconfig="$CONFIG" -build -cook -stage -pak -unattended -utf8output -nop4 > "$LOG" 2>&1 || { tail -40 "$LOG"; exit 1; }
rm -rf "$ROOT/Packaged_nomouse"
mkdir -p "$ROOT/Packaged_nomouse"
ditto "$ROOT/Saved/StagedBuilds/Mac/SimWorld.app" "$ROOT/Packaged_nomouse/SimWorld.app"
echo "log: $LOG"
echo "archived: $ROOT/Packaged_nomouse/SimWorld.app ($(du -sh "$ROOT/Packaged_nomouse/SimWorld.app" | cut -f1))"
