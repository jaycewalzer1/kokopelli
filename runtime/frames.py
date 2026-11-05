"""Small helpers for moving between image files, frame arrays and mp4 clips."""
import hashlib
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from blend import FPS, probe


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def load_rgb(path):
    return np.asarray(Image.open(path).convert("RGB"))


def save_rgb(frame, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(path)
    return str(path)


def write_clip(frames, path):
    """Encode frames, all the same size, to an mp4."""
    height, width = frames[0].shape[:2]
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
