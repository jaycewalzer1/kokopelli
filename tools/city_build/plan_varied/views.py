#!/usr/bin/env python
"""Planner views of the varied city (per-cell obliques, street and canopy-walk views). Same camera protocol as
tools/city_build/render_views.py; only run it inside the editor lock (run_build.py does).

    simworld/.venv/bin/python tools/city_build/plan_varied/views.py --port 9003 [--only fern,moss] --out out/city_kinds/planner/x
"""
import argparse
import sys
import time
from pathlib import Path

# name: (x_m, y_m, z_m, pitch, yaw, fov); yaw 0 looks east, 90 south, 180 west, 270 north
VIEWS = {
    "cell_fern": (230, 230, 95, -32, 225, 70),
    "cell_moss": (300, 235, 95, -33, 270, 70),
    "cell_birch": (240, 300, 70, -24, 180, 75),
    "cell_reed": (370, 395, 90, -30, 300, 72),
    "cell_clover": (230, 590, 90, -30, 220, 70),
    "cell_sorrel": (290, 610, 90, -30, 270, 70),
    "cell_heron": (560, 600, 95, -30, 235, 70),
    "aerial_east": (760, 300, 220, -24, 180, 70),
    "aerial_north": (300, -170, 230, -30, 90, 72),
    "eye_fern_lane": (186, 37, 1.7, 3, 180, 80),
    "eye_sorrel_skyway": (254, 458, 1.7, 12, 315, 85),
    "eye_heron_lane": (455, 553, 1.7, 3, 270, 80),
    "eye_birch_mews": (87, 250, 1.7, 2, 90, 85),
    "walk_moss": (205, 186, 19.7, -4, 0, 85),
    "walk_sorrel": (240, 440, 19.7, -3, 0, 85),
    "walk_clover": (186, 395, 19.7, -6, 90, 85),
    "fallingwater": (577.5, 476, 1.8, 9, 270, 80),
    "fallingwater_air": (612, 500, 32, -26, 232, 70),
    "eye_moss_mews": (222, 86, 1.7, 3, 0, 85),
    "eye_reed_garden": (440, 296, 1.7, 4, 200, 85),
    "eye_clover_mews": (70, 436, 1.7, 3, 90, 85),
    "eye_fern_mews": (145, 160, 1.7, 3, 270, 85),
    "eye_sorrel_lane": (324, 512, 1.7, 4, 270, 85),
    "eye_heron_creekwalk": (504, 520, 1.7, 3, 270, 85),
    "park_aerial": (385, 405, 70, -30, 225, 72),
    "park_aerial_n": (290, 215, 55, -32, 90, 75),
    "park_eye_lawn": (262, 334, 1.7, 3, 350, 85),
    "park_castle": (272, 300, 1.7, 6, 215, 80),
    "mcm_birch_eichler_street": (166, 280, 1.7, 3, 180, 80),
    "mcm_clover_eichler_lane": (47, 515, 1.7, 3, 270, 80),
    "mcm_fern_hanna": (81, 176, 1.7, 3, 270, 80),
    "mcm_reed_sea_ranch": (503, 353, 1.7, 5, 216, 80),
    "jp_fern_sukiya": (139, 84, 1.7, 3, 0, 80),
    "jp_heron_sukiya": (372, 474, 1.7, 4, 15, 80),
    "jp_fern_ando": (62, 30, 1.7, 3, 110, 80),
    "castle_lane_w": (206, 277, 1.7, 9, 0, 80),
    "castle_lane_n": (240, 256.5, 1.7, 14, 90, 85),
    "castle_walk_tower": (186, 229, 19.7, -12, 44, 60),
    "castle_low_aerial": (208, 304, 30, -32, 322, 70),
    "mcm_hanna": (81, 177, 1.7, 4, 300, 75),
    "mcm_x100_moss": (326, 201, 1.7, 4, 270, 75),
    "mcm_hedgerow_clover": (128, 450, 1.7, 4, 25, 75),
    "mcm_eichler_street_eye": (89, 281, 1.6, 2, 0, 80),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9003)
    ap.add_argument("--only", default="")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.port == 9001:
        sys.exit("never 9001")
    from unrealcv import Client
    import warnings
    warnings.filterwarnings("ignore")
    c = Client(("127.0.0.1", args.port))
    if not c.connect(timeout=5):
        sys.exit("cannot connect")

    def req(cmd, timeout=60):
        r = c.request(cmd, timeout=timeout)
        return r if isinstance(r, str) else r.decode("utf-8", "replace")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    keys = [k.strip() for k in args.only.split(",") if k.strip()]
    req("vset /action/game/resume")
    req("vset /camera/0/size 1280 720")
    for name, (x, y, z, pitch, yaw, fov) in VIEWS.items():
        if keys and not any(k in name for k in keys):
            continue
        req(f"vset /camera/0/location {x * 100:.1f} {y * 100:.1f} {z * 100:.1f}")
        req(f"vset /camera/0/rotation {pitch} {yaw} 0")
        req(f"vset /camera/0/fov {fov}")
        time.sleep(args.settle)
        path = out / f"{name}.png"
        # warm-up capture: the first frame after a jump uses the previous view's occlusion results (whole buildings
        # vanish while their shadows stay), so render once, let it settle, then capture for real
        req(f"vget /camera/0/lit {out / '_warmup.png'}")
        time.sleep(1.0)
        r = req(f"vget /camera/0/lit {path}")
        print(f"{name:20s} {'ok' if path.exists() else r[:80]}", flush=True)


if __name__ == "__main__":
    main()
