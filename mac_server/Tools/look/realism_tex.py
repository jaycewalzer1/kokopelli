"""Pack the CC0 texture sets (city/realism/ASSETS.md) for the realism pilot's materials, and build the leaf-card atlas.

    simworld/.venv/bin/python -I Tools/look/realism_tex.py <src_dir> <out_dir>

<src_dir> holds the unzipped ambientCG sets (Saved/realism_src/<Id>/...). Writes, per material:
  T_R_<Name>_C.png  colour, sRGB
  T_R_<Name>_D.png  linear RGBA: R,G = tangent normal x,y (OpenGL convention, like gen_textures.py), B roughness, A AO
plus T_R_Leaf_C.png (RGBA: colour + opacity) / T_R_Leaf_D.png (normal x,y, roughness, thickness) and means.json
(each colour map's mean linear colour, so the materials can divide it out and keep the palette's reference colours).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SETS = {  # material name -> (ambientCG id, output size)
    "Timber": ("Planks023A", 1024),
    "Render": ("Plaster003", 1024),
    "Paving": ("PavingStones138", 1024),
    "Metal": ("Metal009", 512),
    "Bark": ("Bark014", 512),
    "Moss": ("Moss002", 512),
}


def srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def load(path, size, mode="RGB"):
    im = Image.open(path).convert(mode)
    return np.asarray(im.resize((size, size), Image.LANCZOS), dtype=np.float32) / 255.0


def find(src, aid, kind):
    hits = sorted((src / aid).glob(f"{aid}_*_{kind}.png"))
    return hits[0] if hits else None


def pack(src, out, name, aid, size, means):
    col = load(find(src, aid, "Color"), size)
    nrm = load(find(src, aid, "NormalDX"), size)
    nrm[..., 1] = 1.0 - nrm[..., 1]  # DirectX -> OpenGL green
    r = find(src, aid, "Roughness")
    rough = load(r, size, "L") if r else np.full((size, size), 0.6, np.float32)
    a = find(src, aid, "AmbientOcclusion")
    ao = load(a, size, "L") if a else np.ones((size, size), np.float32)
    Image.fromarray((col * 255 + 0.5).astype(np.uint8)).save(out / f"T_R_{name}_C.png")
    d = np.dstack([nrm[..., 0], nrm[..., 1], rough, ao])
    Image.fromarray((d * 255 + 0.5).astype(np.uint8), "RGBA").save(out / f"T_R_{name}_D.png")
    means[name] = [round(float(v), 5) for v in srgb_to_lin(col).reshape(-1, 3).mean(0)]


def leaf_atlas(src, out, means, size=1024, seed=5):
    """One leaf-cluster card: ~70 beech leaves from LeafSet024 radiating from twigs, darker toward the middle."""
    aid = "LeafSet024"
    col = Image.open(find(src, aid, "Color")).convert("RGB")
    opa = Image.open(find(src, aid, "Opacity")).convert("L")
    nrm = Image.open(find(src, aid, "NormalDX")).convert("RGB")
    W, H = col.size
    # the set is a 3 x 3 grid of leaves, stem at the bottom; cut each one by its opacity box
    leaves = []
    for gy in range(3):
        for gx in range(3):
            box = (gx * W // 3, gy * H // 3, (gx + 1) * W // 3, (gy + 1) * H // 3)
            bb = opa.crop(box).getbbox()
            if not bb:
                continue
            b = (box[0] + bb[0], box[1] + bb[1], box[0] + bb[2], box[1] + bb[3])
            leaves.append((col.crop(b), opa.crop(b), nrm.crop(b)))
    rng = np.random.default_rng(seed)
    C = Image.new("RGB", (size, size), (40, 60, 25))
    A = Image.new("L", (size, size), 0)
    N = Image.new("RGB", (size, size), (128, 128, 255))
    T = Image.new("L", (size, size), 0)  # thickness / inner shade
    draw_c, draw_a = ImageDraw.Draw(C), ImageDraw.Draw(A)
    cx = cy = size / 2
    twigs = []
    for k in range(8):  # twigs from the centre outward
        ang = k * 2 * np.pi / 8 + rng.uniform(-0.25, 0.25)
        L = size * rng.uniform(0.32, 0.43)
        x1, y1 = cx + np.cos(ang) * L, cy + np.sin(ang) * L
        twigs.append((ang, L))
        draw_c.line([(cx, cy), (x1, y1)], fill=(70, 52, 34), width=4)
        draw_a.line([(cx, cy), (x1, y1)], fill=255, width=4)
    order = []
    for ang, L in twigs:
        for t in np.linspace(0.15, 1.0, 9):
            order.append((ang + rng.uniform(-0.12, 0.12), L * t, t))
    rng.shuffle(order)
    order.sort(key=lambda o: o[2])  # inner leaves first, outer ones on top
    for ang, dist, t in order:
        lc, la, ln = leaves[rng.integers(len(leaves))]
        s = size * rng.uniform(0.10, 0.145) / max(lc.size)
        sz = (max(1, int(lc.size[0] * s)), max(1, int(lc.size[1] * s)))
        side = rng.choice([-1, 1])
        rot = -np.degrees(ang) - 90 + side * rng.uniform(25, 60)  # stem toward the twig, tip outward
        lc2 = lc.resize(sz, Image.LANCZOS).rotate(rot, expand=True, resample=Image.BICUBIC)
        la2 = la.resize(sz, Image.LANCZOS).rotate(rot, expand=True, resample=Image.BICUBIC)
        ln2 = ln.resize(sz, Image.LANCZOS).rotate(rot, expand=True, resample=Image.BICUBIC, fillcolor=(128, 128, 255))
        shade = 0.62 + 0.38 * t + rng.uniform(-0.08, 0.08)  # inner leaves sit in the crown's shade
        hue = np.array([rng.uniform(0.9, 1.05), rng.uniform(0.95, 1.08), rng.uniform(0.85, 1.0)]) * shade
        lc2 = Image.fromarray(np.clip(np.asarray(lc2, np.float32) * hue, 0, 255).astype(np.uint8))
        px = cx + np.cos(ang) * dist + side * rng.uniform(4, 16) - lc2.size[0] / 2
        py = cy + np.sin(ang) * dist - lc2.size[1] / 2
        pos = (int(px), int(py))
        C.paste(lc2, pos, la2)
        N.paste(ln2, pos, la2)
        A.paste(la2, pos, la2)
        T.paste(Image.new("L", lc2.size, int(255 * t)), pos, la2)
    # keep colour under transparent texels close to the leaves' (no dark halo when mips blend)
    blur = C.filter(ImageFilter.GaussianBlur(12))
    C = Image.composite(C, blur, A)
    col = np.asarray(C, np.float32) / 255
    a = np.asarray(A, np.float32) / 255
    rgba = np.dstack([col, a])
    Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), "RGBA").save(out / "T_R_Leaf_C.png")
    n = np.asarray(N, np.float32) / 255
    n[..., 1] = 1.0 - n[..., 1]
    d = np.dstack([n[..., 0], n[..., 1], np.full(a.shape, 0.55, np.float32), np.asarray(T, np.float32) / 255])
    Image.fromarray((d * 255 + 0.5).astype(np.uint8), "RGBA").save(out / "T_R_Leaf_D.png")
    m = a > 0.5
    means["Leaf"] = [round(float(v), 5) for v in srgb_to_lin(col[m]).mean(0)]
    means["Leaf_coverage"] = round(float(a.mean()), 3)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    means = {}
    for name, (aid, size) in SETS.items():
        pack(src, out, name, aid, size, means)
    leaf_atlas(src, out, means)
    (out / "means.json").write_text(json.dumps(means, indent=1))
    print(json.dumps(means))


if __name__ == "__main__":
    main()
