#!/usr/bin/env python
"""Validate data/city/world.json against data/city/world.json and the building-kind catalog.

    ~/Desktop/kokopelli/simworld/.venv/bin/python -m tools.city_build.plan_varied.check [--world data/city/world.json] [--kits]

Errors (exit 1): overlaps / gaps < 3 m between buildings, anything on a lane or path, out-of-cell footprints,
heights and plot sizes outside the kind's range (module SIZES when the kind exists, else CATALOG.md), sky-bridge
ends that don't land on a 17.5 m roof or landing tower, spans through tall buildings, a broken canopy-walk loop,
places not inside a fitting building / open space of their cell, dangling refs, changes to anything that must stay
(non-residential buildings, lanes, water, landscape, moss_east, bridge_moss_commons, the commons landings), and a
moss_east actor config that differs from the one world.json produces.
Warnings: missing kinds, kind-usage balance, entrances not near a lane/path/open space.
--kits also draws every existing kind at its plot (Python only, no editor) and checks the kit stays under
height_m and that each bridge end meets kit geometry near 17.5 m.
"""
import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RES = ("fern", "moss", "birch", "reed", "clover", "sorrel", "heron")
KEEP = {"moss_east"}
WALK = 17.5
PARK_IDS = {"village_green", "playground"}  # ids build_city reads by name; now central_park / castle_playground kits
STREAM = 0.55  # fallingwater: local y of its stream as a fraction of d (kind author: 0.5-0.6; verify with --kits)
GAP = 3.0
FAMOUS = ("farnsworth", "stahl_house", "glass_house", "kaufmann_desert", "casa_de_vidro", "eames_house")
REPEAT = ("butterfly_row", "coconut_shophouse", "breeze_block_flats", "eichler_court", "stilt_house")
FIT = {  # place category -> words that must appear in the host's use/description (or an open space)
    "cafe": ("cafe", "tea", "shop"), "bakery": ("bakery", "shop"), "health": ("clinic",), "childcare": ("daycare",),
    "fashion_studio": ("fashion", "studio"), "pub_music": ("pub",), "music_studio": ("music", "practice"),
    "community_kitchen": ("kitchen",), "fab_lab": ("fab", "workshop"), "grocery": ("grocery", "shop"),
    "art_studio": ("art", "studio"), "gym": ("gym",), "common_house": ("common",),
}


def catalog():
    out = {}
    for line in (ROOT / "tools" / "city_build" / "kinds" / "CATALOG.md").read_text().splitlines():
        m = re.match(r"\|\s*(\w+)\s*\|\s*(\w+)\s*\|.*\|\s*([\d.]+)-([\d.]+)\s*\|\s*([\d.]+)-([\d.]+)\s*\|\s*([\d.]+)-([\d.]+)\s*\|\s*$", line)
        if m:
            mod, k = m.group(1), m.group(2)
            v = list(map(float, m.groups()[2:]))
            out[k] = {"module": mod, "w": (v[0], v[1]), "d": (v[2], v[3]), "h": (v[4], v[5])}
    return out


def sizes():
    """name -> SIZES entry over every existing kind module (+ the set of kinds that exist)."""
    import importlib
    import pkgutil
    import tools.city_build.kinds as K
    out, have = {}, set()
    for m in pkgutil.iter_modules(K.__path__):
        if m.name in K.SKIP or m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"tools.city_build.kinds.{m.name}")
        except Exception as e:  # a module mid-edit by its author
            print(f"  (kind module {m.name} failed to import: {e!r})")
            continue
        have |= set(getattr(mod, "KINDS", {}))
        out.update(getattr(mod, "SIZES", {}))
    return out, have


def overlap(a, b, pad=0.0):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def rect_gap(a, b):
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return math.hypot(dx, dy)


def inside(p, r, pad=0.0):
    return r[0] - pad <= p[0] <= r[2] + pad and r[1] - pad <= p[1] <= r[3] + pad


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def seg_rect_dist(a, b, r):
    """min distance from segment ab to rect r (0 if they cross)"""
    if inside(a, r) or inside(b, r):
        return 0.0
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25))
    best = 1e9
    for i in range(n + 1):
        t = i / n
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        dx = max(r[0] - p[0], 0, p[0] - r[2])
        dy = max(r[1] - p[1], 0, p[1] - r[3])
        best = min(best, math.hypot(dx, dy))
    return best


def plot_wd(r, front):
    ex, ey = r[2] - r[0], r[3] - r[1]
    return (ex, ey) if front in ("N", "S") else (ey, ex)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=str(ROOT / "data" / "city" / "world.json"))
    ap.add_argument("--kits", action="store_true", help="also draw the existing kinds and check their geometry")
    ap.add_argument("-q", action="store_true", help="only print errors and the summary")
    args = ap.parse_args()
    w0 = json.loads((ROOT / "data" / "city" / "world.json").read_text())
    w = json.loads(Path(args.world).read_text())
    errs, warns = [], []
    E = errs.append
    W = warns.append
    cat = catalog()
    siz, have = sizes()
    cells = {c["id"]: c for c in w["cells"] + w["edges"]}
    lanes = w["lanes"]["segments"]
    blds = {}
    for b in w["buildings"]:
        if b["id"] in blds:
            E(f"duplicate building id {b['id']}")
        blds[b["id"]] = b

    # ---- 1. what must stay unchanged ------------------------------------------------------------------------
    for key in ("lanes", "landscape", "edges", "places_count"):
        if key == "places_count":
            if sorted(p["id"] for p in w["places"]) != sorted(p["id"] for p in w0["places"]):
                E("place ids changed")
            continue
        if w.get(key) != w0.get(key):
            E(f"{key} changed")
    for c0 in w0["cells"]:
        c = cells.get(c0["id"])
        if not c or c["bounds_m"] != c0["bounds_m"]:
            E(f"cell {c0['id']} bounds changed")
        if c0["id"] not in RES and c != c0:
            E(f"cell {c0['id']} changed")
    for b0 in w0["buildings"]:
        if b0.get("cell") in RES and b0["id"] not in KEEP:
            continue
        if b0["id"] in PARK_IDS:  # the user's central park replaces the Village Green lawn and the old playground
            b = blds.get(b0["id"])
            if not b or not b.get("exception"):
                E(f"{b0['id']}: must be the user's park (flagged 'exception')")
            continue
        if b0.get("type") == "canopy_landing" and b0.get("cell") in RES:
            continue
        if blds.get(b0["id"]) != b0:
            E(f"building {b0['id']} must stay unchanged")
    br0 = {s["id"]: s for s in w0["sky_bridges"]["segments"]}
    brs = {s["id"]: s for s in w["sky_bridges"]["segments"]}
    if brs.get("bridge_moss_commons") != br0["bridge_moss_commons"]:
        E("bridge_moss_commons must stay unchanged")
    if w["sky_bridges"]["elevation_m"] != WALK:
        E("sky bridge elevation changed")
    for p0 in w0["paths"]:
        p = next((q for q in w["paths"] if q["id"] == p0["id"]), None)
        if p is None:
            E(f"path {p0['id']} removed")
        elif p0.get("polyline_m") and p.get("polyline_m") != p0["polyline_m"]:
            E(f"path {p0['id']} moved")
    for p0 in w0["places"]:
        p = next(q for q in w["places"] if q["id"] == p0["id"])
        if p0["cell"] not in RES and p0["id"] not in PARK_IDS and p != p0:
            E(f"place {p0['id']} outside the residential cells changed")
        if {k: v for k, v in p.items() if k != "pos_m"} != {k: v for k, v in p0.items() if k != "pos_m"}:
            E(f"place {p0['id']}: only pos_m may change")
    landing_ids0 = {b["id"] for b in w0["buildings"] if b.get("type") == "canopy_landing"}
    for lid in landing_ids0:
        if lid not in blds or blds[lid].get("type") != "canopy_landing":
            E(f"canopy landing {lid} missing")

    # ---- 2. footprints: bounds, lanes, gaps, kinds, sizes ----------------------------------------------------
    solid = [b for b in w["buildings"] if b.get("floors", 0) > 0 and b.get("type") not in ("courtyard",)]
    opens = [b for b in w["buildings"] if b not in solid]
    new = [b for b in w["buildings"] if (b.get("cell") in RES and b["id"] not in KEEP) or b.get("exception")]
    planned = lambda b: b.get("cell") in RES or bool(b.get("exception"))
    kits = [b for b in new if b.get("arch")]
    for b in new:
        r = b["footprint_m"]
        if not (r[0] < r[2] and r[1] < r[3]):
            E(f"{b['id']}: bad rect {r}")
        cb = cells[b["cell"]]["bounds_m"]
        if not (cb[0] - 1e-6 <= r[0] and r[2] <= cb[2] + 1e-6 and cb[1] - 1e-6 <= r[1] and r[3] <= cb[3] + 1e-6):
            E(f"{b['id']}: outside its cell {b['cell']} {cb}")
        for l in lanes:
            if overlap(r, l["rect_m"]):
                E(f"{b['id']}: overlaps lane {l['id']}")
    for i, a in enumerate(solid):
        for b in solid[i + 1:]:
            if not planned(a) and not planned(b):
                continue
            if a.get("on") == b["id"] or b.get("on") == a["id"]:
                continue
            g = rect_gap(a["footprint_m"], b["footprint_m"])
            if g < GAP - 1e-6:
                E(f"{a['id']} / {b['id']}: gap {g:.1f} m < {GAP}")
    for i, a in enumerate(opens):
        for b in opens[i + 1:] + solid:
            if not planned(a) and not planned(b):
                continue
            if overlap(a["footprint_m"], b["footprint_m"]) and not {a["id"], b["id"]} <= PARK_IDS:
                E(f"open space {a['id']} overlaps {b['id']}")
    used = {}
    for b in kits:
        k = b["arch"]
        used.setdefault(k, []).append(b["id"])
        ref = siz.get(k) or cat.get(k)
        if ref is None:
            E(f"{b['id']}: unknown kind {k}")
            continue
        if k not in have:
            W(f"{b['id']}: kind {k} not written yet")
        wd = plot_wd(b["footprint_m"], b["front"])
        for ax, v in (("w", wd[0]), ("d", wd[1]), ("h", b["height_m"])):
            lo, hi = ref[ax]
            if not (lo - 1e-6 <= v <= hi + 1e-6):
                E(f"{b['id']} ({k}): {ax} {v:g} outside {lo:g}-{hi:g}" + ("" if k in siz else " (catalog)"))
        fl = ref.get("floors")
        if fl and not (fl[0] <= b["floors"] <= fl[1]):
            W(f"{b['id']} ({k}): floors {b['floors']} outside {fl}")
        if b["front"] not in "NSEW" or len(b["front"]) != 1:
            E(f"{b['id']}: bad front {b['front']}")
        if len(b.get("palette", [])) != 3:
            E(f"{b['id']}: palette needs 3 names")
        from tools.city_build.build_city import COLORS
        for n in b.get("palette", []):
            if n not in COLORS:
                E(f"{b['id']}: palette colour {n!r} not in build_city.COLORS")
        for key in ("id", "cell", "footprint_m", "front", "arch", "floors", "height_m", "use", "palette", "entrances", "seed"):
            if key not in b:
                E(f"{b['id']}: missing {key}")
        if b["height_m"] > 36.0 + 1e-6:
            E(f"{b['id']}: taller than 36 m")
    composed = {"castle_playground": "central_park"}  # drawn inside another kind's plot
    for k in cat:
        if k not in used and composed.get(k) not in used:
            E(f"kind {k} not used in any cell")
    for k in FAMOUS:
        if len(used.get(k, [])) > 2:
            E(f"famous one-off {k} used {len(used[k])} times")
    cells_of = {k: sorted({blds[i]["cell"] for i in v}) for k, v in used.items()}

    # ---- 3. paths (mews) --------------------------------------------------------------------------------------
    for p in w["paths"]:
        if p.get("cell") not in RES or not p.get("polyline_m"):
            continue
        pl = p["polyline_m"]
        cb = cells[p["cell"]]["bounds_m"]
        for q in pl:
            if not inside(q, cb, 0.01):
                E(f"path {p['id']}: point {q} outside its cell")
        for b in solid:
            for i in range(len(pl) - 1):
                d = seg_rect_dist(pl[i], pl[i + 1], b["footprint_m"])
                if d < 1.5 - 1e-6:
                    E(f"path {p['id']} runs through/too close to {b['id']} ({d:.1f} m < 1.5)")
                    break

    # ---- 3b. the user's exceptions outside the cells (Fallingwater over Willow Creek) --------------------------------
    land = {l["id"]: l for l in w["landscape"]}
    for b in new:
        if not b.get("exception"):
            continue
        r = b["footprint_m"]
        for p in w["paths"]:
            pl = p.get("polyline_m")
            if not pl:
                continue
            half = 1.3 if p.get("type") == "boardwalk" else 1.5
            d = min(seg_rect_dist(pl[i], pl[i + 1], r) for i in range(len(pl) - 1))
            if d < half + 0.5:
                E(f"{b['id']}: {d:.1f} m from path {p['id']} (needs {half + 0.5:.1f})")
        pond = land.get("swim_pond")
        if pond:
            e = pond["ellipse_m"]
            px = min(max(e["center"][0], r[0]), r[2])
            py = min(max(e["center"][1], r[1]), r[3])
            if ((px - e["center"][0]) / (e["rx"] + 5)) ** 2 + ((py - e["center"][1]) / (e["ry"] + 5)) ** 2 < 1:
                E(f"{b['id']}: within 5 m of the swim pond")
        if b.get("arch") == "fallingwater":
            # the kind's stream runs along local x at local y = STREAM * d; it must sit on the real creek
            cl = land["willow_creek"]["centerline_m"]
            wd = plot_wd(r, b["front"])
            along_y = b["front"] in ("E", "W")
            worst = 0.0
            lo, hi = (r[1], r[3]) if along_y else (r[0], r[2])
            for k in range(11):
                t = lo + (hi - lo) * k / 10
                if along_y:
                    xs = [a[0] + (c[0] - a[0]) * (t - a[1]) / (c[1] - a[1]) for a, c in zip(cl, cl[1:], strict=False) if a[1] <= t <= c[1] and c[1] != a[1]]
                    if not xs:
                        E(f"{b['id']}: creek doesn't pass y={t:.0f}")
                        break
                    stream = r[0] + STREAM * wd[1] if b["front"] == "W" else r[2] - STREAM * wd[1]
                    worst = max(worst, abs(xs[0] - stream))
                else:
                    E(f"{b['id']}: fallingwater must face E or W to follow the north-south creek")
                    break
            if worst > 2.0:
                E(f"{b['id']}: kind's stream is {worst:.1f} m off the creek centreline (> 2 m)")
            elif not args.q:
                print(f"  {b['id']}: stream within {worst:.1f} m of the creek centreline (stream at {STREAM:.2f} d)")

    # ---- 4. entrances face a lane, a path or an open space -----------------------------------------------------
    plines = [p["polyline_m"] for p in w["paths"] if p.get("polyline_m")]
    for b in kits:
        r = b["footprint_m"]
        for e in b.get("entrances", []):
            p = e["pos_m"]
            if not inside(p, r, 0.01):
                E(f"{b['id']}: entrance {p} not on the building")
            near = any(inside(p, l["rect_m"], 1.0) for l in lanes)
            near = near or any(seg_dist(p, pl[i], pl[i + 1]) <= 9 for pl in plines for i in range(len(pl) - 1))
            near = near or any(inside(p, o["footprint_m"], 8) for o in opens if o.get("cell") == b["cell"])
            if not near and not b.get("exception"):
                E(f"{b['id']}: entrance {p} faces no lane, path or open space")
            # on the front edge
            fx = {"N": abs(p[1] - r[1]), "S": abs(p[1] - r[3]), "W": abs(p[0] - r[0]), "E": abs(p[0] - r[2])}[b["front"]]
            if fx > 0.5 and not b.get("exception"):
                W(f"{b['id']}: entrance {p} not on the {b['front']} front")
        # a lane-side front must face the lane
        fr = b["front"]
        x0, y0, x1, y1 = r
        probe = {"N": ((x0 + x1) / 2, y0 - 1), "S": ((x0 + x1) / 2, y1 + 1), "W": (x0 - 1, (y0 + y1) / 2), "E": (x1 + 1, (y0 + y1) / 2)}[fr]
        on_lane = any(inside(probe, l["rect_m"]) for l in lanes) or bool(b.get("exception"))
        if not on_lane:
            near_path = any(seg_dist(probe, pl[i], pl[i + 1]) < 9 for pl in plines for i in range(len(pl) - 1))
            near_open = any(inside(probe, o["footprint_m"], 2) for o in opens if o.get("cell") == b["cell"])
            if not (near_path or near_open):
                E(f"{b['id']}: front {fr} faces neither a lane nor a path/open space")

    # ---- 5. canopy walk ----------------------------------------------------------------------------------------
    landings = [b for b in w["buildings"] if b.get("type") == "canopy_landing"]
    # bridge ends land on landing towers or on a bar with a real roof deck (moss_east); kit roofs are not walk decks
    hosts = [b for b in solid if abs(b.get("height_m", 0) - WALK) < 0.01 and not b.get("arch")]
    nodes = {b["id"]: b for b in hosts + landings}
    graph = {}
    for s in w["sky_bridges"]["segments"]:
        a, c = s["span_m"]
        ends = []
        for p in (a, c):
            hit = [b for b in nodes.values() if inside(p, b["footprint_m"], 1.0)]
            if not hit:
                E(f"sky bridge {s['id']}: end {p} lands on nothing at 17.5 m")
                ends.append(None)
            else:
                ends.append(hit[0]["id"])
        L = math.hypot(c[0] - a[0], c[1] - a[1])
        if L > 45:
            E(f"sky bridge {s['id']}: span {L:.0f} m > 45 m")
        for b in solid:
            if b["id"] in ends or b.get("height_m", 0) <= 12:
                continue
            if seg_rect_dist(a, c, b["footprint_m"]) < 0.5:
                E(f"sky bridge {s['id']} passes through {b['id']} ({b['height_m']} m)")
        if None not in ends:
            graph.setdefault(ends[0], set()).add(ends[1])
            graph.setdefault(ends[1], set()).add(ends[0])
    for l in landings:
        if l.get("on") and l["on"] not in blds:
            E(f"landing {l['id']}: host {l['on']} missing")
    # walking across a roof or down a tower joins nothing else; components over the bridge graph
    seen, comps = set(), []
    for n in graph:
        if n in seen:
            continue
        stack, comp = [n], set()
        while stack:
            m = stack.pop()
            if m in comp:
                continue
            comp.add(m)
            stack += list(graph[m] - comp)
        seen |= comp
        comps.append(comp)
    # the commons is a ground link (as in world.json): its two landings join through the plaza
    ground = [tuple(g["between"]) for g in w["sky_bridges"].get("ground_links", [])] or [("landing_commons_west", "landing_commons_south")]
    for a_, c_ in ground:
        for n_ in (a_, c_):
            if n_ not in blds:
                E(f"ground link end {n_} missing")
            elif n_ not in graph:
                W(f"ground link end {n_} has no sky bridge")
    for a, c in ground:
        ca = next((x for x in comps if a in x), None)
        cc = next((x for x in comps if c in x), None)
        if ca is not None and cc is not None and ca is not cc:
            comps.remove(cc)
            ca |= cc
    if len(comps) != 1:
        E(f"canopy walk falls into {len(comps)} pieces: " + " | ".join(",".join(sorted(c)) for c in comps))
    deg1 = [n for n in graph if len(graph[n]) == 1 and n not in {x for g in ground for x in g}]
    if deg1:
        W(f"canopy walk dead ends: {deg1}")
    walk_cells = sorted({nodes[n].get("cell") for n in graph})
    for c in RES:
        if c not in walk_cells:
            E(f"canopy walk misses {c}")

    # ---- 6. places --------------------------------------------------------------------------------------------
    for pl in w["places"]:
        if pl["cell"] not in RES:
            continue
        p = pl["pos_m"]
        host = [b for b in w["buildings"] if b.get("cell") == pl["cell"] and b.get("type") != "canopy_landing" and inside(p, b["footprint_m"])]
        if not host:
            E(f"place {pl['id']} {p} sits in no building/open space of {pl['cell']}")
            continue
        h = host[0]
        words = FIT.get(pl["category"], ())
        text = " ".join(str(h.get(k, "")) for k in ("use", "description", "features", "ground_floor", "id")).lower()
        if h.get("floors", 0) > 0 and words and not any(wd in text for wd in words):
            W(f"place {pl['id']} ({pl['category']}) is in {h['id']} whose use is {h.get('use')!r}")

    for pid in PARK_IDS:
        pl = next((q for q in w["places"] if q["id"] == pid), None)
        if pl and not any(inside(pl["pos_m"], blds[q]["footprint_m"]) for q in PARK_IDS if q in blds):
            E(f"place {pid} {pl['pos_m']} is not inside the park")

    # ---- 7. refs ----------------------------------------------------------------------------------------------
    for f in w["street_furniture"]:
        if f.get("on_building") and f["on_building"] not in blds:
            E(f"street furniture {f['type']} refers to missing {f['on_building']}")
        if f.get("pos_m"):
            for b in solid:
                if planned(b) and inside(f["pos_m"], b["footprint_m"]):
                    E(f"street furniture {f['type']} at {f['pos_m']} is inside {b['id']}")
    if len(w["street_furniture"]) != len(w0["street_furniture"]):
        E("street furniture count changed")

    # ---- 8. moss_east's actor config is identical (the world-model bridge shot) -----------------------------------
    try:
        from tools.city_build import build_city as bc

        def moss_cfg(world):
            pl = bc.Plan(copy.deepcopy(world))
            pl.blds = {b["id"]: b for b in pl.w["buildings"]}
            pl.w["buildings"] = [b for b in pl.w["buildings"] if not b.get("arch")]  # kits don't touch bar configs
            pl.plan_buildings()
            pl.plan_bridges()
            return [(n, cfg) for cls, n, cfg in pl.actors if n in ("CITY_bldg_moss_east", "CITY_bridge_bridge_moss_commons", "CITY_landing_landing_commons_west")]

        if moss_cfg(w0) != moss_cfg(w):
            E("moss_east / bridge_moss_commons / landing_commons_west actor configs differ from world.json's")
    except Exception as e:
        E(f"could not compare moss_east configs: {e!r}")

    # ---- 8b. the whole build_city plan runs (what `build_city.py --world ... --dry` does) ---------------------------
    try:
        from tools.city_build import build_city as bc
        acts = bc.Plan(copy.deepcopy(w)).build()
        if not args.q:
            print(f"  build_city plan: {len(acts)} actors")
    except KeyError as e:
        (W if str(e).strip("'") in cat and str(e).strip("'") not in have else E)(f"build_city plan failed: missing kind {e}")
    except Exception as e:
        E(f"build_city plan failed: {e!r}")

    # ---- 9. kits (geometry) ----------------------------------------------------------------------------------
    if args.kits:
        from tools.city_build.kinds import Plot, all_kinds
        from tools.city_build.build_city import rgb
        ak = all_kinds()
        for b in kits:
            if b["arch"] not in ak:
                continue
            wd = plot_wd(b["footprint_m"], b["front"])
            plot = Plot(w=wd[0], d=wd[1], h_max=b["height_m"], floors=b["floors"], palette=[rgb(n) for n in b["palette"]],
                        seed=b["seed"], use=b["use"], cell=b["cell"])
            try:
                kit = ak[b["arch"]][1](plot)
            except Exception as e:
                E(f"{b['id']} ({b['arch']}): kind raised {e!r}")
                continue
            st = kit.stats()
            bnds = [x for x in (op_bounds(op) for op in kit.ops) if x]
            if b["arch"] == "fallingwater":
                water = {i for i, sl in enumerate(kit.slots) if sl["mat"] == "Water"}
                wb = [op_bounds(op) for op in kit.ops if op[1] in water and op_bounds(op)]
                if not wb:
                    W(f"{b['id']}: no Water ops found in the fallingwater kit")
                else:
                    # local centred cm -> fraction of d from the front (front line at local y = -d/2)
                    longest = max(wb, key=lambda x: x[3] - x[0])
                    frac = ((longest[1] + longest[4]) / 2 / 100 + wd[1] / 2) / wd[1]
                    msg = f"{b['id']}: kit stream at {frac:.2f} d (check.py/plan.py assume {STREAM:.2f})"
                    (W if abs(frac - STREAM) * wd[1] > 1.5 else print)(("WARN? " if False else "  ") + msg if abs(frac - STREAM) * wd[1] <= 1.5 else msg)
            ztop = max((x[5] for x in bnds), default=0) / 100
            for s in w["sky_bridges"]["segments"]:
                for p in s["span_m"]:
                    if not inside(p, b["footprint_m"], 1.0):
                        continue
                    lx, ly = world_to_local(b, p)
                    deck = [x for x in bnds if x[0] - 300 <= lx <= x[3] + 300 and x[1] - 300 <= ly <= x[4] + 300 and 1550 <= x[5] <= 1900]
                    if not deck:
                        W(f"{b['id']} ({b['arch']}): no kit geometry at 15.5-19 m within 3 m of the bridge end {p} ({s['id']})")
            if ztop > b["height_m"] + 0.6:
                W(f"{b['id']} ({b['arch']}): kit top {ztop:.1f} m > height_m {b['height_m']}")
            lim = (8000, 2500) if b["arch"] in ("central_park",) else (4000, 600)  # park author's stated budget
            if st["ops"] > lim[0] or st["inst"] > lim[1] or st["slots"] > 24:
                W(f"{b['id']} ({b['arch']}): budget {st}")
            if not args.q:
                print(f"  kit {b['id']:22s} {b['arch']:18s} top {ztop:5.1f}/{b['height_m']:4.1f} m  {st}")

    # ---- report ----------------------------------------------------------------------------------------------
    if not args.q:
        print(f"kind buildings: {len(kits)} in {len(RES)} cells; open spaces: {sum(1 for b in new if not b.get('arch') and b.get('type') != 'canopy_landing')}; "
              f"landings: {len(landings)}; sky spans: {len(w['sky_bridges']['segments'])}")
        for c in RES:
            ks = [b["arch"] for b in kits if b["cell"] == c]
            hs = [b["height_m"] for b in kits if b["cell"] == c]
            print(f"  {c:7s} {len(ks):2d} buildings, h {min(hs):g}-{max(hs):g} m: {', '.join(sorted(set(ks)))}")
        def gfa(world):
            out = {}
            for b_ in world["buildings"]:
                if b_.get("cell") in RES and b_.get("floors", 0) > 0 and b_.get("type") not in ("courtyard", "canopy_landing"):
                    r_ = b_["footprint_m"]
                    out[b_["cell"]] = out.get(b_["cell"], 0) + (r_[2] - r_[0]) * (r_[3] - r_[1]) * b_["floors"]
            return out
        g0, g1 = gfa(w0), gfa(w)
        print(f"floor area (plot x floors) vs world.json: {sum(g1.values()) / 1000:.0f}k / {sum(g0.values()) / 1000:.0f}k m2 = "
              f"{100 * sum(g1.values()) / sum(g0.values()):.0f}%  (" + ", ".join(f"{c} {100 * g1.get(c, 0) / g0[c]:.0f}%" for c in RES) + ")")
        print("kind use: " + ", ".join(f"{k} x{len(v)} ({'/'.join(cells_of[k])})" for k, v in sorted(used.items())))
        print(f"kinds that exist: {len(have & set(cat))}/{len(cat)}; missing: {sorted(set(cat) - have)}")
    for x in warns:
        print("WARN ", x)
    for x in errs:
        print("ERROR", x)
    print(f"check: {len(errs)} errors, {len(warns)} warnings")
    sys.exit(1 if errs else 0)


def op_bounds(op):
    """(x0, y0, z0, x1, y1, z1) in the kit's local centred frame (cm), approximate for rotated ops"""
    n, a = op[0], op[2:]
    if n == "box":
        return (min(a[0], a[3]), min(a[1], a[4]), min(a[2], a[5]), max(a[0], a[3]), max(a[1], a[4]), max(a[2], a[5]))
    if n == "obox":
        cx, cy, cz, hx, hy, hz = a[:6]
        P, Y, R = (math.radians(v) for v in (a[6:9] + [0, 0, 0])[:3])
        sp, cp, sy, cy_, sr, cr = math.sin(P), math.cos(P), math.sin(Y), math.cos(Y), math.sin(R), math.cos(R)
        ax = (cp * cy_, cp * sy, sp)                                         # UE FRotator axes
        ay = (sr * sp * cy_ - cr * sy, sr * sp * sy + cr * cy_, -sr * cp)
        az = (-(cr * sp * cy_ + sr * sy), cy_ * sr - cr * sp * sy, cr * cp)
        ex, ey, ez = (abs(ax[i]) * hx + abs(ay[i]) * hy + abs(az[i]) * hz for i in range(3))
        return (cx - ex, cy - ey, cz - ez, cx + ex, cy + ey, cz + ez)
    if n in ("beam", "pole"):
        t = a[6] / 2 if n == "beam" else a[6]
        return (min(a[0], a[3]) - t, min(a[1], a[4]) - t, min(a[2], a[5]) - t, max(a[0], a[3]) + t, max(a[1], a[4]) + t, max(a[2], a[5]) + t)
    if n == "cyl":
        r = max(a[3], a[4])
        return (a[0] - r, a[1] - r, a[2], a[0] + r, a[1] + r, a[2] + a[5])
    if n in ("prism", "ribbon"):
        z0, z1, flat = (a[0], a[1], a[3:]) if n == "prism" else (a[1], a[2], a[4:])
        xs, ys = flat[0::2], flat[1::2]
        pad = a[0] / 2 if n == "ribbon" else 0
        return (min(xs) - pad, min(ys) - pad, z0, max(xs) + pad, max(ys) + pad, z1)
    if n == "ell":
        return (a[0] - a[3], a[1] - a[4], a[2] - a[5], a[0] + a[3], a[1] + a[4], a[2] + a[5])
    if n in ("gable", "vault"):
        return (min(a[0], a[3]), min(a[1], a[4]), min(a[2], a[5]), max(a[0], a[3]), max(a[1], a[4]), max(a[2], a[5]) + a[6])
    if n in ("quad", "tri"):
        k = 4 if n == "quad" else 3
        pts = [a[3 * i:3 * i + 3] for i in range(k)]
        return (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts))
    return None


def world_to_local(b, p):
    """world metres -> the kit's local centred frame (cm)"""
    x0, y0, x1, y1 = b["footprint_m"]
    th = math.radians({"N": 0, "E": 90, "S": 180, "W": 270}[b["front"]])
    dx, dy = (p[0] - (x0 + x1) / 2) * 100, (p[1] - (y0 + y1) / 2) * 100
    return (dx * math.cos(th) + dy * math.sin(th), -dx * math.sin(th) + dy * math.cos(th))


if __name__ == "__main__":
    main()
