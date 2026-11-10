"""Japanese homes: a sukiya villa in its stroll garden, and a Tadao Ando concrete courtyard house.

    sukiya_villa     Katsura Imperial Villa, Kyoto (17th c.), and the Kyoto sukiya retreats after it: staggered
                     "geese in flight" wings raised on posts over foundation stones, engawa verandas, shoji walls
                     (off-white panels behind a fine dark timber grid), deep eaves under irimoya (hip-and-gable)
                     roofs of dark grey tile; a stroll garden filling the plot: raked gravel, moss, stepping stones,
                     a koi pond with a granite slab bridge, red Japanese maples, a pruned leaning pine, a stone
                     lantern, bamboo, and a bamboo fence on the street with a roofed gate.
    ando_courtyard   Tadao Ando, Azuma Row House (Sumiyoshi, 1976) and Koshino House (Ashiya, 1981): smooth
                     fair-faced concrete with the formwork tie-hole grid, a blank street face cut by one deep
                     entrance slot, an open-air courtyard between two bars crossed by a bridge, glass only to the
                     courtyard, and Koshino's curved wall and still pool in a moss garden beside it.

Frame (kit.py): x along the street 0..w, y away from the street (front line y = 0), z up, metres.
Deterministic from plot.seed; plot.palette tints small accents only (these are quiet buildings).
"""
import math

from .kit import Kit, LEAF

# ---- colours (sRGB) -----------------------------------------------------------------------------------------------
SHOJI = (236, 232, 218)        # washi paper
PLASTER = (224, 216, 198)      # white-ish clay plaster
HINOKI = (92, 66, 44)          # weathered dark timber (posts, kumiko grid)
DECK = (150, 112, 76)          # engawa boards
SOFFIT = (120, 88, 60)
KAWARA = (70, 74, 80)          # dark grey roof tile
KAWARA_RIDGE = (46, 48, 52)
UNDER = (34, 30, 28)           # shadow under the raised floor
TATAMI = (190, 180, 124)
FUSUMA = (214, 196, 158)
LAMP = (255, 196, 120)
GRAVEL = (206, 202, 192)
RAKE = (176, 172, 162)
MOSS = (82, 112, 50)
MOSS2 = (104, 130, 58)
GRANITE = (160, 156, 148)
STONE_DARK = (112, 110, 104)
WATER = (52, 80, 78)
BAMBOO = (190, 164, 100)
BAMBOO_GREEN = (110, 140, 70)
ROPE = (60, 46, 34)
BARK = (88, 70, 58)
PINE = ((44, 74, 46), (54, 86, 50), (38, 66, 42))
MAPLE = ((176, 36, 34), (196, 52, 40), (150, 28, 40), (206, 84, 44))
HEDGE = ((52, 86, 48), (62, 98, 52))
KOI = ((236, 120, 40), (240, 236, 226), (214, 60, 40))

CONC = (198, 196, 190)         # Ando's smooth fair-faced concrete
CONC_JOINT = (176, 174, 168)
TIE = (96, 96, 96)
MULLION = (40, 42, 44)
GLASS = (150, 170, 176)
OAK = (176, 136, 94)
INTERIOR = (206, 184, 150)
LAWN = (104, 140, 64)


def clamp(v, a, b):
    return max(a, min(b, v))


def blob_pts(cx, cy, rx, ry, rng, n=14, jit=0.18):
    """A star-shaped soft polygon (pond, moss patch) around (cx, cy)."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        f = 1.0 + rng.uniform(-jit, jit)
        pts.append((cx + math.cos(a) * rx * f, cy + math.sin(a) * ry * f))
    return pts


# ---- shared garden pieces -----------------------------------------------------------------------------------------
def maple(k, rng, x, y, h=4.5, cr=1.9):
    """Japanese maple: a slim forked trunk under layered, flattened red canopies."""
    k.plant("Trunk", "Bark", BARK, x, y, 0, 0.22, 0.22, h * 0.55, rng.uniform(0, 360))
    for lean in (25, -25):
        yaw = rng.uniform(0, 360)
        k.plant("Trunk", "Bark", BARK, x, y, h * 0.35, 0.12, 0.12, h * 0.4, yaw, pitch=lean)
    base = rng.choice(MAPLE)
    n = rng.randint(4, 6)
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.3, 0.3)
        rr = cr * rng.uniform(0.35, 0.7)
        s = cr * rng.uniform(0.5, 0.7)
        col = base if rng.random() < 0.6 else rng.choice(MAPLE)
        k.plant("Puff", "Foliage", col, x + math.cos(a) * rr, y + math.sin(a) * rr, h - cr * rng.uniform(0.35, 0.8),
                s, s, s * 0.6, rng.uniform(0, 360))
    k.plant("Puff", "Foliage", base, x, y, h - cr * 0.3, cr * 0.7, cr * 0.7, cr * 0.45, rng.uniform(0, 360))


def pine(k, rng, x, y, h=5.0, lean=22.0, toward=0.0):
    """Pruned black pine (niwaki): a leaning trunk with flat cloud pads on short branches.
    toward = plan direction (degrees, 0 = +x) the trunk leans to."""
    # UE pitch tilts +z toward -x of the yawed frame, so yaw the trunk 180 deg from where it should lean
    L = h * 0.8
    k.plant("Trunk", "Bark", (74, 60, 50), x, y, 0, 0.32, 0.32, L, toward + 180.0, pitch=lean)
    dx, dy = math.cos(math.radians(toward)), math.sin(math.radians(toward))
    off = L * math.sin(math.radians(lean))
    tz = L * math.cos(math.radians(lean))
    tx, ty = x + dx * off, y + dy * off
    # pads: one crown pad at the top, more along the trunk stepping out
    pads = [(1.0, 0.0, 1.5), (0.62, 1.0, 1.25), (0.62, -1.0, 1.1), (0.35, 1.0, 1.0), (0.82, -0.6, 1.0)]
    for f, side, r in pads:
        px, py, pz = x + dx * off * f, y + dy * off * f, tz * f + 0.25
        sx, sy = -dy * side * 1.1, dx * side * 1.1
        if side:
            k.plant("Trunk", "Bark", (74, 60, 50), px, py, pz - 0.6, 0.08, 0.08, 1.2,
                    math.degrees(math.atan2(sy, sx)) + 180.0, pitch=60)
        k.plant("Puff", "Foliage", rng.choice(PINE), px + sx, py + sy, pz, r, r * 0.85, r * 0.42, rng.uniform(0, 360))


def lantern(k, s_stone, s_lamp, x, y, h=2.0):
    """Kasuga stone lantern: base, round shaft, platform, lit firebox, hexagonal hat, finial."""
    k.cyl(s_stone, x, y, 0, 0.32, 0.28, h * 0.1, segs=6)
    k.cyl(s_stone, x, y, h * 0.1, 0.12, 0.12, h * 0.38, segs=8)
    k.cyl(s_stone, x, y, h * 0.48, 0.24, 0.3, h * 0.08, segs=6)
    k.box(s_lamp, x - 0.15, y - 0.15, h * 0.56, x + 0.15, y + 0.15, h * 0.74)
    for sx in (-1, 1):
        for sy in (-1, 1):
            k.box(s_stone, x + sx * 0.17 - 0.03, y + sy * 0.17 - 0.03, h * 0.56, x + sx * 0.17 + 0.03,
                  y + sy * 0.17 + 0.03, h * 0.74)
    k.cyl(s_stone, x, y, h * 0.74, 0.46, 0.14, h * 0.14, segs=6)
    k.ell(s_stone, x, y, h * 0.9, 0.09, 0.09, 0.12, segs=8, rings=4)
    k.solid(x - 0.3, y - 0.3, 0, x + 0.3, y + 0.3, h)


def irimoya(k, s_roof, s_ridge, s_soffit, ex0, ey0, ex1, ey1, ze, zr, f=0.5, t=0.24):
    """Hip-and-gable roof over the eave rectangle, ridge along x. The hipped skirt rises from all four eaves to
    height zg; above it a gable roof (ridge zr) with vertical triangular gable ends, its rakes overhanging the hip."""
    run = (ey1 - ey0) / 2.0
    ym = (ey0 + ey1) / 2.0
    rise = zr - ze
    s = run * f
    zg = ze + rise * f
    nl = math.hypot(rise, run)
    nf, nb = (0, -rise / nl, run / nl), (0, rise / nl, run / nl)
    nlft, nrgt = (-rise / nl, 0, run / nl), (rise / nl, 0, run / nl)
    gx0, gx1 = ex0 + s, ex1 - s
    ov = min(0.5, s * 0.35)           # the gable roof's rakes overhang its gable a little
    # eave slab: soffit and fascia seen from below / the street
    k.box(s_soffit, ex0, ey0, ze - t, ex1, ey1, ze - 0.02)
    k.box(s_ridge, ex0 - 0.03, ey0 - 0.03, ze - t - 0.03, ex1 + 0.03, ey0 + 0.06, ze + 0.02)
    k.box(s_ridge, ex0 - 0.03, ey1 - 0.06, ze - t - 0.03, ex1 + 0.03, ey1 + 0.03, ze + 0.02)
    k.box(s_ridge, ex0 - 0.03, ey0, ze - t - 0.03, ex0 + 0.06, ey1, ze + 0.02)
    k.box(s_ridge, ex1 - 0.06, ey0, ze - t - 0.03, ex1 + 0.03, ey1, ze + 0.02)
    # hipped skirt
    k.quad(s_roof, (ex0, ey0, ze), (ex1, ey0, ze), (gx1, ey0 + s, zg), (gx0, ey0 + s, zg), nf)
    k.quad(s_roof, (ex1, ey1, ze), (ex0, ey1, ze), (gx0, ey1 - s, zg), (gx1, ey1 - s, zg), nb)
    k.quad(s_roof, (ex0, ey1, ze), (ex0, ey0, ze), (gx0, ey0 + s, zg), (gx0, ey1 - s, zg), nlft)
    k.quad(s_roof, (ex1, ey0, ze), (ex1, ey1, ze), (gx1, ey1 - s, zg), (gx1, ey0 + s, zg), nrgt)
    # gable roof on top (planes continue the skirt's slope), lifted a hair so it reads as a separate roof
    lift = 0.04
    k.quad(s_roof, (gx0 - ov, ey0 + s, zg + lift), (gx1 + ov, ey0 + s, zg + lift), (gx1 + ov, ym, zr + lift),
           (gx0 - ov, ym, zr + lift), nf)
    k.quad(s_roof, (gx1 + ov, ey1 - s, zg + lift), (gx0 - ov, ey1 - s, zg + lift), (gx0 - ov, ym, zr + lift),
           (gx1 + ov, ym, zr + lift), nb)
    # undersides of the overhanging rakes so they don't vanish from below
    k.quad(s_soffit, (gx0 - ov, ey0 + s, zg), (gx0 - ov, ym, zr), (gx1 + ov, ym, zr), (gx1 + ov, ey0 + s, zg),
           (0, rise / nl, -run / nl))
    k.quad(s_soffit, (gx1 + ov, ey1 - s, zg), (gx1 + ov, ym, zr), (gx0 - ov, ym, zr), (gx0 - ov, ey1 - s, zg),
           (0, -rise / nl, -run / nl))
    # gable triangles (tsuma), set in from the rake, plaster with a timber frame
    for gx, n in ((gx0, (-1, 0, 0)), (gx1, (1, 0, 0))):
        k.tri(s_soffit, (gx, ey0 + s, zg), (gx, ey1 - s, zg), (gx, ym, zr), n)
    # barge boards along the rakes, ridge, hip ridges
    for gx in (gx0 - ov, gx1 + ov):
        k.beam(s_ridge, (gx, ey0 + s - 0.05, zg + lift), (gx, ym, zr + lift + 0.05), 0.08, 0.22)
        k.beam(s_ridge, (gx, ey1 - s + 0.05, zg + lift), (gx, ym, zr + lift + 0.05), 0.08, 0.22)
    k.box(s_ridge, gx0 - ov - 0.1, ym - 0.2, zr - 0.05, gx1 + ov + 0.1, ym + 0.2, zr + 0.36)
    k.box(s_ridge, gx0 - ov - 0.15, ym - 0.24, zr + 0.2, gx0 - ov + 0.25, ym + 0.24, zr + 0.6)   # onigawara
    k.box(s_ridge, gx1 + ov - 0.25, ym - 0.24, zr + 0.2, gx1 + ov + 0.15, ym + 0.24, zr + 0.6)
    for (ax, ay), (bx, by) in (((ex0, ey0), (gx0, ey0 + s)), ((ex1, ey0), (gx1, ey0 + s)),
                               ((ex0, ey1), (gx0, ey1 - s)), ((ex1, ey1), (gx1, ey1 - s))):
        k.beam(s_ridge, (ax, ay, ze + 0.06), (bx, by, zg + 0.06), 0.18, 0.14)


def shoji_wall(k, s_paper, s_grid, s_post, s_upper, axis, a0, a1, c, z0, z1, side, rng, s_open=None, gap=None):
    """A run of shoji along x (axis='x', at y=c) or along y (axis='y', at x=c), floor z0, top z1.
    side = +1/-1: which way the face looks (the grid sits proud on that side). gap = bays left open (list of
    indices) to show a tatami room behind; s_open draws its warm back wall."""
    zl = z0 + min(2.0, (z1 - z0) * 0.72)     # kamoi / nageshi lintel
    L = a1 - a0
    nb = max(1, int(round(L / 1.82)))
    bay = L / nb
    t = 0.05
    off = side * 0.035

    def B(s, u0, u1, v0, v1, zz0, zz1):
        if axis == "x":
            k.box(s, u0, c + v0, zz0, u1, c + v1, zz1)
        else:
            k.box(s, c + v0, u0, zz0, c + v1, u1, zz1)

    gap = set(gap or ())
    for i in range(nb):
        u0, u1 = a0 + i * bay, a0 + (i + 1) * bay
        if i in gap:
            continue
        B(s_paper, u0, u1, -t / 2, t / 2, z0, zl)
        # kumiko grid: tall narrow panes, a few cross bars
        nv = max(2, int(round(bay / 0.3)))
        for j in range(1, nv):
            u = u0 + bay * j / nv
            B(s_grid, u - 0.012, u + 0.012, off - 0.012, off + 0.012, z0, zl)
        zz = z0 + 0.5
        while zz < zl - 0.12:
            if True:
                B(s_grid, u0, u1, off - 0.012, off + 0.012, zz - 0.012, zz + 0.012)
            zz += 0.27
        B(s_grid, u0, u1, off - 0.015, off + 0.015, z0, z0 + 0.22)     # koshi (kickboard rail)
    # posts, lintel, plaster frieze above
    for i in range(nb + 1):
        u = a0 + i * bay
        B(s_post, u - 0.07, u + 0.07, -0.07, 0.07, z0, z1)
    B(s_post, a0, a1, -0.06 + off, 0.06 + off, zl, zl + 0.1)
    B(s_upper, a0, a1, -0.04, 0.04, zl + 0.1, z1)


# ---- kind 1: sukiya villa -----------------------------------------------------------------------------------------
def sukiya_villa(plot):
    W, D = float(plot.w), float(plot.d)
    k = Kit(W, D)
    rng = plot.rng
    m = {}

    def M(name, mat, tint, scale=0.0):
        if name not in m:
            m[name] = k.mat(mat, tint, scale)
        return m[name]

    paper = M("paper", "Plain", SHOJI)
    grid = M("grid", "Plain", HINOKI)
    post = M("post", "Timber", HINOKI)
    plaster = paper
    soffit = M("soffit", "Timber", SOFFIT)
    deck = soffit
    roof = M("roof", "PermeableStone", KAWARA)
    ridge = M("ridge", "Plain", KAWARA_RIDGE)
    under = M("under", "Plain", UNDER)
    gravel = M("gravel", "Path", GRAVEL)
    rake = M("rake", "Plain", RAKE)
    moss = M("moss", "Moss", MOSS)
    stone = M("stone", "PermeableStone", GRANITE)
    water = M("water", "Water", WATER)
    bamboo = M("bamboo", "Timber", BAMBOO)
    lamp = M("lamp", "Lantern", LAMP)

    # height budget: floor 0.75, eaves 3.35, ridge up to 6.6 (lower if the plot caps us)
    low = plot.h_max < 6.0
    zf = 0.55 if low else 0.75
    ze = zf + (2.4 if low else 2.55)
    zr = clamp(plot.h_max - 0.7, ze + 1.3, ze + 3.3)   # onigawara tops out 0.6 above the ridge

    # ground: raked gravel over the whole plot
    k.box(gravel, 0, 0, 0, W, D, 0.03, skip=16)

    # ---- the house: 2-3 staggered wings ("geese in flight") --------------------------------------------------
    n = 3 if W >= 27 else 2
    dv = clamp(D * 0.28, 6.0, 8.5)        # wing depth (shoji line to back wall)
    dy = clamp(D * 0.13, 2.8, 4.2)        # stagger back per wing
    eng_f, eng_s, ov = 1.2, 0.9, 1.0      # engawa depth front / sides, eave overhang beyond the engawa
    dy = max(1.0, min(dy, (D - (0.6 + ov + 0.5) - dv - (eng_f + ov + 0.6) - 0.36 * D) / max(1, n - 1)))
    side_m = eng_s + ov + 0.4
    back_m = 0.6 + ov + 0.5
    yb_last = D - back_m
    span = W - 2 * side_m
    # wing widths (the first, main shoin is widest)
    fr = [1.25, 1.0, 0.85][:n]
    ws = [span * f / sum(fr) for f in fr]
    wings = []
    x = side_m
    for i in range(n):
        yb = yb_last - (n - 1 - i) * dy
        wings.append((x, yb - dv, x + ws[i], yb))
        x += ws[i]
    if rng.random() < 0.5:            # mirror: the stagger can run either way
        wings = [(W - x1, y0, W - x0, y1) for (x0, y0, x1, y1) in wings]

    for i, (x0, y0, x1, y1) in enumerate(wings):
        # raised floor on posts over foundation stones, engawa around front and sides
        fx0, fx1, fy0, fy1 = x0 - eng_s, x1 + eng_s, y0 - eng_f, y1 + 0.6
        k.box(deck, fx0, fy0, zf - 0.14, fx1, fy1, zf)
        k.box(under, fx0 + 0.35, fy0 + 0.35, 0.03, fx1 - 0.35, fy1 - 0.35, zf - 0.14)
        npost = max(2, int(round((fx1 - fx0) / 1.82)))
        for j in range(npost + 1):
            px = fx0 + 0.1 + (fx1 - fx0 - 0.2) * j / npost
            for py in (fy0 + 0.1, y0, y1):
                k.box(post, px - 0.07, py - 0.07, 0.18, px + 0.07, py + 0.07, zf - 0.14)
                k.plant("Stone", "PermeableStone", STONE_DARK, px, py, 0.0, 0.22, 0.22, 0.2, rng.uniform(0, 360))
        # engawa edge posts carrying the eaves
        for j in range(npost + 1):
            px = fx0 + 0.1 + (fx1 - fx0 - 0.2) * j / npost
            if j % 2 == 0 or j == npost:
                k.box(post, px - 0.06, fy0 + 0.04, zf, px + 0.06, fy0 + 0.16, ze - 0.2)
        # shoji: front (some bays slid open), sides plaster + shoji, back plaster
        nb = max(1, int(round((x1 - x0) / 1.82)))
        opens = {j for j in range(nb) if rng.random() < 0.3}
        if not opens:
            opens = {nb // 2}
        zt = ze - 0.25
        shoji_wall(k, paper, grid, post, plaster, "x", x0, x1, y0, zf, zt, -1, rng, gap=opens)
        shoji_wall(k, paper, grid, post, plaster, "y", y0, y1, x0, zf, zt, -1, rng)
        shoji_wall(k, paper, grid, post, plaster, "y", y0, y1, x1, zf, zt, 1, rng)
        k.box(plaster, x0, y1 - 0.05, zf, x1, y1 + 0.05, zt)
        # the room behind the open bays: tatami floor, a fusuma wall with a warm glow, a tokonoma lamp
        k.box(M("tatami", "Plain", TATAMI), x0, y0, zf, x1, y1, zf + 0.04)
        k.box(paper, x0 + 0.1, y0 + 3.2, zf, x1 - 0.1, y0 + 3.3, zt)
        k.box(soffit, x0, y0, zt - 0.05, x1, y0 + 3.3, zt)
        for j in sorted(opens)[:2]:
            bx = x0 + (j + 0.5) * (x1 - x0) / nb
            k.box(lamp, bx - 0.18, y0 + 2.6, zf + 0.04, bx + 0.18, y0 + 2.9, zf + 0.6)
        # kutsunugi-ishi (shoe stone) at the front step
        cx = (x0 + x1) / 2
        k.box(stone, cx - 0.7, fy0 - 0.75, 0, cx + 0.7, fy0 - 0.05, zf * 0.45)
        # roof
        zri = zr - (0.25 * (n - 1 - i))            # the main wing's ridge is highest
        irimoya(k, roof, ridge, soffit, fx0 - ov, fy0 - ov, fx1 + ov, fy1 + ov, ze, zri, f=0.48)
        k.solid(x0, y0, 0, x1, y1, ze)
        k.solid(fx0, fy0, 0, fx1, fy1, zf)

    # moss band along the drip line of each wing
    for (x0, y0, x1, _y1) in wings:
        k.box(moss, x0 - eng_s - ov - 0.3, y0 - eng_f - ov - 0.6, 0.03, x1 + eng_s + ov + 0.3, y0 - eng_f - ov + 0.2,
              0.05)

    # ---- the garden ------------------------------------------------------------------------------------------
    front_eave = min(y0 - eng_f - ov for (_, y0, _, _) in wings) - 0.6   # garden is y in (fence, front_eave)
    gy0, gy1 = 1.2, max(3.5, front_eave)
    # street fence (kenninji-gaki: split bamboo panels with dark rails) and a roofed gate
    fz = 1.5
    gate_c = W * (0.25 if wings[0][0] < W / 2 else 0.75)
    gw = 1.8
    for a0, a1 in ((0.0, gate_c - gw / 2 - 0.25), (gate_c + gw / 2 + 0.25, W)):
        if a1 - a0 < 0.3:
            continue
        k.box(bamboo, a0, 0.35, 0.12, a1, 0.45, fz)
        for zz in (0.45, 0.9, 1.3):
            k.box(grid, a0, 0.31, zz - 0.035, a1, 0.49, zz + 0.035)
        np_ = max(1, int((a1 - a0) / 1.8))
        for j in range(np_ + 1):
            px = a0 + 0.05 + (a1 - a0 - 0.1) * j / np_
            k.cyl(bamboo, px, 0.4, 0, 0.06, 0.06, fz + 0.12, segs=6)
        k.box(stone, a0, 0.28, 0, a1, 0.52, 0.14)
        k.solid(a0, 0.3, 0, a1, 0.5, fz)
    # side and back hedges (karikomi), clipped low
    for j in range(int(D / 1.4)):
        yy = 1.2 + j * 1.4
        if yy > D - 0.6:
            break
        for xx in (0.55, W - 0.55):
            k.plant("Puff", "Foliage", rng.choice(HEDGE), xx, yy, 0.05, 0.75, 0.85, 0.8, rng.uniform(0, 360))
    for j in range(int(W / 1.5)):
        xx = 1.0 + j * 1.5
        k.plant("Puff", "Foliage", rng.choice(HEDGE), xx, D - 0.55, 0.05, 0.85, 0.7, 0.9, rng.uniform(0, 360))
    # the gate: two posts, a tie beam, a small tiled gable roof, doors swung open
    gx0, gx1 = gate_c - gw / 2 - 0.15, gate_c + gw / 2 + 0.15
    for px in (gx0, gx1):
        k.box(post, px - 0.12, 0.28, 0, px + 0.12, 0.52, 2.55)
    k.box(post, gx0 - 0.3, 0.25, 2.35, gx1 + 0.3, 0.55, 2.55)
    k.box(soffit, gx0 - 0.6, -0.15, 2.55, gx1 + 0.6, 0.95, 2.65)
    k.gable(roof, gx0 - 0.6, -0.15, 2.55, gx1 + 0.6, 0.95, 2.65, 0.75, True)
    k.box(ridge, gx0 - 0.65, 0.33, 3.33, gx1 + 0.65, 0.47, 3.48)
    for sgn, px in ((1, gx0 + 0.12), (-1, gx1 - 0.12)):
        k.obox(post, px + sgn * 0.42 * math.cos(math.radians(70)), 0.4 + 0.42 * math.sin(math.radians(70)), 1.05,
               0.42, 0.03, 1.0, 0, sgn * 70, 0)

    # pond in front of the far wing(s), with stone edging and koi
    far = wings[-1]
    pcx = clamp((far[0] + far[2]) / 2, 4.0, W - 4.0)
    pcy = (gy0 + gy1) / 2 + 0.6
    prx = clamp((far[2] - far[0]) * 0.48, 2.8, 6.0)
    pry = clamp((gy1 - gy0) * 0.36, 1.7, 4.5)
    ppts = blob_pts(pcx, pcy, prx, pry, rng, n=16, jit=0.15)
    k.prism(moss, blob_pts(pcx, pcy, prx + 1.3, pry + 1.0, rng, n=16, jit=0.2), 0.03, 0.05)
    k.prism(under, ppts, 0.05, 0.06)
    k.prism(water, [(px + (pcx - px) * 0.06, py + (pcy - py) * 0.06) for px, py in ppts], 0.06, 0.1)
    for i, (px, py) in enumerate(ppts):
        nx_, ny_ = ppts[(i + 1) % len(ppts)]
        for f in (0.0, 0.5):
            k.plant("Stone", "PermeableStone", rng.choice((GRANITE, STONE_DARK)), px + (nx_ - px) * f,
                    py + (ny_ - py) * f, 0.0, rng.uniform(0.3, 0.5), rng.uniform(0.25, 0.4), rng.uniform(0.2, 0.32),
                    rng.uniform(0, 360))
    for _ in range(7):
        a, rr = rng.uniform(0, 6.28), rng.uniform(0.1, 0.7)
        k.plant("Blob", "Plain", rng.choice(KOI), pcx + math.cos(a) * prx * rr, pcy + math.sin(a) * pry * rr, 0.09,
                0.22, 0.07, 0.03, rng.uniform(0, 360), shadow=False)
    for _ in range(4):
        a, rr = rng.uniform(0, 6.28), rng.uniform(0.3, 0.8)
        k.plant("Disc", "Foliage", LEAF[1], pcx + math.cos(a) * prx * rr, pcy + math.sin(a) * pry * rr, 0.1,
                0.5, 0.5, 0.5, shadow=False)
    # granite slab bridge across the pond's waist (along y), slightly arched in two slabs
    bx = pcx + prx * rng.uniform(-0.25, 0.25)
    b0, b1 = pcy - pry * 1.15, pcy + pry * 1.15
    bm = (b0 + b1) / 2
    k.box(stone, bx - 0.55, b0 - 0.4, 0, bx + 0.55, b0, 0.22)
    k.box(stone, bx - 0.55, b1, 0, bx + 0.55, b1 + 0.4, 0.22)
    k.obox(stone, bx, (b0 + bm) / 2, 0.32, 0.5, (bm - b0) / 2 + 0.05, 0.1, 0, 0, -math.degrees(math.atan2(0.2, bm - b0)))
    k.obox(stone, bx, (bm + b1) / 2, 0.32, 0.5, (b1 - bm) / 2 + 0.05, 0.1, 0, 0, math.degrees(math.atan2(0.2, b1 - bm)))

    # stepping stones: gate -> main wing's shoe stone, with a branch to the bridge
    main = wings[0]
    tx, ty = (main[0] + main[2]) / 2, main[1] - eng_f - 0.9
    path = [(gate_c, 0.9), (gate_c + (tx - gate_c) * 0.3 + 1.0, gy0 + (ty - gy0) * 0.4), (tx, ty)]

    def stones_along(pts, step=0.75, size=0.62):
        out = []
        for (ax, ay), (bx_, by_) in zip(pts, pts[1:], strict=False):
            L = math.hypot(bx_ - ax, by_ - ay)
            nst = max(1, int(L / step))
            for j in range(nst):
                f = j / nst
                x_ = ax + (bx_ - ax) * f + rng.uniform(-0.15, 0.15)
                y_ = ay + (by_ - ay) * f + rng.uniform(-0.1, 0.1)
                k.plant("Disc", "PermeableStone", rng.choice((GRANITE, (150, 146, 136))), x_, y_, 0.02,
                        size * rng.uniform(0.9, 1.15), size * rng.uniform(0.8, 1.0), 2.0, rng.uniform(0, 360))
                out.append((x_, y_))
        return out

    stones_along(path)
    mid = path[1]
    stones_along([mid, (bx, b0 - 0.5)])

    # karesansui: raked lines in the open gravel between path and pond, around one or two set rocks
    rx0 = min(gate_c, tx) - 3.5
    rx1 = max(gate_c, tx) + 3.5
    if abs(pcx - (rx0 + rx1) / 2) < prx + 3:
        rx0, rx1 = (rx0, min(rx1, pcx - prx - 1.5)) if pcx > (rx0 + rx1) / 2 else (max(rx0, pcx + prx + 1.5), rx1)
    rx0, rx1 = max(1.4, rx0), min(W - 1.4, rx1)
    ry0, ry1 = gy0 + 0.4, gy1 - 0.4
    if rx1 - rx0 > 2 and ry1 - ry0 > 1.5:
        rock = ((rx0 + rx1) / 2 + rng.uniform(-1, 1), (ry0 + ry1) / 2 + rng.uniform(-0.4, 0.4))
        yy = ry0
        while yy < ry1:
            if abs(yy - rock[1]) > 1.25:
                k.box(rake, rx0, yy - 0.025, 0.03, rx1, yy + 0.025, 0.045)
            else:   # break the lines around the rock's rings
                dxr = math.sqrt(max(0.0, 1.25 ** 2 - (yy - rock[1]) ** 2))
                k.box(rake, rx0, yy - 0.025, 0.03, rock[0] - dxr, yy + 0.025, 0.045)
                k.box(rake, rock[0] + dxr, yy - 0.025, 0.03, rx1, yy + 0.025, 0.045)
            yy += 0.32
        for rr in (0.85, 1.15):
            k.cyl(rake, rock[0], rock[1], 0.03, rr, rr, 0.015, segs=20, caps=False)
            k.cyl(rake, rock[0], rock[1], 0.03, rr - 0.04, rr - 0.04, 0.015, segs=20, caps=False)
        k.plant("Stone", "PermeableStone", STONE_DARK, rock[0], rock[1], 0, 0.75, 0.55, 0.6, rng.uniform(0, 360))
        k.plant("Stone", "PermeableStone", GRANITE, rock[0] + 0.55, rock[1] + 0.25, 0, 0.35, 0.3, 0.3)
        k.prism(moss, blob_pts(rock[0], rock[1], 0.65, 0.5, rng, n=10), 0.03, 0.05)

    # pine leaning over the pond, a lantern on its bank
    pine_side = -1 if pcx > W / 2 else 1
    px_, py_ = pcx + pine_side * (prx + 0.6), pcy - pry * 0.3
    pine(k, rng, px_, py_, h=min(6.0, ze + 2.2), lean=24, toward=180.0 if pine_side > 0 else 0.0)
    k.prism(moss, blob_pts(px_, py_, 1.6, 1.3, rng, n=10), 0.03, 0.05)
    lantern(k, stone, lamp, pcx - pine_side * (prx * 0.55), pcy + pry + 0.55, h=1.9)
    # maples: by the pond, by the gate, against the house
    spots = [(pcx - pine_side * (prx + 1.2), pcy - pry * 0.6), (gate_c + (2.2 if gate_c < W / 2 else -2.2), 2.4)]
    if n >= 2:
        spots.append(((wings[0][2] + wings[1][0]) / 2, gy1 - 0.4))
    if D > 28:
        spots.append((pcx + pine_side * prx * 0.4, pcy + pry + 1.6))
    if W > 24:
        spots.append((W * 0.5 + rng.uniform(-2, 2), 2.6))
    for sx_, sy_ in spots:
        sx_, sy_ = clamp(sx_, 1.8, W - 1.8), clamp(sy_, 1.8, D - 2)
        maple(k, rng, sx_, sy_, h=rng.uniform(4.0, 5.2), cr=rng.uniform(1.6, 2.1))
        k.prism(moss, blob_pts(sx_, sy_, 1.7, 1.4, rng, n=10), 0.03, 0.05)
    # azalea cushions (o-karikomi) along the fence inside and by the pond
    for _ in range(int(W / 2.2)):
        xx = rng.uniform(1.2, W - 1.2)
        if abs(xx - gate_c) < 1.6:
            continue
        r = rng.uniform(0.5, 0.8)
        k.plant("Puff", "Foliage", rng.choice(HEDGE), xx, rng.uniform(1.0, 1.6), 0.03, r * 1.2, r, r * 0.75,
                rng.uniform(0, 360))
    # bamboo grove in a back corner beside the house
    bxc = 1.6 if wings[-1][0] > W / 2 else W - 1.6
    for _ in range(26):
        xx, yy = bxc + rng.uniform(-1.0, 1.0), D - rng.uniform(1.2, 4.5)
        k.plant("Reed", "Foliage", BAMBOO_GREEN, xx, yy, 0, 1.4, 1.4, rng.uniform(5.5, 7.5), rng.uniform(0, 360))
        if rng.random() < 0.5:
            k.plant("Puff", "Foliage", LEAF[2], xx, yy, rng.uniform(4.5, 6.5), 0.6, 0.6, 0.5, shadow=False)
    return k


# ---- kind 2: Ando concrete courtyard house ------------------------------------------------------------------------
def concrete_face(k, s_joint, axis, a0, a1, c, z0, z1, side, holes=True, panel=1.8, row=0.9, cap=10 ** 6):
    """Fair-faced concrete formwork pattern on a wall face along x (axis='x', face at y=c) or y (at x=c):
    panel joints as thin proud lines, and the tie holes (4 per panel) as small dark cube instances."""
    e = side * 0.008

    def B(u0, u1, zz0, zz1):
        if axis == "x":
            k.box(s_joint, u0, c + min(0, e) - 0.004, zz0, u1, c + max(0, e) + 0.004, zz1)
        else:
            k.box(s_joint, c + min(0, e) - 0.004, u0, zz0, c + max(0, e) + 0.004, u1, zz1)

    np_ = max(1, int(round((a1 - a0) / panel)))
    pw = (a1 - a0) / np_
    nr = max(1, int(round((z1 - z0) / row)))
    rh = (z1 - z0) / nr
    for i in range(1, np_):
        u = a0 + i * pw
        B(u - 0.006, u + 0.006, z0, z1)
    for j in range(1, nr):
        z = z0 + j * rh
        B(a0, a1, z - 0.006, z + 0.006)
    if not holes:
        return 0
    cnt = 0
    per = 4 if np_ * nr * 4 <= cap else 2      # thin the holes out on big faces (instance budget)
    if np_ * nr * per > cap:
        return 0
    fzs = (0.27, 0.73) if per == 4 else (0.5,)
    for i in range(np_):
        for j in range(nr):
            for fu in (0.25, 0.75):
                for fz in fzs:
                    u, z = a0 + (i + fu) * pw, z0 + (j + fz) * rh
                    if axis == "x":
                        k.plant("Cube", "Plain", TIE, u, c + side * 0.008, z, 0.05, 0.03, 0.05, shadow=False, cull_m=60)
                    else:
                        k.plant("Cube", "Plain", TIE, c + side * 0.008, u, z, 0.03, 0.05, 0.05, shadow=False, cull_m=60)
                    cnt += 1
    return cnt


def ando_courtyard(plot):
    W, D = float(plot.w), float(plot.d)
    k = Kit(W, D)
    rng = plot.rng
    conc = k.mat("Plain", CONC)
    joint = k.mat("Plain", CONC_JOINT)
    glass = k.mat("SolarGlass", GLASS, 400.0)
    mull = k.mat("Plain", MULLION)
    oak = k.mat("Timber", OAK)
    inner = k.mat("Plain", INTERIOR)
    lamp = k.mat("Lantern", LAMP)
    moss = k.mat("Moss", MOSS)
    gravel = k.mat("Path", GRAVEL)
    water = k.mat("Water", (44, 64, 66))
    green = k.mat("GreenRoof", (120, 150, 80))
    dark = k.mat("Plain", (30, 30, 32))
    slate = k.mat("PermeableStone", (150, 148, 140))

    H = clamp(plot.h_max - 0.15, 5.6, 7.6)      # back bar: two storeys + parapet; Ando keeps it low
    Hf = clamp(H * 0.52, 3.4, 4.0)               # front bar: one tall storey with a roof garden (Koshino's two bars)
    f2 = H / 2.0 - 0.1                           # back bar upper floor
    # box footprint: full width on narrow plots; on wider ones a side garden for Koshino's curved wall + pool
    side_g = W >= 16.5
    gw = clamp(W * 0.36, 6.0, 9.5) if side_g else 0.0
    left_garden = rng.random() < 0.5
    if side_g and left_garden:
        hx0, hx1 = gw, W - 0.6
    elif side_g:
        hx0, hx1 = 0.6, W - 0.6 - gw
    else:
        hx0, hx1 = 0.6, W - 0.6
    hy0 = clamp(D * 0.12, 2.0, 3.2)             # front strip: moss and gravel
    hy1 = D - clamp(D * 0.14, 2.2, 4.0)
    L = hy1 - hy0
    dbf = clamp(L * 0.3, 4.2, 5.5)               # front bar depth
    dbb = clamp(L * 0.36, 4.8, 6.5)              # back bar depth
    cy0, cy1 = hy0 + dbf, hy1 - dbb              # courtyard between the bars (open to the sky)
    t = 0.25                                     # wall thickness
    xm = (hx0 + hx1) / 2

    # ground
    k.box(gravel, 0, 0, 0, W, D, 0.03, skip=16)
    # ---- the concrete shell ----
    # front bar: blank to the street, one deep entrance slot
    ex = hx0 + (hx1 - hx0) * (0.2 if rng.random() < 0.5 else 0.8)
    ew = 1.1
    k.box(conc, hx0, hy0, 0, ex - ew / 2, hy0 + t, Hf)
    k.box(conc, ex + ew / 2, hy0, 0, hx1, hy0 + t, Hf)
    k.box(conc, ex - ew / 2, hy0, 2.6, ex + ew / 2, hy0 + t, Hf)
    k.box(dark, ex - ew / 2, hy0 + 1.6, 0.03, ex + ew / 2, hy0 + 1.7, 2.6)      # recessed door deep in the slot
    k.box(conc, ex - ew / 2 - 0.02, hy0, 0, ex - ew / 2, hy0 + 1.7, 2.6)
    k.box(conc, ex + ew / 2, hy0, 0, ex + ew / 2 + 0.02, hy0 + 1.7, 2.6)
    k.box(oak, ex - 0.42, hy0 + 1.58, 0.03, ex + 0.42, hy0 + 1.6, 2.35)        # the oak door
    # side walls: front bar height along the front bar and courtyard, full height along the back bar
    for x0_, x1_ in ((hx0, hx0 + t), (hx1 - t, hx1)):
        k.box(conc, x0_, hy0, 0, x1_, cy1, Hf)
        k.box(conc, x0_, cy1, 0, x1_, hy1, H)
    # back bar: front (courtyard) wall above the glass is a concrete band, back wall solid
    k.box(conc, hx0, hy1 - t, 0, hx1, hy1, H)
    # roofs
    k.box(conc, hx0, hy0, Hf - 0.3, hx1, cy0, Hf)
    k.box(conc, hx0, cy1, H - 0.3, hx1, hy1, H)
    k.box(green, hx0 + t, cy1 + 0.25, H, hx1 - t, hy1 - t, H + 0.1)
    # front bar roof garden: a parapet, moss and low planting, reached by the bridge
    k.box(conc, hx0, hy0, Hf, hx1, hy0 + 0.2, Hf + 0.9)
    k.box(green, hx0 + 0.2, hy0 + 0.2, Hf, hx1 - 0.2, cy0 - 0.2, Hf + 0.08)
    # Koshino's roof slit: a long thin skylight along the back bar's side wall
    sl_x = hx0 + t if ex > xm else hx1 - t - 0.3
    k.box(glass, sl_x, cy1 + 0.4, H - 0.02, sl_x + 0.3, hy1 - 0.5, H + 0.02)
    # a single tall slit window in the back bar's upper side wall, seen over the front bar from the street
    sx = hx1 + 0.005 if ex < xm else hx0 - 0.005
    k.box(dark, sx - 0.02, cy1 + 0.8, 0.8, sx + 0.02, cy1 + 1.05, H - 0.7)
    # courtyard faces: full-height glass in thin dark frames
    for yc, side, top in ((cy0, 1, Hf - 0.3), (cy1, -1, H - 0.3)):
        k.box(glass, hx0 + t, yc - 0.02, 0.03, hx1 - t, yc + 0.02, top)
        nm = max(2, int((hx1 - hx0) / 1.8))
        for i in range(nm + 1):
            mx = hx0 + t + (hx1 - hx0 - 2 * t) * i / nm
            k.box(mull, mx - 0.03, yc - 0.05, 0.03, mx + 0.03, yc + 0.05, top)
        k.box(mull, hx0 + t, yc - 0.05, top - 0.06, hx1 - t, yc + 0.05, top)
        db = dbf if side > 0 else dbb
        yi = yc - side * (db - 0.4)
        k.box(inner, hx0 + t, min(yi, yi - side * 0.1), 0.03, hx1 - t, max(yi, yi - side * 0.1), top)
        k.box(oak, hx0 + t, min(yc, yi), 0.03, hx1 - t, max(yc, yi), 0.06)
        zs = [top - 1.0]
        if side < 0:   # the back bar's upper floor slab and its edge
            k.box(conc, hx0, yc - 0.12, f2 - 0.25, hx1, yc + 0.12, f2)
            k.box(oak, hx0 + t, min(yc, yi), f2 - 0.02, hx1 - t, max(yc, yi), f2)
            k.box(inner, hx0 + t, min(yc, yi), f2 - 0.3, hx1 - t, max(yc, yi), f2 - 0.25)
            zs = [f2 - 1.0, top - 1.0]
        for _ in range(2):
            lx = rng.uniform(hx0 + 1.2, hx1 - 1.2)
            for zz in zs:
                k.box(lamp, lx - 0.15, yc - side * 1.6 - 0.15, zz, lx + 0.15, yc - side * 1.6 + 0.15, zz + 0.25)
    # the open-air bridge from the back bar's upper floor across the courtyard to the front roof garden
    bw = 1.2
    left_b = ex < xm
    bx = hx0 + t + 0.1 if left_b else hx1 - t - 0.1 - bw
    zb0, zb1 = f2, Hf
    k.slope(conc, bx, cy0 - 0.1, bx + bw, cy1 + 0.1, zb1 - 0.25, zb0 - 0.25, t=0.25)
    rx = bx + bw - 0.03 if left_b else bx
    k.beam(mull, (rx + 0.015, cy0, zb1 + 1.0), (rx + 0.015, cy1, zb0 + 1.0), 0.04, 0.04)
    for i in range(5):
        y = cy0 + (cy1 - cy0) * i / 4
        zz = zb1 + (zb0 - zb1) * i / 4
        k.box(mull, rx, y - 0.02, zz, rx + 0.03, y + 0.02, zz + 1.0)
    # courtyard floor: slate, moss, one maple rising through it, shallow steps down (Koshino's sunk court)
    k.box(slate, hx0 + t, cy0 + 0.05, 0.03, hx1 - t, cy1 - 0.05, 0.06)
    for i in range(3):
        k.box(conc, hx0 + t, cy0 + 0.05 + i * 0.4, 0.06, hx1 - t, cy0 + 0.45 + i * 0.4, 0.06 + 0.15 * (3 - i))
    mx = xm + (1.2 if left_b else -1.2)
    my = (cy0 + 1.2 + cy1) / 2
    k.prism(moss, blob_pts(mx, my, 1.4, min(1.3, (cy1 - cy0) / 2 - 0.5), rng, n=10), 0.06, 0.08)
    maple(k, rng, mx, my, h=min(Hf + 2.6, 6.5), cr=1.8)
    # formwork pattern: the street face and the visible garden face get tie holes, the back joints only
    budget = 300
    budget -= concrete_face(k, joint, "x", hx0, hx1, hy0, 0, Hf, -1, cap=budget)
    gx_face = hx0 if left_garden else hx1
    gsgn = -1 if left_garden else 1
    if side_g:
        concrete_face(k, joint, "y", hy0, cy1, gx_face, 0, Hf, gsgn, cap=budget // 2)
        concrete_face(k, joint, "y", cy1, hy1, gx_face, 0, H, gsgn, cap=budget // 2)
    concrete_face(k, joint, "x", hx0, hx1, hy1, 0, H, 1, holes=False)
    k.box(conc, hx0, cy1 - 0.12, H - 0.3, hx1, cy1 + 0.12, H)
    k.solid(hx0, hy0, 0, hx1, cy0, Hf)
    k.solid(hx0, cy1, 0, hx1, hy1, H)
    k.solid(hx0, cy0, 0, hx0 + t, cy1, Hf)
    k.solid(hx1 - t, cy0, 0, hx1, cy1, Hf)

    # roof garden planting on the front bar
    for _ in range(int((hx1 - hx0) / 1.5)):
        xx = rng.uniform(hx0 + 0.6, hx1 - 0.6)
        yy = rng.uniform(hy0 + 0.6, cy0 - 0.6)
        if abs(xx - (bx + bw / 2)) < bw:
            continue
        r = rng.uniform(0.35, 0.6)
        k.plant("Puff", "Foliage", rng.choice(HEDGE + (LEAF[1],)), xx, yy, Hf + 0.05, r * 1.2, r, r * 0.7,
                rng.uniform(0, 360))
    # ---- the garden ----
    # front strip: moss, stepping slabs to the slot, clipped shrubs
    k.box(moss, 0.4, 0.4, 0.03, W - 0.4, hy0 - 0.3, 0.05)
    nsl = max(2, int(hy0 / 0.7))
    for i in range(nsl):
        y = 0.15 + i * (hy0 - 0.2) / nsl
        k.box(slate, ex - 0.55, y, 0.03, ex + 0.55, y + 0.45, 0.07)
    for _ in range(int(W / 1.6)):
        xx = rng.uniform(0.8, W - 0.8)
        if abs(xx - ex) < 1.2:
            continue
        r = rng.uniform(0.35, 0.6)
        k.plant("Puff", "Foliage", rng.choice(HEDGE), xx, rng.uniform(0.6, hy0 - 0.6), 0.04, r * 1.2, r, r * 0.7,
                rng.uniform(0, 360))
    # side garden: Koshino's curved wall sweeping out of the house, a still pool inside it, maples in moss
    if side_g:
        gx0_, gx1_ = (0.4, hx0 - 0.3) if left_garden else (hx1 + 0.3, W - 0.4)
        k.box(moss, gx0_, hy0 - 0.2, 0.03, gx1_, D - 0.4, 0.05)
        R = min((gx1_ - gx0_) * 0.85, L * 0.55)
        cxw = gx_face
        cyw = hy0 + 0.6       # the arc springs from the street corner and wraps a pool beside the house
        pts = []
        for i in range(13):
            a = math.radians(90 * i / 12)
            pts.append((cxw + gsgn * R * math.sin(a), cyw + R * math.cos(a)))
        k.ribbon(conc, pts, 0.22, 0, Hf + 0.4)
        # still pool along the house inside the curve, black water flush with a concrete lip
        px0, px1 = sorted((cxw + gsgn * 0.7, cxw + gsgn * (R * 0.55)))
        py0, py1 = cyw + 0.3, cyw + R * 0.62
        k.box(slate, px0 - 0.15, py0 - 0.15, 0.03, px1 + 0.15, py1 + 0.15, 0.14)
        k.box(water, px0, py0, 0.03, px1, py1, 0.16)
        # concrete stepping slabs across the moss to the back, outside the curve
        slx = gx_face + gsgn * min(R + 0.9, gx1_ - gx0_ - 0.8)
        y = hy0
        while y < D - 1.2:
            if math.hypot(slx - cxw, y + 0.22 - cyw) > R + 0.5:
                k.box(slate, slx - 0.45, y, 0.03, slx + 0.45, y + 0.45, 0.08)
            y += 0.85
        # trees: a maple at the front corner, one at the back, a pine leaning out from the curve
        mxg = (gx0_ + gx1_) / 2
        maple(k, rng, clamp(cxw + gsgn * R * 0.55, 1.6, W - 1.6), min(cyw + R + 1.6, D - 2.0),
              h=rng.uniform(4.5, 5.5), cr=1.9)
        if D - (cyw + R) > 6:
            maple(k, rng, clamp(mxg + gsgn * 1.0, 1.6, W - 1.6), D - 2.2, h=rng.uniform(4.0, 5.0), cr=1.7)
        pine(k, rng, cxw + gsgn * R * 0.72, cyw + R * 0.38, h=5.2, lean=20, toward=270.0)
        for _ in range(5):
            k.plant("Stone", "PermeableStone", GRANITE, rng.uniform(gx0_ + 0.4, gx1_ - 0.4),
                    rng.uniform(hy0, D - 1), 0, 0.35, 0.3, 0.2, rng.uniform(0, 360))
    # back strip: a bamboo screen behind the house
    for _ in range(int(W * 1.6)):
        xx = rng.uniform(0.6, W - 0.6)
        yy = rng.uniform(hy1 + 0.5, D - 0.4)
        k.plant("Reed", "Foliage", BAMBOO_GREEN, xx, yy, 0, 1.6, 1.6, rng.uniform(5.0, min(H + 3.0, 9.5)),
                rng.uniform(0, 360))
        if rng.random() < 0.4:
            k.plant("Puff", "Foliage", LEAF[2], xx, yy, rng.uniform(4.0, 6.5), 0.6, 0.6, 0.5, shadow=False)
    return k


KINDS = {"sukiya_villa": sukiya_villa, "ando_courtyard": ando_courtyard}
SIZES = {
    "sukiya_villa": {"w": (20, 35), "d": (20, 35), "h": (5, 8), "floors": (1, 1), "use": "homes"},
    "ando_courtyard": {"w": (12, 25), "d": (16, 30), "h": (6, 10), "floors": (2, 2), "use": "homes"},
}
