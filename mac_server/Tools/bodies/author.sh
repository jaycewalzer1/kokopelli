#!/usr/bin/env bash
# Tools/bodies/author.sh : regenerate the shared body assets headlessly (needs `scripts/build.sh editor` first).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UE="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.8}"
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" "$ROOT/SimWorld.uproject" -run=pythonscript \
	-script="$ROOT/Tools/bodies/author_bodies.py" -unattended -nosplash -stdout -FullStdOutLogOutput -nop4 2>&1 \
	| tee "$ROOT/Saved/author_bodies.log" | grep -E "\[BODIES\]|Error:|error:" | grep -v LogDerivedDataCache | head -60
