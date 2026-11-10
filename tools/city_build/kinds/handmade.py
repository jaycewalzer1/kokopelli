"""Handmade family: bamboo, stacked stone, timber and grass, straight from the user's moodboard.

    bamboo_hall        bamboo pavilions (moodboard 90cf64448d13, 28072b34a9d0, e942be46d019)
    corbero_house      Xavier Corbero's house, Esplugues 1968-: pale stacked volumes, tall slender arches, a still pool
                       (b4970f245701)
    shiroiya_hill      Sou Fujimoto, Shiroiya Hotel 2020: a grassy hill with little white houses on a building
                       (129473520e6f)
    coconut_shophouse  Coconut Club timber shophouses: louvred shutters, vines dripping off the roof (7158e81aabaa)
    stilt_house        timber houses on stilts with decks and ladders over planting (Hiroo Isono, e929f29cc9ee)

Mood from Hiroo Isono (aa91bad1aa52, def46dad836a, 9ede10e3e51a): houses perched on grassy hills, rounded trees,
flowers in the green. Everything is a little old: moss on ledges, weathered timber, warm lit windows.
"""
import math

from .kit import Kit, LEAF, FLOWER, WHITE, TEAK

# ---- shared colours (sRGB) ----------------------------------------------------------------------------------------
BAMBOO = (206, 172, 104)
BAMBOO_OLD = (172, 140, 86)
BAMBOO_DARK = (122, 92, 56)
THATCH = (168, 142, 92)
THATCH_DARK = (132, 108, 70)
LANTERN = (255, 196, 120)
LIT = (255, 210, 150)
DARK_IN = (40, 34, 30)
MOSS = (92, 116, 58)
GRASS = (104, 146, 62)
BARK = (110, 96, 80)
PALE = (232, 224, 210)         # Corbero's pale render
PALE_SHADE = (214, 204, 188)
ROUGH = (128, 118, 104)        # stacked rough stone
WATER = (70, 96, 92)
BRICK_RED = (178, 96, 78)
CONCRETE_HOTEL = (178, 176, 170)
CACTUS = (84, 120, 74)
CYPRESS = (46, 74, 44)
PASTELS = ((222, 196, 160), (196, 214, 196), (232, 200, 180), (190, 206, 214), (230, 214, 156), (214, 180, 172))


class _ShiftKit(Kit):
    """A Kit whose local frame is pushed back by oy metres (so a kind can draw overhangs at y < 0 and still stay
    inside its plot)."""

    def __init__(self, w, d, oy):
        super().__init__(w, d)
        self.oy = oy

    def _p(self, x, y, z=0.0):
        return super()._p(x, y + self.oy, z)


ROLL_SIGN = -1.0   # kit.slope's roll comes out mirrored in UE; slab() uses the sign that renders correctly


def slab(k, s, x0, x1, ya, za, yb, zb, t):
    """A plank/slab spanning x0..x1, whose TOP-FRONT edge runs from (ya, za) to (yb, zb) in the y-z plane."""
    dy, dz = yb - ya, zb - za
    L = math.hypot(dy, dz)
    ang = math.degrees(math.atan2(dz, dy))
    # centre: the midpoint of the edge, pushed down by t/2 along the slab normal
    ny, nz = -dz / L, dy / L
    cy, cz = (ya + yb) / 2 - ny * t / 2, (za + zb) / 2 - nz * t / 2
    k.obox(s, (x0 + x1) / 2, cy, cz, (x1 - x0) / 2, L / 2, t / 2, 0, 0, ROLL_SIGN * ang)


def _mix(a, b, t):
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---- planting helpers ---------------------------------------------------------------------------------------------
def shrub(k, rng, x, y, z, r, flowers=0.5, leaf=None):
    """A soft Puff cushion, sometimes with flowers dotted on top."""
    k.plant("Puff", "Foliage", leaf or rng.choice(LEAF), x, y, z, r * rng.uniform(0.9, 1.2), r * rng.uniform(0.9, 1.2),
            r * rng.uniform(0.6, 0.9), rng.uniform(0, 360))
    if rng.random() < flowers:
        col = rng.choice(FLOWER)
        for _ in range(rng.randint(1, 3)):
            a, rr = rng.uniform(0, 6.28), rng.uniform(0, r * 0.6)
            k.plant("Blob", "Foliage", col, x + math.cos(a) * rr, y + math.sin(a) * rr, z + r * 0.75,
                    0.16 + r * 0.08, 0.16 + r * 0.08, 0.12 + r * 0.05, rng.uniform(0, 360), shadow=False)


def tree(k, rng, x, y, h, cr, flowering=False, z=0.0):
    """Isono's rounded tree: a stout bark trunk under a cluster of blob crowns (wider than tall)."""
    tr = _clamp(h * 0.04, 0.15, 0.45)
    k.plant("Trunk", "Bark", BARK, x, y, z, tr * 2, tr * 2, h * 0.62, rng.uniform(0, 360))
    base = rng.choice(LEAF)
    zc = z + h - cr * 0.75
    k.plant("Blob", "Foliage", base, x, y, zc, cr, cr, cr * 0.72, rng.uniform(0, 360))
    n = rng.randint(3, 5)
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.4, 0.4)
        s = cr * rng.uniform(0.5, 0.7)
        col = base if rng.random() < 0.5 else rng.choice(LEAF)
        k.plant("Blob", "Foliage", col, x + math.cos(a) * cr * 0.75, y + math.sin(a) * cr * 0.75,
                zc - cr * rng.uniform(0.3, 0.6), s, s, s * 0.8, rng.uniform(0, 360))
    if flowering:
        fc = rng.choice(FLOWER[:3])
        for _ in range(7):
            a, rr = rng.uniform(0, 6.28), rng.uniform(0.3, 0.9) * cr
            k.plant("Blob", "Foliage", fc, x + math.cos(a) * rr, y + math.sin(a) * rr,
                    zc + rng.uniform(0.1, 0.6) * cr, 0.4, 0.4, 0.3, shadow=False)


def cypress(k, rng, x, y, h, z=0.0):
    r = h * rng.uniform(0.12, 0.16)
    k.plant("Cone", "Foliage", CYPRESS, x, y, z, r * 2, r * 2, h, rng.uniform(0, 360))


def vines(k, rng, x0, x1, y, z, lmin, lmax, step=0.7, yaw=0.0, cushion=True):
    """Curtain of Fringe along an edge (running along x at y), hanging from z, plus Puff cushions spilling over."""
    n = max(1, int((x1 - x0) / step))
    for i in range(n):
        if rng.random() < 0.25:
            continue
        x = x0 + (i + rng.uniform(0.2, 0.8)) * (x1 - x0) / n
        L = rng.uniform(lmin, lmax)
        k.plant("Fringe", "Foliage", rng.choice(LEAF), x, y + rng.uniform(-0.05, 0.05), z, rng.uniform(0.7, 1.1), 1.0, L,
                yaw + rng.uniform(-12, 12), shadow=False)
        if cushion and rng.random() < 0.45:
            k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, z - 0.05, 0.45, 0.35, 0.3, rng.uniform(0, 360))


def vines_y(k, rng, y0, y1, x, z, lmin, lmax, step=0.8, yaw=90.0):
    """Same as vines() but along a side edge (running along y at x)."""
    n = max(1, int((y1 - y0) / step))
    for i in range(n):
        if rng.random() < 0.3:
            continue
        y = y0 + (i + rng.uniform(0.2, 0.8)) * (y1 - y0) / n
        k.plant("Fringe", "Foliage", rng.choice(LEAF), x, y, z, rng.uniform(0.7, 1.1), 1.0, rng.uniform(lmin, lmax),
                yaw + rng.uniform(-12, 12), shadow=False)


def bed(k, rng, x0, y0, x1, y1, density=0.35, z=0.0, rmin=0.35, rmax=0.8, flowers=0.5):
    """Fill a rectangle with shrubs (density: shrubs per m2, capped)."""
    n = int(_clamp((x1 - x0) * (y1 - y0) * density, 1, 40))
    for _ in range(n):
        shrub(k, rng, rng.uniform(x0, x1), rng.uniform(y0, y1), z, rng.uniform(rmin, rmax), flowers)


def flowers_in_grass(k, rng, x0, y0, x1, y1, n, z=0.0):
    for _ in range(n):
        k.plant("Blob", "Foliage", rng.choice(FLOWER), rng.uniform(x0, x1), rng.uniform(y0, y1), z + 0.05,
                0.12, 0.12, 0.08, shadow=False)


def lantern(k, s_lan, s_cord, x, y, ztop, drop, size=0.22):
    k.pole(s_cord, (x, y, ztop), (x, y, ztop - drop), 0.012, 4)
    k.box(s_lan, x - size / 2, y - size / 2, ztop - drop - size * 1.4, x + size / 2, y + size / 2, ztop - drop)


def banana(k, rng, s_leaf, s_stem, x, y, h):
    """A banana / bird-of-paradise clump: stems + big paddle leaves (oriented boxes)."""
    for j in range(rng.randint(1, 2)):
        bx, by = x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4)
        hh = h * rng.uniform(0.75, 1.0)
        k.pole(s_stem, (bx, by, 0), (bx, by, hh * 0.65), 0.09, 6)
        for i in range(5):
            yaw = i * 72 + rng.uniform(-20, 20)
            L = hh * 0.42
            a = math.radians(yaw)
            pitch = rng.uniform(15, 40)
            cx = bx + math.cos(a) * L * 0.45 * math.cos(math.radians(pitch))
            cy = by + math.sin(a) * L * 0.45 * math.cos(math.radians(pitch))
            cz = hh * 0.65 + L * 0.45 * math.sin(math.radians(pitch))
            k.obox(s_leaf, cx, cy, cz, L / 2, 0.22 * hh / 3, 0.015, pitch, yaw, rng.uniform(-15, 15))


# ---- arch helper (Corbero) ----------------------------------------------------------------------------------------
def arch_head(k, s, c, a, b, zs, r, ztop, axis="x", segs=8):
    """Solid wall above a semicircular arch: the opening is centred at c along the wall, wall thickness from a to b
    (y if axis == "x", x if axis == "y"), springing at zs with radius r, wall top at ztop."""
    def P(u, v, z):
        return (u, v, z) if axis == "x" else (v, u, z)

    def N(nu, nv, nz):
        return (nu, nv, nz) if axis == "x" else (nv, nu, nz)

    for i in range(segs):
        t0, t1 = math.pi * i / segs, math.pi * (i + 1) / segs
        u0, z0 = c - r * math.cos(t0), zs + r * math.sin(t0)
        u1, z1 = c - r * math.cos(t1), zs + r * math.sin(t1)
        k.quad(s, P(u0, a, z0), P(u1, a, z1), P(u1, a, ztop), P(u0, a, ztop), N(0, -1, 0))
        k.quad(s, P(u0, b, z0), P(u1, b, z1), P(u1, b, ztop), P(u0, b, ztop), N(0, 1, 0))
        tm = (t0 + t1) / 2
        k.quad(s, P(u0, a, z0), P(u1, a, z1), P(u1, b, z1), P(u0, b, z0), N(math.cos(tm), 0, -math.sin(tm)))


def arcade(k, s, u0, u1, a, b, z0, z1, n, ratio=0.55, spring=None, axis="x", segs=8, fill=None, sill=0.0):
    """Wall from u0..u1 (along axis), thickness a..b, z0..z1, pierced by n tall arched openings.
    ratio = opening width / bay. spring = springing height above z0 (default tall and slender).
    fill(s_center_u, width, z_bottom, z_spring_top) is called per opening (to put glass / light inside).
    Returns the opening centres."""
    bay = (u1 - u0) / n
    ow = bay * ratio
    r = ow / 2
    zs = z0 + (spring if spring is not None else max(0.6, (z1 - z0) - r - 0.35))
    zs = min(zs, z1 - r - 0.12)

    def box(uu0, uu1, zz0, zz1):
        if axis == "x":
            k.box(s, uu0, a, zz0, uu1, b, zz1)
        else:
            k.box(s, a, uu0, zz0, b, uu1, zz1)

    cs = []
    for i in range(n):
        c = u0 + bay * (i + 0.5)
        cs.append(c)
        # pier to the left of this opening (and the last one on the right)
        box(u0 + bay * i if i else u0, c - r, z0, z1)
        if sill > 0:
            box(c - r, c + r, z0, z0 + sill)
        arch_head(k, s, c, a, b, zs, r, z1, axis, segs)
        if fill:
            fill(c, ow, z0 + sill, zs + r)
    box(cs[-1] + r, u1, z0, z1)
    return cs


# =================================================================================================================
# bamboo_hall
# =================================================================================================================
def bamboo_hall(plot):
    W, D = plot.w, plot.d
    H = _clamp(plot.h_max, 7.0, 14.0)
    k = Kit(W, D)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    bam = k.mat("Timber", BAMBOO)
    bam_old = k.mat("Timber", BAMBOO_OLD)
    tie = k.mat("Timber", BAMBOO_DARK)
    thatch = k.mat("Timber", THATCH)
    floor = k.mat("PermeableStone", (206, 200, 186))
    moss = k.mat("Moss", MOSS)
    lan = k.mat("Lantern", LANTERN)
    cloth = k.mat("Fabric", _mix(pal[2], (196, 52, 48), 0.55))

    variant = "aframe" if rng.random() < 0.4 else "vault"
    mx, my0, my1 = _clamp(W * 0.08, 2.0, 3.5), _clamp(D * 0.14, 2.5, 4.0), 2.0
    x0, x1, y0, y1 = mx, W - mx, my0, D - my1
    plin = 0.35
    k.box(floor, x0 - 0.6, y0 - 0.6, 0, x1 + 0.6, y1 + 0.6, plin)
    k.box(moss, x0 - 0.62, y0 - 0.62, 0, x1 + 0.62, y1 + 0.62, 0.12)
    k.solid(x0, y0, 0, x1, y1, 0.3)

    if variant == "vault":
        # shallow parabolic thatch shell with swooping eaves (90cf64448d13 + e942be46d019)
        oh = 2.0                                   # eave overhang beyond the columns
        ya, yb = y0 - oh, y1 + oh
        half, mid = (yb - ya) / 2, (ya + yb) / 2
        ze = _clamp(H * 0.3, 2.8, 3.8)             # eave tip: low, swooping
        zc = min(H - 0.8, ze + max(2.8, half * 0.42))    # crown (top of the thatch is ~0.4 above)
        t = 0.38
        nseg = 12

        def z_in(y):
            u = _clamp((y - mid) / half, -1.0, 1.0)
            return zc - (zc - ze) * u * u

        thatch_m = k.mat("Timber", _mix(THATCH, MOSS, 0.35))
        thatch_d = k.mat("Timber", THATCH_DARK)
        for i in range(nseg):
            ya_, yb_ = ya + (yb - ya) * i / nseg, ya + (yb - ya) * (i + 1) / nseg
            s_ = thatch_m if i in (0, nseg - 1) else thatch
            slab(k, s_, x0 - 1.0, x1 + 1.0, ya_ - 0.03, z_in(ya_) + t, yb_ + 0.03, z_in(yb_) + t, t)
        # ridge roll + mossy patches + a few tufts growing in the old thatch
        k.pole(thatch_d, (x0 - 1.0, mid, zc + t + 0.05), (x1 + 1.0, mid, zc + t + 0.05), 0.28, 8)
        for _ in range(int((x1 - x0) / 3)):
            px = rng.uniform(x0, x1)
            py = rng.choice((rng.uniform(ya + 0.4, ya + half * 0.5), rng.uniform(yb - half * 0.5, yb - 0.4)))
            k.plant("Puff", "Foliage", rng.choice((MOSS, (110, 130, 64), LEAF[2])), px, py, z_in(py) + t - 0.15,
                    rng.uniform(0.5, 1.0), rng.uniform(0.4, 0.8), 0.35, rng.uniform(0, 360))
            if rng.random() < 0.35:
                k.plant("Blob", "Foliage", rng.choice(FLOWER), px, py, z_in(py) + t, 0.12, 0.12, 0.08, shadow=False)
        # eave edge: a thick dark binding along both eaves
        for ye in (ya, yb):
            k.pole(thatch_d, (x0 - 1.0, ye, ze + t * 0.5), (x1 + 1.0, ye, ze + t * 0.5), 0.2, 6)

        # bamboo ribs under the thatch (pole chains following the curve), and purlins along the hall
        nr = max(4, int((x1 - x0 + 1.8) / 1.5))
        for i in range(nr + 1):
            xr = x0 - 0.9 + (x1 - x0 + 1.8) * i / nr
            m = 8
            for j in range(m):
                ya_, yb_ = ya + 0.2 + (yb - ya - 0.4) * j / m, ya + 0.2 + (yb - ya - 0.4) * (j + 1) / m
                k.pole(bam if i % 3 else bam_old, (xr, ya_, z_in(ya_) - 0.08), (xr, yb_, z_in(yb_) - 0.08), 0.075, 6)
        for f in (-0.75, -0.45, -0.15, 0.15, 0.45, 0.75):
            yy = mid + f * half
            k.pole(bam_old, (x0 - 1.0, yy, z_in(yy) - 0.2), (x1 + 1.0, yy, z_in(yy) - 0.2), 0.07, 6)
        # tree columns: bundles of poles, bound at a knot, that flare out into the roof
        nx = max(3, int(round((x1 - x0) / 6.0)) + 1)
        rows = [y0 + 1.0, y1 - 1.0] + ([mid] if (y1 - y0) > 16 else [])
        for by in rows:
            for i in range(nx):
                bx = x0 + 1.0 + (x1 - x0 - 2.0) * i / (nx - 1)
                if by == mid and 0 < i < nx - 1 and i % 2:
                    continue
                zt = z_in(by)
                knot = plin + _clamp((zt - plin) * 0.38, 1.3, 2.6)
                npo = 8
                for p in range(npo):
                    a = 2 * math.pi * p / npo + rng.uniform(-0.15, 0.15)
                    base = (bx + math.cos(a) * 0.24, by + math.sin(a) * 0.24, plin)
                    kn = (bx + math.cos(a) * 0.16, by + math.sin(a) * 0.16, knot)
                    sp = rng.uniform(1.8, 2.8)
                    tx = bx + math.cos(a) * sp
                    ty = _clamp(by + math.sin(a) * sp, ya + 0.6, yb - 0.6)
                    top = (tx, ty, z_in(ty) - 0.1)
                    s_ = bam if p % 3 else bam_old
                    k.pole(s_, base, kn, 0.07, 6)
                    k.pole(s_, kn, top, 0.065, 6)
                k.cyl(tie, bx, by, knot - 0.3, 0.25, 0.25, 0.4, 10)
                k.cyl(tie, bx, by, plin + 0.3, 0.29, 0.29, 0.14, 10)
                k.solid(bx - 0.3, by - 0.3, 0, bx + 0.3, by + 0.3, knot)
        # bamboo slat screens at both ends (under the curve) with a doorway, open long sides
        for xe in (x0 - 0.2, x1 + 0.2):
            n = int((y1 - y0 + 1.0) / 0.34)
            for i in range(n + 1):
                y = y0 - 0.5 + (y1 - y0 + 1.0) * i / n
                ztop = z_in(y) - 0.1
                zb = plin if abs(y - mid) > 1.6 else plin + 2.7
                if zb < ztop:
                    k.pole(bam if i % 4 else bam_old, (xe, y, zb), (xe, y, ztop), 0.05, 5)
            for zz in (plin + 0.9, plin + 2.7):
                k.pole(tie, (xe, y0 - 0.5, zz), (xe, mid - 1.6, zz), 0.04, 4)
                k.pole(tie, (xe, mid + 1.6, zz), (xe, y1 + 0.5, zz), 0.04, 4)
        roof_top = zc + t
        lan_y = [mid - half * 0.3, mid + half * 0.3]
    else:
        # A-frame (28072b34a9d0): a steep gable whose roof IS the bamboo, a dense lattice of culms with light between
        ez = _clamp(H * 0.2, 1.8, 2.6)
        ya, yb = y0 - 0.7, y1 + 0.7
        mid = (ya + yb) / 2
        rh = H - ez - 0.45
        hw = (yb - ya) / 2

        def z_in(y):
            return ez + rh * (1 - abs(y - mid) / hw) - 0.12

        # purlins + rafters (structure), then the culm lattice on top
        for f in (0.15, 0.4, 0.65, 0.88):
            for sgn in (-1, 1):
                yy = mid + sgn * hw * (1 - f)
                k.pole(bam_old, (x0 - 0.9, yy, z_in(yy) - 0.05), (x1 + 0.9, yy, z_in(yy) - 0.05), 0.08, 6)
        nb = int((x1 - x0 + 1.8) / 0.24)
        for i in range(nb + 1):
            xx = x0 - 0.9 + (x1 - x0 + 1.8) * i / nb + rng.uniform(-0.03, 0.03)
            s_ = bam if i % 5 else bam_old
            for sgn in (-1, 1):
                k.pole(s_, (xx, mid + sgn * (hw + 0.1), ez - 0.1), (xx, mid - sgn * 0.15, ez + rh + 0.12), 0.06, 5)
        # a thatch cap along the ridge only, so the top reads solid and the lower slopes stay airy
        cap = rh * 0.22
        k.gable(thatch, x0 - 1.0, mid - hw * 0.22, ez + rh - cap + 0.12, x1 + 1.0, mid + hw * 0.22, ez + rh - cap + 0.12, cap + 0.1, True)
        k.pole(tie, (x0 - 1.0, mid, ez + rh + 0.24), (x1 + 1.0, mid, ez + rh + 0.24), 0.12, 6)
        # long walls: dense vertical slats with an opening in the front
        for yy in (y0, y1):
            n = int((x1 - x0) / 0.3)
            for i in range(n + 1):
                xx = x0 + (x1 - x0) * i / n
                if yy == y0 and abs(xx - (x0 + x1) / 2) < 1.5:
                    continue
                k.pole(bam if i % 3 else bam_old, (xx, yy, plin), (xx, yy, z_in(yy) + 0.05), 0.05, 5)
            for zz in (plin + 0.8, z_in(yy) - 0.1):
                k.pole(tie, (x0, yy, zz), (x1, yy, zz), 0.04, 4)
        # gable ends: slats following the roof line, doorway in the middle
        for xe in (x0, x1):
            n = int((y1 - y0) / 0.3)
            for i in range(n + 1):
                y = y0 + (y1 - y0) * i / n
                zb = plin if abs(y - mid) > 1.2 else plin + 2.6
                k.pole(bam if i % 3 else bam_old, (xe, y, zb), (xe, y, z_in(y)), 0.05, 5)
        # inner frame: A-trusses
        nt = max(2, int((x1 - x0) / 4.0))
        for i in range(nt + 1):
            xx = x0 + (x1 - x0) * i / nt
            for yy in (y0 + 0.2, y1 - 0.2):
                k.pole(bam_old, (xx, yy, plin), (xx, mid, ez + rh - 0.3), 0.11, 6)
            k.pole(bam_old, (xx, mid - rh * 0.25, ez + rh * 0.55), (xx, mid + rh * 0.25, ez + rh * 0.55), 0.07, 5)
        roof_top = H
        lan_y = [mid - 1.5, mid + 1.5]

    # inside: long table with benches, cloth runner, hanging lanterns, a dog
    tx0, tx1 = x0 + (x1 - x0) * 0.25, x0 + (x1 - x0) * 0.7
    ty = (y0 + y1) / 2 - 0.4
    k.box(bam_old, tx0, ty - 0.45, plin + 0.72, tx1, ty + 0.45, plin + 0.78)
    k.box(cloth, tx0 + 0.3, ty - 0.2, plin + 0.78, tx1 - 0.3, ty + 0.2, plin + 0.8)
    for xx in (tx0 + 0.3, tx1 - 0.3):
        for yy in (ty - 0.35, ty + 0.35):
            k.pole(tie, (xx, yy, plin), (xx, yy, plin + 0.72), 0.04, 4)
    for yy in (ty - 0.85, ty + 0.85):
        k.box(bam, tx0, yy - 0.15, plin + 0.42, tx1, yy + 0.15, plin + 0.46)
    nl = max(3, int((x1 - x0) / 3.5))
    for i in range(nl):
        lx = x0 + 1.0 + (x1 - x0 - 2.0) * (i + 0.5) / nl
        for ly in lan_y:
            zt = z_in(ly)
            lantern(k, lan, tie, lx, ly, zt, rng.uniform(0.8, 1.6), 0.3)
    # cloth banners hanging from the roof (28072b34a9d0's red cloths), in the block's accent colour
    for i in range(rng.randint(2, 4)):
        bx = x0 + (x1 - x0) * (i + 0.5) / 4 + rng.uniform(-0.8, 0.8)
        byy = rng.choice(lan_y)
        zt = z_in(byy) - 0.15
        bh = min(3.0, zt - plin - 1.8)
        if bh > 0.8:
            k.box(cloth, bx - 0.4, byy - 0.02, zt - bh, bx + 0.4, byy + 0.02, zt)
            k.pole(tie, (bx - 0.5, byy, zt), (bx + 0.5, byy, zt), 0.025, 4)
    dx, dy = rng.uniform(x0 + 2, x1 - 2), y0 + 1.5
    k.plant("Blob", "Plain", (178, 124, 70), dx, dy, plin + 0.42, 0.36, 0.14, 0.15, 0)
    k.plant("Blob", "Plain", (178, 124, 70), dx + 0.36, dy, plin + 0.58, 0.12, 0.1, 0.11, 0)
    for lx in (dx - 0.22, dx + 0.22):
        k.plant("Cylinder", "Plain", (150, 104, 60), lx, dy, plin, 0.07, 0.07, 0.32)

    # garden: big old trees, shrubs with flowers along the plinth, flowers in the grass
    # trunks stand just outside the roof ends; the crowns spread over the thatch
    tx_ = max(0.5, x0 - 1.6)
    for (txx, tyy) in ((tx_, rng.uniform(1.5, D * 0.5)), (W - tx_, rng.uniform(D * 0.45, D - 1.5))):
        th = min(plot.h_max + 6.0, roof_top + rng.uniform(3.0, 6.0))
        tree(k, rng, txx, tyy, th, _clamp(th * 0.3, 3.0, 3.8), flowering=rng.random() < 0.35)
    n = int((x1 - x0) / 1.6)
    for i in range(n):
        xx = x0 + (x1 - x0) * (i + rng.uniform(0.2, 0.8)) / n
        if abs(xx - (x0 + x1) / 2) < 2.0 and variant == "aframe":
            continue
        shrub(k, rng, xx, y0 - 1.1 - rng.uniform(0, 0.8), 0, rng.uniform(0.35, 0.75), 0.6)
        if rng.random() < 0.6:
            shrub(k, rng, xx, y1 + 1.0 + rng.uniform(0, 0.6), 0, rng.uniform(0.4, 0.8), 0.4)
    for xe in (x0 - 1.2, x1 + 1.2):
        for _ in range(int((y1 - y0) / 2.5)):
            shrub(k, rng, xe + rng.uniform(-0.4, 0.4), rng.uniform(y0, y1), 0, rng.uniform(0.35, 0.7), 0.5)
    flowers_in_grass(k, rng, 0.3, 0.3, W - 0.3, y0 - 0.8, int(W * 0.8))
    # path to the open front
    k.box(k.mat("Path", (190, 176, 150)), (x0 + x1) / 2 - 1.2, 0, 0, (x0 + x1) / 2 + 1.2, y0 - 0.6, 0.06)
    return k


# =================================================================================================================
# corbero_house
# =================================================================================================================
def corbero_house(plot):
    W, D = plot.w, plot.d
    H = _clamp(plot.h_max, 6.0, 12.0)
    k = Kit(W, D)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    pale = k.mat("RammedEarth", (246, 240, 228), 3000.0)    # worn pale render, big soft mottling
    pale2 = k.mat("RammedEarth", (230, 220, 204), 3000.0)
    # the RammedEarth strata darken with height (world-projected), so the upper storeys get a brighter tint
    pale_hi = k.mat("RammedEarth", (255, 252, 246), 3000.0)
    rough = k.mat("PermeableStone", (176, 162, 140), 260.0)  # big rough stacked blocks
    coping = k.mat("RammedEarth", (226, 218, 202), 1200.0)
    pave = k.mat("Path", (206, 196, 180))
    water = k.mat("Water", WATER)
    dark = k.mat("Plain", DARK_IN)
    lit = k.mat("Lantern", LIT)
    moss = k.mat("Moss", MOSS)
    pot = k.mat("RammedEarth", _mix((176, 104, 72), pal[2], 0.3))
    door = k.mat("Timber", _mix(TEAK, pal[1], 0.35))

    st = _clamp(H * 0.42, 3.4, 4.4)          # a tall storey, for tall slender arches
    py0 = 1.2
    py1 = py0 + _clamp(D * 0.2, 3.0, 5.5)     # pool
    hy0 = _clamp(D * 0.52, py1 + 4.0, D - 7.0)  # house front (arcade line)
    hy1 = D - 1.2
    hx0, hx1 = 1.0, W - 1.0
    side = rng.random() < 0.5                 # which side the tower + wing go

    # courtyard paving, rough stone retaining wall along the back
    k.box(pave, 0.6, py0, 0, W - 0.6, hy1, 0.06)
    k.box(rough, 0.4, D - 1.0, 0, W - 0.4, D - 0.3, 1.3)
    k.box(moss, 0.4, D - 1.02, 1.2, W - 0.4, D - 0.28, 1.36)

    # the still pool: rough stacked-stone basin, pale coping, lily pads
    px0, px1 = W * 0.1, W * 0.9
    for (a0, b0, a1, b1) in ((px0, py0, px1, py0 + 0.6), (px0, py0, px0 + 0.45, py1), (px1 - 0.45, py0, px1, py1),
                             (px0, py1 - 0.35, px1, py1)):
        k.box(rough, a0, b0, 0, a1, b1, 0.8)
    k.box(coping, px0 - 0.06, py0 - 0.06, 0.8, px1 + 0.06, py0 + 0.66, 0.9)
    k.box(coping, px0 - 0.06, py1 - 0.41, 0.8, px1 + 0.06, py1 + 0.06, 0.9)
    k.box(water, px0 + 0.45, py0 + 0.6, 0.0, px1 - 0.45, py1 - 0.35, 0.68)
    k.box(moss, px0 - 0.02, py0 - 0.02, 0.0, px1 + 0.02, py0 + 0.25, 0.3)
    for _ in range(4):
        k.plant("Disc", "Foliage", (82, 120, 60), rng.uniform(px0 + 1, px1 - 1), rng.uniform(py0 + 0.9, py1 - 0.6), 0.68,
                rng.uniform(0.5, 0.9), rng.uniform(0.5, 0.9), 1, rng.uniform(0, 360), shadow=False)
    k.solid(px0, py0, 0, px1, py1, 0.9)

    # ---- base storey: an arcade, a deep loggia, then the lit inner wall ------------------------------------------
    th = 0.45
    yi = hy0 + 2.8
    nbay = max(3, int((hx1 - hx0) / 2.1))
    cs = arcade(k, pale, hx0, hx1, hy0, hy0 + th, 0, st, nbay, ratio=0.52)
    k.box(pale2, hx0, yi, 0, hx1, hy1, st)
    k.box(pale, hx0 - 0.15, hy0 - 0.15, st, hx1 + 0.15, hy1, st + 0.3)       # terrace slab = loggia ceiling
    k.box(pale, hx0, hy0 + th, 0, hx0 + 0.45, yi, st)                         # loggia end walls
    k.box(pale, hx1 - 0.45, hy0 + th, 0, hx1, yi, st)
    mid_i = len(cs) // 2
    for i, c in enumerate(cs):
        if i == mid_i:
            k.box(door, c - 0.6, yi - 0.06, 0, c + 0.6, yi - 0.01, 2.5)
            k.box(dark, c - 0.7, yi - 0.04, 2.5, c + 0.7, yi - 0.01, 2.6)
        else:
            s_ = lit if rng.random() < 0.4 else dark
            k.box(s_, c - 0.42, yi - 0.05, 0.5, c + 0.42, yi - 0.01, min(st - 0.6, 3.0))
    k.solid(hx0, hy0, 0, hx1, hy1, st)
    terrace = st + 0.3
    # parapet with moss along the terrace edge
    k.box(pale, hx0 - 0.15, hy0 - 0.15, terrace, hx1 + 0.15, hy0 + 0.15, terrace + 0.7)
    k.box(moss, hx0 - 0.15, hy0 - 0.17, terrace + 0.68, hx1 + 0.15, hy0 + 0.17, terrace + 0.76)
    k.box(k.mat("GreenRoof", GRASS), hx0 + 0.2, hy1 - 2.5, terrace, hx1 - 0.2, hy1 - 0.2, terrace + 0.12)
    for _ in range(rng.randint(2, 4)):      # a few bunches of creeper spilling over the parapet
        x = rng.uniform(hx0 + 1, hx1 - 3)
        vines(k, rng, x, x + rng.uniform(1.2, 2.6), hy0 - 0.18, terrace + 0.7, 0.8, st * 0.7, 0.4, 180)

    # ---- upper volume, offset, with an open arch frame continuing past it into the sky -----------------------------
    room = H - terrace
    if room > 2.6:
        uw = (hx1 - hx0) * rng.uniform(0.42, 0.55)
        ux0 = hx0 + 1.0 + rng.uniform(0.0, (hx1 - hx0 - 2.0) - uw) if not side else hx1 - 1.0 - uw - rng.uniform(0.0, (hx1 - hx0) * 0.2)
        ux0 = _clamp(ux0, hx0 + 0.5, hx1 - 0.5 - uw)
        ux1 = ux0 + uw
        uy0 = hy0 + rng.uniform(1.6, 2.6)
        utop = terrace + min(room - 0.3, st * 0.9)
        nb2 = max(2, int(uw / 1.9))
        cs2 = arcade(k, pale_hi, ux0, ux1, uy0, uy0 + 0.4, terrace, utop, nb2, ratio=0.48, sill=0.6)
        for c in cs2:
            k.box(lit if rng.random() < 0.45 else dark, c - 0.45, uy0 + 0.42, terrace + 0.6, c + 0.45, uy0 + 0.46, utop - 0.5)
        k.box(pale2, ux0, uy0 + 0.4, terrace, ux1, hy1 - 0.3, utop)
        k.box(pale_hi, ux0 - 0.1, uy0 - 0.1, utop, ux1 + 0.1, hy1 - 0.2, utop + 0.2)
        k.box(moss, ux0 + 0.3, uy0 + 0.3, utop + 0.2, ux1 - 0.3, hy1 - 0.5, utop + 0.25)
        # open frame: the same arcade continued as a free wall (sky through the arches)
        fw = min(2 * 2.0, (ux0 - hx0 - 0.4) if side else (hx1 - ux1 - 0.4))
        if fw > 1.8:
            f0, f1 = (ux0 - fw, ux0) if side else (ux1, ux1 + fw)
            arcade(k, pale_hi, f0, f1, uy0, uy0 + 0.4, terrace, utop, max(1, int(fw / 1.9)), ratio=0.48)
            k.box(pale_hi, f0, uy0 - 0.05, utop, f1, uy0 + 0.45, utop + 0.2)
        # roof garden pots on the terrace
        for _ in range(rng.randint(2, 4)):
            x = rng.uniform(hx0 + 0.6, hx1 - 0.6)
            if ux0 - 0.4 < x < ux1 + 0.4:
                continue
            k.cyl(pot, x, hy0 + 0.6, terrace, 0.28, 0.34, 0.45, 10)
            shrub(k, rng, x, hy0 + 0.6, terrace + 0.4, 0.4, 0.7)

    # ---- belvedere tower: open arches on all four sides at the top -------------------------------------------------
    tw = _clamp(W * 0.11, 2.8, 3.8)
    tx0 = hx1 - tw - 0.2 if side else hx0 + 0.2
    tx1 = tx0 + tw
    ty0 = hy0 + 0.2
    ty1 = ty0 + tw
    if H - terrace > 3.4:
        bz = terrace + (H - terrace) * 0.3
        k.box(pale_hi, tx0, ty0, terrace, tx1, ty1, bz)
        k.box(dark, (tx0 + tx1) / 2 - 0.35, ty0 - 0.02, terrace + 0.4, (tx0 + tx1) / 2 + 0.35, ty0, bz - 0.3)
        top = H - 0.25
        for (axis, a_, b_, u0, u1) in (("x", ty0, ty0 + 0.35, tx0, tx1), ("x", ty1 - 0.35, ty1, tx0, tx1),
                                       ("y", tx0, tx0 + 0.35, ty0 + 0.35, ty1 - 0.35), ("y", tx1 - 0.35, tx1, ty0 + 0.35, ty1 - 0.35)):
            arcade(k, pale_hi, u0, u1, a_, b_, bz, top, 1, ratio=0.62 if axis == "x" else 0.66, axis=axis, segs=8)
        k.box(pale_hi, tx0 - 0.08, ty0 - 0.08, top, tx1 + 0.08, ty1 + 0.08, H)
        k.box(moss, tx0 + 0.2, ty0 + 0.2, H - 0.05, tx1 - 0.2, ty1 - 0.2, H)
        shrub(k, rng, (tx0 + tx1) / 2, (ty0 + ty1) / 2, H - 0.05, 0.5, 0.6)

    # ---- side wing: a two-tier cloister facing the courtyard ------------------------------------------------------
    ww = _clamp(W * 0.13, 2.8, 3.6)
    wx0, wx1 = (hx1 - ww, hx1) if side else (hx0, hx0 + ww)
    wy0, wy1 = py1 + 1.0, hy0
    if wy1 - wy0 > 2.6:
        fa, fb = (wx0, wx0 + 0.4) if side else (wx1 - 0.4, wx1)
        ba, bb = (wx1 - 0.35, wx1) if side else (wx0, wx0 + 0.35)
        nbw = max(1, int((wy1 - wy0) / 2.1))
        z2 = min(H - 0.6, st * 1.85)
        arcade(k, pale, wy0, wy1, fa, fb, 0, st, nbw, ratio=0.52, axis="y")
        if z2 - st > 2.0:
            arcade(k, pale_hi, wy0, wy1, fa, fb, st, z2, nbw, ratio=0.48, axis="y", sill=0.5)
        else:
            z2 = st
        k.box(pale2, ba, wy0, 0, bb, wy1, z2)
        for z in (st - 0.05, z2):
            k.box(pale, wx0, wy0, z, wx1, wy1, z + 0.25)
        k.box(pale, wx0, wy0, 0, wx1, wy0 + 0.4, z2)
        for i in range(nbw):
            c = wy0 + (wy1 - wy0) * (i + 0.5) / nbw
            s_ = lit if rng.random() < 0.4 else dark
            xa_ = ba - 0.03 if side else bb
            k.box(s_, xa_, c - 0.4, 0.5, xa_ + 0.03, c + 0.4, 2.8)
        k.solid(wx0, wy0, 0, wx1, wy1, z2)
        vines_y(k, rng, wy0, wy1, fa - 0.03 if side else fb + 0.03, z2 + 0.2, 0.6, 2.2, yaw=270 if side else 90)
        k.box(moss, wx0, wy0, z2 + 0.25, wx1, wy1, z2 + 0.3)

    # ---- a free-standing arcade wall on the other side (garden wall, sky through it) ------------------------------
    gx = hx0 + 0.2 if side else hx1 - 0.6
    if hy0 - py1 > 3.0:
        gh = st * 0.8
        ng = max(2, int((hy0 - py1 - 0.6) / 1.9))
        arcade(k, pale, py1 + 0.3, hy0, gx, gx + 0.4, 0, gh, ng, ratio=0.55, axis="y")
        k.box(moss, gx - 0.02, py1 + 0.3, gh - 0.05, gx + 0.42, hy0, gh + 0.03)
        k.solid(gx, py1 + 0.3, 0, gx + 0.4, hy0, gh)
    # ---- tall gate frames standing in the courtyard (the photo's central arches) ----------------------------------
    gy = (py1 + hy0) / 2 + 0.6
    if hy0 - py1 > 4.0 and H >= 7.0:
        gw = 2.2
        gx0 = W * rng.uniform(0.3, 0.45)
        nfr = 2 if W > 26 else 1
        for j in range(nfr):
            x0_ = gx0 + j * (gw + 2.4)
            h1 = min(H - 0.8, st * 1.0)
            arcade(k, pale, x0_, x0_ + gw, gy - 0.22, gy + 0.22, 0, h1, 1, ratio=0.6)
            if j == 0 and H - h1 > 3.0:
                arcade(k, pale_hi, x0_, x0_ + gw, gy - 0.22, gy + 0.22, h1, min(H - 0.3, h1 + st * 0.9), 1, ratio=0.55)
            k.solid(x0_, gy - 0.22, 0, x0_ + gw, gy + 0.22, h1)
    k.box(coping, W * 0.62, py1 + 0.7, 0, W * 0.62 + 2.2, py1 + 1.15, 0.45)       # stone bench

    # ---- planting: cypresses, an old pine, potted cacti by the pool, flowers in the front bed ----------------------
    for xx in (0.8, W - 0.8):
        cypress(k, rng, xx, rng.uniform(py1 + 0.5, hy0), min(H + 1.0, plot.h_max) * rng.uniform(0.75, 1.0))
    tree(k, rng, W - 2.4 if side else 2.4, D - 2.2, H + 3.0, 2.8)
    for i in range(rng.randint(5, 8)):
        x = px0 + rng.uniform(0.3, 2.0) if i % 2 else px1 - rng.uniform(0.3, 2.0)
        y = py1 + rng.uniform(0.3, 1.2)
        ph = rng.uniform(0.4, 0.6)
        k.cyl(pot, x, y, 0, 0.3, 0.38, ph, 10)
        for _ in range(rng.randint(1, 3)):
            ch = rng.uniform(0.6, 1.5)
            ox, oy = rng.uniform(-0.12, 0.12), rng.uniform(-0.12, 0.12)
            k.plant("Cylinder", "Foliage", CACTUS, x + ox, y + oy, ph, 0.2, 0.2, ch, rng.uniform(0, 360))
            k.plant("Blob", "Foliage", CACTUS, x + ox, y + oy, ph + ch, 0.1, 0.1, 0.07)
        if rng.random() < 0.4:
            k.plant("Blob", "Foliage", rng.choice(FLOWER), x, y, ph + 0.1, 0.13, 0.13, 0.09)
    bed(k, rng, 0.6, 0.2, W - 0.6, py0 - 0.1, 0.5, 0, 0.3, 0.6, 0.6)
    flowers_in_grass(k, rng, 0.6, 0.1, W - 0.6, py0, int(W * 0.6))
    return k


# =================================================================================================================
# shiroiya_hill
# =================================================================================================================
def shiroiya_hill(plot):
    W, D = plot.w, plot.d
    H = _clamp(plot.h_max, 10.0, 16.0)
    k = Kit(W, D)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    conc = k.mat("PermeableStone", CONCRETE_HOTEL, 600.0)
    conc2 = k.mat("PermeableStone", _mix(CONCRETE_HOTEL, (150, 146, 140), 0.5), 600.0)
    grass = k.mat("GreenRoof", (124, 172, 70))
    white = k.mat("Plain", (242, 241, 236))
    rail = k.mat("Plain", (244, 243, 238))       # crisp white steel (Metal tinted white renders tan)
    brick = k.mat("PermeableStone", BRICK_RED)
    glass = k.mat("SolarGlass", (140, 160, 166), 400.0)
    lit = k.mat("Lantern", LIT)
    dark = k.mat("Plain", (48, 50, 54))
    accent = k.mat("Plain", _mix(pal[2], (200, 70, 50), 0.5))

    sy0 = D - _clamp(D * 0.3, 6.0, 9.0)        # slab front face
    sy1 = D - 0.5
    # back slab: the old concrete hotel block (precast panels), a grid of small windows
    k.box(conc, 0.5, sy0, 0, W - 0.5, sy1, H - 0.6)
    k.box(conc2, 0.3, sy0 - 0.15, H - 0.6, W - 0.3, sy1 + 0.1, H - 0.3)
    k.solid(0.5, sy0, 0, W - 0.5, sy1, H - 0.6)
    nfl = int((H - 2.0) / 3.0)
    ncol = int((W - 2) / 2.6)
    for f in range(nfl):
        z = 1.0 + f * 3.0
        for c in range(ncol):
            if rng.random() < 0.12:
                continue
            x = 1.6 + c * (W - 3.2) / max(1, ncol - 1)
            s_ = lit if rng.random() < 0.22 else dark
            k.box(conc2, x - 0.65, sy0 - 0.1, z - 0.1, x + 0.65, sy0, z + 1.3)
            k.box(s_, x - 0.52, sy0 - 0.14, z, x + 0.52, sy0 - 0.08, z + 1.2)
    # a glass stair tower in the slab (vertical strip)
    gx = W * rng.uniform(0.2, 0.3) if rng.random() < 0.5 else W * rng.uniform(0.7, 0.8)
    k.box(glass, gx - 1.0, sy0 - 0.2, 0, gx + 1.0, sy0 + 0.1, H - 1.0)
    for z in range(3, int(H - 1), 3):
        k.box(dark, gx - 1.02, sy0 - 0.24, z, gx + 1.02, sy0 - 0.18, z + 0.15)

    # the hill: grassy ellipsoid lobes rising from the street to ~0.7 H and leaning on the slab
    lobes = []
    hx_c = W * rng.uniform(0.42, 0.58)
    peak = H * rng.uniform(0.66, 0.74)
    rx_main = min(W / 2 - 1.0, W * 0.46)
    ry_main = (sy0 - 1.0) / 1.254
    rz_main = peak / 0.7
    lobes.append((hx_c, sy0 - ry_main * 0.3, -0.3 * rz_main, rx_main, ry_main, rz_main))
    for sgn in (-1, 1):
        if True:
            rr = rx_main * rng.uniform(0.45, 0.58)
            lx = _clamp(hx_c + sgn * rx_main * rng.uniform(0.7, 0.9), 0.8 + rr, W - 0.8 - rr)
            ry_ = ry_main * rng.uniform(0.65, 0.8)
            rz_ = rz_main * rng.uniform(0.5, 0.7)
            lobes.append((lx, sy0 - ry_ * 0.3, -0.3 * rz_, rr, ry_, rz_))
    lobes = [(cx, cy, cz, min(rx, cx - 0.6, W - 0.6 - cx), ry, rz) for (cx, cy, cz, rx, ry, rz) in lobes]
    for (cx, cy, cz, rx, ry, rz) in lobes:
        k.ell(grass, cx, cy, cz, rx, ry, rz, 32, 14, hemi=True)
    fy = 1.0
    ex = hx_c + rng.choice((-1, 1)) * rx_main * rng.uniform(0.25, 0.4)
    # lobby: a white-framed open mouth tucked into the foot of the hill, a grass lip over it
    k.box(white, ex - 3.2, fy + 2.7, 0, ex + 3.2, fy + 6.0, 3.6)
    for xe in (ex - 3.2, ex + 2.95):
        k.box(white, xe, fy + 0.2, 0, xe + 0.25, fy + 2.7, 3.6)
    k.box(white, ex - 3.2, fy + 0.2, 3.3, ex + 3.2, fy + 2.7, 3.6)
    k.box(grass, ex - 3.3, fy + 0.1, 3.6, ex + 3.3, fy + 6.0, 3.75)
    k.box(k.mat("Plain", (150, 112, 78)), ex - 2.9, fy + 2.6, 0, ex + 2.9, fy + 2.7, 3.3)     # warm back wall
    k.box(k.mat("Plain", (120, 90, 64)), ex - 2.9, fy + 0.2, 3.25, ex + 2.9, fy + 2.7, 3.3)
    for j in range(3):
        lantern(k, lit, rail, ex - 1.8 + 1.8 * j, fy + 1.4, 3.25, 0.6, 0.3)
    for i in range(7):
        x = ex - 2.9 + 5.8 * i / 6
        k.box(rail, x - 0.05, fy + 0.1, 0, x + 0.05, fy + 0.2, 3.3)
    k.box(brick, ex - 4.0, 0, 0, ex + 4.0, fy + 0.2, 0.05)
    k.solid(ex - 3.2, fy + 2.6, 0, ex + 3.2, fy + 6.0, 3.6)

    def surf(x, y):
        best = 0.0
        for (cx, cy, cz, rx, ry, rz) in lobes:
            u = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if u < 1:
                best = max(best, cz + rz * math.sqrt(1 - u))
        return best

    def house(x, y, w, d, wall, ridge, tower=False):
        z0 = surf(x, y)
        for (ox, oy) in ((-w / 2, -d / 2), (w / 2, -d / 2), (-w / 2, d / 2), (w / 2, d / 2)):
            z0 = min(z0, surf(x + ox, y + oy))
        zb = z0 - 0.4
        ztop = min(H - ridge - 0.1, z0 + wall)
        if ztop - z0 < 2.0:
            return None
        k.box(white, x - w / 2, y - d / 2, zb - 1.0, x + w / 2, y + d / 2, ztop)
        k.gable(white, x - w / 2 - 0.05, y - d / 2 - 0.05, ztop, x + w / 2 + 0.05, y + d / 2 + 0.05, ztop, ridge, along_x=False)
        # board-and-batten lines on the front
        nb = int(w / 0.45)
        for i in range(1, nb):
            bx = x - w / 2 + w * i / nb
            k.box(white, bx - 0.02, y - d / 2 - 0.04, z0, bx + 0.02, y - d / 2, ztop)
        # a deep square window, warm inside
        wz = z0 + (ztop - z0) * 0.45
        ww = min(1.2, w * 0.4)
        k.box(dark, x - ww / 2 - 0.08, y - d / 2 - 0.05, wz - 0.08, x + ww / 2 + 0.08, y - d / 2 - 0.01, wz + ww * 0.75 + 0.08)
        k.box(lit if rng.random() < 0.7 else glass, x - ww / 2, y - d / 2 - 0.07, wz, x + ww / 2, y - d / 2 - 0.03, wz + ww * 0.75)
        # Fujimoto's houses are mostly 'chimney' houses: a tall white stack rising from one end
        if tower or rng.random() < 0.5:
            cw_ = min(0.9, w * 0.35)
            cx_ = x + (w / 2 - cw_ / 2 - 0.1) * rng.choice((-1, 1))
            k.box(white, cx_ - cw_ / 2, y + d / 2 - cw_ - 0.1, ztop, cx_ + cw_ / 2, y + d / 2 - 0.1, min(H, ztop + ridge + rng.uniform(1.0, 2.0)))
        k.solid(x - w / 2, y - d / 2, zb, x + w / 2, y + d / 2, ztop)
        return ztop + ridge

    # zigzag stair from the street up the hill: steps follow the ground, white railings both sides
    sx = _clamp(ex + (5.0 if ex < hx_c else -5.0), 2.0, W - 2.0)
    dirx = 1 if sx < hx_c else -1
    top_y = lobes[0][1] - lobes[0][4] * 0.3
    zig = _clamp(rx_main * 0.35, 2.5, 6.0)
    pts = [(sx, 0.5)]
    nfl = 6
    for i in range(1, nfl + 1):
        y = 0.5 + (top_y - 0.5) * i / nfl
        x = sx + (zig * dirx if i % 2 else 0.0) + (hx_c - sx) * 0.5 * i / nfl
        pts.append((_clamp(x, 1.2, W - 1.2), y))
    stair_pts = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay)
        n = max(2, int(L / 0.45))
        ux, uy = (bx - ax) / L, (by - ay) / L
        px_, py_ = -uy, ux
        yaw = math.degrees(math.atan2(uy, ux))
        for i in range(n):
            x, y = ax + (bx - ax) * (i + 0.5) / n, ay + (by - ay) * (i + 0.5) / n
            stair_pts.append((x, y))
            z = surf(x, y) + 0.1
            k.obox(brick, x, y, z - 0.3, L / n / 2 + 0.03, 0.6, 0.36, 0, yaw, 0)
        m = max(2, int(L / 1.4))
        for sgn in (-1, 1):
            prev = None
            for i in range(m + 1):
                x, y = ax + (bx - ax) * i / m + px_ * 0.66 * sgn, ay + (by - ay) * i / m + py_ * 0.66 * sgn
                z = surf(x, y) + 0.1
                k.pole(rail, (x, y, z - 0.2), (x, y, z + 1.0), 0.025, 4)
                if prev:
                    k.pole(rail, (prev[0], prev[1], prev[2] + 1.0), (x, y, z + 1.0), 0.025, 4)
                    k.pole(rail, (prev[0], prev[1], prev[2] + 0.5), (x, y, z + 0.5), 0.015, 4)
                prev = (x, y, z)

    def near_stair(x, y, r):
        return any((x - sx_) ** 2 + (y - sy_) ** 2 < r * r for (sx_, sy_) in stair_pts)

    # houses: one tall 'chimney' house near the top, the rest small and gabled
    placed = []
    nh = int(_clamp(W / 10, 3, 6))
    tries = 0
    while len(placed) < nh and tries < 60:
        tries += 1
        cx, cy, cz, rx, ry, rz = lobes[0] if (len(placed) < 2 or rng.random() < 0.5) else rng.choice(lobes)
        a = rng.uniform(-math.pi * 0.9, -math.pi * 0.1)       # front half of the lobe
        rr = rng.uniform(0.15, 0.7) if placed else 0.1
        x, y = cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr
        tall = not placed
        w = rng.uniform(1.8, 2.3) if tall else rng.uniform(2.4, 3.4)
        d = w * rng.uniform(1.0, 1.3)
        if x - w / 2 < 1 or x + w / 2 > W - 1 or y - d / 2 < fy + 1 or near_stair(x, y, max(w, d) * 0.75 + 0.9):
            continue
        if abs(x - ex) < 3.6 + w / 2 and y - d / 2 < fy + 6.5:
            continue
        if any(abs(x - px) < (w + pw) / 2 + 1.2 and abs(y - py) < (d + pd) / 2 + 1.2 for (px, py, pw, pd) in placed):
            continue
        wall = rng.uniform(4.5, 6.0) if tall else rng.uniform(2.4, 3.2)
        if house(x, y, w, d, wall, rng.uniform(1.2, 1.8), tall) is not None:
            placed.append((x, y, w, d))

    # skylight 'eyelids' poking out of the hill
    for _ in range(rng.randint(3, 5)):
        cx, cy, cz, rx, ry, rz = rng.choice(lobes)
        a, rr = rng.uniform(-math.pi * 0.85, -math.pi * 0.15), rng.uniform(0.45, 0.8)
        x, y = cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr
        z = surf(x, y)
        k.obox(white, x, y, z, 0.7, 0.5, 0.35, 20, math.degrees(a) + 90, 0)
        k.obox(dark, x, y - 0.3, z + 0.02, 0.6, 0.12, 0.25, 20, math.degrees(a) + 90, 0)
    # planting on the hill: small rounded trees, shrubs, a red maple, flowers in the grass
    for i in range(int(_clamp(W / 2.4, 10, 26))):
        cx, cy, cz, rx, ry, rz = rng.choice(lobes)
        a, rr = rng.uniform(-math.pi, 0.2), rng.uniform(0.2, 0.92)
        x, y = cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr
        if any(abs(x - px) < pw / 2 + 0.8 and abs(y - py) < pd / 2 + 0.8 for (px, py, pw, pd) in placed):
            continue
        if near_stair(x, y, 1.4):
            continue
        z = surf(x, y)
        if rng.random() < 0.5:
            th_ = min(rng.uniform(3.0, 5.5), H + 3.0 - z)
            if th_ > 2.0:
                tree(k, rng, x, y, th_, _clamp(th_ * 0.32, 0.9, 1.6), flowering=rng.random() < 0.35, z=z)
        else:
            shrub(k, rng, x, y, z - 0.1, rng.uniform(0.5, 0.9), 0.6)
            shrub(k, rng, x + rng.uniform(-1, 1), y + rng.uniform(-1, 1), surf(x, y) - 0.1, rng.uniform(0.4, 0.7), 0.7)
    red = _mix((190, 56, 44), pal[2], 0.2)
    x, y = W * rng.uniform(0.6, 0.85), fy + 2.5
    z = surf(x, y)
    k.plant("Trunk", "Bark", BARK, x, y, z, 0.2, 0.2, 1.3)
    k.plant("Blob", "Foliage", red, x, y, z + 1.8, 1.0, 0.9, 0.7)
    for _ in range(int(W * 1.2)):
        cx, cy, cz, rx, ry, rz = rng.choice(lobes)
        a, rr = rng.uniform(-math.pi, 0), rng.uniform(0.1, 0.95)
        x, y = cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr
        k.plant("Blob", "Foliage", rng.choice(FLOWER), x, y, surf(x, y), 0.1, 0.1, 0.07, shadow=False)
    # the old slab greened: planters along the roof edge with creeper hanging down the concrete
    for _ in range(int(W / 6)):
        x = rng.uniform(1.0, W - 3.0)
        vines(k, rng, x, x + rng.uniform(1.5, 3.5), sy0 - 0.2, H - 0.35, 1.0, 4.5, 0.45, 180)
    for i in range(int(W / 3)):
        shrub(k, rng, 1.0 + i * 3.0 + rng.uniform(0, 1.5), sy0 + 0.6, H - 0.3, rng.uniform(0.5, 0.9), 0.4)
    # shrubs and ferns along the foot of the hill
    for _ in range(int(W / 2.2)):
        x = rng.uniform(0.8, W - 0.8)
        if abs(x - ex) < 4.2 or abs(x - sx) < 1.5:
            continue
        shrub(k, rng, x, rng.uniform(0.4, 1.4), 0, rng.uniform(0.4, 0.8), 0.5)
    # a slender red post sculpture (whimsy, after the hotel's red pole)
    k.pole(accent, (ex + 3.0, 1.0, 0), (ex + 3.0, 1.0, 5.0), 0.05, 6)
    return k


# =================================================================================================================
# coconut_shophouse
# =================================================================================================================
def coconut_shophouse(plot):
    W, D = plot.w, plot.d
    H = _clamp(plot.h_max, 8.0, 12.0)
    OY = 1.5                                   # the deep roofs overhang the five-foot way by up to 1.5 m
    k = _ShiftKit(W, D, OY)
    D = D - OY
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    timber = k.mat("Timber", TEAK)
    timber_d = k.mat("Timber", (112, 74, 48))
    timber_l = timber
    tile = k.mat("RammedEarth", (168, 84, 62))
    conc = k.mat("PermeableStone", (200, 194, 182))
    floor5 = k.mat("PermeableStone", (196, 164, 140))
    lit = k.mat("Lantern", LIT)
    lan = lit
    dark = k.mat("Plain", (70, 52, 40))        # dim warm interiors / reveals (glass is opaque, so rooms show as gaps)
    inside = dark
    glass = dark
    moss = k.mat("Moss", MOSS)
    leaf = k.mat("Foliage", (70, 120, 50))
    stem = leaf
    shutters = [k.mat("Timber", _mix(c, pal[2], 0.25)) for c in rng.sample([(60, 110, 96), (70, 96, 130), (140, 70, 56), (96, 120, 70)], 2)]
    green_roof = k.mat("GreenRoof", GRASS)

    n = int(_clamp(round(W / 6.5), 2, 5))
    wts = [rng.uniform(0.85, 1.15) for _ in range(n)]
    xs = [0.0]
    for wt in wts:
        xs.append(xs[-1] + W * wt / sum(wts))
    xs[-1] = W
    nf = 3 if H >= 11.0 else 2
    g = 3.6                                    # ground floor
    fh = min(3.4, (H - 1.45 - g) / (nf - 1))        # leaves >= 1.45 m for any roof
    top = g + (nf - 1) * fh                    # top of the facade
    fy = 2.2                                   # five-foot-way depth: shopfront line
    by = D - _clamp(D * 0.18, 2.5, 4.0)        # back face

    colours = list(PASTELS)
    rng.shuffle(colours)
    colours = [_mix(colours[0], pal[0], 0.35), _mix(pal[1], (230, 220, 200), 0.4)] + colours[1:]
    roofs = ["gable", "deep", "flat", "gable", "deep"]
    rng.shuffle(roofs)
    if "deep" not in roofs[:n]:
        roofs[rng.randrange(n)] = "deep"

    # five-foot way floor, continuous
    k.box(floor5, 0, 0, 0, W, fy, 0.15)
    for u in range(n):
        ux0, ux1 = xs[u] + 0.0, xs[u + 1]
        uw = ux1 - ux0
        # each house its own height: some keep one storey less with taller rooms (a stepped roofline)
        nfu, fhu = nf, fh
        if nf == 3 and rng.random() < 0.35:
            nfu, fhu = 2, fh * 1.15
        topu = g + (nfu - 1) * fhu
        balcony = rng.random() < 0.4
        wood = rng.random() < 0.4
        wall = k.mat("Timber", _mix(TEAK, colours[u], 0.25)) if wood else k.mat("RammedEarth", colours[u], 1200.0)
        trim = timber_d if not wood else k.mat("RammedEarth", (232, 226, 210))
        shut = shutters[u % 2]
        pil = 0.35
        # party-wall piers (shared between neighbours): a pier at the street, an opening through the five-foot way
        for (pa, pb) in ([(ux0, ux0 + pil)] + ([(ux1 - pil, ux1)] if u == n - 1 else [])):
            k.box(wall, pa, 0.05, 0, pb, 0.55, topu)
            k.box(wall, pa, 0.55, g - 0.7, pb, fy, topu)
            k.box(wall, pa, fy, 0, pb, by, topu)
            k.box(trim, pa - 0.03, 0.02, 0.0, pb + 0.03, 0.58, 0.35)
        ix0, ix1 = ux0 + pil, ux1 - (pil if u == n - 1 else 0)
        # ground floor: recessed shopfront (folding timber doors, glass) with a warm dim shop inside
        k.box(wall, ix0, fy + 2.4, 0, ix1, by, g)
        k.box(inside, ix0, fy, 0.15, ix1, fy + 2.4, 0.16)
        k.box(inside, ix0, fy + 0.1, g - 0.35, ix1, fy + 2.4, g - 0.3)
        k.box(timber_l, ix0 + 0.6, fy + 1.2, 0.15, ix1 - 0.6, fy + 1.7, 1.1)            # counter
        for j in range(2):
            lx_ = ix0 + (ix1 - ix0) * (j + 1) / 3
            lantern(k, lit, timber_d, lx_, fy + 1.0, g - 0.35, 0.5, 0.3)
        for zz in (1.2, 1.75, 2.3):                                                       # lit shelves of jars
            k.box(lit, ix0 + 0.5, fy + 2.3, zz, ix1 - 0.5, fy + 2.4, zz + 0.22)
            k.box(timber_d, ix0 + 0.45, fy + 2.1, zz - 0.05, ix1 - 0.45, fy + 2.4, zz)
        nd = max(3, int((ix1 - ix0) / 0.9))
        open_ = rng.random() < 0.6
        for i in range(nd + 1):
            x = ix0 + 0.1 + (ix1 - ix0 - 0.2) * i / nd
            k.box(timber_d, x - 0.05, fy - 0.08, 0.15, x + 0.05, fy - 0.02, g - 0.6)
        if not open_:
            # half the folding doors closed: solid timber leaves with a panel line
            for i in range(nd // 2):
                x0_ = ix0 + 0.1 + (ix1 - ix0 - 0.2) * i / nd
                x1_ = ix0 + 0.1 + (ix1 - ix0 - 0.2) * (i + 1) / nd
                k.box(timber, x0_ + 0.05, fy - 0.07, 0.15, x1_ - 0.05, fy - 0.03, g - 0.6)
        k.box(timber_d, ix0 + 0.1, fy - 0.1, g - 0.65, ix1 - 0.1, fy - 0.02, g - 0.55)
        # transom of glass, sign board in a palette colour
        sign = shutters[(u + 1) % 2]
        k.box(sign, ix0 + 0.4, fy - 0.12, g - 0.5, ix1 - 0.4, fy - 0.04, g - 0.1)
        # upper floors project over the five-foot way, carried on the piers + a beam
        k.box(trim, ix0, 0.0, g - 0.05, ix1, fy, g + 0.25)
        for f in range(1, nfu):
            z0, z1 = g + (f - 1) * fhu + 0.25, g + f * fhu
            k.box(wall, ix0, 0.1, z0, ix1, by, z1)
            nw = 2 if uw < 6.0 else 3
            seg = (ix1 - ix0) / nw
            ww = min(1.25, seg * 0.6)
            wh = min(2.1, (z1 - z0) - 0.8)
            wz = z0 + 0.55
            for i in range(nw):
                cx = ix0 + seg * (i + 0.5)
                # dark reveal + glass/light
                k.box(dark, cx - ww / 2, 0.06, wz, cx + ww / 2, 0.1, wz + wh)
                k.box(trim, cx - ww / 2 - 0.08, 0.02, wz - 0.12, cx + ww / 2 + 0.08, 0.1, wz)        # sill
                k.box(trim, cx - ww / 2 - 0.08, 0.02, wz + wh, cx + ww / 2 + 0.08, 0.1, wz + wh + 0.14)
                state = rng.random()
                if state < 0.45:
                    # closed louvred shutters: two leaves with horizontal slats
                    for (sx0, sx1) in ((cx - ww / 2, cx - 0.01), (cx + 0.01, cx + ww / 2)):
                        k.box(shut, sx0, 0.0, wz, sx0 + 0.06, 0.06, wz + wh)
                        k.box(shut, sx1 - 0.06, 0.0, wz, sx1, 0.06, wz + wh)
                        ns = int(wh / 0.17)
                        for j in range(ns):
                            zz = wz + 0.08 + (wh - 0.16) * j / max(1, ns - 1)
                            k.obox(shut, (sx0 + sx1) / 2, 0.03, zz, (sx1 - sx0) / 2 - 0.03, 0.04, 0.012, 0, 0, -30)
                else:
                    # open: warm window, shutter leaves folded flat against the wall either side
                    k.box(lit if rng.random() < 0.6 else glass, cx - ww / 2 + 0.05, 0.04, wz + 0.05, cx + ww / 2 - 0.05, 0.08, wz + wh - 0.05)
                    k.box(trim, cx - 0.03, 0.02, wz, cx + 0.03, 0.06, wz + wh)
                    for sgn in (-1, 1):
                        sx = cx + sgn * (ww / 2 + ww / 4 + 0.02)
                        k.box(shut, sx - ww / 4, 0.0, wz, sx + ww / 4, 0.05, wz + wh)
                        ns = int(wh / 0.25)
                        for j in range(ns):
                            zz = wz + 0.12 + (wh - 0.24) * j / max(1, ns - 1)
                            k.box(timber_d, sx - ww / 4 + 0.05, -0.02, zz - 0.012, sx + ww / 4 - 0.05, 0.0, zz + 0.012)
                # a window box with flowers + a short spill
                if rng.random() < 0.55:
                    k.box(timber_l, cx - ww / 2, -0.35, wz - 0.4, cx + ww / 2, 0.0, wz - 0.12)
                    for j in range(2):
                        shrub(k, rng, cx - ww / 4 + j * ww / 2, -0.18, wz - 0.15, 0.28, 0.8)
                    vines(k, rng, cx - ww / 2, cx + ww / 2, -0.35, wz - 0.3, 0.4, 1.0, 0.5, 180, cushion=False)
            if balcony and f == 1:
                # a timber balcony across the house, posts, a rail and a planter spilling over
                k.box(timber_l, ix0 + 0.05, -0.9, z0 - 0.15, ix1 - 0.05, 0.1, z0)
                npst = max(2, int((ix1 - ix0) / 1.0))
                for j in range(npst + 1):
                    px = ix0 + 0.1 + (ix1 - ix0 - 0.2) * j / npst
                    k.box(timber_d, px - 0.04, -0.88, z0, px + 0.04, -0.8, z0 + 1.0)
                k.box(timber_d, ix0 + 0.05, -0.92, z0 + 1.0, ix1 - 0.05, -0.78, z0 + 1.06)
                k.box(timber_d, ix0 + 0.05, -0.88, z0 + 0.45, ix1 - 0.05, -0.84, z0 + 0.5)
                for j in range(int((ix1 - ix0) / 1.2)):
                    shrub(k, rng, ix0 + 0.6 + j * 1.2, -0.7, z0 + 1.0, 0.35, 0.7)
                vines(k, rng, ix0, ix1, -0.9, z0 - 0.1, 0.5, 1.8, 0.5, 180, cushion=False)
            # floor band + moss staining
            k.box(trim, ix0, -0.05, z1 - 0.15, ix1, 0.1, z1 + 0.05)
            k.box(moss, ix0, 0.07, z0, ix1, 0.11, z0 + 0.25)
        # roof
        kind = roofs[u]
        if kind == "gable":
            # pitched clay roof falling to the street, ridge along x, timber eaves
            ridge = _clamp(H - topu - 0.05, 0.8, 2.4)
            yr = (0.0 + by) / 2
            slab(k, tile, ix0 - 0.05, ix1 + 0.05, -0.8, topu - 0.1, yr + 0.05, topu + ridge, 0.18)
            slab(k, tile, ix0 - 0.05, ix1 + 0.05, yr - 0.05, topu + ridge, by + 0.6, topu - 0.1, 0.18)
            k.box(wall, ix0, 0.1, topu, ix1, by, topu + 0.25)
            # tile courses: thin ribs across the front slope
            for j in range(1, 6):
                f_ = j / 6
                yy, zz = -0.8 + (yr + 0.8) * f_, topu - 0.1 + (ridge + 0.1) * f_
                k.box(timber_d, ix0, yy - 0.03, zz + 0.0, ix1, yy + 0.03, zz + 0.05)
            k.box(timber_d, ix0 - 0.05, -0.85, topu - 0.2, ix1 + 0.05, -0.75, topu + 0.05)
            # gable-end firewall (stepped) on the shared pier
            k.box(wall, ux0, 0.05, topu, ux0 + pil, by, topu + ridge * 0.6)
            vines(k, rng, ix0, ix1, -0.82, topu, 0.6, 2.4, 0.55, 180)
            roof_top = topu + ridge
        elif kind == "deep":
            # Coconut Club: thick flat roof slab with a deep overhang, planted on topu, vines pouring off the edge
            k.box(conc, ix0 - 0.05, -1.4, topu, ix1 + 0.05, by + 0.4, topu + 0.55)
            k.box(green_roof, ix0, -1.3, topu + 0.55, ix1, by + 0.3, topu + 0.7)
            k.box(timber_l, ix0 - 0.06, -1.45, topu + 0.1, ix1 + 0.06, -1.38, topu + 0.45)
            for i in range(int((ix1 - ix0) / 1.2)):
                shrub(k, rng, ix0 + 0.6 + i * 1.2 + rng.uniform(-0.2, 0.2), -0.9, topu + 0.65, rng.uniform(0.45, 0.7), 0.4)
            vines(k, rng, ix0, ix1, -1.42, topu + 0.5, 1.2, min(topu - 1.5, 5.5), 0.45, 180)
            roof_top = topu + 0.7
        else:
            # flat with a stepped parapet front and a roof garden behind
            ph = _clamp(H - topu - 0.5, 0.5, 1.0)
            k.box(wall, ix0, 0.0, topu, ix1, 0.35, topu + ph)
            k.box(wall, (ix0 + ix1) / 2 - 0.9, 0.0, topu + ph, (ix0 + ix1) / 2 + 0.9, 0.35, topu + ph + 0.5)
            k.box(trim, ix0 - 0.05, -0.08, topu + ph - 0.05, ix1 + 0.05, 0.4, topu + ph + 0.05)
            k.box(wall, ix0, 0.35, topu - 0.1, ix1, by, topu + 0.1)
            for i in range(int((ix1 - ix0) / 1.1)):
                shrub(k, rng, ix0 + 0.5 + i * 1.1, rng.uniform(0.9, by * 0.5), topu + 0.1, rng.uniform(0.45, 0.8), 0.6)
            vines(k, rng, ix0, ix1, -0.06, topu + ph, 0.5, 2.2, 0.6, 180)
            roof_top = topu + ph + 0.5
        # back: plain wall face with two windows and a little lean-to
        k.box(dark, ix0 + 0.6, by + 0.01, g + 0.6, ix0 + 1.6, by + 0.05, g + 2.2)
        k.box(lit, ix1 - 1.6, by + 0.01, 1.0, ix1 - 0.6, by + 0.05, 2.6)
        k.solid(ux0, fy, 0, ux1, by, topu)
        # five-foot way life: lanterns, potted palms, a table and chairs out front
        lantern(k, lan, timber_d, (ix0 + ix1) / 2, fy * 0.45, g - 0.05, 0.4, 0.26)
        if rng.random() < 0.6:
            tx = rng.uniform(ix0 + 0.8, ix1 - 0.8)
            k.cyl(timber_l, tx, 1.0, 0.15, 0.35, 0.35, 0.06, 10)
            k.cyl(timber_d, tx, 1.0, 0.15, 0.04, 0.04, 0.7, 6)
            k.box(timber_d, tx - 0.35, 0.95, 0.85, tx + 0.35, 1.05, 0.87)  # (placeholder tray)
            for sgn in (-1, 1):
                k.box(timber_l, tx + sgn * 0.6 - 0.2, 0.8, 0.15, tx + sgn * 0.6 + 0.2, 1.2, 0.6)
        else:
            k.cyl(tile, ix0 + 0.5, 0.6, 0.15, 0.3, 0.36, 0.55, 10)
            shrub(k, rng, ix0 + 0.5, 0.6, 0.65, 0.45, 0.7)
    # the end piers: moss creeping up from the ground
    k.box(moss, -0.02, 0.03, 0, 0.02, by, 1.2)
    k.box(moss, W - 0.02, 0.03, 0, W + 0.0, by, 1.2)
    # banana and palms at the base, out the back yard
    for x in (0.4, W - 0.4):
        if rng.random() < 0.8:
            banana(k, rng, leaf, stem, x, rng.uniform(fy + 0.5, by - 0.5) * 0 + by + 1.2, rng.uniform(3.0, 4.5))
    for _ in range(int(W / 4)):
        banana(k, rng, leaf, stem, rng.uniform(1, W - 1), rng.uniform(by + 0.8, D - 0.6), rng.uniform(2.5, 4.0))
    bed(k, rng, 0.3, by + 0.4, W - 0.3, D - 0.2, 0.3, 0, 0.4, 0.9, 0.4)
    return k


# =================================================================================================================
# stilt_house
# =================================================================================================================
def stilt_house(plot):
    W, D = plot.w, plot.d
    H = _clamp(plot.h_max, 6.0, 9.0)
    k = Kit(W, D)
    rng = plot.rng
    pal = [tuple(c) for c in plot.palette]
    post = k.mat("Timber", (126, 88, 56))
    deck = k.mat("Timber", (164, 118, 76))
    board = k.mat("Timber", _mix((150, 104, 66), pal[0], 0.15))
    trim = k.mat("Timber", (96, 64, 42))
    roof_s = k.mat("Timber", (92, 70, 54)) if rng.random() < 0.5 else k.mat("GreenRoof", GRASS)
    shut = k.mat("Timber", _mix(pal[2], (60, 110, 100), 0.4))
    lit = k.mat("Lantern", LIT)
    glass = k.mat("SolarGlass", (150, 166, 168), 400.0)
    water = k.mat("Water", (58, 88, 92))
    moss = k.mat("Moss", MOSS)
    footing = k.mat("PermeableStone", (150, 144, 132))
    tank = k.mat("GreenRoof", (90, 130, 60))
    rail_h = 1.0

    def pod(dx0, dy0, dx1, dy1, zf, cw, cd, cab_side, gaps):
        """Stilts + deck + cabin. gaps: list of ('front'|'left'|'right'|'back', centre) railing openings.
        Returns the cabin box."""
        nx = max(2, int((dx1 - dx0) / 2.6) + 1)
        ny = max(2, int((dy1 - dy0) / 2.6) + 1)
        xs = [dx0 + 0.2 + (dx1 - dx0 - 0.4) * i / (nx - 1) for i in range(nx)]
        ys = [dy0 + 0.2 + (dy1 - dy0 - 0.4) * j / (ny - 1) for j in range(ny)]
        for x in xs:
            for y in ys:
                lean = rng.uniform(-0.06, 0.06)
                k.pole(post, (x + lean, y, -0.2), (x, y, zf), 0.13, 8)
                k.cyl(footing, x + lean, y, 0, 0.24, 0.2, 0.25, 8)
        for j in (0, ny - 1):
            for i in range(nx - 1):
                if (i + j) % 2 == 0:
                    k.beam(post, (xs[i], ys[j], 0.3), (xs[i + 1], ys[j], zf - 0.3), 0.08, 0.08)
        for i in (0, nx - 1):
            for j in range(ny - 1):
                k.beam(post, (xs[i], ys[j], zf - 0.3), (xs[i], ys[j + 1], 0.3), 0.08, 0.08)
        for y in ys:
            k.box(trim, dx0, y - 0.1, zf - 0.32, dx1, y + 0.1, zf - 0.1)
        k.box(deck, dx0 - 0.1, dy0 - 0.1, zf - 0.1, dx1 + 0.1, dy1 + 0.1, zf + 0.05)
        nb = int((dx1 - dx0) / 0.5)
        for i in range(nb + 1):
            x = dx0 + (dx1 - dx0) * i / nb
            k.box(trim, x - 0.012, dy0 - 0.1, zf + 0.05, x + 0.012, dy1 + 0.1, zf + 0.055)
        k.solid(dx0, dy0, zf - 0.35, dx1, dy1, zf + 0.05)
        # cabin
        cx0 = dx0 + 0.6 if cab_side < 0 else (dx1 - 0.6 - cw if cab_side > 0 else (dx0 + dx1 - cw) / 2)
        cx1 = cx0 + cw
        cy1 = dy1 - 0.5
        cy0 = cy1 - cd
        wall = 2.6
        ridge = max(1.0, min(H - zf - wall - 0.1, cw * 0.32))
        k.box(board, cx0, cy0, zf, cx1, cy1, zf + wall)
        for i in range(1, int(cw / 0.35)):
            x = cx0 + 0.35 * i
            k.box(trim, x - 0.015, cy0 - 0.03, zf, x + 0.015, cy0, zf + wall)
        door_x = (cx0 + cx1) / 2 + rng.uniform(-0.3, 0.3) * max(0.0, cw - 3)
        k.box(trim, door_x - 0.55, cy0 - 0.06, zf, door_x + 0.55, cy0 - 0.02, zf + 2.15)
        k.box(lit, door_x - 0.45, cy0 - 0.07, zf, door_x + 0.45, cy0 - 0.03, zf + 2.05)
        for wx in (cx0 + 0.9, cx1 - 0.9):
            if abs(wx - door_x) < 1.5:
                continue
            k.box(trim, wx - 0.6, cy0 - 0.08, zf + 0.85, wx + 0.6, cy0 - 0.02, zf + 2.1)
            k.box(lit if rng.random() < 0.7 else glass, wx - 0.5, cy0 - 0.09, zf + 0.95, wx + 0.5, cy0 - 0.05, zf + 2.0)
            for sgn in (-1, 1):
                k.box(shut, wx + sgn * 0.85 - 0.25, cy0 - 0.09, zf + 0.9, wx + sgn * 0.85 + 0.25, cy0 - 0.04, zf + 2.05)
            k.box(deck, wx - 0.65, cy0 - 0.4, zf + 0.6, wx + 0.65, cy0 - 0.05, zf + 0.82)
            for sgn in (-1, 1):
                shrub(k, rng, wx + sgn * 0.3, cy0 - 0.22, zf + 0.8, 0.28, 0.9)
        for xe, sgn in ((cx0, -1), (cx1, 1)):
            k.box(lit, xe + sgn * 0.02, (cy0 + cy1) / 2 - 0.45, zf + 1.0, xe + sgn * 0.06, (cy0 + cy1) / 2 + 0.45, zf + 1.9)
        k.gable(roof_s, cx0 - 0.6, cy0 - 0.8, zf + wall, cx1 + 0.6, cy1 + 0.6, zf + wall, ridge, True)
        k.box(trim, cx0 - 0.65, cy0 - 0.85, zf + wall - 0.12, cx1 + 0.65, cy0 - 0.75, zf + wall + 0.02)
        k.box(trim, cx0, cy0, zf + wall - 0.05, cx1, cy1, zf + wall)
        k.box(moss, cx0 - 0.6, cy0 - 0.8, zf + wall, cx1 + 0.6, cy0 - 0.45, zf + wall + 0.06)
        vines(k, rng, cx0 - 0.6, cx1 + 0.6, cy0 - 0.8, zf + wall, 0.3, 1.0, 0.8, 180)
        for x in (cx0 + 0.3, cx1 - 0.3):
            lantern(k, lit, trim, x, cy0 - 0.55, zf + wall - 0.1, 0.35, 0.24)
        k.solid(cx0, cy0, zf, cx1, cy1, zf + wall)
        # railing on all four edges, with openings
        edges = {"front": ((dx0, dy0), (dx1, dy0)), "back": ((dx0, dy1), (dx1, dy1)),
                 "left": ((dx0, dy0), (dx0, dy1)), "right": ((dx1, dy0), (dx1, dy1))}
        for name, (pa, pb) in edges.items():
            alongx = pa[1] == pb[1]
            u0, u1 = (pa[0], pb[0]) if alongx else (pa[1], pb[1])
            cuts = sorted(c for (e, c) in gaps if e == name)
            spans, cur = [], u0
            for c in cuts:
                spans.append((cur, c - 0.6))
                cur = c + 0.6
            spans.append((cur, u1))
            for (s0, s1) in spans:
                if s1 - s0 < 0.2:
                    continue
                m = max(1, int((s1 - s0) / 1.2))
                for i in range(m + 1):
                    u = s0 + (s1 - s0) * i / m
                    x, y = (u, pa[1]) if alongx else (pa[0], u)
                    k.box(post, x - 0.05, y - 0.05, zf, x + 0.05, y + 0.05, zf + rail_h)
                if alongx:
                    k.box(deck, s0, pa[1] - 0.06, zf + rail_h, s1, pa[1] + 0.06, zf + rail_h + 0.06)
                    k.box(trim, s0, pa[1] - 0.03, zf + 0.45, s1, pa[1] + 0.03, zf + 0.5)
                else:
                    k.box(deck, pa[0] - 0.06, s0, zf + rail_h, pa[0] + 0.06, s1, zf + rail_h + 0.06)
                    k.box(trim, pa[0] - 0.03, s0, zf + 0.45, pa[0] + 0.03, s1, zf + 0.5)
        # planters on the front rail + creeper off the deck edge
        for i in range(int((dx1 - dx0) / 2.5)):
            x = dx0 + 1.2 + i * 2.5
            if any(e == "front" and abs(x - c) < 1.0 for (e, c) in gaps):
                continue
            shrub(k, rng, x, dy0, zf + rail_h + 0.05, 0.35, 0.8)
        vines(k, rng, dx0, dx1, dy0 - 0.12, zf - 0.1, 0.4, 1.4, 0.9, 180, cushion=False)
        return cx0, cy0, cx1, cy1, zf + wall

    zf = _clamp(H * 0.36, 2.4, 3.2)
    pair = W >= 15.5 and rng.random() < 0.6
    dy0, dy1 = _clamp(D * 0.2, 2.2, 3.5), D - 1.0
    if pair:
        # Isono: two pods at different heights joined by a little stepped bridge
        split = W * rng.uniform(0.56, 0.62)
        mx0, mx1 = 1.0, split - 0.6
        px0, px1 = split + 1.0, W - 1.0
        pdy0 = dy0 + (dy1 - dy0) * 0.35
        zf2 = min(zf + 1.2, H - 2.6 - 1.2)
        st_x = mx0 + 0.9
        by_ = (pdy0 + dy1) / 2
        pod(mx0, dy0, mx1, dy1, zf, _clamp((mx1 - mx0) * 0.7, 4.5, 7.5), _clamp((dy1 - dy0) * 0.6, 4.0, 6.5), 1,
            [("front", st_x), ("right", by_)])
        pod(px0, pdy0, px1, dy1, zf2, _clamp((px1 - px0) - 1.2, 3.0, 4.5), _clamp((dy1 - pdy0) - 1.2, 3.0, 4.2), 0,
            [("left", by_)])
        nst = max(3, int((zf2 - zf) / 0.2))
        for i in range(nst):
            x0_ = mx1 + (px0 - mx1) * i / nst
            x1_ = mx1 + (px0 - mx1) * (i + 1) / nst
            z = zf + (zf2 - zf) * (i + 1) / nst
            k.box(deck, x0_ - 0.02, by_ - 0.5, z - 0.08, x1_ + 0.02, by_ + 0.5, z + 0.02)
        for sgn in (-1, 1):
            k.pole(post, (mx1, by_ + sgn * 0.55, zf + rail_h), (px0, by_ + sgn * 0.55, zf2 + rail_h), 0.03, 4)
            k.pole(post, ((mx1 + px0) / 2, by_ + sgn * 0.55, -0.1), ((mx1 + px0) / 2, by_ + sgn * 0.55, (zf + zf2) / 2), 0.08, 6)
        main_x1 = mx1
    else:
        dx0, dx1 = 1.0, W - 1.0
        cw = _clamp((dx1 - dx0) * 0.55, 5.0, 9.0)
        cd = _clamp((dy1 - dy0) * 0.6, 4.0, 7.0)
        side_ = rng.choice((-1, 1))
        st_x = dx0 + 0.9 if side_ > 0 else dx1 - 0.9
        pod(dx0, dy0, dx1, dy1, zf, cw, cd, side_, [("front", st_x)])
        main_x1 = dx1
        # Isono's green cylinder: a planted water tank beside the cabin
        tx = dx0 + 1.4 if side_ > 0 else dx1 - 1.4
        ty = (dy0 + dy1) / 2
        k.cyl(tank, tx, ty, zf + 0.05, 0.85, 0.85, 2.0, 14)
        k.cyl(k.mat("Metal", (110, 130, 100)), tx, ty, zf + 2.05, 0.9, 0.9, 0.1, 14)
        for _ in range(3):
            k.plant("Puff", "Foliage", rng.choice(LEAF), tx + rng.uniform(-0.3, 0.3), ty + rng.uniform(-0.3, 0.3), zf + 2.1,
                    0.55, 0.55, 0.45)
        # a ladder up from the deck to a lookout perch with a little roof
        if H - zf - 2.6 > 1.4:
            lx, ly = (dx1 - 1.0, dy1 - 1.0) if side_ < 0 else (dx0 + 1.0, dy1 - 1.0)
            lx = tx
            ly = dy1 - 1.0
            lz1 = min(H - 1.8, zf + 2.9)
            k.box(deck, lx - 0.8, ly - 0.8, lz1 - 0.08, lx + 0.8, ly + 0.8, lz1 + 0.04)
            for sx in (-0.75, 0.75):
                for sy in (-0.75, 0.75):
                    k.pole(post, (lx + sx, ly + sy, zf), (lx + sx, ly + sy, lz1 + 1.1), 0.05, 6)
            k.gable(roof_s, lx - 0.95, ly - 0.95, lz1 + 1.1, lx + 0.95, ly + 0.95, lz1 + 1.1, 0.6, True)
            for sgn in (-1, 1):
                k.pole(post, (lx + sgn * 0.22, ly - 0.85, zf), (lx + sgn * 0.22, ly - 0.85, lz1 + 0.9), 0.035, 5)
            for i in range(int((lz1 - zf) / 0.3)):
                z = zf + 0.3 + i * 0.3
                k.pole(post, (lx - 0.22, ly - 0.85, z), (lx + 0.22, ly - 0.85, z), 0.02, 4)

    # stair down to the ground: a landing at the railing gap, then a flight along the front of the deck
    sdir = 1 if st_x < W / 2 else -1
    sy0, sy1 = dy0 - 1.15, dy0 - 0.1
    k.box(deck, st_x - 0.6, sy0, zf - 0.1, st_x + 0.6, sy1, zf + 0.05)
    k.pole(post, (st_x - 0.55 * sdir, sy0 + 0.05, -0.2), (st_x - 0.55 * sdir, sy0 + 0.05, zf + rail_h), 0.07, 6)
    steps = int(zf / 0.19)
    run = 0.27
    xa = st_x + 0.6 * sdir
    for i in range(steps):
        z = zf - (i + 1) * zf / steps
        x = xa + i * run * sdir
        k.box(deck, min(x, x + run * sdir) - 0.01, sy0, z - 0.04, max(x, x + run * sdir) + 0.01, sy1, z + 0.02)
    xb = xa + steps * run * sdir
    for yy in (sy0 - 0.03, sy1 + 0.03):
        k.beam(post, (xa, yy, zf - 0.05), (xb, yy, -0.05), 0.06, 0.25)
    k.pole(post, (xa, sy0 - 0.05, zf + rail_h), (xb - 0.2 * sdir, sy0 - 0.05, rail_h), 0.03, 4)
    k.pole(post, (xb - 0.2 * sdir, sy0 - 0.05, 0), (xb - 0.2 * sdir, sy0 - 0.05, rail_h), 0.04, 4)
    k.box(deck, st_x - 0.6, sy0 - 0.08, zf + rail_h, st_x + 0.6, sy0 - 0.02, zf + rail_h + 0.05)

    # ground: a mossy meadow bed, a fern-and-flower understorey, a small pond with lily pads and reeds, stepping stones
    k.box(k.mat("GreenRoof", (96, 132, 60)), 0.3, 0.3, 0, W - 0.3, D - 0.3, 0.04)
    pond = rng.random() < 0.6
    if pond:
        px, py = _clamp(W / 2 + rng.uniform(-2, 2), 3.0, W - 3.0), (dy0 + dy1) / 2
        k.cyl(water, px, py, -0.05, 2.2, 2.2, 0.08, 18)
        for _ in range(5):
            k.plant("Disc", "Foliage", (80, 124, 58), px + rng.uniform(-1.5, 1.5), py + rng.uniform(-1.5, 1.5), 0.04,
                    0.6, 0.6, 1, rng.uniform(0, 360), shadow=False)
        for _ in range(14):
            a = rng.uniform(0, 6.28)
            k.plant("Reed", "Foliage", (110, 140, 70), px + math.cos(a) * 2.2, py + math.sin(a) * 2.2, 0,
                    1.4, 1.4, rng.uniform(0.8, 1.5), rng.uniform(0, 360), shadow=False)
    ferns = ((48, 88, 44), LEAF[0], LEAF[3], (66, 110, 52))
    for _ in range(int(_clamp(W * D / 3.2, 40, 90))):
        x, y = rng.uniform(0.3, W - 0.3), rng.uniform(0.3, D - 0.3)
        if pond and math.hypot(x - px, y - py) < 2.4:
            continue
        if sy0 - 0.4 < y < dy0 and min(st_x, xb) - 0.5 < x < max(st_x, xb) + 0.5:
            continue
        r = rng.uniform(0.35, 0.85) if y < dy0 + 0.5 or y > dy1 - 0.3 else rng.uniform(0.3, 0.6)
        shrub(k, rng, x, y, 0, r, 0.45, leaf=rng.choice(ferns))
    for i in range(4):
        k.plant("Stone", "PermeableStone", (170, 164, 150), xb + (0.5 + i * 0.7) * sdir, sy0 + 0.5 + rng.uniform(-0.2, 0.2), 0,
                0.35, 0.3, 0.08, rng.uniform(0, 360))
    flowers_in_grass(k, rng, 0.3, 0.3, W - 0.3, D - 0.3, int(W * D / 4))
    # a big old tree at a back corner, crown over the roof
    th_ = H + rng.uniform(1.0, 3.0)
    cr_ = _clamp(th_ * 0.34, 2.4, 3.6)
    # the trunk stands just behind the deck at a back corner, the crown leans over the roof
    tree(k, rng, W - 1.6 if sdir > 0 else 1.6, D - 0.45, th_, cr_, flowering=rng.random() < 0.4)
    return k


KINDS = {
    "bamboo_hall": bamboo_hall,
    "corbero_house": corbero_house,
    "shiroiya_hill": shiroiya_hill,
    "coconut_shophouse": coconut_shophouse,
    "stilt_house": stilt_house,
}

SIZES = {
    "bamboo_hall": {"w": (24, 50), "d": (16, 30), "h": (8, 14), "floors": (1, 1), "use": "hall"},
    "corbero_house": {"w": (20, 40), "d": (16, 30), "h": (6, 12), "floors": (1, 3), "use": "homes"},
    "shiroiya_hill": {"w": (30, 60), "d": (20, 34), "h": (10, 16), "floors": (3, 5), "use": "hotel"},
    "coconut_shophouse": {"w": (12, 40), "d": (14, 22), "h": (8, 12), "floors": (2, 3), "use": "shops+homes"},
    "stilt_house": {"w": (12, 20), "d": (10, 16), "h": (6, 9), "floors": (1, 1), "use": "homes"},
}
