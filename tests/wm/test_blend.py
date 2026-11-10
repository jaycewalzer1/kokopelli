import subprocess
import tempfile
import unittest
from pathlib import Path

from kokopelli.wm.blend import blend, probe


def solid_clip(path, color, frames=24, size="64x64"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={color}:s={size}:r=24",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def rgb_at(path, frame):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{frame})",
                          "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return tuple(raw[:3])


class BlendTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.red = solid_clip(self.dir / "red.mp4", "red")
        self.blue = solid_clip(self.dir / "blue.mp4", "blue")
        self.output = self.dir / "out" / "blend.mp4"

    def test_each_join_shortens_by_the_overlap(self):
        green = solid_clip(self.dir / "green.mp4", "green", frames=36)
        blend([self.red, self.blue, green], self.output, overlap_frames=6)
        self.assertEqual(probe(self.output), (64, 64, 24 + 24 + 36 - 2 * 6))

    def test_overlap_mixes_the_two_clips(self):
        blend([self.red, self.blue], self.output, overlap_frames=12)
        start, middle, end = (rgb_at(self.output, n) for n in (0, 18, 35))
        self.assertGreater(start[0], 200)
        self.assertLess(start[2], 50)
        self.assertGreater(middle[0], 60)
        self.assertGreater(middle[2], 60)
        self.assertLess(end[0], 50)
        self.assertGreater(end[2], 200)

    def test_one_clip_passes_through(self):
        blend([self.red], self.output)
        self.assertEqual(probe(self.output), (64, 64, 24))

    def test_rejects_clips_that_cannot_blend(self):
        small = solid_clip(self.dir / "small.mp4", "red", size="32x32")
        with self.assertRaisesRegex(ValueError, "differ in size"):
            blend([self.red, small], self.output)
        with self.assertRaisesRegex(ValueError, "at least 48 frames"):
            blend([self.red, self.blue], self.output, overlap_frames=24)
        with self.assertRaisesRegex(ValueError, "no clips"):
            blend([], self.output)


if __name__ == "__main__":
    unittest.main()
