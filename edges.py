"""Edge maps of sim frames, for using the world model as a filter over the sim."""
import subprocess
from pathlib import Path

import cv2
import numpy as np

FPS = 24
# NVIDIA's "medium" preset: what Cosmos's edge control was trained on. Fixed, so edges don't flicker as the light changes.
LOW, HIGH = 100, 200


def edge_frame(rgb):
    """White edges on black, the same shape as the frame."""
    edges = cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), LOW, HIGH)
    return np.stack([edges] * 3, axis=-1)


def read_frames(path):
    capture = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    capture.release()
    if not frames:
        raise ValueError(f"no frames in {path}")
    return frames


def write_frames(frames, output):
    """Encode RGB frames, all the same size, nearly losslessly: compression would soften thin edges."""
    height, width = frames[0].shape[:2]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS),
               "-i", "-", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(output)]
    subprocess.run(command, input=b"".join(frame.tobytes() for frame in frames), check=True)
    return output


def edge_clip(video, output, start=0, count=None):
    """The edge map of part of a video, as a video."""
    frames = read_frames(video)
    end = len(frames) if count is None else start + count
    if end > len(frames):
        raise ValueError(f"{video} has {len(frames)} frames, not {end}")
    return write_frames([edge_frame(frame) for frame in frames[start:end]], output)
