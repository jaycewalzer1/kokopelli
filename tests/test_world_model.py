"""These call the real model, using the smallest clip it accepts."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from blend import probe
from settings import WORLD_MODEL, WORLD_MODEL_WEIGHTS
from world_model import continue_video, image_to_video, text_to_video

SMALL = {"size": "256x256", "frames": 8, "steps": 4, "seed": 7}


class WorldModelTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_settings_name_the_nvidia_model(self):
        self.assertEqual(WORLD_MODEL, "nvidia/Cosmos3-Nano")
        self.assertTrue(WORLD_MODEL_WEIGHTS.is_dir())

    def test_text_to_video(self):
        output = text_to_video("A boat on a calm lake.", self.dir / "text.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    def test_image_to_video(self):
        image = self.dir / "start.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=256x256",
                        "-frames:v", "1", str(image)], check=True)
        output = image_to_video("The picture slowly drifts.", image, self.dir / "image.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    def test_continue_video(self):
        video = self.dir / "start.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=256x256:r=24",
                        "-frames:v", "8", "-pix_fmt", "yuv420p", str(video)], check=True)
        output = continue_video("The picture slowly drifts.", video, self.dir / "next.mp4", **SMALL)
        self.assertEqual(probe(output), (256, 256, 8))

    def test_failure_reports_the_reason(self):
        with self.assertRaisesRegex(RuntimeError, "multiple of 4"):
            text_to_video("A boat.", self.dir / "bad.mp4", frames=7)


if __name__ == "__main__":
    unittest.main()
