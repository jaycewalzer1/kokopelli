"""These call the real model, using the smallest clip it accepts."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

from kokopelli.wm.blend import probe
from kokopelli.settings import WORLD_MODEL, WORLD_MODEL_WEIGHTS
from kokopelli.wm.world_model import continue_video, image_to_video, text_to_video

SMALL = {"size": "256x256", "frames": 8, "steps": 4, "seed": 7}

# Loading Cosmos3-Nano (peak 17.3 GB) in the default run made tests/ peak at 18.3 GB, and five runs at once crashed the Mac.
# These are model jobs: run them through kokopelli/ops/gpu.py with RUN_MODEL_TESTS=1 (command in docs/log/fable/2026-11-09-P1-M.md).
# The model marker (conftest.py skips it unless RUN_MODEL_TESTS is set). The unittest skip keeps a plain unittest run,
# which ignores markers, from loading the model as well.
MODEL = "loads Cosmos3-Nano (peak 17.3 GB)"


def needs_model(test):
    test = unittest.skipUnless(os.environ.get("RUN_MODEL_TESTS"), f"{MODEL}; set RUN_MODEL_TESTS=1 and queue it")(test)
    return pytest.mark.model(reason=MODEL)(test)


class WorldModelTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_settings_name_the_nvidia_model(self):
        self.assertEqual(WORLD_MODEL, "nvidia/Cosmos3-Nano")
        self.assertTrue(WORLD_MODEL_WEIGHTS.is_dir())

    @needs_model
    def test_text_to_video(self):
        output = text_to_video("A boat on a calm lake.", self.dir / "text.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    @needs_model
    def test_image_to_video(self):
        image = self.dir / "start.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=256x256",
                        "-frames:v", "1", str(image)], check=True)
        output = image_to_video("The picture slowly drifts.", image, self.dir / "image.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    @needs_model
    def test_continue_video(self):
        video = self.dir / "start.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=256x256:r=24",
                        "-frames:v", "8", "-pix_fmt", "yuv420p", str(video)], check=True)
        output = continue_video("The picture slowly drifts.", video, self.dir / "next.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    @needs_model
    def test_failure_reports_the_reason(self):
        with self.assertRaisesRegex(RuntimeError, "multiple of 4"):
            text_to_video("A boat.", self.dir / "bad.mp4", frames=7)


if __name__ == "__main__":
    unittest.main()
