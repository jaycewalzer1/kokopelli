"""The Village Green re-imagined: an ecofuturist central park, with a community-built wooden castle playground.

    castle_playground  a 1980s-90s Robert Leathers style community-built wooden castle playground: weathered
                       grey-brown timber towers under steep shingle spires, picket-fence ramparts on posts, a green
                       spiral tube slide, rope/chain bridges with red/white rungs, monkey bars and rings, a little
                       wheelchair ramp, all on wood-chip mulch
    central_park       the heart of the city: a meandering bioswale into a reed wetland with a zig-zag boardwalk, a
                       solar-tree grove around a round stage, a great lawn wrapped by grass-terraced earth seating
                       crowned with wind sculptures, a glass seed dome, colour-banded pollinator meadows, a
                       food-forest edge, a school forecourt and winding paths under many trees; the castle
                       playground is composed in by the shared helper draw_castle()

Frame (kit.py): x along the street 0..w, y away from the street 0..d (front line y = 0), z up, metres.
Deterministic from plot.seed. Foliage comes from a small fixed set of colours (each (prim, mat, tint) is one
component).
"""
import math

from .kit import Kit, WHITE

# ---- colours (sRGB) ----------------------------------------------------------------------------------------------
WEATHERED = (150, 138, 122)    # grey-brown weathered timber
SHINGLE = (96, 82, 70)         # dark weathered cedar shingles
MULCH = (122, 102, 80)         # wood-chip ground
SLIDE_GREEN = (52, 146, 72)
RUNG_RED = (196, 52, 44)
LAWN = (112, 158, 70)
MOUND = (98, 146, 62)
MEADOW = (150, 160, 84)
PATH = (214, 200, 170)
STONE = (198, 190, 174)
WATER = (62, 132, 150)
MARSH = (92, 112, 60)
PV = (44, 56, 78)
DOME = (150, 170, 176)

LEAF = ((62, 104, 46), (78, 124, 56), (96, 138, 60), (54, 92, 50))
BARK = (104, 88, 70)
BIRCH_BARK = (222, 218, 206)
CHERRY = (240, 170, 190)
JACARANDA = (150, 112, 206)
FRUIT = (236, 130, 50)
WILLOW = (128, 156, 70)
REED = ((120, 150, 80), (150, 170, 90))
LILY = (70, 120, 60)
# pollinator meadow bands: lavender, gold, poppy, white yarrow
BANDS = ((150, 112, 206), (240, 200, 70), (214, 72, 84), (246, 242, 230))


def clamp(v, a, b):
    return max(a, min(b, v))


class Slots:
    """Lazily created material slots, shared between the park and the castle (each slot is one draw call)."""

    def __init__(self, k):
        self.k = k
        self._c = {}

    def _m(self, key, mat, tint, scale=0.0):
        if key not in self._c:
            self._c[key] = self.k.mat(mat, tint, scale)
        return self._c[key]

    timber = property(lambda s: s._m("timber", "Timber", WEATHERED))
    shingle = property(lambda s: s._m("shingle", "Timber", SHINGLE))
    mulch = property(lambda s: s._m("mulch", "RammedEarth", MULCH))
    green = property(lambda s: s._m("green", "Plain", SLIDE_GREEN))
    red = property(lambda s: s._m("red", "Plain", RUNG_RED))
    white = property(lambda s: s._m("white", "Plain", WHITE))
    lawn = property(lambda s: s._m("lawn", "GreenRoof", LAWN))
    mound = property(lambda s: s._m("mound", "GreenRoof", MOUND))
    meadow = property(lambda s: s._m("meadow", "GreenRoof", MEADOW))
    path = property(lambda s: s._m("path", "Path", PATH))
    stone = property(lambda s: s._m("stone", "PermeableStone", STONE))
    water = property(lambda s: s._m("water", "Water", WATER))
    marsh = property(lambda s: s._m("marsh", "Moss", MARSH))
    pv = property(lambda s: s._m("pv", "SolarGlass", PV))
    dome = property(lambda s: s._m("dome", "SolarGlass", DOME))


# ---- small geometry helpers --------------------------------------------------------------------------------------
def post(k, s, x, y, z0, z1, t=0.2):
    k.box(s, x - t / 2, y - t / 2, z0, x + t / 2, y + t / 2, z1)


def pickets(k, s, a, b, za, zb, h, gap=0.3, t=0.09, castle=False):
    """A picket fence from a to b (2D) whose base runs from za to zb; castle=True alternates tall/short pickets."""
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    if L < 0.2:
        return
    yaw = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    n = max(1, int(L / gap))
    for i in range(n + 1):
        f = (i + 0.5) / (n + 1)
        x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        z = za + (zb - za) * f
        hh = h * (1.18 if castle and (i // 2) % 2 == 0 else 1.0)
        k.obox(s, x, y, z + hh / 2, t / 2, 0.025, hh / 2, 0, yaw, 0)
    # two rails
    for fz in (0.25, 0.8):
        k.beam(s, (a[0], a[1], za + h * fz), (b[0], b[1], zb + h * fz), 0.09, 0.07)


def pyramid(k, s, cx, cy, z, half, h):
    """Square pyramid roof (4 tris) over [cx +- half, cy +- half] at z, apex h above."""
    apex = (cx, cy, z + h)
    c = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    outs = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    for i in range(4):
        a, b = c[i], c[(i + 1) % 4]
        o = outs[i]
        k.tri(s, (a[0], a[1], z), (b[0], b[1], z), apex, (o[0] * h, o[1] * h, half))
    k.box(s, cx - half, cy - half, z - 0.06, cx + half, cy + half, z)  # soffit


def blob_poly(cx, cy, rx, ry, rng, n=18, jit=0.18):
    """A star-shaped organic outline around (cx, cy) (prism-safe)."""
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = 1 + jit * (0.6 * math.sin(2 * a + ph[0]) + 0.3 * math.sin(3 * a + ph[1]) + 0.2 * math.sin(5 * a + ph[2]))
        pts.append((cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
    return pts


def arc(cx, cy, r, a0, a1, n=16):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def smooth(pts, n=4):
    """Catmull-Rom through the points (meandering paths and swales)."""
    out = []
    P = [pts[0]] + list(pts) + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3) for c in (0, 1)))
    out.append(pts[-1])
    return out


def along(pts, step):
    """Points every `step` m along a polyline, with the unit direction there."""
    out, carry = [], 0.0
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-6:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        t = carry
        while t < L:
            out.append((x0 + ux * t, y0 + uy * t, ux, uy))
            t += step
        carry = t - L
    return out


# ---- planting ----------------------------------------------------------------------------------------------------
class Garden:
    def __init__(self, k, rng):
        self.k, self.r = k, rng

    def tree(self, x, y, h, kind="shade", bloom=None):
        k, r = self.k, self.r
        if kind == "willow":
            th = h * 0.55
            k.plant("Trunk", "Bark", BARK, x, y, 0, 0.42, 0.42, th, r.uniform(0, 360))
            k.plant("Puff", "Foliage", WILLOW, x, y, th + 0.6, h * 0.3, h * 0.3, h * 0.2, r.uniform(0, 360))
            for i in range(6):
                yaw = i * 60 + r.uniform(-15, 15)
                a = math.radians(yaw)
                d = h * 0.24
                k.plant("Fringe", "Foliage", WILLOW, x + d * math.cos(a), y + d * math.sin(a), th + 1.0, h * 0.2, 1.0,
                        th * 0.85, yaw + 90)
            return
        if kind == "birch":
            k.plant("Trunk", "Bark", BIRCH_BARK, x, y, 0, 0.2, 0.2, h * 0.75, r.uniform(0, 360))
            for i in range(3):
                s = h * r.uniform(0.11, 0.16)
                k.plant("Puff", "Foliage", LEAF[2], x + r.uniform(-0.6, 0.6), y + r.uniform(-0.6, 0.6),
                        h * (0.55 + 0.15 * i), s, s, s * 1.2, r.uniform(0, 360))
            return
        if kind == "conifer":
            k.plant("Trunk", "Bark", BARK, x, y, 0, 0.3, 0.3, h * 0.3)
            k.plant("Cone", "Foliage", LEAF[3], x, y, h * 0.15, h * 0.2, h * 0.2, h * 0.55, r.uniform(0, 360))
            k.plant("Cone", "Foliage", LEAF[3], x, y, h * 0.45, h * 0.14, h * 0.14, h * 0.55, r.uniform(0, 360))
            return
        crown = clamp(h * 0.4, 1.4, 4.2)
        th = h - crown * 0.8
        k.plant("Trunk", "Bark", BARK, x, y, 0, 0.4, 0.4, th, r.uniform(0, 360))
        leaf = r.choice(LEAF)
        for _i in range(4):
            a, rr = r.uniform(0, 6.28), r.uniform(0.35, 0.75) * crown
            c = bloom if (bloom and r.random() < 0.65) else leaf
            s = r.uniform(0.6, 0.8) * crown
            k.plant("Puff", "Foliage", c, x + rr * math.cos(a), y + rr * math.sin(a), th + r.uniform(-0.3, 0.5),
                    s, s, s * 0.62, r.uniform(0, 360))
        k.plant("Puff", "Foliage", bloom or leaf, x, y, th + crown * 0.3, crown * 0.72, crown * 0.72, crown * 0.5)
        if kind == "fruit":
            for _i in range(4):
                a = r.uniform(0, 6.28)
                k.plant("Blob", "Foliage", FRUIT, x + crown * 0.75 * math.cos(a), y + crown * 0.75 * math.sin(a),
                        th + r.uniform(-0.2, 0.6), 0.22, 0.22, 0.22, shadow=False)
        elif th > 4.5:
            a = r.uniform(0, 6.28)
            s = crown * 0.6
            k.plant("Puff", "Foliage", leaf, x + 0.4 * crown * math.cos(a), y + 0.4 * crown * math.sin(a), th * 0.75,
                    s, s, s * 0.55, r.uniform(0, 360))

    def shrub(self, x, y, s=1.0, bloom=None, z=0.0):
        k, r = self.k, self.r
        k.plant("Puff", "Foliage", r.choice(LEAF), x, y, z + 0.25 * s, 0.8 * s, 0.8 * s, 0.6 * s, r.uniform(0, 360))
        if bloom:
            k.plant("Blob", "Foliage", bloom, x, y, z + 0.65 * s, 0.45 * s, 0.45 * s, 0.22 * s, shadow=False)

    def reeds(self, x, y, s=1.0):
        r = self.r
        self.k.plant("Reed", "Foliage", r.choice(REED), x, y, 0, 3.2 * s, 3.2 * s, r.uniform(1.0, 1.7) * s,
                     r.uniform(0, 360), shadow=False)


# ======================================================================================================
# the castle playground
# ======================================================================================================
def draw_castle(k, S, x0, y0, w, d, rng, garden=None):
    """A Leathers-style community-built wooden castle playground in [x0, x0+w] x [y0, y0+d]; the gate faces y0."""
    g = garden or Garden(k, rng)
    T, SH = S.timber, S.shingle
    X = lambda f: x0 + w * f  # noqa: E731
    Y = lambda f: y0 + d * f  # noqa: E731
    # wood-chip ground with a timber edging
    k.box(S.mulch, x0, y0, 0, x0 + w, y0 + d, 0.07, skip=16)
    for (a, b) in (((x0, y0), (x0 + w, y0)), ((x0 + w, y0), (x0 + w, y0 + d)), ((x0 + w, y0 + d), (x0, y0 + d)), ((x0, y0 + d), (x0, y0))):
        k.beam(T, (a[0], a[1], 0.1), (b[0], b[1], 0.1), 0.25, 0.2)

    # towers: (name, cx, cy, size, deck, eave, top, roof)
    sc = clamp(min(w / 30.0, d / 24.0), 0.75, 1.15)
    towers = {
        "keep": (X(0.50), Y(0.58), 4.2 * sc, 2.6, 5.6, 10.4, "pyr"),
        "fl": (X(0.15), Y(0.30), 3.0 * sc, 1.8, 3.7, 8.4, "oct"),
        "fr": (X(0.84), Y(0.30), 3.0 * sc, 1.5, 3.4, 7.8, "pyr"),
        "bl": (X(0.17), Y(0.80), 3.2 * sc, 2.1, 4.0, 9.2, "pyr"),
        "br": (X(0.83), Y(0.80), 2.8 * sc, 1.8, 3.7, 7.6, "oct"),
        "gate": (X(0.36), Y(0.16), 2.2 * sc, 1.2, 3.0, 6.6, "oct"),
    }

    def tower(cx, cy, s, deck, eave, top, roof, second=None):
        h = s / 2
        cs = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
        for (px, py) in cs:
            post(k, T, px, py, 0, eave, 0.24)
        # board-clad body below the deck, a doorway on the gate (y0) side
        k.box(T, cx - h, cy + h - 0.06, 0.25, cx + h, cy + h, deck)
        k.box(T, cx - h, cy - h, 0.25, cx - h + 0.06, cy + h, deck)
        k.box(T, cx + h - 0.06, cy - h, 0.25, cx + h, cy + h, deck)
        k.box(T, cx - h, cy - h, 0.25, cx - 0.45, cy - h + 0.06, deck)
        k.box(T, cx + 0.45, cy - h, 0.25, cx + h, cy - h + 0.06, deck)
        k.box(T, cx - 0.45, cy - h, min(deck, 1.6), cx + 0.45, cy - h + 0.06, deck)
        # decks
        for z in [deck] + ([second] if second else []):
            k.box(T, cx - h - 0.1, cy - h - 0.1, z - 0.14, cx + h + 0.1, cy + h + 0.1, z)
            for i in range(4):
                pickets(k, T, cs[i], cs[(i + 1) % 4], z, z, 1.05, gap=0.24, castle=True)
        # eave band and the steep shingle spire
        k.box(T, cx - h - 0.15, cy - h - 0.15, eave - 0.3, cx + h + 0.15, cy + h + 0.15, eave)
        if roof == "pyr":
            pyramid(k, SH, cx, cy, eave, h + 0.3, top - eave)
        else:
            k.cyl(SH, cx, cy, eave, (h + 0.3) * 1.12, 0.0, top - eave, segs=8)
        k.pole(T, (cx, cy, top - 0.2), (cx, cy, top + 0.9), 0.05)
        k.box(S.red if rng.random() < 0.6 else S.white, cx + 0.05, cy - 0.02, top + 0.45, cx + 0.75, cy + 0.02, top + 0.85)
        k.solid(cx - h, cy - h, 0, cx + h, cy + h, deck + 1.1)

    for name, (cx, cy, s, deck, eave, top, roof) in towers.items():
        tower(cx, cy, s, deck, eave, top, roof, second=4.1 if name == "keep" else None)

    def walkway(a, b, za, zb, wd=1.4, solid_=True):
        """Deck on posts between two points (base heights za..zb), picket rails both sides."""
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy * wd / 2, ux * wd / 2
        k.beam(T, (a[0], a[1], za - 0.08), (b[0], b[1], zb - 0.08), wd, 0.16)
        n = max(1, int(L / 2.2))
        for i in range(n + 1):
            f = i / n
            x, y, z = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, za + (zb - za) * f
            for sgn in (-1, 1):
                post(k, T, x + nx * sgn, y + ny * sgn, 0, z, 0.16)
        for sgn in (-1, 1):
            pickets(k, T, (a[0] + nx * sgn, a[1] + ny * sgn), (b[0] + nx * sgn, b[1] + ny * sgn), za, zb, 0.95, gap=0.3)

    def rope_bridge(a, b, z, sag=0.5, wd=1.0):
        """Rope/chain bridge: sagging side chains and red/white rungs."""
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy * wd / 2, ux * wd / 2
        n = max(4, int(L / 0.32))
        zf = lambda f: z - sag * 4 * f * (1 - f)  # noqa: E731
        for i in range(1, n):
            f = i / n
            x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            k.beam(S.red if i % 2 else S.white, (x - nx, y - ny, zf(f)), (x + nx, y + ny, zf(f)), 0.14, 0.05)
        m = 6
        for sgn in (-1, 1):
            for j in range(m):
                f0, f1 = j / m, (j + 1) / m
                for dz in (0.0, 0.9):
                    k.pole(S.white if dz else T, (a[0] + (b[0] - a[0]) * f0 + nx * sgn, a[1] + (b[1] - a[1]) * f0 + ny * sgn, zf(f0) + dz),
                           (a[0] + (b[0] - a[0]) * f1 + nx * sgn, a[1] + (b[1] - a[1]) * f1 + ny * sgn, zf(f1) + dz), 0.035, 5)

    def edge(t, toward):
        """Point on tower t's side facing `toward` (2D)."""
        cx, cy, s = towers[t][0], towers[t][1], towers[t][2]
        dx, dy = toward[0] - cx, toward[1] - cy
        if abs(dx) > abs(dy):
            return (cx + math.copysign(s / 2 + 0.1, dx), cy)
        return (cx, cy + math.copysign(s / 2 + 0.1, dy))

    tw = lambda n: (towers[n][0], towers[n][1])  # noqa: E731
    # picket-fence ramparts on posts joining the towers
    walkway(edge("gate", tw("fl")), edge("fl", tw("gate")), towers["gate"][3], towers["fl"][3])
    walkway(edge("fl", tw("bl")), edge("bl", tw("fl")), towers["fl"][3], towers["bl"][3])
    walkway(edge("bl", tw("keep")), edge("keep", tw("bl")), towers["bl"][3], towers["keep"][3])
    walkway(edge("gate", tw("keep")), edge("keep", tw("gate")), towers["gate"][3], towers["keep"][3])
    walkway(edge("br", tw("fr")), edge("fr", tw("br")), towers["br"][3], towers["fr"][3])
    # rope bridge keep -> br, chain bridge between the back towers' level
    rope_bridge(edge("keep", tw("br")), edge("br", tw("keep")), (towers["keep"][3] + towers["br"][3]) / 2, sag=0.45)
    # green spiral tube slide off the front-right tower
    fx, fy, fs, fdeck = towers["fr"][0], towers["fr"][1], towers["fr"][2], towers["fr"][3]
    scx, scy = fx + fs / 2 + 1.5, fy - 0.6
    scx = min(scx, x0 + w - 1.6)
    k.pole(T, (scx, scy, 0), (scx, scy, fdeck + 1.4), 0.12)
    turns, nseg, R = 1.5, 22, 1.15
    a0 = math.atan2(fy - scy, (fx + fs / 2) - scx)
    prev = None
    for i in range(nseg + 1):
        f = i / nseg
        a = a0 - 2 * math.pi * turns * f
        p = (scx + R * math.cos(a), scy + R * math.sin(a), fdeck + 0.5 - (fdeck + 0.1) * f)
        if prev:
            k.pole(S.green, prev, p, 0.42, 10)
        prev = p
    k.pole(S.green, prev, (prev[0] - 0.9 * math.sin(a), prev[1] + 0.9 * math.cos(a), 0.35), 0.42, 10)
    # a silver-ish straight slide off the gate turret
    gx, gy, gs, gdeck = towers["gate"][0], towers["gate"][1], towers["gate"][2], towers["gate"][3]
    k.beam(S.white, (gx - gs / 2 - 0.1, gy, gdeck), (gx - gs / 2 - 0.1 - gdeck * 2.2, gy, 0.3), 0.8, 0.06)
    for sgn in (-1, 1):
        k.beam(T, (gx - gs / 2 - 0.1, gy + sgn * 0.42, gdeck + 0.25), (gx - gs / 2 - 0.1 - gdeck * 2.2, gy + sgn * 0.42, 0.5), 0.06, 0.25)
    # little wheelchair ramp to a low transfer deck beside the gate turret (1:12-ish)
    lz = 0.6
    rx1, ry = gx + gs / 2 + 0.2, gy - gs / 2 - 1.2
    rx0 = rx1 + 6.0
    rx0 = min(rx0, X(0.70))
    k.beam(T, (rx0, ry, 0.08), (rx1 + 1.6, ry, lz), 1.3, 0.12)
    k.box(T, rx1, ry - 0.9, lz - 0.14, rx1 + 1.6, ry + 0.9, lz)
    for (px, py) in ((rx1, ry - 0.9), (rx1 + 1.6, ry - 0.9), (rx1, ry + 0.9), (rx1 + 1.6, ry + 0.9)):
        post(k, T, px, py, 0, lz, 0.14)
    for sgn in (-1, 1):
        k.beam(T, (rx0, ry + sgn * 0.68, 0.95), (rx1 + 1.6, ry + sgn * 0.68, lz + 0.9), 0.07, 0.07)
        for f in (0.0, 0.5):
            px = rx0 + (rx1 + 1.6 - rx0) * f
            post(k, T, px, ry + sgn * 0.68, 0, 0.1 + (lz - 0.1) * f + 0.9, 0.1)
    # monkey bars and rings in the open back-middle yard
    mx0, mx1, my = X(0.32), X(0.62), Y(0.92) - 0.3
    mx1 = max(mx1, mx0 + 4.5)
    mb_end = mx0 + 4.4
    for x in (mx0, mb_end):
        for sgn in (-1, 1):
            post(k, T, x, my + sgn * 0.3, 0, 2.15, 0.14)
    for sgn in (-1, 1):
        k.beam(T, (mx0, my + sgn * 0.3, 2.15), (mb_end, my + sgn * 0.3, 2.15), 0.1, 0.1)
    n = int((mb_end - mx0) / 0.4)
    for i in range(1, n):
        x = mx0 + (mb_end - mx0) * i / n
        k.pole(S.red if i % 2 else S.white, (x, my - 0.3, 2.13), (x, my + 0.3, 2.13), 0.025, 5)
    # ring frame
    rx_0, rx_1 = mb_end + 1.2, min(mb_end + 5.0, X(0.68))
    if rx_1 - rx_0 > 2.0:
        for x in (rx_0, rx_1):
            post(k, T, x, my, 0, 2.6, 0.16)
        k.beam(T, (rx_0, my, 2.6), (rx_1, my, 2.6), 0.14, 0.14)
        for i in range(3):
            x = rx_0 + (rx_1 - rx_0) * (i + 1) / 4
            k.pole(S.white, (x, my, 2.55), (x, my, 1.75), 0.015, 4)
            k.ell(S.red, x, my, 1.62, 0.13, 0.025, 0.13, segs=10, rings=4)
    # perimeter picket fence with a gate gap facing y0
    gate0, gate1 = X(0.44), X(0.56)
    pickets(k, T, (x0 + 0.3, y0 + 0.3), (gate0, y0 + 0.3), 0, 0, 1.0, gap=0.32)
    pickets(k, T, (gate1, y0 + 0.3), (x0 + w - 0.3, y0 + 0.3), 0, 0, 1.0, gap=0.32)
    pickets(k, T, (x0 + w - 0.3, y0 + 0.3), (x0 + w - 0.3, y0 + d - 0.3), 0, 0, 1.0, gap=0.32)
    pickets(k, T, (x0 + w - 0.3, y0 + d - 0.3), (x0 + 0.3, y0 + d - 0.3), 0, 0, 1.0, gap=0.32)
    pickets(k, T, (x0 + 0.3, y0 + d - 0.3), (x0 + 0.3, y0 + 0.3), 0, 0, 1.0, gap=0.32)
    for gx_ in (gate0, gate1):
        post(k, T, gx_, y0 + 0.3, 0, 2.4, 0.28)
        k.cyl(SH, gx_, y0 + 0.3, 2.4, 0.32, 0.0, 0.9, segs=4)
    # parents' benches inside the gate and a few shrubs along the fence
    for f in (0.25, 0.75):
        bx = X(f)
        k.box(T, bx - 1.0, y0 + 1.0, 0.42, bx + 1.0, y0 + 1.45, 0.5)
        post(k, T, bx - 0.8, y0 + 1.22, 0, 0.42, 0.12)
        post(k, T, bx + 0.8, y0 + 1.22, 0, 0.42, 0.12)
    for i in range(10):
        f = (i + 0.5) / 10
        g.shrub(x0 + w * f, y0 + d + 0.6, rng.uniform(0.8, 1.2), bloom=CHERRY if i % 3 == 0 else None)
    return [(x0, y0, x0 + w, y0 + d)]


def castle_playground(plot):
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    S = Slots(k)
    k.box(S.lawn, 0, 0, 0, plot.w, plot.d, 0.04, skip=16)
    m = 0.8
    draw_castle(k, S, m, m, plot.w - 2 * m, plot.d - 2 * m - 0.6, rng)
    return k


# ======================================================================================================
# the central park
# ======================================================================================================
def solar_tree(k, S, x, y, h, rng):
    """A sculptural solar tree: a tapering white trunk forking into branches that each hold a hexagonal PV leaf."""
    k.cyl(S.white, x, y, 0, 0.42, 0.2, h * 0.62, segs=10)
    nb = 5
    a0 = rng.uniform(0, 360)
    for i in range(nb):
        a = math.radians(a0 + i * 360 / nb + rng.uniform(-14, 14))
        rr = rng.uniform(1.6, 2.8) * h / 9
        zl = h * rng.uniform(0.78, 1.0)
        lx, ly = x + rr * math.cos(a), y + rr * math.sin(a)
        k.pole(S.white, (x, y, h * 0.58), (lx, ly, zl - 0.1), 0.09, 6)
        r = rng.uniform(1.3, 1.9) * h / 9
        hexp = [(lx + r * math.cos(math.radians(60 * j + 30)), ly + r * math.sin(math.radians(60 * j + 30))) for j in range(6)]
        k.prism(S.pv, hexp, zl, zl + 0.08, bottom=True)
        k.cyl(S.white, lx, ly, zl - 0.06, r * 1.04, r * 1.04, 0.06, segs=6)
    # crown leaf
    r = 1.8 * h / 9
    hexp = [(x + r * math.cos(math.radians(60 * j)), y + r * math.sin(math.radians(60 * j))) for j in range(6)]
    k.pole(S.white, (x, y, h * 0.6), (x, y, h * 1.08), 0.12, 6)
    k.prism(S.pv, hexp, h * 1.1, h * 1.1 + 0.08, bottom=True)
    k.cyl(S.white, x, y, h * 1.1 - 0.06, r * 1.04, r * 1.04, 0.06, segs=6)
    k.solid(x - 0.5, y - 0.5, 0, x + 0.5, y + 0.5, 3)


def wind_sculpture(k, S, x, y, z, h, rng):
    """A vertical-axis wind sculpture: a mast with three twisted white blades."""
    k.pole(S.white, (x, y, z), (x, y, z + h), 0.08, 6)
    a0 = rng.uniform(0, 360)
    for b in range(3):
        pts = []
        for j in range(7):
            f = j / 6
            a = math.radians(a0 + b * 120 + 70 * f)
            pts.append((x + 0.9 * math.cos(a), y + 0.9 * math.sin(a), z + h * 0.3 + h * 0.65 * f))
        for j in range(6):
            k.pole(S.white if b else S.red, pts[j], pts[j + 1], 0.07, 4)
    k.cyl(S.stone, x, y, z, 0.5, 0.4, 0.4, segs=8)


def seed_dome(k, S, x, y, R):
    k.cyl(S.stone, x, y, 0, R + 0.8, R + 0.8, 0.4, segs=28)
    k.ell(S.dome, x, y, 0.4, R, R, R * 0.82, segs=24, rings=8, hemi=True)
    # meridian ribs and two rings
    for i in range(8):
        a = math.radians(i * 45)
        prev = None
        for j in range(7):
            ph = (math.pi / 2) * j / 6
            p = (x + R * 1.01 * math.cos(ph) * math.cos(a), y + R * 1.01 * math.cos(ph) * math.sin(a), 0.4 + R * 0.83 * math.sin(ph))
            if prev:
                k.pole(S.white, prev, p, 0.07, 4)
            prev = p
    for ph in (0.45, 0.9):
        rr, z = R * 1.01 * math.cos(ph), 0.4 + R * 0.83 * math.sin(ph)
        pts = [(x + rr * math.cos(2 * math.pi * j / 20), y + rr * math.sin(2 * math.pi * j / 20), z) for j in range(21)]
        for j in range(20):
            k.pole(S.white, pts[j], pts[j + 1], 0.06, 4)
    # an entrance vestibule facing -y
    k.vault(S.white, x - 1.4, y - R - 1.2, 0.4, x + 1.4, y - R * 0.7, 2.6, 0.9, axis_x=False, t=0.12, segs=8)
    k.box(S.dome, x - 1.1, y - R - 1.25, 0.4, x + 1.1, y - R - 1.1, 2.5)
    k.solid(x - R, y - R, 0, x + R, y + R, R * 0.8)


def central_park(plot):
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    S = Slots(k)
    g = Garden(k, rng)
    W, D = plot.w, plot.d
    sx, sy = W / 136.0, D / 112.0
    s = min(sx, sy)
    P = lambda u, v: (u * sx, v * sy)  # noqa: E731  design coords (136 x 112 m) -> plot
    taken = []  # (x, y, r) discs where trees must not go

    def free(x, y, r=0.0):
        return all((x - a) ** 2 + (y - b) ** 2 > (r + c) ** 2 for a, b, c in taken) and 1.5 < x < W - 1.5 and 1.5 < y < D - 1.5

    # ground
    k.box(S.lawn, 0, 0, 0, W, D, 0.04, skip=16)

    # ---- the castle playground (back west corner, gate facing the park) ------------------------------------------
    cw, cd = clamp(32 * sx, 24, 34), clamp(24 * sy, 18, 26)
    cx0, cy0 = W - cw - 2.0, D - cd - 7.5
    draw_castle(k, S, cx0, cy0, cw, cd, rng, g)
    taken.append((cx0 + cw / 2, cy0 + cd / 2, math.hypot(cw, cd) / 2 + 1.5))

    # ---- school forecourt along the back edge (the school's main door is on the axis) ----------------------------
    fy0 = D - 6.0
    k.box(S.stone, 3.0, fy0, 0.0, W - 3.0, D - 0.5, 0.08)
    for i in range(9):
        x = 8 + (W - 16) * i / 8
        k.cyl(S.timber, x, fy0 + 2.8, 0.0, 1.1, 1.1, 0.5, segs=10)
        g.tree(x, fy0 + 2.8, rng.uniform(7, 9), bloom=CHERRY)
        taken.append((x, fy0 + 2.8, 3.5))

    # ---- wetland: a meandering bioswale from the school roofs down to a reed pond ---------------------------------
    pcx, pcy = P(26, 40)
    prx, pry = 17 * s, 13 * s
    marsh = blob_poly(pcx, pcy, prx + 3.5, pry + 3.5, rng, n=20)
    pond = blob_poly(pcx, pcy, prx, pry, rng, n=20, jit=0.14)
    k.prism(S.marsh, marsh, 0.0, 0.06)
    k.prism(S.water, pond, 0.0, 0.1)
    # small island with a willow
    ix, iy = pcx + prx * 0.35, pcy - pry * 0.1
    k.prism(S.marsh, blob_poly(ix, iy, 2.6, 2.0, rng, n=10), 0.0, 0.16)
    g.tree(ix, iy, 8, kind="willow")
    swale = smooth([P(14, 106), P(22, 96), P(12, 84), P(20, 70), P(16, 60), (pcx - prx * 0.3, pcy + pry * 0.8)], 5)
    k.ribbon(S.marsh, swale, 5.0, 0.0, 0.06)
    k.ribbon(S.water, swale, 2.2, 0.0, 0.1)
    outflow = smooth([(pcx + prx * 0.6, pcy - pry * 0.7), P(48, 18), P(40, 8), P(46, 0.6)], 5)
    k.ribbon(S.marsh, outflow, 4.0, 0.0, 0.06)
    k.ribbon(S.water, outflow, 1.6, 0.0, 0.1)
    # stepping-stone weirs in the swale
    for (x, y, ux, uy) in along(swale, 9.0)[1:]:
        for j in (-1, 0, 1):
            k.plant("Stone", "PermeableStone", STONE, x - uy * 0.7 * j, y + ux * 0.7 * j, 0.0, 0.35, 0.3, 0.2, rng.uniform(0, 360))
    # reeds round the margins and along the swale, lily pads on the water
    for _i, (x, y) in enumerate(marsh):
        for _j in range(4):
            g.reeds(x + rng.uniform(-1.6, 1.6), y + rng.uniform(-1.6, 1.6), rng.uniform(0.8, 1.2))
    for (x, y, ux, uy) in along(swale, 1.4) + along(outflow, 1.4):
        side = rng.choice((-1, 1))
        g.reeds(x - uy * side * rng.uniform(1.3, 2.2), y + ux * side * rng.uniform(1.3, 2.2), rng.uniform(0.7, 1.0))
    for _i in range(26):
        a, rr = rng.uniform(0, 6.28), rng.uniform(0.2, 0.75)
        k.plant("Disc", "Foliage", LILY, pcx + prx * rr * math.cos(a), pcy + pry * rr * math.sin(a), 0.11, 0.6, 0.6, 0.02,
                rng.uniform(0, 360), shadow=False)
    for _i in range(10):
        a, rr = rng.uniform(0, 6.28), rng.uniform(0.2, 0.7)
        k.plant("Blob", "Foliage", BANDS[3], pcx + prx * rr * math.cos(a), pcy + pry * rr * math.sin(a), 0.14, 0.18, 0.18,
                0.08, shadow=False)
    taken.append((pcx, pcy, max(prx, pry) + 2.0))
    # zig-zag boardwalk across the wetland
    bw = [(pcx - prx - 4, pcy - pry * 0.2), (pcx - prx * 0.4, pcy + pry * 0.45), (pcx + prx * 0.1, pcy - pry * 0.35),
          (pcx + prx * 0.6, pcy + pry * 0.3), (pcx + prx + 5, pcy + pry * 0.05)]
    k.ribbon(S.timber, bw, 2.2, 0.35, 0.5)
    for (x, y, ux, uy) in along(bw, 2.4):
        for sgn in (-1, 1):
            k.box(S.timber, x - uy * 1.05 * sgn - 0.08, y + ux * 1.05 * sgn - 0.08, 0.0, x - uy * 1.05 * sgn + 0.08,
                  y + ux * 1.05 * sgn + 0.08, 1.45 if sgn > 0 else 0.5)
    k.ribbon(S.timber, bw, 0.1, 1.35, 1.45, offset=1.05)
    # willows and alders by the water
    for (u, v, kind) in ((6, 22, "willow"), (8, 58, "willow"), (44, 30, "willow"), (40, 56, "birch"), (34, 60, "birch"),
                         (4, 40, "birch"), (30, 16, "willow"), (12, 12, "birch")):
        x, y = P(u, v)
        if free(x, y, 1.0):
            g.tree(x, y, rng.uniform(8, 11), kind=kind)
            taken.append((x, y, 3.0))

    # ---- glass seed dome by the swale -------------------------------------------------------------------------
    dx, dy = P(36, 84)
    dR = 7.5 * s
    seed_dome(k, S, dx, dy, dR)
    taken.append((dx, dy, dR + 2.0))
    for i in range(14):
        a = math.radians(-60 + i * 300 / 13)
        g.shrub(dx + (dR + 1.6) * math.cos(a), dy + (dR + 1.6) * math.sin(a), rng.uniform(0.8, 1.2),
                bloom=BANDS[i % 3] if i % 2 else None)

    # ---- solar-tree grove round a stage plaza on the central axis, the great lawn and its terraced bowl -------------
    sgx, sgy = 66 * sx, 55 * sy
    k.cyl(S.stone, sgx, sgy, 0.0, 10.5 * s, 10.5 * s, 0.08, segs=36)
    k.cyl(S.timber, sgx, sgy, 0.0, 4.2 * s, 4.2 * s, 0.6, segs=24)  # round timber stage
    k.cyl(S.path, sgx, sgy, 0.0, 10.5 * s + 1.4, 10.5 * s + 1.4, 0.05, segs=36)
    for i in range(6):
        a = math.radians(90 + 30 + i * 60)
        solar_tree(k, S, sgx + 8.0 * s * math.cos(a), sgy + 8.0 * s * math.sin(a), rng.uniform(8.0, 9.6), rng)
    # benches round the plaza
    for i in range(12):
        a = math.radians(i * 30 + 15)
        bx, by = sgx + 9.6 * s * math.cos(a), sgy + 9.6 * s * math.sin(a)
        k.obox(S.timber, bx, by, 0.45, 0.25, 0.9, 0.05, 0, math.degrees(a), 0)
        k.obox(S.stone, bx, by, 0.2, 0.18, 0.7, 0.2, 0, math.degrees(a), 0)
    taken.append((sgx, sgy, 12.5 * s))
    # great lawn bowl: grass terraces arc round the west side, facing the stage
    r0, nt, step, rise = 24 * s, 6, 1.8 * s, 0.42
    a_lo, a_hi = -45, 45
    for i in range(nt):
        r = r0 + step * (i + 0.5)
        z = rise * (i + 1)
        pts = arc(sgx, sgy, r, a_lo, a_hi, 20)
        k.ribbon(S.mound, pts, step + 0.05, 0.0, z)
        k.ribbon(S.stone, arc(sgx, sgy, r - step / 2 + 0.25, a_lo, a_hi, 20), 0.5, 0.0, z + 0.04)
    # crest path and the bowl's back slope
    H = rise * nt
    rc = r0 + step * nt + 1.5
    k.ribbon(S.path, arc(sgx, sgy, rc, a_lo, a_hi, 22), 3.0, 0.0, H + 0.05)
    # the back slope steps down in grass terraces to the ground
    nb = 3
    for i in range(nb):
        k.ribbon(S.mound, arc(sgx, sgy, rc + 1.5 + 1.4 * (i + 0.5), a_lo, a_hi, 20), 1.45, 0.0, H * (nb - i) / (nb + 1))
    # ramps from the crest walk down at both ends (tangent to the arc)
    feet = []
    for aa, sg in ((a_lo, -1), (a_hi, 1)):
        a = math.radians(aa)
        p = (sgx + rc * math.cos(a), sgy + rc * math.sin(a))
        t = (-math.sin(a) * sg, math.cos(a) * sg)
        L = H * 4.0
        feet.append((p[0] + t[0] * (L + 1.0), p[1] + t[1] * (L + 1.0)))
        k.beam(S.path, (p[0], p[1], H - 0.1), (p[0] + t[0] * L, p[1] + t[1] * L, -0.1), 3.0, 0.3)
        for j in range(4):
            f = (j + 0.5) / 4
            q = (p[0] + t[0] * L * f, p[1] + t[1] * L * f)
            k.obox(S.mound, q[0], q[1], (H - 0.15) * (1 - f) / 2, 1.45, L / 8 + 0.05,
                   (H - 0.15) * (1 - f) / 2, 0, aa, 0)
    # aisles through the terraces
    for aa in (-26, 0, 26):
        for i in range(nt):
            r = r0 + step * (i + 0.5)
            a = math.radians(aa)
            k.obox(S.stone, sgx + r * math.cos(a), sgy + r * math.sin(a), rise * (i + 1) / 2 + 0.02, step / 2 + 0.05, 0.8,
                   rise * (i + 1) / 2 + 0.02, 0, aa, 0)
    # wind sculptures on the back slope
    for aa in (-38, -13, 13, 38):
        a = math.radians(aa)
        rr = rc + 1.5 + 1.4 * 0.5
        wind_sculpture(k, S, sgx + rr * math.cos(a), sgy + rr * math.sin(a), H * nb / (nb + 1), 7.5 * s, rng)
    # keep trees off the bowl and the lawn
    lawn_r = rc + 1.5 + 1.4 * nb + 0.5

    def in_bowl(x, y, pad=0.0):
        dxx, dyy = x - sgx, y - sgy
        r = math.hypot(dxx, dyy)
        a = math.degrees(math.atan2(dyy, dxx))
        return (r < lawn_r + pad and a_lo - 8 < a < a_hi + 8) or r < r0 + pad

    # ---- pollinator meadows in colour bands (front, both sides of the axis) -----------------------------------
    for side, (u0, u1) in enumerate(((50, 62), (76, 130))):
        for b in range(4):
            v = 6.5 + b * 3.9
            pts = smooth([P(u0, v + 1.5), P((u0 + u1) / 2, v - 1.2), P(u1, v + 1.0)], 6)
            k.ribbon(S.meadow, pts, 3.4 * sy, 0.0, 0.07)
            col = BANDS[(b + side) % 4]
            for (x, y, ux, uy) in along(pts, 1.25 if side else 1.4):
                for j in (-1, 1):
                    off = j * rng.uniform(0.3, 1.2) * sy
                    k.plant("Blob", "Foliage", col, x - uy * off, y + ux * off, 0.2, 0.55, 0.55, 0.32, rng.uniform(0, 360),
                            shadow=False)
                if rng.random() < 0.2:
                    k.plant("Puff", "Foliage", LEAF[2], x, y, 0.15, 0.45, 0.45, 0.35, shadow=False)

    # ---- food-forest edge along the west side ------------------------------------------------------------------
    for i in range(16):
        y = 6 + (cy0 - 10) * i / 15
        for x in (W - 7.0, W - 12.0):
            x2, y2 = x + rng.uniform(-1, 1), y + rng.uniform(-1, 1) + (2.5 if x < W - 9 else 0)
            if free(x2, y2, 1.5) and not in_bowl(x2, y2, 1.0):
                g.tree(x2, y2, rng.uniform(5.0, 7.5), kind="fruit" if rng.random() < 0.7 else "shade",
                       bloom=CHERRY if rng.random() < 0.2 else None)
                g.shrub(x2 + rng.uniform(-2, 2), y2 + rng.uniform(-2, 2), rng.uniform(0.7, 1.0), bloom=FRUIT if rng.random() < 0.3 else None)
                taken.append((x2, y2, 3.2))

    # ---- paths ---------------------------------------------------------------------------------------------
    paths = [
        # the central promenade: front gate - stage plaza - school door
        smooth([P(68, 0), P(64, 14), P(68, 30), (sgx, sgy - 10.5 * s - 1.0)], 5),
        smooth([(sgx, sgy + 10.5 * s + 1.0), P(72, 72), P(66, 88), P(68, 106)], 5),
        # perimeter loop (east, back and west), with a pond-side path
        smooth([P(3.5, 2), P(3.0, 30), P(5, 64), P(4, 90), P(10, 104)], 5),
        smooth([P(130, 1), P(133, 30), P(131, 52), (W - 4.0, cy0 - 6), (cx0 + cw * 0.5, cy0 - 0.2)], 5),
        # east: SE entrance - boardwalk; boardwalk - dome - forecourt
        smooth([P(22, 0), P(20, 10), bw[0]], 4),
        smooth([bw[-1], P(54, 47), P(52, 64), P(46, 74), (dx + dR * 0.2, dy - dR - 1.5)], 5),
        smooth([(dx + dR + 1.0, dy + 1), P(54, 94), P(62, 104)], 4),
        # west: SW entrance through the meadow - crest of the bowl - castle gate
        smooth([P(116, 0), P(112, 12), feet[0]], 5),
        smooth([feet[1], P(90, 96), P(94, 106)], 5),
        # across the front, between the meadow bands and the lane
        smooth([P(22, 3), P(46, 3.5), P(68, 2.5), P(96, 3.5), P(116, 3)], 4),
    ]
    for pts in paths:
        k.ribbon(S.path, pts, 3.0, 0.0, 0.08)
    # lantern-free: benches along the promenade
    for pts in paths[:2]:
        for (x, y, ux, uy) in along(pts, 11.0)[1:]:
            bx, by = x - uy * 2.4, y + ux * 2.4
            k.obox(S.timber, bx, by, 0.45, 0.9, 0.25, 0.05, 0, math.degrees(math.atan2(uy, ux)), 0)

    # ---- trees: a shade grove frame round everything left open ----------------------------------------------------
    pathpts = [(x, y) for pts in paths for (x, y, _, _) in along(pts, 2.0)]

    def near_path(x, y, r):
        return any((x - a) ** 2 + (y - b) ** 2 < r * r for a, b in pathpts)

    def ok(x, y, r=2.5):
        return free(x, y, r) and not in_bowl(x, y, 2.0) and not near_path(x, y, 2.6) and not (y < 30 * sy and 46 * sx < x < 132 * sx)

    # an allee of jacarandas along the front promenade, plane trees on to the school, a ring of oaks behind the bowl
    for n, pts in enumerate(paths[:2]):
        for (x, y, ux, uy) in along(pts, 8.5)[1:]:
            for sg in (-1, 1):
                tx, ty = x - uy * 4.6 * sg, y + ux * 4.6 * sg
                if free(tx, ty, 2.0) and not in_bowl(tx, ty, 0.5):
                    g.tree(tx, ty, rng.uniform(8.5, 10), bloom=JACARANDA if n == 0 else None)
                    taken.append((tx, ty, 3.5))
    for i in range(15):
        aa = a_lo - 10 + (a_hi - a_lo + 20) * i / 14
        a = math.radians(aa)
        tx, ty = sgx + (lawn_r + 3.5) * math.cos(a), sgy + (lawn_r + 3.5) * math.sin(a)
        if free(tx, ty, 2.0) and not near_path(tx, ty, 2.4):
            g.tree(tx, ty, rng.uniform(10, 13))
            taken.append((tx, ty, 4.0))
    placed = 0
    for _ in range(1600):
        if placed >= 60:
            break
        # bias towards the edges and the bowl rim so the middle reads as open lawn and water
        x, y = rng.uniform(2, W - 2), rng.uniform(2, D - 7)
        edge = min(x, W - x, y, D - y)
        rim = abs(math.hypot(x - sgx, y - sgy) - (lawn_r + 4)) < 5
        if edge > 18 and not rim and rng.random() < 0.75:
            continue
        if not ok(x, y, 3.0):
            continue
        b = rng.choice((None, None, None, CHERRY, JACARANDA))
        kind = rng.choice(("shade", "shade", "shade", "conifer", "birch"))
        g.tree(x, y, rng.uniform(8, 13) if kind == "shade" else rng.uniform(7, 10), kind=kind, bloom=b)
        taken.append((x, y, 4.5))
        placed += 1
    # understorey shrubs
    for _ in range(140):
        x, y = rng.uniform(2, W - 2), rng.uniform(2, D - 7)
        if free(x, y, 0.5) and not in_bowl(x, y, 1.0) and not near_path(x, y, 2.0) and not (y < 30 * sy and 46 * sx < x < 132 * sx):
            if min(x, W - x, D - y) < 14 or rng.random() < 0.25:
                g.shrub(x, y, rng.uniform(0.7, 1.3), bloom=rng.choice((None, CHERRY, BANDS[0], BANDS[1])))
    return k


KINDS = {"castle_playground": castle_playground, "central_park": central_park}
SIZES = {
    "castle_playground": {"w": (22, 36), "d": (18, 30), "h": (8, 12), "floors": (0, 1), "use": "playground"},
    "central_park": {"w": (110, 150), "d": (90, 125), "h": (10, 14), "floors": (0, 1), "use": "park"},
}
