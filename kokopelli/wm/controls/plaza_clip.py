"""Record a slow walk through the Commons plaza from Unreal (lit frames + metric depth) and encode the depth
the way Cosmos's depth control expects it (experiments/filter_test/scripts/controls.py: linear, near white, sky black,
one scale for the whole clip so the control doesn't flicker).

    simworld/.venv/bin/python -I kokopelli/wm/controls/plaza_clip.py          # needs the city server on 9001

Writes out/city_wm/plaza/{rgb,depth}/NNNN.*, rgb.mp4, depth_control.mp4.
"""
import io
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from unrealcv import Client

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "out" / "city_wm" / "plaza"
START = (470.0, 132.0, 1.7)  # render_views.py "commons_plaza", metres
PITCH, YAW, FOV = 2.0, 205.0, 85.0
FRAMES, STEP_M, FPS = 46, 0.12, 16  # 46 = 1 + 3 x 15: three 16-frame Cosmos chunks carrying 1 frame
SIZE = (448, 256)
SKY_CM = 60000  # controls.py


def encode(pattern, output):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(pattern),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", str(output)], check=True)


def main():
    for sub in ("rgb", "depth", "control"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    c = Client(("127.0.0.1", 9001))
    c.connect()
    try:
        before = c.request("vget /cameras").split()
        c.request("vset /cameras/spawn")
        cam = len(c.request("vget /cameras").split()) - 1  # the new camera is listed last
        assert cam >= len(before), "camera spawn failed"
        c.request(f"vset /camera/{cam}/size {SIZE[0]} {SIZE[1]}")
        c.request(f"vset /camera/{cam}/fov {FOV}")
        c.request(f"vset /camera/{cam}/rotation {PITCH} {YAW} 0")
        dx, dy = math.cos(math.radians(YAW)), math.sin(math.radians(YAW))
        depths = []
        for k in range(FRAMES):
            x, y = START[0] + dx * STEP_M * k, START[1] + dy * STEP_M * k
            c.request(f"vset /camera/{cam}/location {x * 100:.1f} {y * 100:.1f} {START[2] * 100:.1f}")
            Image.open(io.BytesIO(c.request(f"vget /camera/{cam}/lit png"))).convert("RGB").save(OUT / "rgb" / f"{k:04d}.png")
            d = np.load(io.BytesIO(c.request(f"vget /camera/{cam}/depth npy")))
            np.save(OUT / "depth" / f"{k:04d}.npy", d)
            depths.append(d)
    finally:
        c.disconnect()

    depth = np.stack(depths).astype(np.float32)
    sky = depth >= SKY_CM
    near = np.percentile(depth[~sky], 0.5)
    far = np.percentile(depth[~sky], 95)
    linear = np.clip((far - depth) / (far - near), 0, 1)
    linear[sky] = 0
    for k, frame in enumerate(linear):
        Image.fromarray(np.round(frame * 255).astype(np.uint8)).convert("RGB").save(OUT / "control" / f"{k:04d}.png")
    encode(OUT / "rgb" / "%04d.png", OUT / "rgb.mp4")
    encode(OUT / "control" / "%04d.png", OUT / "depth_control.mp4")
    print(f"{FRAMES} frames; depth {near / 100:.1f}-{far / 100:.1f} m, sky {sky.mean():.0%}; {OUT}")


if __name__ == "__main__":
    main()
