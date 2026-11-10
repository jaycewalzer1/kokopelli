"""Reference kind showing the Kit idioms (not used in the city plan): a raised glass pavilion with a butterfly roof."""
from .kit import Kit, WHITE, GLASS, TERRAZZO, LEAF, FLOWER, DARK_STEEL


def example_pavilion(plot):
    k = Kit(plot.w, plot.d)
    rng = plot.rng
    white = k.mat("Metal", WHITE)          # painted steel
    glass = k.mat("SolarGlass", GLASS)
    floor = k.mat("PermeableStone", TERRAZZO)
    dark = k.mat("Plain", DARK_STEEL)
    # footprint inset from the plot edges
    x0, y0, x1, y1 = 3.0, 4.0, plot.w - 3.0, plot.d - 3.0
    lift, fh = 1.2, 3.2
    # raised floor slab + roof structure on a column grid
    k.box(floor, x0, y0, lift, x1, y1, lift + 0.35)
    n = max(2, int((x1 - x0) / 6) + 1)
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        for y in (y0, y1):
            k.box(white, x - 0.12, y - 0.12, 0, x + 0.12, y + 0.12, lift + fh + 0.3)
    # glass walls set back 1 m from the columns, with mullions
    gx0, gy0, gx1, gy1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
    z0, z1 = lift + 0.35, lift + fh
    k.box(glass, gx0, gy0, z0, gx1, gy0 + 0.04, z1)
    k.box(glass, gx0, gy1 - 0.04, z0, gx1, gy1, z1)
    k.box(glass, gx0, gy0, z0, gx0 + 0.04, gy1, z1)
    k.box(glass, gx1 - 0.04, gy0, z0, gx1, gy1, z1)
    m = int((gx1 - gx0) / 1.5)
    for i in range(m + 1):
        x = gx0 + (gx1 - gx0) * i / m
        k.box(dark, x - 0.03, gy0 - 0.03, z0, x + 0.03, gy0 + 0.03, z1)
    # butterfly roof: two slopes meeting low in the middle
    ym = (y0 + y1) / 2
    k.slope(white, x0 - 0.5, y0 - 0.8, x1 + 0.5, ym, z1 + 0.9, z1 + 0.3, t=0.25)
    k.slope(white, x0 - 0.5, ym, x1 + 0.5, y1 + 0.8, z1 + 0.3, z1 + 0.9, t=0.25)
    # steps and planting
    k.box(floor, (x0 + x1) / 2 - 1.5, y0 - 1.6, 0, (x0 + x1) / 2 + 1.5, y0, lift * 0.5)
    k.box(floor, (x0 + x1) / 2 - 1.5, y0 - 0.8, lift * 0.5, (x0 + x1) / 2 + 1.5, y0, lift + 0.35)
    for _ in range(10):
        x, y = rng.uniform(0.5, plot.w - 0.5), rng.uniform(0.5, 2.5)
        k.plant("Puff", "Foliage", rng.choice(LEAF), x, y, 0.2, 0.7, 0.7, 0.5, rng.uniform(0, 360))
        if rng.random() < 0.4:
            k.plant("Blob", "Foliage", rng.choice(FLOWER), x, y, 0.75, 0.25, 0.25, 0.18)
    k.solid(gx0, gy0, 0, gx1, gy1, z1)
    return k


KINDS = {"example_pavilion": example_pavilion}
SIZES = {"example_pavilion": {"w": (16, 40), "d": (12, 24), "h": (5, 7), "floors": (1, 1), "use": "studio"}}
