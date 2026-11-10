"""Blur controls at different strengths: a middle ground between "colours help identify things" and "colours copied
one-to-one look cartoonish".

    .venv/bin/python -I kokopelli/wm/controls/blur_variants.py [--frames 150] [--size 832x480]

NVIDIA's AddControlInputBlur (cosmos-framework .../transfer_control_input/control_input.py) trains with the final
down/up factor drawn from 4..16; presets: medium = 10, high = 16. So:
  v1_medium      downup 10  (what controls.py writes as blur.mp4)
  v2_high        downup 16  only broad colour regions survive; still inside the training range
  v3_high_photo  downup 16 after toning saturation and contrast toward photo levels (slightly outside training)
Writes out/city_wm/bridge/controls/<size>/blur_<variant>.mp4 and blur_variants.json.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controls import blur, load_rgb, resize_rgb  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FPS = 30
SATURATION = 0.7  # CG greens and purples sit well above typical photo saturation
CONTRAST = 0.85   # pull values toward the frame mean: softer, like real exposure latitude


def photo_grade(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 1] *= SATURATION
    out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)
    mean = out.mean(axis=(0, 1), keepdims=True)
    return np.clip(mean + (out - mean) * CONTRAST, 0, 255).astype(np.uint8)


VARIANTS = {
    "v1_medium": lambda rgb: blur(rgb, downup=10)[0],
    "v2_high": lambda rgb: blur(rgb, downup=16)[0],
    "v3_high_photo": lambda rgb: blur(photo_grade(rgb), downup=16)[0],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="out/filter_test/test_clip")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--size", default="832x480")
    args = ap.parse_args()
    size = tuple(int(v) for v in args.size.split("x"))
    clip = ROOT / args.clip
    out = ROOT / "out" / "city_wm" / "bridge" / "controls" / args.size
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name in VARIANTS:
            (Path(tmp) / name).mkdir()
        for k in range(args.frames):
            rgb = resize_rgb(load_rgb(clip, k), size)
            for name, make in VARIANTS.items():
                cv2.imwrite(str(Path(tmp) / name / f"{k:04d}.png"), cv2.cvtColor(make(rgb), cv2.COLOR_RGB2BGR))
        for name in VARIANTS:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(Path(tmp) / name / "%04d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", str(out / f"blur_{name}.mp4")], check=True)
        frames: list[Any] = [cv2.imread(str(Path(tmp) / n / "0100.png")) for n in VARIANTS]
        cv2.imwrite(str(out / "blur_variants_f100.png"), np.hstack(frames))
    (out / "blur_variants.json").write_text(json.dumps({
        "source": args.clip, "frames": args.frames, "size": args.size, "fps": FPS,
        "variants": {"v1_medium": "downup 10 (NVIDIA medium)", "v2_high": "downup 16 (NVIDIA high, edge of training range)",
                     "v3_high_photo": f"downup 16 after saturation x{SATURATION}, contrast x{CONTRAST} (not in NVIDIA's training)"},
        "reference": "cosmos-framework transfer_control_input/control_input.py AddControlInputBlur downup_preset_values"}, indent=1))
    print(f"wrote {len(VARIANTS)} blur variants to {out}")


if __name__ == "__main__":
    main()
