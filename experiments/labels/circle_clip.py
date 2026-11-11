"""Build the ambiguous-circle clip for the label test. No model runs here.

    .venv/bin/python experiments/labels/circle_clip.py

One frozen frame of the garden clip (out/filter_test/test_clip_still, frame 100) with a plain disc drawn into its
segmentation on the lawn. The seg control shows the disc as one more flat-coloured region, so nothing in the control
says what it is: only a label can. Painting it under two different labels is the test (experiments/labels/README.md).

Writes out/labels/circle/clip/:
    segmentation/NNNN.png        the source frame's actor masks plus the disc in its own colour, FRAMES times
    capture.json                 the disc's mask colour, as a capture records it ("mask_colors")
    controls/832x480/seg.mp4     the seg control, drawn as controls.py draws it, the disc one more region
    labels/NNNN.png, labels_meta.json   the label pass (kokopelli/wm/labels.py), actor "circle" = label 1
    sheet.png                    the source render, the raw masks and the seg control side by side
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kokopelli.wm import labels  # noqa: E402
from kokopelli.wm.controls import controls  # noqa: E402

SOURCE, FRAME = ROOT / "out" / "filter_test" / "test_clip_still", 100
OUT = ROOT / "out" / "labels" / "circle" / "clip"
FRAMES = 93   # 3.1 s at 30 fps, 24 latent frames
CENTRE, RADIUS = (262, 585), 98   # in the 1280x720 source: on the lawn, lower left; 127 px across at 832x480, about 4 tokens
ACTOR, COLOUR = "circle", (255, 0, 128)
SIZE = (832, 480)
LABELS = Path(__file__).parent / "circle" / "ball.json"   # pumpkin.json lists the same actor, so one label pass serves both


def main():
    rgb = np.array(Image.open(SOURCE / "rgb" / f"{FRAME:04d}.png").convert("RGB"))
    seg = np.array(Image.open(SOURCE / "segmentation" / f"{FRAME:04d}.png").convert("RGB"))
    assert not (seg == COLOUR).all(-1).any(), "the disc's colour is already an actor's"
    yy, xx = np.mgrid[:seg.shape[0], :seg.shape[1]]
    disc = (xx - CENTRE[0]) ** 2 + (yy - CENTRE[1]) ** 2 <= RADIUS ** 2

    palette = controls.Palette(controls.SEED)
    control = palette.paint(controls.refined_ids(seg, rgb))   # regions from the untouched frame, as for any clip
    control[disc] = palette[ACTOR]
    seg[disc] = COLOUR

    (OUT / "segmentation").mkdir(parents=True, exist_ok=True)
    (OUT / "controls" / "832x480").mkdir(parents=True, exist_ok=True)
    small = cv2.resize(control, SIZE, interpolation=cv2.INTER_NEAREST)
    writer = controls.Writer(OUT / "controls" / "832x480" / "seg.mp4", SIZE)
    for k in range(FRAMES):
        Image.fromarray(seg).save(OUT / "segmentation" / f"{k:04d}.png")
        writer.write(small)
    writer.close()
    capture = {"what": "the ambiguous-circle label test: one frozen frame with a disc drawn into its segmentation",
               "source": f"{SOURCE.relative_to(ROOT)} frame {FRAME}", "fps": controls.FPS, "frames": FRAMES,
               "size": [seg.shape[1], seg.shape[0]], "disc": {"centre": list(CENTRE), "radius": RADIUS},
               "mask_colors": [{"actor": ACTOR, "assigned_rgb": list(COLOUR)}]}
    (OUT / "capture.json").write_text(json.dumps(capture, indent=1) + "\n")
    meta = labels.build_pass(OUT, labels.load(LABELS), labels.capture_colors(capture), LABELS)

    tiles = [cv2.resize(rgb, SIZE, interpolation=cv2.INTER_AREA), cv2.resize(seg, SIZE, interpolation=cv2.INTER_NEAREST), small]
    Image.fromarray(np.hstack(tiles)).save(OUT / "sheet.png")
    row = meta["labels"][0]
    print(f"{ACTOR}: in {row['frames_visible']}/{meta['frames']} frames, {row['area_px'][0]} px of {seg.shape[1]}x{seg.shape[0]}; "
          f"warnings: {meta['warnings'] or 'none'}; wrote {OUT}")


if __name__ == "__main__":
    main()
