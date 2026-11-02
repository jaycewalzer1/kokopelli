"""Generates a real 30 second continuous video, which takes about two hours.

Run it with RUN_LONG_TESTS=1. Finished segments are kept, so a rerun resumes where it stopped.
"""
import os
import subprocess
import unittest
from pathlib import Path

from blend import FPS, blend, probe
from settings import ROOT
from world_model import continue_video, text_to_video

PROMPT = "walking to the kitchen to grab water"
OUT = ROOT / "out" / "continuous_video"
SIZE = "448x256"
STEPS = 30
COND_FRAMES = 5
# Each segment shares COND_FRAMES with the one before: 760 - 8 * 5 = 720 frames, 30 seconds at 24 fps.
SEGMENT_FRAMES = [84] * 8 + [88]


def is_finished(path, frames):
    try:
        return probe(path)[2] == frames
    except (subprocess.CalledProcessError, ValueError):
        return False


def generate_segments():
    segments = []
    for index, frames in enumerate(SEGMENT_FRAMES):
        path = OUT / f"segment_{index:02d}.mp4"
        partial = OUT / f"segment_{index:02d}.partial.mp4"
        if not is_finished(path, frames):
            settings = {"size": SIZE, "frames": frames, "steps": STEPS, "seed": index}
            if segments:
                continue_video(PROMPT, segments[-1], partial, cond_frames=COND_FRAMES, **settings)
            else:
                text_to_video(PROMPT, partial, **settings)
            partial.replace(path)
        print(f"segment {index + 1}/{len(SEGMENT_FRAMES)} ready", flush=True)
        segments.append(path)
    return segments


def scene_cuts(path, threshold=0.3):
    """Return how many frames ffmpeg's scene detector sees as a jump from the frame before."""
    log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vf",
                          f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                         check=True, capture_output=True, text=True).stderr
    return log.count("pts_time:")


@unittest.skipUnless(os.environ.get("RUN_LONG_TESTS"), "takes about two hours; set RUN_LONG_TESTS=1")
class ContinuousVideoTest(unittest.TestCase):
    def test_thirty_seconds_without_a_cut(self):
        final = blend(generate_segments(), OUT / "final.mp4", overlap_frames=COND_FRAMES)
        self.assertEqual(probe(final), (448, 256, 30 * FPS))
        self.assertEqual(scene_cuts(final), 0)


if __name__ == "__main__":
    unittest.main()
