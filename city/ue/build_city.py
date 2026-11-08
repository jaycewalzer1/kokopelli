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


# Per-block facade/roof styles (fields read by SWCityBuilding as st_*). Each block gets its own timber tone,
# wall finish, bay rhythm, balcony type, green walls and roof profile so the eight blocks don't read as clones.
STYLES = {
    # sage/cream/brass: cream lime render, timber galleries (Kampung Admiralty), pitched sedum+PV roofs
    "fern": dict(st_timber=[204, 160, 108], st_core="render", st_render=[238, 226, 200], st_bay_cm=300, st_win=0.55, st_tall=True,
                 st_balcony="gallery", st_green=0.0, st_roof="gable", st_fins="timber"),
    # deep green/terracotta/linen: dark timber Bosco Verticale, deep staggered balconies, rooftop pavilions
    "moss": dict(st_timber=[150, 106, 70], st_timber_dark=[104, 70, 46], st_core="timber", st_bay_cm=360, st_win=0.6,
                 st_balcony="bosco", st_green=0.12, st_roof="pavilions", st_earth=[196, 112, 76]),
    # white oak/pale gold/sky blue: pale timber, narrow bays, tall windows, sawtooth PV roofs
    "birch": dict(st_timber=[226, 196, 152], st_timber_dark=[178, 140, 96], st_core="timber", st_bay_cm=260, st_win=0.7, st_tall=True,
                  st_balcony="default", st_roof="sawtooth", st_fins="none"),
    # indigo/copper/sand: WOHA-ish, sand render, copper fins, vertical gardens
    "reed": dict(st_timber=[128, 92, 66], st_timber_dark=[86, 60, 44], st_core="render", st_render=[216, 196, 160], st_bay_cm=420,
                 st_win=0.68, st_balcony="bosco", st_green=0.3, st_roof="pavilions", st_fins="copper"),
    # rust/steel/clover: red rammed earth, deep small windows, sawtooth roofs
    "clover": dict(st_timber=[182, 132, 90], st_core="earth", st_earth=[184, 104, 72], st_bay_cm=340, st_win=0.42,
                   st_balcony="sparse", st_green=0.1, st_roof="sawtooth"),
    # tomato/ochre/olive: ochre render, galleries, pitched roofs, shutters
    "sorrel": dict(st_timber=[196, 146, 96], st_core="render", st_render=[226, 180, 112], st_bay_cm=320, st_win=0.5,
                   st_balcony="gallery", st_roof="gable", st_shutters=True),
    # slate/coral/white: white render, silvered timber, vertical gardens, pavilions
    "heron": dict(st_timber=[178, 166, 150], st_timber_dark=[120, 110, 100], st_core="render", st_render=[244, 240, 230], st_bay_cm=300,
                  st_win=0.6, st_tall=True, st_balcony="default", st_green=0.2, st_roof="pavilions", st_fins="none"),
}


def top_cut(floors, depth):
    """Court-side / street-side setback of the top floor (mirrors SWCityBuilding's per-floor cuts), metres."""
    court, street = 0.0, 0.0
    if floors >= 6:
        court, street = 6.0, 3.0
    elif floors == 5:
        court = 3.5
    elif floors >= 3:
        court = 3.0
    if depth < 12:
        court = min(court, depth * 0.2)
    return court, street


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

    # ---- canopy walk geometry (mirrors SWCityBuilding) -----------------------------------------
    def bar_frame(self, b):
        """(along_x, cross_lo, cross_hi, court_minus) for a bar: cross axis is y for bars along x."""
        x0, y0, x1, y1 = b["footprint_m"]
        along_x = (x1 - x0) >= (y1 - y0)
        st = self.street_sides(b["footprint_m"])
        sm, sp = ("N", "S") if along_x else ("W", "E")
        street_m, street_p = sm in st, sp in st
        court_minus = street_p and not street_m  # C++: CourtSide 0 (v-) only when v+ is the street
        lo, hi = (y0, y1) if along_x else (x0, x1)
        return along_x, lo, hi, court_minus

    def deck_line(self, b):
        """Cross-axis world coordinate of the canopy-walk deck on this bar's roof, or None."""
        if b.get("cell") not in self.walk_nodes or b.get("floors", 0) == 0 or b.get("type"):
            return None
        h = b["height_m"]
        along_x, lo, hi, court_minus = self.bar_frame(b)
        court, street = top_cut(b["floors"], hi - lo)
        rlo = lo + (court if court_minus else street)
        rhi = hi - (street if court_minus else court)
        if abs(h - WALK_M) < 0.6:
            return (rlo + rhi) / 2
        if WALK_M - 10 < h < WALK_M - 0.6:
            return rlo + 2.4 if court_minus else rhi - 2.4  # raised deck: keep to the court side, clear of landing towers
        return None

    def is_loggia(self, b):
        return b.get("cell") in self.walk_nodes and b.get("floors", 0) >= 6 and abs((b["floors"] - 1) * b["height_m"] / b["floors"] - WALK_M) < 0.6

    def plan_walk_joins(self):
        """Spur points (deck_spurs), terrace gaps and deck lines that make the canopy walk continuous inside each block."""
        self.spurs, self.tgaps = {}, {}
        bars = [b for b in self.w["buildings"] if b.get("floors", 0) > 0 and not b.get("type") and b.get("cell") in self.walk_nodes]
        for wb in bars:
            along_x, lo, hi, _ = self.bar_frame(wb)
            dl = self.deck_line(wb)
            if along_x or dl is None:
                continue
            x0, y0, x1, y1 = wb["footprint_m"]
            for nb in bars:
                if nb is wb or nb.get("cell") != wb.get("cell"):
                    continue
                n_along_x = self.bar_frame(nb)[0]
                nx0, ny0, nx1, ny1 = nb["footprint_m"]
                if not n_along_x or not (nx0 - 0.5 <= dl <= nx1 + 0.5):
                    continue
                face = ny1 if abs(ny1 - y0) < 0.6 else (ny0 if abs(ny0 - y1) < 0.6 else None)
                if face is None:
                    continue
                if self.deck_line(nb) is not None:
                    self.spurs.setdefault(nb["id"], []).append(pt((dl, face)))
                elif self.is_loggia(nb):
                    self.tgaps.setdefault(nb["id"], []).append(pt((dl, face)))
        for l in self.w["buildings"]:
            if l.get("type") != "canopy_landing" or not l.get("on"):
                continue
            host = self.blds[l["on"]]
            dl = self.deck_line(host)
            if dl is None:
                continue
            along_x = self.bar_frame(host)[0]
            lx0, ly0, lx1, ly1 = l["footprint_m"]
            if along_x:
                self.spurs.setdefault(host["id"], []).append(pt(((lx0 + lx1) / 2, ly0 if dl < ly0 else ly1)))
            else:
                self.spurs.setdefault(host["id"], []).append(pt((lx0 if dl < lx0 else lx1, (ly0 + ly1) / 2)))
        for br in self.bridges:
            for end in br["span_m"]:
                for b in bars:
                    if inside(end, b["footprint_m"], 0.5) and self.is_loggia(b):
                        self.tgaps.setdefault(b["id"], []).append(pt(end))

    def plan_buildings(self):
        landings = [b for b in self.w["buildings"] if b.get("type") == "canopy_landing"]
        self.plan_walk_joins()
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
            if b.get("arch"):
                self.add_kit(b, base)
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
            spurs += self.spurs.get(bid, [])
            if spurs:
                base["deck_spurs_cm"] = spurs
            if self.tgaps.get(bid):
                base["terrace_gaps_cm"] = self.tgaps[bid]
            dl = self.deck_line(b)
            if dl is not None:
                along_x = self.bar_frame(b)[0]
                base["deck_line_cm"] = pt(((fp[0] + fp[2]) / 2, dl) if along_x else (dl, (fp[1] + fp[3]) / 2))
            if kind == "bar":
                st = dict(STYLES.get(b.get("cell"), {}))
                # within a block: the 6-storey solar-glass bar keeps glass floors; the south bar keeps its earth base
                if "solar glass" in base["materials"] and st.get("st_core") == "earth":
                    st["st_core"] = "timber"
                if bid.endswith("_south"):
                    st.pop("st_roof", None)
                base.update(st)
            keep = [{"rect_cm": rect(l["footprint_m"])} for l in landings if l.get("on") == bid]
            if keep:
                base["keep_clear"] = keep
            self.add("SWCityBuilding", f"CITY_bldg_{bid}", base)

    def add_kit(self, b, base):
        """A varied-city building: "arch" names a kind in city/ue/kinds/, drawn in Python and sent to SWCityKit."""
        if str(HERE.parents[1]) not in sys.path:
            sys.path.insert(0, str(HERE.parents[1]))
        from city.ue.kinds import Plot, build as build_kind
        from city.ue.kinds.kit import plot_size
        front = b.get("front", "N")
        w, d = plot_size(b["footprint_m"], front)
        plot = Plot(w=w, d=d, h_max=b.get("height_m", 24.0), floors=b.get("floors", 0), palette=base["palette_rgb"],
                    seed=b.get("seed", sum(map(ord, b["id"]))), use=b.get("use", b.get("upper_floors", "")), cell=b.get("cell", ""))
        kit = build_kind(b["arch"], plot)
        self.add("SWCityKit", f"CITY_bldg_{b['id']}", kit.config(b["footprint_m"], front))

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
        slabs = [{"rect_cm": rect([-2000, -2000, 2000, 2000]), "z0": 0, "z1": 0.6, "mat": "Plain", "tint": [64, 86, 32], "scale": 40},
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
            {"rect_cm": rect(self.edges["parkway"]["bounds_m"]), "kind": "flowers", "count": 4500, "z": 2.5},
            {"rect_cm": rect(self.edges["creek_corridor"]["bounds_m"]), "kind": "flowers", "count": 4200, "z": 2.5},
        ]
        # macro variation: soft blotches of different meadow tints/scales over the big green areas
        rnd = random.Random(77)
        for area in (self.edges["parkway"]["bounds_m"], self.edges["creek_corridor"]["bounds_m"]):
            ax0, ay0, ax1, ay1 = area
            n = int((ax1 - ax0) * (ay1 - ay0) / 900)
            for _ in range(n):
                cx, cy = rnd.uniform(ax0, ax1), rnd.uniform(ay0, ay1)
                r = rnd.uniform(6, 16)
                poly = []
                for k in range(10):
                    t = 2 * math.pi * k / 10
                    rr = r * rnd.uniform(0.6, 1.0)
                    poly.append([min(max(cx + math.cos(t) * rr * 1.4, ax0), ax1), min(max(cy + math.sin(t) * rr, ay0), ay1)])
                tint = rnd.choice([[150, 156, 76], [96, 136, 62], [124, 150, 70], [168, 160, 84], [88, 122, 60]])
                slabs.append({"poly_cm": [pt(q) for q in poly], "z0": 0, "z1": round(rnd.uniform(2.6, 3.0), 2), "mat": rnd.choice(["Moss", "GreenRoof"]),
                              "tint": tint, "scale": rnd.choice([10, 16, 24, 40])})
        # the surrounding landscape is its own actor, kept out of Lumen's scene (it doubled the GI cost)
        land_slabs = [slabs[0]]
        land = self.plan_landscape(land_slabs)
        # vibe pass (city/VIBE.md 7): Isono's hot-air balloons and birds, placed where the views look.
        # [x_m, y_m, z_m, colour]: west of the fern lane, NW of the plaza, NE over the creek, north of the canopy
        # walk, and two over the city for the aerials.
        balloons = [[-150, 40, 90, 0], [150, -20, 80, 1], [740, 0, 95, 2], [170, -260, 110, 0], [200, 320, 150, 1], [430, 470, 120, 2]]
        # [x_m, y_m, z_m, count, spread_m]
        birds = [[300, 100, 40, 14, 25], [420, 60, 30, 9, 15], [610, 250, 26, 11, 20], [110, 150, 28, 8, 14], [260, 420, 55, 16, 30]]
        sky = {"balloons": [[x * 100, y * 100, z * 100, c] for x, y, z, c in balloons],
               "birds": [[x * 100, y * 100, z * 100, n, s * 100] for x, y, z, n, s in birds]}
        self.add("SWCityGround", "CITY_ground", {"loc_cm": [0, 0, 0], "slabs": slabs[1:], "scatter": scatter, **sky})
        self.add("SWCityGround", "CITY_landscape", {"loc_cm": [0, 0, 0], "slabs": land_slabs, "gi": False, **land})
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

    # ---- the surrounding landscape --------------------------------------------------------------
    def plan_landscape(self, slabs):
        """Patchwork fields with tracks, hedgerows with copses, poplar windbreaks, orchards and a ring of backdrop hills
        over the 4 km floor (world -2000..2000 m), all outside the city plan."""
        rnd = random.Random(4242)
        W, H = self.w["meta"]["size_m"]
        hedges, trees = [], []
        crops = [  # (weight, mat, tint, scale)
            (30, "Moss", [108, 140, 62], 30), (12, "GreenRoof", [138, 152, 72], 60), (10, "GreenRoof", [196, 170, 92], 90),
            (8, "GreenRoof", [214, 186, 104], 120), (8, "Path", [128, 98, 70], 30), (12, "GreenRoof", [96, 140, 58], 40),
            (4, "GreenRoof", [150, 120, 170], 30), (6, "Moss", [84, 118, 54], 50), (10, "orchard", None, 0)]
        total = sum(cr[0] for cr in crops)

        def pick():
            r = rnd.uniform(0, total)
            for cr in crops:
                r -= cr[0]
                if r <= 0:
                    return cr
            return crops[0]

        def hedge(pts):
            # long cushions far out (instances are the cost), shadows only within ~1 km of the city
            mx, my = (pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2
            d = math.hypot(mx - W / 2, my - H / 2)
            return {"pts": [pt(q) for q in pts], "h": round(rnd.uniform(250, 420)), "w": 380, "step": 1.6 if d < 700 else 3.0,
                    "shadow": d < 500, "cull_cm": 0 if d < 900 else 170000, "tint": rnd.choice([[60, 98, 46], [72, 110, 50], [54, 90, 44]])}

        def plain_tint(t):
            # flat colour roughly matching the textured materials' average look at a distance
            return [int(t[0] * 0.62), int(t[1] * 0.66), int(t[2] * 0.5)]

        def keep_p(x, y):  # hedge density: full near the city, thinner far out (instances are the GPU cost)
            return 0.38 if math.hypot(x - W / 2, y - H / 2) < 900 else 0.24

        def copse_p(x, y):
            return 0.018 if math.hypot(x - W / 2, y - H / 2) < 900 else 0.004

        def near_city(x, y, pad):
            return -pad < x < W + pad and -pad < y < H + pad

        xs = [-1990.0]
        while xs[-1] < 1990:
            xs.append(xs[-1] + rnd.uniform(70, 170))
        ys = [-1990.0]
        while ys[-1] < 1990:
            ys.append(ys[-1] + rnd.uniform(60, 150))
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                x0, x1, y0, y1 = xs[i] + 3, xs[i + 1] - 3, ys[j] + 3, ys[j + 1] - 3
                # keep the city, its 25 m meadow apron and the parkway/farm edges clear
                if x1 > -25 and x0 < W + 25 and y1 > -25 and y0 < H + 25:
                    continue
                crop = pick()
                if crop[1] == "orchard":
                    slabs.append({"rect_cm": rect([x0, y0, x1, y1]), "z0": 0, "z1": 0.9, "mat": "Plain", "tint": plain_tint([118, 146, 66]), "scale": 30})
                    d = math.hypot((x0 + x1) / 2 - W / 2, (y0 + y1) / 2 - H / 2)
                    if d < 1000:
                        sp = rnd.choice(["apple", "persimmon", "fruit"]) if d < 600 else "fruit"
                        step = 14.0 if d < 600 else 20.0
                        yy = y0 + 4
                        while yy < y1 - 3:
                            xx = x0 + 4
                            while xx < x1 - 3:
                                trees.append([round(xx, 1), round(yy, 1), sp, round(rnd.uniform(0.9, 1.15), 2)])
                                xx += step
                            yy += step
                    continue
                far = True  # flat colour everywhere: the textured materials tiled visibly at field scale
                # far fields get the flat-colour material: their texture is sub-pixel from any view but cost ~2 ms of shading
                slabs.append({"rect_cm": rect([x0, y0, x1, y1]), "z0": 0, "z1": round(rnd.uniform(0.8, 1.2), 2), "mat": "Plain" if far else crop[1],
                              "tint": plain_tint(crop[2]) if far else crop[2], "scale": crop[3]})
        # hedgerows on some field edges, with copse trees standing in them; poplar windbreaks on a few
        for i in range(len(xs)):
            for j in range(len(ys) - 1):
                x, y0, y1 = xs[i], ys[j], ys[j + 1]
                if near_city(x, (y0 + y1) / 2, 30) or rnd.random() > keep_p(x, (y0 + y1) / 2):
                    continue
                hedges.append(hedge([(x, y0), (x, y1)]))
                windbreak = rnd.random() < 0.12
                cp = copse_p(x, (y0 + y1) / 2)
                for t in range(int(y0) + 6, int(y1) - 4, 13 if windbreak else 1):
                    if windbreak or rnd.random() < cp:
                        trees.append([round(x + rnd.uniform(-1, 1), 1), float(t), "poplar" if windbreak else "copse", round(rnd.uniform(0.8, 1.3), 2)])
        for j in range(len(ys)):
            for i in range(len(xs) - 1):
                y, x0, x1 = ys[j], xs[i], xs[i + 1]
                if near_city((x0 + x1) / 2, y, 30) or rnd.random() > keep_p((x0 + x1) / 2, y):
                    continue
                hedges.append(hedge([(x0, y), (x1, y)]))
                cp = copse_p((x0 + x1) / 2, y)
                for t in range(int(x0) + 6, int(x1) - 4):
                    if rnd.random() < cp:
                        trees.append([float(t), round(y + rnd.uniform(-1, 1), 1), "copse", round(rnd.uniform(0.8, 1.3), 2)])
        # woods: a few dense clumps
        for _ in range(16):
            while True:
                cx, cy = rnd.uniform(-1800, 1800), rnd.uniform(-1800, 1800)
                if not near_city(cx, cy, 150):
                    break
            r = rnd.uniform(40, 110)
            for _ in range(int(r * r / 150)):
                a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
                trees.append([round(cx + math.cos(a) * rr, 1), round(cy + math.sin(a) * rr, 1), rnd.choice(["copse", "copse", "copse", "cypress", "poplar"]), round(rnd.uniform(0.9, 1.4), 2)])
        # backdrop hills: two rows round the floor edge (the floor ends at +-2 km), nearer row green, outer row higher
        hills = []
        for row, (dist, hmin, hmax, rmin, rmax, tint) in enumerate([(1950, 50, 130, 300, 560, [112, 150, 78]), (2500, 200, 420, 700, 1100, [118, 150, 150])]):
            n = 28 if row == 0 else 12  # outer row: few big hills (mostly fogged; each costs shading)
            for k in range(n):
                t = 2 * math.pi * (k + rnd.uniform(-0.3, 0.3)) / n
                # square-ish ring hugging the floor edge
                cx, cy = math.cos(t), math.sin(t)
                m = max(abs(cx), abs(cy))
                cx, cy = cx / m * dist, cy / m * dist
                rx, ry = rnd.uniform(rmin, rmax), rnd.uniform(rmin, rmax)
                hills.append({"c": pt((cx, cy)), "r": [c(rx), c(ry), c(rnd.uniform(hmin, hmax))], "mat": "Plain", "tint": [int(tint[0] * 0.82), int(tint[1] * 0.86), int(tint[2] * 0.7)], "scale": 200})  # vibe pass: lighter (were 0.62/0.66/0.5: slate)
        self.surround_trees = trees
        self.landscape_counts = {"fields": sum(1 for s_ in slabs if s_.get("z1", 0) <= 1.2 and s_.get("scale", 0) >= 30), "hedges": len(hedges), "trees": len(trees), "hills": len(hills)}
        return {"hedges": hedges, "hills": hills}

    # ---- commons plaza: market street, shade sails, pool, planter benches, bikes, kiosks, flower beds ----------
    def plan_plaza(self):
        rnd = random.Random(515)
        cm_ = self.cells["commons"]["bounds_m"]
        solid = [b["footprint_m"] for b in self.w["buildings"] if b.get("cell") == "commons" and b["id"] not in ("chess_garden",)]
        lawns = ([458, 140, 482, 186], [385, 102, 432, 136], [478, 104, 525, 126])
        pal = [rgb(n) for n in self.palettes.get("commons", [])] + [[236, 122, 100], [226, 200, 120], [96, 160, 140], [240, 232, 214]]
        props, taken = [], []

        def free(p, r, on_lawn_ok=False):
            if not inside(p, cm_, -r):
                return False
            if any(inside(p, q, r + 1.0) for q in solid):
                return False
            if not on_lawn_ok and any(inside(p, q, r * 0.5) for q in lawns):
                return False
            return all(math.hypot(p[0] - q[0], p[1] - q[1]) > r + qr for (q, qr) in taken)

        def put(prop, p, r):
            prop["p"] = pt(p)
            props.append(prop)
            taken.append((p, r))
            self.obstacles.append((p[0], p[1], r + 1.5))

        # market street between the market hall and the amphitheater: two rows of stalls under festoon lights
        mx0, mx1 = 455.0, 470.0
        for k, y in enumerate(range(49, 98, 7)):
            put({"t": "stall", "yaw": 0, "c": pal[k % len(pal)]}, (mx0 + 3.2, y + 0.5), 1.6)
            put({"t": "stall", "yaw": 180, "c": pal[(k + 2) % len(pal)]}, (mx1 - 3.2, y + 3.5), 1.6)
        for y in range(52, 98, 12):
            props.append({"t": "lights", "p": pt((mx0 + 0.8, y)), "q": pt((mx1 - 0.8, y + 4))})
        # shade sails over the chess garden
        for k, p in enumerate(((444, 113), (466, 113), (455, 128))):
            props.append({"t": "sail", "p": pt(p), "yaw": 15 * k, "size": 1000, "c": [[240, 232, 214], [236, 122, 100], [226, 200, 120]][k]})
        # reflecting pool with jets on the east lawn
        props.append({"t": "pool", "p": pt((501, 115)), "rx": 1500, "ry": 380})
        taken.append(((501, 115), 9.0))
        self.obstacles.append((501, 115, 17))
        # flower beds edging the lawn islands
        for (x0, y0, x1, y1) in lawns:
            for _ in range(3):
                p = (rnd.uniform(x0 + 3, x1 - 3), rnd.choice([y0 + 1.5, y1 - 1.5]))
                if free(p, 2.5, True):
                    put({"t": "flowerbed", "yaw": 0, "lx": 500, "ly": 160}, p, 2.5)
        # planter benches, cafe tables, kiosks, bike parking on the paving that's left
        wants = [("planter_bench", 2.6, 8), ("tables", 3.2, 4), ("kiosk", 2.4, 3), ("bikes", 2.6, 4)]
        for t, r, n in wants:
            placed = 0
            for _ in range(4000):
                if placed >= n:
                    break
                p = (rnd.uniform(cm_[0] + 2, cm_[2] - 2), rnd.uniform(cm_[1] + 2, cm_[3] - 2))
                if not free(p, r):
                    continue
                prop = {"t": t, "yaw": rnd.choice([0, 90, 180, 270])}
                if t == "planter_bench":
                    prop.update(size=300, tree=rnd.choice(["maple", "jacaranda", "flowering cherry", "birch"]), scale=0.9)
                if t == "tables":
                    prop["c"] = pal[placed % len(pal)]
                if t == "bikes":
                    prop["n"] = 6
                put(prop, p, r)
                placed += 1
        self.add("SWCityOpenSpace", "CITY_space_commons_plaza", {"kind": "plaza", "rect_cm": rect(cm_), "props": props,
                                                                  "loc_cm": [c((cm_[0] + cm_[2]) / 2), c((cm_[1] + cm_[3]) / 2), 0]})

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
        species_by_lane = {"lane_x1": ["oak", "flame", "maple"], "lane_x2": ["jacaranda", "maple", "flame"], "lane_y1": ["flowering cherry"],
                           "lane_y2": ["maple", "flowering cherry", "oak"], "lane_north_edge": ["poplar", "birch"],
                           "lane_east_edge": ["birch", "poplar"], "lane_south_edge": ["apple", "fruit"], "lane_west_edge": ["birch"]}
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
        food = scatter([fw[0] + 1, fw[1] + 1, fw[2] - 2, hub[1] - 2], 7.0, 0.85, ["fig", "persimmon", "pawpaw", "chestnut", "fruit", "apple", "bamboo"], extra=[((fw[0] + fw[2]) / 2, y, 2.5) for y in range(34, 600, 3)])
        self.add_trees("CITY_trees_food_forest", food)
        pk = self.edges["parkway"]["bounds_m"]
        self.add_trees("CITY_trees_parkway", scatter([pk[0] + 2, pk[1] + 2, pk[2] - 2, pk[3] - 6], 13.0, 0.55, ["oak", "maple", "flowering cherry", "birch", "jacaranda", "poplar", "cypress", "shade"], (0.9, 1.25)))
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
        creek += scatter([cc[0] + 3, cc[1] + 2, cc[2] - 1, cc[3] - 2], 16.0, 0.35, ["birch", "oak", "shade", "poplar", "bamboo"], (0.8, 1.1),
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
                    # orchard rows: one fruit per row line so rows read as an orchard
                    row_sp = ["apple", "persimmon", "fruit", "apple", "fig", "flowering cherry"][int(y) % 6]
                    out.append([round(p[0], 2), round(p[1], 2), row_sp, round(rnd.uniform(0.85, 1.15), 2)])
            for (cx, cy) in ((x0 + 4, y0 + 4), (x1 - 4, y0 + 4), (x0 + 4, y1 - 4), (x1 - 4, y1 - 4)):
                if abs(cx - gx) > 6:
                    out.append([round(cx, 2), round(cy, 2), "bamboo", round(rnd.uniform(0.8, 1.0), 2)])
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
                    green.append([round(p[0], 2), round(p[1], 2), rnd.choice(["shade", "oak", "jacaranda", "flame"]), round(rnd.uniform(0.85, 1.1), 2)])
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
                commons.append([round(p[0], 2), round(p[1], 2), rnd.choice(["jacaranda", "flowering cherry", "flame", "oak", "maple", "bamboo", "willow"]), round(rnd.uniform(0.85, 1.1), 2)])
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

        # the surrounding landscape's trees (copses on hedgerows, woods, orchards, poplar windbreaks) come from plan_landscape
        # near ring casts shadows; the far landscape doesn't (VSM cost), and it is read from the air anyway
        near, far = [], []
        for t in self.surround_trees:
            (near if math.hypot(t[0] - 300, t[1] - 300) < 750 else far).append(t)
        self.add_trees("CITY_trees_surround", near, gi=False)
        self.add_trees("CITY_trees_far", [[t[0], t[1], t[2] + "@far", t[3]] for t in far], shadow=False)

    def add_trees(self, name, trees, shadow=True, gi=True):
        if trees:
            cfg = {"loc_cm": [0, 0, 0], "trees": [[c(t[0]), c(t[1]), t[2], t[3]] for t in trees]}
            if not gi:
                cfg["gi"] = False
            if not shadow:
                cfg["shadow"] = False
                cfg["gi"] = False
                cfg["cull_cm"] = 170000
            self.add("SWCityTrees", name, cfg)

    # ---- realism pilot (city/realism/) ---------------------------------------------------------
    PILOT_M = (330, 80, 420, 150)  # x0, y0, x1, y1: everything seen from the Moss-Commons bridge walk

    def apply_realism(self, actors):
        """Mark the pilot area's actors "real" (realism materials, leaf-card foliage) and move the trees inside it
        into their own CITY_trees_pilot actor. City-wide actors that only cross the area (lanes, the Commons plaza,
        ground, paths) stay as they are, so the rest of the city renders unchanged."""
        x0, y0, x1, y1 = self.PILOT_M
        hit = lambda r: r[0] < x1 and r[2] > x0 and r[1] < y1 and r[3] > y0
        ids = {b["id"] for b in self.w["buildings"] if hit(b["footprint_m"])}
        ids |= {br["id"] for br in self.bridges if any(x0 <= q[0] <= x1 and y0 <= q[1] <= y1 for q in br["span_m"])}
        names = {f"city_{k}_{i}" for i in ids for k in ("bldg", "landing", "bridge", "place")}
        names |= {"city_place_observatory"} if "library" in ids else set()
        pilot_trees, out = [], []
        for cls, name, cfg in actors:
            loc = cfg.get("loc_cm", [None, None])
            if name.lower() in names or (cls == "SWStreetFurniture" and x0 * 100 <= loc[0] <= x1 * 100 and y0 * 100 <= loc[1] <= y1 * 100):
                cfg = {**cfg, "real": True}
            elif cls == "SWCityTrees" and cfg.get("gi", True) and "trees" in cfg:
                inside_ = [t for t in cfg["trees"] if x0 * 100 <= t[0] <= x1 * 100 and y0 * 100 <= t[1] <= y1 * 100]
                if inside_:
                    pilot_trees += inside_
                    cfg = {**cfg, "trees": [t for t in cfg["trees"] if t not in inside_]}
            out.append((cls, name, cfg))
        if pilot_trees:
            out.append(("SWCityTrees", "CITY_trees_pilot", {"loc_cm": [0, 0, 0], "trees": pilot_trees, "real": True}))
        return out

    def build(self):
        self.plan_ground()
        self.plan_lanes()
        self.plan_paths()
        self.plan_water()
        self.plan_buildings()
        self.plan_bridges()
        self.plan_furniture()
        self.plan_places()
        self.plan_plaza()
        self.plan_trees()
        # configure the big landscape actor last: built first, it measured ~1.4 ms slower per frame (aerial) for
        # the same geometry (an ordering effect inside the renderer; reproducible with a full rebuild)
        self.actors.sort(key=lambda a: a[1] == "CITY_landscape")
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
    ap.add_argument("--realism", action="store_true", help="realism pilot around the bridge walk (city/realism/); off = the city as before")
    args = ap.parse_args()

    w = json.loads(Path(args.world).read_text())
    plan = Plan(w)
    actors = plan.build()
    if args.realism:
        actors = plan.apply_realism(actors)
        print("realism pilot:", ", ".join(n for _, n, cfg in actors if cfg.get("real")))
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
