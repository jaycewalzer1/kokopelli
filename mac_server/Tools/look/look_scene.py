"""Spawn the look-dev vignette on the port-9002 instance and capture lit PNGs.

    simworld/.venv/bin/python Tools/look_scene.py <out_dir> [--no-spawn] [--shots a,b]
"""
import sys
import time
from pathlib import Path

from unrealcv import Client

M = "/Game/Solarpunk/Materials/"
SH = "/Engine/BasicShapes/"
c = Client(("127.0.0.1", 9002))
assert c.connect(), "no connection"


def req(cmd):
    r = c.request(cmd)
    if isinstance(r, str) and r.lower().startswith("error"):
        print("ERR", cmd, "->", r)
    return r


n = 0


def obj(mesh, mat, loc, scale, rot=(0, 0, 0), vec=None, scal=None):
    """Spawn a BasicShape with a Solarpunk material. loc in cm, scale in BasicShape units (1 = 100 cm)."""
    global n
    n += 1
    name = f"LK{n:03d}"
    req(f"vset /objects/spawn StaticMeshActor {name}")
    req(f"vset /object/{name}/mesh {SH}{mesh}.{mesh}")
    req(f"vset /object/{name}/material {M}{mat}.{mat}")
    req(f"vset /object/{name}/location {loc[0]} {loc[1]} {loc[2]}")
    req(f"vset /object/{name}/rotation {rot[0]} {rot[1]} {rot[2]}")
    req(f"vset /object/{name}/scale {scale[0]} {scale[1]} {scale[2]}")
    for k, v in (vec or {}).items():
        req(f"vset /object/{name}/mat_vector {k} {v[0]} {v[1]} {v[2]}")
    for k, v in (scal or {}).items():
        req(f"vset /object/{name}/mat_scalar {k} {v}")
    return name


def box(mat, x0, y0, z0, x1, y1, z1, **kw):
    """Axis-aligned box from min/max corners (cm)."""
    return obj("Cube", mat, ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), ((x1 - x0) / 100, (y1 - y0) / 100, (z1 - z0) / 100), **kw)


def tree(x, y, h=900, r=320, seed=0):
    obj("Cylinder", "M_Bark", (x, y, h * 0.35), (0.45, 0.45, h * 0.7 / 100))
    import random
    rnd = random.Random(seed)
    for i in range(6):
        dx, dy, dz = rnd.uniform(-1, 1) * r * 0.55, rnd.uniform(-1, 1) * r * 0.55, rnd.uniform(-0.3, 0.4) * r
        s = rnd.uniform(0.6, 0.95) * r * 2 / 100
        obj("Sphere", "M_Foliage", (x + dx, y + dy, h * 0.78 + dz), (s, s, s * 0.85),
            vec={"Tint": (rnd.uniform(0.85, 1.1), rnd.uniform(0.9, 1.1), rnd.uniform(0.8, 1.0))})


def spawn():
    # ground: meadow, gravel path, paver plaza, pond
    box("M_GreenRoof", -6000, -6000, -2, 6000, 6000, 1, scal={"Scale": 90})
    box("M_Path", -6000, 300, 0, 6000, 650, 3)
    box("M_PermeableStone", -1500, -1800, 0, 1600, 300, 4)
    box("M_Water", 1800, 900, -30, 4200, 2600, 2)
    box("M_RammedEarth", 1750, 850, -30, 4250, 900, 12)   # pond rim
    # building: rammed earth base, CLT upper floors, bronze columns, solar glass pitched roof, green roof deck
    box("M_RammedEarth", -1200, -1600, 4, 600, -400, 380)
    box("M_RammedEarth", 600, -1600, 4, 1300, -900, 380, vec={"Tint": (1.05, 0.9, 0.9)})
    box("M_Timber", -1200, -1600, 380, 600, -500, 1100)
    box("M_SolarGlass", -1100, -505, 450, 500, -495, 1000)                 # south-ish glazing band
    box("M_Timber", -1250, -1650, 1100, 650, -450, 1130)                  # slab edge
    box("M_GreenRoof", -1200, -1600, 1130, -300, -500, 1180, scal={"Scale": 40})
    obj("Cube", "M_SolarGlass", (150, -1050, 1300), (9.0, 11.0, 0.12), rot=(0, 0, 25))  # tilted PV roof
    for i in range(5):
        obj("Cylinder", "M_Metal", (-1100 + i * 400, -330, 190), (0.22, 0.22, 3.7))
    box("M_Metal", -1150, -350, 370, 550, -310, 390, scal={"Patina": 0.6})
    obj("Cube", "M_Fabric", (-300, -200, 400), (16.0, 3.4, 0.05), rot=(0, 0, 20), vec={"Tint": (1.0, 0.75, 0.6)})
    # moss cushions on rocks, steel bench, lanterns along the path
    obj("Sphere", "M_Moss", (1200, 100, 30), (2.2, 1.6, 0.9))
    obj("Sphere", "M_Moss", (1450, 0, 20), (1.2, 1.0, 0.6))
    box("M_Metal", 200, 150, 40, 700, 220, 48, scal={"Steel": 1.0, "Patina": 0.3})
    box("M_Timber", 200, 150, 48, 700, 230, 56, scal={"Scale": 9})
    for i in range(8):
        x = -2400 + i * 650
        obj("Cylinder", "M_Metal", (x, 680, 35), (0.06, 0.06, 0.7), scal={"Steel": 1.0})
        obj("Sphere", "M_Lantern", (x, 680, 78), (0.22, 0.22, 0.26))
    # living facade: vine curtains down the CLT, planters, a second green-roofed block with cascading plants
    for i in range(7):
        x = -1100 + i * 260
        box("M_Foliage", x, -505, 700 + (i % 3) * 90, x + 90, -470, 1130, scal={"Scale": 6})
    box("M_Foliage", 605, -1500, 420, 640, -620, 1100, scal={"Scale": 7})          # east living wall
    for i in range(4):
        x = -1300 + i * 800
        box("M_Timber", x, 50, 4, x + 300, 220, 70, scal={"Scale": 10})
        obj("Sphere", "M_Foliage", (x + 150, 135, 95), (2.9, 1.6, 1.1), scal={"Scale": 6})
    box("M_RammedEarth", -4200, -2600, 0, -2400, -1200, 450, vec={"Tint": (1.08, 0.88, 0.85)})
    box("M_Timber", -4200, -2600, 450, -2400, -1200, 900)
    box("M_GreenRoof", -4250, -2650, 900, -2350, -1150, 960, scal={"Scale": 35})
    for i in range(6):
        obj("Sphere", "M_Foliage", (-4150 + i * 340, -1150, 860), (1.6, 0.9, 1.6), scal={"Scale": 6})
    box("M_SolarGlass", -4100, -1205, 520, -2500, -1195, 850)
    obj("Cube", "M_Fabric", (-3300, -1050, 430), (16.0, 3.0, 0.05), rot=(0, 0, 20), vec={"Tint": (0.65, 0.85, 0.8)})
    # trees
    tree(-2000, -2300, seed=1)
    tree(2300, -600, h=1100, r=380, seed=2)
    tree(-2900, 1500, h=800, seed=3)
    tree(4600, 1800, h=1000, r=360, seed=4)
    tree(900, 1600, h=700, r=260, seed=5)
    # distant blocks so fog/aerial perspective has something to work on
    for i, (x, y) in enumerate([(-5000, -5000), (0, -5200), (5200, -4200), (5400, 4500), (-5400, 3500)]):
        box("M_RammedEarth" if i % 2 else "M_Timber", x - 600, y - 600, 0, x + 600, y + 600, 1500 + 400 * i)
        box("M_GreenRoof", x - 600, y - 600, 1500 + 400 * i, x + 600, y + 600, 1560 + 400 * i)
        tree(x + 900, y + 400, seed=10 + i)


SHOTS = {
    # name: (x, y, z, pitch, yaw, fov)
    "hero": (3400, 3400, 420, -6, -135, 75),        # from the SE-ish across the pond to the building
    "street": (-3600, 480, 170, -2, 5, 80),          # eye level along the lantern path, sun from the side
    "facade": (-200, 900, 600, -12, -95, 70),        # facing the building's south face
    "aerial": (5200, 4800, 3800, -32, -138, 70),     # overview
    "backlit": (-300, -3900, 230, 3, 128, 80),
    "frontlit": (-3300, 2600, 380, -4, -40, 70),       # sun behind camera, south/west faces lit       # looking toward the sun, foliage/awning translucency
    "detail": (1500, 450, 160, -20, -150, 60),       # moss, pavers, bench close-up
}


def capture(out, only=None):
    out.mkdir(parents=True, exist_ok=True)
    req("vset /camera/0/size 1280 720")
    times = {}
    for name, (x, y, z, p, yw, fov) in SHOTS.items():
        if only and name not in only:
            continue
        req(f"vset /camera/0/location {x} {y} {z}")
        req(f"vset /camera/0/rotation {p} {yw} 0")
        req(f"vset /camera/0/fov {fov}")
        req("vget /camera/0/lit png")  # warm-up (Lumen/VSM/temporal history settle)
        time.sleep(1.5)
        req("vget /camera/0/lit png")
        t0 = time.time()
        data = c.request("vget /camera/0/lit png")
        times[name] = time.time() - t0
        (out / f"{name}.png").write_bytes(data)
    print("capture s:", {k: round(v, 3) for k, v in times.items()})
    print("fps/ms:", req("vget /look/fps"))


if __name__ == "__main__":
    out = Path(sys.argv[1])
    only = None
    if "--shots" in sys.argv:
        only = sys.argv[sys.argv.index("--shots") + 1].split(",")
    if "--no-spawn" not in sys.argv:
        spawn()
        time.sleep(8)  # shader / distance-field / Lumen warm-up
    capture(out, only)
