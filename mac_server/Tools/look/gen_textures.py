"""Generate the tileable procedural textures the Solarpunk materials sample (no photos, all math).

    simworld/.venv/bin/python Tools/gen_textures.py <out_dir>

T_SP_Noise.png   RGBA linear: R fbm (low freq), G worley F1 cells, B fine fbm, A ridged fbm
T_SP_Noise_N.png normal map from R+B fbm (for ripples, earth, metal)
T_SP_Leaves.png  RGBA linear: R leaf height, G per-leaf random, B leaf coverage, A cavity/AO
T_SP_Leaves_N.png normal map from leaf height
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

N = 512
rng = np.random.default_rng(7)


def value_noise(n, period, seed):
    """Tileable smooth value noise on an n x n grid with `period` cells."""
    r = np.random.default_rng(seed).random((period, period))
    t = np.arange(n) / n * period
    i0 = np.floor(t).astype(int) % period
    i1 = (i0 + 1) % period
    f = t - np.floor(t)
    f = f * f * f * (f * (f * 6 - 15) + 10)
    a = r[i0][:, i0]; b = r[i0][:, i1]; c = r[i1][:, i0]; d = r[i1][:, i1]
    fy = f[:, None]; fx = f[None, :]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def fbm(n, base, octaves, seed, gain=0.5):
    out = np.zeros((n, n)); amp = 1.0; tot = 0.0
    for o in range(octaves):
        out += amp * value_noise(n, base * 2 ** o, seed + o * 31)
        tot += amp; amp *= gain
    return out / tot


def worley(n, cells, seed):
    r = np.random.default_rng(seed)
    gy, gx = np.mgrid[0:cells, 0:cells]
    jit = r.random((cells, cells, 2))
    px = (gx + jit[..., 0]) / cells; py = (gy + jit[..., 1]) / cells
    pxs = []; pys = []
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            pxs.append((px + ox).ravel()); pys.append((py + oy).ravel())
    pxs = np.concatenate(pxs); pys = np.concatenate(pys)
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    best = np.full((n, n), 9.0)
    for k in range(len(pxs)):
        d = (x - pxs[k]) ** 2 + (y - pys[k]) ** 2
        np.minimum(best, d, out=best)
    return np.sqrt(best) * cells


def normal_from_height(h, strength):
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    nz = np.ones_like(h)
    l = np.sqrt(dx * dx + dy * dy + 1)
    nx, ny, nz = -dx / l, dy / l, nz / l  # UE normal maps: +Y up in texture (DirectX style needs flip); green flipped handled by flip_green False
    return np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5], -1)


def save(arr, path):
    Image.fromarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8)).save(path)
    print("wrote", path)


def leaves(n, count, seed):
    """Scatter overlapping elliptical leaves (tileable): height dome + midrib, random id, coverage, cavity."""
    r = np.random.default_rng(seed)
    height = np.zeros((n, n)); rid = np.zeros((n, n)); cov = np.zeros((n, n))
    y, x = np.mgrid[0:n, 0:n].astype(float)
    for _ in range(count):
        cx, cy = r.random(2) * n
        L = r.uniform(0.045, 0.085) * n; W = L * r.uniform(0.38, 0.55)
        ang = r.random() * np.pi * 2
        ca, sa = np.cos(ang), np.sin(ang)
        x0, x1 = int(cx - L - 2), int(cx + L + 3); y0, y1 = int(cy - L - 2), int(cy + L + 3)
        yy = np.arange(y0, y1) % n; xx = np.arange(x0, x1) % n
        lx = np.arange(x0, x1)[None, :] - cx; ly = np.arange(y0, y1)[:, None] - cy
        u = (lx * ca + ly * sa) / L; v = (-lx * sa + ly * ca) / W
        # leaf shape: pointed ellipse, wider near base
        w = (1 - u ** 2) * (1 + 0.25 * u)
        inside = (np.abs(v) < np.sqrt(np.clip(w, 0, None))) & (np.abs(u) < 1)
        dome = np.clip(1 - u ** 2 - v ** 2 * 0.6, 0, 1) ** 0.5
        rib = np.exp(-(v / 0.06) ** 2) * 0.12
        hgt = (0.35 + 0.65 * dome - rib) * (0.55 + 0.45 * r.random())
        layer = r.random() * 0.15  # later leaves on top
        sub_h = height[np.ix_(yy, xx)]; sub_id = rid[np.ix_(yy, xx)]; sub_c = cov[np.ix_(yy, xx)]
        top = inside & (hgt + layer > sub_h * 0.0 - 1)  # painter's order: later wins
        sub_h[top] = np.maximum(hgt[top] * 0.85 + layer, 0)
        sub_id[top] = r.random()
        sub_c[top] = 1
        height[np.ix_(yy, xx)] = sub_h; rid[np.ix_(yy, xx)] = sub_id; cov[np.ix_(yy, xx)] = sub_c
    height = height / max(height.max(), 1e-6)
    # cavity: darker where height is low relative to neighbourhood blur
    from scipy.ndimage import uniform_filter
    blur = uniform_filter(height, size=15, mode="wrap")
    ao = np.clip(0.5 + (height - blur) * 2.0, 0, 1) * (0.4 + 0.6 * cov)
    return height, rid, cov, ao


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    # domain-warped fbm: breaks the axis-aligned blockiness value noise has at low octaves
    from scipy.ndimage import map_coordinates
    base = fbm(N, 4, 7, 1, gain=0.55)
    wx = (fbm(N, 3, 4, 11) - 0.5) * N * 0.35
    wy = (fbm(N, 3, 4, 12) - 0.5) * N * 0.35
    yy, xx = np.mgrid[0:N, 0:N].astype(float)
    r = map_coordinates(base, [(yy + wy) % N, (xx + wx) % N], order=1, mode="grid-wrap")
    g = worley(N, 8, 2); g = np.clip(g / g.max(), 0, 1)
    b = fbm(N, 32, 4, 3)
    ridge = 1 - np.abs(fbm(N, 8, 5, 4) * 2 - 1)
    ridge = map_coordinates(ridge, [(yy + wx * 0.5) % N, (xx + wy * 0.5) % N], order=1, mode="grid-wrap")
    norm = lambda a: (a - a.min()) / (a.max() - a.min())
    save(np.stack([norm(r), g, norm(b), norm(ridge)], -1), out / "T_SP_Noise.png")
    save(normal_from_height(norm(r) * 0.6 + norm(b) * 0.4, 6.0), out / "T_SP_Noise_N.png")
    h, rid, cov, ao = leaves(N, 1400, 9)
    save(np.stack([h, rid, cov, ao], -1), out / "T_SP_Leaves.png")
    save(normal_from_height(h, 5.0), out / "T_SP_Leaves_N.png")


if __name__ == "__main__":
    main()
