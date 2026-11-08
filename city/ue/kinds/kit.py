"""Kit: author a building as builder ops in Python, sent to ASWCityKit (mac_server .../City/SWCityKit.cpp).

A kind module draws into a Kit in its plot's LOCAL frame, in metres:
    x  0..plot.w along the street frontage (RIGHT to left as seen from the street; left to right from inside looking out)
    y  0..plot.d away from the street (y = 0 is the front line, the street is at y < 0)
    z  up from the ground (0)
Kit.config() turns that into the actor JSON: centimetres, origin at the plot centre, and the actor's yaw so local
-y points at the street, whichever side that is. Colours are sRGB 0-255 triples.

Materials (world-projected, no UVs, so any box size textures correctly): Timber, RammedEarth (also plaster /
render / painted walls when tinted), SolarGlass (all glazing), GreenRoof, Moss, Foliage, Bark, Water,
PermeableStone (concrete, terrazzo, stone, brick when tinted), Path, Metal (steel, bronze; green tint = verdigris),
Fabric (awnings, coloured panels), Lantern (emissive), Plain (flat colour, cheapest).

Instances (foliage etc.): prim in Blob, Trunk, Cube, Cylinder, Reed, Stone, Disc, Puff, Fringe, Cone; unit sizes
in SWCityMesh.h (Puff/Blob radius 100 cm, Cube 100 cm, Cylinder radius 50 x 100 tall, Fringe 100 wide x 100 down).
"""
import math

CM = 100.0
MATS = ("Timber", "RammedEarth", "SolarGlass", "GreenRoof", "Moss", "Foliage", "Bark", "Water", "PermeableStone",
        "Path", "Metal", "Fabric", "Lantern", "Plain")
PRIMS = ("Blob", "Trunk", "Cube", "Cylinder", "Reed", "Stone", "Disc", "Puff", "Fringe", "Cone")

# a few colours the kinds share (sRGB)
WHITE = (238, 236, 228)
OFFWHITE = (226, 220, 204)
CONCRETE = (188, 184, 174)
DARK_STEEL = (52, 54, 58)
GLASS = (150, 170, 176)
TERRAZZO = (214, 206, 190)
BRICK = (170, 92, 66)
TEAK = (150, 96, 58)
LEAF = ((62, 104, 46), (78, 124, 56), (96, 138, 60), (54, 92, 50))
FLOWER = ((214, 72, 84), (236, 132, 160), (240, 206, 80), (246, 242, 230), (170, 96, 190), (236, 120, 60))


class Kit:
    def __init__(self, w, d):
        self.w, self.d = float(w), float(d)
        self.slots, self._slot_ix = [], {}
        self.ops, self.inst, self.collide = [], [], []

    # ---- materials ---------------------------------------------------------------------------------
    def mat(self, name, tint=WHITE, scale=0.0):
        """Slot index for (material, tint[, texture scale cm]). Reuse slots: each is one draw call."""
        assert name in MATS, name
        key = (name, tuple(int(round(v)) for v in tint), float(scale))
        if key not in self._slot_ix:
            self._slot_ix[key] = len(self.slots)
            self.slots.append({"mat": name, "tint": list(key[1]), **({"scale": scale} if scale else {})})
        return self._slot_ix[key]

    # ---- geometry (metres, local frame) ------------------------------------------------------------
    def _p(self, x, y, z=0.0):
        return [round((x - self.w / 2) * CM, 1), round((y - self.d / 2) * CM, 1), round(z * CM, 1)]

    def box(self, s, x0, y0, z0, x1, y1, z1, skip=0):
        """Axis box between two corners. skip bits: 1=-x 2=+x 4=-y(front) 8=+y(back) 16=bottom 32=top."""
        self.ops.append(["box", s, *self._p(x0, y0, z0), *self._p(x1, y1, z1)] + ([skip] if skip else []))

    def obox(self, s, cx, cy, cz, hx, hy, hz, pitch=0.0, yaw=0.0, roll=0.0):
        """Oriented box: centre, HALF extents, rotation in degrees (yaw about z)."""
        self.ops.append(["obox", s, *self._p(cx, cy, cz), hx * CM, hy * CM, hz * CM, pitch, yaw, roll])

    def beam(self, s, a, b, w, h):
        self.ops.append(["beam", s, *self._p(*a), *self._p(*b), w * CM, h * CM])

    def cyl(self, s, x, y, z, r0, r1, h, segs=12, caps=True):
        self.ops.append(["cyl", s, *self._p(x, y, z), r0 * CM, r1 * CM, h * CM, segs, 1 if caps else 0])

    def pole(self, s, a, b, r, segs=8):
        self.ops.append(["pole", s, *self._p(*a), *self._p(*b), r * CM, segs])

    def prism(self, s, pts, z0, z1, bottom=False):
        """Extruded convex (or star-shaped) polygon [(x, y), ...]."""
        flat = [v for x, y in pts for v in self._p(x, y)[:2]]
        self.ops.append(["prism", s, z0 * CM, z1 * CM, 1 if bottom else 0, *flat])

    def ribbon(self, s, pts, w, z0, z1, offset=0.0):
        flat = [v for x, y in pts for v in self._p(x, y)[:2]]
        self.ops.append(["ribbon", s, w * CM, z0 * CM, z1 * CM, offset * CM, *flat])

    def ell(self, s, cx, cy, cz, rx, ry, rz, segs=16, rings=8, hemi=False):
        self.ops.append(["ell", s, *self._p(cx, cy, cz), rx * CM, ry * CM, rz * CM, segs, rings, 1 if hemi else 0])

    def gable(self, s, x0, y0, z0, x1, y1, z1, ridge_h, along_x=True):
        """Triangular roof prism sitting on top of box [x0..x1, y0..y1] at z1, ridge ridge_h above it."""
        self.ops.append(["gable", s, *self._p(x0, y0, z0), *self._p(x1, y1, z1), ridge_h * CM, 1 if along_x else 0])

    def vault(self, s, x0, y0, z0, x1, y1, z1, rise, axis_x=True, t=0.15, segs=12):
        self.ops.append(["vault", s, *self._p(x0, y0, z0), *self._p(x1, y1, z1), rise * CM, 1 if axis_x else 0, t * CM, segs])

    def quad(self, s, a, b, c, d, n):
        """Planar quad a-b-c-d (around the edge) facing direction n (local axes)."""
        self.ops.append(["quad", s, *self._p(*a), *self._p(*b), *self._p(*c), *self._p(*d), *n])

    def tri(self, s, a, b, c, n):
        self.ops.append(["tri", s, *self._p(*a), *self._p(*b), *self._p(*c), *n])

    def slope(self, s, x0, y0, x1, y1, z_front, z_back, t=0.25):
        """Mono-pitch roof slab over [x0..x1, y0..y1] rising from z_front (y0 edge) to z_back (y1 edge).
        Use z_front > z_back for a roof falling to the back; two slopes meeting low = a butterfly roof."""
        dy, dz = y1 - y0, z_back - z_front
        ang = -math.degrees(math.atan2(dz, dy))  # UE roll is positive from +z toward -y here (render-verified)
        L = math.hypot(dy, dz)
        # rotation about local x (roll in UE terms for a box whose long side is y)
        self.obox(s, (x0 + x1) / 2, (y0 + y1) / 2, (z_front + z_back) / 2 + t / 2, (x1 - x0) / 2, L / 2, t / 2, 0, 0, ang)

    # ---- instances, collision ----------------------------------------------------------------------
    def plant(self, prim, mat, tint, x, y, z, sx, sy, sz, yaw=0.0, shadow=True, cull_m=0.0, pitch=0.0, roll=0.0):
        """Instanced primitive: scale is relative to the prim's unit size (Puff radius 1 m at scale 1). pitch/roll
        (degrees) lean it, e.g. a leaning Trunk or palm; they need the SWCityKit build from 2026-11-07 13:20 on."""
        assert prim in PRIMS and mat in MATS, (prim, mat)
        p = self._p(x, y, z)
        self.inst.append([prim, mat, *[int(v) for v in tint], *p, round(yaw, 1), round(sx, 3), round(sy, 3), round(sz, 3),
                          1 if shadow else 0, cull_m * CM] + ([round(pitch, 1), round(roll, 1)] if pitch or roll else []))

    def solid(self, x0, y0, z0, x1, y1, z1):
        """Collision box (walkers can't pass): give every enclosed mass one."""
        self.collide.append([*self._p(x0, y0, z0), *self._p(x1, y1, z1)])

    # ---- output ------------------------------------------------------------------------------------
    def config(self, rect_m, front, extra=None):
        """Actor JSON for a plot rect [x0, y0, x1, y1] (world metres) whose street side is front in N/S/E/W.
        For E/W fronts the plot's local w runs along world y."""
        x0, y0, x1, y1 = rect_m
        yaw = {"N": 0, "E": 90, "S": 180, "W": 270}[front]
        cfg = {"loc_cm": [round((x0 + x1) / 2 * CM, 1), round((y0 + y1) / 2 * CM, 1), 0], "yaw": yaw,
               "slots": self.slots, "ops": self.ops, "inst": self.inst, "collide": self.collide}
        if extra:
            cfg.update(extra)
        return cfg

    def stats(self):
        return {"slots": len(self.slots), "ops": len(self.ops), "inst": len(self.inst), "collide": len(self.collide)}


def plot_size(rect_m, front):
    """(w, d) of a plot in its local frame: w along the street."""
    x0, y0, x1, y1 = rect_m
    ex, ey = abs(x1 - x0), abs(y1 - y0)
    return (ex, ey) if front in ("N", "S") else (ey, ex)


def local_to_world(rect_m, front, x, y):
    """A local (x, y) of a plot back to world metres (for entrances, place markers)."""
    w, d = plot_size(rect_m, front)
    cx, cy = (rect_m[0] + rect_m[2]) / 2, (rect_m[1] + rect_m[3]) / 2
    lx, ly = x - w / 2, y - d / 2
    th = math.radians({"N": 0, "E": 90, "S": 180, "W": 270}[front])
    return (cx + lx * math.cos(th) - ly * math.sin(th), cy + lx * math.sin(th) + ly * math.cos(th))
