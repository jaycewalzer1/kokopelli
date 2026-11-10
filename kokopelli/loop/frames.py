"""Small helpers for moving between image files, frame arrays and mp4 clips."""
import hashlib
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from kokopelli.wm.blend import FPS, probe

NEAR_CM = 50.0
FAR_CM = 10000.0


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"))


def save_rgb(frame, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(path)
    return str(path)


def resized(frame, size):
    """A frame at size, written like 448x256. The sim and the world model don't always render at the same size."""
    width, height = (int(n) for n in size.split("x"))
    if frame.shape[:2] == (height, width):
        return frame
    return np.asarray(Image.fromarray(frame).resize((width, height), Image.LANCZOS))


def control_frame(path, size):
    """A sim render as one frame of a control video. NVIDIA's sample depth video has near bright and far black."""
    if str(path).endswith(".npy"):
        depth = np.nan_to_num(np.load(path), nan=FAR_CM, posinf=FAR_CM).clip(NEAR_CM, FAR_CM)
        # A fixed range, so the picture doesn't flicker as things enter and leave the view.
        gray = (255 * (1 - np.log(depth / NEAR_CM) / np.log(FAR_CM / NEAR_CM))).astype(np.uint8)
        return resized(np.stack([gray] * 3, axis=-1), size)
    return resized(load_rgb(path), size)


def write_clip(frames, path):
    """Encode frames, all the same size, to an mp4."""
    height, width = frames[0].shape[:2]
    # ffmpeg reads a stream of bytes, so a different-sized frame wouldn't fail. It would quietly become garbage frames.
    sizes = {frame.shape for frame in frames}
    if len(sizes) > 1:
        raise ValueError(f"frames differ in size: {sorted(sizes)}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                    "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(path)],
                   input=b"".join(frame.tobytes() for frame in frames), check=True, capture_output=True)
    return str(path)


def read_clip(path):
    width, height, _ = probe(path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


def evenly_spaced(count, wanted):
    """Indexes of wanted frames spread across count, always including the last."""
    if wanted >= count:
        return list(range(count))
    return [round((count - 1) * (i + 1) / wanted) for i in range(wanted)]
