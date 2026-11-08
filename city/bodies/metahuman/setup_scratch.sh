#!/usr/bin/env bash
# Recreate the bodies scratch project: a copy of mac_server (no Binaries/Intermediate/Saved/Packaged/DDC) with the
# MetaHuman Creator + Python plugins and the MHLocal helper plugin enabled, then build the editor target.
#   city/bodies/metahuman/setup_scratch.sh [dest]   (default out/bodies/scratch_project)
set -euo pipefail
K=~/Desktop/kokopelli
DEST="${1:-$K/out/bodies/scratch_project}"
mkdir -p "$DEST"
rsync -a --exclude Binaries --exclude Intermediate --exclude Saved --exclude 'Packaged*' --exclude DerivedDataCache \
  --exclude Build --exclude tests --exclude examples --exclude Content/Characters "$K/mac_server/" "$DEST/"
rsync -a "$K/mac_server/Build/" "$DEST/Build/"
mkdir -p "$DEST/Plugins/MHLocal" && rsync -a "$K/city/bodies/metahuman/MHLocal/" "$DEST/Plugins/MHLocal/"
"$K/.venv/bin/python" - "$DEST/SimWorld.uproject" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
have = {x['Name'] for x in d['Plugins']}
for n in ['PythonScriptPlugin', 'EditorScriptingUtilities', 'MetaHumanCharacter', 'MetaHumanSDK', 'RigLogic', 'HairStrands', 'MHLocal']:
    if n not in have:
        d['Plugins'].append({'Name': n, 'Enabled': True})
d['Description'] = 'SCRATCH COPY for bodies wave 1 (MetaHuman spike). Not the server.'
json.dump(d, open(p, 'w'), indent='\t')
PY
"$DEST/scripts/build.sh" editor
