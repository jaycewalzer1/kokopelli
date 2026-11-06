"""Turn test_clip's raw sim depth (float32 cm) into each model's own control video. No model runs here.

    filter_test/.venv/bin/python filter_test/scripts/controls.py

Writes out/filter_test/controls/:
- cosmos_simdepth.mp4 (448x256): the encoding measured from NVIDIA's own example1_depth.mp4 (out/filter_test/reference/):
  greyscale, near bright, empty background 0, one scale for the whole video (its brightest pixel is 202 in every frame, so it
  isn't stretched per frame), and brightness linear in distance. On the example's flat table the steps in brightness shrink
  toward the camera, which is what linear-in-distance gives and linear-in-inverse-distance doesn't.
- sd15_simdepth.mp4 (912x512) and sd15_simdepth/NNNN.png: what ControlNet v1.1 depth was trained on, MiDaS-style relative
  inverse depth, near bright. One scale for the clip, not per frame, so the control itself doesn't flicker.
Both: sky (the server clamps it at 65504 cm) is 0, and resizing is area-averaged, the antialiased kind Cosmos's own recipe uses
for depth. 1280x720 is 16:9; 448x256 is 1.75:1, so the Cosmos control is squeezed 1.6% horizontally (noted in results).
"""
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "out" / "filter_test" / "test_clip"
OUT = ROOT / "out" / "filter_test" / "controls"
SKY_CM = 60000
COSMOS_SIZE, SD_SIZE = (448, 256), (912, 512)


def encode(frames_glob, output, fps=30):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(frames_glob),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(output)], check=True)


def write(frames, name, size):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    for k, frame in enumerate(frames):
        small = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(folder / f"{k:04d}.png"), np.round(small * 255).astype(np.uint8))
    encode(folder / "%04d.png", OUT / f"{name}.mp4")


def main():
    depth = np.stack([np.load(path) for path in sorted((CLIP / "depth").glob("*.npy"))])
    sky = depth >= SKY_CM
    near, far = np.percentile(depth[~sky], [0.5, 99.5])
    # Half of this clip is within 4 m (deck and railings) and the hills are 465 m off. Linear over all of it would leave
    # everything near white, so the Cosmos scale ends at the 95th percentile and only the hills fall to black with the sky.
    linear_far = np.percentile(depth[~sky], 95)

    linear = np.clip((linear_far - depth) / (linear_far - near), 0, 1)
    linear[sky] = 0
    inverse = np.clip((1 / np.maximum(depth, 1) - 1 / far) / (1 / near - 1 / far), 0, 1)
    inverse[sky] = 0

    OUT.mkdir(parents=True, exist_ok=True)
    write(linear, "cosmos_simdepth", COSMOS_SIZE)
    write(inverse, "sd15_simdepth", SD_SIZE)
    (OUT / "run.json").write_text(json.dumps({"model": "input", "about": "Sim depth converted for each model (controls.py).",
                                              "lines": [f"depth {near / 100:.1f}-{far / 100:.1f} m (Cosmos scale ends at {linear_far / 100:.0f} m), sky {sky.mean():.0%} of pixels"]}))
    (OUT / "scale.json").write_text(json.dumps({"near_cm": float(near), "far_cm": float(far), "cosmos_far_cm": float(linear_far), "sky_fraction": float(sky.mean())}))
    print(f"near {near / 100:.1f} m, far {far / 100:.1f} m, sky {sky.mean():.0%}; controls in {OUT}")


if __name__ == "__main__":
    main()
