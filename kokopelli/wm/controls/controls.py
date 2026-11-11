"""Build Cosmos3-Nano-Sim-Transfer control videos (depth, seg, edge, blur) for a SimWorld shot. No model runs here.

    .venv/bin/python -I kokopelli/wm/controls/controls.py                      # bridge shot, first 150 frames
    .venv/bin/python -I kokopelli/wm/controls/controls.py --frames 300 --clip out/filter_test/test_clip --out out/city_wm/bridge/controls

Writes, under --out, one folder per canvas (832x480 = the model's native 480p 16:9 canvas, and 448x256):
    {depth,depth_inverse,seg,seg_actor,edge,blur}.mp4   30 fps, H.264 yuv420p, 3-channel, same frame count and timing as the rgb
plus controls.json (what each one is, its parameters and the NVIDIA source of each convention) and sheet.png.

Where each convention comes from (NVIDIA cosmos-framework, main, read 2026-11-06):
- canvas: VIDEO_RES_SIZE_INFO["480"]["16,9"] = 832x480 (cosmos_framework/data/generator/utils.py); direct resize of the
  full frame, no crop (inference/transfer_preprocessing.py). 1280x720 -> 832x480 is 0.16% aspect distortion (< 3% limit).
- edge: AddControlInputEdge, preset "medium" = cv2.Canny(rgb, 100, 200) on the RGB already resized to the canvas,
  repeated into 3 channels (data/generator/augmentors/transfer_control_input/control_input.py).
- blur: AddControlInputBlur(use_random=False, downup_preset="medium"): area-downscale x2, bilateral filter
  (d=30, sigma_color=150, sigma_space=100, all scaled by longest_side/720), linear upscale, then cubic down/up by 10
  (control_input.py + blur.py). Also computed from the canvas-resized RGB.
- depth: three-channel grey, near bright, sky black, one scale for the whole clip, linear in distance -- the encoding
  experiments/filter_test/scripts/controls.py measured against NVIDIA's example1_depth.mp4 (reused here, not imported).
- seg: colour-coded masks on black, one colour per region, colours drawn like seg.py's generate_distinct_colors
  (HSV: any hue, saturation 0.1-1, value 0.2-1). Resized with nearest neighbour.
"""
import argparse
import colorsys
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
SIZES = [(832, 480), (448, 256)]
FPS = 30
SKY_CM = 60000  # the server clamps sky at 65504 cm (experiments/filter_test/scripts/controls.py)
SEED = 7

# Material classes used to split SimWorld's per-actor masks (see split_classes). Lab values are OpenCV's 8-bit Lab
# with a*, b* re-centred on 0.
CLASSES = ["neutral", "timber", "foliage", "blossom", "cool"]
MIN_PART = 0.0006  # a material region smaller than this fraction of the frame joins its actor's main material


def load_rgb(clip, k):
    return np.array(Image.open(clip / "rgb" / f"{k:04d}.png").convert("RGB"))


def resize_rgb(rgb, size):
    # NVIDIA resizes RGB with antialiased bicubic (torchvision); PIL's bicubic is the same antialiased filter.
    return np.array(Image.fromarray(rgb).resize(size, Image.Resampling.BICUBIC))


def edge(rgb_small, low=100, high=200):
    e = cv2.Canny(rgb_small, low, high)  # multi-channel input: OpenCV takes the strongest channel's gradient
    return np.repeat(e[..., None], 3, axis=2)


def blur(rgb_small, down=2, d=30, sigma_color=150, sigma_space=100, downup=10):
    h, w = rgb_small.shape[:2]
    small = cv2.resize(rgb_small, (w // down, h // down), interpolation=cv2.INTER_AREA)
    scale = max(small.shape[:2]) / 720  # blur.py scales its 720p parameters by the (downscaled) longest side
    dd = max(1, round(d * scale))
    dd += dd % 2 == 0
    small = cv2.bilateralFilter(small, dd, max(1.0, sigma_color * scale), max(1.0, sigma_space * scale))
    up = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    tiny = cv2.resize(up, (int(w / downup), int(h / downup)), interpolation=cv2.INTER_CUBIC)
    return cv2.resize(tiny, (w, h), interpolation=cv2.INTER_CUBIC), {"bilateral_d": dd, "sigma_color": round(max(1.0, sigma_color * scale), 2),
                                                                      "sigma_space": round(max(1.0, sigma_space * scale), 2)}


def depth_scale(depths):
    sky = depths >= SKY_CM
    near = float(np.percentile(depths[~sky], 0.5))
    # experiments/filter_test/scripts/controls.py: half the clip is within 4 m and the hills are ~465 m off, so linear over all of it
    # would leave everything white; the scale ends at the 95th percentile and only the hills fall to black with the sky.
    far = float(np.percentile(depths[~sky], 95))
    return near, far, float(sky.mean())


def depth_frame(d, near, far, size):
    v = np.clip((far - d) / (far - near), 0, 1)
    v[d >= SKY_CM] = 0
    v = cv2.resize(v, size, interpolation=cv2.INTER_AREA)  # area average = antialiased downscale
    g = np.round(v * 255).astype(np.uint8)
    return np.repeat(g[..., None], 3, axis=2)


def inverse_scale(depths):
    sky = depths >= SKY_CM
    return float(np.percentile(depths[~sky], 5)), float(np.percentile(depths[~sky], 99.5))  # near at the 5th pct: the deck, not the railings, sets white


def depth_inverse_frame(d, near, far, size, floor=0.1):
    """example2's encoding: inverse depth (disparity), near bright, sky black. Non-sky geometry starts at `floor` so the
    hills and dome stay separate from the sky, as example2's far trees (30-110 grey) do."""
    v = np.clip((1 / np.maximum(d, 1) - 1 / far) / (1 / near - 1 / far), 0, 1)
    v = floor + (1 - floor) * v
    v[d >= SKY_CM] = 0
    v = cv2.resize(v.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    g = np.round(v * 255).astype(np.uint8)
    return np.repeat(g[..., None], 3, axis=2)


def split_classes(rgb):
    """Per-pixel material class from colour alone: deterministic, so the same surface keeps its class every frame."""
    lab = cv2.cvtColor(cv2.GaussianBlur(rgb, (5, 5), 0), cv2.COLOR_RGB2LAB).astype(np.float32)
    a, b = lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.hypot(a, b)
    cls = np.zeros(rgb.shape[:2], np.uint8)  # neutral: greys, white render, cream sails, cloud-lit glass
    cls[(chroma >= 9) & (b >= 6) & (a >= -6)] = 1  # timber, brown and tan (sunlit or shadowed)
    cls[(chroma >= 9) & (a < -6) & (b >= 0)] = 2  # foliage, green to yellow-green
    cls[(chroma >= 9) & (a >= 6) & (b < 6)] = 3  # blossom, pink to purple (jacarandas)
    cls[(chroma >= 9) & (b < 0) & (a < 6)] = 4  # cool: teal glass, water, blue-grey distance
    # Majority filter over a 9x9 window removes texture and shading speckle without moving region borders much.
    votes = np.stack([cv2.boxFilter((cls == c).astype(np.float32), -1, (9, 9)) for c in range(len(CLASSES))])
    return votes.argmax(0).astype(np.uint8)


def refined_ids(seg, rgb):
    """Region id per pixel: SimWorld actor (its exact mask colour) x material class. Sky (black) stays 0."""
    actor = seg[..., 0].astype(np.int64) << 16 | seg[..., 1].astype(np.int64) << 8 | seg[..., 2]
    cls = split_classes(rgb)
    ids = actor * 8 + cls
    total = ids.size
    for a in np.unique(actor):
        if a == 0:
            continue
        m = actor == a
        counts = np.bincount(cls[m], minlength=len(CLASSES))
        main = counts.argmax()
        for c in np.flatnonzero(counts):
            if c == main:
                continue
            part = (m & (cls == c)).astype(np.uint8)
            n, lab, stats, _ = cv2.connectedComponentsWithStats(part, connectivity=8)
            small = np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] < MIN_PART * total) + 1
            if len(small):
                ids[np.isin(lab, small)] = a * 8 + main
    ids[actor == 0] = 0
    return ids


class Palette:
    """One fixed colour per region id for the whole clip, drawn like NVIDIA's generate_distinct_colors."""

    def __init__(self, seed=SEED):
        self.rng = np.random.default_rng(seed)
        self.colours: dict[object, tuple[int, ...]] = {0: (0, 0, 0)}

    def __getitem__(self, key):
        if key not in self.colours:
            used = np.array(list(self.colours.values()), np.float32)
            for _ in range(200):  # reject colours too close to one already in use, so neighbours stay distinguishable
                r, g, b = colorsys.hsv_to_rgb(self.rng.uniform(0, 1), self.rng.uniform(0.1, 1), self.rng.uniform(0.2, 1))
                c = np.array([r, g, b]) * 255
                if np.min(np.linalg.norm(used - c, axis=1)) > 70:
                    break
            self.colours[key] = tuple(int(x) for x in c.astype(np.uint8))
        return self.colours[key]

    def paint(self, ids):
        out = np.zeros(ids.shape + (3,), np.uint8)
        for key in np.unique(ids):
            out[ids == key] = self[int(key)]
        return out


class Writer:
    def __init__(self, path, size):
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
                                   "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", "-r", str(FPS),
                                   str(path)], stdin=subprocess.PIPE)

    def write(self, frame):
        assert self.p.stdin is not None  # stdin=PIPE
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        assert self.p.stdin is not None  # stdin=PIPE
        self.p.stdin.close()
        assert self.p.wait() == 0


def sheet(clip, out, frames, picks):
    """Rows rgb/depth/seg/edge/blur, columns = picked frames, read back from the encoded 832x480 videos."""
    w, h = SIZES[0]
    tw, th = w // 2, h // 2
    rows = []
    for name in ["rgb", "depth", "depth_inverse", "seg", "edge", "blur"]:
        if name == "rgb":
            tiles = [resize_rgb(load_rgb(clip, k), (w, h)) for k in picks]
        else:
            cap = cv2.VideoCapture(str(out / f"{w}x{h}" / f"{name}.mp4"))
            got = {}
            for k in range(frames):
                ok, fr = cap.read()
                if k in picks:
                    got[k] = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            tiles = [got[k] for k in picks]
        tiles = [cv2.resize(t, (tw, th), interpolation=cv2.INTER_AREA if name != "seg" else cv2.INTER_NEAREST) for t in tiles]
        label = np.full((th + 4, 120, 3), 30, np.uint8)
        cv2.putText(label, name.replace("_", " "), (8, th // 2 + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        rows.append(np.hstack([label] + [np.pad(t, ((2, 2), (2, 2), (0, 0))) for t in tiles]))
    head = np.full((24, rows[0].shape[1], 3), 30, np.uint8)
    for i, k in enumerate(picks):
        cv2.putText(head, f"frame {k}", (120 + i * (tw + 4) + 8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
    Image.fromarray(np.vstack([head] + rows)).save(out / "sheet.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # pyright: ignore[reportOptionalMemberAccess]  # the module has a docstring
    ap.add_argument("--clip", default="out/filter_test/test_clip")
    ap.add_argument("--out", default="out/city_wm/bridge/controls")
    ap.add_argument("--frames", type=int, default=150, help="first N frames of the clip (150 = 5 s at 30 fps)")
    args = ap.parse_args()
    clip, out = ROOT / args.clip, ROOT / args.out
    n = args.frames
    available = len(list((clip / "rgb").glob("*.png")))
    assert 0 < n <= available, f"clip has {available} frames"

    depths = np.stack([np.load(clip / "depth" / f"{k:04d}.npy") for k in range(n)])
    near, far, sky = depth_scale(depths)
    inv_near, inv_far = inverse_scale(depths)

    writers = {}
    for size in SIZES:
        (out / f"{size[0]}x{size[1]}").mkdir(parents=True, exist_ok=True)
        for name in ["depth", "depth_inverse", "seg", "seg_actor", "edge", "blur"]:
            writers[size, name] = Writer(out / f"{size[0]}x{size[1]}" / f"{name}.mp4", size)

    refined, actors = Palette(SEED), Palette(SEED + 1)
    blur_params, region_count = {}, set()
    for k in range(n):
        rgb = load_rgb(clip, k)
        seg = np.array(Image.open(clip / "segmentation" / f"{k:04d}.png").convert("RGB"))
        ids = refined_ids(seg, rgb)
        region_count.update(np.unique(ids).tolist())
        seg_full = refined.paint(ids)
        actor_full = actors.paint(seg[..., 0].astype(np.int64) << 16 | seg[..., 1].astype(np.int64) << 8 | seg[..., 2])
        for size in SIZES:
            small = resize_rgb(rgb, size)
            writers[size, "depth"].write(depth_frame(depths[k], near, far, size))
            writers[size, "depth_inverse"].write(depth_inverse_frame(depths[k], inv_near, inv_far, size))
            writers[size, "seg"].write(cv2.resize(seg_full, size, interpolation=cv2.INTER_NEAREST))
            writers[size, "seg_actor"].write(cv2.resize(actor_full, size, interpolation=cv2.INTER_NEAREST))
            writers[size, "edge"].write(edge(small))
            b, blur_params[size] = blur(small)
            writers[size, "blur"].write(b)
        if k % 30 == 0:
            print(f"frame {k}/{n}", flush=True)
    for w in writers.values():
        w.close()

    picks = sorted({0, min(50, n - 1), min(100, n - 1), n - 1})
    sheet(clip, out, n, picks)
    ref = "https://github.com/NVIDIA/cosmos-framework (main)"
    meta = {
        "source": {"clip": args.clip, "frames": [0, n - 1], "count": n, "fps": FPS, "source_size": [1280, 720],
                   "rgb": "rgb/NNNN.png", "depth": "depth/NNNN.npy (float32 cm)", "segmentation": "segmentation/NNNN.png (UnrealCV object_mask)"},
        "sets": {f"{w}x{h}": f"{w}x{h}/" for w, h in SIZES},
        "canvas_note": "832x480 is the model's native 480-tier 16:9 canvas (VIDEO_RES_SIZE_INFO['480']['16,9']); Stages 1-3 of Sim-Transfer "
                       "train at 480 only. 448x256 is not a trained bucket (the framework's 256-tier 16:9 is 320x192; 448x256 appears only as a "
                       "commented 'desired' entry), so treat it as a cheap preview size. Both are 16:9 within 3%.",
        "frame_count_note": "The model works in 1+4n frames; 150 frames are trimmed by the server to 149 (whole latent chunks).",
        "encoding": "H.264, yuv420p, CRF 10, 30 fps, 3 channels. The model reads pixels/127.5-1.",
        "one_control_per_request": "The causal Sim-Transfer checkpoint takes exactly one control per request (inference/transfer.py: "
                                   "'Causal transfer AR inference requires exactly one control hint'). Multi-control weighting "
                                   "(control_weights, normalised to sum 1) exists only for the non-distilled Transfer teacher.",
        "controls": {
            "depth": {"what": "relative depth, grey in 3 channels, near bright, linear in distance, one scale for the clip, sky and anything beyond 'far' black",
                      "near_m": round(near / 100, 2), "far_m": round(far / 100, 2), "sky_fraction": round(sky, 3),
                      "resize": "area average of the float map (antialiased), then 8-bit",
                      "reference": "experiments/filter_test/scripts/controls.py (measured vs NVIDIA assets/sample_data/example1/example1_depth.mp4); "
                                   "data-contract.md: 'three-channel relative-depth rendering ... not metric distances'"},
            "depth_inverse": {"what": "inverse depth (disparity), grey in 3 channels, near bright, one scale for the clip, non-sky floor 0.1, sky black",
                              "near_m": round(inv_near / 100, 2), "far_m": round(inv_far / 100, 2), "floor": 0.1,
                              "why": "NVIDIA's two sample depth videos use different encodings. Measured on a flat plane: example1 (simulated robot "
                                     "table) brightens in steps that shrink toward the camera with a fixed max of 202 (linear in distance); example2 "
                                     "(real outdoor video) brightens in equal steps per image row (15-16 grey per 20 rows on the platform, which is "
                                     "what inverse depth gives) and its max drifts 252->229 (estimated, per-window normalised). This outdoor shot "
                                     "spans 1.5-500 m like example2; linear leaves everything within ~15 m above 90% white.",
                              "reference": "models/Cosmos3-Nano-Sim-Transfer/assets/sample_data/example2/example2_depth.mp4 (measured)"},
            "seg": {"what": "SimWorld actor masks split by material colour class, one fixed random colour per (actor, material) region, sky/unlabelled black",
                    "material_classes": CLASSES, "rule": "Lab of the 5x5-blurred rgb: chroma<9 neutral; b>=6,a>=-6 timber; a<-6,b>=0 foliage; "
                    "a>=6,b<6 blossom; b<0,a<6 cool; then 9x9 majority vote; parts < 0.06% of the frame merge into the actor's main class",
                    "regions_in_clip": len(region_count) - 1, "palette": "HSV hue U(0,1), saturation U(0.1,1), value U(0.2,1), seeded, min RGB distance 70",
                    "resize": "nearest neighbour",
                    "reference": f"{ref} data/generator/augmentors/transfer_control_input/seg.py (generate_distinct_colors, black background); "
                                 "model card example1/example2 segmentation videos (per-part random colours on black)"},
            "seg_actor": {"what": "the raw SimWorld actor partition recoloured with the same palette convention (no material split), for comparison",
                          "reference": "same as seg"},
            "edge": {"what": "Canny edges, white on black, 3 channels", "thresholds": [100, 200], "preset": "medium",
                     "computed_on": "rgb resized to each canvas first (antialiased bicubic)",
                     "reference": f"{ref} transfer_control_input/control_input.py AddControlInputEdge; inference/args.py EdgeTransferArgs default MEDIUM"},
            "blur": {"what": "low-frequency colour layout", "preset": "medium", "steps": "INTER_AREA down x2 -> cv2.bilateralFilter -> INTER_LINEAR up -> INTER_CUBIC down/up x10",
                     "bilateral_by_size": {f"{w}x{h}": p for (w, h), p in blur_params.items()},
                     "computed_on": "rgb resized to each canvas first (antialiased bicubic)",
                     "reference": f"{ref} control_input.py AddControlInputBlur(use_random=False, downup_preset='medium'), blur.py bilateral_blur_config; "
                                  "inference/args.py BlurTransferArgs default MEDIUM"},
        },
        "also": "NVIDIA's own runners compute edge and blur on the fly from an rgb vision_path; these files reproduce that so a port without the augmentors can use them.",
    }
    (out / "controls.json").write_text(json.dumps(meta, indent=1))
    print(f"depth {near / 100:.1f}-{far / 100:.1f} m, sky {sky:.0%}, {len(region_count) - 1} seg regions; wrote {out}")


if __name__ == "__main__":
    main()
