#!/usr/bin/env python
"""Capture lit 1280x720 views of the solarpunk city from the SimWorld server.

    ~/Desktop/kokopelli/simworld/.venv/bin/python city/ue/render_views.py [--port 9001] [--only aerial,fern] [--settle 2.5] [--perf 5]

Writes PNGs to ~/Desktop/kokopelli/out/city_renders/<timestamp>/ plus views.json (camera poses,
capture times) and, with --perf N, perf.json (frame stats averaged over N seconds of free running,
from `vbp CITY_manager GetFrameStats`).

Camera 0 is posed with `vset /camera/0/location|rotation|fov` (world metres converted to UE cm:
X = east, Y = south; yaw 0 looks east, 90 south, 180 west, 270 north).
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

OUT = Path.home() / "Desktop" / "kokopelli" / "out" / "city_renders"

# name: (x_m, y_m, z_m, pitch, yaw, fov)
VIEWS = {
    "aerial_overview": (300, 820, 330, -32, 270, 75),
    "aerial_topdown": (300, 300, 780, -89.9, 270, 75),
    "aerial_southwest": (-120, 700, 210, -26, 315, 70),
    "street_fern": (205, 165, 1.7, 2, 250, 80),
    "street_moss": (335, 31, 1.7, 3, 192, 80),
    "street_commons": (465, 202, 1.7, 2, 250, 80),
    "street_birch": (205, 350, 1.7, 2, 245, 80),
    "street_green": (226, 205, 1.7, 3, 45, 80),
    "street_reed": (372, 236, 1.7, 2, 75, 80),
    "street_clover": (205, 530, 1.7, 2, 245, 80),
    "street_sorrel": (330, 385, 1.7, 3, 160, 80),
    "street_heron": (372, 545, 1.7, 2, 295, 80),
    "courtyard_fern": (82, 160, 1.7, 6, 300, 85),
    "canopy_walk": (182, 155, 19.8, -4, 268, 80),
    "canopy_bridge": (187, 112, 19.7, -5, 8, 80),
    "creek_pond": (538, 345, 3.0, -4, 300, 80),
    "creek_aerial": (548, 470, 26, -22, 280, 75),
    "commons_aerial": (470, 225, 38, -28, 245, 75),
    "commons_plaza": (470, 132, 1.7, 2, 205, 85),
    "parkway": (40, 18, 1.7, 2, 10, 80),
    "food_forest": (22, 250, 1.7, 2, 280, 80),
    # added in the polish pass (no "final/" counterpart)
    "canopy_raised": (132, 179.4, 19.8, -6, 0, 80),
    "market_street": (462.5, 101, 1.7, 3, 268, 80),
    "landscape_north": (300, -40, 45, -9, 270, 75),
    "willow_bank": (556, 300, 2.0, 1, 200, 80),
    # realism pilot (city/realism/): the bridge walk's first pose, and the gardens/dome glance
    "bridge_walk": (356.2, 115, 19.67, 2, 0, 90),
    "bridge_glance": (366, 115, 19.67, -4, 45, 90),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--only", default="")
    ap.add_argument("--settle", type=float, default=2.5, help="seconds to let lighting/exposure settle after each move")
    ap.add_argument("--perf", type=float, default=0, help="also measure frame stats for N seconds at the overview")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from unrealcv import Client
    import warnings
    warnings.filterwarnings("ignore")
    c = Client(("127.0.0.1", args.port))
    if not c.connect(timeout=5):
        sys.exit("cannot connect")

    def req(cmd, timeout=60):
        r = c.request(cmd, timeout=timeout)
        return r if isinstance(r, str) else r.decode("utf-8", "replace")

    out = Path(args.out).resolve() if args.out else OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    keys = [k.strip() for k in args.only.split(",") if k.strip()]
    views = {k: v for k, v in VIEWS.items() if not keys or any(q in k for q in keys)}
    req("vset /action/game/resume")
    req("vset /camera/0/size 1280 720")
    log = {}
    for name, (x, y, z, pitch, yaw, fov) in views.items():
        req(f"vset /camera/0/location {x * 100:.1f} {y * 100:.1f} {z * 100:.1f}")
        req(f"vset /camera/0/rotation {pitch} {yaw} 0")
        req(f"vset /camera/0/fov {fov}")
        time.sleep(args.settle)
        t = time.time()
        path = out / f"{name}.png"
        r = req(f"vget /camera/0/lit {path}")
        dt = time.time() - t
        ok = path.exists()
        log[name] = {"pose": [x, y, z, pitch, yaw, fov], "capture_s": round(dt, 3), "ok": ok, "reply": r[:80] if not ok else ""}
        print(f"{name:18s} {dt:5.2f}s {'ok' if ok else r[:80]}")
    if args.perf > 0:
        x, y, z, pitch, yaw, fov = VIEWS["aerial_overview"]
        req(f"vset /camera/0/location {x * 100} {y * 100} {z * 100}")
        req(f"vset /camera/0/rotation {pitch} {yaw} 0")
        perf = {}
        for label, cam in (("overview", VIEWS["aerial_overview"]), ("street", VIEWS["street_fern"]), ("bridge", VIEWS["bridge_walk"])):
            x, y, z, pitch, yaw, fov = cam
            # the player viewport (camera 0's pawn) is what the window renders every frame
            req(f"vset /camera/0/location {x * 100} {y * 100} {z * 100}")
            req(f"vset /camera/0/rotation {pitch} {yaw} 0")
            time.sleep(1.0)
            req("vbp CITY_manager ResetFrameStats")
            time.sleep(args.perf)
            perf[label] = json.loads(json.loads(req("vbp CITY_manager GetFrameStats"))["Stats"])
            print(label, perf[label])
        (out / "perf.json").write_text(json.dumps(perf, indent=1))
    (out / "views.json").write_text(json.dumps(log, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
