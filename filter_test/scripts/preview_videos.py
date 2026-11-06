"""Watchable videos of test_clip's depth and segmentation, for looking at only. Each model gets its own conversion later.

    .venv/bin/python filter_test/scripts/preview_videos.py

Depth is drawn on a log scale (near bright, sky black), scaled by the clip's own 1st-99th percentile so every frame uses
the same scale and nothing flickers. Inverse depth would be the usual choice, but it leaves everything past a few metres black.
"""
import subprocess
from pathlib import Path

import cv2
import numpy as np

CLIP = Path(__file__).resolve().parents[2] / "out" / "filter_test" / "test_clip"
SKY_CM = 60000


def encode(frames_glob, output, fps=30):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(frames_glob),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", str(output)], check=True)


def main():
    files = sorted((CLIP / "depth").glob("*.npy"))
    logs = [np.where(d < SKY_CM, np.log(np.maximum(d, 1.0)), np.nan) for d in map(np.load, files)]
    near, far = np.nanpercentile(np.stack(logs), [1, 99])
    folder = CLIP / "preview_depth"
    folder.mkdir(exist_ok=True)
    for path, frame in zip(files, logs):
        scaled = np.nan_to_num(np.clip((far - frame) / (far - near), 0, 1), nan=0.0)
        cv2.imwrite(str(folder / f"{path.stem}.png"), (scaled * 255).astype(np.uint8))
    encode(folder / "%04d.png", CLIP / "depth.mp4")
    encode(CLIP / "segmentation" / "%04d.png", CLIP / "segmentation.mp4")
    print(f"depth.mp4 and segmentation.mp4 in {CLIP}")


if __name__ == "__main__":
    main()
