"""The agents' city as a 2D plan: city/world.json, and checks that its parts agree with each other.
A check never changes the world. It lists what looks inconsistent, for a person to decide."""
import json
from pathlib import Path

from core.settings import ROOT

WORLD = ROOT / "city" / "world.json"
# The narrowest lane two people walking and one bike can pass in.
MIN_LANE_M = 6


def world(path=None):
    return json.loads(Path(path or WORLD).read_text())


def _inside(point, box):
    x, y = point
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def _overlap(a, b):
    """Area two boxes share. Touching edges share none."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, width) * max(0, height)


def _areas(data):
    return {area["id"]: area["bounds_m"] for area in [*data["cells"], *data["edges"]]}


def _roofs(data):
    """Buildings that have a roof to stand on, as (id, footprint, height)."""
    return [(b["id"], b["footprint_m"], b.get("height_m", 0)) for b in data["buildings"] if b.get("height_m")]


def checks(data):
    """Each problem as {kind, ids, text}. ids name the parts the map should point at."""
    found = []
    areas = _areas(data)

    def note(kind, ids, text):
        found.append({"kind": kind, "ids": ids, "text": text})

    # A sky bridge has to land on a roof at least as high as the bridge, at both ends.
    elevation = data["sky_bridges"]["elevation_m"]
    roofs = _roofs(data)
    for bridge in data["sky_bridges"]["segments"]:
        for end in bridge["span_m"]:
            under = [(bid, height) for bid, box, height in roofs if _inside(end, box)]
            if not under:
                note("bridge", [bridge["id"]], f"{bridge['id']} ends at {end} with no building under it.")
            elif max(height for _, height in under) < elevation:
                bid, height = max(under, key=lambda item: item[1])
                note("bridge", [bridge["id"], bid],
                     f"{bridge['id']} is at {elevation} m but lands on {bid}, which is only {height} m tall.")

    # Everything that names a cell should sit inside it.
    for building in data["buildings"]:
        box, cell = building["footprint_m"], building["cell"]
        if cell in areas and not (_inside(box[:2], areas[cell]) and _inside(box[2:], areas[cell])):
            home = next((aid for aid, bounds in areas.items() if _inside(box[:2], bounds) and _inside(box[2:], bounds)), "nowhere")
            note("placement", [building["id"]], f"{building['id']} says it is in {cell}, but its footprint is in {home}.")
    for place in data["places"]:
        cell = place["cell"]
        if cell in areas and not _inside(place["pos_m"], areas[cell]):
            home = next((aid for aid, bounds in areas.items() if _inside(place["pos_m"], bounds)), "a lane")
            note("placement", [place["id"]], f"{place['id']} says it is in {cell}, but its point is in {home}.")

    # Two buildings in one spot, unless one is open ground the other stands in, or a tower built on the other's roof.
    standing = [b for b in data["buildings"] if b.get("type") != "courtyard"]
    for i, a in enumerate(standing):
        for b in standing[i + 1:]:
            if a.get("on") == b["id"] or b.get("on") == a["id"]:
                continue
            shared = _overlap(a["footprint_m"], b["footprint_m"])
            if shared and a.get("height_m") and b.get("height_m"):
                note("overlap", [a["id"], b["id"]], f"{a['id']} and {b['id']} overlap by {shared:.0f} m².")

    # A walkway that runs through water.
    ponds = [item for item in data["landscape"] if item["type"] == "pond"]
    for path in data["paths"]:
        points = path.get("polyline_m", [])
        for pond in ponds:
            (cx, cy), rx, ry = pond["ellipse_m"]["center"], pond["ellipse_m"]["rx"], pond["ellipse_m"]["ry"]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                wet = [t / 50 for t in range(51) if ((x0 + (x1 - x0) * t / 50 - cx) / rx) ** 2 + ((y0 + (y1 - y0) * t / 50 - cy) / ry) ** 2 < 1]
                if wet:
                    note("water", [path["id"], pond["id"]], f"{path['id']} runs through {pond['id']} for about {len(wet) / 50 * ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5:.0f} m.")
                    break

    for lane in data["lanes"]["segments"]:
        x0, y0, x1, y1 = lane["rect_m"]
        width = min(x1 - x0, y1 - y0)
        if width < MIN_LANE_M:
            note("lane", [lane["id"]], f"{lane['id']} is {width:g} m wide, under {MIN_LANE_M} m.")
    return found
