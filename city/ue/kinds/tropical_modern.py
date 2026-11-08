"""Tropical modern family: Bawa, WOHA, Boeri, re-imagined for the lush solarpunk village.

Kinds (CATALOG.md): bawa_courtyard, kampung_terraces, oasia_tower, breeze_block_flats, vertical_forest.
Every kind draws in the plot's local frame (metres, x along the street, y away from it, z up), stretches its bays to
the plot instead of scaling, stays under plot.h_max and is deterministic from plot.seed.
"""
import math

from .kit import Kit, LEAF, FLOWER

# ---- shared colours -----------------------------------------------------------------------------------------------
LEAVES = LEAF + ((88, 140, 52), (106, 150, 58), (70, 118, 46), (120, 160, 70))
DEEP = ((44, 84, 42), (54, 96, 46), (62, 104, 50))
BARK = (112, 94, 76)
BARK_PALE = (168, 156, 140)
TERRACOTTA = (176, 88, 60)
LIMEWASH = (236, 230, 214)
BOUGAIN = ((206, 46, 128), (226, 70, 150), (190, 36, 110))
FRANGI = ((248, 244, 228), (250, 230, 170), (246, 226, 214))
INTERIOR = (40, 34, 30)
LANTERN = (240, 158, 72)


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _bays(length, target):
    """Number of bays (>= 1) closest to a target bay width: stretch, don't scale."""
    return max(1, int(round(length / target)))


# ---- planting helpers (instances; clusters, not leaves) ----------------------------------------------------------
def bush(k, rng, x, y, z, r, flowers=0.35, fcols=FLOWER, squash=0.7, leaf=None):
    k.plant("Puff", "Foliage", leaf or rng.choice(LEAVES), x, y, z, r, r * rng.uniform(0.85, 1.15), r * squash,
            rng.uniform(0, 360))
    if rng.random() < flowers:
        c = rng.choice(fcols)
        for _ in range(1 + int(r > 0.7)):
            a = rng.uniform(0, 6.283)
            k.plant("Blob", "Foliage", c, x + math.cos(a) * r * 0.45, y + math.sin(a) * r * 0.45, z + r * squash * 0.75,
                    r * 0.32, r * 0.32, r * 0.22, rng.uniform(0, 360))


def tree(k, rng, x, y, z, h, r, trunk_r=0.16, bark=BARK, leaf=None, bloom=None, puffs=3, bloom_n=2):
    """Trunk + a cluster of canopy cushions (+ optional blossom cushions)."""
    k.plant("Trunk", "Bark", bark, x, y, z, trunk_r / 0.5, trunk_r / 0.5, h * 0.72, rng.uniform(0, 360))
    for i in range(puffs):
        a = rng.uniform(0, 6.283) + i * 2.1
        rr = r * rng.uniform(0.55, 0.8)
        o = r * 0.45 if i else 0.0
        k.plant("Puff", "Foliage", leaf or rng.choice(LEAVES), x + math.cos(a) * o, y + math.sin(a) * o,
                z + h * 0.62 + (0 if i else r * 0.25), rr, rr, rr * 0.75, rng.uniform(0, 360))
    if bloom:
        for i in range(bloom_n):
            a = rng.uniform(0, 6.283)
            k.plant("Blob", "Foliage", rng.choice(bloom) if isinstance(bloom[0], tuple) else bloom,
                    x + math.cos(a) * r * 0.5, y + math.sin(a) * r * 0.5, z + h * 0.62 + r * 0.55,
                    r * 0.35, r * 0.35, r * 0.25, rng.uniform(0, 360))


def slender_tree(k, rng, x, y, z, h, lean=0.0):
    """WOHA street tree: a thin pale trunk rising high, small airy crown up top."""
    k.plant("Trunk", "Bark", BARK_PALE, x, y, z, 0.26, 0.26, h, rng.uniform(0, 360))
    a = rng.uniform(0, 6.283)
    for i in range(3):   # loose, lopsided crown: cushions at three heights, swinging round the trunk
        a += rng.uniform(1.6, 2.6)
        rr = rng.uniform(0.8, 1.3) * (1.15 - 0.15 * i)
        off = rng.uniform(0.6, 1.3)
        k.plant("Puff", "Foliage", rng.choice(LEAVES), x + math.cos(a) * off, y + math.sin(a) * off,
                z + h * (0.62 + 0.17 * i), rr, rr * 0.8, rr * 0.45, rng.uniform(0, 360))


def palm(k, rng, x, y, z, h, fronds=5):
    k.plant("Trunk", "Bark", (126, 110, 88), x, y, z, 0.3, 0.3, h, rng.uniform(0, 360))
    top = z + h * 0.97
    for i in range(fronds):
        yaw = i * 360.0 / fronds + rng.uniform(-15, 15)
        a = math.radians(yaw)
        k.plant("Fringe", "Foliage", rng.choice(LEAVES), x + math.sin(a) * 0.9, y + math.cos(a) * 0.9, top + 0.15,
                1.0, 1.0, 1.3, yaw + 90)
    k.plant("Puff", "Foliage", rng.choice(LEAVES), x, y, top, 0.75, 0.75, 0.45, 0)


def fern(k, rng, x, y, z, s=1.0):
    """Tree fern / bird's nest: a low crown of drooping fronds."""
    for i in range(4):
        yaw = i * 90 + rng.uniform(-20, 20)
        a = math.radians(yaw)
        k.plant("Fringe", "Foliage", rng.choice(LEAVES), x + math.sin(a) * 0.35 * s, y + math.cos(a) * 0.35 * s,
                z + 0.9 * s, 0.8 * s, 0.8 * s, 0.85 * s, yaw + 90)
    k.plant("Puff", "Foliage", rng.choice(LEAVES), x, y, z + 0.3 * s, 0.55 * s, 0.55 * s, 0.6 * s, 0)


def drape(k, rng, x0, x1, y, z, length, yaw=0.0, step=0.95, gap=0.0, flowers=None, along_y=False):
    """A curtain of hanging vines along an edge (x0..x1 at y, or y0..y1 at x if along_y), hanging from z."""
    n = max(1, int(abs(x1 - x0) / step))
    for i in range(n):
        if gap and rng.random() < gap:
            continue
        t = x0 + (x1 - x0) * (i + 0.5) / n
        L = length * rng.uniform(0.55, 1.1)
        px, py = (y, t) if along_y else (t, y)
        k.plant("Fringe", "Foliage", rng.choice(LEAVES), px, py, z, rng.uniform(0.9, 1.15), 1.0, L, yaw)
        if flowers and rng.random() < 0.3:
            k.plant("Blob", "Foliage", rng.choice(flowers), px, py, z - L * rng.uniform(0.2, 0.6), 0.22, 0.22, 0.18)


def trough(k, rng, x0, x1, y, z, depth=0.6, density=0.8, flowers=0.4, fcols=FLOWER, along_y=False, r=0.5):
    """Spilling planting along a ledge."""
    L = abs(x1 - x0)
    n = max(1, int(L / (r * 1.6) * density))
    for i in range(n):
        t = x0 + (x1 - x0) * (i + rng.uniform(0.2, 0.8)) / n
        o = rng.uniform(-depth * 0.3, depth * 0.3)
        px, py = (y + o, t) if along_y else (t, y + o)
        bush(k, rng, px, py, z, r * rng.uniform(0.8, 1.2), flowers=flowers, fcols=fcols)


# plant colours are snapped to this fixed set at the end of every build: each distinct (prim, material, tint) is
# its own component, so random or derived tints would multiply them
LEAF_SET = ((62, 104, 46), (88, 140, 52), (120, 160, 70), (50, 90, 46))
FLOWER_SET = ((214, 72, 84), (236, 132, 170), (240, 206, 80), (246, 242, 230), (206, 46, 128), (236, 120, 60))
BARK_SET = (BARK, BARK_PALE)


def _snap(k):
    def near(c, pal):
        return min(pal, key=lambda q: sum((c[i] - q[i]) ** 2 for i in range(3)))
    for it in k.inst:
        if it[1] != "Foliage" and it[0] != "Trunk":
            continue                      # stones, pots, stepping discs keep their colour
        c = tuple(it[2:5])
        it[2:5] = list(near(c, BARK_SET if it[0] == "Trunk" else LEAF_SET + FLOWER_SET))
    return k


def _cap(k, limit=595):
    """Budget guard: if a big plot still overshoots the instance budget, thin the hanging vines (Fringe: nothing
    sits on them) evenly, then the low shrubs' flower dots, deterministically."""
    for prim in ("Fringe", "Blob"):
        over = len(k.inst) - limit
        if over <= 0:
            break
        idx = [i for i, it in enumerate(k.inst) if it[0] == prim]
        if not idx:
            continue
        drop = set(idx[j] for j in range(len(idx)) if (j * min(over, len(idx))) // len(idx) !=
                   ((j + 1) * min(over, len(idx))) // len(idx))
        k.inst = [it for i, it in enumerate(k.inst) if i not in drop]
    return _snap(k)


# ---- building helpers -------------------------------------------------------------------------------------------
def pitched(k, s, x0, y0, x1, y1, z, rise, along_x=True, t=0.18, over=0.0):
    """Two thin roof planes over [x0..x1, y0..y1] (eave height z, ridge z+rise), ridge along x or y."""
    if along_x:
        ym = (y0 + y1) / 2
        k.slope(s, x0 - over, y0 - over, x1 + over, ym, z - over * rise / (ym - y0), z + rise, t=t)
        k.slope(s, x0 - over, ym, x1 + over, y1 + over, z + rise, z - over * rise / (ym - y0), t=t)
    else:
        xm = (x0 + x1) / 2
        half = xm - x0 + over
        L = math.hypot(half, rise + over * rise / (xm - x0))
        ang = math.degrees(math.atan2(rise + over * rise / (xm - x0), half))
        zc = (z - over * rise / (xm - x0) + z + rise) / 2 + t / 2
        k.obox(s, (x0 - over + xm) / 2, (y0 + y1) / 2, zc, L / 2, (y1 - y0) / 2 + over, t / 2, ang, 0, 0)
        k.obox(s, (xm + x1 + over) / 2, (y0 + y1) / 2, zc, L / 2, (y1 - y0) / 2 + over, t / 2, -ang, 0, 0)


def hip(k, s, x0, y0, x1, y1, z, rise, over=0.9, soffit=None, fascia=None):
    """Hipped roof over [x0..x1, y0..y1]: eaves at z (dropping over the overhang), ridge rise above, along the long
    side. Faces are one-sided quads/tris; a flat soffit at eave level closes the underside."""
    ex0, ey0, ex1, ey1 = x0 - over, y0 - over, x1 + over, y1 + over
    half = min(x1 - x0, y1 - y0) / 2
    drop = over * rise / half
    ze = z - drop
    zr = z + rise
    hw = half + over
    if (x1 - x0) >= (y1 - y0):
        ym = (y0 + y1) / 2
        r0, r1 = (ex0 + hw, ym, zr), (ex1 - hw, ym, zr)
        nz = hw / math.hypot(hw, rise + drop)
        ny = (rise + drop) / math.hypot(hw, rise + drop)
        k.quad(s, (ex0, ey0, ze), (ex1, ey0, ze), r1, r0, (0, -ny, nz))
        k.quad(s, (ex1, ey1, ze), (ex0, ey1, ze), r0, r1, (0, ny, nz))
        k.tri(s, (ex0, ey1, ze), (ex0, ey0, ze), r0, (-ny, 0, nz))
        k.tri(s, (ex1, ey0, ze), (ex1, ey1, ze), r1, (ny, 0, nz))
    else:
        xm = (x0 + x1) / 2
        r0, r1 = (xm, ey0 + hw, zr), (xm, ey1 - hw, zr)
        nz = hw / math.hypot(hw, rise + drop)
        nx = (rise + drop) / math.hypot(hw, rise + drop)
        k.quad(s, (ex0, ey1, ze), (ex0, ey0, ze), r0, r1, (-nx, 0, nz))
        k.quad(s, (ex1, ey0, ze), (ex1, ey1, ze), r1, r0, (nx, 0, nz))
        k.tri(s, (ex0, ey0, ze), (ex1, ey0, ze), r0, (0, -nx, nz))
        k.tri(s, (ex1, ey1, ze), (ex0, ey1, ze), r1, (0, nx, nz))
    if fascia is not None:
        t = 0.16
        k.box(fascia, ex0, ey0, ze - t, ex1, ey0 + 0.06, ze)
        k.box(fascia, ex0, ey1 - 0.06, ze - t, ex1, ey1, ze)
        k.box(fascia, ex0, ey0, ze - t, ex0 + 0.06, ey1, ze)
        k.box(fascia, ex1 - 0.06, ey0, ze - t, ex1, ey1, ze)
    if soffit is not None:
        k.box(soffit, ex0, ey0, ze - 0.06, ex1, ey1, ze - 0.02)
    return zr


# =================================================================================================================
# bawa_courtyard: Geoffrey Bawa's tropical modernism (Lunuganga, Number 11, Jayakody house): a low courtyard house of
# limewashed walls under tiled pitched roofs on slender columns, deep verandas round a lawn court with a still pond
# and a frangipani; bougainvillea over the street wall, a roofed gate.
# =================================================================================================================
def _wall_run(k, S, x0, x1, y, z0, z1, rng, along_y=False, inward=1, bay=2.7, doors=0.5, lit=0.45, shutter=None):
    """A limewashed wall from x0..x1 at y (or along y at x) with door / window openings, a dark room behind and a
    warm lamp glowing in some. inward: +1 if the room lies on the +y (+x) side of the wall."""
    n = _bays(x1 - x0, bay)
    bw = (x1 - x0) / n
    t = 0.25

    def bx(s, a0, a1, b0, b1, c0, c1):  # a along the wall, b across it
        if along_y:
            k.box(s, b0, a0, c0, b1, a1, c1)
        else:
            k.box(s, a0, b0, c0, a1, b1, c1)
    y0w, y1w = (y, y + t) if inward > 0 else (y - t, y)
    yin = y + inward * 1.2
    bx(S["dark"], x0, x1, min(yin, yin + inward * 0.05), max(yin, yin + inward * 0.05), z0, z1)  # dim back plane
    for i in range(n):
        a0, a1 = x0 + i * bw, x0 + (i + 1) * bw
        door = rng.random() < doors
        ow = min(1.5, bw - 0.9)
        oa0, oa1 = (a0 + a1) / 2 - ow / 2, (a0 + a1) / 2 + ow / 2
        sill = z0 if door else z0 + 0.9
        head = z0 + 2.3
        bx(S["wall"], a0, oa0, y0w, y1w, z0, z1)
        bx(S["wall"], oa1, a1, y0w, y1w, z0, z1)
        bx(S["wall"], oa0, oa1, y0w, y1w, head, z1)
        if sill > z0:
            bx(S["wall"], oa0, oa1, y0w, y1w, z0, sill)
        # timber frame + glazed / louvred infill set back in the reveal
        fy0, fy1 = (y0w + y1w) / 2 - 0.03, (y0w + y1w) / 2 + 0.03
        bx(S["timber"], oa0, oa1, fy0 - 0.02, fy1 + 0.02, head - 0.08, head)
        bx(S["timber"], oa0, oa0 + 0.08, fy0 - 0.02, fy1 + 0.02, sill, head)
        bx(S["timber"], oa1 - 0.08, oa1, fy0 - 0.02, fy1 + 0.02, sill, head)
        opened = door and shutter is not None and rng.random() < 0.5
        if opened:
            # a pair of coloured louvred leaves folded open against the wall
            fo = (y0w - 0.06, y0w) if inward > 0 else (y1w, y1w + 0.06)
            bx(shutter, oa0 - ow / 2, oa0, fo[0], fo[1], sill + 0.05, head - 0.05)
            bx(shutter, oa1, oa1 + ow / 2, fo[0], fo[1], sill + 0.05, head - 0.05)
        else:
            bx(S["glass"], oa0 + 0.08, oa1 - 0.08, fy0, fy1, sill, head - 0.08)
            bx(S["timber"], (oa0 + oa1) / 2 - 0.03, (oa0 + oa1) / 2 + 0.03, fy0 - 0.02, fy1 + 0.02, sill, head)
        if (opened or (not door and rng.random() < 0.3)) and rng.random() < lit * 1.6:
            # an open pane: a warm timber-lined room behind with a lantern pendant (glass is opaque)
            yb = yin - inward * 0.03
            bx(S["timber"], oa0, oa1, min(yb, yb + inward * 0.02), max(yb, yb + inward * 0.02), sill, head)
            lc = (oa0 + oa1) / 2 + rng.uniform(-0.2, 0.2)
            yl = y + inward * 0.7
            bx(S["lamp"], lc - 0.14, lc + 0.14, yl - 0.14, yl + 0.14, z0 + 1.75, z0 + 2.05)


def _columns(k, S, x0, x1, y, z0, z1, bay=2.7, along_y=False, r=0.11):
    n = _bays(x1 - x0, bay)
    for i in range(n + 1):
        t = x0 + (x1 - x0) * i / n
        px, py = (y, t) if along_y else (t, y)
        k.box(S["stone"], px - 0.2, py - 0.2, z0, px + 0.2, py + 0.2, z0 + 0.25)
        k.cyl(S["col"], px, py, z0 + 0.25, r, r * 0.85, z1 - z0 - 0.25, segs=10)
    return n


def _roof_wing(k, S, x0, y0, x1, y1, z, rise, along_x=True, over=0.95, gable_box=None):
    """Hipped tiled roof with a boarded soffit and a dark ridge cap (along_x kept for call compatibility)."""
    zr = hip(k, S["tile"], x0, y0, x1, y1, z, rise, over=over, soffit=S["timber"], fascia=S["timber"])
    half = min(x1 - x0, y1 - y0) / 2
    if (x1 - x0) >= (y1 - y0):
        ym = (y0 + y1) / 2
        k.box(S["ridge"], x0 + half - over * 0.2, ym - 0.12, zr - 0.06, x1 - half + over * 0.2, ym + 0.12, zr + 0.12)
    else:
        xm = (x0 + x1) / 2
        k.box(S["ridge"], xm - 0.12, y0 + half - over * 0.2, zr - 0.06, xm + 0.12, y1 - half + over * 0.2, zr + 0.12)
    return zr


def _lanterns(k, S, x0, x1, y, z, along_y=False, step=3.2, rng=None):
    n = max(1, int(abs(x1 - x0) / step))
    for i in range(n):
        t = x0 + (x1 - x0) * (i + 0.5) / n
        px, py = (y, t) if along_y else (t, y)
        k.box(S["iron"], px - 0.01, py - 0.01, z - 0.55, px + 0.01, py + 0.01, z)
        k.box(S["lamp"], px - 0.12, py - 0.12, z - 0.85, px + 0.12, py + 0.12, z - 0.55)


def frangipani(k, rng, S, x, y, z, h=4.2):
    """Candelabra frangipani: forked pale branches (ops) ending in leaf tufts with white-yellow flowers."""
    base = (x, y, z)
    fork = (x + rng.uniform(-0.2, 0.2), y + rng.uniform(-0.2, 0.2), z + h * 0.38)
    k.pole(S["bark"], base, fork, 0.13, segs=7)
    for i in range(4):
        a = rng.uniform(0, 6.283) if i == 0 else a + rng.uniform(1.2, 2.0)
        mid = (fork[0] + math.cos(a) * h * 0.22, fork[1] + math.sin(a) * h * 0.22, fork[2] + h * 0.3)
        k.pole(S["bark"], fork, mid, 0.08, segs=6)
        for j in range(2):
            b = a + (j - 0.5) * 1.1
            tip = (mid[0] + math.cos(b) * h * 0.18, mid[1] + math.sin(b) * h * 0.18, mid[2] + h * 0.22)
            k.pole(S["bark"], mid, tip, 0.05, segs=5)
            k.plant("Puff", "Foliage", rng.choice(LEAVES), tip[0], tip[1], tip[2], 0.62, 0.62, 0.38, rng.uniform(0, 360))
            k.plant("Blob", "Foliage", rng.choice(FRANGI), tip[0], tip[1], tip[2] + 0.22, 0.34, 0.34, 0.16)


def bawa_courtyard(plot):
    rng = plot.rng
    w, d = plot.w, plot.d
    k = Kit(w, d)
    pal = plot.palette
    S = {
        "wall": k.mat("Plain", LIMEWASH),
        "tile": k.mat("PermeableStone", TERRACOTTA),

        "timber": k.mat("Timber", (120, 80, 52)),

        "stone": k.mat("PermeableStone", (196, 182, 160)),
        "dark": k.mat("Plain", INTERIOR),
        "glass": k.mat("SolarGlass", (120, 140, 140), 400),
        "lamp": k.mat("Lantern", LANTERN),
        "lawn": k.mat("GreenRoof", (120, 150, 80)),
        "water": k.mat("Water", (60, 90, 96)),
        "bark": k.mat("Bark", BARK_PALE),
        "laterite": k.mat("RammedEarth", _mix((170, 104, 76), pal[2], 0.25)),
    }
    S["iron"] = S["dark"]
    S["ridge"] = S["timber"]
    S["col"] = S["wall"]
    shutter = k.mat("Timber", _mix(pal[1], (40, 90, 80), 0.45))
    plinth = 0.45
    sto = 3.0
    z_e = plinth + sto                     # eave of the single-storey wings
    two = plot.h_max >= 8.7 and d >= 22    # back wing gets an upper storey when the cap allows
    pitch = math.tan(math.radians(30))

    fg = 3.2                                # front garden depth (wall + planting)
    X0, X1, Y0, Y1 = 1.4, w - 1.4, fg + 0.6, d - 1.4
    wd_f = min(7.0, max(5.6, (Y1 - Y0) * 0.27))     # front wing: street veranda + rooms
    wd_b = min(7.0, max(5.4, (Y1 - Y0) * 0.26))     # back wing: rooms + court veranda
    wd_l = min(6.2, max(5.0, (X1 - X0) * 0.2))      # left wing: rooms + court veranda
    vw = 2.0
    cx0, cx1 = X0 + wd_l, X1 - 2.6                  # courtyard (right side: an open colonnade walk)
    cy0, cy1 = Y0 + wd_f, Y1 - wd_b

    # -- plinth and courtyard floor
    k.box(S["stone"], X0 - 0.3, Y0 - 0.3, 0, X1 + 0.3, Y1 + 0.3, plinth)
    k.box(S["lawn"], cx0 + 0.5, cy0 + 0.5, plinth, cx1 - 0.5, cy1 - 0.5, plinth + 0.04)
    k.solid(X0, Y0, 0, X1, Y1, plinth)

    # -- front wing: open street veranda on columns, rooms behind
    fr0 = Y0 + vw                               # room front wall
    k.box(S["stone"], X0, Y0, plinth, X1, fr0, plinth + 0.02)
    _wall_run(k, S, X0, X1, fr0, plinth, z_e, rng, inward=1, doors=0.55, shutter=shutter)
    _wall_run(k, S, cx0, cx1, cy0, plinth, z_e, rng, inward=-1, doors=0.7, shutter=shutter)
    k.box(S["wall"], X0, fr0, plinth, X0 + 0.25, cy0, z_e)
    k.box(S["wall"], X1 - 0.25, fr0, plinth, X1, cy0, z_e)
    _columns(k, S, X0 + 0.3, X1 - 0.3, Y0 + 0.3, plinth, z_e)
    _lanterns(k, S, X0 + 1.5, X1 - 1.5, Y0 + 1.0, z_e, rng=rng)
    k.solid(X0, fr0, plinth, X1, cy0, z_e)
    rise_f = (cy0 - Y0) / 2 * pitch
    _roof_wing(k, S, X0, Y0, X1, cy0, z_e, rise_f, True, gable_box=(X0, fr0, X1, cy0))
    # entrance pavilion breaking forward in the middle: a taller hipped roof on four columns (an ambalama),
    # or a small porch when the height cap is low
    gx = (X0 + X1) / 2 + rng.uniform(-1, 1) * max(0, (X1 - X0) / 2 - 7)
    tall = plot.h_max >= 7.2
    pw = 5.6 if tall else 3.6
    py0 = Y0 - 1.8
    k.box(S["stone"], gx - pw / 2 - 0.4, py0 - 0.4, 0, gx + pw / 2 + 0.4, Y0, plinth)
    k.box(S["stone"], gx - 1.2, py0 - 1.0, 0, gx + 1.2, py0 - 0.4, plinth * 0.5)
    zp = min(z_e + 1.5, plot.h_max - 2.9) if tall else z_e + 0.1
    for xx in (gx - pw / 2, gx + pw / 2):
        k.box(S["stone"], xx - 0.22, py0 - 0.22, plinth, xx + 0.22, py0 + 0.22, plinth + 0.3)
        k.cyl(S["col"], xx, py0, plinth + 0.3, 0.15, 0.13, zp - plinth - 0.3, segs=10)
    if tall:
        # clerestory: timber louvres between the wing roof and the high eave, lit from inside
        k.box(S["timber"], gx - pw / 2 + 0.3, Y0 + 0.6, z_e, gx + pw / 2 - 0.3, cy0 - 0.4, zp)
        for lx in (gx - 1.0, gx + 1.0):
            k.box(S["lamp"], lx - 0.15, Y0 + 0.3, zp - 1.1, lx + 0.15, Y0 + 0.55, zp - 0.8)
        nl = int(pw / 0.32)
        for i in range(nl + 1):
            xx = gx - pw / 2 + 0.3 + (pw - 0.6) * i / nl
            k.box(S["timber"], xx - 0.04, Y0 + 0.1, z_e + 0.2, xx + 0.04, Y0 + 0.2, zp)
        k.box(S["wall"], gx - pw / 2 + 0.3, Y0, z_e - 0.2, gx - pw / 2 + 0.5, cy0 - 0.4, zp)
        k.box(S["wall"], gx + pw / 2 - 0.5, Y0, z_e - 0.2, gx + pw / 2 - 0.3, cy0 - 0.4, zp)
    rise_p = min((cy0 - py0) / 2, pw / 2) * math.tan(math.radians(33))
    rise_p = min(rise_p, plot.h_max - 0.25 - zp)
    _roof_wing(k, S, gx - pw / 2, py0, gx + pw / 2, cy0 - 0.4 if tall else Y0 + 1.6, zp, rise_p, over=0.8)
    # hanging lantern in the porch
    k.box(S["lamp"], gx - 0.18, py0 + 0.9, zp - 1.3, gx + 0.18, py0 + 1.26, zp - 0.8)

    # -- back wing: rooms, court veranda, optional upper floor with a balcony
    br1 = cy1 + vw
    k.box(S["stone"], cx0, cy1, plinth, X1, br1, plinth + 0.02)
    zb = z_e + (sto if two else 0)
    _wall_run(k, S, X0 + wd_l, X1, br1, plinth, z_e, rng, inward=1, doors=0.6, shutter=shutter)
    _wall_run(k, S, X0, X1, Y1, plinth, z_e, rng, inward=-1, doors=0.0, lit=0.3)      # back wall: windows
    if two:
        _wall_run(k, S, X0 + wd_l, X1, Y1, z_e, zb, rng, inward=-1, doors=0.0, lit=0.5)
        k.box(S["wall"], X0, Y1 - 0.25, z_e, X0 + wd_l, Y1, zb)
    k.box(S["wall"], X1 - 0.25, br1, plinth, X1, Y1, zb)
    _columns(k, S, cx0, X1 - 0.3, cy1 + 0.3, plinth, z_e)
    _lanterns(k, S, cx0 + 1.2, X1 - 1.2, cy1 + 1.0, z_e, rng=rng)
    if two:
        k.box(S["timber"], cx0, cy1 - 0.1, z_e, X1, br1, z_e + 0.25)    # veranda roof doubles as balcony floor
        _wall_run(k, S, X0 + wd_l, X1, br1, z_e + 0.25, zb, rng, inward=1, doors=0.8, lit=0.6, shutter=shutter)
        _columns(k, S, cx0, X1 - 0.3, cy1 + 0.3, z_e + 0.25, zb, r=0.09)
        nb = _bays(X1 - 0.3 - cx0, 0.14 * 9)
        k.box(S["timber"], cx0, cy1 + 0.25, z_e + 1.15, X1 - 0.3, cy1 + 0.35, z_e + 1.25)   # balcony rail
        for i in range(nb + 1):
            xx = cx0 + (X1 - 0.3 - cx0) * i / nb
            k.box(S["timber"], xx - 0.03, cy1 + 0.27, z_e + 0.25, xx + 0.03, cy1 + 0.33, z_e + 1.15)
        trough(k, rng, cx0 + 0.4, X1 - 0.6, cy1 + 0.45, z_e + 0.3, density=0.5, flowers=0.6, fcols=BOUGAIN, r=0.4)
        drape(k, rng, cx0 + 0.4, X1 - 0.6, cy1 + 0.2, z_e + 0.3, 1.4, yaw=180, gap=0.45, flowers=BOUGAIN, step=1.2)
    k.solid(X0, br1, plinth, X1, Y1, zb)
    rise_b = (Y1 - cy1) / 2 * pitch
    _roof_wing(k, S, X0, cy1, X1, Y1, zb, rise_b, True, gable_box=(X0, br1, X1, Y1))

    # -- left wing: rooms along the side, veranda to the court
    lr1 = cx0 - vw
    k.box(S["stone"], lr1, cy0, plinth, cx0, cy1, plinth + 0.02)
    _wall_run(k, S, cy0, cy1, lr1, plinth, z_e, rng, along_y=True, inward=-1, doors=0.6, shutter=shutter)
    k.box(S["wall"], X0, cy0, plinth, X0 + 0.25, cy1, z_e)
    _columns(k, S, cy0 + 0.3, cy1 - 0.3, cx0 - 0.3, plinth, z_e, along_y=True)
    k.solid(X0, cy0, plinth, lr1, cy1, z_e)
    rise_l = (cx0 - X0) / 2 * pitch * 0.92
    _roof_wing(k, S, X0, cy0 + 0.4, cx0, cy1 - 0.4, z_e - 0.05, rise_l, False, gable_box=(X0, cy0 + 0.4, lr1, cy1 - 0.4))

    # -- right side: a colonnaded walk along a garden wall, roofed with a lean-to, open to the court
    k.box(S["wall"], X1 - 0.3, cy0, plinth, X1, cy1, plinth + 2.4)
    k.box(S["stone"], X1 - 0.38, cy0, plinth + 2.4, X1 + 0.08, cy1, plinth + 2.52)
    _columns(k, S, cy0 + 0.6, cy1 - 0.6, cx1 + 0.3, plinth, plinth + 2.5, along_y=True, bay=2.4, r=0.09)
    k.obox(S["tile"], (cx1 + X1) / 2 + 0.3, (cy0 + cy1) / 2, plinth + 2.85, (X1 - cx1) / 2 + 0.7, (cy1 - cy0) / 2, 0.08,
           -12, 0, 0)
    k.obox(S["timber"], (cx1 + X1) / 2 + 0.3, (cy0 + cy1) / 2, plinth + 2.73, (X1 - cx1) / 2 + 0.6, (cy1 - cy0) / 2, 0.03,
           -12, 0, 0)
    k.solid(X1 - 0.3, cy0, 0, X1, cy1, plinth + 2.5)

    # -- the court: a still pond with a stone lip, lilies, stepping stones, a frangipani
    pcx, pcy = (cx0 + cx1) / 2 + rng.uniform(-0.8, 0.8), (cy0 + cy1) / 2
    pw2 = max(1.6, (cx1 - cx0) * 0.2)
    ph2 = max(1.1, (cy1 - cy0) * 0.2)
    k.box(S["stone"], pcx - pw2 - 0.3, pcy - ph2 - 0.3, plinth, pcx + pw2 + 0.3, pcy + ph2 + 0.3, plinth + 0.18)
    k.box(S["water"], pcx - pw2, pcy - ph2, plinth, pcx + pw2, pcy + ph2, plinth + 0.2)
    for _ in range(int(pw2 * ph2 * 1.2)):
        k.plant("Disc", "Foliage", rng.choice(DEEP), pcx + rng.uniform(-pw2 + 0.3, pw2 - 0.3),
                pcy + rng.uniform(-ph2 + 0.3, ph2 - 0.3), plinth + 0.21, rng.uniform(0.35, 0.6), rng.uniform(0.35, 0.6),
                0.5, rng.uniform(0, 360))
    for _ in range(3):
        k.plant("Blob", "Foliage", rng.choice(((240, 150, 190), (250, 246, 236))), pcx + rng.uniform(-pw2 + 0.4, pw2 - 0.4),
                pcy + rng.uniform(-ph2 + 0.4, ph2 - 0.4), plinth + 0.25, 0.12, 0.12, 0.08)
    for i in range(4):  # reeds clump at a corner of the pond
        k.plant("Reed", "Foliage", rng.choice(LEAVES), pcx + pw2 - 0.3 + rng.uniform(-0.2, 0.2),
                pcy + ph2 - 0.3 + rng.uniform(-0.2, 0.2), plinth, 1.2, 1.2, rng.uniform(0.9, 1.4))
    fx = cx0 + 1.6 if rng.random() < 0.5 else cx1 - 1.6
    frangipani(k, rng, S, fx, cy1 - 1.6, plinth, h=min(4.4, z_e + 0.6))
    for _ in range(6):                                  # stepping stones across the lawn
        t = rng.random()
        k.plant("Disc", "PermeableStone", (200, 190, 170), cx0 + 0.9 + t * (cx1 - cx0 - 1.8),
                cy0 + 0.9 + rng.uniform(0, 0.4), plinth + 0.03, 0.9, 0.9, 1.0)
    for (px, py) in ((cx0 + 0.8, cy0 + 0.8), (cx1 - 0.8, cy0 + 0.8), (cx1 - 0.8, cy1 - 0.8)):
        k.plant("Cylinder", "PermeableStone", TERRACOTTA, px, py, plinth, 0.9, 0.9, 0.55)
        bush(k, rng, px, py, plinth + 0.55, 0.45, flowers=0.8)
    for _ in range(int((cx1 - cx0) * (cy1 - cy0) / 14)):   # low flowering beds on the lawn (heliconia, ixora)
        bx_, by_ = rng.uniform(cx0 + 0.9, cx1 - 0.9), rng.uniform(cy0 + 0.9, cy1 - 0.9)
        if abs(bx_ - pcx) < pw2 + 0.9 and abs(by_ - pcy) < ph2 + 0.9:
            continue
        bush(k, rng, bx_, by_, plinth, rng.uniform(0.4, 0.7), flowers=0.7,
             fcols=((226, 70, 46), (240, 160, 60), (236, 132, 160), (246, 242, 230)))
    for _ in range(int((cx1 - cx0) / 2.2)):              # ferns and gingers in the court beds
        side = rng.choice((cy0 + 0.6, cy1 - 0.6))
        fern(k, rng, rng.uniform(cx0 + 0.8, cx1 - 0.8), side, plinth, rng.uniform(0.7, 1.0))

    # -- the street: laterite garden wall with bougainvillea, a roofed gate, palms and frangipani in the garden
    wy = 0.7
    gate0, gate1 = gx - 1.3, gx + 1.3
    for a0, a1 in ((0.6, gate0), (gate1, w - 0.6)):
        if a1 - a0 < 0.5:
            continue
        k.box(S["laterite"], a0, wy - 0.18, 0, a1, wy + 0.18, 1.15)
        k.box(S["stone"], a0 - 0.05, wy - 0.24, 1.15, a1 + 0.05, wy + 0.24, 1.25)
        k.solid(a0, wy - 0.18, 0, a1, wy + 0.18, 1.25)
        n = max(1, int((a1 - a0) / 2.4))
        for i in range(n):  # bougainvillea foaming over the wall
            xx = a0 + (a1 - a0) * (i + rng.uniform(0.25, 0.75)) / n
            bush(k, rng, xx + 0.6, wy + 1.0, 0, rng.uniform(0.7, 1.0), flowers=0.7)     # shrub mass behind the wall
            if rng.random() < 0.55:
                bush(k, rng, xx, wy + 0.1, 1.15, rng.uniform(0.55, 0.8), flowers=1.0, fcols=BOUGAIN, squash=0.75)
                k.plant("Fringe", "Foliage", rng.choice(LEAVES), xx, wy - 0.22, 1.3, 1.1, 1.0, 0.8, 180)
                k.plant("Blob", "Foliage", rng.choice(BOUGAIN), xx + 0.2, wy - 0.3, 0.9, 0.28, 0.2, 0.25)
            else:
                bush(k, rng, xx, wy + 0.9, 0, rng.uniform(0.6, 0.9), flowers=0.5)
    for xx in (gate0, gate1):
        k.box(S["laterite"], xx - 0.25, wy - 0.25, 0, xx + 0.25, wy + 0.25, 2.3)
    hip(k, S["tile"], gate0 - 0.3, wy - 0.45, gate1 + 0.3, wy + 0.45, 2.35, 0.6, over=0.2, soffit=S["timber"])
    k.box(S["stone"], gate0, 0, 0, gate1, Y0, 0.05)
    for _ in range(max(2, int(w / 9))):
        xx = rng.uniform(2.2, w - 2.2)
        if abs(xx - gx) < 3.2:
            continue
        if rng.random() < 0.5:
            palm(k, rng, xx, rng.uniform(1.6, Y0 - 1.6), 0, rng.uniform(4.5, min(plot.h_max - 0.5, 7.5)))
        else:
            frangipani(k, rng, S, xx, max(1.9, Y0 - 1.6), 0, h=3.2)
    for _ in range(int(w / 1.5)):
        xx = rng.uniform(1.0, w - 1.0)
        if abs(xx - gx) < 2.0:
            continue
        bush(k, rng, xx, rng.uniform(1.2, Y0 - 0.5), 0, rng.uniform(0.5, 0.95), flowers=0.55)
    # a flowering shade tree at one front corner (flame / pink trumpet), its crown over the wall
    cxs = rng.choice((1.8, w - 1.8))
    tree(k, rng, cxs, 1.9, 0, min(plot.h_max - 0.3, 7.2), 2.6, trunk_r=0.22,
         bloom=rng.choice((((226, 70, 46), (240, 110, 50)), ((236, 132, 170), (246, 170, 196)))), puffs=4, bloom_n=4)
    # a climber on the porch columns and the house corners
    for (px, py) in ((gx - pw / 2, Y0 - 1.2), (X0 + 0.3, Y0 + 0.3), (X1 - 0.3, Y0 + 0.3),
                     (rng.uniform(X0 + 3, X1 - 3), Y0 + 0.3)):
        k.plant("Puff", "Foliage", rng.choice(DEEP), px, py, 0.4, 0.45, 0.45, 1.6)
        k.plant("Blob", "Foliage", rng.choice(BOUGAIN), px, py - 0.2, z_e - 0.6, 0.5, 0.45, 0.4)
    # big old rain trees shading the back corners (planting may rise above the height cap)
    for cxr in rng.sample((2.0, w - 2.0), 2 if w > 34 else 1):
        tree(k, rng, cxr, d - 1.6, 0, plot.h_max + rng.uniform(2.5, 4.5), rng.uniform(4.0, 5.0), trunk_r=0.38,
             leaf=rng.choice(DEEP), puffs=5)
    # back garden strip: climbers up the wall, shrubs, a tree or two leaning over
    n = _bays(X1 - X0, 3.2)
    for i in range(n):
        xx = X0 + (X1 - X0) * (i + rng.uniform(0.3, 0.7)) / n
        r = rng.random()
        if r < 0.4:
            hh = rng.uniform(1.8, zb - 0.5)
            k.plant("Puff", "Foliage", rng.choice(DEEP), xx, Y1 + 0.25, 0.2, rng.uniform(0.7, 1.2), 0.35, hh / 1.0)
            if rng.random() < 0.5:
                k.plant("Blob", "Foliage", rng.choice(BOUGAIN), xx, Y1 + 0.4, hh * 0.8, 0.45, 0.3, 0.35)
        elif r < 0.55 and d - Y1 > 0.9:
            tree(k, rng, xx, d - 0.6, 0, min(plot.h_max - 0.3, rng.uniform(5.5, 7.5)), 2.0, bloom=None, puffs=3)
        else:
            bush(k, rng, xx, Y1 + 0.6, 0, rng.uniform(0.5, 0.8), flowers=0.4)
    # side garden strips
    for _ in range(int(d / 3)):
        bush(k, rng, rng.choice((0.7, w - 0.7)), rng.uniform(Y0, d - 0.7), 0, rng.uniform(0.5, 0.8), flowers=0.3)
    return _cap(k)


# =================================================================================================================
# oasia_tower: WOHA, Oasia Hotel Downtown, Singapore 2016 (moodboard 623179efd1ce): a tower wrapped in a fine red
# fin-and-mesh skin, rounded corners smothered in creeper, big sky-garden voids carved out of the faces (white
# soffits, trees inside), an arched crown with a white truss oculus, the base buried in trees.
# =================================================================================================================
class _Face:
    """One flat face of a rectangular tower: u along the face (left to right seen from outside), n outward."""

    def __init__(self, side, x0, y0, x1, y1):
        self.side = side
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.L = (x1 - x0) if side in ("front", "back") else (y1 - y0)
        self.yaw = {"front": 180.0, "back": 0.0, "left": 270.0, "right": 90.0}[side]

    def xy(self, u, n):
        if self.side == "front":
            return self.x0 + u, self.y0 - n
        if self.side == "back":
            return self.x1 - u, self.y1 + n
        if self.side == "left":
            return self.x0 - n, self.y1 - u
        return self.x1 + n, self.y0 + u

    def box(self, k, s, u0, u1, n0, n1, z0, z1):
        ax, ay = self.xy(u0, n0)
        bx, by = self.xy(u1, n1)
        k.box(s, min(ax, bx), min(ay, by), z0, max(ax, bx), max(ay, by), z1)


def _xslab(k, s, x0, y0, x1, y1, z0, z1, rc):
    """A slab with its corners cut back by rc (hidden inside rounded corner drums)."""
    k.box(s, x0 + rc, y0, z0, x1 - rc, y1, z1)
    k.box(s, x0, y0 + rc, z0, x0 + rc, y1 - rc, z1)
    k.box(s, x1 - rc, y0 + rc, z0, x1, y1 - rc, z1)


def oasia_tower(plot):
    rng = plot.rng
    w, d = plot.w, plot.d
    k = Kit(w, d)
    pal = plot.palette
    RED = (204, 98, 66)
    S = {
        "fin": k.mat("Metal", RED),
        "mesh": k.mat("Fabric", (128, 58, 42)),
        "mesh2": k.mat("Fabric", _mix((196, 104, 76), pal[2], 0.2)),
        "glass": k.mat("SolarGlass", (110, 130, 136), 400),
        "dark": k.mat("Plain", (16, 14, 14)),
        "warm": k.mat("Plain", (190, 136, 86)),
        "lamp": k.mat("Lantern", LANTERN),
        "creeper": k.mat("Foliage", (74, 112, 52)),
        "white": k.mat("Plain", (232, 230, 222)),
        "lawn": k.mat("GreenRoof", (120, 150, 80)),
        "stone": k.mat("PermeableStone", (204, 194, 176)),
        "bark": k.mat("Bark", BARK_PALE),
    }
    H = min(plot.h_max, 36.0) - 0.45
    tx0, tx1, ty0, ty1 = 1.3, w - 1.3, 3.0, d - 1.3
    W, D = tx1 - tx0, ty1 - ty0
    rc = min(3.2, 0.16 * min(W, D))                  # rounded, creeper-clad corners
    sto = 3.2
    zl = 5.2                                         # double-height open lobby
    hc = max(3.6, min(6.5, 0.45 * min(W, D) * 0.5))  # crown vault rise
    zt = H - hc                                      # top of the body
    n = max(3, int((zt - zl) / sto))
    sto = (zt - zl) / n                              # stretch storeys to fit exactly
    # which storeys are sky gardens (2 storeys tall each)
    gardens = []
    if n >= 5:
        gardens.append(n // 2 - 1 if n < 8 else n // 3)
    if n >= 8:
        gardens.append(min(n - 2, 2 * n // 3 + 1))
    garden_rows = {g for g0 in gardens for g in (g0, g0 + 1)}
    faces = [_Face(sd, tx0, ty0, tx1, ty1) for sd in ("front", "right", "back", "left")]
    # which faces open at each garden (the voids wrap two adjacent faces, alternating corners)
    open_faces = {}
    for gi, g0 in enumerate(gardens):
        a = rng.choice((0, 3)) if gi == 0 else rng.choice((1, 2))   # the first void always shows to the street
        open_faces[g0] = {faces[a].side, faces[(a + 1) % 4].side}

    # ---- base: lobby floor, core, open colonnade under the body
    k.box(S["stone"], tx0 - 0.6, ty0 - 2.4, 0, tx1 + 0.6, ty1 + 0.6, 0.2)
    k.box(S["glass"], tx0 + rc, ty0 + 2.0, 0.2, tx1 - rc, ty1 - 2.0, zl - 0.4)
    for i in range(int((W - 2 * rc) / 3.0)):                                          # lanterns in the colonnade
        lx = tx0 + rc + 1.5 + i * 3.0
        k.box(S["lamp"], lx - 0.15, ty0 + 1.35, zl - 1.5, lx + 0.15, ty0 + 1.65, zl - 1.15)
    _xslab(k, S["white"], tx0 + 0.3, ty0 + 0.3, tx1 - 0.3, ty1 - 0.3, zl - 0.45, zl, rc)  # lobby ceiling slab
    nc = _bays(W - 2 * rc, 6.0)
    for i in range(1, nc):
        cx = tx0 + rc + (W - 2 * rc) * i / nc
        k.cyl(S["white"], cx, ty0 + 1.0, 0.2, 0.35, 0.35, zl - 0.6, segs=12)
    k.solid(tx0 + rc, ty0 + 2.0, 0, tx1 - rc, ty1 - 2.0, zl)

    # ---- corners: rounded red drums (fins, the storey bands wrapping round) with creeper climbing in patches
    corners = ((tx0 + rc, ty0 + rc, -1, -1), (tx1 - rc, ty0 + rc, 1, -1), (tx1 - rc, ty1 - rc, 1, 1),
               (tx0 + rc, ty1 - rc, -1, 1))
    for ci, (cx, cy, sx, sy) in enumerate(corners):
        k.cyl(S["mesh"], cx, cy, 0.2, rc - 0.05, rc - 0.05, zt - 0.2, segs=16)
        k.solid(cx - rc, cy - rc, 0, cx + rc, cy + rc, zt)
        am = math.atan2(sy, sx)
        for j in range(7):                                       # vertical fins round the quarter
            a = am + (j - 3) * (math.pi / 2) / 6.5
            k.obox(S["fin"], cx + math.cos(a) * (rc + 0.18), cy + math.sin(a) * (rc + 0.18), (zl + zt) / 2,
                   0.22, 0.04, (zt - zl) / 2, 0, math.degrees(a), 0)
        for row in range(n + 1):                                 # storey bands wrap the corner
            k.cyl(S["fin"], cx, cy, zl + row * sto - (0.35 if row == n else 0), rc + 0.45, rc + 0.45, 0.32, segs=16)
        # creeper: one patch climbing from the ground on two corners, a hanging patch up high on the others
        if ci % 2 == rng.randrange(2):
            za, zb = 0.2, zt * rng.uniform(0.45, 0.95)
        else:
            zb = zt - 0.3
            za = zb - zt * rng.uniform(0.25, 0.5)
        k.cyl(S["creeper"], cx, cy, za, rc + 0.55, rc + 0.5, zb - za, segs=16, caps=False)
        for j in range(int((zb - za) / 2.2)):
            z = za + 0.6 + j * 2.2 + rng.uniform(-0.5, 0.5)
            a = am + rng.uniform(-0.8, 0.8)
            k.plant("Puff", "Foliage", rng.choice(LEAVES + DEEP), cx + math.cos(a) * (rc + 0.5),
                    cy + math.sin(a) * (rc + 0.5), z, rng.uniform(0.7, 1.1), rng.uniform(0.7, 1.1),
                    rng.uniform(1.0, 1.6), rng.uniform(0, 360))
        for j in range(3):                                       # tendrils hanging off the patch top
            a = am + (j - 1) * 0.6 + rng.uniform(-0.2, 0.2)
            k.plant("Fringe", "Foliage", rng.choice(LEAVES), cx + math.cos(a) * (rc + 0.6),
                    cy + math.sin(a) * (rc + 0.6), zb, 1.2, 1.0, rng.uniform(1.5, 3.5), math.degrees(-a) + 90)

    # ---- body: storey by storey, face by face
    blocks = []                                      # (z0, z1) of runs of room storeys, for the dark cores
    r = 0
    while r < n:
        if r in garden_rows:
            r += 1
            continue
        r0 = r
        while r < n and r not in garden_rows:
            r += 1
        blocks.append((zl + r0 * sto, zl + r * sto))
    for (z0, z1) in blocks:
        _xslab(k, S["dark"], tx0 + 0.3, ty0 + 0.3, tx1 - 0.3, ty1 - 0.3, z0, z1, rc + 0.3)
        k.solid(tx0, ty0, z0, tx1, ty1, z1)

    for f in faces:
        u0f, u1f = rc, f.L - rc
        Lf = u1f - u0f
        nb = _bays(Lf, 1.7)
        bw = Lf / nb
        # creeper streaks: columns near the corners are likelier, each grows up from a planter some storeys
        streak_cols = {}
        for b in range(nb):
            edge = min(b, nb - 1 - b) / max(1, nb / 2)
            if rng.random() < 0.55 - 0.45 * edge:
                streak_cols[b] = rng.randint(2, n)
        # windows come in clusters: per (storey, bay) choose infill from a coarse noise
        cl = [[rng.random() for _ in range(nb // 2 + 2)] for _ in range(n // 2 + 2)]
        for row in range(n):
            z0 = zl + row * sto
            z1 = z0 + sto
            if row in garden_rows:
                g0 = row if row in open_faces else row - 1
                if f.side in open_faces.get(g0, ()):
                    continue                     # void: drawn with the garden
            # slab band and a thin mid rail (the photo's finer grid)
            f.box(k, S["fin"], u0f, u1f, -0.05, 0.5, z0, z0 + 0.32)
            f.box(k, S["fin"], u0f, u1f, 0.0, 0.35, z0 + sto * 0.62, z0 + sto * 0.62 + 0.1)
            for b in range(nb):
                ua, ub = u0f + b * bw, u0f + (b + 1) * bw
                in_streak = b in streak_cols and row < streak_cols[b] and row not in garden_rows
                if in_streak:
                    continue
                c = cl[row // 2][b // 2]
                if c < 0.56:
                    # a deep dark window opening (the core shows through), some warmly lit
                    if rng.random() < 0.3:     # lit room: warm back wall + a pendant (no pane: it's open)
                        f.box(k, S["warm"], ua + 0.05, ub - 0.05, -0.29, -0.27, z0 + 0.32, z1)
                        um = (ua + ub) / 2
                        f.box(k, S["lamp"], um - 0.14, um + 0.14, -0.24, -0.0, z1 - 1.25, z1 - 0.95)
                elif c < 0.78:
                    f.box(k, S["mesh"], ua, ub, -0.02, 0.04, z0 + 0.32, z1)
                else:
                    f.box(k, S["mesh2"], ua, ub, -0.02, 0.04, z0 + 0.32, z1)
        # fine vertical fins, one op per fin per run of closed storeys
        nf = _bays(Lf, 0.7)
        runs = []
        row = 0
        while row < n:
            g0 = row if row in open_faces else (row - 1 if row - 1 in open_faces and row in garden_rows else None)
            if g0 is not None and f.side in open_faces.get(g0, ()):
                row += 1
                continue
            a = row
            while row < n and not (row in garden_rows and f.side in open_faces.get(row if row in open_faces else row - 1, ())):
                row += 1
            runs.append((zl + a * sto, zl + row * sto))
        for (z0, z1) in runs:
            for i in range(1, nf):
                u = u0f + Lf * i / nf
                f.box(k, S["fin"], u - 0.035, u + 0.035, 0.05, 0.45, z0, z1)
        # creeper streaks (one op each) with cushions and a hanging fringe at the top
        for b, top in streak_cols.items():
            ua, ub = u0f + b * bw - 0.1, u0f + (b + 1) * bw + 0.1
            for (z0, z1) in runs:
                zt_s = min(z1, zl + top * sto)
                if zt_s <= z0 + 0.5:
                    continue
                f.box(k, S["creeper"], ua, ub, 0.05, 0.55, z0, zt_s)
                for z in range(int(z0) + 1, int(zt_s), 3):
                    if rng.random() < 0.5:
                        px, py = f.xy((ua + ub) / 2 + rng.uniform(-0.4, 0.4), 0.55)
                        k.plant("Puff", "Foliage", rng.choice(LEAVES + DEEP), px, py, z + rng.uniform(0, 2),
                                0.75, 0.75, 1.1, rng.uniform(0, 360))
                px, py = f.xy((ua + ub) / 2, 0.6)
                k.plant("Fringe", "Foliage", rng.choice(LEAVES), px, py, zt_s + 0.3, 1.0, 1.0, rng.uniform(1.2, 2.4), f.yaw)
        # a top band
        f.box(k, S["fin"], u0f, u1f, -0.05, 0.5, zt - 0.35, zt)

    # ---- sky gardens: open two-storey voids on two faces, white soffit, lawn floor, trees, a core wall
    for g0 in gardens:
        z0, z1 = zl + g0 * sto, zl + (g0 + 2) * sto
        _xslab(k, S["white"], tx0 + 0.2, ty0 + 0.2, tx1 - 0.2, ty1 - 0.2, z0, z0 + 0.4, rc)
        _xslab(k, S["lawn"], tx0 + 0.6, ty0 + 0.6, tx1 - 0.6, ty1 - 0.6, z0 + 0.4, z0 + 0.45, rc)
        _xslab(k, S["white"], tx0 + 0.2, ty0 + 0.2, tx1 - 0.2, ty1 - 0.2, z1 - 0.5, z1, rc)
        cw, cd = W * 0.28, D * 0.28                  # lift core, mossy-white
        ccx, ccy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
        k.box(S["white"], ccx - cw / 2, ccy - cd / 2, z0, ccx + cw / 2, ccy + cd / 2, z1)
        k.solid(tx0, ty0, z0, tx1, ty1, z0 + 0.45)
        opened = open_faces[g0]
        for f in faces:
            if f.side in opened:
                # deep red frame lip around the void, a slim white column mid-span
                f.box(k, S["fin"], rc, f.L - rc, -0.05, 0.5, z1 - 0.7, z1)
                f.box(k, S["fin"], rc, f.L - rc, -0.05, 0.5, z0, z0 + 0.55)
                k.cyl(S["white"], *f.xy(f.L / 2, -0.6), z0 + 0.4, 0.3, 0.3, z1 - z0 - 0.9, segs=10)
                # planter along the lip, spilling a curtain over the face below
                pa, pb = f.xy(rc + 0.6, -0.3), f.xy(f.L - rc - 0.6, -0.3)
                along_y = f.side in ("left", "right")
                if along_y:
                    trough(k, rng, pa[1], pb[1], pa[0], z0 + 0.5, along_y=True, density=0.7, flowers=0.5, r=0.55)
                    drape(k, rng, pa[1], pb[1], f.xy(0, 0.6)[0], z0 + 0.4, 3.0, yaw=f.yaw, gap=0.25,
                          flowers=FLOWER, along_y=True, step=1.1)
                else:
                    trough(k, rng, pa[0], pb[0], pa[1], z0 + 0.5, density=0.7, flowers=0.5, r=0.55)
                    drape(k, rng, pa[0], pb[0], f.xy(0, 0.6)[1], z0 + 0.4, 3.0, yaw=f.yaw, gap=0.25,
                          flowers=FLOWER, step=1.1)
            else:
                f.box(k, S["glass"], rc, f.L - rc, -0.1, -0.05, z0 + 0.45, z1 - 0.5)
        # trees and gingers on the garden floor, kept off the core
        for _ in range(int(W * D / 60) + 2):
            tx = rng.uniform(tx0 + 1.5, tx1 - 1.5)
            ty = rng.uniform(ty0 + 1.5, ty1 - 1.5)
            if abs(tx - ccx) < cw / 2 + 1.2 and abs(ty - ccy) < cd / 2 + 1.2:
                continue
            if rng.random() < 0.5:
                tree(k, rng, tx, ty, z0 + 0.45, min(z1 - z0 - 0.4, rng.uniform(4.2, 5.4)), 1.6,
                     bloom=rng.choice((None, ((236, 132, 170),), ((240, 206, 80),))), puffs=2, bloom_n=2)
            else:
                fern(k, rng, tx, ty, z0 + 0.45, rng.uniform(0.9, 1.3))

    # ---- crown: an arched red shell over a roof garden, open at the front with a white truss oculus
    _xslab(k, S["white"], tx0 + 0.2, ty0 + 0.2, tx1 - 0.2, ty1 - 0.2, zt - 0.4, zt, rc)
    _xslab(k, S["lawn"], tx0 + 0.6, ty0 + 0.6, tx1 - 0.6, ty1 - 0.6, zt, zt + 0.05, rc)
    k.vault(S["fin"], tx0, ty0 + 1.2, zt, tx1, ty1, zt, hc, axis_x=False, t=0.25, segs=14)
    k.vault(S["creeper"], tx0 - 0.08, ty0 + 2.6, zt, tx1 + 0.08, ty1 - 1.0, zt, hc + 0.08, axis_x=False, t=0.12, segs=14)
    # ribs on the shell
    for i in range(4):
        yy = ty0 + 1.2 + (D - 1.2) * (i + 0.5) / 4
        k.vault(S["fin"], tx0 - 0.15, yy - 0.12, zt, tx1 + 0.15, yy + 0.12, zt, hc + 0.15, axis_x=False, t=0.2, segs=14)
    # white truss in the front arch
    fy = ty0 + 1.25
    xm = (tx0 + tx1) / 2
    k.beam(S["white"], (tx0 + 0.8, fy, zt + 0.3), (tx1 - 0.8, fy, zt + 0.3), 0.15, 0.15)
    k.beam(S["white"], (tx0 + W * 0.18, fy, zt + hc * 0.62), (tx1 - W * 0.18, fy, zt + hc * 0.62), 0.12, 0.12)
    for a, b in (((tx0 + 0.8, zt + 0.3), (xm, zt + hc - 0.3)), ((tx1 - 0.8, zt + 0.3), (xm, zt + hc - 0.3)),
                 ((xm, zt + 0.3), (tx0 + W * 0.18, zt + hc * 0.62)), ((xm, zt + 0.3), (tx1 - W * 0.18, zt + hc * 0.62)),
                 ((xm, zt + 0.3), (xm, zt + hc - 0.3))):
        k.beam(S["white"], (a[0], fy, a[1]), (b[0], fy, b[1]), 0.1, 0.1)
    for _ in range(int(W / 4) + 2):                  # roof-garden trees under the arch
        tree(k, rng, rng.uniform(tx0 + 2, tx1 - 2), rng.uniform(ty0 + 2.5, ty1 - 2), zt + 0.05,
             min(hc - 0.6, rng.uniform(3.0, 4.5)), 1.5, puffs=2)
    # front lip of the roof: planter spilling over
    trough(k, rng, tx0 + rc, tx1 - rc, ty0 + 0.4, zt, density=0.8, flowers=0.5, r=0.55)
    drape(k, rng, tx0 + rc, tx1 - rc, ty0 - 0.6, zt - 0.3, 3.5, yaw=180, gap=0.3, step=1.2)

    # ---- the base buried in trees
    for _ in range(int((w + d) / 3.2)):
        side = rng.random()
        if side < 0.55:
            x, y = rng.uniform(1.0, w - 1.0), rng.uniform(0.8, ty0 - 0.6)
        elif side < 0.78:
            x, y = rng.choice((0.7, w - 0.7)), rng.uniform(ty0, d - 1)
        else:
            x, y = rng.uniform(1.0, w - 1.0), d - 0.6
        if rng.random() < 0.65:
            tree(k, rng, x, y, 0, rng.uniform(7.5, 12.5), rng.uniform(3.0, 4.2), trunk_r=0.26, puffs=4,
                 leaf=rng.choice(DEEP + LEAVES[:4]))
        else:
            bush(k, rng, x, y, 0, rng.uniform(0.6, 1.1), flowers=0.45)
    for _ in range(int(w / 3)):
        fern(k, rng, rng.uniform(1, w - 1), rng.uniform(0.6, ty0 - 0.3), 0, rng.uniform(0.8, 1.2))
    return _cap(k)


# =================================================================================================================
# vertical_forest: Stefano Boeri Architetti, Vertical Forest Tirana 2023 (moodboard 9e668dceb256, a9a4dc0f1f79): a
# charcoal and blue-glass tower with thin white floor lines, staggered cantilevered planter boxes (white rim, dark
# tapering sides) each carrying a real tree, stepping in to a pointed top; here with flowering shrubs and warm windows.
# =================================================================================================================
_OUT = {"front": (0, -1), "back": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _planter_box(k, S, f, rng, u0, u1, z_top, depth, drop=2.2, taper=0.65, tree_h=4.0, bloom=None):
    """A cantilevered planter box on face f: white rim at z_top, dark sides tapering down to drop below it,
    soil, a tree, shrubs and a spill of vines over the front."""
    ox, oy = _OUT[f.side]
    zb = z_top - drop
    db = depth * taper
    P = lambda u, n, z: (*f.xy(u, n), z)  # noqa: E731
    # front (sloped), bottom, two sides
    k.quad(S["box"], P(u0, depth, z_top), P(u1, depth, z_top), P(u1, db, zb), P(u0, db, zb), (ox, oy, -0.3))
    ux, uy = (f.xy(1, 0)[0] - f.xy(0, 0)[0], f.xy(1, 0)[1] - f.xy(0, 0)[1])
    k.quad(S["under"], P(u0, 0, zb), P(u1, 0, zb), P(u1, db, zb), P(u0, db, zb), (0, 0, -1))
    k.quad(S["box"], P(u0, 0, z_top), P(u0, depth, z_top), P(u0, db, zb), P(u0, 0, zb), (-ux, -uy, 0))
    k.quad(S["box"], P(u1, depth, z_top), P(u1, 0, z_top), P(u1, 0, zb), P(u1, db, zb), (ux, uy, 0))
    # white rim: front + two sides; soil inside
    f.box(k, S["rim"], u0 - 0.02, u1 + 0.02, depth - 0.28, depth + 0.02, z_top - 0.3, z_top)
    f.box(k, S["rim"], u0 - 0.02, u0 + 0.25, 0, depth, z_top - 0.3, z_top)
    f.box(k, S["rim"], u1 - 0.25, u1 + 0.02, 0, depth, z_top - 0.3, z_top)
    f.box(k, S["soil"], u0 + 0.25, u1 - 0.25, 0, depth - 0.28, z_top - 0.9, z_top - 0.35)
    # tension rod from the box tip up to the slab above
    tx, ty = f.xy(u0 + 0.3, depth - 0.15)
    k.box(S["rod"], tx - 0.015, ty - 0.015, z_top, tx + 0.015, ty + 0.015, z_top + 3.0)
    # planting: one tree (sometimes two), a shrub or two with flowers, vines spilling over the front
    um = (u0 + u1) / 2 + rng.uniform(-0.25, 0.25) * (u1 - u0)
    x, y = f.xy(um, depth * 0.5)
    th = tree_h * rng.uniform(0.85, 1.15)
    k.plant("Trunk", "Bark", BARK_PALE, x, y, z_top - 0.4, 0.17, 0.17, th * 0.8, rng.uniform(0, 360))
    lc = rng.choice(((112, 158, 66), (96, 146, 58), (128, 168, 76), (84, 132, 54)))
    # an airy, tall crown: one upright cushion and a smaller one leaning off to the side
    rr = rng.uniform(0.8, 1.05)
    k.plant("Puff", "Foliage", lc, x, y, z_top - 0.4 + th * 0.5, rr, rr * 0.85, th * 0.32, rng.uniform(0, 360))
    a = rng.uniform(0, 6.283)
    k.plant("Puff", "Foliage", _mix(lc, (150, 180, 90), 0.25), x + math.cos(a) * rr * 0.8, y + math.sin(a) * rr * 0.8,
            z_top - 0.4 + th * 0.62, rr * 0.6, rr * 0.6, th * 0.18, rng.uniform(0, 360))
    if bloom:
        k.plant("Blob", "Foliage", bloom[0], x, y, z_top - 0.4 + th * 0.8, 0.45, 0.45, 0.3)
    for side in (u0 + 0.7, u1 - 0.7):
        if rng.random() < 0.7:
            x, y = f.xy(side, depth * 0.55)
            bush(k, rng, x, y, z_top - 0.3, rng.uniform(0.45, 0.65), flowers=0.55)
    if rng.random() < 0.7:
        x, y = f.xy(rng.uniform(u0 + 0.5, u1 - 0.5), depth + 0.05)
        k.plant("Fringe", "Foliage", rng.choice(LEAVES), x, y, z_top - 0.05, rng.uniform(1.0, 1.6), 1.0,
                rng.uniform(1.0, 1.8), f.yaw)


def vertical_forest(plot):
    rng = plot.rng
    w, d = plot.w, plot.d
    k = Kit(w, d)
    pal = plot.palette
    S = {
        "glass": k.mat("SolarGlass", (70, 100, 176), 400),
        "char": k.mat("Plain", (50, 52, 56)),
        "rim": k.mat("Plain", (232, 230, 224)),
        "box": k.mat("Plain", (84, 84, 86)),
        "dark": k.mat("Plain", (26, 22, 20)),
        "warm": k.mat("Plain", (190, 136, 86)),
        "under": k.mat("Plain", (44, 46, 50)),
        "soil": k.mat("GreenRoof", (96, 128, 64)),
        "lamp": k.mat("Lantern", LANTERN),
        "stone": k.mat("PermeableStone", (206, 198, 184)),
        "accent": k.mat("Plain", _mix(pal[2], (220, 120, 60), 0.3)),
        "accent2": k.mat("Plain", _mix(pal[1], (60, 160, 120), 0.3)),
    }
    S["rod"] = S["char"]
    H = min(plot.h_max, 36.0) - 0.3
    tx0, tx1, ty0, ty1 = 2.6, w - 2.6, 4.0, d - 2.6
    W, D = tx1 - tx0, ty1 - ty0
    zg = 4.8                                           # double-height shop floor
    sto = 3.2
    n = max(4, int((H - zg - 1.2) / sto))              # residential floors; the last ones step in
    n_step = max(2, int(n * 0.35))
    step = min(1.6, min(W, D) * 0.32 / n_step)

    def inset(f_):
        return 0.0 if f_ < n - n_step else step * (f_ - (n - n_step) + 1)

    # ---- shop floor: glass, a warm lit interior, a white canopy band, a street of trees
    k.box(S["stone"], tx0 - 1.0, 0.0, 0, tx1 + 1.0, ty1 + 0.5, 0.12)
    k.box(S["glass"], tx0 + 0.6, ty0 + 2.0, 0.12, tx1 - 0.6, ty1 - 0.6, zg)
    k.box(S["dark"], tx0 + 0.6, ty0 + 0.6, 0.12, tx1 - 0.6, ty0 + 2.0, zg)          # deep shop interior
    nbays = _bays(W - 1.2, 3.0)
    bw_ = (W - 1.2) / nbays
    for i in range(nbays + 1):
        xa = tx0 + 0.6 + bw_ * i
        k.box(S["char"], xa - 0.08, ty0 + 0.45, 0.12, xa + 0.08, ty0 + 0.6, zg)
        if i < nbays:
            k.box(S["char"], xa, ty0 + 0.45, 2.6, xa + bw_, ty0 + 0.6, 2.7)            # transom
            for j in range(2):                                                         # pendant lamps
                lx = xa + bw_ * (0.3 + 0.4 * j)
                k.box(S["lamp"], lx - 0.18, ty0 + 0.9, 2.3, lx + 0.18, ty0 + 1.26, 2.6)
            k.box(S["warm"], xa + 0.1, ty0 + 1.94, 0.12, xa + bw_ - 0.1, ty0 + 1.99, zg - 0.4)  # warm back wall
    k.box(S["rim"], tx0 - 0.4, ty0 - 1.6, zg - 0.1, tx1 + 0.4, ty0 + 0.6, zg + 0.25)          # canopy
    k.solid(tx0 + 0.6, ty0 + 0.6, 0, tx1 - 0.6, ty1 - 0.6, zg)

    faces_all = ("front", "right", "back", "left")
    z = zg
    for f_ in range(n):
        e = inset(f_)
        x0, y0, x1, y1 = tx0 + e, ty0 + e, tx1 - e, ty1 - e
        z0, z1 = z, z + sto
        k.box(S["rim"], x0 - 0.18, y0 - 0.18, z0, x1 + 0.18, y1 + 0.18, z0 + 0.28)       # white floor line
        k.box(S["char"], x0 - 0.06, y0 - 0.06, z0 + 0.28, x1 + 0.06, y1 + 0.06, z0 + 0.75)  # spandrel
        k.box(S["glass"], x0, y0, z0 + 0.75, x1, y1, z1)
        k.solid(x0, y0, z0, x1, y1, z1)
        faces = [_Face(sd, x0, y0, x1, y1) for sd in faces_all]
        for fc in faces:
            nm = _bays(fc.L, 1.7)
            for i in range(1, nm):
                u = fc.L * i / nm
                fc.box(k, S["char"], u - 0.05, u + 0.05, 0, 0.08, z0 + 0.75, z1)
                if rng.random() < 0.12:
                    # an open pane: warm room wall flush in the opening, a pendant hanging in front of it
                    fc.box(k, S["warm"], u + 0.06, u + fc.L / nm - 0.06, 0.0, 0.02, z0 + 0.75, z1)
                    um = u + fc.L / nm / 2
                    fc.box(k, S["lamp"], um - 0.14, um + 0.14, 0.02, 0.3, z1 - 1.2, z1 - 0.9)
        z = z1
    # roof: a white crown slab with a little roof garden
    e = inset(n - 1)
    k.box(S["rim"], tx0 + e - 0.18, ty0 + e - 0.18, z, tx1 - e + 0.18, ty1 - e + 0.18, z + 0.35)
    k.box(S["soil"], tx0 + e + 0.3, ty0 + e + 0.3, z + 0.35, tx1 - e - 0.3, ty1 - e - 0.3, z + 0.4)
    for _ in range(3):
        tree(k, rng, rng.uniform(tx0 + e + 1, tx1 - e - 1), rng.uniform(ty0 + e + 1, ty1 - e - 1), z + 0.4,
             min(H - z - 0.6, 3.5), 1.1, trunk_r=0.09, leaf=(112, 158, 66), puffs=2)

    # ---- the planter boxes: staggered, a checkerboard per face, deeper on the street face, fewer on the back
    blooms = (None, None, ((236, 132, 170),), ((246, 242, 230),), ((240, 206, 80),))
    for f_ in range(n):
        e = inset(f_)
        z_top = zg + f_ * sto + 1.05
        if z_top + 3.6 > H:
            continue
        x0, y0, x1, y1 = tx0 + e, ty0 + e, tx1 - e, ty1 - e
        for fc in [_Face(sd, x0, y0, x1, y1) for sd in faces_all]:
            if fc.side == "front" and z_top - 2.4 < zg + 0.4:
                continue                                       # keep the shop canopy clear
            bw = max(3.6, min(6.5, fc.L / 3.2))
            ns = max(1, int((fc.L + 0.8) / bw))
            bw2 = (fc.L + 0.8) / ns
            for j in range(ns):
                if (j + f_) % 2:
                    continue
                if fc.side == "back" and rng.random() < 0.45:
                    continue
                u0 = -0.4 + j * bw2 + 0.25
                u1 = u0 + bw2 - 0.5
                depth = rng.uniform(2.2, 3.0) if fc.side == "front" else rng.uniform(1.9, 2.3) + e * 0.5
                _planter_box(k, S, fc, rng, u0, u1, z_top, depth, drop=min(2.4, sto * 0.7),
                             tree_h=min(5.2, H - z_top), bloom=rng.choice(blooms))

    # ---- a coloured frame up one corner (Tirana's rainbow neighbour, in the block's palette)
    side = rng.choice(("left", "right"))
    fx = tx0 - 0.15 if side == "left" else tx1 + 0.15
    top_z = zg + (n - n_step) * sto
    for i in range(5):
        yy = ty0 + 0.8 + i * 0.9
        if yy > ty1 - 1:
            break
        k.box(S["accent"] if i % 2 == 0 else S["accent2"], fx - 0.1, yy - 0.12, zg + 0.3 + i * 1.1, fx + 0.1, yy + 0.12,
              top_z - i * 1.7)

    # ---- street: trees, flowering shrubs, benches
    for _ in range(int(w / 5) + 1):
        x = rng.uniform(1.2, w - 1.2)
        tree(k, rng, x, rng.uniform(0.9, 1.8), 0, rng.uniform(6, 8.5), rng.uniform(2.0, 2.6), trunk_r=0.2, puffs=3,
             bloom=rng.choice((None, ((236, 132, 170),), ((240, 206, 80),))), bloom_n=3)
    for _ in range(int(w / 2.2)):
        bush(k, rng, rng.uniform(0.8, w - 0.8), rng.uniform(2.0, ty0 - 1.7), 0, rng.uniform(0.45, 0.75), flowers=0.6)
    for _ in range(int((d + w) / 4)):
        x, y = rng.choice(((rng.uniform(0.6, 1.8), rng.uniform(ty0, d - 0.6)),
                           (rng.uniform(w - 1.8, w - 0.6), rng.uniform(ty0, d - 0.6)),
                           (rng.uniform(0.6, w - 0.6), rng.uniform(d - 1.8, d - 0.6))))
        bush(k, rng, x, y, 0, rng.uniform(0.6, 1.0), flowers=0.4)
    return _cap(k)


# =================================================================================================================
# breeze_block_flats: WOHA / tropical breeze-block walk-ups (moodboard b67659d01290, daade5134c59): a warm-grey
# concrete slab block whose upper floors hide behind a screen of breeze blocks over shady loggias, deep black-framed
# glazing on the ground, thin pale trunks and fan palms in a gravel garden; vertical garden slots with vine curtains
# break a long front, the roof is a garden with vines spilling over the parapet.
# =================================================================================================================
def fan_palm(k, rng, x, y, z, h):
    """Fan palm: a slim trunk and a ball of stiff radiating fronds (fringes splayed round, a cushion in the middle)."""
    k.plant("Trunk", "Bark", (128, 116, 98), x, y, z, 0.24, 0.24, h, rng.uniform(0, 360))
    top = z + h
    for i in range(6):
        yaw = i * 60 + rng.uniform(-12, 12)
        a = math.radians(yaw)
        k.plant("Fringe", "Foliage", rng.choice(DEEP), x + math.sin(a) * 0.7, y + math.cos(a) * 0.7, top + 0.7,
                1.3, 1.0, 1.2, yaw + 90)
    k.plant("Puff", "Foliage", rng.choice(DEEP), x, y, top, 0.9, 0.9, 0.7, rng.uniform(0, 360))


def breeze_block_flats(plot):
    rng = plot.rng
    w, d = plot.w, plot.d
    k = Kit(w, d)
    pal = plot.palette
    CON = _mix((150, 144, 136), pal[0], 0.12)
    S = {
        "con": k.mat("RammedEarth", CON),
        "block": k.mat("Plain", _mix(CON, (200, 196, 188), 0.35)),
        "dark": k.mat("Plain", (22, 20, 19)),
        "frame": k.mat("Plain", (30, 30, 32)),
        "glass": k.mat("SolarGlass", (90, 110, 110), 400),
        "lamp": k.mat("Lantern", LANTERN),
        "gravel": k.mat("Path", (196, 184, 160)),
        "lawn": k.mat("GreenRoof", (110, 140, 74)),
        "timber": k.mat("Timber", (132, 90, 58)),
        "door": k.mat("Timber", _mix(pal[2], (120, 70, 40), 0.35)),
        "hedge": k.mat("Foliage", (66, 108, 48)),
    }
    H = min(plot.h_max, 18.0) - 0.2
    X0, X1 = 1.0, w - 1.0
    Y0, Y1 = min(4.5, d * 0.3), d - 1.9
    low = H < 12.5                       # a low cap: a touch tighter storeys so it still gets two floors up
    zg = 3.5 if low else 4.0
    sto = 2.95 if low else 3.2
    n = max(1, min(5, int((H - zg - 0.9) / sto)))
    zt = zg + n * sto
    band = 0.8 if low else 0.95
    par = min(0.9, H - zt)               # parapet height
    L = X1 - X0
    # garden slots: vertical voids in the screen, one per ~16 m (none on short blocks)
    nslot = int(L / 16)
    slots = []
    for j in range(nslot):
        c = X0 + L * (j + 1) / (nslot + 1) + rng.uniform(-1.5, 1.5)
        slots.append((c - 1.6, c + 1.6))

    def in_slot(x):
        return any(a - 0.1 < x < b + 0.1 for a, b in slots)

    # ---- structure: ground floor slab, floor slabs, the dark loggia/back plane, roof
    k.box(S["gravel"], 0, 0, 0, w, Y0, 0.04)
    k.box(S["con"], X0, Y0, 0, X1, Y1, 0.25)
    k.box(S["dark"], X0 + 0.3, Y0 + 1.6, 0.25, X1 - 0.3, Y1 - 0.4, zt)          # interiors / loggia back wall
    k.solid(X0, Y0, 0, X1, Y1, zt)
    # ground floor: piers, deep black-framed glazing, warm rooms
    nb = _bays(L, 3.8)
    bw = L / nb
    for i in range(nb + 1):
        x = X0 + i * bw
        k.box(S["con"], x - 0.3, Y0, 0.25, x + 0.3, Y0 + 1.6, zg)
    for i in range(nb):
        xa, xb = X0 + i * bw + 0.3, X0 + (i + 1) * bw - 0.3
        k.box(S["frame"], xa, Y0 + 1.0, 0.25, xb, Y0 + 1.1, 0.35)
        k.box(S["frame"], xa, Y0 + 1.0, zg - 0.9, xb, Y0 + 1.1, zg - 0.8)
        for t in (0.0, 0.5, 1.0):
            xm = xa + (xb - xa) * t
            k.box(S["frame"], xm - 0.04, Y0 + 1.0, 0.25, xm + 0.04, Y0 + 1.1, zg - 0.8)
        if rng.random() < 0.3:
            k.box(S["door"], xa + 0.1, Y0 + 1.03, 0.35, (xa + xb) / 2 - 0.06, Y0 + 1.08, zg - 0.9)
        if rng.random() < 0.65:
            lx = (xa + xb) / 2 + rng.uniform(-0.6, 0.6)
            k.box(S["timber"], xa, Y0 + 1.56, 0.25, xb, Y0 + 1.6, zg - 0.8)
            k.box(S["lamp"], lx - 0.15, Y0 + 1.3, zg - 1.3, lx + 0.15, Y0 + 1.5, zg - 1.05)
    k.box(S["con"], X0, Y0, zg - 0.8, X1, Y0 + 1.0, zg)                          # lintel band
    # ---- upper floors: solid band at each slab, breeze-block screen between, loggias behind
    for f_ in range(n):
        z0 = zg + f_ * sto
        k.box(S["con"], X0 - 0.1, Y0 - 0.15, z0, X1 + 0.1, Y0 + 0.4, z0 + band)
        # lit rooms at the back of the loggia (glimpsed through the blocks)
        for i in range(_bays(L, 2.8)):
            if rng.random() < 0.35:
                xa = X0 + L * (i + 0.2) / _bays(L, 2.8)
                k.box(S["timber"], xa, Y0 + 1.55, z0 + band, xa + 1.6, Y0 + 1.59, z0 + sto)
                k.box(S["lamp"], xa + 0.65, Y0 + 1.1, z0 + sto - 0.75, xa + 0.95, Y0 + 1.4, z0 + sto - 0.45)
        # horizontal rails of the block courses
        rows = 6
        for r in range(1, rows if not low else 5):
            zr = z0 + band + (sto - band) * r / rows
            for a, b in _gaps(X0, X1, slots):
                k.box(S["block"], a, Y0 - 0.02, zr - 0.03, b, Y0 + 0.28, zr + 0.03)
    k.box(S["con"], X0 - 0.1, Y0 - 0.15, zt, X1 + 0.1, Y0 + 0.4, zt + par)        # parapet band
    # vertical webs of the blocks, one op each running the full screen height (the bands sit in front)
    nf = _bays(L, 0.34)
    for i in range(1, nf):
        x = X0 + L * i / nf
        if in_slot(x):
            continue
        k.box(S["block"], x - 0.035, Y0 - 0.02, zg, x + 0.035, Y0 + 0.28, zt)
    # ---- garden slots: open loggia floors with planters and long vine curtains
    for a, b in slots:
        k.box(S["con"], a - 0.15, Y0 - 0.15, zg, a + 0.15, Y0 + 1.6, zt + par)
        k.box(S["con"], b - 0.15, Y0 - 0.15, zg, b + 0.15, Y0 + 1.6, zt + par)
        for f_ in range(n + 1):
            z0 = zg + f_ * sto
            trough(k, rng, a + 0.4, b - 0.4, Y0 + 0.2, z0 + band, density=0.9, flowers=0.5, r=0.45)
            drape(k, rng, a + 0.3, b - 0.3, Y0 - 0.2, z0 + band + 0.1, rng.uniform(2.2, 3.4), yaw=180, step=0.55,
                  gap=0.2, flowers=FLOWER if rng.random() < 0.5 else None)
            if f_ < n:
                k.plant("Fringe", "Foliage", rng.choice(DEEP), (a + b) / 2, Y0 + 1.5, z0 + sto, 1.6, 1.0, 1.4, 180)
    # ---- ends and back: board-formed walls with punched windows and planter balconies on the back
    k.box(S["con"], X0, Y0, zg, X0 + 0.3, Y1, zt + par)
    k.box(S["con"], X1 - 0.3, Y0, zg, X1, Y1, zt + par)
    k.box(S["con"], X0, Y1 - 0.3, 0.25, X1, Y1, zt + par)
    nbk = _bays(L, 3.0)
    for f_ in range(n + 1):
        z0 = 0.25 if f_ == 0 else zg + (f_ - 1) * sto
        for i in range(nbk):
            xa = X0 + L * i / nbk + 0.7
            xb = X0 + L * (i + 1) / nbk - 0.7
            lit_ = rng.random() < 0.3
            k.box(S["timber"] if lit_ else S["dark"], xa, Y1, z0 + 0.9, xb, Y1 + 0.02, z0 + 2.6)
            if lit_:
                xm = (xa + xb) / 2
                k.box(S["lamp"], xm - 0.13, Y1 + 0.02, z0 + 2.0, xm + 0.13, Y1 + 0.28, z0 + 2.3)
        if f_ > 0:
            # deck-access gallery: slab, block balustrade topped by a planter hedge, vines spilling, flowers
            k.box(S["con"], X0, Y1, z0 - 0.15, X1, Y1 + 1.4, z0 + 0.05)
            k.box(S["block"], X0, Y1 + 1.25, z0 + 0.05, X1, Y1 + 1.4, z0 + 0.95)
            k.box(S["hedge"], X0 + 0.2, Y1 + 1.1, z0 + 0.95, X1 - 0.2, Y1 + 1.45, z0 + 1.3)
            for q in range(int(L / 3.2)):
                xq = X0 + L * (q + rng.uniform(0.2, 0.8)) / int(L / 3.2)
                if rng.random() < 0.5:
                    k.plant("Fringe", "Foliage", rng.choice(LEAVES), xq, Y1 + 1.45, z0 + 1.0, 1.4, 1.0,
                            rng.uniform(1.2, 2.4), 0)
                if rng.random() < 0.3:
                    k.plant("Blob", "Foliage", rng.choice(BOUGAIN + FLOWER), xq, Y1 + 1.28, z0 + 1.3, 0.5, 0.3, 0.25)
    # climbers up the back wall between the windows
    for i in range(nbk + 1):
        if rng.random() < 0.45:
            x = X0 + L * i / nbk
            hh = rng.uniform(3.0, zt)
            k.plant("Puff", "Foliage", rng.choice(DEEP), x, Y1 + 0.2, 0.1, rng.uniform(0.6, 0.9), 0.35, hh)
            if rng.random() < 0.5:
                k.plant("Blob", "Foliage", rng.choice(BOUGAIN + FRANGI), x, Y1 + 0.35, hh * 0.85, 0.4, 0.3, 0.35)
    # ---- roof garden: planters at the parapet with vines dropping over the front, a timber pergola, palms
    k.box(S["lawn"], X0 + 0.3, Y0 + 0.4, zt, X1 - 0.3, Y1 - 0.3, zt + 0.08)
    trough(k, rng, X0 + 0.6, X1 - 0.6, Y0 + 0.9, zt + 0.1, density=0.7, flowers=0.5, r=0.55)
    drape(k, rng, X0 + 0.5, X1 - 0.5, Y0 - 0.25, zt + par - 0.05, 2.0, yaw=180, step=1.0, gap=0.45)
    pw0, pw1 = X0 + L * 0.2, X0 + L * 0.2 + min(10.0, L * 0.35)
    ph = min(2.6, H - zt - 0.2)                                  # pergola height under the cap
    for x in (pw0, (pw0 + pw1) / 2, pw1):
        for y in (Y0 + 2.5, Y1 - 1.5):
            k.box(S["timber"], x - 0.1, y - 0.1, zt, x + 0.1, y + 0.1, zt + ph)
    nslat = int((pw1 - pw0) / 0.5)
    for i in range(nslat + 1):
        x = pw0 + (pw1 - pw0) * i / nslat
        k.box(S["timber"], x - 0.04, Y0 + 2.2, zt + ph, x + 0.04, Y1 - 1.2, zt + ph + 0.12)
    drape(k, rng, pw0, pw1, Y0 + 2.3, zt + ph, min(1.0, ph - 1.2), yaw=180, step=0.9, gap=0.5, flowers=BOUGAIN)
    for _ in range(max(1, int(L / 14))):
        palm(k, rng, rng.uniform(X0 + 2, X1 - 2), rng.uniform(Y1 - 3, Y1 - 1.2), zt + 0.08,
             min(rng.uniform(2.5, 3.5), H - zt - 1.0))
    # ---- the gravel garden: thin pale trunks rising up the screen, fan palms, ferns, big-leaf shrubs
    nt = max(3, int(w / 4.2))
    for i in range(nt):
        x = X0 + L * (i + rng.uniform(0.2, 0.8)) / nt
        y = rng.uniform(0.8, Y0 - 0.9)
        r = rng.random()
        if r < 0.55:
            slender_tree(k, rng, x, y, 0, min(H - 1.2, rng.uniform(zg + 4, zt + 1.5)))
        elif r < 0.8:
            fan_palm(k, rng, x, y, 0, rng.uniform(2.8, 5.0))
        else:
            tree(k, rng, x, y, 0, rng.uniform(6, 9), 2.4, trunk_r=0.2, puffs=3,
                 bloom=rng.choice((((236, 132, 170),), ((226, 70, 46),))), bloom_n=3)
    for _ in range(int(w / 1.8)):
        x, y = rng.uniform(0.6, w - 0.6), rng.uniform(0.5, Y0 - 0.3)
        if rng.random() < 0.5:
            fern(k, rng, x, y, 0, rng.uniform(0.8, 1.2))
        else:
            bush(k, rng, x, y, 0, rng.uniform(0.45, 0.8), flowers=0.4)
    for _ in range(int(d / 2.5)):
        bush(k, rng, rng.choice((0.5, w - 0.5)), rng.uniform(Y0, d - 0.5), 0, rng.uniform(0.5, 0.8), flowers=0.3)
    return _cap(k)


# =================================================================================================================
# kampung_terraces: WOHA, Kampung Admiralty, Singapore 2017 (the "vertical kampung"): a shaded public plaza under
# the first deck, then green terraces stepping up like a hillside park (lawns, allotments, trees, planters spilling
# vines over every edge, timber-louvred community rooms glowing under each step) and slim residential bars with
# solar roofs on top.
# =================================================================================================================
def _hedge(k, S, rng, x0, x1, y, z, along_y=False, w=0.9, h=0.7, puffs=0.35, vines=0.45, out=-1, flowers=FLOWER):
    """A planter-edge hedge (one op) with a few cushions, flowers and vines dropping over the outside."""
    if along_y:
        k.box(S["hedge"], y - w / 2, min(x0, x1), z, y + w / 2, max(x0, x1), z + h)
    else:
        k.box(S["hedge"], min(x0, x1), y - w / 2, z, max(x0, x1), y + w / 2, z + h)
    L = abs(x1 - x0)
    for i in range(int(L / 2.6)):
        t = min(x0, x1) + L * (i + rng.uniform(0.2, 0.8)) / int(L / 2.6)
        px, py = (y, t) if along_y else (t, y)
        if rng.random() < puffs:
            bush(k, rng, px, py, z + h * 0.6, rng.uniform(0.55, 0.85), flowers=0.6, fcols=flowers)
        if rng.random() < vines:
            ox, oy = ((out * (w / 2 + 0.05), 0) if along_y else (0, out * (w / 2 + 0.05)))
            k.plant("Fringe", "Foliage", rng.choice(LEAVES), px + ox, py + oy, z + h, rng.uniform(1.2, 1.8), 1.0,
                    rng.uniform(1.4, 2.8), (90 if out < 0 else 270) if along_y else (180 if out < 0 else 0))


def kampung_terraces(plot):
    rng = plot.rng
    w, d = plot.w, plot.d
    k = Kit(w, d)
    pal = plot.palette
    S = {
        "con": k.mat("Plain", (222, 216, 202)),
        "white": k.mat("Plain", (236, 232, 222)),
        "timber": k.mat("Timber", (150, 100, 62)),
        "glass": k.mat("SolarGlass", (100, 124, 130), 400),
        "dark": k.mat("Plain", (28, 24, 22)),
        "lamp": k.mat("Lantern", LANTERN),
        "lawn": k.mat("GreenRoof", (118, 152, 76)),
        "hedge": k.mat("Foliage", (70, 112, 50)),
        "stone": k.mat("PermeableStone", (210, 200, 182)),
        "solar": k.mat("SolarGlass", (46, 60, 92)),            # scale 0: the panel grid
        "awn": k.mat("Fabric", _mix(pal[2], (220, 120, 70), 0.3)),
        "accent": k.mat("Fabric", _mix(pal[1], (90, 150, 140), 0.3)),
    }
    S["soil"] = S["timber"]
    H = min(plot.h_max, 24.0) - 0.2
    X0, X1, Y0, Y1 = 1.5, w - 1.5, 2.0, d - 1.5
    dens = min(1.0, (2800.0 / (w * d)) ** 0.5)  # big sites: sparser edge cushions, same character
    zd = 5.2                                    # first deck over the public plaza
    tier_h = 3.6
    fd = min(11.0, max(9.0, d * 0.22))          # depth of the residential bar at the back
    # decks: the plaza roof plus up to two more steps, as many as the height and depth allow with >= 1 flat floor
    n_t = 1
    while n_t < 3 and zd + n_t * tier_h + 3.1 + 1.4 <= H and (d - fd - Y0 - 3.5) / (n_t + 1) >= 6.0:
        n_t += 1
    flats_floors = max(1, min(4, int((H - zd - (n_t - 1) * tier_h - 1.4) / 3.1)))
    td = (Y1 - fd - Y0 - 2.0) / n_t             # depth of each terrace step
    side = min(3.5, (X1 - X0) * 0.05)           # each step also pulls in at the sides: a green hill
    tiers = []
    for i in range(n_t):
        tiers.append((X0 + i * side, Y0 + i * td, X1 - i * side, zd + i * tier_h))

    # ---- ground: paving, enclosed market/hawker hall at the back, open plaza under the deck at the front
    k.box(S["stone"], 0.4, 0.0, 0, w - 0.4, d - 0.4, 0.1)
    plaza_d = min(14.0, (Y1 - Y0) * 0.45)
    k.box(S["glass"], X0 + 1.0, Y0 + plaza_d, 0.1, X1 - 1.0, Y1 - 0.5, zd - 0.6)
    k.box(S["con"], X0, Y1 - 0.5, 0.1, X1, Y1, zd)
    k.box(S["con"], X0, Y0 + plaza_d, 0.1, X0 + 1.0, Y1, zd)
    k.box(S["con"], X1 - 1.0, Y0 + plaza_d, 0.1, X1, Y1, zd)
    k.solid(X0, Y0 + plaza_d, 0, X1, Y1, zd)
    nb = _bays(X1 - X0 - 2, 4.0)
    for i in range(nb):                         # shopfront lights + awnings along the hall
        xa = X0 + 1.0 + (X1 - X0 - 2) * i / nb
        xb = xa + (X1 - X0 - 2) / nb
        k.box(S["timber"], xa - 0.06, Y0 + plaza_d - 0.12, 0.1, xa + 0.06, Y0 + plaza_d, zd - 0.6)
        lit_ = rng.random() < 0.7               # open shopfronts: warm timber-lined stalls with pendants
        k.box(S["timber"] if lit_ else S["dark"], xa + 0.1, Y0 + plaza_d - 0.08, 0.1, xb - 0.1, Y0 + plaza_d - 0.04,
              zd - 0.6)
        if lit_:
            for q in range(2):
                lx = xa + (xb - xa) * (0.3 + 0.4 * q)
                k.box(S["lamp"], lx - 0.14, Y0 + plaza_d - 0.45, 2.5, lx + 0.14, Y0 + plaza_d - 0.17, 2.8)
        if rng.random() < 0.6:
            k.obox(S["awn"] if i % 2 else S["accent"], (xa + xb) / 2, Y0 + plaza_d - 0.9, 3.0, (xb - xa) / 2 - 0.2,
                   0.9, 0.04, 0, 0, -18)
    # plaza: columns, a boarded soffit, lanterns, tables, planters, and a light-well with a tree growing up through
    k.box(S["timber"], X0, Y0, zd - 0.6, X1, Y1, zd - 0.5)
    k.box(S["con"], X0 - 0.2, Y0 - 0.2, zd - 0.5, X1 + 0.2, Y1, zd)
    ncx = _bays(X1 - X0, 8.0)
    wx = X0 + (X1 - X0) * (ncx // 2 + 0.5) / ncx      # the light-well, between two column lines
    wy = Y0 + plaza_d * 0.5
    for i in range(ncx + 1):
        x = X0 + 0.6 + (X1 - X0 - 1.2) * i / ncx
        for y in (Y0 + 0.8, Y0 + plaza_d * 0.55 + 0.6):
            k.cyl(S["white"], x, y, 0.1, 0.32, 0.32, zd - 0.7, segs=12)
            k.solid(x - 0.35, y - 0.35, 0, x + 0.35, y + 0.35, zd)
    for i in range(ncx):
        x = X0 + (X1 - X0) * (i + 0.5) / ncx
        for y in (Y0 + plaza_d * 0.3, Y0 + plaza_d * 0.75):
            k.box(S["dark"], x - 0.01, y - 0.01, zd - 1.6, x + 0.01, y + 0.01, zd - 0.6)
            k.box(S["lamp"], x - 0.25, y - 0.25, zd - 2.0, x + 0.25, y + 0.25, zd - 1.6)
            if abs(x - wx) > 2 and rng.random() < 0.7:          # long communal tables + benches
                k.box(S["timber"], x - 1.6, y - 0.45, 0.75, x + 1.6, y + 0.45, 0.82)
                k.box(S["timber"], x - 1.5, y - 0.4, 0.1, x - 1.4, y + 0.4, 0.75)
                k.box(S["timber"], x + 1.4, y - 0.4, 0.1, x + 1.5, y + 0.4, 0.75)
                for by in (y - 0.85, y + 0.85):
                    k.box(S["timber"], x - 1.6, by - 0.18, 0.42, x + 1.6, by + 0.18, 0.48)
    # light-well: a round planter with a big tree up through a hole in the deck (ring of white around it)
    k.cyl(S["con"], wx, wy, 0.1, 2.2, 2.2, 0.6, segs=16)
    k.cyl(S["lawn"], wx, wy, 0.6, 2.0, 2.0, 0.05, segs=16)
    tree(k, rng, wx, wy, 0.65, min(zd + 6.5, H - 2), 3.2, trunk_r=0.3, puffs=4,
         bloom=((236, 132, 170), (246, 170, 196)), bloom_n=3)
    k.cyl(S["white"], wx, wy, zd - 0.6, 3.3, 3.3, 0.75, segs=20, caps=False)

    # ---- terraces
    for i, (tx0, ty0, tx1, z) in enumerate(tiers):
        last = i == n_t - 1
        zn = z + tier_h
        # deck surface (lawn) and its front + side edges
        k.box(S["lawn"], tx0 + 0.3, ty0 + 0.3, z, tx1 - 0.3, Y1 - 0.3, z + 0.06)
        _hedge(k, S, rng, tx0 + 0.5, tx1 - 0.5, ty0 + 0.55, z, flowers=FLOWER + BOUGAIN, puffs=0.35 * dens,
               vines=0.45 * dens)
        if i == 0:   # vines off the back edge of the plaza deck too
            for q in range(int((tx1 - tx0) / 5)):
                k.plant("Fringe", "Foliage", rng.choice(LEAVES), tx0 + (tx1 - tx0) * (q + rng.random()) / int((tx1 - tx0) / 5),
                        Y1 + 0.1, z + 0.1, 1.6, 1.0, rng.uniform(1.5, 3.0), 0)
        _hedge(k, S, rng, ty0 + 1.0, Y1 - 0.5, tx0 + 0.55, z, along_y=True, puffs=0.25 * dens, vines=0.4 * dens, out=-1)
        _hedge(k, S, rng, ty0 + 1.0, Y1 - 0.5, tx1 - 0.55, z, along_y=True, puffs=0.25 * dens, vines=0.4 * dens, out=1)
        # the riser under the next step: timber-louvred, glazed, lit community rooms
        if not last:
            nx0, ny0, nx1, _ = tiers[i + 1]
            k.box(S["con"], nx0 - 0.2, ny0 - 0.2, zn - 0.5, nx1 + 0.2, Y1, zn)      # next deck slab edge
            k.box(S["glass"], nx0, ny0 + 0.6, z, nx1, Y1 - 0.4, zn - 0.5)
            k.solid(nx0, ny0, z, nx1, Y1, zn)
            nl = _bays(nx1 - nx0, 0.9)
            for j in range(nl + 1):
                x = nx0 + (nx1 - nx0) * j / nl
                k.box(S["timber"], x - 0.05, ny0 + 0.2, z + 0.06, x + 0.05, ny0 + 0.4, zn - 0.5)
                if j < nl and j % 3 == 0 and rng.random() < 0.3:   # open bay: warm room + pendant behind louvres
                    x2 = x + (nx1 - nx0) / nl * 2.0
                    k.box(S["timber"], x + 0.1, ny0 + 0.56, z + 0.06, x2, ny0 + 0.6, zn - 0.5)
                    k.box(S["lamp"], (x + x2) / 2 - 0.13, ny0 + 0.42, zn - 1.3, (x + x2) / 2 + 0.13, ny0 + 0.55, zn - 1.0)
            # garden on this step: allotment beds, a pergola, a few trees and benches
            gy0, gy1 = ty0 + 1.4, ny0 - 0.6
            if gy1 - gy0 > 2.0:
                xs = tx0 + 1.5
                while xs < tx1 - 4:
                    kind = rng.random()
                    seg = rng.uniform(6.0, 11.0)
                    xe = min(tx1 - 1.5, xs + seg)
                    if kind < 0.4:                       # allotment rows
                        nrow = max(1, int((gy1 - gy0) / 1.3))
                        for r in range(nrow):
                            yy = gy0 + (gy1 - gy0) * (r + 0.5) / nrow
                            k.box(S["soil"], xs, yy - 0.4, z, xe, yy + 0.4, z + 0.35)
                            k.box(S["hedge"], xs + 0.2, yy - 0.25, z + 0.35, xe - 0.2, yy + 0.25, z + 0.62)
                            if rng.random() < 0.5:
                                c = rng.choice(((214, 72, 84), (240, 206, 80), (236, 120, 60), (170, 96, 190)))
                                for q in range(int((xe - xs) / 3.6)):
                                    k.plant("Blob", "Foliage", c, xs + 1.2 + q * 3.6, yy, z + 0.6, 0.6, 0.26, 0.15)
                    elif kind < 0.7:                     # trees and flowering shrubs on the lawn
                        for q in range(max(1, int(seg / 5))):
                            tree(k, rng, rng.uniform(xs + 1, xe - 1), rng.uniform(gy0 + 0.6, gy1 - 0.6), z + 0.06,
                                 rng.uniform(4.0, 6.0), rng.uniform(1.8, 2.4), puffs=3,
                                 bloom=rng.choice((None, ((236, 132, 170),), ((240, 206, 80),), ((226, 70, 46),))),
                                 bloom_n=2)
                        bush(k, rng, rng.uniform(xs + 1, xe - 1), gy1 - 0.3, z + 0.06, 0.7, flowers=0.8)
                    else:                                # a timber pergola over benches, vines on top
                        for x in (xs + 0.3, xe - 0.3):
                            for y in (gy0 + 0.3, gy1 - 0.3):
                                k.box(S["timber"], x - 0.09, y - 0.09, z, x + 0.09, y + 0.09, z + 2.6)
                        ns = int((xe - xs) / 0.6)
                        for q in range(ns + 1):
                            x = xs + (xe - xs) * q / ns
                            k.box(S["timber"], x - 0.04, gy0, z + 2.6, x + 0.04, gy1, z + 2.72)
                        k.box(S["timber"], xs + 0.6, (gy0 + gy1) / 2 - 0.2, z + 0.42, xe - 0.6, (gy0 + gy1) / 2 + 0.2,
                              z + 0.5)
                        drape(k, rng, xs, xe, gy0, z + 2.6, 1.1, yaw=180, step=1.1, gap=0.35, flowers=BOUGAIN)
                    xs = xe + rng.uniform(1.0, 2.5)

    # ---- residential bar(s) on the top step, with balconies, louvres and solar roofs
    tx0, ty0, tx1, z = tiers[-1]
    zf = z + 0.06
    fy0 = Y1 - fd
    bars = [(tx0 + 0.5, fy0, tx1 - 0.5, Y1)]
    if tx1 - tx0 > 50:                           # long sites: split into two bars with a garden gap
        mid = (tx0 + tx1) / 2 + rng.uniform(-4, 4)
        bars = [(tx0 + 0.5, fy0, mid - 3.5, Y1), (mid + 3.5, fy0, tx1 - 0.5, Y1)]
    # the top park in front of the bars
    gy0, gy1 = ty0 + 1.4, fy0 - 2.2
    if gy1 - gy0 > 1.5:
        for q in range(max(2, int((tx1 - tx0) / 7))):
            x = rng.uniform(tx0 + 2, tx1 - 2)
            tree(k, rng, x, rng.uniform(gy0 + 0.6, max(gy0 + 0.7, gy1)), zf, rng.uniform(4.5, 6.5), 2.2, puffs=3,
                 bloom=rng.choice((None, ((236, 132, 170),), ((240, 206, 80),))), bloom_n=2)
        for q in range(int((tx1 - tx0) / 6)):
            bush(k, rng, rng.uniform(tx0 + 1.5, tx1 - 1.5), rng.uniform(gy0, max(gy0 + 0.1, gy1)), zf,
                 rng.uniform(0.5, 0.8), flowers=0.6)
    sto = 3.1
    for (bx0, by0, bx1, by1) in bars:
        ztop = zf + flats_floors * sto
        k.box(S["con"], bx0, by0 + 1.6, zf, bx1, by1, ztop)
        k.solid(bx0, by0, zf, bx1, by1, ztop)
        nbw = _bays(bx1 - bx0, 2.6)
        for f_ in range(flats_floors):                 # back windows, some lit, a few sills of flowers
            z0 = zf + f_ * sto
            for j in range(nbw):
                xa = bx0 + (bx1 - bx0) * j / nbw + 0.6
                xb = bx0 + (bx1 - bx0) * (j + 1) / nbw - 0.6
                lit_ = rng.random() < 0.25
                k.box(S["timber"] if lit_ else S["dark"], xa, by1, z0 + 0.9, xb, by1 + 0.03, z0 + 2.4)
                if lit_:
                    k.box(S["lamp"], (xa + xb) / 2 - 0.13, by1 + 0.03, z0 + 1.8, (xa + xb) / 2 + 0.13, by1 + 0.25, z0 + 2.1)
                if rng.random() < 0.25:
                    k.box(S["white"], xa - 0.1, by1, z0 + 0.75, xb + 0.1, by1 + 0.4, z0 + 0.9)
                    bush(k, rng, (xa + xb) / 2, by1 + 0.25, z0 + 0.9, 0.38, flowers=0.9)
        for f_ in range(flats_floors):
            z0 = zf + f_ * sto
            # balcony slab, glass behind, timber louvre screens on some bays, planters with spill
            k.box(S["white"], bx0 - 0.1, by0, z0 + sto - 0.25, bx1 + 0.1, by0 + 1.7, z0 + sto)
            k.box(S["glass"], bx0, by0 + 1.55, z0, bx1, by0 + 1.6, z0 + sto - 0.25)
            nbb = _bays(bx1 - bx0, 3.4)
            for j in range(nbb):
                xa = bx0 + (bx1 - bx0) * j / nbb
                xb = xa + (bx1 - bx0) / nbb
                k.box(S["white"], xa - 0.12, by0, z0, xa + 0.12, by0 + 1.6, z0 + sto - 0.25)
                r = rng.random()
                if r < 0.35:
                    for q in range(6):
                        x = xa + 0.4 + (xb - xa - 0.8) * q / 5
                        k.box(S["timber"], x - 0.05, by0 + 0.05, z0 + 0.1, x + 0.05, by0 + 0.2, z0 + sto - 0.3)
                elif r < 0.55:
                    k.box(S["timber"], xa + 0.2, by0 + 1.5, z0, xb - 0.2, by0 + 1.54, z0 + sto - 0.25)
                    k.box(S["lamp"], (xa + xb) / 2 - 0.13, by0 + 1.1, z0 + 1.9, (xa + xb) / 2 + 0.13, by0 + 1.36, z0 + 2.2)
                if rng.random() < 0.55:
                    k.box(S["accent"] if rng.random() < 0.3 else S["white"], xa + 0.2, by0 - 0.1, z0, xb - 0.2,
                          by0 + 0.3, z0 + 0.9)
                    bush(k, rng, (xa + xb) / 2, by0 + 0.1, z0 + 0.9, 0.5, flowers=0.6)
                    if rng.random() < 0.6:
                        k.plant("Fringe", "Foliage", rng.choice(LEAVES), (xa + xb) / 2 + rng.uniform(-0.6, 0.6),
                                by0 - 0.15, z0 + 0.95, 1.3, 1.0, rng.uniform(1.2, 2.4), 180)
        # roof: parapet, solar panels tilted to the sun, a little roof garden strip at the front
        k.box(S["white"], bx0 - 0.1, by0, ztop, bx1 + 0.1, by1, ztop + 0.3)
        npan = _bays(bx1 - bx0 - 2, 2.2)
        ph2 = (by1 - by0 - 4) / 4
        for j in range(npan):
            x = bx0 + 1 + (bx1 - bx0 - 2) * (j + 0.5) / npan
            for row in (0, 1):
                yc = by0 + 2.5 + ph2 + row * (2 * ph2 + 0.5)
                k.obox(S["solar"], x, yc, ztop + 0.8, (bx1 - bx0 - 2) / npan / 2 - 0.1, ph2, 0.05, 0, 0, -15)
        _hedge(k, S, rng, bx0 + 0.6, bx1 - 0.6, by0 + 0.6, ztop + 0.3, puffs=0.3, vines=0.6)
    # ---- the street edge: trees and flowering shrubs in front of the plaza
    for q in range(int(w / 9)):
        tree(k, rng, X0 + (X1 - X0) * (q + 0.5) / int(w / 9), 0.9, 0.1, rng.uniform(5.5, 7.5), 2.2, puffs=3,
             bloom=rng.choice((None, ((236, 132, 170),), ((226, 70, 46),))), bloom_n=2)
    for q in range(int(w / 5)):
        bush(k, rng, rng.uniform(1, w - 1), rng.uniform(0.3, 1.4), 0.1, rng.uniform(0.5, 0.8), flowers=0.5)
    return _cap(k)


def _gaps(a, b, slots):
    """Spans of [a, b] outside the slots."""
    out, cur = [], a
    for s0, s1 in sorted(slots):
        if s0 > cur:
            out.append((cur, s0))
        cur = max(cur, s1)
    if cur < b:
        out.append((cur, b))
    return out


KINDS = {"bawa_courtyard": bawa_courtyard, "oasia_tower": oasia_tower, "vertical_forest": vertical_forest,
         "breeze_block_flats": breeze_block_flats, "kampung_terraces": kampung_terraces}
SIZES = {"bawa_courtyard": {"w": (24, 44), "d": (20, 34), "h": (6, 9), "floors": (1, 2), "use": "homes"},
         "oasia_tower": {"w": (18, 30), "d": (18, 30), "h": (20, 36), "floors": (5, 10), "use": "hotel + homes"},
         "vertical_forest": {"w": (20, 30), "d": (20, 30), "h": (24, 36), "floors": (6, 9), "use": "homes + shops"},
         "breeze_block_flats": {"w": (24, 60), "d": (12, 18), "h": (10, 18), "floors": (3, 5), "use": "homes + studios"},
         "kampung_terraces": {"w": (40, 90), "d": (30, 60), "h": (14, 24), "floors": (3, 6),
                              "use": "market + community + homes"}}
