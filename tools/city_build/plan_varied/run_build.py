#!/usr/bin/env python
"""Clear + build the varied city on the 9003 editor and render it. Run it inside the shared editor lock:

    simworld/.venv/bin/python -m tools.city_build.kinds.locked -- simworld/.venv/bin/python -m tools.city_build.plan_varied.run_build --label r1

Kinds that don't exist yet are mapped to example_pavilion in a scratch copy (out/city_kinds/planner/scratch_world.json);
data/city/world.json itself is never changed. Renders: render_views.py --only aerial,street plus this folder's
views.py (per-cell views), into out/city_kinds/planner/<label>/.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / "simworld" / ".venv" / "bin" / "python")
OUT = ROOT / "out" / "city_kinds" / "planner"


def scratch_world(src):
    from tools.city_build.kinds import all_kinds
    have = set(all_kinds())
    w = json.loads(Path(src).read_text())
    missing = sorted({b["arch"] for b in w["buildings"] if b.get("arch") and b["arch"] not in have})
    for b in w["buildings"]:
        if b.get("arch") in missing:
            b["arch_planned"] = b["arch"]
            b["arch"] = "example_pavilion"
    dst = OUT / "scratch_world.json"
    dst.write_text(json.dumps(w))
    return dst, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--world", default=str(ROOT / "data" / "city" / "world.json"))
    ap.add_argument("--port", default="9003")
    ap.add_argument("--views", default="aerial,street", help="render_views.py --only filter ('' = skip)")
    ap.add_argument("--mine", default="all", help="views.py --only filter ('' = skip)")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--perf", default="0", help="render_views.py --perf seconds (frame stats at overview/street/bridge)")
    args = ap.parse_args()
    assert args.port != "9001"
    out = OUT / args.label
    out.mkdir(parents=True, exist_ok=True)
    world, missing = scratch_world(args.world)
    print("placeholder kinds (example_pavilion):", missing, flush=True)
    t0 = time.time()
    if not args.no_build:
        subprocess.check_call([PY, str(ROOT / "tools/city_build/build_city.py"), "--port", args.port, "--clear"])
        r = subprocess.call([PY, str(ROOT / "tools/city_build/build_city.py"), "--port", args.port, "--world", str(world)])
        print(f"build rc {r} after {time.time() - t0:.0f}s", flush=True)
    if args.mine:
        subprocess.call([PY, str(ROOT / "tools/city_build/plan_varied/views.py"), "--port", args.port, "--only", "" if args.mine == "all" else args.mine, "--out", str(out)])
    if args.views:  # after views.py, so the perf sample (if any) runs on a warm scene
        subprocess.call([PY, str(ROOT / "tools/city_build/render_views.py"), "--port", args.port, "--only", args.views, "--out", str(out), "--perf", args.perf])
    (out / "missing_kinds.json").write_text(json.dumps(missing))
    print(f"done in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
