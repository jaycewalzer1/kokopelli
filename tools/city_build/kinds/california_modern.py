"""California modern houses re-imagined for a lush solarpunk village.

    stahl_house      Pierre Koenig, Stahl House (Case Study House #22), Los Angeles 1960
    kaufmann_desert  Richard Neutra, Kaufmann Desert House, Palm Springs 1946
    butterfly_row    William Krisel / Alexander Construction Co., Palm Springs butterfly-roof houses, 1957-62
    eichler_court    Joseph Eichler (Anshen + Allen, Jones & Emmons) tract homes, 1950-66

Frame (kit.py): x along the street 0..w, y away from the street 0..d (front line y = 0), z up, metres.
Every kind is deterministic from plot.seed and takes its accent colours from plot.palette.
"""
import colorsys
import math

from .kit import Kit, WHITE, DARK_STEEL, GLASS, TERRAZZO, TEAK, LEAF, FLOWER

LAMP = (255, 190, 112)
DIM = (138, 108, 78)
LAWN = (112, 158, 70)
WATER = (64, 160, 196)
POOL_TILE = (120, 196, 214)
PV = (44, 56, 78)
SAND = (214, 196, 160)
SANDSTONE = (196, 168, 126)
ALU = (200, 202, 204)
PALM_LEAF = ((70, 112, 52), (86, 126, 58), (60, 98, 48))
AGAVE = ((96, 132, 108), (84, 120, 96), (110, 140, 116))
JACARANDA = (150, 112, 206)
BOUGAINVILLEA = (214, 62, 132)
# Palm Springs door / accent colours (bright, one per house)
PS_BRIGHT = ((40, 176, 186), (246, 132, 40), (246, 204, 52), (236, 104, 150), (126, 196, 86), (52, 120, 200),
             (220, 70, 60), (150, 210, 200))


def clamp(v, a, b):
    return max(a, min(b, v))


def lerp(a, b, t):
    return a + (b - a) * t


def vivid(rgb, s_min=0.68, v_min=0.88):
    """A palette colour pushed bright enough to read as a mid-century accent."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb(h, max(s, s_min), max(v, v_min))
    return (int(r * 255), int(g * 255), int(b * 255))


def mix(a, b, t):
    return tuple(int(round(lerp(x, y, t))) for x, y in zip(a, b, strict=False))


class Ctx:
    """Kit + rng + lazily created shared slots for one building."""

    def __init__(self, plot):
        self.p = plot
        self.k = Kit(plot.w, plot.d)
        self.r = plot.rng          # plot.rng makes a fresh Random each access: take it once
        self.w, self.d = float(plot.w), float(plot.d)
        pal = list(plot.palette) if plot.palette else [(236, 226, 200), (150, 168, 128), (190, 156, 82)]
        self.pal = [tuple(int(v) for v in c) for c in pal] + [(190, 156, 82)] * (3 - len(pal))
        self._m = {}

    def m(self, name, mat, tint, scale=0.0):
        if name not in self._m:
            self._m[name] = self.k.mat(mat, tint, scale)
        return self._m[name]

    # common slots
    @property
    def glass(self):
        return self.m("glass", "SolarGlass", GLASS, 320.0)

    @property
    def mull(self):
        return self.m("mull", "Metal", DARK_STEEL)

    @property
    def dim(self):
        return self.m("dim", "Plain", DIM)

    @property
    def lamp(self):
        return self.m("lamp", "Lantern", LAMP)

    @property
    def lawn(self):
        return self.m("lawn", "GreenRoof", LAWN)

    @property
    def water(self):
        return self.m("water", "Water", WATER)

    @property
    def pv(self):
        return self.m("pv", "SolarGlass", PV)

    # ---- building pieces ------------------------------------------------------------------------------
    def glaze(self, axis, a0, a1, at, z0, z1, bay=2.4, p_open=0.0, p_lit=0.3, frame=None, t=0.05, sill=0.06):
        """Floor-to-ceiling glazing on a line: axis 'x' runs along x at y=at, 'y' along y at x=at.
        Bays are glass or left open (a slid-back panel showing the lit room behind: SolarGlass is opaque).
        p_lit is kept for call compatibility and ignored (tinted/emissive panes read as solid panels)."""
        k, r = self.k, self.r
        fr = self.mull if frame is None else frame
        L = a1 - a0
        n = max(1, int(round(L / bay)))
        bw = L / n
        opened = []
        for i in range(n):
            b0, b1 = a0 + i * bw, a0 + (i + 1) * bw
            u = r.random()
            if u < p_open:
                opened.append((b0, b1))
                continue
            s = self.glass
            if axis == "x":
                k.box(s, b0, at - t / 2, z0, b1, at + t / 2, z1)
            else:
                k.box(s, at - t / 2, b0, z0, at + t / 2, b1, z1)
        mw = 0.07
        for i in range(n + 1):
            a = a0 + i * bw
            if axis == "x":
                k.box(fr, a - mw / 2, at - 0.06, z0, a + mw / 2, at + 0.06, z1)
            else:
                k.box(fr, at - 0.06, a - mw / 2, z0, at + 0.06, a + mw / 2, z1)
        # head and sill rails
        for zz0, zz1 in ((z0, z0 + sill), (z1 - 0.08, z1)):
            if axis == "x":
                k.box(fr, a0, at - 0.06, zz0, a1, at + 0.06, zz1)
            else:
                k.box(fr, at - 0.06, a0, zz0, at + 0.06, a1, zz1)
        return opened

    def interior(self, x0, y0, x1, y1, z0, z1, back="y1", n_lamps=None, sofa=None):
        """What a lit room looks like through glass: a dim back wall, pendant lanterns, a sofa, a rug."""
        k, r = self.k, self.r
        e = 0.18
        if back == "y1":
            k.box(self.dim, x0 + e, y1 - e - 0.05, z0, x1 - e, y1 - e, z1)
        elif back == "y0":
            k.box(self.dim, x0 + e, y0 + e, z0, x1 - e, y0 + e + 0.05, z1)
        elif back == "x0":
            k.box(self.dim, x0 + e, y0 + e, z0, x0 + e + 0.05, y1 - e, z1)
        else:
            k.box(self.dim, x1 - e - 0.05, y0 + e, z0, x1 - e, y1 - e, z1)
        area = (x1 - x0) * (y1 - y0)
        n = n_lamps if n_lamps is not None else clamp(int(area / 16), 1, 5)
        for i in range(n):
            lx = lerp(x0 + 1.0, x1 - 1.0, (i + 0.5) / n) if (x1 - x0) >= (y1 - y0) else lerp(x0 + 1, x1 - 1, r.random())
            ly = lerp(y0 + 1.0, y1 - 1.0, r.random()) if (x1 - x0) >= (y1 - y0) else lerp(y0 + 1, y1 - 1, (i + 0.5) / n)
            lz = z1 - r.uniform(0.7, 1.0)
            k.box(self.lamp, lx - 0.22, ly - 0.22, lz, lx + 0.22, ly + 0.22, lz + 0.26)
            k.box(self.mull, lx - 0.01, ly - 0.01, lz + 0.26, lx + 0.01, ly + 0.01, z1)
        if sofa is not None and x1 - x0 > 3 and y1 - y0 > 3:
            sx, sy = lerp(x0, x1, r.uniform(0.3, 0.7)), lerp(y0, y1, r.uniform(0.35, 0.65))
            yaw = r.choice((0, 90))
            k.plant("Cube", "Fabric", sofa, sx, sy, z0 + 0.22, 2.2, 0.9, 0.44, yaw)
            k.plant("Cube", "Fabric", mix(sofa, (240, 230, 210), 0.6), sx + 1.6, sy + 0.4, z0 + 0.03, 2.4, 1.8, 0.03, yaw)
            k.plant("Cube", "Lantern", LAMP, sx - 1.5, sy, z0 + 0.8, 0.35, 0.35, 0.45)
            k.plant("Cylinder", "Metal", DARK_STEEL, sx - 1.5, sy, z0, 0.04, 0.04, 0.58)

    def pv_rows(self, x0, y0, x1, y1, z, tilt=8.0, row=1.8, gap=0.5, frame=None):
        """Low-tilt PV rows on a flat roof, panels sloping to the street side (y0)."""
        k = self.k
        y = y0
        frame = frame if frame is not None else self.m("pvframe", "Metal", ALU)
        while y + row <= y1 + 0.01:
            dz = math.sin(math.radians(tilt)) * row
            k.slope(self.pv, x0, y, x1, y + row, z + 0.12, z + 0.12 + dz, t=0.05)
            k.box(frame, x0, y + row - 0.08, z, x1, y + row, z + 0.12 + dz)
            y += row + gap

    def pool(self, x0, y0, x1, y1, ztop, coping, depth=0.14, tile=None):
        """A pool sunk into a deck that is built AROUND it: water surface below the coping top."""
        k = self.k
        cp = 0.45
        k.box(self.water, x0, y0, ztop - depth - 0.02, x1, y1, ztop - depth)
        tile = tile if tile is not None else self.m("pooltile", "Plain", POOL_TILE)
        k.box(tile, x0, y0, 0, x1, y1, ztop - depth - 0.02)
        # coping ring
        k.box(coping, x0 - cp, y0 - cp, 0, x1 + cp, y0, ztop + 0.02)
        k.box(coping, x0 - cp, y1, 0, x1 + cp, y1 + cp, ztop + 0.02)
        k.box(coping, x0 - cp, y0, 0, x0, y1, ztop + 0.02)
        k.box(coping, x1, y0, 0, x1 + cp, y1, ztop + 0.02)

    # ---- planting -------------------------------------------------------------------------------------
    def lawn_patch(self, x0, y0, x1, y1, z=0.0):
        if x1 - x0 > 0.3 and y1 - y0 > 0.3:
            self.k.box(self.lawn, x0, y0, z, x1, y1, z + 0.04)

    def shrub(self, x, y, s=1.0, z=0.0, bloom=0.45, col=None):
        k, r = self.k, self.r
        k.plant("Puff", "Foliage", r.choice(LEAF), x, y, z + 0.25 * s, 0.75 * s, 0.75 * s, 0.6 * s, r.uniform(0, 360))
        if r.random() < bloom:
            c = col or r.choice(FLOWER)
            for _ in range(r.randint(2, 4)):
                a, rr = r.uniform(0, 6.28), r.uniform(0.1, 0.45) * s
                k.plant("Blob", "Foliage", c, x + rr * math.cos(a), y + rr * math.sin(a), z + 0.75 * s,
                        0.2 * s, 0.2 * s, 0.14 * s, shadow=False)

    def flowerbed(self, x0, y0, x1, y1, n=None, z=0.0, cols=None):
        k, r = self.k, self.r
        area = max(0.0, (x1 - x0) * (y1 - y0))
        n = n if n is not None else int(clamp(area * 0.9, 2, 40))
        for _ in range(n):
            x, y = r.uniform(x0, x1), r.uniform(y0, y1)
            if r.random() < 0.45:
                self.shrub(x, y, r.uniform(0.6, 1.1), z=z, bloom=0.7)
            else:
                c = r.choice(cols or FLOWER)
                k.plant("Blob", "Foliage", r.choice(LEAF), x, y, z + 0.1, 0.32, 0.32, 0.22, r.uniform(0, 360), shadow=False)
                k.plant("Blob", "Foliage", c, x, y, z + 0.3, 0.2, 0.2, 0.13, shadow=False)

    def tree(self, x, y, h, bloom=None, spread=1.0):
        """A broad shade tree: trunk plus a cluster of foliage cushions; crown top at h."""
        k, r = self.k, self.r
        crown = clamp(h * 0.42, 1.4, 3.0) * spread
        th = h - crown * 0.75
        k.plant("Trunk", "Bark", (104, 88, 70), x, y, 0, 0.36 * spread, 0.36 * spread, th, r.uniform(0, 360))
        leaf = r.choice(LEAF)
        for _i in range(r.randint(3, 5)):
            a, rr = r.uniform(0, 6.28), r.uniform(0.3, 0.8) * crown
            c = bloom if (bloom and r.random() < 0.6) else leaf
            s = r.uniform(0.6, 0.85) * crown
            k.plant("Puff", "Foliage", c, x + rr * math.cos(a), y + rr * math.sin(a), th + r.uniform(-0.2, 0.5),
                    s, s, s * 0.62, r.uniform(0, 360))
        k.plant("Puff", "Foliage", bloom or leaf, x, y, th + crown * 0.25, crown * 0.7, crown * 0.7, crown * 0.5)
        if th > 3.2:
            # tall trees: lower tiers of foliage down the trunk so they read as full crowns, not lollipops
            for tz in (th * 0.62, th * 0.82) if th > 5.5 else (th * 0.7,):
                for _i in range(2):
                    a = r.uniform(0, 6.28)
                    s = r.uniform(0.5, 0.7) * crown
                    k.plant("Puff", "Foliage", leaf, x + 0.45 * crown * math.cos(a), y + 0.45 * crown * math.sin(a), tz,
                            s, s, s * 0.55, r.uniform(0, 360))

    def palm(self, x, y, h, lean=0.0):
        """Fan/date palm: a slim trunk and a drooping crown of fronds."""
        k, r = self.k, self.r
        th = h - 1.0
        k.plant("Trunk", "Bark", (128, 108, 84), x, y, 0, 0.28, 0.28, th, r.uniform(0, 360))
        n = 8
        y0 = r.uniform(0, 360)
        for i in range(n):
            yaw = y0 + i * 360.0 / n
            a = math.radians(yaw)
            ox, oy = -math.sin(a) * 0.55, math.cos(a) * 0.55
            k.plant("Fringe", "Foliage", r.choice(PALM_LEAF), x + ox, y + oy, th + 0.55, 1.1, 1.0, 1.25, yaw, shadow=True)
        k.plant("Puff", "Foliage", PALM_LEAF[0], x, y, th + 0.15, 0.95, 0.95, 0.55, r.uniform(0, 360))

    def agave(self, x, y, s=1.0, z=0.0):
        """Agave / yucca rosette: a squat cone skirt with a couple of spikes."""
        k, r = self.k, self.r
        c = r.choice(AGAVE)
        k.plant("Cone", "Foliage", c, x, y, z, 1.5 * s, 1.5 * s, 0.75 * s, r.uniform(0, 360))
        for i in range(3):
            a = i * 2.1 + r.uniform(0, 0.5)
            k.plant("Reed", "Foliage", c, x + 0.15 * s * math.cos(a), y + 0.15 * s * math.sin(a), z, 2.2 * s, 2.2 * s,
                    r.uniform(0.7, 1.0) * s, r.uniform(0, 360), shadow=False)

    def boulder(self, x, y, s=1.0):
        r = self.r
        self.k.plant("Stone", "PermeableStone", (176, 150, 118), x, y, 0, 0.7 * s, 0.55 * s, 0.4 * s, r.uniform(0, 360))

    def cactus(self, x, y, h=1.6):
        k, r = self.k, self.r
        c = (84, 128, 80)
        k.plant("Cylinder", "Foliage", c, x, y, 0, 0.32, 0.32, h)
        if h > 1.2:
            k.plant("Cylinder", "Foliage", c, x + 0.3, y, 0.6, 0.2, 0.2, h * 0.45)
            k.plant("Cylinder", "Foliage", c, x - 0.25, y + 0.1, 0.8, 0.2, 0.2, h * 0.35)

    def scatter_trees(self, x0, y0, x1, y1, n, hmax, palms=0.0, bloom=0.3, min_gap=3.0, taken=None):
        """Place n trees in a band, keeping a gap between them (deterministic)."""
        r = self.r
        pts = list(taken or [])
        placed = 0
        for _ in range(n * 8):
            if placed >= n or x1 - x0 < 0.5 or y1 - y0 < 0.5:
                break
            x, y = r.uniform(x0, x1), r.uniform(y0, y1)
            if any((x - px) ** 2 + (y - py) ** 2 < min_gap ** 2 for px, py in pts):
                continue
            pts.append((x, y))
            placed += 1
            h = r.uniform(0.75, 1.0) * hmax
            if r.random() < palms:
                self.palm(x, y, h)
            else:
                b = r.choice((JACARANDA, BOUGAINVILLEA, (240, 170, 190), (246, 236, 220))) if r.random() < bloom else None
                self.tree(x, y, h, bloom=b)
        return pts


# ======================================================================================================
# Stahl House (Pierre Koenig, CSH #22, 1960)
# ======================================================================================================
def stahl_house(plot):
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 3.8, 6.0)
    white = c.m("roofw", "Plain", (244, 244, 240))         # white-painted steel and the thin roof plane
    roofw = white
    panel = c.m("panel", "Metal", (206, 200, 186))         # steel decking walls, warm grey
    deck = c.m("deck", "PermeableStone", TERRAZZO)
    soffit = c.m("soffit", "Timber", (176, 128, 84))       # warm timber ceiling between the beams
    accent = vivid(c.pal[2])

    fz = 0.45 if H >= 4.6 else 0.3                           # podium / floor
    beam_h, roof_t = 0.34, 0.18
    gh = clamp(H - fz - beam_h - roof_t - 0.4, 2.4, 2.95)    # glass height (PV / green roof sit on top)
    ceil = fz + gh
    rz = ceil + beam_h                                       # underside of the roof slab
    # plan: living wing on the left running back from the street, bedroom wing along the back: an L
    lw = clamp(0.25 * w, 6.5, 8.5)
    bd = clamp(0.28 * d, 5.5, 7.5)
    Lx0 = clamp(0.08 * w, 1.8, 3.0)
    Lx1 = Lx0 + lw
    By1 = d - clamp(0.1 * d, 2.0, 3.0)
    By0 = By1 - bd
    carport = w >= 29.5
    cpw = 5.6 if carport else 0.0
    Bx1 = w - clamp(0.08 * w, 2.0, 3.0) - cpw
    ovf = clamp(0.13 * d, 2.6, 3.6)                          # the famous cantilever over the living-room glass
    Ly0 = max(ovf + 1.4, 0.27 * d)
    ovs, ovp, ovb = 2.4, 1.8, 0.8                            # side (pool) / bedroom front / back overhangs
    # pool along the bedroom glass, in the open corner of the L
    px0, px1 = Lx1 + 2.2, Bx1 - 0.8
    py1 = By0 - 2.2
    py0 = max(py1 - clamp(0.18 * d, 3.0, 4.6), Ly0 - 0.4)
    deck_y0 = min(py0 - 1.4, Ly0 - 1.0)

    # ---- podium and pool deck (built around the pool) ----
    dx1 = Bx1 + 0.4
    k.box(deck, Lx0 - 0.4, deck_y0, 0, Lx1, By1 + 0.4, fz)
    k.box(deck, Lx1, py1 + 0.45, 0, dx1, By1 + 0.4, fz)
    k.box(deck, Lx1, deck_y0, 0, px0 - 0.45, py1 + 0.45, fz)
    if dx1 > px1 + 0.45:
        k.box(deck, px1 + 0.45, deck_y0, 0, dx1, py1 + 0.45, fz)
    k.box(deck, px0 - 0.45, deck_y0, 0, px1 + 0.45, py0 - 0.45, fz)
    c.pool(px0, py0, px1, py1, fz, deck)
    # slim steel railing on the deck's street edge (the cliff edge of the original)
    ry = deck_y0 + 0.08
    k.box(white, Lx1 + 2.4, ry - 0.03, fz + 0.95, dx1, ry + 0.03, fz + 1.0)
    k.box(white, Lx1 + 2.4, ry - 0.015, fz + 0.45, dx1, ry + 0.015, fz + 0.48)
    n = max(1, int((dx1 - Lx1 - 2.4) / 1.6))
    for i in range(n + 1):
        x = lerp(Lx1 + 2.4, dx1 - 0.03, i / n)
        k.box(white, x - 0.03, ry - 0.03, fz, x + 0.03, ry + 0.03, fz + 0.95)
    k.box(white, dx1 - 0.06, ry, fz + 0.95, dx1, By0 - 0.3, fz + 1.0)
    # steps from the street garden up to the deck, beside the living wing
    sx = Lx1 + 0.3
    for i in range(3):
        k.box(deck, sx, deck_y0 - 0.35 * (3 - i), 0, sx + 1.8, deck_y0, fz * (i + 1) / 3)

    # ---- glass walls, posts, solid walls ----
    c.glaze("x", Lx0, Lx1, Ly0, fz, ceil, bay=2.4, p_open=0.25, p_lit=0.45)
    c.glaze("y", Ly0, By0, Lx1, fz, ceil, bay=2.5, p_open=0.25, p_lit=0.45)
    c.glaze("x", Lx1, Bx1, By0, fz, ceil, bay=2.6, p_open=0.2, p_lit=0.5)
    k.box(panel, Lx0, Ly0 + 0.1, fz, Lx0 + 0.12, By1, ceil)
    k.box(panel, Lx0, By1 - 0.12, fz, Bx1, By1, ceil)
    k.box(panel, Bx1 - 0.12, By0, fz, Bx1, By1, ceil)
    # ribs on the visible steel decking, and a high clerestory in the back wall
    for i in range(int((By1 - Ly0 - 0.6) / 0.9)):
        y = Ly0 + 0.6 + 0.9 * i
        k.box(panel, Lx0 - 0.05, y, fz, Lx0, y + 0.08, ceil)
    k.box(c.glass, Lx0 + 1, By1 + 0.005, ceil - 0.55, Bx1 - 1, By1 + 0.03, ceil - 0.15)
    for x, y in ((Lx0, Ly0), (Lx1, Ly0), (Lx1, By0), (Bx1, By0)):
        k.box(white, x - 0.08, y - 0.08, fz, x + 0.08, y + 0.08, rz)
    # interiors
    sofa = mix(accent, (90, 80, 70), 0.25)
    c.interior(Lx0 + 0.15, Ly0 + 0.1, Lx1 - 0.1, By1 - 0.15, fz, ceil, back="x0", n_lamps=3, sofa=sofa)
    c.interior(Lx1, By0 + 0.1, Bx1 - 0.15, By1 - 0.15, fz, ceil, back="y1", n_lamps=int(clamp((Bx1 - Lx1) / 3.5, 2, 5)))
    k.box(panel, Lx0 + 1.2, By0 - 3.0, fz, Lx0 + 1.8, By0 - 0.6, fz + 0.9)       # kitchen island
    k.cyl(c.mull, Lx1 - 2.4, Ly0 + 3.0, fz + 1.2, 0.5, 0.18, ceil - fz - 1.2, segs=10)  # hanging fireplace hood

    # ---- roof: thin flat plane on exposed steel beams that run out past the glass ----
    sl = (Lx0 - ovb, Ly0 - ovf, Lx1 + ovs, By1 + ovb)
    sb = (Lx1 + ovs, By0 - ovp, Bx1 + 1.0, By1 + ovb)
    roofs = [sl, sb]
    if carport:
        roofs.append((Bx1 + 1.0, By0 - 0.6, w - 1.6, By1 + ovb))
    for x0, y0, x1, y1 in roofs:
        k.box(roofw, x0, y0, rz, x1, y1, rz + roof_t)
        k.box(soffit, x0 + 0.05, y0 + 0.05, rz - 0.04, x1 - 0.05, y1 - 0.05, rz)
        n = max(2, int((x1 - x0) / 1.9))
        for i in range(n + 1):
            x = lerp(x0 + 0.25, x1 - 0.25, i / n)
            k.box(white, x - 0.07, y0 + 0.04, rz - beam_h, x + 0.07, y1 - 0.04, rz - 0.04)
        k.box(roofw, x0, y0, rz - 0.1, x1, y0 + 0.05, rz)                        # fascia lip
    # PV on the living wing, a rimmed green roof on the bedroom wing; both set in so the white edge reads
    green = c.lawn
    c.pv_rows(sl[0] + 1.2, sl[1] + 1.4, sl[2] - 1.2, sl[3] - 1.0, rz + roof_t, row=1.5, frame=white)
    gx0, gy0, gx1, gy1 = sb[0] + 0.6, sb[1] + 1.2, sb[2] - 1.0, sb[3] - 0.9
    k.box(roofw, gx0, gy0, rz + roof_t, gx1, gy1, rz + roof_t + 0.12)
    k.box(green, gx0 + 0.1, gy0 + 0.1, rz + roof_t + 0.12, gx1 - 0.1, gy1 - 0.1, rz + roof_t + 0.16)
    for _ in range(int((gx1 - gx0) * (gy1 - gy0) / 9)):
        c.shrub(r.uniform(gx0 + 0.6, gx1 - 0.6), r.uniform(gy0 + 0.6, gy1 - 0.6), r.uniform(0.4, 0.7),
                z=rz + roof_t + 0.14, bloom=0.6)
    if carport:
        c.pv_rows(Bx1 + 1.4, By0 - 0.2, w - 2.0, By1 + 0.4, rz + roof_t, row=1.5, frame=white)
    # vines spilling off the green roof's street edge and the pool-side fascia
    for x in [sl[0] + 0.6 + i * 1.3 for i in range(int((sl[2] - sl[0] - 0.6) / 1.3))]:
        if r.random() < 0.6:
            k.plant("Fringe", "Foliage", r.choice(LEAF), x, sl[1] + 0.02, rz + roof_t + 0.1, r.uniform(0.7, 1.1), 1,
                    r.uniform(0.5, 1.1), 180)
    # lanterns hung under the eaves along the pool
    for i in range(int((Bx1 - Lx1 - ovs) / 3.0)):
        x = Lx1 + ovs + 1.5 + i * 3.0
        k.box(c.lamp, x - 0.14, By0 - 1.1, rz - beam_h - 0.55, x + 0.14, By0 - 0.82, rz - beam_h - 0.2)
    for i in range(int((Lx1 - Lx0) / 2.6)):
        x = Lx0 + 1.3 + i * 2.6
        k.box(c.lamp, x - 0.14, Ly0 - 1.4, rz - beam_h - 0.55, x + 0.14, Ly0 - 1.12, rz - beam_h - 0.2)

    # ---- carport: slim posts, a little electric car in the palette colour ----
    if carport:
        cx0, cx1 = Bx1 + 1.0, w - 1.6
        for x, y in ((cx1 - 0.3, By0 - 0.3), (cx1 - 0.3, By1 + 0.4)):
            k.box(white, x - 0.07, y - 0.07, 0, x + 0.07, y + 0.07, rz)
        k.box(deck, cx0, By0 - 0.6, 0, cx1, By1 + 0.4, 0.06)
        mx = (cx0 + cx1) / 2
        k.plant("Cube", "Metal", accent, mx, By0 + 2.4, 0.55, 1.7, 3.9, 0.7)
        k.plant("Cube", "Metal", mix(accent, (250, 250, 250), 0.5), mx, By0 + 2.6, 1.05, 1.5, 2.0, 0.42)
        for ox in (-0.8, 0.8):
            for oy in (1.2, 3.7):
                k.plant("Cylinder", "Plain", (30, 30, 32), mx + ox, By0 + oy, 0.0, 0.62, 0.62, 0.22, 90)
        k.box(deck, mx - 1.4, 0, 0.0, mx + 1.4, By0 - 0.6, 0.05)

    # ---- the pool terrace: loungers, a parasol in the palette colour ----
    for i in range(int(clamp((px1 - px0) / 3.2, 1, 4))):
        lx = px0 + 1.0 + i * 2.2
        k.plant("Cube", "Fabric", (246, 244, 236), lx, py1 + 1.15, fz + 0.2, 0.7, 1.8, 0.12, 0)
        k.plant("Cube", "Fabric", accent, lx, py1 + 1.45, fz + 0.3, 0.68, 0.8, 0.08, 0)
    pr = (px1 - 0.4, py0 - 0.9)
    k.plant("Cylinder", "Metal", WHITE, pr[0], pr[1], fz, 0.05, 0.05, 2.3)
    k.plant("Cone", "Fabric", accent, pr[0], pr[1], fz + 1.9, 2.6, 2.6, 0.5)
    # planters on the deck, spilling over
    for x, y in ((Lx1 + 0.9, deck_y0 + 0.6), (dx1 - 0.6, deck_y0 + 0.6), (Lx1 + 0.9, py1 + 1.0)):
        k.box(deck, x - 0.45, y - 0.45, fz, x + 0.45, y + 0.45, fz + 0.5)
        c.shrub(x, y, 0.9, z=fz + 0.45, bloom=0.9)
        k.plant("Fringe", "Foliage", r.choice(LEAF), x, y - 0.46, fz + 0.5, 0.8, 1, 0.5, 180)

    # ---- garden ----
    gy = deck_y0 - 0.2
    c.lawn_patch(0.3, 0.3, w - 0.3, gy)
    c.lawn_patch(0.3, gy, Lx0 - 0.5, d - 0.3)
    c.lawn_patch(Lx0 - 0.5, By1 + 0.5, w - 0.3, d - 0.3)
    if not carport:
        c.lawn_patch(Bx1 + 0.5, gy, w - 0.3, By1 + 0.5)
    k.box(deck, sx + 0.3, 0, 0.0, sx + 1.5, deck_y0 - 1.05, 0.06)           # path to the steps
    # beds along the street: flowers, agaves, a few palms (it is LA) and boulders
    c.flowerbed(0.6, 0.4, sx - 0.4, min(1.9, gy - 0.4))
    c.flowerbed(sx + 2.0, 0.4, w - 0.6 - (cpw + 1.5 if carport else 0), min(1.9, gy - 0.4))
    tall = min(plot.h_max, 9.0)
    taken = [(sx + 0.9, 1.0)]
    for x in (0.9, (Bx1 + 0.9) if carport else w - 1.0):
        c.palm(x, r.uniform(1.0, 1.8), r.uniform(0.85, 1.0) * tall)
        taken.append((x, 1.5))
    for i in range(int((Bx1 - sx - 3) / 2.4)):
        x = sx + 2.6 + i * 2.4 + r.uniform(-0.4, 0.4)
        y = gy - r.uniform(0.7, 1.3)
        if y > 2.2:
            (c.agave if r.random() < 0.6 else c.boulder)(x, y, r.uniform(0.8, 1.2))
    # side and back gardens: shade trees and flowering shrubs
    c.scatter_trees(0.8, Ly0, max(1.0, Lx0 - 1.2), d - 1.0, 2, tall * 0.95, bloom=0.5, taken=taken)
    c.scatter_trees(1.0, By1 + ovb + 0.9, w - 1.0, d - 0.6, int(w / 6), tall, palms=0.25, bloom=0.4, taken=taken)
    if not carport and w - Bx1 > 3.5:
        c.scatter_trees(Bx1 + 2.0, gy + 1, w - 1.0, By1, 2, tall * 0.9, palms=0.5, taken=taken)
    for _ in range(int(w / 2.5)):
        c.shrub(r.uniform(0.6, w - 0.6), r.uniform(By1 + 0.9, d - 0.5), r.uniform(0.8, 1.3))
    for _ in range(int(d / 3)):
        c.shrub(r.uniform(0.5, max(0.6, Lx0 - 0.6)), r.uniform(Ly0, d - 0.5), r.uniform(0.7, 1.1))

    k.solid(Lx0, Ly0, 0, Lx1, By1, rz)
    k.solid(Lx1, By0, 0, Bx1, By1, rz)
    k.solid(Lx0 - 0.4, deck_y0, 0, dx1, By1 + 0.4, fz)
    return k


# ======================================================================================================
# Kaufmann Desert House (Richard Neutra, Palm Springs, 1946)
# ======================================================================================================
def kaufmann_desert(plot):
    """Neutra's pinwheel: four wings off a living core, thin white roof planes floating past glass and stone,
    the louvered gloriette on the roof, the pool and lawn in the open quadrant."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 4.8, 8.0)
    white = c.m("white", "Plain", (244, 244, 240))
    stone = c.m("stone", "RammedEarth", (206, 174, 130))
    terr = c.m("terr", "PermeableStone", (222, 214, 196))
    louv = c.m("louv", "Metal", (172, 180, 192))
    accent = vivid(c.pal[2])

    fz = 0.25
    gh = 2.85 if H >= 6.0 else clamp(H - fz - 1.9, 2.5, 2.85)
    ceil = fz + gh
    rt = 0.32                                                # fascia depth of the floating planes
    rtop = ceil + rt
    m = min(w, d)
    s = clamp(0.3 * m, 7.0, 10.0)                            # living core
    ww = clamp(0.2 * m, 4.8, 6.5)                            # wing width
    cx, cy = clamp(0.42 * w, 2.5 + ww + 2.0 + s / 2, w - 9 - s / 2), clamp(0.56 * d, 3 + 4 + s / 2, d - 6 - s / 2)
    X0, Y0, X1, Y1 = cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2
    # pinwheel wings: (x0, y0, x1, y1)
    E = (X1, Y0, w - clamp(0.07 * w, 2.0, 3.0), Y0 + ww)     # main bedroom wing, glass to the pool
    N = (X1 - ww, Y1, X1, d - clamp(0.07 * d, 1.8, 2.6))     # guest/service wing to the back
    W = (clamp(0.07 * w, 2.0, 2.8), Y1 - ww, X0, Y1)         # wing to the left, glass to the front garden
    S = (X0, max(3.0, Y0 - clamp(0.45 * (Y0 - 3), 3.5, 7.0)), X0 + ww, Y0)   # breezeway + guest room to the street

    # ---- terraces under everything ----
    for x0, y0, x1, y1 in (E, N, W, (X0, Y0, X1, Y1)):
        k.box(terr, x0 - 0.3, y0 - 0.3, 0, x1 + 0.3, y1 + 0.3, fz)
    k.box(terr, S[0] - 0.3, S[1] - 0.3, 0, S[2] + 0.3, S[3], fz)
    k.box(terr, S[2], Y0 - 2.4, 0, E[2] + 0.3, Y0, fz)        # the pool terrace along the long glass wall

    # ---- core: glass to the pool, stone fireplace wall to the left ----
    c.glaze("x", S[2], X1, Y0, fz, ceil, bay=2.2, p_open=0.3, p_lit=0.45, frame=white)
    k.box(stone, X0, Y0, fz, X0 + 0.45, Y1 - ww, ceil)
    c.interior(X0 + 0.45, Y0, X1, Y1, fz, ceil, back="x0", n_lamps=3, sofa=mix(accent, (120, 100, 80), 0.3))
    # ---- E wing ----
    c.glaze("x", E[0], E[2], E[1], fz, ceil, bay=2.3, p_open=0.25, p_lit=0.45, frame=white)
    c.glaze("y", E[1], E[3], E[2], fz, ceil, bay=2.3, p_open=0.0, p_lit=0.4, frame=white)
    k.box(stone, E[0], E[3] - 0.45, fz, E[2] + 3.0 if E[2] + 3.4 < w else E[2], E[3], ceil)  # back wall runs on out
    c.interior(E[0], E[1], E[2], E[3] - 0.45, fz, ceil, back="y1", n_lamps=int(clamp((E[2] - E[0]) / 3.5, 2, 4)))
    # ---- N wing: glass to the right garden, stone left and back ----
    c.glaze("y", N[1], N[3], N[2], fz, ceil, bay=2.3, p_open=0.2, p_lit=0.45, frame=white)
    k.box(stone, N[0], N[1], fz, N[0] + 0.45, N[3], ceil)
    k.box(stone, N[0], N[3] - 0.45, fz, N[2], N[3], ceil)
    c.interior(N[0] + 0.45, N[1], N[2], N[3] - 0.45, fz, ceil, back="x0", n_lamps=2)
    # ---- W wing: glass to the front garden, stone end and back; the end wall runs out into the garden ----
    c.glaze("x", W[0], W[2], W[1], fz, ceil, bay=2.3, p_open=0.25, p_lit=0.45, frame=white)
    k.box(stone, W[0], W[3] - 0.45, fz, W[2], W[3], ceil)
    k.box(stone, W[0], W[1] - min(3.5, W[1] - 3.5), fz, W[0] + 0.45, W[3], ceil)
    c.interior(W[0] + 0.45, W[1], W[2], W[3] - 0.45, fz, ceil, back="y1", n_lamps=2)
    # ---- S wing: open breezeway on slim posts, a small guest room with a stone face at its street end ----
    gl = min(4.0, (S[3] - S[1]) * 0.5)
    k.box(stone, S[0], S[1], fz, S[2], S[1] + 0.45, ceil)
    k.box(stone, S[0], S[1], fz, S[0] + 0.45, S[1] + gl, ceil)
    c.glaze("y", S[1] + 0.45, S[1] + gl, S[2], fz, ceil, bay=2.0, p_open=0.0, p_lit=0.6, frame=white)
    k.box(stone, S[0] + 0.45, S[1] + gl - 0.12, fz, S[2], S[1] + gl, ceil)
    for y in [S[1] + gl + 2.0 * (i + 1) for i in range(int((S[3] - S[1] - gl - 0.5) / 2.0))]:
        k.box(white, S[2] - 0.2, y - 0.05, fz, S[2] - 0.1, y + 0.05, ceil)
    k.box(stone, S[0], S[1] + gl, fz, S[0] + 0.3, S[3], fz + 0.9)          # low stone bench wall
    for i in range(int((S[3] - S[1] - gl) / 1.6)):
        c.shrub(S[0] - 0.6, S[1] + gl + 0.8 + i * 1.6, 0.8, bloom=0.6)

    # ---- the floating roof planes ----
    ov = 1.9
    planes = [
        (E[0], E[1] - ov, E[2] + ov * 0.8, E[3] + 0.5, 0.00),
        (N[0] - 0.5, N[1], N[2] + ov, N[3] + 0.5, 0.01),
        (W[0] - 0.5, W[1] - ov, W[2], W[3] + 0.5, 0.02),
        (S[0] - 0.6, S[1] - 1.2, S[2] + 0.6, S[3], 0.03),
        (X0 - 0.3, Y0 - ov, X1, Y1, 0.04),
    ]
    for x0, y0, x1, y1, e in planes:
        k.box(white, x0, y0, ceil + e, x1, y1, rtop + e)
    # thin steel posts at the plane corners over terraces
    for x, y in ((E[2] + ov * 0.8 - 0.3, E[1] - ov + 0.3), (S[2] + 0.3, S[1] - 0.9), (W[0] - 0.2, W[1] - ov + 0.3)):
        k.box(white, x - 0.05, y - 0.05, fz, x + 0.05, y + 0.05, ceil)
    # lanterns hung in the deep overhangs
    for i in range(int((E[2] - S[2]) / 3.2)):
        x = S[2] + 1.6 + i * 3.2
        k.box(c.lamp, x - 0.13, Y0 - 1.2, ceil - 0.55, x + 0.13, Y0 - 0.95, ceil - 0.2)
        k.box(c.mull, x - 0.01, Y0 - 1.085, ceil - 0.2, x + 0.01, Y0 - 1.065, ceil)

    # ---- gloriette: the open roof room with vertical aluminium louvers, its own hovering plane ----
    gz0 = rtop + 0.04
    gs = s - 1.4
    gx0, gy0 = X0 + 0.5, Y0 + 0.4
    gx1, gy1 = gx0 + gs, gy0 + gs
    top = H - 0.05
    if top - gz0 >= 2.3:
        gtop = min(top, gz0 + 3.0)
        groof = gtop - 0.28
        k.box(terr, gx0, gy0, gz0 - 0.04, gx1, gy1, gz0 + 0.04)
        # hovering plane, bigger than the room
        k.box(white, gx0 - 1.0, gy0 - 1.2, groof, gx1 + 1.0, gy1 + 0.6, gtop)
        for x, y in ((gx0, gy0), (gx1, gy0), (gx0, gy1), (gx1, gy1)):
            k.box(white, x - 0.06, y - 0.06, gz0, x + 0.06, y + 0.06, groof)
        # louvers on the street side and the pool side
        n = int(gs / 0.42)
        for i in range(n):
            a = gx0 + 0.25 + i * (gs - 0.5) / max(1, n - 1)
            k.obox(louv, a, gy0, (gz0 + groof) / 2, 0.035, 0.28, (groof - gz0) / 2 - 0.05, 0, 35, 0)
            b = gy0 + 0.25 + i * (gs - 0.5) / max(1, n - 1)
            k.obox(louv, gx1, b, (gz0 + groof) / 2, 0.28, 0.035, (groof - gz0) / 2 - 0.05, 0, -35, 0)
        k.box(louv, gx0, gy0 - 0.06, groof - 0.12, gx1, gy0 + 0.06, groof)
        k.box(louv, gx1 - 0.06, gy0, groof - 0.12, gx1 + 0.06, gy1, groof)
        # stone parapet and fireplace chimney at the back, a warm hearth glow
        k.box(stone, gx0, gy1 - 0.4, gz0, gx1, gy1, gz0 + 1.0)
        k.box(stone, gx0, gy1 - 1.2, gz0, gx0 + 1.6, gy1, groof)
        k.box(c.lamp, gx0 + 0.3, gy1 - 1.25, gz0 + 0.25, gx0 + 1.3, gy1 - 1.18, gz0 + 0.85)
        k.box(stone, gx0 + 2.0, gy1 - 0.9, gz0, gx0 + 2.9, gy1, top)  # chimney stack
        for i in range(2):
            lx = gx0 + gs * (0.35 + 0.35 * i)
            k.box(c.lamp, lx - 0.15, gy0 + gs * 0.5 - 0.15, groof - 0.75, lx + 0.15, gy0 + gs * 0.5 + 0.15, groof - 0.45)
            k.box(c.mull, lx - 0.01, gy0 + gs * 0.5 - 0.01, groof - 0.45, lx + 0.01, gy0 + gs * 0.5 + 0.01, groof)
        # deck chairs up there
        k.plant("Cube", "Fabric", accent, gx0 + gs * 0.55, gy0 + gs * 0.45, gz0 + 0.25, 0.7, 1.6, 0.12, 20)
        k.plant("Cube", "Fabric", (240, 236, 226), gx0 + gs * 0.75, gy0 + gs * 0.5, gz0 + 0.25, 0.7, 1.6, 0.12, -10)
        # outdoor stair up the side of the N wing
        sx0 = N[2] + 0.2
        steps = 11
        for i in range(steps):
            y = Y1 + 0.3 + i * 0.3
            k.box(stone, sx0, y, 0, sx0 + 1.1, y + 0.3, fz + (gz0 - fz) * (i + 1) / steps)
    else:
        # low plots: the core rises as a louvered clerestory drum instead of a roof room
        groof = top - 0.3
        k.box(white, gx0 - 0.6, gy0 - 0.8, groof, gx1 + 0.6, gy1 + 0.4, top)
        k.box(c.glass, gx0 + 0.2, gy0 + 0.2, gz0, gx1 - 0.2, gy1 - 0.2, groof)
        n = int(gs / 0.4)
        for i in range(n):
            a = gx0 + 0.2 + i * (gs - 0.4) / max(1, n - 1)
            k.obox(louv, a, gy0, (gz0 + groof) / 2, 0.035, 0.25, (groof - gz0) / 2, 0, 35, 0)
            b = gy0 + 0.2 + i * (gs - 0.4) / max(1, n - 1)
            k.obox(louv, gx1, b, (gz0 + groof) / 2, 0.25, 0.035, (groof - gz0) / 2, 0, -35, 0)
        k.box(stone, gx0 + 0.3, gy1 - 0.9, gz0, gx0 + 1.2, gy1, top)

    # PV on the E and N wing planes (behind the fascia)
    c.pv_rows(E[0] + 0.5, E[1] - ov + 0.8, E[2] + ov * 0.8 - 0.8, E[3] + 0.2, rtop, row=1.4, frame=white)
    c.pv_rows(N[0], N[1] + 0.5, N[2] + ov - 0.8, N[3] + 0.1, rtop + 0.01, row=1.4, frame=white)
    # planters on the W and S planes, vines spilling from the fascia
    for x0, y0, x1, y1, e in planes[2:4]:
        k.box(c.lawn, x0 + 0.5, y0 + 0.5, rtop + e, x1 - 0.5, y1 - 0.5, rtop + e + 0.06)
        for _ in range(int((x1 - x0) * (y1 - y0) / 8)):
            c.shrub(r.uniform(x0 + 0.9, x1 - 0.9), r.uniform(y0 + 0.9, y1 - 0.9), r.uniform(0.5, 0.8), z=rtop + e, bloom=0.5)
        for x in [x0 + 0.5 + i * 1.2 for i in range(int((x1 - x0 - 0.5) / 1.2))]:
            if r.random() < 0.55:
                k.plant("Fringe", "Foliage", r.choice(LEAF), x, y0 + 0.02, rtop + e + 0.05, r.uniform(0.7, 1.1), 1,
                        r.uniform(0.5, 1.2), 180)

    # ---- pool in the open quadrant, lawn around it ----
    qx0, qx1 = S[2] + 2.4, E[2]
    qy0, qy1 = 2.4, Y0 - 3.0
    pl, pw = clamp(0.62 * (qx1 - qx0), 5.0, 14.0), clamp(qy1 - qy0, 2.5, 6.5)
    px0 = qx0 + (qx1 - qx0 - pl) * 0.5
    py1 = qy1
    py0 = py1 - pw
    if pw >= 2.5 and pl >= 5.0:
        c.lawn_patch(0.3, 0.3, w - 0.3, Y0 - 2.4)
        k.box(terr, px0 - 1.4, py0 - 1.4, 0, px0 + pl + 1.4, py1 + 1.4, 0.04)
        c.pool(px0, py0, px0 + pl, py1, 0.14, terr, depth=0.1)
        for i in range(int(clamp(pl / 3, 1, 4))):
            lx = px0 + 0.8 + i * 1.9
            k.plant("Cube", "Fabric", (246, 244, 236), lx, py0 - 0.9, 0.24, 0.7, 1.8, 0.12, 0)
            k.plant("Cube", "Fabric", accent, lx, py0 - 0.6, 0.34, 0.68, 0.8, 0.08, 0)
    else:
        c.lawn_patch(0.3, 0.3, w - 0.3, Y0 - 2.4)

    # ---- garden: desert palette made lush ----
    tall = min(plot.h_max, 9.0)
    k.box(terr, S[0] + 0.6, 0, 0, S[2] - 0.6, S[1] - 0.3, 0.05)              # entry walk
    taken = [((S[0] + S[2]) / 2, S[1] / 2)]
    # garden stone walls running out from the house, Neutra style
    if S[1] > 3.0:
        k.box(stone, S[2] + 0.5, S[1] - 1.0, 0, min(S[2] + 6.0, px0 - 1.6), S[1] - 0.6, 1.0)
    c.lawn_patch(0.3, Y0 - 2.4, W[2], W[1] - 0.3)
    c.lawn_patch(0.3, W[3] + 0.5, N[0] - 0.3, d - 0.3)
    c.lawn_patch(N[2] + 1.6, E[3] + 0.5, w - 0.3, d - 0.3)
    # palms: a tall pair framing the pool, more at the back
    for x, y in ((qx1 + 0.6, 1.2), (W[0] + 0.8, 1.6), (W[0] + 2.4, 3.2)):
        c.palm(x, y, r.uniform(0.85, 1.0) * tall)
        taken.append((x, y))
    taken = c.scatter_trees(0.8, W[3] + 1.2, N[0] - 1.0, d - 0.8, int(w / 10) + 1, tall, palms=0.4, bloom=0.5,
                            taken=taken)
    taken = c.scatter_trees(N[2] + 2.5, E[3] + 1.5, w - 0.8, d - 0.8, int(w / 12) + 1, tall, palms=0.5, bloom=0.5,
                            taken=taken)
    # desert beds: boulders, agaves, barrel cacti, flowering shrubs between them
    beds = [(0.6, 0.6, S[0] - 0.8, min(Y0 - 2.8, W[1] - 2.0)), (N[2] + 1.6, E[3] + 0.8, w - 0.6, d - 0.6),
            (0.6, W[3] + 0.8, N[0] - 0.6, d - 0.6)]
    for x0, y0, x1, y1 in beds:
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        n = int((x1 - x0) * (y1 - y0) / 6)
        for _ in range(n):
            x, y = r.uniform(x0, x1), r.uniform(y0, y1)
            u = r.random()
            if u < 0.3:
                c.agave(x, y, r.uniform(0.7, 1.2))
            elif u < 0.45:
                c.boulder(x, y, r.uniform(0.6, 1.4))
            elif u < 0.55:
                c.cactus(x, y, r.uniform(0.6, 1.8))
            else:
                c.shrub(x, y, r.uniform(0.7, 1.2), bloom=0.6,
                        col=r.choice((BOUGAINVILLEA, (240, 200, 70), (236, 120, 60), (246, 240, 228))))
    # flowers along the street edge
    c.flowerbed(0.5, 0.3, S[0] - 0.3, 1.2)
    c.flowerbed(S[2] + 0.3, 0.3, w - 0.5, 1.1)

    for x0, y0, x1, y1 in (E, N, W, (X0, Y0, X1, Y1), (S[0], S[1], S[2], S[1] + gl)):
        k.solid(x0, y0, 0, x1, y1, rtop)
    return k


# ======================================================================================================
# Palm Springs butterfly-roof houses (William Krisel for the Alexander Construction Co., 1957-62)
# ======================================================================================================
PITCH_SIGN = 1.0     # obox pitch that raises the +x end (checked in the preview)


def tilt_x(k, s, x0, x1, y0, y1, za, zb, t=0.2):
    """Roof slab over [x0..x1, y0..y1] whose underside runs from za at x0 to zb at x1 (tilted about y)."""
    dx, dz = x1 - x0, zb - za
    L = math.hypot(dx, dz)
    ang = math.degrees(math.atan2(dz, dx)) * PITCH_SIGN
    # centre of the slab: midpoint of the underside line, lifted half the thickness along the slab normal
    nx, nz = -dz / L, dx / L
    k.obox(s, (x0 + x1) / 2 + nx * t / 2, (y0 + y1) / 2, (za + zb) / 2 + nz * t / 2, L / 2, (y1 - y0) / 2, t / 2, ang, 0, 0)


def breeze_screen(k, s, axis, a0, a1, at, z0, z1, cell=0.4, t=0.12):
    """Palm Springs breeze-block screen: a grid of block webs with a diamond in every cell."""
    n = max(2, int(round((a1 - a0) / cell)))
    m = max(2, int(round((z1 - z0) / cell)))
    ca, cz = (a1 - a0) / n, (z1 - z0) / m
    web = 0.05
    for i in range(n + 1):
        a = a0 + i * ca
        if axis == "x":
            k.box(s, a - web, at - t / 2, z0, a + web, at + t / 2, z1)
        else:
            k.box(s, at - t / 2, a - web, z0, at + t / 2, a + web, z1)
    for j in range(m + 1):
        z = z0 + j * cz
        if axis == "x":
            k.box(s, a0, at - t / 2, z - web, a1, at + t / 2, z + web)
        else:
            k.box(s, at - t / 2, a0, z - web, at + t / 2, a1, z + web)
    for i in range(n):
        for j in range(m):
            a, z = a0 + (i + 0.5) * ca, z0 + (j + 0.5) * cz
            if axis == "x":
                k.obox(s, a, at, z, ca * 0.2, t / 2, cz * 0.2, 45, 0, 0)
            else:
                k.obox(s, at, a, z, t / 2, ca * 0.2, cz * 0.2, 0, 0, 45)


def _butterfly_house(c, x0, x1, H, colour, wall, idx, slots):
    """One Alexander/Krisel house on the lot [x0..x1] (full depth). Returns nothing; draws into c.k."""
    k, r, d = c.k, c.r, c.d
    white, wall_s, conc, stone = slots["white"], slots["wall"][wall], slots["conc"], slots["stone"]
    block = white
    L = x1 - x0
    fz = 0.15
    zw = fz + 2.75                                             # flat wall top; the V roof sits above
    rise = clamp(0.11 * (L - 2), 0.7, min(1.5, H - zw - 0.45))
    t = 0.2
    fy = clamp(0.24 * d, 3.2, 5.2)                             # front setback
    hd = clamp(d - fy - 3.2, 8.0, 11.5)                        # house depth
    by = fy + hd
    side = clamp(0.06 * L, 0.6, 1.2)
    cp = L >= 13.5                                            # room for a carport
    cw = 3.3 if cp else 0.0
    left_cp = r.random() < 0.5
    hx0 = x0 + side + (cw if (cp and left_cp) else 0.0)
    hx1 = x1 - side - (cw if (cp and not left_cp) else 0.0)
    hw = hx1 - hx0
    vx = hx0 + hw * r.uniform(0.38, 0.62)                      # the valley, often off-centre
    ov_s, ov_f = 0.7, 1.0                                      # side and front/back overhangs
    zl = zw + rise * (vx - hx0 + ov_s) / max(0.1, vx - hx0)    # roof edges, extended along the slope
    zr = zw + rise * (hx1 + ov_s - vx) / max(0.1, hx1 - vx)
    zv = zw + 0.12

    # ---- slab, walls ----
    k.box(conc, hx0 - 0.2, fy - 0.2, 0, hx1 + 0.2, by + 0.2, fz)
    # side walls rise to meet the sloping roof
    k.box(wall_s, hx0, fy, fz, hx0 + 0.2, by, zw + rise * 0.98)
    k.box(wall_s, hx1 - 0.2, fy, fz, hx1, by, zw + rise * 0.98)
    # front facade: from the carport side: storage wall, entry (door + screen), living window
    doors_at_left = not left_cp
    ent_w = 1.3
    ent_x = hx0 + hw * r.uniform(0.28, 0.42) if doors_at_left else hx1 - hw * r.uniform(0.28, 0.42)
    # solid parts of the front wall, a living-room window on the far side from the carport
    win0, win1 = (hx0 + 0.5, ent_x - ent_w / 2 - 0.4) if not doors_at_left else (ent_x + ent_w / 2 + 0.4, hx1 - 0.5)
    solid = []
    if doors_at_left:
        solid = [(hx0, ent_x - ent_w / 2), (win1, hx1)]
    else:
        solid = [(hx0, win0), (ent_x + ent_w / 2, hx1)]
    use_stone = r.random() < 0.35
    for a, b in solid:
        if b - a > 0.05:
            k.box(stone if (use_stone and (b - a) < hw * 0.45) else wall_s, a, fy, fz, b, fy + 0.2, zw)
    # front door (bright, the house's colour) with a narrow sidelight and a lit transom
    dx0, dx1 = ent_x - ent_w / 2, ent_x + ent_w / 2
    k.plant("Cube", "Plain", colour, ent_x - 0.15, fy + 0.02, fz + 1.12, 1.0, 0.06, 2.24)
    k.box(c.glass, ent_x + 0.38, fy + 0.05, fz, dx1, fy + 0.12, fz + 2.24)
    k.box(white, dx0, fy, fz + 2.24, dx1, fy + 0.2, zw)
    k.box(c.lamp, dx0 - 0.25, fy - 0.12, fz + 1.7, dx0 - 0.1, fy, fz + 2.0)
    # living window: floor-to-wall-top glass, some panels slid open on the lit room
    if win1 - win0 > 1.2:
        c.glaze("x", win0, win1, fy + 0.1, fz, zw, bay=1.6, p_open=0.3, frame=white)
        c.interior(win0, fy + 0.1, win1, min(by - 0.3, fy + 4.5), fz, zw, back="y1", n_lamps=2,
                   sofa=mix(colour, (110, 96, 84), 0.4))
    # clerestory glass in the V between the wall top and the roof, front and back
    for yy, n in ((fy + 0.1, (0, -1, 0)), (by - 0.1, (0, 1, 0))):
        k.tri(c.glass, (hx0 + 0.2, yy, zw), (vx, yy, zw), (hx0 + 0.2, yy, zl - rise * ov_s / max(0.1, vx - hx0) - 0.02), n)
        k.tri(c.glass, (vx, yy, zw), (hx1 - 0.2, yy, zw), (hx1 - 0.2, yy, zr - rise * ov_s / max(0.1, hx1 - vx) - 0.02), n)
        if n[1] < 0:
            for f in (0.33, 0.66):
                for xa, xb, _zz in ((hx0, vx, zw + rise), (vx, hx1, zw + rise)):
                    xm = lerp(xa, xb, f)
                    zt = zw + rise * abs(xm - vx) / max(0.1, abs((xa if xa != vx else xb) - vx))
                    k.box(white, xm - 0.04, yy - 0.05, zw, xm + 0.04, yy + 0.02, zt)
            k.box(white, hx0, yy - 0.06, zw - 0.08, hx1, yy + 0.02, zw + 0.02)
    # back: glass wall to the garden
    c.glaze("x", hx0 + 0.2, hx1 - 0.2, by - 0.1, fz, zw, bay=2.0, p_open=0.25, frame=white)
    c.interior(hx0 + 0.2, by - 4.0, hx1 - 0.2, by - 0.1, fz, zw, back="y0", n_lamps=2)

    # ---- the butterfly roof ----
    rf0, rf1 = fy - ov_f, by + ov_f
    tilt_x(k, white, hx0 - ov_s, vx, rf0, rf1, zl, zv, t)
    tilt_x(k, white, vx, hx1 + ov_s, rf0, rf1, zv, zr, t)
    # rain chain from the valley into a planted rain basin (the V roof collects water)
    k.box(white, vx - 0.15, rf0 - 0.3, zv - 0.05, vx + 0.15, rf0 + 0.05, zv + 0.12)
    k.pole(slots["chain"], (vx, rf0 - 0.15, zv - 0.1), (vx, rf0 - 0.15, 0.3), 0.025, segs=4)
    k.plant("Cylinder", "PermeableStone", (150, 140, 128), vx, rf0 - 0.15, 0, 1.0, 1.0, 0.3)
    c.shrub(vx + 0.5, rf0 - 0.3, 0.6, bloom=0.8)
    # PV on the wing that is wider
    if vx - hx0 > hx1 - vx:
        pa, pb, za, zb = hx0 + 0.5, vx - 0.6, zl - rise * (ov_s - 0.5) / max(0.1, vx - hx0), zv
    else:
        pa, pb, za, zb = vx + 0.6, hx1 - 0.5, zv, zr - rise * (ov_s - 0.5) / max(0.1, hx1 - vx)
    if pb - pa > 2.0:
        tilt_x(k, c.pv, pa, pb, fy + 0.2, by - 0.2, za + t + 0.04, zb + t + 0.04, 0.05)
    # about half the houses plant the other wing: a sedum roof with a few cushions
    if r.random() < 0.55:
        if vx - hx0 > hx1 - vx:
            ga, gb, gza, gzb = vx + 0.3, hx1 + 0.3, zv, zr - rise * 0.3 / max(0.1, hx1 - vx)
        else:
            ga, gb, gza, gzb = hx0 - 0.3, vx - 0.3, zl - rise * 0.3 / max(0.1, vx - hx0), zv
        tilt_x(k, c.lawn, ga, gb, fy - 0.4, by + 0.4, gza + t, gzb + t, 0.06)
        for _ in range(int((gb - ga) * hd / 18)):
            gx = r.uniform(ga + 0.4, gb - 0.4)
            gz = lerp(gza, gzb, (gx - ga) / (gb - ga)) + t + 0.05
            c.shrub(gx, r.uniform(fy + 0.4, by - 0.4), r.uniform(0.4, 0.6), z=gz, bloom=0.7)

    # ---- carport with a breeze-block end wall ----
    if cp:
        cx0, cx1 = (x0 + side, hx0) if left_cp else (hx1, x1 - side)
        cz = zw + 0.15
        k.box(white, cx0 - (0.0 if left_cp else 0.0), fy - 0.8, cz, cx1, by - 2.0, cz + 0.18)
        for _px in (cx0 + 0.1, ):
            pass
        ox = cx0 + 0.12 if left_cp else cx1 - 0.12
        for py in (fy - 0.6, fy + 2.6):
            k.box(white, ox - 0.06, py - 0.06, 0, ox + 0.06, py + 0.06, cz)
        breeze_screen(k, block, "x", cx0 + 0.1, cx1 - 0.1, by - 2.2, fz, zw - 0.2)
        k.box(conc, cx0, 0, 0, cx1, by - 2.0, 0.05)
        # an old car turned into a planter, or bikes
        mx = (cx0 + cx1) / 2
        if r.random() < 0.5:
            k.plant("Cube", "Metal", mix(colour, (240, 240, 240), 0.3), mx, fy + 1.4, 0.5, 1.7, 3.9, 0.62)
            k.plant("Cube", "Metal", mix(colour, (240, 240, 240), 0.6), mx, fy + 1.6, 0.98, 1.5, 1.9, 0.36)
            for oy in (0.4, 2.4):                     # retired: its bonnet and boot are flower beds now
                c.shrub(mx, fy + oy, 0.7, z=0.8, bloom=1.0)
            for ox2 in (-0.78, 0.78):
                for oy in (0.2, 2.6):
                    k.plant("Cylinder", "Plain", (30, 30, 32), mx + ox2, fy + oy, 0.0, 0.6, 0.6, 0.2)
        else:
            for i in range(3):
                bx = cx0 + 0.7 + i * 0.9
                k.plant("Cube", "Metal", r.choice(PS_BRIGHT), bx, fy + 2.0, 0.55, 0.06, 1.6, 0.06)
                for oy in (-0.6, 0.6):
                    k.plant("Cylinder", "Plain", (30, 30, 32), bx, fy + 2.0 + oy, 0.0, 0.66, 0.66, 0.04, 90)
            c.shrub(mx, fy - 0.3, 0.8, bloom=0.8)
        k.solid(cx0, by - 2.3, 0, cx1, by - 2.1, zw)
    # ---- entry screen: breeze block in front of the door, a little garden between ----
    if r.random() < 0.7 or not cp:
        sw = min(2.6, hw * 0.3)
        sx0 = (dx1 + 0.3) if doors_at_left else (dx0 - 0.3 - sw)
        breeze_screen(k, block, "x", sx0, sx0 + sw, fy - 1.2, 0.0, 2.2)
        k.box(block, sx0 - 0.08, fy - 1.28, 2.2, sx0 + sw + 0.08, fy - 1.12, 2.3)
        c.flowerbed(sx0, fy - 1.0, sx0 + sw, fy - 0.3, n=3)

    # ---- garden ----
    k.box(conc, dx0 + 0.1, 0, 0, dx1 - 0.1, fy - 0.1, 0.05)                 # walk to the door
    gx0, gx1 = x0 + 0.3, x1 - 0.3
    if cp:
        gx0, gx1 = (hx0 - 0.1, x1 - 0.3) if left_cp else (x0 + 0.3, hx1 + 0.1)
    c.lawn_patch(gx0, 0.3, gx1, fy - 0.2)
    c.lawn_patch(x0 + 0.3, by + 0.4, x1 - 0.3, d - 0.3)
    style = idx % 3
    tall = min(c.p.h_max, 9.0)
    # front: palms are the Palm Springs signature, beds of flowers or a desert garden
    px = gx0 + 1.0 if (doors_at_left is False) else gx1 - 1.0
    c.palm(px, r.uniform(1.0, 1.8), r.uniform(0.85, 1.0) * tall)
    if L > 14 and r.random() < 0.6:
        c.palm(px + (1.6 if px < (gx0 + gx1) / 2 else -1.6), r.uniform(1.6, 2.4), r.uniform(0.7, 0.85) * tall)
    if style == 0:
        c.flowerbed(gx0 + 0.3, 0.4, gx1 - 0.3, 1.2, n=int(L / 2.2))
    elif style == 1:
        for _ in range(int(L / 2.5)):
            x = r.uniform(gx0 + 0.4, gx1 - 0.4)
            if abs(x - ent_x) > 1.0:
                (c.agave if r.random() < 0.6 else c.boulder)(x, r.uniform(0.6, fy - 1.5), r.uniform(0.7, 1.1))
        for _ in range(3):
            c.cactus(r.uniform(gx0 + 0.4, gx1 - 0.4), r.uniform(0.6, 1.4), r.uniform(0.8, 1.7))
    else:
        for _ in range(int(L / 2.6)):
            x = r.uniform(gx0 + 0.3, gx1 - 0.3)
            if abs(x - ent_x) > 1.0:
                c.shrub(x, r.uniform(0.5, 1.2), r.uniform(0.6, 0.9), bloom=0.9, col=r.choice((BOUGAINVILLEA, (240, 200, 70))))
    # citrus or jacaranda by the side, shrubs along the side walls
    c.tree(r.uniform(x0 + 1.0, x1 - 1.0), r.uniform(by + 1.6, d - 1.2), min(tall, r.uniform(4.0, 6.0)),
           bloom=r.choice((JACARANDA, (246, 160, 60), None, (240, 170, 190))))
    for _ in range(int(L / 5)):
        c.shrub(r.uniform(x0 + 0.6, x1 - 0.6), r.uniform(by + 0.8, d - 0.5), r.uniform(0.7, 1.2))
    # back garden: a small pool or vegetable beds
    if d - by > 4.5 and L > 12 and r.random() < 0.5:
        pw = min(3.0, d - by - 2.2)
        pl = min(6.0, L - 4.0)
        pxa = x0 + (L - pl) / 2
        c.pool(pxa, by + 1.2, pxa + pl, by + 1.2 + pw, 0.12, conc, depth=0.08, tile=white)
    elif d - by > 2.5:
        for i in range(int((L - 2) / 2.2)):
            bx = x0 + 1.2 + i * 2.2
            k.box(slots["bed"], bx, by + 1.0, 0, bx + 1.6, min(d - 0.6, by + 3.0), 0.35)
            for j in range(3):
                k.plant("Blob", "Foliage", r.choice(LEAF), bx + 0.4 + j * 0.4, by + 1.6, 0.35, 0.25, 0.25, 0.2, shadow=False)
    k.solid(hx0, fy, 0, hx1, by, zw)


def butterfly_row(plot):
    """A row of 3-6 Palm Springs butterfly-roof houses, each its own colour, carport, screen and garden."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 4.6, 8.0)
    n = int(clamp(round(w / 21.0), 3, 6))
    slots = {
        "white": c.m("white", "Plain", (244, 244, 240)),
        "wall": [c.m("wall0", "Plain", (240, 237, 228)), c.m("wall1", "Plain", mix(c.pal[0], (250, 244, 232), 0.5))],
        "conc": c.m("conc", "PermeableStone", (214, 208, 196)),
        "stone": c.m("stone", "PermeableStone", (186, 160, 128), 40.0),
        "bed": c.m("bed", "Timber", TEAK),
        "chain": c.m("chain", "Metal", (176, 112, 64)),
    }
    cols = list(PS_BRIGHT)
    r.shuffle(cols)
    cols[0] = vivid(c.pal[2])                       # one house always wears the block's own accent
    r.shuffle(cols)
    # lot widths: even split with a little jitter so the row isn't a clone line
    jit = [r.uniform(0.85, 1.15) for _ in range(n)]
    tot = sum(jit)
    x = 0.0
    for i in range(n):
        lw = w * jit[i] / tot
        _butterfly_house(c, x, x + lw, H, cols[i % len(cols)], (i + (i // 2)) % 2, i, slots)
        # low hedge between lots
        if i > 0:
            for j in range(int((d - 1.0) / 2.0)):
                c.k.plant("Puff", "Foliage", r.choice(LEAF), x, 0.8 + j * 2.0, 0.1, 0.75, 0.75, 0.6, r.uniform(0, 360))
        x += lw
    return k


# ======================================================================================================
# Fallingwater (Frank Lloyd Wright, Mill Run PA, 1935-39) -- on its own rock ledge, stream and falls
# ======================================================================================================
CHEROKEE = (168, 52, 38)
CREAM = (232, 214, 170)
RHODO = ((214, 120, 170), (240, 220, 230), (190, 110, 190), (230, 150, 170))


def _terrace(c, s, x0, y0, x1, y1, z, sides, par=1.0, t=0.38, pt=0.3):
    """Cantilevered concrete terrace: slab under z, solid parapet with a rounded top on the given sides
    ('f' front y0, 'b' back y1, 'l' x0, 'r' x1)."""
    k = c.k
    k.box(s, x0, y0, z - t, x1, y1, z)
    rr = pt / 2 + 0.03
    segs = {"f": ((x0, y0), (x1, y0)), "b": ((x0, y1), (x1, y1)), "l": ((x0, y0), (x0, y1)), "r": ((x1, y0), (x1, y1))}
    for sd in sides:
        (ax, ay), (bx, by) = segs[sd]
        if sd in "fb":
            yy = ay + (pt / 2 if sd == "f" else -pt / 2)
            k.box(s, ax, yy - pt / 2, z, bx, yy + pt / 2, z + par)
            k.pole(s, (ax, yy, z + par), (bx, yy, z + par), rr, segs=8)
        else:
            xx = ax + (pt / 2 if sd == "l" else -pt / 2)
            k.box(s, xx - pt / 2, ay, z, xx + pt / 2, by, z + par)
            k.pole(s, (xx, ay, z + par), (xx, by, z + par), rr, segs=8)
    # rounded slab nose along the front: the soft edge of Wright's trays
    if "f" in sides:
        k.pole(s, (x0, y0 + 0.05, z - t / 2), (x1, y0 + 0.05, z - t / 2), t / 2 + 0.02, segs=8)


def fallingwater(plot):
    """Wright's Fallingwater: cream trays cantilevered over a stream and its falls from a stone core."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 9.0, 14.0)
    cream = c.m("cream", "Plain", CREAM)
    stone = c.m("stone", "PermeableStone", (150, 128, 104), 55.0)    # coursed sandstone of the core
    ledge = c.m("ledge", "RammedEarth", (184, 160, 120))               # bedded rock of the ledge
    red = c.m("red", "Metal", CHEROKEE)
    moss = c.m("moss", "Moss", (96, 130, 62))
    foam = (236, 244, 246)

    st = 2.85
    nlv = 3 if H >= 11.8 else 2
    Zb = clamp(H - nlv * st - 0.9, 2.6, 3.4)          # top of the rock ledge = living-room floor
    Zw = Zb - 0.9                                      # upstream water
    nfall = 3 if Zw >= 1.5 else 2
    drop = (Zw - 0.1) / nfall
    sl = 1.7                                            # length of each fall step
    ys = 0.55 * d
    half = clamp(0.085 * d, 2.1, 3.2)
    ys0, ys1 = ys - half, ys + half
    xf = clamp(0.6 * w, 14.0, w - 9.0)                 # lip of the first fall
    xd = xf + (nfall - 1) * sl                          # foot of the falls (downstream pool begins)

    # ---- the stream and its falls ----
    k.box(ledge, 0, ys0, 0, xf, ys1, Zw - 0.04)
    k.box(c.water, 0, ys0, Zw - 0.04, xf, ys1, Zw)
    for i in range(1, nfall):
        x0 = xf + (i - 1) * sl
        z = Zw - i * drop
        k.box(ledge, x0, ys0, 0, x0 + sl, ys1, z - 0.04)
        k.box(c.water, x0, ys0, z - 0.04, x0 + sl, ys1, z)
    k.box(c.water, xd, ys0, 0, w, ys1, 0.1)
    for i in range(nfall):
        x = xf + i * sl
        ztop = Zw - i * drop
        zbot = Zw - (i + 1) * drop if i < nfall - 1 else 0.1
        k.box(c.water, x - 0.02, ys0 + 0.1, zbot, x + 0.1, ys1 - 0.1, ztop + 0.02)       # the falling sheet
        for j in range(int((ys1 - ys0) / 0.9)):
            yy = ys0 + 0.5 + j * 0.9 + r.uniform(-0.2, 0.2)
            k.plant("Blob", "Plain", foam, x + 0.45, yy, zbot, r.uniform(0.35, 0.55), r.uniform(0.35, 0.5), 0.14,
                    shadow=False)
    # ---- rock ledges: the house bank (behind), the near bank (street side), stepped downstream ----
    k.box(ledge, 0, ys1, 0, xd + 1.0, d - 0.4, Zb)
    k.box(ledge, xd + 1.0, ys1, 0, w - 0.4, d - 0.4, Zb * 0.45)
    k.box(moss, 0, ys1 + 0.4, Zb, xd + 1.0, d - 0.4, Zb + 0.04)
    k.box(moss, xd + 1.0, ys1 + 0.4, Zb * 0.45, w - 0.4, d - 0.4, Zb * 0.45 + 0.04)
    nb = Zw + 0.45
    k.box(ledge, 0, ys0 - 2.6, 0, xf + 0.6, ys0, nb)
    k.box(ledge, 0, ys0 - 4.6, 0, xf - 1.0, ys0 - 2.6, nb * 0.5)
    k.box(moss, 0, ys0 - 2.4, nb, xf + 0.4, ys0 - 0.3, nb + 0.04)
    k.box(moss, 0, ys0 - 4.4, nb * 0.5, xf - 1.2, ys0 - 2.6, nb * 0.5 + 0.04)
    k.box(moss, 0.2, 0.2, 0, w - 0.2, ys0 - 4.6, 0.04)                      # forest floor toward the street
    k.box(moss, xf + 0.6, ys0 - 4.6, 0, w - 0.2, ys0, 0.04)
    # boulders along every edge, many of them mossy
    def rocks(x0, x1, y, z, n, s=1.0):
        for _ in range(n):
            x = r.uniform(x0, x1)
            sc = r.uniform(0.7, 1.6) * s
            mat, tint = ("Moss", (92, 124, 60)) if r.random() < 0.4 else ("PermeableStone", r.choice(((140, 128, 112), (160, 146, 126), (120, 112, 100))))
            k.plant("Stone", mat, tint, x, y + r.uniform(-0.4, 0.4), z, sc, sc * 0.8, sc * 0.55, r.uniform(0, 360))
    rocks(0.5, xf, ys0 - 2.6, nb * 0.45, int(xf / 2.2))
    rocks(0.5, xf - 1.0, ys0 - 4.6, 0, int(xf / 2.5))
    rocks(xf + 0.2, w - 0.5, ys0 - 0.3, 0, int((w - xf) / 1.6), 1.1)
    rocks(xd + 1.0, w - 0.5, ys1 + 0.2, 0, int((w - xd) / 1.8), 1.1)
    rocks(xf - 0.4, xd + 1.2, ys1 + 0.2, Zb * 0.4, 4, 1.3)
    rocks(0.5, xf, ys1 + 0.2, Zw - 0.3, int(xf / 3))
    for i in range(nfall):
        x = xf + i * sl
        rocks(x - 0.3, x + 0.3, ys0 + 0.1, Zw - (i + 1) * drop, 1, 0.9)
        rocks(x - 0.3, x + 0.3, ys1 - 0.1, Zw - (i + 1) * drop, 1, 0.9)

    # ---- the house ----
    xh1 = xf - 0.4                                      # the house stops at the lip; T2 reaches out over the falls
    xh0 = xh1 - clamp(0.36 * w, 10.0, 14.0)
    yb0 = ys1 + 0.9
    yb1 = min(d - 2.2, yb0 + clamp(0.3 * d, 6.5, 10.5))
    z1, z2, z3 = Zb, Zb + st, Zb + 2 * st
    ceil_t = 0.38
    # stone core + chimney mass rising through every level, coursed stone piers at the back
    chx0, chx1 = xh0 + 0.4, xh0 + 2.9
    k.box(stone, chx0, yb1 - 2.6, 0, chx1, yb1, H - 0.05)
    k.box(stone, chx0 - 0.15, yb1 - 2.75, H - 0.6, chx1 + 0.15, yb1 + 0.15, H - 0.35)
    k.box(stone, xh0, yb0, z1, xh0 + 0.6, yb1, z1 + st - ceil_t)
    k.box(stone, xh0, yb1 - 0.5, z1, xh1, yb1, z1 + st - ceil_t)
    for x in (xh0 + 0.25 * (xh1 - xh0), xh0 + 0.62 * (xh1 - xh0)):
        k.box(stone, x - 0.35, yb0 - 0.05, z1, x + 0.35, yb0 + 0.6, z1 + st - ceil_t)     # stone piers in the glass
    # level 1: living room, ribbon glass to the terrace and the falls side
    c.glaze("x", xh0 + 0.6, xh1, yb0 + 0.1, z1, z1 + st - ceil_t, bay=0.95, p_open=0.12, frame=red)
    c.glaze("y", yb0 + 0.1, yb1 - 0.5, xh1 - 0.05, z1, z1 + st - ceil_t, bay=0.95, p_open=0.0, frame=red)
    c.interior(xh0 + 0.6, yb0 + 0.1, xh1, yb1 - 0.5, z1, z1 + st - ceil_t, back="y1", n_lamps=4,
               sofa=mix(vivid(c.pal[2]), CHEROKEE, 0.5))
    # T1: the great living-room tray, out over the stream toward the street
    t1 = (xh0 - 1.2, ys0 - 0.5, xh1 + 1.2, yb0)
    _terrace(c, cream, t1[0], t1[1], t1[2], t1[3], z1, "flr")
    k.box(cream, xh0 - 0.4, yb0, z1 + st - ceil_t, xh1 + 0.4, yb1 + 0.4, z1 + st)          # ceiling / L2 floor
    # the stair hanging from the tray down to the water, on red hangers
    sx0, sx1 = t1[0] - 1.25, t1[0] - 0.05
    nst = 8
    for i in range(nst):
        y = ys1 - 0.2 - i * (ys1 - ys0 - 0.8) / nst
        z = z1 - 0.2 - (z1 - Zw - 0.25) * (i + 1) / nst
        k.box(cream, sx0, y - 0.3, z - 0.06, sx1, y, z)
    k.box(cream, sx0 - 0.2, ys0 + 0.2, Zw + 0.1, sx1 + 0.2, ys0 + 1.2, Zw + 0.25)           # landing at the water
    for x in (sx0, sx1):
        k.pole(red, (x, ys1 - 0.2, z1 - 0.2), (x, ys0 + 0.6, Zw + 0.25), 0.04, segs=6)
        k.pole(red, (x, ys0 + 0.6, z1 + 1.0), (x, ys0 + 0.6, Zw + 0.25), 0.03, segs=6)
        k.pole(red, (x, ys1 - 0.2, z1 + 1.0), (x, ys0 + 0.6, z1 + 1.0), 0.03, segs=6)

    # level 2: bedrooms; T2 crosses at right angles, reaching out sideways over the falls
    l2 = (xh0 + 1.0, yb0 + 1.4, xh1 - 0.6, yb1)
    k.box(stone, l2[2] - 0.6, l2[1], z2, l2[2], l2[3], z2 + st - ceil_t)
    c.glaze("x", l2[0], l2[2] - 0.6, l2[1], z2, z2 + st - ceil_t, bay=0.95, p_open=0.15, frame=red)
    c.interior(l2[0], l2[1], l2[2] - 0.6, l2[3] - 0.1, z2, z2 + st - ceil_t, back="y1", n_lamps=3)
    t2 = (l2[2] - 1.0, ys0 + 0.6, min(w - 1.0, xd + 2.0), l2[3] - 1.2)
    _terrace(c, cream, t2[0], t2[1], t2[2], t2[3], z2, "frb")
    _terrace(c, cream, l2[0] - 0.6, yb0 - 0.2, l2[2] - 1.0, l2[1], z2, "fl")
    top_lv = z3 if nlv == 3 else None
    k.box(cream, l2[0] - 0.5, l2[1] - 0.6, z2 + st - ceil_t, l2[2] + 0.6, l2[3] + 0.4, z2 + st)
    # level 3 (tall plots): the study and its own small tray, back toward the street
    if top_lv is not None:
        l3 = (xh0 + 1.0, l2[1] + 1.6, xh0 + 1.0 + 0.5 * (xh1 - xh0), yb1)
        c.glaze("x", l3[0] + 0.4, l3[2], l3[1], z3, z3 + st - ceil_t, bay=0.95, p_open=0.15, frame=red)
        c.glaze("y", l3[1], l3[3] - 0.3, l3[2], z3, z3 + st - ceil_t, bay=0.95, frame=red)
        c.interior(l3[0] + 0.4, l3[1], l3[2], l3[3] - 0.3, z3, z3 + st - ceil_t, back="y1", n_lamps=2)
        _terrace(c, cream, l3[0] - 0.4, l2[1] - 0.4, l3[2] + 0.8, l3[1], z3, "flr")
        k.box(cream, l3[0] - 0.6, l3[1] - 0.8, z3 + st - ceil_t, l3[2] + 0.8, l3[3] + 0.4, z3 + st)
        roof_z = z3 + st
    else:
        roof_z = z2 + st
    # concrete trellis beams running back from the top over the entry
    for i in range(5):
        x = chx1 + 0.6 + i * 0.9
        k.box(cream, x - 0.1, yb1 - 1.0, roof_z - 0.5, x + 0.1, min(d - 0.5, yb1 + 3.0), roof_z - 0.2)
    k.box(red, chx1 + 0.4, min(d - 0.5, yb1 + 3.0) - 0.2, 0, chx1 + 0.55, min(d - 0.5, yb1 + 3.0) - 0.05, roof_z - 0.5)
    # PV hidden on the top roof behind its edge
    c.pv_rows(l2[0] + 0.6, l2[1] + 0.6, l2[2] - 0.4, l2[3] - 0.2, roof_z if top_lv is None else z2 + st, row=1.4,
              frame=cream) if top_lv is None else None

    # ---- life on the trays: planters, vines, lanterns, chairs ----
    def planter(x, y, z):
        k.box(cream, x - 0.5, y - 0.35, z, x + 0.5, y + 0.35, z + 0.5)
        c.shrub(x, y, 0.8, z=z + 0.45, bloom=0.8, col=r.choice(RHODO))
    planter(t1[0] + 1.0, t1[1] + 0.9, z1)
    planter(t1[2] - 1.0, t1[1] + 0.9, z1)
    planter(t2[2] - 0.9, t2[1] + 0.9, z2)
    for x0, x1, y, z in ((t1[0], t1[2], t1[1], z1 + 1.0), (t2[0], t2[2], t2[1], z2 + 1.0)):
        for i in range(int((x1 - x0) / 1.3)):
            if r.random() < 0.45:
                k.plant("Fringe", "Foliage", r.choice(LEAF), x0 + 0.6 + i * 1.3, y - 0.02, z + 0.1, r.uniform(0.7, 1.1), 1,
                        r.uniform(0.6, 1.4), 180)
    for i in range(int((t1[2] - t1[0]) / 3.0)):
        x = t1[0] + 1.5 + i * 3.0
        k.box(c.lamp, x - 0.12, t1[1] + 0.05, z1 + 1.05, x + 0.12, t1[1] + 0.3, z1 + 1.3)
    acc = vivid(c.pal[2])
    for i in range(3):
        k.plant("Cube", "Fabric", (240, 232, 214) if i % 2 else acc, xh0 + 2 + i * 1.6, (t1[1] + yb0) / 2, z1 + 0.22,
                0.7, 1.6, 0.12, r.uniform(-15, 15))

    # ---- woods: rhododendron clusters on the banks, big trees behind ----
    def rhodo(x, y, z, s=1.0):
        k.plant("Puff", "Foliage", (52, 86, 48), x, y, z + 0.3 * s, 1.1 * s, 1.0 * s, 0.8 * s, r.uniform(0, 360))
        col = r.choice(RHODO)
        for _ in range(r.randint(3, 6)):
            a, rr = r.uniform(0, 6.28), r.uniform(0.2, 0.8) * s
            k.plant("Blob", "Foliage", col, x + rr * math.cos(a), y + rr * math.sin(a), z + 0.9 * s, 0.24 * s, 0.24 * s,
                    0.18 * s, shadow=False)
    for _ in range(int(w / 3)):
        rhodo(r.uniform(0.6, xf - 0.5), r.uniform(ys0 - 2.2, ys0 - 0.6), nb, r.uniform(0.7, 1.1))
    for _ in range(int(w / 4)):
        rhodo(r.uniform(0.6, w - 0.6), r.uniform(0.6, 1.8), 0, r.uniform(0.8, 1.2))
    for _ in range(int(w / 5)):
        x = r.uniform(xd + 1.2, w - 0.6)
        rhodo(x, r.uniform(ys1 + 0.8, d - 0.8), Zb * 0.45 + 0.04, r.uniform(0.8, 1.2))
    # ferns along the water
    for _ in range(int(w / 2)):
        x = r.uniform(0.5, w - 0.5)
        if xh0 - 1.5 < x < xh1 + 1.5:
            continue
        zz = Zb if x < xd + 1.0 else Zb * 0.45
        k.plant("Puff", "Foliage", r.choice(LEAF), x, ys1 + 0.6, zz, 0.5, 0.5, 0.35, r.uniform(0, 360), shadow=False)
    tall = min(H + 1.0, plot.h_max)
    taken = [((xh0 + xh1) / 2, (yb0 + yb1) / 2)]
    taken += [(x, y) for x, y in [(xh0 + i, yb0 + j) for i in range(0, int(xh1 - xh0) + 1, 2)
                                  for j in range(0, int(yb1 - yb0) + 1, 2)]]
    for x0_, y0_, x1_, y1_, n in ((0.8, yb0, xh0 - 2.0, d - 0.8, 2), (xh1 + 2.0, t2[3] + 1.5, w - 0.8, d - 0.8, 2),
                                  (0.8, yb1 + 0.5, w - 0.8, d - 0.8, 2), (0.8, 0.6, 3.0, 2.2, 1), (w - 3.0, 0.6, w - 0.8, 2.2, 1)):
        for _ in range(n * 6):
            if n <= 0 or x1_ - x0_ < 0.5 or y1_ - y0_ < 0.3:
                break
            x, y = r.uniform(x0_, x1_), r.uniform(y0_, y1_)
            if any((x - px) ** 2 + (y - py) ** 2 < 16 for px, py in taken):
                continue
            taken.append((x, y))
            n -= 1
            c.tree(x, y, r.uniform(0.75, 1.0) * tall, spread=1.2,
                   bloom=(r.choice(((236, 220, 160), (240, 236, 220))) if r.random() < 0.3 else None))
    # stepping stones across the downstream pool
    for i in range(int((ys1 - ys0) / 0.8)):
        k.plant("Disc", "PermeableStone", (176, 166, 150), w - 3.0 + r.uniform(-0.2, 0.2), ys0 + 0.4 + i * 0.8, 0.1,
                1.2, 1.0, 2.0, r.uniform(0, 360))

    k.solid(0, ys1, 0, xd + 1.0, d - 0.4, Zb)
    k.solid(0, ys0 - 2.6, 0, xf + 0.6, ys0, nb)
    k.solid(xh0, yb0, Zb, xh1, yb1, roof_z)
    k.solid(chx0, yb1 - 2.6, 0, chx1, yb1, H)
    return k


# ======================================================================================================
# Eichler homes (Joseph Eichler with Anshen + Allen / Jones & Emmons, 1950-66)
# ======================================================================================================
EICHLER_DOORS = ((236, 120, 40), (240, 196, 50), (40, 160, 160), (200, 60, 50), (90, 150, 200), (130, 170, 70))
SIDING = ((128, 134, 112), (150, 120, 90), (116, 124, 132), (176, 150, 100), (110, 96, 80))
MAPLE = (186, 64, 44)


def _eichler(c, x0, x1, H, idx, slots, door, siding, sid_col):
    k, r, d = c.k, c.r, c.d
    trim, roof, conc, beam = slots["trim"], slots["roof"], slots["conc"], slots["beam"]
    L = x1 - x0
    fz = 0.12
    zw = fz + 2.55                                              # 8.5 ft walls
    fy = clamp(0.2 * d, 3.6, 6.0)
    hd = clamp(d - fy - 3.6, 9.5, 15.0)
    by = fy + hd
    hw = min(L - 3.4, 17.0)
    hx0 = x0 + (L - hw) / 2 + r.uniform(-0.4, 0.4) * max(0.0, L - hw - 3.4) / 2
    hx1 = hx0 + hw
    xr = (hx0 + hx1) / 2                                        # ridge, gable to the street
    t = 0.18
    ov = 0.75
    rise = min(0.24 * hw / 2, H - zw - t - 0.15)
    zr = lambda x: zw + rise * (1 - abs(x - xr) / (hw / 2))
    # plan: garage on one side of the front, entry beside it, the atrium behind the entry, living at the back
    g_left = r.random() < 0.5
    gw = min(5.6, hw * 0.36)
    gx0, gx1 = (hx0, hx0 + gw) if g_left else (hx1 - gw, hx1)
    aw = clamp(hw * 0.32, 3.6, 5.6)
    ad = clamp(hd * 0.32, 3.4, 5.0)
    ax0 = clamp(xr - aw / 2 + (0.8 if g_left else -0.8), hx0 + 3.0, hx1 - 3.0 - aw)
    ax1 = ax0 + aw
    ay0 = fy + clamp(hd * 0.25, 2.6, 3.4)
    ay1 = ay0 + ad
    ent_x = (ax0 + ax1) / 2

    # ---- slab, walls ----
    k.box(conc, hx0 - 0.2, fy - 0.2, 0, hx1 + 0.2, by + 0.2, fz)
    # nearly blank front: vertical siding, a garage door, a bright entry door, a high strip of windows
    k.box(siding, hx0, fy, fz, hx1, fy + 0.18, zw)
    k.plant("Cube", "Timber", mix(sid_col, (240, 236, 226), 0.35), (gx0 + gx1) / 2, fy - 0.02, fz + 1.1, gw - 0.8, 0.06, 2.2)
    for i in range(1, 4):
        k.box(trim, gx0 + 0.4, fy - 0.07, fz + 0.55 * i, gx1 - 0.4, fy - 0.03, fz + 0.55 * i + 0.03)
    k.plant("Cube", "Plain", door, ent_x, fy - 0.03, fz + 1.12, 1.0, 0.06, 2.24)
    k.box(c.glass, ent_x + 0.6, fy - 0.03, fz, ent_x + 1.0, fy, fz + 2.24)
    k.box(c.lamp, ent_x - 0.85, fy - 0.15, fz + 1.75, ent_x - 0.65, fy - 0.02, fz + 2.05)
    sx0, sx1 = (gx1 + 0.6, ent_x - 1.0) if g_left else (ent_x + 1.4, gx0 - 0.6)
    if sx1 - sx0 > 1.0:
        k.box(c.glass, sx0, fy - 0.03, zw - 0.55, sx1, fy, zw - 0.12)
    ox0, ox1 = (ent_x + 1.4, hx1 - 0.6) if g_left else (hx0 + 0.6, ent_x - 1.0)
    if ox1 - ox0 > 1.0:
        k.box(c.glass, ox0, fy - 0.03, zw - 0.55, ox1, fy, zw - 0.12)
    # gable end over the front wall: siding with a glass clerestory band at the ridge
    k.tri(siding, (hx0, fy, zw), (hx1, fy, zw), (xr, fy, zw + rise), (0, -1, 0))
    k.tri(siding, (hx0, by, zw), (hx1, by, zw), (xr, by, zw + rise), (0, 1, 0))
    # side walls (blank), back wall all glass on posts
    k.box(siding, hx0, fy, fz, hx0 + 0.15, by, zw)
    k.box(siding, hx1 - 0.15, fy, fz, hx1, by, zw)
    c.glaze("x", hx0 + 0.15, hx1 - 0.15, by - 0.08, fz, zw, bay=2.4, p_open=0.3, frame=beam)
    k.tri(c.glass, (xr - rise * 2.2, by - 0.06, zw), (xr + rise * 2.2, by - 0.06, zw), (xr, by - 0.06, zw + rise * 0.95),
          (0, 1, 0))
    c.interior(hx0 + 0.15, ay1 + 0.2, hx1 - 0.15, by - 0.1, fz, zw, back="y0", n_lamps=3,
               sofa=mix(door, (120, 100, 80), 0.4))
    # the atrium: glass on all four sides, open to the sky, a maple and ferns in it
    c.glaze("x", ax0, ax1, ay0, fz, zw, bay=1.6, p_open=0.25, frame=beam)
    c.glaze("x", ax0, ax1, ay1, fz, zw, bay=1.6, p_open=0.3, frame=beam)
    c.glaze("y", ay0, ay1, ax0, fz, zw, bay=1.6, p_open=0.0, frame=beam)
    c.glaze("y", ay0, ay1, ax1, fz, zw, bay=1.6, p_open=0.2, frame=beam)
    k.box(c.lawn, ax0 + 0.1, ay0 + 0.1, fz, ax1 - 0.1, ay1 - 0.1, fz + 0.05)
    k.box(conc, ax0 + 0.1, ay0 + 0.1, fz + 0.05, ax0 + 1.1, ay1 - 0.1, fz + 0.08)
    c.tree(ax0 + aw * 0.62, ay0 + ad * 0.5, min(zw + rise + 0.6, H), bloom=MAPLE if r.random() < 0.6 else None)
    for _ in range(4):
        c.shrub(r.uniform(ax0 + 1.4, ax1 - 0.4), r.uniform(ay0 + 0.4, ay1 - 0.4), 0.6, z=fz, bloom=0.4)
    c.interior(hx0 + 0.15, ay0, ax0, ay1, fz, zw, back="x0", n_lamps=1)

    # ---- roof: low gable, cut open over the atrium; beams run out past the eaves ----
    yf, yb = fy - ov, by + ov
    xl, xR = hx0 - ov, hx1 + ov
    pieces = []
    for xa, xb in ((xl, xr), (xr, xR)):
        pieces.append((xa, xb, yf, ay0))
        pieces.append((xa, xb, ay1, yb))
    pieces += [(xl, ax0, ay0, ay1), (ax1, xR, ay0, ay1)]
    for xa, xb, ya, yb_ in pieces:
        if xa < xr < xb:
            for p, q in ((xa, xr), (xr, xb)):
                tilt_x(k, roof, p, q, ya, yb_, zr(p), zr(q), t)
        else:
            tilt_x(k, roof, xa, xb, ya, yb_, zr(xa), zr(xb), t)
    # fascia at the gable ends, ridge beam and purlins projecting past them (the Eichler signature)
    for yy, sgn in ((yf, -1), (yb, 1)):
        for xa, xb in ((xl, xr), (xr, xR)):
            k.beam(trim, (xa, yy, zr(xa) + t / 2), (xb, yy, zr(xb) + t / 2), 0.08, t + 0.12)
        for xx in (xr, xr - hw * 0.25, xr + hw * 0.25):
            z = zr(xx) - 0.12
            k.box(beam, xx - 0.07, yy if sgn > 0 else yy - 0.6, z - 0.22, xx + 0.07, yy + 0.6 if sgn > 0 else yy, z)
    # exposed rafters under the side eaves, posts along the back glass
    n = int((by - fy) / 1.2)
    for i in range(n + 1):
        y = fy + i * (by - fy) / n
        for xa, xb in ((xl, hx0), (hx1, xR)):
            k.beam(beam, (xa, y, zr(xa) - 0.06), (xb, y, zr(xb) - 0.06), 0.08, 0.16)
    # PV on one slope, back half (catches the sun, hidden from the street)
    pa, pb = (xr + 0.5, xR - 0.6) if r.random() < 0.5 else (xl + 0.6, xr - 0.5)
    tilt_x(k, c.pv, pa, pb, ay1 + 0.5, yb - 0.6, zr(pa) + t + 0.03, zr(pb) + t + 0.03, 0.05)
    # vines spilling from the eaves at the front corners
    for x in (xl + 0.4, xR - 0.4):
        k.plant("Fringe", "Foliage", r.choice(LEAF), x, (fy + by) / 2, zr(x) - 0.05, 0.9, 1.0, 1.4, 90)

    # ---- garden: Japanese-influenced, lush ----
    k.box(conc, gx0 + 0.3, 0, 0, gx1 - 0.3, fy - 0.2, 0.05)                    # driveway
    for i in range(int((fy - 0.6) / 0.9)):
        k.box(conc, ent_x - 0.6, 0.3 + i * 0.9, 0, ent_x + 0.6, 0.9 + i * 0.9 - 0.25, 0.06)   # stepping pavers
    gl0, gl1 = (gx1 + 0.1, x1 - 0.3) if g_left else (x0 + 0.3, gx0 - 0.1)
    c.lawn_patch(gl0, 0.3, gl1, fy - 0.3)
    c.lawn_patch(x0 + 0.3, by + 0.5, x1 - 0.3, d - 0.3)
    tall = min(c.p.h_max + 1.0, 7.0, c.p.h_max)
    # a sculpted pine or a flowering tree in the front lawn, boulders and grasses around
    tx = gl0 + (gl1 - gl0) * (0.25 if g_left else 0.75)
    if abs(tx - ent_x) < 1.8:
        tx = gl1 - 1.2 if g_left else gl0 + 1.2
    c.tree(tx, r.uniform(1.4, max(1.5, fy - 1.6)), tall * r.uniform(0.85, 1.0),
           bloom=r.choice((None, (240, 170, 190), JACARANDA, MAPLE)))
    for _ in range(int(L / 4)):
        x = r.uniform(gl0 + 0.4, gl1 - 0.4)
        if abs(x - ent_x) > 1.0:
            c.boulder(x, r.uniform(0.6, fy - 0.8), r.uniform(0.6, 1.1))
    c.flowerbed(gl0 + 0.2, fy - 1.2, gl1 - 0.2, fy - 0.35, n=int(L / 1.6))
    for _ in range(int(L / 2.0)):
        x = r.uniform(gl0 + 0.3, gl1 - 0.3)
        if abs(x - ent_x) > 0.9:
            k.plant("Reed", "Foliage", r.choice(((150, 170, 90), (120, 150, 80))), x, r.uniform(0.4, 1.0), 0, 6, 6, 0.6,
                    shadow=False)
    # back garden: patio, fruit trees, vegetable beds
    k.box(conc, hx0 + 0.5, by + 0.2, 0, hx1 - 0.5, by + 2.2, 0.06)
    for i in range(2):
        k.plant("Cube", "Fabric", door if i == 0 else (240, 232, 214), hx0 + 2 + i * 1.2, by + 1.2, 0.3, 0.6, 0.6, 0.45)
    if d - by > 3.5:
        c.scatter_trees(x0 + 1.0, by + 2.8, x1 - 1.0, d - 0.8, max(1, int(L / 9)), tall, bloom=0.5)
    for _ in range(int(L / 2.5)):
        c.shrub(r.uniform(x0 + 0.5, x1 - 0.5), r.uniform(by + 2.4, d - 0.4), r.uniform(0.7, 1.2))
    # shrubs along the side walls
    for xs in (hx0 - 0.6, hx1 + 0.6):
        if x0 + 0.4 < xs < x1 - 0.4:
            for i in range(int(hd / 2.2)):
                c.shrub(xs, fy + 1.0 + i * 2.2, r.uniform(0.7, 1.0), bloom=0.5)
    k.solid(hx0, fy, 0, hx1, by, zw)


def eichler_court(plot):
    """1-3 Eichler homes side by side on a garden court: blank gable fronts, open atriums, glass to the garden."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 3.9, 6.0)
    n = int(clamp(round(w / 20.0), 1, 3))
    slots = {
        "trim": c.m("trim", "Plain", (236, 232, 222)),
        "roof": c.m("roof", "PermeableStone", (172, 166, 156)),
        "conc": c.m("conc", "PermeableStone", (212, 204, 190)),
        "beam": c.m("beam", "Timber", (120, 84, 56)),
    }
    doors = list(EICHLER_DOORS)
    r.shuffle(doors)
    doors[0] = vivid(c.pal[2])
    sids = list(SIDING)
    r.shuffle(sids)
    sids[0] = mix(c.pal[1], (110, 100, 86), 0.35)          # one house in the block's own muted green/earth
    x = 0.0
    for i in range(n):
        lw = w / n
        siding = c.m(f"siding{i}", "Timber", sids[i])
        _eichler(c, x, x + lw, H, i, slots, doors[i], siding, sids[i])
        if i > 0:
            for j in range(int((d - 1.0) / 1.5)):
                c.k.plant("Puff", "Foliage", r.choice(LEAF), x, 0.8 + j * 1.5, 0.1, 0.65, 0.65, 0.6, r.uniform(0, 360))
        x += lw
    return k


KINDS = {"eichler_court": eichler_court, "fallingwater": fallingwater, "butterfly_row": butterfly_row, "stahl_house": stahl_house, "kaufmann_desert": kaufmann_desert}
SIZES = {
    "eichler_court": {"w": (24, 60), "d": (18, 30), "h": (4, 6), "floors": (1, 1), "use": "homes"},
    "fallingwater": {"w": (26, 44), "d": (24, 40), "h": (9, 14), "floors": (2, 3), "use": "homes"},
    "butterfly_row": {"w": (30, 140), "d": (14, 22), "h": (5, 8), "floors": (1, 1), "use": "homes"},
    "stahl_house": {"w": (22, 36), "d": (18, 30), "h": (4, 6), "floors": (1, 1), "use": "homes"},
    "kaufmann_desert": {"w": (26, 40), "d": (22, 34), "h": (5, 8), "floors": (1, 2), "use": "homes"},
}
