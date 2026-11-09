#!/usr/bin/env bash
# Apply MetaHuman Creator Core Data to the city bodies, end to end (wave 2b). Re-runnable.
#
#   city/bodies/apply_core_data.sh [--check-only] [--skip-make]
#
#   1. make_bodies.py   skin, hair, brows, beard, outfit from city/bodies/looks.json; High + Low assembly (scratch project)
#   2. add_fade.py      BodyFade on the (re-copied) Common masters
#   3. migrate_bodies.sh  scratch -> mac_server/Content/Characters/Bodies
#   4. write_parts.py   Bodies.json grooms/outfit (+ kai's height) from what the assembly produced
#   5. package_bodies.sh  cook + package -> mac_server/Packaged_bodies (never Packaged/)
#   6. full conformance suite on the packaged build, port 9004
#   7. city build + wave2_renders.py evidence -> out/bodies/renders/wave2_core/ (contact_sheet.png)
#
# Exit codes: 0 done, 3 Core Data not installed (nothing changed), 4 deferred (a bodies_demo* or wm* job is running or
# waiting in the GPU queue: our 9004 server is stopped; re-run later), 5 a step failed (see out/bodies/wave2_core.log).
# Rules (city/bodies/PLAN.md): port 9004 only, every Unreal process RAM-claimed (the helpers do it), never 9001/9003
# or mac_server/Packaged/. Env: CORE_DATA_DIR (default the engine's MetaHumanCharacter Content/Optional).
set -uo pipefail
K=~/Desktop/kokopelli
OPT="${CORE_DATA_DIR:-/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional}"
OUT="$K/out/bodies/renders/wave2_core"
LOG="$K/out/bodies/wave2_core.log"
CHECK_ONLY=0; SKIP_MAKE=0
for a in "$@"; do
  case "$a" in --check-only) CHECK_ONLY=1;; --skip-make) SKIP_MAKE=1;; esac
done

if [[ ! -d "$OPT/TextureSynthesis" ]]; then
  echo "MetaHuman Creator Core Data is not installed ($OPT/TextureSynthesis missing)."
  echo "Install it in the Epic Games Launcher: Unreal Engine > Library > 5.8 > Options > 'MetaHuman Creator Core Data'."
  exit 3
fi
[[ $CHECK_ONLY == 1 ]] && { echo "Core Data present: $OPT"; exit 0; }

mkdir -p "$OUT" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "== apply_core_data $(date '+%Y-%m-%d %H:%M:%S')"
PY="$K/.venv/bin/python"
SPY="$K/simworld/.venv/bin/python"
STEPS=()

# Heavy steps only while no demo or world-model job is RUNNING or waiting in the GPU queue (coordinator, 2026-11-08:
# the bodies_demo_* two-agent demo on 9001 and wm* runs have priority). Otherwise keep our 9004 game down.
queue_ok() {
  local st; st="$(python3 "$K/.claude/worktrees/ops/ops/gpu.py" status 2>/dev/null)" || return 1
  if echo "$st" | grep -E '^(RUNNING|waiting)\s+\S+\s+(wmbodies|bodies_demo)' >/dev/null; then return 1; fi
  return 0
}
gate() {  # gate <step name>
  if ! queue_ok; then
    echo "DEFERRED before '$1': a bodies_demo* or wm* job is running or waiting in the GPU queue. Stopping our 9004 server."
    "$K/city/bodies/serve_9004.sh" stop
    summary deferred "$1"
    exit 4
  fi
  echo "-- $1 ($(date +%H:%M:%S))"
}
summary() {  # summary <status> [step]
  "$PY" - "$OUT/apply.json" "$1" "${2:-}" "${STEPS[@]:-}" <<'PY'
import json, sys, time
path, status, step, *steps = sys.argv[1:]
json.dump({"status": status, "at_step": step or None, "steps_done": [s for s in steps if s], "when": time.strftime("%Y-%m-%d %H:%M:%S"),
           "script": "city/bodies/apply_core_data.sh", "log": "out/bodies/wave2_core.log"}, open(path, "w"), indent=1)
PY
}
fail() { echo "FAILED: $1"; "$K/city/bodies/serve_9004.sh" stop; summary failed "$1"; exit 5; }

"$K/city/bodies/serve_9004.sh" stop   # assets are about to change under it

# Light preparation (no Unreal): resolve looks.json against the installed wardrobe before any gate.
python3 "$K/city/bodies/metahuman/looks.py" --check --json > "$OUT/looks_check.json"
python3 "$K/city/bodies/metahuman/looks.py" --check || fail "looks.json does not resolve against the installed wardrobe (see $OUT/looks_check.json)"
STEPS+=(looks_check)
[[ ${PREPARE_ONLY:-0} == 1 ]] && { summary prepared looks_check; echo "prepared; heavy steps not started"; exit 0; }

if [[ $SKIP_MAKE == 0 ]]; then
  gate "make_bodies"
  rm -f "$K/out/bodies/make/status.json"
  "$K/city/bodies/metahuman/run_editor_gui.sh" "$K/city/bodies/metahuman/make_bodies.py" "$K/out/bodies/make_core.log"
  "$PY" -c "import json,sys; s=json.load(open('$K/out/bodies/make/status.json')); print(s); sys.exit(0 if s['status']=='ok' else 1)" \
    || fail "make_bodies (see out/bodies/make_core.log, out/bodies/make/make_report.json)"
  STEPS+=(make_bodies)
  gate "add_fade"
  "$K/city/bodies/metahuman/run_editor_gui.sh" "$K/city/bodies/metahuman/add_fade.py" "$K/out/bodies/add_fade_core.log" || fail add_fade
  STEPS+=(add_fade)
fi

gate "migrate"
"$K/city/bodies/migrate_bodies.sh" > "$K/out/bodies/migrate_core.log" 2>&1 || fail "migrate_bodies (out/bodies/migrate_core.log)"
STEPS+=(migrate)
"$PY" "$K/city/bodies/write_parts.py" || fail write_parts
STEPS+=(write_parts)
# Chaos outfit assets draw with the ChaosClothComponent: the plugin must be on for the cook.
if grep -q "ChaosOutfitAsset" "$K/out/bodies/write_parts.json"; then
  "$PY" - "$K/mac_server/SimWorld.uproject" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
if not any(x.get("Name") == "ChaosOutfitAsset" for x in d.get("Plugins", [])):
    d.setdefault("Plugins", []).append({"Name": "ChaosOutfitAsset", "Enabled": True})
    json.dump(d, open(p, "w"), indent="\t"); print("enabled ChaosOutfitAsset in", p)
PY
fi

gate "package"
"$K/city/bodies/package_bodies.sh" || fail "package_bodies"
STEPS+=(package)

gate "suite"
"$K/city/bodies/serve_9004.sh" packaged >/dev/null || fail "packaged server did not start"
(cd "$K" && SIMCV_PORT=9004 "$SPY" -I -m pytest mac_server/tests -q -p no:cacheprovider > "$OUT/suite.log" 2>&1)
SUITE_RC=$?
tail -3 "$OUT/suite.log"
STEPS+=("suite_rc_$SUITE_RC")

gate "renders"
(cd "$K" && "$SPY" city/ue/build_city.py --port 9004 > "$OUT/build_city.log" 2>&1) || fail "city build"
(cd "$K" && "$SPY" city/bodies/wave2_renders.py evidence --port 9004 --out "$OUT" --label packaged-core-data) || fail "renders"
STEPS+=(renders)
"$K/city/bodies/serve_9004.sh" stop
summary "$([[ $SUITE_RC == 0 ]] && echo ok || echo suite_failed)"
echo "contact sheet: $OUT/contact_sheet.png"
if [[ $SUITE_RC == 0 ]]; then
  echo "- $(date '+%Y-%m-%d %H:%M') (wave 2b, apply_core_data.sh) TO THE DEMO AGENT: a Core-Data mac_server/Packaged_bodies/SimWorld.app is ready (skin, hair, brows, outfits; $(tail -1 "$OUT/suite.log" | tr -d '=')); renders out/bodies/renders/wave2_core/contact_sheet.png. Not swapped into Packaged/: your call before the world-model run." >> "$K/city/bodies/LOG.md"
fi
[[ $SUITE_RC == 0 ]] || exit 5
