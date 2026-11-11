"""Glass houses: four famous mid-century glass pavilions re-imagined for the solarpunk Garden Village.

    farnsworth     Mies van der Rohe, Farnsworth House (Plano, Illinois) 1951
    glass_house    Philip Johnson, Glass House (New Canaan, Connecticut) 1949
    casa_de_vidro  Lina Bo Bardi, Casa de Vidro (Sao Paulo) 1951
    eames_house    Charles and Ray Eames, Eames House / Case Study House #8 (Pacific Palisades) 1949

Each keeps its signature move (Farnsworth's white columns welded to the outside of floating slabs; Johnson's
black steel corners and brick cylinder; Bo Bardi's glass box on thin pilotis with a tree through it; the Eames
two-storey black steel grid with primary-colour infill and the court between house and studio) and sets it in a
garden: trees close by, meadow flowers, green roofs out of sight, warm lit rooms behind the glass.
Local frame: x along the street (0..w), y away from it (0..d), z up, metres.
"""
import math

from .kit import Kit, WHITE, CONCRETE, GLASS, BRICK, TEAK, LEAF, FLOWER

BARK = (92, 78, 62)
TRAVERTINE = (226, 214, 188)
BLACK_STEEL = (34, 35, 38)
LAWN = (92, 138, 62)
EUCALYPT = (104, 132, 98)        # blue-grey green


def _clamp(v, a, b):
    return max(a, min(b, v))


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


# ---- planting ------------------------------------------------------------------------------------------------
def tree(k, rng, x, y, h, spread=None, z=0.0, leaf=None, bloom=None, trunk_r=None, layers=None):
    """A soft cushion tree: tapered trunk and 3-6 Puff cushions; bloom = flower colour dusted on top."""
    spread = spread or h * 0.32
    trunk_r = trunk_r or _clamp(h * 0.025, 0.12, 0.4)
    leaf = leaf or rng.choice(LEAF)
    th = h * 0.62
    k.plant("Trunk", "Bark", BARK, x, y, z, trunk_r / 0.5, trunk_r / 0.5, th, rng.uniform(0, 360))
    n = layers or rng.randint(3, 5)
    for i in range(n):
        a = rng.uniform(0, 2 * math.pi)
        r = spread * (0.15 + 0.45 * rng.random()) if i else 0.0
        s = spread * rng.uniform(0.55, 0.8) if i else spread * 0.75
        cz = z + th + rng.uniform(-0.1, 0.25) * h * 0.3 + (0.12 * h if i == 0 else 0)
        k.plant("Puff", "Foliage", rng.choice((leaf, leaf, rng.choice(LEAF))), x + r * math.cos(a), y + r * math.sin(a), cz,
                s, s, s * 0.75, rng.uniform(0, 360))
        if bloom and rng.random() < 0.8:
            k.plant("Puff", "Foliage", bloom, x + r * math.cos(a), y + r * math.sin(a), cz + s * 0.35,
                    s * 0.62, s * 0.62, s * 0.4, rng.uniform(0, 360), shadow=False)


def tall_tree(k, rng, x, y, h, spread, leaf=None, z=0.0):
    """Eucalyptus / forest tree: a long pale trunk and a loose crown of small cushions spread
    through its upper third (so it reads as airy, not as a lollipop)."""
    leaf = leaf or rng.choice(LEAF)
    r = _clamp(h * 0.018, 0.12, 0.3)
    k.plant("Trunk", "Bark", (168, 156, 136), x, y, z, r / 0.5, r / 0.5, h * 0.85, rng.uniform(0, 360))
    tx, ty = x, y
    n = rng.randint(4, 6)
    for i in range(n):
        f = i / max(1, n - 1)
        a = rng.uniform(0, 2 * math.pi)
        rr = spread * rng.uniform(0.2, 0.75) * (1.0 - 0.5 * f)
        s = spread * rng.uniform(0.42, 0.66)
        k.plant("Puff", "Foliage", rng.choice((leaf, EUCALYPT)), tx + rr * math.cos(a),
                ty + rr * math.sin(a), z + h * (0.62 + 0.3 * f) + rng.uniform(-0.2, 0.2), s, s, s * 0.55,
                rng.uniform(0, 360))


def shrub(k, rng, x, y, r, z=0.0, flowers=0.5, leaf=None):
    k.plant("Puff", "Foliage", leaf or rng.choice(LEAF), x, y, z + r * 0.3, r, r, r * 0.8, rng.uniform(0, 360))
    if rng.random() < flowers:
        c = rng.choice(FLOWER)
        for _ in range(rng.randint(1, 3)):
            a = rng.uniform(0, 2 * math.pi)
            k.plant("Blob", "Foliage", c, x + r * 0.45 * math.cos(a), y + r * 0.45 * math.sin(a), z + r * 0.95,
                    r * 0.32, r * 0.32, r * 0.22, shadow=False)


def flowers(k, rng, x0, y0, x1, y1, n, avoid=(), palette=None, z=0.0):
    """Meadow dots: grass tufts (Reed) and flower heads; avoid = list of (x0, y0, x1, y1) rects."""
    pal = list(FLOWER) + list(palette or [])
    for _ in range(n):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if any(a[0] <= x <= a[2] and a[1] <= y <= a[3] for a in avoid):
            continue
        if rng.random() < 0.45:
            s = rng.uniform(0.25, 0.5)
            k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, z, s, s, s * 0.6, rng.uniform(0, 360), shadow=False,
                    cull_m=90)
            c = rng.choice(pal)
            k.plant("Blob", "Foliage", c, x, y, z + s * 0.6, 0.13, 0.13, 0.1, shadow=False, cull_m=70)
        else:
            k.plant("Reed", "Foliage", rng.choice(LEAF), x, y, z, 1.6, 1.6, rng.uniform(0.4, 0.8),
                    rng.uniform(0, 360), shadow=False, cull_m=60)


def lawn(k, s, x0, y0, x1, y1, z=0.03):
    k.box(s, x0, y0, 0, x1, y1, z, skip=16)


def glazing(k, a, b, z0, z1, pane, glass, mull, lit=None, p_lit=0.0, rng=None, t=0.05, mw=0.06, md=0.1,
            rails=(), open_panes=(), fold=None):
    """A glass wall from a to b (along x or y) with mullions every ~pane m and transoms at z in rails. The glass is
    opaque, so a lived-in room is suggested by some panes glowing warm (curtain or lamp light behind, partly drawn).
    open_panes: pane indices left empty (open sliding doors). Returns the mullion positions along the run."""
    (ax, ay), (bx, by) = a, b
    along_x = abs(bx - ax) >= abs(by - ay)
    lo, hi = (min(ax, bx), max(ax, bx)) if along_x else (min(ay, by), max(ay, by))
    c = ay if along_x else ax
    L = hi - lo
    n = max(1, int(round(L / pane)))

    def B(s, u0, u1, v0, v1, w0, w1):         # u along the run, v across, w = z
        if along_x:
            k.box(s, u0, v0, w0, u1, v1, w1)
        else:
            k.box(s, v0, u0, w0, v1, u1, w1)

    edges = [lo + L * i / n for i in range(n + 1)]
    runs, cur = [], None                        # contiguous glass spans (skip open panes)
    for i in range(n):
        if i in open_panes:
            cur = None
            continue
        if cur is None:
            cur = [edges[i], edges[i + 1]]
            runs.append(cur)
        else:
            cur[1] = edges[i + 1]
    for u0, u1 in runs:
        B(glass, u0, u1, c - t / 2, c + t / 2, z0, z1)
    if lit is not None and rng is not None:
        for i in range(n):
            if i in open_panes or rng.random() >= p_lit:
                continue
            u0, u1 = edges[i], edges[i + 1]
            f = rng.choice((1.0, 0.55, 0.4, 0.3, 0.3))
            if rng.random() < 0.5:
                u1 = u0 + (u1 - u0) * f
            else:
                u0 = u1 - (u1 - u0) * f
            if fold is None:
                B(lit, u0 + 0.02, u1 - 0.02, c - t / 2 - 0.01, c + t / 2 + 0.01, z0 + 0.02, z1)
            else:                                # a drawn curtain: lit folds and shaded folds
                m = max(2, int((u1 - u0) / 0.16))
                for j in range(m):
                    v0, v1 = u0 + (u1 - u0) * j / m, u0 + (u1 - u0) * (j + 1) / m
                    B(lit if j % 2 == 0 else fold, v0 + 0.01, v1, c - t / 2 - 0.015, c + t / 2 + 0.015, z0 + 0.02, z1 - 0.02)
    for u in edges:
        B(mull, u - mw / 2, u + mw / 2, c - md / 2, c + md / 2, z0, z1)
    for z in rails:
        B(mull, lo, hi, c - md / 2, c + md / 2, z - mw / 2, z + mw / 2)
    return edges


# ---- Farnsworth House ----------------------------------------------------------------------------------------
def farnsworth(plot):
    """Mies, Farnsworth House 1951: a white steel frame whose eight wide-flange columns are welded to the OUTSIDE
    of two floating slabs; an open porch bay at one end; a lower floating terrace offset sideways; floating
    travertine steps; silk curtains behind full-height glass. Here: a flowering meadow, a big maple by the porch,
    a reed pond for the Fox River, a green roof with a few PV panels (only the canopy walk sees it)."""
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    W, D = plot.w, plot.d
    white = k.mat("Plain", WHITE)                # painted steel: Plain reads crisp white (Metal reads tan)
    glass = k.mat("SolarGlass", GLASS, 400)       # scale 400: smooth dark glass, not the PV cell grid
    trav = k.mat("Plain", TRAVERTINE)
    silk = k.mat("Lantern", (250, 215, 160))     # lamp-lit silk curtains behind the glass
    shade = k.mat("Lantern", (232, 192, 140))   # their folds
    lamp = silk
    groof = k.mat("GreenRoof", (120, 150, 80))
    grass = k.mat("Moss", LAWN)
    dark = k.mat("Plain", (46, 42, 40))          # leather chairs, shadows, PV
    accent = k.mat("Fabric", pal[1])             # cushions, rug
    water = k.mat("Water", (60, 92, 100))

    # ---- dimensions: three or more 6.7 m bays with ~1.7 m cantilevered ends, like the real 77 x 28 ft house
    L = _clamp(W - 4.0, 15.0, 29.0)
    cant = _clamp(L * 0.075, 1.2, 1.8)
    nb = max(2, int(round((L - 2 * cant) / 6.7)))
    bay = (L - 2 * cant) / nb
    HD = _clamp(D * 0.5, 7.0, 8.8)                 # house depth (y)
    hx0 = (W - L) / 2 + _clamp(W * 0.04, 0.6, 1.4)  # shifted right so the terrace can step out on the left
    hx1 = hx0 + L
    hy1 = D - _clamp(D * 0.08, 1.0, 1.8)
    hy0 = hy1 - HD
    fl = 1.6 if plot.h_max >= 5.4 else 1.2         # floor level (5'3" above the flood plain)
    ft = 0.42                                      # slab fascia depth
    ceil = fl + 2.9
    top = ceil + ft
    cw = 0.2                                       # W8 column flange
    # ---- house slabs
    k.box(white, hx0, hy0, fl - ft, hx1, hy1, fl)             # floor slab (white fascia)
    k.box(trav, hx0 + 0.02, hy0 + 0.02, fl, hx1 - 0.02, hy1 - 0.02, fl + 0.02, skip=16)  # travertine floor
    k.box(white, hx0, hy0, ceil, hx1, hy1, top - 0.22)        # roof slab ...
    for bx0, by0, bx1, by1 in ((hx0, hy0, hx1, hy0 + 0.15), (hx0, hy1 - 0.15, hx1, hy1),
                               (hx0, hy0, hx0 + 0.15, hy1), (hx1 - 0.15, hy0, hx1, hy1)):
        k.box(white, bx0, by0, top - 0.22, bx1, by1, top, skip=16)  # ... whose fascia hides a green roof
    k.box(groof, hx0 + 0.15, hy0 + 0.15, top - 0.22, hx1 - 0.15, hy1 - 0.15, top - 0.06, skip=16)
    # columns on the outside face of both long sides
    cols = [hx0 + cant + bay * i for i in range(nb + 1)]
    for x in cols:
        for y0c, y1c in ((hy0 - cw, hy0), (hy1, hy1 + cw)):
            k.box(white, x - 0.1, y0c, 0, x + 0.1, y1c, top)
    # ---- glass enclosure: everything but the porch bay (left: cantilever + first bay)
    gx0 = cols[1] if nb >= 3 else cols[0] + bay * 0.6
    gx1 = hx1 - 0.05
    gy0, gy1 = hy0 + 0.06, hy1 - 0.06
    z0, z1 = fl + 0.02, ceil
    pane = bay / 3.0
    glazing(k, (gx0, gy0), (gx1, gy0), z0, z1, pane, glass, white, silk, 0.22, rng, fold=shade)
    glazing(k, (gx0, gy1), (gx1, gy1), z0, z1, pane, glass, white, silk, 0.3, rng, fold=shade)
    glazing(k, (gx0, gy0), (gx0, gy1), z0, z1, pane, glass, white, silk, 0.25, rng, fold=shade)
    glazing(k, (gx1, gy0), (gx1, gy1), z0, z1, pane, glass, white, silk, 0.3, rng, fold=shade)
    # double door in the porch wall
    dy = (gy0 + gy1) / 2
    k.box(white, gx0 - 0.07, dy - 0.04, z0, gx0 + 0.07, dy + 0.04, z0 + 2.3)
    k.box(white, gx0 - 0.07, dy - 1.0, z0 + 2.26, gx0 + 0.07, dy + 1.0, z0 + 2.34)
    # porch life: a dark daybed and potted ferns under the roof
    k.box(dark, hx0 + cant * 0.6, hy1 - 2.2, z0, hx0 + cant * 0.6 + 0.8, hy1 - 0.4, z0 + 0.42)
    k.box(accent, hx0 + cant * 0.6 + 0.05, hy1 - 2.15, z0 + 0.42, hx0 + cant * 0.6 + 0.75, hy1 - 0.45, z0 + 0.5)
    for x, y in ((gx0 - 0.5, gy1 - 0.5), (gx0 - 0.5, gy0 + 0.5), (hx0 + 0.5, gy1 - 0.5)):
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, z0 + 0.3, 0.42, 0.42, 0.55, rng.uniform(0, 360))
    k.solid(hx0, hy0, 0, hx1, hy1, top)

    # ---- terrace: a lower floating slab, offset toward the porch end and out to the front
    tl = _clamp(L * 0.7, 10.0, 17.0)
    tx0 = max(0.6, hx0 - _clamp(W * 0.06, 0.5, 2.2))
    tx1 = tx0 + tl
    ty1 = hy0 - cw - 0.15
    ty0 = max(2.2, ty1 - _clamp(D * 0.36, 3.8, 6.7))
    tz = fl * 0.56                                   # terrace level, a third of the way to the floor
    k.box(white, tx0, ty0, tz - ft * 0.85, tx1, ty1, tz)
    k.box(trav, tx0 + 0.02, ty0 + 0.02, tz, tx1 - 0.02, ty1 - 0.02, tz + 0.02, skip=16)
    tn = max(2, int(round((tl - 2) / 6.7)))
    for i in range(tn + 1):
        x = tx0 + 1.0 + (tl - 2.0) * i / tn
        for y0c, y1c in ((ty0 - cw, ty0), (ty1, ty1 + cw)):
            k.box(white, x - 0.1, y0c, 0, x + 0.1, y1c, tz)
    # floating travertine steps: ground -> terrace (front edge), terrace -> porch
    sw = 2.6
    sx0 = tx0 + tl * 0.55
    n1 = max(3, int(round(tz / 0.18)))
    for i in range(n1):
        y = ty0 - (n1 - i) * 0.34
        z = tz * (i + 1) / (n1 + 0) - 0.08
        k.box(trav, sx0, y, z - 0.06, sx0 + sw, y + 0.36, z + 0.02)
    n2 = max(3, int(round((fl - tz) / 0.18)))
    px0 = hx0 + cant + 0.4
    for i in range(n2):
        y = ty1 - (n2 - i) * 0.34
        z = tz + (fl - tz) * (i + 1) / (n2 + 1)
        k.box(trav, px0, y, z - 0.06, px0 + sw, y + 0.36, z + 0.02)
    # terrace life: a pair of lounge chairs with block-colour cushions, a few pots
    for i in range(2):
        x = tx0 + 1.4 + i * 1.3
        k.box(dark, x, ty0 + 0.8, tz, x + 0.7, ty0 + 2.4, tz + 0.35)
        k.box(accent, x + 0.05, ty0 + 0.85, tz + 0.35, x + 0.65, ty0 + 2.35, tz + 0.42)
    for x, y in ((tx1 - 0.7, ty1 - 0.7), (tx1 - 0.7, ty0 + 0.7), (tx1 - 1.6, ty1 - 0.7)):
        k.cyl(trav, x, y, tz, 0.42, 0.3, 0.38, segs=10)
        shrub(k, rng, x, y, 0.42, z=tz + 0.38, flowers=0.9)

    # ---- garden: lawn, meadow, the big maple, a reed pond for the river, black maples behind
    lawn(k, grass, 0, 0, W, D)
    # pond at the front right (the Fox River in miniature) with reeds and stepping stones
    pr = _clamp(min(W - tx1, ty0) * 0.45, 1.2, 3.2)
    pcx, pcy = min(W - pr - 0.5, max(tx1 + pr + 1.0, W * 0.8)), max(pr + 0.4, ty0 * 0.5)
    if pcx - pr > tx1 - 0.5 or pcy + pr < ty0:
        k.cyl(water, pcx, pcy, 0.0, pr, pr, 0.06, segs=14)
        for _ in range(14):
            a = rng.uniform(0, 2 * math.pi)
            k.plant("Reed", "Foliage", rng.choice(LEAF), pcx + pr * math.cos(a) * rng.uniform(0.85, 1.1),
                    pcy + pr * math.sin(a) * rng.uniform(0.85, 1.1), 0, 2.2, 2.2, rng.uniform(0.9, 1.5), rng.uniform(0, 360))
        for _ in range(3):
            k.plant("Disc", "Foliage", (70, 120, 60), pcx + rng.uniform(-pr, pr) * 0.6, pcy + rng.uniform(-pr, pr) * 0.6,
                    0.07, 1.0, 1.0, 1.0, shadow=False)
    # the maple by the porch (Mies's sugar maple), flowering canopies elsewhere
    tree(k, rng, max(1.5, tx0 - 0.6), min(hy1 - 0.5, hy0 + 2.0), _clamp(plot.h_max * 1.4, 8.0, 10.5),
         spread=_clamp(W * 0.13, 2.8, 4.2), leaf=LEAF[2])
    tree(k, rng, W - 1.4, hy1 - 1.0, rng.uniform(7.0, 9.0), spread=3.0, bloom=rng.choice([FLOWER[1], pal[2], FLOWER[4]]))
    for i in range(int(L / 8) + 1):
        x = min(W - 1.2, hx0 + 3 + i * 8 + rng.uniform(-1, 1))
        tree(k, rng, x, D - 0.4, rng.uniform(6.5, 9.0), spread=2.6)
    # stepping stones from the street to the first step, with low lanterns
    sxm = sx0 + sw / 2
    y = 0.4
    i = 0
    while y < ty0 - n1 * 0.34 - 0.3:
        k.plant("Disc", "PermeableStone", TRAVERTINE, sxm + (0.35 if i % 2 else -0.35) * 0.6, y, 0.02, 1.1, 0.8, 1.0,
                rng.uniform(0, 30), shadow=False)
        if i % 2 == 0:
            for side in (-1, 1):
                lx = sxm + side * 1.2
                k.box(dark, lx - 0.05, y - 0.05, 0, lx + 0.05, y + 0.05, 0.55)
                k.box(lamp, lx - 0.09, y - 0.09, 0.55, lx + 0.09, y + 0.09, 0.75)
        y += 0.75
        i += 1
    path = (sxm - 1.4, 0, sxm + 1.4, ty0)
    # kitchen garden: timber raised beds behind the house end, where the plot is deep enough
    bed = k.mat("Timber", TEAK)
    beds = []
    bx = hx1 + 0.8
    if W - bx > 2.4:
        for j in range(3):
            by0 = hy0 + j * (HD / 3.0) + 0.3
            k.box(bed, bx, by0, 0, min(W - 0.4, bx + 1.4), by0 + HD / 3.0 - 0.6, 0.45)
            beds.append((bx, by0, min(W - 0.4, bx + 1.4), by0 + HD / 3.0 - 0.6))
            for q in range(4):
                k.plant("Puff", "Foliage", rng.choice(LEAF), bx + 0.35 + q * 0.3 * (min(W - 0.4, bx + 1.4) - bx) / 1.4,
                        by0 + 0.5 + rng.uniform(0, HD / 3.0 - 1.6), 0.45, 0.32, 0.32, 0.4, shadow=False)
    flowers(k, rng, 0.3, 0.3, W - 0.3, D - 0.3, int(W * D * 0.4),
            avoid=[(tx0 - 0.3, ty0 - 0.3, tx1 + 0.3, ty1 + 0.3), (hx0 - 0.3, hy0 - 0.3, hx1 + 0.3, hy1 + 0.3),
                   (sx0 - 0.3, ty0 - n1 * 0.34 - 0.5, sx0 + sw + 0.3, ty0), path,
                   (pcx - pr, pcy - pr, pcx + pr, pcy + pr)] + beds, palette=pal)
    for x in (hx1 - 2.0, hx1 - 7.0, tx1 + 1.0, hx0 + 1.0, (hx0 + hx1) / 2):
        shrub(k, rng, x, hy0 - 0.9, rng.uniform(0.6, 0.9), flowers=0.7)
    for x in (hx0 + 2.0, (hx0 + hx1) / 2 + 2.5, hx1 - 1.5):
        shrub(k, rng, x, min(hy1 + 0.9, D - 0.9), rng.uniform(0.7, 1.0), flowers=0.5)
    # clumps of tall flowering perennials in the meadow (foxglove / hollyhock spires)
    for _ in range(int(W / 5)):
        x, y = rng.uniform(1.0, W - 1.0), rng.uniform(0.6, max(0.8, ty0 - 2.2))
        if sx0 - 1.6 < x < sx0 + sw + 1.6:
            continue
        c = rng.choice(FLOWER + tuple(pal))
        for _q in range(rng.randint(3, 5)):
            px, py = x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.3, 0.3)
            hh = rng.uniform(0.9, 1.5)
            k.plant("Reed", "Foliage", LEAF[1], px, py, 0, 2.5, 2.5, hh, rng.uniform(0, 360), shadow=False, cull_m=70)
            k.plant("Blob", "Foliage", c, px, py, hh * 0.75, 0.09, 0.09, 0.28, shadow=False, cull_m=70)
    # a picnic in the meadow: blanket in the block colour, a basket
    bxp = W - 3.6 if sx0 < W * 0.5 else 1.2
    byp = rng.uniform(0.8, max(0.9, ty0 - 2.6))
    k.obox(accent, bxp + 1.0, byp + 0.7, 0.05, 0.9, 0.7, 0.012, 0, rng.uniform(-15, 15), 0)
    k.box(k.mat("Timber", TEAK), bxp + 1.5, byp + 0.9, 0.06, bxp + 1.9, byp + 1.15, 0.3)
    # PV panels on the green roof (for the canopy walk)
    for i in range(max(2, int((gx1 - gx0) / 3.2))):
        x = gx0 + 0.6 + i * 3.0
        if x + 2.4 > hx1 - 0.6:
            break
        k.obox(dark, x + 1.2, (hy0 + hy1) / 2, top - 0.08, 1.2, HD * 0.3, 0.025, 0, 0, 3)
    return k


# ---- Glass House ---------------------------------------------------------------------------------------------
def glass_house(plot):
    """Philip Johnson, Glass House 1949: a 56 x 32 ft glass box framed in charcoal steel (H-section corner
    columns plus two per long side, a deep black roof fascia), a brick floor 10 in above the lawn, a door centred
    in every face, and the only thing that touches the ceiling: a brick cylinder (bathroom + hearth) that rises
    through the roof. Inside: a low walnut cabinet wall, a white rug with Barcelona chairs, a painting on an easel.
    The glass here is opaque, so some panes are left empty: from the street you look straight through to the
    cylinder and the lamps. Garden: a promontory lawn ringed by big trees, a dry-stone wall, a flower meadow."""
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    W, D = plot.w, plot.d
    steel = k.mat("Plain", BLACK_STEEL)
    glass = k.mat("SolarGlass", GLASS, 400)
    brick = k.mat("PermeableStone", BRICK)
    floor = k.mat("PermeableStone", (176, 104, 80), 60)   # the herringbone-ish brick floor, finer
    walnut = k.mat("Timber", (110, 72, 46))
    rugc = k.mat("Plain", (236, 232, 222))
    leather = k.mat("Plain", (60, 48, 40))
    lamp = k.mat("Lantern", (250, 215, 160))
    groof = k.mat("GreenRoof", (120, 150, 80))
    grass = k.mat("Moss", LAWN)
    stone = k.mat("PermeableStone", (168, 162, 150), 120)
    accent = k.mat("Plain", pal[0])

    L = _clamp(W * 0.7, 12.0, 17.0)
    HD = _clamp(D * 0.62, 7.6, 9.8)
    x0 = (W - L) / 2
    x1 = x0 + L
    y1 = D - _clamp(D * 0.18, 2.4, 4.0)
    y0 = y1 - HD
    pz = 0.25                                         # brick floor 10 in above the lawn
    ceil = pz + _clamp(plot.h_max - 1.3, 2.7, 3.2)    # 10.5 ft room
    top = ceil + 0.42
    cw = 0.22
    # plinth + floor
    k.box(brick, x0 - 0.1, y0 - 0.1, 0, x1 + 0.1, y1 + 0.1, pz)
    k.box(floor, x0, y0, pz, x1, y1, pz + 0.01, skip=16)
    # roof: slab + black fascia lip hiding a green roof
    k.box(steel, x0, y0, ceil, x1, y1, top - 0.2)
    for bx0, by0, bx1, by1 in ((x0, y0, x1, y0 + 0.12), (x0, y1 - 0.12, x1, y1), (x0, y0, x0 + 0.12, y1),
                               (x1 - 0.12, y0, x1, y1)):
        k.box(steel, bx0, by0, top - 0.2, bx1, by1, top, skip=16)
    k.box(groof, x0 + 0.12, y0 + 0.12, top - 0.2, x1 - 0.12, y1 - 0.12, top - 0.05, skip=16)
    k.box(rugc, x0 + 0.05, y0 + 0.05, ceil - 0.02, x1 - 0.05, y1 - 0.05, ceil, skip=32)  # ceiling
    # columns: H-section corners (two flanges), two more on each long side
    for cx, sx in ((x0, 1), (x1, -1)):
        for cy, sy in ((y0, 1), (y1, -1)):
            k.box(steel, cx - (cw if sx > 0 else 0) * 0 - (0 if sx > 0 else 0), cy, 0, cx + sx * cw, cy + sy * 0.05, top)
            k.box(steel, cx, cy, 0, cx + sx * 0.05, cy + sy * cw, top)
    bays = [x0 + L * i / 3 for i in range(4)]
    for x in bays[1:3]:
        for y, s in ((y0, 1), (y1, -1)):
            k.box(steel, x - 0.1, min(y, y + s * 0.2), 0, x + 0.1, max(y, y + s * 0.2), top)
    # black steel base channel all round, at floor level
    for bx0, by0, bx1, by1 in ((x0, y0, x1, y0 + 0.08), (x0, y1 - 0.08, x1, y1), (x0, y0, x0 + 0.08, y1),
                               (x1 - 0.08, y0, x1, y1)):
        k.box(steel, bx0, by0, pz, bx1, by1, pz + 0.12)
    # glazing: long sides 3 bays x 2 panes, short sides 3 panes; door in the middle of each face.
    z0, z1 = pz, ceil
    dh = pz + 2.25
    pane = L / 6
    # open = transparent panes (the glass reads opaque, so leave some empty to see in)
    front_open = {1, 2, 3, 4}
    back_open = {2, 3}
    glazing(k, (x0, y0 + 0.03), (x1, y0 + 0.03), z0, z1, pane, glass, steel, md=0.1, open_panes=front_open)
    glazing(k, (x0, y1 - 0.03), (x1, y1 - 0.03), z0, z1, pane, glass, steel, md=0.1, open_panes=back_open)
    glazing(k, (x0 + 0.03, y0), (x0 + 0.03, y1), z0, z1, HD / 3, glass, steel, md=0.1, open_panes={1})
    glazing(k, (x1 - 0.03, y0), (x1 - 0.03, y1), z0, z1, HD / 3, glass, steel, md=0.1)
    # doors: a door frame + transom rail in the middle pane of each face
    xm = (x0 + x1) / 2
    ym = (y0 + y1) / 2
    for y in (y0 + 0.03, y1 - 0.03):
        k.box(steel, xm - 0.55, y - 0.05, dh - 0.04, xm + 0.55, y + 0.05, dh + 0.04)
        k.box(steel, x0 + 2 * pane, y - 0.05, dh - 0.03, x0 + 4 * pane, y + 0.05, dh + 0.03)
    for x in (x0 + 0.03, x1 - 0.03):
        k.box(steel, x - 0.05, ym - 0.55, dh - 0.04, x + 0.05, ym + 0.55, dh + 0.04)
        k.box(steel, x - 0.05, y0 + HD / 3, dh - 0.03, x + 0.05, y0 + 2 * HD / 3, dh + 0.03)
    # interior layout, mirrored along x by seed
    mir = rng.random() < 0.5

    def MX(x):
        return x0 + x1 - x if mir else x

    def Bm(s_, ax, ay, az, bx, by, bz):
        ax, bx = MX(ax), MX(bx)
        k.box(s_, min(ax, bx), ay, az, max(ax, bx), by, bz)

    # ---- the brick cylinder, off centre toward the back right, rising through the roof
    cr = 1.5 if L >= 14 else 1.25
    ccx, ccy = x0 + L * 0.68, y0 + HD * 0.62
    k.cyl(brick, MX(ccx), ccy, pz, cr, cr, min(top + 0.6, plot.h_max - 0.05) - pz, segs=20)
    k.cyl(steel, MX(ccx), ccy, min(top + 0.6, plot.h_max - 0.05) - 0.06, cr + 0.04, cr + 0.04, 0.06, segs=20)  # cap
    Bm(leather, ccx - 0.6, ccy - cr - 0.02, pz + 0.35, ccx + 0.6, ccy - cr + 0.4, pz + 1.15)  # hearth
    Bm(lamp, ccx - 0.42, ccy - cr + 0.05, pz + 0.38, ccx + 0.42, ccy - cr + 0.3, pz + 0.62)                        # fire
    # ---- interior
    # walnut cabinet wall (bed screen) at the left end, kitchen counter on the right
    Bm(walnut, x0 + L * 0.2, y0 + HD * 0.45, pz, x0 + L * 0.2 + 0.6, y1 - 0.9, pz + 1.8)
    Bm(walnut, x0 + L * 0.84, y0 + 0.9, pz, x1 - 0.8, y0 + 1.6, pz + 0.95)
    # bed
    Bm(rugc, x0 + 0.8, y0 + HD * 0.55, pz, x0 + L * 0.2 - 0.3, y1 - 1.0, pz + 0.45)
    Bm(accent, x0 + 0.8, y0 + HD * 0.55, pz + 0.45, x0 + L * 0.2 - 0.3, y0 + HD * 0.55 + 0.9, pz + 0.5)
    # living group on a white rug: four dark chairs and a low table
    lx, ly = x0 + L * 0.42, y0 + HD * 0.42
    Bm(rugc, lx - 1.8, ly - 1.4, pz, lx + 1.8, ly + 1.4, pz + 0.02)
    for sx, sy in ((-1.1, -0.8), (1.1, -0.8), (-1.1, 0.8), (1.1, 0.8)):
        Bm(leather, lx + sx - 0.36, ly + sy - 0.36, pz, lx + sx + 0.36, ly + sy + 0.36, pz + 0.42)
        Bm(leather, lx + sx - 0.36, ly + sy + 0.26 * (1 if sy > 0 else -1) - 0.06, pz + 0.42,
              lx + sx + 0.36, ly + sy + 0.26 * (1 if sy > 0 else -1) + 0.06, pz + 0.8)
    Bm(glass, lx - 0.5, ly - 0.4, pz + 0.38, lx + 0.5, ly + 0.4, pz + 0.42)
    # the painting on its easel
    ex, ey = lx - 2.4, y0 + 1.4
    k.pole(walnut, (MX(ex - 0.4), ey, pz), (MX(ex), ey + 0.1, pz + 1.9), 0.03)
    k.pole(walnut, (MX(ex + 0.4), ey, pz), (MX(ex), ey + 0.1, pz + 1.9), 0.03)
    Bm(accent, ex - 0.55, ey - 0.05, pz + 0.8, ex + 0.55, ey, pz + 1.65)
    # dining table + chairs, lamps
    tx, ty = x0 + L * 0.84, y0 + HD * 0.5
    Bm(walnut, tx - 0.6, ty - 0.6, pz + 0.72, tx + 0.6, ty + 0.6, pz + 0.76)
    k.cyl(steel, MX(tx), ty, pz, 0.08, 0.08, 0.72, segs=6)
    for a in range(4):
        ang = a * math.pi / 2
        Bm(leather, tx + 0.85 * math.cos(ang) - 0.2, ty + 0.85 * math.sin(ang) - 0.2, pz,
              tx + 0.85 * math.cos(ang) + 0.2, ty + 0.85 * math.sin(ang) + 0.2, pz + 0.45)
    for x, y in ((lx + 2.0, ly - 1.2), (x0 + L * 0.2 - 0.6, y0 + 1.0), (tx - 1.4, ty + 1.2)):
        k.cyl(steel, MX(x), y, pz, 0.02, 0.02, 1.35, segs=4, caps=False)
        k.cyl(lamp, MX(x), y, pz + 1.35, 0.22, 0.16, 0.3, segs=8)
    # indoor plants
    for x, y in ((x0 + 0.6, y0 + 0.6), (x1 - 0.6, y1 - 0.6), (lx + 2.3, y1 - 0.7)):
        k.plant("Puff", "Foliage", rng.choice(LEAF), MX(x), y, pz + 0.35, 0.45, 0.45, 0.7, rng.uniform(0, 360))
    k.solid(x0, y0, 0, x1, y1, top)

    # ---- garden: the lawn promontory, a dry-stone wall at the street, big trees, a meadow
    lawn(k, grass, 0, 0, W, D)
    # dry-stone wall along the street with a gap on the path
    gx = xm
    for a0, a1 in ((0.3, gx - 1.2), (gx + 1.2, W - 0.3)):
        if a1 - a0 > 0.8:
            k.box(stone, a0, 0.3, 0, a1, 0.85, 0.75)
            for _ in range(int((a1 - a0) / 1.6)):
                x = rng.uniform(a0 + 0.3, a1 - 0.3)
                k.plant("Puff", "Foliage", rng.choice(LEAF), x, 0.6, 0.7, 0.45, 0.35, 0.3, rng.uniform(0, 360),
                        shadow=False)
                if rng.random() < 0.6:
                    k.plant("Blob", "Foliage", rng.choice(FLOWER), x + 0.1, 0.55, 0.92, 0.14, 0.14, 0.1, shadow=False)
    # path of flat stones to the front door
    y = 1.2
    while y < y0 - 0.5:
        k.plant("Disc", "PermeableStone", (190, 184, 170), gx + rng.uniform(-0.15, 0.15), y, 0.02, 1.3, 0.9, 1.0,
                rng.uniform(0, 40), shadow=False)
        y += 0.8
    # big trees around the promontory, two in front framing the house, one flowering
    spots = [(1.4, D - 1.6), (W - 1.4, D - 1.4), (1.6, y0 + 1.0), (W - 1.8, y0 - 0.6), (W * 0.35, D - 0.8)]
    for i, (x, y) in enumerate(spots):
        tree(k, rng, x, y, rng.uniform(7.5, 10.5), spread=rng.uniform(2.6, 3.6),
             bloom=(pal[2] if i == 3 else (FLOWER[1] if i == 1 else None)))
    flowers(k, rng, 0.3, 1.0, W - 0.3, D - 0.3, int(W * D * 0.35),
            avoid=[(x0 - 1.2, y0 - 1.2, x1 + 1.2, y1 + 0.6), (gx - 0.9, 0, gx + 0.9, y0)], palette=pal)
    for x in (x0 - 0.9, x1 + 0.9):
        for y in (y0 + 0.5, y1 - 0.5):
            shrub(k, rng, x, y, rng.uniform(0.6, 0.85), flowers=0.6)
    # garden lanterns along the path, a timber bench under the front tree facing the house
    y = 1.6
    while y < y0 - 0.6:
        for sx in (-0.9, 0.9):
            k.cyl(steel, gx + sx, y, 0, 0.035, 0.035, 0.55, segs=4, caps=False)
            k.cyl(lamp, gx + sx, y, 0.55, 0.1, 0.1, 0.2, segs=6)
        y += 1.8
    bx = W - 3.4 if rng.random() < 0.5 else 1.4
    by = max(1.6, y0 - 2.4)
    bench = walnut
    k.box(bench, bx, by, 0.42, bx + 1.8, by + 0.45, 0.48)
    k.box(bench, bx, by + 0.4, 0.48, bx + 1.8, by + 0.46, 0.85)
    for xx in (bx + 0.1, bx + 1.6):
        k.box(steel, xx, by + 0.05, 0, xx + 0.1, by + 0.4, 0.42)
    return k


# ---- Casa de Vidro -------------------------------------------------------------------------------------------
def casa_de_vidro(plot):
    """Lina Bo Bardi, Casa de Vidro 1951: a long glass living box on slender round steel pilotis, held out from a
    forested hillside; the back of the house rests on the hill as a plain rendered wing. A light steel stair
    climbs from the garden straight up through the floor; a patio void opens through the middle of the box and a
    tree grows up through it. Sky-blue glass-mosaic floor, white slabs, sliding panes open to the trees.
    Here the hill is a stack of planted stone terraces, and the forest crowds right up to the glass."""
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    W, D = plot.w, plot.d
    white = k.mat("Plain", WHITE)
    glass = k.mat("SolarGlass", GLASS, 400)
    mull = k.mat("Plain", (70, 74, 78))
    mosaic = k.mat("Plain", (128, 186, 214))
    render = k.mat("Plain", (232, 226, 210))
    stone = k.mat("PermeableStone", (176, 166, 146), 90)
    groof = k.mat("GreenRoof", (120, 150, 80))
    soil = k.mat("Moss", (112, 150, 70))
    wood = k.mat("Timber", (150, 100, 62))
    lamp = k.mat("Lantern", (250, 215, 160))
    dark = k.mat("Plain", (44, 42, 40))
    accent = k.mat("Plain", pal[0])

    # ---- dimensions
    BW = _clamp(W - 4.5, 13.0, 24.0)
    BD = _clamp(D * 0.48, 7.5, 11.5)
    bx0 = (W - BW) / 2
    bx1 = bx0 + BW
    by0 = _clamp(D * 0.16, 2.4, 4.0)
    by1 = by0 + BD
    room = 3.0
    fl = _clamp(plot.h_max - room - 1.2, 3.4, 5.2)       # floor level at the front (the hill falls away)
    st = 0.32                                           # slab thickness
    top = fl + room + st
    # ---- the hill: a planted slope rising under the back half of the box to floor level, then a plateau
    ha = by0 + BD * 0.15
    hb = by1 - 0.2
    nl = math.hypot(fl, hb - ha)
    k.quad(soil, (0.3, ha, 0.02), (W - 0.3, ha, 0.02), (W - 0.3, hb, fl), (0.3, hb, fl), (0, -fl / nl, (hb - ha) / nl))
    for x, nx in ((0.3, -1), (W - 0.3, 1)):
        k.tri(soil, (x, ha, 0), (x, hb, 0), (x, hb, fl), (nx, 0, 0))
    k.box(stone, 0.3, hb, 0, W - 0.3, D - 0.3, fl - 0.08)
    k.box(soil, 0.3, hb, fl - 0.08, W - 0.3, D - 0.3, fl, skip=16)

    def ground(y):                                      # ground height under the box at y
        return _clamp((y - ha) / (hb - ha), 0.0, 1.0) * fl

    # a low dry-stone wall part way up, and the slope dressed with ferns, shrubs and flowers
    wy = ha + (hb - ha) * 0.45
    k.box(stone, 0.5, wy - 0.2, 0, W * rng.uniform(0.35, 0.6), wy + 0.2, ground(wy) + 0.45)
    for _ in range(int(W * 4.5)):
        x, y = rng.uniform(0.6, W - 0.6), rng.uniform(ha + 0.2, D - 0.6)
        z = ground(y)
        if rng.random() < 0.3:
            k.plant("Reed", "Foliage", rng.choice(LEAF), x, y, z, 2.0, 2.0, rng.uniform(0.5, 1.0), rng.uniform(0, 360),
                    shadow=False, cull_m=60)
            continue
        r = rng.uniform(0.4, 1.0)
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, z, r, r, r * 0.7, rng.uniform(0, 360), shadow=False)
        if rng.random() < 0.22:
            k.plant("Blob", "Foliage", rng.choice(FLOWER + tuple(pal)), x, y, z + r * 0.6, 0.16, 0.16, 0.12,
                    shadow=False)
    for i in range(int(W / 0.9)):                        # plants trailing over the plateau edge at the back
        x = 0.6 + (W - 1.2) * (i + rng.random()) / int(W / 0.9)
        k.plant("Fringe", "Foliage", rng.choice(LEAF), x, D - 0.28, fl, rng.uniform(0.9, 1.5), 1.0,
                fl * rng.uniform(0.35, 0.85), 0, shadow=False)
        if i % 3 == 0:
            r = rng.uniform(0.5, 0.9)
            k.plant("Puff", "Foliage", rng.choice(LEAF), x, D - 0.1, 0, r, r * 0.7, r, rng.uniform(0, 360), shadow=False)
            if rng.random() < 0.4:
                k.plant("Blob", "Foliage", rng.choice(FLOWER), x, D - 0.1, r * 0.8, 0.15, 0.15, 0.12, shadow=False)
    for x in (0.28, W - 0.28):                            # creepers down the side walls of the plateau
        for i in range(int((D - hb) / 1.2)):
            k.plant("Fringe", "Foliage", rng.choice(LEAF), x, hb + 0.6 + i * 1.2, fl, 1.1, 1.0, fl * rng.uniform(0.3, 0.7),
                    90 if x > 1 else 270, shadow=False)

    # ---- slabs (with the patio void and the stair opening cut out)
    px0 = bx0 + BW * 0.58
    px1 = px0 + _clamp(BW * 0.16, 2.4, 3.6)
    py0 = by0 + BD * 0.5
    py1 = by1 - 1.6
    n = int(math.ceil(fl / 0.18))                       # stair: a straight flight along the front, under the box
    run = 0.27
    sxa = bx0 + 1.2
    sxb = sxa + n * run
    sy0, sy1 = by0 + 1.0, by0 + 2.2
    sx0, sx1 = sxb - 2.4, sxb                           # floor opening at its head

    def slab(s, z0, z1, holes):
        """Slab over the box footprint minus rectangular holes (x-strips)."""
        xs = sorted({bx0, bx1} | {h[0] for h in holes} | {h[2] for h in holes})
        for a, b in zip(xs, xs[1:], strict=False):
            ys = [by0]
            for h in holes:
                if h[0] <= a and b <= h[2]:
                    ys += [h[1], h[3]]
            ys.append(by1)
            ys.sort()
            for j in range(0, len(ys), 2):
                if ys[j + 1] - ys[j] > 0.01:
                    k.box(s, a, ys[j], z0, b, ys[j + 1], z1)

    slab(white, fl - st, fl, [(px0, py0, px1, py1), (sx0, sy0, sx1, sy1)])
    slab(mosaic, fl, fl + 0.015, [(px0, py0, px1, py1), (sx0, sy0, sx1, sy1)])
    slab(white, fl + room, top, [(px0, py0, px1, py1)])
    k.box(groof, bx0 + 0.2, by0 + 0.2, top, bx1 - 0.2, by1 - 0.2, top + 0.06, skip=16)  # roof garden
    # ---- pilotis: thin round columns on a 2-3 row grid, standing on the terrace or ground below
    ncx = max(3, int(round(BW / 4.2)) + 1)
    rows = [by0 + 0.6, by0 + BD * 0.5 - 0.3]
    if BD > 9:
        rows.append(by1 - 0.6)
    for y in rows:
        g = ground(y)
        if fl - st - g < 0.4:
            continue
        for i in range(ncx):
            x = bx0 + 0.6 + (BW - 1.2) * i / (ncx - 1)
            k.cyl(white, x, y, g, 0.09, 0.09, fl - st - g, segs=8)
    # ---- glass walls: front and sides fully glazed (some sliding panes pushed open), back half on the hill
    z0, z1 = fl, fl + room
    pane = 1.5
    nfront = max(1, int(round(BW / pane)))
    open_f = {i for i in range(nfront) if rng.random() < 0.4}
    glazing(k, (bx0, by0 + 0.08), (bx1, by0 + 0.08), z0, z1, pane, glass, mull, lamp, 0.12, rng, mw=0.05, md=0.08,
            rails=(z0 + 2.35,), open_panes=open_f)
    for x in (bx0 + 0.06, bx1 - 0.06):
        glazing(k, (x, by0 + 0.08), (x, by0 + BD * 0.62), z0, z1, pane, glass, mull, lamp, 0.15, rng, mw=0.05,
                md=0.08, rails=(z0 + 2.35,), open_panes={0} if rng.random() < 0.5 else ())
        k.box(render, x - 0.1, by0 + BD * 0.62, z0, x + 0.1, by1, z1)
    k.box(render, bx0, by1 - 0.2, z0, bx1, by1, z1)
    # glass round the patio void
    for (a, b) in (((px0, py0), (px1, py0)), ((px0, py0), (px0, py1)), ((px1, py0), (px1, py1))):
        glazing(k, a, b, z0, z1, 1.2, glass, mull, mw=0.05, md=0.08, open_panes={0} if a[1] == b[1] else ())
    # roof fascia line (a thin white edge that reads from far)
    k.box(white, bx0 - 0.15, by0 - 0.15, top - 0.12, bx1 + 0.15, by0, top)
    # ---- interior seen through the open panes: bookcase wall, bowl chairs, a long table, lamps, plants
    k.box(wood, bx0 + 0.6, by1 - 0.65, z0, px0 - 0.6, by1 - 0.25, z0 + 2.4)
    for i in range(int((px0 - bx0 - 1.2) / 0.9)):
        x = bx0 + 0.7 + i * 0.9
        k.box(rng.choice([accent, dark, render, lamp]), x, by1 - 0.68, z0 + 0.4 + (i % 3) * 0.6, x + 0.5,
              by1 - 0.6, z0 + 0.65 + (i % 3) * 0.6)
    for i in range(3):
        x = bx0 + BW * (0.12 + 0.12 * i)
        y = by0 + 2.0 + (i % 2) * 1.2
        k.ell(accent if i != 1 else dark, x, y, z0 + 0.55, 0.45, 0.45, 0.3, segs=10, rings=4, hemi=True)
        k.cyl(dark, x, y, z0, 0.2, 0.2, 0.42, segs=6)
    k.box(wood, bx0 + BW * 0.68, by0 + 1.2, z0 + 0.74, bx0 + BW * 0.68 + 2.6, by0 + 2.2, z0 + 0.79)
    for x in (bx0 + BW * 0.68 + 0.4, bx0 + BW * 0.68 + 2.2):
        k.box(wood, x - 0.05, by0 + 1.3, z0, x + 0.05, by0 + 2.1, z0 + 0.74)
    for x, y in ((bx0 + BW * 0.3, by0 + 3.3), (bx1 - 1.0, by0 + 1.0), (bx0 + 1.0, by0 + 1.0)):
        k.cyl(dark, x, y, z0, 0.02, 0.02, 1.4, segs=4, caps=False)
        k.cyl(lamp, x, y, z0 + 1.4, 0.25, 0.18, 0.3, segs=8)
    k.box(lamp, bx0 + 1.0, by0 + 1.0, z1 - 0.05, bx1 - 1.0, by0 + 1.3, z1)     # light along the front ceiling
    for x in (bx0 + 0.7, bx1 - 0.7, bx0 + BW * 0.5):
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, by0 + 0.6, z0 + 0.4, 0.55, 0.55, 0.85, rng.uniform(0, 360))
    k.solid(bx0, by0, fl - st, bx1, by1, top)
    for y in rows:
        k.solid(bx0 + 0.5, y - 0.1, 0, bx1 - 0.5, y + 0.1, fl - st)
    # ---- the stair: a single light steel flight from the garden straight up into the floor
    for i in range(n):
        x = sxa + i * run
        z = fl * (i + 1) / n
        k.box(dark, x, sy0 + 0.05, z - 0.04, x + run + 0.03, sy1 - 0.05, z)
    for y in (sy0 + 0.04, sy1 - 0.04):
        k.beam(dark, (sxa, y, 0.0), (sxb, y, fl), 0.06, 0.2)
        k.pole(dark, (sxa, y, 0.95), (sxb, y, fl + 0.95), 0.02, segs=5)
        for j in range(0, n, 4):
            x = sxa + j * run
            k.pole(dark, (x, y, fl * j / n), (x, y, fl * j / n + 0.95), 0.015, segs=4)
    k.box(stone, sxa - 1.2, sy0 - 0.3, 0, sxa, sy1 + 0.3, 0.05)            # landing pad
    # ---- the back wing on the hill: plain render, small windows, green roof
    wy0 = by1
    if D - wy0 > 3.0:
        wx0, wx1 = bx0 + BW * 0.1, bx1 - BW * 0.3
        wh = 2.9
        k.box(render, wx0, wy0, fl, wx1, D - 0.8, fl + wh)
        k.box(groof, wx0 - 0.1, wy0 - 0.1, fl + wh, wx1 + 0.1, D - 0.7, fl + wh + 0.2)
        for i in range(int((wx1 - wx0) / 2.4)):
            x = wx0 + 1.0 + i * 2.4
            k.box(wood, x, D - 0.85, fl + 0.9, x + 0.9, D - 0.75, fl + 2.2)
        k.solid(wx0, wy0, fl, wx1, D - 0.8, fl + wh)
    # ---- the forest: the patio tree through the roof, trees crowding the sides, an understorey
    hmax = plot.h_max
    tcx, tcy = (px0 + px1) / 2, (py0 + py1) / 2
    th = min(hmax + 6.0, top + 4.5)
    k.plant("Trunk", "Bark", BARK, tcx, tcy, ground(tcy), 0.5, 0.5, th - ground(tcy) - 1.6, rng.uniform(0, 360))
    for i in range(4):
        a = i * math.pi / 2 + rng.uniform(-0.4, 0.4)
        r = 1.2 if i else 0
        k.plant("Puff", "Foliage", rng.choice(LEAF), tcx + r * math.cos(a), tcy + r * math.sin(a), th - 1.9,
                2.4, 2.4, 1.6, rng.uniform(0, 360))
    for x, y in ((bx0 - 1.2, by0 + 1.0), (bx1 + 1.0, by0 + 2.5), (bx0 - 0.8, by1 - 0.5), (bx1 + 1.2, by1 + 0.5),
                 (W * 0.5 + rng.uniform(-3, 3), D - 0.5)):
        x = _clamp(x, 0.6, W - 0.6)
        tall_tree(k, rng, x, y, min(hmax + 6.0, rng.uniform(11.0, 16.0)), rng.uniform(2.6, 3.6))
    for i in range(int(W / 7) + 1):                    # forest on the hill behind
        x = 2.0 + (W - 4.0) * (i + rng.uniform(0.2, 0.8)) / (int(W / 7) + 1)
        tall_tree(k, rng, x, D - rng.uniform(0.8, 2.0), min(hmax + 6.0, fl + rng.uniform(7.0, 11.0)) - fl, rng.uniform(2.4, 3.4), z=fl)
    tree(k, rng, max(1.2, bx0 + 0.4), 1.0, rng.uniform(5.5, 7.0), spread=2.4, bloom=rng.choice((FLOWER[4], pal[2])))
    tree(k, rng, min(W - 1.2, bx1 - 1.0), 0.9, rng.uniform(5.0, 6.5), spread=2.2, bloom=FLOWER[0])
    # understorey under the house: ferns, a stone path to the stair, a bench
    for _ in range(int(BW * 0.9)):
        x, y = rng.uniform(bx0, bx1), rng.uniform(0.6, ha)
        if sxa - 1.4 < x < sxb + 0.3 and y < sy1 + 0.4:
            continue
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, 0, rng.uniform(0.35, 0.7), rng.uniform(0.35, 0.7), 0.5,
                rng.uniform(0, 360), shadow=False)
        if rng.random() < 0.3:
            k.plant("Blob", "Foliage", rng.choice(FLOWER + tuple(pal)), x, y, 0.45, 0.14, 0.14, 0.1, shadow=False)
    y = 0.4
    i = 0
    while y < sy0 - 0.4:
        k.plant("Disc", "PermeableStone", (186, 178, 160), sxa - 0.6 + rng.uniform(-0.2, 0.2), y, 0.02, 1.2,
                0.9, 1.0, rng.uniform(0, 40), shadow=False)
        if i % 2 == 0:                                   # low path lanterns
            lx = sxa - 1.5
            k.cyl(dark, lx, y, 0, 0.04, 0.04, 0.5, segs=4, caps=False)
            k.cyl(lamp, lx, y, 0.5, 0.12, 0.1, 0.22, segs=6)
        y += 0.8
        i += 1
    k.box(wood, bx1 - 4.0, by0 + 1.6, 0.42, bx1 - 2.2, by0 + 2.0, 0.48)
    for x in (bx1 - 3.9, bx1 - 2.4):
        k.box(stone, x, by0 + 1.65, 0, x + 0.15, by0 + 1.95, 0.42)
    k.box(lamp, bx1 - 3.3, by0 + 1.7, fl - st - 0.06, bx1 - 2.9, by0 + 1.9, fl - st)   # a lamp under the slab
    flowers(k, rng, 0.3, 0.3, W - 0.3, by0 - 0.2, int(W * 3.5), avoid=[(sxa - 1.4, 0, sxa + 0.2, by0)], palette=pal)
    return k


# ---- Eames House ---------------------------------------------------------------------------------------------
EAMES_RED = (196, 52, 40)
EAMES_BLUE = (36, 70, 158)
EAMES_YELLOW = (232, 184, 48)
EAMES_WHITE = (238, 236, 226)
EAMES_BLACK = (34, 34, 36)
CEMESTO = (156, 152, 140)
TRANSLUCENT = (226, 228, 220)


def eames_house(plot):
    """Charles and Ray Eames, Eames House (Case Study House #8) 1949: two boxes of the same off-the-shelf steel
    kit, a two-storey frame on a 7 ft 4 in bay, the residence and the studio, with a court between them, set
    against a retaining wall on the hillside and fronted by a meadow and a row of eucalyptus. The facades are a
    grid of glass, translucent wired glass and flat stucco panels in red, blue, white, black and ochre, braced by
    thin X-rods. Here the court is a kitchen garden under lanterns, and the roofs carry sedum and PV."""
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    W, D = plot.w, plot.d
    frame = k.mat("Plain", EAMES_BLACK)
    glass = k.mat("SolarGlass", GLASS, 400)
    lit = k.mat("Lantern", (250, 215, 160))
    trans = k.mat("Plain", TRANSLUCENT)
    cols = {"red": k.mat("Plain", EAMES_RED), "blue": k.mat("Plain", EAMES_BLUE), "yellow": k.mat("Plain", EAMES_YELLOW),
            "white": k.mat("Plain", EAMES_WHITE), "black": frame, "grey": k.mat("Plain", CEMESTO)}
    accent = k.mat("Plain", pal[1])
    conc = k.mat("PermeableStone", CONCRETE, 200)
    pave = conc
    wood = k.mat("Timber", (170, 120, 76))
    groof = k.mat("GreenRoof", (120, 150, 80))
    grass = k.mat("Moss", LAWN)
    pv = frame

    # ---- module: 7'4" bays; split the frontage into residence | court | studio
    bay = 2.24
    nb = max(12, int((W - 1.6) / bay))
    n_studio = max(4, int(round(nb * 0.3)))
    n_court = max(3, int(round(nb * 0.22)))
    n_house = nb - n_studio - n_court
    x0 = (W - nb * bay) / 2
    # local +x runs right-to-left seen from the street: studio at low x so that, as at Pacific Palisades seen from
    # the meadow, the residence is on the left and the studio on the right
    sx0, sx1 = x0, x0 + n_studio * bay
    hx0, hx1 = sx1 + n_court * bay, x0 + nb * bay
    BD = _clamp(D * 0.45, 6.1, 7.0)                    # 20 ft deep
    y1 = D - 1.6                                        # retaining wall behind
    y0 = y1 - BD
    h1 = 3.0                                            # first floor line
    h2 = _clamp(plot.h_max - 0.7, 6.0, 6.6)             # roof underside
    top = h2 + 0.45
    fw = 0.11                                           # 4 in H columns

    def facade(axis_x, c, u0, u1, n, outward, pattern, double=()):
        """Panel grid on a wall at y = c (axis_x) or x = c; n bays from u0 to u1; outward = +1/-1 normal sign.
        pattern(i, storey) -> one of 'glass', 'glass4', 'lit', 'open', 'trans', 'solid:<col>', 'split:<col>'.
        double: bays that are one double-height glass wall (the living room)."""
        def B(s, a0, a1, z0, z1, d0, d1):
            if axis_x:
                k.box(s, a0, c + d0 * outward if outward > 0 else c + d1 * outward, z0, a1,
                      c + d1 * outward if outward > 0 else c + d0 * outward, z1)
            else:
                k.box(s, c + d0 * outward if outward > 0 else c + d1 * outward, a0, z0,
                      c + d1 * outward if outward > 0 else c + d0 * outward, a1, z1)
        bw = (u1 - u0) / n
        for i in range(n):
            a0, a1 = u0 + i * bw, u0 + (i + 1) * bw
            storeys = [(0.15, h2)] if i in double else [(0.15, h1 - 0.15), (h1 + 0.2, h2)]
            for si, (z0, z1) in enumerate(storeys):
                p = pattern(i, si if i not in double else 2)
                kind, _, col = p.partition(":")
                if kind == "solid":
                    B(cols.get(col, accent) if col != "accent" else accent, a0, a1, z0, z1, -0.02, 0.03)
                    continue
                if kind == "trans":
                    B(trans, a0, a1, z0, z1, -0.02, 0.03)
                    rows = 3 if z1 - z0 < 3.5 else 6
                    for r in range(1, rows):
                        z = z0 + (z1 - z0) * r / rows
                        B(frame, a0, a1, z - 0.025, z + 0.025, 0.0, 0.06)
                    continue
                zs = z0
                if kind == "split":
                    zs = z0 + (z1 - z0) * 0.42
                    B(cols.get(col, accent) if col != "accent" else accent, a0, a1, z0, zs, -0.02, 0.03)
                    B(frame, a0, a1, zs - 0.03, zs + 0.03, 0.0, 0.06)
                if kind != "open":
                    B(glass, a0, a1, zs, z1, -0.02, 0.02)
                if kind == "lit":
                    B(lit, a0 + 0.06, a1 - 0.06, zs + 0.04, z1 - 0.04, 0.02, 0.035)
                # muntins
                hz = [zs + (z1 - zs) * f for f in ((0.66,) if z1 - zs < 3.5 else (0.3, 0.55, 0.78))]
                for z in hz:
                    B(frame, a0, a1, z - 0.025, z + 0.025, 0.0, 0.06)
                if kind == "glass4" or i in double:
                    am = (a0 + a1) / 2
                    B(frame, am - 0.025, am + 0.025, zs, z1, 0.0, 0.06)
        # columns, floor band, roof fascia
        for i in range(n + 1):
            a = u0 + i * bw
            B(frame, a - fw / 2, a + fw / 2, 0, top, 0.0, 0.12)
        for i in range(n):
            if i not in double:
                a0, a1 = u0 + i * bw, u0 + (i + 1) * bw
                B(frame, a0, a1, h1 - 0.15, h1 + 0.2, 0.0, 0.1)
        B(frame, u0 - 0.05, u1 + 0.05, h2, top, 0.0, 0.14)
        B(frame, u0 - 0.05, u1 + 0.05, 0.0, 0.15, 0.0, 0.1)

    def xbrace(axis_x, c, a0, a1, z0, z1, outward):
        off = 0.1 * outward
        if axis_x:
            k.pole(frame, (a0, c + off, z0), (a1, c + off, z1), 0.018, segs=4)
            k.pole(frame, (a1, c + off, z0), (a0, c + off, z1), 0.018, segs=4)
        else:
            k.pole(frame, (c + off, a0, z0), (c + off, a1, z1), 0.018, segs=4)
            k.pole(frame, (c + off, a1, z0), (c + off, a0, z1), 0.018, segs=4)

    def box_shell(bx0, bx1, n, front_pat, end_pat, back_pat, double=(), braces=()):
        k.box(conc, bx0, y0, 0, bx1, y1, 0.15)                               # slab
        k.box(frame, bx0, y0, h2, bx1, y1, top - 0.05)                        # roof deck
        k.box(groof, bx0 + 0.15, y0 + 0.15, top - 0.05, bx1 - 0.15, y1 - 0.15, top + 0.02, skip=16)
        facade(True, y0, bx0, bx1, n, -1, front_pat, double)
        facade(True, y1, bx0, bx1, n, 1, back_pat)
        nd = max(2, int(round(BD / bay)))
        facade(False, bx0, y0, y1, nd, -1, end_pat)
        facade(False, bx1, y0, y1, nd, 1, end_pat)
        for i in braces:
            a0 = bx0 + (bx1 - bx0) * i / n
            xbrace(True, y0, a0, a0 + (bx1 - bx0) / n, 0.15, h2, -1)
        k.solid(bx0, y0, 0, bx1, y1, top)

    # facade patterns: deterministic per seed, the residence mostly glass, the studio more colour
    ccycle = ["red", "blue", "white", "black", "yellow", "white", "grey"]
    rng.shuffle(ccycle)

    def house_front(i, s):
        if s == 2:
            return "glass"
        r = rng.random()
        if s == 0:
            return "open" if r < 0.25 else "lit" if r < 0.4 else "split:" + ccycle[i % len(ccycle)] if r < 0.55 else "glass4"
        return "solid:" + ccycle[(i * 3) % len(ccycle)] if r < 0.3 else "trans" if r < 0.5 else "lit" if r < 0.62 else "glass"

    def studio_front(i, s):
        r = rng.random()
        if s == 0:
            return "open" if r < 0.2 else "solid:" + ccycle[(i + 2) % len(ccycle)] if r < 0.45 else "glass4" if r < 0.75 else "trans"
        return "solid:" + ccycle[(i * 2 + 1) % len(ccycle)] if r < 0.45 else "trans" if r < 0.75 else "lit"

    def ends(i, s):
        r = rng.random()
        return "solid:" + ("white" if r < 0.35 else "black" if r < 0.5 else "red" if r < 0.6 else "accent") if r < 0.7 else "trans"

    def backs(i, s):
        return "solid:" + ("grey" if rng.random() < 0.6 else "white")

    nliv = min(3, max(2, n_house // 3))
    living = set(range(n_house - nliv, n_house))        # double-height living room at the far end from the court
    box_shell(hx0, hx1, n_house, house_front, ends, backs, double=living,
              braces=[i for i in (n_house // 2 - 1,) if i not in living])
    box_shell(sx0, sx1, n_studio, studio_front, ends, backs, braces=[n_studio // 2])

    # interiors seen through open sliders: warm timber back walls, a lounge chair, shelves, plants, lamps
    for bx0, bx1 in ((hx0, hx1), (sx0, sx1)):
        k.box(wood, bx0 + 0.2, y1 - 0.35, 0.15, bx1 - 0.2, y1 - 0.25, h1 - 0.15)
        k.box(cols["white"], bx0 + 0.1, y0 + 0.1, h1 - 0.17, bx1 - 0.1, y1 - 0.1, h1 - 0.15)  # ceiling
        for i in range(int((bx1 - bx0) / 1.6)):
            x = bx0 + 0.6 + i * 1.6
            k.box(rng.choice([cols["red"], cols["blue"], cols["yellow"], wood, accent]), x, y1 - 0.75,
                  0.15 + (i % 3) * 0.5 + 0.3, x + 0.7, y1 - 0.35, 0.15 + (i % 3) * 0.5 + 0.7)
        for j in range(2):
            x = bx0 + (bx1 - bx0) * (0.3 + 0.4 * j)
            k.plant("Puff", "Foliage", rng.choice(LEAF), x, y0 + 0.8, 0.5, 0.5, 0.5, 0.9, rng.uniform(0, 360))
            k.cyl(frame, x + 1.0, y0 + 1.6, 0.15, 0.02, 0.02, 1.4, segs=4, caps=False)
            k.cyl(lit, x + 1.0, y0 + 1.6, 1.55, 0.24, 0.18, 0.3, segs=8)
        k.box(frame, bx0 + 2.0, y0 + 2.0, 0.15, bx0 + 2.8, y0 + 2.8, 0.55)      # lounge chair
        k.box(frame, bx0 + 2.0, y0 + 2.65, 0.55, bx0 + 2.8, y0 + 2.85, 1.05)
    # potted plants and a timber planter strip along the front of both boxes; vines down the court-facing ends
    for bx0, bx1 in ((hx0, hx1), (sx0, sx1)):
        for i in range(int((bx1 - bx0) / 3.0)):
            x = bx0 + 0.8 + i * 3.0 + rng.uniform(-0.3, 0.3)
            k.cyl(cols["white"] if i % 2 else cols["grey"], x, y0 - 0.55, 0, 0.28, 0.22, 0.5, segs=8)
            shrub(k, rng, x, y0 - 0.55, rng.uniform(0.35, 0.5), z=0.45, flowers=0.7)
    for x, rot in ((sx1 + 0.12, 90), (hx0 - 0.12, 270)):
        for i in range(int(BD / 0.9)):
            k.plant("Fringe", "Foliage", rng.choice(LEAF), x, y0 + 0.4 + i * 0.9, top, 1.0, 1.0,
                    rng.uniform(1.5, 3.8), rot, shadow=False)
    # roof PV over the studio (canopy walk view)
    for i in range(max(1, int((sx1 - sx0 - 1.0) / 2.2))):
        x = sx0 + 0.7 + i * 2.2
        k.obox(pv, x + 0.9, (y0 + y1) / 2, top + 0.15, 0.9, BD * 0.33, 0.025, 0, 0, 4)

    # ---- the court: paving, kitchen-garden beds, a tree, lanterns strung across
    cx0, cx1 = sx1 + 0.2, hx0 - 0.2
    k.box(pave, cx0, y0 - 0.6, 0, cx1, y1, 0.04, skip=16)
    nbeds = max(1, int((cx1 - cx0 - 1.0) / 2.4))
    for j in range(nbeds):
        bxa = cx0 + 0.6 + j * (cx1 - cx0 - 1.2) / nbeds
        bxb = bxa + (cx1 - cx0 - 1.2) / nbeds - 0.8
        k.box(wood, bxa, y1 - 2.6, 0, bxb, y1 - 0.4, 0.5)
        for q in range(4):
            k.plant("Puff", "Foliage", rng.choice(LEAF), bxa + (bxb - bxa) * (q + 0.5) / 4, y1 - 1.5 + rng.uniform(-0.5, 0.5),
                    0.5, 0.35, 0.35, 0.45, shadow=False)
            if rng.random() < 0.5:
                k.plant("Blob", "Foliage", rng.choice(FLOWER), bxa + (bxb - bxa) * (q + 0.5) / 4, y1 - 1.5, 0.85,
                        0.12, 0.12, 0.1, shadow=False)
    tree(k, rng, (cx0 + cx1) / 2 + rng.uniform(-1, 1), y0 + 1.4, min(plot.h_max + 1.5, 8.5), spread=2.6,
         bloom=rng.choice((pal[2], FLOWER[1], None)))
    k.box(wood, cx0 + 0.6, y0 + 0.4, 0.42, cx0 + 2.4, y0 + 0.8, 0.48)          # bench
    for xx in (cx0 + 0.7, cx0 + 2.2):
        k.box(frame, xx, y0 + 0.45, 0, xx + 0.1, y0 + 0.75, 0.42)
    # lantern string from house to studio
    for yy in (y0 + 0.6, y1 - 0.4):
        n = 7
        for q in range(n):
            f = (q + 0.5) / n
            x = cx0 + (cx1 - cx0) * f
            z = h1 + 0.4 - 0.5 * math.sin(math.pi * f)
            k.box(lit, x - 0.08, yy - 0.08, z - 0.16, x + 0.08, yy + 0.08, z)
        k.pole(frame, (cx0, yy, h1 + 0.45), ((cx0 + cx1) / 2, yy, h1 - 0.1), 0.008, segs=3)
        k.pole(frame, ((cx0 + cx1) / 2, yy, h1 - 0.1), (cx1, yy, h1 + 0.45), 0.008, segs=3)

    # ---- the hillside: retaining wall behind, planted bank on top
    k.box(conc, 0.2, y1 + 0.3, 0, W - 0.2, y1 + 0.7, 2.6)
    k.box(grass, 0.2, y1 + 0.7, 0, W - 0.2, D - 0.1, 2.6)
    for _ in range(int(W / 1.3)):
        x = rng.uniform(0.4, W - 0.4)
        k.plant("Fringe", "Foliage", rng.choice(LEAF), x, y1 + 0.28, 2.6, rng.uniform(0.7, 1.3), 1.0,
                rng.uniform(0.6, 1.6), 180, shadow=False)
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, y1 + 1.0 + rng.uniform(0, max(0.1, D - y1 - 1.4)), 2.6,
                0.6, 0.6, 0.5, rng.uniform(0, 360), shadow=False)

    # ---- the meadow and the eucalyptus row in front
    lawn(k, grass, 0, 0, W, y1 + 0.3)
    ne = max(4, int(W / 4.2))
    for i in range(ne):
        x = 1.2 + (W - 2.4) * (i + rng.uniform(0.25, 0.75)) / ne
        y = rng.uniform(1.0, max(1.2, y0 - 1.6))
        tall_tree(k, rng, x, y, min(plot.h_max + 7.0, rng.uniform(11.5, 15.5)), rng.uniform(2.0, 3.0),
                  leaf=EUCALYPT)
    flowers(k, rng, 0.3, 0.3, W - 0.3, y0 - 0.4, min(220, int(W * (y0 - 0.7) * 0.8)), palette=pal)
    for x in (hx0 + 1.0, hx1 - 1.5, sx0 + 1.0, sx1 - 1.0):
        shrub(k, rng, x, y0 - 0.8, rng.uniform(0.55, 0.8), flowers=0.8)
    # a path of stones to the court
    y = 0.4
    while y < y0 - 0.6:
        k.plant("Disc", "PermeableStone", (190, 180, 160), (cx0 + cx1) / 2 + rng.uniform(-0.3, 0.3), y, 0.02,
                1.2, 0.9, 1.0, rng.uniform(0, 40), shadow=False)
        y += 0.8
    return k


KINDS = {"farnsworth": farnsworth, "glass_house": glass_house, "casa_de_vidro": casa_de_vidro,
         "eames_house": eames_house}
SIZES = {
    "farnsworth": {"w": (20, 34), "d": (12, 20), "h": (5, 7), "floors": (1, 1), "use": "homes"},
    "glass_house": {"w": (16, 26), "d": (12, 18), "h": (4, 6), "floors": (1, 1), "use": "homes"},
    "casa_de_vidro": {"w": (18, 30), "d": (14, 24), "h": (8, 12), "floors": (1, 2), "use": "homes"},
    "eames_house": {"w": (30, 50), "d": (10, 16), "h": (7, 9), "floors": (2, 2), "use": "homes + studio"},
}
