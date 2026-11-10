"""Walkable map of the city from world.json, and routes between named places.

The sim's move_to walks a straight line and stops if blocked, so an agent can't cross the city
with it alone. This rasterises the plan into 2 m cells (building masses and water block, ground-floor
passages stay open, matching SWCityBuilding.cpp), finds a route with A*, then keeps only the corners
so each leg is a straight line move_to can walk.

world.json: x east, y south, metres, origin at the NW corner. Unreal is the same axes in cm.
"""
import heapq
import json
import math
from pathlib import Path

WORLD = Path(__file__).resolve().parents[2] / "data" / "city" / "world.json"
CELL_M = 2.0
SIZE_M = 600.0
CLEARANCE_M = 1.0  # keep the capsule off walls
PASSAGE_HALF_M = 2.5  # SWCityBuilding.cpp cuts +-250 cm


def _inside(p, rect, pad=0.0):
    x0, y0, x1, y1 = rect
    return x0 - pad <= p[0] <= x1 + pad and y0 - pad <= p[1] <= y1 + pad


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


class NavMap:
    def __init__(self, world_path=WORLD):
        self.w = json.loads(Path(world_path).read_text())
        self.n = int(SIZE_M / CELL_M)
        self.places = {p["id"]: p for p in self.w["places"]}
        self._build()
        self.doors = {pid: self._door(p["pos_m"]) for pid, p in self.places.items()}

    # --- grid -----------------------------------------------------------------------------------

    def _build(self):
        masses, gaps = [], []
        for b in self.w["buildings"]:
            if "courtyard" in b["id"]:
                continue  # the courtyard footprint is open ground
            masses.append(b["footprint_m"])
            for e in b.get("entrances", []):
                if "passage" in e.get("type", ""):
                    gaps.append((b["footprint_m"], e["pos_m"]))
        creek = next((l for l in self.w["landscape"] if l["type"] == "creek"), None)
        pond = next((l for l in self.w["landscape"] if l["type"] == "pond"), None)
        boardwalk = next((p["polyline_m"] for p in self.w["paths"] if p["id"] == "creek_boardwalk"), [])

        self.free = bytearray(self.n * self.n)
        self.solid = bytearray(self.n * self.n)  # walls only: water stops feet, not eyes
        for j in range(self.n):
            for i in range(self.n):
                p = ((i + 0.5) * CELL_M, (j + 0.5) * CELL_M)
                blocked = any(_inside(p, m, CLEARANCE_M) for m in masses)
                if blocked:
                    for rect, (gx, gy) in gaps:
                        # a passage runs through the bar's short axis at the entrance position
                        x0, y0, x1, y1 = rect
                        along_x = (x1 - x0) >= (y1 - y0)
                        if _inside(p, rect, CLEARANCE_M) and (
                                abs(p[0] - gx) <= PASSAGE_HALF_M - CLEARANCE_M if along_x else abs(p[1] - gy) <= PASSAGE_HALF_M - CLEARANCE_M):
                            blocked = False
                            break
                self.solid[j * self.n + i] = 1 if blocked and any(_inside(p, m_) for m_ in masses) else 0
                if not blocked and creek:
                    line = creek["centerline_m"]
                    near = min(_seg_dist(p, line[k], line[k + 1]) for k in range(len(line) - 1))
                    on_walk = boardwalk and min(_seg_dist(p, boardwalk[k], boardwalk[k + 1]) for k in range(len(boardwalk) - 1)) < 1.5
                    blocked = near < creek["width_m"] / 2 + 0.5 and not on_walk
                if not blocked and pond:
                    (cx, cy), rx, ry = pond["ellipse_m"]["center"], pond["ellipse_m"]["rx"], pond["ellipse_m"]["ry"]
                    blocked = ((p[0] - cx) / rx) ** 2 + ((p[1] - cy) / ry) ** 2 < 1.0
                self.free[j * self.n + i] = 0 if blocked else 1

    def cell(self, p):
        return (min(self.n - 1, max(0, int(p[0] / CELL_M))), min(self.n - 1, max(0, int(p[1] / CELL_M))))

    def centre(self, c):
        return ((c[0] + 0.5) * CELL_M, (c[1] + 0.5) * CELL_M)

    def is_free(self, c):
        return 0 <= c[0] < self.n and 0 <= c[1] < self.n and self.free[c[1] * self.n + c[0]]

    def nearest_free(self, p, max_r=40):
        c0 = self.cell(p)
        if self.is_free(c0):
            return c0
        for r in range(1, max_r):
            ring = [(c0[0] + dx, c0[1] + dy) for dx in range(-r, r + 1) for dy in (-r, r)]
            ring += [(c0[0] + dx, c0[1] + dy) for dx in (-r, r) for dy in range(-r + 1, r)]
            ring = [c for c in ring if self.is_free(c)]
            if ring:
                return min(ring, key=lambda c: math.dist(self.centre(c), p))
        return None

    def _door(self, pos):
        """Places sit inside buildings; you arrive at the nearest open ground."""
        c = self.nearest_free(pos)
        return self.centre(c) if c else tuple(pos)

    # --- routes ---------------------------------------------------------------------------------

    def route(self, start, goal):
        """Waypoints in metres from start to goal, corners only. None if unreachable."""
        s, g = self.nearest_free(start), self.nearest_free(goal)
        if s is None or g is None:
            return None
        steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
        frontier = [(0.0, s)]
        came, cost = {s: None}, {s: 0.0}
        while frontier:
            _, cur = heapq.heappop(frontier)
            if cur == g:
                break
            for dx, dy, w in steps:
                nxt = (cur[0] + dx, cur[1] + dy)
                if not self.is_free(nxt) or (dx and dy and not (self.is_free((cur[0] + dx, cur[1])) and self.is_free((cur[0], cur[1] + dy)))):
                    continue
                c = cost[cur] + w
                if c < cost.get(nxt, 1e18):
                    cost[nxt], came[nxt] = c, cur
                    heapq.heappush(frontier, (c + math.dist(nxt, g), nxt))
        if g not in came:
            return None
        cells = [g]
        while came[cells[-1]] is not None:
            cells.append(came[cells[-1]])
        cells.reverse()
        return [self.centre(c) for c in self._corners(cells)] + ([tuple(goal)] if self._clear(self.cell(goal), g) else [])

    def _clear(self, a, b):
        """Straight line between two cells stays on free cells (sampled every half cell)."""
        n = max(1, int(math.dist(a, b) * 2))
        return all(self.is_free((round(a[0] + (b[0] - a[0]) * k / n), round(a[1] + (b[1] - a[1]) * k / n))) for k in range(n + 1))

    def _corners(self, cells):
        out, k = [cells[0]], 0
        while k < len(cells) - 1:
            far = k + 1
            for j in range(len(cells) - 1, k, -1):
                if self._clear(cells[k], cells[j]):
                    far = j
                    break
            out.append(cells[far])
            k = far
        return out[1:]

    def line_of_sight(self, a, b):
        """True if no building wall stands between two points (metres). Ground level only."""
        ca, cb = self.cell(a), self.cell(b)
        n = max(1, int(math.dist(ca, cb) * 2))
        for k in range(1, n):
            c = (round(ca[0] + (cb[0] - ca[0]) * k / n), round(ca[1] + (cb[1] - ca[1]) * k / n))
            if c not in (ca, cb) and self.solid[c[1] * self.n + c[0]]:
                return False
        return True

    def length(self, start, waypoints):
        pts = [start, *waypoints]
        return sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))

    def place_at(self, p, radius_m=12.0):
        """The named place you are standing at, if any."""
        best = min(self.doors.items(), key=lambda kv: math.dist(kv[1], p))
        return best[0] if math.dist(best[1], p) <= radius_m else None


if __name__ == "__main__":
    import time
    t = time.time()
    nav = NavMap()
    print(f"grid {nav.n}x{nav.n} built in {time.time() - t:.1f}s, {sum(nav.free) / len(nav.free):.0%} walkable")
    home = nav.doors["fern_common"]
    bad = []
    for pid, door in nav.doors.items():
        r = nav.route(home, door)
        if r is None:
            bad.append(pid)
        else:
            print(f"  fern_common -> {pid:15s} {len(r):2d} legs {nav.length(home, r):6.0f} m")
    print("unreachable:", bad or "none")
