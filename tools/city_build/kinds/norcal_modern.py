"""Northern California mid-century modern houses, faithful to famous originals, set in lush gardens.

    eichler_atrium   Claude Oakland / Anshen + Allen for Joseph Eichler, atrium model, Palo Alto & Terra Linda 1955-64
    sea_ranch        Moore Lyndon Turnbull Whitaker (MLTW), Sea Ranch Condominium One, Sonoma coast 1965
    hedgerow_house   Joseph Esherick, Hedgerow Houses, Sea Ranch 1966
    hanna_honeycomb  Frank Lloyd Wright, Hanna-Honeycomb House, Stanford 1937
    eichler_x100     A. Quincy Jones & Frederick Emmons for Eichler, X-100 steel house, San Mateo 1956

Frame (kit.py): x along the street 0..w, y away from the street 0..d (front line y = 0), z up, metres.
Deterministic from plot.seed; accents from plot.palette. Shared house helpers (glazing, interiors, trees) come
from california_modern.Ctx so both families look like one city.
"""
import math

from .california_modern import Ctx, clamp, lerp, mix, vivid, tilt_x, LAMP, JACARANDA, MAPLE
from .kit import WHITE, DARK_STEEL, LEAF, FLOWER

REDWOOD = (146, 96, 66)          # oiled redwood siding
WEATHERED = (122, 110, 98)       # Sea Ranch silvered redwood
SHINGLE = (96, 92, 88)           # weathered cedar shingle roofs
GROOVE = (58, 46, 38)            # shadow lines between boards
FASCIA = (232, 228, 216)
CONC = (206, 200, 188)
CYPRESS = ((40, 70, 50), (48, 80, 54), (36, 62, 46))
GOLD = ((200, 176, 112), (184, 164, 102), (170, 160, 98), (150, 150, 92))
LUPINE = (122, 104, 206)
POPPY = (246, 146, 40)
CEANOTHUS = (96, 120, 214)
AGAPANTHUS = (120, 140, 230)
CITRUS = (246, 168, 40)
EICHLER_DOORS = ((236, 120, 40), (240, 196, 50), (40, 160, 160), (200, 60, 50), (90, 150, 200))
BRICK_HANNA = (178, 112, 86)
COPPER = (98, 150, 128)          # patinated copper
COPPER_DARK = (122, 96, 70)
CYPRESS_WOOD = (156, 120, 86)    # Hanna board-and-batten (cypress)
X100_COLS = ((236, 176, 40), (214, 84, 54), (54, 120, 170), (70, 150, 120), (240, 236, 226))


# ======================================================================================================
# shared pieces
# ======================================================================================================
def boards(k, wall, line, axis, a0, a1, at, z0, z1, out, t=0.16, pitch=0.3, top=None, horiz=False):
    """A board-clad wall whose OUTER face is at `at` (out = -1/+1: the outward side along y for axis 'x', along x for
    'y'), with thin shadow lines: vertical boards (grooved plywood / redwood) or, with horiz, horizontal battens.
    top(a) -> z gives a sloped top (shed walls); the wall is then drawn as a quad + the lines follow it."""
    if top is None:
        if axis == "x":
            k.box(wall, a0, at if out < 0 else at - t, z0, a1, at + t if out < 0 else at, z1)
        else:
            k.box(wall, at if out < 0 else at - t, a0, z0, at + t if out < 0 else at, a1, z1)
    else:
        za, zb = top(a0), top(a1)
        if axis == "x":
            k.quad(wall, (a0, at, z0), (a1, at, z0), (a1, at, zb), (a0, at, za), (0, out, 0))
        else:
            k.quad(wall, (at, a0, z0), (at, a1, z0), (at, a1, zb), (at, a0, za), (out, 0, 0))
    e, g = 0.012 * out, 0.022
    if horiz:
        n = max(1, int((z1 - z0) / pitch))
        for i in range(1, n + 1):
            z = z0 + i * (z1 - z0) / (n + 0.5)
            if axis == "x":
                k.box(line, a0, at + e - 0.02 * out, z, a1, at + e, z + 0.05)
            else:
                k.box(line, at + e - 0.02 * out, a0, z, at + e, a1, z + 0.05)
        return
    n = max(1, int((a1 - a0) / pitch))
    for i in range(1, n):
        a = a0 + i * (a1 - a0) / n
        zt = top(a) if top else z1
        if axis == "x":
            k.box(line, a - g / 2, min(at, at + e), z0, a + g / 2, max(at, at + e), zt)
        else:
            k.box(line, min(at, at + e), a - g / 2, z0, max(at, at + e), a + g / 2, zt)


def cypress(c, x, y, h, lean=0.0, flat=1.0, wind=0.0):
    """Monterey cypress: a dark, dense, wind-sheared crown in flat tiers on a short leaning trunk (lean in degrees;
    the upper crown is pushed downwind along +x by `wind` metres)."""
    k, r = c.k, c.r
    th = h * 0.3
    k.plant("Trunk", "Bark", (92, 76, 64), x, y, 0, 0.42, 0.42, th + 0.8, r.uniform(0, 360), roll=lean)
    col = r.choice(CYPRESS)
    tiers = 3 if h > 5 else 2
    sz = clamp(h / 7.0, 0.6, 1.25) * flat
    for i in range(tiers):
        f = i / max(1, tiers - 1)
        zz = lerp(h * 0.38, h * 0.82, f)
        s = (2.5 - 0.7 * f) * sz
        for _j in range(2):
            k.plant("Puff", "Foliage", col, x + wind * f + r.uniform(-0.5, 0.5), y + r.uniform(-0.5, 0.5), zz,
                    s * r.uniform(0.9, 1.1), s * r.uniform(0.8, 1.0), s * 0.5, r.uniform(0, 360))


def hedgerow(c, x0, y0, x1, y1, h, wind=0.0):
    """A row of cypress (the Sea Ranch windbreaks) from (x0, y0) to (x1, y1): overlapping crowns over a dense skirt."""
    k, r = c.k, c.r
    L = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(L / 2.6))
    for i in range(n):
        t = (i + 0.5) / n
        cypress(c, lerp(x0, x1, t) + r.uniform(-0.3, 0.3), lerp(y0, y1, t) + r.uniform(-0.3, 0.3), h * r.uniform(0.8, 1.0),
                lean=r.uniform(-6, 6), wind=wind)
    for i in range(int(L / 1.8)):
        t = (i + 0.5) / int(L / 1.8)
        k.plant("Puff", "Foliage", CYPRESS[1], lerp(x0, x1, t), lerp(y0, y1, t), 0.6, 1.5, 1.5, 1.2, r.uniform(0, 360))


def meadow(c, x0, y0, x1, y1, n, flowers=0.25, z=0.0):
    """Coastal meadow: golden bunch grass, a few green tufts, lupine spires and poppies."""
    k, r = c.k, c.r
    if x1 - x0 > 0.3 and y1 - y0 > 0.3:
        k.box(c.m("meadow", "GreenRoof", (150, 150, 88)), x0, y0, z, x1, y1, z + 0.03)
    for _ in range(n):
        x, y = r.uniform(x0, x1), r.uniform(y0, y1)
        u = r.random()
        if u < flowers * 0.5:
            k.plant("Reed", "Foliage", LUPINE, x, y, z, 5, 5, r.uniform(0.5, 0.8), shadow=False)
            k.plant("Puff", "Foliage", (86, 120, 70), x, y, z, 0.3, 0.3, 0.2, shadow=False)
        elif u < flowers:
            k.plant("Blob", "Foliage", POPPY, x, y, z + 0.18, 0.16, 0.16, 0.1, shadow=False)
            k.plant("Blob", "Foliage", (110, 140, 90), x, y, z + 0.05, 0.25, 0.25, 0.12, shadow=False)
        else:
            k.plant("Reed", "Foliage", r.choice(GOLD), x, y, z, 9, 9, r.uniform(0.5, 0.95), r.uniform(0, 360),
                    shadow=False)


def oak(c, x, y, h):
    """Coast live oak: a short trunk under a broad, low, dense crown."""
    c.tree(x, y, h, spread=1.35)


def redwood(c, x, y, h):
    """Coast redwood: a tall narrow conifer."""
    k, r = c.k, c.r
    k.plant("Trunk", "Bark", (120, 70, 50), x, y, 0, 0.5, 0.5, h * 0.35, r.uniform(0, 360))
    col = (44, 78, 50)
    k.plant("Cone", "Foliage", col, x, y, h * 0.22, 3.4, 3.4, h * 0.5, r.uniform(0, 360))
    k.plant("Cone", "Foliage", col, x, y, h * 0.55, 2.2, 2.2, h * 0.45, r.uniform(0, 360))


def ferns(c, x0, y0, x1, y1, n, z=0.0):
    k, r = c.k, c.r
    for _ in range(n):
        x, y = r.uniform(x0, x1), r.uniform(y0, y1)
        k.plant("Cone", "Foliage", (70, 120, 56), x, y, z, 1.3, 1.3, 0.45, r.uniform(0, 360), shadow=False)


def car(c, x, y, col, yaw=90):
    """A small vintage coupe pointing along y (yaw 90) or x (yaw 0)."""
    k = c.k
    along_y = yaw == 90
    L, W = 4.2, 1.7
    sx, sy = (W, L) if along_y else (L, W)
    k.plant("Cube", "Plain", col, x, y, 0.3, sx, sy, 0.62)
    cx, cy = (W * 0.9, L * 0.5) if along_y else (L * 0.5, W * 0.9)
    k.plant("Cube", "Plain", mix(col, (250, 250, 250), 0.6), x, y + (0.2 if along_y else 0), 0.92, cx, cy, 0.46)
    for a in (-1, 1):
        for b in (-1, 1):
            ox, oy = (a * W * 0.42, b * L * 0.32) if along_y else (b * L * 0.32, a * W * 0.42)
            k.plant("Cube", "Plain", (30, 30, 32), x + ox, y + oy, 0.0, 0.22, 0.6, 0.6) if along_y else \
                k.plant("Cube", "Plain", (30, 30, 32), x + ox, y + oy, 0.0, 0.6, 0.22, 0.6)


def hex_pts(cx, cy, R, rot=0.0):
    """Flat-front hexagon (vertices at 0, 60, ... degrees): faces look at +-y, so one faces the street."""
    return [(cx + R * math.cos(math.radians(rot + 60 * i)), cy + R * math.sin(math.radians(rot + 60 * i)))
            for i in range(6)]


# ======================================================================================================
# Eichler atrium house (Claude Oakland / Anshen + Allen, 1955-64)
# ======================================================================================================
def eichler_atrium(plot):
    """One Eichler: a long low side-gable with beam tails along the eave, a blank grooved front, an entry that opens
    straight into the open-air atrium (maple, ferns), a carport under the same roofline, glass to the back garden."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 4.0, 6.0)
    siding_col = mix(c.pal[1], (132, 120, 98), 0.55)
    siding = c.m("siding", "Timber", siding_col)
    line = c.m("groove", "Plain", mix(siding_col, GROOVE, 0.7))
    beam = c.m("beam", "Timber", (118, 80, 52))
    trim = c.m("trim", "Plain", FASCIA)
    roof = c.m("roof", "PermeableStone", (150, 146, 138))
    conc = c.m("conc", "PermeableStone", CONC)
    door = vivid(c.pal[2]) if r.random() < 0.6 else r.choice(EICHLER_DOORS)
    door_s = c.m("door", "Plain", door)

    fz = 0.15
    zw = fz + 2.5
    fy = clamp(0.22 * d, 4.2, 7.0)
    hd = clamp(d - fy - 5.0, 9.0, 14.5)
    by = fy + hd
    yr = fy + hd / 2
    half = hd / 2
    rise = min(half * math.tan(math.radians(12)), H - zw - 0.32)
    zr = lambda y: zw + rise * (1 - abs(y - yr) / half)
    cw = clamp(0.3 * w, 4.6, 6.4)
    car_left = r.random() < 0.5
    m0 = 0.9
    if car_left:
        cx0, cx1 = m0, m0 + cw
        hx0, hx1 = cx1, w - m0 - 0.4
    else:
        hx0, hx1 = m0 + 0.4, w - m0 - cw
        cx0, cx1 = hx1, w - m0
    hw = hx1 - hx0
    aw = clamp(0.38 * hw, 3.4, 5.6)
    axc = (hx0 + hx1) / 2 + (0.6 if car_left else -0.6)
    ax0, ax1 = axc - aw / 2, axc + aw / 2
    ay0, ay1 = fy + 0.18, fy + clamp(0.42 * hd, 3.6, 5.4)
    ov, ovs = 0.95, 0.55
    yf, yb = fy - ov, by + ov
    xl = hx0 - (0.0 if car_left else ovs)
    xR = hx1 + (ovs if car_left else 0.0)

    # ---- slab, walls ----
    k.box(conc, hx0 - 0.15, fy - 0.15, 0, hx1 + 0.15, by + 0.15, fz)
    # front: blank grooved siding, the entry into the atrium, a high strip of bedroom windows
    gx0, gx1 = ax0 + 0.5, min(ax1 - 0.4, ax0 + 3.1)          # the entry opening
    boards(k, siding, line, "x", hx0, gx0, fy, fz, zw, -1)
    boards(k, siding, line, "x", gx1, hx1, fy, fz, zw, -1)
    k.box(siding, gx0, fy, zw - 0.3, gx1, fy + 0.16, zw)
    # bright entry door swung open into the atrium, and a slatted gate panel beside it
    dw = 1.0
    dxa = gx0 if car_left else gx1
    sgn = 1 if car_left else -1
    k.obox(door_s, dxa + sgn * 0.33, fy + 0.4, fz + 1.12, dw / 2, 0.03, 1.1, 0, sgn * 70, 0)
    sx0, sx1 = (gx0 + dw, gx1) if car_left else (gx0, gx1 - dw)
    n = max(2, int((sx1 - sx0) / 0.22))
    for i in range(n + 1):
        x = lerp(sx0 + 0.04, sx1 - 0.04, i / n)
        k.box(beam, x - 0.03, fy + 0.02, fz, x + 0.03, fy + 0.1, zw - 0.3)
    k.box(c.lamp, gx0 - 0.42, fy - 0.12, fz + 1.7, gx0 - 0.22, fy, fz + 2.0)
    # house number and a mail slot: small, but the Eichler front is about restraint
    wx0, wx1 = (gx1 + 0.8, hx1 - 0.7) if car_left else (hx0 + 0.7, gx0 - 0.8)
    if wx1 - wx0 > 1.2:
        k.box(c.glass, wx0, fy - 0.03, zw - 0.62, wx1, fy, zw - 0.12)
    # side walls with their gable triangles
    for x, o in ((hx0, -1), (hx1, 1)):
        boards(k, siding, line, "y", fy, by, x, fz, zw, o, pitch=0.45)
        k.tri(siding, (x, fy, zw), (x, by, zw), (x, yr, zw + rise), (o, 0, 0))
    # back: floor-to-ceiling glass on posts
    c.glaze("x", hx0 + 0.15, hx1 - 0.15, by - 0.06, fz, zw, bay=2.4, p_open=0.35, frame=beam)
    c.interior(hx0 + 0.2, ay1 + 0.3, hx1 - 0.2, by - 0.15, fz, zw, back="x0" if car_left else "x1", n_lamps=3,
               sofa=mix(door, (110, 96, 80), 0.35))
    # the atrium: glass on three sides, open to the sky, its back glass with an open slider into the lit living room
    c.glaze("y", ay0, ay1, ax0, fz, zw, bay=1.5, frame=beam)
    c.glaze("y", ay0, ay1, ax1, fz, zw, bay=1.5, p_open=0.25, frame=beam)
    c.glaze("x", ax0, ax1, ay1, fz, zw, bay=1.6, p_open=0.45, frame=beam)
    k.box(c.dim, ax0 + 0.3, ay1 + 2.6, fz, ax1 - 0.3, ay1 + 2.7, zw)
    for i in range(2):
        lx = lerp(ax0 + 0.8, ax1 - 0.8, i)
        k.box(c.lamp, lx - 0.2, ay1 + 1.3, zw - 0.9, lx + 0.2, ay1 + 1.7, zw - 0.65)
    k.box(c.lawn, ax0 + 0.08, ay0 + 0.1, fz, ax1 - 0.08, ay1 - 0.1, fz + 0.04)
    for i in range(int((ay1 - ay0 - 0.3) / 0.9)):
        k.box(conc, gx0 + 0.2, ay0 + 0.2 + i * 0.9, fz + 0.04, gx0 + 1.1, ay0 + 0.85 + i * 0.9, fz + 0.07)
    mx = ax1 - 1.1 if car_left else ax0 + 1.1
    c.tree(mx, (ay0 + ay1) / 2 + 0.3, min(zr(ay1) + 1.2, plot.h_max + 1.5), bloom=MAPLE, spread=0.6)
    ferns(c, ax0 + 0.4, ay0 + 0.5, ax1 - 0.4, ay1 - 0.4, 5, z=fz)
    c.interior(hx0 + 0.2, ay0, ax0, ay1, fz, zw, back="x0", n_lamps=1)
    c.interior(ax1, ay0, hx1 - 0.2, ay1, fz, zw, back="x1", n_lamps=1)

    # ---- roof: low side gable, open over the atrium (beams continue across as a trellis) ----
    t = 0.16
    pieces = [(xl, ax0, yf, yr), (ax1, xR, yf, yr), (ax0, ax1, yf, ay0), (ax0, ax1, ay1, yr)]
    for xa, xb, ya, yb_ in pieces:
        k.slope(roof, xa, ya, xb, yb_, zr(ya), zr(yb_), t)
    k.slope(roof, xl, yr, xR, yb, zr(yr), zr(yb), t)
    # carport: a flat roof at the eave line, on slim posts, its own storage wall at the back
    zc = zw + 0.02
    cy0, cy1 = yf, fy + 6.2
    k.box(roof, cx0, cy0, zc, cx1, cy1, zc + t)
    k.box(trim, cx0, cy0 - 0.04, zc - 0.06, cx1, cy0, zc + t + 0.04)
    k.box(c.lawn, cx0 + 0.3, cy0 + 0.3, zc + t, cx1 - 0.3, cy1 - 0.3, zc + t + 0.05)
    for x in (cx0 + 0.25, cx1 - 0.25):
        if (car_left and x < hx0 - 0.3) or (not car_left and x > hx1 + 0.3):
            k.box(beam, x - 0.07, fy - 0.07, 0, x + 0.07, fy + 0.07, zc)
            k.box(beam, x - 0.07, cy1 - 0.5, 0, x + 0.07, cy1 - 0.36, zc)
    boards(k, siding, line, "x", cx0 + 0.15, cx1 - 0.15, cy1 - 0.2, 0, zc, 1, t=0.6)
    k.box(beam, cx0, fy - 0.08, zc - 0.28, cx1, fy + 0.08, zc)            # carport header
    for i in range(3):
        k.plant("Fringe", "Foliage", r.choice(LEAF), lerp(cx0 + 0.6, cx1 - 0.6, i / 2), cy0 + 0.1, zc + t,
                0.9, 1.0, r.uniform(0.6, 1.2), 0)
    # fascia along both eaves, and the beam tails: rafters every 1.2 m running front to back past the fascia
    for yy in (yf, yb):
        k.box(trim, xl, yy - 0.03, zr(yy) - 0.08, xR, yy + 0.03, zr(yy) + t + 0.05)
    nb = int((xR - xl) / 1.2)
    for i in range(nb + 1):
        x = lerp(xl + 0.15, xR - 0.15, i / nb)
        for ya, yb_ in ((yf - 0.42, fy + 0.4), (by - 0.4, yb + 0.42)):
            k.beam(beam, (x, ya, zr(ya) - 0.13), (x, yb_, zr(yb_) - 0.13), 0.1, 0.24)
        if ax0 + 0.1 < x < ax1 - 0.1:   # the open trellis over the atrium
            k.beam(beam, (x, ay0, zr(ay0) - 0.05), (x, ay1, zr(ay1) - 0.05), 0.1, 0.22)
    k.box(trim, xl, yr - 0.08, zr(yr) + t, xR, yr + 0.08, zr(yr) + t + 0.06)  # ridge cap
    # PV on the back slope, hidden from the street
    k.slope(c.pv, xl + 0.6, yr + 0.4, xR - 0.6, yb - 0.5, zr(yr + 0.4) + t + 0.02, zr(yb - 0.5) + t + 0.02, 0.05)

    # ---- garden: front lawn with a maple and boulders, driveway, back patio and citrus ----
    k.box(conc, cx0 + 0.4, 0, 0, cx1 - 0.4, fy + 5.5, 0.05)
    pv_x = (gx0 + gx1) / 2
    for i in range(int((fy - 0.4) / 0.85)):
        k.box(conc, pv_x - 0.7, 0.3 + i * 0.85, 0, pv_x + 0.7, 0.85 + i * 0.85, 0.06)
    if r.random() < 0.65:
        car(c, (cx0 + cx1) / 2, fy + 2.4, door if r.random() < 0.5 else (226, 220, 200))
    else:
        for i in range(3):
            k.plant("Cube", "Plain", vivid(r.choice(FLOWER)), cx0 + 1 + i * 0.7, cy1 - 1.0, 0.5, 0.06, 1.7, 0.9)
    gl0, gl1 = (hx0 + 0.2, w - 0.3) if car_left else (0.3, hx1 - 0.2)
    c.lawn_patch(gl0, 0.3, gl1, fy - 0.4)
    # a slatted redwood privacy fence returning from the front wall on the far side
    fxa = hx1 + 0.2 if car_left else 0.3
    fxb = w - 0.3 if car_left else hx0 - 0.2
    if fxb - fxa > 0.5:
        for i in range(int((fxb - fxa) / 0.2)):
            x = fxa + 0.1 + i * 0.2
            k.box(beam, x - 0.05, fy + 0.3, 0, x + 0.05, fy + 0.36, 1.8)
    tx = gl0 + 1.6 if car_left else gl1 - 1.6
    if abs(tx - pv_x) < 2.2:
        tx = gl1 - 1.4 if car_left else gl0 + 1.4
    c.tree(tx, r.uniform(1.4, max(1.5, fy - 1.8)), min(plot.h_max + 1.0, 5.8), spread=0.85,
           bloom=r.choice(((240, 170, 190), JACARANDA, None, None)))
    for xs_ in (hx0 + 0.6, hx1 - 0.6):     # shrubs tucked against the front wall
        for i in range(3):
            xx = xs_ + (i * 0.9 if xs_ < pv_x else -i * 0.9)
            if abs(xx - pv_x) > 1.6 and not (cx0 - 0.3 < xx < cx1 + 0.3):
                c.shrub(xx, fy - 0.55, r.uniform(0.7, 1.0), bloom=0.6)
    for _ in range(int(hw / 3)):
        x = r.uniform(gl0 + 0.4, gl1 - 0.4)
        if abs(x - pv_x) > 1.1:
            c.boulder(x, r.uniform(0.6, fy - 0.9), r.uniform(0.5, 0.9))
    c.flowerbed(gl0 + 0.2, fy - 1.3, gl1 - 0.2, fy - 0.45, n=int(hw / 1.2), cols=(AGAPANTHUS, (246, 242, 230), CITRUS))
    for _ in range(int(hw / 1.4)):
        x = r.uniform(gl0 + 0.3, gl1 - 0.3)
        if abs(x - pv_x) > 0.9:
            k.plant("Reed", "Foliage", r.choice(((150, 170, 90), (120, 150, 80), (178, 168, 110))), x,
                    r.uniform(0.4, 1.2), 0, 6, 6, 0.6, shadow=False)
    # back garden: a patio, a lawn, citrus and an oak
    k.box(conc, hx0 + 0.4, by + 0.15, 0, hx1 - 0.4, by + 2.4, 0.06)
    c.lawn_patch(0.3, by + 2.4, w - 0.3, d - 0.3)
    k.plant("Cube", "Fabric", door, hx0 + 2.0, by + 1.3, 0.3, 1.8, 0.7, 0.3)
    if d - by > 4.0:
        oak(c, r.uniform(1.5, w - 1.5), d - 2.0, min(plot.h_max + 3.0, 8.0))
        for _ in range(max(1, int(w / 9))):
            x, y = r.uniform(1.2, w - 1.2), r.uniform(by + 3.0, d - 1.0)
            c.tree(x, y, 3.2, spread=0.7)
            for j in range(5):
                a = j * 1.25
                k.plant("Blob", "Foliage", CITRUS, x + 0.8 * math.cos(a), y + 0.8 * math.sin(a), 2.4 + 0.3 * (j % 2),
                        0.13, 0.13, 0.13, shadow=False)
    for _ in range(int(w / 2.0)):
        c.shrub(r.uniform(0.5, w - 0.5), r.uniform(max(by + 2.6, d - 1.6), d - 0.4), r.uniform(0.7, 1.1))
    for xs in (0.5, w - 0.5):
        for i in range(int(hd / 2.0)):
            c.shrub(xs, fy + 1.0 + i * 2.0 + (5.5 if abs(xs - (cx0 + cx1) / 2) < cw else 0), r.uniform(0.7, 1.0))
    k.solid(hx0, fy, 0, hx1, by, zw)
    return k


# ======================================================================================================
# Sea Ranch Condominium One (MLTW: Moore, Lyndon, Turnbull, Whitaker, 1965)
# ======================================================================================================
def _shed(c, s, line, x0, y0, x1, y1, zlo, zhi, fall, roof):
    """A timber-clad box with a single steep shed roof falling toward `fall` in 'y0', 'y1', 'x0', 'x1'. Returns top(x,y)."""
    k = c.k
    if fall in ("y0", "y1"):
        za, zb = (zlo, zhi) if fall == "y0" else (zhi, zlo)
        top = lambda a: lerp(za, zb, (a - y0) / (y1 - y0))
        boards(k, s, line, "x", x0, x1, y0, 0, za, -1, t=0.2)
        boards(k, s, line, "x", x0, x1, y1, 0, zb, 1, t=0.2)
        boards(k, s, line, "y", y0, y1, x0, 0, max(za, zb), -1, top=top)
        boards(k, s, line, "y", y0, y1, x1, 0, max(za, zb), 1, top=top)
        k.slope(roof, x0 - 0.12, y0 - 0.12, x1 + 0.12, y1 + 0.12, za - 0.03, zb - 0.03, 0.18)
    else:
        za, zb = (zlo, zhi) if fall == "x0" else (zhi, zlo)
        top = lambda a: lerp(za, zb, (a - x0) / (x1 - x0))
        boards(k, s, line, "y", y0, y1, x0, 0, za, -1, t=0.2)
        boards(k, s, line, "y", y0, y1, x1, 0, zb, 1, t=0.2)
        boards(k, s, line, "x", x0, x1, y0, 0, max(za, zb), -1, top=top)
        boards(k, s, line, "x", x0, x1, y1, 0, max(za, zb), 1, top=top)
        tilt_x(k, roof, x0 - 0.12, x1 + 0.12, y0 - 0.12, y1 + 0.12, za - 0.03, zb - 0.03, 0.18)
    k.solid(x0, y0, 0, x1, y1, max(zlo, zhi))
    return top


def _bay(c, s, axis, a0, a1, at, out, z0, z1, depth=0.9, open_=False):
    """A boxed bay window that pushes out of a blank wall (Condo One's 'saddlebag' bays), with its own little shed."""
    k = c.k
    if axis == "x":
        yo = at + out * depth
        ya, yb = min(at, yo), max(at, yo)
        k.box(s, a0, ya, z0 - 0.25, a1, yb, z0)
        k.box(s, a0, ya, z0, a0 + 0.12, yb, z1)
        k.box(s, a1 - 0.12, ya, z0, a1, yb, z1)
        if not open_:
            k.box(c.glass, a0 + 0.12, yo - 0.03, z0, a1 - 0.12, yo + 0.03, z1)
        else:
            k.box(c.lamp, (a0 + a1) / 2 - 0.2, at - out * 0.8 - 0.2, z1 - 0.8, (a0 + a1) / 2 + 0.2, at - out * 0.8 + 0.2, z1 - 0.55)
            k.box(c.dim, a0 + 0.1, at - out * 1.6 - 0.05, z0 - 0.3, a1 - 0.1, at - out * 1.6 + 0.05, z1)
        k.slope(s, a0 - 0.05, ya - 0.05, a1 + 0.05, yb + 0.05, z1 + (0.35 if out > 0 else 0.0),
                z1 + (0.0 if out > 0 else 0.35), 0.12)
    else:
        xo = at + out * depth
        xa, xb = min(at, xo), max(at, xo)
        k.box(s, xa, a0, z0 - 0.25, xb, a1, z0)
        k.box(s, xa, a0, z0, xb, a0 + 0.12, z1)
        k.box(s, xa, a1 - 0.12, z0, xb, a1, z1)
        k.box(c.glass, xo - 0.03, a0 + 0.12, z0, xo + 0.03, a1 - 0.12, z1)
        tilt_x(k, s, xa - 0.05, xb + 0.05, a0 - 0.05, a1 + 0.05, z1 + (0.35 if out > 0 else 0.0),
               z1 + (0.0 if out > 0 else 0.35), 0.12)


def sea_ranch(plot):
    """Condominium One: a tight cluster of tall weathered-redwood boxes round a courtyard, each under its own steep
    shed roof, nearly windowless, a few boxed bays and one glass corner; a golden meadow, a cypress hedgerow behind."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 6.5, 10.0)
    wood_col = mix(WEATHERED, c.pal[0], 0.12)
    wood = c.m("wood", "Timber", wood_col)
    line = c.m("groove", "Plain", mix(wood_col, GROOVE, 0.65))
    roof = c.m("roof", "Timber", SHINGLE)
    deck = c.m("deck", "Timber", (128, 112, 96))

    # cluster footprint: a U around a courtyard, open to the street (the sea side)
    x0, x1 = clamp(0.1 * w, 2.4, 4.0), w - clamp(0.1 * w, 2.4, 4.0)
    y0 = clamp(0.2 * d, 4.5, 7.0)
    y1 = d - clamp(0.2 * d, 4.5, 7.5)
    cwid = x1 - x0
    dep = y1 - y0
    side = clamp(0.3 * cwid, 5.5, 8.0)        # width of the side wings
    back = clamp(0.38 * dep, 5.5, 8.0)        # depth of the back range
    units = []
    # back range: 2-3 units, sheds falling to the street, the tower at one end
    nb = 3 if cwid >= 26 else 2
    xs = [x0 + side * 0.6] + [lerp(x0 + side * 0.6, x1 - side * 0.6, (i + 1) / nb) for i in range(nb)]
    tower_left = r.random() < 0.5
    for i in range(nb):
        ua, ub = xs[i], xs[i + 1]
        jog = r.uniform(-0.6, 0.6)
        units.append((ua, y1 - back + jog, ub, y1, "y0", r.uniform(0.55, 0.62) * H, r.uniform(0.82, 0.9) * H))
    # side wings: 1-2 units each, sheds falling outward or to the street
    for left in (True, False):
        xa, xb = (x0, x0 + side) if left else (x1 - side, x1)
        ns = 2 if dep - back >= 11 else 1
        ys = [y0 + lerp(0, dep - back, j / ns) for j in range(ns + 1)]
        for j in range(ns):
            fall = r.choice(("y0", "x0" if left else "x1"))
            ya, yb = ys[j] - (0.0 if j else r.uniform(0, 1.0)), ys[j + 1]
            units.append((xa + (0.7 if j % 2 else 0.0) * (1 if left else -1), ya, xb - (0.0 if j % 2 else 0.0), yb, fall,
                          r.uniform(0.38, 0.48) * H, r.uniform(0.62, 0.74) * H))
    # tower: the tall element at a back corner, its shed falling inward
    tw = clamp(0.2 * cwid, 4.0, 5.2)
    tx0 = x0 + 0.4 if tower_left else x1 - 0.4 - tw
    ty0 = y1 - back - tw * 0.4
    units.append((tx0, ty0, tx0 + tw, ty0 + tw, "x1" if tower_left else "x0", 0.66 * H, H - 0.05))
    tops = []
    for (ua, va, ub, vb, fall, zlo, zhi) in units:
        tops.append(_shed(c, wood, line, ua, va, ub, vb, zlo, zhi, fall, roof))

    # windows: Condo One is nearly blind; a few saddlebag bays, deep small windows, one big glass corner to the sea
    for _j, (ua, va, ub, vb, fall, zlo, _zhi) in enumerate(units):
        cx = (ua + ub) / 2
        if fall == "y0" and ub - ua > 3.0:
            # a boxed bay on the low street wall, plus a clerestory slot high on the side
            if r.random() < 0.75:
                bw = min(2.6, ub - ua - 1.2)
                _bay(c, wood, "x", cx - bw / 2, cx + bw / 2, va, -1, 1.1, min(zlo - 0.6, 3.4), open_=r.random() < 0.35)
            else:
                k.box(c.glass, cx - 0.5, va - 0.03, 1.2, cx + 0.5, va, 2.4)
        elif fall in ("x0", "x1"):
            ox = ua if fall == "x0" else ub
            if r.random() < 0.6:
                _bay(c, wood, "y", va + 1.0, min(vb - 1.0, va + 3.2), ox, -1 if fall == "x0" else 1, 1.0,
                     min(zlo - 0.5, 3.0))
            else:
                k.box(c.glass, ox - 0.03, va + 1.0, 1.0, ox + 0.03, va + 1.9, zlo - 0.6)
        else:
            k.box(c.glass, cx - 0.45, va - 0.03, 1.4, cx + 0.45, va, 2.5)
    # tower: a tall glass corner looking to the sea, with a lit room and a pendant behind an open pane
    ta, tb = tx0, tx0 + tw
    gx = (ta + 0.5, ta + 2.2) if tower_left else (tb - 2.2, tb - 0.5)
    k.box(c.mull, gx[0] - 0.06, ty0 - 0.05, 3.0, gx[1] + 0.06, ty0 + 0.02, 3.08)
    k.box(c.glass, gx[0], ty0 - 0.04, 3.08, gx[1], ty0, 0.66 * H - 0.6)
    k.box(c.dim, ta + 0.3, ty0 + 0.4, 0.66 * H - 2.6, tb - 0.3, ty0 + 0.5, 0.66 * H - 0.6)
    # the main living bay: a glass box in the inner corner of the U, toward the courtyard, one pane slid back
    lx0, lx1 = xs[nb // 2] - 2.0, xs[nb // 2] + 2.0
    ly = y1 - back - 0.02
    k.box(c.glass, lx0, ly - 0.05, 0.6, lx0 + 1.6, ly, 3.4)
    k.box(c.glass, lx1 - 1.6, ly - 0.05, 0.6, lx1, ly, 3.4)
    k.box(c.dim, lx0 + 0.2, ly + 2.4, 0.6, lx1 - 0.2, ly + 2.5, 3.4)
    k.box(c.lamp, (lx0 + lx1) / 2 - 0.25, ly + 1.2, 2.5, (lx0 + lx1) / 2 + 0.25, ly + 1.7, 2.8)
    k.box(c.mull, lx0, ly - 0.08, 3.4, lx1, ly, 3.5)
    for x in (lx0, lx0 + 1.6, lx1 - 1.6, lx1):
        k.box(c.mull, x - 0.04, ly - 0.08, 0.6, x + 0.04, ly, 3.4)
    # chimney flues: tall dark metal pipes
    for _ in range(2):
        u = units[r.randrange(len(units) - 1)]
        fx, fy_ = lerp(u[0], u[2], 0.7), lerp(u[1], u[3], 0.6)
        k.cyl(c.mull, fx, fy_, 0, 0.16, 0.16, max(u[5], u[6]) + 0.4, segs=8)

    # courtyard: a weathered deck, a little planted hollow of ferns and ceanothus
    qx0 = x0 + side
    qx1 = x1 - side
    qy0, qy1 = y0 + 0.5, y1 - back
    k.box(deck, qx0 + 0.2, qy1 - 3.2, 0, qx1 - 0.2, qy1, 0.25)
    for i in range(int((qx1 - qx0) / 0.3)):
        x = qx0 + 0.3 + i * 0.3
        k.box(line, x, qy1 - 3.2, 0.25, x + 0.02, qy1, 0.255)
    c.lawn_patch(qx0, qy0, qx1, qy1 - 3.2)
    for _ in range(int((qx1 - qx0) / 1.5)):
        c.shrub(r.uniform(qx0 + 0.6, qx1 - 0.6), r.uniform(qy0 + 0.6, qy1 - 3.8), r.uniform(0.7, 1.1), bloom=0.6,
                col=r.choice((CEANOTHUS, (246, 242, 230), LUPINE)))
    ferns(c, qx0 + 0.4, qy1 - 4.6, qx1 - 0.4, qy1 - 3.4, int((qx1 - qx0) / 1.5))
    # a boardwalk from the street into the courtyard
    mid = (qx0 + qx1) / 2
    k.box(deck, mid - 0.7, 0, 0, mid + 0.7, qy1 - 3.2, 0.15)

    # the site: a meadow all round, a cypress hedgerow behind, wildflowers
    hb = d - 1.8
    hedgerow(c, 0.5, hb, w - 0.5, hb, min(H + 3.0, plot.h_max + 4.0), wind=1.2)
    meadow(c, 0.3, 0.3, w - 0.3, y0 - 0.3, int(w * 2.0), flowers=0.3)
    meadow(c, 0.3, y0, x0 - 0.2, hb - 1.5, int(dep * 0.8), flowers=0.2)
    meadow(c, x1 + 0.2, y0, w - 0.3, hb - 1.5, int(dep * 0.8), flowers=0.2)
    meadow(c, x0, y1 + 0.3, x1, hb - 2.0, int(cwid * 0.5), flowers=0.2)
    for _ in range(3):
        c.boulder(r.uniform(0.6, w - 0.6), r.uniform(0.6, y0 - 1.2), r.uniform(0.6, 1.2))
    return k


# ======================================================================================================
# Esherick Hedgerow House (Joseph Esherick, Sea Ranch 1966)
# ======================================================================================================
def hedgerow_house(plot):
    """A low house tucked in the lee of a cypress hedgerow: one long shed roof that dives toward the hedge almost to the
    ground and lifts toward the meadow, a lower studio wing stepping down under the same slope; redwood boards."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 4.5, 7.0)
    wood_col = mix(mix(REDWOOD, WEATHERED, 0.55), c.pal[0], 0.1)
    wood = c.m("wood", "Timber", wood_col)
    line = c.m("groove", "Plain", mix(wood_col, GROOVE, 0.65))
    roof = c.m("roof", "Timber", SHINGLE)
    deck = c.m("deck", "Timber", (132, 112, 94))
    trim = c.m("trim", "Plain", (70, 62, 56))

    hedge_left = r.random() < 0.5
    hz = 2.2                         # hedge-side eave: you could touch it
    hzz = H - 0.15
    fy = clamp(0.24 * d, 4.0, 7.0)
    hd = clamp(0.48 * d, 7.0, 12.0)
    by = fy + hd
    gw = 3.6                          # hedgerow band
    hw = clamp(0.55 * w, 7.5, 13.0)
    if hedge_left:
        hx_lo, hx_hi = gw + 0.6, gw + 0.6 + hw            # low side at the hedge
    else:
        hx_hi, hx_lo = w - gw - 0.6 - hw, w - gw - 0.6
    xa, xb = min(hx_lo, hx_hi), max(hx_lo, hx_hi)
    zlo_at = lambda x: lerp(hz, hzz, (x - hx_lo) / (hx_hi - hx_lo))
    k.box(c.m("conc", "PermeableStone", CONC), xa - 0.1, fy - 0.1, 0, xb + 0.1, by + 0.1, 0.15)
    # walls: the low hedge-side wall, the tall meadow wall, trapezoid front and back
    lo_out = -1 if hedge_left else 1
    boards(k, wood, line, "y", fy, by, hx_lo, 0, hz, lo_out, t=0.2)
    boards(k, wood, line, "y", fy, by, hx_hi, 0, hzz, -lo_out, t=0.2)
    for yy, o in ((fy, -1), (by, 1)):
        boards(k, wood, line, "x", xa, xb, yy, 0, hzz, o, top=zlo_at)
    # the roof: one plane, overhanging the meadow wall, nearly reaching the ground on the hedge side
    ext_lo = 0.9
    sl = (hzz - hz) / (hx_hi - hx_lo)
    x_lo_e = hx_lo - ext_lo * (1 if hedge_left else -1)
    x_hi_e = hx_hi + 0.5 * (1 if hedge_left else -1)
    z_lo_e, z_hi_e = zlo_at(x_lo_e), zlo_at(x_hi_e)
    ra, rb = min(x_lo_e, x_hi_e), max(x_lo_e, x_hi_e)
    tilt_x(k, roof, ra, rb, fy - 0.5, by + 0.5, zlo_at(ra), zlo_at(rb), 0.2)
    # meadow wall: a long high clerestory under the eave and a big window seat bay at eye level
    hi_out = -lo_out
    k.box(c.glass, hx_hi - 0.03 if hi_out > 0 else hx_hi - 0.0, fy + 0.6, hzz - 0.9, hx_hi + 0.03 * hi_out, by - 0.6, hzz - 0.25)
    _bay(c, wood, "y", fy + 1.2, fy + 1.2 + min(3.2, hd * 0.35), hx_hi, hi_out, 0.7, 2.5)
    # street front: one deep window and the entry, a timber porch and a lantern
    fx = lerp(xa, xb, 0.62 if hedge_left else 0.38)
    k.box(c.glass, fx - 0.9, fy - 0.03, 1.0, fx + 0.9, fy, 2.4)
    k.box(trim, fx - 1.0, fy - 0.12, 0.95, fx + 1.0, fy, 1.02)
    ex = lerp(xa, xb, 0.3 if hedge_left else 0.7)
    k.box(c.m("door", "Plain", mix(vivid(c.pal[2]), (90, 70, 50), 0.25)), ex - 0.5, fy - 0.04, 0.15, ex + 0.5, fy, 2.2)
    k.box(c.lamp, ex + 0.65, fy - 0.12, 1.7, ex + 0.85, fy, 2.0)
    k.box(deck, ex - 1.4, fy - 1.6, 0, ex + 1.4, fy, 0.25)
    # back: a glass wall onto a deck in the lee, one slider open onto a lit room
    c.glaze("x", xa + 0.4, xb - 0.4, by + 0.02, 0.15, min(zlo_at(xa), zlo_at(xb)) - 0.2, bay=2.2, p_open=0.35)
    c.interior(xa + 0.3, fy + 0.3, xb - 0.3, by - 0.2, 0.15, min(zlo_at(xa), zlo_at(xb)) - 0.2, back="y0", n_lamps=2,
               sofa=mix(vivid(c.pal[2]), (110, 96, 80), 0.4))
    k.box(deck, xa, by, 0, xb, by + 2.6, 0.3)
    # chimney: a square timber-clad flue punching through the slope
    chx = lerp(hx_lo, hx_hi, 0.45)
    chz = min(zlo_at(chx) + 1.3, H - 0.5)
    k.box(wood, chx - 0.45, by - 2.6, 0, chx + 0.45, by - 1.7, chz)
    k.box(c.mull, chx - 0.15, by - 2.3, chz, chx + 0.15, by - 2.0, chz + 0.5)
    # studio wing on the meadow side, lower, its own shed parallel to the main roof
    sw = clamp(w - (xb - xa) - gw - 2.2, 0, 5.5)
    if sw >= 3.5:
        s_lo = hx_hi + (0.0 if hedge_left else 0.0)
        s_hi = hx_hi + sw * (1 if hedge_left else -1)
        sa, sb = min(s_lo, s_hi), max(s_lo, s_hi)
        sy0, sy1 = by - 5.5, by + 0.8
        z0s, z1s = 2.5, min(3.6, hzz - 1.2)
        top = lambda x: lerp(z0s, z1s, (x - s_lo) / (s_hi - s_lo))
        boards(k, wood, line, "y", sy0, sy1, s_hi, 0, z1s, -lo_out, t=0.2)
        for yy, o in ((sy0, -1), (sy1, 1)):
            boards(k, wood, line, "x", sa, sb, yy, 0, z1s, o, top=top)
        tilt_x(k, roof, sa - 0.15, sb + 0.15, sy0 - 0.3, sy1 + 0.3, top(sa - 0.15), top(sb + 0.15), 0.18)
        k.box(c.glass, s_hi - 0.03, sy0 + 0.8, 0.8, s_hi + 0.03, sy0 + 2.6, 2.3)
        k.solid(sa, sy0, 0, sb, sy1, z1s)
    k.solid(xa, fy, 0, xb, by, hzz)

    # hedgerow along the plot side, tall above the low eave; meadow everywhere else; a sheltered garden in the lee
    hxh = gw / 2 if hedge_left else w - gw / 2
    hedgerow(c, hxh, 0.8, hxh, d - 0.8, min(H + 2.5, plot.h_max + 4.0), wind=0.0)
    meadow(c, 0.3, 0.3, w - 0.3, fy - 1.7, int(w * 2.2), flowers=0.3)
    mx0, mx1 = (xb + 0.3, w - 0.3) if hedge_left else (0.3, xa - 0.3)
    meadow(c, mx0, fy, mx1, d - 0.4, int((mx1 - mx0) * (d - fy) * 0.5), flowers=0.25)
    # the lee garden behind the house: kitchen beds, ferns and a bench (the lushness is hidden from the wind)
    gy0, gy1 = by + 2.8, d - 0.6
    if gy1 - gy0 > 1.5:
        c.lawn_patch(xa, gy0, xb, gy1)
        for i in range(int((xb - xa) / 2.6)):
            bx = xa + 0.6 + i * 2.6
            k.box(deck, bx, gy0 + 0.4, 0, bx + 1.8, gy0 + 1.4, 0.35)
            for j in range(4):
                k.plant("Puff", "Foliage", r.choice(LEAF), bx + 0.3 + j * 0.4, gy0 + 0.9, 0.35, 0.28, 0.28, 0.25)
        c.flowerbed(xa + 0.3, gy0 + 1.8, xb - 0.3, gy1, cols=(CEANOTHUS, POPPY, (246, 242, 230), LUPINE))
    ferns(c, xa, by + 2.6, xb, by + 3.0, 4)
    for _ in range(3):
        c.boulder(r.uniform(0.8, w - 0.8), r.uniform(0.5, fy - 1.5), r.uniform(0.6, 1.1))
    return k


# ======================================================================================================
# Hanna-Honeycomb House (Frank Lloyd Wright, Stanford 1937)
# ======================================================================================================
def _hex_pod(c, slots, cx, cy, R, zf, zw, roof_r, rise, glass_faces, open_face, chimney=None):
    """One hexagonal room: brick base, horizontal board-and-batten or French doors on each face, a low hipped
    (pyramidal) copper roof with a wide overhang and a dark copper fascia."""
    k = c.k
    brick, wood, batt, cop, cop_e, soff = (slots[n] for n in ("brick", "wood", "batt", "copper", "fascia", "soffit"))
    pts = hex_pts(cx, cy, R)
    k.prism(brick, pts, 0, zf + 0.75)
    for i in range(6):
        (ax, ay), (bx, by_) = pts[i], pts[(i + 1) % 6]
        mx, my = (ax + bx) / 2, (ay + by_) / 2
        nx, ny = (mx - cx) / (R * 0.866), (my - cy) / (R * 0.866)
        zm = (zf + 0.75 + zw) / 2
        hgt = zw - zf - 0.75
        if i == open_face:
            k.box(c.lamp, cx - 0.25, cy - 0.25, zw - 1.0, cx + 0.25, cy + 0.25, zw - 0.7)
            for j in range(4):
                u = (j + 0.5) / 4
                px, py = lerp(ax, bx, u), lerp(ay, by_, u)
                k.beam(batt, (px, py, zf + 0.75), (px, py, zw), 0.1, 0.1)
            continue
        if i in glass_faces:
            k.beam(c.glass, (ax, ay, zm), (bx, by_, zm), 0.05, hgt)
            for j in range(5):
                u = j / 4
                px, py = lerp(ax, bx, u) + nx * 0.03, lerp(ay, by_, u) + ny * 0.03
                k.beam(batt, (px, py, zf + 0.75), (px, py, zw), 0.09, 0.09)
            k.beam(batt, (ax + nx * 0.03, ay + ny * 0.03, zw - 0.55), (bx + nx * 0.03, by_ + ny * 0.03, zw - 0.55), 0.06, 0.06)
        else:
            k.beam(wood, (ax, ay, zm), (bx, by_, zm), 0.16, hgt)
            n = max(2, int(hgt / 0.32))
            for j in range(1, n):
                z = zf + 0.75 + j * hgt / n
                k.beam(batt, (ax + nx * 0.09, ay + ny * 0.09, z), (bx + nx * 0.09, by_ + ny * 0.09, z), 0.04, 0.07)
    # roof: six triangular facets from a low eave to a centre peak
    top = (cx, cy, zw + 0.25 + rise)
    eave = [(x, y, zw + 0.25) for x, y in hex_pts(cx, cy, roof_r)]
    for i in range(6):
        a, b = eave[i], eave[(i + 1) % 6]
        mx, my = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        L = math.hypot(mx, my)
        s = rise / (roof_r * 0.866)
        n = (mx / L * s, my / L * s, 1.0)
        k.tri(cop, a, b, top, n)
        k.tri(soff, (a[0], a[1], a[2] - 0.12), (b[0], b[1], b[2] - 0.12), (top[0], top[1], top[2] - 0.6), (0, 0, -1))
        k.beam(cop_e, (a[0], a[1], a[2] - 0.08), (b[0], b[1], b[2] - 0.08), 0.12, 0.3)
    k.solid(cx - R * 0.8, cy - R * 0.8, 0, cx + R * 0.8, cy + R * 0.8, zw)
    if chimney:
        hc = hex_pts(cx + chimney[0], cy + chimney[1], 0.9)
        k.prism(brick, hc, 0, chimney[2])
        k.prism(cop_e, hex_pts(cx + chimney[0], cy + chimney[1], 1.0), chimney[2], chimney[2] + 0.15)


def hanna_honeycomb(plot):
    """Wright's Hanna House: rooms on a hexagonal grid, a zigzag chain of hexagonal pods with brick bases, horizontal
    board-and-batten and French doors at 120-degree corners, under low pyramidal copper roofs with wide eaves, a tall
    brick chimney, hexagonal brick terraces stepping into a lawn under live oaks."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 5.0, 7.5)
    wood_col = mix(CYPRESS_WOOD, c.pal[0], 0.1)
    slots = {
        "brick": c.m("brick", "PermeableStone", BRICK_HANNA),
        "wood": c.m("wood", "Timber", wood_col),
        "batt": c.m("batt", "Timber", mix(wood_col, (70, 50, 36), 0.45)),
        "copper": c.m("copper", "Metal", COPPER),
        "fascia": c.m("fascia", "Metal", COPPER_DARK),
        "soffit": c.m("soffit", "Plain", (218, 200, 168)),
    }
    zf, zw = 0.35, 3.05
    rise = min(1.5, H - zw - 0.25 - 1.0)
    # the chain: living (big) -> study -> bedrooms, zigzagging along x at 30/330 degrees
    sc = clamp(min(w / 30.0, d / 26.0), 0.85, 1.3)
    for _ in range(20):
        RL, RS = 5.0 * sc, 3.7 * sc
        ov = 1.5 * sc
        pods = [(0.0, 0.0, RL)]
        dirs = (30, -30)
        i = 0
        while True:
            px, py, pr = pods[-1]
            a = math.radians(dirs[i % 2])
            dist = (pr + RS) * 0.866
            nx_, ny_ = px + dist * math.cos(a), py + dist * math.sin(a)
            if nx_ + RS + ov + RL + ov > w - 1.5 or len(pods) >= 4:
                break
            pods.append((nx_, ny_, RS))
            i += 1
        bx0 = min(p[0] - p[2] - ov for p in pods)
        bx1 = max(p[0] + p[2] + ov for p in pods)
        by0 = min(p[1] - p[2] * 0.866 - ov for p in pods)
        by1 = max(p[1] + p[2] * 0.866 + ov for p in pods)
        if len(pods) >= 3 and bx1 - bx0 <= w - 2.0 and by1 - by0 <= d - 7.0:
            break
        if len(pods) >= 2 and bx1 - bx0 <= w - 2.0 and by1 - by0 <= d - 7.0 and sc < 0.8:
            break
        sc *= 0.94
    ox = (w - (bx1 - bx0)) / 2 - bx0
    oy = clamp(0.32 * d, 5.5, 9.0) - by0
    if oy + by1 > d - 2.5:
        oy = d - 2.5 - by1
    if r.random() < 0.5:   # mirror the chain so it climbs either way
        pods = [(-p[0], p[1], p[2]) for p in pods]
        ox = (w - (bx1 - bx0)) / 2 + bx1
    pods = [(p[0] + ox, p[1] + oy, p[2]) for p in pods]
    for j, (px, py, pr) in enumerate(pods):
        big = j == 0
        glass = {4, 5, 3} if py <= min(q[1] for q in pods) + 0.1 else {4, 5}   # faces toward the street side
        glass |= {1}                                                            # and to the back garden
        rr = pr + (1.6 if big else 1.3) * sc
        ri = rise if big else rise * 0.8
        chim = (pr * 0.35, pr * 0.3, H) if big else None
        _hex_pod(c, slots, px, py, pr, zf, zw if big else zw - 0.2, rr, ri, glass, open_face=4 if big else (5 if j % 2 else -1),
                 chimney=chim)
    # terraces: hexagonal brick platforms spilling from the living pod toward the street, low brick walls on hex angles
    brick = slots["brick"]
    lx, ly, lr = pods[0]
    k.prism(brick, hex_pts(lx, ly - lr * 0.95, lr * 0.85), 0, 0.3)
    k.prism(c.lawn, hex_pts(lx, ly - lr * 0.95, lr * 0.6), 0.3, 0.33)
    wall_pts = [hex_pts(lx, ly - lr * 0.95, lr * 0.85 + 0.2)[i] for i in (0, 5, 4, 3)]
    k.ribbon(brick, wall_pts, 0.35, 0, 0.75)
    for (px, py, pr) in pods[1:]:
        k.prism(brick, hex_pts(px, py, pr + 0.9), 0, zf)
    for x, y in wall_pts:
        for _ in range(2):
            c.shrub(x + r.uniform(-0.6, 0.6), y + r.uniform(-0.6, 0.6), r.uniform(0.7, 1.0), z=0.0, bloom=0.7,
                    col=r.choice(((236, 132, 160), (246, 242, 230), (214, 72, 84))))
    # the garden: a big lawn, live oaks (the Stanford hillside), flower borders along the brick
    c.lawn_patch(0.3, 0.3, w - 0.3, d - 0.3)
    xs = [p[0] for p in pods]
    oak(c, min(xs) - 3.0 if min(xs) - 3.0 > 2 else 2.0, d - 3.0, min(plot.h_max + 3.0, 9.0))
    oak(c, 2.0 if r.random() < 0.5 else w - 2.0, 2.2, min(plot.h_max + 2.0, 8.0))
    c.scatter_trees(1.0, by1 + oy + 0.5, w - 1.0, d - 0.8, max(1, int(w / 12)), min(plot.h_max + 1.5, 7.5), bloom=0.4,
                    taken=[(p[0], p[1]) for p in pods])
    for (px, py, pr) in pods:
        for i in range(6):
            a = math.radians(30 + 60 * i)
            c.shrub(px + (pr + 1.0) * math.cos(a), py + (pr + 1.0) * math.sin(a), r.uniform(0.6, 0.9), bloom=0.55)
    c.flowerbed(1.0, 0.6, w - 1.0, 2.0, n=int(w / 1.6))
    path_x = lx
    for i in range(int((ly - lr * 1.8) / 0.9)):
        k.prism(brick, hex_pts(path_x + (0.3 if i % 2 else -0.3), 0.6 + i * 0.9, 0.38), 0, 0.06)
    return k


# ======================================================================================================
# Eichler X-100 (A. Quincy Jones & Frederick Emmons, San Mateo 1956)
# ======================================================================================================
def eichler_x100(plot):
    """The steel Eichler: a flat roof on an exposed dark steel frame with I-beam ends, an 8-foot grid infilled with
    glass, white and bold colour panels, an open interior court, a steel-framed carport, glass to the garden."""
    c = Ctx(plot)
    k, r, w, d = c.k, c.r, c.w, c.d
    H = clamp(plot.h_max, 4.0, 5.5)
    steel = c.m("steel", "Plain", (46, 48, 52))
    roofw = c.m("roofw", "Plain", (236, 234, 228))
    panel_w = c.m("panelw", "Plain", (232, 228, 214))
    conc = c.m("conc", "PermeableStone", CONC)
    cols = list(X100_COLS[:4])
    r.shuffle(cols)
    cols[0] = vivid(c.pal[2])
    colour = [c.m(f"col{i}", "Plain", cols[i]) for i in range(2)]
    soffit = c.m("soffit", "Timber", (170, 126, 84))

    fz = 0.3
    zc = fz + 2.6
    rt = 0.28
    bay = 2.44                              # the 8-foot module
    fy = clamp(0.22 * d, 4.0, 6.5)
    nby = max(4, int(clamp(d - fy - 5.0, 9.0, 15.0) / bay))
    by = fy + nby * bay
    carport = w >= 21.0
    cpw = 2 * bay if carport else 0.0
    car_left = r.random() < 0.5
    nbx = max(4, int((w - 2.4 - cpw) / bay))
    hw = nbx * bay
    if car_left:
        hx0 = w - 1.2 - hw
        cx0, cx1 = hx0 - cpw, hx0
    else:
        hx0 = 1.2
        cx0, cx1 = hx0 + hw, hx0 + hw + cpw
    hx1 = hx0 + hw
    gx = [hx0 + i * bay for i in range(nbx + 1)]
    gy = [fy + j * bay for j in range(nby + 1)]
    # the court: two bays wide, two deep, centred
    ci0 = max(1, nbx // 2 - 1)
    cj0 = max(1, nby // 2 - 1)
    qx0, qx1, qy0, qy1 = gx[ci0], gx[ci0 + 2], gy[cj0], gy[cj0 + 2]

    k.box(conc, hx0 - 0.3, fy - 0.3, 0, hx1 + 0.3, by + 0.3, fz)
    # front: the grid infill (glass, white, colour), the entry a glass door beside a colour panel
    pattern = []
    ent = nbx // 2 if not car_left else nbx // 2 - 1
    for i in range(nbx):
        if i == ent:
            pattern.append("door")
        elif i in (ent - 1, ent + 1):
            pattern.append("col0" if i == ent - 1 else "white")
        else:
            pattern.append(r.choice(("white", "white", "high", "col1", "high")))
    for i, p in enumerate(pattern):
        a0, a1 = gx[i] + 0.08, gx[i + 1] - 0.08
        if p == "white":
            k.box(panel_w, a0, fy - 0.04, fz, a1, fy + 0.06, zc)
        elif p.startswith("col"):
            k.box(colour[int(p[3])], a0, fy - 0.04, fz, a1, fy + 0.06, zc)
        elif p == "high":
            k.box(panel_w, a0, fy - 0.04, fz, a1, fy + 0.06, zc - 0.8)
            k.box(c.glass, a0, fy - 0.03, zc - 0.8, a1, fy + 0.03, zc)
        else:
            k.box(c.glass, a0, fy - 0.03, fz, (a0 + a1) / 2, fy + 0.03, zc)
            k.box(colour[0], (a0 + a1) / 2, fy - 0.04, fz, a1, fy + 0.06, zc - 0.5)
            k.box(c.glass, (a0 + a1) / 2, fy - 0.03, zc - 0.5, a1, fy + 0.03, zc)
            k.box(c.lamp, a1 - 0.2, fy - 0.3, fz + 1.8, a1 - 0.05, fy - 0.12, fz + 2.1)
    # sides: white and colour panels with a glass bay
    for x, o in ((hx0, -1), (hx1, 1)):
        for j in range(nby):
            a0, a1 = gy[j] + 0.08, gy[j + 1] - 0.08
            if j == nby - 1:
                k.box(c.glass, x - 0.03, a0, fz, x + 0.03, a1, zc)
            elif (j + (1 if o > 0 else 0)) % 3 == 1:
                k.box(colour[1], x - 0.06, a0, fz, x + 0.04, a1, zc)
            else:
                k.box(panel_w, x - 0.06, a0, fz, x + 0.04, a1, zc)
    # back: all glass, sliders open into lit rooms
    c.glaze("x", hx0, hx1, by, fz, zc, bay=bay, p_open=0.35, frame=steel)
    c.interior(hx0 + 0.1, qy1 + 0.2, hx1 - 0.1, by - 0.1, fz, zc, back="y0", n_lamps=3,
               sofa=mix(cols[1], (100, 90, 80), 0.3))
    # the court, glass all round, a pool of planting, open to the sky
    c.glaze("x", qx0, qx1, qy0, fz, zc, bay=bay / 2, p_open=0.25, frame=steel)
    c.glaze("x", qx0, qx1, qy1, fz, zc, bay=bay / 2, p_open=0.25, frame=steel)
    c.glaze("y", qy0, qy1, qx0, fz, zc, bay=bay / 2, frame=steel)
    c.glaze("y", qy0, qy1, qx1, fz, zc, bay=bay / 2, frame=steel)
    k.box(c.lawn, qx0 + 0.1, qy0 + 0.1, fz, qx1 - 0.1, qy1 - 0.1, fz + 0.04)
    for _ in range(4):
        c.boulder(r.uniform(qx0 + 0.6, qx1 - 1.8), r.uniform(qy0 + 0.6, qy1 - 0.6), r.uniform(0.4, 0.7))
    c.tree(qx1 - 1.0, (qy0 + qy1) / 2, min(zc + rt + 2.0, plot.h_max + 2.0), bloom=r.choice((MAPLE, None)), spread=0.7)
    ferns(c, qx0 + 0.4, qy0 + 0.4, qx0 + 0.9, qy1 - 0.4, 3, z=fz)
    c.interior(hx0 + 0.1, fy + 0.15, qx0, qy1, fz, zc, back="x0", n_lamps=2)

    # steel frame: columns on the grid at the perimeter, I-beams across y that run out past the roof edge
    for x in gx:
        for y in (fy, by):
            k.box(steel, x - 0.08, y - 0.08, fz, x + 0.08, y + 0.08, zc)
        k.box(steel, x - 0.07, fy - 1.25, zc, x + 0.07, by + 1.25, zc + 0.36)
        k.box(steel, x - 0.12, fy - 1.25, zc, x + 0.12, fy - 1.15, zc + 0.36)   # I-beam end flange
        k.box(steel, x - 0.12, by + 1.15, zc, x + 0.12, by + 1.25, zc + 0.36)
    for y in gy:
        for x in (hx0, hx1):
            k.box(steel, x - 0.08, y - 0.08, fz, x + 0.08, y + 0.08, zc)
    # flat roof deck (with a hole over the court), white fascia, timber soffit
    rz = zc + 0.36
    ox0, oy0, ox1, oy1 = hx0 - 0.6, fy - 1.1, hx1 + 0.6, by + 1.1
    for (a, b, cc, dd) in ((ox0, oy0, ox1, qy0), (ox0, qy1, ox1, oy1), (ox0, qy0, qx0, qy1), (qx1, qy0, ox1, qy1)):
        k.box(roofw, a, b, rz, cc, dd, rz + rt)
        k.box(soffit, a + 0.02, b + 0.02, rz - 0.03, cc - 0.02, dd - 0.02, rz)
    # solar: PV rows on the back half, a green roof on the front
    c.pv_rows(ox0 + 0.8, qy1 + 0.6, ox1 - 0.8, oy1 - 0.6, rz + rt, row=1.6, frame=steel)
    k.box(c.lawn, ox0 + 0.5, oy0 + 0.6, rz + rt, ox1 - 0.5, qy0 - 0.4, rz + rt + 0.06)
    for _ in range(int((ox1 - ox0) / 2)):
        c.shrub(r.uniform(ox0 + 0.8, ox1 - 0.8), r.uniform(oy0 + 0.9, qy0 - 0.7), r.uniform(0.35, 0.55), z=rz + rt + 0.06)
    for i in range(int((ox1 - ox0) / 3.0)):
        k.plant("Fringe", "Foliage", r.choice(LEAF), ox0 + 1.5 + i * 3.0, oy0 + 0.05, rz + rt, 1.0, 1.0,
                r.uniform(0.6, 1.4), 0)
    # carport: two bays of the same steel frame and flat roof
    if carport:
        for x in (cx0 + 0.15 if car_left else cx1 - 0.15,):
            for y in (fy - 0.6, fy + 2 * bay):
                k.box(steel, x - 0.08, y - 0.08, 0, x + 0.08, y + 0.08, zc)
        k.box(steel, cx0, fy - 0.68, zc, cx1, fy - 0.52, zc + 0.36)
        k.box(roofw, cx0, fy - 1.1, rz, cx1, fy + 2 * bay + 0.6, rz + rt)
        k.box(soffit, cx0, fy - 1.1, rz - 0.03, cx1, fy + 2 * bay + 0.6, rz)
        k.box(colour[1], cx0 + 0.2 if car_left else cx1 - 0.3, fy + 2 * bay - 0.2, 0, cx0 + 0.3 if car_left else cx1 - 0.2,
              fy + 2 * bay + 0.6, zc)
        k.box(conc, cx0 + 0.3, 0, 0, cx1 - 0.3, fy + 2 * bay, 0.05)
        if r.random() < 0.7:
            car(c, (cx0 + cx1) / 2, fy + 1.6, cols[2])
    k.solid(hx0, fy, 0, hx1, by, zc)

    # garden: lawn, a birch grove and a magnolia, low agapanthus beds, steel-edged gravel, back lawn and fruit trees
    gl0, gl1 = (hx0, w - 0.3) if car_left else (0.3, hx1)
    c.lawn_patch(gl0, 0.3, gl1, fy - 1.3)
    exm = (gx[ent] + gx[ent + 1]) / 2
    for i in range(int((fy - 0.5) / 0.9)):
        k.box(conc, exm - 0.6, 0.3 + i * 0.9, 0, exm + 0.6, 0.9 + i * 0.9 - 0.2, 0.06)
    c.flowerbed(gl0 + 0.2, fy - 1.2, gl1 - 0.2, fy - 0.2, n=int(hw / 1.0), cols=(AGAPANTHUS, (246, 242, 230), CITRUS))
    for j in range(3):
        x = (gl0 + 1.5 + j * 1.3) if exm > (gl0 + gl1) / 2 else (gl1 - 1.5 - j * 1.3)
        k.plant("Trunk", "Bark", (232, 228, 220), x, 1.2 + (j % 2) * 1.0, 0, 0.18, 0.18, 4.0, roll=r.uniform(-5, 5))
        k.plant("Puff", "Foliage", (110, 150, 70), x, 1.2 + (j % 2) * 1.0, 4.3, 1.1, 1.1, 1.3)
    c.lawn_patch(0.3, by + 1.4, w - 0.3, d - 0.3)
    k.box(conc, hx0, by + 0.2, 0, hx1, by + 1.4, 0.06)
    if d - by > 4.0:
        c.scatter_trees(1.2, by + 2.6, w - 1.2, d - 1.0, max(1, int(w / 9)), min(plot.h_max + 2.5, 7.0), bloom=0.5)
    for _ in range(int(w / 2.0)):
        c.shrub(r.uniform(0.5, w - 0.5), r.uniform(d - 1.6, d - 0.4), r.uniform(0.7, 1.1))
    return k


KINDS = {"eichler_atrium": eichler_atrium, "sea_ranch": sea_ranch, "hedgerow_house": hedgerow_house,
         "hanna_honeycomb": hanna_honeycomb, "eichler_x100": eichler_x100}
SIZES = {
    "eichler_atrium": {"w": (16, 26), "d": (18, 32), "h": (4, 6), "floors": (1, 1), "use": "homes"},
    "sea_ranch": {"w": (24, 38), "d": (22, 34), "h": (7, 10), "floors": (2, 3), "use": "homes"},
    "hedgerow_house": {"w": (16, 26), "d": (16, 28), "h": (4.5, 7), "floors": (1, 2), "use": "homes"},
    "hanna_honeycomb": {"w": (24, 38), "d": (22, 34), "h": (5, 7.5), "floors": (1, 1), "use": "homes"},
    "eichler_x100": {"w": (18, 30), "d": (18, 30), "h": (4, 5.5), "floors": (1, 1), "use": "homes"},
}
