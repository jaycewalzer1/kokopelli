#!/usr/bin/env bash
# Tools/author.sh [only=M_A,M_B] : regenerate textures + materials headlessly.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UE="/Users/Shared/Epic Games/UE_5.8"
TEX="$ROOT/Saved/sp_tex"
~/Desktop/kokopelli/simworld/.venv/bin/python "$ROOT/Tools/gen_textures.py" "$TEX" >/dev/null
export SP_TEX_DIR="$TEX" SP_ONLY="${1:-}"
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$ROOT/SimWorld.uproject" -run=pythonscript -script="$ROOT/Tools/make_materials.py" -unattended -nosplash -stdout -FullStdOutLogOutput -nop4 2>&1 | tee "$ROOT/Saved/author.log" | grep -E "\[SP\]|Error|error:|Failed" | grep -v "LogDerivedDataCache" | head -80
