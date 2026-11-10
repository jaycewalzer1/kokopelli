#!/usr/bin/env python
"""ASCII height map (world frame, 2 m cells, height in m // 2 as a hex digit) of a planned building's kit.

    simworld/.venv/bin/python -m tools.city_build.plan_varied.kitmap fern_habitat [--world data/city/world.json]
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from tools.city_build.plan_varied.check import op_bounds, plot_wd  # noqa: E402


def heights(b, world=None):
    from tools.city_build.kinds import Plot, all_kinds
    from build_city import rgb
    wd = plot_wd(b["footprint_m"], b["front"])
    kit = all_kinds()[b["arch"]][1](Plot(w=wd[0], d=wd[1], h_max=b["height_m"], floors=b["floors"], palette=[rgb(n) for n in b["palette"]],
                                          seed=b["seed"], use=b["use"], cell=b["cell"]))
    x0, y0, x1, y1 = b["footprint_m"]
    th = math.radians({"N": 0, "E": 90, "S": 180, "W": 270}[b["front"]])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    nx, ny = int(math.ceil((x1 - x0) / 2)), int(math.ceil((y1 - y0) / 2))
    H = [[0.0] * nx for _ in range(ny)]
    for op in kit.ops:
        bb = op_bounds(op)
        if not bb or op[0] in ("pole",):
            continue
        # local cm box corners -> world
        pts = []
        for lx in (bb[0], bb[3]):
            for ly in (bb[1], bb[4]):
                pts.append((cx + (lx * math.cos(th) - ly * math.sin(th)) / 100, cy + (lx * math.sin(th) + ly * math.cos(th)) / 100))
        wx0, wx1 = min(p[0] for p in pts), max(p[0] for p in pts)
        wy0, wy1 = min(p[1] for p in pts), max(p[1] for p in pts)
        if (wx1 - wx0) * (wy1 - wy0) < 0.5:
            continue
        for j in range(ny):
            for i in range(nx):
                px, py = x0 + 2 * i + 1, y0 + 2 * j + 1
                if wx0 <= px <= wx1 and wy0 <= py <= wy1:
                    H[j][i] = max(H[j][i], bb[5] / 100)
    return H


def main():
    world = json.loads(Path(sys.argv[sys.argv.index("--world") + 1] if "--world" in sys.argv else ROOT / "data/city/world.json").read_text())
    for bid in [a for a in sys.argv[1:] if not a.startswith("--") and not a.endswith(".json")]:
        b = next(x for x in world["buildings"] if x["id"] == bid)
        H = heights(b)
        print(f"{bid} {b['arch']} {b['footprint_m']} front {b['front']}: rows = y from {b['footprint_m'][1]} (2 m), digit = height // 2 m (h = 17.5 -> 8)")
        for j, row in enumerate(H):
            print(f"{b['footprint_m'][1] + 2 * j:5.0f} " + "".join("%x" % min(15, int(h // 2)) if h > 0.3 else "." for h in row))


if __name__ == "__main__":
    main()
