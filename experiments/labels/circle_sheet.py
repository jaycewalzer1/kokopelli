"""Lay the ambiguous-circle paints side by side. No model runs here.

    .venv/bin/python experiments/labels/circle_sheet.py

Reads out/labels/circle/<run>/<run>.mp4 (run_circle.sh) and writes, in out/labels/circle/:
    compare.mp4    the seg control and the five paints in one 3x2 grid
    sheet.png      the disc's surroundings, one row per paint, one column per moment
    change.json    how far each labeled paint moved from the unlabeled one, inside and outside the disc (0-255)
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kokopelli.wm import label_check, labels  # noqa: E402
from kokopelli.wm.controls import controls  # noqa: E402

OUT = ROOT / "out" / "labels" / "circle"
CLIP = OUT / "clip"
GRID = [("control", "seg control"), ("ball_a", "soccer ball, caption only"), ("ball_b", "soccer ball, masked"),
        ("none", "no label"), ("pumpkin_a", "pumpkin, caption only"), ("pumpkin_b", "pumpkin, masked")]
MOMENTS = [3, 33, 63, 92]   # painted frames; a batch paint shows clip frame i-3, and this clip never moves
CROP = 256


def titled(frame, text):
    frame = frame.copy()
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(frame, text, (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def main():
    videos = {"control": label_check.read_video(CLIP / "controls" / "832x480" / "seg.mp4")}
    for run, _ in GRID[1:]:
        path = OUT / run / f"{run}.mp4"
        if path.exists():
            videos[run] = label_check.read_video(path)
    n = min(len(v) for v in videos.values())
    h, w = videos["control"].shape[1:3]
    blank = np.zeros((h, w, 3), np.uint8)

    writer = controls.Writer(OUT / "compare.mp4", (3 * w, 2 * h))
    for i in range(n):
        cells = [titled(videos[run][i] if run in videos else blank, title) for run, title in GRID]
        writer.write(np.vstack([np.hstack(cells[:3]), np.hstack(cells[3:])]))
    writer.close()

    label_frames = labels.read_frames(CLIP / "labels", w, h, n)
    ys, xs = np.nonzero(label_frames[0])
    half = int(max(xs.max() - xs.min(), ys.max() - ys.min()) * 0.9)
    cx, cy = int(xs.mean()), int(ys.mean())
    x0, y0 = min(max(0, cx - half), w - 2 * half), min(max(0, cy - half), h - 2 * half)
    rows = []
    for run, title in GRID:
        if run not in videos:
            continue
        tiles = [cv2.resize(videos[run][min(i, n - 1)][y0:y0 + 2 * half, x0:x0 + 2 * half], (CROP, CROP), interpolation=cv2.INTER_CUBIC)
                 for i in MOMENTS]
        name = np.full((CROP, 250, 3), 30, np.uint8)
        cv2.putText(name, title, (8, CROP // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        rows.append(np.hstack([name] + tiles))
    Image.fromarray(np.vstack(rows)).save(OUT / "sheet.png")

    change = {}
    if "none" in videos:
        for run in videos:
            if run not in ("control", "none"):
                change[run] = label_check.outside_change(videos[run], videos["none"], label_frames)
    (OUT / "change.json").write_text(json.dumps({"what": "mean absolute pixel difference from the unlabeled paint (0-255), "
                                                 "inside = the disc widened by one token", "runs": change}, indent=1) + "\n")
    print(json.dumps(change))
    print(f"wrote {OUT / 'compare.mp4'}, {OUT / 'sheet.png'}, {OUT / 'change.json'}")


if __name__ == "__main__":
    main()
