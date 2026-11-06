"""HLSL bodies for the realism pilot's materials (/Game/Realism/Materials/M_*_Real). Imported by make_realism.py.

Same contract as sp_hlsl.py (one Custom node, main output = base colour, extra outputs Rough/Nrm/Metal/SSS/Spec/Opac),
and the same Tint semantics (Tint is relative to SWCityMesh.cpp's RefColor), so the palette doesn't change. Inputs:
P (world cm), N (vertex normal WS), UV (TexCoord 0), Tint, Scale, Tc (photo colour, sRGB), Td (packed: normal x,y /
roughness / AO), Tn (T_SP_Noise for macro variation), Steel.

Photo detail is divided by the texture's own mean colour (realism_tex.py -> means.json) and multiplied by the
material's reference colour: the average colour stays the palette's, the photo adds only detail. Imperfections are
world-space and cheap: macro value variation (7-25 m), AO in cavities, weathering, rain streaks, moss.
"""
import json
from pathlib import Path

PRELUDE = r"""
struct RF
{
	float3 Wt(float3 n, float k) { float3 w = pow(abs(n), k); return w / (w.x + w.y + w.z + 1e-5); }
	float Lum(float3 c) { return dot(c, float3(0.3, 0.59, 0.11)); }
};
RF f;
N = normalize(N);
Rough = 0.8; Metal = 0; SSS = 0; Spec = 0.5; Nrm = N; Opac = 1;
float3 w = f.Wt(N, 6);
// Planar UVs per axis, u along the board/grain: floors (x, y); X-facing walls (z, y); Y-facing walls (z, x).
// Each projection's world axes (Ua, Ub, Nn) turn the tangent-space normal back into world space.
float2 uZ = P.xy, uX = P.zy, uY = P.zx;
"""

# Shared surface: triplanar photo colour + packed data with real normals, macro variation and AO. Expects
# MEAN, REF (float3 literals) and TILE (cm per texture repeat, scaled by Scale) substituted.
SURFACE = r"""
float S = TILE;
float4 cZ = Tc.Sample(TcSampler, uZ / S), cX = Tc.Sample(TcSampler, uX / S), cY = Tc.Sample(TcSampler, uY / S);
float4 dZ = Td.Sample(TdSampler, uZ / S), dX = Td.Sample(TdSampler, uX / S), dY = Td.Sample(TdSampler, uY / S);
float3 col = cX.rgb * w.x + cY.rgb * w.y + cZ.rgb * w.z;
float4 dat = dX * w.x + dY * w.y + dZ * w.z;
float3 tZ = float3(dZ.xy * 2 - 1, 1), tX = float3(dX.xy * 2 - 1, 1), tY = float3(dY.xy * 2 - 1, 1);
float3 nZ = normalize(tZ.x * float3(1, 0, 0) + tZ.y * float3(0, 1, 0) + tZ.z * float3(0, 0, sign(N.z)));
float3 nX = normalize(tX.x * float3(0, 0, 1) + tX.y * float3(0, 1, 0) + tX.z * float3(sign(N.x), 0, 0));
float3 nY = normalize(tY.x * float3(0, 0, 1) + tY.y * float3(1, 0, 0) + tY.z * float3(0, sign(N.y), 0));
Nrm = normalize(lerp(N, normalize(nX * w.x + nY * w.y + nZ * w.z), NSTR));
float3 c = col / MEAN * REF;
float ao = dat.a;
// macro variation: big soft patches of lighter/darker, warmer/cooler (what survives a 10x blur)
float4 m1 = Tn.Sample(TnSampler, (uZ * w.z + uX * w.x + uY * w.y) / 2500);
float4 m2 = Tn.Sample(TnSampler, (uZ * w.z + uX * w.x + uY * w.y) / 700 + 0.37);
float macro = 0.80 + 0.26 * m1.r + 0.16 * m2.b;
c *= macro * float3(1.0 + 0.05 * (m1.g - 0.5), 1.0, 1.0 - 0.06 * (m1.g - 0.5));
c *= lerp(1.0, ao, 0.85);
Rough = saturate(dat.b * ROUGHK);
float up = saturate(N.z);
float wall = 1 - saturate(abs(N.z) * 1.5);
"""

MOSS = r"""
// moss: on upward faces, in cavities and in big damp patches
float mz = saturate(up * 1.2) * smoothstep(0.55, 0.85, m2.g * 0.7 + (1 - ao) * 0.6 + m1.a * 0.3) * MOSSK;
c = lerp(c, float3(0.035, 0.07, 0.015) * (0.8 + 0.4 * m2.r), mz);
Rough = lerp(Rough, 0.9, mz);
"""

STREAKS = r"""
// rain streaks on walls: dark vertical runs, long in z
float st = Tn.Sample(TnSampler, float2((P.x + P.y) / 140, P.z / 2600)).a;
c *= lerp(1.0, 0.78 + 0.22 * smoothstep(0.35, 0.75, st), wall * STREAKK);
"""


def _f3(v):
    return "float3(%.5f, %.5f, %.5f)" % tuple(v)


def _srgb(r, g, b):
    def lin(x):
        x /= 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return (lin(r), lin(g), lin(b))


# RefColor (SWCityMesh.cpp) as linear colours
REF = {
    "Timber": _srgb(196, 148, 98), "RammedEarth": _srgb(200, 146, 92), "GreenRoof": _srgb(112, 140, 70),
    "Moss": _srgb(104, 142, 66), "Foliage": _srgb(78, 124, 56), "Bark": _srgb(98, 76, 58),
    "PermeableStone": _srgb(176, 166, 150), "Path": _srgb(206, 190, 160), "Metal": _srgb(196, 160, 84),
}


def surface(tex, ref, tile, rough_k=1.0, nstr=0.8, moss=0.0, streaks=0.0, extra=""):
    """Body for an opaque surface material using texture set `tex` (T_R_<tex>_C/_D)."""
    means = json.loads((Path(__file__).parent / "realism_means.json").read_text())
    code = (SURFACE.replace("MEAN", _f3(means[tex])).replace("REF", _f3(REF[ref]))
            .replace("TILE", f"max(Scale, 1) * {tile:.3f}").replace("ROUGHK", f"{rough_k:.3f}").replace("NSTR", f"{nstr:.3f}"))
    if moss:
        code += MOSS.replace("MOSSK", f"{moss:.3f}")
    if streaks:
        code += STREAKS.replace("STREAKK", f"{streaks:.3f}")
    return code + extra + "\nreturn c * Tint;\n"


BODIES = {}
# Scale defaults below are the Solarpunk materials' (sp_hlsl.SPEC) so instance Scale overrides keep working;
# tile = cm per photo repeat per unit of Scale.
BODIES["M_Timber_Real"] = (surface("Timber", "Timber", 120 / 18, nstr=0.9, moss=0.35, streaks=0.6, extra=r"""
// weathered larch: exposed upward boards silver toward warm grey in patches; end-grain/joints stay darker
float silver = saturate(up * 0.75 + wall * 0.25) * smoothstep(0.25, 0.75, m2.r * 0.6 + m1.b * 0.5);
float g = f.Lum(c);
c = lerp(c, float3(g, g, g) * float3(1.05, 1.0, 0.92) * 1.08, silver * 0.55);
Rough = lerp(Rough, 0.85, silver * 0.5);
"""), 18.0)
BODIES["M_RammedEarth_Real"] = (surface("Render", "RammedEarth", 200 / 9, rough_k=1.1, nstr=0.6, moss=0.25, streaks=1.0, extra=r"""
// rammed-earth lifts: faint horizontal bands every ~15 cm with a wobble
float band = Tn.Sample(TnSampler, float2((P.x + P.y) / 900, P.z / 15)).r;
c *= 0.93 + 0.12 * band * wall;
"""), 9.0)
BODIES["M_PermeableStone_Real"] = (surface("Paving", "PermeableStone", 150 / 40, nstr=1.0, moss=0.5), 40.0)
BODIES["M_Path_Real"] = (surface("Paving", "Path", 110 / 2.5, nstr=1.0, moss=0.3), 2.5)
BODIES["M_Bark_Real"] = (surface("Bark", "Bark", 70 / 5, nstr=1.0, moss=0.4), 5.0)
BODIES["M_Moss_Real"] = (surface("Moss", "Moss", 90 / 6, rough_k=1.2, nstr=1.0), 6.0)
BODIES["M_GreenRoof_Real"] = (surface("Moss", "GreenRoof", 250 / 60, rough_k=1.2, nstr=1.0), 60.0)
BODIES["M_Metal_Real"] = (surface("Metal", "Metal", 80 / 40, rough_k=0.9, nstr=0.5, extra=r"""
// bronze by default, dark steel with Steel = 1; verdigris patina on upward faces and in streaks
c = lerp(c, float3(0.20, 0.21, 0.22) * macro, Steel);
float pat = (1 - Steel) * saturate(up * 0.8 + 0.2) * smoothstep(0.45, 0.8, m2.g + (1 - ao) * 0.4);
c = lerp(c, float3(0.10, 0.24, 0.19), pat * 0.7);
Metal = lerp(1.0, 0.1, pat);
Rough = lerp(Rough * 0.8 + 0.12, 0.7, pat);
// a green tint (the dome's verdigris) means old copper: matte, mostly non-metallic, mottled with darker runs
float verd = saturate((Tint.g - Tint.r) * 1.5);
Metal = lerp(Metal, 0.15, verd);
Rough = lerp(Rough, 0.62, verd);
float runs = Tn.Sample(TnSampler, float2((P.x + P.y) / 120, P.z / 900)).a;
c *= lerp(1.0, 0.72 + 0.4 * m2.r * smoothstep(0.2, 0.8, runs), verd);
"""), 40.0)

# Leaf cards: UV over the leaf-cluster atlas, alpha-masked, two-sided foliage shading. The vertex normal is the crown
# sphere's (EPrim::Leaves), which gives soft crown shading; Td.a (leaf thickness/inner shade) darkens the inner leaves.
LEAF = r"""
float4 col = Tc.Sample(TcSampler, UV);
float4 dat = Td.Sample(TdSampler, UV);
Opac = col.a;
float3 c = col.rgb / MEAN * REF;
float4 m1 = Tn.Sample(TnSampler, P.xy / 1800);
c *= (0.72 + 0.28 * dat.a) * (0.85 + 0.3 * m1.r);
// light from below the crown is mostly transmitted: subsurface colour = a brighter, yellower leaf
SSS = c * float3(1.15, 1.25, 0.7) * 0.8;
Rough = 0.55;
Spec = 0.35;
return c * Tint;
"""


def leaf_body():
    means = json.loads((Path(__file__).parent / "realism_means.json").read_text())
    return LEAF.replace("MEAN", _f3(means["Leaf"])).replace("REF", _f3(REF["Foliage"]))


BODIES["M_Foliage_Real"] = (leaf_body(), 10.0)

# name -> (texture set, shading, two_sided, masked, wired outputs)
SPEC = {
    "M_Timber_Real": ("Timber", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_RammedEarth_Real": ("Render", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_PermeableStone_Real": ("Paving", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_Path_Real": ("Paving", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_Bark_Real": ("Bark", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_Moss_Real": ("Moss", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_GreenRoof_Real": ("Moss", "default", False, False, ["Rough", "Nrm", "Spec"]),
    "M_Metal_Real": ("Metal", "default", False, False, ["Rough", "Nrm", "Metal"]),
    "M_Foliage_Real": ("Leaf", "foliage", True, True, ["Rough", "Spec", "SSS", "Opac"]),
}
