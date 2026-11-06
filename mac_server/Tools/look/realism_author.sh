#!/usr/bin/env bash
# Tools/look/realism_author.sh [only=M_A_Real,M_B_Real] : pack the realism textures and (re)build /Game/Realism headlessly.
# Sources: Saved/realism_src/<ambientCG id>/ (city/realism/ASSETS.md says where each came from).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UE="/Users/Shared/Epic Games/UE_5.8"
TEX="$ROOT/Saved/realism_tex"
~/Desktop/kokopelli/simworld/.venv/bin/python -I "$ROOT/Tools/look/realism_tex.py" "$ROOT/Saved/realism_src" "$TEX" >/dev/null || exit 1
cp "$TEX/means.json" "$ROOT/Tools/look/realism_means.json"
export RL_TEX_DIR="$TEX" RL_ONLY="${1:-}"
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$ROOT/SimWorld.uproject" -run=pythonscript -script="$ROOT/Tools/look/make_realism.py" -unattended -nosplash -stdout -FullStdOutLogOutput -nop4 2>&1 | tee "$ROOT/Saved/realism_author.log" | grep -E "\[RL\]|Error|error:|Failed" | grep -v "LogDerivedDataCache" | head -80
