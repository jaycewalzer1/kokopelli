"""HLSL bodies for the Solarpunk materials (one Custom node each). Imported by make_materials.py.

Every body sees these inputs:  P (absolute world position, cm), N (vertex normal WS), Tint (float3), Scale (cm),
Tn/Tnn (noise RGBA / its normal map), Tl/Tln (leaves RGBA / normal), Time, plus per-material extras.
Main output = base colour. Additional outputs (assign by name): Rough, Nrm (world-space normal), Metal, Emis, SSS, Spec.
"""

PRELUDE = r"""
struct SPF
{
	float3 Wt(float3 n, float k) { float3 w = pow(abs(n), k); return w / (w.x + w.y + w.z + 1e-5); }
	float4 Tri(Texture2D T, SamplerState S, float3 p, float3 w)
	{
		return T.Sample(S, p.zy) * w.x + T.Sample(S, p.xz) * w.y + T.Sample(S, p.xy) * w.z;
	}
	float3 UN(float4 c, float s) { float2 xy = (c.xy * 2 - 1) * s; return float3(xy, sqrt(saturate(1 - dot(xy, xy)))); }
	float3 TriN(Texture2D T, SamplerState S, float3 p, float3 n, float3 w, float s)
	{
		float3 a = UN(T.Sample(S, p.zy), s), b = UN(T.Sample(S, p.xz), s), c = UN(T.Sample(S, p.xy), s);
		a = float3(a.xy + n.zy, abs(a.z) * n.x);
		b = float3(b.xy + n.xz, abs(b.z) * n.y);
		c = float3(c.xy + n.xy, abs(c.z) * n.z);
		return normalize(a.zyx * w.x + b.xzy * w.y + c.xyz * w.z);
	}
	// Screen-space-derivative bump (Mikkelsen): perturb n by a height field h given in cm.
	float3 Bump(float3 p, float3 n, float h)
	{
		float3 dx = ddx(p), dy = ddy(p);
		float hx = ddx(h), hy = ddy(h);
		float3 r1 = cross(dy, n), r2 = cross(n, dx);
		float det = dot(dx, r1);
		float3 g = sign(det) * (hx * r1 + hy * r2);
		return normalize(abs(det) * n - g);
	}
	float H1(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
	float H2(float2 p) { return frac(sin(dot(p, float2(269.5, 183.3))) * 21783.1361); }
	// Planar UV for the dominant axis: u runs along the wall, v up (z) on walls; xy on floors/roofs.
	float2 Plan(float3 p, float3 n)
	{
		float3 a = abs(n);
		if (a.z >= a.x && a.z >= a.y) return p.xy;
		return (a.x > a.y) ? float2(p.y, p.z) : float2(p.x, p.z);
	}
	float IsWall(float3 n) { float3 a = abs(n); return (a.z >= a.x && a.z >= a.y) ? 0 : 1; }
	float Lum(float3 c) { return dot(c, float3(0.3, 0.59, 0.11)); }
};
SPF f;
N = normalize(N);
Rough = 0.8; Metal = 0; Emis = 0; SSS = 0; Spec = 0.5; Nrm = N;
"""

# All colours below are linear.
BODIES = {}

BODIES["M_Timber"] = r"""
// CLT: vertical lamellae Scale cm wide, staggered end joints, warm grain.
float S = max(Scale, 1);
float2 uv = f.Plan(P, N);
float bu = floor(uv.x / S);
float hb = f.H1(float2(bu, 3.1));
float len = S * (14 + 10 * hb);
float bv = floor((uv.y + hb * 400) / len);
float hid = f.H1(float2(bu, bv));
float4 nz = Tn.Sample(TnSampler, float2(uv.x / (S * 1.6), uv.y / (S * 24)) + hid);
float4 nf = Tn.Sample(TnSampler, float2(uv.x / (S * 0.35), uv.y / (S * 9)) + hid * 3);
float rings = frac(uv.x / S * (3 + 3 * hid) + nz.r * 2.5 + nf.b * 0.4 + hid * 7);
float grain = smoothstep(0.0, 0.25, rings) * smoothstep(1.0, 0.55, rings);
float gfw = fwidth(uv.x / S * (3 + 3 * hid));
grain = lerp(grain, 0.45, saturate(gfw * 2.5));          // fade fine grain before it aliases
float3 light = float3(0.62, 0.38, 0.17);
float3 dark = float3(0.40, 0.21, 0.08);
float3 c = lerp(dark, light, 0.35 + 0.5 * grain);
c *= 0.82 + 0.3 * hid;
c = lerp(c, c * float3(1.06, 0.95, 0.85), f.H2(float2(bu, bv)));  // some boards redder
// knots
float kn = smoothstep(0.86, 0.95, nz.g) * step(0.55, hid);
c = lerp(c, dark * 0.55, kn * 0.8);
float2 fr = float2(frac(uv.x / S), frac((uv.y + hb * 400) / len));
float du = min(fr.x, 1 - fr.x) * S, dv = min(fr.y, 1 - fr.y) * len;
float sfw = max(fwidth(uv.x), fwidth(uv.y));
float seam = (1 - smoothstep(0.08, 0.35 + sfw, min(du, dv))) * saturate(1.5 - sfw / 3);
c = lerp(c, dark * 0.35, seam * 0.85);
float h = -seam * 0.25 + grain * 0.03 + nf.b * 0.05;
Nrm = f.Bump(P, N, h);
Rough = 0.62 + 0.15 * (1 - grain) + seam * 0.2;
Spec = 0.4;
return c * Tint;
"""

BODIES["M_RammedEarth"] = r"""
// Rammed earth: horizontal strata (Scale = mean layer thickness, cm), ochre / rose / sand, tamped lift lines.
float S = max(Scale, 0.5);
float3 w = f.Wt(N, 6);
float2 uv = f.Plan(P, N);
float4 warp = Tn.Sample(TnSampler, float2(uv.x / (S * 40), P.z / (S * 6)));
float t = P.z / S + (warp.r - 0.5) * 1.6;
float lid = floor(t);
float lh = f.H1(float2(lid, 1.7));
float3 ochre = float3(0.50, 0.26, 0.10);
float3 rose = float3(0.52, 0.24, 0.17);
float3 sand = float3(0.62, 0.44, 0.27);
float3 umber = float3(0.30, 0.15, 0.07);
float3 c = lh < 0.35 ? lerp(ochre, rose, lh / 0.35) : (lh < 0.7 ? lerp(rose, sand, (lh - 0.35) / 0.35) : lerp(sand, ochre, (lh - 0.7) / 0.3));
float big = f.H1(float2(floor(P.z / (S * 9)), 9.2));
c = lerp(c, umber, 0.25 * big * big);
float ft = frac(t);
c *= (0.82 + 0.33 * f.H2(float2(lid, 4.4))) * (0.9 + 0.14 * ft);                       // each lift lighter toward its top (compaction)
float4 sp = f.Tri(Tn, TnSampler, P / (S * 1.5), w);
float4 sp2 = f.Tri(Tn, TnSampler, P / (S * 0.25), w);
c *= 0.85 + 0.3 * sp.b;
float pebble = smoothstep(0.12, 0.04, sp2.g);
c = lerp(c, lerp(umber, sand * 1.2, sp2.r), pebble * 0.7);
float lift = 1 - smoothstep(0.0, 0.08, min(ft, 1 - ft));
c *= 1 - 0.15 * lift * f.IsWall(N);
float h = (sp.b * 0.15 + pebble * 0.12 - lift * 0.2) * f.IsWall(N) + sp.b * 0.1;
Nrm = f.Bump(P, N, h);
Rough = 0.92;
Spec = 0.35;
return c * Tint;
"""

BODIES["M_SolarGlass"] = r"""
// Building-integrated PV glass: dark blue-green, cells Scale cm, module frames every 6 x 10 cells.
float S = max(Scale, 1);
float2 uv = f.Plan(P, N) / S;
float2 cl = frac(uv);
float2 cid = floor(uv);
float d = min(min(cl.x, 1 - cl.x), min(cl.y, 1 - cl.y));
float fw = max(fwidth(uv.x), fwidth(uv.y));
float gap = 1 - smoothstep(0.02, 0.02 + fw * 1.5 + 0.02, d);
float2 mod6 = float2(frac(uv.x / 6), frac(uv.y / 10));
float2 md = min(mod6, 1 - mod6) * float2(6, 10);
float frame = 1 - smoothstep(0.06, 0.06 + fw * 1.5, min(md.x, md.y));
float hc = f.H1(cid);
float4 crys = Tn.Sample(TnSampler, uv * 0.37 + hc);
float3 glass = float3(0.008, 0.025, 0.035) * (0.8 + 0.4 * hc) + float3(0.0, 0.006, 0.012) * crys.g;
float3 c = lerp(glass, float3(0.035, 0.045, 0.05), gap * 0.5);
c = lerp(c, float3(0.11, 0.075, 0.045), frame);  // dark bronze frames
Rough = lerp(0.07 + 0.04 * crys.g, 0.4, max(frame, gap * 0.5));
Metal = frame * 0.9;
Spec = 0.6;
Nrm = f.Bump(P, N, (-gap * 0.08 + frame * 0.3) * S * 0.05);
return c * Tint;
"""

BODIES["M_GreenRoof"] = r"""
// Meadow / sedum roof: lush grass with yellow-green sedum drifts, a few rusty sedum tufts, wildflower specks.
// Scale = drift size, cm.
float S = max(Scale, 5);
float3 w = f.Wt(N, 4);
float4 big = f.Tri(Tn, TnSampler, P / (S * 5), w);
float4 mid = f.Tri(Tn, TnSampler, P / (S * 1.1) + 0.21, w);
float4 lf = f.Tri(Tl, TlSampler, P / (S * 0.5), w);
float4 lf2 = f.Tri(Tl, TlSampler, P / (S * 0.17), w);
float3 grass = float3(0.06, 0.17, 0.025);
float3 lush = float3(0.09, 0.22, 0.03);
float3 sedum = float3(0.16, 0.25, 0.04);
float3 red = float3(0.20, 0.09, 0.04);
float3 c = lerp(grass, lush, smoothstep(0.25, 0.75, mid.r));
float sd = smoothstep(0.6, 0.85, big.r * 0.75 + mid.b * 0.35);
c = lerp(c, sedum, sd * 0.85);
c = lerp(c, red, smoothstep(0.7, 0.9, mid.a) * sd * 0.5);
c *= lerp(0.7, 1.15, lf.g) * lerp(0.55, 1.0, lf.a);
c *= lerp(0.8, 1.1, lf2.a);
// wildflowers: sparse leaves become petals, mostly where the meadow is not sedum
float fl = step(0.955, lf2.g) * lf2.b * smoothstep(0.45, 0.75, big.a) * (1 - sd);
float fh = frac(lf2.g * 97.0);
float3 petal = fh < 0.4 ? float3(0.9, 0.85, 0.7) : (fh < 0.75 ? float3(0.9, 0.6, 0.05) : float3(0.8, 0.25, 0.45));
c = lerp(c, petal, fl);
float3 n1 = f.TriN(Tln, TlnSampler, P / (S * 0.5), N, w, 1.0);
Nrm = normalize(lerp(n1, f.TriN(Tln, TlnSampler, P / (S * 0.17), N, w, 1.0), 0.5));
Rough = 0.8;
Spec = 0.35;
return c * Tint;
"""

BODIES["M_Moss"] = r"""
// Cushion moss. Scale = cushion size, cm.
float S = max(Scale, 0.5);
float3 w = f.Wt(N, 4);
float4 big = f.Tri(Tn, TnSampler, P / (S * 6), w);
float4 lf = f.Tri(Tl, TlSampler, P / (S * 0.5), w);
float4 cell = f.Tri(Tn, TnSampler, P / (S * 1.2), w);
float3 deep = float3(0.035, 0.09, 0.012);
float3 bright = float3(0.17, 0.26, 0.03);
float3 c = lerp(deep, bright, saturate(big.r * 1.3 - 0.1));
float cushion = smoothstep(0.75, 0.2, cell.g);
c *= lerp(0.45, 1.15, cushion) * lerp(0.55, 1.1, lf.a);
c = lerp(c, float3(0.35, 0.28, 0.08), step(0.97, lf.g) * 0.6);  // sporophyte flecks
Nrm = f.TriN(Tln, TlnSampler, P / (S * 0.5), f.Bump(P, N, cushion * S * 0.4), w, 1.4);
Rough = 0.9;
Spec = 0.3;
SSS = c * 0.4 * Tint;
return c * Tint;
"""

BODIES["M_Foliage"] = r"""
// Leafy canopy: Ghibli-style leaf clumps (worley cells ~25 leaves across) with deep gaps, two-tone leaves
// (Scale = leaf length, cm), clump-scale bump so a sphere reads as a cluster of cushions; two-sided foliage SSS.
float S = max(Scale, 1);
float3 w = f.Wt(N, 3);
float4 lf = f.Tri(Tl, TlSampler, P / (S * 8), w);
float4 cl = f.Tri(Tn, TnSampler, P / (S * 22), w);
float4 big = f.Tri(Tn, TnSampler, P / (S * 60), w);
float clump = smoothstep(0.85, 0.15, cl.g);          // 1 at clump centre, 0 in the gaps
float3 darkL = float3(0.025, 0.075, 0.015);
float3 lightL = float3(0.15, 0.27, 0.035);
float3 c = lerp(darkL, lightL, saturate(lf.g * 0.55 + clump * 0.5 + big.r * 0.3 - 0.15));
c = lerp(c, c * float3(1.3, 1.05, 0.5), smoothstep(0.6, 0.9, big.a) * 0.45);   // sun-yellowed clumps
c *= lerp(0.35, 1.1, lf.a) * lerp(0.45, 1.0, lf.b);
c *= lerp(0.45, 1.05, clump);
float3 nb = f.Bump(P, N, clump * S * 3.0);
Nrm = f.TriN(Tln, TlnSampler, P / (S * 8), nb, w, 1.2);
Rough = 0.6;
Spec = 0.3;
SSS = float3(0.20, 0.30, 0.035) * lerp(0.4, 1.0, clump) * Tint;
return c * Tint;
"""

BODIES["M_Bark"] = r"""
// Bark: vertical fissured ridges (Scale = ridge spacing, cm), grey-brown with lichen.
float S = max(Scale, 0.5);
float3 w = f.Wt(N, 4);
float2 uvX = float2(P.y / S, P.z / (S * 7));
float2 uvY = float2(P.x / S, P.z / (S * 7));
float4 a = Tn.Sample(TnSampler, uvX * 0.25) * w.x + Tn.Sample(TnSampler, uvY * 0.25) * w.y + Tn.Sample(TnSampler, P.xy / (S * 3)) * w.z;
float4 b = Tn.Sample(TnSampler, uvX * 0.9 + 0.3) * w.x + Tn.Sample(TnSampler, uvY * 0.9 + 0.3) * w.y + Tn.Sample(TnSampler, P.xy / S) * w.z;
float ridge = saturate(a.a * 1.4 - 0.2) * 0.7 + b.a * 0.3;
float3 deep = float3(0.035, 0.025, 0.018);
float3 top = float3(0.22, 0.17, 0.12);
float3 c = lerp(deep, top, smoothstep(0.25, 0.85, ridge));
c *= 0.85 + 0.3 * b.b;
float lichen = smoothstep(0.62, 0.8, a.r) * smoothstep(0.4, 0.7, ridge);
c = lerp(c, float3(0.20, 0.26, 0.15), lichen * 0.7);
float moss = smoothstep(0.55, 0.75, b.r) * (1 - smoothstep(0.3, 0.6, ridge));
c = lerp(c, float3(0.06, 0.12, 0.02), moss * 0.6);
Nrm = f.Bump(P, N, ridge * S * 0.35);
Rough = 0.9;
Spec = 0.3;
return c * Tint;
"""

BODIES["M_Water"] = r"""
// Still creek / pond water: dark green-teal, glassy, two panning ripple layers (Scale = ripple wavelength, cm).
float S = max(Scale, 1);
float2 p = P.xy / (S * 4);
float3 n1 = f.UN(Tnn.Sample(TnnSampler, p + Time * float2(0.011, 0.007)), 0.35);
float3 n2 = f.UN(Tnn.Sample(TnnSampler, p * 2.3 - Time * float2(0.009, -0.013)), 0.25);
float3 tn = normalize(float3(n1.xy + n2.xy, n1.z * n2.z));
float flat = f.IsWall(N) < 0.5 ? 1 : 0;
Nrm = flat > 0 ? normalize(float3(tn.xy * sign(N.z), abs(N.z)) ) : N;
float4 alg = Tn.Sample(TnSampler, P.xy / (S * 30));
float3 c = lerp(float3(0.006, 0.022, 0.02), float3(0.02, 0.04, 0.02), alg.r);
Rough = 0.035;
Spec = 0.5;
return c * Tint;
"""

BODIES["M_PermeableStone"] = r"""
// Running-bond permeable pavers (Scale = paver length, cm) with mossy open joints.
float S = max(Scale, 2);
float2 uv = f.Plan(P, N) / float2(S, S * 0.5);
float row = floor(uv.y);
uv.x += f.H1(float2(row, 0.5)) > 0.5 ? 0.5 : 0.0;
uv.x += row * 0.5;
float2 id = floor(uv);
float2 fr = frac(uv);
float2 dd = min(fr, 1 - fr) * float2(S, S * 0.5);
float d = min(dd.x, dd.y);
float joint = 0.9;  // cm half-joint
float bevel = smoothstep(joint, joint + 0.8, d);
float hs = f.H1(id), hs2 = f.H2(id);
float3 w = f.Wt(N, 4);
float4 sp = f.Tri(Tn, TnSampler, P / (S * 0.3), w);
float4 big = f.Tri(Tn, TnSampler, P / (S * 6), w);
float3 stoneA = float3(0.29, 0.27, 0.23);
float3 stoneB = float3(0.19, 0.19, 0.18);
float3 stoneC = float3(0.33, 0.26, 0.20);
float3 st = hs < 0.5 ? lerp(stoneA, stoneB, hs * 2) : lerp(stoneA, stoneC, (hs - 0.5) * 2);
st *= 0.85 + 0.3 * sp.b;
st = lerp(st, st * 0.6, smoothstep(0.75, 0.95, sp.g) * 0.3);
float mossy = saturate(smoothstep(0.35, 0.75, big.r) + 0.25);
float3 jointC = lerp(float3(0.06, 0.045, 0.03), float3(0.06, 0.14, 0.02), mossy) * (0.6 + 0.6 * sp.r);
float creep = (1 - smoothstep(joint, joint + 2.5 + 3 * big.r, d)) * mossy * step(0.3, sp.a);
float3 c = lerp(jointC, st, bevel);
c = lerp(c, float3(0.09, 0.17, 0.03) * (0.7 + 0.5 * sp.r), creep * 0.8 * bevel);
Nrm = f.Bump(P, N, bevel * 0.8 + sp.b * 0.15 + (hs2 - 0.5) * 0.1);
Rough = lerp(0.95, 0.78 - 0.1 * hs2, bevel);
Spec = 0.4;
return c * Tint;
"""

BODIES["M_Path"] = r"""
// Compacted earth with fine gravel (Scale = gravel stone size, cm).
float S = max(Scale, 0.3);
float3 w = f.Wt(N, 4);
float4 g1 = f.Tri(Tn, TnSampler, P / (S * 8), w);
float4 g2 = f.Tri(Tn, TnSampler, P / (S * 3.3) + 0.37, w);
float4 big = f.Tri(Tn, TnSampler, P / (S * 120), w);
float3 earth = lerp(float3(0.30, 0.20, 0.12), float3(0.42, 0.31, 0.19), big.r);
earth *= 0.85 + 0.25 * g1.b;
float st1 = smoothstep(0.42, 0.28, g1.g);
float st2 = smoothstep(0.38, 0.22, g2.g) * 0.8;
float3 gravel1 = lerp(float3(0.36, 0.33, 0.28), float3(0.55, 0.47, 0.36), g1.r);
float3 gravel2 = lerp(float3(0.25, 0.21, 0.17), float3(0.48, 0.42, 0.34), g2.a);
float3 c = lerp(earth, gravel1, st1);
c = lerp(c, gravel2, st2 * (1 - st1));
float damp = smoothstep(0.6, 0.85, big.a);
c *= 1 - 0.25 * damp;
Nrm = f.Bump(P, N, (st1 * 0.6 + st2 * 0.4) * S * 0.4 + g1.b * 0.1);
Rough = 0.95 - 0.2 * damp;
Spec = 0.4;
return c * Tint;
"""

BODIES["M_Metal"] = r"""
// Weathered bronze (Steel = 0) or dark steel (Steel = 1); Patina 0..1 verdigris/rust amount. Scale = blotch size, cm.
float S = max(Scale, 1);
float3 w = f.Wt(N, 4);
float4 big = f.Tri(Tn, TnSampler, P / (S * 2), w);
float2 uv = f.Plan(P, N);
float4 streak = Tn.Sample(TnSampler, float2(uv.x / (S * 0.15), uv.y / (S * 3)));
float4 fine = f.Tri(Tn, TnSampler, P / (S * 0.08), w);
float3 bronze = float3(0.55, 0.33, 0.14) * (0.8 + 0.3 * big.b);
float3 steel = float3(0.10, 0.10, 0.105) * (0.8 + 0.4 * fine.b);
float3 metalC = lerp(bronze, steel, Steel);
float pmask = saturate((big.r * 0.8 + streak.r * 0.2 + fine.b * 0.15) - (1 - Patina) * 0.95);
pmask = smoothstep(0.05, 0.35, pmask);
float3 verd = lerp(float3(0.16, 0.36, 0.28), float3(0.30, 0.50, 0.40), fine.r);
float3 rust = lerp(float3(0.20, 0.07, 0.03), float3(0.32, 0.14, 0.05), fine.r);
float3 pat = lerp(verd, rust, Steel);
float3 c = lerp(metalC * Tint, pat, pmask);
Metal = 1 - pmask;
Rough = lerp(0.32 + 0.15 * fine.b + 0.1 * Steel, 0.85, pmask);
Nrm = f.Bump(P, N, pmask * 0.08 + fine.b * 0.02);
return c;
"""

BODIES["M_Fabric"] = r"""
// Canvas awning: woven cream canvas with optional stripes (Scale = stripe width, cm; Stripes 0/1). Two-sided, back-lit glow.
float S = max(Scale, 1);
float2 uv = f.Plan(P, N);
float stripe = step(0.5, frac(uv.x / (S * 2))) * Stripes;
float3 cream = float3(0.72, 0.62, 0.46);
float3 c = lerp(cream, cream * float3(0.55, 0.32, 0.2), stripe);
float2 wv = uv / 0.35;
float fw = fwidth(wv.x);
float weave = lerp(sin(wv.x * 6.283) * sin(wv.y * 6.283) * 0.5 + 0.5, 0.5, saturate(fw * 2));
float4 nz = Tn.Sample(TnSampler, uv / 60);
float4 nz2 = Tn.Sample(TnSampler, uv / 9);
c *= 0.88 + 0.12 * weave;
c *= 0.85 + 0.2 * nz.r;
c = lerp(c, c * float3(0.75, 0.72, 0.6), smoothstep(0.65, 0.9, nz2.a) * 0.4);  // weathering
Nrm = f.Bump(P, N, weave * 0.03 + nz.r * 0.6);
Rough = 0.88;
Spec = 0.3;
SSS = c * 0.8 * Tint;
return c * Tint;
"""

BODIES["M_Lantern"] = r"""
// Warm paper / glass lantern glow. Glow = emissive multiplier. Scale = fibre pattern size, cm.
float S = max(Scale, 0.5);
float3 w = f.Wt(N, 4);
float4 nz = f.Tri(Tn, TnSampler, P / (S * 3), w);
float4 fib = f.Tri(Tn, TnSampler, P / S, w);
float3 warm = float3(1.0, 0.42, 0.11);
float fl = 0.9 + 0.1 * sin(Time * 2.3 + nz.r * 6);
Emis = warm * Tint * Glow * (0.75 + 0.35 * nz.r + 0.15 * fib.b) * fl;
Rough = 0.6;
Spec = 0.3;
return float3(0.8, 0.6, 0.4) * Tint;
"""

# name: (shading, two_sided, extra scalar params {name: default}, default Scale, outputs to wire)
SPEC = {
    "M_Timber": ("default", False, {}, 18.0, ["Rough", "Nrm", "Spec"]),
    "M_RammedEarth": ("default", False, {}, 9.0, ["Rough", "Nrm", "Spec"]),
    "M_SolarGlass": ("default", False, {}, 16.0, ["Rough", "Nrm", "Metal", "Spec"]),
    "M_GreenRoof": ("default", False, {}, 60.0, ["Rough", "Nrm", "Spec"]),
    "M_Moss": ("default", False, {}, 6.0, ["Rough", "Nrm", "Spec"]),
    "M_Foliage": ("foliage", True, {}, 10.0, ["Rough", "Nrm", "Spec", "SSS"]),
    "M_Bark": ("default", False, {}, 5.0, ["Rough", "Nrm", "Spec"]),
    "M_Water": ("default", False, {}, 60.0, ["Rough", "Nrm", "Spec"]),
    "M_PermeableStone": ("default", False, {}, 40.0, ["Rough", "Nrm", "Spec"]),
    "M_Path": ("default", False, {}, 2.5, ["Rough", "Nrm", "Spec"]),
    "M_Metal": ("default", False, {"Steel": 0.0, "Patina": 0.3}, 40.0, ["Rough", "Nrm", "Metal"]),
    "M_Fabric": ("foliage", True, {"Stripes": 1.0}, 20.0, ["Rough", "Nrm", "Spec", "SSS"]),
    "M_Lantern": ("default", False, {"Glow": 4.0}, 4.0, ["Rough", "Emis", "Spec"]),
}
