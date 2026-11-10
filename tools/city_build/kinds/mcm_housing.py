"""Mid-century modern housing, re-imagined for a lush solarpunk village: the dense types that carry most homes.

    unite_habitation   Le Corbusier, Unite d'Habitation, Marseille 1952
    habitat67          Moshe Safdie, Habitat 67, Montreal 1967
    lever_slab         SOM (Gordon Bunshaft), Lever House, New York 1952 (as a housing / studio slab)
    barbican_terrace   Chamberlin, Powell and Bon, Barbican Estate terraces, London 1965-76

Local frame (kit.py): x along the street 0..w, y away from it 0..d (front at y = 0), z up, metres.
Every kind stretches its bays / modules to the plot (never scales), stays under plot.h_max and is deterministic
from plot.seed. Budgets: < ~4000 ops, < ~600 plant instances, ~12 material slots.
"""
import colorsys
import math

from .kit import Kit, LEAF, FLOWER

# ---- shared colours (sRGB) ------------------------------------------------------------------------------
CONC = (228, 206, 174)        # warm, sun-softened concrete (Plain)
CONC_SHADE = (184, 168, 146)  # soffits, pilotis, recesses
LIT = (255, 196, 120)         # Lantern: pendants and lamps (a lit room shows through an OPEN pane, never a lit pane)
TIMBER = (196, 148, 98)
GREENROOF = (112, 140, 70)
MOSS = (88, 120, 58)
GLASS = (52, 72, 96)
PV = (40, 56, 84)             # PV uses SolarGlass at scale 0 (its panel grid); windows use scale 400
CORB_RED, CORB_YELLOW, CORB_GREEN, CORB_BLUE = (196, 58, 44), (236, 186, 52), (72, 140, 84), (58, 104, 164)
LEAVES = LEAF + ((70, 118, 52), (104, 146, 62))


def _clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def _vivid(c, s_min=0.5, v=0.78):
    """A palette colour pushed to a usable accent (saturated, mid-bright)."""
    h, s, _ = colorsys.rgb_to_hsv(*(x / 255.0 for x in c))
    r, g, b = colorsys.hsv_to_rgb(h, max(s, s_min), v)
    return (int(r * 255), int(g * 255), int(b * 255))


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _span(total, target, lo=1):
    """Number of equal modules of about `target` metres filling `total`, and their exact size."""
    n = max(lo, int(round(total / target)))
    return n, total / n


# ---- glazing and lit rooms ----------------------------------------------------------------------------
# SolarGlass is opaque. A lit room is drawn as an open pane: a gap in the glazing run with a shallow
# timber-lined room behind it (back wall, ceiling, floor, jambs) and a Lantern pendant hanging inside.
def _fbox(k, s, axis, plane, out, t0, t1, n0, n1, z0, z1):
    """Box on a facade. axis 'y': the face lies in y = plane (runs along x); 'x': in x = plane (runs along y).
    t runs along the face, n is the offset along the outward normal (out = -1 / +1), negative = inside."""
    a, b = plane + out * n0, plane + out * n1
    lo, hi = min(a, b), max(a, b)
    if axis == "y":
        k.box(s, min(t0, t1), lo, z0, max(t0, t1), hi, z1)
    else:
        k.box(s, lo, min(t0, t1), z0, hi, max(t0, t1), z1)


def _glazing(k, glass, axis, plane, out, t0, t1, z0, z1, gaps=(), th=0.06):
    """A glass run t0..t1 on a face (outer surface on the plane), minus the open panes in gaps [(a, b), ...]."""
    cur = t0
    for a, b in sorted(gaps):
        if a > cur + 0.02:
            _fbox(k, glass, axis, plane, out, cur, a, -th, 0.0, z0, z1)
        cur = max(cur, b)
    if t1 > cur + 0.02:
        _fbox(k, glass, axis, plane, out, cur, t1, -th, 0.0, z0, z1)


def _room(k, wall, lit, axis, plane, out, t0, t1, z0, z1, depth=1.8, pendants=1):
    """The lit room behind an open pane t0..t1 x z0..z1: warm timber lining and Lantern pendant(s)."""
    _fbox(k, wall, axis, plane, out, t0, t1, -depth - 0.06, -depth, z0, z1)        # back wall
    _fbox(k, wall, axis, plane, out, t0, t1, -depth, 0.0, z1 - 0.06, z1 + 0.02)    # ceiling
    _fbox(k, wall, axis, plane, out, t0, t1, -depth, 0.0, z0 - 0.02, z0 + 0.04)    # floor
    _fbox(k, wall, axis, plane, out, t0 - 0.05, t0, -depth, 0.0, z0, z1)            # jambs
    _fbox(k, wall, axis, plane, out, t1, t1 + 0.05, -depth, 0.0, z0, z1)
    for i in range(pendants):
        tm = t0 + (t1 - t0) * (i + 0.5) / pendants
        zp = min(z1 - 0.55, z0 + 2.0)
        _fbox(k, lit, axis, plane, out, tm - 0.2, tm + 0.2, -depth * 0.5 - 0.2, -depth * 0.5 + 0.2, zp - 0.32, zp)
        _fbox(k, wall, axis, plane, out, tm - 0.015, tm + 0.015, -depth * 0.5 - 0.015, -depth * 0.5 + 0.015, zp, z1)


# ---- planting ----------------------------------------------------------------------------------------
class Green:
    """Budgeted planting helpers (Puff cushions, Fringe curtains, flower dots, trees)."""

    def __init__(self, k, rng, budget=590):
        self.k, self.rng, self.budget = k, rng, budget

    @property
    def left(self):
        return self.budget - len(self.k.inst)

    def _ok(self, n=1):
        return len(self.k.inst) + n <= self.budget

    def puff(self, x, y, z, rx, ry, rz, flower=0.0, cull=260.0, shadow=True):
        if not self._ok():
            return
        r = self.rng
        bloom = r.random() < flower
        tint = r.choice(FLOWER[:3] + FLOWER[4:]) if bloom and r.random() < 0.35 else r.choice(LEAVES)
        self.k.plant("Puff", "Foliage", tint, x, y, z, rx, ry, rz, r.uniform(0, 360), shadow, cull)
        if bloom and tint in LEAVES and self._ok():     # flowers dotted on the green cushion
            for _ in range(1 + (rx > 0.7)):
                if not self._ok():
                    break
                a = r.uniform(0, 6.283)
                self.k.plant("Blob", "Foliage", r.choice(FLOWER), x + math.cos(a) * rx * 0.45, y + math.sin(a) * ry * 0.45,
                             z + rz * 0.55, 0.16 + rx * 0.12, 0.16 + rx * 0.12, 0.12 + rx * 0.08, r.uniform(0, 360), False, 160.0)

    def dots(self, x, y, z, s=0.22, cull=160.0):
        """A small flower cluster (Blob) sitting in the green."""
        if not self._ok():
            return
        r = self.rng
        self.k.plant("Blob", "Foliage", r.choice(FLOWER), x, y, z, s, s, s * 0.7, r.uniform(0, 360), False, cull)

    def fringe(self, x, y, z, width, length, face, flower=0.12, cull=260.0):
        """Trailing plants hanging from (x, y, z): face = 'front' (-y) | 'back' (+y) | 'left' (-x) | 'right' (+x)."""
        if not self._ok():
            return
        r = self.rng
        yaw = {"front": 180.0, "back": 0.0, "left": 90.0, "right": 270.0}[face]
        p = r.random()
        tint = r.choice(FLOWER[:3] + FLOWER[5:]) if p < flower else r.choice(LEAVES)
        self.k.plant("Fringe", "Foliage", tint, x, y, z, width, 1.0, length, yaw, False, cull)

    def tree(self, x, y, z, h, crown, blossom=0.25, zcap=None):
        if not self._ok(3):
            return
        if zcap is not None and z + h * 0.72 + crown * 0.7 > zcap:   # shrink to fit under the height cap
            h = (zcap - z - crown * 0.7) / 0.72
            if h < 1.6:
                return
        r = self.rng
        k = self.k
        k.plant("Trunk", "Bark", (98, 76, 58), x, y, z, 0.28 * crown / 2.5, 0.28 * crown / 2.5, h * 0.75, r.uniform(0, 360), True, 400)
        tint = r.choice(FLOWER[:2] + (FLOWER[4],)) if r.random() < blossom else r.choice(LEAVES)
        k.plant("Blob", "Foliage", tint, x, y, z + h * 0.72, crown, crown, crown * 0.7, r.uniform(0, 360), True, 400)
        k.plant("Puff", "Foliage", r.choice(LEAVES), x + r.uniform(-0.4, 0.4) * crown, y + r.uniform(-0.4, 0.4) * crown,
                z + h * 0.6, crown * 0.75, crown * 0.75, crown * 0.5, r.uniform(0, 360), True, 400)

    def bed(self, x0, y0, x1, y1, z, n, size=(0.6, 1.1), flower=0.3):
        """Scatter n cushions (and some flowers) in a rectangle."""
        r = self.rng
        for _ in range(n):
            s = r.uniform(*size)
            x, y = r.uniform(x0, x1), r.uniform(y0, y1)
            self.puff(x, y, z, s, s * r.uniform(0.8, 1.1), s * 0.6, 0.0)
            if r.random() < flower:
                self.dots(x + r.uniform(-0.3, 0.3), y + r.uniform(-0.3, 0.3), z + s * 0.5, 0.2 + s * 0.1)


def _lamp(k, s_pole, s_lit, x, y, z=0.0, h=3.2):
    """A slim garden lantern on a post."""
    k.box(s_pole, x - 0.05, y - 0.05, z, x + 0.05, y + 0.05, z + h)
    k.box(s_lit, x - 0.16, y - 0.16, z + h, x + 0.16, y + 0.16, z + h + 0.38)
    k.box(s_pole, x - 0.22, y - 0.22, z + h + 0.38, x + 0.22, y + 0.22, z + h + 0.45)


# =========================================================================================================
# Unite d'Habitation
# =========================================================================================================
def unite_habitation(plot):
    """Le Corbusier's Unite d'Habitation (Marseille, 1952), scaled to 4-6 floors.

    A long concrete slab lifted on massive tapering pilotis over a garden, its long faces a deep brise-soleil
    grid of loggias with painted side and back walls (red / yellow / green / blue) and double-height duplex
    living rooms, a band of fine louvres at the 'interior street' floor, blank end walls with an external stair,
    and the sculptural roof terrace (ventilation stack, vaulted gym, running track, paddling pool) turned into
    a roof garden with a PV pergola. Every loggia planter spills over its parapet."""
    rng = plot.rng
    w, d, H = plot.w, plot.d, plot.h_max
    k = Kit(w, d)
    g = Green(k, rng, 590)
    pal = plot.palette

    conc = k.mat("Plain", CONC)
    rough = k.mat("PermeableStone", (232, 214, 186), 600.0)   # pre-cast parapets: panel joints, a shade darker
    shade = k.mat("Plain", CONC_SHADE)
    glass = k.mat("SolarGlass", GLASS, 400.0)   # scale 400: smooth window glass (scale 0 is the PV grid)
    lit = k.mat("Lantern", LIT)
    wood = k.mat("Timber", _mix(TIMBER, pal[2], 0.2))
    roofg = k.mat("GreenRoof", GREENROOF)
    pv = k.mat("SolarGlass", PV)
    # Corbusier's loggia colours; one drifts toward the block palette so blocks differ
    cols = [CORB_RED, CORB_YELLOW, CORB_GREEN, CORB_BLUE]
    j = rng.randrange(4)
    cols[j] = _mix(cols[j], _vivid(pal[rng.randrange(3)], 0.55, 0.74), 0.5)
    cslots = [k.mat("Plain", c) for c in cols]
    red, blue = cslots[0], cslots[3]
    wts = [rng.uniform(0.6, 1.4) for _ in range(4)]

    def pick_col():
        return rng.choices(cslots, wts)[0]

    # ---- massing -------------------------------------------------------------------------------------
    mx = 2.5
    x0, x1 = mx, w - mx
    D = _clamp(d - 4.5, 11.0, 18.5)
    y0 = _clamp((d - D) * 0.6, 2.0, d - D - 0.8)
    y1 = y0 + D
    ld = 1.5                     # loggia depth (brise-soleil projection in front of the glass)
    t_fin, t_sl = 0.24, 0.26
    fh, ts, rp = 2.85, 1.2, 1.4  # storey (Modulor-ish), transfer slab, roof parapet
    n = _clamp(int((H - ts - 3.8 - 3.0) / fh), 4, 6)    # leave ~3 m over the roof for the terrace sculpture
    if plot.floors > 0:
        n = _clamp(plot.floors, 4, n)
    lp = _clamp(H - ts - n * fh - 3.6, 3.8, 5.5)        # clear height under the slab
    z1 = lp + ts
    zr = z1 + n * fh
    nb, b = _span(x1 - x0, 3.66)
    k.solid(x0, y0, lp, x1, y1, zr + rp)
    mid = n // 2                 # the 'interior street' floor: fine louvres instead of loggias (front)

    # ---- the two long faces: front (out = -1, outer plane y0) and back (out = +1, plane y1) --------
    for side, (yo, out) in enumerate(((y0, -1), (y1, 1))):
        yi = yo - out * ld
        ya, yb = min(yo, yi), max(yo, yi)
        dbl = set()              # f in dbl: floors f and f+1 are one double-height living-room loggia
        for f in range(n - 1):
            if f % 3 == side and f not in (mid, mid - 1):
                dbl.add(f)
        # plan the cells first: which side carries the painted panel, which rooms are lit (open panes)
        gaps = {f: [] for f in range(n)}
        cells = []
        for f in range(n):
            if f - 1 in dbl or (f == mid and side == 0):
                continue
            za = z1 + f * fh
            zt = za + fh * (2 if f in dbl else 1)
            for i in range(nb):
                xa, xc = x0 + i * b + t_fin / 2, x0 + (i + 1) * b - t_fin / 2
                left = rng.random() < 0.5
                pw = (xc - xa) * rng.uniform(0.26, 0.38) if rng.random() < 0.5 else 0.0
                lit_ = rng.random() < 0.22
                cells.append((f, za, zt, xa, xc, left, pw, rng.random() < 0.35, lit_))
                if lit_:      # open the window part of the cell (beside the painted panel)
                    ga, gc = (xa + max(pw, 0.15), xc - 0.15) if left else (xa + 0.15, xc - max(pw, 0.15))
                    for ff in ((f, f + 1) if f in dbl else (f,)):
                        gaps[ff].append((ga, gc))
                    _room(k, wood, lit, "y", yi, out, ga, gc, za + t_sl / 2, zt - t_sl / 2, 2.2)
        if side == 0:      # the interior street: shops behind louvres, every other bay open and lit
            za = z1 + mid * fh
            for i in range(nb):
                if (i + side) % 2 == 0 or rng.random() < 0.3:
                    xa, xc = x0 + i * b + t_fin / 2, x0 + (i + 1) * b - t_fin / 2
                    gaps[mid].append((xa, xc))
                    _room(k, wood, lit, "y", yi, out, xa, xc, za + t_sl / 2, za + fh - t_sl / 2, 2.8, 2)
        for f in range(n):
            za = z1 + f * fh
            _glazing(k, glass, "y", yi, out, x0, x1, za, za + fh, gaps[f])
            k.box(wood, x0, yi + 0.01 * out, za + 2.05, x1, yi + 0.05 * out, za + 2.13)   # timber transoms
        for f in range(n + 1):
            z = z1 + f * fh
            if f - 1 in dbl:     # a double row: slab only over the few single-height flats in it
                i = 0
                while i < nb:
                    if rng.random() < 0.16:
                        c = i + 1 + (rng.random() < 0.4)
                        k.box(conc, x0 + i * b, ya, z - t_sl / 2, x0 + min(c, nb) * b, yb, z + t_sl / 2)
                        i = c
                    i += 1
                continue
            k.box(conc, x0 - 0.12, ya - 0.04, z - t_sl / 2, x1 + 0.12, yb + 0.04, z + t_sl / 2)
        for i in range(nb + 1):
            x = x0 + i * b
            k.box(conc, x - t_fin / 2, ya, z1, x + t_fin / 2, yb, zr)
        for f in range(n):
            if f - 1 in dbl or (f == mid and side == 0):
                continue
            za = z1 + f * fh
            # parapet: one long pre-cast band per row
            k.box(rough, x0 + t_fin / 2, yo - 0.02 if out < 0 else yo - 0.16, za + t_sl / 2,
                  x1 - t_fin / 2, yo + 0.16 if out < 0 else yo + 0.02, za + 1.08)
        for f, za, zt, xa, xc, left, pw, sidewall, lit_ in cells:
            # painted panel on the back wall beside the window (reads head-on)
            if pw > 0:
                pa, pc = (xa, xa + pw) if left else (xc - pw, xc)
                k.box(pick_col(), pa, yi + 0.005 * out, za + t_sl / 2, pc, yi + 0.04 * out, zt - t_sl / 2)
            # painted side wall of the loggia
            if sidewall:
                xs = xa if not left else xc - 0.04
                k.box(pick_col(), xs, ya, za + t_sl / 2, xs + 0.04, yb, zt - t_sl / 2)
        if side == 0:            # the interior street: dense timber louvres
            za = z1 + mid * fh
            m, s_ = _span(x1 - x0, 0.75)
            for i in range(m + 1):
                x = x0 + i * s_
                k.box(wood, x - 0.05, yo, za + t_sl / 2, x + 0.05, yo + 0.32, za + fh - t_sl / 2)

    # ---- pilotis + the 'artificial ground' slab ---------------------------------------------------
    k.box(shade, x0 + 0.9, y0 + 0.9, lp, x1 - 0.9, y1 - 0.9, lp + ts * 0.6)
    k.box(conc, x0, y0, lp + ts * 0.6, x1, y1, z1 - t_sl / 2 + 0.01)
    npier, ps = _span(x1 - x0 - 5.0, 7.8)
    piers = []
    for i in range(npier + 1):
        x = x0 + 2.5 + i * ps
        for yy in (y0 + D * 0.26, y1 - D * 0.26):
            for dy in (-0.62, 0.62):
                k.cyl(shade, x, yy + dy, 0, 0.5, 1.0, lp + 0.1, 12, False)
            piers.append((x, yy))
            k.solid(x - 0.6, yy - 1.2, 0, x + 0.6, yy + 1.2, lp)
        # a deep rib under the slab on each pier line (the coffered 'sol artificiel')
        k.box(shade, x - 0.35, y0 + 0.9, lp - 0.55, x + 0.35, y1 - 0.9, lp)
        # life under the slab: a timber bench, a planter, a lantern hung from the soffit
        if i < npier:
            xb = x + ps * 0.5
            yc = (y0 + y1) / 2 + rng.uniform(-1.0, 1.0)
            if rng.random() < 0.6:
                k.box(wood, xb - 1.0, yc - 0.25, 0.42, xb + 1.0, yc + 0.25, 0.5)
                k.box(shade, xb - 0.8, yc - 0.2, 0, xb - 0.6, yc + 0.2, 0.42)
                k.box(shade, xb + 0.6, yc - 0.2, 0, xb + 0.8, yc + 0.2, 0.42)
            else:
                k.box(rough, xb - 0.9, yc - 0.6, 0, xb + 0.9, yc + 0.6, 0.5)
                g.puff(xb, yc, 0.45, 0.85, 0.55, 0.45, 0.4)
            k.box(shade, xb - 0.02, yc - 0.02, lp - 1.1, xb + 0.02, yc + 0.02, lp)
            k.box(lit, xb - 0.2, yc - 0.2, lp - 1.5, xb + 0.2, yc + 0.2, lp - 1.1)

    # entrance hall under the slab: glazed box with timber frames and a sculpted canopy
    xm = w / 2 + rng.choice((-1, 1)) * b * max(1, nb // 5)
    hw = min(6.0, (x1 - x0) * 0.07)
    ey0, ey1 = y0 + D * 0.34, y1 - D * 0.34
    k.box(glass, xm - hw, ey0 + 0.06, 0, xm + hw, ey1, lp)                # the hall (its front opens)
    _glazing(k, glass, "y", ey0, -1, xm - hw, xm + hw, 0, lp, [(xm - 1.6, xm + 1.6)])
    _room(k, wood, lit, "y", ey0, -1, xm - 1.6, xm + 1.6, 0.0, lp - 0.3, 2.6, 1)
    nm = 7
    for i in range(nm):
        x = xm - hw + i * (2 * hw / (nm - 1))
        k.box(wood, x - 0.07, ey0 - 0.12, 0, x + 0.07, ey0, lp)
    k.box(wood, xm - hw, ey0 - 0.12, 2.3, xm + hw, ey0, 2.42)
    k.box(conc, xm - 3.2, y0 - 2.6, 3.0, xm + 3.2, ey0, 3.25)          # canopy reaching to the path
    k.box(shade, xm - 0.16, y0 - 2.4, 0, xm + 0.16, y0 - 2.08, 3.0)
    k.box(shade, xm - 1.6, 0.0, 0, xm + 1.6, ey0, 0.05)                # path

    # ---- end walls + external stair ---------------------------------------------------------------
    for xe, o in ((x0, -1), (x1, 1)):
        k.box(conc, xe - (0.3 if o < 0 else 0), y0 - 0.12, lp + ts * 0.6, xe + (0.3 if o > 0 else 0), y1 + 0.12, zr + rp)
        for f in range(n):
            za = z1 + f * fh
            for yy in (0.36, 0.5, 0.64):
                k.box(wood if rng.random() < 0.35 else glass, xe + o * 0.31 - 0.02, y0 + D * yy - 0.35, za + 0.9,
                      xe + o * 0.31 + 0.02, y0 + D * yy + 0.35, za + 2.0)
    se = rng.randrange(2)        # which end carries the stair (and the nursery on the roof)
    xs = (x0 - 1.4) if se == 0 else (x1 + 1.4)
    if 1.0 < xs < w - 1.0:
        ys = y0 + D * 0.72
        k.box(conc, xs - 1.0, ys - 1.7, 0, xs + 1.0, ys + 1.7, zr + 0.8)
        k.box(glass, xs - 1.02, ys - 0.22, 1.2, xs + 1.02, ys + 0.22, zr - 0.4)
        k.box(red, xs - 1.02, ys - 1.7, 0.0, xs + 1.02, ys - 1.2, 2.6)    # painted door reveal
        k.solid(xs - 1.0, ys - 1.7, 0, xs + 1.0, ys + 1.7, zr + 0.8)

    # ---- roof terrace: warm concrete deck, running track, sculpture, planted islands ----------------
    k.box(shade, x0 + 0.3, y0 + 0.3, zr, x1 - 0.3, y1 - 0.3, zr + 0.08)
    for (a, bb, c, e) in ((x0, y0 - 0.12, x1, y0 + 0.3), (x0, y1 - 0.3, x1, y1 + 0.12),
                          (x0, y0, x0 + 0.3, y1), (x1 - 0.3, y0, x1, y1)):
        k.box(conc, a, bb, zr, c, e, zr + rp)
    k.ribbon(red, [(x0 + 1.1, y0 + 1.1), (x1 - 1.1, y0 + 1.1), (x1 - 1.1, y1 - 1.1), (x0 + 1.1, y1 - 1.1),
                   (x0 + 1.1, y0 + 1.1)], 1.1, zr + 0.08, zr + 0.12)
    room = H - 0.1 - zr
    L = x1 - x0
    gl = _clamp(L * 0.18, 9.0, 16.0)
    gx0, gx1 = (x1 - 2.0 - gl, x1 - 2.0) if se == 0 else (x0 + 2.0, x0 + 2.0 + gl)
    pl = _clamp(L * 0.16, 7.0, 14.0)
    px0, px1 = (x0 + 2.0, x0 + 2.0 + pl) if se == 0 else (x1 - 2.0 - pl, x1 - 2.0)
    # gym with a curved shell roof
    gy0, gy1 = y0 + 2.4, y1 - 2.4
    gh = min(room - 0.2, 4.4)
    k.box(glass, gx0 + 0.3, gy0 + 0.36, zr, gx1 - 0.3, gy1 - 0.3, zr + gh * 0.45)
    gm = (gx0 + gx1) / 2
    gg = [(gm - 3.2, gm - 0.6), (gm + 0.6, gm + 3.2)]
    _glazing(k, glass, "y", gy0 + 0.3, -1, gx0 + 0.3, gx1 - 0.3, zr, zr + gh * 0.45, gg)
    for ga, gc in gg:
        _room(k, wood, lit, "y", gy0 + 0.3, -1, ga, gc, zr + 0.08, zr + gh * 0.45, 2.0)
    k.vault(conc, gx0, gy0, zr + gh * 0.45, gx1, gy1, zr + gh * 0.45, gh * 0.55, True, 0.3, 14)
    for xx in (gx0, gx1):
        k.box(conc, xx - 0.2, gy0, zr, xx + 0.2, gy1, zr + gh * 0.45)
    # PV pergola over the nursery terrace: timber posts with vines
    zp = zr + min(2.9, room - 0.6)
    npp, pps = _span(px1 - px0, 3.2)
    for i in range(npp + 1):
        x = px0 + i * pps
        for yy in (y0 + 2.2, y1 - 2.2):
            k.box(wood, x - 0.09, yy - 0.09, zr, x + 0.09, yy + 0.09, zp)
            g.fringe(x, yy - 0.12, zp, 1.0, zp - zr - 0.3, "front")
    k.box(wood, px0 - 0.2, y0 + 2.0, zp, px1 + 0.2, y1 - 2.0, zp + 0.18)
    k.slope(pv, px0 - 0.3, y0 + 1.9, px1 + 0.3, y1 - 1.9, zp + 0.18, zp + 0.55, 0.08)
    g.bed(px0, y0 + 3.0, px1, y1 - 3.0, zr + 0.08, int(pl / 2.5), (0.5, 0.8), 0.5)
    # the middle of the deck: the ventilation stack and machine room, the paddling pool, planted islands
    ma, mb = (px1 + 2.0, gx0 - 2.0) if se == 0 else (gx1 + 2.0, px0 - 2.0)
    xv = ma + (mb - ma) * rng.uniform(0.5, 0.7)
    yv = (y0 + y1) / 2 + rng.uniform(-0.8, 0.8)
    hs = min(room, 6.0)
    r0 = min(2.6, 0.45 * hs + 0.9)
    k.cyl(conc, xv, yv, zr, r0, r0 * 0.62, hs - 0.45, 20)
    k.cyl(shade, xv, yv, zr + hs - 0.45, r0 * 0.68, r0 * 0.68, 0.45, 20)
    hm = min(room, 3.4)
    k.cyl(conc, xv + r0 + 1.4, yv, zr, 1.0, 1.0, hm, 14)                 # machine-room drum + block
    k.box(conc, xv + r0 + 1.4, yv - 1.0, zr, xv + r0 + 4.4, yv + 1.0, zr + hm)
    k.box(cslots[1], xv + r0 + 4.38, yv - 0.5, zr, xv + r0 + 4.44, yv + 0.5, zr + min(2.1, hm - 0.2))   # painted door
    xpool = ma + (mb - ma) * 0.16
    pwid = min(7.0, (mb - ma) * 0.22)
    pd = min(5.0, D - 7.0)
    k.box(conc, xpool - pwid / 2, y0 + 2.6, zr, xpool + pwid / 2, y0 + 2.6 + pd, zr + 0.45)
    k.box(blue, xpool - pwid / 2 + 0.3, y0 + 2.9, zr + 0.3, xpool + pwid / 2 - 0.3, y0 + 2.3 + pd, zr + 0.47)
    # planted islands along both long sides (raised beds, green top, cushions and small trees)
    for yy, hwid in ((y0 + 2.75, 0.85), (y1 - 2.75, 0.85)):
        nisl, il = _span(mb - ma, 5.5)
        for i in range(nisl):
            xa, xc = ma + i * il + 0.6, ma + (i + 1) * il - 0.6
            xmid = (xa + xc) / 2
            if abs(xmid - xv) < r0 + 1.5 or (xa < xv + r0 + 4.6 and xc > xv + r0) and abs(yy - yv) < 2.5:
                continue
            if xa < xpool + pwid / 2 + 0.5 and xc > xpool - pwid / 2 - 0.5 and yy < y0 + 3.0 + pd:
                continue
            k.box(conc, xa, yy - hwid, zr, xc, yy + hwid, zr + 0.5)
            k.box(roofg, xa + 0.15, yy - hwid + 0.15, zr + 0.5, xc - 0.15, yy + hwid - 0.15, zr + 0.56)
            if rng.random() < 0.45:
                g.tree(xmid + rng.uniform(-1, 1), yy, zr + 0.55, 4.2, rng.uniform(1.2, 1.7), 0.45, H + 6.0)
            for _ in range(2):
                g.puff(rng.uniform(xa + 0.6, xc - 0.6), yy + rng.uniform(-0.3, 0.3), zr + 0.5, rng.uniform(0.6, 0.9),
                       0.6, 0.45, 0.4)
            g.fringe(xmid, yy - hwid - 0.03 if yy < yv else yy + hwid + 0.03, zr + 0.56, il * 0.6, 0.45,
                     "front" if yy < yv else "back", 0.3)
    # green spilling off the parapet top (the long faces)
    for i in range(int(L / 2.4)):
        x = x0 + 1.2 + i * 2.4 + rng.uniform(-0.3, 0.3)
        g.fringe(x, y0 - 0.14, zr + rp, rng.uniform(1.8, 2.6), rng.uniform(0.7, 1.7), "front")
        if i % 2:
            g.fringe(x, y1 + 0.14, zr + rp, rng.uniform(1.8, 2.6), rng.uniform(0.7, 1.7), "back")

    # ---- ground: garden under and around the slab (planted before the loggias so it gets its share) --
    for i in range(int(L / 12)):
        x = x0 + 6 + i * 12
        if abs(x - xm) > hw + 2.5:
            _lamp(k, shade, lit, x, max(0.6, y0 - 1.2))
    if y0 > 3.0:
        g.bed(0.5, 0.3, w - 0.5, y0 - 1.8, 0, int(w / 3.5), (0.6, 1.2), 0.35)
    for (x, yy) in piers[::2]:
        g.puff(x + 1.4, yy, 0, 1.0, 1.4, 0.5, 0.25)
    g.bed(x0, y0 + 1.2, x1, y1 - 1.2, 0, int(w / 12), (0.7, 1.2), 0.2)
    for i in range(int(w / 15)):
        x = rng.uniform(1.5, w - 1.5)
        front = (i % 3 != 0) or d - y1 < 2.5
        y = rng.uniform(0.8, max(1.0, y0 - 1.5)) if front else rng.uniform(y1 + 0.8, d - 0.5)
        room_y = (y0 - y) if front else (y - y1)       # keep crowns out from under the slab
        crown = min(rng.uniform(1.6, 2.4), room_y + 0.4)
        if crown >= 1.0:
            g.tree(x, y, 0, min(rng.uniform(4.0, 6.0), lp + 1.0), crown, 0.35)

    # ---- planting on the loggias, from what's left of the budget ----------------------------------------
    ncell = nb * n
    per = _clamp((g.left - 4) / max(1, 2 * ncell), 0.3, 2.5)
    for side, (yo, out) in enumerate(((y0, -1), (y1, 1))):
        face = "front" if out < 0 else "back"
        dens = per * (1.3 if side == 0 else 0.7)
        for f in range(n):
            if f == mid and side == 0:
                continue
            za = z1 + f * fh
            for i in range(nb):
                xa = x0 + i * b
                q = dens
                while q > 0:
                    if rng.random() < min(q, 1.0):
                        xm2 = xa + b * rng.uniform(0.3, 0.7)
                        if rng.random() < 0.55:
                            g.fringe(xm2, yo + out * 0.06, za + 1.08, b * rng.uniform(0.55, 0.95),
                                     rng.uniform(1.0, 2.6), face)
                        else:
                            g.puff(xm2, yo - out * 0.1, za + 1.0, b * rng.uniform(0.2, 0.34), 0.38, 0.42, 0.25)
                    q -= 1.0
    return k


# =========================================================================================================
# Habitat 67
# =========================================================================================================
def _ov(a, b):
    """Overlap area of two rects (x0, y0, x1, y1)."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _inside(px, py, r, m=0.0):
    return r[0] - m < px < r[2] + m and r[1] - m < py < r[3] + m


def habitat67(plot):
    """Moshe Safdie's Habitat 67 (Montreal, 1967), fitted to the plot.

    Identical pre-cast concrete boxes stacked in three directions into hill-like clusters around lift cores,
    each box offset from the one below so that its roof is the garden of the home above. Glass-vaulted
    pedestrian streets run between the cores through the voids. Solarpunk: every exposed roof is a planted
    terrace spilling over its parapet, some carry a fabric sail or PV, the voids hold trees."""
    rng = plot.rng
    w, d, H = plot.w, plot.d, plot.h_max
    k = Kit(w, d)
    g = Green(k, rng, 590)
    pal = plot.palette

    conc = k.mat("Plain", CONC)
    conc2 = k.mat("Plain", (206, 188, 160))       # boxes cast a little darker: the pile reads as units
    shade = k.mat("Plain", CONC_SHADE)
    glass = k.mat("SolarGlass", GLASS, 400.0)   # scale 400: smooth window glass (scale 0 is the PV grid)
    lit = k.mat("Lantern", LIT)
    roofg = k.mat("GreenRoof", GREENROOF)
    wood = k.mat("Timber", _mix(TIMBER, pal[2], 0.2))
    pv = k.mat("SolarGlass", PV)
    sail = k.mat("Fabric", _vivid(pal[0], 0.35, 0.92))
    sail2 = k.mat("Fabric", _vivid(pal[1], 0.4, 0.85))
    canopy = glass                                # SolarGlass ignores tint

    BL, BW, BH = 9.0, 4.6, 3.0                    # the module (real: 11.7 x 5.3 x 3 m)
    NL = _clamp(int((H - 1.3) / BH), 3, 7)
    m = max(1, int(round(w / 27.0)))
    cy = d * 0.5
    span = w / m
    cores = []
    for i in range(m):
        cx = span * (i + 0.5) + rng.uniform(-0.12, 0.12) * span
        peak = NL - (0 if (i == m // 2) else rng.randint(1, 2))
        cores.append((cx, cy + (rng.uniform(-0.12, 0.12) * d), max(2, peak)))
    core_r = [(cx - 1.6, cy_ - 1.6, cx + 1.6, cy_ + 1.6) for cx, cy_, _ in cores]
    # the pedestrian street: a level and a band along x between the outer cores
    bl = _clamp(NL // 2, 1, NL - 1) if m > 1 else None
    street = (cores[0][0], cy - 1.5, cores[-1][0], cy + 1.5) if bl is not None else None

    levels = [[] for _ in range(NL)]
    for lvl in range(NL):
        for ci, (cx, cyc, peak) in enumerate(cores):
            if lvl >= peak:
                continue
            frac = lvl / peak
            Rx = min(span * 0.55, 18.0) * (1.0 - 0.35 * frac)
            Ry = min(d * 0.5 - 1.0, 16.0) * (1.0 - 0.35 * frac)
            base = 0.5 * min(span, 36.0) * min(d - 2.0, 32.0) / (BL * BW)
            target = max(1, int(round(base * (1.0 - 0.6 * frac) + rng.uniform(-0.8, 0.8))))
            got = 0
            cands = []
            step = 1.15
            nx_, ny_ = int(Rx / step), int(Ry / step)
            for ix in range(-nx_, nx_ + 1):
                for iy in range(-ny_, ny_ + 1):
                    if (ix * step / max(Rx, 1)) ** 2 + (iy * step / max(Ry, 1)) ** 2 <= 1.0:
                        ax = rng.random() < (0.6 if (lvl + ci) % 2 == 0 else 0.4)
                        cands.append((round((cx + ix * step) / step) * step, round((cyc + iy * step) / step) * step, ax))
            rng.shuffle(cands)
            for bx, by, ax in cands:
                if got >= target:
                    break
                ex, ey = (BL, BW) if ax else (BW, BL)
                r = (bx - ex / 2, by - ey / 2, bx + ex / 2, by + ey / 2)
                if r[0] < 0.4 or r[1] < 0.4 or r[2] > w - 0.4 or r[3] > d - 0.4:
                    continue
                if any(_ov(r, o) > 0.01 for o in levels[lvl]) or any(_ov(r, c) > 0 for c in core_r):
                    continue
                if street and lvl == bl and _ov(r, street) > 0:
                    continue
                if lvl > 0:
                    sup = sum(_ov(r, o) for o in levels[lvl - 1]) / (ex * ey)
                    if sup < 0.4 or sup > 0.85:    # must stand on the box below, but leave it a garden
                        continue
                levels[lvl].append(r)
                got += 1

    # ---- boxes ---------------------------------------------------------------------------------------
    boxes = [(lvl, r) for lvl in range(NL) for r in levels[lvl]]
    nbox = len(boxes)
    # planting share for each box's roof (ground gets ~110 first, below)
    roof_share = _clamp((g.budget - 120) / max(1, nbox), 2, 9)
    g.budget -= 110                                # held back for the ground garden
    for lvl, r in boxes:
        x0, y0, x1, y1 = r
        z0, z1 = lvl * BH, lvl * BH + BH
        ax = (x1 - x0) > (y1 - y0)
        s = conc if rng.random() < 0.6 else conc2
        above = levels[lvl + 1] if lvl + 1 < NL else []
        same = levels[lvl]

        def face_free(fx0, fy0, fx1, fy1):
            probe = (fx0, fy0, fx1, fy1)
            return not any(o is not r and _ov(probe, o) > 0.05 for o in same)

        # which end faces are free to glaze, and is one of them an open, lit window?
        ends = []
        for e in (0, 1):
            if ax:
                xe = x0 if e == 0 else x1
                if face_free(xe - 0.3, y0 + 0.5, xe + 0.3, y1 - 0.5):
                    ends.append(("x", xe, -1 if e == 0 else 1, y0, y1))
            else:
                ye = y0 if e == 0 else y1
                if face_free(x0 + 0.5, ye - 0.3, x1 - 0.5, ye + 0.3):
                    ends.append(("y", ye, -1 if e == 0 else 1, x0, x1))
        lit_end = rng.choice(ends) if ends and rng.random() < 0.35 else None
        dep = 1.7
        sx0, sy0, sx1, sy1 = x0, y0, x1, y1
        if lit_end:                       # shorten the shell: the lit end is built as a frame + room
            axis_, pl, o, _, _ = lit_end
            if axis_ == "x":
                sx0, sx1 = (x0 + dep, x1) if o < 0 else (x0, x1 - dep)
            else:
                sy0, sy1 = (y0 + dep, y1) if o < 0 else (y0, y1 - dep)
        k.box(s, sx0, sy0, z0 + 0.14, sx1, sy1, z1 - 0.02)
        k.box(shade, x0 + 0.12, y0 + 0.12, z0, x1 - 0.12, y1 - 0.12, z0 + 0.14)    # shadow joint between units
        k.solid(x0, y0, z0, x1, y1, z1)
        wz0, wz1 = z0 + 0.5, z1 - 0.45
        for end in ends:
            axis_, pl, o, ta, tb = end
            wa, wb = ta + 0.6, tb - 0.6
            tm = (wa + wb) / 2
            if end is lit_end:
                for (fa, fb, za_, zb_) in ((ta, tb, z0 + 0.14, wz0), (ta, tb, wz1, z1 - 0.02), (ta, wa, wz0, wz1), (wb, tb, wz0, wz1)):
                    _fbox(k, s, axis_, pl, o, fa, fb, -dep, 0.0, za_, zb_)
                ga, gb = (tm, wb) if rng.random() < 0.5 else (wa, tm)
                _glazing(k, glass, axis_, pl, o, wa, wb, wz0, wz1, [(ga, gb)])
                _room(k, wood, lit, axis_, pl, o, ga, gb, wz0, wz1, dep - 0.1)
            else:
                _fbox(k, glass, axis_, pl, o, wa, wb, 0.0, 0.04, wz0, wz1)
            _fbox(k, wood, axis_, pl, o, tm - 0.06, tm + 0.06, 0.0, 0.07, wz0, wz1)       # timber mullion
            _fbox(k, shade, axis_, pl, o, ta + 0.4, tb - 0.4, -0.04, 0.08, z0 + 0.35, wz0)  # sill
        # long-side strip window
        L_ = (x1 - x0) if ax else (y1 - y0)
        sd = rng.choice((0, 1))
        a0 = rng.uniform(0.8, L_ * 0.35)
        a1 = a0 + rng.uniform(2.5, L_ * 0.5)
        if ax:
            ye = y0 if sd == 0 else y1
            o = -1 if sd == 0 else 1
            if face_free(x0 + a0, ye - 0.3, x0 + a1, ye + 0.3):
                k.box(glass, x0 + a0, min(ye, ye + o * 0.04), z0 + 0.9, x0 + a1, max(ye, ye + o * 0.04), z1 - 0.5)
        else:
            xe = x0 if sd == 0 else x1
            o = -1 if sd == 0 else 1
            if face_free(xe - 0.3, y0 + a0, xe + 0.3, y0 + a1):
                k.box(glass, min(xe, xe + o * 0.04), y0 + a0, z0 + 0.9, max(xe, xe + o * 0.04), y0 + a1, z1 - 0.5)

        # ---- the roof garden: green deck, parapet on exposed edges, cushions, curtains --------------
        cover = sum(_ov(r, o) for o in above) / ((x1 - x0) * (y1 - y0))
        if cover > 0.9:
            continue
        k.box(roofg, x0 + 0.25, y0 + 0.25, z1 - 0.02, x1 - 0.25, y1 - 0.25, z1 + 0.1)
        edges = ((x0, y0, x1, y0 + 0.25, "front", (x0 + x1) / 2, y0), (x0, y1 - 0.25, x1, y1, "back", (x0 + x1) / 2, y1),
                 (x0, y0, x0 + 0.25, y1, "left", x0, (y0 + y1) / 2), (x1 - 0.25, y0, x1, y1, "right", x1, (y0 + y1) / 2))
        top = not above or cover < 0.01
        for ex0, ey0, ex1, ey1, face, mx_, my_ in edges:
            if any(_inside(mx_, my_, o, 0.3) for o in above):
                continue
            k.box(conc, ex0, ey0, z1, ex1, ey1, z1 + 0.7)
            # trailing plants over the exposed parapet (not into a neighbour)
            if face_free(ex0 - (0.3 if face == "left" else 0), ey0 - (0.3 if face == "front" else 0),
                         ex1 + (0.3 if face == "right" else 0), ey1 + (0.3 if face == "back" else 0)):
                along = (ex1 - ex0) if face in ("front", "back") else (ey1 - ey0)
                for j in range(1 + (along > 6) + (rng.random() < 0.6)):
                    if face in ("front", "back"):
                        fx, fy = rng.uniform(ex0 + 1.2, ex1 - 1.2), (ey0 if face == "front" else ey1) + (-0.04 if face == "front" else 0.04)
                        px_, py_ = fx, (ey0 + ey1) / 2
                    else:
                        fx, fy = (ex0 if face == "left" else ex1) + (-0.04 if face == "left" else 0.04), rng.uniform(ey0 + 1.2, ey1 - 1.2)
                        px_, py_ = (ex0 + ex1) / 2, fy
                    g.fringe(fx, fy, z1 + 0.72, rng.uniform(1.8, 3.0), rng.uniform(1.2, 2.9), face, 0.2)
                    if j == 0:      # a cushion spilling over the parapet top
                        g.puff(px_, py_, z1 + 0.6, rng.uniform(0.7, 1.0), 0.6, 0.45, 0.3)
        # cushions on the uncovered part of the deck
        n_p = int(roof_share * (1 - cover) * 0.45) + 1
        for _ in range(n_p * 3):
            if n_p <= 0:
                break
            px, py = rng.uniform(x0 + 0.8, x1 - 0.8), rng.uniform(y0 + 0.8, y1 - 0.8)
            if any(_inside(px, py, o, 0.7) for o in above):
                continue
            s_ = rng.uniform(0.6, 1.0)
            g.puff(px, py, z1 + 0.3, s_, s_ * 0.9, s_ * 0.75, 0.3)
            n_p -= 1
        zpv = min(z1 + 1.6, H - 0.12)
        if top and rng.random() < 0.5 and zpv > z1 + 1.25:
            # the top homes: PV on a light timber frame over half the roof
            if ax:
                xa = x0 + 0.5 if rng.random() < 0.5 else (x0 + x1) / 2
                k.slope(pv, xa, y0 + 0.5, xa + (x1 - x0) / 2 - 0.5, y1 - 0.5, z1 + 1.0, zpv, 0.06)
                for xx in (xa + 0.2, xa + (x1 - x0) / 2 - 0.7):
                    k.box(wood, xx - 0.06, y0 + 0.7, z1, xx + 0.06, y0 + 0.82, z1 + 1.05)
            else:
                ya = y0 + 0.5 if rng.random() < 0.5 else (y0 + y1) / 2
                k.slope(pv, x0 + 0.5, ya, x1 - 0.5, ya + (y1 - y0) / 2 - 0.5, z1 + 1.0, zpv, 0.06)
                for yy in (ya + 0.2, ya + (y1 - y0) / 2 - 0.7):
                    k.box(wood, x0 + 0.7, yy - 0.06, z1, x0 + 0.82, yy + 0.06, z1 + 1.05)
        elif cover < 0.5 and rng.random() < 0.22 and z1 + 2.6 < H:
            # a fabric sail on timber posts over the terrace
            cxs, cys = (x0 + x1) / 2, (y0 + y1) / 2
            hx, hy = (x1 - x0) * 0.3, (y1 - y0) * 0.3
            if not any(_ov((cxs - hx, cys - hy, cxs + hx, cys + hy), o) > 0 for o in above):
                for sx_ in (-1, 1):
                    for sy_ in (-1, 1):
                        k.box(wood, cxs + sx_ * hx - 0.05, cys + sy_ * hy - 0.05, z1, cxs + sx_ * hx + 0.05, cys + sy_ * hy + 0.05, z1 + 2.3)
                k.obox(rng.choice((sail, sail2)), cxs, cys, z1 + 2.35, hx + 0.2, hy + 0.2, 0.03, 0, 0, rng.uniform(-6, 6))

    # ---- lift cores ----------------------------------------------------------------------------------
    for (cx, cyc, peak), cr in zip(cores, core_r):
        zt = min(H - 0.3, peak * BH + 1.2)
        k.box(conc2, cr[0], cr[1], 0, cr[2], cr[3], zt)
        k.box(wood, cx - 0.35, cr[1] - 0.03, 0.0, cx + 0.35, cr[1], 2.3)            # timber door
        k.box(shade, cr[0] - 0.15, cr[1] - 0.15, zt, cr[2] + 0.15, cr[3] + 0.15, zt + 0.25)
        k.solid(*cr[:2], 0, *cr[2:], zt)
    # ---- the pedestrian street: a deck between the cores under a glass vault -----------------------
    if street:
        zs = bl * BH
        sx0, sx1 = street[0], street[2]
        k.box(wood, sx0, cy - 1.3, zs, sx1, cy + 1.3, zs + 0.2)
        k.box(shade, sx0, cy - 1.3, zs - 0.6, sx1, cy + 1.3, zs)
        for yy in (cy - 1.3, cy + 1.25):
            k.box(conc, sx0, yy, zs + 0.2, sx1, yy + 0.05, zs + 1.05)
        nr, rs = _span(sx1 - sx0, 3.0)
        for i in range(nr + 1):
            x = sx0 + i * rs
            for yy in (cy - 1.3, cy + 1.2):
                k.box(conc, x - 0.08, yy, zs + 0.2, x + 0.08, yy + 0.1, zs + 2.1)
            if i % 2 == 0:
                g.fringe(x + rs / 2, cy - 1.35, zs + 0.1, 2.0, rng.uniform(1.0, 2.2), "front")
        k.vault(canopy, sx0, cy - 1.35, zs + 2.1, sx1, cy + 1.35, zs + 2.1, 0.8, True, 0.06, 10)
        # piers under the street where it spans the ground
        if bl >= 1:
            for i in range(0, nr + 1, 2):
                x = sx0 + i * rs
                if not any(_inside(x, cy, o, 0.2) for lv in levels[:bl] for o in lv):
                    k.box(shade, x - 0.3, cy - 0.3, 0, x + 0.3, cy + 0.3, zs - 0.6)

    # ---- ground: paths, beds, trees in the voids, lamps ------------------------------------------
    g.budget += 110
    occupied0 = levels[0] + core_r
    k.box(shade, w * 0.5 - 1.2, 0, 0, w * 0.5 + 1.2, cy - 1.6, 0.04)
    tries = 0
    nt = 0
    while nt < max(2, int(w * d / 260)) and tries < 200:
        tries += 1
        x, y = rng.uniform(2, w - 2), rng.uniform(1.5, d - 1.5)
        if any(_inside(x, y, o, 2.2) for o in occupied0):
            continue
        g.tree(x, y, 0, rng.uniform(4.0, 6.5), rng.uniform(1.6, 2.4), 0.4)
        nt += 1
    for r in levels[0][: max(0, g.left - int(w * d / 60) - 10) // 2]:
        # foundation planting: cushions along the long faces of the ground boxes
        x0, y0, x1, y1 = r
        for _ in range(2):
            if (x1 - x0) > (y1 - y0):
                px, py = rng.uniform(x0 + 1, x1 - 1), rng.choice((y0 - 0.5, y1 + 0.5))
            else:
                px, py = rng.choice((x0 - 0.5, x1 + 0.5)), rng.uniform(y0 + 1, y1 - 1)
            if any(_inside(px, py, o, 0.1) for o in occupied0) or not (0.5 < px < w - 0.5 and 0.5 < py < d - 0.5):
                continue
            g.puff(px, py, 0, rng.uniform(0.7, 1.1), 0.7, 0.55, 0.35)
    tries = 0
    nb_ = 0
    while nb_ < int(w * d / 60) and tries < 400:
        tries += 1
        x, y = rng.uniform(0.6, w - 0.6), rng.uniform(0.4, d - 0.4)
        if any(_inside(x, y, o, 0.3) for o in occupied0):
            continue
        s_ = rng.uniform(0.6, 1.2)
        g.puff(x, y, 0, s_, s_, s_ * 0.6, 0.35)
        nb_ += 1
    for i in range(max(2, int(w / 14))):
        x = 3 + i * (w - 6) / max(1, int(w / 14) - 1)
        if not any(_inside(x, 0.8, o, 0.4) for o in occupied0):
            _lamp(k, shade, lit, x, 0.8)
    return k


# =========================================================================================================
# Lever House
# =========================================================================================================
def lever_slab(plot):
    """SOM / Gordon Bunshaft's Lever House (New York, 1952), as a housing and studio slab.

    A one-storey podium lifted on slim steel columns over an open plaza, a garden court cut through its middle,
    its roof a garden; above it, at 90 degrees to the street and to one side, a thin slab of blue-green glass
    with stainless mullions and dark green spandrel bands, a recessed 'neck' floor where it meets the podium,
    and a banded mechanical crown. Solarpunk: window boxes trail down the glass, the roof is PV and garden, vines
    climb the plaza columns, the court is a small forest."""
    rng = plot.rng
    w, d, H = plot.w, plot.d, plot.h_max
    k = Kit(w, d)
    g = Green(k, rng, 590)
    pal = plot.palette

    steel = k.mat("Plain", (204, 208, 210))              # stainless mullions, column cladding
    vision = k.mat("SolarGlass", GLASS, 400.0)                 # vision glass (SolarGlass ignores tint)
    spand = k.mat("Plain", (62, 122, 118))                # blue-green wire-glass spandrels carry the colour
    lit = k.mat("Lantern", LIT)
    stone = k.mat("Plain", (222, 214, 198))               # terrazzo / marble soffit + paving
    dark = k.mat("Plain", (64, 70, 72))
    roofg = k.mat("GreenRoof", GREENROOF)
    wood = k.mat("Timber", _mix(TIMBER, pal[2], 0.25))
    pv = k.mat("SolarGlass", PV)
    accent = k.mat("Plain", _vivid(pal[0], 0.4, 0.9))       # blinds: Plain (Fabric is striped)
    water = k.mat("Water", (64, 118, 128))

    # ---- podium -------------------------------------------------------------------------------------
    m = 1.0
    px0, py0, px1, py1 = m, m, w - m, d - m
    tall = H >= 23.0
    zc = 4.4 if tall else 3.7         # plaza clear height
    zp = zc + (3.7 if tall else 3.3)  # podium roof
    # the court: a hole through the podium, a little off-centre, away from the slab side
    side = rng.randrange(2)           # 0: slab on the low-x side, 1: high-x side
    T = _clamp(w * 0.2, 7.5, 10.5)    # slab thickness (along x): thin
    sx0 = (px0 + 1.5) if side == 0 else (px1 - 1.5 - T)
    sx1 = sx0 + T
    sy0, sy1 = py0 + 3.0, py1 - 1.0  # slab along y, set back from the street
    # court in the remaining width
    fx0, fx1 = (sx1 + 3.0, px1 - 3.5) if side == 0 else (px0 + 3.5, sx0 - 3.0)
    if fx1 - fx0 < 5.0:               # narrow plots: the court slides under the slab's edge
        fx0, fx1 = ((px0 + px1) / 2 - 3.0, (px0 + px1) / 2 + 3.0)
    fy0, fy1 = py0 + (py1 - py0) * 0.3, py1 - (py1 - py0) * 0.22
    court = (fx0, fy0, fx1, fy1)
    # podium body: a glass band with spandrel above, around the perimeter and the court
    for j, (a, b_, c, e) in enumerate(((px0, py0, px1, fy0), (px0, fy1, px1, py1), (px0, fy0, fx0, fy1), (fx1, fy0, px1, fy1))):
        k.box(spand, a + 0.05, b_ + 0.05, zc + 0.35, c - 0.05, e - 0.05, zc + 0.95)
        k.box(vision, a + 0.1, b_ + (2.1 if j == 0 else 0.1), zc + 0.95, c - 0.1, e - 0.1, zp - 1.4)
        k.box(spand, a + 0.05, b_ + 0.05, zp - 1.4, c - 0.05, e - 0.05, zp - 0.5)
    # the street face of the podium: studios, some with the window open and the lamps on
    pg = []
    x = px0 + 1.0
    while x < px1 - 4.0:
        x += rng.uniform(2.0, 7.0)
        if x + 3.0 < px1 - 0.5:
            pg.append((x, x + rng.uniform(1.5, 3.0)))
            x = pg[-1][1]
    _glazing(k, vision, "y", py0 + 0.1, -1, px0 + 0.1, px1 - 0.1, zc + 0.95, zp - 1.4, pg)
    for ga, gb in pg:
        _room(k, wood, lit, "y", py0 + 0.1, -1, ga, gb, zc + 0.95, zp - 1.4, 1.9)
    # soffit and roof slabs, as four strips around the court
    for z0_, z1_ in ((zc, zc + 0.35), (zp - 0.5, zp)):
        for (a, b_, c, e) in ((px0, py0, px1, fy0), (px0, fy1, px1, py1), (px0, fy0, fx0, fy1), (fx1, fy0, px1, fy1)):
            k.box(stone, a, b_, z0_, c, e, z1_)
    # podium mullions (outer faces + court faces)
    for (xa, xb, yy) in ((px0, px1, py0), (px0, px1, py1), (fx0, fx1, fy0), (fx0, fx1, fy1)):
        nm_, ms = _span(xb - xa, 1.55)
        for i in range(nm_ + 1):
            x = xa + i * ms
            k.box(steel, x - 0.04, yy - 0.06, zc + 0.35, x + 0.04, yy + 0.06, zp - 0.5)
    for (ya, yb, xx) in ((py0, py1, px0), (py0, py1, px1), (fy0, fy1, fx0), (fy0, fy1, fx1)):
        nm_, ms = _span(yb - ya, 1.55)
        for i in range(nm_ + 1):
            y = ya + i * ms
            k.box(steel, xx - 0.06, y - 0.04, zc + 0.35, xx + 0.06, y + 0.04, zp - 0.5)
    # columns over the plaza (steel-clad), vines on some
    ncx, csx = _span(px1 - px0 - 2.0, 6.0)
    ncy, csy = _span(py1 - py0 - 2.0, 6.0)
    for i in range(ncx + 1):
        for j in range(ncy + 1):
            x, y = px0 + 1.0 + i * csx, py0 + 1.0 + j * csy
            if _inside(x, y, court, 0.6):
                continue
            k.box(steel, x - 0.22, y - 0.22, 0, x + 0.22, y + 0.22, zc)
            if rng.random() < 0.3:
                g.fringe(x, y - 0.25, zc, 0.8, rng.uniform(1.5, 3.2), "front", 0.15)
    k.solid(px0, py0, zc, px1, py1, zp)
    # glass lobby under the slab
    lx0, lx1 = sx0 + 1.0, sx1 - 1.0
    ly0 = sy0 + 1.0
    ly1 = max(ly0 + 4.0, min(sy0 + 12.0, sy1 - 2.0))
    lm = (lx0 + lx1) / 2
    k.box(vision, lx0, ly0 + 0.06, 0, lx1, ly1, zc)
    _glazing(k, vision, "y", ly0, -1, lx0, lx1, 0, zc, [(lm - 1.6, lm + 1.6)])
    _room(k, wood, lit, "y", ly0, -1, lm - 1.6, lm + 1.6, 0.0, zc - 0.4, 2.8, 2)
    nm_, ms = _span(lx1 - lx0, 1.55)
    for i in range(nm_ + 1):
        k.box(steel, lx0 + i * ms - 0.04, ly0 - 0.08, 0, lx0 + i * ms + 0.04, ly0, zc)
    k.solid(lx0, ly0, 0, lx1, ly1, zc)
    # plaza paving + the court garden (open to the sky): a pool, a tree, beds
    k.box(stone, 0.2, 0.0, 0, w - 0.2, d - 0.2, 0.04)
    cx_, cy_ = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    k.box(roofg, fx0 + 0.3, fy0 + 0.3, 0, fx1 - 0.3, fy1 - 0.3, 0.12)
    k.box(stone, cx_ - 2.2, fy0 + 0.6, 0, cx_ + 2.2, fy0 + 2.6, 0.45)
    k.box(water, cx_ - 1.9, fy0 + 0.9, 0.3, cx_ + 1.9, fy0 + 2.3, 0.46)
    g.tree(cx_ + rng.uniform(-1, 1), cy_ + 1.0, 0.1, min(9.0, zp + 1.5), 2.6, 0.5)
    g.bed(fx0 + 0.6, fy0 + 3.0, fx1 - 0.6, fy1 - 0.6, 0.1, int((fx1 - fx0) * (fy1 - fy0) / 5), (0.6, 1.1), 0.4)
    for _ in range(6):
        g.fringe(rng.uniform(fx0 + 1, fx1 - 1), fy0 - 0.05, zp - 0.3, 2.0, rng.uniform(1.5, 3.0), "back", 0.2)

    # ---- the slab -----------------------------------------------------------------------------------
    fh = 3.2 if tall else 3.1
    zn = zp + (3.0 if tall else 0.0)   # top of the recessed neck floor (only when there's height for it)
    crown = 2.4 if tall else 1.2
    n = _clamp(int((H - 0.1 - crown - zn) / fh + 1e-6), 2, 8)
    if plot.floors > 0:
        n = _clamp(plot.floors - 2, 2, n)
    zt = zn + n * fh                   # top of the last studio floor
    if tall:                           # neck: glass set back, dark
        k.box(dark, sx0 + 0.9, sy0 + 0.9, zp, sx1 - 0.9, sy1 - 0.9, zn)
        k.box(vision, sx0 + 0.85, sy0 + 0.85, zp + 0.2, sx1 - 0.85, sy1 - 0.85, zn - 0.3)
        k.box(stone, sx0, sy0, zn - 0.3, sx1, sy1, zn)
    k.solid(sx0, sy0, zp, sx1, sy1, zt + crown)
    # curtain wall: vision glass core, spandrel bands per floor, mullions full height
    k.box(dark, sx0 + 2.1, sy0 + 2.1, zn, sx1 - 2.1, sy1 - 2.1, zt)        # core; rooms line the glass
    for f in range(n):
        z = zn + f * fh
        k.box(spand, sx0, sy0, z + fh - 1.05, sx1, sy1, z + fh)
    faces = (("front", sx0, sy0, sx1, sy0), ("back", sx0, sy1, sx1, sy1), ("left", sx0, sy0, sx0, sy1), ("right", sx1, sy0, sx1, sy1))
    for face, xa, ya, xb, yb in faces:
        Lf = max(xb - xa, yb - ya)
        nm_, ms = _span(Lf, 1.45)
        o = {"front": (0, -1), "back": (0, 1), "left": (-1, 0), "right": (1, 0)}[face]
        for i in range(nm_ + 1):
            t = i * ms
            x, y = (xa + t, ya) if face in ("front", "back") else (xa, ya + t)
            k.box(steel, x - 0.05 + o[0] * 0.04, y - 0.05 + o[1] * 0.04, zn, x + 0.05 + o[0] * 0.04, y + 0.05 + o[1] * 0.04, zt + crown)
        # rooms: vision glass per floor, some panes open onto lit studios, a few coloured blinds
        axis_, plane, out_, ta = ("y", ya, o[1], xa) if face in ("front", "back") else ("x", xa, o[0], ya)
        for f in range(n):
            z = zn + f * fh
            gaps = []
            for i in range(nm_):
                t0, t1 = ta + i * ms + 0.06, ta + (i + 1) * ms - 0.06
                r_ = rng.random()
                if r_ < 0.12:
                    gaps.append((t0, t1))
                    _room(k, wood, lit, axis_, plane, out_, t0, t1, z, z + fh - 1.05, 1.9)
                elif r_ > 0.92:
                    _fbox(k, accent, axis_, plane, out_, t0, t1, 0.01, 0.03, z + fh - 1.7, z + fh - 1.08)
            _glazing(k, vision, axis_, plane, out_, ta, ta + Lf, z, z + fh - 1.05, gaps)
            # a run of window boxes on this floor: planters on the spandrel with trailing plants
            if rng.random() < (0.8 if face in ("front", "left", "right") else 0.5):
                a = rng.randrange(nm_)
                bn = rng.randint(2, max(2, min(7, nm_ - a)))
                t0, t1 = a * ms, min(Lf, (a + bn) * ms)
                zb = z + fh - 1.05
                if face in ("front", "back"):
                    k.box(wood, xa + t0, ya + o[1] * 0.45 - 0.2, zb - 0.1, xa + t1, ya + o[1] * 0.45 + 0.2, zb + 0.35)
                else:
                    k.box(wood, xa + o[0] * 0.45 - 0.2, ya + t0, zb - 0.1, xa + o[0] * 0.45 + 0.2, ya + t1, zb + 0.35)
                tt = t0 + 0.6
                while tt < t1 - 0.4:
                    x, y = (xa + tt, ya + o[1] * 0.67) if face in ("front", "back") else (xa + o[0] * 0.67, ya + tt)
                    if rng.random() < 0.6:
                        g.fringe(x, y, zb + 0.3, rng.uniform(1.0, 1.6), rng.uniform(1.0, 2.8), face, 0.18)
                    else:
                        x2, y2 = (x, ya + o[1] * 0.45) if face in ("front", "back") else (xa + o[0] * 0.45, y)
                        g.puff(x2, y2, zb + 0.3, 0.55, 0.55, 0.35, 0.35)
                    tt += rng.uniform(0.9, 1.4)
    # crown: the mechanical floors, banded, with a roof garden and PV
    k.box(pv, sx0 + 0.05, sy0 + 0.05, zt, sx1 - 0.05, sy1 - 0.05, zt + crown)      # PV skin on the plant floors
    for zz in ((zt + 0.7, zt + 1.5) if tall else (zt + 0.5,)):
        k.box(steel, sx0 - 0.02, sy0 - 0.02, zz, sx1 + 0.02, sy1 + 0.02, zz + 0.12)
    k.box(stone, sx0 - 0.05, sy0 - 0.05, zt + crown - 0.25, sx1 + 0.05, sy1 + 0.05, zt + crown)
    k.box(roofg, sx0 + 0.4, sy0 + 0.4, zt + crown, sx1 - 0.4, sy1 - 0.4, zt + crown + 0.08)
    room = H - (zt + crown) - 0.1
    if room > 0.6:
        npv, pvs = _span(sy1 - sy0 - 2.0, 3.0)
        for i in range(npv):
            ya_ = sy0 + 1.0 + i * pvs
            k.slope(pv, sx0 + 1.0, ya_, sx1 - 1.0, ya_ + pvs * 0.8, zt + crown + 0.15, zt + crown + min(0.6, room - 0.1), 0.05)
    for i in range(int((sy1 - sy0) / 2.2)):
        y = sy0 + 1.1 + i * 2.2
        for xx, face in ((sx0 - 0.06, "left"), (sx1 + 0.06, "right")):
            g.fringe(xx, y, zt + crown, rng.uniform(1.4, 2.2), rng.uniform(0.8, 2.0), face)
    for xx in (sx0 + T * 0.3, sx0 + T * 0.7):
        g.fringe(xx, sy0 - 0.06, zt + crown, 2.0, rng.uniform(0.8, 2.0), "front")

    # ---- podium roof garden -----------------------------------------------------------------------
    def on_slab(x, y, mm=0.8):
        return _inside(x, y, (sx0, sy0, sx1, sy1), mm)

    # lawn + planting beds on the roof ring, a pergola along the street edge
    for (a, b_, c, e) in ((px0, py0, px1, fy0), (px0, fy1, px1, py1), (px0, fy0, fx0, fy1), (fx1, fy0, px1, fy1)):
        k.box(roofg, a + 0.4, b_ + 0.4, zp, c - 0.4, e - 0.4, zp + 0.08)
    # parapet planters on the outer edge (spilling)
    for (a, b_, c, e, face) in ((px0, py0, px1, py0 + 0.6, "front"), (px0, py1 - 0.6, px1, py1, "back"),
                                (px0, py0, px0 + 0.6, py1, "left"), (px1 - 0.6, py0, px1, py1, "right")):
        k.box(stone, a, b_, zp, c, e, zp + 0.55)
        Lf = max(c - a, e - b_)
        for i in range(int(Lf / 2.0)):
            t = (i + 0.5) * Lf / int(Lf / 2.0)
            if face in ("front", "back"):
                x, y = a + t, (b_ - 0.05 if face == "front" else e + 0.05)
                if on_slab(x, y):
                    continue
                g.fringe(x, y, zp + 0.55, 1.8, rng.uniform(0.8, 2.2), face, 0.2)
                if i % 2 == 0:
                    g.puff(x, (b_ + e) / 2, zp + 0.5, 0.75, 0.5, 0.4, 0.4)
            else:
                x, y = (a - 0.05 if face == "left" else c + 0.05), b_ + t
                if on_slab(x, y):
                    continue
                g.fringe(x, y, zp + 0.55, 1.8, rng.uniform(0.8, 2.2), face, 0.2)
                if i % 2 == 0:
                    g.puff((a + c) / 2, y, zp + 0.5, 0.5, 0.75, 0.4, 0.4)
    # the court rim: planters with curtains into the court
    for (a, b_, c, e) in ((fx0 - 0.5, fy0 - 0.5, fx1 + 0.5, fy0), (fx0 - 0.5, fy1, fx1 + 0.5, fy1 + 0.5)):
        k.box(stone, a, b_, zp, c, e, zp + 0.5)
    # a timber pergola (with sail) and clipped cushions, trees in tubs
    tries = 0
    ntree = 0
    while ntree < max(2, int(w * d / 220)) and tries < 120:
        tries += 1
        x, y = rng.uniform(px0 + 1.5, px1 - 1.5), rng.uniform(py0 + 1.5, py1 - 1.5)
        if on_slab(x, y, 2.2) or _inside(x, y, court, 2.0):
            continue
        k.cyl(stone, x, y, zp, 0.9, 1.0, 0.6, 10)
        g.tree(x, y, zp + 0.6, rng.uniform(3.0, 4.5), rng.uniform(1.3, 1.9), 0.4)
        ntree += 1
    tries = 0
    nbed = 0
    while nbed < int(w * d / 48) and tries < 400:
        tries += 1
        x, y = rng.uniform(px0 + 1.0, px1 - 1.0), rng.uniform(py0 + 1.0, py1 - 1.0)
        if on_slab(x, y, 0.8) or _inside(x, y, court, 0.8):
            continue
        s_ = rng.uniform(0.5, 0.95)
        g.puff(x, y, zp + 0.05, s_, s_, s_ * 0.55, 0.4)
        nbed += 1
    pg0, pg1 = (sx1 + 1.5, px1 - 1.0) if side == 0 else (px0 + 1.0, sx0 - 1.5)
    if pg1 - pg0 > 4:
        npg, pgs = _span(pg1 - pg0, 2.6)
        for i in range(npg + 1):
            x = pg0 + i * pgs
            for y in (py0 + 1.2, py0 + 3.6):
                k.box(wood, x - 0.07, y - 0.07, zp, x + 0.07, y + 0.07, zp + 2.6)
            k.box(wood, x - 0.05, py0 + 1.0, zp + 2.6, x + 0.05, py0 + 3.8, zp + 2.75)
            g.fringe(x, py0 + 1.1, zp + 2.6, 1.6, rng.uniform(0.8, 1.8), "front", 0.3)
        k.box(wood, pg0, py0 + 1.13, zp + 2.75, pg1, py0 + 1.27, zp + 2.85)
        k.box(wood, pg0, py0 + 3.53, zp + 2.75, pg1, py0 + 3.67, zp + 2.85)
        k.slope(pv, pg0, py0 + 1.0, pg1, py0 + 3.8, zp + 2.85, zp + 3.25, 0.06)
    # ---- street edge: lamps + cushions -------------------------------------------------------------
    for i in range(max(2, int(w / 10))):
        x = 2.0 + i * (w - 4.0) / max(1, int(w / 10) - 1)
        _lamp(k, dark, lit, x, 0.4)
    return k


# =========================================================================================================
# Barbican terrace
# =========================================================================================================
def _lunette(k, s, xa, xb, y, z, rise, out, segs=8):
    """Fill the half-ellipse end of a vault (span xa..xb, springing at z) in the plane y, facing out (-1/+1)."""
    cx, hw = (xa + xb) / 2, (xb - xa) / 2
    pts = [(cx - math.cos(math.pi * i / segs) * hw, z + math.sin(math.pi * i / segs) * rise) for i in range(segs + 1)]
    for i in range(segs):
        (ax_, az), (bx_, bz) = pts[i], pts[i + 1]
        if out < 0:
            k.tri(s, (cx, y, z), (bx_, y, bz), (ax_, y, az), (0, -1, 0))
        else:
            k.tri(s, (cx, y, z), (ax_, y, az), (bx_, y, bz), (0, 1, 0))


def barbican_terrace(plot):
    """Chamberlin, Powell and Bon's Barbican terrace blocks (London, 1965-76).

    A long block raised over a highwalk podium, both long faces wrapped in continuous balconies whose
    board-marked concrete fronts have rounded lips and carry planting troughs that overflow, cross walls
    marking each flat, and a top floor of barrel vaults whose arched ends line the skyline. At the foot,
    an arcade of columns and a water garden. Solarpunk: every trough spills, the vault shoulders carry PV,
    the gutters between the vaults are planted."""
    rng = plot.rng
    w, d, H = plot.w, plot.d, plot.h_max
    k = Kit(w, d)
    g = Green(k, rng, 590)
    pal = plot.palette

    conc = k.mat("Plain", (220, 206, 184))
    board = k.mat("RammedEarth", (226, 214, 196))         # board-marked balcony fronts: horizontal strata
    shade = k.mat("Plain", CONC_SHADE)
    glass = k.mat("SolarGlass", GLASS, 400.0)   # scale 400: smooth window glass (scale 0 is the PV grid)
    lit = k.mat("Lantern", LIT)
    wood = k.mat("Timber", _mix((150, 100, 62), pal[2], 0.2))   # dark hardwood window frames
    roofg = k.mat("GreenRoof", GREENROOF)
    water = k.mat("Water", (64, 118, 128))
    pv = k.mat("SolarGlass", PV)
    accent = k.mat("Fabric", _vivid(pal[rng.randrange(3)], 0.45, 0.85))

    # ---- massing -------------------------------------------------------------------------------------
    x0, x1 = 2.0, w - 2.0
    pod = H >= 16.5                       # a highwalk podium when there's height for it
    zpod = 3.8 if pod else 0.0
    fh = 3.0
    span_v = 6.0                          # barrel vault span (top floor)
    rise = 1.7
    n = _clamp(int((H - 0.2 - zpod - rise) / fh), 3, 6)    # balconied floors; the last one is vaulted
    if plot.floors > 0:
        n = _clamp(plot.floors - pod, 3, n)
    bd = 1.6                              # balcony depth
    D = _clamp(d - 5.5, 8.5, 14.0)        # enclosed depth
    yb0 = _clamp((d - D) * 0.55, 2.4, 5.0)  # front balcony line
    yw0, yw1 = yb0 + bd, yb0 + bd + D - 2 * bd   # wall lines (balconies inside the D)
    yb1 = yw1 + bd
    zf = zpod                             # first floor level
    zv = zf + n * fh                      # roof slab = vault springing
    ztop = zv
    rise = _clamp(H - 0.2 - zv, 1.7, 2.6)    # spare height goes into the arches
    nb, b = _span(x1 - x0, 7.2)           # flats: cross-wall spacing
    k.solid(x0, yw0, zf, x1, yw1, zv + rise)

    # ---- balconied floors ------------------------------------------------------------------------------
    for side, (yo, yw, out) in enumerate(((yb0, yw0, -1), (yb1, yw1, 1))):
        ya, yb = min(yo, yw), max(yo, yw)
        face = "front" if out < 0 else "back"
        for f in range(n + 1):
            z = zf + f * fh
            # the slab, with its rounded lip
            k.box(conc, x0, ya, z - 0.36, x1, yb, z)
            k.pole(conc, (x0, yo, z - 0.18), (x1, yo, z - 0.18), 0.2, 8)
            if f == n:
                break
            # board-marked front upstand + rounded coping
            k.box(board, x0, yo - 0.14, z, x1, yo + 0.14, z + 1.1)
            k.pole(conc, (x0, yo, z + 1.1), (x1, yo, z + 1.1), 0.17, 8)
            # the wall behind: glass in dark timber frames, lights, a few awnings
            nm_, ms = _span(x1 - x0, 1.8)
            gaps = []
            i = 0
            while i < nm_:
                if rng.random() < 0.13:          # an open pane onto a lit room (one or two frames wide)
                    c = min(nm_, i + 1 + (rng.random() < 0.4))
                    ga, gb = x0 + i * ms + 0.06, x0 + c * ms - 0.06
                    gaps.append((ga, gb))
                    _room(k, wood, lit, "y", yw, out, ga, gb, z, z + fh - 0.36, 2.0, c - i)
                    i = c
                i += 1
            _glazing(k, glass, "y", yw, out, x0, x1, z, z + fh - 0.28, gaps, 0.08)
            for i in range(nm_ + 1):
                x = x0 + i * ms
                k.box(wood, x - 0.06, min(yw, yw + out * 0.05), z, x + 0.06, max(yw, yw + out * 0.05), z + fh - 0.28)
            k.box(wood, x0, min(yw, yw + out * 0.05), z + 2.1, x1, max(yw, yw + out * 0.05), z + 2.2)
            for i in range(nb):
                r_ = rng.random()
                xa = x0 + i * b + rng.uniform(0.6, b * 0.45)
                if r_ > 0.86 and side == 0:
                    k.slope(accent, xa, yw - 1.0, xa + rng.uniform(2.0, 3.4), yw, z + 2.35, z + 2.6, 0.03)
        # cross walls: one tall fin per flat, from the first floor to the top floor
        for i in range(nb + 1):
            x = x0 + i * b
            k.box(board, x - 0.17, ya - (0.2 if out < 0 else 0), zf - 0.28, x + 0.17, yb + (0.2 if out > 0 else 0), ztop)

    # ---- the vaults: a row of barrels across the full depth, their arched ends over the top balconies -----
    nv, vs = _span(x1 - x0, span_v)
    for i in range(nv + 1):
        x = x0 + i * vs
        k.box(conc, x - 0.25, yb0, zv, x + 0.25, yb1, zv + 0.35)
    for i in range(nv):
        xa, xc = x0 + i * vs, x0 + (i + 1) * vs
        k.vault(conc, xa, yb0 - 0.15, zv, xc, yb1 + 0.15, zv, rise, False, 0.22, 10)
        for yy, o in ((yb0 - 0.15, -1), (yb1 + 0.15, 1)):
            _lunette(k, glass, xa + 0.22, xc - 0.22, yy + (0.06 if o < 0 else -0.06), zv, rise - 0.22, o, 8)
            k.box(wood, (xa + xc) / 2 - 0.06, min(yy, yy - o * 0.1), zv, (xa + xc) / 2 + 0.06, max(yy, yy - o * 0.1), zv + rise - 0.25)
        # PV on the vault shoulder, planting in the gutter beside it
        if rng.random() < 0.65:
            ang = math.degrees(math.atan(0.577 * rise / (vs / 2)))   # tangent to the arch at a quarter span
            k.obox(pv, xa + vs * 0.25, (yb0 + yb1) / 2, zv + rise * 0.87 + 0.08, vs * 0.16, (yb1 - yb0) * 0.42, 0.04, ang, 0, 0)
        for yy in (yb0 + 0.8, (yb0 + yb1) / 2, yb1 - 0.8):
            if rng.random() < 0.6:
                g.puff(xa, yy, zv + 0.3, 0.6, 0.9, 0.5, 0.3)
    # gable ends of the block: solid board-marked walls with a slot
    for xe, o in ((x0, -1), (x1, 1)):
        k.box(board, xe - (0.3 if o < 0 else 0), yw0, zf - 0.36, xe + (0.3 if o > 0 else 0), yw1, zv + 0.35)
        k.box(glass, xe + o * 0.31 - 0.02, (yw0 + yw1) / 2 - 0.5, zf + 0.8, xe + o * 0.31 + 0.02, (yw0 + yw1) / 2 + 0.5, zv - 0.6)

    # ---- the foot: arcade + highwalk + water garden ----------------------------------------------------
    if pod:
        # ground floor recessed behind thick round columns; shopfronts lit
        sg = []
        for i in range(int((x1 - x0) / 7)):
            xa = x0 + 2 + i * 7 + rng.uniform(0, 2)
            if xa + 3 < x1 - 0.6 and rng.random() < 0.55:
                sg.append((xa, xa + rng.uniform(2.0, 3.2)))
        _glazing(k, glass, "y", yw0 + 1.8, -1, x0 + 0.5, x1 - 0.5, 0, zpod - 0.36, sg, 0.1)
        for ga, gb in sg:
            _room(k, wood, lit, "y", yw0 + 1.8, -1, ga, gb, 0.0, zpod - 0.36, 2.4, 2)
        k.box(shade, x0 + 0.5, yw0 + 4.3, 0, x1 - 0.5, yw1 - 0.5, zpod - 0.36)
        k.solid(x0 + 0.5, yw0 + 1.8, 0, x1 - 0.5, yw1 - 0.5, zpod)
        for i in range(nb + 1):
            x = x0 + i * b
            for yy in (yb0 + 0.4, yw1 - 0.4):
                k.cyl(conc, x, yy, 0, 0.42, 0.42, zpod - 0.28, 12, False)
        # highwalk: a deck along the front with a balustrade, over a water garden
        hy0 = 0.6
        k.box(conc, 0.4, hy0, zpod - 0.3, w - 0.4, yb0, zpod)
        k.box(board, 0.4, hy0, zpod, w - 0.4, hy0 + 0.25, zpod + 1.05)
        k.pole(conc, (0.4, hy0 + 0.12, zpod + 1.05), (w - 0.4, hy0 + 0.12, zpod + 1.05), 0.15, 8)
        k.pole(conc, (0.4, hy0, zpod - 0.15), (w - 0.4, hy0, zpod - 0.15), 0.18, 8)
        nc, cs = _span(w - 2.0, 7.0)
        for i in range(nc + 1):
            k.cyl(conc, 1.0 + i * cs, hy0 + 0.9, 0, 0.32, 0.32, zpod - 0.3, 10, False)
        # water garden at the foot of the highwalk
        k.box(water, 1.0, hy0 + 1.4, 0.0, w - 1.0, yb0 - 0.2, 0.08)
        for i in range(int(w / 3.0)):
            x = rng.uniform(1.2, w - 1.2)
            if rng.random() < 0.5:
                k.plant("Reed", "Foliage", rng.choice(LEAVES), x, rng.uniform(hy0 + 1.6, yb0 - 0.4), 0.05,
                        rng.uniform(0.8, 1.3), rng.uniform(0.8, 1.3), rng.uniform(0.9, 1.5), rng.uniform(0, 360), False, 200)
        # highwalk planters: troughs on the balustrade
        for i in range(int((w - 1.0) / 2.6)):
            x = 1.0 + i * 2.6 + rng.uniform(-0.3, 0.3)
            g.fringe(x, hy0 - 0.04, zpod + 1.05, rng.uniform(1.8, 2.6), rng.uniform(1.4, 3.2), "front", 0.2)
            if i % 2 == 0:
                g.puff(x, hy0 + 0.4, zpod + 0.95, 0.9, 0.5, 0.45, 0.4)
        for i in range(int(w / 9)):
            x = 3 + i * 9 + rng.uniform(-1, 1)
            if x < w - 2:
                _lamp(k, shade, lit, x, hy0 + 1.0, zpod, 2.8)
    else:
        # low version: a water garden and lawn in front, the ground floor is a home floor
        if yb0 > 3.2:
            k.box(water, 1.0, 0.6, 0.0, w - 1.0, yb0 - 0.9, 0.08)
        else:
            g.bed(0.8, 0.4, w - 0.8, yb0 - 0.6, 0, int(w / 2.2), (0.5, 0.9), 0.35)
        for i in range(int(w / 2.5)):
            x = rng.uniform(1.0, w - 1.0)
            k.plant("Reed", "Foliage", rng.choice(LEAVES), x, rng.uniform(0.7, max(0.8, yb0 - 1.0)), 0.05,
                    rng.uniform(0.8, 1.3), rng.uniform(0.8, 1.3), rng.uniform(0.9, 1.5), rng.uniform(0, 360), False, 200)
    # a half-round stair tower on the back
    xs = x0 + (x1 - x0) * rng.choice((0.25, 0.5, 0.75))
    if d - yb1 > 2.2:
        k.cyl(board, xs, yb1 + 0.4, 0, 1.9, 1.9, zv + 0.6, 16)
        k.box(glass, xs - 0.25, yb1 + 0.4 + 1.86, 1.0, xs + 0.25, yb1 + 0.4 + 1.93, zv - 0.4)
        k.solid(xs - 1.9, yb1 - 1.5, 0, xs + 1.9, yb1 + 2.3, zv + 0.6)

    # ---- planting: troughs on every balcony (budgeted) ---------------------------------------------
    for i in range(int(w / 16)):
        x = rng.uniform(2, w - 2)
        if d - yb1 > 3.0:
            g.tree(x, rng.uniform(yb1 + 1.5, d - 1.0), 0, rng.uniform(4.5, 7.0), rng.uniform(1.6, 2.3), 0.35)
    if d - yb1 > 1.5:
        g.bed(1.0, yb1 + 0.6, w - 1.0, d - 0.3, 0, int(w / 4), (0.6, 1.1), 0.3)
    nrun = 2 * n * (x1 - x0) / 2.6
    per = _clamp((g.left - 2) / max(1.0, nrun), 0.2, 1.6)
    for side, (yo, out) in enumerate(((yb0, -1), (yb1, 1))):
        face = "front" if out < 0 else "back"
        dens = per * (1.25 if side == 0 else 0.75)
        for f in range(n):
            z = zf + f * fh + 1.1
            x = x0 + 0.4
            while x < x1 - 0.4:
                step = rng.uniform(2.0, 3.0)
                q = dens
                while q > 0:
                    if rng.random() < min(1.0, q):
                        xx = x + rng.uniform(0, step)
                        if rng.random() < 0.6:
                            g.fringe(min(xx, x1 - 0.8), yo + out * 0.19, z + 0.12, rng.uniform(1.6, 2.8), rng.uniform(1.0, 2.7), face, 0.13)
                        else:
                            g.puff(min(xx, x1 - 0.8), yo - out * 0.05, z + 0.05, rng.uniform(0.7, 1.1), 0.38, 0.42, 0.35)
                    q -= 1.0
                x += step
    return k


KINDS = {
    "unite_habitation": unite_habitation,
    "habitat67": habitat67,
    "lever_slab": lever_slab,
    "barbican_terrace": barbican_terrace,
}

SIZES = {
    "unite_habitation": {"w": (60, 140), "d": (16, 24), "h": (18, 24), "floors": (4, 6), "use": "homes"},
    "habitat67": {"w": (30, 80), "d": (20, 40), "h": (12, 24), "floors": (3, 7), "use": "homes"},
    "lever_slab": {"w": (30, 60), "d": (20, 40), "h": (18, 30), "floors": (4, 8), "use": "homes + studios"},
    "barbican_terrace": {"w": (40, 120), "d": (14, 22), "h": (12, 21), "floors": (3, 7), "use": "homes"},
}
