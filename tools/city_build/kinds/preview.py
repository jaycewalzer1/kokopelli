#!/usr/bin/env python
"""Render one building kind in the editor on port 9003, holding the shared editor lock.

    ~/Desktop/kokopelli/simworld/.venv/bin/python -m tools.city_build.kinds.preview --kind farnsworth --w 30 --d 20 [--h 24]
        [--seed 3] [--at X,Y] [--front S] [--views front,front_r,aerial,back,eye] [--keep] [--json-only]

Writes out/city_kinds/<kind>/<HHMMSS>_<w>x<d>/{front,front_r,aerial,back,eye}.png and info.json (op counts,
build info, timings). The preview actor CITY_kitpreview is removed again unless --keep.

--at puts the plot centre at world metres X,Y (default: the empty test field west of the city, -130,345). The
lock (out/city_kinds/.editor.lock) serialises every agent's use of the one editor: the server takes one client at
a time. It is held only while rendering (about a minute); wait, never break it.
"""
import argparse
import fcntl
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from tools.city_build.kinds import Plot, all_kinds  # noqa: E402

OUT = ROOT / "out" / "city_kinds"
LOCK = OUT / ".editor.lock"
NAME = "CITY_kitpreview"


def req(c, cmd, timeout=120):
    r = c.request(cmd, timeout=timeout)
    return r if isinstance(r, str) else r.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True)
    ap.add_argument("--w", type=float, required=True)
    ap.add_argument("--d", type=float, required=True)
    ap.add_argument("--h", type=float, default=24.0)
    ap.add_argument("--floors", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--use", default="homes")
    ap.add_argument("--at", default="-130,345")
    ap.add_argument("--front", default="N", choices=list("NSEW"))
    ap.add_argument("--views", default="front,front_r,aerial,back,eye")
    ap.add_argument("--port", type=int, default=9003)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json-only", action="store_true", help="build the kit and print stats, no editor")
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()
    if args.port == 9001:
        sys.exit("port 9001 is the user's live server: never")

    kinds = all_kinds()
    if args.kind not in kinds:
        sys.exit(f"unknown kind {args.kind}; known: {', '.join(sorted(kinds))}")
    plot = Plot(w=args.w, d=args.d, h_max=args.h, floors=args.floors, seed=args.seed, use=args.use)
    t0 = time.time()
    kit = kinds[args.kind][1](plot)
    cx, cy = (float(v) for v in args.at.split(","))
    ex, ey = (args.w, args.d) if args.front in "NS" else (args.d, args.w)
    rect = [cx - ex / 2, cy - ey / 2, cx + ex / 2, cy + ey / 2]
    cfg = kit.config(rect, args.front)
    js = json.dumps(cfg, separators=(",", ":"))
    info = {"kind": args.kind, "plot": vars(plot) | {"palette": plot.palette}, "rect_m": rect, "front": args.front,
            "kit": kit.stats(), "json_kb": round(len(js) / 1e3, 1), "python_s": round(time.time() - t0, 2)}
    print(json.dumps(info))
    if args.json_only:
        return

    # camera ring around the plot, in world metres; local front direction -> world
    fx, fy = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[args.front]
    rx, ry = -fy, fx  # local +x (along the frontage) in world
    hgt = max(6.0, min(args.h, 40.0))
    R = min(max(args.w, args.d, hgt) * 1.25 + 8, 75.0)  # wide rows: stay inside the test field's hedges

    def pose(ang_from_front, dist, z, look_z):
        a = math.radians(ang_from_front)
        dx, dy = fx * math.cos(a) + rx * math.sin(a), fy * math.cos(a) + ry * math.sin(a)
        px, py = cx + dx * dist, cy + dy * dist
        yaw = math.degrees(math.atan2(cy - py, cx - px))
        pitch = math.degrees(math.atan2(look_z - z, dist))
        return px, py, z, pitch, yaw

    views = {
        "front": pose(-28, R, 1.7, hgt * 0.45),
        "front_r": pose(35, R * 0.9, 6.0, hgt * 0.4),
        "aerial": pose(-40, R * 1.1, R * 0.9, 0),
        "back": pose(150, R, 3.0, hgt * 0.4),
        "eye": pose(5, max(args.d * 0.5, 9.0), 1.7, 3.0),
    }
    want = [v.strip() for v in args.views.split(",") if v.strip()]
    out = OUT / args.kind / f"{datetime.now():%H%M%S}_{args.w:g}x{args.d:g}"
    out.mkdir(parents=True, exist_ok=True)

    from unrealcv import Client
    import warnings
    warnings.filterwarnings("ignore")
    OUT.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as lk:
        tw = time.time()
        print("waiting for the editor lock...", flush=True)
        fcntl.flock(lk, fcntl.LOCK_EX)
        lk.seek(0), lk.truncate(), lk.write(f"{os.getpid()} {args.kind} {datetime.now():%H:%M:%S}\n"), lk.flush()
        info["lock_wait_s"] = round(time.time() - tw, 1)
        c = Client(("127.0.0.1", args.port))
        if not c.connect(timeout=10):
            sys.exit(f"cannot connect to the editor on {args.port} (is it running? see tools/city_build/kinds/README.md)")
        try:
            names = req(c, "vget /objects").split()
            if any(n.lower() == NAME.lower() for n in names):
                req(c, f"vset /object/{NAME}/destroy")
            req(c, f"vset /objects/spawn_bp_asset /Script/SimWorld.SWCityKit {NAME}")
            t1 = time.time()
            r = req(c, f"vbp {NAME} Configure {js}", timeout=300)
            info["configure_s"] = round(time.time() - t1, 2)
            try:
                info["build"] = json.loads(json.loads(req(c, f"vbp {NAME} GetBuildInfo"))["Info"])
            except Exception:
                info["build"] = {"reply": r[:200]}
            req(c, "vset /action/game/resume")
            req(c, "vset /camera/0/size 1280 720")
            req(c, "vset /camera/0/fov 75")
            for v in want:
                px, py, pz, pitch, yaw = views[v]
                req(c, f"vset /camera/0/location {px * 100:.1f} {py * 100:.1f} {pz * 100:.1f}")
                req(c, f"vset /camera/0/rotation {pitch:.2f} {yaw:.2f} 0")
                time.sleep(args.settle)
                req(c, f"vget /camera/0/lit {out / (v + '.png')}")
            if not args.keep:
                req(c, f"vset /object/{NAME}/destroy")
        finally:
            c.disconnect()
            lk.seek(0), lk.truncate(), lk.flush()
            fcntl.flock(lk, fcntl.LOCK_UN)
    (out / "info.json").write_text(json.dumps(info, indent=1))
    print("build:", info.get("build"), "wrote", out)


if __name__ == "__main__":
    main()
