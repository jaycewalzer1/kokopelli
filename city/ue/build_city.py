#!/usr/bin/env python
"""Build the solarpunk city from city/world.json in the SimWorld Unreal server (mac_server).

    ~/Desktop/kokopelli/simworld/.venv/bin/python city/ue/build_city.py [--port 9001] [--clear] [--only buildings,trees,...] [--dry]

world.json: origin at the NW corner, x east, y south, metres.
UE:         X = east, Y = south, Z up, centimetres. So UE = world * 100 with no flip
            (UE is left-handed; seen from above with X to the right, +Y points down the screen = south).

Every element becomes one actor named CITY_<type>_<id>, spawned with
`vset /objects/spawn_bp_asset /Script/SimWorld.<Class> <name>` and filled with
`vbp <name> Configure <json>`: the element's world.json object plus converted/derived fields
(everything ending in _cm is UE centimetres). See mac_server/docs/CITY.md.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORLD = HERE.parent / "world.json"
CM = 100.0
WALK_M = 17.5

# Named palette colours (sRGB). world.json "block_palettes" use these names.
COLORS = {
    "sage": (150, 168, 128), "cream": (236, 226, 200), "brass": (190, 156, 82),
    "deep green": (52, 92, 62), "terracotta": (196, 108, 72), "linen": (226, 214, 190),
    "white oak": (212, 186, 148), "pale gold": (226, 200, 120), "sky blue": (130, 180, 214),
    "indigo": (62, 74, 130), "copper": (184, 110, 70), "sand": (220, 200, 160),
    "rust": (168, 82, 50), "steel": (120, 128, 136), "clover green": (98, 150, 80),
    "tomato red": (210, 70, 56), "ochre": (204, 150, 70), "olive": (120, 124, 60),
    "slate": (96, 106, 116), "coral": (236, 122, 100), "white": (240, 238, 232),
    "rose earth": (196, 128, 112), "verdigris": (96, 160, 140), "warm glass": (210, 190, 150),
    "natural timber": (196, 148, 98),
}


def rgb(name):
    return list(COLORS.get(name.lower().strip(), (180, 170, 150)))


def c(v):
    return round(v * CM, 1)


def pt(p):
    return [c(p[0]), c(p[1])]


def rect(r):
    return [c(r[0]), c(r[1]), c(r[2]), c(r[3])]


def inside(p, r, pad=0.0):
    return r[0] - pad <= p[0] <= r[2] + pad and r[1] - pad <= p[1] <= r[3] + pad


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


# ---------------------------------------------------------------------------------------------
# Plan: world.json -> list of (class, name, config) actors


class Plan:
    def __init__(self, w):
        self.w = w
        self.actors = []  # (class, name, cfg)
        self.cells = {c["id"]: c for c in w["cells"]}
        self.edges = {e["id"]: e for e in w["edges"]}
        self.areas = {**self.cells, **self.edges}
        self.lanes = w["lanes"]["segments"]
        self.blds = {b["id"]: b for b in w["buildings"]}
        self.solid = [b for b in w["buildings"] if b.get("floors", 0) > 0 and b.get("type") not in ("courtyard",)]
        land = {l["id"]: l for l in w["landscape"]}
        self.pond = land.get("swim_pond")
        self.creek = land.get("willow_creek")
        self.runnel_lanes = set(land.get("lane_runnels", {}).get("follows", []))
        self.palettes = w["aesthetic"]["block_palettes"]
        self.bridges = w["sky_bridges"]["segments"]
        self.bridge_elev = w["sky_bridges"]["elevation_m"]
        self.walk_nodes = set()
        for p in w["paths"]:
            if p.get("type") == "rooftop_path":
                self.walk_nodes = set(p.get("nodes", []))
        self.obstacles = []  # (x, y, radius m) for tree placement
        self.place_spots = []

    def add(self, cls, name, cfg):
        self.actors.append((cls, name, cfg))

    def lane_at(self, p):
        for l in self.lanes:
            if inside(p, l["rect_m"]):
                return l
        return None

    def in_building(self, p, pad=0.0):
        for b in self.solid:
            if inside(p, b["footprint_m"], pad):
                return b
        return None

    # ---- buildings -------------------------------------------------------------------------
    def street_sides(self, fp):
        x0, y0, x1, y1 = fp
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        probes = {"N": (mx, y0 - 1.0), "S": (mx, y1 + 1.0), "W": (x0 - 1.0, my), "E": (x1 + 1.0, my)}
        out = []
        for side, p in probes.items():
            if self.lane_at(p) or not any(inside(p, a["bounds_m"]) for a in self.cells.values()):
                out.append(side)
        return out

    def plan_buildings(self):
        landings = [b for b in self.w["buildings"] if b.get("type") == "canopy_landing"]
        for b in self.w["buildings"]:
            fp = b["footprint_m"]
            bid = b["id"]
            cell = self.areas.get(b.get("cell"), {})
            pal = b.get("palette") or self.palettes.get(b.get("cell"), ["natural timber"])
            base = dict(b)
            base["rect_cm"] = rect(fp)
            base["loc_cm"] = [c((fp[0] + fp[2]) / 2), c((fp[1] + fp[3]) / 2), 0]
            base["palette_rgb"] = [rgb(n) for n in pal]
            if b.get("type") == "canopy_landing":
                host = self.blds.get(b.get("on")) if b.get("on") else None
                base["base_cm"] = c(host["height_m"]) if host else 0
                base["top_cm"] = c(b.get("height_m", WALK_M))
                self.add("SWCanopyLanding", f"CITY_landing_{bid}", base)
                self.obstacles.append(((fp[0] + fp[2]) / 2, (fp[1] + fp[3]) / 2, 7))
                continue
            if b.get("type") == "courtyard":
                gates = [e["pos_m"][0] for e in b.get("entrances", [])]
                base["kind"] = "courtyard"
                base["gates_x_cm"] = [c(g) for g in gates[:1]]
                self.add("SWCityOpenSpace", f"CITY_space_{bid}", base)
                continue
            if b.get("floors", 0) == 0:
                base["kind"] = bid if bid in ("amphitheater", "chess_garden", "playground", "village_green") else "lawn"
                self.add("SWCityOpenSpace", f"CITY_space_{bid}", base)
                continue
            kind = bid if bid in ("market_hall", "library", "bathhouse", "willow_school", "mobility_hub", "greenhouse") else "bar"
            base["kind"] = kind
            base["height_cm"] = c(b["height_m"])
            base["street_sides"] = self.street_sides(fp)
            base["entrances"] = [dict(e, pos_cm=pt(e["pos_m"])) for e in b.get("entrances", [])]
            if not base.get("materials"):
                base["materials"] = {
                    "library": "rammed earth base, timber upper, solar glass",
                    "bathhouse": "CLT timber, bamboo louvers",
                    "willow_school": "CLT timber + solar glass",
                }.get(bid, "CLT timber")
            if cell.get("id") in self.walk_nodes or "canopy walk" in b.get("roof", ""):
                base["walk_cm"] = c(WALK_M)
            # rooftop feature of the cell: on the east bar of each block, the library in the Commons
            feats = [f for f in cell.get("rooftop", []) if f != "canopy_walk_node"]
            if feats and (bid.endswith("_east") or (bid == "library")):
                base["rooftop_feature"] = feats[0]
            # bridge spurs from the deck to roof edges where sky bridges land
            spurs = []
            for br in self.bridges:
                for end in br["span_m"]:
                    if inside(end, fp, 0.5) and abs(b["height_m"] - self.bridge_elev) < 0.6:
                        spurs.append(pt(end))
            if spurs:
                base["deck_spurs_cm"] = spurs
            keep = [{"rect_cm": rect(l["footprint_m"])} for l in landings if l.get("on") == bid]
            if keep:
                base["keep_clear"] = keep
            self.add("SWCityBuilding", f"CITY_bldg_{bid}", base)

    # ---- bridges -----------------------------------------------------------------------------
    def plan_bridges(self):
        for br in self.bridges:
            (ax, ay), (bx, by) = br["span_m"]
            cfg = dict(br)
            cfg["loc_cm"] = [c((ax + bx) / 2), c((ay + by) / 2), 0]
            cfg["yaw"] = math.degrees(math.atan2(by - ay, bx - ax))
            cfg["length_cm"] = c(math.hypot(bx - ax, by - ay))
            cfg["width_cm"] = c(self.w["sky_bridges"].get("width_m", 4))
            cfg["elevation_cm"] = c(self.bridge_elev)
            self.add("SWSkyBridge", f"CITY_bridge_{br['id']}", cfg)

    # ---- lanes, paths, water -----------------------------------------------------------------
    def plan_lanes(self):
        for i, l in enumerate(self.lanes):
            cfg = dict(l, rect_cm=rect(l["rect_m"]), z_bias=0.15 * i, surface=self.w["lanes"]["surface"])
            if l["id"] in self.runnel_lanes:
                cfg["runnel"] = True
                cfg["runnel_offset_cm"] = 600  # keep the lane centre free for the green loop trail
            self.add("SWCityLane", f"CITY_lane_{l['id']}", cfg)

    def plan_paths(self):
        for p in self.w["paths"]:
            if p.get("type") == "rooftop_path":
                continue  # built as roof decks + sky bridges
            cfg = dict(p, polyline_cm=[pt(q) for q in p["polyline_m"]])
            if p["type"] == "boardwalk":
                cfg["width_cm"] = 260
                cfg["deck_cm"] = 60
            else:
                cfg["width_cm"] = 300
            self.add("SWCityPath", f"CITY_path_{p['id']}", cfg)
        # a meandering trail through the parkway (not in world.json; visual only)
        pk = self.edges["parkway"]["bounds_m"]
        line = [[x, (pk[1] + pk[3]) / 2 + 5 * math.sin(x / 45.0)] for x in range(0, 601, 20)]
        self.add("SWCityPath", "CITY_path_parkway_trail", {"type": "trail", "polyline_cm": [pt(q) for q in line], "width_cm": 280})

    def plan_water(self):
        if self.creek:
            cfg = dict(self.creek, type="creek", centerline_cm=[pt(q) for q in self.creek["centerline_m"]],
                       width_cm=c(self.creek.get("width_m", 8)))
            if self.pond:
                e = self.pond["ellipse_m"]
                cfg["skip_ellipse_cm"] = [c(e["center"][0]), c(e["center"][1]), c(e["rx"] + 4), c(e["ry"] + 4)]
            self.add("SWCityWater", "CITY_water_willow_creek", cfg)
        if self.pond:
            e = self.pond["ellipse_m"]
            self.add("SWCityWater", "CITY_water_swim_pond", dict(self.pond, type="pond", ellipse_cm=[c(e["center"][0]), c(e["center"][1]), c(e["rx"]), c(e["ry"])]))

    # ---- ground ------------------------------------------------------------------------------
    def plan_ground(self):
        W, H = self.w["meta"]["size_m"]
        # meadow skirt round the plan ("the rest of the mile"), under everything else
        slabs = [{"rect_cm": rect([-700, -700, W + 700, H + 700]), "z0": 0, "z1": 1, "mat": "Moss", "tint": [112, 140, 64]},
                 {"rect_cm": rect([0, 0, W, H]), "z0": 0, "z1": 2, "mat": "Moss", "tint": [104, 142, 66]}]
        meadow = [132, 150, 74]
        slabs.append({"rect_cm": rect(self.edges["parkway"]["bounds_m"]), "z0": 0, "z1": 2.5, "mat": "Moss", "tint": [116, 152, 70]})
        slabs.append({"rect_cm": rect(self.edges["creek_corridor"]["bounds_m"]), "z0": 0, "z1": 2.5, "mat": "GreenRoof", "tint": meadow})
        cm_ = self.cells["commons"]["bounds_m"]
        slabs.append({"rect_cm": rect(cm_), "z0": 0, "z1": 3, "mat": "PermeableStone", "tint": [206, 178, 160]})
        # lawn islands in the commons plaza
        for r in ([458, 140, 482, 186], [385, 102, 432, 136], [478, 104, 525, 126]):
            slabs.append({"rect_cm": rect(r), "z0": 0, "z1": 4, "mat": "Moss", "tint": [118, 160, 72]})
        scatter = [
            {"rect_cm": rect(self.edges["parkway"]["bounds_m"]), "kind": "flowers", "count": 2600, "z": 2.5},
            {"rect_cm": rect(self.edges["creek_corridor"]["bounds_m"]), "kind": "flowers", "count": 2400, "z": 2.5},
        ]
        self.add("SWCityGround", "CITY_ground", {"loc_cm": [0, 0, 0], "slabs": slabs, "scatter": scatter})
        # edges as open spaces
        fs = self.edges["farm_south"]["bounds_m"]
        excl = [{"rect_cm": rect(b["footprint_m"])} for b in self.w["buildings"] if inside(((b["footprint_m"][0] + b["footprint_m"][2]) / 2, (b["footprint_m"][1] + b["footprint_m"][3]) / 2), fs)]
        self.add("SWCityOpenSpace", "CITY_space_farm_south", {"kind": "plots", "rect_cm": rect(fs), "exclude": excl,
                                                              "loc_cm": [c((fs[0] + fs[2]) / 2), c((fs[1] + fs[3]) / 2), 0]})
        fw = self.edges["farm_west"]["bounds_m"]
        hub = self.blds.get("mobility_hub", {}).get("footprint_m", [0, 600, 0, 600])
        fw2 = [fw[0], fw[1], fw[2], min(fw[3], hub[1] - 1)]
        self.add("SWCityOpenSpace", "CITY_space_farm_west", {"kind": "food_forest", "rect_cm": rect(fw2),
                                                             "loc_cm": [c((fw2[0] + fw2[2]) / 2), c((fw2[1] + fw2[3]) / 2), 0]})

    # ---- furniture + places --------------------------------------------------------------------
    def facing_into_lane(self, p):
        l = self.lane_at(p)
        if not l:
            return 0.0
        r = l["rect_m"]
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        if (r[2] - r[0]) >= (r[3] - r[1]):  # lane along x: face across (north/south) toward the centre
            return -90.0 if p[1] > cy else 90.0
        return 180.0 if p[0] > cx else 0.0

    def plan_furniture(self):
        counts = {}
        for f in self.w["street_furniture"]:
            t = f["type"]
            counts[t] = counts.get(t, 0) + 1
            name = f"CITY_furn_{t}_{counts[t]:03d}"
            cfg = dict(f)
            if t == "mural_wall":
                b = self.blds[f["on_building"]]
                fp = b["footprint_m"]
                sides = self.street_sides(fp)
                along_x = (fp[2] - fp[0]) >= (fp[3] - fp[1])
                ends = ["W", "E"] if along_x else ["N", "S"]
                side = next((s for s in ends if s in sides), sides[0] if sides else "S")
                mx, my = (fp[0] + fp[2]) / 2, (fp[1] + fp[3]) / 2
                off = 0.0 if side in ends else 0.25 * ((fp[2] - fp[0]) if along_x else (fp[3] - fp[1]))
                pos, yaw, width = {
                    "N": ((mx + off, fp[1] - 0.6), -90.0, fp[2] - fp[0]), "S": ((mx + off, fp[3] + 0.6), 90.0, fp[2] - fp[0]),
                    "W": ((fp[0] - 0.6, my + off), 180.0, fp[3] - fp[1]), "E": ((fp[2] + 0.6, my + off), 0.0, fp[3] - fp[1]),
                }[side]
                cfg.update(loc_cm=[c(pos[0]), c(pos[1]), 0], yaw=yaw, wall_w_cm=c(min(width - 2, 13)), wall_h_cm=c(min(b["height_m"] * 0.45, 8)),
                           palette_rgb=[rgb(n) for n in b.get("palette", ["natural timber"])])
            else:
                p = f["pos_m"]
                cfg.update(loc_cm=[c(p[0]), c(p[1]), 0], yaw=self.facing_into_lane(p))
                self.obstacles.append((p[0], p[1], 2.2))
            self.add("SWStreetFurniture", name, cfg)

    def plan_places(self):
        used = []
        for pl in self.w["places"]:
            p = list(pl["pos_m"])
            cfg = dict(pl)
            cell = pl.get("cell")
            pal = self.palettes.get(cell, ["natural timber", "sage", "coral"])
            cfg["palette_rgb"] = [rgb(n) for n in pal]
            b = self.in_building(p)
            if pl["category"] == "swimming" and self.pond:
                e = self.pond["ellipse_m"]
                p = [e["center"][0] + e["rx"] + 1.0, e["center"][1]]
                yaw, opn = 0.0, False
            elif b is None:
                yaw, opn = 0.0, True
            else:
                x0, y0, x1, y1 = b["footprint_m"]
                d = {"W": p[0] - x0, "E": x1 - p[0], "N": p[1] - y0, "S": y1 - p[1]}
                # prefer faces that open onto a lane
                st = self.street_sides(b["footprint_m"])
                side = min(d, key=lambda k: d[k] + (0 if k in st else 1000))
                p = {"W": [x0, p[1]], "E": [x1, p[1]], "N": [p[0], y0], "S": [p[0], y1]}[side]
                yaw = {"W": 180.0, "E": 0.0, "N": -90.0, "S": 90.0}[side]
                opn = False
            # don't stack two places on one spot
            while any(math.hypot(p[0] - q[0], p[1] - q[1]) < 5 for q in used):
                if abs(yaw) in (0.0, 180.0):
                    p[1] += 8
                else:
                    p[0] += 8
            used.append(p)
            cfg.update(loc_cm=[c(p[0]), c(p[1]), 0], yaw=yaw, open=opn)
            rad = 8 if pl["category"] in ("cafe", "bakery", "pub_music", "market") else 5
            self.obstacles.append((p[0] + 3 * math.cos(math.radians(yaw)), p[1] + 3 * math.sin(math.radians(yaw)), rad))
            self.add("SWCityPlace", f"CITY_place_{pl['id']}", cfg)

    # ---- trees ---------------------------------------------------------------------------------
    def tree_ok(self, p, extra=()):
        if self.in_building(p, 2.0):
            return False
        for l in [b for b in self.w["buildings"] if b.get("type") == "canopy_landing"]:
            if inside(p, l["footprint_m"], 3):
                return False
        for br in self.bridges:
            if seg_dist(p, *br["span_m"]) < 4.5:
                return False
        for (x, y, r) in list(self.obstacles) + list(extra):
            if math.hypot(p[0] - x, p[1] - y) < r:
                return False
        if self.pond:
            e = self.pond["ellipse_m"]
            if ((p[0] - e["center"][0]) / (e["rx"] + 5)) ** 2 + ((p[1] - e["center"][1]) / (e["ry"] + 5)) ** 2 < 1:
                return False
        if self.creek:
            cl = self.creek["centerline_m"]
            if min(seg_dist(p, cl[i], cl[i + 1]) for i in range(len(cl) - 1)) < self.creek["width_m"] / 2 + 2.5:
                return False
        for path in self.w["paths"]:
            if path.get("polyline_m"):
                pl = path["polyline_m"]
                if min(seg_dist(p, pl[i], pl[i + 1]) for i in range(len(pl) - 1)) < 2.6:
                    return False
        return True

    def entrances_near(self, p, r=3.0):
        for b in self.w["buildings"]:
            for e in b.get("entrances", []):
                if math.hypot(p[0] - e["pos_m"][0], p[1] - e["pos_m"][1]) < r:
                    return True
        return False

    def plan_trees(self):
        rnd = random.Random(20261105)
        species_by_lane = {"lane_x1": ["oak"], "lane_x2": ["maple"], "lane_y1": ["flowering cherry"], "lane_y2": ["maple", "flowering cherry", "oak"]}
        street = []
        for l in self.lanes:
            x0, y0, x1, y1 = l["rect_m"]
            along_x = (x1 - x0) >= (y1 - y0)
            width = (y1 - y0) if along_x else (x1 - x0)
            sp = species_by_lane.get(l["id"], ["oak", "maple", "flowering cherry"])
            if width >= 12:
                rows = [3.5, width - 3.5]
            else:
                rows = {"lane_north_edge": [-3.0], "lane_east_edge": [width + 3.5], "lane_south_edge": [width + 2.8]}.get(l["id"], [])
            for r in rows:
                start, end = (x0, x1) if along_x else (y0, y1)
                t = start + 5
                while t < end - 3:
                    p = (t, y0 + r) if along_x else (x0 + r, t)
                    hits = sum(1 for m in self.lanes if inside(p, m["rect_m"], 1.0))
                    if (hits <= 1 or width < 12) and self.tree_ok(p) and not self.entrances_near(p, 4.0):
                        street.append([round(p[0], 2), round(p[1], 2), rnd.choice(sp), round(rnd.uniform(0.85, 1.1), 2)])
                    t += 8
        self.add_trees("CITY_trees_street", street)

        # food forest (dense), parkway grove (open), creek willows + alders
        def scatter(bounds, step, keep, species, scale=(0.8, 1.15), extra=()):
            out = []
            x0, y0, x1, y1 = bounds
            y = y0 + step / 2
            while y < y1:
                x = x0 + step / 2
                while x < x1:
                    p = (x + rnd.uniform(-step * 0.4, step * 0.4), y + rnd.uniform(-step * 0.4, step * 0.4))
                    if rnd.random() < keep and inside(p, bounds) and self.tree_ok(p, extra):
                        out.append([round(p[0], 2), round(p[1], 2), rnd.choice(species), round(rnd.uniform(*scale), 2)])
                    x += step
                y += step
            return out

        fw = self.edges["farm_west"]["bounds_m"]
        hub = self.blds["mobility_hub"]["footprint_m"]
        food = scatter([fw[0] + 1, fw[1] + 1, fw[2] - 2, hub[1] - 2], 7.0, 0.85, ["fig", "persimmon", "pawpaw", "chestnut", "fruit"], extra=[((fw[0] + fw[2]) / 2, y, 2.5) for y in range(34, 600, 3)])
        self.add_trees("CITY_trees_food_forest", food)
        pk = self.edges["parkway"]["bounds_m"]
        self.add_trees("CITY_trees_parkway", scatter([pk[0] + 2, pk[1] + 2, pk[2] - 2, pk[3] - 6], 13.0, 0.55, ["oak", "maple", "flowering cherry", "birch", "jacaranda"], (0.9, 1.25)))
        creek = []
        if self.creek:
            cl = self.creek["centerline_m"]
            for i in range(len(cl) - 1):
                a, b = cl[i], cl[i + 1]
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                n = (-(b[1] - a[1]) / L, (b[0] - a[0]) / L)
                t = 0
                while t < L:
                    for side in (-1, 1):
                        if rnd.random() < 0.55:
                            off = side * rnd.uniform(7, 11)
                            p = (a[0] + (b[0] - a[0]) * t / L + n[0] * off, a[1] + (b[1] - a[1]) * t / L + n[1] * off)
                            if inside(p, self.edges["creek_corridor"]["bounds_m"]) and self.tree_ok(p):
                                creek.append([round(p[0], 2), round(p[1], 2), "willow", round(rnd.uniform(0.85, 1.2), 2)])
                    t += 11
        cc = self.edges["creek_corridor"]["bounds_m"]
        creek += scatter([cc[0] + 3, cc[1] + 2, cc[2] - 1, cc[3] - 2], 16.0, 0.35, ["birch", "oak", "shade"], (0.8, 1.1),
                         extra=[(q[0], q[1], 7) for q in creek])
        self.add_trees("CITY_trees_creek", creek)

        # courtyards: fruit trees round the edges, clear of paths
        for b in self.w["buildings"]:
            if b.get("type") != "courtyard":
                continue
            x0, y0, x1, y1 = b["footprint_m"]
            gx = b["entrances"][0]["pos_m"][0] if b.get("entrances") else (x0 + x1) / 2
            cy = (y0 + y1) / 2
            out = []
            for t in [x0 + 6 + 8 * i for i in range(int((x1 - x0 - 10) / 8) + 1)]:
                for y in (y0 + 6, y1 - 6, cy - 9, cy + 12, (y0 + cy) / 2, (cy + y1) / 2 + 4):
                    p = (t + rnd.uniform(-1.5, 1.5), y + rnd.uniform(-1, 1))
                    if abs(p[0] - gx) < 4 or not (x0 + 3 < p[0] < x1 - 3):
                        continue
                    if y not in (y0 + 6, y1 - 6) and rnd.random() < 0.55:
                        continue
                    out.append([round(p[0], 2), round(p[1], 2), rnd.choice(["fruit", "fruit", "persimmon", "fig", "flowering cherry"]), round(rnd.uniform(0.85, 1.15), 2)])
            self.add_trees(f"CITY_trees_{b['id']}", out)

        # Village Green: big shade trees round the lawn; the Commons: scattered trees between buildings
        vg = self.blds["village_green"]["footprint_m"]
        pg = self.blds["playground"]["footprint_m"]
        green = []
        x = vg[0] + 4
        while x < vg[2] - 3:
            for y in (vg[1] + 5, vg[3] - 5):
                p = (x + rnd.uniform(-2, 2), y + rnd.uniform(-1.5, 1.5))
                if not inside(p, pg, 4):
                    green.append([round(p[0], 2), round(p[1], 2), rnd.choice(["shade", "oak", "jacaranda"]), round(rnd.uniform(0.85, 1.1), 2)])
            x += 17
        y = vg[1] + 18
        while y < vg[3] - 10:
            for x in (vg[0] + 5, vg[2] - 5):
                p = (x + rnd.uniform(-1.5, 1.5), y + rnd.uniform(-2, 2))
                if not inside(p, pg, 4):
                    green.append([round(p[0], 2), round(p[1], 2), rnd.choice(["shade", "oak", "maple"]), round(rnd.uniform(0.85, 1.1), 2)])
            y += 17
        self.add_trees("CITY_trees_green", green)
        cmb = self.cells["commons"]["bounds_m"]
        solid_commons = [b["footprint_m"] for b in self.w["buildings"] if b.get("cell") == "commons"]
        commons = []
        for _ in range(500):
            p = (rnd.uniform(cmb[0] + 3, cmb[2] - 3), rnd.uniform(cmb[1] + 3, cmb[3] - 3))
            if any(inside(p, r, 3.5) for r in solid_commons):
                continue
            if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 8 for q in commons):
                continue
            if self.tree_ok(p):
                commons.append([round(p[0], 2), round(p[1], 2), rnd.choice(["jacaranda", "flowering cherry", "oak", "maple"]), round(rnd.uniform(0.85, 1.1), 2)])
        # low planting islands between the commons buildings
        for _ in range(900):
            p = (rnd.uniform(cmb[0] + 2, cmb[2] - 2), rnd.uniform(cmb[1] + 2, cmb[3] - 2))
            if any(inside(p, r, 1.5) for r in solid_commons) or not self.tree_ok(p):
                continue
            if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 3 for q in commons):
                continue
            if math.sin(p[0] / 9.0) + math.cos(p[1] / 7.0) > 0.4:
                commons.append([round(p[0], 2), round(p[1], 2), "shrub", round(rnd.uniform(0.7, 1.4), 2)])
        self.add_trees("CITY_trees_commons", commons)

        # distant woods round the plan so aerials don't end at the edge of the map
        surround = []
        for _ in range(1400):
            p = (rnd.uniform(-450, 1050), rnd.uniform(-450, 1050))
            if -15 < p[0] < 615 and -15 < p[1] < 615:
                continue
            # clumped: keep with a probability that varies smoothly in space
            if (math.sin(p[0] / 37.0) + math.cos(p[1] / 29.0) + math.sin((p[0] + p[1]) / 53.0)) < 0.2:
                continue
            surround.append([round(p[0], 1), round(p[1], 1), rnd.choice(["oak", "oak", "maple", "chestnut", "birch", "willow" if p[0] > 600 else "shade"]), round(rnd.uniform(0.9, 1.4), 2)])
        self.add_trees("CITY_trees_surround", surround)

    def add_trees(self, name, trees):
        if trees:
            self.add("SWCityTrees", name, {"loc_cm": [0, 0, 0], "trees": [[c(t[0]), c(t[1]), t[2], t[3]] for t in trees]})

    def build(self):
        self.plan_ground()
        self.plan_lanes()
        self.plan_paths()
        self.plan_water()
        self.plan_buildings()
        self.plan_bridges()
        self.plan_furniture()
        self.plan_places()
        self.plan_trees()
        return self.actors


# ---------------------------------------------------------------------------------------------
# Server I/O


class Sim:
    def __init__(self, port):
        from unrealcv import Client
        import warnings
        warnings.filterwarnings("ignore")
        self.c = Client(("127.0.0.1", port))
        if not self.c.connect(timeout=5):
            sys.exit(f"cannot connect to SimCV on port {port}")

    def req(self, cmd, timeout=120):
        r = self.c.request(cmd, timeout=timeout)
        return r if isinstance(r, str) else r.decode("utf-8", "replace")

    def batch(self, cmds):
        out = self.c.request_batch(cmds)
        return [r if isinstance(r, str) else r.decode("utf-8", "replace") for r in out]

    def city_names(self):
        return [n for n in self.req("vget /objects").split() if n.lower().startswith("city_")]

    def clear(self):
        names = self.city_names()
        for i in range(0, len(names), 100):
            self.batch([f"vset /object/{n}/destroy" for n in names[i:i + 100]])
        self.req("vset /action/clean_garbage")
        return len(names)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--world", default=str(WORLD))
    ap.add_argument("--clear", action="store_true", help="only remove every CITY_* actor")
    ap.add_argument("--only", default="", help="comma list of name substrings to (re)build, e.g. bldg_fern,trees")
    ap.add_argument("--dry", action="store_true", help="print the plan, don't connect")
    args = ap.parse_args()

    w = json.loads(Path(args.world).read_text())
    actors = Plan(w).build()
    if args.only:
        keys = [k.strip().lower() for k in args.only.split(",") if k.strip()]
        actors = [a for a in actors if any(k in a[1].lower() for k in keys)]
    if args.dry:
        from collections import Counter
        print(Counter(a[0] for a in actors))
        trees = sum(len(a[2].get("trees", [])) for a in actors)
        print(f"{len(actors)} actors, {trees} trees, json {sum(len(json.dumps(a[2])) for a in actors) / 1e3:.0f} kB")
        return

    sim = Sim(args.port)
    t0 = time.time()
    if args.clear:
        print(f"cleared {sim.clear()} CITY_* actors in {time.time() - t0:.1f}s")
        return
    existing = {n.lower() for n in sim.city_names()}
    stale = [a[1] for a in actors if a[1].lower() in existing]
    if stale:
        for i in range(0, len(stale), 100):
            sim.batch([f"vset /object/{n}/destroy" for n in stale[i:i + 100]])
        sim.req("vset /action/clean_garbage")
    if "city_manager" not in existing:
        sim.req("vset /objects/spawn_bp_asset /Script/SimWorld.SWCityManager CITY_manager")
    errors = 0
    t1 = time.time()
    # spawn in batches, then configure one by one (each Configure builds meshes on the game thread)
    for i in range(0, len(actors), 50):
        chunk = actors[i:i + 50]
        for (cls, name, _), r in zip(chunk, sim.batch([f"vset /objects/spawn_bp_asset /Script/SimWorld.{cls} {name}" for cls, name, _ in chunk])):
            if r.lower().startswith("error"):
                errors += 1
                print("spawn", name, r)
    t2 = time.time()
    slow = []
    for cls, name, cfg in actors:
        s = time.time()
        r = sim.req(f"vbp {name} Configure {json.dumps(cfg, separators=(',', ':'))}")
        if r.lower().startswith("error"):
            errors += 1
            print("configure", name, r[:200])
        slow.append((time.time() - s, name))
    t3 = time.time()
    infos = sim.batch([f"vbp {name} GetBuildInfo" for _, name, _ in actors])
    tris = inst = 0
    for (_, name, _), r in zip(actors, infos):
        try:
            info = json.loads(json.loads(r)["Info"])
            tris += info["tris"]
            inst += info["instances"]
            if not info["ok"]:
                errors += 1
                print("build", name, info.get("error"))
        except Exception:
            print("info?", name, r[:120])
    slow.sort(reverse=True)
    print(f"{len(actors)} actors: spawn {t2 - t1:.1f}s, configure {t3 - t2:.1f}s, total {time.time() - t0:.1f}s; "
          f"~{tris / 1e6:.2f} M tris, {inst} instances, {errors} errors")
    print("slowest:", ", ".join(f"{n} {t:.2f}s" for t, n in slow[:5]))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
