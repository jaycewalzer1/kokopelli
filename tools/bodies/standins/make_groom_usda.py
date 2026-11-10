"""Writes standin_hair.usda: a small hair cap (BasisCurves under a GroomAPI prim) for the m6 groom tests.
Centred on the origin (attached to the 'head' bone), z up, cm. Plain text USD, no pxr needed."""
import math, random, sys
from pathlib import Path
rng = random.Random(7)
counts, pts = [], []
for _i in range(400):
    # roots on the upper half of a 10 cm sphere, strands falling outwards and down
    u, v = rng.random() * 2 * math.pi, rng.uniform(0.05, 1.0)
    th = math.acos(v)
    r = 10.0
    root = (r * math.sin(th) * math.cos(u), r * math.sin(th) * math.sin(u), r * math.cos(th))
    n = [c / r for c in root]
    seg = 6
    counts.append(seg)
    for k in range(seg):
        t = k / (seg - 1)
        L = 8.0 * t
        pts.append((root[0] + n[0] * L * 0.6, root[1] + n[1] * L * 0.6, root[2] + n[2] * L * 0.3 - 6.0 * t * t))
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name('standin_hair.usda'))
fmt = lambda p: '(%.3f, %.3f, %.3f)' % p
out.write_text(f'''#usda 1.0
(
    defaultPrim = "StandinHair"
    metersPerUnit = 0.01
    upAxis = "Z"
)

def Xform "StandinHair" (
    prepend apiSchemas = ["GroomAPI"]
)
{{
    def BasisCurves "Strands"
    {{
        uniform token type = "linear"
        int[] curveVertexCounts = [{", ".join(map(str, counts))}]
        point3f[] points = [{", ".join(map(fmt, pts))}]
        float[] widths = [0.08] (interpolation = "constant")
    }}
}}
''')
print(out, len(counts), 'curves')
