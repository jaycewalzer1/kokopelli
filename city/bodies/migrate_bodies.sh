#!/usr/bin/env bash
# Migrate agent A's MetaHuman bodies from the scratch project into the server (wave 2, city/bodies/PLAN.md).
# Re-runnable: run it again after make_bodies.py has rebuilt the bodies (e.g. once Core Data is installed).
#
#   city/bodies/migrate_bodies.sh [scratch_project]     (default out/bodies/scratch_project)
#
# The package paths are identical in both projects (/Game/Characters/Bodies/...), so a file copy is a valid
# migration: no references need fixing. Copied: per person <id>/{High,Low}/ (body + face meshes, materials,
# textures, physics, DNA) and the shared Common/ folder. Left out: MHC_<id> (editable MetaHuman Creator character,
# editor-only, needs the MetaHumanCharacter plugin), BP_<id>_* (assembled actor blueprints; the server builds its
# own actor) and Render/ (A's render level). The destination folder is mirrored (--delete), so stale files of an
# earlier migration go away; nothing outside mac_server/Content/Characters/Bodies is touched.
# Writes out/bodies/migrate.json (what was copied, sizes, whether Core Data was installed).
set -euo pipefail
K=~/Desktop/kokopelli
SRC="${1:-$K/out/bodies/scratch_project}/Content/Characters/Bodies"
DST="$K/mac_server/Content/Characters/Bodies"
OPT="/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional"
[[ -d "$SRC/Common" ]] || { echo "error: no bodies in $SRC (run city/bodies/metahuman/make_bodies.py first)" >&2; exit 1; }
if pgrep -f "UnrealEditor.*$K/mac_server/SimWorld.uproject" >/dev/null; then
  echo "error: an editor/game on mac_server/SimWorld.uproject is running; stop it before replacing its assets" >&2
  exit 1
fi
mkdir -p "$DST"
rsync -a --delete --exclude 'MHC_*.uasset' --exclude 'BP_*.uasset' --exclude '/Render/' "$SRC/" "$DST/"
"$K/.venv/bin/python" - "$SRC" "$DST" "$OPT" <<'PY'
import json, os, sys, time, pathlib
src, dst, opt = map(pathlib.Path, sys.argv[1:])
def size(p):
    return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
people = sorted(p.name for p in dst.iterdir() if p.is_dir() and p.name != 'Common')
out = {
    'when': time.strftime('%Y-%m-%d %H:%M:%S'),
    'source': str(src), 'dest': str(dst), 'script': 'city/bodies/migrate_bodies.sh',
    'core_data_installed': (opt / 'BodyTextures').exists() or (opt / 'TextureSynthesis').exists(),
    'people': {p: {t: round(size(dst / p / t) / 1e6, 1) for t in ('High', 'Low') if (dst / p / t).exists()} for p in people},
    'common_mb': round(size(dst / 'Common') / 1e6, 1),
    'total_mb': round(size(dst) / 1e6, 1),
    'files': sum(1 for _ in dst.rglob('*.uasset')),
}
k = pathlib.Path(os.path.expanduser('~/Desktop/kokopelli/out/bodies'))
k.mkdir(parents=True, exist_ok=True)
(k / 'migrate.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
PY
