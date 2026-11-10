#!/usr/bin/env bash
# Cook + package the bodies server build into mac_server/Packaged_bodies/ (wave 2). NEVER touches mac_server/Packaged/
# (queued jobs on 9001 use it; swapping is the user's call). Same UAT call as `scripts/build.sh package`, but the
# staged bundle is copied to Packaged_bodies instead of Packaged. Runs under a ram_share hold (bodies_build, 16 GB).
#   tools/bodies/package_bodies.sh [Development]
set -euo pipefail
K=~/Desktop/kokopelli
ROOT="$K/mac_server"
CONFIG="${1:-Development}"
UE="/Users/Shared/Epic Games/UE_5.8"
LOG="$ROOT/Saved/BuildLogs/package-bodies-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
cd "$K"
.venv/bin/python kokopelli/ops/ram_share.py hold --name bodies_build --gb 16 -- \
  "$UE/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun -project="$ROOT/SimWorld.uproject" -platform=Mac \
  -clientconfig="$CONFIG" -build -cook -stage -pak -unattended -utf8output -nop4 > "$LOG" 2>&1 || { tail -40 "$LOG"; exit 1; }
rm -rf "$ROOT/Packaged_bodies"
mkdir -p "$ROOT/Packaged_bodies"
ditto "$ROOT/Saved/StagedBuilds/Mac/SimWorld.app" "$ROOT/Packaged_bodies/SimWorld.app"
echo "log: $LOG"
echo "archived: $ROOT/Packaged_bodies/SimWorld.app ($(du -sh "$ROOT/Packaged_bodies/SimWorld.app" | cut -f1))"
